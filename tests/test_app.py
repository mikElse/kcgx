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
        self.level = -96.0
        self.ambient = False
        self.soloed = False
        self.activity = 0.0

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self):
        self.ambient = not self.ambient
        return self.ambient


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
        if i >= len(names):
            ident, label = f"{ident}_{i}", f"{label} #{i}"
        out.append(FakeSession(ident, label))
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
async def test_long_names_truncate_visibly():
    session = FakeSession(
        "kpdx3_twr_118700_extra_long",
        "KPDX Tower (Rwy 10L/28R 118.7 and quite a lot more)",
    )
    app = SquelchApp(Config(icao="KPDX"), [session])
    async with app.run_test(size=SIZE):
        text, _strips = rendered(app)
        assert overflowing(app) == []
        joined = "\n".join(text)
        assert "…" in joined, "a real cut must be marked, not silently clipped"


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

        # The app's own 25 Hz level timer also fires during pause(),
        # which would make the count depend on wall-clock timing. Stop
        # it so this measures _tick_levels and nothing else.
        app._level_timer.stop()
        app._sessions[1].muted = False
        row.refresh_all()
        for level in (-50.0, -20.0, -8.0):
            app._sessions[1].level = level
            app._tick_levels()
        await pilot.pause()
        assert len(row._history) == 3, "an audible feed meters every tick"


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
        assert last.name not in "\n".join(rendered(app)[0]), (
            "the last feed should start below the fold, or this proves nothing"
        )
        for _ in range(19):
            await pilot.press("down")
        await pilot.pause()

        assert app._selected == 19
        joined = "\n".join(rendered(app)[0])
        assert last.name in joined, (
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
    app._tick_levels()
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
        assert any("░" in line for line in text), "an idle meter reads as a flat line"


# -- row states ------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_audible_feed_is_expanded_and_a_muted_one_is_compact():
    app = make_app(3)
    async with app.run_test(size=SIZE):
        audible = app._rows[id(app._sessions[0])]
        muted = app._rows[id(app._sessions[1])]
        assert app._sessions[0].muted is False
        assert audible.expanded is True
        assert audible.has_class("expanded")
        assert muted.expanded is False
        assert muted.has_class("compact")


@pytest.mark.asyncio
async def test_unmuting_grows_the_row_and_muting_shrinks_it():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        row = app._rows[id(app._sessions[1])]
        assert row.outer_size.height == 2, "compact is one line plus its rule"
        app._selected = 1
        app._apply_selection()
        await pilot.press("space")
        await pilot.pause()
        assert row.outer_size.height == 4, "expanded is name, meter, controls"


@pytest.mark.asyncio
async def test_a_compact_row_shows_no_meter():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        session = app._sessions[1]
        for level in (-50.0, -20.0, -8.0):
            session.level = level
            app._tick_levels()
        await pilot.pause()
        row = app._rows[id(session)]
        assert len(row._history) == 0, "a compact row is not polled at all"
        assert not row._meter_widget.display, "and does not draw the meter"


@pytest.mark.asyncio
async def test_the_stack_still_fits_48_columns_in_both_states():
    app = make_app(12)
    async with app.run_test(size=SIZE) as pilot:
        for index in (1, 2, 3):
            app._sessions[index].muted = False
            app._rows[id(app._sessions[index])].refresh_all()
        await pilot.pause()
        # Not `cell_length == 48`: render_strips clips every strip to the
        # screen width, so that assertion only restates run_test(size=...).
        # Overflow shows up in a widget's own size. See overflowing().
        assert overflowing(app) == []


# -- clicking --------------------------------------------------------------


@pytest.mark.asyncio
async def test_clicking_a_row_body_toggles_its_mute():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        session = app._sessions[1]
        assert session.muted is True
        await pilot.click(app._rows[id(session)], offset=(3, 0))
        await pilot.pause()
        assert session.muted is False


@pytest.mark.asyncio
async def test_clicking_a_row_selects_it():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        assert app._selected == 0
        target = app._sessions[2]
        await pilot.click(app._rows[id(target)], offset=(3, 0))
        await pilot.pause()
        # By identity: the click unmutes it, which lifts it up the stack, so
        # `_sessions[2]` is a different feed by the time this runs.
        assert app.selected_session is target


@pytest.mark.asyncio
async def test_clicking_the_ambient_control_does_not_toggle_mute():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        session = app._sessions[1]
        row = app._rows[id(session)]
        content = row.content_region
        x = content.x - row.region.x + 36  # inside the compact [A] span
        await pilot.click(row, offset=(x, content.y - row.region.y))
        await pilot.pause()
        assert session.ambient is True
        assert session.muted is True, "the ambient control is not the mute control"


# -- solo ------------------------------------------------------------------


def mix(app, order=None):
    """Mute state per feed, in a stable order.

    Takes the session list explicitly because `app._sessions` now reorders
    whenever audibility changes -- audible feeds sort to the top. A
    positional assertion against it would be reading a different feed after
    every toggle, so callers capture the discovery order first and pass it.
    """
    return [session.muted for session in (order if order is not None else app._sessions)]


@pytest.mark.asyncio
async def test_solo_mutes_every_other_feed():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        original = list(app._sessions)
        app._selected = 2
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        assert mix(app, original) == [True, True, False, True]


@pytest.mark.asyncio
async def test_solo_restores_the_prior_mix_including_other_unmuted_feeds():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        original = list(app._sessions)
        original[3].muted = False
        before = mix(app, original)
        assert before == [False, True, True, False]
        app._selected = 2
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        await pilot.press("S")
        await pilot.pause()
        assert mix(app, original) == before


@pytest.mark.asyncio
async def test_moving_the_solo_then_disengaging_returns_to_the_pre_solo_mix():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        original = list(app._sessions)
        before = mix(app, original)
        app._selected = app._sessions.index(original[1])
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        app._selected = app._sessions.index(original[3])
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        assert mix(app, original) == [True, True, True, False]
        await pilot.press("S")
        await pilot.pause()
        assert mix(app, original) == before


@pytest.mark.asyncio
async def test_muting_by_hand_during_solo_cancels_it():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        app._selected = 1
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        assert app._solo.active is True
        app._selected = 3
        app._apply_selection()
        await pilot.press("space")
        await pilot.pause()
        assert app._solo.active is False, "a manual mute is a new intent"


@pytest.mark.asyncio
async def test_the_soloed_row_is_marked():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        original = list(app._sessions)
        app._selected = 1
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        assert app._rows[id(original[1])].has_class("soloed")
        assert not app._rows[id(original[0])].has_class("soloed")


@pytest.mark.asyncio
async def test_solo_expands_only_the_soloed_row():
    """Expansion follows audibility, so solo reshapes the whole stack."""
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        original = list(app._sessions)
        app._selected = 2
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        heights = [app._rows[id(s)].outer_size.height for s in original]
        assert heights == [2, 2, 4, 2]


# -- ambient ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_toggles_ambient_on_the_selected_feed_only():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("a")
        await pilot.pause()
        assert [s.ambient for s in app._sessions] == [True, False, False]


@pytest.mark.asyncio
async def test_ambient_does_not_change_mute():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app._selected = 1
        app._apply_selection()
        before = mix(app)
        await pilot.press("a")
        await pilot.pause()
        assert mix(app) == before
        assert app._rows[id(app._sessions[1])].has_class("ambient")


# -- activity sorting ------------------------------------------------------


def set_activity(app, values):
    for session, value in zip(app._sessions, values):
        session.activity = value


@pytest.mark.asyncio
async def test_the_stack_reorders_busiest_first_once_settled():
    """Activity ordering, among feeds of equal audibility.

    Every feed here is muted, so the audible-first tier cannot mask what is
    being tested -- with the default fixture, session 0 is unmuted and would
    lead on audibility alone regardless of its activity.
    """
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        original = list(app._sessions)
        for session in original:
            session.muted = True
        set_activity(app, [0.1, 0.9, 0.5])
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert app._sessions == [original[1], original[2], original[0]]


@pytest.mark.asyncio
async def test_one_tick_is_not_enough_to_reorder():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.9, 0.5])
        original = list(app._sessions)
        app._tick_resort()
        await pilot.pause()
        assert app._sessions == original


@pytest.mark.asyncio
async def test_a_keypress_defers_a_resort():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.9, 0.5])
        original = list(app._sessions)
        for _ in range(2):
            app._tick_resort()
        await pilot.press("down")
        await pilot.pause()
        app._tick_resort()
        await pilot.pause()
        assert app._sessions == original, "the stack must not move under a keypress"


@pytest.mark.asyncio
async def test_the_selection_follows_the_feed_across_a_resort():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("down")
        await pilot.pause()
        selected = app.selected_session
        set_activity(app, [0.1, 0.9, 0.5])
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert app.selected_session is selected, "a resort must not change what is selected"


@pytest.mark.asyncio
async def test_a_resort_moves_the_widgets_not_just_the_list():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.9, 0.5])
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        painted = [row.session for row in app.query(FeedRow)]
        assert painted == app._sessions


@pytest.mark.asyncio
async def test_a_resort_preserves_meter_history():
    """Rows are moved, never remounted."""
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        # The app's own 25 Hz level timer also fires during pause(),
        # which would make the count depend on wall-clock timing. Stop
        # it so this measures _tick_levels and nothing else.
        app._level_timer.stop()
        session = app._sessions[2]
        session.muted = False
        app._rows[id(session)].refresh_all()
        for level in (-20.0, -10.0, -5.0):
            session.level = level
            app._tick_levels()
        set_activity(app, [0.1, 0.9, 0.5])
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert len(app._rows[id(session)]._history) == 3


@pytest.mark.asyncio
async def test_offline_feeds_sink_to_the_bottom():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        original = list(app._sessions)
        # Muted, or the silent feed would lead on audibility rather than
        # sinking -- which is a different behaviour, tested elsewhere.
        for session in original:
            session.muted = True
        set_activity(app, [0.0, 0.4, 0.8])
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert app._sessions[-1] is original[0]


# -- theme -----------------------------------------------------------------

from squelch.themes import METER_PALETTES, TEXTUAL_THEME_PREFIX


@pytest.mark.asyncio
async def test_applying_a_theme_switches_the_textual_theme():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app.apply_theme("matrix")
        await pilot.pause()
        assert app.theme == f"{TEXTUAL_THEME_PREFIX}matrix"


@pytest.mark.asyncio
async def test_applying_a_theme_repaints_every_meter():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app.apply_theme("amber")
        await pilot.pause()
        for row in app.query(FeedRow):
            assert row.palette is METER_PALETTES["amber"]


@pytest.mark.asyncio
async def test_an_unknown_theme_is_ignored():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app.apply_theme("ocean")
        await pilot.pause()
        before = app.theme
        app.apply_theme("chartreuse")
        await pilot.pause()
        assert app.theme == before


@pytest.mark.asyncio
async def test_the_pane_still_fits_48_columns_under_every_theme():
    # Not `cell_length == 48`: render_strips clips every strip to the screen
    # width, so that assertion only restates run_test(size=...). Overflow
    # shows up in a widget's own size. See overflowing().
    for name in METER_PALETTES:
        app = make_app(6)
        async with app.run_test(size=SIZE) as pilot:
            app.apply_theme(name)
            await pilot.pause()
            assert overflowing(app) == [], name


@pytest.mark.asyncio
async def test_no_radar_theme_leaves_the_app_on_its_default():
    """Standalone squelch must not require tmux to start."""
    app = make_app(3)
    async with app.run_test(size=SIZE):
        assert app._radar_theme is None


# -- metering --------------------------------------------------------------


@pytest.mark.asyncio
async def test_expanded_rows_take_a_level_each_tick():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        # The app's own 25 Hz level timer also fires during pause(),
        # which would make the count depend on wall-clock timing. Stop
        # it so this measures _tick_levels and nothing else.
        app._level_timer.stop()
        app._sessions[0].level = -20.0
        app._tick_levels()
        app._tick_levels()
        await pilot.pause()
        assert len(app._rows[id(app._sessions[0])]._history) == 2


@pytest.mark.asyncio
async def test_compact_rows_are_not_polled():
    """A muted feed draws no meter, so drawing one is wasted work."""
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app._sessions[1].level = -20.0
        app._tick_levels()
        await pilot.pause()
        assert len(app._rows[id(app._sessions[1])]._history) == 0


@pytest.mark.asyncio
async def test_the_meter_shows_the_post_compression_level():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app._sessions[0].level = -6.0
        app._tick_levels()
        await pilot.pause()
        assert app._rows[id(app._sessions[0])]._history[-1] == -6.0


@pytest.mark.asyncio
async def test_polling_survives_a_session_with_no_row():
    app = make_app(2)
    async with app.run_test(size=SIZE):
        app._rows.clear()
        app._tick_levels()


# -- audible feeds on top --------------------------------------------------


@pytest.mark.asyncio
async def test_audible_feeds_sit_above_muted_ones():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        # The audible feed is the *quietest*, so activity alone would sink it.
        set_activity(app, [0.0, 0.9, 0.5, 0.1])
        original = list(app._sessions)
        for _ in range(3):
            app._tick_resort()
        await pilot.pause()
        assert app._sessions[0] is original[0], "what you can hear leads"
        assert app._sessions[1:] == [original[1], original[2], original[3]]


@pytest.mark.asyncio
async def test_unmuting_lifts_a_feed_to_the_top_at_once():
    """No settle delay: the move is the direct result of your own keypress."""
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.0, 0.0, 0.9])
        original = list(app._sessions)
        app._selected = 3
        app._apply_selection()
        await pilot.press("space")
        await pilot.pause()
        assert app._sessions[0] is original[3], (
            "unmuted and busiest of the audible pair, so it leads immediately"
        )


@pytest.mark.asyncio
async def test_muting_drops_it_back_in_on_activity():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.0, 0.0, 0.9])
        original = list(app._sessions)
        app._selected = 3
        app._apply_selection()
        await pilot.press("space")
        await pilot.pause()
        assert app._sessions[0] is original[3]
        await pilot.press("space")
        await pilot.pause()
        assert app._sessions[0] is original[0], "the audible feed leads again"
        assert app._sessions[1] is original[3], (
            "muted, it rejoins the sort as the busiest of the muted group"
        )


@pytest.mark.asyncio
async def test_the_selection_still_follows_the_feed_across_an_unmute():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.0, 0.0, 0.9])
        app._selected = 3
        app._apply_selection()
        chosen = app.selected_session
        await pilot.press("space")
        await pilot.pause()
        assert app.selected_session is chosen, (
            "space must keep acting on the feed you just unmuted"
        )


@pytest.mark.asyncio
async def test_solo_puts_the_soloed_feed_on_top():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.9, 0.0, 0.0, 0.0])
        original = list(app._sessions)
        app._selected = 2
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        assert app._sessions[0] is original[2], "the only audible feed leads"


@pytest.mark.asyncio
async def test_an_immediate_reorder_is_not_proposed_again():
    """The Resorter is told, so it does not re-apply what is already there."""
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        set_activity(app, [0.1, 0.0, 0.0, 0.9])
        app._selected = 3
        app._apply_selection()
        await pilot.press("space")
        await pilot.pause()
        after = list(app._sessions)
        for _ in range(4):
            app._tick_resort()
        await pilot.pause()
        assert app._sessions == after, "the order must be stable afterwards"


# -- the footer ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_footer_advertises_config_and_not_feeds_or_quit():
    """`f` and `q` still work; they just no longer spend footer cells."""
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        footer = rendered(app)[0][-1]
        assert "[c] config" in footer
        assert "feeds" not in footer
        assert "quit" not in footer


@pytest.mark.asyncio
async def test_the_unadvertised_keys_still_work():
    """Dropping them from the footer must not drop them from the app --
    `q` is the only way out."""
    app = make_app(3)
    async with app.run_test(size=SIZE):
        actions = {binding[1] for binding in app.BINDINGS}
        assert "quit" in actions
        assert "show_feeds" in actions


@pytest.mark.asyncio
async def test_the_footer_fits_the_pane():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert overflowing(app) == []
