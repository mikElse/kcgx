"""Signal processing for the mixing engine.

Everything here is a pure function or a small stateful class over NumPy
arrays, deliberately: it is the only way to test a compressor's knee or a
reverb's decay without an audio device, and the callback that calls it is a
real-time context where nothing may allocate.

Gain is computed once per block and ramped across it rather than computed
per sample. At a 16 ms block that is inaudible for speech, and it is what
makes the whole chain vectorisable.
"""

from __future__ import annotations

import math

import numpy as np

SAMPLE_RATE = 16_000
# 16 ms. Chosen so that every reverb delay line is longer than one block:
# a delay shorter than the block feeds back into the block being computed,
# which cannot be vectorised.
BLOCK = 256
BLOCK_SECONDS = BLOCK / SAMPLE_RATE
SILENCE_FLOOR_DBFS = -96.0

THRESHOLD_DBFS = -12.0
RATIO = 4.0
KNEE_DB = 6.0
MAKEUP_DB = 6.0
# Without this, 4:1 upward compression below -12 dBFS boosts a -50 dBFS
# noise floor by ~28 dB and hiss becomes the loudest thing in the pane.
RANGE_LIMIT_DB = 12.0
GATE_OPEN_DBFS = -40.0
# Hysteresis: a signal hovering at the open point would otherwise chatter
# between 0 and 12 dB of boost, which is exactly what a squelch tail does.
GATE_CLOSE_DBFS = -46.0
ATTACK_S = 0.005
RELEASE_S = 0.150


def block_dbfs(block: np.ndarray) -> float:
    """RMS level of a block, floored."""
    if block.size == 0:
        return SILENCE_FLOOR_DBFS
    mean_square = float(np.dot(block, block) / block.size)
    if mean_square <= 0.0:
        return SILENCE_FLOOR_DBFS
    return max(SILENCE_FLOOR_DBFS, 10.0 * math.log10(mean_square))


def smoothing(tau_seconds: float, block_seconds: float = BLOCK_SECONDS) -> float:
    """One-pole coefficient for a time constant, at block rate."""
    if tau_seconds <= 0.0:
        return 0.0
    return math.exp(-block_seconds / tau_seconds)


def upward_gain_db(
    level_db: float,
    *,
    threshold: float = THRESHOLD_DBFS,
    ratio: float = RATIO,
    knee: float = KNEE_DB,
    range_limit: float = RANGE_LIMIT_DB,
) -> float:
    """How much to lift a signal sitting below the threshold.

    Soft knee: within +/- knee/2 of the threshold the curve is quadratic, so
    it meets the flat region and the sloped region without a step. A step
    here is audible as a click.
    """
    slope = 1.0 - 1.0 / ratio
    below = threshold - level_db
    half = knee / 2.0
    if below <= -half:
        gain = 0.0
    elif below >= half:
        gain = below * slope
    else:
        gain = slope * (below + half) ** 2 / (2.0 * knee)
    return min(gain, range_limit)


class Compressor:
    """Gate, then upward compression, then makeup.

    The gate scales the *boost*, never the signal: a gated feed is quiet
    rather than absent, and makeup still applies, so closing the gate cannot
    make a feed vanish mid-word.
    """

    def __init__(
        self,
        *,
        threshold: float = THRESHOLD_DBFS,
        ratio: float = RATIO,
        knee: float = KNEE_DB,
        makeup: float = MAKEUP_DB,
        range_limit: float = RANGE_LIMIT_DB,
        gate_open: float = GATE_OPEN_DBFS,
        gate_close: float = GATE_CLOSE_DBFS,
        attack: float = ATTACK_S,
        release: float = RELEASE_S,
    ) -> None:
        self._threshold = threshold
        self._ratio = ratio
        self._knee = knee
        self._makeup = makeup
        self._range = range_limit
        self._open_at = gate_open
        self._close_at = gate_close
        self._attack = smoothing(attack)
        self._release = smoothing(release)
        self._envelope = SILENCE_FLOOR_DBFS
        self._gate = 0.0
        self.gate_open = False
        self.gain_db = makeup
        self._applied = 10 ** (makeup / 20)
        # Preallocated: the callback may not allocate. `_unit` is a fixed
        # 0..1 ramp; `np.linspace` has no `out=` parameter, so the per-block
        # ramp is built by scaling this instead of generating a new one.
        self._unit = np.linspace(0.0, 1.0, BLOCK, dtype=np.float32)
        self._ramp = np.zeros(BLOCK, dtype=np.float32)

    def process(self, block: np.ndarray, out: np.ndarray) -> None:
        level = block_dbfs(block)
        # Attack when the signal rises, release when it falls -- the
        # asymmetry is what stops a compressor pumping on speech.
        coefficient = self._attack if level > self._envelope else self._release
        self._envelope = level + coefficient * (self._envelope - level)

        if self._envelope > self._open_at:
            self.gate_open = True
        elif self._envelope < self._close_at:
            self.gate_open = False
        target = 1.0 if self.gate_open else 0.0
        self._gate = target + self._release * (self._gate - target)

        boost = upward_gain_db(
            self._envelope,
            threshold=self._threshold,
            ratio=self._ratio,
            knee=self._knee,
            range_limit=self._range,
        )
        self.gain_db = boost * self._gate + self._makeup
        target_linear = 10 ** (self.gain_db / 20)

        # Ramp across the block rather than stepping at its boundary: a
        # step in gain between two blocks is a discontinuity, i.e. a click.
        n = len(block)
        ramp = self._ramp[:n]
        np.multiply(self._unit[:n], target_linear - self._applied, out=ramp)
        np.add(ramp, self._applied, out=ramp)
        np.multiply(block, ramp, out=out[:n])
        self._applied = target_linear
