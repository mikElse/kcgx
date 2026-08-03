"""One stereo output for every feed.

Replaces twelve independent PortAudio streams. That change is what makes a
relative bus gain, coordinated panning, and a *shared* reverb possible at
all -- and it is also the one place per-feed isolation could be lost, since
a device failure that used to cost one row now costs all audio. Every
failure path here is therefore written to degrade to silence-for-one rather
than silence-for-all.

Between a feed's ring buffer and the sum there is now nothing at all: the
gate and the compressor that used to sit there were removed on 2026-08-02.
An unmuted feed contributes exactly the samples its decoder wrote.
"""

from __future__ import annotations

import numpy as np

from squelch.dsp import (
    BLOCK,
    SAMPLE_RATE,
    Reverb,
    block_dbfs,
    pan_gains,
    pan_positions,
)
from squelch.ringbuffer import RingBuffer

AMBIENT_GAIN_DB = -8.0
AMBIENT_GAIN = 10 ** (AMBIENT_GAIN_DB / 20)
BUFFER_SECONDS = 0.5
SILENCE_FLOOR_DBFS = -96.0


class Channel:
    """One feed's slot in the mix.

    A pure conduit: samples enter the ring buffer and leave the mix at the
    value they were decoded at. There is nothing between the two -- no gate,
    no compressor -- so a channel has no signal-dependent state to go wrong.
    """

    def __init__(self, capacity: int) -> None:
        self.buffer = RingBuffer(capacity)
        # Plain attributes, read by the callback without synchronisation.
        # Rebinding a bool is atomic under CPython, and a change that takes
        # effect one block late is not observable.
        self.muted = True
        self.ambient = False
        self.level_dbfs = SILENCE_FLOOR_DBFS
        self._raw = np.zeros(BLOCK, dtype=np.float32)


class Mixer:
    def __init__(
        self,
        *,
        block: int = BLOCK,
        volume: float = 1.0,
        ambient_enabled: bool = True,
    ) -> None:
        self._block = block
        # Read by the callback without synchronisation, like `muted` and
        # `ambient`: rebinding a float is atomic under CPython and a gain
        # that lands one block late is not observable.
        self.volume = float(volume)
        self._ambient_enabled = bool(ambient_enabled)
        self._capacity = int(SAMPLE_RATE * BUFFER_SECONDS)
        self._channels: list[Channel] = []
        self._reverb = Reverb()
        self._stream = None
        self.failed = False
        # Every buffer the callback touches is allocated here, once.
        self._dry = np.zeros(block, dtype=np.float32)
        self._amb_l = np.zeros(block, dtype=np.float32)
        self._amb_r = np.zeros(block, dtype=np.float32)
        self._wet_l = np.zeros(block, dtype=np.float32)
        self._wet_r = np.zeros(block, dtype=np.float32)
        self._scratch = np.zeros(block, dtype=np.float32)
        self._positions: list[float] = []
        self._ambient: list[Channel] = []
        self._ambient_count = -1

    def add_channel(self) -> Channel:
        channel = Channel(self._capacity)
        self._channels.append(channel)
        return channel

    def set_ambient_enabled(self, enabled: bool) -> None:
        """Bypass the ambient bus: no panning, no reverb, no second sum."""
        self._ambient_enabled = bool(enabled)

    @property
    def ambient_enabled(self) -> bool:
        return self._ambient_enabled

    # -- rendering -----------------------------------------------------

    def render(self, out: np.ndarray) -> None:
        """Fill `out`, shaped (block, 2), with one block of the mix.

        Real-time context: allocates nothing, takes no lock, logs nothing,
        and cannot raise.
        """
        block = self._block
        dry = self._dry
        amb_l = self._amb_l
        amb_r = self._amb_r
        dry[:] = 0.0
        amb_l[:] = 0.0
        amb_r[:] = 0.0

        # Rebuilt in place, never as a new list: the callback allocates
        # nothing. Positions are recomputed only when the count changes.
        self._ambient.clear()
        for channel in self._channels:
            if channel.ambient:
                self._ambient.append(channel)
        if len(self._ambient) != self._ambient_count:
            self._ambient_count = len(self._ambient)
            self._positions = pan_positions(self._ambient_count)

        index = 0
        scratch = self._scratch[:block]
        for channel in self._channels:
            raw = channel._raw
            channel.buffer.read_into(raw)
            channel.level_dbfs = block_dbfs(raw)
            if not channel.muted:
                dry += raw
            if channel.ambient and self._ambient_enabled:
                position = (
                    self._positions[index] if index < len(self._positions) else 0.0
                )
                left, right = pan_gains(position)
                # Through the scratch buffer: `raw * scalar` would allocate
                # a temporary on every feed of every block.
                np.multiply(raw, left * AMBIENT_GAIN, out=scratch)
                amb_l += scratch
                np.multiply(raw, right * AMBIENT_GAIN, out=scratch)
                amb_r += scratch
                index += 1

        if self._ambient_enabled:
            try:
                self._reverb.process(amb_l, amb_r, self._wet_l, self._wet_r)
            except Exception:
                self._wet_l[:] = 0.0
                self._wet_r[:] = 0.0
            # 100% wet: the ambient bus contributes only its reverb.
            np.add(dry, self._wet_l, out=out[:block, 0])
            np.add(dry, self._wet_r, out=out[:block, 1])
        else:
            # Bypassed: the reverb is not run at all, rather than run and
            # added as silence. Its comb loops are the one part of this
            # callback that is not vectorised, so skipping them is most of
            # the mixer's cost.
            np.copyto(out[:block, 0], dry)
            np.copyto(out[:block, 1], dry)
        # Master volume, before the clip so turning it up cannot push the
        # sum past full scale. `out=` because the callback allocates nothing.
        np.multiply(out, self.volume, out=out)
        np.clip(out, -1.0, 1.0, out=out)

    # -- the device ----------------------------------------------------

    def start(self, *, stream_factory=None) -> None:
        """Open the output stream. A failure loses sound, not the pane."""
        if stream_factory is None:
            import sounddevice

            stream_factory = sounddevice.OutputStream
        try:
            self._stream = stream_factory(
                samplerate=SAMPLE_RATE,
                channels=2,
                dtype="float32",
                blocksize=self._block,
                callback=self._callback,
            )
            self._stream.start()
        except Exception:
            # Warned once by the caller. Every feed keeps decoding and
            # metering: this preserves the old per-session "no audio
            # device" behaviour, hoisted to one place.
            self._stream = None
            self.failed = True

    def _callback(self, outdata, frames, time_info, status) -> None:
        try:
            self.render(outdata)
        except Exception:
            outdata[:] = 0.0

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            # Shutdown must not raise: this runs in main()'s finally clause
            # and a PortAudio complaint here would mask whatever actually
            # brought the app down.
            pass
