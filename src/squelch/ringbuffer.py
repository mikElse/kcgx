"""One feed's buffer between its decoder thread and the audio callback.

Single producer, single consumer, no locks. The producer is paced by the
network and the consumer by the sound device, and they will not agree --
so the two failure directions are both handled here rather than anywhere
else: a starved read pads with silence, and an overfull write drops its
oldest samples. Both are bounded, per-feed, and inaudible, which is what
keeps one misbehaving feed from affecting the other eleven.
"""

from __future__ import annotations

import numpy as np


class RingBuffer:
    def __init__(self, capacity: int) -> None:
        self.capacity = int(capacity)
        self._data = np.zeros(self.capacity, dtype=np.float32)
        self._write = 0
        self._available = 0

    @property
    def available(self) -> int:
        return self._available

    def write(self, samples: np.ndarray) -> int:
        """Append `samples`, dropping the oldest on overflow.

        Returns how many samples were dropped. Dropping rather than blocking
        is deliberate: blocking here would push backpressure onto a decoder
        thread that also has to keep reporting connection state.
        """
        n = len(samples)
        if n >= self.capacity:
            # Only the newest capacity samples can survive.
            dropped = self._available + n - self.capacity
            self._data[:] = samples[-self.capacity :]
            self._write = 0
            self._available = self.capacity
            return max(0, dropped)

        end = self._write + n
        if end <= self.capacity:
            self._data[self._write : end] = samples
        else:
            split = self.capacity - self._write
            self._data[self._write :] = samples[:split]
            self._data[: end - self.capacity] = samples[split:]
        self._write = end % self.capacity

        dropped = max(0, self._available + n - self.capacity)
        self._available = min(self.capacity, self._available + n)
        return dropped

    def read_into(self, out: np.ndarray) -> int:
        """Fill `out` with the oldest samples, padding with silence.

        Writes in place -- the callback owns `out` and must not allocate.
        Returns how many real samples were delivered.
        """
        n = len(out)
        take = min(n, self._available)
        if take:
            start = (self._write - self._available) % self.capacity
            end = start + take
            if end <= self.capacity:
                out[:take] = self._data[start:end]
            else:
                split = self.capacity - start
                out[:split] = self._data[start:]
                out[split:take] = self._data[: end - self.capacity]
            self._available -= take
        if take < n:
            out[take:] = 0.0
        return take
