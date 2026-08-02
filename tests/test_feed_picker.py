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
    """Selecting must map to the row actually navigated to, not just *a* row.

    Regression guard: asserting only `chosen[0].ident in {f.ident for f in
    FEEDS}` (membership in the whole set) would pass even if selection
    always returned the first feed regardless of navigation -- it can't
    distinguish "picked the right row" from "picked any row". The list
    starts with index 0 highlighted, so two "down" presses land on index 2;
    this asserts the hook receives exactly FEEDS[2], not merely something
    from FEEDS.
    """
    app = make_app()
    chosen = []
    app.on_feed_selected = chosen.append
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("f")
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert chosen == [FEEDS[2]]


@pytest.mark.asyncio
async def test_long_label_and_ident_truncate_visibly_within_row_width():
    """A pathologically long label/ident must fit the row, and any cut must
    be marked -- not silently clipped by the container border.

    Regression test: FeedPicker > ListView is `width: 44` with a `solid`
    border (squelch.tcss), leaving exactly 42 content columns. The row
    format used to be `label[:26]` + " " + `ident[:17]` = 44 characters --
    2 over the container's actual content width -- so an already-truncated
    ident silently lost two more characters with no ellipsis or any
    indication truncation had happened twice. This asserts the rendered row
    both fits (all strips still 48 cells) and shows a visible "…" for a
    label/ident long enough to need cutting, with the exact expected
    truncation (computed independently here, not by calling the
    production helper) so a regression that silently drops extra
    characters would be caught rather than passing by coincidence.
    """
    long_feed = Feed(
        ident="kpdx_extremely_long_ident_value_that_overflows",
        label="KPDX Extremely Long Feed Label That Overflows The Row",
    )
    app = SquelchApp(
        Config(),
        feed_label="Portland Tower",
        frequency="118.10",
        feed_loader=lambda: [long_feed],
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("f")
        await pilot.pause()
        text, strips = rendered(app)
        assert all(s.cell_length == 48 for s in strips)

        row = next(line for line in text if "KPDX Extremely" in line)
        assert "…" in row, (
            "a row long enough to need truncation must show an ellipsis, "
            "not silently drop characters"
        )
        # Independently-computed expected truncation (26-wide label field,
        # 15-wide ident field -- the exact widths that fit 42 content
        # columns), not derived from the production `_fit` helper.
        expected_label = "KPDX Extremely Long Feed …"
        expected_ident = "kpdx_extremely…"
        assert expected_label in row
        assert expected_ident in row
        # And the ident must show its OWN ellipsis -- if the row were still
        # silently clipped by the container border, the ident's tail would
        # just vanish with no "…" of its own, even though `row` (a full,
        # unclipped compositor line) would still contain the raw
        # `_fit(ident, 15)` text next to it.
        ident_pos = row.index(expected_ident)
        assert row[ident_pos + len(expected_ident) - 1] == "…"


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
