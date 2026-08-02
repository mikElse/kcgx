"""Tests for the status pane app.

Capture uses the compositor, not screen.render_lines(): a container renders
Blank and its children are painted separately, so render_lines() reports
blank fill for every child widget.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from textual.geometry import Size

from kcgx.airports import Airport
from kcgx.status import (
    PICKER_POPUP,
    STATUS_ROWS,
    STATUS_WIDTH,
    StatusPane,
    open_picker,
)

SIZE = (STATUS_WIDTH, STATUS_ROWS)

PDX = Airport("KPDX", "PDX", "Portland International Airport", "Portland",
              "OR", "US", 45.5887, -122.598, "large")
ORD = Airport("KORD", "ORD", "Chicago O'Hare International Airport", "Chicago",
              "IL", "US", 41.9786, -87.9048, "large")
AIRPORTS = [PDX, ORD]

PDT = timezone(timedelta(hours=-7), "PDT")
T1 = datetime(2026, 8, 2, 19, 55, tzinfo=timezone.utc)
T2 = datetime(2026, 8, 2, 20, 30, tzinfo=timezone.utc)


def rendered(app):
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


def make(icaos=("KPDX",), times=(T1,), clicks=None):
    """Build a pane whose resolver and clock are scripted, not real."""
    icao_seq = list(icaos)
    time_seq = list(times)

    def resolver():
        return icao_seq[0] if len(icao_seq) == 1 else icao_seq.pop(0)

    def now():
        t = time_seq[0] if len(time_seq) == 1 else time_seq.pop(0)
        return t, t.astimezone(PDT)

    return StatusPane(
        resolver=resolver,
        airports_loader=lambda: AIRPORTS,
        now=now,
        opener=lambda: (clicks if clicks is not None else []).append("opened"),
    )


@pytest.mark.asyncio
async def test_capture_sees_mounted_widget_content():
    """Guards the capture helper; blank fill would satisfy everything below."""
    app = make()
    async with app.run_test(size=SIZE):
        text, _ = rendered(app)
        assert any("KPDX" in line for line in text)


@pytest.mark.asyncio
async def test_it_shows_the_airport_and_both_clocks():
    app = make()
    async with app.run_test(size=SIZE):
        joined = "\n".join(rendered(app)[0])
        assert "KPDX" in joined
        assert "Portland International Airport" in joined
        assert "1955Z" in joined
        assert "12:55" in joined


@pytest.mark.asyncio
async def test_it_shows_the_picker_affordance():
    app = make()
    async with app.run_test(size=SIZE):
        assert "airport" in "\n".join(rendered(app)[0])


@pytest.mark.asyncio
async def test_the_clock_advances_on_tick():
    app = make(times=(T1, T2))
    async with app.run_test(size=SIZE) as pilot:
        assert "1955Z" in "\n".join(rendered(app)[0])
        app.tick()
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "2030Z" in joined
        assert "1955Z" not in joined


@pytest.mark.asyncio
async def test_a_changed_airport_is_picked_up_on_the_next_tick():
    """This is what lets `kcgx go` leave the status pane alone."""
    app = make(icaos=("KPDX", "KORD"))
    async with app.run_test(size=SIZE) as pilot:
        assert "KPDX" in "\n".join(rendered(app)[0])
        app.tick()
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "KORD" in joined
        assert "Chicago O'Hare International Airport" in joined


@pytest.mark.asyncio
async def test_an_unknown_icao_shows_the_bare_code():
    app = make(icaos=("ZZZZ",))
    async with app.run_test(size=SIZE):
        assert "ZZZZ" in "\n".join(rendered(app)[0])


@pytest.mark.asyncio
async def test_a_failing_resolver_keeps_the_last_known_airport_and_the_clock_still_ticks():
    """The airport half of tick() must not take the clock half down with it.

    A corrupt state file (UnicodeDecodeError) or any other resolver failure
    must not kill the pane on the very tick it happens: the airport we last
    knew stays on screen, and the clock -- which does not depend on the
    resolver at all -- keeps advancing.
    """
    calls = {"n": 0}

    def flaky_resolver():
        calls["n"] += 1
        if calls["n"] == 1:
            return "KPDX"
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    times = [T1, T2]

    def now():
        t = times[0] if len(times) == 1 else times.pop(0)
        return t, t.astimezone(PDT)

    app = StatusPane(
        resolver=flaky_resolver,
        airports_loader=lambda: AIRPORTS,
        now=now,
        opener=lambda: None,
    )
    async with app.run_test(size=SIZE) as pilot:
        joined = "\n".join(rendered(app)[0])
        assert "KPDX" in joined
        assert "1955Z" in joined

        app.tick()
        await pilot.pause()

        assert app.is_running
        joined = "\n".join(rendered(app)[0])
        assert "KPDX" in joined
        assert "2030Z" in joined


@pytest.mark.asyncio
async def test_clicking_the_affordance_opens_the_picker():
    clicks = []
    app = make(clicks=clicks)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.click("#hint")
        await pilot.pause()
    assert clicks == ["opened"], "the click did not reach the opener"


@pytest.mark.asyncio
async def test_clicking_the_clock_does_not_open_the_picker():
    """Only the affordance is a button; the rest of the line is text."""
    clicks = []
    app = make(clicks=clicks)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.click("#clock")
        await pilot.pause()
    assert clicks == []


@pytest.mark.asyncio
async def test_a_failing_opener_does_not_kill_the_pane():
    """Losing the mouse shortcut is not a reason to lose the clock."""
    def boom():
        raise RuntimeError("no tmux here")

    app = StatusPane(
        resolver=lambda: "KPDX",
        airports_loader=lambda: AIRPORTS,
        now=lambda: (T1, T1.astimezone(PDT)),
        opener=boom,
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.click("#hint")
        await pilot.pause()
        assert app.is_running
        assert "1955Z" in "\n".join(rendered(app)[0])


@pytest.mark.asyncio
async def test_no_widget_is_wider_than_the_pane():
    """Overflow is invisible to the compositor.

    render_strips() clips every strip to the screen width, so asserting on
    cell_length only restates the size passed to run_test().
    """
    app = make()
    async with app.run_test(size=SIZE):
        too_wide = [
            (w.__class__.__name__, w.id, w.outer_size.width)
            for w in app.screen.query("*")
            if w.outer_size.width > STATUS_WIDTH
        ]
        assert too_wide == []


def test_the_click_and_the_keybinding_run_the_same_popup():
    """One spelling, or the hint text drifts from what the key does."""
    from pathlib import Path

    conf = (Path(__file__).resolve().parent.parent / "kcgx.tmux.conf").read_text()
    bind = next(
        line for line in conf.splitlines() if line.strip().startswith("bind a ")
    )
    for token in PICKER_POPUP:
        assert token in bind, f"{token!r} missing from: {bind}"


def test_open_picker_shells_out_to_tmux():
    calls = []
    open_picker(run=lambda argv, **kw: calls.append(argv))
    assert calls == [("tmux", *PICKER_POPUP)]
