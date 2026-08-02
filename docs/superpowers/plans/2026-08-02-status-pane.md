# Cockpit Status Pane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cockpit's shell pane with a four-row status pane above
squelch showing the current airport, Zulu and local time, and a clickable
way into the airport picker.

**Architecture:** A small Textual app (`kcgx-status`) renders two lines built
by pure formatting functions. It ticks once a second, re-reading the airport
through the same `kcgx.state.current_icao()` the resolver uses, so no other
component changes to keep it current. `bin/kcgx` gains the third pane and
stops addressing panes by index: each pane is tagged with a tmux
`@kcgx_role` user option and looked up by role.

**Tech Stack:** Python 3.14, Textual 8.2.8, pytest (`asyncio_mode = "auto"`),
bash, tmux 3.7b, uv / `uv_build`.

**Spec:** `docs/superpowers/specs/2026-08-02-status-pane-design.md`

## Global Constraints

- Python `>=3.14`; Textual pinned `>=8.2.8,<9`. **No new runtime dependencies.**
- Run everything through uv from the repo root:
  `cd /Users/mikelse/kcgx && uv run --project . pytest -q`
- The suite is **251 tests** at the start of this plan and must stay green.
- **Textual test capture must use
  `app.screen._compositor.render_strips(Size(w, h))`**, never
  `screen.render_lines()`, which returns blank fill for child widgets.
- **Never assert `cell_length`** to check layout width — the compositor clips
  every strip to the screen width, so such an assertion cannot fail. Assert
  widgets' `outer_size.width`, as
  `tests/test_airport_picker.py::test_no_widget_is_wider_than_the_popup` does.
- **Revert-check every new test**: `git diff` clean before each break, ONE
  break at a time, run the single named test, record the actual output,
  restore with `git checkout --`, confirm `git diff` empty. Never document a
  transcript you have not literally just observed. Nine tests on the previous
  branch turned out to pass with the behaviour they named removed.
- **No test may write to `~/.local/state/kcgx/` or `~/.cache/squelch/`.**
  `tests/conftest.py` has an autouse backstop; do not rely on it alone.
- **The repo owner may have a live cockpit running.** Never run bare `kcgx`,
  `kcgx stop`, or `kcgx go` without `KCGX_SOCKET` set to a private socket.
  Kill any tmux server you create.
- The repo owner commits to this branch from a parallel session. Scope every
  `git add` to files you changed; leave untracked files alone.
- Commit after every task. End each message with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `src/kcgx/status.py` | formatting functions + the Textual status app |
| `tests/test_status_format.py` | the pure formatting functions |
| `tests/test_status_app.py` | the Textual app |

**Modify:**

| Path | Change |
|---|---|
| `pyproject.toml` | `kcgx-status` console script |
| `bin/kcgx` | role tags, three-pane layout, retarget by role, select squelch after `go` |
| `kcgx.tmux.conf` | no change to the binding; it is asserted against `status.py`'s constant |
| `tests/test_kcgx_launcher.py` | layout, roles, retarget-by-role |
| `README.md` | shell pane is gone; document the status pane |

---

### Task 1: The two status lines

Pure functions, no Textual, no clock of their own. Everything the pane
displays is decided here, so it can be tested without a terminal.

**Files:**
- Create: `src/kcgx/status.py`, `tests/test_status_format.py`

**Interfaces:**
- Consumes: `kcgx.airports.Airport` (frozen dataclass: `icao, iata, name,
  city, region, country, lat, lon, size`, plus a `where` property).
- Produces:
  - `STATUS_WIDTH = 48`, `STATUS_ROWS = 4`, `CONTENT_WIDTH = 46`
  - `PICKER_HINT = "▾ airport (^b a)"`, `PICKER_HINT_SHORT = "▾"`
  - `fit(text: str, width: int) -> str`
  - `airport_line(airport: Airport | None, icao: str, width: int) -> str`
  - `clock_text(now_utc: datetime, now_local: datetime) -> str`
  - `hint_for_width(available: int) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_status_format.py`:

```python
"""Tests for the status pane's two lines.

These are pure functions on purpose: everything the pane decides to show is
decided here, where it can be checked without a terminal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kcgx.airports import Airport
from kcgx.status import (
    CONTENT_WIDTH,
    PICKER_HINT,
    PICKER_HINT_SHORT,
    airport_line,
    clock_text,
    fit,
    hint_for_width,
)

PDX = Airport("KPDX", "PDX", "Portland International Airport", "Portland",
              "OR", "US", 45.5887, -122.598, "large")

PDT = timezone(timedelta(hours=-7), "PDT")
UTC_NOON = datetime(2026, 8, 2, 19, 55, tzinfo=timezone.utc)
LOCAL_NOON = UTC_NOON.astimezone(PDT)


def test_fit_pads_short_text_and_marks_real_cuts():
    assert fit("ab", 5) == "ab   "
    assert fit("abcdef", 4) == "abc…"
    assert fit("abcd", 4) == "abcd"
    assert fit("abc", 0) == ""


# -- line 1 ----------------------------------------------------------------


def test_the_airport_line_carries_the_code_and_the_name():
    line = airport_line(PDX, "KPDX", CONTENT_WIDTH)
    assert line.startswith("KPDX")
    assert "Portland International Airport" in line


def test_the_airport_line_is_exactly_the_width_asked_for():
    assert len(airport_line(PDX, "KPDX", CONTENT_WIDTH)) == CONTENT_WIDTH


def test_a_long_name_is_cut_visibly():
    long = Airport("XXXX", "", "A" * 90, "Nowhere", "ZZ", "US", 0.0, 0.0, "large")
    assert "…" in airport_line(long, "XXXX", CONTENT_WIDTH)


def test_an_airport_missing_from_the_dataset_still_shows_its_code():
    """The airport-search work made an unknown ICAO survivable; so does this."""
    line = airport_line(None, "ZZZZ", CONTENT_WIDTH)
    assert line.startswith("ZZZZ")
    assert len(line) == CONTENT_WIDTH


# -- line 2 ----------------------------------------------------------------


def test_the_clock_shows_zulu_then_local():
    text = clock_text(UTC_NOON, LOCAL_NOON)
    assert text.startswith("1955Z")
    assert "12:55" in text
    assert "PDT" in text


def test_zulu_is_four_digits_and_a_z():
    """'1955Z' is what ATC says; '19:55Z' is not."""
    assert clock_text(UTC_NOON, LOCAL_NOON).split()[0] == "1955Z"


def test_midnight_zulu_keeps_its_leading_zeros():
    utc = datetime(2026, 8, 2, 0, 5, tzinfo=timezone.utc)
    assert clock_text(utc, utc.astimezone(PDT)).startswith("0005Z")


def test_the_hint_is_shown_in_full_when_it_fits():
    assert hint_for_width(len(PICKER_HINT)) == PICKER_HINT
    assert hint_for_width(CONTENT_WIDTH) == PICKER_HINT


def test_the_hint_degrades_rather_than_pushing_the_clock_off():
    """The clocks win; the keybinding still works without the words."""
    assert hint_for_width(len(PICKER_HINT) - 1) == PICKER_HINT_SHORT
    assert hint_for_width(1) == PICKER_HINT_SHORT


def test_both_line_two_fields_fit_the_real_width():
    clocks = clock_text(UTC_NOON, LOCAL_NOON)
    hint = hint_for_width(CONTENT_WIDTH - len(clocks) - 1)
    assert hint == PICKER_HINT, "at 46 columns the full hint should fit"
    assert len(clocks) + 1 + len(hint) <= CONTENT_WIDTH
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_status_format.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kcgx.status'`

- [ ] **Step 3: Implement the formatting**

Create `src/kcgx/status.py`:

```python
"""The cockpit's status pane: which airport, what time, how to change it.

Four rows in the top of the right column, above squelch. The two lines it
shows are built by the pure functions here so that what the pane says can
be checked without a terminal.

`fit` is deliberately a local copy rather than an import from
kcgx.picker -- these are two independently-sized surfaces, and coupling
them would mean a change to the picker's row layout could silently reflow
the status line.
"""

from __future__ import annotations

from datetime import datetime

from kcgx.airports import Airport

# The right column is 48 columns; one cell of padding each side leaves 46.
STATUS_WIDTH = 48
CONTENT_WIDTH = STATUS_WIDTH - 2
# One row of padding, two content lines, one row of padding.
STATUS_ROWS = 4

PICKER_HINT = "▾ airport (^b a)"
PICKER_HINT_SHORT = "▾"


def fit(text: str, width: int) -> str:
    """Pad to `width`, or truncate with a visible ellipsis."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def airport_line(airport: Airport | None, icao: str, width: int) -> str:
    """Code and name -- or the bare code when the dataset has no such field.

    `airport` is None when the remembered ICAO is not in the dataset, which
    a dataset regeneration can cause. Showing the code alone is honest and
    keeps the pane alive; the airport-search work made the same choice.
    """
    if airport is None:
        return fit(icao, width)
    return fit(f"{airport.icao}  {airport.name}", width)


def clock_text(now_utc: datetime, now_local: datetime) -> str:
    """Zulu first, because that is what you are hearing on the feed."""
    return f"{now_utc:%H%M}Z   {now_local:%H:%M %Z}"


def hint_for_width(available: int) -> str:
    """The picker affordance, shrunk rather than dropped.

    When the pane is too narrow for both, the clocks win: the keybinding
    still works without the words next to it, but a clock that silently
    disappears is worse than a hint that shrinks.
    """
    if available >= len(PICKER_HINT):
        return PICKER_HINT
    return PICKER_HINT_SHORT
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_status_format.py -v
```

Expected: PASS (11 tests)

- [ ] **Step 5: Revert-check**

Do these one at a time, `git diff` clean before and after each:

1. Change `clock_text`'s format to `%H:%M` for the Zulu half. Confirm
   `test_zulu_is_four_digits_and_a_z` FAILS. Restore.
2. Make `hint_for_width` always return `PICKER_HINT`. Confirm
   `test_the_hint_degrades_rather_than_pushing_the_clock_off` FAILS. Restore.
3. Make `airport_line` return `""` when `airport is None`. Confirm
   `test_an_airport_missing_from_the_dataset_still_shows_its_code` FAILS.
   Restore.

Record the observed output for each.

- [ ] **Step 6: Commit**

```bash
cd /Users/mikelse/kcgx
git add src/kcgx/status.py tests/test_status_format.py
git commit -m "feat(kcgx): the status pane's two lines

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The status app

**Files:**
- Modify: `src/kcgx/status.py`, `pyproject.toml`
- Create: `tests/test_status_app.py`

**Interfaces:**
- Consumes: Task 1's formatting functions; `kcgx.airports.load_airports()`,
  `kcgx.airports.find(icao, airports)`; `kcgx.state.current_icao()`.
- Produces:
  - `PICKER_POPUP: tuple[str, ...]` — the tmux argv the click runs
  - `now_pair() -> tuple[datetime, datetime]`
  - `open_picker(run=subprocess.run) -> None`
  - `StatusPane(*, resolver=current_icao, airports_loader=load_airports,
    now=now_pair, opener=open_picker)` — a Textual `App`
  - `main() -> int` — the `kcgx-status` console script

- [ ] **Step 1: Write the failing tests**

Create `tests/test_status_app.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_status_app.py -v
```

Expected: FAIL — `ImportError: cannot import name 'StatusPane'`

- [ ] **Step 3: Add the console script to `pyproject.toml`**

In the existing `[project.scripts]` table:

```toml
[project.scripts]
squelch = "squelch.__main__:main"
kcgx-airport = "kcgx.__main__:main"
kcgx-status = "kcgx.status:main"
```

Leave `[tool.uv.build-backend]` alone — `kcgx` is already a built module.

- [ ] **Step 4: Implement the app**

Append to `src/kcgx/status.py` (add `subprocess`, `sys`, and the Textual
imports to the **top-of-file import block**, not here):

```python
# The same popup `Ctrl-b a` opens. It is spelled here and in
# kcgx.tmux.conf, and test_the_click_and_the_keybinding_run_the_same_popup
# pins the two together -- a hint that says "^b a" while the click does
# something else would be worse than no hint at all.
PICKER_POPUP = ("display-popup", "-E", "-w", "64", "-h", "20", "kcgx go")

TICK_SECONDS = 1.0


def now_pair() -> tuple[datetime, datetime]:
    """UTC and local from one instant, so the two clocks cannot disagree."""
    utc = datetime.now(timezone.utc)
    return utc, utc.astimezone()


def open_picker(run: Callable[..., object] = subprocess.run) -> None:
    run(("tmux", *PICKER_POPUP))


class StatusPane(App[None]):
    CSS = """
    Screen { background: $surface; }
    #body { padding: 1; }
    #airport { height: 1; }
    #line2 { height: 1; }
    #clock { width: auto; }
    #hint { width: 1fr; text-align: right; color: $text-muted; }
    #hint:hover { color: $text; }
    """

    def __init__(
        self,
        *,
        resolver: Callable[[], str] = current_icao,
        airports_loader: Callable[[], list[Airport]] = load_airports,
        now: Callable[[], tuple[datetime, datetime]] = now_pair,
        opener: Callable[[], None] = open_picker,
    ) -> None:
        super().__init__()
        self._resolver = resolver
        self._airports_loader = airports_loader
        self._now = now
        self._opener = opener
        self._airports: list[Airport] = []
        self._icao = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="body"):
            yield Static("", id="airport")
            with Horizontal(id="line2"):
                yield Static("", id="clock")
                yield Static("", id="hint")

    def on_mount(self) -> None:
        self._airports = self._airports_loader()
        self.tick()
        self.set_interval(TICK_SECONDS, self.tick)

    def tick(self) -> None:
        """Redraw the clock, and pick up an airport that changed underneath.

        Re-reading through the resolver every second is what lets `kcgx go`
        move the cockpit without touching this pane: no respawn, no flicker,
        and it is right even if the remembered airport changes by some other
        route.
        """
        icao = self._resolver()
        airport = find(icao, self._airports)
        self.query_one("#airport", Static).update(
            airport_line(airport, icao, CONTENT_WIDTH), layout=False
        )

        utc, local = self._now()
        clocks = clock_text(utc, local)
        self.query_one("#clock", Static).update(clocks, layout=False)
        self.query_one("#hint", Static).update(
            hint_for_width(CONTENT_WIDTH - len(clocks) - 1), layout=False
        )

    def on_click(self, event: Click) -> None:
        widget = getattr(event, "widget", None)
        if widget is None or widget.id != "hint":
            return
        try:
            self._opener()
        except Exception:
            # Losing the mouse shortcut is not a reason to lose the clock;
            # `Ctrl-b a` still works.
            pass


def main() -> int:
    StatusPane().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Top-of-file imports to add:

```python
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.widgets import Static

from kcgx.airports import Airport, find, load_airports
from kcgx.state import current_icao
```

- [ ] **Step 5: Run to verify they pass**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_status_app.py -v
```

Expected: PASS (12 tests)

`Click` does carry a `widget` attribute on Textual 8.2.8 — verified:
`Click.__init__(self, widget: 'Widget | None', x, y, ...)`. So
`event.widget.id` is the right check.

If `test_clicking_the_affordance_opens_the_picker` still fails, the click is
reaching `on_click` with a different widget than you expect (a child, or the
container). Print `event.widget` and `event.widget.id` to see what actually
arrived, and adjust the handler — **not** the test's target — so that
clicking the hint works and clicking the clock does not.

- [ ] **Step 6: Look at it in a real terminal**

```bash
cd /Users/mikelse/kcgx
tmux -L statusprobe kill-server 2>/dev/null
tmux -L statusprobe new-session -d -x 48 -y 4 "uv run --project . kcgx-status"
sleep 12
tmux -L statusprobe capture-pane -p | sed 's/^/|/'
tmux -L statusprobe kill-server 2>/dev/null
```

Expected: a blank line, the airport line, the clock-and-hint line, a blank
line. Confirm the padding is one cell on each side and nothing wraps. Paste
the capture into your report.

- [ ] **Step 7: Revert-check**

One at a time, `git diff` clean before and after each:

1. Make `tick` skip the resolver (hardcode `icao = "KPDX"`). Confirm
   `test_a_changed_airport_is_picked_up_on_the_next_tick` FAILS. Restore.
2. Make `on_click` return before calling `self._opener()`. Confirm
   `test_clicking_the_affordance_opens_the_picker` FAILS. Restore.
3. Drop the `widget.id != "hint"` guard so any click opens the picker.
   Confirm `test_clicking_the_clock_does_not_open_the_picker` FAILS. Restore.
4. Remove the `try/except` around `self._opener()`. Confirm
   `test_a_failing_opener_does_not_kill_the_pane` FAILS. Restore.
5. Change `PICKER_POPUP`'s width to `"80"`. Confirm
   `test_the_click_and_the_keybinding_run_the_same_popup` FAILS. Restore.

- [ ] **Step 8: Commit**

```bash
cd /Users/mikelse/kcgx
git add src/kcgx/status.py tests/test_status_app.py pyproject.toml
git commit -m "feat(kcgx): a status pane showing the airport, the time, and a way in

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The cockpit layout

**Files:**
- Modify: `bin/kcgx`, `tests/test_kcgx_launcher.py`

**Interfaces:**
- Consumes: `kcgx-status` (Task 2).
- Produces: `KCGX_STATUS_ROWS` (default 4) and `KCGX_STATUS_CMD` env seams;
  `@kcgx_role` values `adsb`, `status`, `squelch` on the three panes.

- [ ] **Step 1: Replace the shell-pane variables**

In `bin/kcgx`'s environment header, replace the `KCGX_SHELL_ROWS` line with:

```
#   KCGX_STATUS_ROWS   height of the status pane       (default: 4)
#   KCGX_STATUS_CMD    command for the status pane
```

and replace the `SHELL_ROWS=` assignment with:

```bash
STATUS_ROWS="${KCGX_STATUS_ROWS:-4}"
```

Then grep for any other use and update it:

```bash
cd /Users/mikelse/kcgx && grep -rn "SHELL_ROWS" bin tests README.md
```

- [ ] **Step 2: Add the status command and role helpers**

Beside the existing `ADSB_CMD` / `SQUELCH_CMD` assignments:

```bash
STATUS_CMD="${KCGX_STATUS_CMD:-uv run --project '$REPO' kcgx-status}"
```

Beside `adsb_cmd` / `squelch_cmd`:

```bash
status_cmd() {
    printf '%s' "$STATUS_CMD"
}

# Panes are found by role, not by index. Inserting the status pane renumbers
# squelch from 1 to 2 while its pane id stays the same, and retargeting the
# wrong pane fails silently -- the cockpit looks fine and points elsewhere.
pane_for_role() {  # $1=adsb|status|squelch
    tm list-panes -t "=$SESSION:cockpit" -F '#{@kcgx_role} #{pane_id}' |
        awk -v role="$1" '$1 == role { print $2; exit }'
}
```

- [ ] **Step 3: Retarget by role**

Replace `retarget`:

```bash
retarget() {  # $1=icao $2=lat $3=lon
    tm respawn-pane -k -t "$(pane_for_role adsb)" "$(adsb_cmd "$2" "$3")"
    tm respawn-pane -k -t "$(pane_for_role squelch)" "$(squelch_cmd "$1")"
}
```

The status pane is deliberately not respawned: it re-reads the airport on
its own tick, so it stays current without flickering.

- [ ] **Step 4: Build three panes and tag them**

Replace the `new-session` / `split-window` / `select-pane` block:

```bash
# -P -F prints the new pane's id, so each pane is identified at the moment
# it is created rather than inferred from an index afterwards.
adsb_pane="$(tm new-session -d -s "$SESSION" -n cockpit -x "$cols" -y "$rows" \
    -P -F '#{pane_id}' "$(adsb_cmd "$LAT" "$LON")")"
apply_config
squelch_pane="$(tm split-window -h -l "$SQUELCH_COLS" -t "$adsb_pane" \
    -P -F '#{pane_id}' "$(squelch_cmd "$ICAO")")"
# -b puts the new pane *above* the one it splits.
status_pane="$(tm split-window -v -b -l "$STATUS_ROWS" -t "$squelch_pane" \
    -P -F '#{pane_id}' "$(status_cmd)")"

tm set -p -t "$adsb_pane" @kcgx_role adsb
tm set -p -t "$squelch_pane" @kcgx_role squelch
tm set -p -t "$status_pane" @kcgx_role status

# Land on squelch — it's the pane you read, and the only one that takes keys.
tm select-pane -t "$squelch_pane"
```

- [ ] **Step 5: Return focus to squelch after a switch**

In the `go` arm, after the `retarget` call and before the `printf`:

```bash
        # Clicking the status pane makes it tmux's active pane, so without
        # this the arrow keys would drive the status pane instead of
        # squelch's feed list. Also fixes `Ctrl-b a` pressed from adsb-tui.
        tm select-pane -t "$(pane_for_role squelch)"
```

- [ ] **Step 6: Update `usage()`**

```bash
usage() {
    cat <<'USAGE'
kcgx — open the cockpit: live traffic, ATC audio, a status line.

  kcgx             open the cockpit, or reattach to a running one
  kcgx go [query]  search for an airport and point both panes at it
  kcgx stop        shut the cockpit down
  kcgx --help      this

Drag any pane border with the mouse to resize. Ctrl-b then a opens the
airport search, as does clicking the status pane; Ctrl-b then r respawns a
pane that has died.
USAGE
}
```

- [ ] **Step 7: Write the failing launcher tests**

Append to `tests/test_kcgx_launcher.py`:

```python
# -- the status pane -------------------------------------------------------

FAKE_STATUS = "sh -c 'sleep 300'"


def roles(tmux, session):
    """Map role -> pane id, the same lookup bin/kcgx does."""
    out = {}
    for line in panes(tmux, session, "#{@kcgx_role}\t#{pane_id}"):
        role, _, pane_id = line.partition("\t")
        if role.strip():
            out[role.strip()] = pane_id.strip()
    return out


def test_the_cockpit_has_three_panes_and_no_shell(cockpit):
    run, tmux, session = cockpit
    run(KCGX_STATUS_CMD=FAKE_STATUS)
    commands = panes(tmux, session, "#{pane_start_command}")
    assert len(commands) == 3
    assert not any(c.strip() == "" for c in commands), (
        "an empty pane command is the shell pane that should be gone"
    )


def test_every_pane_carries_its_role(cockpit):
    run, tmux, session = cockpit
    run(KCGX_STATUS_CMD=FAKE_STATUS)
    assert set(roles(tmux, session)) == {"adsb", "status", "squelch"}


def test_the_status_pane_sits_above_squelch_and_is_four_rows(cockpit):
    run, tmux, session = cockpit
    run(KCGX_STATUS_CMD=FAKE_STATUS)
    by_id = {}
    for line in panes(tmux, session, "#{pane_id}\t#{pane_top}\t#{pane_height}"):
        pane_id, top, height = line.split("\t")
        by_id[pane_id] = (int(top), int(height))
    r = roles(tmux, session)
    assert by_id[r["status"]][1] == 4, "status pane should be four rows"
    assert by_id[r["status"]][0] < by_id[r["squelch"]][0], "status sits above"


def test_retarget_still_finds_both_panes_after_the_layout_change(cockpit, airport_stub):
    """The whole point of the role tags."""
    run, tmux, session = cockpit
    run(
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    result = run(
        args=("go",),
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    assert result.returncode == 0, result.stderr

    by_id = {}
    for line in panes(tmux, session, "#{pane_id}\t#{pane_start_command}"):
        pane_id, _, cmd = line.partition("\t")
        by_id[pane_id] = cmd
    r = roles(tmux, session)
    assert "--site-lat 47.4479" in by_id[r["adsb"]]
    assert "--icao KSEA" in by_id[r["squelch"]]
    assert "--icao" not in by_id[r["status"]], "the status pane is not retargeted"


def test_go_leaves_squelch_selected(cockpit, airport_stub):
    run, tmux, session = cockpit
    run(
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    run(
        args=("go",),
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    active = tmux(
        "display-message", "-p", "-t", f"={session}:cockpit", "#{pane_id}"
    ).stdout.strip()
    assert active == roles(tmux, session)["squelch"]


def test_launch_leaves_squelch_selected(cockpit):
    run, tmux, session = cockpit
    run(KCGX_STATUS_CMD=FAKE_STATUS)
    active = tmux(
        "display-message", "-p", "-t", f"={session}:cockpit", "#{pane_id}"
    ).stdout.strip()
    assert active == roles(tmux, session)["squelch"]
```

Also add `"KCGX_STATUS_CMD": FAKE_STATUS` to the `cockpit` fixture's default
`env` dict, so the existing launcher tests do not launch a real Textual app.

- [ ] **Step 8: Run the launcher tests**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_kcgx_launcher.py -v
```

Expected: PASS, new and old.

- [ ] **Step 9: Revert-check**

One at a time, `git diff` clean before and after each:

1. Change `retarget` back to `-t "=$SESSION:cockpit.0"` / `.1`. Confirm
   `test_retarget_still_finds_both_panes_after_the_layout_change` FAILS,
   and note *which* pane got the wrong command — that is the silent failure
   the roles exist to prevent. Restore.
2. Remove the `tm select-pane` line from the `go` arm. Confirm
   `test_go_leaves_squelch_selected` FAILS. Restore.
3. Drop the `-b` from the status `split-window`. Confirm
   `test_the_status_pane_sits_above_squelch_and_is_four_rows` FAILS.
   Restore.

- [ ] **Step 10: Try it on a private socket**

```bash
cd /Users/mikelse/kcgx
tmux -L statuslive kill-server 2>/dev/null
env KCGX_SOCKET=statuslive KCGX_SESSION=slive KCGX_SIZE=200x50 KCGX_DETACHED=1 \
    KCGX_STATE_PATH=/tmp/kcgx-status-probe-state \
    KCGX_ADSB_CMD="sh -c 'sleep 300'" KCGX_SQUELCH_CMD="sh -c 'sleep 300'" \
    ./bin/kcgx
sleep 14
tmux -L statuslive list-panes -t '=slive:cockpit' \
    -F '#{@kcgx_role} #{pane_width}x#{pane_height}'
echo "--- the status pane as drawn ---"
tmux -L statuslive capture-pane -p -t "$(tmux -L statuslive list-panes \
    -t '=slive:cockpit' -F '#{@kcgx_role} #{pane_id}' |
    awk '$1=="status"{print $2}')" | sed 's/^/|/'
tmux -L statuslive kill-server 2>/dev/null
rm -f /tmp/kcgx-status-probe-state
```

**Do not run bare `kcgx` or `kcgx stop`** — the repo owner may have a live
cockpit. Paste the capture into your report.

- [ ] **Step 11: Commit**

```bash
cd /Users/mikelse/kcgx
git add bin/kcgx tests/test_kcgx_launcher.py
git commit -m "feat(kcgx): status pane replaces the shell pane, panes found by role

Inserting a pane renumbers squelch, and retargeting the wrong pane fails
silently, so panes are now tagged with @kcgx_role and looked up by it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the README and find what is now false**

```bash
cd /Users/mikelse/kcgx && grep -n "shell\|kcgx go\|pane" README.md
```

At minimum, the ASCII layout diagram and the sentence saying `kcgx go
[query]` works "from the shell pane" are both now wrong.

- [ ] **Step 2: Correct them and document the status pane**

Match the README's existing plain voice — bold lead-in phrase, dense
paragraph, no marketing language, no emoji headers. Cover:

- The right column is a four-row status pane above squelch; there is no
  shell pane.
- It shows the ICAO and airport name, the time in Zulu and locally, and
  `▾ airport (^b a)`.
- Clicking that field opens the same picker as `Ctrl-b a`.
- `kcgx go [query]` still works — from any terminal, not from a pane inside
  the cockpit.
- The airport's own local time is not shown, because the dataset has no
  timezone column and deriving it from longitude would be wrong across DST
  and political boundaries.

Update the layout diagram to three panes.

- [ ] **Step 3: Verify every command you wrote**

Run each command you put in the README, except bare `kcgx` / `kcgx stop` /
`kcgx go` (the owner's cockpit may be live). `kcgx --help` is safe. If a
command does not behave as documented, fix the doc.

- [ ] **Step 4: Run the full suite**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest -q
```

Expected: all green, roughly 251 + 29 tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/mikelse/kcgx
git add README.md
git commit -m "docs: the status pane, and no more shell pane

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes

**Spec coverage** — layout and four rows → Task 3; the two lines and their
degradation → Task 1; clickability, ticking, and the shared popup spelling →
Task 2; role tags and select-squelch-after-`go` → Task 3; error handling
(unknown ICAO, failing opener, narrow pane) → Tasks 1 and 2; docs → Task 4.

**Verified at plan time** — `set -p @kcgx_role` works on tmux 3.7b, is
readable via `list-panes -F '#{@kcgx_role}'`, and **survives
`respawn-pane -k`**, which is what `retarget` issues. Also measured: after
`split-window -v -b`, the status pane takes index 1 and squelch moves from
index 1 to 2 while pane ids stay stable — the concrete fragility the roles
remove.

**Deliberately not respawned** — the status pane is absent from `retarget`.
It re-reads the airport on its own tick, which is what keeps `kcgx go`
unchanged and the pane flicker-free.

**Also verified at plan time** — `Click` carries `widget: Widget | None` on
Textual 8.2.8, so `event.widget.id` is the right discriminator; and
`-P -F '#{pane_id}'` prints the new pane's id from `new-session` and from
both `split-window` forms, which is what lets each pane be identified at
creation rather than inferred from an index afterwards. The three-pane
geometry was measured: status `top=0 h=4`, squelch `top=5 h=25`.

**Unverified at plan time** — that a tmux mouse click inside the status pane
reaches Textual's `on_click` in a real cockpit. tmux mouse mode is on and
already forwards clicks to squelch, and the picker's own mouse handling
works, so the mechanism is established; but this specific pane has not been
clicked by a human. Task 3 Step 10 builds a real cockpit on a private
socket, and the repo owner will exercise the click afterwards.
