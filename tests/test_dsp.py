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


def test_the_gate_has_a_single_threshold():
    """Opens and closes at the same level, by request.

    This replaces a hysteresis test. The gate used to open at -40 and hold
    until -46 so a signal hovering at the threshold could not chatter; the
    thresholds are now equal, so it can. What is left damping it is the
    ramp, which the next test pins -- if that goes too, a hovering signal
    steps the full 12 dB between blocks.
    """
    from squelch.dsp import GATE_CLOSE_DBFS, GATE_OPEN_DBFS

    assert GATE_OPEN_DBFS == GATE_CLOSE_DBFS == -55.0

    comp = Compressor()
    run_blocks(comp, -20.0, 20)
    assert comp.gate_open is True
    run_blocks(comp, -65.0, 60)
    assert comp.gate_open is False, "below the single threshold it shuts"


def test_the_gate_ramps_rather_than_steps():
    """A hard gate steps the whole range at the threshold and chatters.

    With the hysteresis removed this ramp is the only thing left damping a
    signal that sits near -40, so it is pinned deliberately hard. The
    levels matter: a crossing where the boost is small cannot detect a
    missing ramp, because the envelope's own attack smoothing limits the
    jump anyway. Crossing from -70 to just above the -55 threshold puts the
    boost at the 12 dB range limit, so an ungated step is the full 12 and
    the assertion can actually fail.
    """
    comp = Compressor()
    run_blocks(comp, -70.0, 40)
    quiet_gain = comp.gain_db
    assert comp.gate_open is False
    out = np.zeros(BLOCK, dtype=np.float32)
    comp.process(tone(-54.0), out)
    assert comp.gate_open is True, "the level must actually cross the threshold"
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
    """The 1.2 kHz roll-off, measured across a band rather than at a point.

    Two single tones will not do it: four parallel combs put deep notches
    and peaks all over the spectrum, so a lone 400 Hz tone can land in a
    null and read quieter than 3 kHz on a peak while the roll-off is
    working perfectly. Measured on this reverb, 400 Hz gives 45 and 800 Hz
    gives 259 -- ripple of that size swamps the filter being tested.
    Averaging over a band cancels the ripple.
    """
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

    def band(low, high, points=25):
        return float(np.mean([energy(float(f)) for f in np.linspace(low, high, points)]))

    below = band(200.0, 800.0)
    above = band(2600.0, 3400.0)
    assert above < below / 2.0, (
        f"a 1.2 kHz roll-off must clearly attenuate 3 kHz "
        f"(got {above:.1f} against {below:.1f})"
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
