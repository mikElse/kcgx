"""squelch.runtime: discovering an airport's feeds, building sessions, and
filling the feed cache. Moved here from the terminal app's test_main.py when
the terminal app was retired in phase E; the server uses all of it."""

from __future__ import annotations

from squelch.config import Config
from squelch.feeds import (
    COLD_FETCH_ATTEMPTS,
    REFRESH_ATTEMPTS,
    Feed,
    read_cached_feeds,
)
from squelch.mixer import Mixer
from squelch.runtime import (
    build_sessions,
    load_feeds,
    refresh_feeds,
)
from squelch.session import FeedSession

FEEDS = [
    Feed(ident="kpdx3_twr", label="KPDX Tower (Both)"),
    Feed(ident="kpdx3_gnd", label="KPDX Ground"),
    Feed(ident="kpdx3_atis", label="KPDX ATIS"),
]


# -- arguments -------------------------------------------------------------


# -- feed discovery --------------------------------------------------------


def test_load_feeds_returns_everything_the_airport_publishes(tmp_path):
    warnings = []
    feeds = load_feeds(
        Config(), warn=warnings.append, fetch=lambda icao, **_: FEEDS, cache_dir=tmp_path
    )
    assert feeds == FEEDS
    assert warnings == []


def test_load_feeds_falls_back_to_the_configured_feed_when_discovery_fails(tmp_path):
    """An empty pane is worse than one known-good feed."""

    def boom(icao, **_):
        raise RuntimeError("network down")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=boom,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    assert warnings and "network down" in warnings[0]
    assert "kpdx3_twr" in warnings[0], "say what it opened instead"


def test_load_feeds_falls_back_when_the_airport_lists_nothing(tmp_path):
    warnings = []
    feeds = load_feeds(
        Config(feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=lambda i, **_: [],
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    assert warnings


# -- sessions --------------------------------------------------------------


class StubSession:
    def __init__(self, feed, events, *, muted=True, icao="",
                 activity_threshold=-40.0, channel=None):
        self.feed = feed
        self.events = events
        self.muted = muted
        self.icao = icao
        self.activity_threshold = activity_threshold
        self.channel = channel
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def build(feeds=FEEDS, config=None):
    return build_sessions(
        feeds,
        config or Config(icao="KPDX", feed="kpdx3_twr"),
        events=None,
        session_factory=StubSession,
    )


def test_one_session_is_built_per_feed():
    assert [s.feed.ident for s in build()] == [f.ident for f in FEEDS]


def test_exactly_one_feed_starts_unmuted():
    """Everything meters; one thing is audible."""
    sessions = build()
    unmuted = [s.feed.ident for s in sessions if not s.muted]
    assert unmuted == ["kpdx3_twr"]


def test_the_configured_feed_is_the_unmuted_one():
    sessions = build(config=Config(icao="KPDX", feed="kpdx3_atis"))
    assert [s.feed.ident for s in sessions if not s.muted] == ["kpdx3_atis"]


def test_an_unmatched_configured_feed_still_leaves_something_audible():
    """Opening entirely silent reads as broken."""
    sessions = build(config=Config(icao="KPDX", feed="does_not_exist"))
    assert sum(1 for s in sessions if not s.muted) == 1


def test_the_icao_is_passed_through_for_label_stripping():
    assert all(s.icao == "KPDX" for s in build())


def test_building_no_sessions_does_not_crash():
    assert build(feeds=[]) == []


# -- misc ------------------------------------------------------------------


# -- feed discovery, cached ------------------------------------------------
#
# LiveATC's listing page sits behind Cloudflare bot protection that refuses
# roughly three requests in four. A cache means a launch usually needs no
# request at all, and a launch that does can fall back to a stale list
# rather than to a single feed.


def test_a_fresh_cache_is_used_without_hitting_the_network(tmp_path):
    from squelch.feeds import write_cached_feeds

    write_cached_feeds("KPDX", FEEDS, directory=tmp_path)
    calls = []

    def fetch(icao, **_):
        calls.append(icao)
        raise AssertionError("must not fetch when the cache is fresh")

    feeds = load_feeds(
        Config(icao="KPDX"), warn=[].append, fetch=fetch, cache_dir=tmp_path
    )
    assert feeds == FEEDS
    assert calls == []


def test_a_successful_fetch_populates_the_cache(tmp_path):
    from squelch.feeds import read_cached_feeds

    load_feeds(
        Config(icao="KPDX"),
        warn=[].append,
        fetch=lambda icao, **_: FEEDS,
        cache_dir=tmp_path,
    )
    assert read_cached_feeds("KPDX", directory=tmp_path) == FEEDS


def test_a_stale_cache_beats_falling_back_to_one_feed(tmp_path):
    """The whole point of the app is the whole airport."""
    import os
    import time

    from squelch.feeds import cache_path, write_cached_feeds

    write_cached_feeds("KPDX", FEEDS, directory=tmp_path)
    path = cache_path("KPDX", directory=tmp_path)
    ancient = time.time() - (30 * 24 * 60 * 60)
    os.utime(path, (ancient, ancient))

    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert feeds == FEEDS, "a stale list is far better than a single feed"
    assert warnings and "cached" in warnings[0].lower()


def test_no_cache_and_a_blocked_fetch_still_opens_the_configured_feed(tmp_path):
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    assert warnings


# -- the picker's loader ---------------------------------------------------


def test_picker_refreshes_but_falls_back_to_the_cache(tmp_path):
    """Pressing `f` is an explicit refresh, so it tries the network first.

    But the listing is refused three times in four, and a picker that
    usually says "could not load feeds" is useless — the cache is a far
    better answer than an error.
    """
    from squelch.feeds import write_cached_feeds
    from squelch.runtime import picker_feeds

    write_cached_feeds("KPDX", FEEDS, directory=tmp_path)

    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    assert (
        picker_feeds(Config(icao="KPDX"), fetch=blocked, cache_dir=tmp_path) == FEEDS
    )


def test_picker_prefers_a_successful_refresh_and_recaches_it(tmp_path):
    from squelch.feeds import read_cached_feeds, write_cached_feeds
    from squelch.runtime import picker_feeds

    write_cached_feeds("KPDX", [Feed("old", "Old")], directory=tmp_path)
    fresh = picker_feeds(
        Config(icao="KPDX"), fetch=lambda icao, **_: FEEDS, cache_dir=tmp_path
    )
    assert fresh == FEEDS
    assert read_cached_feeds("KPDX", directory=tmp_path) == FEEDS


def test_picker_returns_empty_when_there_is_no_cache_and_no_network(tmp_path):
    """Empty is what makes the app say 'could not load feeds'."""
    from squelch.runtime import picker_feeds

    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    assert picker_feeds(Config(icao="KPDX"), fetch=blocked, cache_dir=tmp_path) == []


# -- switching airports ----------------------------------------------------
#
# The cockpit can now retarget squelch at any airport, so a feed lookup
# that fails at KORD must not quietly fall back to a KPDX feed. Audio from
# the wrong airport under a header reading KORD is worse than silence.


def test_a_failed_lookup_at_a_new_airport_opens_nothing(tmp_path):
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KORD", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert feeds == [], "kpdx3_twr is not a KORD feed"
    assert warnings and "KORD" in warnings[0]


def test_the_configured_feed_is_still_used_at_its_own_airport(tmp_path):
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]


def test_an_empty_icao_does_not_trust_any_feed_as_its_own(tmp_path):
    """`"anything".startswith("")` is True, so a blank icao must be

    excluded explicitly -- otherwise every configured feed would look like
    it belonged to the (nonexistent) airport, reopening the wrong-airport-
    audio hole this task exists to close. A hand-edited config file can
    reach this: `_checked` only validates that `icao` is a string, not
    that it's non-empty.
    """
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert feeds == []


def test_an_unreachable_listing_says_it_can_be_retried(tmp_path):
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    load_feeds(
        Config(icao="KORD", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert "retry" in warnings[0].lower()


def test_an_airport_liveatc_does_not_cover_does_not_suggest_retrying(tmp_path):
    """Retrying a field with no feeds will never produce one."""
    from squelch.feeds import FeedError

    def empty(icao, **_):
        raise FeedError("no feeds found on page")

    warnings = []
    feeds = load_feeds(
        Config(icao="KBDN", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=empty,
        cache_dir=tmp_path,
    )
    assert feeds == []
    assert "no feeds" in warnings[0].lower()
    assert "retry" not in warnings[0].lower()


def test_a_page_with_no_feeds_falls_back_to_the_cache(tmp_path):
    """No feeds on a page that loaded is also what a markup change looks
    like -- LiveATC's 2026-10 one blanked a cached thirty-feed airport."""
    from squelch.feeds import FeedError, write_cached_feeds

    def empty(icao, **_):
        raise FeedError("no feeds found on page")

    write_cached_feeds("KORD", [Feed(ident="kord_twr", label="KORD Tower")],
                       directory=tmp_path)
    warnings = []
    feeds = load_feeds(
        Config(icao="KORD", feed="kord_twr"),
        warn=warnings.append,
        fetch=empty,
        cache_dir=tmp_path,
        ttl_seconds=0,  # stale, so the listing is asked for
    )
    assert [f.ident for f in feeds] == ["kord_twr"]
    assert "cached" in warnings[0].lower()


# -- which feed comes up audible ------------------------------------------


def test_a_tower_feed_is_preferred_when_nothing_matches_the_config():
    """Arriving somewhere new should land on the interesting channel."""
    feeds = [
        Feed(ident="kord_atis", label="KORD ATIS"),
        Feed(ident="kord_gnd", label="KORD Ground"),
        Feed(ident="kord_twr", label="KORD Tower"),
    ]
    sessions = build_sessions(
        feeds,
        Config(icao="KORD", feed="kpdx3_twr"),
        events=None,
        session_factory=StubSession,
    )
    assert [s.feed.ident for s in sessions if not s.muted] == ["kord_twr"]


# Pins the index-0 default and would catch preferred_index returning some
# other constant, but neither feed here contains "twr"/"tower", so this
# cannot detect the matching loop being deleted -- it is not evidence that
# tower-matching works; see test_a_tower_feed_is_preferred_when_nothing_
# matches_the_config for that.
def test_the_first_feed_is_used_when_there_is_no_tower():
    feeds = [
        Feed(ident="kord_atis", label="KORD ATIS"),
        Feed(ident="kord_gnd", label="KORD Ground"),
    ]
    sessions = build_sessions(
        feeds,
        Config(icao="KORD", feed="kpdx3_twr"),
        events=None,
        session_factory=StubSession,
    )
    assert [s.feed.ident for s in sessions if not s.muted] == ["kord_atis"]


# -- the mixer -------------------------------------------------------------


def test_every_session_gets_a_channel():
    mixer = Mixer()
    feeds = [Feed(ident="a_twr", label="A Tower"), Feed(ident="a_gnd", label="A Ground")]
    sessions = build_sessions(
        feeds, Config(feed="a_twr"), events=None, mixer=mixer,
        session_factory=FeedSession,
    )
    assert len(mixer._channels) == 2
    assert all(s._channel is not None for s in sessions)


def test_the_configured_feed_starts_audible_on_its_channel():
    mixer = Mixer()
    feeds = [Feed(ident="a_twr", label="A Tower"), Feed(ident="a_gnd", label="A Ground")]
    build_sessions(
        feeds, Config(feed="a_twr"), events=None, mixer=mixer,
        session_factory=FeedSession,
    )
    assert mixer._channels[0].muted is False
    assert mixer._channels[1].muted is True


# ---------------------------------------------------------------------------
# --refresh-feeds
#
# The cold-launch problem, moved somewhere it can be solved. LiveATC refuses
# roughly three requests in four, so squelch's eight attempts fail about 10%
# of the time -- and when they do, the pane opens on the single configured
# feed with nothing said about the other eleven. Raising the launch budget
# trades a wrong pane for a slow one. This runs where nobody is waiting.

def test_refresh_feeds_caches_what_it_finds(tmp_path):
    out = []
    code = refresh_feeds(
        Config(icao="KPDX"),
        out=out.append,
        fetch=lambda icao, **_: FEEDS,
        cache_dir=tmp_path,
    )
    assert code == 0
    assert read_cached_feeds("KPDX", directory=tmp_path) == FEEDS
    printed = "\n".join(out)
    for feed in FEEDS:
        assert feed.ident in printed, printed


def test_refresh_feeds_asks_for_more_attempts_than_a_launch_does(tmp_path):
    """The whole reason it exists. Eight attempts fail ~10% of the time at
    one-in-four; twenty fail ~0.3%, and the cost is a wall clock nobody is
    watching.
    """
    seen = {}

    def record(icao, **kwargs):
        seen.update(kwargs)
        return FEEDS

    refresh_feeds(
        Config(icao="KPDX"), out=lambda _: None, fetch=record, cache_dir=tmp_path
    )
    assert seen.get("attempts") == REFRESH_ATTEMPTS
    assert REFRESH_ATTEMPTS > COLD_FETCH_ATTEMPTS


def test_refresh_feeds_reports_a_refusal_without_caching_anything(tmp_path):
    def blocked(icao, **_):
        raise OSError("HTTP Error 403: Forbidden")

    out = []
    code = refresh_feeds(
        Config(icao="KPDX"), out=out.append, fetch=blocked, cache_dir=tmp_path
    )
    assert code != 0
    assert read_cached_feeds("KPDX", directory=tmp_path) is None
    printed = "\n".join(out).lower()
    assert "403" in printed, "the actual error is what tells you whose fault it is"
    assert "bot protection" in printed, "no hint that this is usually not local"


# ---------------------------------------------------------------------------

def test_the_fallback_to_one_feed_still_says_how_to_retry(tmp_path):
    """The case that actually happens on a first launch: default config,
    default airport, listing refused. It opened kpdx3_twr and said so, and
    that was the entire message -- one feed out of twelve, no reason given
    for the other eleven, and nothing to suggest the listing was worth
    asking for again.
    """
    def blocked(icao, **_):
        raise OSError("HTTP Error 403: Forbidden")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    message = " ".join(warnings)
    assert "kpdx3_twr" in message, message
    assert "press f to retry" in message, message
    assert "403" in message, message


