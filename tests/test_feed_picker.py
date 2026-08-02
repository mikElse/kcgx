import pytest
from textual.geometry import Size

from squelch.app import SquelchApp
from squelch.config import Config
from squelch.feeds import Feed

SIZE = (48, 42)
FEEDS = [
    Feed(ident="kpdx_twr", label="Portland Tower"),
    Feed(ident="kpdx_gnd", label="Portland Ground"),
    Feed(ident="kpdx_app", label="Portland Approach"),
]


def make_app():
    return SquelchApp(
        Config(), feed_label="Portland Tower", frequency="118.10",
        feed_loader=lambda: FEEDS,
    )


def rendered(app):
    # Same rationale as tests/test_app.py's rendered() helper: Screen.render_
    # lines() returns blank fill for mounted child widgets in Textual 8.2.8,
    # so content assertions against it would fail even though a modal screen
    # (or the base screen) is genuinely showing the expected text. Using the
    # compositor directly is what actually sees painted widget content. Do
    # not "simplify" this back to render_lines() -- see
    # test_app.py::test_capture_sees_mounted_widget_content, which guards
    # this exact helper shape.
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


@pytest.mark.asyncio
async def test_f_opens_picker_listing_feeds():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("f")
        await pilot.pause()
        text, _strips = rendered(app)
        joined = "\n".join(text)
        assert "Portland Ground" in joined
        assert "kpdx_app" in joined


@pytest.mark.asyncio
async def test_picker_stays_within_48_columns():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("f")
        await pilot.pause()
        _text, strips = rendered(app)
        assert all(s.cell_length == 48 for s in strips)


@pytest.mark.asyncio
async def test_escape_dismisses_without_selecting():
    app = make_app()
    chosen = []
    app.on_feed_selected = chosen.append
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert chosen == []


@pytest.mark.asyncio
async def test_selecting_a_feed_invokes_hook():
    app = make_app()
    chosen = []
    app.on_feed_selected = chosen.append
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert len(chosen) == 1
        assert chosen[0].ident in {f.ident for f in FEEDS}


@pytest.mark.asyncio
async def test_loader_failure_shows_message_not_crash():
    def boom():
        raise RuntimeError("network down")

    app = SquelchApp(
        Config(), feed_label="Portland Tower", frequency="118.10", feed_loader=boom
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("f")
        await pilot.pause()
        text, _strips = rendered(app)
        assert "could not load feeds" in "\n".join(text).lower()
