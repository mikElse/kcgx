import itertools

from squelch.audio import StreamReader, backoff_delays, ffmpeg_command
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


def test_reader_reconnects_after_process_dies():
    spawned = []

    def spawn(url):
        proc = FakeProcess([b"\x00" * FRAME_BYTES])
        spawned.append(proc)
        return proc

    delays = []
    reader = StreamReader("u", spawn=spawn, sleep=delays.append)
    list(itertools.islice(reader.frames(), 3))
    assert len(spawned) >= 2, "must respawn ffmpeg after EOF"
    assert delays[0] == 1.0, "first retry waits 1 s"


def test_stop_halts_iteration():
    proc = FakeProcess([b"\x00" * FRAME_BYTES] * 100)
    reader = StreamReader("u", spawn=lambda url: proc, sleep=lambda s: None)
    it = reader.frames()
    next(it)
    reader.stop()
    assert list(it) == []
    assert proc.killed
