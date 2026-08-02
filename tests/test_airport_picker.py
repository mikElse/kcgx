"""Tests for the airport picker.

Capture uses the compositor, not screen.render_lines(): in Textual 8.2.8 a
container renders Blank and its children are painted separately, so
render_lines() reports blank fill for every child widget and every width
assertion below would pass vacuously.
"""

from __future__ import annotations

import pytest
from textual.geometry import Size

from kcgx.airports import Airport
from kcgx.picker import POPUP_HEIGHT, POPUP_WIDTH, AirportPicker, fit, row_text

SIZE = (POPUP_WIDTH, POPUP_HEIGHT)

AIRPORTS = [
    Airport("KPDX", "PDX", "Portland International Airport", "Portland",
            "OR", "US", 45.5887, -122.598, "large"),
    Airport("KTTD", "TTD", "Portland-Troutdale Airport", "Troutdale",
            "OR", "US", 45.5494, -122.401, "medium"),
    Airport("KORD", "ORD", "Chicago O'Hare International Airport", "Chicago",
            "IL", "US", 41.9786, -87.9048, "large"),
    Airport("KSEA", "SEA", "Seattle–Tacoma International Airport", "Seattle",
            "WA", "US", 47.4479, -122.310, "large"),
]


def rendered(app):
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


# -- row rendering ---------------------------------------------------------


def test_fit_pads_short_text_and_marks_real_cuts():
    assert fit("ab", 5) == "ab   "
    assert fit("abcdef", 4) == "abc…"
    assert fit("abcd", 4) == "abcd"
    assert fit("abc", 0) == ""


def test_a_row_carries_the_code_the_name_and_the_place():
    line = row_text(AIRPORTS[0], 58)
    assert line.startswith("KPDX")
    assert "Portland International" in line
    assert "Portland, OR" in line


def test_a_row_is_exactly_the_width_asked_for():
    for airport in AIRPORTS:
        assert len(row_text(airport, 58)) == 58


def test_a_long_name_is_cut_visibly_not_silently():
    long = Airport("XXXX", "", "A" * 90, "Nowhere", "ZZ", "US", 0.0, 0.0, "large")
    assert "…" in row_text(long, 58)


# -- the app ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_sees_mounted_widget_content():
    """Guards the capture helper itself against silently returning blank fill."""
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE):
        text, _ = rendered(app)
        assert any("KPDX" in line for line in text)


@pytest.mark.asyncio
async def test_it_opens_showing_everything():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE):
        joined = "\n".join(rendered(app)[0])
        assert "KPDX" in joined and "KORD" in joined


@pytest.mark.asyncio
async def test_typing_filters_the_list():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"portland")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "KPDX" in joined
        assert "KORD" not in joined, "typing must actually narrow the list"


@pytest.mark.asyncio
async def test_enter_returns_the_highlighted_airport():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"kord")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value is not None
    assert app.return_value.icao == "KORD"


@pytest.mark.asyncio
async def test_arrows_move_the_highlight_while_typing():
    """Focus stays in the input, so the app must forward up/down itself."""
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"portland")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value.icao == "KTTD", (
        "down did not move the highlight off the first match"
    )


@pytest.mark.asyncio
async def test_escape_cancels_with_no_selection():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("escape")
        await pilot.pause()
    assert app.return_value is None


@pytest.mark.asyncio
async def test_enter_on_no_matches_does_not_select_anything():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"qqqqzz")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "no airports match" in joined.lower()
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running, "enter with nothing highlighted must not exit"
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_an_initial_query_prefilters():
    app = AirportPicker(AIRPORTS, initial="seattle")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "KSEA" in joined
        assert "KPDX" not in joined


@pytest.mark.asyncio
async def test_the_popup_never_overflows_its_width():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE):
        _text, strips = rendered(app)
        assert all(s.cell_length == POPUP_WIDTH for s in strips)
