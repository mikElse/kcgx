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
    cached_age_seconds,
    fetch_feeds,
    read_cached_feeds,
    write_cached_feeds,
)
from squelch.session import FeedSession, SessionEvents

FFMPEG_MISSING = (
    "ffmpeg not found on PATH — squelch decodes feeds with it. "
    "Install it (macOS: brew install ffmpeg) and start squelch again."
)


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


def feed_selection_hint(feed: Feed) -> str:
    """What to tell the user when they pick a feed from the overlay.

    The picker lists the same feeds already on screen; selecting one is a
    way to find its ident, not a way to change what is playing.
    """
    return f"{feed.ident} — already open; use [space] on its row to unmute"


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
    except Exception as exc:
        stale = read_cached_feeds(config.icao, directory=cache_dir)
        if stale:
            days = (age or 0) / 86400
            warn(
                f"could not refresh the feed list for {config.icao} ({exc}) — "
                f"using the cached list from {days:.0f} day(s) ago"
            )
            return stale
        warn(f"could not list feeds for {config.icao} ({exc}) — opening {config.feed}")
        return [Feed(ident=config.feed, label=config.feed)]

    if not feeds:
        stale = read_cached_feeds(config.icao, directory=cache_dir)
        if stale:
            warn(f"no feeds listed for {config.icao} — using the cached list")
            return stale
        warn(f"no feeds listed for {config.icao} — opening {config.feed}")
        return [Feed(ident=config.feed, label=config.feed)]

    write_cached_feeds(config.icao, feeds, directory=cache_dir)
    return feeds


def build_sessions(
    feeds: list[Feed],
    config: Config,
    events: SessionEvents,
    *,
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
            )
        )
    if sessions and all(s.muted for s in sessions):
        # The configured ident matched nothing this airport publishes.
        # Opening entirely silent reads as broken, so unmute the first.
        sessions[0].muted = False
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
        on_level=lambda session, dbfs: safe_call(app, app.set_level, session, dbfs),
        on_state=lambda session, state: safe_call(app, app.set_state, session, state),
        on_warn=lambda session, message: safe_call(
            app, app.warn_for, session, message
        ),
    )

    sessions = sessions_builder(feeds, config, events)
    app = app_factory(
        config,
        sessions,
        feed_loader=lambda: fetch_feeds(config.icao),
    )
    app.on_feed_selected = lambda feed: app.warn(feed_selection_hint(feed))

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
        # Unconditional: an exception escaping the UI must not leave a dozen
        # PortAudio streams and ffmpeg processes behind.
        for session in sessions:
            session.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
