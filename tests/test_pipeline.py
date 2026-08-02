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


class FakePlayer:
    def __init__(self):
        self.written = []
        self.muted = False

    def write(self, pcm):
        self.written.append(pcm)


def collect_events():
    got = {"levels": [], "states": []}
    return got, Events(
        on_level=lambda d: got["levels"].append(d),
        on_state=lambda s: got["states"].append(s),
    )


def loud_frame():
    return struct.pack("<h", 8000) * (FRAME_BYTES // 2)


def test_every_frame_reaches_the_player():
    player = FakePlayer()
    _got, events = collect_events()
    Pipeline(FakeReader([loud_frame()] * 6), player, events).run()
    assert len(player.written) == 6


def test_levels_are_decimated_not_emitted_per_frame():
    """One reading per group, not one per 20 ms frame.

    Each emission is a `call_from_thread` round trip billed to the audio
    thread, and a 20-sample meter fed at 50 Hz turns over 2.5x a second.
    """
    got, events = collect_events()
    Pipeline(FakeReader([loud_frame()] * 20), FakePlayer(), events, level_every=5).run()
    assert len(got["levels"]) == 4


def test_level_emitted_is_the_peak_of_its_group():
    """A short transient must not be missed between samples."""
    quiet = struct.pack("<h", 100) * (FRAME_BYTES // 2)
    frames = [quiet, quiet, loud_frame(), quiet, quiet]
    got, events = collect_events()
    Pipeline(FakeReader(frames), FakePlayer(), events, level_every=5).run()
    assert len(got["levels"]) == 1
    assert got["levels"][0] == rms_dbfs(loud_frame())


def test_live_state_is_reported_once_not_per_frame():
    got, events = collect_events()
    Pipeline(FakeReader([loud_frame()] * 10), FakePlayer(), events).run()
    assert got["states"] == ["live"]


def test_heartbeat_reports_reconnecting_and_is_not_played():
    """A `None` is the absence of a sample, not silence.

    It must reach neither the speaker nor the level calculation, but it
    must move the state and keep the meter alive — otherwise the pane
    freezes on "LIVE" through an outage.
    """
    player = FakePlayer()
    got, events = collect_events()
    Pipeline(FakeReader([loud_frame(), None, None]), player, events).run()

    assert len(player.written) == 1, "a heartbeat must never be played"
    assert got["states"] == ["live", "reconnecting"]
    assert SILENCE_FLOOR_DBFS in got["levels"], "the meter must keep moving"


def test_state_returns_to_live_after_a_reconnect():
    got, events = collect_events()
    Pipeline(FakeReader([loud_frame(), None, loud_frame()]), FakePlayer(), events).run()
    assert got["states"] == ["live", "reconnecting", "live"]


def test_a_raising_callback_does_not_stop_the_loop():
    """Events callbacks are UI shims; a teardown race must not stop audio."""

    def explode(*_args):
        raise RuntimeError("UI is gone")

    player = FakePlayer()
    Pipeline(
        FakeReader([loud_frame()] * 10),
        player,
        Events(on_level=explode, on_state=explode),
    ).run()
    assert len(player.written) == 10


def test_stop_halts_the_loop_and_stops_the_reader():
    reader = FakeReader([loud_frame()] * 100)
    player = FakePlayer()
    _got, events = collect_events()
    pipeline = Pipeline(reader, player, events)
    pipeline.stop()
    pipeline.run()
    assert reader.stopped
    assert player.written == []


# -- the activity tap ------------------------------------------------------


def collect_all():
    got = {"levels": [], "states": [], "activity": []}
    return got, Events(
        on_level=lambda d: got["levels"].append(d),
        on_state=lambda s: got["states"].append(s),
        on_activity=lambda d: got["activity"].append(d),
    )


def loud_frames(n):
    return [struct.pack("<h", 8000) * (FRAME_BYTES // 2) for _ in range(n)]


def test_activity_is_reported_at_a_fixed_ten_hertz():
    got, events = collect_all()
    Pipeline(FakeReader(loud_frames(20)), FakePlayer(), events).run()
    assert len(got["activity"]) == 4, "20 frames at one per 5 is 4 readings"


def test_the_display_rate_is_independent_of_the_activity_rate():
    got, events = collect_all()
    Pipeline(
        FakeReader(loud_frames(20)), FakePlayer(), events, level_every=2
    ).run()
    assert len(got["levels"]) == 10
    assert len(got["activity"]) == 4


def test_the_display_rate_can_be_changed_at_runtime():
    got, events = collect_all()
    pipeline = Pipeline(FakeReader(loud_frames(20)), FakePlayer(), events)
    pipeline.set_level_every(2)
    pipeline.run()
    assert len(got["levels"]) == 10


def test_a_reconnect_heartbeat_does_not_feed_activity():
    """A `None` is the absence of a sample, not five minutes of silence."""
    got, events = collect_all()
    Pipeline(FakeReader([None] * 10), FakePlayer(), events).run()
    assert got["activity"] == []
    assert got["states"] == ["reconnecting"]


def test_events_can_still_be_built_without_an_activity_callback():
    """Existing construction sites must keep working."""
    events = Events(on_level=lambda d: None, on_state=lambda s: None)
    Pipeline(FakeReader(loud_frames(10)), FakePlayer(), events).run()


def test_a_failing_activity_callback_does_not_stop_the_pump():
    def explode(_dbfs):
        raise RuntimeError("boom")

    events = Events(
        on_level=lambda d: None,
        on_state=lambda s: None,
        on_activity=explode,
    )
    player = FakePlayer()
    Pipeline(FakeReader(loud_frames(10)), player, events).run()
    assert len(player.written) == 10, "audio must survive a broken callback"
