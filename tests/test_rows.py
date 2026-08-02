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


from squelch.rows import control_at


def test_a_compact_click_on_the_name_is_not_a_control():
    assert control_at(0, 0, expanded=False) is None
    assert control_at(20, 0, expanded=False) is None


def test_a_compact_click_hits_the_ambient_and_mute_controls():
    line = compact_line("Ground", muted=True, ambient=False, state="live")
    for x in range(len(line)):
        if line[x : x + 3] == "[A]":
            assert control_at(x, 0, expanded=False) == "ambient"
        if line[x : x + 5] == "[OFF]":
            assert control_at(x, 0, expanded=False) == "mute"


def test_a_compact_row_has_no_solo_control():
    assert "solo" not in {
        control_at(x, 0, expanded=False) for x in range(ROW_WIDTH)
    }


def test_a_compact_click_below_the_first_line_is_nothing():
    assert control_at(2, 1, expanded=False) is None


def test_expanded_controls_live_on_the_control_line_only():
    assert control_at(1, 0, expanded=True) is None, "the name line"
    assert control_at(1, 2, expanded=True) is None, "a meter line"
    assert control_at(1, 4, expanded=True) == "solo"


def test_expanded_click_hits_each_control():
    line = control_line(muted=False, ambient=False, soloed=False, activity=None)
    assert line.index("[S]") == 0
    assert control_at(0, 4, expanded=True) == "solo"
    assert control_at(line.index("[ ON]"), 4, expanded=True) == "mute"
    assert control_at(line.index("[A]"), 4, expanded=True) == "ambient"


def test_expanded_click_on_the_activity_readout_is_not_a_control():
    assert control_at(ROW_WIDTH - 1, 4, expanded=True) is None


def test_the_gaps_between_controls_are_not_controls():
    assert control_at(3, 4, expanded=True) is None
    assert control_at(4, 4, expanded=True) is None


def test_out_of_range_coordinates_are_safe():
    assert control_at(-1, 0, expanded=False) is None
    assert control_at(999, 4, expanded=True) is None
    assert control_at(0, -3, expanded=True) is None


from rich.text import Text

from squelch.rows import (
    DEFAULT_PALETTE,
    MeterPalette,
    gradient_style,
    meter_text,
)

PALETTE = MeterPalette(dim="dim", text="white", accent="green", peak="red")


def test_silence_uses_the_dim_stop():
    assert gradient_style(0, PALETTE) == "dim"


def test_a_peak_uses_the_peak_stop():
    assert gradient_style(METER_STEPS - 1, PALETTE) == "red"


def test_the_gradient_climbs_through_every_stop():
    seen = [gradient_style(step, PALETTE) for step in range(METER_STEPS)]
    assert set(seen) == {"dim", "white", "green", "red"}


def test_the_gradient_never_goes_backwards():
    order = ["dim", "white", "green", "red"]
    seen = [order.index(gradient_style(s, PALETTE)) for s in range(METER_STEPS)]
    assert seen == sorted(seen), "louder must never render cooler"


def test_meter_text_is_three_lines():
    text = meter_text([-20.0] * 10, PALETTE, width=10)
    assert isinstance(text, Text)
    assert text.plain.count("\n") == 2


def test_meter_text_matches_the_plain_renderer():
    history = [-50.0, -20.0, -5.0]
    plain = "\n".join(meter_rows(history, width=3))
    assert meter_text(history, PALETTE, width=3).plain == plain


def test_meter_text_colours_a_loud_column_differently_from_a_quiet_one():
    text = meter_text([-96.0, 0.0], PALETTE, width=2)
    styles = {str(span.style) for span in text.spans}
    assert "dim" in styles
    assert "red" in styles


def test_the_default_palette_defines_every_stop():
    for stop in ("dim", "text", "accent", "peak"):
        assert getattr(DEFAULT_PALETTE, stop)


def test_every_default_palette_stop_is_a_style_rich_can_resolve():
    """Regression guard: Textual CSS variables are not Rich styles.

    The meter is coloured per cell through rich.Text, which resolves style
    strings itself and has never heard of `$text-disabled`. A palette
    written in Textual variables parses fine and then raises MissingStyle
    at render time, taking down every test that paints a row.
    """
    from rich.style import Style

    for stop in ("dim", "text", "accent", "peak"):
        value = getattr(DEFAULT_PALETTE, stop)
        Style.parse(value)  # raises rich.errors.StyleSyntaxError if bogus
