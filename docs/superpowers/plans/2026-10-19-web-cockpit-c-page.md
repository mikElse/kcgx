# Web Cockpit Phase C: The Page

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace phase B's debug page with the real cockpit page: the NORAD
wall from the mockup, every control a click, served by the phase B server.
Status screen with the airport and clocks, the frequency stack with
oscilloscope traces and M and S buttons, the lamp bar, the teletype, the
four sheets (change airport, feeds, config, shut down), palettes, glow and
display effects remembered on the server, and a radar screen that fills its
pane with range rings until phase D puts aircraft on it.

**Architecture:** No build step. `index.html`, one stylesheet and ten small
ES modules under `src/kcgx/web/`, served by the existing Starlette app.
The page keeps a store built only from protocol frames and never changes it
itself: a click sends a message and the view redraws when the server's
answer comes back, so every tab shows exactly what the server applied.

| Module | Job |
|---|---|
| `store.js` | the page's copy of the server state, level history per feed |
| `connection.js` | the one WebSocket, reconnect with backoff |
| `theme.js` | palette colours for canvases, read from the CSS variables |
| `stack.js` | the frequency stack and its traces |
| `status.js`, `lamps.js`, `log.js`, `radar.js` | one screen each |
| `sheets.js` | the four dialogs |
| `main.js` | wiring, header buttons, prefs onto `<html>`, the banner |

Server side, phase C adds `kcgx.prefs` (palette, glow, display, remembered
beside the airport), a `prefs` message and frame, static file serving, and
`kcgx.demo` behind `kcgx-web --demo`: synthetic feeds that need no network,
ffmpeg or audio device, which the browser tests and any look at the page
run against.

**Tech Stack:** as phase B, plus Share Tech Mono and B612 Mono (SIL OFL,
Fontsource 5.3.0) and, for the browser tests only, Playwright 1.56.0 with
Chromium in its own dependency group.

**Spec:** `docs/superpowers/specs/2026-10-18-web-cockpit-design.md`, sections
"Visual language", "Themes", "Display effects", "Every action is a click",
"Transport", "Testing". The mockup is the design canvas published during
planning; where spec and mockup disagree, the mockup is the intent.

## Decisions this plan makes that the spec did not

All of these were written into the spec on 2026-10-19, in the same commit
as this plan.

1. **Prefs live on the server**, in `prefs.json` beside the airport file
   (`kcgx.prefs`), so `KCGX_STATE_PATH` moves both and the conftest
   backstop already isolates tests from it. A page sends `{"t": "prefs",
   ...}` with one or more of `palette`, `glow`, `display`; the server checks
   each against its known names exactly, saves, and broadcasts a `prefs`
   frame. The snapshot carries `prefs`. Not browser storage: a second tab
   or a relaunch must agree.
2. **Four palettes, not six:** WOPR, AMBER, MATRIX, MONO. `default`,
   `color` and `ocean` were the same idea as WOPR in a weaker colour.
3. **The lamp bar's system lamps are RADAR, SERVER, AUDIO and EMERG.** The
   mockup's LINK is SERVER, because "link" did not say what it linked.
   Feed lamps are lit in the state colour (cyan live, amber starting or
   reconnecting, red orange offline) and dark when parked, as the spec says.
4. **`/` is the cockpit; phase B's page moves to `/debug`**, kept because it
   shows the raw protocol. `/static/` is served `no-cache` like the pages.
5. **`kcgx-web --demo`** skips the ffmpeg check and runs `kcgx.demo`. It
   remembers nothing: neither airport nor prefs are written.
6. **Fonts are vendored** as Latin-only woff2 from Fontsource 5.3.0, with
   their OFL licences beside them: Share Tech Mono for display text, B612
   Mono (400 and 700) for small dense text.
7. **The local clock is the viewer's own**, with its zone abbreviation: the
   airport dataset has no time zones.
8. **"press f to retry" becomes "open FEEDS to retry"** on its way to the
   page. The station rewrites the line; squelch's own text is unchanged for
   the terminal. The picker fetches the listing afresh on every open, so
   the hint is true.
9. **No banner of key hints anywhere, and no ambient control.** Already
   decided; the browser tests now enforce the first.
10. **Browser tests are behaviour tests, not screenshot comparisons.**
    Screenshot references wait for phase D, when the radar has something
    worth comparing. Playwright is a separate `browser` dependency group so
    a plain `uv sync` stays light; without it `tests/test_page.py` skips.
11. **The radar screen is a placeholder** in phase C: range rings at 10,
    20, 30 and 40 nm with the 40 nm ring fitting the shorter side, the
    airport in pink at the centre, and RECENTRE redrawing it. Phase D
    replaces `radar.js`.

## Global Constraints

- Work in the `feat/web-cockpit` worktree at `/Users/mikelse/kcgx_web`.
- **No new runtime dependency.** The one new dev dependency is Playwright,
  in its own `browser` group.
- **The web modules never import Textual**: `kcgx.prefs` and `kcgx.demo`
  join `WEB_MODULES`.
- **Bind to `127.0.0.1` only**, including the browser tests' subprocess.
- **No test touches the network, ffmpeg or an audio device**, and **no test
  writes to `~/.local/state/kcgx/` or `~/.cache/squelch/`.** Station tests
  inject `remember_prefs`; the server tests' station factory passes a no-op;
  the browser tests' server runs with `KCGX_STATE_PATH` and `HOME` in a
  temporary folder.
- **Every action is a click.** No keyboard shortcuts, no key hints in any
  label, no feed selection. Ordinary Tab, Enter, Space and Escape on real
  buttons and dialogs are accessibility, not shortcuts.
- Run everything through uv from the repo root:
  `cd /Users/mikelse/kcgx_web && uv run --project . pytest -q`. For the
  browser tests, once: `uv sync --group dev --group browser` and
  `uv run playwright install chromium`.
- The suite is **871 tests** at the start and **930** at the end with the
  browser group (914 and one skipped module without it).
- **Existing tests change in four places only:** `test_web_imports.py` gains
  two module names; `test_station.py`'s `make()` gains `prefs` and
  `remembered_prefs` parameters; `test_server.py`'s station factory passes
  `remember_prefs`; and `test_the_debug_page_is_served` asks `/debug`
  instead of `/` (a new test covers `/`). Check with `git diff main -- tests/`.
- **Revert-check every new test**: clean tree, one break, run the named
  test, record the real output, restore, confirm clean.
- The terminal cockpit may be running from `/Users/mikelse/kcgx`; `--demo`
  plays nothing and opens no streams, so it can run alongside.
- Commit after every task. End each message with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `src/kcgx/prefs.py` | palette, glow, display: names, defaults, read, write |
| `src/kcgx/demo.py` | synthetic feeds, sessions and mixer for `--demo` |
| `src/kcgx/web/index.html` | the cockpit page |
| `src/kcgx/web/static/cockpit.css` | palettes, layout, screens, display effects |
| `src/kcgx/web/static/js/*.js` | the ten modules above |
| `src/kcgx/web/static/fonts/` | five files, **already committed with this plan** |
| `tests/test_prefs.py`, `tests/test_demo.py`, `tests/test_page.py` | one per new piece |

**Modify:** `pyproject.toml` and `uv.lock` (Task 1), `tests/test_web_imports.py`
(Tasks 2 and 5), `src/kcgx/protocol.py` and `tests/test_protocol.py` (Task 3),
`src/kcgx/station.py` and `tests/test_station.py` (Task 4),
`src/kcgx/server.py` and `tests/test_server.py` (Task 7), `docs/README.md`
(Task 10).

## The protocol at the end of phase C

Phase B's table, plus:

| Direction | `t` | Carries |
|---|---|---|
| server to page | `snapshot` | gains `prefs`: `{palette, glow, display}` |
| server to page | `prefs` | `palette`, `glow`, `display`, after any page changed one |
| page to server | `prefs` | one or more of `palette` (WOPR, AMBER, MATRIX, MONO), `glow` (OFF, LOW, FULL), `display` (OFF, VECTOR, CRT), exact names |

HTTP gains `GET /debug` and `GET /static/…`, both `no-cache`; `GET /` is now
the cockpit.

---

### Task 1: Dependencies

**Files:** `pyproject.toml`, `uv.lock`.

- [ ] **Step 1:** Apply this to `pyproject.toml` (the `browser` group and a
  `browser` marker):

```diff
diff --git a/pyproject.toml b/pyproject.toml
index 4b07a3f..eed5d6a 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -35,6 +35,12 @@ dev = [
     "pytest>=9.1.1",
     "pytest-asyncio>=1.4.0",
 ]
+# The page's own tests drive a real browser: `uv sync --group browser` and
+# `uv run playwright install chromium`. Without them those tests skip.
+browser = [
+    "playwright==1.56.0",
+]
 
 [tool.pytest.ini_options]
 asyncio_mode = "auto"
+markers = ["browser: drives the cockpit page in a real browser (skips without Playwright)"]
```

- [ ] **Step 2:** `uv lock`, then `uv sync --group dev --group browser` and
  `uv run playwright install chromium`. Playwright 1.56.0 matches Chromium
  141; a newer Playwright wants a newer browser build than some machines
  have, which is why it is pinned exactly.
- [ ] **Step 3:** Suite: **871 passed**. Commit `build: playwright for the page's tests`.

---

### Task 2: `kcgx.prefs`

**Files:** Create `src/kcgx/prefs.py`, `tests/test_prefs.py`; add
`"kcgx.prefs"` to `WEB_MODULES` in `tests/test_web_imports.py`.

- [ ] **Step 1: Tests.** Create `tests/test_prefs.py`:

```python
"""The page's look, remembered on the server (kcgx.prefs)."""

from __future__ import annotations

import json

from kcgx.prefs import DEFAULTS, clean, prefs_path, read_prefs, write_prefs


def test_nothing_remembered_gives_the_defaults(tmp_path):
    assert read_prefs(path=tmp_path / "prefs.json") == DEFAULTS


def test_written_prefs_read_back(tmp_path):
    path = tmp_path / "prefs.json"
    write_prefs({"palette": "AMBER", "glow": "FULL", "display": "VECTOR"}, path=path)
    assert read_prefs(path=path) == {"palette": "AMBER", "glow": "FULL", "display": "VECTOR"}


def test_unknown_values_and_keys_fall_back_to_the_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"palette": "PLAID", "glow": "full", "evil": "<script>"}))
    assert read_prefs(path=path) == {**DEFAULTS, "glow": "FULL"}


def test_a_broken_file_gives_the_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{not json")
    assert read_prefs(path=path) == DEFAULTS
    path.write_text("[1, 2]")
    assert read_prefs(path=path) == DEFAULTS


def test_clean_keeps_only_known_names():
    assert clean({"palette": "mono", "display": 3, "glow": "BRIGHT"}) == {"palette": "MONO"}


def test_failing_to_write_is_not_an_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    write_prefs(DEFAULTS, path=blocker / "prefs.json")  # parent is a file


def test_prefs_live_beside_the_remembered_airport(tmp_path, monkeypatch):
    monkeypatch.setenv("KCGX_STATE_PATH", str(tmp_path / "state" / "airport"))
    assert prefs_path() == tmp_path / "state" / "prefs.json"
```

- [ ] **Step 2:** Run them: they fail with `ModuleNotFoundError: kcgx.prefs`.
- [ ] **Step 3: The module.** Create `src/kcgx/prefs.py`:

```python
"""How the page looks: palette, glow and display effects.

Remembered on the server, beside the airport, so every tab and every launch
agrees. A page changes them with a `prefs` message; the server checks every
value against the names below, so nothing a page sends can end up in the
file unless it is one of them.
"""

from __future__ import annotations

import json
from pathlib import Path

from kcgx.state import default_path

PALETTES = ("WOPR", "AMBER", "MATRIX", "MONO")
GLOWS = ("OFF", "LOW", "FULL")
DISPLAYS = ("OFF", "VECTOR", "CRT")

CHOICES = {"palette": PALETTES, "glow": GLOWS, "display": DISPLAYS}

DEFAULTS = {"palette": "WOPR", "glow": "LOW", "display": "CRT"}


def prefs_path() -> Path:
    """Beside the remembered airport, so KCGX_STATE_PATH relocates both."""
    return default_path().parent / "prefs.json"


def clean(values: dict) -> dict:
    """Only the known keys, each only if it is one of its allowed names."""
    out = {}
    for key, allowed in CHOICES.items():
        value = values.get(key)
        if isinstance(value, str) and value.upper() in allowed:
            out[key] = value.upper()
    return out


def read_prefs(*, path: Path | None = None) -> dict:
    """The remembered prefs over the defaults. Anything unreadable, or any
    value that is not a known name, quietly falls back to its default."""
    path = prefs_path() if path is None else path
    try:
        stored = json.loads(path.read_text())
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return {**DEFAULTS, **clean(stored)}


def write_prefs(prefs: dict, *, path: Path | None = None) -> None:
    """Remember `prefs`. Failing to is a lost convenience, not an error."""
    path = prefs_path() if path is None else path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**DEFAULTS, **clean(prefs)}, indent=2) + "\n")
    except OSError:
        pass
```

- [ ] **Step 4:** `uv run pytest -q tests/test_prefs.py tests/test_web_imports.py`: all pass.
  Suite: **879 passed** (7 here, 1 import guard).
- [ ] **Step 5:** Commit `feat(web): prefs remembered beside the airport`.

---

### Task 3: The `prefs` message and frame

**Files:** `src/kcgx/protocol.py`, `tests/test_protocol.py`.

- [ ] **Step 1: Tests.** Apply:

```diff
diff --git a/tests/test_protocol.py b/tests/test_protocol.py
index 3f3a6ba..c171497 100644
--- a/tests/test_protocol.py
+++ b/tests/test_protocol.py
@@ -7,6 +7,7 @@ import json
 import pytest
 
 from kcgx.airports import find, load_airports
+from kcgx.prefs import DEFAULTS
 from kcgx.protocol import (
     PROTOCOL,
     BadMessage,
@@ -17,6 +18,7 @@ from kcgx.protocol import (
     levels_frame,
     order_frame,
     parse_client,
+    prefs_frame,
     snapshot,
 )
 from squelch.feeds import Feed
@@ -90,6 +92,22 @@ def test_a_snapshot_has_the_feeds_in_stack_order_and_the_protocol_version():
     assert [f["ident"] for f in frame["feeds"]] == ["kpdx3_twr", "kpdx3_gnd"]
     assert frame["volume"] == 0.8
     assert frame["log"] == [{"z": "1955Z", "text": "hello"}]
+    assert frame["prefs"] == DEFAULTS
+
+
+def test_a_snapshot_carries_the_prefs_it_is_given():
+    prefs = {"palette": "MONO", "glow": "OFF", "display": "VECTOR"}
+    frame = snapshot(
+        airport=None, icao="KPDX", loading=False, sessions=[], volume=1,
+        max_streams=7, audio_ok=True, log=[], prefs=prefs,
+    )
+    assert frame["prefs"] == prefs
+
+
+def test_a_prefs_frame_is_flat():
+    assert prefs_frame({"palette": "AMBER", "glow": "LOW", "display": "CRT"}) == {
+        "t": "prefs", "palette": "AMBER", "glow": "LOW", "display": "CRT",
+    }
 
 
 def test_levels_are_keyed_by_ident_and_rounded():
@@ -132,9 +150,22 @@ def test_volume_is_clamped_to_the_unit_range(value, expected):
     }
 
 
+def test_prefs_parse_one_or_more_known_names():
+    assert parse_client('{"t":"prefs","palette":"MATRIX"}') == {"t": "prefs", "palette": "MATRIX"}
+    assert parse_client('{"t":"prefs","glow":"OFF","display":"CRT"}') == {
+        "t": "prefs", "glow": "OFF", "display": "CRT",
+    }
+
+
 @pytest.mark.parametrize(
     "text",
     [
+        '{"t": "prefs"}',
+        '{"t": "prefs", "palette": "PLAID"}',
+        '{"t": "prefs", "palette": "amber"}',
+        '{"t": "prefs", "glow": 1}',
+        '{"t": "prefs", "display": "CRT", "palette": null}',
+        '{"t": "prefs", "theme": "WOPR"}',
         "not json",
         "[1, 2]",
         '{"t": "explode"}',
```

- [ ] **Step 2:** They fail: `ImportError: cannot import name 'prefs_frame'`.
- [ ] **Step 3: The protocol.** Apply:

```diff
diff --git a/src/kcgx/protocol.py b/src/kcgx/protocol.py
index d74ecde..3f5166e 100644
--- a/src/kcgx/protocol.py
+++ b/src/kcgx/protocol.py
@@ -19,6 +19,8 @@ import re
 from collections.abc import Iterable
 from typing import Any
 
+from kcgx.prefs import CHOICES, DEFAULTS
+
 PROTOCOL = 1
 
 # LiveATC idents as parse_airport_page leaves them: lower case, digits and
@@ -75,6 +77,7 @@ def snapshot(
     max_streams: int,
     audio_ok: bool,
     log: Iterable[dict],
+    prefs: dict | None = None,
 ) -> dict:
     """Everything a page needs to draw from nothing: sent on connect and
     after every airport change."""
@@ -88,6 +91,7 @@ def snapshot(
         "max_streams": int(max_streams),
         "audio_ok": bool(audio_ok),
         "log": list(log),
+        "prefs": dict(prefs or DEFAULTS),
     }
 
 
@@ -115,6 +119,10 @@ def volume_frame(value: float) -> dict:
     return {"t": "volume", "value": round(float(value), 2)}
 
 
+def prefs_frame(prefs: dict) -> dict:
+    return {"t": "prefs", **prefs}
+
+
 def message_frame(entry: dict) -> dict:
     return {"t": "message", **entry}
 
@@ -158,9 +166,27 @@ def parse_client(text: str) -> dict:
         return {"t": "volume", "value": min(1.0, max(0.0, float(value)))}
     if kind == "input":
         return {"t": "input"}
+    if kind == "prefs":
+        return {"t": "prefs", **_prefs(data)}
     raise BadMessage(f"unknown message type: {kind!r}")
 
 
+def _prefs(data: dict) -> dict:
+    """At least one of palette, glow, display, each one of its known names.
+    Names are exact: the page sends what the server sent it."""
+    changes = {}
+    for key, allowed in CHOICES.items():
+        if key not in data:
+            continue
+        value = data[key]
+        if not isinstance(value, str) or value not in allowed:
+            raise BadMessage(f"{key} must be one of {', '.join(allowed)}")
+        changes[key] = value
+    if not changes:
+        raise BadMessage("prefs needs palette, glow or display")
+    return changes
+
+
 def _ident(data: dict) -> str:
     value = data.get("ident")
     if not isinstance(value, str) or not IDENT_RE.fullmatch(value):
```

- [ ] **Step 4:** `uv run pytest -q tests/test_protocol.py`: 42 passed.
  Suite: **888 passed**.
- [ ] **Step 5:** Commit `feat(web): prefs in the protocol`.

---

### Task 4: The station keeps prefs, and the page's retry hint

**Files:** `src/kcgx/station.py`, `tests/test_station.py`.

- [ ] **Step 1: Tests.** Apply (the `make()` change is additive: both new
  parameters default to what every existing test had):

```diff
diff --git a/tests/test_station.py b/tests/test_station.py
index 22a9dd3..859a2b0 100644
--- a/tests/test_station.py
+++ b/tests/test_station.py
@@ -19,11 +19,12 @@ from squelch.mixer import Mixer
 from squelch.runtime import AUDIO_FAILED
 from station_fakes import AIRPORTS, LISTINGS, Builder, listing, picker
 
-def make(loader=listing, *, mixer=None):
+def make(loader=listing, *, mixer=None, prefs=None, remembered_prefs=None):
     loop = asyncio.get_running_loop()
     hub = Hub()
     builder = Builder()
     remembered = []
+    remembered_prefs = [] if remembered_prefs is None else remembered_prefs
     station = Station(
         Config(icao="KPDX", feed="kpdx3_twr"),
         hub,
@@ -34,6 +35,8 @@ def make(loader=listing, *, mixer=None):
         sessions_builder=builder,
         picker_loader=picker,
         remember=remembered.append,
+        prefs=prefs,
+        remember_prefs=lambda p: remembered_prefs.append(dict(p)),
     )
     return station, hub, builder, remembered
 
@@ -105,6 +108,16 @@ async def test_listing_warnings_reach_the_log_after_the_feeds():
     assert "cached list" in hub.log[-1]["text"]
 
 
+async def test_a_retry_hint_names_the_pages_button_not_a_key():
+    def refused(config, *, warn):
+        warn("KPDX — LiveATC refused the feed list; press f to retry")
+        return []
+
+    station, hub, _, _ = make(refused)
+    await station.open("KPDX")
+    assert hub.log[-1]["text"].endswith("refused the feed list; open FEEDS to retry")
+
+
 async def test_a_listing_that_raises_leaves_an_empty_stack_and_says_so():
     def broken(config, *, warn):
         raise OSError("network down")
@@ -311,3 +324,27 @@ async def test_stop_stops_every_feed_and_releases_the_mixer_channels():
     station.stop()
     assert all(s.stopped for s in sessions)
     assert mixer._channels == []
+
+
+# -- how the page looks ------------------------------------------------------
+
+
+async def test_the_snapshot_carries_the_prefs_the_station_was_given():
+    station, *_ = make(prefs={"palette": "AMBER", "glow": "FULL", "display": "OFF"})
+    assert station.snapshot()["prefs"] == {"palette": "AMBER", "glow": "FULL", "display": "OFF"}
+
+
+async def test_without_prefs_the_station_uses_the_defaults():
+    station, *_ = make()
+    assert station.snapshot()["prefs"] == {"palette": "WOPR", "glow": "LOW", "display": "CRT"}
+
+
+async def test_a_prefs_change_is_remembered_and_reaches_every_page():
+    saved = []
+    station, hub, *_ = make(remembered_prefs=saved)
+    page = watch(hub)
+    station.handle({"t": "prefs", "palette": "MATRIX"})
+    assert saved == [{"palette": "MATRIX", "glow": "LOW", "display": "CRT"}]
+    assert frames(page, "prefs") == [{"t": "prefs", "palette": "MATRIX", "glow": "LOW", "display": "CRT"}]
+    station.handle({"t": "prefs", "glow": "OFF"})
+    assert station.prefs == {"palette": "MATRIX", "glow": "OFF", "display": "CRT"}
```

- [ ] **Step 2:** They fail: `TypeError: Station.__init__() got an unexpected keyword argument 'prefs'`.
- [ ] **Step 3: The station.** Apply:

```diff
diff --git a/src/kcgx/station.py b/src/kcgx/station.py
index 54810f0..562e7e2 100644
--- a/src/kcgx/station.py
+++ b/src/kcgx/station.py
@@ -22,6 +22,7 @@ from typing import Any
 from kcgx import protocol
 from kcgx.airports import Airport, find
 from kcgx.hub import Hub
+from kcgx.prefs import DEFAULTS, write_prefs
 from kcgx.state import write_airport
 from squelch.cockpit import ADDED, FEED, MESSAGE, ORDER, Cockpit
 from squelch.config import Config
@@ -49,6 +50,8 @@ class Station:
         sessions_builder: Callable[..., list] = build_sessions,
         picker_loader: Callable[..., list[Feed]] = picker_feeds,
         remember: Callable[[str], None] = write_airport,
+        prefs: dict | None = None,
+        remember_prefs: Callable[[dict], None] = write_prefs,
     ) -> None:
         self.config = config
         self.hub = hub
@@ -59,6 +62,8 @@ class Station:
         self._sessions_builder = sessions_builder
         self._picker_loader = picker_loader
         self._remember = remember
+        self._remember_prefs = remember_prefs
+        self.prefs = dict(prefs or DEFAULTS)
         self._events = SessionEvents(
             on_state=lambda session, state: self._post(self._session_changed, session),
             on_warn=lambda session, message: self._post(
@@ -123,7 +128,7 @@ class Station:
         self.loading = False
         self.hub.broadcast(self.snapshot())
         for message in warnings:
-            self.hub.note(message)
+            self.hub.note(_for_the_page(message))
         self.cockpit.start()
 
     async def available_feeds(self) -> list[dict]:
@@ -165,11 +170,20 @@ class Station:
             self.open_feed(message["ident"])
         elif kind == "input":
             cockpit.note_input()
+        elif kind == "prefs":
+            self.set_prefs({k: v for k, v in message.items() if k != "t"})
 
     def set_volume(self, value: float) -> None:
         self.mixer.volume = float(value)
         self.hub.broadcast(protocol.volume_frame(self.mixer.volume))
 
+    def set_prefs(self, changes: dict) -> None:
+        """Palette, glow or display, already validated by the protocol.
+        Remembered, and sent to every page so all tabs look the same."""
+        self.prefs = {**self.prefs, **changes}
+        self._remember_prefs(self.prefs)
+        self.hub.broadcast(protocol.prefs_frame(self.prefs))
+
     def open_feed(self, ident: str) -> None:
         if self.cockpit.session(ident) is not None:
             return  # already open: the page selects it
@@ -202,6 +216,7 @@ class Station:
             max_streams=self.cockpit.max_streams,
             audio_ok=not getattr(self.mixer, "failed", False),
             log=self.hub.log,
+            prefs=self.prefs,
         )
 
     # -- shutting down -----------------------------------------------------
@@ -255,3 +270,9 @@ class Station:
     async def _in_thread(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
         loop = asyncio.get_running_loop()
         return await loop.run_in_executor(None, functools.partial(fn, *args, **kwargs))
+
+
+def _for_the_page(message: str) -> str:
+    """squelch's listing warnings name the terminal's key; the page's retry
+    is the FEEDS button, whose list is fetched afresh on every open."""
+    return message.replace("press f to retry", "open FEEDS to retry")
```

- [ ] **Step 4:** `uv run pytest -q tests/test_station.py`: 26 passed.
  Suite: **892 passed**.
- [ ] **Step 5:** Commit `feat(web): the station keeps prefs; retry hint names FEEDS`.

---

### Task 5: Demo feeds

**Files:** Create `src/kcgx/demo.py`, `tests/test_demo.py`; add
`"kcgx.demo"` to `WEB_MODULES`.

- [ ] **Step 1: Tests.** Create `tests/test_demo.py`:

```python
"""The demo feeds behind kcgx-web --demo (kcgx.demo)."""

from __future__ import annotations

from kcgx import demo
from squelch.config import Config


class Events:
    def __init__(self):
        self.states = []

    def on_state(self, session, state):
        self.states.append((session.feed.ident, state))


def sessions(icao="KPDX", feed="kpdx_twr", clock=None):
    config = Config(icao=icao, feed=feed)
    feeds = demo.listing(config, warn=lambda line: None)
    built = demo.build(feeds, config, Events())
    if clock is not None:
        for session in built:
            session._clock = clock
    return built


def test_the_listing_is_named_for_the_airport():
    feeds = demo.listing(Config(icao="KSEA"), warn=lambda line: None)
    assert feeds[0].ident == "ksea_twr"
    assert feeds[0].label == "KSEA Tower"
    assert len(feeds) == len(demo.POSITIONS)


def test_the_picker_offers_more_than_the_listing():
    config = Config(icao="KPDX")
    listed = {f.ident for f in demo.listing(config, warn=lambda line: None)}
    offered = {f.ident for f in demo.picker(config)}
    assert listed < offered


def test_only_the_configured_feed_is_audible():
    built = sessions(feed="kpdx_app")
    assert [s.feed.ident for s in built if not s.muted] == ["kpdx_app"]


def test_the_first_feed_is_audible_when_the_configured_one_is_elsewhere():
    built = sessions(feed="ksea_twr")
    assert [s.muted for s in built][:2] == [False, True]


def test_names_drop_the_airport():
    assert sessions()[0].name == "Tower"


def test_a_feed_is_silent_until_it_is_live():
    session = sessions(clock=lambda: 10.0)[0]
    assert session.level == demo.SILENT_DBFS
    session.start()
    assert session.state == "live"
    assert -70 < session.level < -9


def test_levels_are_the_same_for_the_same_moment():
    a = sessions(clock=lambda: 123.4)[0]
    b = sessions(clock=lambda: 123.4)[0]
    a.start()
    b.start()
    assert a.level == b.level


def test_a_busy_feed_talks_more_than_a_quiet_one():
    def talking(ident):
        session = next(s for s in sessions() if s.feed.ident == ident)
        session.start()
        count = 0
        for slot in range(400):
            session._clock = lambda t=slot * demo.SLOT_SECONDS: t
            count += session.level > -40
        return count

    assert talking("kpdx_atis") > talking("kpdx_twr") > talking("kpdx_gnd_ramp")


def test_center_reconnects_before_it_goes_live():
    session = next(s for s in sessions() if s.feed.ident == "kpdx_ctr")
    session.start()
    assert session.state == "reconnecting"
    session._timer.cancel()
    session._set("live")
    assert session.state == "live"


def test_parking_cancels_a_pending_reconnect():
    session = next(s for s in sessions() if s.feed.ident == "kpdx_ctr")
    session.start()
    timer = session._timer
    session.park()
    assert session.state == "parked"
    assert session._timer is None and timer.finished.is_set()
    session._set("live")  # a late timer firing changes nothing
    assert session.state == "parked"


def test_the_demo_mixer_needs_no_device():
    mixer = demo.DemoMixer(volume=0.5)
    mixer.start()
    mixer.clear_channels()
    mixer.stop()
    assert mixer.volume == 0.5 and not mixer.failed
```

- [ ] **Step 2:** They fail with `ImportError: cannot import name 'demo' from 'kcgx'`.
- [ ] **Step 3: The module.** Create `src/kcgx/demo.py`:

```python
"""A station with nothing real behind it: synthetic feeds for any airport.

`kcgx-web --demo` runs on this. No LiveATC, no ffmpeg, no audio device, no
writes to the state directory: the page can be built, tested and looked at
without spending any of LiveATC's seven streams or hearing anything. The
browser tests run against it too.

Every feed meters, chatters and changes state the way a real one does, so
the page cannot tell the difference except that nothing plays.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections.abc import Callable

from squelch.config import Config
from squelch.feeds import Feed

# (suffix, label, how busy: the fraction of 1.5 s slots with someone talking)
POSITIONS = [
    ("twr", "Tower", 0.38),
    ("app", "Approach", 0.30),
    ("atis", "ATIS", 0.95),
    ("gnd", "Ground", 0.22),
    ("del", "Clearance Delivery", 0.08),
    ("dep", "Departure", 0.18),
    ("twr_n", "Tower (North)", 0.12),
    ("ctr", "Center", 0.10),
    ("gnd_ramp", "Ground (Ramp)", 0.04),
]

# In the picker but not opened at start, so opening a feed can be tried.
EXTRA = [
    ("app_final", "Approach (Final)", 0.20),
    ("guard", "Emergency Guard 121.5", 0.01),
]

SLOT_SECONDS = 1.5
SILENT_DBFS = -96.0


def _feeds(icao: str, positions) -> list[Feed]:
    return [Feed(f"{icao.lower()}_{suffix}", f"{icao.upper()} {label}") for suffix, label, _ in positions]


def listing(config: Config, *, warn: Callable[[str], None]) -> list[Feed]:
    """Stands in for squelch.runtime.load_feeds."""
    return _feeds(config.icao, POSITIONS)


def picker(config: Config) -> list[Feed]:
    """Stands in for squelch.runtime.picker_feeds."""
    return _feeds(config.icao, POSITIONS + EXTRA)


def _busy_for(ident: str) -> float:
    for suffix, _, busy in POSITIONS + EXTRA:
        if ident.endswith("_" + suffix):
            return busy
    return 0.1


class DemoSession:
    """Behaves like squelch.session.FeedSession, minus the network."""

    def __init__(self, feed: Feed, events, *, muted: bool, icao: str, clock=time.monotonic):
        self.feed = feed
        prefix = f"{icao.upper()} "
        self.name = feed.label[len(prefix):] if feed.label.upper().startswith(prefix) else feed.label
        self.events = events
        self.muted = muted
        self.state = "starting"
        self.ambient = False
        self.soloed = False
        self.connected = False
        self._busy = _busy_for(feed.ident)
        self._seed = sum(map(ord, feed.ident))
        self._clock = clock
        self._timer: threading.Timer | None = None

    # -- what the station reads ------------------------------------------------

    @property
    def level(self) -> float:
        if not self.connected or self.state != "live":
            return SILENT_DBFS
        now = self._clock()
        slot = int(now / SLOT_SECONDS)
        talking = random.Random(self._seed * 100_003 + slot).random() < self._busy
        jitter = random.Random(self._seed * 7 + int(now * 25)).random()
        if talking:
            return -24.0 + 14.0 * jitter
        return -66.0 + 8.0 * jitter

    @property
    def activity(self) -> float:
        if self._busy <= 0:
            return 0.0
        drift = 0.85 + 0.15 * math.sin(self._clock() / 45.0 + self._seed)
        return max(0.0, min(1.0, self._busy * drift))

    # -- what the cockpit drives -----------------------------------------------

    def start(self) -> None:
        if self.connected:
            return
        self.connected = True
        # The Center feed reconnects once on its way up, so the page's amber
        # state is visible in the demo; the event arrives from another thread,
        # as a real feed's does.
        if self.feed.ident.endswith("_ctr"):
            self._set("reconnecting")
            self._timer = threading.Timer(3.0, self._set, args=("live",))
            self._timer.daemon = True
            self._timer.start()
        else:
            self._set("live")

    def park(self) -> None:
        self._cancel()
        self.connected = False
        self._set("parked")

    def stop(self) -> None:
        self._cancel()
        self.connected = False

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self) -> bool:
        self.ambient = not self.ambient
        return self.ambient

    def _set(self, state: str) -> None:
        if state == "live" and not self.connected:
            return
        self.state = state
        self.events.on_state(self, state)

    def _cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def build(feeds, config: Config, events, *, mixer=None) -> list[DemoSession]:
    """Stands in for squelch.runtime.build_sessions: everything muted but the
    configured feed, or the first feed when that is not here."""
    sessions = [
        DemoSession(feed, events, muted=feed.ident != config.feed, icao=config.icao)
        for feed in feeds
    ]
    if sessions and all(s.muted for s in sessions):
        sessions[0].muted = False
    return sessions


class DemoMixer:
    """The parts of squelch.mixer.Mixer the station touches. Plays nothing."""

    failed = False

    def __init__(self, *, volume: float = 1.0, **_ignored) -> None:
        self.volume = volume

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def clear_channels(self) -> None:
        pass
```

- [ ] **Step 4:** `uv run pytest -q tests/test_demo.py tests/test_web_imports.py`: all pass.
  Suite: **904 passed**.
- [ ] **Step 5:** Commit `feat(web): demo feeds`.

---

### Task 6: The page

**Files:** Create `src/kcgx/web/index.html`, `src/kcgx/web/static/cockpit.css`
and the ten modules in `src/kcgx/web/static/js/`. No tests in this task:
Task 7 checks every module is served and imports nothing missing, and Task 8
drives the page.

- [ ] **Step 1: Fonts.** They are already in `src/kcgx/web/static/fonts/`,
  committed with this plan, because neither the sandbox nor the Mac's VM
  could reach a font CDN. Check them:

```
shasum -a 256 src/kcgx/web/static/fonts/*
```

```
59f9dc1656343e445fdd11b8ea147b7b22c47d3af3cfec0406401a9f17468334  OFL-B612Mono.txt
9909bc951ab73dcf212a1675aab327ffafa853c2b8e8d11a066b1bcc57afeefb  OFL-ShareTechMono.txt
36316fb226f98c51db117b8ba357316013a610a1d0f7607d2af73ea3f9194848  b612-mono-latin-400-normal.woff2
4994d0b2f403b6805d8b918c01b0d5122808373373795f8149ccc231ebd197f3  b612-mono-latin-700-normal.woff2
41e6b9f297f7d9a2df2aaa274092f76d2f72711a15ca455f7f4f4f92caf16b72  share-tech-mono-latin-400-normal.woff2
```

  They are the `files/*-latin-*-normal.woff2` and `LICENSE` of
  `npm pack @fontsource/share-tech-mono@5.3.0` and
  `npm pack @fontsource/b612-mono@5.3.0`, renamed `OFL-*.txt`.

- [ ] **Step 2: The page.** Create `src/kcgx/web/index.html`:

```html
<!doctype html>
<html lang="en" data-palette="WOPR" data-glow="LOW" data-display="CRT">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KCGX</title>
<link rel="stylesheet" href="/static/cockpit.css">
<script type="module" src="/static/js/main.js"></script>
</head>
<body>
<div class="page">

  <header class="bar">
    <div class="brand">
      <span class="brand-name">KCGX</span>
      <span class="brand-sub" id="where-served">LOCAL COCKPIT</span>
    </div>
    <nav class="bar-buttons" aria-label="Cockpit controls">
      <button type="button" class="btn" id="open-feeds">FEEDS</button>
      <button type="button" class="btn" id="open-config">CONFIG</button>
      <button type="button" class="btn" id="next-palette" aria-label="Next palette">PALETTE <span id="palette-name">WOPR</span></button>
      <button type="button" class="btn btn-alarm" id="open-shutdown">SHUT DOWN</button>
    </nav>
  </header>

  <div class="banner" id="banner" role="status" hidden></div>

  <div class="toprow">
    <section class="screen screen-radar" aria-label="Radar">
      <div class="ovl" aria-hidden="true"></div>
      <div class="radar-wrap">
        <canvas id="radar" class="radar jit" role="img" aria-label="Radar: range rings around the airport; aircraft arrive in phase D"></canvas>
        <div class="hud hud-left" aria-hidden="true"><span>RNG 40 NM</span><span id="radar-poll">RADAR NOT YET RUNNING</span></div>
        <div class="hud hud-right" aria-hidden="true"><span id="radar-tracks">0 TRACKS</span></div>
      </div>
      <div class="screen-title">
        <span class="title-text">TRAFFIC</span>
        <div class="title-tools">
          <span class="muted small" id="radar-position"></span>
          <button type="button" class="btn btn-small" id="recentre">RECENTRE</button>
        </div>
      </div>
    </section>

    <div class="column">
      <section class="screen screen-status" aria-label="Status">
        <div class="ovl" aria-hidden="true"></div>
        <div class="status-body">
          <div class="status-top">
            <div class="status-airport">
              <span class="icao" id="icao">····</span>
              <span class="airport-name" id="airport-name"></span>
              <span class="muted small" id="airport-where"></span>
            </div>
            <div class="clocks">
              <span class="zulu" id="zulu">0000Z</span>
              <span class="local" id="local">00:00</span>
            </div>
          </div>
          <button type="button" class="btn btn-pink" id="open-airport">CHANGE AIRPORT</button>
        </div>
        <div class="screen-title"><span class="title-text">STATUS</span></div>
      </section>

      <section class="screen screen-freq" aria-label="Frequencies">
        <div class="ovl" aria-hidden="true"></div>
        <div class="freq-counts muted small" id="freq-counts"></div>
        <div class="stack" id="stack"></div>
        <div class="screen-title"><span class="title-text">FREQUENCIES</span></div>
      </section>
    </div>
  </div>

  <div class="lamps" id="lamps" role="group" aria-label="Status lamps"></div>

  <div class="bottomrow">
    <section class="screen screen-tracks" aria-label="Tracks">
      <div class="ovl" aria-hidden="true"></div>
      <div class="tracks-body">
        <table class="tracks">
          <thead>
            <tr><th>CALLSIGN</th><th>TYPE</th><th class="num">ALT FT</th><th class="num">GS KT</th><th class="num">TRK</th><th class="num">DIST NM</th><th class="num">SQWK</th></tr>
          </thead>
          <tbody id="tracks-body"></tbody>
        </table>
        <p class="muted small empty" id="tracks-empty">NO TRACKS. THE RADAR ARRIVES IN PHASE D.</p>
      </div>
      <div class="screen-title"><span class="title-text">TRACKS</span></div>
    </section>

    <section class="screen screen-log" aria-label="Teletype">
      <div class="ovl" aria-hidden="true"></div>
      <div class="log" id="log" role="log" aria-live="polite"></div>
      <div class="screen-title"><span class="title-text">TELETYPE</span></div>
    </section>
  </div>
</div>

<dialog class="sheet" id="airport-sheet" aria-labelledby="airport-title">
  <form method="dialog" class="sheet-head">
    <h2 id="airport-title">CHANGE AIRPORT</h2>
    <button class="btn btn-small" value="close" aria-label="Close">CLOSE</button>
  </form>
  <label class="field"><span class="muted small">SEARCH CODE, NAME OR CITY</span>
    <input id="airport-query" type="search" autocomplete="off" spellcheck="false">
  </label>
  <div class="choices" id="airport-results"></div>
</dialog>

<dialog class="sheet" id="feeds-sheet" aria-labelledby="feeds-title">
  <form method="dialog" class="sheet-head">
    <h2 id="feeds-title">FEEDS</h2>
    <button class="btn btn-small" value="close" aria-label="Close">CLOSE</button>
  </form>
  <label class="field"><span class="muted small">FILTER</span>
    <input id="feeds-query" type="search" autocomplete="off" spellcheck="false">
  </label>
  <p class="muted small" id="feeds-status"></p>
  <div class="choices" id="feeds-results"></div>
</dialog>

<dialog class="sheet" id="config-sheet" aria-labelledby="config-title">
  <form method="dialog" class="sheet-head">
    <h2 id="config-title">CONFIG</h2>
    <button class="btn btn-small" value="close" aria-label="Close">CLOSE</button>
  </form>
  <h3 class="muted small">OUTPUT</h3>
  <label class="field field-row"><span>MASTER VOLUME</span>
    <input id="volume" type="range" min="0" max="100" step="5">
    <span class="num" id="volume-value">100%</span>
  </label>
  <h3 class="muted small">LOOK</h3>
  <div class="field-row" role="group" aria-label="Palette"><span>PALETTE</span><div class="segments" data-pref="palette"></div></div>
  <div class="field-row" role="group" aria-label="Glow"><span>GLOW</span><div class="segments" data-pref="glow"></div></div>
  <div class="field-row" role="group" aria-label="Display"><span>DISPLAY</span><div class="segments" data-pref="display"></div></div>
  <h3 class="muted small">LIMITS</h3>
  <div class="field-row"><span>STREAMS AT ONCE</span><span class="num" id="max-streams">7</span><span class="muted small">LIVEATC'S LIMIT; FIXED</span></div>
</dialog>

<dialog class="sheet sheet-small" id="shutdown-sheet" aria-labelledby="shutdown-title">
  <h2 id="shutdown-title">SHUT DOWN THE COCKPIT?</h2>
  <p class="muted small">EVERY FEED STOPS AND THE SERVER EXITS. RUN KCGX AGAIN TO START IT.</p>
  <form method="dialog" class="sheet-actions">
    <button class="btn" value="cancel">CANCEL</button>
    <button class="btn btn-alarm" value="confirm" id="confirm-shutdown">SHUT DOWN</button>
  </form>
</dialog>

<div class="ended" id="ended" hidden><span>COCKPIT SHUT DOWN</span></div>
</body>
</html>
```

- [ ] **Step 3: The stylesheet.** Create `src/kcgx/web/static/cockpit.css`:

```css
/* KCGX cockpit. The look is the NORAD wall in WarGames: line art on black,
   framed screens with their names along the bottom, lamps between them.
   Everything visual hangs off three attributes on <html>, set from the
   server's prefs: data-palette, data-glow, data-display. */

@font-face { font-family: "Share Tech Mono"; src: url("fonts/share-tech-mono-latin-400-normal.woff2") format("woff2"); font-weight: 400; font-display: swap; }
@font-face { font-family: "B612 Mono"; src: url("fonts/b612-mono-latin-400-normal.woff2") format("woff2"); font-weight: 400; font-display: swap; }
@font-face { font-family: "B612 Mono"; src: url("fonts/b612-mono-latin-700-normal.woff2") format("woff2"); font-weight: 700; font-display: swap; }

/* -- palettes: one meaning per colour (spec, Visual language) ------------ */

:root, [data-palette="WOPR"] {
  --wall: #06080b; --frame: #7f93a6; --cyan: #40d4ff; --dim: #2f86ab; --blue: #4a74ff;
  --green: #6cff4a; --alarm: #ff5a36; --pink: #ff8fdc; --white: #f4f6ff; --amber: #ffb648;
  --text: #c4f0ff; --muted: #7fa9be; --rule: #1a2229;
}
[data-palette="AMBER"] {
  --wall: #080603; --frame: #8a6a30; --cyan: #ffb000; --dim: #a87400; --blue: #b37700;
  --green: #d99a1a; --alarm: #ffffff; --pink: #ffd98a; --white: #fff1d0; --amber: #ffc94d;
  --text: #ffd58a; --muted: #b88f48; --rule: #221a0c;
}
[data-palette="MATRIX"] {
  --wall: #030703; --frame: #2f7a45; --cyan: #38ff6e; --dim: #22a04c; --blue: #22a04c;
  --green: #9bffb0; --alarm: #ffffff; --pink: #d4ffdc; --white: #effff2; --amber: #a6ff5a;
  --text: #b8ffc8; --muted: #64b07a; --rule: #0d2214;
}
[data-palette="MONO"] {
  --wall: #060606; --frame: #8a8a8a; --cyan: #e8e8e8; --dim: #8c8c8c; --blue: #9a9a9a;
  --green: #bdbdbd; --alarm: #ff5a36; --pink: #ffffff; --white: #ffffff; --amber: #cfcfcf;
  --text: #e8e8e8; --muted: #a0a0a0; --rule: #1e1e1e;
}

/* -- glow ------------------------------------------------------------------ */

:root { --glow: 0 0 7px currentColor; --frame-glow: 0 0 14px color-mix(in srgb, var(--frame) 27%, transparent); }
[data-glow="OFF"] { --glow: none; --frame-glow: none; }
[data-glow="FULL"] { --glow: 0 0 4px currentColor, 0 0 16px currentColor; }

/* -- page ------------------------------------------------------------------ */

* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body { background: var(--wall); color: var(--text); font: 13px/1.4 "B612 Mono", ui-monospace, Menlo, monospace; letter-spacing: 0.06em; }
button, input { font: inherit; letter-spacing: inherit; color: inherit; }
.muted { color: var(--muted); }
.small { font-size: 12px; letter-spacing: 0.14em; }
.num { font-variant-numeric: tabular-nums; }
[hidden] { display: none !important; }

/* Header, banner, top row, lamps, bottom row. The top row takes what the
   window has left; screens are grid cells, so they can never overlap. Each
   part has a named area, so the hidden banner leaves its row empty rather
   than shifting the others up; spacing is margins, so an empty row costs
   nothing. */
.page {
  height: 100vh; min-height: 720px; padding: 16px 20px 20px;
  display: grid; grid-template-rows: auto auto minmax(380px, 1fr) auto minmax(180px, 24vh);
  grid-template-areas: "bar" "banner" "top" "lamps" "bottom";
}
.bar { grid-area: bar; }
.banner { grid-area: banner; margin-top: 14px; }
.toprow { grid-area: top; margin-top: 14px; }
.lamps { grid-area: lamps; margin-top: 14px; }
.bottomrow { grid-area: bottom; margin-top: 14px; }
.toprow { display: grid; grid-template-columns: minmax(0, 1fr) minmax(340px, 400px); gap: 14px; min-height: 0; }
.column { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 14px; min-height: 0; min-width: 0; }
.bottomrow { display: grid; grid-template-columns: minmax(0, 1fr) minmax(340px, 400px); gap: 14px; min-height: 0; }
.toprow > *, .bottomrow > * { min-width: 0; min-height: 0; }

@media (max-width: 1100px) {
  .page { height: auto; grid-template-rows: auto auto auto auto auto; }
  .toprow, .bottomrow { grid-template-columns: minmax(0, 1fr); }
  .radar-wrap { flex: 0 0 auto; height: 440px; }
  .stack { max-height: 70vh; }
  .log { max-height: 40vh; }
}

/* -- header ---------------------------------------------------------------- */

.bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
.brand { display: flex; align-items: baseline; gap: 18px; }
.brand-name { font: 22px "Share Tech Mono", monospace; letter-spacing: 0.32em; color: var(--white); text-shadow: var(--glow); }
.brand-sub { font-size: 12px; letter-spacing: 0.18em; color: var(--muted); }
.bar-buttons { display: flex; flex-wrap: wrap; gap: 8px; }

.btn {
  min-height: 40px; padding: 0 14px; background: transparent; cursor: pointer;
  border: 1px solid var(--frame); color: var(--text); font-size: 13px; letter-spacing: 0.12em;
}
.btn:hover { border-color: var(--cyan); color: var(--white); }
.btn:focus-visible, .feed:focus-visible, .choice:focus-visible { outline: 2px solid var(--pink); outline-offset: 2px; }
.btn-small { min-height: 32px; padding: 0 10px; font-size: 12px; }
.btn-alarm { border-color: var(--alarm); color: var(--alarm); }
.btn-pink { border-color: var(--pink); color: var(--pink); }
.btn[aria-pressed="true"] { border-color: var(--pink); color: var(--pink); }

.banner { padding: 8px 14px; border: 1px solid var(--amber); color: var(--amber); font-size: 12px; letter-spacing: 0.16em; text-align: center; }
.banner.bad { border-color: var(--alarm); color: var(--alarm); }

/* -- screens ------------------------------------------------------------------ */

.screen {
  position: relative; overflow: hidden; contain: paint;
  display: flex; flex-direction: column; min-height: 0;
  background: #000; border: 1px solid var(--frame); box-shadow: var(--frame-glow);
}
.screen-title {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 8px 16px; border-top: 1px solid var(--frame); flex: 0 0 auto;
}
.title-text { font: 20px "Share Tech Mono", monospace; letter-spacing: 0.18em; color: var(--white); text-shadow: var(--glow); }
.title-tools { display: flex; align-items: center; gap: 14px; }

/* radar */
.screen-radar { min-height: 0; }
.radar-wrap { position: relative; flex: 1 1 auto; min-height: 0; overflow: hidden; contain: paint; }
.radar { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.hud { position: absolute; top: 14px; display: flex; flex-direction: column; gap: 4px; pointer-events: none;
  font: 13px "Share Tech Mono", monospace; letter-spacing: 0.14em; color: var(--muted); white-space: pre; }
.hud-left { left: 18px; }
.hud-right { right: 18px; align-items: flex-end; }

/* status */
.status-body { padding: 16px 18px 14px; display: flex; flex-direction: column; gap: 10px; }
.status-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.status-airport { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.icao { font: 64px/1 "Share Tech Mono", monospace; letter-spacing: 0.12em; color: var(--white); text-shadow: var(--glow); }
.airport-name { font-size: 13px; letter-spacing: 0.14em; text-transform: uppercase; }
.clocks { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex: 0 0 auto; }
.zulu { font: 40px/1 "Share Tech Mono", monospace; letter-spacing: 0.08em; color: var(--cyan); text-shadow: var(--glow); }
.local { font: 20px "Share Tech Mono", monospace; letter-spacing: 0.1em; color: var(--muted); }
#open-airport { align-self: flex-start; }

/* frequencies */
.freq-counts { display: flex; justify-content: space-between; gap: 8px; padding: 12px 16px 6px; }
.stack { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding: 6px 12px 12px; }
.stack-empty { margin: auto; text-align: center; color: var(--muted); letter-spacing: 0.16em; }

.feed { width: 100%; text-align: left; background: transparent; }
.feed.expanded { border: 1px solid var(--dim); padding: 10px 12px 8px; display: flex; flex-direction: column; gap: 6px; }
.feed-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.feed-name { font: 17px "Share Tech Mono", monospace; letter-spacing: 0.1em; color: var(--text); text-shadow: var(--glow);
  text-transform: uppercase; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.feed-state { font-size: 15px; min-width: 16px; text-align: center; flex: 0 0 auto; }
.state-live { color: var(--cyan); }
.state-reconnecting, .state-starting { color: var(--amber); }
.state-offline { color: var(--alarm); }
.state-parked { color: var(--muted); }
.trace { display: block; width: 100%; height: 36px; }
.feed-controls { display: flex; align-items: center; gap: 6px; }
.feed-controls .btn { min-height: 34px; min-width: 44px; padding: 0; font-size: 12px; border-color: var(--dim); }
.feed-controls .btn[aria-pressed="true"] { border-color: var(--pink); color: var(--pink); }
.spacer { flex: 1 1 auto; }
.chatter-label { font-size: 11px; letter-spacing: 0.14em; color: var(--muted); }
.chatter-big { font: 30px/1 "Share Tech Mono", monospace; color: var(--cyan); text-shadow: var(--glow); font-variant-numeric: tabular-nums; }

.feed.compact {
  min-height: 44px; display: flex; align-items: center; gap: 10px; padding: 0 12px; cursor: pointer;
  border: 1px solid transparent; border-bottom-color: var(--rule);
}
.feed.compact:hover { border-color: var(--dim); }
.feed.compact .feed-name { font-size: 15px; flex: 1 1 auto; text-shadow: none; }
.feed.compact.parked .feed-name { color: var(--muted); }
.note { font-size: 12px; color: var(--muted); }
.chatter-small { font: 18px "Share Tech Mono", monospace; min-width: 26px; text-align: right; color: var(--cyan); font-variant-numeric: tabular-nums; }
.parked .chatter-small { color: var(--muted); }
.feed.flash { animation: flash 1.2s ease-out; }
@keyframes flash { from { border-color: var(--pink); box-shadow: 0 0 12px var(--pink); } }

/* lamps */
.lamps { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 14px 18px; padding: 10px 16px;
  border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.lamp { --lamp: var(--cyan); display: flex; flex-direction: column; align-items: center; gap: 6px; }
.lamp-gap { margin-left: 28px; }
.lamp-light { width: 34px; height: 12px; border: 1px solid var(--muted); background: transparent; }
.lamp-label { font-size: 10px; letter-spacing: 0.12em; color: var(--muted); }
.lamp.on .lamp-light { background: var(--lamp); border-color: var(--lamp); }
.lamp.warn { --lamp: var(--amber); }
.lamp.fault { --lamp: var(--alarm); }
[data-glow="LOW"] .lamp.on .lamp-light, [data-glow="FULL"] .lamp.on .lamp-light { box-shadow: 0 0 10px var(--lamp); }

/* tracks */
.tracks-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 8px 12px 4px; }
.tracks { width: 100%; min-width: 560px; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
.tracks th { padding: 6px 8px; font-weight: 400; color: var(--muted); text-align: left; }
.tracks th.num { text-align: right; }
.empty { padding: 8px; }

/* teletype */
.log { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 8px;
  font-size: 12px; line-height: 1.5; letter-spacing: 0.08em; text-transform: uppercase; }
.log-z { color: var(--muted); margin-right: 12px; }
.log-line.warn { color: var(--amber); }
.log-line.alarm { color: var(--alarm); }
.log-line.page { color: var(--muted); }
.cursor { color: var(--cyan); }

/* -- sheets ------------------------------------------------------------------- */

.sheet {
  width: min(560px, calc(100vw - 32px)); max-height: min(80vh, 720px); padding: 18px 20px; overflow: auto;
  background: #000; color: var(--text); border: 1px solid var(--frame); box-shadow: 0 0 24px color-mix(in srgb, var(--frame) 40%, transparent);
}
.sheet::backdrop { background: rgba(0, 0, 0, 0.7); }
.sheet-small { width: min(440px, calc(100vw - 32px)); }
.sheet h2 { margin: 0; font: 22px "Share Tech Mono", monospace; letter-spacing: 0.16em; color: var(--white); text-shadow: var(--glow); }
.sheet h3 { margin: 18px 0 8px; font-weight: 400; }
.sheet-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; }
.sheet-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.field input[type="search"] { background: #000; border: 1px solid var(--dim); padding: 8px 10px; min-height: 40px; text-transform: uppercase; }
.field input[type="search"]:focus { outline: none; border-color: var(--pink); }
.field-row, .field.field-row { display: flex; flex-direction: row; align-items: center; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
.field-row > span:first-child { min-width: 150px; }
.field-row input[type="range"] { flex: 1 1 160px; accent-color: var(--cyan); }
.segments { display: flex; flex-wrap: wrap; gap: 6px; }
.choices { display: flex; flex-direction: column; gap: 4px; }
.choice { display: flex; gap: 14px; align-items: baseline; width: 100%; min-height: 40px; padding: 6px 10px; text-align: left;
  background: transparent; border: 1px solid var(--rule); cursor: pointer; }
.choice:hover { border-color: var(--cyan); }
.choice .code { font: 16px "Share Tech Mono", monospace; color: var(--cyan); min-width: 56px; }
.choice .what { text-transform: uppercase; }
.choice .tag { margin-left: auto; color: var(--muted); font-size: 11px; letter-spacing: 0.14em; }
.choice .tag.on { color: var(--pink); }
.choice.current { border-color: var(--pink); }

.ended { position: fixed; inset: 0; display: grid; place-items: center; background: rgba(0, 0, 0, 0.88);
  font: 28px "Share Tech Mono", monospace; letter-spacing: 0.24em; color: var(--alarm); text-shadow: var(--glow); }

/* -- display effects (spec, Display effects) ------------------------------------ */

.ovl { position: absolute; inset: 0; z-index: 2; pointer-events: none; display: none; }
[data-display="VECTOR"] .ovl { display: block; background: radial-gradient(ellipse at center, transparent 62%, rgba(0, 0, 0, 0.27) 100%); }
[data-display="CRT"] .ovl { display: block; background:
  repeating-linear-gradient(to bottom, rgba(0, 0, 0, 0.34) 0, rgba(0, 0, 0, 0.34) 1px, transparent 1px, transparent 3px),
  radial-gradient(ellipse at center, transparent 52%, rgba(0, 0, 0, 0.42) 100%); }
[data-display="CRT"] .screen { border-radius: 16px; }
[data-display="VECTOR"] .screen, [data-display="CRT"] .screen { animation: flicker 7.3s infinite; }
.screen:nth-of-type(2n) { animation-delay: -2.1s; }
.column .screen:nth-of-type(2) { animation-delay: -4.6s; }
[data-display="VECTOR"] .jit, [data-display="CRT"] .jit { animation: jitter 5.1s infinite; }
[data-display="CRT"] .jit { filter: drop-shadow(1px 0 0 rgba(255, 40, 90, 0.35)) drop-shadow(-1px 0 0 rgba(0, 210, 255, 0.35)); }
@keyframes flicker { 0%, 100% { opacity: 1; } 31% { opacity: 1; } 31.6% { opacity: 0.93; } 32.2% { opacity: 1; }
  64% { opacity: 1; } 64.4% { opacity: 0.97; } 65% { opacity: 0.95; } 65.6% { opacity: 1; } 88% { opacity: 0.985; } }
@keyframes jitter { 0%, 93%, 100% { transform: translate(0, 0); } 94% { transform: translate(0.7px, -0.4px); }
  95% { transform: translate(-0.6px, 0.3px); } 96% { transform: translate(0.3px, 0.5px); } 97% { transform: translate(0, 0); } }

@media (prefers-reduced-motion: reduce) {
  .screen, .jit, .feed.flash { animation: none !important; }
}
```

- [ ] **Step 4: `store.js`.** Create `src/kcgx/web/static/js/store.js`:

```javascript
// The page's copy of the server's state, built only from protocol frames
// (spec, Transport). Views never change it; they send messages and wait for
// the server's answer, so every tab shows exactly what the server applied.

export const HISTORY = 160; // level samples kept per feed: 6.4 s at 25 Hz
export const SILENT = -96;

export function createStore() {
  const state = {
    connected: false,
    shutdown: false,
    airport: null,
    loading: true,
    feeds: new Map(), // ident -> feed view
    order: [], // idents, stack order
    volume: 1,
    maxStreams: 7,
    audioOk: true,
    prefs: { palette: "WOPR", glow: "LOW", display: "CRT" },
    log: [],
    history: new Map(), // ident -> { samples: Float32Array, next: number }
  };
  const listeners = new Set();
  const emit = (kind, detail) => { for (const fn of listeners) fn(kind, detail, state); };

  function historyFor(ident) {
    let h = state.history.get(ident);
    if (!h) {
      h = { samples: new Float32Array(HISTORY).fill(SILENT), next: 0 };
      state.history.set(ident, h);
    }
    return h;
  }

  function apply(frame) {
    switch (frame.t) {
      case "snapshot":
        state.airport = frame.airport;
        state.loading = frame.loading;
        state.feeds = new Map(frame.feeds.map((f) => [f.ident, f]));
        state.order = frame.feeds.map((f) => f.ident);
        state.volume = frame.volume;
        state.maxStreams = frame.max_streams;
        state.audioOk = frame.audio_ok;
        state.prefs = { ...state.prefs, ...(frame.prefs || {}) };
        state.log = frame.log.slice(-200);
        for (const ident of [...state.history.keys()]) {
          if (!state.feeds.has(ident)) state.history.delete(ident);
        }
        emit("all");
        break;
      case "feed":
        state.feeds.set(frame.feed.ident, frame.feed);
        emit("feed", frame.feed.ident);
        break;
      case "added":
        state.feeds.set(frame.feed.ident, frame.feed);
        if (!state.order.includes(frame.feed.ident)) state.order.push(frame.feed.ident);
        emit("order");
        break;
      case "order":
        state.order = frame.idents.filter((ident) => state.feeds.has(ident));
        emit("order");
        break;
      case "levels":
        for (const [ident, db] of Object.entries(frame.v)) {
          const h = historyFor(ident);
          h.samples[h.next] = db;
          h.next = (h.next + 1) % HISTORY;
        }
        emit("levels");
        break;
      case "chatter":
        for (const [ident, value] of Object.entries(frame.v)) {
          const feed = state.feeds.get(ident);
          if (feed) feed.chatter = value;
        }
        emit("chatter");
        break;
      case "volume":
        state.volume = frame.value;
        emit("volume");
        break;
      case "prefs": {
        const { t, ...prefs } = frame;
        state.prefs = { ...state.prefs, ...prefs };
        emit("prefs");
        break;
      }
      case "message":
        state.log.push({ z: frame.z, text: frame.text });
        if (state.log.length > 200) state.log.shift();
        emit("message", { z: frame.z, text: frame.text });
        break;
      case "error":
        emit("message", { z: "PAGE", text: "error: " + frame.text, page: true });
        break;
    }
  }

  return {
    state,
    apply,
    historyFor,
    setConnected(value) { state.connected = value; emit("connection"); },
    setShutdown() { state.shutdown = true; emit("connection"); },
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
  };
}
```

- [ ] **Step 5: `connection.js`.** Create `src/kcgx/web/static/js/connection.js`:

```javascript
// One WebSocket to the server, reconnected with backoff (spec, Error
// handling: "WebSocket drops"). Nothing is lost while it is down: the server
// holds all state, and the first frame after a reconnect is a snapshot.

const BACKOFF_MS = [500, 1000, 2000, 4000, 5000];

export function connect(store) {
  let socket = null;
  let attempt = 0;
  let stopped = false;

  function open() {
    if (stopped) return;
    socket = new WebSocket(`ws://${location.host}/ws`);
    socket.addEventListener("open", () => {
      attempt = 0;
      store.setConnected(true);
    });
    socket.addEventListener("message", (event) => {
      let frame;
      try { frame = JSON.parse(event.data); } catch { return; }
      store.apply(frame);
    });
    socket.addEventListener("close", () => {
      store.setConnected(false);
      if (stopped) return;
      const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
      attempt += 1;
      setTimeout(open, wait);
    });
  }

  open();

  return {
    send(message) {
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
    },
    stop() {
      stopped = true;
      if (socket) socket.close();
    },
  };
}
```

- [ ] **Step 6: `theme.js`.** Create `src/kcgx/web/static/js/theme.js`:

```javascript
// Palette colours for the canvases, read from the CSS custom properties the
// stylesheet sets per palette, so the DOM and the canvases always agree.

let cache = null;

export function colours() {
  if (!cache) {
    const css = getComputedStyle(document.documentElement);
    const read = (name) => css.getPropertyValue(name).trim();
    cache = {
      cyan: read("--cyan"), dim: read("--dim"), pink: read("--pink"), white: read("--white"),
      amber: read("--amber"), alarm: read("--alarm"), muted: read("--muted"), text: read("--text"),
    };
  }
  return cache;
}

export function glowBlur() {
  const glow = document.documentElement.dataset.glow;
  return glow === "FULL" ? 9 : glow === "LOW" ? 4 : 0;
}

// Called when prefs change: the next read picks up the new palette.
export function forget() { cache = null; }

export function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
```

- [ ] **Step 7: `stack.js`.** Create `src/kcgx/web/static/js/stack.js`:

```javascript
// The frequency stack (spec, The feed stack in this language). An audible
// feed is an expanded row: name, an oscilloscope trace of its level, M and S.
// A muted feed is one compact line, and the whole line is a button that
// unmutes it. Rows are moved, never rebuilt, when the order changes, so a
// trace keeps its history across a reorder.

import { HISTORY } from "./store.js";
import { colours, glowBlur } from "./theme.js";

const GLYPHS = { live: "●", reconnecting: "◐", starting: "◐", offline: "○", parked: "‖" };
const STATES = { live: "LIVE", reconnecting: "RECONNECTING", starting: "STARTING", offline: "OFFLINE", parked: "PARKED" };
const INPUT_EVERY_MS = 1000;

const two = (fraction) => String(Math.round((fraction || 0) * 100)).padStart(2, "0");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function mountStack({ stack, counts }, store, send) {
  const rows = new Map(); // ident -> { node, shape, parts }
  let levelsDirty = false;

  function stateGlyph(feed) {
    const span = el("span", `feed-state state-${feed.state}`, GLYPHS[feed.state] || "●");
    span.title = STATES[feed.state] || feed.state.toUpperCase();
    span.setAttribute("aria-label", span.title);
    return span;
  }

  function buildExpanded(feed) {
    const node = el("div", "feed expanded");
    const head = el("div", "feed-head");
    const name = el("span", "feed-name", feed.name);
    const glyph = stateGlyph(feed);
    head.append(name, glyph);
    const trace = el("canvas", "trace");
    trace.setAttribute("aria-hidden", "true");
    const controls = el("div", "feed-controls");
    const mute = el("button", "btn", "M");
    mute.type = "button";
    mute.addEventListener("click", () => send({ t: "mute", ident: feed.ident }));
    const solo = el("button", "btn", "S");
    solo.type = "button";
    solo.addEventListener("click", () => send({ t: "solo", ident: feed.ident }));
    const label = el("span", "chatter-label", "CHATTER");
    const chatter = el("span", "chatter-big", two(feed.chatter));
    controls.append(mute, solo, el("span", "spacer"), label, chatter);
    node.append(head, trace, controls);
    return { node, parts: { name, glyph, trace, mute, solo, chatter } };
  }

  function buildCompact(feed) {
    const node = el("button", "feed compact");
    node.type = "button";
    node.addEventListener("click", () => send({ t: "mute", ident: feed.ident }));
    const name = el("span", "feed-name", feed.name);
    const note = el("span", "note", "♪");
    note.setAttribute("aria-hidden", "true");
    const chatter = el("span", "chatter-small", two(feed.chatter));
    const glyph = stateGlyph(feed);
    node.append(name, note, chatter, glyph);
    return { node, parts: { name, glyph, chatter } };
  }

  function update(row, feed) {
    const { parts } = row;
    parts.name.textContent = feed.name;
    parts.glyph.textContent = GLYPHS[feed.state] || "●";
    parts.glyph.className = `feed-state state-${feed.state}`;
    parts.glyph.title = STATES[feed.state] || feed.state.toUpperCase();
    parts.glyph.setAttribute("aria-label", parts.glyph.title);
    parts.chatter.textContent = two(feed.chatter);
    if (row.shape === "expanded") {
      parts.mute.setAttribute("aria-pressed", String(feed.muted));
      parts.mute.setAttribute("aria-label", `Mute ${feed.name}`);
      parts.solo.setAttribute("aria-pressed", String(feed.soloed));
      parts.solo.setAttribute("aria-label", `Solo ${feed.name}`);
    } else {
      row.node.classList.toggle("parked", feed.state === "parked");
      row.node.setAttribute(
        "aria-label",
        `Unmute ${feed.name}, chatter ${two(feed.chatter)} percent, ${parts.glyph.title.toLowerCase()}`,
      );
    }
  }

  function render() {
    const { state } = store;
    const wanted = new Set(state.order);
    for (const [ident, row] of rows) {
      if (!wanted.has(ident)) { row.node.remove(); rows.delete(ident); }
    }
    let previous = null;
    for (const ident of state.order) {
      const feed = state.feeds.get(ident);
      if (!feed) continue;
      const shape = feed.muted ? "compact" : "expanded";
      let row = rows.get(ident);
      if (!row || row.shape !== shape) {
        const built = shape === "expanded" ? buildExpanded(feed) : buildCompact(feed);
        const fresh = { ...built, shape };
        if (row) row.node.replaceWith(fresh.node);
        row = fresh;
        rows.set(ident, row);
        row.node.dataset.ident = ident;
      }
      update(row, feed);
      // Move only what is out of place: a moved node keeps its canvas.
      const expectedNext = previous ? previous.nextSibling : stack.firstChild;
      if (row.node !== expectedNext) stack.insertBefore(row.node, expectedNext);
      previous = row.node;
    }
    renderEmpty();
    renderCounts();
    levelsDirty = true;
  }

  function renderEmpty() {
    const { state } = store;
    let message = "";
    if (!state.connected && !state.airport) message = "CONNECTING";
    else if (state.loading) message = `LOADING FEEDS FOR ${state.airport ? state.airport.icao : ""}`;
    else if (state.order.length === 0) message = `NO FEEDS AT ${state.airport ? state.airport.icao : "THIS AIRPORT"}`;
    let empty = stack.querySelector(".stack-empty");
    if (message) {
      if (!empty) { empty = el("p", "stack-empty"); stack.append(empty); }
      empty.textContent = message;
    } else if (empty) {
      empty.remove();
    }
  }

  function renderCounts() {
    const { state } = store;
    const feeds = [...state.feeds.values()];
    const live = feeds.filter((f) => f.state === "live").length;
    const parked = feeds.filter((f) => f.state === "parked").length;
    counts.replaceChildren(
      el("span", "", `${feeds.length} FEEDS`),
      el("span", "", `${live} LIVE  ${parked} PARKED`),
      el("span", "", `VOL ${Math.round(state.volume * 100)}%`),
    );
  }

  // -- the traces ---------------------------------------------------------------

  function drawTrace(canvas, ident) {
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(canvas.clientWidth * ratio));
    const height = Math.max(1, Math.round(canvas.clientHeight * ratio));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const ctx = canvas.getContext("2d");
    const c = colours();
    ctx.clearRect(0, 0, width, height);
    const mid = height / 2;
    ctx.save();
    ctx.strokeStyle = c.dim;
    ctx.lineWidth = Math.max(1, 0.6 * ratio);
    ctx.setLineDash([1 * ratio, 4 * ratio]);
    ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(width, mid); ctx.stroke();
    ctx.restore();

    const h = store.historyFor(ident);
    ctx.save();
    ctx.strokeStyle = c.cyan;
    ctx.lineWidth = 1.2 * ratio;
    ctx.lineJoin = "round";
    ctx.shadowColor = c.cyan;
    ctx.shadowBlur = glowBlur() * ratio;
    ctx.beginPath();
    for (let i = 0; i < HISTORY; i += 1) {
      const slot = (h.next + i) % HISTORY;
      const db = h.samples[slot];
      const amp = Math.min(1, Math.max(0, (db + 70) / 58));
      const sign = slot % 2 ? 1 : -1;
      const x = (i / (HISTORY - 1)) * width;
      const y = mid + sign * amp * mid * 0.92;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();
  }

  function frame() {
    if (levelsDirty) {
      levelsDirty = false;
      for (const [ident, row] of rows) {
        if (row.shape === "expanded") drawTrace(row.parts.trace, ident);
      }
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // The viewer's hand on the stack holds the resort (spec, Feature parity).
  let lastInput = 0;
  stack.addEventListener("pointermove", () => {
    const now = performance.now();
    if (now - lastInput > INPUT_EVERY_MS) { lastInput = now; send({ t: "input" }); }
  });

  store.subscribe((kind) => {
    if (kind === "levels") levelsDirty = true;
    else if (kind === "prefs") levelsDirty = true;
    else if (kind !== "message") render();
  });
  window.addEventListener("resize", () => { levelsDirty = true; });
  render();

  return {
    // Bring an open feed into view and mark it, for the feed picker.
    show(ident) {
      const row = rows.get(ident);
      if (!row) return;
      row.node.scrollIntoView({ block: "nearest" });
      row.node.classList.remove("flash");
      void row.node.offsetWidth;
      row.node.classList.add("flash");
    },
  };
}
```

- [ ] **Step 8: `status.js`.** Create `src/kcgx/web/static/js/status.js`:

```javascript
// The status screen: the airport and two clocks. Zulu is HHMMZ; local is the
// viewer's own clock with its zone, since the airport dataset has no zones.

const pad = (n) => String(n).padStart(2, "0");

export function mountStatus(nodes, store) {
  const zone = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" })
    .formatToParts(new Date()).find((p) => p.type === "timeZoneName");

  function tick() {
    const now = new Date();
    nodes.zulu.textContent = `${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}Z`;
    nodes.local.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())} ${zone ? zone.value : ""}`.trim();
  }

  function render() {
    const airport = store.state.airport;
    if (!airport) return;
    nodes.icao.textContent = airport.icao;
    nodes.name.textContent = (airport.name || "UNKNOWN AIRPORT").toUpperCase();
    nodes.where.textContent = (airport.where || "").toUpperCase();
    document.title = `KCGX ${airport.icao}`;
  }

  tick();
  setInterval(tick, 1000);
  store.subscribe((kind) => { if (kind === "all") render(); });
  render();
}
```

- [ ] **Step 9: `lamps.js`.** Create `src/kcgx/web/static/js/lamps.js`:

```javascript
// The lamp bar (spec, Visual language): one lamp per feed, lit in its state
// colour (cyan live, amber reconnecting, red offline, dark parked), then the
// system lamps. RADAR and EMERG stay dark until phase D.

const SHORT = [
  [/clearance delivery/i, "DEL"], [/delivery/i, "DEL"], [/approach/i, "APP"], [/departure/i, "DEP"],
  [/tower/i, "TWR"], [/ground/i, "GND"], [/atis/i, "ATIS"], [/center|centre/i, "CTR"],
  [/emergency|guard/i, "GRD"], [/ramp/i, "RAMP"],
];

export function shortLabel(name) {
  for (const [pattern, short] of SHORT) if (pattern.test(name)) return short;
  return name.replace(/^[A-Z]{3,4}\s+/, "").slice(0, 4).toUpperCase();
}

const LIT = { live: "live", starting: "warn", reconnecting: "warn", offline: "fault" };

function lamp(label, colour, title) {
  const on = Boolean(colour);
  const node = document.createElement("span");
  node.className = `lamp ${on ? `on ${colour}` : ""}`.trim();
  const light = document.createElement("span");
  light.className = "lamp-light";
  const text = document.createElement("span");
  text.className = "lamp-label";
  text.textContent = label;
  node.append(light, text);
  node.title = title;
  node.setAttribute("aria-label", `${title}: ${on ? "on" : "off"}`);
  return node;
}

export function mountLamps(row, store) {
  function render() {
    const { state } = store;
    const lamps = [];
    const seen = new Map();
    for (const ident of state.order) {
      const feed = state.feeds.get(ident);
      if (!feed) continue;
      let label = shortLabel(feed.name);
      const count = (seen.get(label) || 0) + 1;
      seen.set(label, count);
      if (count > 1) label = `${label}${count}`;
      const title = `${feed.name}, ${feed.state}${feed.muted ? ", muted" : ""}`;
      lamps.push(lamp(label, LIT[feed.state], title));
    }
    const gap = document.createElement("span");
    gap.className = "lamp-gap";
    lamps.push(
      gap,
      lamp("RADAR", null, "Radar, arrives in phase D"),
      lamp("SERVER", state.connected ? "live" : "fault", "Connection to the KCGX server"),
      lamp("AUDIO", state.connected ? (state.audioOk ? "live" : "fault") : null, "Audio output on the server"),
      lamp("EMERG", null, "Emergency squawk, arrives in phase D"),
    );
    row.replaceChildren(...lamps);
  }
  store.subscribe((kind) => {
    if (kind !== "levels" && kind !== "chatter" && kind !== "message" && kind !== "volume") render();
  });
  render();
}
```

- [ ] **Step 10: `log.js`.** Create `src/kcgx/web/static/js/log.js`:

```javascript
// The teletype: one line per message, newest at the bottom. A new line types
// itself out within 400 ms; with reduced motion it appears at once. The
// snapshot's history is drawn instantly.

import { reducedMotion } from "./theme.js";

const CAP = 200;
const TYPE_MS = 400;

function kindOf(text) {
  if (/^error|fail|could not|403|offline/i.test(text)) return "alarm";
  if (/reconnect|retry|warn/i.test(text)) return "warn";
  return "";
}

export function mountLog(node, store) {
  const queue = [];
  let typing = false;

  function line(entry) {
    const row = document.createElement("div");
    row.className = `log-line ${entry.page ? "alarm" : kindOf(entry.text)}`.trim();
    const z = document.createElement("span");
    z.className = "log-z";
    z.textContent = entry.z;
    const text = document.createElement("span");
    text.className = "log-text";
    row.append(z, text);
    return { row, text };
  }

  function stick(fn) {
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 24;
    fn();
    while (node.childElementCount > CAP) node.firstElementChild.remove();
    if (atBottom) node.scrollTop = node.scrollHeight;
  }

  function drawAll() {
    queue.length = 0;
    stick(() => {
      node.replaceChildren();
      for (const entry of store.state.log) {
        const { row, text } = line(entry);
        text.textContent = entry.text.toUpperCase();
        node.append(row);
      }
    });
    node.scrollTop = node.scrollHeight;
  }

  function next() {
    const entry = queue.shift();
    if (!entry) { typing = false; return; }
    typing = true;
    const { row, text } = line(entry);
    const full = entry.text.toUpperCase();
    stick(() => node.append(row));
    if (reducedMotion() || queue.length > 3) {
      text.textContent = full;
      next();
      return;
    }
    const start = performance.now();
    const step = (now) => {
      const shown = Math.min(full.length, Math.ceil(((now - start) / TYPE_MS) * full.length));
      text.textContent = full.slice(0, shown);
      if (shown < full.length) requestAnimationFrame(step);
      else next();
    };
    requestAnimationFrame(step);
  }

  store.subscribe((kind, detail) => {
    if (kind === "all") drawAll();
    else if (kind === "message") { queue.push(detail); if (!typing) next(); }
  });

  return {
    // A line from the page itself, such as a failed request.
    say(text) { queue.push({ z: "PAGE", text, page: true }); if (!typing) next(); },
  };
}
```

- [ ] **Step 11: `sheets.js`.** Create `src/kcgx/web/static/js/sheets.js`:

```javascript
// The four sheets: change airport, feeds, config and shut down. Each is a
// <dialog>, so focus, Escape and the backdrop come from the browser.

const CHOICES = {
  palette: ["WOPR", "AMBER", "MATRIX", "MONO"],
  glow: ["OFF", "LOW", "FULL"],
  display: ["OFF", "VECTOR", "CRT"],
};

function button(className, label, onClick) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  node.textContent = label;
  node.addEventListener("click", onClick);
  return node;
}

function debounce(fn, ms) {
  let timer = 0;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

async function json(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `${response.status}`);
  return body;
}

export function mountAirportSheet({ sheet, query, results }, store, log) {
  let ask = 0;
  const search = debounce(async () => {
    const mine = (ask += 1);
    const q = query.value.trim();
    if (!q) { results.replaceChildren(); return; }
    let found = [];
    try { found = await json(`/api/airports?q=${encodeURIComponent(q)}`); } catch (error) { log.say(`airport search failed: ${error.message}`); }
    if (mine !== ask) return;
    if (!found.length) {
      const none = document.createElement("p");
      none.className = "muted small";
      none.textContent = "NO MATCHING AIRPORTS";
      results.replaceChildren(none);
      return;
    }
    results.replaceChildren(...found.slice(0, 40).map((airport) => {
      const node = button("choice", "", () => choose(airport.icao));
      const code = document.createElement("span");
      code.className = "code";
      code.textContent = airport.icao;
      const name = document.createElement("span");
      name.className = "what";
      name.textContent = airport.name.toUpperCase();
      const where = document.createElement("span");
      where.className = "muted small";
      where.textContent = airport.where.toUpperCase();
      if (store.state.airport && airport.icao === store.state.airport.icao) node.classList.add("current");
      node.append(code, name, where);
      return node;
    }));
  }, 150);

  async function choose(icao) {
    sheet.close();
    try {
      await json("/api/airport", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ icao }),
      });
    } catch (error) {
      log.say(`could not change airport: ${error.message}`);
    }
  }

  query.addEventListener("input", search);
  return {
    open() {
      query.value = "";
      results.replaceChildren();
      sheet.showModal();
      query.focus();
    },
  };
}

export function mountFeedsSheet({ sheet, query, status, results }, store, send, onOpened) {
  let feeds = [];

  function draw() {
    const filter = query.value.trim().toLowerCase();
    const shown = feeds.filter((f) => !filter || f.label.toLowerCase().includes(filter) || f.ident.includes(filter));
    status.textContent = `${feeds.length} FEEDS AT ${store.state.airport ? store.state.airport.icao : ""}, ${feeds.filter((f) => f.open).length} OPEN`;
    results.replaceChildren(...shown.map((feed) => {
      const node = button("choice", "", () => {
        if (!feed.open) send({ t: "open_feed", ident: feed.ident });
        sheet.close();
        onOpened(feed.ident);
      });
      const name = document.createElement("span");
      name.className = "what";
      name.textContent = feed.label.toUpperCase();
      const tag = document.createElement("span");
      tag.className = feed.open ? "tag on" : "tag";
      tag.textContent = feed.open ? "OPEN" : "ADD";
      node.append(name, tag);
      return node;
    }));
  }

  query.addEventListener("input", draw);
  return {
    async open() {
      query.value = "";
      feeds = [];
      results.replaceChildren();
      status.textContent = "LOADING THE FEED LIST";
      sheet.showModal();
      query.focus();
      try {
        feeds = await json("/api/feeds/available");
      } catch {
        status.textContent = "COULD NOT LOAD THE FEED LIST";
        return;
      }
      draw();
    },
  };
}

export function mountConfigSheet({ sheet, volume, volumeValue, maxStreams }, store, send) {
  const groups = [...sheet.querySelectorAll(".segments")];
  for (const group of groups) {
    const pref = group.dataset.pref;
    group.replaceChildren(...CHOICES[pref].map((value) => {
      const node = button("btn seg", value, () => send({ t: "prefs", [pref]: value }));
      node.dataset.value = value;
      return node;
    }));
  }

  const sendVolume = debounce((value) => send({ t: "volume", value }), 60);
  volume.addEventListener("input", () => {
    volumeValue.textContent = `${volume.value}%`;
    sendVolume(Number(volume.value) / 100);
  });

  function render() {
    const { state } = store;
    if (document.activeElement !== volume) {
      volume.value = String(Math.round(state.volume * 100));
      volumeValue.textContent = `${volume.value}%`;
    }
    maxStreams.textContent = String(state.maxStreams);
    for (const group of groups) {
      const current = state.prefs[group.dataset.pref];
      for (const node of group.children) node.setAttribute("aria-pressed", String(node.dataset.value === current));
    }
  }

  store.subscribe((kind) => { if (kind === "all" || kind === "volume" || kind === "prefs") render(); });
  render();
  return { open() { render(); sheet.showModal(); } };
}

export function mountShutdownSheet({ sheet }, store, onEnded, log) {
  sheet.addEventListener("close", async () => {
    if (sheet.returnValue !== "confirm") return;
    try {
      await json("/api/shutdown", { method: "POST" });
      onEnded();
    } catch (error) {
      log.say(`shut down failed: ${error.message}`);
    }
  });
  return { open() { sheet.returnValue = ""; sheet.showModal(); } };
}

export { CHOICES };
```

- [ ] **Step 12: `radar.js`.** Create `src/kcgx/web/static/js/radar.js`:

```javascript
// The radar placeholder until phase D: range rings every 10 nm out to 40,
// the airport in pink at the centre, sized to fill its pane. The 40 nm ring
// fits the shorter side; the longer side shows more of the map.

import { colours, glowBlur } from "./theme.js";

const RINGS_NM = [10, 20, 30, 40];

export function mountRadar(canvas, store) {
  let dirty = true;

  function draw() {
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(box.width * ratio));
    const height = Math.max(1, Math.round(box.height * ratio));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    const ctx = canvas.getContext("2d");
    const c = colours();
    const cx = width / 2;
    const cy = height / 2;
    const perNm = Math.max(0, Math.min(width, height) / 2 - 18 * ratio) / 40;
    ctx.clearRect(0, 0, width, height);

    ctx.save();
    ctx.strokeStyle = c.dim;
    ctx.lineWidth = ratio;
    ctx.setLineDash([2 * ratio, 6 * ratio]);
    ctx.beginPath();
    ctx.moveTo(0, cy); ctx.lineTo(width, cy);
    ctx.moveTo(cx, 0); ctx.lineTo(cx, height);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.strokeStyle = c.cyan;
    ctx.shadowColor = c.cyan;
    ctx.shadowBlur = glowBlur() * ratio;
    ctx.lineWidth = ratio;
    ctx.fillStyle = c.dim;
    ctx.font = `${11 * ratio}px "Share Tech Mono", monospace`;
    ctx.textAlign = "left";
    for (const nm of RINGS_NM) {
      ctx.globalAlpha = nm === 40 ? 0.9 : 0.45;
      ctx.beginPath();
      ctx.arc(cx, cy, nm * perNm, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.fillText(`${nm}`, cx + nm * perNm * Math.SQRT1_2 + 4 * ratio, cy - nm * perNm * Math.SQRT1_2 - 4 * ratio);
    }
    ctx.restore();

    const airport = store.state.airport;
    ctx.save();
    ctx.strokeStyle = c.pink;
    ctx.fillStyle = c.pink;
    ctx.shadowColor = c.pink;
    ctx.shadowBlur = glowBlur() * ratio;
    ctx.lineWidth = 1.5 * ratio;
    ctx.beginPath();
    ctx.arc(cx, cy, 6 * ratio, 0, Math.PI * 2);
    ctx.stroke();
    if (airport) {
      ctx.font = `${13 * ratio}px "Share Tech Mono", monospace`;
      ctx.fillText(airport.icao, cx + 10 * ratio, cy + 18 * ratio);
    }
    ctx.restore();
  }

  function frame() {
    if (dirty) { dirty = false; draw(); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  new ResizeObserver(() => { dirty = true; }).observe(canvas);
  store.subscribe((kind) => { if (kind === "all" || kind === "prefs") dirty = true; });
  return { redraw() { dirty = true; } };
}
```

- [ ] **Step 13: `main.js`.** Create `src/kcgx/web/static/js/main.js`:

```javascript
// The cockpit page: one store, one connection, and the views that draw it.
// Every action is a click (spec, Every action is a click).

import { createStore } from "./store.js";
import { connect } from "./connection.js";
import { forget } from "./theme.js";
import { mountStack } from "./stack.js";
import { mountStatus } from "./status.js";
import { mountLamps } from "./lamps.js";
import { mountLog } from "./log.js";
import { mountRadar } from "./radar.js";
import {
  CHOICES, mountAirportSheet, mountConfigSheet, mountFeedsSheet, mountShutdownSheet,
} from "./sheets.js";

const $ = (id) => document.getElementById(id);
const store = createStore();
const link = connect(store);
const send = (message) => link.send(message);

function applyPrefs() {
  const { prefs } = store.state;
  const root = document.documentElement;
  root.dataset.palette = prefs.palette;
  root.dataset.glow = prefs.glow;
  root.dataset.display = prefs.display;
  $("palette-name").textContent = prefs.palette;
  forget();
}

const log = mountLog($("log"), store);
const stack = mountStack({ stack: $("stack"), counts: $("freq-counts") }, store, send);
mountStatus({
  icao: $("icao"), name: $("airport-name"), where: $("airport-where"), zulu: $("zulu"), local: $("local"),
}, store);
mountLamps($("lamps"), store);
const radar = mountRadar($("radar"), store);

const airportSheet = mountAirportSheet(
  { sheet: $("airport-sheet"), query: $("airport-query"), results: $("airport-results") }, store, log,
);
const feedsSheet = mountFeedsSheet(
  { sheet: $("feeds-sheet"), query: $("feeds-query"), status: $("feeds-status"), results: $("feeds-results") },
  store, send, (ident) => setTimeout(() => stack.show(ident), 300),
);
const configSheet = mountConfigSheet(
  { sheet: $("config-sheet"), volume: $("volume"), volumeValue: $("volume-value"), maxStreams: $("max-streams") },
  store, send,
);
const shutdownSheet = mountShutdownSheet({ sheet: $("shutdown-sheet") }, store, () => {
  store.setShutdown();
  link.stop();
  $("ended").hidden = false;
}, log);

$("open-airport").addEventListener("click", () => airportSheet.open());
$("open-feeds").addEventListener("click", () => feedsSheet.open());
$("open-config").addEventListener("click", () => configSheet.open());
$("open-shutdown").addEventListener("click", () => shutdownSheet.open());
$("next-palette").addEventListener("click", () => {
  const all = CHOICES.palette;
  const next = all[(all.indexOf(store.state.prefs.palette) + 1) % all.length];
  send({ t: "prefs", palette: next });
});
$("recentre").addEventListener("click", () => radar.redraw());

function banner() {
  const { state } = store;
  const node = $("banner");
  let text = "";
  let kind = "";
  if (state.shutdown) text = "";
  else if (!state.connected) { text = "CONNECTION LOST. RECONNECTING TO THE KCGX SERVER"; kind = "warn"; }
  else if (!state.audioOk) { text = "NO AUDIO OUTPUT ON THE SERVER. THE FEEDS STILL RUN; CHECK THE SOUND DEVICE"; kind = "bad"; }
  node.hidden = !text;
  node.textContent = text;
  node.className = `banner ${kind}`.trim();
}

store.subscribe((kind) => {
  if (kind === "all" || kind === "prefs") { applyPrefs(); radar.redraw(); }
  if (kind === "all" || kind === "connection") banner();
});
banner();
$("where-served").textContent = `LOCAL COCKPIT  ${location.host}`;
```

- [ ] **Step 14:** Every module parses:
  `for f in src/kcgx/web/static/js/*.js; do node --input-type=module --check < $f; done`
  (skip if there is no Node; Task 7 and Task 8 catch the same things).
  Suite: **904 passed**, unchanged.
- [ ] **Step 15:** Commit `feat(web): the cockpit page`.

---

### Task 7: Serving the page, prefs and `--demo`

**Files:** `src/kcgx/server.py`, `tests/test_server.py`.

- [ ] **Step 1: Tests.** Apply. `test_the_debug_page_is_served` now asks
  `/debug`; `test_the_cockpit_page_is_served` takes over `/`. The import
  block is re-sorted by ruff, which is why the `kcgx.prefs` import appears
  where it does.

```diff
diff --git a/tests/test_server.py b/tests/test_server.py
index 29f5bb3..d30d87b 100644
--- a/tests/test_server.py
+++ b/tests/test_server.py
@@ -12,12 +12,12 @@ import json
 import pytest
 from starlette.testclient import TestClient
 from starlette.websockets import WebSocketDisconnect
+from station_fakes import AIRPORTS, Builder, listing, picker
 
 from kcgx.server import HOST, LocalOnly, create_app, main, parse_args
 from kcgx.station import Station
 from squelch.config import Config
 from squelch.mixer import Mixer
-from station_fakes import AIRPORTS, Builder, listing, picker
 
 BASE = "http://127.0.0.1:8473"
 # A full URL: the test client sends Host: testserver for a bare path.
@@ -38,6 +38,7 @@ def app(**kwargs):
             sessions_builder=Builder(),
             picker_loader=picker,
             remember=lambda icao: None,
+            remember_prefs=lambda prefs: None,
         )
 
     options = dict(level_hz=0, resort_seconds=0)
@@ -176,16 +177,83 @@ def test_levels_stream_while_a_page_is_open():
 # -- HTTP ----------------------------------------------------------------------
 
 
-def test_the_debug_page_is_served():
+def test_the_cockpit_page_is_served():
     asgi, _ = app()
     with client(asgi) as http:
         response = http.get("/")
     assert response.status_code == 200
     assert "text/html" in response.headers["content-type"]
+    assert "/static/js/main.js" in response.text
+    assert response.headers["cache-control"] == "no-cache"
+
+
+def test_the_debug_page_is_served():
+    asgi, _ = app()
+    with client(asgi) as http:
+        response = http.get("/debug")
+    assert response.status_code == 200
     assert "/ws" in response.text
     assert response.headers["cache-control"] == "no-cache"
 
 
+@pytest.mark.parametrize(
+    "path, kind",
+    [
+        ("/static/cockpit.css", "text/css"),
+        ("/static/js/main.js", "javascript"),
+        ("/static/fonts/share-tech-mono-latin-400-normal.woff2", "font/woff2"),
+    ],
+)
+def test_static_files_are_served_uncached(path, kind):
+    asgi, _ = app()
+    with client(asgi) as http:
+        response = http.get(path)
+    assert response.status_code == 200
+    assert kind in response.headers["content-type"]
+    assert response.headers["cache-control"] == "no-cache"
+
+
+def test_static_files_stay_inside_their_folder():
+    asgi, _ = app()
+    with client(asgi) as http:
+        assert http.get("/static/../server.py").status_code == 404
+        assert http.get("/static/%2e%2e/server.py").status_code == 404
+
+
+def test_every_module_the_page_imports_is_served():
+    """A missing or misnamed module is a blank page with no error on the
+    server: catch it here."""
+    import re
+
+    from kcgx.server import WEB_DIR
+
+    js = WEB_DIR / "static" / "js"
+    asgi, _ = app()
+    with client(asgi) as http:
+        for module in js.glob("*.js"):
+            for name in re.findall(r'from "\./([\w.]+)"', module.read_text()):
+                assert (js / name).is_file(), f"{module.name} imports a missing {name}"
+                assert http.get(f"/static/js/{name}").status_code == 200
+
+
+def test_prefs_from_one_page_reach_another():
+    asgi, _ = app()
+    with client(asgi) as http, http.websocket_connect(WS) as one, http.websocket_connect(WS) as two:
+        assert ready(one)["prefs"]["palette"] == "WOPR"
+        ready(two)
+        one.send_text(json.dumps({"t": "prefs", "palette": "AMBER"}))
+        frame = until(two, lambda f: f["t"] == "prefs")
+        assert frame == {"t": "prefs", "palette": "AMBER", "glow": "LOW", "display": "CRT"}
+
+
+def test_a_bad_prefs_message_gets_an_error():
+    asgi, _ = app()
+    with client(asgi) as http, http.websocket_connect(WS) as ws:
+        ready(ws)
+        ws.send_text(json.dumps({"t": "prefs", "palette": "PLAID"}))
+        assert until(ws, lambda f: f["t"] == "error")["text"].startswith("palette")
+
+
 def test_airport_search_uses_the_dataset():
     asgi, _ = app()
     with client(asgi) as http:
@@ -294,3 +362,38 @@ def test_the_command_serves_and_closes_the_mixer_afterwards(monkeypatch, tmp_pat
     assert served["port"] == 9100
     assert isinstance(served["app"], LocalOnly)
     assert mixers[0].started and mixers[0].stopped
+
+
+def test_demo_needs_no_ffmpeg_and_remembers_nothing(monkeypatch, tmp_path):
+    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
+    served = {}
+
+    def serve(asgi, port, on_server):
+        served["app"] = asgi
+
+    lines = []
+    code = main(["--demo", "--icao", "KSEA"], which=lambda n: None, serve=serve, out=lines.append)
+    assert code == 0
+    assert lines[-1].endswith("(KSEA, demo)")
+    with TestClient(served["app"], base_url=BASE) as http, http.websocket_connect(WS) as ws:
+        assert ready(ws)["feeds"][0]["ident"] == "ksea_twr"
+        ws.send_text(json.dumps({"t": "prefs", "palette": "MONO"}))
+        until(ws, lambda f: f["t"] == "prefs")
+    from kcgx.prefs import prefs_path
+    from kcgx.state import default_path
+
+    assert not prefs_path().exists()
+    assert not default_path().exists()
+
+
+def test_prefs_are_read_at_startup(monkeypatch, tmp_path):
+    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
+    from kcgx.prefs import prefs_path, write_prefs
+
+    write_prefs({"palette": "MATRIX", "glow": "OFF", "display": "VECTOR"})
+    assert prefs_path().exists()
+    served = {}
+    main(["--demo", "--icao", "KPDX"], which=lambda n: None,
+         serve=lambda asgi, port, on_server: served.setdefault("app", asgi), out=lambda line: None)
+    with TestClient(served["app"], base_url=BASE) as http, http.websocket_connect(WS) as ws:
+        assert ready(ws)["prefs"] == {"palette": "MATRIX", "glow": "OFF", "display": "VECTOR"}
```

- [ ] **Step 2:** They fail: `/` still serves the debug page, `/static/`
  is a 404, and `--demo` is an unknown argument.
- [ ] **Step 3: The server.** Apply:

```diff
diff --git a/src/kcgx/server.py b/src/kcgx/server.py
index d435a41..a701c20 100644
--- a/src/kcgx/server.py
+++ b/src/kcgx/server.py
@@ -5,10 +5,11 @@ Binds to 127.0.0.1 and nowhere else, and answers only pages served from
 itself (see LocalOnly). Audio plays on this machine through the mixer;
 pages only ever receive state and levels.
 
-    kcgx-web [--port 8473] [--icao KPDX]
+    kcgx-web [--port 8473] [--icao KPDX] [--demo]
 
-Until phase C ships the real page, / serves a bare debug page that can
-drive every control.
+/ is the cockpit page; /debug is the bare page phase B used to drive the
+server, kept because it shows the raw protocol. --demo runs synthetic feeds
+with no network, ffmpeg or audio (see kcgx.demo).
 """
 
 from __future__ import annotations
@@ -27,12 +28,14 @@ from typing import Any
 from starlette.applications import Starlette
 from starlette.requests import Request
 from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
-from starlette.routing import Route, WebSocketRoute
+from starlette.routing import Mount, Route, WebSocketRoute
+from starlette.staticfiles import StaticFiles
 from starlette.websockets import WebSocket, WebSocketDisconnect
 
 from kcgx import protocol
 from kcgx.airports import find, load_airports, search
 from kcgx.hub import Client, Hub
+from kcgx.prefs import read_prefs
 from kcgx.state import current_icao
 from kcgx.station import Station, UnknownAirport
 
@@ -44,6 +47,19 @@ WEB_DIR = Path(__file__).parent / "web"
 
 StationFactory = Callable[[Hub, Callable[..., None]], Station]
 
+# Revalidate on every load, so an edited page or script shows on a plain
+# reload instead of after the browser's heuristic cache expires.
+NO_CACHE = {"Cache-Control": "no-cache"}
+
+
+class _Static(StaticFiles):
+    """The page's scripts, styles and fonts, served no-cache."""
+
+    async def get_response(self, path, scope):
+        response = await super().get_response(path, scope)
+        response.headers.update(NO_CACHE)
+        return response
+
 
 # -- answering local pages only ----------------------------------------------
 
@@ -128,13 +144,10 @@ def create_app(
             station.stop()
 
     async def page(request: Request):
-        # no-cache: revalidate on every load, so an edited page shows on a
-        # plain reload instead of after the browser's heuristic cache expires.
-        return FileResponse(
-            WEB_DIR / "debug.html",
-            media_type="text/html",
-            headers={"Cache-Control": "no-cache"},
-        )
+        return FileResponse(WEB_DIR / "index.html", media_type="text/html", headers=NO_CACHE)
+
+    async def debug(request: Request):
+        return FileResponse(WEB_DIR / "debug.html", media_type="text/html", headers=NO_CACHE)
 
     async def health(request: Request):
         station = request.app.state.station
@@ -211,6 +224,8 @@ def create_app(
     app = Starlette(
         routes=[
             Route("/", page),
+            Route("/debug", debug),
+            Mount("/static", app=_Static(directory=WEB_DIR / "static"), name="static"),
             Route("/api/health", health),
             Route("/api/airports", airports),
             Route("/api/airport", set_airport, methods=["POST"]),
@@ -269,6 +284,11 @@ def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
         help=f"port on {HOST} (default {DEFAULT_PORT}, or $KCGX_PORT)",
     )
     parser.add_argument("--icao", help="start at this airport instead of the remembered one")
+    parser.add_argument(
+        "--demo",
+        action="store_true",
+        help="synthetic feeds: no network, no ffmpeg, no audio, nothing remembered",
+    )
     return parser.parse_args(argv)
 
 
@@ -294,7 +314,7 @@ def main(
     from squelch.runtime import FFMPEG_MISSING
 
     args = parse_args(argv)
-    if which("ffmpeg") is None:
+    if not args.demo and which("ffmpeg") is None:
         print(f"kcgx-web: {FFMPEG_MISSING}", file=sys.stderr)
         return 2
     try:
@@ -309,6 +329,19 @@ def main(
         print(f"kcgx-web: no airport {icao!r} in the dataset", file=sys.stderr)
         return 2
 
+    if args.demo:
+        from kcgx import demo
+
+        mixer_factory = demo.DemoMixer
+        options = {
+            "feeds_loader": demo.listing,
+            "sessions_builder": demo.build,
+            "picker_loader": demo.picker,
+            "remember": lambda icao: None,
+            "remember_prefs": lambda prefs: None,
+        }
+    else:
+        options = {}
     if mixer_factory is None:
         from squelch.mixer import Mixer as mixer_factory
     mixer = mixer_factory(
@@ -318,15 +351,16 @@ def main(
     )
     mixer.start()
 
+    prefs = read_prefs()
     holder: dict[str, Any] = {}
     app = create_app(
         station_factory=lambda hub, post: Station(
-            config, hub, post=post, airports=known, mixer=mixer
+            config, hub, post=post, airports=known, mixer=mixer, prefs=prefs, **options
         ),
         initial_icao=icao,
         on_exit=lambda: setattr(holder["server"], "should_exit", True),
     )
-    out(f"kcgx: http://{HOST}:{args.port}/  ({icao})")
+    out(f"kcgx: http://{HOST}:{args.port}/  ({icao}{', demo' if args.demo else ''})")
     try:
         serve(app, args.port, lambda server: holder.__setitem__("server", server))
     finally:
```

- [ ] **Step 4:** `uv run pytest -q tests/test_server.py`: 37 passed.
  Suite: **914 passed**.
- [ ] **Step 5:** `uv run kcgx-web --demo --port 8474` prints
  `kcgx: http://127.0.0.1:8474/  (KPDX, demo)`. Open it: the wall appears,
  Tower is expanded with a moving trace, nine lamps sit in the bar, and
  two quiet feeds are parked (LiveATC's limit of seven, simulated).
  Ctrl-C.
- [ ] **Step 6:** Commit `feat(web): serve the cockpit; kcgx-web --demo`.

---

### Task 8: The page in a browser

**Files:** Create `tests/test_page.py`.

- [ ] **Step 1:** Create `tests/test_page.py`:

```python
"""The cockpit page in a real browser, against `kcgx-web --demo`.

These need Playwright and its Chromium (`uv sync --group browser`, then
`uv run playwright install chromium`); without them they skip. The server
runs as a subprocess with its state in a temporary folder, so nothing here
touches ~/.local/state/kcgx.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

playwright_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

SIZES = [(1440, 900), (1280, 720), (1100, 760), (820, 1000), (390, 844)]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    state = tmp_path_factory.mktemp("page-state")
    port = _free_port()
    env = {
        **os.environ,
        "KCGX_STATE_PATH": str(state / "airport"),
        "HOME": str(state / "home"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "kcgx.server", "--demo", "--icao", "KPDX", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=1) as response:
                if json.load(response)["ok"]:
                    break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.fail("kcgx-web --demo never answered: " + process.stdout.read().decode())
    yield base
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch()
        except playwright_api.Error as error:  # no browser installed
            pytest.skip(f"no Chromium for Playwright: {error}")
        yield launched
        launched.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(server + "/")
    page.wait_for_selector(".feed.expanded")
    yield page
    context.close()
    assert errors == [], errors


def feed_names(page, shape):
    return page.eval_on_selector_all(f".feed.{shape} .feed-name", "els => els.map(e => e.textContent)")


# -- layout --------------------------------------------------------------------


@pytest.mark.parametrize("width, height", SIZES)
def test_no_two_screens_overlap_and_none_spills_out(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(200)
    boxes = page.eval_on_selector_all(
        ".screen",
        "els => els.map(e => { const r = e.getBoundingClientRect();"
        " return [e.getAttribute('aria-label'), r.left, r.top, r.right, r.bottom]; })",
    )
    assert len(boxes) == 5
    for i, (name, left, top, right, bottom) in enumerate(boxes):
        assert right - left > 100 and bottom - top > 40, f"{name} collapsed at {width}x{height}"
        for other, l2, t2, r2, b2 in boxes[i + 1:]:
            apart = right <= l2 + 0.5 or r2 <= left + 0.5 or bottom <= t2 + 0.5 or b2 <= top + 0.5
            assert apart, f"{name} overlaps {other} at {width}x{height}"
    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_width <= width, f"the page scrolls sideways at {width}x{height}"


@pytest.mark.parametrize("width, height", [(1440, 900), (1100, 760), (820, 1000)])
def test_the_forty_mile_ring_fits_the_shorter_side_of_the_radar(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(300)
    box = page.eval_on_selector("#radar", "e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }")
    size = page.eval_on_selector("#radar", "e => [e.width / devicePixelRatio, e.height / devicePixelRatio]")
    assert abs(box[0] - size[0]) <= 1 and abs(box[1] - size[1]) <= 1, "the canvas does not fill its pane"


def test_no_label_carries_a_key_hint(page):
    text = page.inner_text("body")
    assert not re.search(r"\[[A-Z/]{1,6}\]", text), "a bracketed key hint is on the page"
    assert "AMBIENT" not in text.upper()


# -- the feed stack ------------------------------------------------------------


def test_clicking_a_compact_row_unmutes_it_and_m_mutes_it_again(page):
    assert "ATIS" not in feed_names(page, "expanded")
    page.click(".feed.compact:has-text('ATIS')")
    page.wait_for_selector(".feed.expanded:has-text('ATIS')")
    page.click(".feed.expanded:has-text('ATIS') button:text-is('M')")
    page.wait_for_selector(".feed.compact:has-text('ATIS')")
    assert "ATIS" not in feed_names(page, "expanded")


def test_s_solos_and_lights(page):
    solo = ".feed.expanded:has-text('Tower') button:text-is('S')"
    page.click(solo)
    page.wait_for_selector(f"{solo}[aria-pressed=true]")
    page.click(solo)
    page.wait_for_selector(f"{solo}[aria-pressed=false]")


def test_the_trace_draws(page):
    page.wait_for_timeout(1500)
    lit = page.eval_on_selector(
        ".feed.expanded .trace",
        "c => { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;"
        " let n = 0; for (let i = 3; i < d.length; i += 4) n += d[i] > 0; return n; }",
    )
    assert lit > 50


# -- sheets --------------------------------------------------------------------


def test_the_feed_picker_adds_a_feed(page):
    page.click("#open-feeds")
    page.wait_for_selector("#feeds-results .choice")
    page.click("#feeds-results .choice:has-text('GUARD')")
    page.wait_for_selector(".feed:has-text('Emergency Guard')")
    page.click("#open-feeds")
    page.wait_for_selector("#feeds-results .choice:has-text('GUARD') .tag.on")


def test_changing_airport_redraws_everything(page):
    page.click("#open-airport")
    page.fill("#airport-query", "seattle")
    page.click("#airport-results .choice:has-text('KSEA')")
    page.wait_for_function("document.getElementById('icao').textContent === 'KSEA'")
    page.wait_for_selector(".feed.expanded")
    assert page.title() == "KCGX KSEA"
    page.click("#open-airport")
    page.fill("#airport-query", "KPDX")
    page.click("#airport-results .choice:has-text('KPDX')")
    page.wait_for_function("document.getElementById('icao').textContent === 'KPDX'")


def test_prefs_apply_to_every_tab(page, browser, server):
    other = browser.new_page()
    other.goto(server + "/")
    other.wait_for_selector(".feed.expanded")
    page.click("#next-palette")
    other.wait_for_function("document.documentElement.dataset.palette === 'AMBER'")
    page.click("#open-config")
    page.click(".segments[data-pref=display] button:text-is('VECTOR')")
    other.wait_for_function("document.documentElement.dataset.display === 'VECTOR'")
    page.click(".segments[data-pref=display] button:text-is('CRT')")
    page.click(".segments[data-pref=palette] button:text-is('WOPR')")
    other.wait_for_function("document.documentElement.dataset.palette === 'WOPR'")
    assert other.get_attribute("html", "data-display") == "CRT"
    other.close()


def test_the_volume_slider_reaches_the_server(page):
    page.click("#open-config")
    page.fill("#volume", "40")
    page.dispatch_event("#volume", "input")
    page.wait_for_function("document.getElementById('freq-counts').textContent.includes('VOL 40%')")
    page.fill("#volume", "100")
    page.dispatch_event("#volume", "input")
    page.wait_for_function("document.getElementById('freq-counts').textContent.includes('VOL 100%')")
```

- [ ] **Step 2:** `uv run pytest -q tests/test_page.py`: 16 passed in about
  12 s. Without the browser group it reports one skipped module.
  Suite: **930 passed**.
- [ ] **Step 3:** Commit `test(web): the page in a browser`.

---

### Task 9: By hand, on the Mac

- [ ] `uv run kcgx-web --demo`. Open it at full width and compare with the
  mockup: the wall, the lamp bar, the screen titles along the bottoms, the
  CRT layer on. Resize from wide to a phone width: nothing overlaps, the
  radar rings stay round and the 40 nm ring fits the shorter side.
- [ ] Click a compact row: it expands and is heard (in demo, it just
  expands). M mutes it, S solos and lights pink, S again restores.
- [ ] PALETTE cycles WOPR, AMBER, MATRIX, MONO, and a second tab follows.
  CONFIG: glow and display change at once; volume follows the slider.
  Restart the server (not `--demo`): the palette comes back.
- [ ] CHANGE AIRPORT, type `seattle`, pick KSEA: everything redraws.
- [ ] Stop the terminal cockpit (`kcgx stop` in `/Users/mikelse/kcgx`), then
  `uv run kcgx-web` for real: Tower audible, levels in step with what is
  heard, FEEDS opens a feed that was not open and it plays.
- [ ] Turn the Mac's output device off or unplug headphones before starting
  with none: the banner and the red AUDIO lamp say so.
- [ ] SHUT DOWN, confirm: the page says COCKPIT SHUT DOWN and the command
  exits 0.

Anything that fails here is a bug in this phase.

---

### Task 10: Documentation

- [ ] **Step 1:** In `docs/README.md`, phase C links this plan and is marked built.
- [ ] **Step 2:** Add an Execution record section to this plan.
- [ ] **Step 3:** Commit `docs: phase C done`.

---

## Execution record

Built 2026-10-19 on `feat/web-cockpit`, one commit per task (9090681 to
ec3f173), from the dry-run files; before any change, every file the plan
modifies matched the dry run's base byte for byte. On the branch, without
the browser group: 914 passed, `test_page.py` skipped. The browser tests
passed (16) against the same files in the cloud sandbox; the Mac's sandbox
could not download Chromium, so their first run on the branch is Task 9.
On the Mac the full suite passed after one fix outside this phase: the
launcher's no-terminal test assumed pytest had no terminal, and failed
when run from one (409f8f4 makes it run the launcher with none). Task 9,
2026-10-19: the owner ran the page with `--demo` and for real, and
confirmed every check passes.

## Self-Review Notes

- **Dry run, 2026-10-19.** Every file and diff above was built in a scratch
  copy of the branch and run before this plan was written; the plan is
  generated from those files. Full suite **929 passed, 1 skipped** in a
  Linux sandbox, where the one skip is the existing `test_setup.py` case that
  cannot run as root (on the Mac it runs: 930). The five PortAudio tests ran
  against a stand-in `sounddevice`, as in phase B. `kcgx-web --demo` was
  served by uvicorn and driven by Playwright and Chromium 141 at 1440 by 900,
  1280 by 720, 1100 by 760, 820 by 1000 and 390 by 844, with screenshots
  compared against the mockup.
- **What the dry run caught.** The hidden banner dropped out of the page
  grid and every row moved up one, squashing the radar to 86 px: the rows
  are now named grid areas. The radar drew a negative radius in a pane of
  zero height. Lit lamps had no colour because `--lamp` was never defined,
  and then followed mute rather than the spec's state colours. The volume
  row stacked vertically because `.field` and `.field-row` disagreed. The
  JS used class names the stylesheet did not have for choices, the log and
  the lamps. All fixed in the files above.
- **Revert checks, all run, each failing its named test:**

| Break | Test | Result |
|---|---|---|
| remove `grid-template-areas` from `.page` | `test_page.py -k overlap` | 5 failed |
| drop `NO_CACHE` from `_Static` | `test_server.py -k static` | 3 failed |
| label M as `[M]` | `test_page.py -k key_hint` | 1 failed |
| `set_prefs` stops remembering | `test_station.py -k prefs` | 1 failed |
| `--demo` keeps the real `remember_prefs` | `test_server.py -k demo` | 1 failed |
| prefs names compared case-blind | `test_protocol.py -k refused` | 1 failed |
| S sends `mute` | `test_page.py -k solo` | 1 failed |
| prefs not applied to `<html>` | `test_page.py -k every_tab` | 1 failed |
| the retry hint passed through unchanged | `test_station.py -k retry_hint` | 1 failed |

- **Lint.** `ruff check` on every touched file reports one finding fewer
  than on the branch before this plan.
- **Not in this phase, on purpose:** aircraft, the map, the tracks table's
  rows, the emergency lamp (D); the launcher and opening a browser (E).
- **Test count:** 871 → 871 (T1) → 879 (T2) → 888 (T3) → 892 (T4) → 904
  (T5) → 904 (T6) → 914 (T7) → 930 (T8).
