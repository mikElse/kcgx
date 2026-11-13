# Web Cockpit Phase G: The 11/12 Tweaks, Round Two

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the owner's second "KCGX Tweaks 11/12" list. The cockpit boots
with a line-drawn animation in the last palette. CONFIG becomes a full-screen
sheet with four tabs and owns a new set of graphics settings. The tracks
table chooses and filters its columns, keeps its header in view, resizes and
collapses, and its sort order sets which aircraft are bright on the radar.
The radar styles every map layer, follows the chosen aircraft at 10 nm with a
data box beside it, zooms in to the runways, fades parked traffic and draws
flight tags over everything. The frequencies pane plays one feed at a time,
picked by a click, under a master mute and volume.

**Source:** "KCGX Tweaks 11/12" (the owner, pasted 2026-11-13). This is the
second list with that title; the first was phase F
(`2026-11-12-cockpit-tweaks.md`). Every line is mapped to a task in
[Coverage](#coverage).

**Architecture:**

| Piece | Job |
|---|---|
| `kcgx.prefs` | a fifth kind, `Table`, for the map's per-layer styles; about forty new keys; a migration for `glow` |
| `kcgx.protocol`, `kcgx.station` | `select` and `master_mute` messages; partial table updates merged; `poll_secs` reaches the radar; a `boot` flag in the first snapshot |
| `squelch.cockpit` | `select(ident)`: this feed audible, every other muted |
| `kcgx.radar`, `kcgx.demo` | more fields from each adsb.lol aircraft; `still` seconds for parked traffic; refresh from prefs |
| `kcgx.names` (new) | feed titles without the airport's code or city |
| `index.html`, `cockpit.css` | the tabbed config sheet; the frequencies header; the tracks pane's grip, collapse and filters; the boot cover |
| `sheets.js` | tabs; a `table` binder for the map styles |
| `frames.js` (new) | one frame clock for every canvas, capped by `fps_max` |
| `radar.js` | layer styles, zoom-scaled fonts, a tag layer on top, follow, a data box, click to centre, tails by time and speed, ground fade, rank shading |
| `tracks.js` | columns by pref, filters, sort in prefs, the rank it publishes for the radar |
| `stack.js` | one expanded feed; no M or S; a click selects |
| `boot.js`, `boot-scene.js` (new) | the animation, ported from `Vector Cockpit Drawing/vector-scene.jsx` to a canvas |

**Tech Stack:** as phase F. No new Python dependency, no npm, no build step.
New font files are vendored WOFF2 with their OFL licences, as B612 Mono and
Share Tech Mono already are.

**Spec:** `docs/superpowers/specs/2026-10-18-web-cockpit-design.md`. This plan
changes "Visual language", "Display effects", "Rendering", "The feed stack",
"Radar" and "Every action is a click"; the last task writes the changes in.

## What was checked before writing this

- **The animation is 140 lines of real scene code inside a design tool's
  runtime.** `Vector Cockpit.dc.html` loads `support.js`, which fetches React
  18.3.1, ReactDOM and Babel standalone from unpkg and compiles the `.jsx` in
  the browser. The scene is `vector-scene.jsx`; `animations-v3.jsx` is the
  tool's generic engine, of which only `clamp` and five easings are used.
  `Vector Cockpit v1.dc.html` is an older 4:3 version without the tower and
  is ignored. The `uploads/` images are reference pictures; nothing loads
  them. There is no sound.
- **The animation runs 21.7 s and loops.** Scenes: Draw 0 to 3 s, Takeoff 3
  to 6, Turn 6 to 9.2, Tower 9.2 to 12.2, Lights 12.2 to 17.2, Outro 17.2 to
  21.7. Everything is a function of one time `T`, so it ports as a pure
  `frame(ctx, T, colours)`.
- **Its colours are one hard-coded object** (`vector-scene.jsx:16`), which
  maps onto the page's palette variables:

  | role | hex | becomes |
  |---|---|---|
  | bg | `#05070c` | `--wall` |
  | sky (buildings) | `#3fb4dc` | `--cyan` |
  | horizon | `#2b6f86` | `--dim` |
  | dome | `#e06cc0` | `--pink` |
  | runway edges | `#e2604c` | `--alarm` (in AMBER and MATRIX that is white; use `--frame` if it reads wrong) |
  | runway centre | `#4a6be0` | `--blue` |
  | thresholds, tower, letters | `#e8ecf2` | `--white` |
  | lights, panes | `#e8a83c`, `#f2b958` | `--amber` |
  | the four window panes | `#9a62a8`, `#e06cc0`, `#3fb4dc`, `#f2b958` | `--pink` at 60 %, `--pink`, `--cyan`, `--amber` |

- **One feed is already audible at launch** (`runtime.build_sessions`: all
  muted but the configured or preferred one). "One feed at a time" is
  keeping that true after launch, not a new start-up rule.
- **Feed titles carry the airport two ways.** The cached listings: `KPDX
  Tower (Both)`, `KSEA Ground` (the ICAO, which `session.strip_icao` already
  drops), and `Chicago Approach (10R/28C)` at KORD and KMDW, `Seattle Center`
  at KSEA (the city, which nothing drops). The dataset's `where` for those
  airports is `Chicago, IL` and `Seattle, WA`. `ZSE Seattle Center` at KPDX
  names another city and stays.
- **The aircraft frame has twelve fields** (`radar.py:290-320`): `hex`,
  `label`, `type`, `lat`, `lon`, `alt`, `gs`, `trk`, `sq`, `age`, `dist`,
  `brg`. adsb.lol's replies carry more (readsb's `r`, `desc`, `ownOp`,
  `baro_rate`, `alt_geom`, `category`, `nav_altitude_mcp`, …). **Not
  checked:** which of them `/v2/point` actually returns. Task 7 reads the
  OpenAPI document (`https://api.adsb.lol/api/openapi.json`) and keeps only
  the fields it promises.
- **Runways are centrelines only.** `tools/build_geodata.py:258` keeps the
  two ends from OurAirports' `runways.csv` and drops `width_ft`. Thick, true
  width runways need that column, so the map has to be rebuilt; the code must
  work with the old map too (Task 10).
- **The airport dataset has no elevation.** `airports.csv` is
  `icao,iata,name,city,region,country,lat,lon,size`. The ground fade compares
  barometric altitude, which is above sea level (decision 9).
- **The tracks table's sort is page state today** (`tracks.js:21`), and the
  title bar is the strip at the bottom of each pane (`cockpit.css:150`).
- **Map layers have no show or hide.** Their styles are one literal table in
  `drawStatic` (`radar.js:404-414`); places, rings, runways and the home ring
  are styled by constants beside their own drawing code.
- **Frame rate is uncapped**: `radar.js` and `stack.js` each run their own
  `requestAnimationFrame` loop. Persistence (the burn-in) fades the moving
  layer by a fixed 0.45 a frame (`radar.js:819`), so it already looks
  different at 60 and 120 Hz.
- **Canvas 2D cannot draw lines without anti-aliasing.** There is no switch
  for it; `imageSmoothingEnabled` affects only `drawImage`. See decision 6.
- **The view never follows anything and never animates**: every change is a
  jump (`radar.js:267`, `926-977`).

## Decisions this plan makes that the list did not

The first six are the ones most worth the owner's eye before work starts.

1. **The boot animation plays once per launch, whole (21.7 s), and any key or
   click skips it.** "Once per launch" is the first page the server serves
   after it starts: the first snapshot it sends carries `boot: true`, every
   later one `false`. A reload, a second tab or the window reopened does not
   replay it. A setting turns it off (`boot_anim`), and the OS's reduced
   motion skips it. The page under it connects and fills in while it plays,
   so skipping lands on a cockpit already live.
2. **CONFIG full-screen covers the radar.** Phase F docked it right with a
   clear backdrop so changes could be watched; the list asks for centred and
   full-screen, and that wins. The sheet is opaque, Escape and CLOSE leave it,
   and it remembers the last tab within the page.
3. **A feed is picked like a radio button.** Clicking a feed makes it the one
   audible feed; clicking the one already playing does nothing. Silence is the
   new master mute, which keeps the picked feed and the volume as they were
   and is not a pref (it is audio state, like the volume). The volume slider
   moves from CONFIG into the frequencies pane and leaves CONFIG.
4. **Filters belong to the table; the sort belongs to both.** A filter hides
   rows and never touches the radar. The sort order ranks every aircraft,
   filtered or not, and the radar shades and stacks by that rank. Filters are
   page state (gone on reload, so nothing is hidden at the next launch for a
   reason nobody remembers); the sort column, direction and visible columns
   are prefs.
5. **Rank shading is linear from the top row to a floor.** The first row of
   the sort is full brightness and drawn on top; the last is `sort_floor` %
   (default 40) and drawn underneath. The focused aircraft is always first.
   Within the radar's glow batches, z-order holds within a colour (cyan under
   alarm under pink, as now); tags, drawn on their own layer (decision 8),
   follow rank exactly.
6. **"Anti-aliasing" is a render scale.** OFF draws the radar and the traces
   at half resolution and scales them up with `image-rendering: pixelated`
   (hard, stepped lines); ON draws at the display's resolution (today); SUPER
   draws at twice it and lets the browser scale down (smoother, four times the
   pixels). The boot animation follows the same setting.
7. **Tail brightness is three bands.** Below `tail_gs_low` knots a tail is
   drawn at `tail_alpha_min`, above `tail_gs_high` at `tail_alpha_max`, and
   between, or when the speed is unknown, at `tail_alpha` (the default). The
   fade along the tail's length stays. Tail length is in seconds, not points,
   so it holds when the poll rate changes.
8. **Flight tags move to a layer of their own, drawn last and drawn
   normally**, not added. Tag boxes go down first on that layer, then the
   text, so a tag and its box sit over map lines, other aircraft and other
   trails. Tags no longer leave a persistence trail of their own.
9. **Parked traffic is judged on what the aircraft reports.** An aircraft is
   still when its ground speed is under `ground_gs` and it reports `GND` or a
   barometric altitude under `ground_alt` feet. That altitude is above sea
   level (the dataset has no field elevation), so at a high field keep
   `ground_alt` at 0, where only `GND` counts. The server counts how long each
   track has been still (`still` seconds in the frame), so every tab agrees
   and a reload does not restart the clock. After `ground_min` minutes it
   fades to `ground_alpha` % or hides, per `ground_mode`. The table is not
   affected; its filters are for that.
10. **Selecting an aircraft moves the view to it at `follow_nm` (10) and
    follows it.** A drag stops the following and keeps the focus; a double
    click recentres on the airport as now; unfocusing eases back to the view
    from before the focus. View moves ease over 400 ms unless `view_ease` is
    OFF.
11. **The data box shows the table's visible columns, in the table's order**,
    as `NAME: VALUE` lines, beside the focused aircraft on its left, or on its
    right when the left would leave the radar. It is a DOM overlay, so it is
    sharp at any render scale and takes the UI font.
12. **"Clicking map elements" is symbols and labels**: the home ring,
    airports, navaids, cities, peaks and state names. Lines (coasts,
    airspace, airways) are not targets. A click on one eases the view to
    centre it and keeps the zoom.
13. **Label sizes follow the zoom between a floor and a ceiling.** Each layer
    has a default size (the map table's LABEL column; the tag size for tags),
    which is the size at the view the range sets. Zooming in by k grows it by
    `k^0.35`, zooming out shrinks it the same way, and the result is held
    between `label_min` and `label_max`.
14. **The radar zooms in to 0.25 nm.** Runways become solid and as wide as
    they are (`width_ft`, or 150 ft where the map has none), never thinner
    than their width on the map table. The home ring keeps its 24 to 64 px.
15. **Glow is three numbers**, map, traffic and text, 0 to 100 (0 to 12 px of
    blur). A stored `glow` of OFF, LOW or FULL becomes 0, 33 or 75 in all
    three. Burn-in is time based: `burn_in` is the half-life of the moving
    layer's fade, so it looks the same at any frame rate; the default matches
    today's look at 60 Hz.
16. **The poll interval cannot go below 15 s.** adsb.lol asks for no more
    than one request every 15 s; the setting runs 15 to 120 in steps of 5, and
    the existing back-off still doubles it on failures.
17. **Fonts are vendored, never fetched.** FONT offers CLASSIC (today's pair:
    B612 Mono for text, Share Tech Mono for titles and the radar), each of
    B612 MONO, SHARE TECH MONO, IBM PLEX MONO, JETBRAINS MONO and VT323 for
    everything, and SYSTEM (`ui-monospace, Menlo`). All are monospaced and
    OFL. FONT SIZE sets the base text size (13 px today) and UI ZOOM scales
    the whole page (CSS `zoom`); neither changes radar label sizes, which
    have their own.
18. **The tracks pane's height is a pref in percent of the page** (10 to 80,
    default 24, the `24vh` of today). Dragging previews locally and sends on
    release. Collapsed, only its title bar shows and the radar takes the rest.
    In the one-column layout (under 1100 px) there is no grip; collapse still
    works.
19. **Feed titles lose the airport's ICAO, IATA and city as whole words**,
    anywhere in the title, case-insensitive, with spaces tidied. If nothing
    would be left, the title stays as it was. A setting (`short_names`) turns
    it off.
20. **The airport picker is 840 px wide** (50 % over 560), fixed height
    (`min(80vh, 720px)`), centred, and does not grow or shrink with its
    results.
21. **"Radar movement behaviour" is three settings**: aircraft MOTION
    (GLIDE, dead-reckoned between polls as now, or STEP, jump at each poll),
    VIEW MOVES (OFF, QUICK 250 ms, SMOOTH 600 ms) and ZOOM SPEED (25 to 400 %
    of today's wheel rate).
22. **The `Vector Cockpit Drawing/` folder stays out of the repo.** It holds
    the design tool's runtime, a 1.5 MB photo and other references; the port
    cites `vector-scene.jsx` by line. The owner decides whether to keep it, add
    it to `.git/info/exclude`, or commit `vector-scene.jsx` alone under
    `docs/`.

## Global Constraints

- Work in the `feat/web-cockpit` worktree at `/Users/mikelse/kcgx_web`.
- **No new Python dependency**, no npm, no CDN at run time.
- **No test touches the network, ffmpeg or an audio device**, and none writes
  to `~/.local/state/kcgx/`, `~/.cache/squelch/` or `~/Applications/`, as in
  phase F. Page tests run with `boot_anim: false` written to their prefs file
  (conftest), except the boot tests.
- **Tests first** in every task: the failing test, seen failing, then the
  code, then `uv run pytest` (and the `browser` group for page work), then
  the commit.
- **The page changes nothing itself.** Every setting is a `prefs` message;
  the page redraws from the server's `prefs` frame. The exceptions are view
  state: pan, zoom, follow, filters, the open config tab, and a drag in
  progress.
- **Ids that tests and `kcgx go` rely on stay**: `#open-airport`,
  `#open-config`, `#open-shutdown`, `#airport-sheet`, `#airport-query`,
  `#airport-results`, `#radar`, `#tracks-body`, `#tracks-head`, `#icao`,
  `#volume`. `#freq-counts` goes (Task 6) and its tests change with it.
- `tests/test_page_prefs.py` keeps holding the markup to the schema, tables
  included.
- Both browsers: every page test runs in Chromium and WebKit, as since
  Task 10 of phase F.
- One commit per task, in the repo's style.

## File Structure

```
src/kcgx/prefs.py                 Table kind, new keys, glow migration
src/kcgx/protocol.py              select, master_mute; table prefs; boot in snapshot; volume frame carries muted
src/kcgx/station.py               select, master mute, poll_secs, deep merge of tables, boot flag
src/kcgx/names.py                 new: short_feed_name
src/kcgx/radar.py                 more fields, still seconds, set_refresh
src/kcgx/demo.py                  the new fields; two parked aircraft
src/kcgx/hub.py                   first client gets boot: true
src/squelch/cockpit.py            select
src/squelch/mixer.py              master mute
tools/build_geodata.py            runway width_ft (map rebuild: Task 10)
src/kcgx/data/geo.json.gz         rebuilt with widths (if the rebuild can run)
src/kcgx/web/index.html           tabs, freq header, tracks grip and filters, boot cover, data box
src/kcgx/web/static/cockpit.css   all of the above; fonts; zoom; sticky header
src/kcgx/web/static/fonts/        + IBM Plex Mono, JetBrains Mono, VT323 (WOFF2 + OFL)
src/kcgx/web/static/js/frames.js  new: the capped frame clock
src/kcgx/web/static/js/boot.js    new: cover, playback, skip, fade in
src/kcgx/web/static/js/boot-scene.js new: path data and frame(), from vector-scene.jsx
src/kcgx/web/static/js/main.js    applyPrefs for the new keys; boot; zoom; font
src/kcgx/web/static/js/sheets.js  tabs; table binder; airport sheet size
src/kcgx/web/static/js/store.js   defaults; trails by time; master mute
src/kcgx/web/static/js/theme.js   glow by layer; render scale
src/kcgx/web/static/js/status.js  clock formats
src/kcgx/web/static/js/stack.js   one feed, select, header
src/kcgx/web/static/js/tracks.js  columns, filters, sort prefs, rank, resize, collapse
src/kcgx/web/static/js/radar.js   most of Part 4
tests/test_prefs.py, test_protocol.py, test_station.py, test_radar.py, test_demo.py,
tests/test_cockpit.py, test_mixer.py, test_hub.py, test_build_geodata.py   updated
tests/test_names.py               new
tests/test_page_prefs.py          tables, tabs
tests/test_page.py                updated; new page tests per task
tests/test_boot.py                new (browser)
```

## The settings

New and changed keys, as Task 1 writes them. Existing keys not listed keep
their phase F definitions. Numbers are integers; "tenths" means the stored
value is ten times the pixels.

**General tab**

| key | kind | values | default | row |
|---|---|---|---|---|
| `boot_anim` | flag | | true | BOOT ANIMATION |
| `ui_zoom` | number | 50 to 200 (%), step 5 | 100 | UI ZOOM |
| `font` | choice | CLASSIC, B612, SHARETECH, PLEX, JETBRAINS, VT323, SYSTEM | CLASSIC | FONT |
| `font_px` | number | 10 to 20 | 13 | FONT SIZE |
| `clock_24h` | flag | | true | 24-HOUR LOCAL |
| `clock_seconds` | flag | | false | SECONDS |
| `clock_zone` | flag | | true | ZONE NAME |
| `palette`, `display`, `scan_opacity`, `scan_size` | | as phase F | | THEME, DISPLAY, SCANLINES |
| `glow_map` | number | 0 to 100 | 33 | GLOW: MAP |
| `glow_traffic` | number | 0 to 100 | 33 | GLOW: TRAFFIC |
| `glow_text` | number | 0 to 100 | 33 | GLOW: TEXT |
| `aa` | choice | OFF, ON, SUPER | ON | ANTI-ALIASING |
| `burn_in` | number | 0 to 100 | matches today at 60 Hz (Task 4 sets it) | BURN-IN |
| `fps_max` | number | 15 to 120; 120 is the display's own rate | 60 | MAX FRAME RATE |
| `poll_secs` | number | 15 to 120, step 5 | 15 | RADAR POLL |
| `motion` | choice | GLIDE, STEP | GLIDE | AIRCRAFT MOTION |
| `view_ease` | choice | OFF, QUICK, SMOOTH | QUICK | VIEW MOVES |
| `zoom_speed` | number | 25 to 400 (%) | 100 | ZOOM SPEED |
| `lamps`, `teletype` | | as phase F | | LAYOUT |

`glow` (the phase F choice) leaves the schema; `read_prefs` migrates it.

**Traffic tab**

| key | kind | values | default | row |
|---|---|---|---|---|
| `range_nm`, `tag_fields`, `box_*` | | as phase F | | |
| `map` | table | rows and columns below | today's look | MAP LAYERS (a grid) |
| `label_min` | number | 6 to 20 (px) | 9 | LABEL MIN |
| `label_max` | number | 12 to 48 (px) | 26 | LABEL MAX |
| `tag_px` | number | 10 to 28 (px) | 16 | TAG SIZE |
| `follow_nm` | number | 1 to 50 | 10 | FOLLOW RADIUS |
| `info_box` | flag | | true | DATA BOX |
| `tail_secs` | number | 0 to 600, step 15 | 180 | TAIL LENGTH |
| `tail_alpha` | number | 0 to 100 | 95 | TAIL DEFAULT |
| `tail_alpha_min` | number | 0 to 100 | 35 | TAIL SLOW |
| `tail_alpha_max` | number | 0 to 100 | 95 | TAIL FAST |
| `tail_gs_low` | number | 0 to 600 (kt) | 40 | SLOW BELOW |
| `tail_gs_high` | number | 0 to 600 (kt) | 250 | FAST ABOVE |
| `ground_mode` | choice | SHOW, FADE, HIDE | FADE | PARKED TRAFFIC |
| `ground_gs` | number | 0 to 50 (kt) | 5 | BELOW SPEED |
| `ground_alt` | number | 0 to 5000 (ft), step 100 | 0 | BELOW ALTITUDE |
| `ground_min` | number | 0 to 30 (min) | 2 | AFTER |
| `ground_alpha` | number | 0 to 100 | 25 | FADE TO |

The `map` table. Columns: `show` (flag), `alpha` (0 to 100), `line` (SOLID,
DASH, DOT), `width` (tenths, 5 to 80), `label` (px, 8 to 32). A row has only
the columns that mean something for it; the defaults are what
`radar.js` draws now.

| row | show | alpha | line | width | label |
|---|---|---|---|---|---|
| COAST | on | 100 | SOLID | 18 | |
| LAKE | on | 75 | SOLID | 12 | |
| RIVER | on | 50 | SOLID | 10 | |
| COUNTRY | on | 90 | DASH | 12 | |
| STATE | on | 55 | SOLID | 10 | |
| AIRWAY | on | 70 | DASH | 12 | |
| CLASS_B | on | 90 | DASH | 14 | |
| CLASS_C | on | 80 | DASH | 13 | |
| CLASS_D | on | 45 | DOT | 10 | |
| RUNWAYS | on | 100 | | 16 | |
| RINGS | on | 35 | SOLID | 10 | 12 |
| HOME | on | 100 | | 18 | 30 |
| AIRPORTS | on | 85 | | 13 | 13 |
| NAVAIDS | on | 85 | | 13 | 13 |
| CITIES | on | 85 | | 13 | 13 |
| PEAKS | on | 85 | | 13 | 13 |
| STATE_NAMES | on | 100 | | | 14 |

Label alpha stays `LABEL_ALPHA` (0.4, brightening on hover) times the row's
alpha. Class D's dash today is `[3, 5]` and reads as DOT; Task 10 checks the
three patterns against the current pixels at width 1.

**Tracks tab**

| key | kind | values | default | row |
|---|---|---|---|---|
| `track_cols` | subset | CALLSIGN, TYPE, REG, ALT, VS, GS, TRK, DIST, BRG, SQWK, HEX, DESC, OPER, CAT, AGE, LAT, LON | CALLSIGN, TYPE, ALT, GS, TRK, DIST, SQWK | COLUMNS |
| `track_sort` | choice | the same names | DIST | SORT BY |
| `track_desc` | flag | | false | DESCENDING |
| `sort_floor` | number | 0 to 100 | 40 | DIMMEST (RADAR) |
| `tracks_open` | flag | | true | (the pane's collapse button) |
| `tracks_pct` | number | 10 to 80 | 24 | (the pane's grip) |

Task 7 may drop names from `track_cols` that `/v2/point` does not return.

**Frequencies tab**

| key | kind | values | default | row |
|---|---|---|---|---|
| `short_names` | flag | | true | DROP THE AIRPORT FROM NAMES |

Master mute and volume are not prefs; they live in the pane's header.

---

# Part 1: settings and the sheet

### Task 1: The schema, round two

**Files:** `src/kcgx/prefs.py`, `src/kcgx/protocol.py`, `src/kcgx/station.py`,
`store.js`, `tests/test_prefs.py`, `tests/test_protocol.py`,
`tests/test_station.py`, `tests/conftest.py`

- [ ] **Tests first.** `test_prefs.py`: the defaults are the tables above. A
  `Table` reads back; an unknown row, an unknown column, a column a row does
  not have, and a cell that fails its spec each drop only that cell in
  `clean` and refuse the whole message in the protocol (`BadMessage` naming
  `map.COAST.alpha`). A partial table (`{"COAST": {"alpha": 60}}`) is legal
  on the wire, and `Station.set_prefs` merges it cell by cell, so two tabs
  changing two cells both land. A stored `"glow": "FULL"` reads as 75 in the
  three glow keys; a stored `glow_map` beats the migration. `conftest`'s page
  server writes `{"boot_anim": false}` to its prefs file.
- [ ] **`Table`:**

  ```python
  @dataclass(frozen=True)
  class Table:
      columns: dict[str, Choice | Flag | Number]
      rows: dict[str, dict[str, Any]]  # row -> its defaults; its keys are the columns it has

      def check(self, value: Any) -> dict:
          """A partial table: any rows, any of each row's own columns."""
          if not isinstance(value, dict):
              raise ValueError("must be an object of rows")
          out = {}
          for row, cells in value.items():
              if row not in self.rows or not isinstance(cells, dict):
                  raise ValueError(f"has no row {row}")
              out[row] = {}
              for col, cell in cells.items():
                  if col not in self.rows[row]:
                      raise ValueError(f"{row} has no {col}")
                  out[row][col] = self.columns[col].check(cell)
          return out

      @property
      def default(self) -> dict:
          return {row: dict(cells) for row, cells in self.rows.items()}
  ```

  `clean` walks cells and keeps those that pass. `DEFAULTS["map"]` is the full
  table; `write_prefs` writes it whole. `merge(prefs, changes)` in
  `prefs.py` merges tables a cell at a time and replaces everything else;
  `Station.set_prefs` uses it.
- [ ] **The migration** runs in `read_prefs` before `clean`: `glow` →
  `glow_map`, `glow_traffic`, `glow_text` unless those are stored.
- [ ] All the other keys from [The settings](#the-settings). `store.js`
  defaults match. Nothing reads them yet.
- [ ] Commit `feat(prefs): a table kind, and the round two settings`.

### Task 2: CONFIG full-screen, in tabs; the airport picker fixed

**Files:** `index.html`, `cockpit.css`, `sheets.js`,
`tests/test_page_prefs.py`, `tests/test_page.py`

- [ ] **Tests first.** `test_page_prefs.py`: every schema key has exactly one
  `[data-pref]` control, except `tracks_open` and `tracks_pct`, which are
  bound by the tracks pane (Task 9) and listed as such; each control sits in
  the tab its table above names; a `table` control declares the schema's rows
  in order and, per row, exactly its columns, with matching ranges and names.
  Browser: `#config-sheet` fills the viewport less a 16 px margin and is
  centred (within 1 px) at every size in `SIZES`; four tabs, `role="tablist"`,
  arrow keys move between them, the first opens on GENERAL and the sheet
  reopens on the last one used; one cell of the map grid round trips to a
  second tab's `store.state.prefs.map`; `#volume` is not in the sheet.
  `#airport-sheet` is 840 px wide (or the viewport less 32 px), its height
  does not change between no results and forty, and it is centred.
- [ ] **Tabs** are buttons over four `<section role="tabpanel">`s; the
  existing rows move into them as the settings tables say. The OUTPUT section
  goes. A `data-kind="table"` control is a `<table>` whose rows and columns
  come from `data-rows` and `data-columns`, and whose cells are bound with the
  same binders as single controls, each sending
  `{t: "prefs", map: {ROW: {col: value}}}`.
- [ ] **CSS:** `#config-sheet { inset: 0; margin: auto; width: calc(100vw - 32px); height: calc(100vh - 32px); max-width: none; max-height: none; }`,
  `#config-sheet::backdrop { background: rgb(0 0 0 / 0.85); }`. Tab panels
  scroll; the tab bar and CLOSE do not.
  `#airport-sheet { width: min(840px, calc(100vw - 32px)); height: min(80vh, 720px); }`
  with its results scrolling inside.
- [ ] Commit `feat(web): config is a full-screen sheet in four tabs`.

### Task 3: General: zoom, font, size, clocks

**Files:** `cockpit.css`, `main.js`, `status.js`, `radar.js` (font only),
`static/fonts/`, `tests/test_page.py`

- [ ] **Tests first.** `ui_zoom: 150` makes `#icao`'s rendered height 1.5
  times what it was (within 1 px), and a click at an aircraft's chevron on
  the radar still focuses it (pointer maths survive CSS `zoom` in both
  engines). `font_px: 16` makes a tracks cell's computed font size 16 px.
  Each `font` value sets the computed `font-family` of `body` and of
  `.title-text`, and `document.fonts.check` is true for it after load; the
  radar's `debug().font` names it. The clock: 12-hour reads `3:07 PM`,
  seconds add `:SS` to both clocks, `clock_zone: false` drops the zone.
- [ ] **Fonts.** Vendor IBM Plex Mono 400, JetBrains Mono 400 and VT323 400,
  latin subset, as WOFF2 with their OFL texts, from the fontsource packages
  (fetched once by the implementer, by hand; not at run time).
  `--font-text` and `--font-display` custom properties replace the two
  literal families in `cockpit.css`; `applyPrefs` sets them. `radar.js` reads
  `--font-display` in place of its `FONT` constant and marks the static layer
  dirty when it changes.
- [ ] **Zoom** is `zoom: calc(var(--ui-zoom) / 100)` on `.page` and on each
  `<dialog>`. Check `radar.js`'s `local()`: if a browser reports pointer
  coordinates and `getBoundingClientRect` in different spaces under `zoom`,
  divide by the zoom there. Record what each engine did in the task's notes.
- [ ] **Font size:** the body's `13px` becomes `var(--font-px)`; sizes that
  are relative to it today stay relative. Title and big figures stay fixed.
- [ ] Commit `feat(web): zoom, font and size for the page; clock formats`.

### Task 4: Graphics: frame rate, render scale, glow, burn-in, poll, motion

**Files:** `frames.js` (new), `radar.js`, `stack.js`, `theme.js`, `main.js`,
`cockpit.css`, `src/kcgx/radar.py`, `src/kcgx/station.py`,
`tests/test_radar.py`, `tests/test_station.py`, `tests/test_page.py`

- [ ] **Tests first.** Python: `Radar.set_refresh(30)` sets the base delay,
  keeps the back-off rules, never triggers a poll; a `poll_secs` change
  reaches it through `Station.set_prefs`; 10 is refused by the schema. Page:
  with `fps_max: 15`, the radar draws between 13 and 16 frames in a second
  (count `debug().frames`); with 120, as many as the browser gives. `aa: OFF`
  makes the radar canvas's backing store half the CSS size times the device
  ratio and its computed `image-rendering` `pixelated`; SUPER, twice. Each
  glow number changes only its own layer (`debug().blur` per layer; the
  feed name's computed `text-shadow` for text). With `burn_in: 0` a moved
  aircraft leaves no trace in the next frame; at the default, the trace's
  half-life is the same at `fps_max` 30 and 60 (within a frame). `motion:
  STEP`: between polls an aircraft's drawn position does not change.
  `zoom_speed: 200` doubles the zoom per wheel step.
- [ ] **`frames.js`**: one `requestAnimationFrame` loop; `onFrame(fn)`
  registers a callback; callbacks run only when at least `1000 / fps_max` ms
  (less 1 ms of slack) have passed since the last run. `radar.js`,
  `stack.js` and `boot.js` use it in place of their own loops.
- [ ] **Render scale** in `theme.js`: `renderScale()` is 0.5, 1 or 2 by
  `aa`; every canvas sizes its backing store by `devicePixelRatio *
  renderScale()`.
- [ ] **Glow**: `glowBlur(layer)` is `prefs["glow_" + layer] * 12 / 100`
  px; the CSS `--glow` text shadow is built from `glow_text`.
  `[data-glow]` selectors in the stylesheet become the custom property.
- [ ] **Burn-in**: the moving layer's fade becomes
  `1 - 0.5 ** (elapsed_ms / half_life_ms)`, half-life from `burn_in`. Pick the
  mapping so the default matches 0.45 a frame at 60 Hz, and say which in the
  commit.
- [ ] **Motion**: STEP draws `ac.lat/lon` as polled; GLIDE reckons as now.
- [ ] Commit `feat(web): frame rate, render scale, glow by layer, burn-in by time`.

### Task 5: Performance

**Files:** `radar.js`, `tests/test_page.py`

The list asks to "look into improving performance in general". Phase F left
two costs open (its "Not in this plan"):

- [ ] **Measure first**, as phase F did (600 aircraft injected, 250 nm,
  1440 by 900, 1x and 2x, both engines, glow at default), and write the
  numbers into this task. Also the static layer while panning.
- [ ] **The static layer's glow per colour**, as Task 10 of phase F did for
  aircraft: draw every line of a colour bare on a scratch canvas, then once
  onto `still` with the shadow.
- [ ] **During a pan or zoom, move the bitmap**: draw the last `still`
  transformed by the gesture's offset and scale, and redraw it properly 120
  ms after the gesture stops (and at once on release).
- [ ] **Cull**: skip aircraft, trail segments and tags wholly off the screen
  (with a tag's width of margin).
- [ ] Measure again; record both columns. The page must look the same when
  still: a screenshot diff of the demo at rest under 0.1 % of pixels.
- [ ] Commit `perf(radar): glow per colour on the map; cheap pans; cull`.

---

# Part 2: frequencies

### Task 6: One feed at a time; the pane's header

**Files:** `src/squelch/cockpit.py`, `src/squelch/mixer.py`,
`src/kcgx/protocol.py`, `src/kcgx/station.py`, `src/kcgx/names.py` (new),
`stack.js`, `index.html`, `cockpit.css`, `store.js`, `tests/test_cockpit.py`,
`tests/test_mixer.py`, `tests/test_protocol.py`, `tests/test_station.py`,
`tests/test_names.py` (new), `tests/test_page.py`

- [ ] **Tests first, Python.** `Cockpit.select("b")` leaves only `b`
  audible, cancels any solo, reconciles streams (a parked `b` is started and
  another parked to keep the count), emits a `feed` frame for every changed
  session and reorders at once; `select` of the audible feed changes nothing
  and emits nothing. `{"t": "select", "ident": …}` parses;
  `{"t": "master_mute", "on": true}` parses, `on` must be a boolean. The
  mixer with `master_muted` renders silence and keeps `volume`; the volume
  frame and the snapshot carry `muted`. `short_feed_name`:

  | label | airport | result |
  |---|---|---|
  | `Chicago Approach (10R/28C)` | KORD, ORD, Chicago | `Approach (10R/28C)` |
  | `ZAU Chicago Center` | KORD | `ZAU Center` |
  | `KPDX Tower (Both)` | KPDX, PDX, Portland | `Tower (Both)` |
  | `Seattle Center` | KSEA, SEA, Seattle | `Center` |
  | `ZSE Seattle Center` | KPDX | unchanged |
  | `Chicago` | KORD | unchanged (nothing left) |
  | `Chicago O'Hare Tower` | KORD | `Tower` |
  | `Seattle–Tacoma Ground` | KSEA | `Ground` |

  The city is the part of `where` before the comma. The airport's own name
  is also stripped when it heads the title: its words up to the first of
  International, Regional, Airport, Field or Municipal (`Chicago O'Hare`,
  `Seattle–Tacoma`), tried before the city so the longer match wins. The
  last two rows are made up; the others are from the cached listings in
  `~/.cache/squelch/`, copied into the test as literals (the test reads no
  cache).
- [ ] **Server.** `Cockpit.select`; `mixer.master_muted`; `Station.handle`
  for both; `feed_view` adds `title` (the short name when `short_names`,
  otherwise `name`), recomputed on airport change and on that pref changing
  (send every feed again). `mute` and `solo` stay in the protocol for
  `/debug`; the page stops sending them.
- [ ] **Tests first, page.** No `M` or `S` button anywhere in the stack.
  Exactly one `.feed.expanded`. Clicking a compact feed sends `select` and,
  once the frame lands, that feed is the expanded one; clicking the expanded
  one sends nothing. The expanded row's head reads name, chatter `NN%`,
  status glyph, left to right, with the chatter's right edge 4 to 12 px from
  the glyph's left, as in a compact row; there is no "CHATTER" text. The
  trace is 60 px tall. `.feed-name`'s computed `letter-spacing` is under
  0.06 em. `#freq-counts` is gone; `#freq-head` holds a mute button
  (`aria-pressed`, speaker icon, crossed when muted) and `#volume` with its
  readout; the mute round trips to a second tab. The names are titles:
  in the demo, a feed labelled with the demo airport's city reads without it.
- [ ] **Page.** `stack.js`: the expanded row is the feed that is not muted;
  the compact rows are buttons that `select`. `.trace { height: 60px; }`;
  `.feed-name { letter-spacing: 0.04em; }`. The header is
  `[mute] [volume slider] [NN%]`; the volume binding moves from
  `sheets.js` to `stack.js` unchanged.
- [ ] Commit `feat(audio): pick one feed; a master mute; titles without the airport`.

---

# Part 3: tracks

### Task 7: Everything adsb.lol says about an aircraft

**Files:** `src/kcgx/radar.py`, `src/kcgx/demo.py`, `src/kcgx/prefs.py` (if
names drop), `tests/test_radar.py`, `tests/test_demo.py`

- [ ] **Check the API first.** Read the OpenAPI document and write down, in
  this task, which of these `/v2/point` promises: `r` (REG), `desc` (DESC),
  `ownOp` (OPER), `baro_rate` (VS), `category` (CAT), `seen_pos` (AGE, kept
  already). LAT, LON, BRG, HEX are ours. Drop from `track_cols` any it does
  not promise.
- [ ] **Tests first.** `merge` keeps each promised field, upper-cased text,
  rounded numbers, `None` when missing; the frame carries them under short
  keys (`reg`, `desc`, `oper`, `vs`, `cat`). A track whose speed is under
  `ground_gs` and that reports `GND` (or an altitude under `ground_alt`) has
  `still` counting up in seconds from the poll it first qualified; one poll
  that fails the test resets it to 0. The radar takes the three `ground_*`
  values from the station as it takes the range.
- [ ] **Demo**: every new field on every leg; two aircraft parked at the
  field (`GND`, 0 kt) from the first poll, so the fade can be seen after
  `ground_min`.
- [ ] Commit `feat(radar): every field adsb.lol gives; how long a track has stood still`.

### Task 8: The table: columns, filters, sort, a fixed header

**Files:** `tracks.js`, `index.html`, `cockpit.css`, `tests/test_page.py`

- [ ] **Tests first.** The header shows exactly `track_cols`, in schema
  order; a COLUMNS button in the tracks title bar opens a checklist of every
  column that round trips `track_cols`. A row of filters under the header:
  text columns (CALLSIGN, TYPE, REG, SQWK, HEX, DESC, OPER, CAT) match a
  case-insensitive substring; number columns (ALT, VS, GS, TRK, DIST, BRG,
  AGE, LAT, LON) take `min`/`max` (either may be empty; ALT reads `GND` as
  0). Filtering hides rows only: `debug().hits` still has every aircraft. A
  CLEAR control empties every filter. Clicking a header sends `track_sort`
  and `track_desc`, and a second tab sorts the same. Scrolled 500 px down a
  table of 200 injected aircraft, the header's top is at the body's top
  (within 1 px) and opaque (a pixel under it is the header's background).
  The focused aircraft still leads, and passes the filters whatever they say.
- [ ] **Columns** are one table of definitions, as `COLUMNS` is now, keyed by
  the schema's names, each with its title, text, sort value and filter kind.
- [ ] **Sticky header:** `.tracks thead th { position: sticky; top: 0; background: #000; z-index: 1; }`,
  the filter row stuck under it.
- [ ] **Rank**: after sorting (filters not applied), `tracks.js` publishes
  `rank: Map<hex, 0..1>` (0 for the first) on the store, and emits
  `"rank"`. The radar reads it in Task 13.
- [ ] Commit `feat(tracks): choose, filter and sort columns; the header stays`.

### Task 9: The pane resizes and collapses

**Files:** `tracks.js`, `index.html`, `cockpit.css`, `main.js`,
`tests/test_page.py`

- [ ] **Tests first.** Dragging the tracks pane's top edge up by 100 px
  makes it 100 px taller and the radar 100 px shorter (within 2 px), and on
  release sends `tracks_pct`; a second tab takes the same height. The drag
  cannot go past 10 % or 80 %. The collapse button (`aria-expanded`) leaves
  only the title bar; the radar's bottom edge then sits one gap above it; a
  second tab collapses too. The frequencies pane's bottom stays level with
  the tracks pane's in every state. Under 1100 px wide there is no grip, and
  collapse works.
- [ ] **CSS:** the last grid row becomes `var(--tracks-row)`, which
  `applyPrefs` sets to `calc(var(--tracks-pct) * 1vh)` or, collapsed,
  `min-content`. The grip is a 6 px strip across the pane's top
  (`cursor: row-resize`), `role="separator"` with `aria-valuenow`, and moves
  by 2 % on arrow keys.
- [ ] The radar's `ResizeObserver` already redraws on the change; check it
  does once per drag frame, not more.
- [ ] Commit `feat(tracks): drag to resize, click to collapse`.

---

# Part 4: traffic

### Task 10: Map layers by setting; labels by zoom; close in on the runways

**Files:** `radar.js`, `tools/build_geodata.py`, `src/kcgx/geodata.py`,
`src/kcgx/data/geo.json.gz`, `tests/test_build_geodata.py`,
`tests/test_page.py`

- [ ] **Tests first.** With the default `map`, the demo's static layer is
  pixel-identical to before this task (within 0.1 %: the dash patterns are
  now named). `show: false` on COAST leaves `debug().layers.coast` 0 and no
  coast pixels; `alpha`, `line` and `width` change what `debug().styles`
  reports for that layer. `label` changes a place's text height. At the
  range's view a CITIES label is its `label` px; zoomed in 4x it is
  `label * 4^0.35` px or `label_max`, whichever is less; zoomed out to 160 nm
  at range 40, no less than `label_min`. Tags scale the same from `tag_px`.
  The wheel zooms in to 0.25 nm. At 0.5 nm a runway is drawn as a filled
  quadrilateral its `width_ft` wide (or 150 ft), and no narrower than
  `map.RUNWAYS.width / 10` px. `build_geodata.runways` keeps `width_ft` as a
  fifth element when present; `geodata` passes it through; a map without it
  still draws.
- [ ] **Styles from the table.** The literal table at `radar.js:404-414` and
  the constants for rings, runways, home and places read from
  `prefs.map`. `line` maps to dashes in units of the width: SOLID `[]`, DASH
  `[5w, 5w]`, DOT `[w, 3w]`, which Task 10 checks against today's patterns
  and adjusts per layer if a default would change.
- [ ] **Label size:** `labelPx(base) = clamp(label_min, base * (range / view.nm) ** 0.35, label_max)`,
  used for every still label and for tags.
- [ ] **Runways:** solid, filled, at true width once that is wider than the
  line width; `VIEW_MIN_NM` 0.25. Rebuild `geo.json.gz` with widths **if
  the implementer may fetch OurAirports' `runways.csv`** (the tool already
  does); if not, leave the old map, which draws at 150 ft, and list the
  rebuild under Built as owed.
- [ ] Commit `feat(radar): style every map layer; labels follow the zoom; runways up close`.

### Task 11: Tags over everything; the HUD's two readouts

**Files:** `radar.js`, `index.html`, `main.js`, `tests/test_page.py`

- [ ] **Tests first.** Inject two aircraft so that one's trail crosses the
  other's tag: the pixels of the tag's text are the tag's colour, not the sum
  of trail and tag (read them; today they are brighter where the trail
  crosses). With AIRCRAFT boxed and fill 100, the box's interior is black
  over a coast line **and** over another aircraft's trail. With persistence
  on, a moved tag leaves no ghost in the next frame. The HUD's first line is
  the poll age, the second the range. The age reads `5 SECONDS AGO`, `1
  SECOND AGO`; errors keep their wording (`RADAR TIMEOUT, PICTURE 40
  SECONDS OLD`).
- [ ] **A fourth canvas, `tags`,** cleared each frame; boxes then text, both
  `source-over`, tags in rank order (last rank first, so the top row's tag is
  on top). `frame()`: clear, `still`, `trace` (lighter), `tags`. The glow on
  tags is `glow_traffic`, drawn the bare-then-shadow way.
- [ ] Swap `#radar-range` and `#radar-poll` in `index.html`; reword
  `drawHud`.
- [ ] Commit `feat(radar): flight tags over every map element; the poll reads in seconds`.

### Task 12: Centre on a click; follow the chosen aircraft; its data box

**Files:** `radar.js`, `focus.js`, `tracks.js`, `index.html`, `cockpit.css`,
`tests/test_page.py`

- [ ] **Tests first.** Clicking a city's symbol or label eases the view
  until that city is at the centre (within 1 px) and `view.nm` is unchanged;
  with `view_ease: OFF` in one frame. Focusing an aircraft, from the radar
  or the table, eases the view to `follow_nm` on it; after a poll and 2 s of
  reckoning it is still centred (within 2 px). A drag ends following
  (`debug().following` false) and keeps the focus. Unfocusing eases back to
  the view before the focus. A double click recentres on the airport and
  ends following. The data box (`#ac-info`) shows one `NAME: VALUE` line
  per visible column in order, from the same text functions as the table;
  sits left of the chevron with its right edge 12 px from it, or right of it
  when there is no room; follows the aircraft every frame; hides with
  `info_box: false` or when nothing is focused.
- [ ] **View moves:** `goTo({nm, x, y}, ms)` eases `view` with
  easeInOutCubic over `view_ease`'s duration; a wheel or drag during one
  cancels it. Following sets the target to the reckoned position every
  frame, with no easing once arrived.
- [ ] **Hits for places:** the still layer already records `placed`
  rectangles; add the symbol's point to each and test clicks against them
  after aircraft.
- [ ] **The data box** is an absolutely placed `<dl>` in `.radar-wrap`,
  `pointer-events: none`, in the UI font, boxed with the label box settings
  when AIRCRAFT is boxed. `tracks.js` exports its column text functions for
  it.
- [ ] Commit `feat(radar): click to centre; follow the focus at 10 nm; a data box beside it`.

### Task 13: Tails, parked traffic and the sort's shading

**Files:** `radar.js`, `store.js`, `tests/test_page.py`

- [ ] **Tests first.** `tail_secs: 60` keeps only trail points from the last
  60 s (`debug().hits[].trail` length); 0 draws no trail; the store keeps up
  to 600 s whatever is set, so lengthening shows history at once. A trail's
  newest segment's alpha is `tail_alpha_min` for an aircraft under
  `tail_gs_low`, `tail_alpha_max` over `tail_gs_high`, `tail_alpha` between
  and when `gs` is null (all times the existing fade along the trail, stale
  and focus factors). With `ground_mode: FADE` an aircraft whose `still` is
  over `ground_min * 60` is drawn at `ground_alpha` (chevron, tail and tag);
  HIDE leaves it out of `debug().hits` and unclickable; SHOW changes nothing;
  the focused aircraft is never faded or hidden. Sorting by DIST: the nearest
  aircraft's chevron is at full alpha, the farthest at `sort_floor`, and the
  nearest is drawn last within its colour; reversing the sort reverses both.
- [ ] **Trails by time:** the store keeps `[lat, lon, t]` points for 600 s;
  the radar draws those within `tail_secs`.
- [ ] **One alpha per aircraft:** `stale × focusDim × rank × ground`, and
  for its tail additionally the speed band; computed once per aircraft per
  frame.
- [ ] Commit `feat(radar): tails by time and speed; parked traffic fades; the sort shades`.

---

# Part 5: boot

### Task 14: The boot animation

**Files:** `boot-scene.js` (new), `boot.js` (new), `index.html`,
`cockpit.css`, `main.js`, `src/kcgx/hub.py`, `src/kcgx/protocol.py`,
`tests/test_hub.py`, `tests/test_boot.py` (new)

- [ ] **Tests first.** Python: the first client a hub accepts gets
  `boot: true` in its snapshot, every later one `false`, a reconnect
  included. Browser (`test_boot.py`, with `boot_anim: true`): the page opens
  under `#boot`, an opaque cover in `--wall`, and `.page` has opacity 0;
  `window.kcgx.boot.t` advances; at `t = 21.7` the cover fades out over
  600 ms and `.page` in; a key or a click at any time does the same at once;
  the socket was connected and the radar drawing beneath it (the HUD's age is
  written before the fade). In AMBER the scene's tower pixels are the AMBER
  palette's `--white`, not WOPR's. A second page on the same server gets no
  cover. `boot_anim: false` and reduced motion each give no cover. The cover
  is decided once, from the first snapshot's `boot && boot_anim`: a later
  `prefs` frame turning `boot_anim` on shows no cover (test it; the page
  fixture resets prefs to DEFAULTS, where it is on). The page
  shows nothing at all (black, no WOPR flash) until the first snapshot or
  1.5 s, whichever is first.
- [ ] **`boot-scene.js`**: the path data from `vector-scene.jsx:3-43`
  (runway, skyline, dome, tower), the role map, the six scene functions
  (`vector-scene.jsx:44-116`) and the five easings, as a pure
  `frame(ctx, T, colours, {glow, ratio})`. Paths are `Path2D` from their `d`
  strings; draw-on uses each path's length, measured once with a detached
  `SVGPathElement.getTotalLength()`, as a dash offset. "KCGX" is
  `strokeText` in `--font-display`, after `document.fonts.ready`. The
  original's own burn-in (four ghost renders) is dropped: the canvas fades
  by `burn_in` as the radar's moving layer does. Motion blur is dropped. The
  scanlines and vignette are the page's `.ovl`.
- [ ] **`boot.js`**: the cover holds the canvas; it waits for the first
  snapshot (or 1.5 s) to know the palette and whether to play; plays on
  `frames.js` at `fps_max` and `aa`; skips on `keydown` or `pointerdown`;
  fades and removes itself. `index.html`'s `<html>` gains
  `data-booting`, under which `.page` and every `<dialog>` are
  `opacity: 0`, so the first paint is black, not the default palette.
- [ ] Commit `feat(web): the cockpit boots with the vector animation`.

### Task 15: By hand, and the docs

- [ ] `uv run --group browser pytest`, green in both engines.
- [ ] `kcgx --demo` at 1440 by 900 and 1100 by 760, WOPR and AMBER: walk the
  [Coverage](#coverage) table line by line. Compare the boot to the
  `.dc.html` played in a browser (it fetches its runtime from unpkg; that is
  the reviewer's machine, not the app).
- [ ] **The owner's, on the Mac:** real feeds at KORD (titles without
  "Chicago"), picking feeds while one is parked, master mute; real traffic at
  KPDX for parked fading, follow at 10 nm, 0.25 nm on the runways; the boot in
  KCGX.app; UI zoom in KCGX.app (WKWebView's own zoom is separate and not
  used).
- [ ] README, spec, a Built section here, a row in `docs/README.md`.
- [ ] Commit `docs: phase G built`.

---

## Coverage

| The list | Task |
|---|---|
| Boot: the vector animation in the last palette | 14 |
| Boot: the UI fades in after it, boots normally | 14 |
| Tracks: add or hide columns for all available data | 7, 8 |
| Tracks: a filter for each column | 8 |
| Tracks: sort sets brightness and z-order on the radar | 8, 13 |
| Tracks: column headers fixed when scrolling | 8 |
| Tracks: drag the top to resize, Traffic fills | 9 |
| Tracks: collapse and expand, Traffic fills | 9 |
| Traffic: show, opacity, line type, label size for every map marking | 1, 2, 10 |
| Traffic: clicking a map element centres on it | 12 |
| Traffic: min, max and default font size by zoom | 1, 10 |
| Traffic: selecting an aircraft zooms to 10 nm and follows | 12 |
| Traffic: a data box left of the selected aircraft | 12 |
| Traffic: fade or hide grounded flights by speed, time, altitude | 1, 7, 13 |
| Traffic: zoom much closer; thicker, solid runways | 10 |
| Traffic: tail length | 13 |
| Traffic: tail brightness by groundspeed | 13 |
| Traffic: labels and box fills over every map element | 11 |
| Traffic: "N SECONDS AGO", swapped with RNG | 11 |
| Frequencies: no mute or solo | 6 |
| Frequencies: a click selects; one feed at a time | 6 |
| Frequencies: chatter left of the status glyph | 6 |
| Frequencies: no "CHATTER" | 6 |
| Frequencies: waveform twice as tall | 6 |
| Frequencies: airport dropped from titles | 6 |
| Frequencies: counts line becomes master mute and volume | 6 |
| Frequencies: tighter letter spacing on titles | 6 |
| Config: centred, full-screen | 2 |
| Config: tabs General, Traffic, Tracks, Frequencies | 2 |
| Config: clock format | 3 |
| Config: UI zoom | 3 |
| Config: anti-aliasing | 4 |
| Config: finer glow; performance | 4, 5 |
| Config: burn-in | 4 |
| Config: default font size | 3 |
| Config: font picker, monospaced only | 3 |
| Config: max frame rate, 15 at least | 4 |
| Config: poll refresh rate | 4 |
| Config: radar movement behaviour | 4 |
| Airport: picker fixed and centred | 2 |
| Airport: picker 50 % wider | 2 |

## Execution: worktrees and agents

Read as tasks, the plan is one long line through `radar.js`, `index.html`,
`cockpit.css` and `test_page.py`, which nearly every task edits. Work is
split across worktrees by **who owns which file**, not by task number. A
serial Phase 0 first cuts the shared files into parts each lane can own.
Tasks 4 and 5 are each split between lanes (4a to 4e, 5a and 5b below).

### Phase 0: seams (serial, in `/Users/mikelse/kcgx_web`)

One agent at a time, on `feat/web-cockpit`, each step reviewed and committed
before the next. Nothing branches off until every step is in.

| Step | What | Why the lanes need it |
|---|---|---|
| P0.1 | **Task 1**, whole: every new key, `Table`, the migration, store defaults | each lane then reads prefs and never edits `prefs.py` or `store.js` defaults |
| P0.2 | **Task 2**, whole: tabs, the table binder, **a control for every key** (test_page_prefs requires it), the airport picker | each lane's settings already exist in the sheet; no lane edits the config markup or `sheets.js` |
| P0.3 | **Split `radar.js`, no behaviour change**: `radar/index.js` (mount, `frame()`, `debug()`, the HUD), `radar/still.js` (`drawStatic`, places, rings, home), `radar/moving.js` (aircraft, trails, tags), `radar/view.js` (view, wheel, drag, double click, hit tests). `debug()` keeps its shape. The whole suite passes unchanged. | three lanes then work in radar files that are theirs alone |
| P0.4a | **Each radar module owns its state** (from P0.3's review): `radar/view.js`, `radar/still.js` and `radar/moving.js` each export `init(radar)`, which adds that module's fields, binds its listeners and returns optional `{ tick(now), debug() }` hooks. `radar/index.js` keeps only the shared core (`canvas`, `store`, `hud`, `staticDirty`, `size()`, a `radar.canvases` list `size()` resizes), calls the three `init`s in a fixed order (view, still, moving, so listener order is unchanged), runs every `tick` at the start of `frame()`, and merges each `debug()` (two modules giving the same key is an error). Objects on `radar` are changed in place, never replaced. `drawMoving` leaves its reckoned aircraft on `radar.now` for view.js to follow. Also here, since they change the same frame loop: `frames.js` and the `theme.js` helpers from P0.4b. Proved by P0.3's screenshot diff again. | MAP and TRAFFIC would otherwise both edit `mountRadar`, `frame()` and `debug()` in their first tasks |
| P0.4b | **Shared modules and contracts**: `frames.js` (Task 4a: the capped clock, `fps_max`) adopted by radar and stack; `theme.js` `renderScale()` and `glowBlur(layer)` (default 33 → 3.96 px, as LOW's 4); `columns.js` holding every Tracks column (title, text, sort value, filter kind) for all seventeen names, tolerant of missing fields; `store.state.rank` (an empty `Map` until tracks fills it) and `ac.still` (absent until the server sends it) documented in `store.js`; page test fixtures (`server`, `browser`, `page`, `other`, `set_prefs`, `SIZES`, …) moved from `test_page.py` to `tests/page_fixtures.py` and imported back; one marked section per lane at the end of `cockpit.css` and one marked anchor per lane in `index.html` (`<!-- G:freq-head -->`, `<!-- G:tracks-grip -->`, `<!-- G:ac-info -->`, `<!-- G:boot -->`) | lanes code to these and never wait on one another |

### The lanes

Each lane is a worktree and a branch off `feat/web-cockpit` once P0.4 is
in. "Owns" means only that lane edits the file; anything else needs a note
to the integrator first.

| Lane | Worktree, branch | Tasks | Owns |
|---|---|---|---|
| **AUDIO** | `../kcgx_g_audio`, `g/audio` | 6; render scale and `glow_traffic` on the stack's traces (from 4) | `squelch/cockpit.py`, `squelch/mixer.py`, `kcgx/names.py`, `stack.js`; in `protocol.py` and `station.py` only `select`, `master_mute` and `title`; in `index.html` the `G:freq-head` anchor (which takes in `#freq-counts`); `mountVolume` (moved out of `sheets.js`) and the two mount lines for the stack and the volume in `main.js` |
| **TRACKS** | `../kcgx_g_tracks`, `g/tracks` | 7, 8, 9; **4b** (`poll_secs`: `Radar.set_refresh`, the station's half) | `kcgx/radar.py`, `kcgx/demo.py`, `tracks.js`, `columns.js`; the `--tracks-row` custom property, which `tracks.js` sets itself (the grid reads `var(--tracks-row, minmax(160px, 24vh))` from Phase 0) |
| **CHROME** | `../kcgx_g_chrome`, `g/chrome` | 3; **4c** (`glow_text`, `--glow`, the `[data-glow]` rules) | `main.js` (`applyPrefs` only), `status.js`, `theme.js`, fonts, the body and page rules in `cockpit.css` |
| **MAP** | `../kcgx_g_map`, `g/map` | 10, 12; **4d** (`glow_map`, `zoom_speed`, `view_ease`); **5a** (glow by colour on the map; moving the bitmap during gestures, drawn inside `drawStatic` onto `still`, so `index.js` keeps pasting it at 0,0) | `radar/still.js`, `radar/view.js`, `tools/build_geodata.py`, `geodata.py` |
| **TRAFFIC** | `../kcgx_g_traffic`, `g/traffic` | 11, 13; **4e** (`glow_traffic`, `burn_in`, `motion`, render scale on the radar's canvases); **5b** (culling) | `radar/moving.js`, `radar/index.js` (the tags layer, the HUD), trails in `store.js` |
| **BOOT** | `../kcgx_g_boot`, `g/boot` | 14 | `boot.js`, `boot-scene.js`, `hub.py`, `boot` in `protocol.py` |

Cross-lane contracts, set in P0.4 so no lane waits:

- `debug()` keys are per lane and never shared: MAP adds `styles`, `following`, `blur_map`; TRAFFIC adds `blur_traffic` and its own. (Task 4's test says `debug().blur` per layer: read it as these keys.) The seams test asserts a superset of the core keys, not an exact set.
- Pointer maths use `radar.size().ratio`, never `devicePixelRatio`, so TRAFFIC's render scale reaches MAP's hit tests without an edit to `view.js`.
- Lane CSS sections come after the narrow-layout media rules in `cockpit.css`, so a lane rule that must differ under 1100 px carries its own `@media` inside its section.
- `columns.js` sorts a missing figure below every real one (`-Infinity`) and gives each column `value(ac)` (a number or null; GND is 0) for number filters, so a filter can drop what reports nothing.
- A module's `post(now)` hook, if it returns one, runs after drawing, so MAP's follow and data box (Task 12) read this frame's `radar.now`.

- TRAFFIC reads `store.state.rank` and `ac.still`. Its tests set both
  through `window.kcgx.store`, so it does not need TRACKS merged.
- MAP's data box (Task 12) takes its lines from `columns.js` and the
  visible columns from `prefs.track_cols`. TRACKS may change how a column
  reads, but not the module's interface.
- MAP and TRAFFIC both call `labelPx()`. MAP writes it in `radar/still.js`
  and exports it. Until MAP is merged, TRAFFIC uses the P0.3 stub, which
  returns its argument.

### Inside a lane

Per task, as phase F did (its `fix: task N review findings` commits):

1. **Implementer agent**, fresh, briefed with: this plan's path, the task
   number(s), the lane's "owns" list, the Global Constraints, and "run your
   lane's test files plus `uv run pytest -q tests/test_page_prefs.py` and
   the non-browser suite; the full browser suite is the integrator's". It
   commits once, in the repo's style.
2. **Reviewer agent**, fresh. It gets the commit's diff and the task's text,
   not the implementer's report.
3. **Fix agent**, or the implementer resumed, for the findings. It commits
   `fix: task N review findings`.

New page tests go in a file of the lane's own:
`tests/test_page_audio.py`, `_tracks`, `_chrome`, `_map`, `_traffic` and
`tests/test_boot.py`. Each imports `page_fixtures`. A lane edits
`test_page.py` only to mend a test its own change breaks, and lists each one
in its last commit's message, so the integrator expects the conflict.

Every worktree needs its own `uv sync --group browser`. The Playwright
browsers in `~/Library/Caches/ms-playwright` are shared. Test servers pick
free ports and set `KCGX_STATE_PATH`, so lanes cannot collide. **Do not run
`uv run playwright install` in a lane.** Phase F's install garbage-collected
another project's browsers.

### Waves

Each lane's browser tests run in both engines. More than three lanes running
them at once makes timing tests flaky, and phase F already has two
poll-race flakes. So:

| Wave | Runs | Starts when |
|---|---|---|
| 0 | Phase 0 | now |
| 1 | MAP, TRAFFIC, AUDIO | P0.4 is in. MAP is the critical path (10 then 12), so it starts first. |
| 2 | TRACKS, CHROME | AUDIO is merged |
| 3 | BOOT | CHROME is merged. Its fade depends on CHROME's `--font-display` and opacity rules, which it builds on rather than guesses. |
| 4 | Task 15 | every lane is merged |

If MAP runs long, wave 3 starts beside it. BOOT touches no radar file.

### Integration (in `/Users/mikelse/kcgx_web`)

The integrator is the main session, not a subagent. For each lane that
reports done:

1. In the lane's worktree: `git rebase feat/web-cockpit`, then its own tests
   again.
2. In the integration worktree: `git merge --no-ff g/<lane>` with message
   `merge: phase G <lane>` and the attribution lines. Resolve conflicts:
   `test_page.py`, the `cockpit.css` sections, `index.html` anchors.
3. Run the full suite there (`uv run --group browser pytest -q`, about 10
   minutes and growing). On a red run, the lane's fix agent mends it on the
   lane branch, and step 1 repeats.
4. Tell the other running lanes to rebase at their next task boundary, not
   mid-task.
5. `git worktree remove ../kcgx_g_<lane>`; delete the branch once merged.

Merge order follows the waves: AUDIO, then MAP and TRAFFIC in whichever
order they finish, then TRACKS, CHROME, BOOT. The one ordering that matters:
**MAP before TRAFFIC if both are ready**, so `labelPx` replaces the stub
before TRAFFIC's tag tests run against the real one.

### What can go wrong

- **P0.3's split breaks something the tests do not see.** It is a pure move.
  The reviewer diffs behaviour, not text: screenshots of the demo before and
  after at two sizes, under 0.1 % of pixels different.
- **Two lanes need the same new protocol field.** Only AUDIO and BOOT touch
  `protocol.py`, in different functions. Anything else goes to the
  integrator, who adds it on `feat/web-cockpit` and has both lanes rebase.
- **Task 10's map rebuild needs the network.** The MAP lane does not fetch;
  it leaves the old map (runways at 150 ft) and lists the rebuild as owed,
  as Task 10 says.
- **Flaky tests at merge time.** A failure in a test the merged lane did not
  touch is re-run alone once. If it passes, it is noted under Built, not
  chased.

## Not in this plan

- Filters applied to the radar (decision 4). A follow-up flag could dim what
  the filters hide.
- Clicking map lines (coasts, airspace) to centre them.
- Field elevation for the ground fade (needs `elevation_ft` in
  `airports.csv` and a rebuild).
- Remembered filters.
- Per-item box styles, decluttering tags at 250 nm (phase F's list).
- The boot animation's own motion blur and four-ghost burn-in.
