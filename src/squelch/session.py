"""One feed's runtime: reader, pipeline, mixer channel, and its thread.

Each feed is fully independent. Twelve feeds means twelve ffmpeg processes,
twelve PortAudio output streams, and twelve ways to fail — so a session that
cannot resolve its URL, or whose ffmpeg dies, must end up as a dead dot on
its own row and nothing more. It must never stall startup or interfere with
the other eleven, which is why every session owns its own thread and is
guarded end to end.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from squelch.activity import ActivityTracker

from squelch.audio import (
    FRAME_SAMPLES,
    SILENCE_FLOOR_DBFS,
    StreamReader,
    pcm_to_float,
)
from squelch.feeds import Feed, resolve_stream
from squelch.pipeline import Events, Pipeline

# Feed labels all start with the airport's ICAO ("KPDX Tower (Both)"), which
# is already in the global header. Stripping it buys five columns back for
# the name itself on a 48-column row.
def strip_icao(label: str, icao: str) -> str:
    prefix = f"{icao.upper()} "
    if label.upper().startswith(prefix):
        return label[len(prefix):]
    return label


@dataclass
class SessionEvents:
    """Callbacks carrying the session that produced them.

    The UI has one row per session, so every signal has to say which row it
    belongs to. Kept separate from `pipeline.Events`, which is per-feed and
    knows nothing about there being more than one.
    """

    on_state: Callable[["FeedSession", str], None]
    on_warn: Callable[["FeedSession", str], None]


class FeedSession:
    """Everything needed to stream, play, and meter one feed."""

    def __init__(
        self,
        feed: Feed,
        events: SessionEvents,
        *,
        muted: bool = True,
        icao: str = "",
        activity_threshold: float = -40.0,
        resolve: Callable[[str], str] = resolve_stream,
        reader_factory: Callable[..., Any] = StreamReader,
        channel: Any = None,
        pipeline_factory: Callable[..., Any] = Pipeline,
    ) -> None:
        self.feed = feed
        self.name = strip_icao(feed.label, icao) if icao else feed.label
        self.events = events
        self.state = "starting"
        self._activity = ActivityTracker(activity_threshold)
        self._channel = channel
        self._muted = bool(muted)
        self._ambient = False
        if channel is not None:
            channel.muted = self._muted
        # Preallocated: filled once per frame on this feed's thread.
        self._staging = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        self._resolve = resolve
        self._reader_factory = reader_factory
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any = None
        self._reader: Any = None
        self._thread: threading.Thread | None = None
        # A session is started and parked repeatedly as stream slots move
        # between feeds (see slots.py), and a parked feed's thread can still
        # be inside resolve() or unwinding its pipeline when the next start
        # comes. Each start is a new generation; anything a stale one tries
        # to do -- install a pipeline, report a state -- is dropped, so a
        # feed parked a moment ago cannot reappear as "offline", or worse,
        # quietly open a second stream.
        self._lock = threading.Lock()
        self._generation = 0
        self._connected = False

    # -- audio ---------------------------------------------------------

    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool) -> None:
        # Gated at the mixer's bus routing, so the stream, the reader, and
        # the activity count all keep running -- muting silences a feed
        # without making it stop being watched.
        self._muted = bool(value)
        if self._channel is not None:
            self._channel.muted = self._muted

    @property
    def ambient(self) -> bool:
        return self._ambient

    @property
    def level(self) -> float:
        """Post-compression, read from the mixer.

        The meter shows what you hear, and compression happens inside the
        audio callback -- so this cannot come from the pipeline, which sees
        the frame before any of it.
        """
        if self._channel is None:
            return SILENCE_FLOOR_DBFS
        return self._channel.level_dbfs

    def write(self, pcm: bytes) -> None:
        """Sink for the pipeline: decode into the channel's ring buffer."""
        if self._channel is None:
            return
        count = pcm_to_float(pcm, self._staging)
        if count:
            self._channel.buffer.write(self._staging[:count])

    @property
    def activity(self) -> float:
        return self._activity.fraction()

    def _on_activity(self, dbfs: float) -> None:
        # Stays on this thread: the tracker is arithmetic, and marshalling a
        # 10 Hz reading per feed onto the UI thread would cost more than the
        # ranking is worth.
        self._activity.push(dbfs)

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self) -> bool:
        self._ambient = not self._ambient
        if self._channel is not None:
            self._channel.ambient = self._ambient
        return self._ambient

    # -- lifecycle -----------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether this feed holds one of the stream slots.

        True from start() to park() or stop(), whatever the stream itself is
        doing -- a feed that is reconnecting still holds its slot.
        """
        return self._connected

    def start(self) -> None:
        with self._lock:
            if self._connected:
                return
            self._connected = True
            self._generation += 1
            generation = self._generation
        self._thread = threading.Thread(
            target=self.run, args=(generation,), daemon=True
        )
        self._thread.start()

    def park(self) -> None:
        """Give up the stream slot, and say so on the row."""
        self._disconnect()
        self._set_state("parked")

    def run(self, generation: int | None = None) -> None:
        if generation is None:
            generation = self._generation
        try:
            self._run(generation)
        except Exception as exc:
            # A daemon thread that dies with an unhandled exception prints
            # nothing and leaves this feed's row frozen at whatever it last
            # said. One feed's failure is its own business, but it has to be
            # visible as such.
            self._fail(f"{type(exc).__name__}: {exc}", generation)

    def _run(self, generation: int) -> None:
        try:
            url = self._resolve(self.feed.ident)
        except Exception:
            self._fail("could not resolve feed", generation)
            return

        reader = self._reader_factory(url)
        pipeline = self._pipeline_factory(
            reader,
            # This session is the sink: the pipeline hands it frames and it
            # decodes them into the mixer channel's ring buffer.
            self,
            Events(
                on_state=lambda state: self._set_state(state, generation),
                on_activity=self._on_activity,
            ),
        )
        with self._lock:
            # Parked or stopped while resolve() was in flight. The reader
            # has not spawned ffmpeg yet -- that happens on its first read --
            # so dropping both here opens nothing.
            if generation != self._generation:
                return
            self._reader = reader
            self._pipeline = pipeline
        pipeline.run()
        # run() only returns when the reader stops, which for a live feed
        # means we asked it to.
        self._set_state("offline", generation)

    def stop(self) -> None:
        self._disconnect()

    def _disconnect(self) -> None:
        with self._lock:
            self._connected = False
            self._generation += 1
            pipeline, self._pipeline = self._pipeline, None
            self._reader = None
        if pipeline is not None:
            try:
                pipeline.stop()
            except Exception:
                pass

    # -- state ---------------------------------------------------------

    def _set_state(self, state: str, generation: int | None = None) -> None:
        if generation is not None and generation != self._generation:
            return
        self.state = state
        self.events.on_state(self, state)

    def _fail(self, message: str, generation: int | None = None) -> None:
        if generation is not None and generation != self._generation:
            return
        self._set_state("offline")
        self.events.on_warn(self, message)
