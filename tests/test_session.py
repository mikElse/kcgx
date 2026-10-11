"""Tests for one feed's runtime.

The critical property is isolation: twelve feeds means twelve ways to fail,
and any one of them must end up as a dead dot on its own row without
touching the others.
"""

from __future__ import annotations

import threading

import pytest

from squelch.feeds import Feed
from squelch.mixer import Mixer
from squelch.session import FeedSession, SessionEvents, strip_icao


def channel():
    """A real mixer channel, not a fake: the session/mixer contract is
    exactly what these tests are for, and a fake would be free to drift."""
    return Mixer().add_channel()


class FakePipeline:
    """Reports one activity reading and one state, then returns."""

    def __init__(self, reader, sink, events):
        self.reader = reader
        self.sink = sink
        self.events = events
        self.stopped = False

    def run(self):
        self.events.on_state("live")
        self.events.on_activity(-12.0)

    def stop(self):
        self.stopped = True


def recorder():
    got = {"states": [], "warns": []}
    return got, SessionEvents(
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
        channel=channel(),
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


def test_runs_the_pipeline_and_reports_state_and_activity():
    session, got = make()
    session.run()
    assert ("kpdx3_twr", "live") in got["states"]
    assert session.activity == 1.0, "-12 dBFS is well above the busy threshold"


def test_muting_gates_audio_but_not_the_stream():
    """The meter and the ranking must keep running while a feed is muted."""
    session, _got = make(muted=True)
    session.run()
    assert session.muted is True
    assert session.activity == 1.0, "a muted feed must still be measured"


def test_toggle_mute_flips_the_channel_gate():
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
        pipeline_factory=FakePipeline,
    )
    sessions = [
        FeedSession(
            Feed(ident=ident, label=f"KPDX {ident}"),
            events,
            channel=channel(),
            **common,
        )
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
    measured = {s.feed.ident for s in sessions if s.activity > 0.0}
    assert measured == {"good_one", "good_two"}


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


# -- activity --------------------------------------------------------------


def test_a_session_starts_with_no_activity():
    session, _ = make()
    assert session.activity == 0.0


def test_activity_readings_reach_the_tracker():
    session, _ = make()
    for _ in range(10):
        session._on_activity(-10.0)
    assert session.activity == 1.0


def test_activity_ignores_levels_below_the_threshold():
    session, _ = make()
    for _ in range(10):
        session._on_activity(-70.0)
    assert session.activity == 0.0


def test_muting_a_session_mutes_its_channel():
    ch = channel()
    session, _ = make(channel=ch)
    session.muted = False
    assert ch.muted is False
    session.muted = True
    assert ch.muted is True


def test_ambient_routing_reaches_the_channel():
    ch = channel()
    session, _ = make(channel=ch)
    session.toggle_ambient()
    assert ch.ambient is True


def test_a_session_reports_the_channel_s_level():
    ch = channel()
    session, _ = make(channel=ch)
    ch.level_dbfs = -18.0
    assert session.level == -18.0


def test_a_session_without_a_channel_still_constructs():
    """Sessions are built before the mixer opens its device."""
    session, _ = make(channel=None)
    session.muted = False
    assert session.muted is False
    session.write(b"\x00\x00" * 320)


def test_frames_reach_the_channel_s_ring_buffer():
    ch = channel()
    session, _ = make(channel=ch)
    assert ch.buffer.available == 0
    session.write(b"\x00\x40" * 320)
    assert ch.buffer.available == 320


# -- parking (see slots.py) ------------------------------------------------


class BlockingPipeline:
    """Runs until stopped, like a live stream does."""

    instances: list = []

    def __init__(self, reader, sink, events):
        self.events = events
        self.done = threading.Event()
        BlockingPipeline.instances.append(self)

    def run(self):
        self.events.on_state("live")
        self.done.wait(5)

    def stop(self):
        self.done.set()


def wait_for(predicate, timeout=2.0):
    deadline = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        deadline.wait(0.01)
    return predicate()


def test_a_session_is_not_connected_until_started():
    session, _ = make()
    assert session.connected is False


def test_park_stops_the_stream_and_says_parked():
    BlockingPipeline.instances.clear()
    session, got = make(pipeline_factory=BlockingPipeline)
    session.start()
    assert wait_for(lambda: ("kpdx3_twr", "live") in got["states"])
    session.park()
    assert session.connected is False
    assert session.state == "parked"
    assert BlockingPipeline.instances[0].done.is_set(), "the stream kept running"


def test_a_parked_feed_does_not_then_report_offline():
    """The parked pipeline's thread unwinds after park() returns, and its
    closing "offline" would overwrite "parked" on the row."""
    BlockingPipeline.instances.clear()
    session, got = make(pipeline_factory=BlockingPipeline)
    session.start()
    assert wait_for(lambda: session.state == "live")
    session.park()
    session._thread.join(2)
    assert session.state == "parked"
    assert got["states"][-1] == ("kpdx3_twr", "parked")


def test_a_parked_feed_can_be_started_again():
    BlockingPipeline.instances.clear()
    session, got = make(pipeline_factory=BlockingPipeline)
    session.start()
    assert wait_for(lambda: session.state == "live")
    session.park()
    session.start()
    assert session.connected is True
    assert wait_for(lambda: len(BlockingPipeline.instances) == 2)
    assert wait_for(lambda: session.state == "live")
    session.stop()


def test_parked_while_resolving_opens_no_stream():
    """resolve() is an HTTP fetch; a park that lands during it must stop the
    stream that would otherwise be opened once it returns."""
    BlockingPipeline.instances.clear()
    resolving = threading.Event()
    release = threading.Event()

    def slow_resolve(ident):
        resolving.set()
        release.wait(2)
        return f"https://example.test/{ident}"

    session, got = make(resolve=slow_resolve, pipeline_factory=BlockingPipeline)
    session.start()
    assert resolving.wait(2)
    session.park()
    release.set()
    session._thread.join(2)
    assert session.state == "parked"
    assert session._pipeline is None
    # A pipeline may have been built, but never run: run() is what reads the
    # reader, and the reader is what spawns ffmpeg.
    assert ("kpdx3_twr", "live") not in got["states"]


def test_start_twice_opens_one_stream():
    BlockingPipeline.instances.clear()
    session, _ = make(pipeline_factory=BlockingPipeline)
    session.start()
    session.start()
    assert wait_for(lambda: session.state == "live")
    assert len(BlockingPipeline.instances) == 1
    session.stop()
