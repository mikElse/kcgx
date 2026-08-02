"""Tests for one feed's runtime.

The critical property is isolation: twelve feeds means twelve ways to fail,
and any one of them must end up as a dead dot on its own row without
touching the others.
"""

from __future__ import annotations

import threading

import pytest

from squelch.feeds import Feed
from squelch.session import FeedSession, SessionEvents, strip_icao


class FakePlayer:
    def __init__(self, fail_start=False):
        self.muted = False
        self.started = False
        self.stopped = False
        self.written = []
        self._fail_start = fail_start

    def start(self):
        if self._fail_start:
            raise RuntimeError("no device")
        self.started = True

    def write(self, pcm):
        if not self.muted:
            self.written.append(pcm)

    def stop(self):
        self.stopped = True


class FakePipeline:
    """Reports one level and one state, then returns."""

    def __init__(self, reader, player, events):
        self.reader = reader
        self.player = player
        self.events = events
        self.stopped = False

    def run(self):
        self.events.on_state("live")
        self.events.on_level(-12.0)

    def stop(self):
        self.stopped = True


def recorder():
    got = {"levels": [], "states": [], "warns": []}
    return got, SessionEvents(
        on_level=lambda s, d: got["levels"].append((s.feed.ident, d)),
        on_state=lambda s, st: got["states"].append((s.feed.ident, st)),
        on_warn=lambda s, m: got["warns"].append((s.feed.ident, m)),
    )


def make(feed=None, **overrides):
    got, events = recorder()
    kwargs = dict(
        muted=True,
        icao="KPDX",
        resolve=lambda ident: f"https://example.test/{ident}",
        reader_factory=lambda url: object(),
        player_factory=FakePlayer,
        pipeline_factory=FakePipeline,
    )
    kwargs.update(overrides)
    session = FeedSession(
        feed or Feed(ident="kpdx3_twr", label="KPDX Tower (Both)"), events, **kwargs
    )
    return session, got


def test_strip_icao_frees_columns_for_the_name():
    assert strip_icao("KPDX Tower (Both)", "KPDX") == "Tower (Both)"
    assert strip_icao("KPDX ATIS", "kpdx") == "ATIS"


def test_strip_icao_leaves_a_label_that_does_not_carry_the_prefix():
    assert strip_icao("ZSE Seattle Center (PDX Area)", "KPDX") == (
        "ZSE Seattle Center (PDX Area)"
    )


def test_name_has_the_icao_stripped():
    session, _ = make()
    assert session.name == "Tower (Both)"


def test_runs_the_pipeline_and_reports_level_and_state():
    session, got = make()
    session.run()
    assert ("kpdx3_twr", "live") in got["states"]
    assert ("kpdx3_twr", -12.0) in got["levels"]
    assert session.level == -12.0


def test_muting_gates_audio_but_not_the_stream():
    """The meter must keep running while a feed is muted."""
    session, got = make(muted=True)
    session.run()
    assert session.muted is True
    assert got["levels"], "a muted feed must still report levels"


def test_toggle_mute_flips_the_player_gate():
    session, _ = make(muted=True)
    assert session.toggle_mute() is False
    assert session.muted is False
    assert session.toggle_mute() is True


def test_a_feed_that_cannot_resolve_goes_offline_and_says_so():
    def boom(ident):
        raise RuntimeError("404")

    session, got = make(resolve=boom)
    session.run()
    assert session.state == "offline"
    assert got["warns"] == [("kpdx3_twr", "could not resolve feed")]


def test_a_missing_audio_device_warns_but_keeps_metering():
    """One unavailable device must not take down every feed at once."""
    session, got = make(player_factory=lambda: FakePlayer(fail_start=True))
    session.run()
    assert any("no audio device" in m for _ident, m in got["warns"])
    assert got["levels"], "the meter is still worth having without audio"


def test_an_unexpected_failure_is_reported_not_swallowed():
    """A daemon thread dying silently leaves the row frozen forever."""

    class ExplodingPipeline:
        def __init__(self, *a, **kw):
            pass

        def run(self):
            raise OSError("stream closed by peer")

        def stop(self):
            pass

    session, got = make(pipeline_factory=ExplodingPipeline)
    session.run()
    assert session.state == "offline"
    assert any("stream closed by peer" in m for _ident, m in got["warns"])


def test_one_failing_feed_does_not_affect_the_others():
    """The property the whole multi-feed design rests on."""
    got, events = recorder()

    def resolve(ident):
        if ident == "broken":
            raise RuntimeError("404")
        return f"https://example.test/{ident}"

    common = dict(
        icao="KPDX",
        resolve=resolve,
        reader_factory=lambda url: object(),
        player_factory=FakePlayer,
        pipeline_factory=FakePipeline,
    )
    sessions = [
        FeedSession(Feed(ident=ident, label=f"KPDX {ident}"), events, **common)
        for ident in ("good_one", "broken", "good_two")
    ]
    for session in sessions:
        session.run()

    # The broken feed never reached "live" and warned; the others streamed
    # normally. (Every session ends "offline" here because the fake pipeline
    # returns immediately, which a session correctly reads as the stream
    # having ended — so assert on what was *reported*, not the final state.)
    reported = {(ident, state) for ident, state in got["states"]}
    assert ("broken", "live") not in reported
    assert ("good_one", "live") in reported
    assert ("good_two", "live") in reported
    assert got["warns"] == [("broken", "could not resolve feed")]
    live_levels = {ident for ident, _ in got["levels"]}
    assert live_levels == {"good_one", "good_two"}


def test_start_runs_on_its_own_thread_and_stop_is_safe():
    session, got = make()
    session.start()
    for _ in range(200):
        if got["states"]:
            break
        threading.Event().wait(0.01)
    assert got["states"], "the session thread never ran"
    session.stop()  # must not raise even though the pipeline already returned


def test_stop_is_safe_before_anything_started():
    session, _ = make()
    session.stop()  # no pipeline, no reader yet


@pytest.mark.parametrize("state", ["live", "reconnecting", "offline"])
def test_state_is_tracked_for_the_row_to_read(state):
    session, _ = make()
    session._set_state(state)
    assert session.state == state


def test_a_session_starts_off_the_ambient_bus():
    session, _ = make()
    assert session.ambient is False


def test_toggle_ambient_flips_and_reports_the_new_value():
    session, _ = make()
    assert session.toggle_ambient() is True
    assert session.ambient is True
    assert session.toggle_ambient() is False
    assert session.ambient is False


def test_ambient_is_independent_of_mute():
    """A feed can be routed to the ambient bus while muted on the dry bus."""
    session, _ = make()
    session.toggle_ambient()
    assert session.ambient is True
    assert session.muted is True
