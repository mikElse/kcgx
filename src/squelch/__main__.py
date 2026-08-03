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
    CACHE_TTL_SECONDS,
    Feed,
    FeedError,
    cached_age_seconds,
    fetch_feeds,
    read_cached_feeds,
    write_cached_feeds,
)
from squelch.mixer import Mixer
from squelch.radar_theme import RadarTheme
from squelch.session import FeedSession, SessionEvents

AUDIO_FAILED = (
    "no audio device — every feed is still connecting and metering, "
    "but nothing can be heard"
)

FFMPEG_MISSING = (
    "ffmpeg not found on PATH — squelch decodes feeds with it. "
    "Install it (macOS: brew install ffmpeg) and start squelch again."
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
    return parser.parse_args(argv)


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


def _no_feeds(
    config: Config,
    warn: Callable[[str], None],
    reason: str,
    *,
    retryable: bool,
) -> list[Feed]:
    """What to open when the airport's feed list could not be had.

    The configured feed is only a sane fallback at its own airport. Since
    the cockpit can retarget squelch anywhere, falling back to kpdx3_twr at
    KORD would play Portland tower under a header reading KORD -- audio
    from the wrong airport is worse than an empty pane.

    The ident-prefix check is a heuristic, not a lookup, and it is
    deliberately conservative in both directions:

    - It requires a non-empty `config.icao` before trusting the prefix
      match, because `"anything".startswith("")` is True in Python -- an
      empty ICAO (reachable from a hand-edited config file; `_checked`
      only validates the type) would otherwise make every feed look like
      it belonged to the airport, which is exactly the wrong-airport-audio
      failure this function exists to prevent. There is deliberately no
      symmetric guard on `config.feed`: an empty feed cannot start with a
      non-empty ICAO, so `"".startswith("KPDX")` is already False and a
      `config.feed and` conjunct would be dead weight that reads as though
      the two cases were alike.
    - It also means a feed named after a region rather than a field --
      `norcal_app`, `chicago_center` -- never matches its airport's ICAO,
      so someone who configures one as their home feed loses the fallback
      on every network hiccup. That is accepted: it fails safe (a blank
      pane with a message) rather than failing wrong (someone else's
      audio), and deciding whether a regional feed covers a given airport
      isn't answerable offline.
    """
    # The `config.icao and` guard is load-bearing -- see the docstring; an
    # empty ICAO would match every feed. Its absence on config.feed is not
    # an oversight.
    if config.icao and config.feed.lower().startswith(config.icao.lower()):
        warn(f"{config.icao} — {reason}; opening {config.feed}")
        return [Feed(ident=config.feed, label=config.feed)]
    tail = "; press f to retry" if retryable else ""
    warn(f"{config.icao} — {reason}{tail}")
    return []


def load_feeds(
    config: Config,
    *,
    warn: Callable[[str], None],
    fetch: Callable[[str], list[Feed]] = fetch_feeds,
    cache_dir: Path | None = None,
    ttl_seconds: float = CACHE_TTL_SECONDS,
) -> list[Feed]:
    """Every feed the airport publishes, or the best available substitute.

    LiveATC's listing page sits behind Cloudflare bot protection that
    refuses roughly three requests in four, so this leans on a cache: a
    fresh one is used outright, which makes the common launch need no
    request at all. When a fetch is needed and fails, a stale cache still
    beats the last resort of opening the single configured feed -- feed
    lists change on the order of months, and the whole point of the app is
    the whole airport.
    """
    age = cached_age_seconds(config.icao, directory=cache_dir)
    if age is not None and age < ttl_seconds:
        cached = read_cached_feeds(config.icao, directory=cache_dir)
        if cached:
            return cached

    try:
        feeds = fetch(config.icao)
    except FeedError:
        # The page loaded and had no feeds on it. Retrying will not
        # conjure one, so do not suggest it.
        return _no_feeds(
            config, warn, "LiveATC has no feeds for this airport", retryable=False
        )
    except Exception as exc:
        stale = read_cached_feeds(config.icao, directory=cache_dir)
        if stale:
            days = (age or 0) / 86400
            warn(
                f"could not refresh the feed list for {config.icao} ({exc}) — "
                f"using the cached list from {days:.0f} day(s) ago"
            )
            return stale
        return _no_feeds(
            config,
            warn,
            f"could not reach LiveATC's listing ({exc})",
            retryable=True,
        )

    if not feeds:
        stale = read_cached_feeds(config.icao, directory=cache_dir)
        if stale:
            warn(f"no feeds listed for {config.icao} — using the cached list")
            return stale
        return _no_feeds(
            config, warn, "LiveATC has no feeds for this airport", retryable=False
        )

    write_cached_feeds(config.icao, feeds, directory=cache_dir)
    return feeds


def picker_feeds(
    config: Config,
    *,
    fetch: Callable[[str], list[Feed]] = fetch_feeds,
    cache_dir: Path | None = None,
) -> list[Feed]:
    """The feed list for the `f` overlay.

    Pressing `f` is an explicit request to look, so this refreshes rather
    than serving the cache outright -- but the listing is refused roughly
    three times in four, and a picker that usually reports "could not load
    feeds" is useless. A stale list is a far better answer than an error.
    """
    try:
        feeds = fetch(config.icao)
    except Exception:
        return read_cached_feeds(config.icao, directory=cache_dir) or []
    if feeds:
        write_cached_feeds(config.icao, feeds, directory=cache_dir)
        return feeds
    return read_cached_feeds(config.icao, directory=cache_dir) or []


def preferred_index(feeds: list[Feed]) -> int:
    """Which feed to leave audible when the configured one matched nothing.

    Tower is where the interesting traffic is; LiveATC's listing order is
    arbitrary and often opens on ATIS, which is a recorded loop.
    """
    for index, feed in enumerate(feeds):
        text = f"{feed.ident} {feed.label}".lower()
        if "twr" in text or "tower" in text:
            return index
    return 0


def build_sessions(
    feeds: list[Feed],
    config: Config,
    events: SessionEvents,
    *,
    mixer: Any = None,
    session_factory: Callable[..., Any] = FeedSession,
) -> list[Any]:
    """One session per feed, all muted except the configured one.

    Everything meters from the start, so the whole field's activity is
    visible immediately; only the configured feed is audible, because a
    dozen simultaneous voices is not something anyone can follow.
    """
    sessions = []
    for feed in feeds:
        sessions.append(
            session_factory(
                feed,
                events,
                muted=feed.ident != config.feed,
                icao=config.icao,
                channel=None if mixer is None else mixer.add_channel(),
                activity_threshold=config.activity_threshold_dbfs,
            )
        )
    if sessions and all(s.muted for s in sessions):
        # The configured ident matched nothing this airport publishes.
        # Opening entirely silent reads as broken, so unmute the best guess.
        sessions[preferred_index(feeds)].muted = False
    return sessions


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
    )
    sessions = sessions_builder(feeds, config, events, mixer=mixer)
    # Before the app, so a device failure is already known and is replayed
    # with the other startup warnings once the UI is up.
    mixer.start()
    report_audio_failure(mixer, pending.append)
    app = app_factory(
        config,
        sessions,
        feed_loader=lambda: picker_feeds(config),
        mixer=mixer,
        # Defaults to the real os.environ and subprocess.run, and does
        # nothing at all when KCGX_RADAR_PANE is unset -- so this is safe
        # outside the cockpit.
        radar_theme=RadarTheme(),
    )

    def start_everything() -> None:
        for message in pending:
            app.warn(message)
        for session in sessions:
            session.start()

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
        for session in sessions:
            session.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
