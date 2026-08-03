"""Tests for the audio pump.

The pipeline no longer owns a worker thread or a queue — transcription was
removed — so what remains is the loop that feeds the speaker and reports
level and connection state.
"""

import struct

from squelch.audio import FRAME_BYTES, SILENCE_FLOOR_DBFS, rms_dbfs
from squelch.pipeline import Events, Pipeline


class FakeReader:
    def __init__(self, frames):
        self._frames = frames
        self.reconnecting = False
        self.stopped = False

    def frames(self):
        yield from self._frames

    def stop(self):
        self.stopped = True


class FakeSink:
    """Stands in for the FeedSession the pipeline hands frames to."""

    def __init__(self):
        self.written = []

    def write(self, pcm):
        self.written.append(pcm)


def collect_events():
    got = {"states": [], "activity": []}
    return got, Events(
        on_state=lambda s: got["states"].append(s),
        on_activity=lambda d: got["activity"].append(d),
    )


def loud_frame():
    return struct.pack("<h", 8000) * (FRAME_BYTES // 2)


def test_every_frame_reaches_the_player():
    player = FakeSink()
    _got, events = collect_events()
    Pipeline(FakeReader([loud_frame()] * 6), player, events).run()
    assert len(player.written) == 6


def test_activity_is_decimated_not_emitted_per_frame():
    """One reading per group, not one per 20 ms frame."""
    got, events = collect_events()
    Pipeline(FakeReader([loud_frame()] * 20), FakeSink(), events).run()
    assert len(got["activity"]) == 4


def test_the_activity_reading_is_the_peak_of_its_group():
    """A short transient must not be missed between samples."""
    quiet = struct.pack("<h", 100) * (FRAME_BYTES // 2)
    frames = [quiet, quiet, loud_frame(), quiet, quiet]
    got, events = collect_events()
    Pipeline(FakeReader(frames), FakeSink(), events).run()
    assert len(got["activity"]) == 1
    assert got["activity"][0] == rms_dbfs(loud_frame())


def test_live_state_is_reported_once_not_per_frame():
    got, events = collect_events()
    Pipeline(FakeReader([loud_frame()] * 10), FakeSink(), events).run()
    assert got["states"] == ["live"]


def test_heartbeat_reports_reconnecting_and_is_not_played():
    """A `None` is the absence of a sample, not silence.

    It must reach neither the mixer nor the activity count, but it must
    move the state — otherwise the pane freezes on "LIVE" through an
    outage. Counting it as activity would read an outage as five minutes
    of quiet and sink a busy frequency down the stack.
    """
    sink = FakeSink()
    got, events = collect_events()
    Pipeline(FakeReader([loud_frame(), None, None]), sink, events).run()

    assert len(sink.written) == 1, "a heartbeat must never be played"
    assert got["states"] == ["live", "reconnecting"]


def test_state_returns_to_live_after_a_reconnect():
    got, events = collect_events()
    Pipeline(FakeReader([loud_frame(), None, loud_frame()]), FakeSink(), events).run()
    assert got["states"] == ["live", "reconnecting", "live"]


def test_a_raising_callback_does_not_stop_the_loop():
    """Events callbacks are UI shims; a teardown race must not stop audio."""

    def explode(*_args):
        raise RuntimeError("UI is gone")

    player = FakeSink()
    Pipeline(
        FakeReader([loud_frame()] * 10),
        player,
        Events(on_state=explode, on_activity=explode),
    ).run()
    assert len(player.written) == 10


def test_stop_halts_the_loop_and_stops_the_reader():
    reader = FakeReader([loud_frame()] * 100)
    player = FakeSink()
    _got, events = collect_events()
    pipeline = Pipeline(reader, player, events)
    pipeline.stop()
    pipeline.run()
    assert reader.stopped
    assert player.written == []


# -- the activity tap ------------------------------------------------------


def collect_all():
    return collect_events()


def loud_frames(n):
    return [struct.pack("<h", 8000) * (FRAME_BYTES // 2) for _ in range(n)]


def test_activity_is_reported_at_a_fixed_ten_hertz():
    got, events = collect_all()
    Pipeline(FakeReader(loud_frames(20)), FakeSink(), events).run()
    assert len(got["activity"]) == 4, "20 frames at one per 5 is 4 readings"


def test_a_reconnect_heartbeat_does_not_feed_activity():
    """A `None` is the absence of a sample, not five minutes of silence."""
    got, events = collect_all()
    Pipeline(FakeReader([None] * 10), FakeSink(), events).run()
    assert got["activity"] == []
    assert got["states"] == ["reconnecting"]


def test_events_can_still_be_built_without_an_activity_callback():
    """Existing construction sites must keep working."""
    events = Events(on_state=lambda s: None)
    Pipeline(FakeReader(loud_frames(10)), FakeSink(), events).run()


def test_a_failing_activity_callback_does_not_stop_the_pump():
    def explode(_dbfs):
        raise RuntimeError("boom")

    events = Events(on_state=lambda s: None, on_activity=explode)
    player = FakeSink()
    Pipeline(FakeReader(loud_frames(10)), player, events).run()
    assert len(player.written) == 10, "audio must survive a broken callback"
