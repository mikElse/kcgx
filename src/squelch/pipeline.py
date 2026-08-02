"""Pump decoded audio from the reader to the speaker and the meter.

Runs entirely on the caller's thread. `Events` callbacks are
UI-marshalling shims (`__main__` wires them onto `app.call_from_thread`),
and a UI teardown race must never stop playback — every callback invocation
goes through `_emit`, which swallows exceptions from the callback itself.

The reader yields `bytes | None` (see `StreamReader.frames`): a `None` is a
heartbeat emitted while a reconnect backoff is being waited out. It means
"no audio this tick", not "silence" — it is reported as `reconnecting` and
never reaches the speaker.

Two level taps leave here, not one. `on_level` is what the meter draws and
is decimated to whatever rate the row needs; `on_activity` is what the
five-minute ranking counts and is fixed at 10 Hz. They are separate because
the mixing engine compresses the audio between them — upward compression
exists to raise quiet signals, so ranking on a post-compression level would
push every feed toward the same number and destroy the ranking entirely.
`on_activity` is consumed on this thread and is never marshalled to the UI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from squelch.audio import SILENCE_FLOOR_DBFS, rms_dbfs

# Frames arrive every 20 ms (50 Hz). Marshalling a level onto the UI thread
# that often is both wasteful -- every call is a `call_from_thread` round
# trip billed to the *audio* thread -- and useless: the meter is a 20-sample
# window, so at 50 Hz it turns over two and a half times a second and reads
# as noise rather than a waveform. Emitting one reading per 5 frames gives
# 10 Hz, a two-second window, and a fifth of the marshalling cost. The
# reading emitted is the loudest of the group, so a short transient is
# still seen rather than being missed between samples.
LEVEL_DECIMATION = 5

# Activity is counted at a fixed 10 Hz regardless of what the meter is
# doing: it feeds a five-minute average, where more resolution buys nothing.
ACTIVITY_DECIMATION = 5


@dataclass
class Events:
    on_level: Callable[[float], None]
    on_state: Callable[[str], None]
    # Defaulted so every existing construction site keeps working. A feed
    # whose activity nobody is counting is a legitimate configuration.
    on_activity: Callable[[float], None] = lambda _dbfs: None


class Pipeline:
    def __init__(
        self,
        reader,
        player,
        events: Events,
        *,
        level_every: int = LEVEL_DECIMATION,
    ) -> None:
        self._reader = reader
        self._player = player
        self._events = events
        self._stopped = False
        self._last_state = ""
        self._level_every = max(1, level_every)
        self._level_count = 0
        self._level_peak = SILENCE_FLOOR_DBFS
        self._activity_count = 0
        self._activity_peak = SILENCE_FLOOR_DBFS

    def run(self) -> None:
        for frame in self._reader.frames():
            if self._stopped:
                break
            if frame is None:
                # No audio this tick: the reader is waiting out a reconnect
                # backoff and is only checking in so we can keep the pane
                # honest. Nothing may be written to the speaker -- a `None`
                # is not silence, it is the absence of a sample -- but the
                # state and the meter must both keep moving.
                self._report_state("reconnecting")
                self._emit_level(SILENCE_FLOOR_DBFS, force=True)
                continue
            self._report_state("live")
            self._player.write(frame)
            raw = rms_dbfs(frame)
            # Pre-compression, for the ranking. Post-compression, for the
            # meter. Identical until the mixing engine lands between them.
            self._emit_activity(raw)
            self._emit_level(raw)

    def stop(self) -> None:
        self._stopped = True
        self._reader.stop()

    def set_level_every(self, n: int) -> None:
        """Change the display rate. Safe to call from another thread.

        A compact row draws no meter, so it stops emitting display levels
        entirely; an expanded row wants more than the 10 Hz the ranking
        needs. Rebinding an int is atomic under CPython, and a rate that
        takes effect one frame late is not observable.
        """
        self._level_every = max(0, n)

    def _emit_activity(self, dbfs: float) -> None:
        self._activity_peak = max(self._activity_peak, dbfs)
        self._activity_count += 1
        if self._activity_count < ACTIVITY_DECIMATION:
            return
        peak = self._activity_peak
        self._activity_count = 0
        self._activity_peak = SILENCE_FLOOR_DBFS
        self._emit(self._events.on_activity, peak)

    def _emit_level(self, dbfs: float, *, force: bool = False) -> None:
        """Peak-hold and decimate level readings -- see LEVEL_DECIMATION."""
        if self._level_every == 0 and not force:
            # A compact row draws no meter; there is nobody to tell.
            return
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
        """Invoke an Events callback without letting it take down the loop.

        Events callbacks are UI-marshalling shims, and
        `app.call_from_thread(...)` can raise while the UI is tearing down
        mid-quit. Swallowing is safe specifically because the callback does
        no pipeline work of its own -- if it fails, there is nobody left who
        needed to be told.
        """
        try:
            callback(*args)
        except Exception:
            pass
