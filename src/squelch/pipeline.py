"""Pump decoded audio from the reader to the speaker and the meter.

Runs entirely on the caller's thread. `Events` callbacks are
UI-marshalling shims (`__main__` wires them onto `app.call_from_thread`),
and a UI teardown race must never stop playback — every callback invocation
goes through `_emit`, which swallows exceptions from the callback itself.

The reader yields `bytes | None` (see `StreamReader.frames`): a `None` is a
heartbeat emitted while a reconnect backoff is being waited out. It means
"no audio this tick", not "silence" — it is reported as `reconnecting` and
never reaches the speaker.
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


@dataclass
class Events:
    on_level: Callable[[float], None]
    on_state: Callable[[str], None]


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
            self._emit_level(rms_dbfs(frame))

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
