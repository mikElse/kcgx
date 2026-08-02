import itertools
import subprocess

import pytest

from squelch.audio import (
    RECONNECT_TICK_S,
    Player,
    StreamReader,
    backoff_delays,
    ffmpeg_command,
)
from squelch.vad import FRAME_BYTES


def test_ffmpeg_command_requests_16k_mono_s16le():
    cmd = ffmpeg_command("https://example.test/stream")
    assert cmd[0] == "ffmpeg"
    assert "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "16000"
    assert "-ac" in cmd and cmd[cmd.index("-ac") + 1] == "1"
    assert "-f" in cmd and cmd[cmd.index("-f") + 1] == "s16le"
    assert cmd[-1] == "-"
    assert "https://example.test/stream" in cmd


def test_backoff_doubles_then_caps():
    assert list(itertools.islice(backoff_delays(cap=30.0), 8)) == [
        1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0
    ]


class FakeProcess:
    """Stands in for a Popen with a readable stdout."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.stdout = self
        self.killed = False

    def read(self, n):
        return self._chunks.pop(0) if self._chunks else b""

    def poll(self):
        return None if self._chunks else 1

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 1


def test_frames_are_exactly_frame_sized():
    proc = FakeProcess([b"\x01" * 1000, b"\x02" * 280])
    reader = StreamReader("u", spawn=lambda url: proc, sleep=lambda s: None)
    frames = list(itertools.islice(reader.frames(), 2))
    assert all(len(f) == FRAME_BYTES for f in frames)


def audio_only(frames):
    """Drop the reconnect heartbeats -- see StreamReader.frames' contract."""
    return [f for f in frames if f is not None]


def test_reader_reconnects_after_process_dies():
    spawned = []

    def spawn(url):
        proc = FakeProcess([b"\x00" * FRAME_BYTES])
        spawned.append(proc)
        return proc

    slept = []
    reader = StreamReader("u", spawn=spawn, sleep=slept.append)
    # Take items until the *second* connection's first frame arrives: the
    # backoff now hands back a `None` heartbeat every RECONNECT_TICK_S
    # instead of sleeping silently, so one gap costs several iterator items.
    taken = []
    for item in reader.frames():
        taken.append(item)
        if len(audio_only(taken)) == 2:
            break
    assert len(audio_only(taken)) == 2
    assert len(spawned) >= 2, "must respawn ffmpeg after EOF"
    assert sum(slept) == pytest.approx(1.0), "first retry waits 1 s in total"
    assert all(s <= RECONNECT_TICK_S for s in slept), (
        "the backoff must be slept in short ticks, never as one silent "
        "block -- the consumer cannot report an outage it is never told "
        "about"
    )


def test_backoff_yields_heartbeats_instead_of_sleeping_silently():
    """The reader must check in while it waits out a reconnect.

    Regression test for the header being stuck on "LIVE" through every
    outage: the delay used to be a single `sleep()` inside the generator,
    so the consumer was parked inside its `for` statement for the whole
    gap and had no opportunity to report anything at all. The first gap is
    1.0 s at a 0.25 s tick, so at least three heartbeats must arrive
    between the last frame of one connection and the first of the next.
    """
    procs = iter(
        [
            FakeProcess([b"\xaa" * FRAME_BYTES]),
            FakeProcess([b"\xbb" * FRAME_BYTES]),
        ]
    )
    reader = StreamReader("u", spawn=lambda url: next(procs), sleep=lambda s: None)
    taken = list(itertools.islice(reader.frames(), 8))

    assert taken[0] == b"\xaa" * FRAME_BYTES
    gap = taken[1 : taken.index(b"\xbb" * FRAME_BYTES)]
    assert gap, "no heartbeat at all was emitted during the backoff"
    assert all(item is None for item in gap)
    assert len(gap) >= 3, (
        f"a 1.0 s backoff at a {RECONNECT_TICK_S} s tick must yield at "
        f"least 3 heartbeats, got {len(gap)}"
    )


def test_reconnecting_flag_is_set_while_heartbeating():
    """The heartbeats must arrive *while* `reconnecting` is True.

    Guards the flag and the heartbeat staying in step: a heartbeat emitted
    with the flag already cleared would be reported as "live" by the
    consumer, which is the same invisible-outage bug in a different place.
    """
    procs = iter(
        [
            FakeProcess([b"\xaa" * FRAME_BYTES]),
            FakeProcess([b"\xbb" * FRAME_BYTES]),
        ]
    )
    reader = StreamReader("u", spawn=lambda url: next(procs), sleep=lambda s: None)
    seen = []
    for item in itertools.islice(reader.frames(), 8):
        seen.append((item, reader.reconnecting))
    heartbeats = [flag for item, flag in seen if item is None]
    assert heartbeats and all(heartbeats)


def test_backoff_resets_after_a_healthy_connection():
    """A connection that actually delivered audio clears the schedule.

    Regression test: `backoff_delays()` used to be created once, outside
    the reconnect loop, so the delay only ever grew. After a handful of
    routine dropouts spread over an evening, every later gap -- including
    ones following hours of healthy streaming -- waited the full 30 s cap.
    """
    # Every connection delivers exactly one frame and then dies -- i.e.
    # every connection was "healthy" by the only measure the reader has.
    gaps = []
    current = []

    def sleep(seconds):
        current.append(seconds)

    reader = StreamReader(
        "u",
        spawn=lambda url: FakeProcess([b"\x01" * FRAME_BYTES]),
        sleep=sleep,
    )
    for item in reader.frames():
        if item is not None and current:
            gaps.append(sum(current))
            current.clear()
            if len(gaps) == 3:
                break

    assert len(gaps) == 3, "test must observe three reconnects"
    assert gaps == pytest.approx([1.0, 1.0, 1.0]), (
        "each connection delivered frames, so every gap is a fresh outage "
        f"and must restart the backoff at 1 s, got {gaps!r}"
    )


def test_stop_halts_iteration():
    proc = FakeProcess([b"\x00" * FRAME_BYTES] * 100)
    reader = StreamReader("u", spawn=lambda url: proc, sleep=lambda s: None)
    it = reader.frames()
    next(it)
    reader.stop()
    assert list(it) == []
    assert proc.killed


def test_buffer_does_not_span_reconnect():
    """A partial frame from a dead connection must never be spliced onto
    the next connection's bytes.

    First connection delivers 300 bytes (less than one frame) and then
    dies. Second connection delivers exactly one frame's worth of
    distinguishable bytes. The first yielded frame must be composed
    entirely of the second connection's bytes -- not a mix of both.
    """
    procs = iter(
        [
            FakeProcess([b"\xaa" * 300]),
            FakeProcess([b"\xbb" * FRAME_BYTES]),
        ]
    )
    reader = StreamReader("u", spawn=lambda url: next(procs), sleep=lambda s: None)
    # The first connection dies without ever completing a frame, so the
    # heartbeats emitted while the backoff is waited out come first; the
    # first *audio* frame is the one under test.
    frame = next(f for f in itertools.islice(reader.frames(), 20) if f is not None)
    assert frame == b"\xbb" * FRAME_BYTES, (
        "leftover bytes from the dead first connection leaked into a frame "
        "from the second connection"
    )


class TimeoutThenReapableProcess(FakeProcess):
    """A process whose first wait() times out, then reaps successfully."""

    def __init__(self, chunks):
        super().__init__(chunks)
        self.wait_calls = []

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if len(self.wait_calls) == 1:
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout)
        return 1


def test_kill_reaps_process_after_wait_timeout():
    """If the first wait() after kill() times out, the process must still
    be reaped rather than silently abandoned."""
    proc = TimeoutThenReapableProcess([b"\x00" * FRAME_BYTES] * 5)
    reader = StreamReader("u", spawn=lambda url: proc, sleep=lambda s: None)
    it = reader.frames()
    next(it)
    reader.stop()
    list(it)
    assert proc.killed
    assert len(proc.wait_calls) >= 2, (
        "must retry wait() after TimeoutExpired instead of abandoning the "
        "process unreaped"
    )


class FakeStream:
    """A PortAudio-ish stream that records the order of operations."""

    def __init__(self):
        self.calls = []

    def write(self, pcm):
        self.calls.append("write")

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


def test_player_stop_detaches_stream_before_closing_it():
    """A concurrent write() must see None, not a stream mid-close.

    Regression test: stop() used to call `self._stream.stop()` while
    `self._stream` still referenced the live stream, so the audio thread
    could enter write() and hand PCM to PortAudio during (or after) the
    close. The check is done from inside the stream's own stop(), which is
    the exact instant the race window used to be open.
    """
    player = Player()
    stream = FakeStream()
    observed = {}

    def stop():
        observed["stream_attr"] = player._stream
        stream.calls.append("stop")

    stream.stop = stop
    player._stream = stream
    player.stop()

    assert observed["stream_attr"] is None, (
        "the stream reference must be cleared before the stream is stopped, "
        "so a write() racing this call short-circuits instead of writing "
        "into a stream being torn down"
    )
    assert stream.calls == ["stop", "close"]


def test_player_stop_is_idempotent_and_never_raises():
    """stop() runs from main()'s finally clause; it must not add a crash."""

    class ExplodingStream(FakeStream):
        def stop(self):
            raise RuntimeError("PortAudio is unhappy")

    player = Player()
    player.stop()  # never started
    player._stream = ExplodingStream()
    player.stop()
    player.stop()
    assert player._stream is None
