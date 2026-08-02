"""The signal processing, as arithmetic.

None of this opens an audio device. The compressor's range limit and gate
are the important parts: without them, 4:1 upward compression below -12 dBFS
boosts a -50 dBFS noise floor by ~28 dB and hiss becomes the loudest thing
in the pane.
"""

import math

import numpy as np
import pytest

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
    """A signal hovering just under the open point must not chatter.

    The envelope has to actually *settle* inside the -46..-40 band for this
    to test anything. Five blocks at -42 does not: the envelope is still
    releasing from -20 (release is ~0.9 per 16 ms block) and is nowhere near
    -42 yet, so the gate stays open whether or not there are two thresholds
    -- the assertion passes on envelope lag alone. Sixty blocks settles it.
    """
    comp = Compressor()
    run_blocks(comp, -20.0, 20)
    assert comp.gate_open is True
    run_blocks(comp, -43.0, 60)
    assert comp.gate_open is True, "between the open and close points it holds"
    run_blocks(comp, -50.0, 60)
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
