"""The signal processing, as arithmetic.

None of this opens an audio device. What is left to test is the ambient
bus -- panning and the reverb -- plus `block_dbfs`, which now feeds only
the meter and the activity ranking. The gate and the compressor that used
to dominate this file were removed on 2026-08-02; their tests went with
them rather than being kept as a description of code that is not there.
"""

import math

import numpy as np
import pytest

from squelch.dsp import BLOCK, SAMPLE_RATE, block_dbfs


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


# -- panning ---------------------------------------------------------------

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
