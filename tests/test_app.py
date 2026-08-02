import pytest
from textual.containers import VerticalScroll
from textual.geometry import Size
from textual.widgets import Static

from squelch.app import (
    MAX_MESSAGES,
    MessageLog,
    SquelchApp,
    meter_bar,
)
from squelch.config import Config

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
async def test_reconnecting_state_is_visible():
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        app.set_state("reconnecting")
        await pilot.pause()
        text, strips = rendered(app)
        assert "RECONNECTING" in "\n".join(text)
        assert all(s.cell_length == 48 for s in strips)


@pytest.mark.asyncio
async def test_offline_state_does_not_claim_live():
    """The header must not keep reading "● LIVE" once nothing is playing.

    Regression guard for Task 9's feed-resolution-failure path: when
    `resolve_stream()` fails, `__main__.py` calls `set_state("offline")` so
    the header shows the truth alongside the warning already printed to
    the transcript. Before this, any unrecognized state string silently
    fell back to "LIVE" -- the app would look alive while dead, exactly
    the failure mode error handling exists to prevent.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        app.set_state("offline")
        await pilot.pause()
        text, strips = rendered(app)
        joined = "\n".join(text)
        assert "OFFLINE" in joined
        assert "LIVE" not in joined
        assert all(s.cell_length == 48 for s in strips)


@pytest.mark.asyncio
async def test_header_never_exceeds_48_cells_for_pathological_state():
    """_refresh_header's 48-cell invariant must hold structurally, not just
    for the two state strings ("LIVE", "RECONNECTING") that the app itself
    ever produces via set_state().

    Regression test: at the boundary where `right` (the state glyph plus
    text) reaches or exceeds 48 characters, `content_room` collapses to 0
    but the old code still emitted `" " + right` unconditionally -- 49+
    cells for a `right` that is itself >=48 chars, silently violating the
    layout's core invariant. There is no public way to make set_state()
    produce such a string today, so this reaches into the private `_state`
    attribute directly to exercise the boundary the fix targets.

    This asserts on the literal string _refresh_header passes to
    `Static.update()`, captured by wrapping the header widget's own
    `update` method, rather than on the compositor-rendered strip. An
    earlier version of this test asserted `strips[0].cell_length == 48`
    and passed even with the fix fully reverted: Textual's test harness
    always renders to the fixed `Size(48, 42)` requested by `run_test`, so
    the compositor pads/clips whatever `_refresh_header` produced back to
    exactly 48 cells regardless of whether the composition itself was
    correct -- with the fix reverted, the actual (unclipped) string was
    `' ●' + 'X' * 199` (201 cells), silently truncated by the framework
    rather than composed correctly by us. Capturing the raw argument to
    `update()` is the only way to see what `_refresh_header` itself
    computed.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        header = app.query_one("#header", Static)
        composed: list[str] = []
        original_update = header.update

        def capture(content, **kwargs):
            composed.append(content)
            return original_update(content, **kwargs)

        header.update = capture

        app._state = "X" * 200
        app._refresh_header()
        await pilot.pause()

        assert composed, "_refresh_header must call Static.update()"
        assert len(composed[-1]) == 48, (
            f"_refresh_header composed a {len(composed[-1])}-cell string "
            f"({composed[-1]!r}), not 48 -- the compositor's own fixed-size "
            "rendering cannot be trusted to catch this; the composed "
            "string itself must be exactly 48 cells"
        )


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

    This is a sweep, not a single case: it also covers the *exact-fit*
    boundary, where the label's length lands precisely on the pre-fix `room`
    value. That length used to slip past the old `len(left) > room` check
    untruncated -- ljust(room) is a no-op on a string already `room` chars
    long -- so nothing ever reserved a separating column, and the label
    butted straight into "●" (e.g. "...118.10● LIVE") despite never
    triggering the "too long" branch at all. `content_room` (`room - 1`)
    fixes this by reserving that column unconditionally; the sweep below
    checks a label exactly at the old `room` boundary (must now truncate),
    a label exactly at the new `content_room` boundary (must fit with no
    truncation, but still get the separator), and one comfortably short of
    it (existing untruncated case).
    """
    long_label = "Seattle Approach East Sector Combined Frequency Two"
    frequency = "118.10"
    for state, state_text in (("live", "LIVE"), ("reconnecting", "RECONNECTING")):
        right = f"● {state_text} "
        room = 48 - len(right)  # pre-fix boundary: used to allow collision
        content_room = room - 1  # post-fix boundary: exact fit, no truncation

        def label_of_left_length(target_left_len: int) -> str:
            # left = " " + label + "  " + frequency
            return "X" * (target_left_len - 3 - len(frequency))

        cases = {
            "comfortably short": label_of_left_length(room - 10),
            "exact new boundary (content_room, no truncation expected)":
                label_of_left_length(content_room),
            "exact old boundary (room, must now truncate)":
                label_of_left_length(room),
            "descriptive long label": long_label,
        }
        for case_name, label in cases.items():
            app = SquelchApp(Config(), feed_label=label, frequency=frequency)
            async with app.run_test(size=SIZE) as pilot:
                app.set_state(state)
                await pilot.pause()
                text, strips = rendered(app)
                header = text[0]
                assert strips[0].cell_length == 48, case_name
                state_pos = header.index("●")
                assert header[state_pos - 1] == " ", (
                    f"[{case_name}, state={state}] label must never collide "
                    "straight into the state glyph -- a separating space is "
                    "required unconditionally, not only when truncation "
                    "happens to trigger"
                )

        # The descriptive long label and the label truncated at the old
        # `room` boundary must both show visible truncation, ellipsis
        # followed immediately by the guaranteed separator space.
        for label in (long_label, label_of_left_length(room)):
            app = SquelchApp(Config(), feed_label=label, frequency=frequency)
            async with app.run_test(size=SIZE) as pilot:
                app.set_state(state)
                await pilot.pause()
                text, strips = rendered(app)
                header = text[0]
                assert "…" in header
                ellipsis_pos = header.index("…")
                assert header[ellipsis_pos + 1] == " ", (
                    "ellipsis must be followed by a separating space, not "
                    "glued straight into the state glyph"
                )


# -- final-fix regression tests -------------------------------------------


@pytest.mark.asyncio
async def test_header_does_not_claim_live_before_any_audio():
    """A freshly constructed app has received nothing; it must not say LIVE.

    Regression test: `_state` was initialised to "LIVE", so the pane read
    "● LIVE" from the very first frame drawn -- through the entire model
    load, which on a first run is a ~1.5 GB download taking minutes. A
    blank transcript under a confident "LIVE" reads as a broken feed, and
    the natural reaction is to kill it.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text, strips = rendered(app)
        joined = "\n".join(text)
        assert "LIVE" not in joined, (
            "the header claimed LIVE before a single frame had arrived"
        )
        assert "STARTING" in joined
        assert all(s.cell_length == 48 for s in strips)


@pytest.mark.asyncio
async def test_on_start_runs_once_the_app_is_running():
    """The pipeline hook must fire from on_mount, not before App.run().

    Regression test: `__main__` used to start the pipeline thread and only
    then call `app.run()`. The thread's first statement is a warn(), which
    reaches `call_from_thread` before the loop is up, raises
    RuntimeError("App is not running"), and is swallowed -- so the
    "loading transcription model" message was lost 100% of the time. A hook
    invoked from on_mount is by construction after the app is running, and
    that is what this asserts: the warn issued from inside on_start is
    actually on screen.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    app.on_start = lambda: app.warn("loading transcription model")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text, _strips = rendered(app)
        assert "loading transcription model" in "\n".join(text)


@pytest.mark.asyncio
async def test_chrome_widgets_are_cached_not_requeried():
    """set_level runs for the app's whole lifetime; it must not query the DOM.

    A DOM query per meter tick is pure overhead billed to the audio thread
    (set_level is reached via call_from_thread, which the audio thread
    blocks on).
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        queries = []
        original = app.query_one

        def counting_query_one(*args, **kwargs):
            queries.append(args)
            return original(*args, **kwargs)

        app.query_one = counting_query_one
        for _ in range(20):
            app.set_level(-25.0)
        app.set_state("live")
        app.action_toggle_mute()
        await pilot.pause()
        assert queries == [], (
            f"chrome updates must use cached widget references, got {queries!r}"
        )


@pytest.mark.asyncio
async def test_clock_tick_after_teardown_does_not_raise():
    """The 1 s interval timer outlives the widgets it refreshes.

    Regression test: `_tick_clock` -> `_refresh_meter` -> `query_one("#meter")`
    raised `NoMatches` when the timer fired during shutdown, after the
    widget had been unmounted. That exception propagated out of App.run(),
    so `main()` never reached `player.stop()` and the PortAudio stream was
    left open.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
    # The app is fully torn down here -- exactly the state the timer can
    # fire in.
    app._tick_clock()
    app.set_level(-20.0)
    app.set_state("reconnecting")
    app.warn("late warning with nowhere to go")


@pytest.mark.asyncio
async def test_clock_timer_is_stopped_on_unmount():
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app._clock_timer is not None
    assert app._clock_timer is None, "the clock timer must be stopped at unmount"


@pytest.mark.asyncio
async def test_long_startup_warnings_stay_within_48_columns():
    """The new startup messages are long; the pane budget still holds."""
    from squelch.__main__ import FFMPEG_MISSING, feed_selection_hint
    from squelch.feeds import Feed

    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        for message in (
                        FFMPEG_MISSING,
            feed_selection_hint(Feed(ident="kpdx3_twr", label="Portland Tower")),
        ):
            app.warn(message)
            await pilot.pause()
        app.set_state("offline")
        await pilot.pause()
        text, strips = rendered(app)
        assert all(s.cell_length == 48 for s in strips)
        joined = "\n".join(text)
        # The messages wrap, so match on fragments that survive wrapping.
        assert "ffmpeg not found on PATH" in joined
        assert "restart with" in joined




# The transcript is gone, but the message log it became still has to do the
# three things the transcript tests covered: keep long messages inside the
# 48-column budget with a consistent indent, cap retention so an hours-long
# run does not grow without bound, and scroll new messages into view.


@pytest.mark.asyncio
async def test_long_warning_wraps_with_a_consistent_indent():
    """Continuation lines must share the first line's indent.

    A literal two-space prefix only indents the first line; once the text
    wraps, continuation lines start flush left and the message reads
    ragged. The indent comes from the widget's `padding-left` instead, so
    it applies to every wrapped line.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        app.warn(
            "could not resolve feed kpdx3_twr — check the ident, and press "
            "[f] to list the feeds this airport actually publishes"
        )
        await pilot.pause()
        text, strips = rendered(app)
        assert all(s.cell_length == 48 for s in strips)

        body = [line for line in text if line.strip()]
        wrapped = [
            line for line in body if "check the ident" in line or "publishes" in line
        ]
        assert wrapped, "the message did not wrap; widen the test input"
        indents = {len(line) - len(line.lstrip()) for line in wrapped}
        assert len(indents) == 1, f"wrapped lines disagree on indent: {indents}"
        assert indents.pop() > 1, "continuation lines lost their indent"


@pytest.mark.asyncio
async def test_messages_are_capped():
    """Mounted widgets are never reclaimed by Textual on their own.

    Without a cap, RSS grows linearly and every set_level gets slower,
    because a refresh scales with the number of mounted children — a cost
    billed to the audio thread, which blocks waiting for it.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        for i in range(MAX_MESSAGES + 40):
            app.warn(f"message {i}")
        await pilot.pause()

        log = app.query_one("#messages", MessageLog)
        assert len(log.children) == MAX_MESSAGES
        assert len(app._entries) == MAX_MESSAGES

        text = "\n".join(rendered(app)[0])
        assert "message 0" not in text, "the oldest message should have been dropped"
        assert f"message {MAX_MESSAGES + 39}" in text


@pytest.mark.asyncio
async def test_new_messages_are_scrolled_into_view_when_the_log_is_full():
    """A warning below the fold is a warning nobody sees.

    Regression test: messages used to mount without scrolling, so once the
    log had filled the pane, "could not load feeds" landed below the
    viewport — pressing `f` with a dead network looked exactly like
    pressing a key that does nothing.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        for i in range(30):  # comfortably more than the pane's height
            app.warn(f"filler {i}")
        await pilot.pause()
        app.warn("could not load feeds")
        await pilot.pause()

        text, strips = rendered(app)
        assert "could not load feeds" in "\n".join(text), (
            "the warning was mounted below the viewport and never scrolled "
            "into view"
        )
        assert all(s.cell_length == 48 for s in strips)


@pytest.mark.asyncio
async def test_scrolling_up_suspends_following_and_returning_resumes_it():
    """Reading back must not be interrupted by an incoming message."""
    app = SquelchApp(Config(), feed_label="Portland Tower", frequency="118.10")
    async with app.run_test(size=SIZE) as pilot:
        for i in range(40):
            app.warn(f"filler {i}")
        await pilot.pause()

        log = app.query_one("#messages", MessageLog)
        log.scroll_to(y=0, animate=False)
        await pilot.pause()
        assert log._follow is False, "a user scroll must suspend following"

        parked = log.scroll_y
        app.warn("arriving while you read")
        await pilot.pause()
        assert log.scroll_y == parked, "an incoming message yanked the view"

        log.scroll_to(y=log.max_scroll_y, animate=False)
        await pilot.pause()
        assert log._follow is True, "returning to the bottom must resume following"
