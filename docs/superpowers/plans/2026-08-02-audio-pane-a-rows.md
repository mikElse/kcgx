# Audio Pane A — Row Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the squelch feed row so audibility drives its height, the feed ident is gone, every control is clickable, and `S` solos a feed.

**Architecture:** Row rendering moves out of `app.py` into a new `rows.py`. Every layout decision becomes a pure function over strings and integers — line renderers, the three-row meter, and click hit-testing — so the hard parts are unit-testable without a running app. `app.py` keeps only the application shell: selection, solo state, and event routing.

**Tech Stack:** Python 3.14, Textual 8.2.8, pytest 9.1.1 with `pytest-asyncio` (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-08-02-audio-pane-rows-design.md`

## Global Constraints

- The pane is **exactly 48 columns**. Rows carry `padding: 0 1`, leaving **46 content cells**. No rendered line may exceed 48 cells.
- The pane is **42 rows** tall in tests (`SIZE = (48, 42)`).
- Compact row height is **2** (1 border + 1 content). Expanded row height is **6** (1 border + 1 name + 3 meter + 1 controls).
- Name field is **34 cells** compact, **44 cells** expanded.
- `feeds.py`, `audio.py`, `pipeline.py`, `session.py`, and `config.py` **must not import `textual`**. `rows.py` may.
- Truncation is always marked with `…` — never a silent slice. Use the existing `_fit`.
- Feed labels are third-party text: every `Static` rendering them keeps `markup=False`.
- No test may access the network or open an audio device.
- Run tests with `uv run pytest`. Run the whole suite before every commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/squelch/rows.py` | **New.** `FeedRow` widget, layout constants, line renderers, 3-row meter, click hit-testing |
| `src/squelch/solo.py` | **New.** Solo state machine. Pure, no Textual, no session imports |
| `src/squelch/app.py` | Application shell: header, footer, message log, selection, solo wiring, feed picker |
| `src/squelch/session.py` | Gains an `ambient` flag |
| `src/squelch/squelch.tcss` | Compact/expanded heights, control lit/dim styling |
| `tests/test_rows.py` | **New.** Pure renderer and hit-test tests |
| `tests/test_solo.py` | **New.** Solo state machine tests |
| `tests/test_app.py` | Extended: click-to-mute, row states, bindings, picker |

---

### Task 1: Extract row rendering into `rows.py`

A pure move. No behaviour changes, so the existing suite must pass untouched at the end.

**Files:**
- Create: `src/squelch/rows.py`
- Modify: `src/squelch/app.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `squelch.rows` exporting `BLOCKS`, `FLOOR_DBFS`, `ROW_WIDTH`, `NAME_WIDTH`, `IDENT_WIDTH`, `METER_WIDTH`, `_STATE_DOTS`, `_glyph_for`, `meter_bar`, `_fit`, `FeedRow`. `app.py` re-imports all of these into its own namespace so `from squelch.app import FeedRow, _fit, meter_bar, METER_WIDTH` keeps working.

- [ ] **Step 1: Create `src/squelch/rows.py`**

Move these from `src/squelch/app.py` verbatim, with no edits: `BLOCKS`, `FLOOR_DBFS`, `ROW_WIDTH`, `NAME_WIDTH`, `IDENT_WIDTH`, `METER_WIDTH`, `_STATE_DOTS`, `_glyph_for`, `meter_bar`, `_fit`, and the whole `FeedRow` class.

Head the file:

```python
"""Rendering for one feed's row.

Every layout decision here is a pure function over strings and integers, so
the 48-column budget can be tested without a running app. `app.py` owns the
application shell; this module owns what a row looks like.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static
```

- [ ] **Step 2: Rewire `app.py`**

Delete the moved definitions from `app.py` and add, next to its other imports:

```python
from squelch.rows import (
    BLOCKS,
    FLOOR_DBFS,
    IDENT_WIDTH,
    METER_WIDTH,
    NAME_WIDTH,
    ROW_WIDTH,
    FeedRow,
    _fit,
    _glyph_for,
    meter_bar,
)
```

`app.py` still uses `_fit` in `_refresh_header`, and `tests/test_app.py` imports `METER_WIDTH`, `FeedRow`, `_fit`, and `meter_bar` from `squelch.app` — this import keeps all of that working.

- [ ] **Step 3: Run the full suite to prove nothing changed**

Run: `uv run pytest`
Expected: PASS, same count as before the move.

- [ ] **Step 4: Commit**

```bash
git add src/squelch/rows.py src/squelch/app.py
git commit -m "refactor(squelch): move row rendering into rows.py"
```

---

### Task 2: The three-row meter

One waveform three cells tall — 24 vertical steps instead of 8. Replaces `meter_bar`.

**Files:**
- Modify: `src/squelch/rows.py`
- Create: `tests/test_rows.py`
- Modify: `tests/test_app.py` (delete the `meter_bar` tests)

**Interfaces:**
- Consumes: `BLOCKS`, `FLOOR_DBFS` from Task 1.
- Produces: `METER_ROWS = 3`, `METER_STEPS = 24`, `METER_WIDTH = 46`, `level_step(dbfs: float) -> int` returning `0..23`, and `meter_rows(history: Sequence[float], width: int = METER_WIDTH) -> tuple[str, str, str]` returning top, middle, bottom lines each exactly `width` cells.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rows.py`:

```python
"""Pure rendering tests for one feed's row.

Nothing here starts an app: these are the functions that decide what fits
in 46 cells, and they are the cheapest place to prove it.
"""

from squelch.rows import (
    METER_ROWS,
    METER_STEPS,
    METER_WIDTH,
    level_step,
    meter_rows,
)


def test_silence_is_the_lowest_step():
    assert level_step(-96.0) == 0


def test_full_scale_is_the_highest_step():
    assert level_step(0.0) == METER_STEPS - 1


def test_the_floor_and_below_both_clamp_to_zero():
    assert level_step(-60.0) == 0
    assert level_step(-200.0) == 0


def test_steps_increase_with_level():
    quiet, mid, loud = level_step(-50.0), level_step(-30.0), level_step(-5.0)
    assert quiet < mid < loud


def test_meter_returns_three_rows_of_the_requested_width():
    rows = meter_rows([-20.0] * 10, width=12)
    assert len(rows) == METER_ROWS
    assert all(len(row) == 12 for row in rows)


def test_a_silent_meter_fills_only_the_bottom_row():
    top, middle, bottom = meter_rows([-96.0] * 8, width=8)
    assert set(top) == {" "}
    assert set(middle) == {" "}
    assert set(bottom) == {"▁"}


def test_a_full_scale_meter_fills_every_row():
    top, middle, bottom = meter_rows([0.0] * 8, width=8)
    assert set(top) == {"█"}
    assert set(middle) == {"█"}
    assert set(bottom) == {"█"}


def test_a_mid_level_fills_below_and_leaves_the_top_empty():
    """A column is one sample drawn across 24 steps, not three meters."""
    top, middle, bottom = meter_rows([-30.0], width=1)
    assert bottom == "█", "everything below the level reads as full"
    assert top == " ", "nothing above the level is drawn"
    assert middle not in (" ",), "the level itself lands in the middle row"


def test_a_short_history_is_padded_on_the_left():
    top, _middle, bottom = meter_rows([0.0], width=5)
    assert top == "    █", "the newest sample belongs at the right"
    assert bottom == "▁▁▁▁█"


def test_history_scrolls_oldest_off_the_left():
    loud_then_quiet = [0.0] + [-96.0] * 12
    top, _middle, _bottom = meter_rows(loud_then_quiet, width=10)
    assert set(top) == {" "}, "the loud sample has scrolled off"


def test_the_default_width_is_the_full_content_row():
    assert METER_WIDTH == 46
    assert all(len(row) == 46 for row in meter_rows([-20.0] * 50))
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_rows.py -v`
Expected: FAIL with `ImportError: cannot import name 'METER_ROWS'`.

- [ ] **Step 3: Implement**

In `src/squelch/rows.py`, replace `METER_WIDTH = 44` with the block below, and delete `_glyph_for` and `meter_bar` along with their now-dead uses:

```python
METER_ROWS = 3
# One glyph per row of vertical resolution, so a sample spans 3 x 8 steps.
# At a single row a colour gradient has too few cells to read as a gradient,
# which is the whole reason the expanded meter is worth its height.
METER_STEPS = METER_ROWS * len(BLOCKS)  # 24
# The meter row carries nothing else, so it gets the full content width.
METER_WIDTH = 46


def level_step(dbfs: float) -> int:
    """Quantise one level reading to 0..METER_STEPS-1."""
    fraction = max(0.0, min(1.0, (dbfs - FLOOR_DBFS) / -FLOOR_DBFS))
    return max(0, min(METER_STEPS - 1, int(fraction * METER_STEPS)))


def _column(step: int) -> tuple[str, str, str]:
    """Top, middle, and bottom glyphs for one sample.

    Rows below the level read as full blocks, the row containing it gets a
    partial glyph, and rows above it are blank -- so the three rows compose
    into one tall bar rather than three independent meters.
    """
    glyphs = []
    for row in range(METER_ROWS):  # 0 = bottom
        base = row * len(BLOCKS)
        if step >= base + len(BLOCKS) - 1:
            glyphs.append(BLOCKS[-1])
        elif step < base:
            glyphs.append(" ")
        else:
            glyphs.append(BLOCKS[step - base])
    glyphs.reverse()  # top first
    return glyphs[0], glyphs[1], glyphs[2]


def meter_rows(
    history: Sequence[float], width: int = METER_WIDTH
) -> tuple[str, str, str]:
    """Render a rolling history of levels as one bar per sample.

    Oldest sample at the left, newest at the right. Only the most recent
    `width` samples are shown; if fewer exist, the left is padded with the
    idle column so a fresh meter reads as a flat low line rather than a gap.
    """
    recent = list(history)[-width:]
    columns = [_column(0)] * (width - len(recent))
    columns += [_column(level_step(level)) for level in recent]
    return (
        "".join(c[0] for c in columns),
        "".join(c[1] for c in columns),
        "".join(c[2] for c in columns),
    )
```

- [ ] **Step 4: Point `FeedRow` at the new meter**

In `FeedRow`, the history deque already uses `maxlen=METER_WIDTH`, which now widens to 46 automatically. Change `refresh_meter` to render three lines into one `Static`:

```python
    def refresh_meter(self) -> None:
        if self._meter_widget is None:
            return
        self._meter_widget.update("\n".join(meter_rows(self._history)), layout=False)
```

and change the meter `Static` in `compose` to reserve three rows via its CSS class (Task 5 sets the height).

- [ ] **Step 5: Delete the superseded tests**

In `tests/test_app.py`, delete `test_meter_bar_respects_width`, `test_silent_history_renders_flat_and_low`, `test_a_short_history_is_padded_not_left_empty`, and `test_history_scrolls_oldest_off_the_left`, and drop `meter_bar` from its import list. `tests/test_rows.py` covers all four behaviours against the replacement.

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_rows.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/squelch/rows.py tests/test_rows.py tests/test_app.py
git commit -m "feat(squelch): render the feed meter three rows tall"
```

---

### Task 3: The `ambient` flag on a session

`[A]` is rendered and toggleable in this plan but silent until spec D lands. It sets a flag D's mixer will read.

**Files:**
- Modify: `src/squelch/session.py`
- Modify: `tests/test_session.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FeedSession.ambient: bool` (default `False`) and `FeedSession.toggle_ambient() -> bool` returning the new value.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_session.py`:

```python
def test_a_session_starts_off_the_ambient_bus():
    session = make_session()
    assert session.ambient is False


def test_toggle_ambient_flips_and_reports_the_new_value():
    session = make_session()
    assert session.toggle_ambient() is True
    assert session.ambient is True
    assert session.toggle_ambient() is False
    assert session.ambient is False


def test_ambient_is_independent_of_mute():
    """A feed can be routed to the ambient bus while muted on the dry bus."""
    session = make_session()
    session.toggle_ambient()
    assert session.ambient is True
    assert session.muted is True
```

If `tests/test_session.py` has no `make_session` helper, add one that mirrors how the existing tests build a `FeedSession` (it must inject `resolve`, `reader_factory`, `player_factory`, and `pipeline_factory` fakes so nothing touches the network or an audio device).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_session.py -k ambient -v`
Expected: FAIL with `AttributeError: 'FeedSession' object has no attribute 'ambient'`.

- [ ] **Step 3: Implement**

In `FeedSession.__init__`, after `self.state = "starting"`:

```python
        # Routed to the ambient bus. Rendered and toggleable now; the mixer
        # that acts on it arrives with spec D, so this is deliberately inert
        # rather than absent -- the UI is the same either way.
        self.ambient = False
```

and beside `toggle_mute`:

```python
    def toggle_ambient(self) -> bool:
        self.ambient = not self.ambient
        return self.ambient
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/session.py tests/test_session.py
git commit -m "feat(squelch): add the ambient routing flag to a feed session"
```

---

### Task 4: Line renderers

Three pure functions producing exactly 46 cells each. The ident disappears here.

**Files:**
- Modify: `src/squelch/rows.py`
- Modify: `tests/test_rows.py`

**Interfaces:**
- Consumes: `_fit`, `ROW_WIDTH`, `_STATE_DOTS` from Task 1.
- Produces:
  - `NAME_WIDTH = 34`, `NAME_WIDTH_EXPANDED = 44`
  - `compact_line(name: str, *, muted: bool, ambient: bool, state: str) -> str`
  - `expanded_name_line(name: str, *, state: str) -> str`
  - `control_line(*, muted: bool, ambient: bool, soloed: bool, activity: float | None) -> str`

  All three return exactly `ROW_WIDTH` cells. `activity` is a fraction in `0.0..1.0`, or `None` for "not yet measured" (spec B fills it in).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rows.py`:

```python
from squelch.rows import (
    NAME_WIDTH,
    NAME_WIDTH_EXPANDED,
    ROW_WIDTH,
    compact_line,
    control_line,
    expanded_name_line,
)

LONG_NAME = "Approach (Final) South Arrivals 124.35"


def test_every_line_is_exactly_the_content_width():
    lines = [
        compact_line("Tower (Both)", muted=True, ambient=False, state="live"),
        expanded_name_line("Tower (Both)", state="live"),
        control_line(muted=False, ambient=False, soloed=False, activity=0.34),
    ]
    assert [len(line) for line in lines] == [ROW_WIDTH] * 3


def test_the_ident_is_gone_from_the_row():
    line = compact_line("Tower (Both)", muted=True, ambient=False, state="live")
    assert "kpdx" not in line.lower()


def test_compact_shows_the_name_the_controls_and_the_state_dot():
    line = compact_line("Tower (Both)", muted=True, ambient=False, state="live")
    assert "Tower (Both)" in line
    assert "[A]" in line
    assert "[OFF]" in line
    assert line.endswith("●")


def test_compact_shows_on_when_audible():
    line = compact_line("Ground", muted=False, ambient=False, state="live")
    assert "[ ON]" in line
    assert "[OFF]" not in line


def test_the_on_off_control_is_the_same_width_in_both_states():
    """A toggle that changes width shifts every cell beside it."""
    off = compact_line("Ground", muted=True, ambient=False, state="live")
    on = compact_line("Ground", muted=False, ambient=False, state="live")
    assert len(off) == len(on) == ROW_WIDTH
    assert off.index("[") == on.index("[")


def test_state_dots_reach_the_line():
    for state, dot in (("live", "●"), ("reconnecting", "◐"), ("offline", "○")):
        assert compact_line("Ground", muted=True, ambient=False, state=state).endswith(dot)
        assert expanded_name_line("Ground", state=state).endswith(dot)


def test_a_long_name_truncates_visibly_rather_than_silently():
    line = compact_line(LONG_NAME, muted=True, ambient=False, state="live")
    assert "…" in line
    assert len(line) == ROW_WIDTH


def test_expanded_gives_the_name_more_room_than_compact():
    assert NAME_WIDTH_EXPANDED > NAME_WIDTH
    compact = compact_line(LONG_NAME, muted=True, ambient=False, state="live")
    expanded = expanded_name_line(LONG_NAME, state="live")
    assert expanded.count("…") == 1
    assert len(expanded.split("…")[0]) > len(compact.split("…")[0])


def test_the_name_field_is_wider_than_the_old_24_cell_field():
    """Dropping the ident is what this buys."""
    assert NAME_WIDTH == 34


def test_control_line_carries_all_three_controls():
    line = control_line(muted=False, ambient=False, soloed=False, activity=None)
    assert "[S]" in line
    assert "[ ON]" in line
    assert "[A]" in line


def test_control_line_shows_activity_when_measured():
    line = control_line(muted=False, ambient=False, soloed=False, activity=0.34)
    assert "busy 34%" in line


def test_control_line_omits_activity_until_it_is_measured():
    line = control_line(muted=False, ambient=False, soloed=False, activity=None)
    assert "busy" not in line
    assert len(line) == ROW_WIDTH


def test_activity_rounds_rather_than_truncating():
    line = control_line(muted=False, ambient=False, soloed=False, activity=0.999)
    assert "busy 100%" in line
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_rows.py -k "line or width or ident" -v`
Expected: FAIL with `ImportError: cannot import name 'compact_line'`.

- [ ] **Step 3: Implement**

In `src/squelch/rows.py`, replace `NAME_WIDTH = 24` and delete `IDENT_WIDTH` entirely, then add:

```python
# Dropping the ident buys the name 10 cells compact and 20 expanded. The
# ident was never typed at runtime; `feed` in squelch.toml and the picker
# are where it is still needed.
NAME_WIDTH = 34
NAME_WIDTH_EXPANDED = 44

# Both states of the mute toggle are 5 cells, so nothing beside it shifts
# when it flips.
_ON = "[ ON]"
_OFF = "[OFF]"
_SOLO = "[S]"
_AMBIENT = "[A]"


def _toggle(muted: bool) -> str:
    return _OFF if muted else _ON


def compact_line(
    name: str, *, muted: bool, ambient: bool, state: str
) -> str:
    """Name, controls, and state dot on one line.

    A muted feed is compact, and a compact row still has to offer a way back
    -- so the toggle lives here as well as on the expanded control line.
    """
    dot = _STATE_DOTS.get(state, "●")
    return (
        f"{_fit(name, NAME_WIDTH)} {_AMBIENT} {_toggle(muted)} {dot}"
    )


def expanded_name_line(name: str, *, state: str) -> str:
    """Name and state dot. The controls get their own line below the meter."""
    dot = _STATE_DOTS.get(state, "●")
    return f"{_fit(name, NAME_WIDTH_EXPANDED)} {dot}"


def control_line(
    *, muted: bool, ambient: bool, soloed: bool, activity: float | None
) -> str:
    """The expanded row's control strip, with activity right-aligned."""
    controls = f"{_SOLO}  {_toggle(muted)}  {_AMBIENT}"
    readout = "" if activity is None else f"busy {round(activity * 100)}%"
    return controls + readout.rjust(ROW_WIDTH - len(controls))
```

`ambient` and `soloed` are accepted but not yet reflected in the text — lit/dim is a CSS concern handled in Task 5, and the parameters are in the signature now so no caller changes when it lands.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_rows.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/rows.py tests/test_rows.py
git commit -m "feat(squelch): drop the ident and render the row control strip"
```

---

### Task 5: Compact and expanded row states

**Files:**
- Modify: `src/squelch/rows.py`
- Modify: `src/squelch/squelch.tcss`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: Task 4's renderers, Task 3's `session.ambient`.
- Produces: `FeedRow.expanded: bool` (read-only property, `not session.muted`), `FeedRow.refresh_all()` unchanged in name. CSS classes `compact` and `expanded` on the row.

- [ ] **Step 1: Write the failing tests**

In `tests/test_app.py`, extend `FakeSession.__init__` with `self.ambient = False`, add `toggle_ambient` mirroring `toggle_mute`, add `self.soloed = False` and `self.activity = None`, then append:

```python
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
        assert row.outer_size.height == 6, "expanded is name, meter x3, controls"


@pytest.mark.asyncio
async def test_a_compact_row_shows_no_meter():
    app = make_app(3)
    async with app.run_test(size=SIZE) as pilot:
        session = app._sessions[1]
        for level in (-50.0, -20.0, -8.0):
            app.set_level(session, level)
        await pilot.pause()
        row = app._rows[id(session)]
        assert len(row._history) == 3, "a muted feed keeps metering"
        assert not row._meter_widget.display, "but does not draw the meter"


@pytest.mark.asyncio
async def test_the_stack_still_fits_48_columns_in_both_states():
    app = make_app(12)
    async with app.run_test(size=SIZE) as pilot:
        for index in (1, 2, 3):
            app._sessions[index].muted = False
            app._rows[id(app._sessions[index])].refresh_all()
        await pilot.pause()
        _text, strips = rendered(app)
        assert all(s.cell_length == 48 for s in strips)
```

Delete `test_each_feed_shows_its_ident` — the ident is gone by design, and Task 4's `test_the_ident_is_gone_from_the_row` asserts the replacement. Replace `test_long_names_and_idents_truncate_visibly` with the same test renamed `test_long_names_truncate_visibly` and its ident references removed.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_app.py -k "expanded or compact" -v`
Expected: FAIL with `AttributeError: 'FeedRow' object has no attribute 'expanded'`.

- [ ] **Step 3: Implement `FeedRow`**

Replace `FeedRow`'s body in `src/squelch/rows.py`:

```python
class FeedRow(Vertical):
    """One feed. Compact when muted, expanded when audible.

    Expansion follows audibility rather than selection so the pane gives its
    height to what you can actually hear -- and so the tall meter and its
    redraw cost scale with the number of audible feeds, not the number of
    feeds that exist.
    """

    def __init__(self, session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._history: deque[float] = deque(maxlen=METER_WIDTH)
        self._name_widget: Static | None = None
        self._meter_widget: Static | None = None
        self._controls_widget: Static | None = None

    @property
    def expanded(self) -> bool:
        return not self.session.muted

    def compose(self) -> ComposeResult:
        # markup=False: feed labels are arbitrary third-party text and must
        # never be parsed as Rich console markup.
        yield Static(classes="feed-name", markup=False)
        yield Static(classes="feed-meter", markup=False)
        yield Static(classes="feed-controls", markup=False)

    def on_mount(self) -> None:
        self._name_widget = self.query_one(".feed-name", Static)
        self._meter_widget = self.query_one(".feed-meter", Static)
        self._controls_widget = self.query_one(".feed-controls", Static)
        self.refresh_all()

    def push_level(self, dbfs: float) -> None:
        self._history.append(dbfs)
        self.refresh_meter()

    def refresh_all(self) -> None:
        self.refresh_name()
        self.refresh_meter()

    def refresh_name(self) -> None:
        if self._name_widget is None or self._controls_widget is None:
            return
        session = self.session
        expanded = self.expanded
        self.set_class(expanded, "expanded")
        self.set_class(not expanded, "compact")
        # Dimming is a class, not a colour written into the string: the
        # meter must keep its full contrast relationship while the whole row
        # reads as inactive.
        self.set_class(session.muted, "muted")
        self.set_class(bool(getattr(session, "ambient", False)), "ambient")
        self.set_class(bool(getattr(session, "soloed", False)), "soloed")

        if expanded:
            self._name_widget.update(
                expanded_name_line(session.name, state=session.state),
                layout=False,
            )
            self._controls_widget.update(
                control_line(
                    muted=session.muted,
                    ambient=bool(getattr(session, "ambient", False)),
                    soloed=bool(getattr(session, "soloed", False)),
                    activity=getattr(session, "activity", None),
                ),
                layout=False,
            )
        else:
            self._name_widget.update(
                compact_line(
                    session.name,
                    muted=session.muted,
                    ambient=bool(getattr(session, "ambient", False)),
                    state=session.state,
                ),
                layout=False,
            )
        self._meter_widget.display = expanded
        self._controls_widget.display = expanded

    def refresh_meter(self) -> None:
        if self._meter_widget is None or not self.expanded:
            return
        self._meter_widget.update("\n".join(meter_rows(self._history)), layout=False)
```

`refresh_meter` returns early when compact, so a muted feed accumulates history without paying any redraw cost — which is what makes "meters whether or not it is audible" affordable at twelve feeds.

- [ ] **Step 4: Update the CSS**

In `src/squelch/squelch.tcss`, replace the `.feed`, `.feed-name`, and `.feed-meter` rules:

```css
.feed {
    padding: 0 1;
    border-top: solid $primary;
}

/* Compact is one line plus its rule; expanded adds a three-row meter and a
   control strip. Heights are fixed rather than auto so a row cannot change
   height between a level update and a click. */
.feed.compact {
    height: 2;
}

.feed.expanded {
    height: 6;
}

/* Muted feeds dim, but their meters keep running -- muting is an audio
   gate, not a pause. */
.feed.muted {
    color: $text-disabled;
}

.feed.selected {
    background: $boost;
}

.feed-name {
    height: 1;
}

.feed-meter {
    height: 3;
}

.feed-controls {
    height: 1;
}
```

- [ ] **Step 5: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/squelch/rows.py src/squelch/squelch.tcss tests/test_app.py
git commit -m "feat(squelch): expand audible feeds and keep muted ones compact"
```

---

### Task 6: Click hit-testing

A pure function first, then the widget wiring. This is what makes clicks testable without guessing at pixel offsets.

**Files:**
- Modify: `src/squelch/rows.py`
- Modify: `tests/test_rows.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: the layout constants from Task 4.
- Produces: `control_at(x: int, y: int, *, expanded: bool) -> str | None` returning `"solo"`, `"mute"`, `"ambient"`, or `None` for "no control here — treat as a row-body click". Coordinates are relative to the row's **content** origin, so `(0, 0)` is the first cell after the border and padding.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rows.py`:

```python
from squelch.rows import control_at


def test_a_compact_click_on_the_name_is_not_a_control():
    assert control_at(0, 0, expanded=False) is None
    assert control_at(20, 0, expanded=False) is None


def test_a_compact_click_hits_the_ambient_and_mute_controls():
    line = compact_line("Ground", muted=True, ambient=False, state="live")
    for x in range(len(line)):
        if line[x : x + 3] == "[A]":
            assert control_at(x, 0, expanded=False) == "ambient"
        if line[x : x + 5] == "[OFF]":
            assert control_at(x, 0, expanded=False) == "mute"


def test_a_compact_row_has_no_solo_control():
    assert "solo" not in {
        control_at(x, 0, expanded=False) for x in range(ROW_WIDTH)
    }


def test_a_compact_click_below_the_first_line_is_nothing():
    assert control_at(2, 1, expanded=False) is None


def test_expanded_controls_live_on_the_control_line_only():
    assert control_at(1, 0, expanded=True) is None, "the name line"
    assert control_at(1, 2, expanded=True) is None, "a meter line"
    assert control_at(1, 4, expanded=True) == "solo"


def test_expanded_click_hits_each_control():
    line = control_line(muted=False, ambient=False, soloed=False, activity=None)
    assert line.index("[S]") == 0
    assert control_at(0, 4, expanded=True) == "solo"
    assert control_at(line.index("[ ON]"), 4, expanded=True) == "mute"
    assert control_at(line.index("[A]"), 4, expanded=True) == "ambient"


def test_expanded_click_on_the_activity_readout_is_not_a_control():
    assert control_at(ROW_WIDTH - 1, 4, expanded=True) is None


def test_the_gaps_between_controls_are_not_controls():
    assert control_at(3, 4, expanded=True) is None
    assert control_at(4, 4, expanded=True) is None


def test_out_of_range_coordinates_are_safe():
    assert control_at(-1, 0, expanded=False) is None
    assert control_at(999, 4, expanded=True) is None
    assert control_at(0, -3, expanded=True) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_rows.py -k control_at -v`
Expected: FAIL with `ImportError: cannot import name 'control_at'`.

- [ ] **Step 3: Implement**

Append to `src/squelch/rows.py`. The spans are derived from the format strings in Task 4, so a change to either must change both:

```python
# Cell spans of each control, as half-open [start, stop) ranges within the
# 46-cell content area. Derived from the format strings above -- compact is
# `name(34) SP [A](3) SP [xx](5) SP dot`, expanded's control line is
# `[S](3) SP SP [xx](5) SP SP [A](3)`.
_COMPACT_AMBIENT = (NAME_WIDTH + 1, NAME_WIDTH + 4)          # 35..38
_COMPACT_TOGGLE = (NAME_WIDTH + 5, NAME_WIDTH + 10)          # 39..44
_EXPANDED_SOLO = (0, 3)
_EXPANDED_TOGGLE = (5, 10)
_EXPANDED_AMBIENT = (12, 15)

# Row-relative line indices when expanded: name, meter x3, controls.
CONTROL_LINE_Y = 4


def _within(x: int, span: tuple[int, int]) -> bool:
    return span[0] <= x < span[1]


def control_at(x: int, y: int, *, expanded: bool) -> str | None:
    """Which control, if any, sits at a content-relative cell.

    `None` means "no control here", which the caller treats as a click on
    the row body -- and a click on the row body toggles mute, so the common
    action never requires aiming at a 5-cell target.
    """
    if expanded:
        if y != CONTROL_LINE_Y:
            return None
        if _within(x, _EXPANDED_SOLO):
            return "solo"
        if _within(x, _EXPANDED_TOGGLE):
            return "mute"
        if _within(x, _EXPANDED_AMBIENT):
            return "ambient"
        return None
    if y != 0:
        return None
    if _within(x, _COMPACT_AMBIENT):
        return "ambient"
    if _within(x, _COMPACT_TOGGLE):
        return "mute"
    return None
```

- [ ] **Step 4: Wire it to clicks**

Add to `FeedRow`:

```python
    def on_click(self, event) -> None:
        """Route a click to a control, or to the row body.

        Coordinates come from the screen and are rebased on `content_region`
        rather than on hardcoded offsets, so the border and padding in the
        stylesheet stay the single source of truth for where content starts.
        """
        content = self.content_region
        control = control_at(
            event.screen_x - content.x,
            event.screen_y - content.y,
            expanded=self.expanded,
        )
        self.post_message(RowClicked(self, control))
```

and above the class:

```python
class RowClicked(Message):
    """A click landed on a row, on `control` or on its body (`None`)."""

    def __init__(self, row: "FeedRow", control: str | None) -> None:
        super().__init__()
        self.row = row
        self.control = control
```

importing `from textual.message import Message`.

- [ ] **Step 5: Handle it in the app**

In `SquelchApp`, add:

```python
    def on_row_clicked(self, message: RowClicked) -> None:
        session = message.row.session
        self._selected = self._sessions.index(session)
        self._apply_selection()
        if message.control == "solo":
            self.action_toggle_solo()
        elif message.control == "ambient":
            self.action_toggle_ambient()
        else:
            # Both an explicit [ON]/[OFF] hit and a click anywhere on the
            # row body mute the feed -- the common action must not require
            # aiming at a 5-cell target.
            self.action_toggle_mute()
```

Import `RowClicked` from `squelch.rows`. `action_toggle_solo` and `action_toggle_ambient` arrive in Tasks 7 and 8; add temporary stubs that `pass` so this task's tests run, and delete the stubs when those tasks land.

- [ ] **Step 6: Write the click tests**

Append to `tests/test_app.py`:

```python
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
        await pilot.click(app._rows[id(app._sessions[2])], offset=(3, 0))
        await pilot.pause()
        assert app.selected_session is app._sessions[2]


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
```

- [ ] **Step 7: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/squelch/rows.py src/squelch/app.py tests/test_rows.py tests/test_app.py
git commit -m "feat(squelch): make rows and their controls clickable"
```

---

### Task 7: The solo state machine

Pure, no Textual, no session imports. Solo is the one piece of this plan with real state, so it gets its own module and its own tests.

**Files:**
- Create: `src/squelch/solo.py`
- Create: `tests/test_solo.py`

**Interfaces:**
- Consumes: nothing.
- Produces: class `Solo` with:
  - `active: bool`
  - `target: object | None` — the soloed key, or `None`
  - `engage(target, states: dict) -> dict` — record `states` if not already active, return the new mute states
  - `disengage() -> dict | None` — return the recorded states, or `None` if not active
  - `cancel() -> None` — discard the recording without restoring
  - `is_soloed(key) -> bool`

  `states` maps an opaque key (the caller uses `id(session)`) to `bool` muted.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_solo.py`:

```python
"""The solo state machine.

Solo has to be reversible: engaging records the mix so one press of `S`
returns to it. Everything here is about that recording surviving -- or
being correctly discarded -- as the user keeps pressing things.
"""

from squelch.solo import Solo

# Three feeds: the first audible, the others muted.
MIX = {"a": False, "b": True, "c": True}


def test_a_fresh_solo_is_inactive():
    solo = Solo()
    assert solo.active is False
    assert solo.target is None


def test_engaging_mutes_everything_except_the_target():
    solo = Solo()
    assert solo.engage("b", MIX) == {"a": True, "b": False, "c": True}
    assert solo.active is True
    assert solo.target == "b"


def test_disengaging_restores_the_recorded_mix_exactly():
    solo = Solo()
    solo.engage("b", MIX)
    assert solo.disengage() == MIX
    assert solo.active is False
    assert solo.target is None


def test_disengaging_when_inactive_returns_nothing():
    assert Solo().disengage() is None


def test_soloing_a_second_feed_keeps_the_original_recording():
    """One disengage must still return to the pre-solo mix."""
    solo = Solo()
    solo.engage("b", MIX)
    moved = solo.engage("c", {"a": True, "b": False, "c": True})
    assert moved == {"a": True, "b": True, "c": False}
    assert solo.target == "c"
    assert solo.disengage() == MIX


def test_cancel_discards_the_recording_without_restoring():
    solo = Solo()
    solo.engage("b", MIX)
    solo.cancel()
    assert solo.active is False
    assert solo.disengage() is None


def test_is_soloed_names_only_the_target():
    solo = Solo()
    solo.engage("b", MIX)
    assert solo.is_soloed("b") is True
    assert solo.is_soloed("a") is False


def test_nothing_is_soloed_when_inactive():
    assert Solo().is_soloed("a") is False


def test_engaging_does_not_mutate_the_caller_s_mix():
    solo = Solo()
    original = dict(MIX)
    solo.engage("b", MIX)
    assert MIX == original


def test_soloing_the_only_feed_leaves_it_audible():
    solo = Solo()
    assert solo.engage("a", {"a": True}) == {"a": False}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_solo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'squelch.solo'`.

- [ ] **Step 3: Implement**

Create `src/squelch/solo.py`:

```python
"""Solo: hear one feed, then get your mix back.

Kept apart from the UI and from `FeedSession` because the interesting part
is not muting -- it is that engaging records the mix so one press returns to
it, and that the recording has to survive the solo moving to another feed
while being discarded the moment the user mutes something by hand.
"""

from __future__ import annotations


class Solo:
    def __init__(self) -> None:
        self._recorded: dict | None = None
        self.target = None

    @property
    def active(self) -> bool:
        return self._recorded is not None

    def engage(self, target, states: dict) -> dict:
        """Mute everything but `target`, recording `states` the first time.

        Moving the solo to a different feed deliberately does *not*
        re-record: the recording is of the mix the user built, and the mixes
        that solo itself creates are not worth returning to.
        """
        if self._recorded is None:
            self._recorded = dict(states)
        self.target = target
        return {key: key != target for key in states}

    def disengage(self) -> dict | None:
        recorded, self._recorded = self._recorded, None
        self.target = None
        return recorded

    def cancel(self) -> None:
        """Drop the recording without restoring it.

        Called when the user mutes something by hand while solo is active:
        they have expressed a new intent, so returning to the old mix later
        would undo it.
        """
        self._recorded = None
        self.target = None

    def is_soloed(self, key) -> bool:
        return self.active and key == self.target
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_solo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/solo.py tests/test_solo.py
git commit -m "feat(squelch): add the solo state machine"
```

---

### Task 8: Wire solo and ambient into the app

**Files:**
- Modify: `src/squelch/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `Solo` from Task 7, `session.toggle_ambient` from Task 3, `RowClicked` from Task 6.
- Produces: `SquelchApp.action_toggle_solo()`, `SquelchApp.action_toggle_ambient()`, bindings `S` and `a`, and `session.soloed` maintained on every session for `FeedRow.refresh_name` to read.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
# -- solo ------------------------------------------------------------------


def mix(app):
    return [s.muted for s in app._sessions]


@pytest.mark.asyncio
async def test_solo_mutes_every_other_feed():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        app._selected = 2
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        assert mix(app) == [True, True, False, True]


@pytest.mark.asyncio
async def test_solo_restores_the_prior_mix_including_other_unmuted_feeds():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        app._sessions[3].muted = False
        before = mix(app)
        assert before == [False, True, True, False]
        app._selected = 2
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        await pilot.press("S")
        await pilot.pause()
        assert mix(app) == before


@pytest.mark.asyncio
async def test_moving_the_solo_then_disengaging_returns_to_the_pre_solo_mix():
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        before = mix(app)
        app._selected = 1
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        app._selected = 3
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        assert mix(app) == [True, True, True, False]
        await pilot.press("S")
        await pilot.pause()
        assert mix(app) == before


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
        app._selected = 1
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        assert app._rows[id(app._sessions[1])].has_class("soloed")
        assert not app._rows[id(app._sessions[0])].has_class("soloed")


@pytest.mark.asyncio
async def test_solo_expands_only_the_soloed_row():
    """Expansion follows audibility, so solo reshapes the whole stack."""
    app = make_app(4)
    async with app.run_test(size=SIZE) as pilot:
        app._selected = 2
        app._apply_selection()
        await pilot.press("S")
        await pilot.pause()
        heights = [app._rows[id(s)].outer_size.height for s in app._sessions]
        assert heights == [2, 2, 6, 2]


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_app.py -k "solo or ambient" -v`
Expected: FAIL — `S` and `a` are unbound, and `app._solo` does not exist.

- [ ] **Step 3: Implement**

In `SquelchApp.BINDINGS`, replace the list with:

```python
    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("space", "toggle_mute", "Mute"),
        ("S", "toggle_solo", "Solo"),
        ("a", "toggle_ambient", "Ambient"),
        ("f", "show_feeds", "Feeds"),
        ("q", "quit", "Quit"),
    ]
```

In `__init__`, after `self._selected = 0`:

```python
        self._solo = Solo()
        for session in self._sessions:
            session.soloed = False
```

Import `from squelch.solo import Solo`.

Replace `action_toggle_mute` and delete the Task 6 stubs:

```python
    def action_toggle_mute(self) -> None:
        session = self.selected_session
        if session is None:
            return
        if self._solo.active:
            # The user has muted something by hand, so the mix solo recorded
            # is no longer the one they want back.
            self._solo.cancel()
            self._clear_solo_marks()
        session.toggle_mute()
        self._refresh_row(session)

    def action_toggle_solo(self) -> None:
        session = self.selected_session
        if session is None:
            return
        if self._solo.is_soloed(id(session)):
            restored = self._solo.disengage()
            if restored is not None:
                self._apply_mix(restored)
        else:
            states = {id(s): s.muted for s in self._sessions}
            self._apply_mix(self._solo.engage(id(session), states))
        self._clear_solo_marks()
        self._refresh_rows()

    def action_toggle_ambient(self) -> None:
        session = self.selected_session
        if session is None:
            return
        session.toggle_ambient()
        self._refresh_row(session)

    def _apply_mix(self, states: dict) -> None:
        for session in self._sessions:
            if id(session) in states:
                session.muted = states[id(session)]

    def _clear_solo_marks(self) -> None:
        for session in self._sessions:
            session.soloed = self._solo.is_soloed(id(session))

    def _refresh_row(self, session) -> None:
        row = self._rows.get(id(session))
        if row is not None:
            row.refresh_all()

    def _refresh_rows(self) -> None:
        for session in self._sessions:
            self._refresh_row(session)
```

`refresh_all` rather than `refresh_name`, because a mute change flips the row between compact and expanded and the meter has to be redrawn or cleared.

- [ ] **Step 4: Style the lit and dim controls**

Append to `src/squelch/squelch.tcss`:

```css
/* Controls read as lit or dim by the row's own state. The row already dims
   wholesale when muted, so these only need to mark what is *on*. */
.feed.soloed .feed-controls {
    text-style: bold;
}

.feed.ambient .feed-name,
.feed.ambient .feed-controls {
    color: $secondary;
}
```

- [ ] **Step 5: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/squelch/app.py src/squelch/squelch.tcss tests/test_app.py
git commit -m "feat(squelch): add solo and ambient routing controls"
```

---

### Task 9: The feed picker becomes a jump list

**Files:**
- Modify: `src/squelch/app.py`
- Modify: `src/squelch/__main__.py`
- Modify: `tests/test_feed_picker.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `SquelchApp._sessions`, `_selected`, `_apply_selection`.
- Produces: `SquelchApp.on_feed_selected` now defaults to jumping the selection to the matching session. `feed_selection_hint` is deleted from `__main__.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_feed_picker.py`:

```python
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
        assert any("knowhere_twr" in str(w.renderable) for w in app._entries)


@pytest.mark.asyncio
async def test_the_picker_still_shows_idents_as_secondary_text():
    """Idents leave the row but not the picker -- squelch.toml still takes one."""
    feeds = [Feed(ident="kpdx3_twr", label="KPDX Tower (Both)")]
    screen = FeedPicker(feeds)
    app = make_app(1)
    async with app.run_test(size=SIZE) as pilot:
        await app.push_screen(screen)
        await pilot.pause()
        assert "kpdx3_twr" in "\n".join(rendered(app)[0])
```

Use whatever `make_app` / `rendered` helpers `tests/test_feed_picker.py` already defines; if it has none, import them from `tests/test_app.py` by copying the two helpers, matching that file's style.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_feed_picker.py -v`
Expected: FAIL with `AttributeError: 'SquelchApp' object has no attribute 'jump_to_feed'`.

- [ ] **Step 3: Implement**

In `SquelchApp`, replace `self.on_feed_selected = lambda feed: None` in `__init__` with `self.on_feed_selected = self.jump_to_feed`, and add:

```python
    def jump_to_feed(self, feed) -> None:
        """Move the selection to `feed`'s row.

        The picker used to exist to report an ident, which stopped making
        sense when the row stopped showing one. What it is good for now is
        finding a frequency quickly -- which matters more once activity
        sorting is moving rows around.
        """
        for index, session in enumerate(self._sessions):
            if session.feed.ident == feed.ident:
                self._selected = index
                self._apply_selection()
                return
        self.warn(f"{feed.ident} is not open")
```

- [ ] **Step 4: Delete the superseded hint**

In `src/squelch/__main__.py`, delete `feed_selection_hint` and the line
`app.on_feed_selected = lambda feed: app.warn(feed_selection_hint(feed))`.
The app now wires its own default. Delete the `feed_selection_hint` tests in `tests/test_main.py`.

- [ ] **Step 5: Show idents as secondary text in the picker**

In `FeedPicker.compose`, keep the ident but mark it visually secondary:

```python
    def compose(self) -> ComposeResult:
        yield ListView(
            *[
                ListItem(
                    Label(
                        f"{_fit(f.label, _PICKER_LABEL_WIDTH)} "
                        f"{_fit(f.ident, _PICKER_IDENT_WIDTH)}",
                        markup=False,
                        classes="picker-ident",
                    )
                )
                for f in self._feeds
            ],
            id="feedlist",
        )
```

and in `squelch.tcss`:

```css
FeedPicker ListItem .picker-ident {
    color: $text-muted;
}
```

- [ ] **Step 6: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/squelch/app.py src/squelch/__main__.py src/squelch/squelch.tcss tests/test_feed_picker.py tests/test_main.py
git commit -m "feat(squelch): turn the feed picker into a jump list"
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code-facing.

- [ ] **Step 1: Update the sample pane**

In `README.md`, replace the squelch sample block with the new layout:

```
 KCGX  12 feeds               07:54:29  10 live
────────────────────────────────────────────────
 Tower (Both)                               ●
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 [S]  [ ON]  [A]
────────────────────────────────────────────────
 Ground                          [A] [OFF] ◐
────────────────────────────────────────────────
 Clearance Delivery              [A] [OFF] ●
```

- [ ] **Step 2: Rewrite the prose that the old layout supported**

Replace the paragraph beginning "`♪` is audible, `·` is muted" with:

> An audible feed is **expanded** — a three-row meter and its full controls.
> A muted feed collapses to a single **compact** line. Expansion follows what
> you can hear, so the pane spends its height on the frequencies you are
> actually listening to. **Every feed meters whether or not it is audible** —
> muting is an audio gate, not a pause — a muted feed simply keeps its history
> without drawing it. The dot on the right is that feed's connection: `●`
> live, `◐` reconnecting, `○` offline.
>
> Feed idents no longer appear on the row. They are still what `feed` in
> `squelch.toml` and `--feed` take, and the feed picker (`f`) still shows them.

- [ ] **Step 3: Update the key bindings table**

```markdown
| Key     | Action |
|---------|--------|
| `↑` `↓` | Move the selection through the stack. |
| `space` | Mute/unmute the selected feed. Its meter keeps running either way. |
| `S`     | Solo the selected feed — mute every other one. Press again to restore the previous mix. |
| `a`     | Route the selected feed to the ambient bus. |
| `f`     | Open the feed picker and jump to a feed by name. |
| `escape`| (in the feed picker) Close it without choosing anything. |
| `q`     | Quit. |

Every control is also clickable: `[S]`, `[ ON]`/`[OFF]`, and `[A]`. Clicking
anywhere else on a row toggles its mute.
```

- [ ] **Step 4: Update "Known limitations"**

Delete "The picker cannot switch feeds, because they are all already open" and "There is no master mute or solo — muting is per feed." Add:

> - `[A]` is rendered and toggleable but silent until the mixing engine lands.

- [ ] **Step 5: Run the full suite once more**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs(squelch): document the restructured feed row"
```

---

## Verification

After Task 10, the following must all hold:

- `uv run pytest` passes with no skips.
- No source file outside `app.py` and `rows.py` imports `textual`.
- `grep -rn "IDENT_WIDTH\|meter_bar\|feed_selection_hint" src/ tests/` returns nothing.
- Launching `uv run squelch` in a 48-column pane shows one expanded feed and the rest compact, and clicking a compact row expands it.
