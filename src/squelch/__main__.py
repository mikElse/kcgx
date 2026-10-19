"""Command line entry point."""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from squelch.app import SquelchApp
from squelch.config import Config, ConfigError, load_config
from squelch.feeds import (
    REFRESH_ATTEMPTS,
    Feed,
    FeedError,
    fetch_feeds,
    write_cached_feeds,
)
from squelch.mixer import Mixer
from squelch.radar_theme import RadarTheme
from squelch.session import SessionEvents

# Re-exported: these used to be defined here, and callers still import them
# from here.
from squelch.runtime import (  # noqa: F401
    AUDIO_FAILED,
    FFMPEG_MISSING,
    _no_feeds,
    build_sessions,
    load_feeds,
    picker_feeds,
    preferred_index,
)


def report_audio_failure(mixer, warn: Callable[[str], None]) -> None:
    """One warning for the whole app, not one per feed.

    Twelve independent output streams became one, so a device that will not
    open is now a single event. Losing sound must not lose the pane: every
    feed keeps connecting, metering, and ranking.
    """
    if mixer.failed:
        warn(AUDIO_FAILED)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="squelch", description=__doc__)
    parser.add_argument(
        "--feed", help="LiveATC feed ident to leave unmuted, e.g. kpdx3_twr"
    )
    parser.add_argument("--icao", help="Airport whose feeds to open")
    parser.add_argument(
        "--refresh-feeds",
        action="store_true",
        help="fetch and cache the airport's feed list, then exit; no UI, no audio",
    )
    return parser.parse_args(argv)


def refresh_feeds(
    config: Config,
    *,
    out: Callable[[str], None] = print,
    fetch: Callable[..., list[Feed]] = fetch_feeds,
    cache_dir: Path | None = None,
) -> int:
    """Fill the feed cache for `config.icao` from outside the UI.

    This exists because of where the waiting can happen. LiveATC fronts its
    listing with Cloudflare and refuses roughly three requests in four, so a
    cold launch is a coin flip: squelch tries eight times and then opens the
    single configured feed, which at the default airport reads as "squelch
    only found KPDX tower" and gives no sign that the other eleven feeds
    exist. More attempts at launch is not the answer -- that trades a wrong
    pane for a pane that takes a minute to appear.

    Out here nobody is waiting on a UI, so it can afford to be patient. Once
    this has run, launches read the cache and make no request at all.
    """
    out(f"Fetching the LiveATC feed list for {config.icao}...")
    try:
        feeds = fetch(
            config.icao, cache_dir=cache_dir, attempts=REFRESH_ATTEMPTS
        )
    except FeedError:
        out(f"LiveATC publishes no feeds for {config.icao}.")
        return 1
    except Exception as exc:
        out(f"Could not reach LiveATC's listing for {config.icao}: {exc}")
        out("This is usually its bot protection rather than anything local.")
        out("Nothing was cached; try again, or just start squelch.")
        return 1
    if not feeds:
        out(f"LiveATC publishes no feeds for {config.icao}.")
        return 1
    write_cached_feeds(config.icao, feeds, directory=cache_dir)
    out(f"Cached {len(feeds)} feed(s) for {config.icao}:")
    for feed in feeds:
        out(f"  {feed.ident:<18} {feed.label}")
    return 0


def safe_call(app: Any, func: Callable[..., None], *args: Any) -> None:
    """Marshal onto the UI thread without ever raising back onto ours.

    Sessions run on daemon threads. If the app is not running by the time
    one of these fires (already quit, or not yet started),
    `call_from_thread` raises `RuntimeError("App is not running")`. That's
    harmless -- there is nobody to tell -- but left uncaught it would kill
    that session's thread with a stray traceback.
    """
    try:
        app.call_from_thread(func, *args)
    except Exception:
        pass


def main(
    argv: list[str] | None = None,
    *,
    app_factory: Callable[..., Any] = SquelchApp,
    feeds_loader: Callable[..., list[Feed]] = load_feeds,
    sessions_builder: Callable[..., list[Any]] = build_sessions,
    which: Callable[[str], str | None] = shutil.which,
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

    # Before the ffmpeg check: filling the cache needs no decoder, and a
    # machine part-way through setup should still be able to warm it.
    if args.refresh_feeds:
        return refresh_feeds(config)

    if which("ffmpeg") is None:
        print(f"squelch: {FFMPEG_MISSING}", file=sys.stderr)
        return 2

    # Warnings raised before the app exists have nowhere to go yet, so they
    # are collected and replayed once it is running.
    pending: list[str] = []
    feeds = feeds_loader(config, warn=pending.append)

    app: Any = None
    events = SessionEvents(
        on_state=lambda session, state: safe_call(app, app.set_state, session, state),
        on_warn=lambda session, message: safe_call(
            app, app.warn_for, session, message
        ),
    )

    mixer = Mixer(
        volume=config.master_volume,
        ambient_enabled=config.ambient_enabled,
        buffer_seconds=config.buffer_seconds,
    )
    sessions = sessions_builder(feeds, config, events, mixer=mixer)
    # Before the app, so a device failure is already known and is replayed
    # with the other startup warnings once the UI is up.
    mixer.start()
    report_audio_failure(mixer, pending.append)
    def open_feed(feed: Feed) -> Any:
        """An unstarted session for a feed the stack does not have.

        Its own mixer channel, unmuted: the only route here is picking a
        feed that is not open, which is a request to hear it. The app
        mounts the row and starts it.
        """
        return sessions_builder([feed], replace(config, feed=feed.ident),
                                events, mixer=mixer)[0]

    app = app_factory(
        config,
        sessions,
        feed_loader=lambda: picker_feeds(config),
        feed_opener=open_feed,
        mixer=mixer,
        # Defaults to the real os.environ and subprocess.run, and does
        # nothing at all when KCGX_RADAR_PANE is unset -- so this is safe
        # outside the cockpit.
        radar_theme=RadarTheme(),
    )

    def start_everything() -> None:
        for message in pending:
            app.warn(message)
        # Not every session: LiveATC streams a handful of feeds to one
        # address, and the app decides which (see slots.py).
        app.start_streams()

    # Started from on_mount, not here: a call_from_thread issued before
    # App.run() has the loop up raises "App is not running" and is lost.
    app.on_start = start_everything

    try:
        app.run()
    finally:
        # Unconditional: an exception escaping the UI must not leave the
        # output stream and a dozen ffmpeg processes behind. The mixer goes
        # first -- the callback reads the channels the sessions are still
        # writing to.
        mixer.stop()
        # app._sessions, not the local: a feed opened from the picker after
        # startup is not in the list built above, and leaving it out leaks
        # an ffmpeg process and a thread per feed opened that way.
        for session in getattr(app, "_sessions", sessions) or sessions:
            session.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
