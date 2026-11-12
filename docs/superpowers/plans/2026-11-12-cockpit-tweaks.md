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
  (`radar.js:264`, `:289`, `:362`, `:445`). Task 11 finds out; the radar must
  measure and draw consistently either way.

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

- [ ] **Tests first.** Expose each tag's lines and box in `debug()`
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
- [ ] **Tags.** Formats: `CALLSIGN` the label; `TYPE`; `SQWK`; `ALT` feet
  or `GND` as now; `GS` `230KT`; `TRK` `270°`; `DIST` `12.4NM`. Empty
  values are skipped. Two or fewer chosen fields join on one line;
  otherwise identity over numbers. The click rectangle
  (`radar.js:452`) covers every line.
- [ ] **One helper paints every box**, always `source-over`:

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

- [ ] **Static labels** (home name, airports, navaids, cities, peaks,
  state names, ring numbers): call `box` on the still layer just before
  the text, when the label's kind is in `box_items`. The collision
  rectangle pushed to `taken` and `placed` is the box, not the text, so
  boxes never overlap and hover covers the box. The box's own alpha does
  not follow the label's hover brightening.
- [ ] **Aircraft tags** cannot be boxed on the moving layer: it reaches
  the screen by addition, and adding black changes nothing. In `frame()`,
  after `drawImage(still)` and before the moving layer is added, paint
  each tag's box straight onto the visible canvas, at the aircraft's own
  alpha (so a dimmed or stale aircraft's box dims with it). `drawMoving`
  returns the rectangles.
- [ ] **HUD.** `applyPrefs` sets `data-box-hud` on `<html>` and four
  custom properties (`--box-fill`, `--box-pad`, `--box-border`,
  `--box-width`); CSS boxes `.hud span` from them, border in
  `color-mix(in srgb, currentColor var(--box-border), transparent)`.
- [ ] Commit `feat(radar): chosen flight tags; boxes behind labels`.

### Task 9: Part 1 by hand

- [ ] `uv run pytest` and the browser group, green.
- [ ] `kcgx --demo`, then walk the [Coverage](#coverage) table line by
  line at 1440 by 900 and 1100 by 760, in WOPR and AMBER, with display
  CRT and OFF.
- [ ] `kcgx` against real feeds and traffic at KPDX: range to 250 and
  back, a 2.5 nm zoom on the runways, boxes on with a busy picture.
- [ ] Note what was seen in the plan's "Built" section, as phases C to E
  did.

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

- [ ] Parametrise the `browser` fixture over `chromium` and `webkit`
  (`uv run playwright install webkit`); each skips when its browser is
  not installed, as Chromium does today.
- [ ] Run the page tests in WebKit and fix what differs. Look first at:
  `ctx.letterSpacing` on the canvas (if WebKit ignores it, labels are
  measured and drawn without it, which is consistent, but check the home
  name's spacing by eye); `<dialog>` and `::backdrop`; the `.jit`
  `drop-shadow` filter on a full-size canvas (frame rate); wheel deltas
  on the radar; `<select>` styling in the config sheet.
- [ ] Commit `test(web): the page in WebKit as well as Chromium`.

### Task 11: KCGX.app

**Files:** `macos/KCGXWindow.swift`, `macos/Info.plist.in`,
`macos/build.sh`, `.gitignore` (`build/`), `main.js`

- [ ] **`macos/build.sh <destination>`** compiles and assembles:

  ```bash
  swiftc -O -framework Cocoa -framework WebKit macos/KCGXWindow.swift -o "$APP/Contents/MacOS/KCGX"
  sed -e "s|@REPO@|$REPO|" -e "s|@PATH@|$PATH|" macos/Info.plist.in > "$APP/Contents/Info.plist"
  codesign --force --sign - "$APP"
  ```

  Ad hoc signed, never notarised: it is built on the machine that runs
  it, so it carries no quarantine flag. The default destination is
  `~/Applications/KCGX.app`.
- [ ] **`Info.plist.in`:** bundle id `com.kcgx.cockpit`, name KCGX,
  `CFBundleURLTypes` registering `kcgx`, `NSAppTransportSecurity` with
  `NSAllowsLocalNetworking`, and two keys of our own filled at build:
  `KCGXRepo` (so the app can run `bin/kcgx`) and `KCGXPath` (a Dock
  launch has no shell `PATH`, and `bin/kcgx` needs `uv`).
- [ ] **The app's behaviour**, one `NSWindow` holding one `WKWebView`:

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
- [ ] **Security:** any web page can open a `kcgx://` link. So the scheme
  carries a port and a fragment and nothing else, the host is always
  `127.0.0.1`, the port must be an integer from 1024 to 65535, and the
  health check must name kcgx before anything loads.
- [ ] `main.js`, in `onEnded`:
  `window.webkit?.messageHandlers?.kcgx?.postMessage("ended")`. A no-op
  in a browser.
- [ ] No unit tests reach Swift. Check by hand, and list each row of the
  table above as checked in the "Built" section.
- [ ] Commit `feat(window): KCGX.app, the cockpit in its own window`.

### Task 12: The launcher opens it; setup builds it

**Files:** `launcher.py`, `setup.sh`, `bin/kcgx` (comment),
`tests/test_launcher.py`, `tests/test_setup.py`

- [ ] **Tests first.** `pick_opener` returns the window opener when the
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
- [ ] `launcher.main(argv, *, opener=None)`: `opener or pick_opener(args)`.
  `--browser` on `kcgx` and `kcgx go`. Help and the module docstring say
  "its own window" where they said "a browser".
- [ ] `setup.sh` step 5 becomes "The launcher on your PATH, and its
  window": after the symlink, on macOS, run `macos/build.sh`. A failed
  build is a warning, never fatal. Still seven steps. Step 7's check adds
  one advisory line: the app is there and `codesign --verify` passes.
- [ ] `--uninstall` paths, if `setup.sh` has them, remove the app.
- [ ] Commit `feat(launcher): kcgx opens its own window`.

### Task 13: The docs

**Files:** `README.md`,
`docs/superpowers/specs/2026-10-18-web-cockpit-design.md`, this plan

- [ ] **README:** "Running it" (the window, `--browser`, close versus
  quit); "The cockpit" (no FEEDS or PALETTE, the icons, lamps and teletype
  off by default, the focused track); "The radar" (range, 2.5 nm, double
  click, tags, boxes); "Configuration" (the CONFIG table from this plan;
  `radar_range_nm` retired from `squelch.toml`, with the date); "When it
  opens on one feed" (choose the airport again); "Install" step 5;
  "Development" (WebKit in the browser group).
- [ ] **Spec:** write the fifteen decisions into their sections, dated
  2026-11-12, as phase E did.
- [ ] Add a "Built" section here: what was done, what was seen by hand,
  the 250 nm frame time, anything deferred.
- [ ] Commit `docs: phase F built`.

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
- Per-item box styles: one fill, padding and border for every boxed item.
- A sticky header on the tracks table.
