"""Wire the stream, segmenter, and transcriber together.

Owns two threads: the caller's thread runs the audio loop, and a single
worker runs inference. Inference is deliberately not allowed to apply
backpressure to audio — if the model falls behind, work is dropped and the
gap is reported, because stale text presented as live is worse than a gap.

`Events` callbacks are UI-marshalling shims (Task 9 wires them onto
`app.call_from_thread`), and a UI teardown race must never kill audio
playback or the inference worker — every callback invocation is routed
through `_emit`, which swallows exceptions from the callback itself.
Shutdown is similarly bounded: the sentinel handoff to the worker never
blocks, so `run()` returns within `shutdown_timeout` even if the
transcriber never returns.

The reader yields `bytes | None` (see `StreamReader.frames`): a `None` is
a heartbeat emitted while a reconnect backoff is being waited out. It means
"no audio this tick", not "silence" -- it is reported as `reconnecting` and
reaches neither the speaker nor the segmenter.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from squelch.vad import SILENCE_FLOOR_DBFS, rms_dbfs

# Frames arrive every 20 ms (50 Hz). Marshalling a level onto the UI thread
# that often is both wasteful -- every call is a `call_from_thread` round
# trip billed to the *audio* thread -- and useless: the meter is a 20-sample
# window, so at 50 Hz it turns over two and a half times a second and reads
# as noise rather than a waveform. Emitting one reading per 5 frames gives
# 10 Hz, a two-second window, and a fifth of the marshalling cost. The
# reading emitted is the loudest of the group, so a short transient is
# still seen rather than being missed between samples.
LEVEL_DECIMATION = 5


@dataclass(frozen=True)
class Block:
    started_at: datetime
    text: str


@dataclass
class Events:
    on_level: Callable[[float], None]
    on_pending: Callable[[], None]
    on_block: Callable[[Block], None]
    on_state: Callable[[str], None]
    on_dropped: Callable[[], None]
    # A transcription that comes back blank still has to resolve the
    # "░ transcribing…" placeholder that on_pending put on screen. It is
    # deliberately *not* on_block with empty text (that would render an
    # empty transcript entry) and deliberately not on_dropped (nothing was
    # lost -- the model simply heard no words, which is routine for a
    # squelch click). Without it the placeholder is permanent, and
    # mark_pending's guard then suppresses every later utterance.
    on_blank: Callable[[], None]


_SENTINEL = object()


class Pipeline:
    def __init__(
        self,
        reader,
        segmenter,
        transcriber,
        player,
        events: Events,
        *,
        now: Callable[[], datetime] = datetime.now,
        queue_size: int = 8,
        shutdown_timeout: float = 30.0,
        level_every: int = LEVEL_DECIMATION,
    ) -> None:
        self._reader = reader
        self._segmenter = segmenter
        self._transcriber = transcriber
        self._player = player
        self._events = events
        self._now = now
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._stopped = False
        self._last_state = ""
        self._shutdown_timeout = shutdown_timeout
        self._level_every = max(1, level_every)
        self._level_count = 0
        self._level_peak = SILENCE_FLOOR_DBFS

    def run(self) -> None:
        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()
        try:
            for frame in self._reader.frames():
                if self._stopped:
                    break
                if frame is None:
                    # No audio this tick: the reader is waiting out a
                    # reconnect backoff and is only checking in so we can
                    # keep the pane honest. Nothing may be written to the
                    # speaker or fed to the segmenter -- a `None` is not
                    # silence, it is the absence of a sample -- but the
                    # state and the meter must both keep moving.
                    self._report_state("reconnecting")
                    self._emit_level(SILENCE_FLOOR_DBFS, force=True)
                    continue
                self._report_state("live")
                self._player.write(frame)
                self._emit_level(rms_dbfs(frame))
                utterance = self._segmenter.feed(frame)
                if utterance is not None:
                    self._emit(self._events.on_pending)
                    self._submit(utterance)
        finally:
            # Never block shutdown on a full queue: if the worker is wedged
            # inside transcribe() and never drains it, a plain blocking put
            # here would hang forever and worker.join below would never
            # even be reached. The worker is a daemon thread, so once the
            # join times out, run() returns regardless of whether the
            # worker itself has exited.
            self._enqueue_sentinel()
            worker.join(timeout=self._shutdown_timeout)

    def stop(self) -> None:
        self._stopped = True
        self._reader.stop()

    def _emit_level(self, dbfs: float, *, force: bool = False) -> None:
        """Peak-hold and decimate level readings -- see LEVEL_DECIMATION."""
        self._level_peak = max(self._level_peak, dbfs)
        self._level_count += 1
        if not force and self._level_count < self._level_every:
            return
        peak = self._level_peak
        self._level_count = 0
        self._level_peak = SILENCE_FLOOR_DBFS
        self._emit(self._events.on_level, peak)

    def _report_state(self, state: str) -> None:
        if state != self._last_state:
            self._last_state = state
            self._emit(self._events.on_state, state)

    def _emit(self, callback: Callable[..., None], *args) -> None:
        """Invoke an Events callback without letting it take down a thread.

        Events callbacks are UI-marshalling shims (Task 9 wires on_block to
        app.call_from_thread(...), which can raise while the UI is tearing
        down mid-quit). A flaky or torn-down UI must never stop audio
        playback or kill the inference worker. Swallowing is safe
        specifically because the callback does no pipeline work of its
        own -- if it fails, there is nobody left who needed to be told.
        """
        try:
            callback(*args)
        except Exception:
            pass

    def _enqueue_sentinel(self) -> None:
        """Put the shutdown sentinel without ever blocking.

        Same drop-oldest strategy as _submit, but unconditional: shutdown
        must complete even if the queue is full and the worker never
        drains it on its own.
        """
        while True:
            try:
                self._queue.put_nowait(_SENTINEL)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass

    def _submit(self, utterance) -> None:
        try:
            self._queue.put_nowait((self._now(), utterance))
        except queue.Full:
            evicted = True
            try:
                self._queue.get_nowait()  # drop oldest
            except queue.Empty:
                # The worker drained the slot between our failed put and
                # our eviction attempt -- nothing was actually lost, so
                # this must not be reported as a drop.
                evicted = False
            if evicted:
                self._emit(self._events.on_dropped)
            try:
                self._queue.put_nowait((self._now(), utterance))
            except queue.Full:
                pass

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                return
            started_at, utterance = item
            try:
                transcript = self._transcriber.transcribe(utterance.pcm)
            except Exception:
                # One bad inference must not kill the worker, but it must
                # not vanish either — a lost transmission is visible.
                self._emit(self._events.on_dropped)
                continue
            text = transcript.text.strip()
            if text:
                self._emit(
                    self._events.on_block,
                    Block(started_at=started_at, text=text),
                )
            else:
                # Blank result. on_pending already mounted a placeholder for
                # this utterance and only add_block/mark_dropped/mark_blank
                # take it back down -- staying quiet here strands it forever.
                self._emit(self._events.on_blank)
