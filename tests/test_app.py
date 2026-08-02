from datetime import datetime

import pytest
from textual.geometry import Size
from textual.widgets import Static

from squelch.app import SquelchApp, meter_bar
from squelch.config import Config
from squelch.pipeline import Block

SIZE = (48, 42)


# meter_bar's shape changed from "repeat one quantised glyph across the
# whole width" to "one glyph per recent sample, oldest at the left, newest
# at the right, scrolling as new samples are pushed" -- a rolling level
# history rather than a uniform block. These three tests replace the three
# that pinned the old uniform-fill behaviour (in particular
# `assert set(bar) == {"▁"}` for a single value, which no longer applies to
# a per-sample history). No other test in this file was changed.


def test_meter_bar_respects_width():
    assert len(meter_bar([-30.0], width=26)) == 26


def test_meter_bar_silence_is_all_low():
    """No samples yet, or an all-silent history: a flat low line, not a gap."""
    assert meter_bar([], width=20) == "▁" * 20
    assert meter_bar([-96.0] * 20, width=20) == "▁" * 20


def test_meter_bar_loud_sample_appears_at_newest_end():
    history = [-96.0] * 19 + [-1.0]
    bar = meter_bar(history, width=20)
    assert bar[-1] == "█"
    assert bar[:-1] == "▁" * 19


def test_meter_bar_scrolls_oldest_sample_off():
    """Once more than `width` samples have been pushed, the oldest is gone."""
    history = [-1.0] + [-96.0] * 20  # 21 samples into a width-20 window
    bar = meter_bar(history, width=20)
    assert "█" not in bar
    assert bar == "▁" * 20


def rendered(app):
    # Deliberately NOT Screen.render_lines(): in Textual 8.2.8 that only
    # renders the Screen widget's own background (a container's render()
    # returns Blank) and never touches mounted children, which are painted
    # separately by the compositor. Calling it here would make every content
    # assertion below fail against blank fill, while cell-width assertions
    # would keep passing "by accident" since blank fill is still 48 cells
    # wide -- a silent false-positive on exactly the width guarantee this
    # file exists to protect. render_strips() is a *public* method on
    # Compositor; the only private surface touched is the `_compositor`
    # attribute itself, which is what Textual's own App.export_screenshot()
    # reaches into for the same reason. Do not "simplify" this back to
    # render_lines() -- see test_capture_sees_mounted_widget_content below,
    # which exists specifically to catch that regression.
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


@pytest.mark.asyncio
async def test_capture_sees_mounted_widget_content():
    """Guard for `rendered()` itself, not for the app.

    test_layout_fits_48_columns_exactly asserts every line is exactly 48
    cells -- a capture that silently returned blank fill (the exact failure
    mode Screen.render_lines has in this Textual version) would satisfy that
    assertion perfectly. Right now that vacuity is only caught indirectly, by
    the content assertions in other tests. This test says "the capture is
    broken" directly: it mounts a known, distinctive string and asserts the
    capture helper actually sees it, so a future Textual version that changes
    the compositor's shape fails here plainly instead of as three unrelated
    -looking layout failures.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        sentinel = "CAPTURE-HELPER-SENTINEL-4271"
        app.query_one("#footer", Static).update(sentinel)
        await pilot.pause()
        text, _strips = rendered(app)
        assert sentinel in "\n".join(text)


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


@pytest.mark.asyncio
async def test_long_label_truncates_with_ellipsis_not_collision():
    """A long feed label must not run straight into the state glyph.

    Regression test: truncation used to be a bare slice, so a long enough
    label produced e.g. "...Approach Eas● RECONNECTING" -- text glued
    directly onto "●" with no separator, reading like a rendering bug rather
    than deliberate truncation. There must be a visible ellipsis and at
    least one space before the state indicator, and the header must still
    be exactly 48 cells for both state widths.
    """
    long_label = "Seattle Approach East Sector Combined Frequency Two"
    for state in ("live", "reconnecting"):
        app = SquelchApp(Config(), feed_label=long_label, frequency="118.10")
        async with app.run_test(size=SIZE) as pilot:
            app.set_state(state)
            await pilot.pause()
            text, strips = rendered(app)
            header = text[0]
            assert strips[0].cell_length == 48
            assert "…" in header
            ellipsis_pos = header.index("…")
            assert header[ellipsis_pos + 1] == " ", (
                "ellipsis must be followed by a separating space, not glued "
                "straight into the state glyph"
            )
