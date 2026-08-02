import threading

import pytest
from textual.geometry import Size

from squelch.__main__ import feed_selection_hint
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
        Config(),
        feed_label="Portland Tower",
        frequency="118.10",
        feed_loader=lambda: [long_feed],
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
        Config(), feed_label="Portland Tower", frequency="118.10", feed_loader=boom
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
        Config(), feed_label="Portland Tower", frequency="118.10",
        feed_loader=slow_loader,
    )
    try:
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("f")
            # The loader is still blocked. The UI must remain responsive.
            await pilot.press("space")
            await pilot.pause()
            text, _strips = rendered(app)
            assert "MUTED" in "\n".join(text), (
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
async def test_selection_hint_names_the_ident_and_the_flag():
    """Selecting a feed must tell the user what to do about it.

    Restarting the stream in place is out of scope for v1, but the picker
    used to be wired to a no-op default that `__main__` never replaced --
    selecting a feed produced no visible effect whatsoever. `main()` now
    installs `feed_selection_hint`; this exercises that same wiring end to
    end through the real picker.
    """
    app = make_app()
    app.on_feed_selected = lambda feed: app.warn(feed_selection_hint(feed))
    async with app.run_test(size=SIZE) as pilot:
        await open_picker(pilot, app)
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        text, strips = rendered(app)
        joined = "\n".join(text)
        assert "kpdx_gnd" in joined, "the message must name the chosen feed"
        assert "--feed" in joined, "the message must name the flag that starts it"
        assert all(s.cell_length == 48 for s in strips)


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
        Config(), feed_label="Portland Tower", feed_loader=lambda: FEEDS
    )
    with pytest.raises(RuntimeError):
        app.call_from_thread(app._present_feeds, FEEDS)  # the raw hazard
    SquelchApp._load_feeds.__wrapped__(app)  # must not raise
