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
# Measured against five minutes of live KPDX tower and ground on
# 2026-08-02 (tools/gate_tune.py). LiveATC squelches at the source: 87% of
# blocks sit at exactly -96 dBFS, digital silence, with a ~70 dB gap up to
# speech. There is no analog noise floor for the gate to reject, so the
# -40 this used to sit at was not protecting against anything -- it was
# sitting *inside* the range transmissions pass through, and re-triggering
# about once per transmission.
#
# Toggles per minute on tower, against a true transmission count of 5.8
# (measured at -70, below anything on the feed):
#
#     -40 single        12.2    110% spurious
#     -40/-46 hyst       9.0     55% spurious
#     -55 single         6.6     14% spurious
#
# Hence -55, and hence a single threshold: moving the gate out of the
# signal's way beats hysteresis at the wrong level. Open and close are
# deliberately equal, set on request; the gate ramp in `process` is what
# damps a crossing into a slew rather than a step, and is now the only
# thing doing so.
#
# The tradeoff this accepts: a feed carrying a genuine open-squelch noise
# floor above -55 dBFS would no longer be gated. None of KPDX's feeds do.
# If a future airport's does, raise this rather than reinstating the
# hysteresis -- the measurement above is what to re-run.
GATE_OPEN_DBFS = -55.0
GATE_CLOSE_DBFS = -55.0
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

    def set_gate(self, dbfs: float) -> None:
        """Move the gate threshold. Safe to call from another thread.

        Rebinding a float is atomic under CPython, and a threshold that
        takes effect one block late is not observable. Open and close move
        together: the hysteresis was removed deliberately (see
        GATE_OPEN_DBFS), so a single number is the whole control.
        """
        self._open_at = self._close_at = float(dbfs)

    @property
    def gate_dbfs(self) -> float:
        return self._open_at

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


# The centre feed is phase-inverted and attenuated 6 dB, so an odd number of
# ambient feeds does not pile a correlated signal up in the middle.
CENTRE_GAIN = 10 ** (-6.0 / 20)


def pan_positions(n: int) -> list[float]:
    """Positions for `n` ambient feeds, spread left to right across +/-0.5."""
    if n <= 0:
        return []
    half = n // 2
    if half == 0:
        # A single ambient feed. The formula below divides by `half`, so
        # this case is handled here rather than relied upon to fall out.
        return [0.0]
    step = 0.5 / half
    left = [-i * step for i in range(half, 0, -1)]
    right = [i * step for i in range(1, half + 1)]
    centre = [0.0] if n % 2 else []
    return left + centre + right


def pan_gains(position: float) -> tuple[float, float]:
    """Equal-power (-3 dB) gains for a position in [-0.5, 0.5]."""
    theta = (position + 1.0) * math.pi / 4.0
    left = math.cos(theta)
    right = math.sin(theta)
    if position == 0.0:
        return -left * CENTRE_GAIN, -right * CENTRE_GAIN
    return left, right


RT60_S = 0.100
LOWPASS_HZ = 1200.0

# Schroeder topology: four parallel combs into two series allpasses. An FDN
# buys nothing for a 100 ms tail. Every delay exceeds BLOCK so a block never
# feeds back into itself -- that constraint, not the classic Freeverb
# values, is what set these numbers.
COMB_DELAYS_L = (405, 431, 463, 492)
COMB_DELAYS_R = (413, 439, 471, 500)
# Right-channel delays differ from the left's, which is the whole source of
# stereo width here.
ALLPASS_DELAYS_L = (283, 347)
ALLPASS_DELAYS_R = (291, 355)
# 0.3, not the classic Schroeder 0.5. A diffuser normally uses a delay of a
# few milliseconds, where g=0.5 rings for far less than the reverb tail. The
# "every delay > BLOCK" rule forces these lines to at least 257 samples
# (16 ms), and at that length g=0.5 rings for ~100 ms on its own -- measured:
# the allpass pair alone decayed only 48 dB over 200 ms while the combs
# managed 123 dB, so the diffusers, not the combs, set the tail length. 0.3
# brings them inside the RT60 budget the combs are tuned to.
ALLPASS_FEEDBACK = 0.3


def comb_feedback(delay: int, rt60: float = RT60_S) -> float:
    """Feedback for a comb of `delay` samples to decay 60 dB in `rt60`."""
    return 10 ** (-3.0 * delay / (rt60 * SAMPLE_RATE))


def lowpass_coefficient(hz: float) -> float:
    """One-pole coefficient for a cutoff, at the engine's sample rate."""
    return math.exp(-2.0 * math.pi * hz / SAMPLE_RATE)


class _Comb:
    """A lowpass-damped feedback comb.

    Vectorised on the guarantee that `delay > BLOCK`: every sample this
    block needs from the delay line was written before the block started.
    """

    def __init__(self, delay: int, damping: float) -> None:
        self._line = np.zeros(delay, dtype=np.float32)
        self._delay = delay
        self._index = 0
        self._feedback = comb_feedback(delay)
        self._damping = damping
        self._store = 0.0
        self._scratch = np.zeros(BLOCK, dtype=np.float32)

    def process(self, block: np.ndarray, out: np.ndarray) -> None:
        n = len(block)
        read = self._index
        end = read + n
        if end <= self._delay:
            delayed = self._line[read:end]
        else:
            split = self._delay - read
            self._scratch[:split] = self._line[read:]
            self._scratch[split:n] = self._line[: end - self._delay]
            delayed = self._scratch[:n]
        np.copyto(out[:n], delayed)
        # One-pole damping on both the output and the feedback path.
        #
        # Freeverb damps only the feedback and emits the raw delayed sample,
        # which works because its feedback is ~0.84 and the filter compounds
        # over dozens of passes. At RT60 100 ms the feedback here is 0.17,
        # so a signal makes about four passes and feedback-only damping is
        # inaudible -- measured: 3 kHz came out no quieter than 400 Hz, so
        # the 1.2 kHz roll-off existed on paper only. Emitting the damped
        # value makes it a real one-pole lowpass on the tail, which is what
        # "presence without intelligibility" actually requires.
        damped = self._store
        for i in range(n):
            damped = (1.0 - self._damping) * out[i] + self._damping * damped
            out[i] = damped
            value = block[i] + self._feedback * damped
            self._line[(read + i) % self._delay] = value
        self._store = damped
        self._index = end % self._delay


class _Allpass:
    def __init__(self, delay: int) -> None:
        self._line = np.zeros(delay, dtype=np.float32)
        self._delay = delay
        self._index = 0

    def process(self, block: np.ndarray, out: np.ndarray) -> None:
        n = len(block)
        for i in range(n):
            slot = (self._index + i) % self._delay
            buffered = self._line[slot]
            value = block[i] + ALLPASS_FEEDBACK * buffered
            out[i] = buffered - ALLPASS_FEEDBACK * value
            self._line[slot] = value
        self._index = (self._index + n) % self._delay


class Reverb:
    """A short, dark, fully-wet room.

    100% wet by design: ambient feeds are heard only as reverb, never as
    direct signal. Combined with the 1.2 kHz roll-off and the 100 ms tail
    the result is presence without intelligibility, which is the point of
    the ambient bus.
    """

    def __init__(self) -> None:
        damping = lowpass_coefficient(LOWPASS_HZ)
        self._combs_l = [_Comb(d, damping) for d in COMB_DELAYS_L]
        self._combs_r = [_Comb(d, damping) for d in COMB_DELAYS_R]
        self._allpass_l = [_Allpass(d) for d in ALLPASS_DELAYS_L]
        self._allpass_r = [_Allpass(d) for d in ALLPASS_DELAYS_R]
        self._acc = np.zeros(BLOCK, dtype=np.float32)
        self._one = np.zeros(BLOCK, dtype=np.float32)

    def process(self, left, right, out_l, out_r) -> None:
        self._side(left, out_l, self._combs_l, self._allpass_l)
        self._side(right, out_r, self._combs_r, self._allpass_r)

    def _side(self, block, out, combs, allpasses) -> None:
        n = len(block)
        acc = self._acc[:n]
        one = self._one[:n]
        acc[:] = 0.0
        for comb in combs:
            comb.process(block, one)
            acc += one
        acc /= len(combs)
        for allpass in allpasses:
            allpass.process(acc, one)
            acc[:] = one
        np.copyto(out[:n], acc)
