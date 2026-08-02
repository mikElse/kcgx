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


from squelch.rows import (
    NAME_WIDTH,
    NAME_WIDTH_EXPANDED,
    ROW_WIDTH,
    compact_line,
    control_line,
    expanded_name_line,
)

# Longer than NAME_WIDTH_EXPANDED, so it truncates in *both* fields and the
# comparison below is between two real cuts rather than a cut and a fit.
LONG_NAME = "Approach (Final) South Arrivals 124.35 MHz Sector 3"


def test_every_line_is_exactly_the_content_width():
    lines = [
        compact_line("Tower (Both)", muted=True, ambient=False, state="live"),
        expanded_name_line("Tower (Both)", state="live"),
        control_line(muted=False, ambient=False, soloed=False, activity=0.34),
    ]
    assert [len(line) for line in lines] == [ROW_WIDTH] * 3


def test_the_ident_is_gone_from_the_row():
    line = compact_line("Tower (Both)", muted=True, ambient=False, state="live")
    assert "kpdx" not in line.lower()


def test_compact_shows_the_name_the_controls_and_the_state_dot():
    line = compact_line("Tower (Both)", muted=True, ambient=False, state="live")
    assert "Tower (Both)" in line
    assert "[A]" in line
    assert "[OFF]" in line
    assert line.endswith("●")


def test_compact_shows_on_when_audible():
    line = compact_line("Ground", muted=False, ambient=False, state="live")
    assert "[ ON]" in line
    assert "[OFF]" not in line


def test_the_on_off_control_is_the_same_width_in_both_states():
    """A toggle that changes width shifts every cell beside it."""
    off = compact_line("Ground", muted=True, ambient=False, state="live")
    on = compact_line("Ground", muted=False, ambient=False, state="live")
    assert len(off) == len(on) == ROW_WIDTH
    assert off.index("[") == on.index("[")


def test_state_dots_reach_the_line():
    for state, dot in (("live", "●"), ("reconnecting", "◐"), ("offline", "○")):
        assert compact_line("Ground", muted=True, ambient=False, state=state).endswith(dot)
        assert expanded_name_line("Ground", state=state).endswith(dot)


def test_a_long_name_truncates_visibly_rather_than_silently():
    line = compact_line(LONG_NAME, muted=True, ambient=False, state="live")
    assert "…" in line
    assert len(line) == ROW_WIDTH


def test_expanded_gives_the_name_more_room_than_compact():
    assert NAME_WIDTH_EXPANDED > NAME_WIDTH
    compact = compact_line(LONG_NAME, muted=True, ambient=False, state="live")
    expanded = expanded_name_line(LONG_NAME, state="live")
    assert expanded.count("…") == 1
    assert len(expanded.split("…")[0]) > len(compact.split("…")[0])


def test_the_name_field_is_wider_than_the_old_24_cell_field():
    """Dropping the ident is what this buys."""
    assert NAME_WIDTH == 34


def test_control_line_carries_all_three_controls():
    line = control_line(muted=False, ambient=False, soloed=False, activity=None)
    assert "[S]" in line
    assert "[ ON]" in line
    assert "[A]" in line


def test_control_line_shows_activity_when_measured():
    line = control_line(muted=False, ambient=False, soloed=False, activity=0.34)
    assert "busy 34%" in line


def test_control_line_omits_activity_until_it_is_measured():
    line = control_line(muted=False, ambient=False, soloed=False, activity=None)
    assert "busy" not in line
    assert len(line) == ROW_WIDTH


def test_activity_rounds_rather_than_truncating():
    line = control_line(muted=False, ambient=False, soloed=False, activity=0.999)
    assert "busy 100%" in line
