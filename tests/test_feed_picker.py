import threading

import pytest
from textual.geometry import Size

from squelch.app import FeedPicker, SquelchApp
from squelch.config import Config
from squelch.feeds import Feed

SIZE = (48, 42)


class _FakeSession:
    def __init__(self, ident, label):
        from squelch.feeds import Feed as _Feed

        self.feed = _Feed(ident=ident, label=label)
        self.name = label
        self.muted = True
        self.state = "live"

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted


def _two_sessions():
    return [_FakeSession("a_twr", "Tower"), _FakeSession("a_gnd", "Ground")]
FEEDS = [
    Feed(ident="kpdx_twr", label="Portland Tower"),
    Feed(ident="kpdx_gnd", label="Portland Ground"),
    Feed(ident="kpdx_app", label="Portland Approach"),
]


def _sessions(n):
    """n open sessions. The first len(FEEDS) carry FEEDS' own idents, so a
    pick in the picker resolves to a real row."""
    out = []
    for i in range(n):
        feed = FEEDS[i % len(FEEDS)]
        ident = feed.ident if i < len(FEEDS) else f"{feed.ident}_{i}"
        out.append(_FakeSession(ident, f"Feed {i}"))
    return out


def make_app(n=0):
    return SquelchApp(
        Config(), _sessions(n), feed_loader=lambda: FEEDS,
    )


async def open_picker(pilot, app):
    """Press `f` and wait for the (now threaded) feed load to finish.

    action_show_feeds hands the loader to a Textual thread worker rather
    than calling it inline -- see SquelchApp._load_feeds -- so one
    `pilot.pause()` is no longer sufficient to observe the result.
    """
    await pilot.press("f")
    await app.workers.wait_for_complete()
    await pilot.pause()


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


def overflowing(app):
    """Widgets laid out wider than the 48-column pane.

    Same rationale as tests/test_app.py's helper: render_strips clips every
    strip to the screen width, so a cell_length assertion cannot fail. A
    widget that does not fit shows up in its own size.
    """
    return [
        (widget.__class__.__name__, widget.id, widget.outer_size.width)
        for widget in app.screen.query("*")
        if widget.outer_size.width > SIZE[0]
    ]


@pytest.mark.asyncio
async def test_f_opens_picker_listing_feeds():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, app)
        text, _strips = rendered(app)
        joined = "\n".join(text)
        assert "Portland Ground" in joined
        assert "kpdx_app" in joined


@pytest.mark.asyncio
async def test_picker_stays_within_48_columns():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, app)
        _text, strips = rendered(app)
        assert all(s.cell_length == 48 for s in strips)


@pytest.mark.asyncio
async def test_escape_dismisses_without_selecting():
    app = make_app()
    chosen = []
    app.on_feed_selected = chosen.append
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, app)
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
        await open_picker(pilot, app)
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
        Config(), [], feed_loader=lambda: [long_feed],
    )
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, app)
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
        Config(), [], feed_loader=boom
    )
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, app)
        text, _strips = rendered(app)
        assert "could not load feeds" in "\n".join(text).lower()


@pytest.mark.asyncio
async def test_pressing_f_does_not_block_the_event_loop():
    """The feed fetch must not run on the event loop.

    Regression test: `action_show_feeds` called the injected loader inline.
    In production that loader is an HTTP GET with a 15 s timeout, so a
    flaky network froze Textual's event loop for up to fifteen seconds --
    and because the audio thread reaches the UI through
    `call_from_thread`, which waits on that same loop, playback stopped
    too. Here the loader blocks on an Event; the app must still process
    keystrokes (and repaint) while it is blocked. The Event has its own
    timeout so a regression fails the assertion rather than hanging.
    """
    gate = threading.Event()

    def slow_loader():
        gate.wait(timeout=2.0)
        return FEEDS

    app = SquelchApp(
        Config(), _two_sessions(), feed_loader=slow_loader,
    )
    try:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("f")
            # The loader is still blocked. The UI must remain responsive.
            await pilot.press("down")
            await pilot.pause()
            assert app._selected == 1, (
                "the event loop was blocked by the feed fetch -- keystrokes "
                "(and therefore playback, which marshals through the same "
                "loop) stalled until the loader returned"
            )
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "Portland Ground" in "\n".join(rendered(app)[0]), (
                "the picker must still open once the load completes"
            )
    finally:
        gate.set()


@pytest.mark.asyncio
async def test_pressing_f_three_times_stacks_only_one_picker():
    """Three quick presses of `f` against a slow loader must yield one picker.

    Regression test: `exclusive=True, group="feeds"` marks superseded
    workers cancelled, but Textual cannot interrupt a running thread --
    each worker's thread body kept running regardless and marshalled its
    own result back via `call_from_thread`, so three presses against a
    slow feed fetch produced three stacked `FeedPicker` screens (three
    escapes needed to get back to the main screen), not one. The loader
    is gated on a `threading.Event` under this test's control -- never
    `time.sleep()` -- with its own timeout so a regression fails the
    assertion rather than hanging the suite.
    """
    gate = threading.Event()
    calls: list[int] = []

    def slow_loader():
        calls.append(1)
        gate.wait(timeout=2.0)
        return FEEDS

    app = SquelchApp(
        Config(), [], feed_loader=slow_loader,
    )
    try:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(calls) == 3, "all three presses must reach the loader"
            pickers = [s for s in app.screen_stack if isinstance(s, FeedPicker)]
            assert len(pickers) == 1, (
                f"expected exactly one stacked picker, found {len(pickers)}"
            )
    finally:
        gate.set()


@pytest.mark.asyncio
async def test_picking_a_feed_jumps_to_its_row_end_to_end():
    """Selecting a feed must have a visible effect.

    The picker used to be wired to a no-op default that `__main__` replaced
    with a hint message; it is now a jump list, and the app wires its own
    default. This drives the whole path through the real picker: two rows
    down from the top is FEEDS[1], and the selection must land on the
    session carrying that ident -- not merely change to *something*.
    """
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        assert app._selected == 0
        await open_picker(pilot, app)
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert app.selected_session.feed.ident == FEEDS[1].ident
        assert overflowing(app) == []


def test_feed_worker_never_raises_when_the_app_has_gone():
    """Press `f`, then `q`, while the fetch is still in flight.

    The worker is left holding a result for an app that has already gone;
    `call_from_thread` then raises "App is not running". Nobody needs a
    picker at that point, but uncaught it surfaces as a worker traceback
    printed after the app has exited. Driven against the undecorated worker
    body on a never-started app, which is the same condition without the
    timing.
    """
    app = SquelchApp(
        Config(), [], feed_loader=lambda: FEEDS
    )
    with pytest.raises(RuntimeError):
        app.call_from_thread(app._present_feeds, FEEDS)  # the raw hazard
    SquelchApp._load_feeds.__wrapped__(app)  # must not raise


# -- jump list -------------------------------------------------------------


@pytest.mark.asyncio
async def test_choosing_a_feed_moves_the_selection_to_its_row():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        assert app._selected == 0
        app.jump_to_feed(app._sessions[2].feed)
        await pilot.pause()
        assert app.selected_session is app._sessions[2]


@pytest.mark.asyncio
async def test_choosing_a_feed_that_is_not_open_warns_rather_than_jumping():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        app.jump_to_feed(Feed(ident="knowhere_twr", label="Nowhere Tower"))
        await pilot.pause()
        assert app._selected == 0
        assert len(app._entries) == 1, "an unopenable feed must say so"
        assert "knowhere_twr" in "\n".join(rendered(app)[0])


@pytest.mark.asyncio
async def test_the_picker_still_shows_idents_as_secondary_text():
    """Idents leave the row but not the picker -- squelch.toml still takes one."""
    app = make_app(1)
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, app)
        assert "kpdx_gnd" in "\n".join(rendered(app)[0])
        labels = app.screen.query(".picker-ident")
        assert len(labels) == len(FEEDS), (
            "every picker row must mark its ident as secondary text"
        )
