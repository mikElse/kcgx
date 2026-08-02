# Audio Pane D — Mixing Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace twelve independent mono output streams with one stereo mixing engine: per-feed ring buffers, upward compression, a dry bus and a panned ambient bus, and a shared reverb.

**Architecture:** Each feed's existing thread writes decoded PCM into its own ring buffer. One `sounddevice` callback pulls a block from every buffer, applies gate → compressor per feed, sums the dry and ambient buses, runs the ambient sum through a shared Schroeder reverb, and writes stereo. All DSP is pure NumPy over preallocated buffers, so it is tested offline with no audio device.

**Tech Stack:** Python 3.14, NumPy (new dependency), `sounddevice` 0.5.5 in callback mode, pytest 9.1.1.

**Spec:** `docs/superpowers/specs/2026-08-02-audio-mixer-design.md`

**Depends on:** plan A (supplies `session.ambient`). Independent of plans B and C, but see "Supersedes" below.

## Supersedes part of plan B

Plan B routes the **display** level through `Pipeline.on_level` and `Pipeline.set_level_every`. That tap measures the frame *before* compression, and the whole point of the split is that the meter should show what you hear. Once the mixer exists, compression happens inside the callback, so the display level must come from there.

This plan therefore moves display levels to a **polled read**: the mixer stores a per-feed post-compression peak, and the UI polls it at 25 Hz. `Pipeline.on_level` and `set_level_every` are deleted. `Pipeline.on_activity` is unchanged and still measures pre-compression — that is exactly what plan B specified, and it survives intact.

If plan B has not been built, skip Task 10's deletions and wire the polled read directly.

## Global Constraints

- Sample rate **16 kHz**, block size **256 samples (16 ms)**, **2 output channels**, `float32` internally.
- **Every reverb delay line must be longer than the block size.** A delay shorter than a block feeds back into the block being computed and cannot be vectorised. This is why the block is 256 and not 512.
- Ring buffers hold **500 ms (8000 samples)** per feed. Overflow **drops the oldest** block.
- Compressor: threshold **−12 dBFS**, ratio **4:1**, knee **6 dB** soft, makeup **+6 dB**, range limit **12 dB**, attack **5 ms**, release **150 ms**.
- Gate: opens at **−40 dBFS**, closes at **−46 dBFS**, ramped on the release constant. It attenuates the **upward boost only**, never the signal.
- Ambient bus: **−8 dB** relative to dry, reverb **100 % wet**, **RT60 100 ms**, feedback low-pass at **1.2 kHz**.
- Panning: equal-power (−3 dB) law, positions spread across **±0.5**. Odd counts put one feed at centre, **phase-inverted and −6 dB**. Guard the division when `⌊N/2⌋` is 0.
- **The callback is a real-time context.** No allocation, no locks, no logging, no raising. All buffers preallocated; NumPy ops use `out=`.
- A feed may be on the dry bus, the ambient bus, **both**, or neither. `[ON]` and `[A]` are independent toggles.
- `dsp.py`, `ringbuffer.py`, `mixer.py`, `audio.py`, `session.py` **must not import `textual`**.
- No test may open an audio device. `sounddevice` is imported lazily and injected in tests.
- Run tests with `uv run pytest`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/squelch/ringbuffer.py` | **New.** SPSC ring buffer, drop-oldest overflow |
| `src/squelch/dsp.py` | **New.** Envelope, gate, upward compressor, panner, reverb |
| `src/squelch/mixer.py` | **New.** Per-feed channels, bus summing, the callback, the output stream |
| `src/squelch/audio.py` | `Player` deleted; `StreamReader` unchanged |
| `src/squelch/session.py` | Owns a ring buffer, registers a channel with the mixer |
| `src/squelch/pipeline.py` | Writes to the buffer; display tap removed |
| `src/squelch/app.py` | Polls per-feed levels from the mixer |
| `src/squelch/config.py` | Compressor, ambient, and reverb parameters |
| `tests/test_ringbuffer.py`, `tests/test_dsp.py`, `tests/test_mixer.py` | **New.** |

---

### Task 1: The ring buffer

**Files:**
- Modify: `pyproject.toml`
- Create: `src/squelch/ringbuffer.py`
- Create: `tests/test_ringbuffer.py`

**Interfaces:**
- Consumes: nothing.
- Produces: class `RingBuffer(capacity: int)` with `write(samples: np.ndarray) -> int` (returns samples dropped), `read_into(out: np.ndarray) -> int` (returns samples actually delivered; fills the remainder with zeros), `available: int`, `capacity: int`.

- [ ] **Step 1: Add NumPy**

```bash
uv add numpy
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_ringbuffer.py`:

```python
"""The per-feed buffer between a network-paced writer and a device-paced
reader.

Twelve ffmpeg processes decode twelve independent streams with no common
clock. Reconciling them against one 16 kHz consumer is this class's entire
job, so the interesting cases are starvation and overflow, not the happy
path.
"""

import numpy as np

from squelch.ringbuffer import RingBuffer


def block(value, n):
    return np.full(n, value, dtype=np.float32)


def test_a_fresh_buffer_is_empty():
    assert RingBuffer(100).available == 0


def test_written_samples_come_back_in_order():
    buf = RingBuffer(100)
    buf.write(np.arange(8, dtype=np.float32))
    out = np.zeros(8, dtype=np.float32)
    assert buf.read_into(out) == 8
    assert np.array_equal(out, np.arange(8, dtype=np.float32))


def test_reading_more_than_written_pads_with_silence():
    """A starved feed contributes silence for the block, nothing more."""
    buf = RingBuffer(100)
    buf.write(block(1.0, 4))
    out = np.full(8, 9.0, dtype=np.float32)
    assert buf.read_into(out) == 4
    assert np.array_equal(out[:4], block(1.0, 4))
    assert np.array_equal(out[4:], np.zeros(4, dtype=np.float32))


def test_reading_an_empty_buffer_yields_pure_silence():
    buf = RingBuffer(100)
    out = np.full(8, 9.0, dtype=np.float32)
    assert buf.read_into(out) == 0
    assert not out.any()


def test_reading_consumes():
    buf = RingBuffer(100)
    buf.write(block(1.0, 8))
    out = np.zeros(4, dtype=np.float32)
    buf.read_into(out)
    assert buf.available == 4


def test_writing_past_capacity_drops_the_oldest():
    buf = RingBuffer(8)
    buf.write(np.arange(8, dtype=np.float32))
    dropped = buf.write(np.arange(100, 104, dtype=np.float32))
    assert dropped == 4
    out = np.zeros(8, dtype=np.float32)
    buf.read_into(out)
    assert np.array_equal(out[-4:], np.arange(100, 104, dtype=np.float32))
    assert np.array_equal(out[:4], np.arange(4, 8, dtype=np.float32))


def test_available_never_exceeds_capacity():
    buf = RingBuffer(8)
    for _ in range(10):
        buf.write(block(1.0, 8))
    assert buf.available == 8


def test_a_write_larger_than_capacity_keeps_only_the_newest():
    buf = RingBuffer(4)
    buf.write(np.arange(10, dtype=np.float32))
    out = np.zeros(4, dtype=np.float32)
    buf.read_into(out)
    assert np.array_equal(out, np.arange(6, 10, dtype=np.float32))


def test_wrapping_preserves_order():
    buf = RingBuffer(8)
    out = np.zeros(6, dtype=np.float32)
    buf.write(np.arange(6, dtype=np.float32))
    buf.read_into(out)
    buf.write(np.arange(10, 16, dtype=np.float32))
    buf.read_into(out)
    assert np.array_equal(out, np.arange(10, 16, dtype=np.float32))


def test_read_into_does_not_allocate_a_new_array():
    buf = RingBuffer(100)
    buf.write(block(1.0, 8))
    out = np.zeros(8, dtype=np.float32)
    before = out.__array_interface__["data"][0]
    buf.read_into(out)
    assert out.__array_interface__["data"][0] == before
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_ringbuffer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'squelch.ringbuffer'`.

- [ ] **Step 4: Implement**

Create `src/squelch/ringbuffer.py`:

```python
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
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_ringbuffer.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/squelch/ringbuffer.py tests/test_ringbuffer.py
git commit -m "feat(squelch): add the per-feed audio ring buffer"
```

---

### Task 2: Envelope, gate, and the upward compressor

**Files:**
- Create: `src/squelch/dsp.py`
- Create: `tests/test_dsp.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SAMPLE_RATE = 16_000`, `BLOCK = 256`, `SILENCE_FLOOR_DBFS = -96.0`
  - `block_dbfs(block: np.ndarray) -> float`
  - `smoothing(tau_seconds: float, block_seconds: float) -> float`
  - `upward_gain_db(level_db, *, threshold=-12.0, ratio=4.0, knee=6.0, range_limit=12.0) -> float`
  - class `Compressor(...)` with `process(block: np.ndarray, out: np.ndarray) -> None` and read-only `gain_db`, `gate_open`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dsp.py`:

```python
"""The signal processing, as arithmetic.

None of this opens an audio device. The compressor's range limit and gate
are the important parts: without them, 4:1 upward compression below -12 dBFS
boosts a -50 dBFS noise floor by ~28 dB and hiss becomes the loudest thing
in the pane.
"""

import math

import numpy as np

from squelch.dsp import (
    BLOCK,
    SAMPLE_RATE,
    Compressor,
    block_dbfs,
    smoothing,
    upward_gain_db,
)

BLOCK_SECONDS = BLOCK / SAMPLE_RATE


def tone(dbfs, n=BLOCK):
    """A constant-amplitude block at a given level."""
    amplitude = 10 ** (dbfs / 20)
    return np.full(n, amplitude, dtype=np.float32)


# -- level -----------------------------------------------------------------


def test_full_scale_is_zero_dbfs():
    assert block_dbfs(tone(0.0)) == pytest.approx(0.0, abs=0.01)


def test_a_known_level_round_trips():
    assert block_dbfs(tone(-20.0)) == pytest.approx(-20.0, abs=0.01)


def test_digital_silence_is_the_floor():
    assert block_dbfs(np.zeros(BLOCK, dtype=np.float32)) == -96.0


# -- the static curve ------------------------------------------------------


def test_nothing_above_the_threshold_is_boosted():
    assert upward_gain_db(0.0) == 0.0
    assert upward_gain_db(-5.0) == 0.0


def test_below_the_knee_the_ratio_applies():
    """(threshold - level) * (1 - 1/ratio), so -20 gets 8 * 0.75 = 6 dB."""
    assert upward_gain_db(-20.0) == pytest.approx(6.0, abs=0.01)


def test_the_range_limit_caps_the_boost():
    assert upward_gain_db(-40.0) == 12.0
    assert upward_gain_db(-80.0) == 12.0


def test_the_range_limit_saturates_at_minus_28():
    """(−12 − −28) × 0.75 = 12, exactly the limit."""
    assert upward_gain_db(-28.0) == pytest.approx(12.0, abs=0.01)


def test_without_the_limit_a_noise_floor_would_run_away():
    """The reason the limit exists, pinned so nobody removes it."""
    unlimited = upward_gain_db(-50.0, range_limit=math.inf)
    assert unlimited == pytest.approx(28.5, abs=0.1)
    assert upward_gain_db(-50.0) == 12.0


def test_the_knee_is_continuous_at_its_lower_edge():
    """A step in the gain curve is audible as a click."""
    assert abs(upward_gain_db(-15.001) - upward_gain_db(-15.0)) < 0.01


def test_the_knee_is_continuous_at_its_upper_edge():
    assert abs(upward_gain_db(-9.001) - upward_gain_db(-9.0)) < 0.01


def test_the_knee_eases_in_above_the_threshold():
    """A soft knee starts lifting before the threshold instead of
    cornering at it. A hard knee would give exactly 0 here."""
    assert upward_gain_db(-10.0) > 0.0
    assert upward_gain_db(-9.0) == 0.0


def test_the_curve_is_monotonic():
    levels = np.linspace(-90.0, 0.0, 200)
    gains = [upward_gain_db(float(x)) for x in levels]
    assert all(a >= b for a, b in zip(gains, gains[1:])), "quieter must never gain less"


# -- smoothing -------------------------------------------------------------


def test_a_short_time_constant_is_nearly_instant():
    """5 ms against a 16 ms block: attack lands inside one block."""
    assert smoothing(0.005, BLOCK_SECONDS) < 0.05


def test_a_long_time_constant_retains_most_of_the_previous_value():
    assert 0.85 < smoothing(0.150, BLOCK_SECONDS) < 0.95


# -- the compressor --------------------------------------------------------


def run_blocks(comp, level, count):
    out = np.zeros(BLOCK, dtype=np.float32)
    for _ in range(count):
        comp.process(tone(level), out)
    return out


def test_makeup_gain_applies_above_the_threshold():
    comp = Compressor()
    out = run_blocks(comp, -6.0, 20)
    assert block_dbfs(out) == pytest.approx(0.0, abs=0.2), "-6 plus 6 dB makeup"


def test_a_quiet_signal_is_lifted_by_the_limit_plus_makeup():
    comp = Compressor()
    out = run_blocks(comp, -35.0, 40)
    assert block_dbfs(out) == pytest.approx(-35.0 + 12.0 + 6.0, abs=0.3)


def test_the_gate_closes_on_the_noise_floor():
    comp = Compressor()
    out = run_blocks(comp, -60.0, 60)
    assert comp.gate_open is False
    assert block_dbfs(out) == pytest.approx(-60.0 + 6.0, abs=0.3), (
        "makeup still applies; the boost does not"
    )


def test_the_gate_opens_above_its_threshold():
    comp = Compressor()
    run_blocks(comp, -20.0, 20)
    assert comp.gate_open is True


def test_the_gate_has_hysteresis():
    """A signal hovering at -40 must not chatter."""
    comp = Compressor()
    run_blocks(comp, -20.0, 20)
    assert comp.gate_open is True
    run_blocks(comp, -42.0, 5)
    assert comp.gate_open is True, "between the open and close points it holds"
    run_blocks(comp, -50.0, 30)
    assert comp.gate_open is False, "below the close point it eventually shuts"


def test_the_gate_ramps_rather_than_steps():
    """A hard gate steps 12 dB at the threshold and chatters audibly."""
    comp = Compressor()
    run_blocks(comp, -60.0, 40)
    quiet_gain = comp.gain_db
    out = np.zeros(BLOCK, dtype=np.float32)
    comp.process(tone(-20.0), out)
    assert comp.gain_db - quiet_gain < 12.0, "one block cannot jump the whole range"


def test_release_is_gradual_not_a_step():
    """Gain must not jump to its new target in one block.

    Asserted as a shape rather than a precise fraction: gain is a
    non-linear function of the envelope (it is flat above the threshold and
    clamped at the range limit), so the envelope's time constant does not
    map proportionally onto gain travel.
    """
    comp = Compressor()
    run_blocks(comp, -6.0, 20)
    loud = comp.gain_db
    run_blocks(comp, -22.0, 1)
    after_one = comp.gain_db
    run_blocks(comp, -22.0, 8)
    after_nine = comp.gain_db
    assert loud <= after_one < after_nine
    assert after_nine < 13.5, "still travelling toward the target"


def test_release_eventually_reaches_its_target():
    comp = Compressor()
    run_blocks(comp, -6.0, 20)
    run_blocks(comp, -22.0, 200)
    # (-12 - -22) * 0.75 = 7.5 of boost, plus 6 dB makeup.
    assert comp.gain_db == pytest.approx(13.5, abs=0.1)


def test_attack_is_fast():
    comp = Compressor()
    run_blocks(comp, -35.0, 40)
    out = np.zeros(BLOCK, dtype=np.float32)
    comp.process(tone(-6.0), out)
    assert comp.gain_db < 8.0, "a loud block must be caught within one block"


def test_process_writes_in_place():
    comp = Compressor()
    out = np.zeros(BLOCK, dtype=np.float32)
    before = out.__array_interface__["data"][0]
    comp.process(tone(-20.0), out)
    assert out.__array_interface__["data"][0] == before


def test_silence_stays_silent():
    comp = Compressor()
    out = np.zeros(BLOCK, dtype=np.float32)
    comp.process(np.zeros(BLOCK, dtype=np.float32), out)
    assert not out.any()
```

Add `import pytest` at the top of the file.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_dsp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'squelch.dsp'`.

- [ ] **Step 3: Implement**

Create `src/squelch/dsp.py`:

```python
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
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_dsp.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/dsp.py tests/test_dsp.py
git commit -m "feat(squelch): add the gated upward compressor"
```

---

### Task 3: The panner

**Files:**
- Modify: `src/squelch/dsp.py`
- Modify: `tests/test_dsp.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `pan_positions(n: int) -> list[float]` — left to right across ±0.5
  - `pan_gains(position: float) -> tuple[float, float]` — equal-power L, R, with the centre inverted and −6 dB

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dsp.py`:

```python
from squelch.dsp import pan_gains, pan_positions


def test_no_ambient_feeds_means_no_positions():
    assert pan_positions(0) == []


def test_a_single_feed_sits_in_the_centre():
    """Guards the division by floor(N/2), which is zero here."""
    assert pan_positions(1) == [0.0]


def test_two_feeds_go_hard_to_each_side():
    assert pan_positions(2) == [-0.5, 0.5]


def test_four_feeds_reproduce_the_specified_spread():
    """50%L, 25%L, 25%R, 50%R."""
    assert pan_positions(4) == [-0.5, -0.25, 0.25, 0.5]


def test_an_odd_count_puts_one_feed_in_the_centre():
    assert pan_positions(3) == [-0.5, 0.0, 0.5]
    assert pan_positions(5) == [-0.5, -0.25, 0.0, 0.25, 0.5]


def test_six_feeds_spread_evenly():
    positions = pan_positions(6)
    assert positions[0] == -0.5 and positions[-1] == 0.5
    assert len(positions) == 6
    assert positions == sorted(positions)


def test_positions_never_exceed_half():
    for n in range(1, 13):
        assert all(-0.5 <= p <= 0.5 for p in pan_positions(n))


def test_positions_are_symmetric():
    for n in range(1, 13):
        positions = pan_positions(n)
        assert positions == [-p for p in reversed(positions)]


def test_panning_is_equal_power():
    for position in (-0.5, -0.25, 0.25, 0.5):
        left, right = pan_gains(position)
        assert left**2 + right**2 == pytest.approx(1.0, abs=1e-6)


def test_hard_left_favours_the_left():
    left, right = pan_gains(-0.5)
    assert left > right


def test_hard_right_favours_the_right():
    left, right = pan_gains(0.5)
    assert right > left


def test_the_centre_is_inverted_and_attenuated():
    left, right = pan_gains(0.0)
    assert left < 0 and right < 0, "phase inverted"
    assert left == pytest.approx(right)
    magnitude = math.sqrt(left**2 + right**2)
    assert 20 * math.log10(magnitude) == pytest.approx(-6.0, abs=0.01)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_dsp.py -k pan -v`
Expected: FAIL with `ImportError: cannot import name 'pan_positions'`.

- [ ] **Step 3: Implement**

Append to `src/squelch/dsp.py`:

```python
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
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_dsp.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/dsp.py tests/test_dsp.py
git commit -m "feat(squelch): add equal-power panning for the ambient bus"
```

---

### Task 4: The reverb

**Files:**
- Modify: `src/squelch/dsp.py`
- Modify: `tests/test_dsp.py`

**Interfaces:**
- Consumes: `BLOCK`, `SAMPLE_RATE`.
- Produces:
  - `RT60_S = 0.100`, `LOWPASS_HZ = 1200.0`
  - `COMB_DELAYS_L`, `COMB_DELAYS_R`, `ALLPASS_DELAYS_L`, `ALLPASS_DELAYS_R`
  - `comb_feedback(delay: int, rt60: float = RT60_S) -> float`
  - `lowpass_coefficient(hz: float) -> float`
  - class `Reverb()` with `process(left: np.ndarray, right: np.ndarray, out_l: np.ndarray, out_r: np.ndarray) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dsp.py`:

```python
from squelch.dsp import (
    ALLPASS_DELAYS_L,
    ALLPASS_DELAYS_R,
    COMB_DELAYS_L,
    COMB_DELAYS_R,
    LOWPASS_HZ,
    RT60_S,
    Reverb,
    comb_feedback,
    lowpass_coefficient,
)


def impulse_response(blocks=40):
    """Feed one impulse and collect the stereo tail."""
    reverb = Reverb()
    left = np.zeros(BLOCK, dtype=np.float32)
    right = np.zeros(BLOCK, dtype=np.float32)
    out_l = np.zeros(BLOCK, dtype=np.float32)
    out_r = np.zeros(BLOCK, dtype=np.float32)
    tail_l, tail_r = [], []
    left[0] = right[0] = 1.0
    for index in range(blocks):
        reverb.process(left, right, out_l, out_r)
        tail_l.append(out_l.copy())
        tail_r.append(out_r.copy())
        if index == 0:
            left[0] = right[0] = 0.0
    return np.concatenate(tail_l), np.concatenate(tail_r)


def test_every_delay_line_is_longer_than_a_block():
    """A delay shorter than the block feeds back into the block being
    computed, which cannot be vectorised."""
    for delays in (COMB_DELAYS_L, COMB_DELAYS_R, ALLPASS_DELAYS_L, ALLPASS_DELAYS_R):
        assert min(delays) > BLOCK, delays


def test_comb_feedback_matches_the_decay_formula():
    assert comb_feedback(1600) == pytest.approx(10 ** -3.0, rel=1e-6)


def test_a_shorter_delay_needs_more_feedback():
    assert comb_feedback(400) > comb_feedback(800)


def test_the_lowpass_coefficient_matches_the_cutoff():
    expected = math.exp(-2 * math.pi * LOWPASS_HZ / SAMPLE_RATE)
    assert lowpass_coefficient(LOWPASS_HZ) == pytest.approx(expected)
    assert 0.6 < lowpass_coefficient(1200.0) < 0.65


def test_the_tail_decays_sixty_db_in_about_a_hundred_milliseconds():
    tail, _ = impulse_response()
    window = int(RT60_S * SAMPLE_RATE)
    early = float(np.abs(tail[:window]).max())
    late = float(np.abs(tail[window * 2 : window * 3]).max())
    assert early > 0.0
    decay_db = 20 * math.log10(max(late, 1e-12) / early)
    assert decay_db < -50.0, f"tail is too long: {decay_db:.1f} dB"


def test_the_tail_is_not_instantaneous():
    """A reverb that dies inside one block is not a reverb."""
    tail, _ = impulse_response()
    assert float(np.abs(tail[BLOCK : BLOCK * 3]).max()) > 1e-4


def test_energy_above_the_cutoff_is_attenuated():
    t = np.arange(BLOCK * 20, dtype=np.float32) / SAMPLE_RATE

    def energy(hz):
        """Total output energy for a tone, from a fresh reverb each time."""
        reverb = Reverb()
        out_l = np.zeros(BLOCK, dtype=np.float32)
        out_r = np.zeros(BLOCK, dtype=np.float32)
        signal = np.sin(2 * np.pi * hz * t).astype(np.float32)
        total = 0.0
        for start in range(0, len(signal), BLOCK):
            chunk = signal[start : start + BLOCK]
            reverb.process(chunk, chunk, out_l, out_r)
            total += float(np.dot(out_l, out_l))
        return total

    assert energy(3000.0) < energy(400.0), (
        "a 1.2 kHz roll-off must attenuate 3 kHz more than 400 Hz"
    )


def test_the_channels_are_decorrelated():
    """Stereo width comes from different delay lengths per channel."""
    left, right = impulse_response()
    assert not np.allclose(left, right)
    correlation = float(
        np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right) + 1e-12)
    )
    assert correlation < 0.99


def test_the_output_is_fully_wet():
    """100% wet: the direct signal must not appear in the output."""
    reverb = Reverb()
    left = np.zeros(BLOCK, dtype=np.float32)
    right = np.zeros(BLOCK, dtype=np.float32)
    out_l = np.zeros(BLOCK, dtype=np.float32)
    out_r = np.zeros(BLOCK, dtype=np.float32)
    left[:] = 1.0
    right[:] = 1.0
    reverb.process(left, right, out_l, out_r)
    assert not np.allclose(out_l, left), "the dry signal is passing straight through"


def test_process_writes_in_place():
    reverb = Reverb()
    zeros = np.zeros(BLOCK, dtype=np.float32)
    out_l = np.zeros(BLOCK, dtype=np.float32)
    out_r = np.zeros(BLOCK, dtype=np.float32)
    before = out_l.__array_interface__["data"][0]
    reverb.process(zeros, zeros, out_l, out_r)
    assert out_l.__array_interface__["data"][0] == before
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_dsp.py -k reverb -v`
Expected: FAIL with `ImportError: cannot import name 'Reverb'`.

- [ ] **Step 3: Implement**

Append to `src/squelch/dsp.py`:

```python
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
ALLPASS_FEEDBACK = 0.5


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
        # One-pole damping inside the feedback path, so each pass through
        # the loop is darker than the last.
        damped = self._store
        for i in range(n):
            damped = (1.0 - self._damping) * out[i] + self._damping * damped
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
```

The per-sample loops inside `_Comb` and `_Allpass` are the one place this file is not vectorised — a damped feedback loop is inherently sequential. At 256 samples per block, two channels, four combs and two allpasses, that is roughly 3000 iterations per 16 ms. If profiling shows it dominates, replace the loop body with a `scipy.signal.lfilter` call; do not do so speculatively.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_dsp.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/dsp.py tests/test_dsp.py
git commit -m "feat(squelch): add the ambient bus reverb"
```

---

### Task 5: The mixer

**Files:**
- Create: `src/squelch/mixer.py`
- Create: `tests/test_mixer.py`

**Interfaces:**
- Consumes: `RingBuffer`, `Compressor`, `Reverb`, `pan_positions`, `pan_gains`, `BLOCK`, `SAMPLE_RATE`, `block_dbfs`.
- Produces:
  - `AMBIENT_GAIN_DB = -8.0`, `BUFFER_SECONDS = 0.5`
  - class `Channel` with `buffer: RingBuffer`, `muted: bool`, `ambient: bool`, `level_dbfs: float`
  - class `Mixer` with `add_channel() -> Channel`, `render(out: np.ndarray) -> None` (out is `(BLOCK, 2)` float32), `start(stream_factory)`, `stop()`, `failed: bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mixer.py`:

```python
"""Summing twelve feeds into one stereo bus.

The mixer is the one change that threatens the codebase's per-feed
isolation rule -- twelve output streams become one -- so most of these
tests are about a single feed failing without taking the others with it.
"""

import numpy as np
import pytest

from squelch.dsp import BLOCK, block_dbfs
from squelch.mixer import AMBIENT_GAIN_DB, Mixer


def frame(value=0.5, n=BLOCK):
    return np.full(n, value, dtype=np.float32)


def out_buffer():
    return np.zeros((BLOCK, 2), dtype=np.float32)


def render(mixer, blocks=1):
    out = out_buffer()
    for _ in range(blocks):
        mixer.render(out)
    return out


def test_a_mixer_with_no_channels_renders_silence():
    assert not render(Mixer()).any()


def test_a_muted_channel_is_silent():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = True
    channel.buffer.write(frame())
    assert not render(mixer).any()


def test_an_audible_channel_reaches_both_output_channels():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame())
    out = render(mixer)
    assert out[:, 0].any() and out[:, 1].any()


def test_the_dry_bus_is_centred():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame())
    out = render(mixer)
    assert np.allclose(out[:, 0], out[:, 1])


def test_a_starved_channel_contributes_silence_not_a_crash():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    assert channel.buffer.available == 0
    render(mixer)


def test_one_starved_channel_does_not_silence_the_others():
    """Per-feed isolation, which is the codebase's governing rule."""
    mixer = Mixer()
    starved = mixer.add_channel()
    healthy = mixer.add_channel()
    starved.muted = healthy.muted = False
    healthy.buffer.write(frame())
    assert render(mixer).any()


def test_two_audible_channels_sum():
    mixer = Mixer()
    out = out_buffer()
    one = mixer.add_channel()
    one.muted = False
    one.buffer.write(frame(0.2))
    mixer.render(out)
    single = float(np.abs(out[:, 0]).max())

    mixer = Mixer()
    for _ in range(2):
        channel = mixer.add_channel()
        channel.muted = False
        channel.buffer.write(frame(0.2))
    mixer.render(out)
    assert float(np.abs(out[:, 0]).max()) > single


# -- the ambient bus -------------------------------------------------------


def test_an_ambient_only_channel_is_audible():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = True
    channel.ambient = True
    channel.buffer.write(frame())
    assert render(mixer, blocks=4).any(), "ambient routing is independent of mute"


def test_the_ambient_bus_sits_below_the_dry_bus():
    def peak(*, ambient):
        mixer = Mixer()
        channel = mixer.add_channel()
        channel.muted = ambient
        channel.ambient = ambient
        channel.buffer.write(frame())
        out = out_buffer()
        best = 0.0
        for _ in range(8):
            channel.buffer.write(frame())
            mixer.render(out)
            best = max(best, float(np.abs(out).max()))
        return best

    assert peak(ambient=True) < peak(ambient=False)


def test_the_ambient_gain_is_minus_eight_db():
    assert AMBIENT_GAIN_DB == -8.0


def test_two_ambient_feeds_are_panned_apart():
    mixer = Mixer()
    for _ in range(2):
        channel = mixer.add_channel()
        channel.muted = True
        channel.ambient = True
    mixer._channels[0].buffer.write(frame())
    out = render(mixer, blocks=4)
    assert not np.allclose(out[:, 0], out[:, 1]), "one feed left of centre"


def test_a_feed_can_be_on_both_buses():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.ambient = True
    channel.buffer.write(frame())
    assert render(mixer, blocks=4).any()


# -- metering --------------------------------------------------------------


def test_the_channel_reports_its_post_compression_level():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame(0.05))
    render(mixer)
    assert channel.level_dbfs > block_dbfs(frame(0.05)), "makeup gain is included"


def test_a_muted_channel_still_meters():
    """Muting is an audio gate, not a pause."""
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = True
    channel.buffer.write(frame())
    render(mixer)
    assert channel.level_dbfs > -96.0


# -- real-time discipline --------------------------------------------------


def test_render_does_not_allocate():
    """The callback is a real-time context. Allocation there is a bug."""
    import tracemalloc

    mixer = Mixer()
    for _ in range(12):
        channel = mixer.add_channel()
        channel.muted = False
    out = out_buffer()
    for _ in range(20):
        for channel in mixer._channels:
            channel.buffer.write(frame())
        mixer.render(out)

    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for _ in range(50):
        for channel in mixer._channels:
            channel.buffer.write(frame())
        mixer.render(out)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    grown = sum(s.size_diff for s in after.compare_to(before, "filename"))
    assert grown < 16_000, f"render allocated {grown} bytes"


def test_render_writes_in_place():
    mixer = Mixer()
    out = out_buffer()
    before = out.__array_interface__["data"][0]
    mixer.render(out)
    assert out.__array_interface__["data"][0] == before


def test_a_channel_whose_chain_raises_does_not_break_the_block():
    mixer = Mixer()
    broken = mixer.add_channel()
    healthy = mixer.add_channel()
    broken.muted = healthy.muted = False
    healthy.buffer.write(frame())

    def explode(_block, _out):
        raise RuntimeError("boom")

    broken._compressor.process = explode
    out = out_buffer()
    mixer.render(out)
    assert out.any(), "the healthy feed must still be heard"


# -- the stream ------------------------------------------------------------


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        pass


def test_start_opens_a_stereo_stream_at_the_engine_rate():
    made = {}

    def factory(**kwargs):
        made.update(kwargs)
        return FakeStream(**kwargs)

    mixer = Mixer()
    mixer.start(stream_factory=factory)
    assert made["channels"] == 2
    assert made["samplerate"] == 16_000
    assert made["blocksize"] == BLOCK
    assert mixer.failed is False


def test_a_device_that_will_not_open_is_recorded_not_raised():
    """Losing sound must not stop the pane metering."""

    def factory(**kwargs):
        raise RuntimeError("no device")

    mixer = Mixer()
    mixer.start(stream_factory=factory)
    assert mixer.failed is True


def test_stop_is_safe_before_start_and_twice():
    mixer = Mixer()
    mixer.stop()
    mixer.start(stream_factory=lambda **kw: FakeStream(**kw))
    mixer.stop()
    mixer.stop()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_mixer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'squelch.mixer'`.

- [ ] **Step 3: Implement**

Create `src/squelch/mixer.py`:

```python
"""One stereo output for every feed.

Replaces twelve independent PortAudio streams. That change is what makes a
relative bus gain, coordinated panning, and a *shared* reverb possible at
all -- and it is also the one place per-feed isolation could be lost, since
a device failure that used to cost one row now costs all audio. Every
failure path here is therefore written to degrade to silence-for-one rather
than silence-for-all.
"""

from __future__ import annotations

import numpy as np

from squelch.dsp import (
    BLOCK,
    SAMPLE_RATE,
    Compressor,
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
    """One feed's slot in the mix."""

    def __init__(self, capacity: int) -> None:
        self.buffer = RingBuffer(capacity)
        # Plain attributes, read by the callback without synchronisation.
        # Rebinding a bool is atomic under CPython, and a change that takes
        # effect one block late is not observable.
        self.muted = True
        self.ambient = False
        self.level_dbfs = SILENCE_FLOOR_DBFS
        self._compressor = Compressor()
        self._raw = np.zeros(BLOCK, dtype=np.float32)
        self._shaped = np.zeros(BLOCK, dtype=np.float32)


class Mixer:
    def __init__(self, *, block: int = BLOCK) -> None:
        self._block = block
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
            shaped = channel._shaped
            channel.buffer.read_into(raw)
            try:
                channel._compressor.process(raw, shaped)
            except Exception:
                # One feed's chain must never cost the other eleven their
                # block. Silence for this feed, this block.
                shaped[:] = 0.0
            channel.level_dbfs = block_dbfs(shaped)
            if not channel.muted:
                dry += shaped
            if channel.ambient:
                position = (
                    self._positions[index] if index < len(self._positions) else 0.0
                )
                left, right = pan_gains(position)
                # Through the scratch buffer: `shaped * scalar` would
                # allocate a temporary on every feed of every block.
                np.multiply(shaped, left * AMBIENT_GAIN, out=scratch)
                amb_l += scratch
                np.multiply(shaped, right * AMBIENT_GAIN, out=scratch)
                amb_r += scratch
                index += 1

        try:
            self._reverb.process(amb_l, amb_r, self._wet_l, self._wet_r)
        except Exception:
            self._wet_l[:] = 0.0
            self._wet_r[:] = 0.0

        # 100% wet: the ambient bus contributes only its reverb.
        np.add(dry, self._wet_l, out=out[:block, 0])
        np.add(dry, self._wet_r, out=out[:block, 1])
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
```

Three details are load-bearing for the allocation test and must not be "simplified" away: the ambient list is cleared and refilled rather than rebuilt with a comprehension; every scaled add goes through `_scratch` with `out=`, because `array * scalar` allocates; and the compressor's gain ramp scales a fixed unit ramp, because `np.linspace` has no `out=` parameter.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_mixer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/mixer.py tests/test_mixer.py
git commit -m "feat(squelch): add the stereo mixing engine"
```

---

### Task 6: Sessions feed the mixer

**Files:**
- Modify: `src/squelch/session.py`
- Modify: `src/squelch/audio.py`
- Modify: `src/squelch/pipeline.py`
- Modify: `tests/test_session.py`, `tests/test_audio.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Mixer`, `Channel` (Task 5).
- Produces:
  - `Player` deleted from `audio.py`.
  - `pcm_to_float(pcm: bytes, out: np.ndarray) -> int` in `audio.py`.
  - `FeedSession(..., channel=None)`; `muted`, `ambient` proxy to the channel.
  - `Pipeline` writes frames to a sink with `write(pcm: bytes)`; its display tap is removed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audio.py`:

```python
import numpy as np

from squelch.audio import pcm_to_float


def test_pcm_converts_to_normalised_floats():
    pcm = struct.pack("<hhhh", 0, 16384, -16384, 32767)
    out = np.zeros(4, dtype=np.float32)
    assert pcm_to_float(pcm, out) == 4
    assert out[0] == 0.0
    assert out[1] == pytest.approx(0.5, abs=1e-3)
    assert out[2] == pytest.approx(-0.5, abs=1e-3)
    assert out[3] == pytest.approx(1.0, abs=1e-3)


def test_a_short_buffer_takes_what_fits():
    pcm = struct.pack("<hhhh", 100, 200, 300, 400)
    out = np.zeros(2, dtype=np.float32)
    assert pcm_to_float(pcm, out) == 2


def test_empty_pcm_yields_nothing():
    assert pcm_to_float(b"", np.zeros(4, dtype=np.float32)) == 0
```

Append to `tests/test_session.py`:

```python
def test_muting_a_session_mutes_its_channel():
    mixer = Mixer()
    channel = mixer.add_channel()
    session = make_session(channel=channel)
    session.muted = False
    assert channel.muted is False
    session.muted = True
    assert channel.muted is True


def test_ambient_routing_reaches_the_channel():
    mixer = Mixer()
    channel = mixer.add_channel()
    session = make_session(channel=channel)
    session.toggle_ambient()
    assert channel.ambient is True


def test_a_session_reports_the_channel_s_level():
    mixer = Mixer()
    channel = mixer.add_channel()
    session = make_session(channel=channel)
    channel.level_dbfs = -18.0
    assert session.level == -18.0


def test_a_session_without_a_channel_still_constructs():
    """Sessions are built before the mixer opens its device."""
    session = make_session(channel=None)
    session.muted = False
    assert session.muted is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_audio.py tests/test_session.py -v`
Expected: FAIL with `ImportError: cannot import name 'pcm_to_float'`.

- [ ] **Step 3: Implement the conversion and delete `Player`**

In `src/squelch/audio.py`, delete the whole `Player` class and add:

```python
import numpy as np


def pcm_to_float(pcm: bytes, out: np.ndarray) -> int:
    """Decode s16le bytes into normalised floats, in place.

    Writes into `out` rather than returning an array: this runs on the feed
    thread for every frame, and the destination is a preallocated staging
    buffer.
    """
    samples = np.frombuffer(pcm, dtype="<i2")
    n = min(len(samples), len(out))
    if n:
        # Assignment casts int16 to float32; scaling in place afterwards
        # avoids the dtype juggling `np.multiply(..., out=)` would need.
        out[:n] = samples[:n]
        out[:n] *= 1.0 / 32768.0
    return n
```

Delete `tests/test_audio.py`'s `Player` tests. `StreamReader` and its tests are untouched.

- [ ] **Step 4: Make the pipeline write to a sink**

In `src/squelch/pipeline.py`, delete `_emit_level`, `set_level_every`, `LEVEL_DECIMATION`, and `Events.on_level`. Keep `on_state` and `on_activity`. `Pipeline.run`'s live branch becomes:

```python
            self._report_state("live")
            self._sink.write(frame)
            self._emit_activity(rms_dbfs(frame))
```

and the `frame is None` branch keeps only `self._report_state("reconnecting")`. Rename the constructor's `player` parameter to `sink`. Update `tests/test_pipeline.py`: `FakePlayer` becomes `FakeSink`, and delete the tests that asserted display-level decimation — Task 10 replaces that behaviour and `tests/test_mixer.py` covers metering.

- [ ] **Step 5: Give the session a channel**

In `src/squelch/session.py`, replace the player wiring. `__init__` takes `channel=None` instead of `player_factory`:

```python
        self._channel = channel
        self._muted = muted
        self._ambient = False
        if channel is not None:
            channel.muted = muted
        self._staging = np.zeros(FRAME_SAMPLES, dtype=np.float32)
```

```python
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

    def toggle_ambient(self) -> bool:
        self._ambient = not self._ambient
        if self._channel is not None:
            self._channel.ambient = self._ambient
        return self._ambient

    @property
    def level(self) -> float:
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
```

`_run` passes `self` as the pipeline's sink and drops the `self._player.start()` block entirely — the mixer owns the device now, and its single failure is reported once by `main()`.

**Delete what plan B's display path left behind.** If plan B was built, these
are now dead and must go rather than linger as a second, silent metering path:
`EXPANDED_DECIMATION`, `COMPACT_DECIMATION`, and `_apply_display_rate` in
`session.py`. The `player_factory` parameter goes too, so `make_session` in
`tests/test_session.py` must drop it and take `channel=` instead. Confirm with
`grep -rn "player_factory\|_apply_display_rate\|DECIMATION" src/ tests/` — only
`ACTIVITY_DECIMATION` should survive.

- [ ] **Step 6: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/squelch/audio.py src/squelch/session.py src/squelch/pipeline.py tests/
git commit -m "feat(squelch): route feeds into the mixer instead of per-feed streams"
```

---

### Task 7: Configuration

**Files:**
- Modify: `src/squelch/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: the DSP defaults.
- Produces: `Config` gains `compressor_threshold_dbfs = -12.0`, `compressor_ratio = 4.0`, `compressor_makeup_db = 6.0`, `compressor_range_db = 12.0`, `ambient_gain_db = -8.0`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_the_audio_defaults_match_the_dsp_module():
    from squelch import dsp

    config = Config()
    assert config.compressor_threshold_dbfs == dsp.THRESHOLD_DBFS
    assert config.compressor_ratio == dsp.RATIO
    assert config.compressor_makeup_db == dsp.MAKEUP_DB
    assert config.compressor_range_db == dsp.RANGE_LIMIT_DB


def test_the_audio_parameters_can_be_configured(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text(
        "compressor_threshold_dbfs = -18.0\n"
        "compressor_ratio = 2.0\n"
        "ambient_gain_db = -12.0\n"
    )
    config = load_config(path)
    assert config.compressor_threshold_dbfs == -18.0
    assert config.compressor_ratio == 2.0
    assert config.ambient_gain_db == -12.0


def test_a_non_numeric_ratio_is_rejected(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text('compressor_ratio = "hard"\n')
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "compressor_ratio" in str(exc.value)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config.py -k "audio or ratio" -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'compressor_threshold_dbfs'`.

- [ ] **Step 3: Implement**

In `src/squelch/config.py`, add to `Config`:

```python
    # Audio shaping. The range limit and the gate are not decorative: at
    # 4:1 with no limit, a -50 dBFS noise floor gains ~28 dB and hiss
    # becomes the loudest thing in the pane.
    compressor_threshold_dbfs: float = -12.0
    compressor_ratio: float = 4.0
    compressor_makeup_db: float = 6.0
    compressor_range_db: float = 12.0
    ambient_gain_db: float = -8.0
```

- [ ] **Step 4: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/config.py tests/test_config.py
git commit -m "feat(squelch): expose the audio shaping parameters in config"
```

---

### Task 8: Wire the mixer into startup

**Files:**
- Modify: `src/squelch/__main__.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `Mixer` (Task 5), `FeedSession(channel=...)` (Task 6).
- Produces: `main()` builds one `Mixer`, gives each session a channel, starts it before the app, warns once if it failed, and stops it in the `finally` clause.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
def test_every_session_gets_a_channel():
    mixer = Mixer()
    feeds = [Feed(ident="a_twr", label="A Tower"), Feed(ident="a_gnd", label="A Ground")]
    sessions = build_sessions(feeds, Config(feed="a_twr"), events(), mixer=mixer)
    assert len(mixer._channels) == 2
    assert all(s._channel is not None for s in sessions)


def test_the_configured_feed_starts_audible_on_its_channel():
    mixer = Mixer()
    feeds = [Feed(ident="a_twr", label="A Tower"), Feed(ident="a_gnd", label="A Ground")]
    build_sessions(feeds, Config(feed="a_twr"), events(), mixer=mixer)
    assert mixer._channels[0].muted is False
    assert mixer._channels[1].muted is True


def test_a_failed_audio_device_warns_once_and_still_runs():
    """Losing sound must not lose the pane."""
    warnings = []
    mixer = Mixer()
    mixer.start(stream_factory=lambda **kw: (_ for _ in ()).throw(RuntimeError()))
    assert mixer.failed is True
    report_audio_failure(mixer, warnings.append)
    assert len(warnings) == 1
    assert "audio" in warnings[0].lower()


def test_no_warning_when_the_device_opened():
    warnings = []
    mixer = Mixer()
    mixer.start(stream_factory=lambda **kw: FakeStream())
    report_audio_failure(mixer, warnings.append)
    assert warnings == []
```

Add whatever `events()` and `FakeStream` helpers `tests/test_main.py` needs, mirroring `tests/test_mixer.py`'s `FakeStream`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_main.py -k "channel or audio" -v`
Expected: FAIL — `build_sessions` takes no `mixer`.

- [ ] **Step 3: Implement**

In `src/squelch/__main__.py`:

```python
AUDIO_FAILED = (
    "no audio device — every feed is still connecting and metering, "
    "but nothing can be heard"
)


def report_audio_failure(mixer, warn) -> None:
    if mixer.failed:
        warn(AUDIO_FAILED)
```

Give `build_sessions` a `mixer` parameter and a channel per feed:

```python
def build_sessions(feeds, config, events, *, mixer, session_factory=FeedSession):
    sessions = []
    for feed in feeds:
        sessions.append(
            session_factory(
                feed,
                events,
                muted=feed.ident != config.feed,
                icao=config.icao,
                channel=mixer.add_channel(),
                activity_threshold=config.activity_threshold_dbfs,
            )
        )
    if sessions and all(s.muted for s in sessions):
        # The configured ident matched nothing this airport publishes.
        # Opening entirely silent reads as broken, so unmute the first.
        sessions[0].muted = False
    return sessions
```

In `main()`:

```python
    mixer = Mixer()
    sessions = sessions_builder(feeds, config, events, mixer=mixer)
    mixer.start()
    report_audio_failure(mixer, pending.append)
```

and in the `finally` clause, before stopping the sessions:

```python
        mixer.stop()
```

- [ ] **Step 4: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/__main__.py tests/test_main.py
git commit -m "feat(squelch): start one mixer for every feed"
```

---

### Task 9: Poll levels for the meter

Replaces plan B's `Pipeline.on_level` path, which measured pre-compression.

**Files:**
- Modify: `src/squelch/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `session.level` (Task 6).
- Produces: `SquelchApp.LEVEL_INTERVAL = 1 / 25`, `SquelchApp._tick_levels()`. `SquelchApp.set_level` is deleted.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
# -- metering --------------------------------------------------------------


@pytest.mark.asyncio
async def test_expanded_rows_take_a_level_each_tick():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app._sessions[0].level = -20.0
        app._tick_levels()
        app._tick_levels()
        await pilot.pause()
        assert len(app._rows[id(app._sessions[0])]._history) == 2


@pytest.mark.asyncio
async def test_compact_rows_are_not_polled():
    """A muted feed draws no meter, so drawing one is wasted work."""
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app._sessions[1].level = -20.0
        app._tick_levels()
        await pilot.pause()
        assert len(app._rows[id(app._sessions[1])]._history) == 0


@pytest.mark.asyncio
async def test_the_meter_shows_the_post_compression_level():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app._sessions[0].level = -6.0
        app._tick_levels()
        await pilot.pause()
        assert app._rows[id(app._sessions[0])]._history[-1] == -6.0


@pytest.mark.asyncio
async def test_polling_survives_a_session_with_no_row():
    app = make_app(2)
    async with app.run_test(size=SIZE):
        app._rows.clear()
        app._tick_levels()
```

Give `FakeSession` a `self.level = -96.0` attribute.

**Tests from earlier plans that call `app.set_level` must be updated in this
step**, since it no longer exists. Each becomes: set `session.level`, then call
`app._tick_levels()`. The known callers are `test_a_compact_row_shows_no_meter`
(plan A, Task 5) and `test_a_resort_preserves_meter_history` (plan B, Task 6).
Run `grep -rn "set_level" tests/` and convert every hit.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_app.py -k tick_levels -v`
Expected: FAIL with `AttributeError: 'SquelchApp' object has no attribute '_tick_levels'`.

- [ ] **Step 3: Implement**

In `src/squelch/app.py`, delete `set_level`, add:

```python
    # 25 Hz: fast enough to read as a waveform, and the cost scales with
    # what you are listening to rather than with how many feeds exist.
    LEVEL_INTERVAL = 1 / 25
```

In `on_mount`:

```python
        self._level_timer = self.set_interval(self.LEVEL_INTERVAL, self._tick_levels)
```

In `on_unmount`, stop it alongside the others. Add:

```python
    def _tick_levels(self) -> None:
        """Read each audible feed's post-compression level.

        Polled rather than pushed: the level is computed inside the audio
        callback, which is a real-time context and may not call into the
        UI. Reading a float from here costs nothing and removes level
        updates from the audio path entirely.
        """
        for session in self._sessions:
            row = self._rows.get(id(session))
            if row is not None and row.expanded:
                row.push_level(session.level)
```

In `src/squelch/__main__.py`, delete `on_level` from the `SessionEvents` construction and from `session.py`'s `SessionEvents` dataclass, along with `_set_level`.

- [ ] **Step 4: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/app.py src/squelch/__main__.py src/squelch/session.py tests/
git commit -m "feat(squelch): poll post-compression levels for the meter"
```

---

### Task 10: Documentation and manual verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite the "Cost" section**

> ## Cost
>
> One ffmpeg process, one ring buffer, and one thread per feed — twelve of
> each at KPDX — feeding **one** stereo output stream. Bandwidth is trivial at
> roughly 16–32 kbps per feed; the CPU is mostly ffmpeg decode plus one
> mixing callback every 16 ms. Worth watching on battery.

- [ ] **Step 2: Document the audio chain**

Add a section:

> ## Audio shaping
>
> ```
> ffmpeg ─► ring buffer ─► gate ─► upward comp ─┬─► dry bus (centre) ───────────────┐
>                                               │                                   ├─► stereo
>                                               └─► ambient bus (−8 dB, panned) ─► reverb ─┘
> ```
>
> **Upward compression** lifts quiet feeds instead of you riding a gain
> control: 4:1 below −12 dBFS with a 6 dB soft knee and +6 dB makeup. Two
> limits keep it honest — a **12 dB range limit**, and a **gate** at −40 dBFS
> that closes at −46. Without them, 4:1 upward compression boosts a −50 dBFS
> noise floor by about 28 dB and hiss becomes the loudest thing in the pane.
> The gate attenuates the *boost*, never the signal, and ramps rather than
> steps, so a signal hovering at the threshold does not chatter.
>
> **`[A]` routes a feed to the ambient bus**: 8 dB down, panned, and heard
> only through a short dark reverb — 100 ms, fully wet, rolled off above
> 1.2 kHz. Ambient feeds are present without being intelligible, which is the
> point. With several on the bus they spread across the stereo field between
> 50% left and 50% right; an odd number puts one in the centre, phase-inverted
> and 6 dB down so it does not pile up in the middle.

- [ ] **Step 3: Update the configuration table**

```markdown
| `compressor_threshold_dbfs` | `-12.0` | Below this, upward compression applies |
| `compressor_ratio` | `4.0` | Upward compression ratio |
| `compressor_makeup_db` | `6.0` | Gain applied to every feed |
| `compressor_range_db` | `12.0` | Maximum upward gain |
| `ambient_gain_db` | `-8.0` | Ambient bus level, relative to the dry bus |
```

- [ ] **Step 4: Update "Known limitations"**

Replace "`[A]` is rendered and toggleable but silent until the mixing engine lands" with:

> - The reverb is fixed. Decay, damping, and wetness are not configurable.
> - All feeds share one output device; there is no per-feed device routing.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Manual verification — the one step that needs hardware**

Run `uv run squelch` on a live airport and confirm:

1. Several feeds are audible simultaneously through one stereo stream.
2. A quiet feed is noticeably lifted, and no feed's noise floor is audibly boosted during silence.
3. `[A]` on three or four feeds produces a diffuse wash spread across the stereo field, sitting behind the dry feeds without masking them.
4. Toggling `[A]` produces no click.
5. Unplugging and reconnecting the output device does not crash the app.

Record the result in the commit message.

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs(squelch): document the mixing engine and audio shaping"
```

---

## Verification

- `uv run pytest` passes with no skips.
- `grep -rn "class Player" src/` returns nothing.
- `grep -rn "sounddevice" src/` shows only the lazy import inside `Mixer.start`.
- `tests/test_mixer.py::test_render_does_not_allocate` passes — the real-time discipline is asserted, not assumed.
- Manual verification in Task 10 Step 6 completed and recorded.
