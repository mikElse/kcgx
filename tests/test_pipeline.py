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


def test_on_block_exception_does_not_kill_worker():
    """A raising UI callback must cost at most one block, not every
    subsequent utterance for the rest of the run.

    Task 9 wires on_block to app.call_from_thread(...), which can raise
    while the Textual app is tearing down mid-quit. Before the fix, that
    exception propagated out of the worker thread's loop body and killed
    the thread outright -- every utterance queued after the first one would
    silently vanish (no on_block, no on_dropped, nothing).
    """
    calls = {"count": 0}

    def flaky_on_block(block):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("UI gone mid-quit")

    got, events = collect_events()
    events.on_block = flaky_on_block

    transcriber = FakeTranscriber()
    frames = [loud_frame()] * 12  # FakeSegmenter -> 4 utterances
    Pipeline(
        FakeReader(frames), FakeSegmenter(), transcriber, FakePlayer(), events
    ).run()

    assert transcriber.seen == 4, "every utterance must still reach the model"
    assert calls["count"] == 4, "on_block must still be invoked for later blocks"


def test_flaky_level_callback_does_not_abort_audio_loop():
    """A raising on_level (or on_pending/on_state) callback must not stop
    playback -- at most the UI lost one update, audio keeps flowing.
    """
    got, events = collect_events()

    def flaky_on_level(db):
        got["levels"].append(db)
        raise RuntimeError("UI widget vanished")

    events.on_level = flaky_on_level
    player = FakePlayer()
    frames = [loud_frame()] * 9
    Pipeline(
        FakeReader(frames), FakeSegmenter(), FakeTranscriber(), player, events
    ).run()

    assert player.written == 9
    assert len(got["levels"]) == 9


def test_submit_does_not_report_drop_when_worker_already_drained_the_slot():
    """Full-then-Empty is not a real drop.

    If put_nowait raises Full but the worker races ahead and drains the
    slot before our eviction attempt runs, get_nowait raises Empty and
    nothing was actually lost -- only a genuine eviction of a live item
    should fire on_dropped. This interleaving is real (confirmed reachable)
    but too narrow a window to hit reliably through real thread scheduling,
    so it is exercised directly against _submit with a controlled fake
    queue rather than via real contention.
    """
    import queue as queue_module

    class RaceyQueue:
        def __init__(self):
            self.put_calls = 0

        def put_nowait(self, item):
            self.put_calls += 1
            if self.put_calls == 1:
                raise queue_module.Full
            # retry after the (failed) eviction attempt succeeds

        def get_nowait(self):
            raise queue_module.Empty

    got, events = collect_events()
    p = Pipeline(
        FakeReader([]), FakeSegmenter(), FakeTranscriber(), FakePlayer(), events
    )
    p._queue = RaceyQueue()

    p._submit(Utterance(start_s=0.0, end_s=1.0, pcm=loud_frame()))

    assert got["dropped"] == 0


def test_shutdown_does_not_block_when_transcriber_never_returns():
    """run() must return within a bounded time even if the transcriber is
    permanently wedged and the queue is full.

    Before the fix, the sentinel handoff (`self._queue.put(_SENTINEL)`) was
    a plain blocking put with no timeout: if the queue was already full
    *and* the worker was genuinely busy inside transcribe() (not merely
    idle-and-about-to-dequeue), that put -- not just worker.join -- hung
    until the in-flight transcription finished, so the documented shutdown
    bound was never even reached.

    The queue-is-full-but-worker-is-idle interleaving resolves in
    microseconds regardless of the bug (the worker just dequeues
    immediately), so reproducing the real hang requires forcing the
    worker to genuinely be mid-transcribe before the last utterance is
    queued. `GatedReader` blocks frame delivery (via an Event, not a
    sleep) until the transcriber signals it has actually started, which
    deterministically creates that interleaving.
    """
    import threading

    worker_started = threading.Event()

    class GatedReader:
        def __init__(self, frames):
            self._frames = frames
            self.reconnecting = False
            self.stopped = False

        def frames(self):
            for i, frame in enumerate(self._frames):
                yield frame
                if i == 2:  # just yielded the utterance-completing frame
                    # Don't hand over the remaining frames until the
                    # worker is verifiably busy inside transcribe() --
                    # otherwise the "full queue" state resolves before
                    # the worker ever gets scheduled, and the bug this
                    # test targets never has a chance to trigger.
                    worker_started.wait(timeout=5)

        def stop(self):
            self.stopped = True

    class NeverReturningTranscriber(FakeTranscriber):
        def transcribe(self, pcm):
            worker_started.set()
            threading.Event().wait(timeout=10)  # blocks; nobody ever sets it
            return super().transcribe(pcm)

    got, events = collect_events()
    p = Pipeline(
        GatedReader([loud_frame()] * 6),
        FakeSegmenter(),
        NeverReturningTranscriber(),
        FakePlayer(),
        events,
        queue_size=1,
        shutdown_timeout=0.2,
    )

    runner = threading.Thread(target=p.run)
    runner.start()
    runner.join(timeout=5)

    assert not runner.is_alive(), "run() must not hang handing off the sentinel"
