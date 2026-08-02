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
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from squelch.vad import rms_dbfs


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

    def run(self) -> None:
        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()
        try:
            for frame in self._reader.frames():
                if self._stopped:
                    break
                self._player.write(frame)
                self._emit(self._events.on_level, rms_dbfs(frame))
                self._report_state(
                    "reconnecting" if self._reader.reconnecting else "live"
                )
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
            if transcript.text.strip():
                self._emit(
                    self._events.on_block,
                    Block(started_at=started_at, text=transcript.text.strip()),
                )
