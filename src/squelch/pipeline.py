"""Pump decoded audio from the reader to the speaker and the meter.

Runs entirely on the caller's thread. `Events` callbacks are
UI-marshalling shims (`__main__` wires them onto `app.call_from_thread`),
and a UI teardown race must never stop playback — every callback invocation
goes through `_emit`, which swallows exceptions from the callback itself.

The reader yields `bytes | None` (see `StreamReader.frames`): a `None` is a
heartbeat emitted while a reconnect backoff is being waited out. It means
"no audio this tick", not "silence" — it is reported as `reconnecting` and
never reaches the speaker.

One level tap leaves here: `on_activity`, the five-minute ranking's count,
fixed at 10 Hz and consumed on this thread — it is never marshalled to the
UI. It is measured **pre-compression** deliberately. Upward compression
exists to raise quiet signals, so ranking on a post-compression level would
push every feed toward the same number and destroy the ranking entirely.

There is no display tap. The meter shows what you *hear*, and compression
happens inside the mixer's callback, downstream of here — so the level the
meter draws is read from the mixer instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from squelch.audio import SILENCE_FLOOR_DBFS, rms_dbfs

# Activity is counted at a fixed 10 Hz regardless of what the meter is
# doing: it feeds a five-minute average, where more resolution buys nothing.
ACTIVITY_DECIMATION = 5


@dataclass
class Events:
    on_state: Callable[[str], None]
    # Defaulted so every existing construction site keeps working. A feed
    # whose activity nobody is counting is a legitimate configuration.
    on_activity: Callable[[float], None] = lambda _dbfs: None


class Pipeline:
    def __init__(self, reader, sink, events: Events) -> None:
        self._reader = reader
        self._sink = sink
        self._events = events
        self._stopped = False
        self._last_state = ""
        self._activity_count = 0
        self._activity_peak = SILENCE_FLOOR_DBFS

    def run(self) -> None:
        for frame in self._reader.frames():
            if self._stopped:
                break
            if frame is None:
                # No audio this tick: the reader is waiting out a reconnect
                # backoff and is only checking in so we can keep the pane
                # honest. Nothing may be written to the sink -- a `None` is
                # not silence, it is the absence of a sample -- but the
                # state must keep moving. Activity is deliberately not fed:
                # a heartbeat is the absence of a sample, not five minutes
                # of quiet.
                self._report_state("reconnecting")
                continue
            self._report_state("live")
            self._sink.write(frame)
            self._emit_activity(rms_dbfs(frame))

    def stop(self) -> None:
        self._stopped = True
        self._reader.stop()

    def _emit_activity(self, dbfs: float) -> None:
        self._activity_peak = max(self._activity_peak, dbfs)
        self._activity_count += 1
        if self._activity_count < ACTIVITY_DECIMATION:
            return
        peak = self._activity_peak
        self._activity_count = 0
        self._activity_peak = SILENCE_FLOOR_DBFS
        self._emit(self._events.on_activity, peak)

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
