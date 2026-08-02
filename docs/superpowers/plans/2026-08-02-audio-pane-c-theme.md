# Audio Pane C — Theme Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the audio pane adopt the radar pane's colour scheme, and keep it in step when that theme changes at runtime.

**Architecture:** `adsb-tui` does not persist its theme, so the rendered pane is the only source of truth. A worker thread polls `tmux capture-pane -e`, counts the truecolor background sequences, and looks the most frequent one up in a table of harvested backgrounds. Extraction and lookup are pure functions; the subprocess is injected, so nothing in the test suite needs tmux or adsb-tui.

**Tech Stack:** Python 3.14, Textual 8.2.8 (`textual.theme.Theme`, `App.register_theme`, `App.theme`), pytest 9.1.1.

**Spec:** `docs/superpowers/specs/2026-08-02-audio-pane-theme-design.md`

**Depends on:** plan A (needs `rows.py` and the row widgets) and plan B (supplies `MeterPalette`, which this plan populates per theme).

## Global Constraints

- The theme is identified by the **most frequent** `ESC[48;2;r;g;b m` background in a capture — never the first. The first background varies with adsb-tui's layout: `default` yields `rgb(22,26,32)` in radar layout and `rgb(28,32,38)` in full layout.
- Matching is **exact** against the harvested table. An unrecognised background leaves the current theme in place — never snap to the nearest of six.
- Polling runs on a **worker thread** with a **2 s subprocess timeout**. It must never touch audio or block the event loop.
- A failed poll is **silent**. A closed pane must not warn every 3 s for hours.
- Fallback order: sampled theme → `theme` key from `adsb-tui.toml` (read once) → `default`.
- The adsb-tui config path is `$XDG_CONFIG_HOME/ads-b-tui/adsb-tui.toml`, falling back to `~/.config/ads-b-tui/adsb-tui.toml`.
- `themes.py` and `radar_theme.py` **must not import `textual`** except for the `Theme` construction in `themes.py`, which is unavoidable and confined to one function.
- No test may run `tmux`, run `adsb-tui`, or read the user's real config. Inject the runner and the path.
- Run tests with `uv run pytest`.

---

## Harvested data

Measured against `~/bin/adsb-tui` on 2026-08-02 across the `radar`, `full`, and `compact` layouts in `--demo-mode`. All six sets are pairwise disjoint.

**Backgrounds** (the identifying fingerprint):

| theme | backgrounds |
|---|---|
| `default` | `(18,20,24)` `(20,22,26)` `(22,26,32)` `(28,32,38)` `(198,238,232)` |
| `color` | `(10,16,20)` `(14,20,24)` `(16,22,26)` `(20,26,30)` |
| `amber` | `(20,16,10)` `(24,18,10)` `(28,22,12)` `(32,24,14)` `(255,220,120)` |
| `ocean` | `(10,18,24)` `(12,24,30)` |
| `matrix` | `(0,12,0)` `(0,16,0)` `(0,18,0)` `(0,22,0)` |
| `mono` | `(4,4,4)` `(8,8,8)` `(10,10,10)` `(20,20,20)` |

**Foregrounds.** `default`, `amber`, `ocean`, and `matrix` emit truecolor foregrounds and were harvested directly. **`color` and `mono` emit none** — they draw with the terminal's own ANSI palette. Their squelch palettes therefore use ANSI colour names rather than hex, which is the faithful match: adopting the terminal's palette is exactly what adsb-tui is doing.

| theme | harvested foregrounds |
|---|---|
| `default` | `(140,150,160)` `(198,238,232)` `(108,221,214)` `(255,200,120)` `(255,102,102)` |
| `amber` | `(140,110,40)` `(255,191,0)` |
| `ocean` | `(80,120,130)` `(0,200,220)` |
| `matrix` | `(0,120,0)` |
| `color`, `mono` | none — ANSI |

Where a theme yielded fewer than four distinct foregrounds, the remaining meter stops are interpolated within the harvested hue family. Those values are marked in the source.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/squelch/themes.py` | **New.** Background extraction, RGB → theme name, the six palettes, Textual `Theme` construction |
| `src/squelch/radar_theme.py` | **New.** The poller: subprocess invocation, change detection, config fallback |
| `src/squelch/app.py` | Register themes, apply on change, push the palette to every row |
| `bin/kcgx` | Export `KCGX_RADAR_PANE` |
| `tests/test_themes.py` | **New.** Extraction, mapping, palette completeness |
| `tests/test_radar_theme.py` | **New.** Polling, failure modes, fallback chain |
| `tests/test_app.py` | Extended: theme application repaints rows |
| `tests/test_kcgx_launcher.py` | Extended: the pane id is exported |

---

### Task 1: Background extraction and theme identification

**Files:**
- Create: `src/squelch/themes.py`
- Create: `tests/test_themes.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `THEME_BACKGROUNDS: dict[str, tuple[tuple[int, int, int], ...]]` — the harvested table
  - `backgrounds(capture: str) -> list[tuple[int, int, int]]` — every background in order of appearance
  - `dominant_background(capture: str) -> tuple[int, int, int] | None` — the most frequent, ties broken by first appearance
  - `theme_for(capture: str) -> str | None` — the theme name, or `None`
  - `THEME_NAMES: tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_themes.py`:

```python
"""Identifying the radar pane's theme from what it painted.

adsb-tui never writes its theme to disk -- verified: two `t` presses and a
clean quit left the config byte-identical while the pane background changed.
The rendered pane is the only source of truth, so these tests work on
captured escape sequences.
"""

from squelch.themes import (
    THEME_BACKGROUNDS,
    THEME_NAMES,
    backgrounds,
    dominant_background,
    theme_for,
)

ESC = "\x1b"


def paint(*triples):
    """A capture-pane-shaped string with the given backgrounds."""
    return "".join(f"{ESC}[48;2;{r};{g};{b}mXX" for r, g, b in triples)


def test_backgrounds_are_extracted_in_order():
    assert backgrounds(paint((1, 2, 3), (4, 5, 6))) == [(1, 2, 3), (4, 5, 6)]


def test_a_capture_with_no_backgrounds_yields_nothing():
    assert backgrounds("plain text, no escapes") == []
    assert dominant_background("plain text") is None
    assert theme_for("plain text") is None


def test_foreground_sequences_are_not_mistaken_for_backgrounds():
    capture = f"{ESC}[38;2;10;20;30mtext"
    assert backgrounds(capture) == []


def test_the_dominant_background_is_the_most_frequent():
    capture = paint((1, 1, 1), (2, 2, 2), (2, 2, 2))
    assert dominant_background(capture) == (2, 2, 2)


def test_a_tie_is_broken_by_first_appearance():
    """Deterministic, so a theme cannot flicker between two equal fills."""
    capture = paint((1, 1, 1), (2, 2, 2))
    assert dominant_background(capture) == (1, 1, 1)


def test_every_theme_is_identified_by_its_own_backgrounds():
    for name, triples in THEME_BACKGROUNDS.items():
        for triple in triples:
            assert theme_for(paint(triple)) == name, f"{name} {triple}"


def test_the_theme_survives_a_layout_change():
    """`default` fills with (22,26,32) in radar layout and (28,32,38) in
    full layout. Both must identify the same theme."""
    assert theme_for(paint((22, 26, 32))) == "default"
    assert theme_for(paint((28, 32, 38))) == "default"


def test_an_unknown_background_identifies_nothing():
    assert theme_for(paint((123, 45, 67))) is None


def test_a_stray_highlight_does_not_outvote_the_pane_fill():
    capture = paint(*([(14, 20, 24)] * 70), *([(198, 238, 232)] * 3))
    assert theme_for(capture) == "color"


def test_the_background_sets_are_pairwise_disjoint():
    """Any single recognised triple must identify exactly one theme."""
    seen = {}
    for name, triples in THEME_BACKGROUNDS.items():
        for triple in triples:
            assert triple not in seen, f"{triple} in both {seen.get(triple)} and {name}"
            seen[triple] = name


def test_all_six_adsb_tui_themes_are_covered():
    assert set(THEME_NAMES) == {
        "default",
        "color",
        "amber",
        "ocean",
        "matrix",
        "mono",
    }
    assert set(THEME_BACKGROUNDS) == set(THEME_NAMES)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_themes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'squelch.themes'`.

- [ ] **Step 3: Implement**

Create `src/squelch/themes.py`:

```python
"""The radar pane's colour scheme, read off the radar pane.

adsb-tui ships six themes and a `t` key that cycles them at runtime, and it
never writes the result anywhere: measured on 2026-08-02, two `t` presses
and a clean quit left its TOML byte-identical while the pane background
moved from rgb(14,20,24) to rgb(24,18,10). Watching the file would observe
nothing, so the theme is identified from what the pane actually painted.
"""

from __future__ import annotations

import re
from collections import Counter

# Harvested from ~/bin/adsb-tui on 2026-08-02 across the radar, full, and
# compact layouts. Identification uses the *most frequent* background, not
# the first: the first varies with layout (default paints (22,26,32) in
# radar and (28,32,38) in full), while the most frequent is the pane fill.
# The sets are pairwise disjoint, which a test enforces.
THEME_BACKGROUNDS: dict[str, tuple[tuple[int, int, int], ...]] = {
    "default": ((18, 20, 24), (20, 22, 26), (22, 26, 32), (28, 32, 38), (198, 238, 232)),
    "color": ((10, 16, 20), (14, 20, 24), (16, 22, 26), (20, 26, 30)),
    "amber": ((20, 16, 10), (24, 18, 10), (28, 22, 12), (32, 24, 14), (255, 220, 120)),
    "ocean": ((10, 18, 24), (12, 24, 30)),
    "matrix": ((0, 12, 0), (0, 16, 0), (0, 18, 0), (0, 22, 0)),
    "mono": ((4, 4, 4), (8, 8, 8), (10, 10, 10), (20, 20, 20)),
}

THEME_NAMES = tuple(THEME_BACKGROUNDS)

_BY_BACKGROUND = {
    triple: name
    for name, triples in THEME_BACKGROUNDS.items()
    for triple in triples
}

_BACKGROUND_RE = re.compile(r"\x1b\[48;2;(\d{1,3});(\d{1,3});(\d{1,3})m")


def backgrounds(capture: str) -> list[tuple[int, int, int]]:
    """Every truecolor background in a captured pane, in order."""
    return [
        (int(r), int(g), int(b)) for r, g, b in _BACKGROUND_RE.findall(capture)
    ]


def dominant_background(capture: str) -> tuple[int, int, int] | None:
    """The most frequent background -- the pane fill.

    Ties break by first appearance so the answer is deterministic and a
    theme cannot flicker between two equally common fills.
    """
    found = backgrounds(capture)
    if not found:
        return None
    counts = Counter(found)
    best = max(counts.values())
    for triple in found:
        if counts[triple] == best:
            return triple
    return None


def theme_for(capture: str) -> str | None:
    """Which adsb-tui theme painted this, or `None` if it is not one of ours.

    Deliberately an exact match rather than nearest-colour: an unrecognised
    fill means adsb-tui has changed or something else is in that pane, and
    silently snapping to the closest of six would be worse than doing
    nothing.
    """
    triple = dominant_background(capture)
    if triple is None:
        return None
    return _BY_BACKGROUND.get(triple)
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_themes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/themes.py tests/test_themes.py
git commit -m "feat(squelch): identify the radar pane's theme from its backgrounds"
```

---

### Task 2: The six palettes

**Files:**
- Modify: `src/squelch/themes.py`
- Modify: `tests/test_themes.py`

**Interfaces:**
- Consumes: `THEME_NAMES` (Task 1), `MeterPalette` from plan B's `rows.py`.
- Produces:
  - `METER_PALETTES: dict[str, MeterPalette]` — one per theme
  - `textual_theme(name: str) -> Theme` — a registered-ready Textual theme
  - `TEXTUAL_THEME_PREFIX = "kcgx-"` — registered names are `kcgx-default`, `kcgx-color`, and so on, so they cannot collide with Textual's built-ins

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_themes.py`:

```python
from squelch.themes import METER_PALETTES, TEXTUAL_THEME_PREFIX, textual_theme


def test_every_theme_has_a_meter_palette():
    assert set(METER_PALETTES) == set(THEME_NAMES)


def test_every_palette_defines_all_four_stops():
    for name, palette in METER_PALETTES.items():
        for stop in ("dim", "text", "accent", "peak"):
            assert getattr(palette, stop), f"{name}.{stop} is empty"


def test_palette_stops_are_distinct_within_a_theme():
    """A gradient whose stops collide is not a gradient."""
    for name, palette in METER_PALETTES.items():
        stops = [palette.dim, palette.text, palette.accent, palette.peak]
        assert len(set(stops)) == 4, f"{name} has duplicate stops"


def test_color_and_mono_use_ansi_names_not_hex():
    """Neither emits truecolor foregrounds; they draw with the terminal's
    own palette, so matching them means doing the same."""
    for name in ("color", "mono"):
        assert not METER_PALETTES[name].accent.startswith("#")


def test_the_other_themes_use_harvested_hex():
    for name in ("default", "amber", "ocean", "matrix"):
        assert METER_PALETTES[name].accent.startswith("#")


def test_textual_themes_are_built_for_every_name():
    for name in THEME_NAMES:
        theme = textual_theme(name)
        assert theme.name == f"{TEXTUAL_THEME_PREFIX}{name}"
        assert theme.background
        assert theme.primary


def test_an_unknown_theme_name_raises():
    import pytest

    with pytest.raises(KeyError):
        textual_theme("chartreuse")


def test_the_textual_background_matches_the_pane_fill():
    """squelch sitting beside the radar pane must not be a different shade."""
    theme = textual_theme("matrix")
    assert theme.background.lower() == "#001000"  # rgb(0,16,0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_themes.py -k "palette or textual" -v`
Expected: FAIL with `ImportError: cannot import name 'METER_PALETTES'`.

- [ ] **Step 3: Implement**

Append to `src/squelch/themes.py`:

```python
from textual.theme import Theme

from squelch.rows import MeterPalette

TEXTUAL_THEME_PREFIX = "kcgx-"

# The pane fill each theme is matched to. Picked from THEME_BACKGROUNDS as
# the one adsb-tui uses for the body of the pane, so squelch sits beside it
# in the same shade rather than a neighbouring one.
_FILL = {
    "default": "#161a20",   # rgb(22,26,32)
    "color": "#0e1418",     # rgb(14,20,24)
    "amber": "#18120a",     # rgb(24,18,10)
    "ocean": "#0a1218",     # rgb(10,18,24)
    "matrix": "#001000",    # rgb(0,16,0)
    "mono": "#080808",      # rgb(8,8,8)
}

# Meter gradient stops. `default`, `amber`, `ocean`, and `matrix` are built
# from foregrounds harvested off the live binary; where a theme yielded
# fewer than four distinct foregrounds the gaps are interpolated within its
# harvested hue family, and those are marked. `color` and `mono` emit no
# truecolor foregrounds at all -- they draw with the terminal's own ANSI
# palette, so matching them means naming ANSI colours rather than hex.
METER_PALETTES: dict[str, MeterPalette] = {
    "default": MeterPalette(
        dim="#8c96a0",      # harvested rgb(140,150,160)
        text="#c6eee8",     # harvested rgb(198,238,232)
        accent="#6cddd6",   # harvested rgb(108,221,214)
        peak="#ff6666",     # harvested rgb(255,102,102)
    ),
    "color": MeterPalette(
        dim="bright_black",
        text="white",
        accent="cyan",
        peak="red",
    ),
    "amber": MeterPalette(
        dim="#8c6e28",      # harvested rgb(140,110,40)
        text="#c99518",     # interpolated
        accent="#ffbf00",   # harvested rgb(255,191,0)
        peak="#ffdc78",     # harvested rgb(255,220,120)
    ),
    "ocean": MeterPalette(
        dim="#507882",      # harvested rgb(80,120,130)
        text="#3aa8bb",     # interpolated
        accent="#00c8dc",   # harvested rgb(0,200,220)
        peak="#b9f0f7",     # interpolated
    ),
    "matrix": MeterPalette(
        dim="#007800",      # harvested rgb(0,120,0)
        text="#00b400",     # interpolated
        accent="#00ff00",   # interpolated
        peak="#b4ffb4",     # interpolated
    ),
    "mono": MeterPalette(
        dim="bright_black",
        text="white",
        accent="bright_white",
        peak="bright_yellow",
    ),
}


def textual_theme(name: str) -> Theme:
    """A Textual theme matching one of adsb-tui's.

    Registered under a `kcgx-` prefix so these can never collide with
    Textual's own built-in theme names.
    """
    palette = METER_PALETTES[name]
    fill = _FILL[name]
    return Theme(
        name=f"{TEXTUAL_THEME_PREFIX}{name}",
        primary=palette.accent,
        secondary=palette.text,
        warning=palette.peak,
        error=palette.peak,
        success=palette.accent,
        accent=palette.accent,
        foreground=palette.text,
        background=fill,
        surface=fill,
        panel=fill,
        dark=True,
    )
```

Note the import of `MeterPalette` from `squelch.rows`, which pulls Textual in transitively — acceptable and confined, since `themes.py` already imports `Theme`.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_themes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/themes.py tests/test_themes.py
git commit -m "feat(squelch): add palettes matching adsb-tui's six themes"
```

---

### Task 3: The poller

**Files:**
- Create: `src/squelch/radar_theme.py`
- Create: `tests/test_radar_theme.py`

**Interfaces:**
- Consumes: `theme_for` (Task 1).
- Produces:
  - `POLL_SECONDS = 3.0`, `CAPTURE_TIMEOUT = 2.0`, `PANE_ENV = "KCGX_RADAR_PANE"`
  - `capture_command(pane: str) -> list[str]`
  - `adsb_config_path(environ: dict) -> Path`
  - `configured_theme(path: Path) -> str | None`
  - class `RadarTheme(*, environ, runner=subprocess.run, config_path=None)` with `initial() -> str` and `poll() -> str | None` (returns the new theme name only when it has changed)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_radar_theme.py`:

```python
"""Following the radar pane's theme.

Nothing here runs tmux or adsb-tui: the subprocess runner is injected and
the config path is a tmp_path. The failure modes matter more than the happy
path -- a pane that has been closed must not warn every three seconds for
the rest of a multi-hour session.
"""

import subprocess

import pytest

from squelch.radar_theme import (
    CAPTURE_TIMEOUT,
    PANE_ENV,
    RadarTheme,
    adsb_config_path,
    capture_command,
    configured_theme,
)

ESC = "\x1b"


def paint(r, g, b, n=10):
    return f"{ESC}[48;2;{r};{g};{b}mXX" * n


AMBER = paint(24, 18, 10)
OCEAN = paint(10, 18, 24)


class FakeRunner:
    """Stands in for subprocess.run."""

    def __init__(self, *results):
        self._results = list(results)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        result = self._results.pop(0) if self._results else self._results
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(argv, 0, stdout=result, stderr="")


def theme(runner, environ=None, **kwargs):
    return RadarTheme(
        environ=environ if environ is not None else {PANE_ENV: "%3"},
        runner=runner,
        **kwargs,
    )


# -- the command -----------------------------------------------------------


def test_the_capture_command_targets_the_pane_and_keeps_escapes():
    argv = capture_command("%3")
    assert argv[:2] == ["tmux", "capture-pane"]
    assert "-e" in argv, "without -e there are no colours to read"
    assert "-p" in argv
    assert argv[-2:] == ["-t", "%3"]


# -- polling ---------------------------------------------------------------


def test_a_capture_identifies_the_theme():
    assert theme(FakeRunner(AMBER)).poll() == "amber"


def test_the_same_theme_twice_reports_a_change_only_once():
    t = theme(FakeRunner(AMBER, AMBER))
    assert t.poll() == "amber"
    assert t.poll() is None, "no change, nothing to apply"


def test_a_changed_theme_is_reported():
    t = theme(FakeRunner(AMBER, OCEAN))
    assert t.poll() == "amber"
    assert t.poll() == "ocean"


def test_the_subprocess_gets_a_timeout():
    runner = FakeRunner(AMBER)
    theme(runner).poll()
    assert runner.calls[0][1]["timeout"] == CAPTURE_TIMEOUT


# -- failure ---------------------------------------------------------------


def test_a_timeout_leaves_the_theme_alone():
    t = theme(FakeRunner(AMBER, subprocess.TimeoutExpired("tmux", 2.0)))
    assert t.poll() == "amber"
    assert t.poll() is None


def test_a_missing_tmux_leaves_the_theme_alone():
    assert theme(FakeRunner(FileNotFoundError("tmux"))).poll() is None


def test_a_closed_pane_leaves_the_theme_alone():
    assert theme(FakeRunner(subprocess.CalledProcessError(1, "tmux"))).poll() is None


def test_an_unrecognised_background_leaves_the_theme_alone():
    t = theme(FakeRunner(AMBER, paint(123, 45, 67)))
    assert t.poll() == "amber"
    assert t.poll() is None, "an unknown fill is not a reason to restyle"


def test_polling_without_a_pane_id_does_nothing():
    runner = FakeRunner(AMBER)
    assert theme(runner, environ={}).poll() is None
    assert runner.calls == [], "no pane means no subprocess at all"


# -- the config fallback ---------------------------------------------------


def test_the_config_path_honours_xdg(tmp_path):
    path = adsb_config_path({"XDG_CONFIG_HOME": str(tmp_path)})
    assert path == tmp_path / "ads-b-tui" / "adsb-tui.toml"


def test_the_config_path_falls_back_to_dot_config():
    path = adsb_config_path({})
    assert path.parts[-3:] == (".config", "ads-b-tui", "adsb-tui.toml")


def test_the_configured_theme_is_read(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text('layout = "radar"\ntheme = "ocean"\n')
    assert configured_theme(path) == "ocean"


def test_a_missing_config_yields_nothing(tmp_path):
    assert configured_theme(tmp_path / "nope.toml") is None


def test_an_unparseable_config_yields_nothing(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text("this is not = = toml")
    assert configured_theme(path) is None


def test_an_unknown_configured_theme_yields_nothing(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text('theme = "chartreuse"\n')
    assert configured_theme(path) is None


# -- the fallback chain ----------------------------------------------------


def test_initial_prefers_the_live_pane(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text('theme = "ocean"\n')
    t = theme(FakeRunner(AMBER), config_path=path)
    assert t.initial() == "amber"


def test_initial_falls_back_to_the_config(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text('theme = "ocean"\n')
    t = theme(FakeRunner(FileNotFoundError("tmux")), config_path=path)
    assert t.initial() == "ocean"


def test_initial_falls_back_to_default(tmp_path):
    t = theme(
        FakeRunner(FileNotFoundError("tmux")),
        config_path=tmp_path / "nope.toml",
    )
    assert t.initial() == "default"


def test_initial_outside_the_cockpit_still_reads_the_config(tmp_path):
    """Standalone squelch themes statically rather than not at all."""
    path = tmp_path / "adsb-tui.toml"
    path.write_text('theme = "matrix"\n')
    t = theme(FakeRunner(), environ={}, config_path=path)
    assert t.initial() == "matrix"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_radar_theme.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'squelch.radar_theme'`.

- [ ] **Step 3: Implement**

Create `src/squelch/radar_theme.py`:

```python
"""Following the radar pane's theme, one `capture-pane` at a time.

Every failure here is silent by design. A pane that has been closed, a tmux
that is not running, a capture that times out -- all of them mean "keep the
theme you have". Warning about any of them would put a message in the log
every three seconds for the rest of the session.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

from squelch.themes import THEME_NAMES, theme_for

POLL_SECONDS = 3.0
# Short, because a hung tmux must not accumulate worker threads over a
# multi-hour session.
CAPTURE_TIMEOUT = 2.0
PANE_ENV = "KCGX_RADAR_PANE"
DEFAULT_THEME = "default"


def capture_command(pane: str) -> list[str]:
    # -e keeps the escape sequences, which are the entire point; -p writes
    # to stdout rather than a paste buffer.
    return ["tmux", "capture-pane", "-e", "-p", "-t", pane]


def adsb_config_path(environ) -> Path:
    root = environ.get("XDG_CONFIG_HOME")
    base = Path(root) if root else Path.home() / ".config"
    return base / "ads-b-tui" / "adsb-tui.toml"


def configured_theme(path: Path) -> str | None:
    """The theme adsb-tui launched with, if the config names a known one."""
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return None
    name = data.get("theme")
    return name if name in THEME_NAMES else None


class RadarTheme:
    def __init__(
        self,
        *,
        environ=None,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        config_path: Path | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._runner = runner
        self._config_path = config_path
        self._current: str | None = None

    def initial(self) -> str:
        """The theme to start on: sampled, else configured, else default."""
        sampled = self._sample()
        if sampled is not None:
            self._current = sampled
            return sampled
        path = self._config_path
        if path is None:
            path = adsb_config_path(self._environ)
        configured = configured_theme(path)
        self._current = configured or DEFAULT_THEME
        return self._current

    def poll(self) -> str | None:
        """The new theme name, or `None` if nothing changed or nothing could
        be read."""
        sampled = self._sample()
        if sampled is None or sampled == self._current:
            return None
        self._current = sampled
        return sampled

    def _sample(self) -> str | None:
        pane = self._environ.get(PANE_ENV)
        if not pane:
            return None
        try:
            result = self._runner(
                capture_command(pane),
                capture_output=True,
                text=True,
                timeout=CAPTURE_TIMEOUT,
                check=True,
            )
        except Exception:
            # tmux missing, pane gone, non-zero exit, timeout. All of them
            # mean the same thing to us: keep what we have.
            return None
        return theme_for(result.stdout or "")
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_radar_theme.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/squelch/radar_theme.py tests/test_radar_theme.py
git commit -m "feat(squelch): poll the radar pane for its current theme"
```

---

### Task 4: Apply the theme in the app

**Files:**
- Modify: `src/squelch/app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `METER_PALETTES`, `textual_theme`, `TEXTUAL_THEME_PREFIX` (Task 2), `RadarTheme`, `POLL_SECONDS` (Task 3).
- Produces: `SquelchApp.apply_theme(name: str) -> None`, `SquelchApp._poll_theme()` (a threaded worker), and `SquelchApp(..., radar_theme=None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
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
    for name in METER_PALETTES:
        app = make_app(6)
        async with app.run_test(size=SIZE) as pilot:
            app.apply_theme(name)
            await pilot.pause()
            _text, strips = rendered(app)
            assert all(s.cell_length == 48 for s in strips), name


@pytest.mark.asyncio
async def test_no_radar_theme_leaves_the_app_on_its_default():
    """Standalone squelch must not require tmux to start."""
    app = make_app(3)
    async with app.run_test(size=SIZE):
        assert app._radar_theme is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_app.py -k theme -v`
Expected: FAIL with `AttributeError: 'SquelchApp' object has no attribute 'apply_theme'`.

- [ ] **Step 3: Implement**

In `src/squelch/app.py`, import:

```python
from squelch.radar_theme import POLL_SECONDS, RadarTheme
from squelch.themes import METER_PALETTES, TEXTUAL_THEME_PREFIX, textual_theme
```

Add a keyword argument to `SquelchApp.__init__`:

```python
        radar_theme: RadarTheme | None = None,
```

and in the body:

```python
        self._radar_theme = radar_theme
        self._theme_timer = None
```

In `on_mount`, after the existing setup:

```python
        for name in METER_PALETTES:
            self.register_theme(textual_theme(name))
        if self._radar_theme is not None:
            self.apply_theme(self._radar_theme.initial())
            self._theme_timer = self.set_interval(POLL_SECONDS, self._poll_theme)
```

In `on_unmount`, beside the other timers:

```python
        if self._theme_timer is not None:
            self._theme_timer.stop()
            self._theme_timer = None
```

Add:

```python
    def apply_theme(self, name: str) -> None:
        """Adopt one of adsb-tui's themes, repainting the meters with it."""
        palette = METER_PALETTES.get(name)
        if palette is None:
            return
        self.theme = f"{TEXTUAL_THEME_PREFIX}{name}"
        for row in self._rows.values():
            row.palette = palette
            row.refresh_meter()

    @work(thread=True, exclusive=True, group="theme")
    def _poll_theme(self) -> None:
        """Sample the radar pane off the event loop.

        `capture-pane` is a subprocess. Called straight from the timer it
        would block Textual's loop for its whole timeout -- and because the
        audio threads reach the UI through call_from_thread, which waits on
        that same loop, playback would stop too.
        """
        assert self._radar_theme is not None
        name = self._radar_theme.poll()
        if name is None:
            return
        try:
            self.call_from_thread(self.apply_theme, name)
        except Exception:
            # The app quit while the capture was in flight.
            pass
```

- [ ] **Step 4: Wire it in `__main__.py`**

In `main()`, build the tracker and pass it:

```python
    app = app_factory(
        config,
        sessions,
        feed_loader=lambda: picker_feeds(config),
        radar_theme=RadarTheme(),
    )
```

importing `from squelch.radar_theme import RadarTheme`. `RadarTheme` defaults to the real `os.environ` and `subprocess.run`, and does nothing at all when `KCGX_RADAR_PANE` is unset — so this is safe outside the cockpit.

- [ ] **Step 5: Run**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/squelch/app.py src/squelch/__main__.py tests/test_app.py
git commit -m "feat(squelch): adopt the radar pane's theme and follow it live"
```

---

### Task 5: Export the pane id from the launcher

**Files:**
- Modify: `bin/kcgx`
- Modify: `tests/test_kcgx_launcher.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the squelch pane's environment carries `KCGX_RADAR_PANE` set to the adsb-tui pane's id.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_kcgx_launcher.py`, following that file's existing style for building a detached session on an isolated socket:

```python
def test_the_squelch_pane_knows_the_radar_pane_id(kcgx_session):
    """squelch samples the radar pane's colours, so it needs its id."""
    value = kcgx_session.pane_env("squelch", "KCGX_RADAR_PANE")
    assert value, "KCGX_RADAR_PANE must be exported into the squelch pane"
    assert value.startswith("%"), "tmux pane ids look like %0, %1, ..."


def test_the_radar_pane_id_matches_the_adsb_pane(kcgx_session):
    exported = kcgx_session.pane_env("squelch", "KCGX_RADAR_PANE")
    assert exported == kcgx_session.pane_id("adsb")
```

If `tests/test_kcgx_launcher.py` has no `kcgx_session` fixture with `pane_env` and `pane_id` helpers, add them: `pane_env` runs `tmux show-environment -t <session> <name>` or reads `/proc`-free via `tmux display-message -p -t <pane> '#{pane_id}'`; `pane_id` runs `tmux list-panes -F '#{pane_index} #{pane_id}'`. Match the isolated-socket pattern (`KCGX_SOCKET`, `KCGX_DETACHED`) the existing tests already use.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_kcgx_launcher.py -k radar -v`
Expected: FAIL — the variable is unset.

- [ ] **Step 3: Implement**

In `bin/kcgx`, after the adsb-tui pane is created and before the squelch pane is split, capture the adsb pane id and pass it through. Locate the `split-window` that creates the squelch pane and give it the environment:

```bash
# squelch samples the radar pane's rendered colours to match its theme --
# adsb-tui never writes the theme anywhere, so the pane is the only source
# of truth. Pass the pane id it needs to capture.
RADAR_PANE="$(tm display-message -p -t "$SESSION:0.0" '#{pane_id}')"
```

and prefix the squelch command:

```bash
tm split-window -h -l "$SQUELCH_COLS" -t "$SESSION:0.0" \
    -e "KCGX_RADAR_PANE=$RADAR_PANE" \
    "$SQUELCH_CMD"
```

`split-window -e` requires tmux 3.0+; the script already refuses anything below 3.1, so no additional version guard is needed.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_kcgx_launcher.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bin/kcgx tests/test_kcgx_launcher.py
git commit -m "feat(kcgx): tell squelch which pane the radar is in"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code-facing.

- [ ] **Step 1: Document the theme sync**

Add a section under the cockpit description:

> ### Matching themes
>
> squelch adopts the radar pane's colour scheme, including its meter gradient.
> It tracks `adsb-tui`'s `t` key within about three seconds.
>
> It does that by *looking at* the radar pane rather than by reading its
> config. `adsb-tui` does not write the theme anywhere when you cycle it —
> measured: two `t` presses and a clean quit leave its TOML byte-identical —
> so the rendered pane is the only truthful source. `kcgx` passes the pane id
> in `KCGX_RADAR_PANE`, and squelch runs `tmux capture-pane -e` every three
> seconds and matches the pane's background colour against the six known
> themes.
>
> Run outside the cockpit, with no `KCGX_RADAR_PANE` set, squelch reads
> `theme` from `adsb-tui.toml` once at startup and stays there. Failing that,
> it uses `default`. Nothing about this can fail loudly: an unreadable pane,
> a missing tmux, or an unrecognised colour all just leave the current theme
> in place.

- [ ] **Step 2: Note the environment variable**

Add to the launcher's environment-override list in `README.md` and in the header comment of `bin/kcgx`:

```
#   KCGX_RADAR_PANE    tmux pane id squelch samples for its theme
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add README.md bin/kcgx
git commit -m "docs(kcgx): document theme sync with the radar pane"
```

---

## Verification

- `uv run pytest` passes with no skips.
- `grep -rn "subprocess" tests/test_radar_theme.py` shows only the injected fake and the exception types — no real invocation.
- `uv run squelch` starts with no tmux running and does not raise.
- In a live cockpit, pressing `t` in the radar pane restyles squelch within ~3 s, and the meter gradient changes with it.
