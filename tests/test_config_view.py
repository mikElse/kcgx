"""The config overlay.

The table is a pure function of a Config, so most of this needs no app.
The point of the screen is honesty about which keys are actually honoured,
so that is what most of these assert.
"""

from __future__ import annotations

import pytest
from textual.geometry import Size

from squelch import dsp
from squelch.app import SquelchApp
from squelch.config import Config
from squelch.config_view import (
    CONTENT_WIDTH,
    FIXED,
    INERT,
    LIVE,
    ConfigScreen,
    config_rows,
    row_text,
)
from squelch.mixer import AMBIENT_GAIN_DB

SIZE = (48, 42)


def statuses(config=None):
    return {s.label: s.status for s in config_rows(config or Config())}


# -- the table -------------------------------------------------------------


def test_every_row_fits_the_overlay_exactly():
    for setting in config_rows(Config()):
        assert len(row_text(setting)) == CONTENT_WIDTH, setting.label


def test_a_long_label_cannot_widen_a_row():
    from squelch.config_view import Setting

    line = row_text(Setting("x" * 80, "y" * 80, INERT))
    assert len(line) == CONTENT_WIDTH


def test_the_chatter_threshold_is_the_one_audio_key_that_is_honoured():
    """build_sessions passes it to every FeedSession; the rest go nowhere."""
    assert statuses()["Chatter threshold"] == LIVE


def test_the_compressor_keys_are_marked_inert():
    """They are read into Config and consumed by nothing: Channel builds its
    Compressor from the dsp module defaults."""
    marks = statuses()
    for label in (
        "Comp threshold",
        "Comp ratio",
        "Comp makeup",
        "Comp range limit",
        "Ambient bus (set)",
    ):
        assert marks[label] == INERT, label


def test_what_is_compiled_in_is_marked_fixed():
    marks = statuses()
    for label in ("Gate", "Reverb decay", "Reverb roll-off", "Ambient bus (in use)"):
        assert marks[label] == FIXED, label


def test_the_table_shows_configured_values_not_just_defaults():
    config = Config(compressor_ratio=2.5, activity_threshold_dbfs=-35.5)
    values = {s.label: s.value for s in config_rows(config)}
    assert "2.5" in values["Comp ratio"]
    assert "-35.5" in values["Chatter threshold"]


def test_the_ambient_rows_show_the_gap_between_asked_and_applied():
    """The clearest illustration of what `inert` means."""
    config = Config(ambient_gain_db=-20.0)
    values = {s.label: s.value for s in config_rows(config)}
    assert "-20.0" in values["Ambient bus (set)"]
    assert f"{AMBIENT_GAIN_DB:.1f}" in values["Ambient bus (in use)"]
    assert values["Ambient bus (set)"] != values["Ambient bus (in use)"]


def test_the_gate_row_tracks_the_dsp_module():
    values = {s.label: s.value for s in config_rows(Config())}
    assert f"{dsp.GATE_OPEN_DBFS:.1f}" in values["Gate"]


# -- the screen ------------------------------------------------------------


def make_app():
    return SquelchApp(Config(icao="KPDX"), [])


def rendered(app):
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


@pytest.mark.asyncio
async def test_c_opens_the_config_overlay():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_the_overlay_lists_the_audio_settings():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "Comp ratio" in joined
        assert "Chatter threshold" in joined


@pytest.mark.asyncio
async def test_the_overlay_says_which_settings_do_nothing_yet():
    """Half the table is inert. A modal that did not say so would lie."""
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert INERT in joined
        assert "not yet applied" in joined


@pytest.mark.asyncio
async def test_escape_closes_the_overlay():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_c_closes_it_again():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert not isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_the_overlay_stays_within_the_pane():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        too_wide = [
            (w.__class__.__name__, w.id, w.outer_size.width)
            for w in app.screen.query("*")
            if w.outer_size.width > SIZE[0]
        ]
        assert too_wide == []


@pytest.mark.asyncio
async def test_no_row_wraps_onto_a_second_line():
    """Regression guard: getting the width wrong wraps rather than clips.

    The overlay is 44 wide with a border *and* `padding: 0 1`, so the usable
    width is 40, not 42. Sizing rows to 42 turned every one of them into two
    lines and left a column of orphaned status words -- and it still
    contained every string the other tests look for, so only a check on the
    painted line itself catches it.
    """
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        painted = [line for line in rendered(app)[0] if "│" in line]
        orphans = [
            line
            for line in painted
            if line.split("│")[1].strip() in (INERT, FIXED, LIVE)
        ]
        assert orphans == [], f"rows wrapped: {orphans}"
        for setting in config_rows(Config()):
            assert any(
                setting.label in line and setting.status in line for line in painted
            ), f"{setting.label} and its marker are not on one line"
