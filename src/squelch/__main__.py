"""Command line entry point."""

from __future__ import annotations

import argparse
import shutil
import sys
import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from squelch.app import SquelchApp
from squelch.audio import Player, StreamReader
from squelch.config import Config, ConfigError, load_config
from squelch.feeds import Feed, fetch_feeds, resolve_stream
from squelch.pipeline import Events, Pipeline

FFMPEG_MISSING = (
    "ffmpeg not found on PATH — squelch decodes the feed with it. "
    "Install it (macOS: brew install ffmpeg) and start squelch again."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="squelch", description=__doc__)
    parser.add_argument("--feed", help="LiveATC feed ident, e.g. kpdx3_twr")
    parser.add_argument("--icao", help="Airport ICAO for the feed picker")
    return parser.parse_args(argv)


def try_start(
    start: Callable[[], None], on_error: Callable[[str], None], message: str
) -> bool:
    """Run a startup step, degrading rather than crashing.

    An unavailable audio device should cost you one feature, not the whole
    application.
    """
    try:
        start()
    except Exception:
        on_error(message)
        return False
    return True


def safe_call(app: Any, func: Callable[..., None], *args: Any) -> None:
    """Marshal onto the UI thread without ever raising back onto ours.

    Unlike the `Events` callbacks -- which route through `Pipeline._emit`'s
    own exception-swallowing wrapper -- calls made directly from this module
    (`warn()`, and the state signals) have no such guard. If the app is not
    running by the time one of these fires (already quit, or not yet
    started), `call_from_thread` raises `RuntimeError("App is not
    running")`. That's harmless -- there is nobody to tell -- but left
    uncaught it would kill the pipeline thread with a stray traceback.
    """
    try:
        app.call_from_thread(func, *args)
    except Exception:
        pass


def feed_selection_hint(feed: Feed) -> str:
    """What to tell the user when they pick a feed from the overlay.

    Switching the live stream in place is out of scope for v1, but a picker
    that silently does nothing is worse than no picker: it reads as a bug.
    Naming the ident and the exact flag turns a dead end into an instruction.
    """
    return f"selected {feed.ident} — restart with: squelch --feed {feed.ident}"


def build_pipeline_runner(
    config: Config,
    *,
    warn: Callable[[str], None],
    set_state: Callable[[str], None],
    player: Any,
    events: Events,
    resolve: Callable[[str], str] = resolve_stream,
    reader_factory: Callable[..., Any] = StreamReader,
    pipeline_factory: Callable[..., Any] = Pipeline,
    which: Callable[[str], str | None] = shutil.which,
) -> Callable[[], None]:
    """Build the callable that runs on the background pipeline thread.

    Every collaborator is injectable because this function is the whole of
    squelch's wiring and it runs on a daemon thread, where an unhandled
    exception is invisible: the thread dies, nothing is printed, and the
    pane sits at its last state forever.
    """

    def run() -> None:
        try:
            _run()
        except Exception as exc:
            # Everything below the feed-resolution step used to be
            # unguarded: a missing ffmpeg (FileNotFoundError from Popen) or
            # a read error on the ffmpeg pipe (OSError) killed this thread
            # in silence.
            warn(f"stopped: {type(exc).__name__}: {exc}")
            set_state("offline")

    def _run() -> None:
        if which("ffmpeg") is None:
            warn(FFMPEG_MISSING)
            set_state("offline")
            return

        try_start(player.start, warn, "no audio device — nothing will be audible")

        try:
            url = resolve(config.feed)
        except Exception:
            warn(
                f"could not resolve feed {config.feed} — check the ident "
                "(press [f] to list this airport's feeds)"
            )
            # The header must not keep claiming "● LIVE" once nothing is
            # actually playing -- see set_state's "offline" entry.
            set_state("offline")
            return

        pipeline_factory(reader_factory(url), player, events).run()

    return run


def main(
    argv: list[str] | None = None,
    *,
    app_factory: Callable[..., Any] = SquelchApp,
    runner_factory: Callable[..., Callable[[], None]] = build_pipeline_runner,
) -> int:
    args = parse_args(argv)
    try:
        config = load_config()
    except ConfigError as exc:
        # Before the UI exists, so this is the one place a plain stderr
        # message beats a message-log warning.
        print(f"squelch: {exc}", file=sys.stderr)
        return 2
    if args.feed:
        config = replace(config, feed=args.feed)
    if args.icao:
        config = replace(config, icao=args.icao)

    app = app_factory(
        config,
        feed_label=config.feed,
        feed_loader=lambda: fetch_feeds(config.icao),
    )

    player = Player()
    app.on_mute_change = lambda muted: setattr(player, "muted", muted)
    # Runs on the UI thread (the picker's dismiss callback), so no marshalling.
    app.on_feed_selected = lambda feed: app.warn(feed_selection_hint(feed))

    events = Events(
        on_level=lambda d: app.call_from_thread(app.set_level, d),
        on_state=lambda s: app.call_from_thread(app.set_state, s),
    )

    runner = runner_factory(
        config,
        warn=lambda message: safe_call(app, app.warn, message),
        set_state=lambda state: safe_call(app, app.set_state, state),
        player=player,
        events=events,
    )

    # Started from on_mount, not here: a call_from_thread issued before
    # App.run() has the loop up raises "App is not running" and is
    # swallowed, so any early warning would be lost.
    app.on_start = lambda: threading.Thread(target=runner, daemon=True).start()

    try:
        app.run()
    finally:
        # Unconditional: an exception escaping the UI (e.g. a timer firing
        # against an unmounted widget during teardown) must not leave the
        # PortAudio stream open.
        player.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
