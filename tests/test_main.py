"""Tests for the wiring: discovering feeds, building sessions, starting up."""

from __future__ import annotations

import pytest

from squelch.__main__ import (
    FFMPEG_MISSING,
    build_sessions,
    feed_selection_hint,
    load_feeds,
    main,
    parse_args,
    safe_call,
)
from squelch.config import Config
from squelch.feeds import Feed

FEEDS = [
    Feed(ident="kpdx3_twr", label="KPDX Tower (Both)"),
    Feed(ident="kpdx3_gnd", label="KPDX Ground"),
    Feed(ident="kpdx3_atis", label="KPDX ATIS"),
]


# -- arguments -------------------------------------------------------------


def test_defaults_come_from_config():
    args = parse_args([])
    assert args.feed is None
    assert args.icao is None


def test_feed_and_icao_overrides():
    args = parse_args(["--feed", "ksea_twr", "--icao", "KSEA"])
    assert args.feed == "ksea_twr"
    assert args.icao == "KSEA"


# -- feed discovery --------------------------------------------------------


def test_load_feeds_returns_everything_the_airport_publishes():
    warnings = []
    assert load_feeds(Config(), warn=warnings.append, fetch=lambda icao: FEEDS) == FEEDS
    assert warnings == []


def test_load_feeds_falls_back_to_the_configured_feed_when_discovery_fails():
    """An empty pane is worse than one known-good feed."""

    def boom(icao):
        raise RuntimeError("network down")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"), warn=warnings.append, fetch=boom
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    assert warnings and "network down" in warnings[0]
    assert "kpdx3_twr" in warnings[0], "say what it opened instead"


def test_load_feeds_falls_back_when_the_airport_lists_nothing():
    warnings = []
    feeds = load_feeds(Config(feed="kpdx3_twr"), warn=warnings.append, fetch=lambda i: [])
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    assert warnings


# -- sessions --------------------------------------------------------------


class StubSession:
    def __init__(self, feed, events, *, muted=True, icao=""):
        self.feed = feed
        self.events = events
        self.muted = muted
        self.icao = icao
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


def test_feed_selection_hint_points_at_the_row_not_a_restart():
    """Every feed is already open, so selecting one is a lookup, not a switch."""
    hint = feed_selection_hint(Feed(ident="ksea_twr", label="KSEA Tower"))
    assert "ksea_twr" in hint
    assert "space" in hint


def test_safe_call_swallows_an_app_that_is_not_running():
    class DeadApp:
        def call_from_thread(self, func, *args):
            raise RuntimeError("App is not running")

    safe_call(DeadApp(), lambda: None)  # must not raise


# -- main() ----------------------------------------------------------------


class FakeApp:
    def __init__(self, config, sessions, **kwargs):
        self.config = config
        self.sessions = sessions
        self.on_start = lambda: None
        self.on_feed_selected = lambda feed: None
        self.warnings = []
        self.ran = False

    def warn(self, message):
        self.warnings.append(message)

    def run(self):
        self.ran = True
        self.on_start()


def run_main(argv=None, **overrides):
    holder = {}

    def app_factory(config, sessions, **kwargs):
        holder["app"] = FakeApp(config, sessions, **kwargs)
        return holder["app"]

    kwargs = dict(
        app_factory=app_factory,
        feeds_loader=lambda config, warn: FEEDS,
        sessions_builder=lambda feeds, config, events: [
            StubSession(f, events) for f in feeds
        ],
        which=lambda name: f"/usr/bin/{name}",
    )
    kwargs.update(overrides)
    code = main(argv or [], **kwargs)
    return code, holder.get("app")


def test_main_starts_every_session():
    code, app = run_main()
    assert code == 0
    assert app.ran
    assert all(s.started for s in app.sessions)


def test_main_stops_every_session_even_if_the_ui_raises():
    """A dozen ffmpeg processes and PortAudio streams must not be left behind."""
    holder = {}

    class ExplodingApp(FakeApp):
        def run(self):
            self.on_start()
            raise RuntimeError("ui blew up")

    def app_factory(config, sessions, **kwargs):
        holder["app"] = ExplodingApp(config, sessions, **kwargs)
        return holder["app"]

    with pytest.raises(RuntimeError):
        main(
            [],
            app_factory=app_factory,
            feeds_loader=lambda config, warn: FEEDS,
            sessions_builder=lambda feeds, config, events: [
                StubSession(f, events) for f in feeds
            ],
            which=lambda name: f"/usr/bin/{name}",
        )
    assert all(s.stopped for s in holder["app"].sessions)


def test_main_refuses_to_start_without_ffmpeg(capsys):
    code, app = run_main(which=lambda name: None)
    assert code == 2
    assert app is None, "the UI must not start with no way to decode audio"
    assert "brew install ffmpeg" in capsys.readouterr().err


def test_discovery_warnings_are_replayed_once_the_ui_is_running():
    """Warnings raised before the app exists have nowhere to go yet."""

    def loader(config, warn):
        warn("could not list feeds for KPDX")
        return FEEDS[:1]

    _code, app = run_main(feeds_loader=loader)
    assert "could not list feeds for KPDX" in app.warnings


def test_main_rejects_an_invalid_config_before_starting_the_ui(tmp_path, monkeypatch):
    bad = tmp_path / "squelch.toml"
    bad.write_text("feed = 3\n")  # must be a string
    import squelch.config as config_module

    monkeypatch.setattr(config_module, "DEFAULT_PATH", bad)
    started = []

    def app_factory(config, sessions, **kwargs):
        started.append(config)
        raise AssertionError("the UI must not start with an unusable config")

    assert main([], app_factory=app_factory) == 2
    assert started == []


def test_cli_overrides_reach_the_sessions():
    seen = {}

    def loader(config, warn):
        seen["config"] = config
        return FEEDS

    run_main(["--icao", "KSEA", "--feed", "ksea_twr"], feeds_loader=loader)
    assert seen["config"].icao == "KSEA"
    assert seen["config"].feed == "ksea_twr"
