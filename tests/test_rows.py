"""Pure rendering tests for one feed's row.

Nothing here starts an app: these are the functions that decide what fits
in 46 cells, and they are the cheapest place to prove it.
"""

from squelch.rows import (
    METER_ROWS,
    METER_STEPS,
    METER_WIDTH,
    level_step,
    meter_rows,
)


def test_silence_is_the_lowest_step():
    assert level_step(-96.0) == 0


def test_full_scale_is_the_highest_step():
    assert level_step(0.0) == METER_STEPS - 1


def test_the_floor_and_below_both_clamp_to_zero():
    assert level_step(-60.0) == 0
    assert level_step(-200.0) == 0


def test_steps_increase_with_level():
    quiet, mid, loud = level_step(-50.0), level_step(-30.0), level_step(-5.0)
    assert quiet < mid < loud


def test_meter_returns_three_rows_of_the_requested_width():
    rows = meter_rows([-20.0] * 10, width=12)
    assert len(rows) == METER_ROWS
    assert all(len(row) == 12 for row in rows)


def test_a_silent_meter_fills_only_the_bottom_row():
    top, middle, bottom = meter_rows([-96.0] * 8, width=8)
    assert set(top) == {" "}
    assert set(middle) == {" "}
    assert set(bottom) == {"▁"}


def test_a_full_scale_meter_fills_every_row():
    top, middle, bottom = meter_rows([0.0] * 8, width=8)
    assert set(top) == {"█"}
    assert set(middle) == {"█"}
    assert set(bottom) == {"█"}


def test_a_mid_level_fills_below_and_leaves_the_top_empty():
    """A column is one sample drawn across 24 steps, not three meters."""
    top, middle, bottom = meter_rows([-30.0], width=1)
    assert bottom == "█", "everything below the level reads as full"
    assert top == " ", "nothing above the level is drawn"
    assert middle not in (" ",), "the level itself lands in the middle row"


def test_a_short_history_is_padded_on_the_left():
    top, _middle, bottom = meter_rows([0.0], width=5)
    assert top == "    █", "the newest sample belongs at the right"
    assert bottom == "▁▁▁▁█"


def test_history_scrolls_oldest_off_the_left():
    loud_then_quiet = [0.0] + [-96.0] * 12
    top, _middle, _bottom = meter_rows(loud_then_quiet, width=10)
    assert set(top) == {" "}, "the loud sample has scrolled off"


def test_the_default_width_is_the_full_content_row():
    assert METER_WIDTH == 46
    assert all(len(row) == 46 for row in meter_rows([-20.0] * 50))
