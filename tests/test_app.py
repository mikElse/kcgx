from datetime import datetime

import pytest
from textual.geometry import Size

from squelch.app import SquelchApp, meter_bar
from squelch.config import Config
from squelch.pipeline import Block

SIZE = (48, 42)


def test_meter_bar_silence_is_all_low():
    bar = meter_bar(-96.0, width=20)
    assert len(bar) == 20
    assert set(bar) == {"▁"}


def test_meter_bar_loud_reaches_top():
    assert "█" in meter_bar(-1.0, width=20)


def test_meter_bar_respects_width():
    assert len(meter_bar(-30.0, width=26)) == 26


def rendered(app):
    # Screen.render_lines() only renders the Screen widget's own background
    # (a container's render() returns Blank) -- it does not include mounted
    # children, which are painted separately by the compositor. The
    # compositor is also what Textual's own export_screenshot() reaches into
    # for the same reason, so this is the faithful way to capture what is
    # actually on screen in this Textual version.
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


@pytest.mark.asyncio
async def test_layout_fits_48_columns_exactly():
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE):
        _text, strips = rendered(app)
        assert len(strips) == 42
        assert all(s.cell_length == 48 for s in strips), "no line may exceed 48 cells"


@pytest.mark.asyncio
async def test_long_transcript_wraps_and_does_not_overflow():
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        app.add_block(
            Block(
                started_at=datetime(2026, 8, 2, 14, 31, 42),
                text=(
                    "Alaska four twelve heavy Portland tower wind two eight "
                    "zero at one two runway two eight left cleared to land "
                    "traffic is a Dash Eight on a three mile final"
                ),
            )
        )
        await pilot.pause()
        _text, strips = rendered(app)
        assert all(s.cell_length == 48 for s in strips)


@pytest.mark.asyncio
async def test_block_timestamp_and_text_are_displayed():
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        app.add_block(
            Block(started_at=datetime(2026, 8, 2, 14, 31, 42), text="cleared to land")
        )
        await pilot.pause()
        text, _strips = rendered(app)
        joined = "\n".join(text)
        assert "14:31:42" in joined
        assert "cleared to land" in joined


@pytest.mark.asyncio
async def test_reconnecting_state_is_visible():
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        app.set_state("reconnecting")
        await pilot.pause()
        text, strips = rendered(app)
        assert "RECONNECTING" in "\n".join(text)
        assert all(s.cell_length == 48 for s in strips)


@pytest.mark.asyncio
async def test_mute_toggles_footer_hint():
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("space")
        text, _ = rendered(app)
        assert "MUTED" in "\n".join(text)
