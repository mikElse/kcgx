# The cockpit in a browser

*2026-10-18*

## The problem

kcgx is three terminal programs held together by tmux. That works, but it
puts a ceiling on what the cockpit can be:

* **The radar is someone else's binary.** `adsb-tui` decides what the radar
  looks like, cannot be extended, ships under a non-commercial licence, and
  has needed a pile of workarounds to keep talking to adsb.lol (the
  User-Agent smuggled through `api_key_header`, a config screen that deletes
  it on save, a hand-tuned `radar_aspect`).
* **The layout is tmux.** Pane roles, index drift, the server's captured
  environment, `display-popup`, the `PATH` dependency behind `Ctrl-b a`:
  a large share of the launcher and its 1,600 lines of tests exist to manage
  tmux rather than to show air traffic.
* **Theme matching is screen scraping.** squelch reads the radar's colours
  by running `tmux capture-pane` every three seconds, because there is no
  other way to know what `adsb-tui` is showing.
* **Terminal cells are the resolution.** A 48 column pane, meters made of
  four shade characters, an ICAO banner drawn in quadrant blocks.

## What we are building

The same cockpit, rendered as a web page served from your own machine.
`kcgx` starts a small local server and opens a browser tab:

```
┌──────────────────────────────────────┐ ┌──────────────────┐
│        PORTLAND        ◯             │ │ 1955Z   12:55 PDT│  status
│      INTERNATIONAL   (ring)          │ ├──────────────────┤
│   coastline, rivers, borders         │ │ TOWER (BOTH)   ● │
│   ⋯ dashed class B ⋯   ◇ navaids     │ │ ╱╲__╱╲╱╲_____╱╲_ │  frequencies
│        ASA412 6172  ╲                │ │ [S] [ON] [A]  34 │
│                 ⟵────  trail         │ │ GROUND   ♪ 07  ◐ │
│                                      │ │ CLEARANCE ♪ 00 ● │
│               TRAFFIC                │ │                  │
└──────────────────────────────────────┘ └──────────────────┘
 ▪ ▪ ▪ ▪ ▪ ▪ ▪ ▪   lamp bar: one lamp per feed   ▪ ▪ ▪ ▪
┌──────────────────────────────────────┐ ┌──────────────────┐
│ traffic table (collapsible)          │ │ teletype log     │
└──────────────────────────────────────┘ └──────────────────┘
```

The look is the NORAD war room from *WarGames* (1983): vector line art on
black, framed screens on a wall, a row of indicator lamps between them. See
[Visual language](#visual-language) below; the reference stills are in
`war_games_examples/`. A mockup of the main screen and a visual language
board were approved on 2026-10-18 (the "KCGX Web Cockpit" design canvas);
where this spec and the mockup disagree, the mockup is the intent.

**Audio stays on the server.** The Python mixer keeps playing through the
machine's output device exactly as it does today. The browser is a control
surface and a display: it never receives audio, only state and meter levels.
That is what lets this reuse nearly all of squelch, and it preserves the
cockpit's best property: closing the tab is like detaching tmux, and the
audio keeps playing.

**Every existing feature survives**, with one deliberate exception (theme
matching, which has nothing left to match). The parity table below is the
acceptance test for the whole batch.

**It stays local.** The server binds to `127.0.0.1` only. LiveATC's terms
cover rebroadcast and redistribution, and a hosted version would be both.
Personal listening on the machine running it is what the README already
promises, and nothing here changes that.

## Feature parity

Every row must hold before the terminal cockpit is retired.

| Today | In the browser |
|---|---|
| One row per feed, all metering, one audible at start | Same, from the same `build_sessions` |
| Expanded row (meter + controls) when audible, compact when muted | Same rule. Meter becomes a scrolling bar strip on a canvas |
| `●` live, `◐` reconnecting, `○` offline, `‖` parked | Same states, same glyphs, plus a tooltip naming the state |
| Audible first, then by five minute chatter | Same `rank()` |
| Reorder only after 15 s stable and 2 s untouched | Same `Resorter`. "Touched" now includes pointer hover over the stack |
| Mute/unmute moves the row at once; selection follows the feed | Same |
| `space` mute, `S` solo, `a` ambient, `↑` `↓` select | Same keys, plus click targets |
| Click anywhere on a row toggles mute | Same |
| Seven stream limit, parking, refusing an eighth audible feed | Same `slots.plan()` and the same refusal message |
| `c` config overlay, master volume live in 5% steps | Side sheet. Volume is a slider; other rows keep live/inert/fixed/off labels |
| `f` feed picker, opens a feed that is not open | Same, as a searchable list |
| Message log, capped at 200 | Same cap, same text |
| Feed list cache, retry budgets, one feed fallback, never another airport's audio | Unchanged: `load_feeds`, `picker_feeds`, `_no_feeds` move as they are |
| `squelch --refresh-feeds` | Unchanged CLI |
| Status pane: big ICAO, airport name, Zulu and local clocks | Airport name in large stroked capitals beside its ring on the radar; ICAO and both clocks on the status screen |
| `Ctrl-b a` / click `▾ airport` opens airport search | `/` or click the airport name; same `search()` over the same CSV |
| `kcgx go [query]`, exact ICAO skips the picker | Same CLI; it talks to the running server |
| Remembered airport in `~/.local/state/kcgx/airport` | Same file, same `current_icao()` resolution order |
| Airports LiveATC does not cover still get a radar | Same: empty stack with a message, radar works |
| Radar: aircraft around the airport from adsb.lol, 15 s polling | Our own radar on a map. Same endpoint, same interval, same polite User-Agent |
| adsb-tui traffic table, row selection | Traffic table under the map; selecting a row or a blip highlights both |
| adsb-tui `t` theme cycling, six themes | `t` cycles the WOPR palette and the six names as variants of it |
| squelch follows the radar's theme | **Dropped.** One app, one theme setting |
| Header shows `ERR 429` / `ERR 403` on a refused refresh | Radar shows the last good picture with a "refresh refused" badge |
| Dead pane stays visible; `Ctrl-b r` respawns it | A failed feed or radar shows its error in place, with a retry control |
| Running `kcgx` again reattaches | Running `kcgx` again opens a tab on the running server |
| Closing the terminal detaches, audio continues | Closing the tab, same |
| `kcgx stop`, `Ctrl-b q` (asks first), picker `^q` stops every cockpit | `kcgx stop`; a Shut down control in the page (asks first) |
| `q` in squelch quits | `q` opens the same Shut down confirmation |
| Refuses below 100 columns | Responsive: below about 900 px the radar and stack stack vertically |

## Architecture

```
            browser tab(s)
   ┌───────────────────────────────┐
   │  radar   status   feed stack  │   plain ES modules, no build step
   └──────────────┬────────────────┘
        HTTP + one WebSocket, 127.0.0.1 only
   ┌──────────────┴────────────────┐
   │  kcgx server (Starlette)      │
   │   Cockpit controller          │  extracted from SquelchApp
   │   RadarPoller                 │  adsb.lol, every 15 s
   │   FeedSessions + Mixer        │  unchanged
   └──────────────┬────────────────┘
              sounddevice → speakers
```

### The controller: the one real refactor

squelch's core is already UI free: `session`, `mixer`, `feeds`, `activity`,
`slots`, `solo`, `dsp`, `pipeline`, `audio`, `ringbuffer`, `config`, and on
the kcgx side `airports` and `state`. None of them import Textual.

But the *rules* that tie them together live inside `SquelchApp`: selection,
`reconcile_streams`, `_refuse_over_limit`, the solo bookkeeping in
`action_toggle_solo`, `_reorder_now` and `apply_order`, `open_feed`,
`jump_to_feed`, warnings. Those are not rendering; they are the cockpit's
behaviour, and both front ends need exactly the same version of them.

So the first phase moves them into `src/squelch/cockpit.py`:

```python
class Cockpit:
    """Feeds, mix and ordering for one airport. No UI, no event loop."""

    def snapshot(self) -> dict          # everything a client needs to draw
    def levels(self) -> list[float]     # one dBFS per feed, stack order
    def toggle_mute(self, ident) -> None
    def toggle_solo(self, ident) -> None
    def toggle_ambient(self, ident) -> None
    def set_volume(self, value) -> None
    def open_feed(self, feed) -> None
    def tick_resort(self) -> None       # called every RESORT_INTERVAL
    def note_input(self) -> None        # feeds Resorter's quiet period
    def stop(self) -> None
```

It emits changes through a single callback (`on_change(kind, payload)`) in
place of `call_from_thread`. Feeds are addressed by `ident`, not by
`id(session)` or row index, because a browser cannot hold a Python object id
and an index is exactly the thing reordering changes.

`SquelchApp` is then rewritten to drive a `Cockpit`. **That is the gate for
everything after it:** the terminal squelch keeps working on the new
controller, and the behavioural tests in `test_app.py` are moved to
`test_cockpit.py` and pass against it with no Textual involved. If the
browser work stopped there, the codebase would still be better for it.

Selection is the one thing that does not move. It is per viewer: two tabs
can have different rows selected, and `space` acts on the selected feed by
sending its ident.

### Changing airport

Today `kcgx go` writes the state file and respawns two tmux panes, so a new
airport is a new squelch process. In the server it is in process:

1. `write_airport(icao)`.
2. `cockpit.stop()`: every session stopped, the mixer's channels released.
3. A new `Cockpit` built with `load_feeds` for the new ICAO, on a worker
   thread, because the listing fetch can take several seconds of retries.
4. The radar poller moves to the new coordinates.
5. One `airport` message to every client, then a full snapshot.

The mixer itself survives the switch, so the output device is opened once
per server and an airport change never produces a click or a device
renegotiation.

### Radar

The server polls `https://api.adsb.lol/v2/point/{lat}/{lon}/{range_nm}` and
pushes the result to clients. It is polled on the server, not in the
browser, for three reasons:

* adsb.lol refuses requests without a contactable `User-Agent`, and a
  browser is not allowed to set one.
* One poller serves every open tab, so two tabs do not double the rate.
* The 15 second interval and the over-rate penalty described in the README
  apply per address; the server is where that discipline can be kept.

`KCGX_ADSB_UA` keeps its meaning. `refresh_secs` and the range move into
`squelch.toml` as `radar_refresh_secs` (default `15`) and `radar_range_nm`
(default `40`). A refused poll keeps the last good aircraft list, marks it
with its age, and backs off: 15 s, 30 s, 60 s, capped at 120 s, reset on
the first success.

In the browser the radar is **our own vector renderer, not a map
library.** The look calls for line art and nothing else: no imagery, no
tiles, no fills. That rules out MapLibre and its base styles, and it is a
better trade anyway: no tile provider, no key, no network dependency for
the map, and full control over every stroke.

The projection is azimuthal equidistant centred on the airport, so range
rings are true circles and distance reads straight off the screen. Positions
are dead reckoned between polls from ground speed and track, as adsb-tui
does, and an aircraft not seen for `radar_stale_secs` (default `60`) fades
and then drops. The geography comes from vendored public domain data, built
the way `airports.csv` already is; see [Map data](#map-data).

The traffic table under the map shows callsign, type, altitude, ground
speed, track, distance and squawk, sortable by column, and collapses to a
single summary line. Selecting a row and selecting a blip are the same
action.

### Transport

**HTTP** for things that happen once:

| Route | Does |
|---|---|
| `GET /` | the page |
| `GET /api/airports?q=` | `search()` results |
| `POST /api/airport` | change airport (body: `icao`) |
| `GET /api/feeds/available` | `picker_feeds()` for the feed picker |
| `POST /api/shutdown` | stop the server, asks nothing (the page asks first) |
| `GET /api/health` | `200` with version and airport; used by the launcher |

**One WebSocket** at `/ws` for everything live. Server to client:

| Message | When |
|---|---|
| `snapshot` | on connect, and after an airport change |
| `feed` | one feed's state, mute, solo, ambient or chatter changed |
| `order` | the stack order changed (a list of idents) |
| `levels` | 25 times a second: one dBFS per feed in stack order |
| `aircraft` | each radar poll, success or refusal |
| `message` | a warning for the log |
| `airport` | the airport is changing (so the page can show it at once) |

Client to server: `mute`, `solo`, `ambient`, `volume`, `open_feed`, `input`
(the "you have touched the stack" signal that keeps reordering away from the
pointer), each carrying an ident where relevant.

**Levels are the only high rate stream.** 25 Hz matches `LEVEL_INTERVAL`
today. Thirty feeds at 25 Hz is 750 floats a second: small enough for JSON,
so there is no binary framing. Every feed's level is sent, muted or not,
because every feed meters today and a row that expands should already have
its history. The browser keeps that history; the server keeps none.

The levels loop reads `session.level` exactly as `_tick_levels` does: polled
from the asyncio loop, never pushed from the audio callback, which stays a
real time context that touches nothing else.

### Threads

Sessions keep their own threads; the mixer keeps PortAudio's. The server
adds one asyncio event loop (uvicorn's), and the `Cockpit`'s `on_change`
callback hands events onto it with `loop.call_soon_threadsafe`. That is the
direct replacement for `call_from_thread`, with the same rule: a callback
that fires after shutdown is dropped silently, not raised into a session
thread.

### Front end

No build step and no Node. The page is plain HTML, CSS and ES modules served
from `src/kcgx/web/`. Nothing is vendored but the Hershey glyph data and
one font file. This keeps the install's promise that `uv` is the only
toolchain, and it keeps the front end readable in the same repo by the same
person who reads the Python.

If the UI outgrows that, Preact with `htm` can be vendored the same way
without introducing a build. Choosing a framework now is not needed to start.

### Visual language

The reference is the NORAD wall in *WarGames*: four stills in
`war_games_examples/`. What makes it read as that, and so what the page
must do:

**Everything is a line.** Coastlines, borders, rivers, airspace, waypoints,
aircraft and most of the text are strokes on pure black. No fills, no
gradients, no imagery, no rounded cards. Where a panel needs a boundary it
gets a thin frame, never a background.

**Lines glow.** Each stroke is drawn twice with additive blending: a wide,
faint, blurred pass and a thin bright core. That is the phosphor look, and
it is cheap. On top of the glow sits a display effects layer, CRT by
default; see [Display effects](#display-effects).

**Colour is meaning, not decoration.** One palette, used the same way on
every screen:

| Colour | Means | Used for |
|---|---|---|
| Cyan | ours, nominal | home country coastline and borders, aircraft, labels, feed traces |
| Blue, dashed | structure | airways and the lines joining navaids |
| Green | elsewhere | foreign coastlines and borders |
| Red orange, dashed | restricted or alarm | class B and C airspace, emergency squawks, errors |
| Pink | focus | the ring round the airport, its name, the selected aircraft |
| White | motion | aircraft trails |
| Amber | places | cities and other airports as small open circles |

**Shapes from the film, given jobs here.** Waypoints and navaids are
diamonds; other airports are triangles; aircraft are chevrons pointing along
track, trailing a white line of their last positions (the film's missile
tracks); the home airport sits in a pink ring with its name set large
beside it, exactly as the stills label each base. Labels are callsign and
altitude, `ASA412 6172`. An aircraft with no callsign is labelled `UNK1`,
`UNK2` in order of first sighting, and an emergency squawk (`7500`, `7600`,
`7700`) turns that aircraft red orange.

**Text.** Two faces, both public domain or OFL, both vendored:

* **Hershey Simplex**, drawn as strokes through the same glow pipeline as
  the map, for anything large: the airport name, panel titles, clocks,
  chatter figures, map labels. This is what makes the text belong to the
  lines rather than sit on top of them.
* A plain monospaced face for small, dense text (the traffic table, the
  config sheet, the log), where stroked glyphs blur. Tabular figures
  throughout, so nothing jitters as it updates.

All caps everywhere, as on the wall.

**The wall, not a dashboard.** Each region of the page is a framed screen
with a title set in caps along its bottom edge (`TRAFFIC`, `FREQUENCIES`,
like `MISSILE WARNING` in the still). Between the screens runs a **lamp
bar**: one small lamp per feed, lit in that feed's state colour (cyan live,
amber reconnecting, red offline, dark parked), then a gap and lamps for the
radar poll, the WebSocket and the audio device, then a gap and an
**emergency lamp**, dark until an aircraft in range squawks `7500`, `7600`
or `7700`, then lit red orange and labelled with the code. It is the whole field's health at a glance, the way
`●◐○` was on each row, and it stays visible when the stack is scrolled.

**The feed stack in this language.** An expanded row's meter becomes a
scrolling vector trace, an oscilloscope line of the last few seconds' level,
rather than a bar strip. Its controls are small framed capitals: `[S]`
`[ON]` `[A]`. The chatter figure is a two digit stroked number, the way the
wall numbers its sectors (`27`). Compact rows are a name, a figure and a
state glyph on one line.

**The log is a teletype.** New messages type out a character at a time, in
caps, with a block cursor, each prefixed with its Zulu time (`1955Z`).
Fast enough never to delay a warning (the whole line inside 400 ms), and
instant under reduced motion.

The log carries one kind of message squelch never had: **an emergency
squawk.** When an aircraft in range first shows `7500`, `7600` or `7700`,
the radar adds one line, in red orange, with callsign, code, distance and
bearing (`1955Z  N52RT SQUAWKING 7600, 33 NM NW`). One line per aircraft
per code, not one per poll; a second line when the squawk clears. This is
the only radar event that reaches the log, so the log stays a place for
things worth reading.

**Restraint.** The glow is a setting (`glow` in the config sheet: off,
low, full; default low), and so is the display layer (`display`: off,
vector, crt; default crt). `prefers-reduced-motion` turns off flicker,
jitter, line draw on, the teletype, trail fading and any easing, whatever
`display` says. Contrast is checked against the
black for every palette colour at the sizes it is used.

### Themes

The six adsb-tui names (`default`, `color`, `amber`, `ocean`, `matrix`,
`mono`) existed to match a radar that is going away. In their place the
vector style has one default palette, **WOPR** (the table above), plus the
six kept as palette variants of the same style, so `t` still cycles: `amber`
and `matrix` become single phosphor monochromes, which suit the look well,
and `mono` becomes white on black. Palettes are CSS custom properties read
by both the DOM and the canvas renderer.

The Textual specific half of `themes.py` and all of `radar_theme.py` go with
the terminal UI. The chosen palette is a setting the server remembers (in
the state directory, beside the airport), so every tab and every launch
agrees.

### Rendering

One full window canvas per screen, Canvas 2D with `globalCompositeOperation
= "lighter"` for the additive glow. Static geography is drawn once per
airport or zoom change into an offscreen canvas and copied each frame;
only aircraft, trails, the selection ring and the feed traces redraw at
display rate. At 40 nm that is a few thousand static segments and a few
hundred dynamic ones, well inside Canvas 2D. WebGL is the escape hatch if
it is ever not, and nothing in the data model would need to change.

The radar pans and zooms with the pointer and wheel, snapping back to the
airport on `home`. Range rings label themselves in nautical miles.

### Display effects

The film's screens were vector displays, and the effects that make the
mockup feel alive are vector ones: beam flicker, lines drawing on, a little
jitter, glow, phosphor persistence. Scanlines and curvature belong to
raster CRTs, but they read instantly as "old screen" and the mockup was
approved with them on. So there are three settings, and **CRT is the
default**:

| `display` | What it adds |
|---|---|
| `off` | nothing; glow alone, per the `glow` setting |
| `vector` | flicker, jitter, line draw on, phosphor persistence, vignette |
| `crt` | everything in `vector`, plus scanlines, rounded screen corners and a slight colour fringe on the radar |

The values below are the mockup's, and are the starting point:

* **Flicker.** Each screen's brightness dips, irregularly, three or four
  times in a seven second cycle, never below 93%. Screens are slightly out of
  phase so the wall never blinks as one.
* **Jitter.** The radar moves by under a pixel, for about a tenth of a
  second, roughly every five seconds. Never the feed stack or the tables:
  jitter on text you are reading is an annoyance, not atmosphere.
* **Line draw on.** Coastlines, rivers and borders trace themselves over
  about two seconds, the way the film's screens draw. In the app this plays
  on load and on every airport change, never on a loop.
* **Phosphor persistence.** Moving things leave a short fading afterimage.
* **Vignette.** Corners darken: to 27% at the edge in `vector`, 42% in
  `crt`. (These are the mockup's values after it was dialled back by 30%.)
* **Scanlines** (`crt` only). One dark line every three pixels at 34%
  opacity, over every screen.
* **Corners** (`crt` only). Screens get a 16 px radius.
* **Colour fringe** (`crt` only). The radar gets a one pixel red and cyan
  offset, at 35%.

**Where each effect is done.** The radar is a canvas, so it gets one small
WebGL pass after it is drawn: bloom, persistence (each frame fades the
last instead of clearing it), beam flicker and the colour fringe. That is
the right place for them, because persistence and bloom need the pixels.
Everything else on the page is ordinary HTML, which a canvas shader cannot
reach, so flicker, jitter, vignette, scanlines and corners there are CSS:
an overlay element per screen, with `pointer-events: none` so it never
takes a click.

**Our own code, not a library.** [RetroZone](https://github.com/TheMarco/retrozone)
(MIT) is the closest existing match: a WebGL pass over any canvas with a
vector mode (bloom, persistence, beam flicker) and a CRT mode (scanlines,
interlace flicker). It is a good reference for the shaders, credited where
we borrow from it. It is not a dependency, because it ships only through
npm (and this front end has no build step), its flicker and noise are not
adjustable, and at the time of writing it is two commits old. The pass we
need is about two hundred lines.

**Settings, not states.** `display` and `glow` are remembered beside the
palette, so every tab and every launch agrees.

### Map data

Built offline by `tools/build_geodata.py`, the same pattern as
`tools/build_airports.py`, and committed so the map needs no network:

| Layer | Source | Licence |
|---|---|---|
| Coastlines, lakes, rivers | Natural Earth 10 m | public domain |
| Country and state borders | Natural Earth 10 m | public domain |
| Navaids | OurAirports `navaids.csv` | public domain |
| Runways of every airport in the dataset | OurAirports `runways.csv` | public domain |
| Class B, C and D airspace (US) | FAA aeronautical data | public domain |

Simplified to the resolution a 40 nm screen can show, the whole set should
land in single digit megabytes. The server clips it to the current airport
on each change and sends only what is on screen, so the browser never loads
the world. Outside the US there is no airspace layer; everything else is
global.

The home airport's runways are drawn as white lines inside its ring at
close zoom, which is the stills' base outlines put to honest use.

### Keyboard

| Key | Action |
|---|---|
| `↑` `↓` | select |
| `space` | mute or unmute selected |
| `S` | solo selected |
| `a` | ambient for selected |
| `f` | feed picker |
| `c` | config sheet |
| `/` | airport search |
| `t` | next theme |
| `q` | shut down (asks first) |
| `esc` | close whatever is open |

Keys are ignored while focus is in a text field, which is the browser's
version of the picker's "typing always filters" rule. `^q` is not needed:
the airport search no longer has to compete with a bare `q`.

## The launcher

`bin/kcgx` stops being a tmux script and becomes a thin wrapper over a new
`kcgx` console script:

```
kcgx              start the server if it is not running, then open the page
kcgx go [query]   pick an airport (terminal prompt, or exact ICAO) and tell the server
kcgx stop         ask the server to stop
kcgx --no-open    start without opening a browser
```

The server runs detached, writes its port and pid to
`~/.local/state/kcgx/server.json`, and logs to
`~/.local/state/kcgx/server.log`. "Running" means `GET /api/health` answers,
not that the file exists; a stale file from a crash is replaced. The default
port is `8473` (`KCGX_PORT` overrides it); if it is taken by something that
is not kcgx, the server picks a free one and records it.

`kcgx go` without a query keeps the existing Textual picker for now, since
it is a terminal command; with `--open` it opens the page with the search
already showing instead.

## Security

A server on localhost is reachable by every web page the browser opens, so
two checks apply to every request and the WebSocket handshake:

* **Host** must be `127.0.0.1:<port>` or `localhost:<port>`. That defeats
  DNS rebinding.
* **Origin**, when present, must be the same. That stops another site's
  page from muting your feeds or shutting the cockpit down.

No authentication beyond that: it is one person's machine.

## Install changes

`setup.sh` gets shorter.

| Step | Becomes |
|---|---|
| 2 System packages | `ffmpeg` and PortAudio; **tmux dropped** |
| 4 Python dependencies | adds `starlette` and `uvicorn` |
| 5 Launcher on `PATH` | unchanged, and no longer critical: no popup depends on it |
| 6 `adsb-tui` | **removed**, with its licence prompt |
| 7 Where the radar gets aircraft | **removed**; there is no adsb-tui config to write |
| 8 Feed list | unchanged |
| 9 Checking it works | starts the server, insists on `200` from `/api/health`, checks the page and the WebSocket, then stops it |

Platform support widens: with no adsb-tui binary to download, ARM Linux is
no longer a stopping point.

## Components

```
src/squelch/cockpit.py        new: the controller extracted from app.py
src/squelch/app.py            drives Cockpit (until retired)
src/kcgx/server.py            new: Starlette app, WebSocket hub, routes
src/kcgx/radar.py             new: adsb.lol poller and backoff
src/kcgx/launcher.py          new: start/stop/go, server.json, health check
src/kcgx/web/                 new: index.html, css, js modules, vendor/
src/kcgx/web/vector/          new: projection, glow pipeline, Hershey text
src/kcgx/geodata.py           new: loads and clips map layers per airport
src/kcgx/data/geo/            new: committed map layers
tools/build_geodata.py        new: builds them from the sources above
src/kcgx/state.py             gains theme read/write beside the airport
```

Removed in the final phase: `bin/kcgx`'s tmux logic, `kcgx.tmux.conf`,
`squelch/radar_theme.py`, the Textual halves of `themes.py`, `rows.py`,
`config_view.py`, `kcgx/status.py`, `kcgx/bigtext.py`. Whether
`squelch/app.py` and `kcgx/picker.py` go too is an open question.

## Testing

* **Controller.** `test_cockpit.py` takes over the behaviour tests from
  `test_app.py`: ordering, resort timing, slots, refusal, solo restore, open
  feed. Fake sessions, a fake clock, no Textual.
* **Server.** Starlette's `TestClient` drives routes and the WebSocket
  against a `Cockpit` with fake sessions: a mute message produces a `feed`
  and an `order` message; Host and Origin checks reject what they should.
* **Radar.** The poller against a fake fetch: success, `429`, `403`, backoff
  and reset, stale aging, coordinates moving on an airport change.
* **Geodata.** The build is deterministic; clipping keeps exactly what
  falls inside the range; the projection round trips; an airport near the
  antimeridian or a pole does not tear the map.
* **Look.** Playwright screenshots of the radar and the stack against fixed
  fake data, one per palette, compared to committed references. A visual
  change has to be accepted on purpose. Screenshots are taken with reduced
  motion forced on, so flicker and jitter cannot make them flaky; one more
  per `display` mode checks the static parts of each (scanlines, corners,
  vignette).
* **Emergency squawks.** A fake poll sequence where a squawk appears,
  persists and clears produces exactly two log lines and lights, then
  darkens, the emergency lamp.
* **Launcher.** Start, second start reuses, stale `server.json`, `stop` when
  not running is not an error, port collision.
* **Browser.** One Playwright smoke test against Chromium (already in the
  dev environment) with fake sessions: the page loads, rows render, `space`
  mutes, the levels stream moves a meter, airport search retargets. Kept
  deliberately small; the logic lives in Python where it is cheap to test.
* **Manual.** One run against real hardware and a live airport, as the
  mixer work required: audio continuous, meters in step with what is heard,
  radar populated, tab closed and reopened without a gap in the audio.

## Build order

| Phase | What | Gate |
|---|---|---|
| **A** | Extract `Cockpit`; terminal squelch runs on it | all existing squelch tests pass, moved where they belong |
| **B** | Server, routes, WebSocket, levels loop | server tests pass; a fake cockpit is drivable from a script |
| **C** | Page: status header, feed stack, meters, config sheet, feed picker, messages | Playwright smoke test |
| **D** | Radar: geodata build, vector renderer, poller, aircraft, table, palettes | geodata and screenshot tests; manual check at a busy airport |
| **E** | Launcher, `setup.sh`, README; remove tmux, adsb-tui and the Textual UI | parity table holds end to end; manual hardware run |

A comes first because it is the only phase that touches working code, and it
leaves the terminal cockpit intact. B through D add new files alongside the
existing cockpit, reachable as `kcgx web` while they are being built. E is
the switch, and the only phase that deletes anything.

## Error handling

* **No audio device.** As today: one warning, every feed still connects and
  meters. The page shows it in the log and as a persistent badge on the
  volume control.
* **ffmpeg missing.** The server refuses to start, with the same message
  squelch prints today; `kcgx` prints it in the terminal it was run from.
* **WebSocket drops** (laptop sleep, server restart). The page shows a
  "reconnecting" bar, retries with backoff, and redraws from a fresh
  `snapshot` on reconnect. Nothing is lost, because the server holds all
  state.
* **Server dies.** The page says so and stops pretending to be live. `kcgx`
  starts a new one.
* **Feed listing refused.** Unchanged behaviour and messages, including "press
  f to retry".
* **adsb.lol refused.** Last good picture, age badge, backoff, as above.

## Open questions

1. **How much of the film to quote.** The palette, shapes and lamp bar
   are in. A `GREETINGS PROFESSOR FALKEN` style line in the teletype on
   first launch, or a DEFCON style status readout, would be fun and is easy
   to overdo. Leaning toward one quiet nod in the splash and none in the
   working UI.
2. **Keep the terminal squelch?** After phase A it costs little to keep
   `squelch` as a standalone terminal player on the shared controller. The
   cost is keeping Textual as a dependency and its tests alive.
3. **Feed reordering under the pointer.** Hovering the stack counts as
   touching it, so rows do not move under a cursor that is about to click.
   That may hold the order still for too long if the mouse just rests there;
   needs a feel test.
4. **Port.** `8473` is arbitrary. Fine unless it collides with something
   you run.
5. **Alarm colour in the monochrome palettes.** In `amber` and `matrix`
   the alarm colour is white rather than red orange, to keep them single
   hue. Worth checking on real hardware that an emergency still reads as
   one at a glance.
