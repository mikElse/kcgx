# Web Cockpit Phase F: The 11/12 Tweaks, and Its Own Window

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the owner's 2026-11-12 tweak list to the browser cockpit: a
denser page, a slimmer header, a config sheet that owns every look and radar
setting, a radar that zooms to 2.5 nm and ranges to 250, boxed labels,
configurable flight tags, a teletype and lamp bar that are off unless asked
for. Then make `kcgx` open the cockpit in its own window (a small WebKit
app) instead of a Chrome tab.

**Source:** "KCGX Tweaks 11/12" (the owner, 2026-11-12), plus the same day's
follow up: "launch in its own dedicated browser/wrapper that isn't Chrome".
Every line of the list is mapped to a task in [Coverage](#coverage).

**Architecture:**

| Piece | Job |
|---|---|
| `kcgx.prefs` | one typed schema (choice, flag, number, subset) for every setting; the file, the protocol and the page are all checked against it |
| `kcgx.protocol`, `kcgx.station` | `prefs` messages validated by the schema; a `range_nm` change reaches the radar poller |
| `kcgx.radar`, `kcgx.geodata` | the range is live (10 to 250 nm); the map is clipped at 320 nm |
| `index.html`, `cockpit.css` | one page grid with named areas, switched by `data-lamps` and `data-teletype`; spacing tokens; icon buttons |
| `sheets.js` | the config sheet, built from `data-pref` controls; the feeds sheet goes |
| `radar.js` | view held in nm, not a zoom factor; computed rings; flight tags; label boxes |
| `tracks.js`, `stack.js` | focused row pinned and enlarged; smaller chatter and M/S |
| `macos/KCGXWindow.swift` | `KCGX.app`: one WKWebView window on the local server |
| `kcgx.launcher`, `setup.sh` | open the app when it is built, the default browser otherwise; step 5 builds it |

**Tech Stack:** as phase E. No new Python dependency. The window is one
Swift file compiled by `swiftc` (Xcode command line tools, which Homebrew
already requires on a Mac). Playwright's WebKit joins Chromium in the
`browser` test group.

**Spec:** `docs/superpowers/specs/2026-10-18-web-cockpit-design.md`. This
plan changes "Visual language", "Themes", "Display effects", "Rendering",
"Every action is a click", "The launcher" and "Install changes"; Task 13
writes the changes into the spec.

## What was checked before writing this

- **adsb.lol's radius cap is 250 nm.** Its OpenAPI document
  (`https://api.adsb.lol/api/openapi.json`, read 2026-11-12) gives
  `/v2/point/{lat}/{lon}/{radius}` a `maximum` of 250 and the summary
  "Aircrafts surrounding a point (lat, lon) up to 250nm". That is "the
  maximum possible value" for the range setting.
- **The map can cover it cheaply.** Clipped at 320 nm instead of 200, the
  map is 0.11 MB (KPDX), 0.22 MB (KJFK) and 0.30 MB (EGLL) of JSON, clipped
  in under 0.1 s. One radius for every airport; no tiers.
- **A black fill does nothing on the radar as it is drawn today.** The
  static layer draws with `globalCompositeOperation = "lighter"`
  (`radar.js:177`) and the moving layer is added to the screen the same way
  (`radar.js:488`). Label boxes must be painted `source-over`; see Task 8.
- **Every feed an airport publishes already opens at launch**
  (`runtime.load_feeds`, `build_sessions`). The FEEDS sheet only matters
  when the listing could not be fetched; choosing the airport again
  (`Station.change_airport`) refetches it.
- **Nothing reads `protocol.PROTOCOL` but the health reply**, so the new
  pref keys are additive and the number stays 1.
- **Not checked:** whether WebKit honours `ctx.letterSpacing` on a canvas
  (`radar.js:264`, `:289`, `:362`, `:445`). Task 10 finds out; the radar must
  measure and draw consistently either way. *Task 10, 2026-11-12:* it
  does, and measures with it.

## Decisions this plan makes that the list did not

Each is the plan's reading of an ambiguous line, or a consequence of one.
The first four are the ones most worth the owner's eye before work starts.

1. **"Control the radar's range to the maximum possible value" is a range
   slider, 10 to 250 nm in 10 nm steps**, default 40. It is a pref, changed
   live from CONFIG and remembered. `radar_range_nm` leaves `squelch.toml`
   (an old file that sets it still loads; unknown keys are ignored). A
   change applies to the next scheduled poll and never triggers one: a
   dragged slider must not become a burst against adsb.lol's 15 s ask.
   Shrinking the range drops the aircraft beyond it at once.
2. **"Remove feeds" removes the button and its sheet from the page; the
   server keeps `/api/feeds/available` and `open_feed`**, which `/debug`
   still drives. When a launch falls back to one feed, the log's hint
   becomes "choose the airport again to retry".
3. **With RECENTRE gone, a double click on the radar recentres it.**
   Without one there is no way back from a pan short of changing airport.
4. **Hiding the teletype must not hide errors.** While it is hidden, a
   page error (airport search failed, a refused message, shut down failed)
   shows in the banner for 8 s. Server notes are still collected, so
   turning the teletype on shows the history.
5. **The lamp bar sits under the radar, at the radar's width**, when shown.
   It can no longer span the page, because the frequencies pane now runs
   the full height of the right column.
6. **Zoom is held in nautical miles.** The view is "N nm from the centre to
   the nearer edge", from 2.5 up to `max(160, range)`. Range rings are
   computed (a 1, 2, 5 step chosen so three to five show) instead of the
   fixed 10/20/30/40. The home ring is capped at 64 px so it does not fill
   the screen at 2.5 nm.
7. **The focused aircraft pins to the top of the tracks table however it
   was focused** (a click on the radar or on its callsign): there is one
   focus. Sorting orders the rest beneath it.
8. **Flight tags are two lines once more than two fields are chosen:**
   identity (callsign, type, squawk) over numbers (altitude, ground speed,
   track, distance). The default, callsign and altitude, is the one line
   drawn today. No fields chosen means no tag.
9. **Label boxes are off by default** (no items selected). The items are
   AIRCRAFT, HOME, AIRPORTS, NAVAIDS, CITIES, PEAKS, STATES, RINGS and HUD.
   The border takes the text's colour; the fill is black. Placement
   reserves the box, not just the text, so two boxes never overlap.
10. **The config sheet docks to the right edge with a clear backdrop**, so
    scanlines, boxes and range can be seen changing while they are set.
11. **"Theme" is the palette.** The row is labelled THEME and is a
    `<select>`. Glow and display stay as segments.
12. **Scanline size is the pitch in px (2 to 8, default 3); the dark line
    is a third of it.** Opacity is 0 to 100 %, default 34. Both apply only
    with display CRT and are disabled otherwise.
13. **Icons are our own inline SVG line drawings** (search, gear, power):
    no icon font, no licence to carry, and they take the palette through
    `currentColor`. Each button keeps its id, an `aria-label` and a `title`.
14. **The window is a native WKWebView app on macOS; Linux keeps the
    default browser.** See Task 12 for what was weighed.
15. **In the window, the red close button hides it and the audio plays on;
    Quit (and the power icon) stops the cockpit.** That is how a Mac audio
    app behaves, and it gives "keep listening" and "stop" one gesture each.

## Global Constraints

- Work in the `feat/web-cockpit` worktree at `/Users/mikelse/kcgx_web`.
- **No new Python dependency.**
- **No test touches the network, ffmpeg or an audio device**, and none
  writes to `~/.local/state/kcgx/`, `~/.cache/squelch/` or
  `~/Applications/`: servers are `--demo` on free ports with
  `KCGX_STATE_PATH` set, and the app path comes from `KCGX_APP`.
- **Tests first** in every task: write the failing test, see it fail, make
  it pass, run the whole suite (`uv run pytest`), commit.
- **The page changes nothing itself.** Every setting is a `prefs` message;
  the page redraws from the server's `prefs` frame, so every tab agrees.
- **Ids that tests and `kcgx go` rely on stay:** `#open-airport`,
  `#open-config`, `#open-shutdown`, `#airport-sheet`, `#airport-query`,
  `#airport-results`, `#radar`, `#tracks-body`, `#tracks-head`, `#icao`,
  `#freq-counts`, `#volume`.
- One commit per task, in the repo's style (`feat(web): ...`,
  `feat(radar): ...`, `docs: ...`).

## File Structure

```
src/kcgx/prefs.py                 rewritten: the schema
src/kcgx/protocol.py              _prefs validates by schema
src/kcgx/station.py               range from prefs; set_prefs retunes the radar; the retry hint
src/kcgx/radar.py                 Radar.set_range
src/kcgx/geodata.py               DEFAULT_RADIUS_NM 200 -> 320
src/squelch/config.py             radar_range_nm removed
src/kcgx/launcher.py              pick_opener, --browser
src/kcgx/web/index.html           flat grid, icon buttons, config sheet, no feeds sheet
src/kcgx/web/static/cockpit.css   grid areas, tokens, density, icons, boxes for the HUD
src/kcgx/web/static/js/main.js    applyPrefs, wiring, banner errors
src/kcgx/web/static/js/sheets.js  config sheet by data-pref; feeds sheet removed
src/kcgx/web/static/js/store.js   default prefs
src/kcgx/web/static/js/radar.js   view in nm, rings, tags, boxes, double click
src/kcgx/web/static/js/tracks.js  focused row first
src/kcgx/web/static/js/stack.js   chatter %, show() removed
macos/KCGXWindow.swift            new: the window
macos/Info.plist.in               new: bundle metadata, the kcgx:// scheme
macos/build.sh                    new: swiftc, bundle, ad hoc sign
setup.sh                          step 5 also builds the window (macOS)
tests/test_prefs.py, test_protocol.py, test_station.py, test_radar.py,
tests/test_config.py, test_geodata.py, test_launcher.py, test_setup.py   updated
tests/test_page.py                updated, and run in WebKit too
tests/test_page_prefs.py          new: index.html's controls agree with the schema (no browser)
README.md, docs/superpowers/specs/2026-10-18-web-cockpit-design.md   Task 13
```

## The settings

The whole schema, as Task 1 writes it. Names on the wire are exact; flags
are JSON booleans, numbers are integers, subsets are lists in schema order.

| key | kind | values | default | CONFIG row |
|---|---|---|---|---|
| `palette` | choice | WOPR, AMBER, MATRIX, MONO | WOPR | THEME (dropdown) |
| `glow` | choice | OFF, LOW, FULL | LOW | GLOW |
| `display` | choice | OFF, VECTOR, CRT | CRT | DISPLAY |
| `scan_opacity` | number | 0 to 100 (%) | 34 | SCANLINE OPACITY |
| `scan_size` | number | 2 to 8 (px) | 3 | SCANLINE SIZE |
| `lamps` | flag | | false | STATUS LAMPS |
| `teletype` | flag | | false | TELETYPE |
| `range_nm` | number | 10 to 250 | 40 | RANGE (step 10) |
| `tag_fields` | subset | CALLSIGN, TYPE, SQWK, ALT, GS, TRK, DIST | CALLSIGN, ALT | FLIGHT TAG |
| `box_items` | subset | AIRCRAFT, HOME, AIRPORTS, NAVAIDS, CITIES, PEAKS, STATES, RINGS, HUD | none | LABEL BOXES |
| `box_fill` | number | 0 to 100 (%) | 70 | BOX FILL |
| `box_pad` | number | 0 to 12 (px) | 4 | BOX PADDING |
| `box_border` | number | 0 to 100 (%) | 50 | BOX BORDER |
| `box_width` | number | 1 to 5 (px) | 1 | BORDER WIDTH |

CONFIG's sections, top to bottom: OUTPUT (master volume), LOOK (theme,
glow, display, scanline opacity, scanline size), LAYOUT (status lamps,
teletype), RADAR (range, flight tag, label boxes, box fill, box padding,
box border, border width). LIMITS is gone.

---

# Part 1: the tweaks

### Task 1: The prefs schema

**Files:** `src/kcgx/prefs.py`, `src/kcgx/protocol.py`,
`tests/test_prefs.py`, `tests/test_protocol.py`, `tests/test_station.py`,
`tests/test_server.py`

- [x] **Tests first.** In `test_prefs.py`: the defaults are the table
  above; a stored flag, number and subset read back; a number out of range,
  a bool where a number is wanted (`true` is not `1`), a float, a subset
  with an unknown name, and a subset that is not a list each fall back to
  that key's default without disturbing the others; a subset is stored
  de-duplicated in schema order; an empty subset is kept (it is a real
  choice, not a missing one). In `test_protocol.py`: each kind parses; each
  bad shape raises `BadMessage` naming the key; `{"t":"prefs"}` and an
  unknown key (`theme`) are still refused. Replace the exact three key
  dicts in `test_prefs.py`, `test_station.py:334-350` and
  `test_protocol.py:99-109` with `{**DEFAULTS, ...}`.
- [x] **The schema.** Four small frozen dataclasses, each with
  `check(value)` that returns the canonical value or raises `ValueError`:

  ```python
  @dataclass(frozen=True)
  class Choice:
      names: tuple[str, ...]
      default: str
      def check(self, value):
          if isinstance(value, str) and value in self.names:
              return value
          raise ValueError(f"must be one of {', '.join(self.names)}")

  @dataclass(frozen=True)
  class Flag:
      default: bool
      def check(self, value):
          if isinstance(value, bool):
              return value
          raise ValueError("must be true or false")

  @dataclass(frozen=True)
  class Number:
      low: int
      high: int
      default: int
      def check(self, value):
          if isinstance(value, bool) or not isinstance(value, int) or not self.low <= value <= self.high:
              raise ValueError(f"must be a whole number from {self.low} to {self.high}")
          return value

  @dataclass(frozen=True)
  class Subset:
      names: tuple[str, ...]
      default: tuple[str, ...]
      def check(self, value):
          if not isinstance(value, list) or any(v not in self.names for v in value):
              raise ValueError(f"must be a list drawn from {', '.join(self.names)}")
          return [n for n in self.names if n in value]
  ```

  `SCHEMA: dict[str, Choice | Flag | Number | Subset]` is the table above.
  `DEFAULTS` is derived from it (subset defaults as lists). `CHOICES` stays
  exported for anything that imports it.
- [x] **`clean()` stays lenient, `protocol._prefs` stays strict**, and both
  call `check`. `clean` keeps its one kindness: a stored choice in lower
  case is upper cased before checking (`test_prefs.py:23`). `_prefs` turns
  `ValueError` into `BadMessage(f"{key} {reason}")`.
- [x] `store.js`: the default `prefs` object matches `DEFAULTS`.
- [x] Run the suite; commit `feat(prefs): one schema for every setting`.

### Task 2: The range is live, up to 250 nm

**Files:** `src/kcgx/radar.py`, `src/kcgx/station.py`,
`src/kcgx/geodata.py`, `src/squelch/config.py`, `src/kcgx/demo.py`,
`tests/test_radar.py`, `tests/test_station.py`, `tests/test_config.py`,
`tests/test_geodata.py`

- [x] **Tests first.** `Radar.set_range(20)` sets `range_nm`, drops tracks
  whose distance is over 20, sends one frame whose `range` is 20, and does
  not set the wake event (assert `fetch` is not called again before the
  delay). The next `poll` asks `fetch` for 20. A station built with
  `prefs={"range_nm": 120}` gives its radar 120; `handle({"t": "prefs",
  "range_nm": 250})` retunes it; a prefs change that does not touch
  `range_nm` sends no aircraft frame. `Config()` has no `radar_range_nm`,
  and a TOML file that sets it still loads. `geodata.clip` defaults to 320.
- [x] `Radar.set_range`; `Station.__init__` reads `self.prefs["range_nm"]`;
  `Station.set_prefs` calls `set_range` when the value changed.
- [x] Remove `radar_range_nm` from `Config` and its comment; fix the
  comment on `DEFAULT_RADIUS_NM` (250 nm range, with margin to pan).
- [x] `demo.traffic` ignores its `range_nm` today, so the demo shows the
  same eleven aircraft at any range. Have it drop legs that start beyond
  the range, so shrinking the range visibly thins the demo.
- [x] Commit `feat(radar): the range is a setting, 10 to 250 nm`.

**Risk to watch, not solve here:** 250 nm around a busy field can be
several hundred aircraft. The page redraws every one each frame and
rebuilds the table every poll. Task 7 measures it (step there); if a frame
takes over 16 ms the fix is to skip tags below a density threshold, which
is its own change.

### Task 3: One grid; lamps and teletype off by default

**Files:** `index.html`, `cockpit.css`, `main.js`, `tests/test_page.py`

- [x] **Tests first** (browser). By default four screens show (Radar,
  Airport, Frequencies, Tracks), `#lamps` and the teletype are not
  displayed, and the frequencies pane's bottom edge is level with the
  tracks pane's (within 1 px) at every size in `SIZES` wider than 1100.
  With `teletype` on, five screens show and the teletype sits under
  frequencies, level with tracks. With `lamps` on, the bar sits between
  radar and tracks and is no wider than the radar. The no-overlap test
  runs in all four combinations. Set prefs in tests by sending the message
  through the page's own socket: expose `send` beside `store` on
  `window.kcgx`.
- [x] **Flatten the page.** `.toprow`, `.column` and `.bottomrow` go; the
  eight parts become children of `.page`, placed by name:

  ```css
  .page {
    height: 100vh; min-height: 640px; padding: var(--page-pad);
    display: grid; column-gap: var(--gap);
    grid-template-columns: minmax(0, 1fr) minmax(320px, 380px);
    grid-template-rows: auto auto auto minmax(240px, 1fr) auto minmax(160px, 24vh);
    grid-template-areas:
      "bar bar" "banner banner"
      "radar status" "radar freq" "lamps freq" "tracks freq";
  }
  [data-teletype="ON"] .page { grid-template-areas:
      "bar bar" "banner banner"
      "radar status" "radar freq" "lamps freq" "tracks log"; }
  .lamps, .screen-log { display: none; }
  [data-lamps="ON"] .lamps { display: flex; }
  [data-teletype="ON"] .screen-log { display: flex; }
  @media (max-width: 1100px) {
    .page, [data-teletype="ON"] .page { height: auto; grid-template-columns: minmax(0, 1fr);
      grid-template-rows: none; grid-auto-rows: auto;
      grid-template-areas: "bar" "banner" "radar" "status" "freq" "lamps" "tracks" "log"; }
  }
  ```

  Rows are still spaced by `margin-top` on each part, as the comment at
  `cockpit.css:50` explains, so a hidden part costs nothing.
- [x] `<html>` gains `data-lamps="OFF" data-teletype="OFF"` so the first
  paint is the default layout. `applyPrefs` sets both from the prefs.
- [x] The flicker offsets at `cockpit.css:253-254` name panes instead of
  positions (`.screen-freq`, `.screen-tracks`).
- [x] `mountLog` still runs while hidden. In `main.js`, a `message` with
  `page: true`, or one `log.say` raises, shows in the banner for 8 s when
  `prefs.teletype` is false (decision 4). Test:
  `window.kcgx.store.apply({t: "error", text: "x"})` puts "ERROR: X" in
  the banner with the teletype off, and leaves the banner alone with it on.
- [x] Commit `feat(web): one grid; lamps and teletype are settings`.

### Task 4: The header and the airport pane

**Files:** `index.html`, `cockpit.css`, `main.js`, `sheets.js`,
`stack.js`, `station.py`, `setup.sh`, `tests/test_page.py`,
`tests/test_station.py`, `tests/test_setup.py`

- [x] **Tests first.** `#open-feeds`, `#next-palette`, `#feeds-sheet` and
  `#recentre` are not in the page. `#open-config` and `#open-shutdown`
  have no visible text, a computed `border-top-width` of `0px`, and an
  accessible name ("Config", "Shut down"). The airport pane has no
  `.screen-title`; `#open-airport` is an icon whose right edge is at the
  pane's inner right edge and whose bottom is level with the bottom of the
  airport's name block (within 2 px). Delete
  `test_the_feed_picker_adds_a_feed`. `test_station`: the fallback note
  reads "choose the airport again to retry".
- [x] **Header:** remove FEEDS and PALETTE; CONFIG becomes the gear,
  SHUT DOWN the power icon (in `--alarm`).

  ```css
  .icon-btn { display: inline-grid; place-items: center; width: 30px; height: 30px; padding: 0;
    background: none; border: 0; color: var(--text); cursor: pointer; }
  .icon-btn:hover { color: var(--white); }
  .icon-btn:focus-visible { outline: 2px solid var(--pink); outline-offset: 2px; }
  .icon-btn svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.6;
    stroke-linecap: round; stroke-linejoin: round; }
  .icon-alarm { color: var(--alarm); }
  ```

- [x] **Airport pane:** ICAO and clocks on top as now; beneath, the name
  and place on the left and the search icon bottom right. The STATUS title
  bar goes; the section's `aria-label` becomes "Airport".

  ```html
  <div class="status-bottom">
    <div class="status-names">
      <span class="airport-name" id="airport-name"></span>
      <span class="muted small" id="airport-where"></span>
    </div>
    <button type="button" class="icon-btn" id="open-airport" aria-label="Search airports" title="Search airports">…svg…</button>
  </div>
  ```

  `.status-bottom { display: flex; justify-content: space-between; align-items: flex-end; gap: var(--gap); }`
- [x] Remove `mountFeedsSheet`, the feeds `<dialog>`, `stack.show`, the
  `.feed.flash` rule and `.choice .tag`. Remove `$("palette-name")` from
  `applyPrefs`. The server's feeds endpoint and `open_feed` stay.
- [x] `station._for_the_page` (`station.py:292`) and `setup.sh:517` stop
  saying "open FEEDS".
- [x] Commit `feat(web): icons in the header; the airport pane loses its title`.

### Task 5: The config sheet

**Files:** `index.html`, `sheets.js`, `main.js`, `cockpit.css`,
`tests/test_page_prefs.py` (new), `tests/test_page.py`

- [x] **Tests first.** `test_page_prefs.py` needs no browser: it parses
  `index.html` with `html.parser` and asserts that every key in
  `prefs.SCHEMA` has exactly one `[data-pref]` control, that a number's
  `min`/`max` equal the schema's, and that a choice's or subset's option
  values equal the schema's names in order. This is what stops the page
  and the server drifting, in place of the `CHOICES` copy in `sheets.js`.
  Browser: choosing AMBER in the THEME `<select>` reaches a second tab
  (rewrite `test_prefs_apply_to_every_tab` around it); each number slider
  and each subset button round trips to the second tab's
  `window.kcgx.store.state.prefs`; `#max-streams` and "LIMITS" are gone;
  scanline controls are disabled unless display is CRT; with the sheet
  open, a pixel of the radar is not darkened by a backdrop.
- [x] **Controls are declared in the HTML and bound generically:**

  ```html
  <label class="field-row"><span>THEME</span>
    <select data-pref="palette"><option>WOPR</option><option>AMBER</option><option>MATRIX</option><option>MONO</option></select></label>
  <label class="field-row"><span>SCANLINE OPACITY</span>
    <input type="range" data-pref="scan_opacity" min="0" max="100" step="1"><span class="num" data-unit="%"></span></label>
  <div class="field-row" role="group" aria-label="Flight tag"><span>FLIGHT TAG</span>
    <div class="segments" data-pref="tag_fields" data-kind="subset" data-values="CALLSIGN TYPE SQWK ALT GS TRK DIST"></div></div>
  <div class="field-row" role="group" aria-label="Teletype"><span>TELETYPE</span>
    <div class="segments" data-pref="teletype" data-kind="flag"></div></div>
  ```

  `mountConfigSheet` walks `[data-pref]`: a `<select>` sends on `change`;
  a range sends on `input`, debounced 80 ms, and is not overwritten by a
  `prefs` frame while it is the active element (as the volume slider is
  not, `sheets.js:151`); a `choice` segment group is one pressed button; a
  `flag` group is OFF/ON; a `subset` group toggles each button and sends
  the whole list.
- [x] **Docked, clear backdrop** (decision 10):
  `#config-sheet { margin: 0 0 0 auto; height: 100vh; max-height: none; width: min(420px, 100vw); }`
  and `#config-sheet::backdrop { background: transparent; }`.
- [x] **Scanlines:**

  ```css
  :root { --scan-alpha: 0.34; --scan-size: 3px; --scan-line: 1px; }
  [data-display="CRT"] .ovl { display: block; background:
    repeating-linear-gradient(to bottom, rgb(0 0 0 / var(--scan-alpha)) 0 var(--scan-line),
      transparent var(--scan-line) var(--scan-size)),
    radial-gradient(ellipse at center, transparent 52%, rgba(0, 0, 0, 0.42) 100%); }
  ```

  `applyPrefs` sets the three properties: alpha `scan_opacity / 100`, size
  `scan_size` px, line `max(1, round(scan_size / 3))` px.
- [x] The radar HUD's "RNG 40 NM" (`index.html:33`) is written from
  `prefs.range_nm`.
- [x] Commit `feat(web): config owns every setting`.

### Task 6: Density, frequencies and tracks

**Files:** `cockpit.css`, `stack.js`, `tracks.js`, `tests/test_page.py`

- [x] **Tests first.** Chatter reads `NN%` in an expanded and a compact
  row; `.chatter-big`'s computed font size is under 20 px; an M button is
  no taller than 26 px. Focusing an aircraft on the radar makes its row
  the first in `#tracks-body`, with every cell's computed font size 1.2
  times a neighbour's (within 0.1 px); clicking a sort header leaves it
  first and sorts the rest; unfocusing returns it to its sorted place.
  `test_no_two_screens_overlap` still passes at every size.
- [x] **Spacing tokens**, used everywhere a literal is today:

  ```css
  :root { --gap: 10px; --page-pad: 10px 12px 12px; --pad-x: 10px; --pad-y: 6px; }
  ```

  | rule | now | after |
  |---|---|---|
  | `.page` padding; gaps between screens | 16/20/20; 14 | 10/12/12; 10 |
  | `body` line height | 1.4 | 1.3 |
  | `.btn`; `.btn-small` | 40 high, 0 14; 32, 0 10 | 30, 0 10; 26, 0 8 |
  | `.screen-title` | 8 16 | 4 10 |
  | `.status-body` | 16 18 14, gap 10 | 10 12 8, gap 6 |
  | `.freq-counts` | 12 16 6 | 6 10 4 |
  | `.stack`; `.feed.expanded` | 6 12 12, gap 6; 10 12 8, gap 6 | 4 8 8, gap 4; 6 8 6, gap 4 |
  | `.feed.compact` | 44 high, 0 12 | 32, 0 8 |
  | `.feed-controls .btn` (M, S) | 34 by 44 | 24 by 28 |
  | `.tracks-body`; `th`; `td` | 8 12 4; 6 8; 5 8 | 4 8 2; 3 6; 2 6 |
  | `.log` | 12 16, gap 8 | 8 10, gap 4 |
  | `.lamps` | 10 16 | 6 10 |
  | `.hud` | top 14, sides 18 | top 8, sides 10 |
  | `.sheet`; `.choice` | 18 20; 40 high, 6 10 | 12 14; 32, 4 8 |

  These are starting values. Finish by eye: screenshot the demo at each
  size in `SIZES`, with the teletype and lamps on and off, and adjust.
  Font sizes do not change here except the two chatter figures.
- [x] **Chatter:** `.chatter-big` 30 px to 18 px, `.chatter-small` 18 to
  14; both `min-width: 4ch; text-align: right`. The text is
  `` `${Math.round(fraction * 100)}%` `` in both shapes (no zero padding
  now that the sign makes it a number).
- [x] **Tracks:** in `render()`, after sorting, move the focused aircraft
  to index 0. `.tracks tr.focused td { font-size: 1.2em; }` (the callsign
  button inherits it). On focus, set `.tracks-body`'s `scrollTop` to 0 in
  place of `scrollIntoView` (`tracks.js:90`).
- [x] Commit `feat(web): a denser page; the focused track leads the table`.

### Task 7: The radar's view: 2.5 nm, computed rings, no button

**Files:** `radar.js`, `index.html`, `main.js`, `tests/test_page.py`

- [x] **Tests first.** The wheel zooms in until `debug().view.nm` is 2.5
  and no further, and out to `max(160, range)`. With range 40 and the view
  untouched, the 40 nm ring's radius on screen is the shorter half side
  less 18 px (the old fit, now asserted). At a 2.5 nm view at least two
  rings are on screen. Setting range 120 resets the view to 120 and draws
  a ring at 120. A double click after a pan and zoom returns the view to
  `{nm: range, panX: 0, panY: 0}` (rewrite
  `test_the_wheel_zooms_dragging_pans_and_recentre_resets`).
- [x] **View in nm.** `view = { nm, panX, panY }`; `nm` starts at, and
  resets to, `prefs.range_nm`.
  `scale = (min(width, height) / 2 - 18 * ratio) / view.nm`. The wheel
  divides `nm` by the factor and clamps to `[2.5, max(160, range)]`.
  `RANGE_NM`, `RINGS_NM`, `ZOOM_MIN` and `ZOOM_MAX` go. Small airports
  show when `view.nm <= 27` (the old `zoom >= 1.5` at 40 nm).
- [x] **Rings.** `step` is the first of 0.5, 1, 2, 5, 10, 20, 50 with
  `view.nm / step <= 5`. Draw every multiple of `step` up to the range
  that is within the visible radius, dim; then the range ring itself,
  bright, whether or not it is a multiple. Numbers read `2.5`, not `2.50`.
- [x] **Home ring** is `clamp(2.5 nm on screen, 24 px, 64 px)`, so the
  airport's name stays beside it at any zoom.
- [x] **Double click recentres**; the RECENTRE button and its listener go.
  The bearing and distance readout in the title bar stays. `debug().view`
  reports `nm`; `radar.recentre()` stays for tests.
- [x] A range change (a `prefs` frame with a new `range_nm`) resets the
  view and marks the static layer dirty.
- [x] **Measure 250 nm.** With the demo unable to fill it, inject a 600
  aircraft frame through `window.kcgx.store.apply` and read the frame time
  in the Performance panel. Record the number in the commit message. Over
  16 ms: open a follow up, do not fix it here.
  **Measured 2026-11-12, headless Chromium under Playwright (no
  Performance panel), 1440 by 900, canvas 1024 by 588, range and view 250,
  600 aircraft each with a full 12 point trail, glow LOW, display CRT:
  34.7 ms a frame at 1x (the radar's frame callback 32.0 ms of it) and
  66.3 ms at 2x, against 16.7 ms and 0.8 ms with the demo's eleven. Over 16 ms.
  Follow up, not done here:** the cost is the glow (with glow OFF the same
  picture holds 16.7 ms at 1x: callback 13 ms) and the trails (one point
  each, glow LOW: callback 12 ms). Each trail segment is its own stroke
  with a shadow, 6600 a frame, and every aircraft is drawn whether or not
  it is on screen.
- [x] Commit `feat(radar): zoom to 2.5 nm, rings by the view, range from prefs`.

### Task 8: Flight tags and label boxes

**Files:** `radar.js`, `cockpit.css`, `main.js`, `tests/test_page.py`

- [x] **Tests first.** Expose each tag's lines and box in `debug()`
  (`hits[].tag = { lines, x, y, w, h }`) and each placed label's `boxed`
  flag. With the default prefs a tag is one line, `LABEL ALT`. With all
  seven fields it is two lines in the fixed order. With none, `tag` is
  null and the aircraft is still clickable by its chevron. With
  `box_items: ["AIRCRAFT"]`, `box_fill: 100`: the pixel just inside a
  tag's box corner on the visible canvas is black where a coastline ran
  under it (pick a tag over a drawn line, or inject an aircraft onto one),
  and the pixel on the box edge has the tag's colour. With `box_fill: 0`
  and `box_border: 0` the canvas is pixel-identical to boxes off. No two
  `placed` rectangles overlap with `box_pad: 12`. `HUD` in `box_items`
  gives `.hud span` a non-transparent background.
- [x] **Tags.** Formats: `CALLSIGN` the label; `TYPE`; `SQWK`; `ALT` feet
  or `GND` as now; `GS` `230KT`; `TRK` `270°`; `DIST` `12.4NM`. Empty
  values are skipped. Two or fewer chosen fields join on one line;
  otherwise identity over numbers. The click rectangle
  (`radar.js:452`) covers every line.
- [x] **One helper paints every box**, always `source-over`:

  ```js
  function box(ctx, rect, colour, ratio, prefs, alpha = 1) {
    const pad = prefs.box_pad * ratio;
    const lw = prefs.box_width * ratio;
    const r = { x: rect.x - pad, y: rect.y - pad, w: rect.w + 2 * pad, h: rect.h + 2 * pad };
    ctx.save();
    ctx.globalCompositeOperation = "source-over";
    ctx.shadowBlur = 0;
    ctx.setLineDash([]);
    ctx.globalAlpha = alpha * (prefs.box_fill / 100);
    ctx.fillStyle = "#000";
    ctx.fillRect(r.x, r.y, r.w, r.h);
    if (prefs.box_border > 0) {
      ctx.globalAlpha = alpha * (prefs.box_border / 100);
      ctx.strokeStyle = colour;
      ctx.lineWidth = lw;
      ctx.strokeRect(r.x + lw / 2, r.y + lw / 2, r.w - lw, r.h - lw);
    }
    ctx.restore();
    return r;
  }
  ```

- [x] **Static labels** (home name, airports, navaids, cities, peaks,
  state names, ring numbers): call `box` on the still layer just before
  the text, when the label's kind is in `box_items`. The collision
  rectangle pushed to `taken` and `placed` is the box, not the text, so
  boxes never overlap and hover covers the box. The box's own alpha does
  not follow the label's hover brightening.
- [x] **Aircraft tags** cannot be boxed on the moving layer: it reaches
  the screen by addition, and adding black changes nothing. In `frame()`,
  after `drawImage(still)` and before the moving layer is added, paint
  each tag's box straight onto the visible canvas, at the aircraft's own
  alpha (so a dimmed or stale aircraft's box dims with it). `drawMoving`
  returns the rectangles.
- [x] **HUD.** `applyPrefs` sets `data-box-hud` on `<html>` and four
  custom properties (`--box-fill`, `--box-pad`, `--box-border`,
  `--box-width`); CSS boxes `.hud span` from them, border in
  `color-mix(in srgb, currentColor var(--box-border), transparent)`.
- [x] Commit `feat(radar): chosen flight tags; boxes behind labels`.

  **As built, where it differs from the above.** A label's text never
  moves when its box is turned on or resized. The box is the capitals the
  label inks (0.7 of the text's size above the baseline), then the padding,
  then the border outside the padding as CSS has it for the HUD, on whole
  pixels; a place's box takes in its symbol. What a label reserves (`x, y,
  w, h` in `placed`, a ring's `label` and `hits[].tag`) is its old text
  rectangle grown to hold that box, and the painted rectangle is reported
  beside the flag as `box`. So the helper is two, `boxAbout` (the
  rectangle) and `paintBox` (the paint). On the still layer every place is
  given its room first, then the boxes are painted, then symbols and names,
  so a box hides map lines and never a symbol; the home name's box goes
  down before the home ring. `TRK` reads `030°`, as the table pads it. The
  map that ships names no states (`labels.state` is empty), so STATES has
  nothing to box until one does; its test gives the page a map with one.
  State names are always drawn without glow; before, one could take the
  glow left by a place whose label did not fit.

  **No box lies across another still label** (added in review; the first
  build let a box paint over a ring number). Bare labels cross as they
  always have, light on light: the airport's name over the ring number
  nearest it, a place's name over a number. Once either of two is boxed
  they are kept apart, and the one placed later gives way. The airport's
  name has its place first, so with HOME or RINGS boxed a ring number that
  would meet it takes its other place (there is one only when the airport
  is off the middle of the screen) or is left off: the demo's default view
  loses its 10 nm number, and range 250 its 50 and 100. The numbers come
  next, so a boxed place or state keeps off every one of them, and every
  place does once RINGS is boxed. So "fill 0 and border 0 is
  pixel-identical" holds for AIRCRAFT and HUD at any padding and, in the
  demo's picture, for the places at padding 0; not for HOME or RINGS, and
  at a wider padding a boxed label reserves more room, so fewer may fit.

  Flight tags are not placed around one another, boxed or not: two boxed
  tags that overlap are both painted and neither reads well (left for Task
  9's look). A click tries every chevron before any tag, so an aircraft
  under another's tag or its box is still the one focused.

  The tag test shows lit then black where the 20 nm range ring, not a
  coastline, crosses the box's padding; it checks the corners black
  separately and the edge's colour with the border at 100.

### Task 9: Part 1 by hand

- [x] `uv run pytest` and the browser group, green.
- [x] `kcgx --demo`, then walk the [Coverage](#coverage) table line by
  line at 1440 by 900 and 1100 by 760, in WOPR and AMBER, with display
  CRT and OFF.
- [ ] `kcgx` against real feeds and traffic at KPDX: range to 250 and
  back, a 2.5 nm zoom on the runways, boxes on with a busy picture.
- [x] Note what was seen in the plan's "Built" section, as phases C to E
  did.

  **As done, 2026-11-12.** What was seen is under [Built](#built), which
  this task starts and Task 13 finishes. Two things differ from the steps
  above.

  The walk was not made by eye at a screen. A script drove the demo
  through Playwright's headless Chromium, as a hand would (the sheet's own
  controls, the wheel, a drag, a double click), and its screenshots were
  read afterwards. So the second step is ticked for what a script and a
  screenshot can show, and no further.

  **The third step was not run, and is the owner's, on the Mac.** The
  workflow that built this plan may not start the real server, contact
  LiveATC or adsb.lol, or open an audio device, so nothing here has been
  seen against real feeds or real traffic. It is the next thing to do by
  hand, and [Built](#built) lists what to look at while doing it.

---

# Part 2: its own window

### What was weighed

| Option | Why not, or why |
|---|---|
| **A WKWebView app in Swift, built by setup** | **Chosen.** WebKit, not Chromium. A real app: its own Dock icon, name and window, `Cmd-Q`. No Python dependency; `swiftc` comes with the command line tools Homebrew already needs. About 200 lines. |
| pywebview | Also WebKit on a Mac, but adds pywebview and pyobjc, and the app shows as "Python" in the Dock unless it is bundled anyway. |
| Chrome or Edge `--app=` | The cheapest, and exactly what was ruled out. |
| Electron | Chromium. |
| Tauri | WebKit, but a Rust toolchain and a build system for one window. |
| Safari's "Add to Dock" | No Chrome, no code, but it cannot be scripted, so `kcgx` and `kcgx go seattle` could not open it or hand it a search. |

Linux keeps the default browser in this plan (decision 14). The launcher's
seam (Task 12) is where a GTK WebKit window would later plug in.

### Task 10: The page in WebKit

**Files:** `tests/test_page.py`, `pyproject.toml` comment, `README.md`
(Development), `radar.js` if needed

- [x] Parametrise the `browser` fixture over `chromium` and `webkit`
  (`uv run playwright install webkit`); each skips when its browser is
  not installed, as Chromium does today.
- [x] Run the page tests in WebKit and fix what differs. Look first at:
  `ctx.letterSpacing` on the canvas (if WebKit ignores it, labels are
  measured and drawn without it, which is consistent, but check the home
  name's spacing by eye); `<dialog>` and `::backdrop`; the `.jit`
  `drop-shadow` filter on a full-size canvas (frame rate); wheel deltas
  on the radar; `<select>` styling in the config sheet.
  **Done 2026-11-12, in Playwright's WebKit 26.0 (build 2215), headless.**
  The 188 page tests of Task 9 passed in it unchanged. What was looked at,
  beside Chromium at 1440 by 900, at 1x and 2x:
  - *`ctx.letterSpacing`:* this WebKit has it, measures with it and draws
    with it; the home name, the places and the tags are spaced as in
    Chromium, and the boxes are the same size to the pixel.
  - *`<dialog>` and `::backdrop`:* the same. The config sheet docks right
    with a clear backdrop, the airport sheet is centred over 70 % black.
    One difference, the browsers' own: with a query typed, Escape closes
    the airport sheet in WebKit; Chromium clears the field first and
    leaves the sheet open. *Fixed after review, in `sheets.js`:* the
    search field takes Escape itself and closes the sheet, so both do as
    WebKit did, and a test holds it in each.
  - *The `.jit` filter:* no cost that could be measured (10.0 ms a frame
    with and without it, at 1x and 2x; twelve blurred shadows in its place
    took 12.2, so the measure does see a filter).
  - *Frame rate, which was the real difference.* The glow was a canvas
    shadow on every trail segment and every chevron, and a shadow costs
    by the draw. With full trails, glow LOW, range 40: 25 ms a frame for
    the demo's eleven aircraft, 63 ms for 30, 118 ms for 60, and 1.1 s for
    Task 7's 600 at 250 nm. Chromium drawing on the GPU (the full build
    with `--enable-gpu`, which is what the owner's Chrome does) was as
    slow: 25, 67 and 140 ms. Task 7's 34.7 ms was the headless shell,
    which draws in software and pays by the pixel instead. **Fixed here,
    in `radar.js`:** the aircraft's lines are drawn bare on a canvas of
    their own, a colour at a time, and that canvas is drawn onto the moving
    layer once with the shadow. After: WebKit 10.0 ms a frame (its headless
    100 Hz) at 11, 30, 60 and 120 aircraft and 10.7 ms with 600 at 250 nm;
    Chromium on the GPU 8.3 ms (120 Hz) at every count. The headless shell
    holds 16.7 ms at 1x and pays for the one large shadow at 2x (33 ms).
    The picture is the same to the eye; where lines cross, a few hundred
    pixels in 600 000 differ, and a tag is now always over a trail. This
    is the first half of the follow up under "Not in this plan"; the second
    (skip what is off the screen) is not done.
  - *Wheel deltas:* the same numbers reach the page in both (pixel mode,
    the delta as sent). A real trackpad was not tried.
  - *`<select>`, and the sliders:* WebKit drew its own dropdown, rounded
    and 21 px high whatever the stylesheet said, and its own sliders,
    whose track does not show on black and which ignore `accent-color`.
    Both are now drawn by the stylesheet (`appearance: none`): a square
    dropdown with an arrow in the text's colour, and a slider that is a
    line in `--dim` with a block in `--cyan`. The same in both browsers,
    so the sliders changed in Chromium too (no filled part).
- [x] Commit `test(web): the page in WebKit as well as Chromium`.

### Task 11: KCGX.app

**Files:** `macos/KCGXWindow.swift`, `macos/Info.plist.in`,
`macos/build.sh`, `.gitignore` (`build/`), `main.js`,
`tests/test_window.py` (new), `tests/test_page.py`

- [x] **`macos/build.sh <destination>`** compiles and assembles:

  ```bash
  swiftc -O -framework Cocoa -framework WebKit macos/KCGXWindow.swift -o "$APP/Contents/MacOS/KCGX"
  sed -e "s|@REPO@|$REPO|" -e "s|@PATH@|$PATH|" macos/Info.plist.in > "$APP/Contents/Info.plist"
  codesign --force --sign - "$APP"
  ```

  Ad hoc signed, never notarised: it is built on the machine that runs
  it, so it carries no quarantine flag. The default destination is
  `~/Applications/KCGX.app`.
  *As built, 2026-11-12:* three things more than the lines above. `swiftc`
  is given `-target <arch>-apple-macos12.0`, so the one `#available` guard
  in the source compiles without a warning. The repo and the `PATH` are
  escaped for XML and for sed before they go into the plist (a folder
  named `R&D` would have broken both). And the bundle is put together
  beside the destination and moved into place once it is signed, so a
  failed build leaves the app that was there and a rebuild never writes
  into a running one.
  *After review, 2026-11-12:* the destination is the app itself and
  whatever is there is replaced, so `build.sh ~/Applications` would have
  emptied that folder. Now the destination must be named `something.app`
  (a trailing slash is allowed), and anything already there must be a
  bundle this script built, known by `com.kcgx.cockpit` in its
  `Info.plist`. Anything else is refused with exit 2 before a file is
  made, compiled or removed.
- [x] **`Info.plist.in`:** bundle id `com.kcgx.cockpit`, name KCGX,
  `CFBundleURLTypes` registering `kcgx`, `NSAppTransportSecurity` with
  `NSAllowsLocalNetworking`, and two keys of our own filled at build:
  `KCGXRepo` (so the app can run `bin/kcgx`) and `KCGXPath` (a Dock
  launch has no shell `PATH`, and `bin/kcgx` needs `uv`).
- [x] **The app's behaviour**, one `NSWindow` holding one `WKWebView`:

  | Event | What it does |
  |---|---|
  | `kcgx://show?port=8473&fragment=airport%3Dseattle` | checks `http://127.0.0.1:<port>/api/health` says `"app": "kcgx"`, then loads `http://127.0.0.1:<port>/#<fragment>`; if that page is already loaded, only sets the fragment, so the socket is kept. Shows and activates the window. |
  | launched with no URL (Dock, Spotlight) | runs `<KCGXRepo>/bin/kcgx --no-open` with `KCGXPath`, reads `server.json` for the port, loads it; the launcher's error text on failure |
  | red close button | hides the window; the app and the audio keep running; a Dock click shows it again |
  | Quit | POSTs `/api/shutdown` (2 s limit), then exits |
  | the page's power icon | the page already POSTs shutdown; it then posts `ended` to `window.webkit.messageHandlers.kcgx`, and the app exits without asking again |
  | a link to anywhere but `127.0.0.1` | refused in the window, opened in the default browser |

  Also: the window's title follows `document.title` ("KCGX KPDX"); its
  frame is remembered (`setFrameAutosaveName`); it is black before the
  page loads; `isInspectable` is on; a minimal menu (KCGX: Hide, Quit.
  Edit: Cut, Copy, Paste, Select All, without which the airport search
  cannot paste. View: Reload, Full Screen. Window).
  *As built, 2026-11-12,* where the table left a choice:
  - The red button hides the app, as Hide does, not only its window, so
    that Cmd-Tab brings it back as well as the Dock icon.
  - When the window has no cockpit in it (the launcher failed, nothing
    answered on the port, a link was refused), it says so in words, and
    View > Reload starts the cockpit as a Dock launch does.
  - The page is kept in no cache and no store on disk
    (`WKWebsiteDataStore.nonPersistent()`): every setting is the
    server's. Only the window's frame is remembered.
  - Another page on this server opened as a new window (`/debug` with a
    target) loads in the one window. A link out goes to the browser only
    if it was pressed, and only if it is http or https; anything else
    that would leave the server is dropped.
  - Two arguments for checking a build from a terminal:
    `KCGX --port N` shows the cockpit on that port as a link would, and
    `KCGX --check <link>` prints the page a link would show, or
    `refused`, and exits before there is an app or a window.
  - *After review:* one launcher at a time. While `bin/kcgx --no-open` is
    starting the cockpit, Reload does nothing (a second launcher could
    start a second server), and Quit says STOPPING THE COCKPIT, waits for
    the launcher (30 s at most; the launcher's own limit is 20 s), then
    shuts down the cockpit it recorded and exits. Before, Quit left at
    once and the cockpit came up with no window.
- [x] **Security:** any web page can open a `kcgx://` link. So the scheme
  carries a port and a fragment and nothing else, the host is always
  `127.0.0.1`, the port must be an integer from 1024 to 65535, and the
  health check must name kcgx before anything loads.
  *As built:* a link is `kcgx://show` with `port` and `fragment`, once
  each; a path, a user, a port on the link itself, a fragment on the link
  itself or any other parameter refuses it. The fragment is not refused
  for what it holds: every byte a URL's fragment may not hold is escaped,
  so it stays a fragment whatever was sent (512 bytes at most). A link
  that is refused, or whose port does not answer as kcgx, never starts the
  cockpit, even if it is what opened the app. The `ended` message is taken
  only from the main frame of the page on the port being shown.
  *After review:* "even if it is what opened the app" rested on the link
  arriving before the app had finished launching, or within a second of
  it. It now also rests on what launched the app: if the launch's Apple
  event is a GetURL, the cockpit is not started, however late the link
  itself arrives. The page's side: a fragment may hold an escape that
  is no character (`airport=%E9`), which the window hands on as it came;
  `fromLink` in `main.js` threw on it and the rest of the page never ran.
  It now takes such a query as written.
- [x] `main.js`, in `onEnded`:
  `window.webkit?.messageHandlers?.kcgx?.postMessage("ended")`. A no-op
  in a browser.
- [ ] No unit tests reach Swift. Check by hand, and list each row of the
  table above as checked in the "Built" section.
  **Open, and the owner's:** the rows are listed there, most of them as
  not seen. Nobody has looked at the window, and the app as committed
  has never been started. The thirteen steps under "For the owner" are
  this check; do them, at least 1, 2, 4, 8, 9 and 10, before Task 12
  makes `kcgx` depend on the window.
  *Changed, 2026-11-12:* one kind does. `tests/test_window.py` builds the
  real app into the test's own folder (on a Mac with `swiftc`; elsewhere
  it skips), checks `codesign --verify`, and asks the binary with
  `--check` what 44 links would show: 14 it shows, 30 it refuses. The
  same file drives `build.sh` with a fake `swiftc` and `codesign`, which
  runs anywhere. Nothing in it opens a window or registers the app. The
  page's half of `ended` is tested in both browsers (`test_page.py`).
  Everything that needs a window is under
  [KCGX.app](#kcgxapp-task-11-2026-11-12) in "Built".
- [x] Commit `feat(window): KCGX.app, the cockpit in its own window`.

### Task 12: The launcher opens it; setup builds it

**Files:** `launcher.py`, `setup.sh`, `bin/kcgx` (comment),
`tests/test_launcher.py`, `tests/test_setup.py`

- [x] **Tests first.** `pick_opener` returns the window opener when the
  platform is darwin and `KCGX_APP` (default `~/Applications/KCGX.app`)
  exists, and `webbrowser.open` when it does not, on Linux, with
  `--browser`, or with `KCGX_BROWSER=1`. The window opener runs
  `open -a <app> kcgx://show?port=<port>&fragment=<quoted>` (inject
  `run`), and falls back to the browser if `open` exits non-zero.
  `kcgx go seattle` hands the app `fragment=airport%3Dseattle`. Existing
  tests keep injecting `opener` and are untouched. Setup: on macOS with a
  fake `swiftc` on the test's `PATH`, step 5 builds into the test's
  `KCGX_APP`; with no `swiftc`, it says the cockpit will open in the
  browser and carries on; on Linux it does not try.
- [x] `launcher.main(argv, *, opener=None)`: `opener or pick_opener(args)`.
  `--browser` on `kcgx` and `kcgx go`. Help and the module docstring say
  "its own window" where they said "a browser".
  *As built, 2026-11-12:* the opener still takes the page's address, so
  the port and the fragment are read back out of it. The fragment is
  quoted whole, on top of the quoting it already has as part of that
  address (`#airport=new%20york` goes as `fragment=airport%3Dnew%2520york`),
  which is what the app unquotes once. The fallback also covers an `open`
  that is missing or does not return within 15 s, and says on stderr that
  the browser is being used. `KCGX_BROWSER` set to nothing or to `0` is
  off. `kcgx --browser go` works as well as `kcgx go --browser`.
  `tests/test_window.py` gained one test that is not in this task's list
  of files: the link the launcher makes, read by the real app through
  `--check`, shows the page it was made from.
- [x] `setup.sh` step 5 becomes "The launcher on your PATH, and its
  window": after the symlink, on macOS, run `macos/build.sh`. A failed
  build is a warning, never fatal. Still seven steps. Step 7's check adds
  one advisory line: the app is there and `codesign --verify` passes.
  *As built, 2026-11-12:* the build comes after the PATH question as well
  as after the symlink, because the app keeps the `PATH` it was built with
  and that is the step which settles it. Setup reads `KCGX_APP` as the
  launcher does and passes it to `build.sh`. It does not ask before
  building, as it does not ask before linking. On Linux the step keeps its
  old title and says nothing of a window. Step 7's row is `window`: `ok`
  with the path; `none`, which is not counted as a warning, when there is
  no app (the launcher opens the browser, so nothing is wrong); `warn`
  when an app is there and does not verify, since macOS will not start it.
  The last line reads "Opening the cockpit..." without saying where.
- [x] `--uninstall` paths, if `setup.sh` has them, remove the app.
  *2026-11-12:* it has none, so there was nothing to do. To remove the
  window by hand: `rm -rf ~/Applications/KCGX.app`.
- [x] Commit `feat(launcher): kcgx opens its own window`.

*After review, 2026-11-12.*

- **This task landed before Task 11's hand check, which is still open.**
  Task 11 asked for the owner's steps 1, 2, 4, 8, 9 and 10 before `kcgx`
  came to depend on the window; nobody has done them. So
  `open -a <app> kcgx://show?...` handing a page to a running app has not
  been seen to work by anyone: the tests hold the link's text and what the
  app's `--check` makes of it, and no more. What limits it: the window is
  used only once KCGX.app exists at `$KCGX_APP`, which takes `setup.sh` or
  `macos/build.sh` run by the owner. **`kcgx --browser`, or `KCGX_BROWSER=1`
  in the environment, is the way back** if the window misbehaves after
  that. Task 13 should say both in "Built" and in the README.
- **The fallback is to `open`, not to the window.** The launcher goes to
  the browser when `open` fails, is missing or hangs. `open` exits 0 once
  it has handed the link over, so an app that then crashes, whose health
  check fails, or that shows nothing, is not noticed and `kcgx` reports
  success. The launcher now keeps from the app the two things it is known
  to refuse (a port outside 1024 to 65535, as `KCGX_PORT=80` would give,
  and a fragment over 512 bytes, as a very long `kcgx go` query would) and
  shows those pages in the browser, saying so. `tests/test_window.py`
  holds the two limits to the real app. The rest is left to the hand check.
- **"The app exists" means its program is there**
  (`Contents/MacOS/KCGX`), not that something is at the path. `KCGX_APP`
  naming a folder that is not the bundle (`~/Applications`, say) used to
  run `open -a` on it, fail, and print the fallback line at every `kcgx`.
- **`KCGX_BROWSER` is on for anything but nothing or `0`**, `false` and
  `no` included. Left so, and said in the launcher's docstring.
- **`kcgx --no-open go` opened the page**, and after this task that meant
  the window: `go`'s own `--no-open` had a default that put the flag back
  to off. It was older than this task and is the fault this task had
  already mended for `--browser`; mended the same way.
- **Step 7's hint names the app.** For an app that does not verify it
  said `rebuild it: <repo>/macos/build.sh`, which builds
  `~/Applications/KCGX.app` whatever `KCGX_APP` says. It now ends with the
  destination.
- **Setup's banner and `--help` no longer say every step asks.** Step 5
  makes the link and builds the app without a question of its own, as
  above; the behaviour is unchanged. The banner says step 5 makes what is
  kcgx's own without asking (it is printed before the platform is known,
  so it does not name the app, which Linux is not offered); `--help` names
  the link and the app. The README's line ("asks before each one that
  changes...") is Task 13's.

### Task 13: The docs

**Files:** `README.md`,
`docs/superpowers/specs/2026-10-18-web-cockpit-design.md`, this plan

- [x] **README:** "Running it" (the window, `--browser`, close versus
  quit); "The cockpit" (no FEEDS or PALETTE, the icons, lamps and teletype
  off by default, the focused track); "The radar" (range, 2.5 nm, double
  click, tags, boxes); "Configuration" (the CONFIG table from this plan;
  `radar_range_nm` retired from `squelch.toml`, with the date); "When it
  opens on one feed" (choose the airport again); "Install" step 5;
  "Development" (WebKit in the browser group).
- [x] **Spec:** write the fifteen decisions into their sections, dated
  2026-11-12, as phase E did.
- [x] Add a "Built" section here: what was done, what was seen by hand,
  the 250 nm frame time, anything deferred.
- [x] Commit `docs: phase F built`.

  **As done, 2026-11-12.** Four things beyond the list above. The README
  also says what the list could not have known: that with the teletype
  off the one-feed fallback's line is not seen, that flight tags overlap,
  that STATES has nothing to box, and that the window had not been
  watched when it was written. Its "Known limitations", "What it needs",
  "Doing it by hand" and "History" were brought up to date as well as the
  sections named. The spec gained the settings table, the window, the
  `kcgx:` scheme's rules and three open questions, beside the fifteen
  decisions. And `docs/README.md`, which is not in this task's files,
  gained a row for phase F, as phase E's docs commit gave it one.

  The suite for this commit was run without one test,
  `tests/test_launcher.py::test_go_when_not_running_starts_at_that_airport`,
  for the reason given under [Built](#built): it starts the real server,
  which the workflow that built this plan may not do. This commit changes
  three documents and an index that no test reads.

*After review, 2026-11-12.*

- **`kcgx go KSEA` opens nothing, and the README said it showed the
  window.** "Running it" had "`kcgx` and `kcgx go` show the cockpit
  there". `cmd_go` opens a page in two cases only: for the search (no
  airport, or a query naming several), and after a switch when `--open` is
  given. The README now says so and lists `kcgx go --open KSEA`; the
  spec's sentence under the window carries the same clause. Task 12's
  wording above and row 12 of "What was done" are as loose and are left
  as written, being the record of that task. No test was added: no test
  reads the README, and the behaviour it now states was already held by
  `test_go_with_an_icao_switches_the_running_cockpit` (nothing opened)
  and `test_go_open_opens_the_page_after_switching`.
- **`docs/README.md` stays as committed.** It was outside this task's
  files and is said so above; the review accepted it.
- **The one test left out is still left out,** in this review's run of the
  suite too, for the same reason: `1268 passed, 1 deselected in 602.49s
  (0:10:02)`, run on these three documents as committed but for this one
  line. It is the owner's to decide, under "Owed by the owner".

---

## Coverage

Every line of the 11/12 list, and where it is done.

| The list | Task |
|---|---|
| Tighten padding around all text | 6 |
| Hide status indicators by default; setting to show | 3, 5 |
| Radar: closer zoom, 2.5 nm | 7 |
| Radar: remove RECENTRE | 7 (double click instead) |
| Radar: range setting, to the maximum | 2, 5, 7 |
| Radar: boxes (fill opacity, padding, border opacity, border width 1 to 5, which items) | 1, 5, 8 |
| Radar: which flight info shows | 1, 5, 8 |
| Airport pane: search icon, bottom right, opposite the name | 4 |
| Airport pane: remove STATUS | 4 |
| Teletype: off by default, a setting, frequencies fills the space | 3, 5 |
| Frequencies: less padding in M and S | 6 |
| Frequencies: smaller chatter figure, with % in both states | 6 |
| Tracks: selected flight to the top, 20 % larger in every cell | 6 |
| Header: remove FEEDS | 4 |
| Header: remove PALETTE | 4 |
| Header: CONFIG as a settings icon, no border | 4 |
| Header: SHUT DOWN as a power icon, no border | 4 |
| Config: scanline opacity and size | 1, 5 |
| Config: theme as a dropdown | 5 |
| Config: remove LIMITS | 5 |
| Config: every setting above | 1, 5 |
| Its own window, not Chrome | 10, 11, 12 |

## Order, and what can run side by side

1 and 2 first, in that order: everything else reads the schema. 3 before 4
and 5 (they edit the same HTML). 6, 7 and 8 touch different files from each
other after 5 and can go to separate workers; 8 needs 7's view. Part 2
needs only Part 1's `main.js`, and Task 10 can start any time after 5.

## Not in this plan

- An icon for KCGX.app (it gets the generic one).
- A window on Linux.
- Decluttering tags when 250 nm fills the screen (Task 7 measures first).
- **Follow up from Task 7's measurement: the radar's frame time with a
  full 250 nm picture.** 600 aircraft with full trails took 34.7 ms a
  frame (the numbers and how they were taken are under Task 7), against a
  16 ms budget. The work, none of it done in this plan: draw each trail
  as one stroke, or a few, instead of a stroke and a shadow for every
  segment, or draw trails without the shadow; and skip aircraft and trail
  points that are off the screen.
  *Changed by Task 10, 2026-11-12:* the shadow for every segment turned
  out to be what WebKit, and Chromium on a GPU, could not afford at any
  range (63 ms a frame for 30 aircraft), so the glow became one shadow for
  each colour there, and the 250 nm picture came with it: 10.7 ms in
  WebKit, 8.3 ms in Chromium on the GPU. Skipping what is off the screen
  is still not done, and the static layer still redraws with a shadow on
  every map line and symbol while the map is panned or zoomed (30 to 40 ms
  a frame in WebKit).
- Per-item box styles: one fill, padding and border for every boxed item.
- A sticky header on the tracks table.

## Built

Built on 2026-11-12, on `feat/web-cockpit`, in 24 commits from `5c0df95`
to `bb8927a` and the docs commit that carries this section: one commit
for each task and one or two of review fixes after it. Task 9 started
this section and Task 11 added to it; Task 13 wrote the rest and left
theirs as they were, below.

**Read this first.** The plan was built by a workflow of agents that may
not start the real server, contact LiveATC or adsb.lol, open an audio
device or write to `~/Applications`. So **nothing in phase F has been
seen by a person at a screen, heard, or run against real feeds or real
traffic**, and nobody has looked at the window. Everything below was
tested, measured in headless browsers, or read from screenshots a script
took of the demo. What that leaves is listed under
[Owed by the owner](#owed-by-the-owner). Until `./setup.sh` or
`macos/build.sh` is run, there is no `~/Applications/KCGX.app` on this
Mac and `kcgx` opens the browser as before.

### What was done

| Task | Commits | What |
|---|---|---|
| 1 | `5c0df95`, `ece0c4f` | `kcgx.prefs.SCHEMA`: fourteen settings of four kinds. The file is read leniently through it, the protocol strictly; a setting the schema does not have refuses the message. |
| 2 | `7bbffd8`, `2af3087` | The range is the pref `range_nm`, 10 to 250. `Radar.set_range` retunes the running radar and never wakes the poller; shrinking drops what is beyond at once. `radar_range_nm` left `Config`. The map is clipped at 320 nm. The demo sends what is inside the range. |
| 3 | `2d1c865`, `d50e65c` | One page grid of eight named parts. Lamps and teletype are prefs, off by default. A page error shows in the banner for 8 s while the teletype is hidden. |
| 4 | `b637dc8`, `fe9a02b` | The header is a gear and a power icon; FEEDS, PALETTE, the feeds sheet and RECENTRE are gone; the airport pane has no title and a search icon bottom right. A double click recentres (it came in here, with RECENTRE's going, so the page was never without a way back). The retry hint reads "choose the airport again". |
| 5 | `73813b8`, `ff10b96` | The config sheet: one `[data-pref]` control for each setting, bound by kind, docked right with a clear backdrop. THEME is a dropdown, the scanlines are two sliders, LIMITS is gone. `tests/test_page_prefs.py` holds the markup to the schema. |
| 6 | `d18b8e9`, `66b4ebc` | The spacing tokens and the denser values. Chatter reads `NN%` at 18 and 14 px; M and S are 28 by 24 px. The focused aircraft is the table's first row, a fifth larger. |
| 7 | `37cfa27`, `24d2fbe` | The view is held in nm: the wheel runs from 2.5 nm to 160 or the range; rings are computed and their numbers placed; the home ring is held between 24 and 64 px. The 250 nm frame time was measured (below). |
| 8 | `d2720e5`, `20aaace` | Flight tags from `tag_fields`, one line or two. Label boxes for nine kinds of item, painted `source-over`; no box lies across another still label. |
| 9 | `c4d1bab`, `224f150` | Part 1 walked by a script; no code changed. Written up below. |
| 10 | `1d2ac37`, `54b0c57` | Every page test runs in Chromium and in WebKit. Three fixes: the aircraft's glow is one shadow for each colour; sliders and the dropdown are drawn by the stylesheet; Escape in the airport search closes the sheet in both. |
| 11 | `bacf859`, `0120a07` | `macos/KCGXWindow.swift`, `Info.plist.in`, `build.sh`; `tests/test_window.py`. The page tells the window when it has shut down. |
| 12 | `809c320`, `bb8927a` | `kcgx` and `kcgx go` open the app when it is there, the browser otherwise; `--browser`, `KCGX_BROWSER`, `KCGX_APP`. Setup's step 5 builds the app on macOS; step 7 has a `window` row. |
| 13 | this commit | The README, the spec, this section, and a row in `docs/README.md`. |

Every line of the 11/12 list is in the [Coverage](#coverage) table, and
each has code and tests behind it. Where a task built something other
than its steps said, the task's own "As built" note says so.

### The suite

It was 650 tests before the plan. After each task, as that task reported
it: 798 after Task 4, 867 after 5, 879 after 6, 890 after 7, 926 after 8,
934 after 9, 1136 after 10 (when every page test began to run twice, once
in each browser), 1199 after 11, 1249 after 12 and 1269 after its
review. The quoted 90 s became about ten minutes, most of it Chromium's
half of the page tests.

For this commit, `uv run --quiet --group browser pytest -q` with the one
test named below left out: `1268 passed, 1 deselected in 597.55s
(0:09:57)`, none skipped and none failed. It was run while these
documents were being written; the tree it ran on differs from this commit
only in the four Markdown files, and no test reads a Markdown file.

Three things about it that a reader should know.

- **One test starts the real server, and was left out of this task's
  run.** `tests/test_launcher.py::test_go_when_not_running_starts_at_that_airport`
  runs `kcgx go KSEA` with nothing running, so `python -m kcgx.server`
  starts without `--demo`, is checked and is stopped about a second
  later. It is older than this plan (phase E) and Task 12 found it. In
  that second the server may open the audio device and begin fetching
  LiveATC's listing for KSEA and polling adsb.lol; nobody has measured
  whether it does. The test's home and state are in a temporary folder,
  so nothing of the owner's is written. It breaks this plan's own
  constraint ("no test touches the network, ffmpeg or an audio device")
  and every full run of the suite before this one included it. It was
  not changed, because no task was given it. **For the owner to decide:**
  the smallest change is to start the demo first, as its neighbours do,
  and to test "start at that airport" some other way.
- **Two page tests fail now and then.** `test_a_refused_radar_says_so_and_dims_its_lamp`
  and `test_an_emergency_squawk_lights_the_lamp_and_turns_the_row_red`
  put an aircraft frame into the page by hand and lose it if the demo's
  15 s poll lands before the page has shown it. Tasks 7 and 11 each met
  one, each passed alone, and neither was mended. A third,
  `test_a_callsign_pressed_far_down_a_one_column_page_brings_its_row_back_into_view`,
  failed once in Task 7 for the same poll re-rendering the table under it.
- **`tests/test_window.py` compiles the real app** into the test's own
  temporary folder on a Mac with `swiftc`. None of those copies was ever
  listed by Launch Services.

### What was seen, and how

Nothing by a person. What stands in for it:

- **Task 9's walk of Part 1**, by script, in headless Chromium, on the
  demo: every line of the list at two sizes, two palettes and two
  displays, 349 checks and 119 screenshots read afterwards. It is
  written up under [Part 1 by hand](#part-1-by-hand-task-9-2026-11-12).
- **Tasks 4 to 8 each looked at their own screenshots** of the demo, in
  Chromium, mostly WOPR with display CRT.
- **Task 10 looked at the page in Playwright's WebKit 26.0** beside
  Chromium, at 1440 by 900, at 1x and 2x. That is not the system's
  WKWebView (Safari here is 27.2), which is what KCGX.app uses.
- **Task 11 ran an earlier build of the app once**, for 13 s, without
  looking at it. See [KCGX.app](#kcgxapp-task-11-2026-11-12).

### The 250 nm frame time

The demo cannot fill 250 nm, so 600 aircraft, each with a full 12 point
trail, were put into the page by hand. All of it is from headless
browsers at 1440 by 900 (a 1024 by 588 radar), glow LOW, display CRT; the
figure is the mean interval between frames. None of it is from a real
display, and a real 250 nm picture has never been drawn.

| Where | Before Task 10 | After |
|---|---|---|
| Chromium's headless shell (draws in software), 1x | 34.7 ms (Task 7) | 19.2 ms |
| the same, 2x | 66.3 ms (Task 7) | 45.5 ms |
| Playwright's WebKit, 1x | 1.1 s | 10.7 ms |
| the same, 2x | not taken | 11.8 ms |
| Chromium on the GPU, 1x and 2x | not taken at 600 (it crashed); 136 ms at 60 aircraft and 40 nm | 8.3 ms |
| WebKit, 1x, with every tag boxed | | 11.6 ms |

Headless WebKit ticks every 10.0 ms and Chromium on the GPU every 8.3 ms,
so 8.3 ms means no frame was late, and 10.7 to 11.8 ms that some were.
Task 7
found the cost (a canvas shadow on each of 6600 trail strokes) and left
it, as its step said; Task 10 met the same cost at any range in WebKit
and on a GPU (25 ms a frame for the demo's eleven aircraft) and changed
the glow to one shadow for each colour. The shell, which the tests run
in, is the one place still over 16 ms at 250 nm, and at 2x it is slower
than it was at ordinary ranges too: about 33 ms a frame with any traffic
and the glow on, where it held 16.7 ms. A Mac with no GPU acceleration
and a 2x display would see that.

Not done: aircraft and trail points off the screen are still drawn; and
the static layer still redraws with a shadow on every map line and symbol
while the map is panned, zoomed or drawing on. Task 10 measured that at
31 to 54 ms a frame in WebKit, and in Chromium on the GPU at 16 to 28 ms
at 40 nm and 67 to 100 ms at 250 nm. Task 10's change costs one more
full-size canvas, about 9.6 MB at 2x.

### Owed by the owner

Every hand check an earlier task reported as not done, gathered. None has
been done.

**With real feeds and traffic** (Task 9's third step; `kcgx` at KPDX).

1. The range to 250 and back. A wider range fills in only at the next
   scheduled poll (up to 15 s; that is decision 1), so the wide rings
   show empty until then: is that acceptable against the real service?
   Shrinking should drop aircraft at once.
2. A real 250 nm picture: how many aircraft, the frame rate (the numbers
   above are headless), and how badly the tags overlap.
3. A 2.5 nm zoom on the runways.
4. Boxes on with a busy picture.
5. Audio. Nothing here opened an audio device: master volume, M and S
   muting and soloing, the chatter percentage following real speech, and
   the AUDIO lamp were seen only as demo values.
6. With lamps and teletype off, as they now are by default: is it clear
   enough when a launch has fallen back to one feed, or when an aircraft
   squawks an emergency? Neither note reaches the banner (decision 4
   sends only the page's own errors there). Noticed in Task 13, while
   writing the README; no task looked at it.

**On the real display.**

7. The look of CRT, glow, scanlines and flicker; the scanline sliders
   through their range.
8. The wheel on a trackpad. The tests send exact pixel deltas, and the
   small-airport test depends on them.
9. The sliders. They are drawn by the stylesheet since Task 10 and have
   no filled part, in Chrome too: a change the list did not ask for.
10. The icons and M and S as targets: 30 px and 28 by 24 px. Small for a
    finger at 390 px wide.

**The window.** The thirteen steps under
[KCGX.app](#kcgxapp-task-11-2026-11-12), "For the owner, with the window
in front of you". Task 11 asked for at least 1, 2, 4, 8, 9 and 10 before
Task 12 made `kcgx` depend on the window; Task 12 landed without them.
What has never happened at all:

11. A link delivered through `open -a <app> 'kcgx://show?port=...'`, to a
    closed app and to an open one (the fragment set without a reload).
12. A launch from the Dock or Spotlight starting the real cockpit.
13. The red button hiding, the Dock icon bringing back, Cmd-Q stopping
    the cockpit, the power icon ending the app.
14. A refused link, or one to a port nothing answers on, **not** starting
    the cockpit (step 10 there; the one that matters most).
15. The title, the remembered frame, black before the page, paste in the
    airport search, Reload, Full Screen, Inspect Element.
16. Whether the page keeps up while the app is hidden. It keeps its
    socket and is sent levels 25 times a second; WebKit may throttle a
    hidden page, and the hub drops a page that stops reading (it then
    reconnects). Not measured.

`kcgx --browser`, or `KCGX_BROWSER=1`, is the way back if any of it goes
wrong, and `rm -rf ~/Applications/KCGX.app` removes the window.

**Setup.** `./setup.sh` has not been run for real since step 5 learned
to build the app; the tests drive it with a fake `swiftc`.

17. A real run on this Mac: the app built into `~/Applications`, step 7's
    `window` row, and the cockpit then opening in the window.
18. Not tried, and reasoned only: on a Mac without the command line
    tools, `/usr/bin/swiftc` is Apple's placeholder, so `command -v
    swiftc` finds it, the build runs it, and macOS may show its install
    dialog unannounced before the build fails with setup's warning.

**For the owner's decision**, each reported by a task and left alone.

19. The config sheet is modal with no backdrop: the page behind looks
    live and takes no clicks, and a click outside does not close the
    sheet. It also covers the right 40 % of the radar at 1100 px wide.
20. A range change from any tab resets every tab's pan and zoom.
21. The wheel is not limited to the range: at range 10 it still goes out
    to 160 nm, with map and no traffic beyond the bright ring.
22. Quit stops whatever cockpit the window shows, one started from a
    terminal included, and so does logging out.
23. Setup builds the app without asking (about 15 s the first time, a new
    app in `~/Applications` that claims the `kcgx:` scheme).
24. The power icon turns white under the pointer, and is white at rest in
    AMBER and MATRIX.
25. A failed airport search raises its banner behind the airport sheet's
    70 % black backdrop, where it is dim.
26. Problems 1 to 3 under Part 1 below: overlapping tags, a long airport
    name cut by the radar's edge, pressed buttons outside WOPR.
27. The test that starts the real server (under "The suite" above).

### Deferred

Beside what "Not in this plan" already lists (an icon, a window on Linux,
decluttering tags, the rest of the frame time work, per-item box styles,
a sticky table header):

- **STATES in LABEL BOXES does nothing visible.** `/api/geo` returns no
  state names for any airport, so the button has nothing to box. The code
  path is tested with a map that has one.
- **Flight tags and the home name are not placed around one another.** At
  2.5 nm the home name's box and the nearest aircraft's tag sit on each
  other.
- **The launcher does not check that what is at `$KCGX_APP` is the KCGX
  app**, only that a program is at `Contents/MacOS/KCGX` inside it.
- **`setup.sh --check` does not list `swiftc`,** and setup has no
  uninstall.
- **A slider still in hand is not moved by another tab's change** to the
  same setting until it loses focus. As the volume slider always was.
- **The RANGE slider moves in tens** but the schema allows any whole
  number: a hand-edited 45 reads "45 NM" with the thumb at the nearest
  step.
- **`ctx.letterSpacing` missing** is handled in `radar.js` and tested in
  no browser: both engines have it.
- **`squelch.runtime` still writes "press f to retry"** and the station
  rewrites it by replacing the words. If the wording there changes, the
  page shows the terminal's hint.

### Left on this Mac

Things the build left, or found, outside the repo. None was touched by
Task 13.

- **A demo server is still running:** PID 10877,
  `kcgx.server --demo --icao KPDX --port 56904`, started 12:09 on
  2026-11-12 by an earlier task's script and orphaned. It is the demo (no
  network, no audio). `kill 10877` ends it.
- **`~/Desktop/KCGX.app`** (`com.mikelse.kcgx`) is not from this plan. It
  does not claim `kcgx:`, but once setup has built the new app Spotlight
  will offer two called KCGX.
- **`uv run playwright install webkit`** (Task 10) garbage-collected two
  browser builds that belong to another Playwright on this machine,
  `chromium-1243` and `chromium_headless_shell-1243`, at about 14:39.
  They were back by 16:07, reinstalled by something else.
- **No app is registered.** `build/KCGX.app` was deleted after Task 11's
  review, and `lsregister -dump` listed no `com.kcgx.cockpit` after Task
  12. Building into the repo's `build/` again will register it again
  within a minute; see below.
- **Screenshots and measuring scripts** are in the workflow's scratch
  folder, not in the repo, and will not outlast it.

### Part 1 by hand (Task 9, 2026-11-12)

**The suite.** `uv run --quiet --group browser pytest -q`: 934 passed in
366 s, none skipped. Playwright's Chromium was installed, so the browser
tests ran. It was 650 before the plan.

**How the walk was made.** By a script, not by eye. A `--demo` cockpit for
KPDX on a free port, with `KCGX_STATE_PATH` and `HOME` in a temporary
folder, driven through Playwright's headless Chromium: the THEME dropdown,
the segment buttons, the sliders by the keyboard and by a dragged mouse,
the wheel, a drag and a double click on the radar, a click on a callsign.
It ran once for each of 1440 by 900 and 1100 by 760, WOPR and AMBER,
display CRT and OFF: eight walks, 320 checks, none failed, and no page or
console error in any. Two more passes (a cockpit started with remembered
settings, at 1440 by 900; tuning the boxes while zoomed in and an airport
with a long name, at both sizes) made 29 checks, none failed. Glow was LOW
in the eight. MATRIX with glow FULL and display VECTOR, and MONO with glow
OFF, were each looked at once, at 1440 by 900. The 119 screenshots were
read; they are not kept in the repo.

What this cannot say, and step 3 of Task 9 is there to say: how the glow,
the scanlines and the flicker look on a real display; how the wheel feels
on a trackpad; anything about real feeds or real traffic.

**The two sizes are two layouts.** 1440 by 900 is the two column page and
never scrolls (the document is 900 px high by default and with lamps and
teletype on). 1100 by 760 sits on the `max-width: 1100px` break, so it is
the one column page, and scrolls: 1452 px by default, 1601 px with lamps
and teletype on, in the order radar, airport, frequencies, lamps, tracks,
teletype.

**Line by line.** The same in WOPR and AMBER, CRT and OFF, unless said.

| The list | Seen |
|---|---|
| Tighten padding around all text | Nothing touches or is clipped at either size. At 1440 by 900 the tracks pane shows six rows and the top of a seventh, and scrolls; at 1100 all eleven show. |
| Hide status indicators by default; setting to show | Hidden by default. STATUS LAMPS ON in the sheet: at 1440 the bar is under the radar at exactly its width (12 to 1038 px), above tracks; at 1100 it is between frequencies and tracks. Nine feed lamps, then RADAR, SERVER, AUDIO, EMERG. |
| Radar: closer zoom, 2.5 nm | The wheel stops at 2.5 nm, at range 40 and at range 250. KPDX's three runways read as three white lines, the home ring holds at 64 px, the rings are 0.5 nm apart and numbered. Out, the wheel stops at 160 nm with range 40 and at 250 with range 250. The view holds while settings are changed in the sheet. |
| Radar: remove RECENTRE | No button. After a zoom and a dragged pan, a double click returns the view to the range, centred. |
| Radar: range setting, to the maximum | The slider goes 10 to 250 by the keys and by the mouse; the sheet reads "250 NM" and the HUD "RNG 250 NM". At 250 the rings are 50, 100, 150, 200 and 250, the last bright; back at 40 the view resets. At 10 (rings 2 to 10) every aircraft beyond it left the radar and the table at once, and two stayed; back at 40 the picture filled with the next scheduled poll, 2.2 s later in that run. A cockpit started with range 120 remembered opens at 120. A new airport keeps the range. On a wide radar the 250 nm view reaches further left and right than the map's 320 nm; east of about 350 nm the places stop and only the airways carry on. Nothing looks cut off. |
| Radar: boxes | All nine items on at the defaults (fill 70, padding 4, border 50, width 1): places, ring numbers, the airport's name and the HUD each sit in a box in their own colour, and no box of those lies across another (flight tags do: problem 1 below). HOME, CITIES and RINGS alone: only those are boxed, and the 10 nm number is left off, as Task 8 records. At fill 100, padding 12, border 100, width 5 the HUD's spans measure 12 px of padding, a 5 px border, black behind. STATES could not be seen: the map names none. |
| Radar: which flight info shows | Default, one line: `ASA412 3100`. All seven, two lines: `ASA412 B39M 4512` over `3100 230KT 270° 11.0NM`. TYPE, GS and DIST, two lines: `B39M` over `230KT 10.0NM`. None: chevrons only. |
| Airport pane: search icon, bottom right, opposite the name | 13 px from the pane's right edge and 9 px from its bottom at both sizes, its bottom level with the name block's. At 1440 CYUL's name wraps to two lines, the pane grows from 127 to 144 px, the icon stays bottom right, and the page still does not scroll; at 1100 the name fits on one line. |
| Airport pane: remove STATUS | No title bar: the ICAO, the clocks, the name, the place, the icon. |
| Teletype: off by default, a setting, frequencies fills the space | Off: at 1440 frequencies runs to the bottom of the page, level with tracks. On: the teletype is under frequencies, level with tracks, and frequencies stops above it. With it off, a refused message showed in the banner: "ERROR: RANGE_NM MUST BE A WHOLE NUMBER FROM 10 TO 250". |
| Frequencies: less padding in M and S | Each is 28 by 24 px. |
| Frequencies: smaller chatter figure, with % | 18 px in the expanded row, 14 px in the compact ones; `27%`, `7%`, no leading zero, right aligned. |
| Tracks: selected flight to the top, 20 % larger | A click on the fourth row's callsign: it is the first row, 15.6 px against 13 in all seven cells, outlined; the rest dim, on the radar as well. A second click lets it go. |
| Header: remove FEEDS, remove PALETTE | Gone. The bar reads `KCGX  LOCAL COCKPIT 127.0.0.1:<port>` and two icons. |
| Header: CONFIG and SHUT DOWN as icons, no border | A gear and a power symbol, 0 px border, each with a name for a screen reader and a tooltip. The power icon is red in WOPR and white in AMBER, whose alarm colour is white. It asks before it stops; CANCEL keeps the cockpit. |
| Config: scanline opacity and size | Both sliders are greyed unless display is CRT. At 0 % no lines. At 100 % and 8 px a black 3 px line every 8 px cuts through every row of text on the page and it is hard to read: the far end of both sliders, as asked. |
| Config: theme as a dropdown | A `<select>` of the four; the page changes at once. |
| Config: remove LIMITS | Gone. OUTPUT, LOOK, LAYOUT, RADAR. |
| Config: every setting above | All fourteen. The sheet is 420 px wide on the right edge, full height, and fits without scrolling at 900 and at 760 px. The radar beside it is not darkened and changes as each control moves. At 1100 the sheet covers the radar's right two fifths; the airport is still in view. Settings remembered in `prefs.json` come back on the page and in every control; `--demo` never writes the file. |
| Its own window, not Chrome | Part 2; not walked here. |

**Problems seen. None was fixed in Task 9; no code changed.**

1. **Flight tags lie on one another where aircraft are close.** With the
   default two fields at 40 nm, two or three tags by the airport overlap
   and one crosses the airport's name. With all seven fields, the five or
   six nearest the airport cannot be read, and boxes make it worse: each
   opaque box hides the tag under it. At 250 nm the demo's aircraft, all
   within 40 nm, are one block in the middle of the screen. At 2.5 nm the
   same tags read well. This is the decluttering that is under
   [Not in this plan](#not-in-this-plan), and what Task 8 left for this
   look. Deferred. Real traffic at 250 nm will show how much it matters.
2. **A long airport name runs off the radar.** CYUL's, "MONTREAL / PIERRE
   ELLIOTT TRUDEAU INTERNATIONAL", is drawn in two lines at 30 px and the
   second is cut by the radar's right edge at 1440 by 900. The split is
   phase D's (`nameLines`), and the name is not on the 11/12 list.
   Deferred.
3. **A pressed button is hard to tell from one that is not, outside
   WOPR.** Pressed is the palette's `--pink`: pink in WOPR, but in AMBER,
   MATRIX and MONO within a shade of `--text` (AMBER's are `#ffd98a` and
   `#ffd58a`), so the words hardly change and only the border brightens.
   CONFIG now has 26 such buttons. Older than this plan, not on the list.
   Deferred, for the owner's eye.
4. **Escape in the airport search, with text typed, clears the text and
   leaves the sheet open.** The field is `type="search"`, and that is what
   Chromium does with one. Left as it is; Task 10 will show what WebKit
   does. *Task 10:* WebKit closes the sheet at the first Escape, text or
   no text, and the page now does the same in both (`sheets.js`).

**For the owner, on the Mac (Task 9's third step, not run).** `kcgx` at
KPDX: the range to 250 and back; a 2.5 nm zoom on the runways; boxes on
with a busy picture, which is where problem 1 will show; the frame rate at
250 nm with real traffic (Task 7 measured 34.7 ms a frame with 600
injected aircraft, in a browser drawing in software; after Task 10's
change to the glow it is 10.7 ms in WebKit and 8.3 ms in Chromium on a
GPU); and the look of CRT, glow and scanlines on the real display.

### KCGX.app (Task 11, 2026-11-12)

**Built and signed.** `macos/build.sh build/KCGX.app` (the repo's own
`build/`, which git ignores; never `~/Applications`): Swift 6.3.3, no
warning, 15 s the first time and 2 s after. `codesign --verify --strict`
passes: ad hoc, identifier `com.kcgx.cockpit`, arm64. The plist reads
back with the repo and the `PATH` it was built with.

**The suite.** `uv run --quiet --group browser pytest -q`: 1199 passed in
617 s, none skipped; 59 of them are new (55 in `tests/test_window.py`, and
two of the page in each browser). The run before it had two failures and
1197 passes: `test_an_emergency_squawk_lights_the_lamp_and_turns_the_row_red`
in Chromium and `test_a_refused_radar_says_so_and_dims_its_lamp` in WebKit.
Both put an aircraft frame into the page by hand and lose it if the demo's
15 s poll lands before the page has shown it; Task 7 met the second one.
Each passed three times running on its own, and nothing here touches what
they test.

**Run once.** The binary was started once, directly, as
`build/KCGX.app/Contents/MacOS/KCGX --port <port>` against a `--demo`
cockpit on a free port, for 13 s, and then killed. Nobody looked at the
window. What the two processes said: the app checked the port's health
and logged `loading http://127.0.0.1:<port>/`; one second later the server
had a page's socket, held from a WebKit networking process; the app was
still up at 12 s; the socket left when the app was killed. So plain http
to `127.0.0.1` is let through by `NSAllowsLocalNetworking`, the page runs,
and its WebSocket connects. It was never opened through `open` or a
`kcgx://` link, which would have made the build folder the Mac's handler
for the scheme.

One run was the allowance, and four small changes came after it, so the
app as committed has been compiled, signed and asked with `--check`, but
not started: the wait for a link when macOS says the launch was not a
plain one; the saved frame applied by name before the window is centred;
Reload reloading whatever page of the server is showing; and a reload
after a crash of the page leaving out the fragment.

The review's fixes came after those, and are likewise compiled, signed
and unstarted: a launch by a link told by its Apple event; Reload ignored
while the launcher runs; and Quit waiting for the launcher. **So nothing
below the `--check` tests is verified at run time.** What the window does
is known from one 13 s run of an earlier build and from reading.

**The table, row by row.**

| Event | Checked |
|---|---|
| `kcgx://show?port=...&fragment=...` | What a link may ask for: by the tests, through `--check` (14 links shown, 30 refused). The health check and the load: by the one run, which takes the same path after the link is read. **Not seen:** a link arriving through `open`; the fragment set on a page already loaded, with the socket kept; the window shown and brought to the front. |
| launched with no URL | **Not run:** it would have started the real cockpit. Its parts were: `bin/kcgx --demo --no-open`, read through a pipe as the app reads it, ends the pipe in 1 s and leaves the server running, and `server.json` holds the port as the app expects. |
| red close button | **Not seen.** |
| Quit | **Not seen.** The run was ended with a kill, which is not a Quit: the demo server was still answering after it, as it should be. |
| the page's power icon | The page's half is tested in Chromium and WebKit: `ended` is posted once, after the server has answered the shut down, and a browser with no such handler is untroubled. **Not seen:** the app exiting on it. |
| a link to anywhere but `127.0.0.1` | **Not seen.** The cockpit page has no link that leaves it today, so there is nothing to press. |
| the title, the frame, black before the page, the inspector, the menu | The frame: after the run the app's defaults held `NSWindow Frame KCGXCockpit = 560 358 1440 932`, a 1440 by 900 window centred on the screen (removed again afterwards). Black before the page: the call it rests on, `_setDrawsBackground:`, exists in this macOS's WebKit. **Not seen:** the rest. |

**For the owner, with the window in front of you.** Build it where you
like (`macos/build.sh` alone builds `~/Applications/KCGX.app`), start
`kcgx --demo --no-open` and open the app at it with
`open -a <app> 'kcgx://show?port=<port>'`:

1. The window is black, then the cockpit; the title reads `KCGX KPDX`
   and follows a change of airport.
2. `open -a <app> 'kcgx://show?port=<port>&fragment=airport%3Dseattle'`
   with the window already open: the airport search opens with `seattle`
   typed, the window comes to the front, and the page does not reload
   (the radar does not draw on again).
3. Cmd-V pastes into the airport search; Cmd-A, Cmd-C, Cmd-X work there.
4. The red button: the window goes, the server keeps answering
   (`kcgx status`); a click on the Dock icon brings the window back as it
   was.
5. View > Reload redraws the page. View > Enter Full Screen, and back.
6. Move and resize the window, quit, open it again: it is where it was.
7. Right click, Inspect Element opens the inspector.
8. The power icon, then SHUT DOWN: the app exits and `kcgx status` says
   not running.
9. Start the demo again, open the app, Cmd-Q: the same.
10. With no cockpit running, `open -a <app> 'kcgx://show?port=1'` and
    `open -a <app> 'kcgx://show?port=<a free port>'`: the window says the
    link is not one it opens, or that nothing answers, and
    `kcgx status` still says not running.
11. Last, with real feeds: quit everything and open KCGX from the Dock or
    Spotlight. It says STARTING THE COCKPIT, then shows it, with audio.
12. The same again, and Cmd-R while it says STARTING THE COCKPIT: nothing
    happens, and `kcgx status` afterwards names one server.
13. The same again, and Cmd-Q while it says STARTING THE COCKPIT: it says
    STOPPING THE COCKPIT, exits once the cockpit has come up (30 s at
    most), and `kcgx status` says not running.

Step 10 is the one that matters most: a refused link must never start the
cockpit, and no test can open the app through a link.

**Two things found on the way.**

- *Building an app in the repo registers it.* Within a minute of the
  first build, and before anything was run, Launch Services listed
  `build/KCGX.app` as the handler for `kcgx:` (seen in `lsregister
  -dump`): macOS registers an app it finds in an indexed folder, and did
  so again within 20 s of a rebuild. It was unregistered each time
  (`lsregister -u`), and with the bundle left where it was it stayed
  unlisted for the ten minutes of the suite. The copies the tests build
  under the system's temporary folder were never listed. Once setup has built
  `~/Applications/KCGX.app`, a copy left in `build/` is a second app with
  the same identifier; delete it. *After review:* the one this task left
  in `build/` has been deleted; it was not listed by `lsregister -dump`.
- *There is already a `~/Desktop/KCGX.app`* on this Mac (identifier
  `com.mikelse.kcgx`, not from this plan, left alone). It does not claim
  the `kcgx:` scheme, but Spotlight will offer two apps called KCGX.
