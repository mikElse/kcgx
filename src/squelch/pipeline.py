"""Wire the stream, segmenter, and transcriber together.

Owns two threads: the caller's thread runs the audio loop, and a single
worker runs inference. Inference is deliberately not allowed to apply
backpressure to audio — if the model falls behind, work is dropped and the
gap is reported, because stale text presented as live is worse than a gap.
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

    def run(self) -> None:
        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()
        try:
            for frame in self._reader.frames():
                if self._stopped:
                    break
                self._player.write(frame)
                self._events.on_level(rms_dbfs(frame))
                self._report_state(
                    "reconnecting" if self._reader.reconnecting else "live"
                )
                utterance = self._segmenter.feed(frame)
                if utterance is not None:
                    self._events.on_pending()
                    self._submit(utterance)
        finally:
            self._queue.put(_SENTINEL)
            worker.join(timeout=30)

    def stop(self) -> None:
        self._stopped = True
        self._reader.stop()

    def _report_state(self, state: str) -> None:
        if state != self._last_state:
            self._last_state = state
            self._events.on_state(state)

    def _submit(self, utterance) -> None:
        try:
            self._queue.put_nowait((self._now(), utterance))
        except queue.Full:
            try:
                self._queue.get_nowait()  # drop oldest
            except queue.Empty:
                pass
            self._events.on_dropped()
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
                self._events.on_dropped()
                continue
            if transcript.text.strip():
                self._events.on_block(
                    Block(started_at=started_at, text=transcript.text.strip())
                )
