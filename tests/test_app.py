import pytest
from textual.geometry import Size
from textual.widgets import Static

from squelch.app import (
    MAX_MESSAGES,
    FeedRow,
    MessageLog,
    SquelchApp,
    _fit,
)
from squelch.config import Config
from squelch.feeds import Feed

SIZE = (48, 42)


class FakeSession:
    def __init__(self, ident, label, *, muted=True, state="live"):
        self.feed = Feed(ident=ident, label=label)
        self.name = label.replace("KPDX ", "")
        self.muted = muted
        self.state = state

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted


def sessions(n=3, **kwargs):
    names = [
        ("kpdx3_twr", "KPDX Tower (Both)"),
        ("kpdx3_gnd", "KPDX Ground"),
        ("kpdx_app_124350", "KPDX Approach (Final) #1"),
        ("kpdx3_atis", "KPDX ATIS"),
        ("kpdx3_del", "KPDX Clearance Delivery"),
    ]
    out = []
    for i in range(n):
        ident, label = names[i % len(names)]
        out.append(FakeSession(f"{ident}_{i}" if i >= len(names) else ident, label))
    if out:
        out[0].muted = kwargs.get("first_muted", False)
    return out


def make_app(n=3, **kwargs):
    return SquelchApp(Config(icao="KPDX", feed="kpdx3_twr"), sessions(n, **kwargs))


PANE_WIDTH = SIZE[0]


def rendered(app):
    """Capture what is actually painted.

    Must use the compositor, not screen.render_lines(): in Textual 8.2.8 a
    container's render() returns Blank and children are painted separately,
    so render_lines() reports blank fill for every child widget — which
    would make the content assertions below pass vacuously.
    """
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


def overflowing(app):
    """Widgets laid out wider than squelch's 48-column pane.

    Overflow is invisible to the compositor: render_strips() clips every
    strip to the screen width, so `all(s.cell_length == 48 ...)` only
    restates the size passed to run_test(). Appending `#feeds { width: 200; }`
    to squelch.tcss — a gross overflow of the pane — leaves every such
    assertion green. A widget that does not fit shows up in its own size,
    not in what gets painted.
    """
    return [
        (widget.__class__.__name__, widget.id, widget.outer_size.width)
        for widget in app.screen.query("*")
        if widget.outer_size.width > PANE_WIDTH
    ]


# -- layout ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_sees_mounted_widget_content():
    """Guards the capture helper itself.

    A capture that silently returned blank fill would satisfy every
    cell_length assertion below perfectly.
    """
    app = make_app()
    async with app.run_test(size=SIZE):
        text, _ = rendered(app)
        assert any("Tower (Both)" in line for line in text)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 5, 12, 30])
async def test_layout_fits_48_columns_at_any_feed_count(count):
    app = make_app(count)
    async with app.run_test(size=SIZE):
        _text, strips = rendered(app)
        assert len(strips) == 42
        assert overflowing(app) == []


@pytest.mark.asyncio
async def test_long_names_and_idents_truncate_visibly():
    session = FakeSession(
        "kpdx3_twr_118700_extra_long", "KPDX Tower (Rwy 10L/28R 118.7 and more)"
    )
    app = SquelchApp(Config(icao="KPDX"), [session])
    async with app.run_test(size=SIZE):
        text, _strips = rendered(app)
        assert overflowing(app) == []
        joined = "\n".join(text)
        assert "…" in joined, "a real cut must be marked, not silently clipped"


@pytest.mark.asyncio
async def test_each_feed_shows_its_ident():
    """The ident is the string you would pass to --feed."""
    app = make_app(3)
    async with app.run_test(size=SIZE):
        joined = "\n".join(rendered(app)[0])
        assert "kpdx3_twr" in joined
        assert "kpdx3_gnd" in joined


@pytest.mark.asyncio
async def test_header_counts_feeds_and_live_ones():
    app = make_app(4)
    app._sessions[2].state = "offline"
    async with app.run_test(size=SIZE) as pilot:
        app.set_state(app._sessions[2], "offline")
        await pilot.pause()
        header = rendered(app)[0][0]
        assert "4 feeds" in header
        assert "3 live" in header


@pytest.mark.asyncio
async def test_state_dots_distinguish_live_reconnecting_and_offline():
    app = make_app(3)
    app._sessions[1].state = "reconnecting"
    app._sessions[2].state = "offline"
    async with app.run_test(size=SIZE) as pilot:
        for session in app._sessions:
            app.set_state(session, session.state)
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "●" in joined and "◐" in joined and "○" in joined


# -- mute ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_space_toggles_mute_on_the_selected_feed_only():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        before = [s.muted for s in app._sessions]
        await pilot.press("space")
        after = [s.muted for s in app._sessions]
        assert after[0] != before[0], "the selected feed should have toggled"
        assert after[1:] == before[1:], "no other feed may be touched"


@pytest.mark.asyncio
async def test_muted_feeds_are_dimmed_but_keep_metering():
    """Muting is an audio gate, not a pause."""
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        row = app._rows[id(app._sessions[1])]
        assert app._sessions[1].muted is True
        assert row.has_class("muted"), "a muted feed must render dimmed"

        for level in (-50.0, -20.0, -8.0):
            app.set_level(app._sessions[1], level)
        await pilot.pause()
        assert len(row._history) == 3, "a muted feed must keep metering"


@pytest.mark.asyncio
async def test_unmuting_removes_the_dim_class():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app._selected = 1
        app._apply_selection()
        await pilot.press("space")
        await pilot.pause()
        assert not app._rows[id(app._sessions[1])].has_class("muted")


# -- selection and scrolling ----------------------------------------------


@pytest.mark.asyncio
async def test_arrows_move_the_selection_and_clamp_at_the_ends():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        assert app._selected == 0
        await pilot.press("up")
        assert app._selected == 0, "must not wrap past the top"
        await pilot.press("down")
        await pilot.press("down")
        assert app._selected == 2
        await pilot.press("down")
        assert app._selected == 2, "must not wrap past the bottom"


@pytest.mark.asyncio
async def test_only_the_selected_row_carries_the_selection_class():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("down")
        await pilot.pause()
        selected = [
            index
            for index, session in enumerate(app._sessions)
            if app._rows[id(session)].has_class("selected")
        ]
        assert selected == [1]


@pytest.mark.asyncio
async def test_selection_scrolls_a_feed_past_the_viewport_into_view():
    """More feeds than fit is the case the stack was designed for.

    Asserts the selected feed is actually *rendered*, not merely that the
    container scrolled: Textual's own VerticalScroll answers arrow keys
    too, so `scroll_y > 0` is true whether or not we scroll the selection
    into view — an assertion on it passes with the behaviour removed.
    """
    app = make_app(20)
    async with app.run_test(size=SIZE) as pilot:
        last = app._sessions[-1]
        assert last.feed.ident not in "\n".join(rendered(app)[0]), (
            "the last feed should start below the fold, or this proves nothing"
        )
        for _ in range(19):
            await pilot.press("down")
        await pilot.pause()

        assert app._selected == 19
        joined = "\n".join(rendered(app)[0])
        assert last.feed.ident in joined, (
            "the selection moved to a feed that was never scrolled into view"
        )
        assert overflowing(app) == []


# -- messages --------------------------------------------------------------


@pytest.mark.asyncio
async def test_warn_for_names_the_feed_it_belongs_to():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app.warn_for(app._sessions[1], "could not resolve feed")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "Ground" in joined and "could not resolve feed" in joined


@pytest.mark.asyncio
async def test_messages_are_capped():
    app = make_app(2)
    async with app.run_test(size=SIZE) as pilot:
        for i in range(MAX_MESSAGES + 25):
            app.warn(f"message {i}")
        await pilot.pause()
        assert len(app.query_one("#messages", MessageLog).children) == MAX_MESSAGES
        assert len(app._entries) == MAX_MESSAGES


@pytest.mark.asyncio
async def test_messages_do_not_squeeze_the_feeds_off_screen():
    """The log is height:auto with a cap, so feeds keep their rows."""
    app = make_app(6)
    async with app.run_test(size=SIZE) as pilot:
        for i in range(40):
            app.warn(f"message {i}")
        await pilot.pause()
        text, _strips = rendered(app)
        assert overflowing(app) == []
        assert any("Tower (Both)" in line for line in text), (
            "warnings pushed every feed out of the pane"
        )


# -- helpers ---------------------------------------------------------------


def test_fit_pads_short_text_and_marks_real_cuts():
    assert _fit("ab", 5) == "ab   "
    assert _fit("abcdef", 4) == "abc…"
    assert _fit("abcd", 4) == "abcd"
    assert _fit("abc", 0) == ""


@pytest.mark.asyncio
async def test_teardown_is_quiet_after_the_app_exits():
    """The clock timer outlives the widgets it refreshes."""
    app = make_app(3)
    async with app.run_test(size=SIZE):
        pass
    app._tick_clock()
    app.set_level(app._sessions[0], -10.0)
    app.set_state(app._sessions[0], "offline")
    app.warn("after teardown")


@pytest.mark.asyncio
async def test_an_empty_feed_list_does_not_crash_the_pane():
    app = SquelchApp(Config(icao="KPDX"), [])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("down")
        await pilot.press("space")
        await pilot.pause()
        assert overflowing(app) == []


@pytest.mark.asyncio
async def test_feed_row_renders_before_any_level_arrives():
    app = make_app(2)
    async with app.run_test(size=SIZE):
        row = app._rows[id(app._sessions[0])]
        assert isinstance(row, FeedRow)
        assert isinstance(row._name_widget, Static)
        text, _ = rendered(app)
        assert any("▁" in line for line in text), "an idle meter reads as a flat line"
