import struct
from datetime import datetime

from squelch.asr import Transcript
from squelch.pipeline import Block, Events, Pipeline
from squelch.vad import FRAME_BYTES, Utterance


class FakeReader:
    def __init__(self, frames):
        self._frames = frames
        self.reconnecting = False
        self.stopped = False

    def frames(self):
        yield from self._frames

    def stop(self):
        self.stopped = True


class FakeSegmenter:
    """Emits an utterance every 3rd frame."""

    def __init__(self):
        self.count = 0

    def feed(self, frame):
        self.count += 1
        if self.count % 3 == 0:
            return Utterance(start_s=0.0, end_s=1.0, pcm=frame)
        return None

    def flush(self):
        return None


class FakeTranscriber:
    def __init__(self, text="cleared to land"):
        self.text = text
        self.seen = 0

    def transcribe(self, pcm):
        self.seen += 1
        return Transcript(text=self.text, avg_logprob=-0.2)


class FakePlayer:
    def __init__(self):
        self.written = 0
        self.muted = False

    def write(self, pcm):
        self.written += 1


def collect_events():
    got = {"levels": [], "blocks": [], "states": [], "pending": 0, "dropped": 0}
    return got, Events(
        on_level=lambda d: got["levels"].append(d),
        on_pending=lambda: got.__setitem__("pending", got["pending"] + 1),
        on_block=lambda b: got["blocks"].append(b),
        on_state=lambda s: got["states"].append(s),
        on_dropped=lambda: got.__setitem__("dropped", got["dropped"] + 1),
    )


def loud_frame():
    return struct.pack("<h", 8000) * (FRAME_BYTES // 2)


def test_pipeline_emits_blocks_and_levels():
    frames = [loud_frame()] * 9
    got, events = collect_events()
    p = Pipeline(
        FakeReader(frames), FakeSegmenter(), FakeTranscriber(), FakePlayer(), events
    )
    p.run()
    assert len(got["blocks"]) == 3
    assert all(isinstance(b, Block) for b in got["blocks"])
    assert got["blocks"][0].text == "cleared to land"
    assert len(got["levels"]) == 9
    assert got["pending"] == 3


def test_pipeline_feeds_player_every_frame():
    player = FakePlayer()
    got, events = collect_events()
    Pipeline(
        FakeReader([loud_frame()] * 6), FakeSegmenter(), FakeTranscriber(), player, events
    ).run()
    assert player.written == 6


def test_empty_transcript_is_not_emitted_as_block():
    got, events = collect_events()
    Pipeline(
        FakeReader([loud_frame()] * 3),
        FakeSegmenter(),
        FakeTranscriber(text="   "),
        FakePlayer(),
        events,
    ).run()
    assert got["blocks"] == []


def test_reconnect_state_is_reported():
    reader = FakeReader([loud_frame()] * 3)
    reader.reconnecting = True
    got, events = collect_events()
    Pipeline(reader, FakeSegmenter(), FakeTranscriber(), FakePlayer(), events).run()
    assert "reconnecting" in got["states"]


def test_backpressure_drops_instead_of_blocking():
    """A slow model must not stall audio; oldest pending work is dropped.

    Deterministic by construction: the transcriber blocks on an event rather
    than a sleep, and the assertions wait on a condition rather than a
    duration, so the test cannot flake under load.
    """
    import threading
    import time

    gate = threading.Event()

    class BlockingTranscriber(FakeTranscriber):
        def transcribe(self, pcm):
            gate.wait(timeout=10)
            return super().transcribe(pcm)

    got, events = collect_events()
    p = Pipeline(
        FakeReader([loud_frame()] * 90),
        FakeSegmenter(),
        BlockingTranscriber(),
        FakePlayer(),
        events,
        queue_size=2,
    )
    runner = threading.Thread(target=p.run)
    runner.start()
    try:
        deadline = time.monotonic() + 10
        while got["dropped"] == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
    finally:
        gate.set()
        runner.join(timeout=15)

    assert not runner.is_alive(), "audio loop must not deadlock on a slow model"
    assert got["dropped"] > 0


def test_transcriber_failure_is_reported_not_swallowed():
    """A model that raises must cost one transmission, not vanish silently."""

    class BrokenTranscriber:
        def transcribe(self, pcm):
            raise RuntimeError("inference exploded")

    got, events = collect_events()
    Pipeline(
        FakeReader([loud_frame()] * 3),
        FakeSegmenter(),
        BrokenTranscriber(),
        FakePlayer(),
        events,
    ).run()
    assert got["blocks"] == []
    assert got["dropped"] == 1
