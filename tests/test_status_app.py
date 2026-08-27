"""Tests for the status pane app.

Capture uses the compositor, not screen.render_lines(): a container renders
Blank and its children are painted separately, so render_lines() reports
blank fill for every child widget.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from textual.geometry import Size

from kcgx.airports import Airport
from kcgx.status import (
    CONTENT_WIDTH,
    PICKER_HINT,
    PICKER_HINT_SHORT,
    PICKER_POPUP,
    STATUS_ROWS,
    STATUS_WIDTH,
    TICK_SECONDS,
    StatusPane,
    open_picker,
)

SIZE = (STATUS_WIDTH, STATUS_ROWS)

PDX = Airport("KPDX", "PDX", "Portland International Airport", "Portland",
              "OR", "US", 45.5887, -122.598, "large")
ORD = Airport("KORD", "ORD", "Chicago O'Hare International Airport", "Chicago",
              "IL", "US", 41.9786, -87.9048, "large")
# A name that does not fit the design width but does fit a widened pane,
# so the two resize tests below can tell "cut at 46" from "cut at all".
LONG = Airport("KLNG", "LNG", "Somewhere With A Very Long Airport Name Indeed",
               "Nowhere", "ZZ", "US", 0.0, 0.0, "large")
AIRPORTS = [PDX, ORD, LONG]

PDT = timezone(timedelta(hours=-7), "PDT")
T1 = datetime(2026, 8, 2, 19, 55, tzinfo=timezone.utc)
T2 = datetime(2026, 8, 2, 20, 30, tzinfo=timezone.utc)


def rendered(app, size=SIZE):
    strips = app.screen._compositor.render_strips(Size(*size))
    return [s.text for s in strips], strips


def shows(joined, code):
    """Is `code` on screen, drawn as block capitals?

    The tests below were written when the code was printed as text. It is
    the same assertion -- the pane is showing this airport -- so they get a
    spelling of it that survives the change rather than a weaker check.
    """
    from kcgx import bigtext as _bt
    return all(row.rstrip() in joined for row in _bt.render(code) if row.strip())


def make(icaos=("KPDX",), times=(T1,), clicks=None):
    """Build a pane whose resolver and clock are scripted, not real.

    The scripted resolver takes `known` and ignores it: the pane hands its
    own dataset to whatever resolver it was given, and a fake that answers
    from a list has no use for it. What `known` is *for* is checked against
    the real current_icao() below.
    """
    icao_seq = list(icaos)
    time_seq = list(times)

    def resolver(known=None):
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
        assert shows("\n".join(text), "KPDX")


@pytest.mark.asyncio
async def test_it_shows_the_airport_and_both_clocks():
    app = make()
    async with app.run_test(size=SIZE):
        joined = "\n".join(rendered(app)[0])
        assert shows(joined, "KPDX")
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
        assert shows("\n".join(rendered(app)[0]), "KPDX")
        app.tick()
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert shows(joined, "KORD")
        assert "Chicago O'Hare International Airport" in joined


# The longest the timer test below will ever wait, however TICK_SECONDS is
# edited. The bound has to live in the sleep itself, not in the test above:
# a failing test does not stop the run, so `TICK_SECONDS = 3600.0` failed
# that assertion in 0.24s and then sat in a 5400-second sleep regardless.
TICK_WAIT_CEILING = 5.0


def test_the_tick_is_fast_enough_to_be_a_clock():
    """Pins the period, which the timer test below cannot.

    That test sleeps for a multiple of TICK_SECONDS, so a period stretched
    to an hour would not fail it -- capped, it would merely stop proving
    anything. This is what turns that mutation into a failure, and it is
    the real requirement anyway: a clock showing minutes has to repaint
    well inside a minute.
    """
    assert 0 < TICK_SECONDS <= TICK_WAIT_CEILING


@pytest.mark.asyncio
async def test_the_pane_ticks_by_itself_with_nobody_driving_it():
    """The one test that waits for the real timer instead of calling tick().

    Every other test here calls `app.tick()` by hand, so all of them stay
    green with `set_interval` deleted or its period set to an hour -- and a
    pane that only paints once is a frozen clock and an airport that never
    catches up with `kcgx go`. This one sleeps past a tick boundary and
    asserts the pane moved on its own, which is the only way that line is
    protected.

    Real wall-clock time, deliberately: Textual's timers run on the event
    loop this test shares, so a scripted clock would prove nothing about
    whether anything is scheduled.

    Capped at TICK_WAIT_CEILING so that editing TICK_SECONDS can never hang
    the suite -- past that the wait stops being long enough to prove
    anything, but test_the_tick_is_fast_enough_to_be_a_clock has already
    failed by then and says why.
    """
    app = make(icaos=("KPDX", "KORD"))
    async with app.run_test(size=SIZE) as pilot:
        assert shows("\n".join(rendered(app)[0]), "KPDX")

        await asyncio.sleep(min(TICK_SECONDS, TICK_WAIT_CEILING) * 1.5)
        await pilot.pause()

        joined = "\n".join(rendered(app)[0])
        assert shows(joined, "KORD"), "the pane never ticked without being told to"
        assert "Chicago O'Hare International Airport" in joined


@pytest.mark.asyncio
async def test_an_unknown_icao_shows_the_bare_code():
    app = make(icaos=("ZZZZ",))
    async with app.run_test(size=SIZE):
        assert shows("\n".join(rendered(app)[0]), "ZZZZ")


@pytest.mark.asyncio
async def test_an_unknown_remembered_icao_falls_back_where_the_launcher_pointed(
    tmp_path,
):
    """The pane must not contradict the cockpit it is describing.

    bin/kcgx resolves through `current_icao(known=...)`, so a remembered
    ICAO the dataset no longer has is skipped and adsb-tui and squelch are
    pointed at the next source. The pane called the same function without
    the predicate, so with ZZZZ remembered you got radar and audio on
    Portland and a status line reading ZZZZ -- one function, two spellings,
    which is the failure current_icao() was written to make impossible.

    Both sources are unknown here, so the answer is FALLBACK_ICAO, and the
    config loader is scripted so the assertion does not depend on whether
    the developer happens to have a ~/.config/squelch/squelch.toml.
    """
    from functools import partial

    from squelch.config import Config

    from kcgx.state import FALLBACK_ICAO, current_icao

    state = tmp_path / "airport"
    state.write_text("ZZZZ\n")

    app = StatusPane(
        resolver=partial(
            current_icao, path=state, config_loader=lambda: Config(icao="ZZZZ")
        ),
        airports_loader=lambda: AIRPORTS,
        now=lambda: (T1, T1.astimezone(PDT)),
        opener=lambda: None,
    )
    async with app.run_test(size=SIZE):
        joined = "\n".join(rendered(app)[0])
        assert not shows(joined, "ZZZZ"), "the pane is naming an airport nothing else is on"
        assert FALLBACK_ICAO == "KPDX"
        assert shows(joined, "KPDX")
        assert "Portland International Airport" in joined


@pytest.mark.asyncio
async def test_a_failing_resolver_keeps_the_last_known_airport_and_the_clock_still_ticks():
    """The airport half of tick() must not take the clock half down with it.

    A corrupt state file (UnicodeDecodeError) or any other resolver failure
    must not kill the pane on the very tick it happens: the airport we last
    knew stays on screen, and the clock -- which does not depend on the
    resolver at all -- keeps advancing.
    """
    calls = {"n": 0}

    def flaky_resolver(known=None):
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
        assert shows(joined, "KPDX")
        assert "1955Z" in joined

        app.tick()
        await pilot.pause()

        assert app.is_running
        joined = "\n".join(rendered(app)[0])
        assert shows(joined, "KPDX")
        assert "2030Z" in joined


@pytest.mark.asyncio
async def test_a_failing_clock_keeps_the_last_known_time_and_the_airport_still_updates():
    """The mirror of the resolver test: tick() must be symmetric.

    A `now` that raises (never happens with the real now_pair(), but
    tick() must not depend on that) must not skip the airport update, and
    must not kill the pane either -- the last-known clock stays on screen.
    """
    icaos = ["KPDX", "KORD"]

    def resolver(known=None):
        return icaos[0] if len(icaos) == 1 else icaos.pop(0)

    calls = {"n": 0}

    def flaky_now():
        calls["n"] += 1
        if calls["n"] == 1:
            return T1, T1.astimezone(PDT)
        raise RuntimeError("clock unavailable")

    app = StatusPane(
        resolver=resolver,
        airports_loader=lambda: AIRPORTS,
        now=flaky_now,
        opener=lambda: None,
    )
    async with app.run_test(size=SIZE) as pilot:
        joined = "\n".join(rendered(app)[0])
        assert shows(joined, "KPDX")
        assert "1955Z" in joined

        app.tick()
        await pilot.pause()

        assert app.is_running
        joined = "\n".join(rendered(app)[0])
        assert shows(joined, "KORD")
        assert "Chicago O'Hare International Airport" in joined
        assert "1955Z" in joined


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
        resolver=lambda known=None: "KPDX",
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
async def test_a_narrowed_pane_cuts_visibly_and_degrades_the_hint():
    """Every splitter here is drag-resizable, so 48 columns is a default.

    Formatting to CONTENT_WIDTH regardless left tmux to do the cutting,
    and tmux just clips: line 1 lost its trailing words with no ellipsis
    to say so, and the hint was chopped mid-string ("▾ airport") rather
    than degrading to "▾" -- which meant PICKER_HINT_SHORT, the
    degradation the pane is designed around and test_status_format.py
    checks, could not be reached at any width in the running app.

    The explicit tick is the point of on_mount's first paint: it happens
    before the first layout, when every widget still reports width 0, so
    the design width stands in for exactly one frame.
    """
    narrow = (30, STATUS_ROWS)
    app = make()
    async with app.run_test(size=narrow) as pilot:
        app.tick()
        await pilot.pause()
        joined = "\n".join(rendered(app, narrow)[0])
        assert "…" in joined, "the pane was cut by tmux, not by fit()"
        assert PICKER_HINT not in joined
        assert PICKER_HINT_SHORT in joined


@pytest.mark.asyncio
async def test_a_widened_pane_uses_the_room_it_was_given():
    """The other half: line 1 stopped at 46 while line 2 stretched."""
    assert len(f"{LONG.icao}  {LONG.name}") > CONTENT_WIDTH, (
        "this name has to be one the design width would cut"
    )
    wide = (80, STATUS_ROWS)
    app = make(icaos=("KLNG",))
    async with app.run_test(size=wide) as pilot:
        app.tick()
        await pilot.pause()
        joined = "\n".join(rendered(app, wide)[0])
        assert LONG.name in joined, "line 1 stopped at the design width"
        assert "…" not in joined


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
    """One spelling, or the hint text drifts from what the key does.

    Token lists, not substrings. `token in bind` asked only whether each
    character sequence appeared *somewhere* in the line, which every digit
    and short flag does by accident: a 6x2 popup passed, because "6" and
    "2" are inside "64" and "20", and so did running bare `kcgx` instead of
    `kcgx go`, because "kcgx" is a prefix of it. Either one leaves the hint
    reading "^b a" while the click does something else, or nothing usable
    -- exactly what this test exists to rule out. shlex, not .split(), so
    the quoted "kcgx go" stays one argument on both sides.
    """
    import shlex
    from pathlib import Path

    conf = (Path(__file__).resolve().parent.parent / "kcgx.tmux.conf").read_text()
    bind = next(
        line for line in conf.splitlines() if line.strip().startswith("bind a ")
    )
    tokens = shlex.split(bind)
    assert tokens[:2] == ["bind", "a"], bind
    assert tokens[2:] == list(PICKER_POPUP), (
        f"kcgx.tmux.conf runs {tokens[2:]}, the click runs {list(PICKER_POPUP)}"
    )


def test_open_picker_shells_out_to_tmux():
    calls = []
    open_picker(run=lambda argv, **kw: calls.append(argv))
    assert calls == [("tmux", *PICKER_POPUP)]


# ---------------------------------------------------------------------------
# The ICAO as block capitals
#
# The code is what you read from across the room, so it is drawn rather
# than printed. That has two consequences the tests below pin: the literal
# code is no longer on screen as text, and the pane needs four rows for the
# banner where it used to need one line for the whole airport.

from pathlib import Path            # noqa: E402
import re                           # noqa: E402

from kcgx import bigtext            # noqa: E402
from kcgx.status import banner_text, detail_line   # noqa: E402

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_the_code_is_drawn_as_block_capitals():
    app = make()
    async with app.run_test(size=SIZE):
        joined = "\n".join(rendered(app)[0])
    for row in bigtext.render("KPDX"):
        assert row.rstrip() in joined, f"missing banner row: {row!r}"


@pytest.mark.asyncio
async def test_the_name_line_no_longer_repeats_the_code():
    """The banner carries the code, so printing it again alongside the
    name would spend a line of a four-line pane saying it twice."""
    app = make()
    async with app.run_test(size=SIZE):
        joined = "\n".join(rendered(app)[0])
    assert "Portland International Airport" in joined
    assert "KPDX" not in joined, "the code is still being printed as text"


@pytest.mark.asyncio
async def test_a_pane_too_narrow_for_the_banner_falls_back_to_the_plain_line():
    """Every splitter here is drag-resizable. Narrower than the banner, the
    pane goes back to exactly what it showed before this feature existed --
    a wrapped or clipped banner would be worse than no banner."""
    narrow = (bigtext.width("KPDX") - 1 + 2, STATUS_ROWS)
    app = make()
    async with app.run_test(size=narrow) as pilot:
        # on_mount paints before the first layout, when every widget still
        # reports width 0 and the design width stands in -- so the banner
        # decision on that frame is made against 46 columns, not these.
        app.tick()
        await pilot.pause()
        joined = "\n".join(rendered(app, narrow)[0])
    # The literal string, deliberately: the whole point of the fallback
    # is that the code goes back to being printed rather than drawn.
    assert "KPDX" in joined, "no fallback to the plain code"
    for row in bigtext.render("KPDX"):
        assert row.rstrip() not in joined, "banner drawn into a pane too narrow"


def test_banner_text_is_empty_when_it_will_not_fit():
    assert banner_text("KPDX", bigtext.width("KPDX")) != ""
    assert banner_text("KPDX", bigtext.width("KPDX") - 1) == ""


def test_the_detail_line_carries_the_code_only_when_the_banner_does_not():
    wide = CONTENT_WIDTH
    assert detail_line(PDX, "KPDX", wide, banner="drawn").strip() == PDX.name
    assert detail_line(PDX, "KPDX", wide, banner="").strip().startswith("KPDX")


def test_an_unknown_code_leaves_the_detail_line_blank():
    """The banner still spells the code, so there is nothing to add."""
    assert detail_line(None, "ZZZZ", CONTENT_WIDTH, banner="drawn").strip() == ""


def test_the_launcher_and_the_app_agree_about_the_pane_height():
    """The height is declared twice -- here and in bin/kcgx -- and tmux
    believes the launcher. If they drift, the pane the app formats for is
    not the pane it gets and the banner clips with nothing to show for it.
    """
    source = (REPO / "bin" / "kcgx").read_text()
    match = re.search(r'STATUS_ROWS="\$\{KCGX_STATUS_ROWS:-(\d+)\}"', source)
    assert match, "could not find the launcher's STATUS_ROWS default"
    assert int(match.group(1)) == STATUS_ROWS, (
        f"bin/kcgx defaults to {match.group(1)} rows, status.py says {STATUS_ROWS}"
    )
