# The cockpit in a browser

*2026-10-18. Changed by phase F on 2026-11-12 (the owner's "KCGX Tweaks
11/12" list, and a window of its own); each change is written into the
section it belongs to and carries that date. The plan, with its fifteen
decisions, is `docs/superpowers/plans/2026-11-12-cockpit-tweaks.md`.
Changed again by phase G on 2026-11-13 (the owner's second list of that
title), the same way: each change in its section, dated 2026-11-13 and
naming the decision it comes from. That plan, with its twenty-two
decisions, is `docs/superpowers/plans/2026-11-13-cockpit-tweaks-g.md`.*

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
│        ASA412 6172  ╲                │ │  M   S        34 │
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

**The wall as it stands since 2026-11-12 (phase F).** The owner's list of
that day rearranged it, and where the list and the mockup disagree the
list is the later word. The lamp bar and the teletype are shown only when
turned on, the status screen lost its title, and the frequencies run the
full height of the right column:

```
 KCGX  LOCAL COCKPIT 127.0.0.1:8473                        ⚙  ⏻
┌──────────────────────────────────────┐ ┌──────────────────┐
│                                      │ │ KPDX   1955Z     │  the airport
│   coastline, rivers, borders         │ │ PORTLAND       ⌕ │  (no title)
│        ASA412 6172  ╲                │ ├──────────────────┤
│                 ⟵────  trail         │ │ TOWER (BOTH)   ● │
│               TRAFFIC                │ │ ╱╲__╱╲╱╲_____╱╲_ │
└──────────────────────────────────────┘ │  M   S       34% │  frequencies
 ▪ ▪ ▪ ▪  lamp bar, when turned on       │ GROUND    7%   ◐ │
┌──────────────────────────────────────┐ │                  │
│ traffic table                        │ ├──────────────────┤
│               TRACKS                 │ │ teletype, when   │
└──────────────────────────────────────┘ │ turned on        │
                                         └──────────────────┘
```

And `kcgx` no longer has to open a browser tab: on a Mac the page is shown
in a small app of its own (see [The launcher](#the-launcher)).

**The wall since 2026-11-13 (phase G).** The second list kept the layout
and changed what is in it. The frequencies screen opens with a master
mute and the volume, and holds one expanded feed, the one heard. The
tracks screen has a grip along its top edge and tools in its title bar,
and may be folded to that bar, the radar taking the room. A cockpit
launch opens on the boot animation, over all of it (see [The boot
animation](#the-boot-animation)):

```
 KCGX  LOCAL COCKPIT 127.0.0.1:8473                        ⚙  ⏻
┌──────────────────────────────────────┐ ┌──────────────────┐
│ 5 SECONDS AGO              12 TRACKS │ │ KPDX   1955Z     │  the airport
│ RNG 40 NM                            │ │ PORTLAND       ⌕ │
│   ┌──────────┐  ASA412 6172          │ ├──────────────────┤
│   │ data box │ ╲                     │ │ ◁) ━━━━━━━━  80% │  master mute, volume
│   └──────────┘  ⟵──── TRAFFIC        │ │ TOWER     34%  ● │
└──────────────────────────────────────┘ │ ╱╲__╱╲╱╲_____╱╲_ │  the one heard
╞══════════ grip: drag for height ═════╡ │ GROUND    7%   ◐ │  a click picks it
┌──────────────────────────────────────┐ │                  │
│ CALLSIGN TYPE ALT…   (sticky header) │ │                  │
│ [filters]                            │ │                  │
│ TRACKS          CLEAR COLUMNS  ⌄     │ │   FREQUENCIES    │
└──────────────────────────────────────┘ └──────────────────┘
```

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

Every row must hold before the terminal cockpit is retired. They did:
phase E retired it on 2026-10-22, after the owner checked phases C and D on
the Mac against real feeds and traffic.

| Today | In the browser |
|---|---|
| One row per feed, all metering, one audible at start | Same, from the same `build_sessions` |
| Expanded row (meter + controls) when audible, compact when muted | Same rule. Meter becomes a scrolling bar strip on a canvas |
| `●` live, `◐` reconnecting, `○` offline, `‖` parked | Same states, same glyphs, plus a tooltip naming the state |
| Audible first, then by five minute chatter | Same `rank()` |
| Reorder only after 15 s stable and 2 s untouched | Same `Resorter`. "Touched" now includes pointer hover over the stack |
| Mute/unmute moves the row at once; selection follows the feed | Same |
| `space` mute, `S` solo, `a` ambient, `↑` `↓` select | **M** and **S** buttons on each row; no keys (see Every action is a click). **Ambient is dropped from the page**: no button for it (decided 2026-10-19). The server and protocol keep it, so it can return without a protocol change |
| Click anywhere on a row toggles mute | Same |
| Seven stream limit, parking, refusing an eighth audible feed | Same `slots.plan()` and the same refusal message |
| `c` config overlay, master volume live in 5% steps | CONFIG button opens a side sheet. Volume is a slider; other rows keep live/inert/fixed/off labels |
| `f` feed picker, opens a feed that is not open | FEEDS button opens the same, as a searchable list |
| Message log, capped at 200 | Same cap, same text |
| Feed list cache, retry budgets, one feed fallback, never another airport's audio | Unchanged: `load_feeds`, `picker_feeds`, `_no_feeds` move as they are |
| `squelch --refresh-feeds` | `kcgx-web --refresh-feeds [--icao]` (phase E); `squelch.runtime.refresh_feeds` does the work, as before |
| Status pane: big ICAO, airport name, Zulu and local clocks | Airport name in large stroked capitals beside its ring on the radar; ICAO and both clocks on the status screen. Local is the viewer's own clock and zone, since the airport dataset has no time zones |
| `Ctrl-b a` / click `▾ airport` opens airport search | CHANGE AIRPORT button, or click the airport name; same `search()` over the same CSV |
| `kcgx go [query]`, exact ICAO skips the picker | Same CLI; it talks to the running server. An ICAO, or a query naming one airport, switches at once (starting the server there if need be); none, or one naming several, opens the page at `#airport=<query>` with the search showing (phase E) |
| Remembered airport in `~/.local/state/kcgx/airport` | Same file, same `current_icao()` resolution order |
| Airports LiveATC does not cover still get a radar | Same: empty stack with a message, radar works |
| Radar: aircraft around the airport from adsb.lol, 15 s polling | Our own radar on a map. Same endpoint, same interval, same polite User-Agent |
| adsb-tui traffic table, row selection | Traffic table under the map; selecting a row or a blip highlights both |
| adsb-tui `t` theme cycling, six themes | PALETTE button cycles four palettes: WOPR, AMBER, MATRIX, MONO (see Themes) |
| squelch follows the radar's theme | **Dropped.** One app, one theme setting |
| Header shows `ERR 429` / `ERR 403` on a refused refresh | Radar shows the last good picture with a "refresh refused" badge |
| Dead pane stays visible; `Ctrl-b r` respawns it | A failed feed or radar shows its error in place, with a retry control |
| Running `kcgx` again reattaches | Running `kcgx` again opens a tab on the running server |
| Closing the terminal detaches, audio continues | Closing the tab, same |
| `kcgx stop`, `Ctrl-b q` (asks first), picker `^q` stops every cockpit | `kcgx stop`; a Shut down control in the page (asks first) |
| `q` in squelch quits | SHUT DOWN button, which asks first |
| Refuses below 100 columns | Responsive: below about 900 px the radar and stack stack vertically |

**Rows changed since, by phase F (2026-11-12).** The table above is what
was accepted when the terminal cockpit was retired, and is left as it was.
The owner's list of 2026-11-12 then changed these:

| Row | Since 2026-11-12 |
|---|---|
| `c` config overlay | CONFIG is a gear icon. Its sheet docks to the right edge with a clear backdrop and holds every setting of the look, the layout and the radar (decision 10; see Themes). LIMITS, its one row that could not be changed, is gone |
| `f` feed picker | **Removed from the page** (decision 2). Every feed an airport publishes already opens at launch, so the picker only mattered when the listing could not be fetched, and choosing the airport again refetches it. The server keeps `/api/feeds/available` and `open_feed`, which `/debug` still drives |
| Message log | Unchanged in what it holds; **hidden unless turned on** (TELETYPE in CONFIG). See "The log is a teletype" |
| Status pane | No STATUS title; a search icon, bottom right opposite the airport's name, in place of the CHANGE AIRPORT button |
| Traffic table, row selection | The focused aircraft is also the table's first row, a fifth larger (decision 7) |
| `t` theme cycling | No PALETTE button: the four palettes are THEME, a dropdown in CONFIG (decision 11) |
| Running `kcgx` again reattaches | Shows the running cockpit in its own window on a Mac, in a tab elsewhere (decision 14) |
| Closing the terminal detaches | Closing the window, like closing the tab, leaves the audio playing; **quitting the app stops the cockpit** (decision 15) |
| `q` quits; `Ctrl-b q` | The power icon in the header, which asks first; Quit in the window |

**Rows changed since, by phase G (2026-11-13).** The second list changed
these, and the two tables above are left as they were:

| Row | Since 2026-11-13 |
|---|---|
| One row per feed, one audible at start | One audible **always**: a feed is picked like a radio button (decision 3). Every feed still has its row and meters |
| Expanded row when audible, compact when muted | Same rule, and so exactly one expanded row. Its head is title, chatter, state glyph; its trace is 60 px tall |
| `space` mute, `S` solo; M and S buttons | **No M or S on the page.** A click on a compact row picks that feed. `mute` and `solo` stay in the protocol for `/debug` |
| Click anywhere on a row toggles mute | Click anywhere on a compact row picks it; a click on the one playing does nothing |
| Mute/unmute moves the row at once | Picking moves the rows at once |
| `c` config overlay, master volume live in 5% steps | CONFIG fills the window, in four tabs (decision 2). Volume, and a new master mute, sit at the top of the frequencies screen (decision 3) |
| adsb-tui traffic table, row selection | Seventeen columns to choose from, a filter on each, the sort a setting that also ranks the radar, a header that stays, a height to drag and a fold (decisions 4, 5 and 18) |
| Running `kcgx` again reattaches | The first cockpit page after a start plays the boot animation; reattaching does not (decision 1) |

## Architecture

```
            browser tab(s)
   ┌───────────────────────────────┐
   │  radar   status   feed stack  │   plain ES modules, no build step
   └──────────────┬────────────────┘
        HTTP + one WebSocket, 127.0.0.1 only
   ┌──────────────┴────────────────┐
   │  kcgx.server  (Starlette)     │  routes, /ws, LocalOnly guard, ticks
   │  kcgx.hub                     │  open pages, one queue each; the log
   │  kcgx.station                 │  mixer, airport, actions for pages
   │   Cockpit controller          │  extracted from SquelchApp
   │   RadarPoller                 │  adsb.lol, every 15 s (phase D)
   │   FeedSessions + Mixer        │  unchanged
   └──────────────┬────────────────┘
              sounddevice → speakers
```

`kcgx.protocol` holds every JSON shape that crosses the socket, in both
directions, as pure functions; nothing else builds a frame. `squelch.runtime`
holds feed loading and session building (`load_feeds`, `build_sessions`,
`picker_feeds`), moved out of `squelch.__main__` because that module imports
Textual and the server must not. `squelch.__main__` re-exported every name
until phase E removed it with the terminal app.

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

    sessions -> list                    # stack order; a copy
    def session(self, ident)            # by ident, or None
    def start(self) -> None             # take stream slots; say what parked
    def toggle_mute(self, ident) -> bool
    def toggle_solo(self, ident) -> bool
    def toggle_ambient(self, ident) -> bool
    def open_feed(self, feed)           # the new session, or None
    def tick_resort(self) -> None       # its owner calls it every 5 s
    def note_input(self) -> None        # feeds Resorter's quiet period
    def stop(self) -> None              # stop every session, say nothing
```

**No wire format and no volume on `Cockpit`.** Snapshots and level frames
are the server's business and live in `kcgx.protocol`; volume belongs to the
mixer, which belongs to the server, not to an airport. That keeps `Cockpit`
free of anything a page needs, so the terminal app drives exactly the same
object.

It emits changes through a single callback (`on_change(kind, payload)`) in
place of `call_from_thread`. Feeds are addressed by `ident`, not by
`id(session)` or row index, because a browser cannot hold a Python object id
and an index is exactly the thing reordering changes.

`SquelchApp` is then rewritten to drive a `Cockpit`. **That is the gate for
everything after it:** the terminal squelch keeps working on the new
controller, every existing test passes without being edited, and
`test_cockpit.py` covers the same rules with no Textual involved. The
app's tests retire with the terminal UI in phase E; the cockpit's stay. If
the browser work stopped there, the codebase would still be better for it.

Selection is the one thing that does not move. It belongs to a viewer, not
to the airport, so it stays in the terminal app, which needs it for its
keys. The web page has no selection at all (see Every action is a click):
each control sends its own row's ident.

**`Cockpit.select(ident)`** (2026-11-13, phase G decision 3) is not that
selection: it picks the one feed that is heard. It leaves only that feed
audible, cancels any solo, reconciles the streams (a parked feed is
started, and another parked to keep the count), announces each
feed that changed once, and reorders at once. Picking the feed already
audible changes nothing and says nothing. The rule "one feed at a time"
lives here, on the server, so every tab keeps it whatever it sends;
`build_sessions` already started with one audible feed, and `select` keeps
it so. The master mute is the mixer's (`Mixer.master_muted`: silence out,
the volume kept, every channel still metering), not the cockpit's, and,
like the volume, it is state, not a pref.

### Changing airport

Today `kcgx go` writes the state file and respawns two tmux panes, so a new
airport is a new squelch process. In the server it is in process:

1. `write_airport(icao)`.
2. `cockpit.stop()`, then `Mixer.clear_channels()`. Clearing rebinds the
   channel list rather than emptying it in place, and the audio callback
   reads the list once per block, so a clear from the event loop never
   disturbs a block PortAudio is in the middle of.
3. An empty `Cockpit` for the new airport, and a snapshot with
   `loading: true` to every page, so the change shows at once.
4. `load_feeds` for the new ICAO on a worker thread, because the listing
   fetch can take several seconds of retries; then, back on the loop, the
   new sessions, a new `Cockpit`, its `start()`, and a second snapshot with
   the feeds.
5. The radar poller moves to the new coordinates (phase D).

A second change while the first is still fetching wins: every change bumps
a generation number, and a fetch that finishes under an older one is thrown
away before any of its sessions are built. Session events from the airport
before, still arriving as their threads wind down, are dropped for the same
reason: the station only reports sessions that belong to the cockpit on
show.

The mixer itself survives the switch, so the output device is opened once
per server and an airport change never produces a click or a device
renegotiation. The owner confirmed this on the Mac on 2026-10-19.

### Radar

The server polls `https://api.adsb.lol/v2/point/{lat}/{lon}/{range_nm}` and
pushes the result to clients. It is polled on the server, not in the
browser, for three reasons:

* adsb.lol refuses requests without a contactable `User-Agent`, and a
  browser is not allowed to set one.
* One poller serves every open tab, so two tabs do not double the rate.
* The 15 second interval and the over-rate penalty described in the README
  apply per address; the server is where that discipline can be kept.
* adsb.lol's OpenAPI document (read 2026-11-14) now also states a daily
  quota on `/v2/`: 500 requests per address with no key, 1,000 with a
  free key, 7,200 for a feeder, `429` with `Retry-After` beyond it.
  Every 15 s is 5,760 a day. KCGX sends no key and does not read
  `Retry-After`; whether the quota is enforced has not been seen (a live
  reply carried no quota headers). An open question for the owner.

`KCGX_ADSB_UA` keeps its meaning. `refresh_secs` and the range move into
`squelch.toml` as `radar_refresh_secs` (default `15`), `radar_range_nm`
(default `40`) and `radar_stale_secs` (default `60`), all whole numbers. A
config file can lengthen the interval but never shorten it below adsb.lol's
15 s. (The range left the file on 2026-11-12 and the interval on
2026-11-13; both are prefs now, below.) A refused poll keeps the last good aircraft list, marks it with its
age, and backs off: 15 s, 30 s, 60 s, capped at 120 s, reset on the first
success. The page names the refusal: `ERR 429`, `ERR 403`, `NO CONNECTION`.

**The range is a setting, not a config key** (decided 2026-11-12, phase F,
decision 1). The owner asked to "control the radar's range to the maximum
possible value". adsb.lol's own OpenAPI document gives the point endpoint
a maximum radius of 250 nm, so the range is a pref, `range_nm`, a whole
number from 10 to 250 (default 40), set by a slider in CONFIG in steps of
10 and remembered with the other prefs. `radar_range_nm` left
`squelch.toml` on that date; a file that still sets it loads, because
unknown keys are ignored. A change reaches the running radar
(`Radar.set_range`) and **never causes a poll**: the new range is asked
for at the next poll that was due anyway, so a dragged slider cannot
become a burst against adsb.lol's 15 s ask. Shrinking the range drops the
aircraft beyond it at once, and a reply that was asked for at a wider
range is cut to the new one before it is merged. An aircraft dropped for
being out of range takes its emergency squawk out of the announced set
without a line in the log; a wider range that brings it back announces it
afresh.

**The poll interval is a setting too** (2026-11-13, phase G decision 16).
`radar_refresh_secs` left `squelch.toml` and became the pref `poll_secs`,
15 to 120 s in steps of 5 (default 15), RADAR POLL in CONFIG. The schema
cannot go under 15, adsb.lol's ask. As with the range, a change reaches
the radar (`Radar.set_refresh`) and never causes a poll. The back-off
still doubles the interval per refusal in a row, now capped at two
minutes or four intervals, whichever is longer, so it backs off at least
twice at any interval (15, 30, 60, 120 s; at 120: 240 and 480 s).

**Every field the table can show** (2026-11-13, Task 7). Each aircraft
now also keeps readsb's `r`, `baro_rate` and `category`, sent as `reg`,
`vs` and `cat`: text in capitals, the rate rounded, `null` where the
reply leaves one out. The plan said to read adsb.lol's OpenAPI document
first and keep only the fields `/v2/point` promises. Task 7 kept `desc`
and `ownOp` too, as `desc` and `oper`, without the document; read on
2026-11-14, it has `r`, `baro_rate` and `category` (optional, as every
field but a few is) and neither of the others, and a live `/v2/point`
reply at KORD that day (36 aircraft) had `r` on all, `category` on 35,
`baro_rate` on 22 and `desc` or `ownOp` on none. DESC and OPER were
dropped. A file that saved either among its columns, or as the sort,
loses that setting to its default, as any bad value does; both lived one
day, unreleased.

**How long a track has stood still** (2026-11-13, decision 9). A track is
still while its ground speed is under `ground_gs` and it reports `GND`
or, with `ground_alt` above 0, a barometric altitude under it. The frame's
`still` is the seconds it has been so, counted from the poll it first
qualified; one poll that finds it otherwise resets it to 0, and one that
does not hear from it changes nothing. It is counted on the server so
every tab agrees and a reload keeps the clock. The altitude is above sea
level, since the airport dataset has no elevations; at a high field
`ground_alt` should stay 0, where only `GND` counts. `Radar.set_ground`
takes the two thresholds from the prefs, as `set_range` takes the range.
What the page does with `still` is under Visual language.

The picture is the server's (`kcgx.radar`, built in phase D): it merges
each poll into the aircraft it already has, drops any not heard from for
`radar_stale_secs`, numbers aircraft with no callsign `UNK1`, `UNK2` in
order of first sighting, and announces emergency squawks, so every tab
agrees on all of it. An airport change forgets the picture and polls the
new field at once; a reply for the old field that arrives late is thrown
away.

In the browser the radar is **our own vector renderer, not a map
library.** The look calls for line art and nothing else: no imagery, no
tiles, no fills. That rules out MapLibre and its base styles, and it is a
better trade anyway: no tile provider, no key, no network dependency for
the map, and full control over every stroke.

The projection is azimuthal equidistant centred on the airport, so range
rings are true circles and distance reads straight off the screen. Positions
are dead reckoned between polls from ground speed and track, as adsb-tui
does, and an aircraft starts to fade 30 s after its last position and
drops at `radar_stale_secs`. The geography comes from vendored public domain data, built
the way `airports.csv` already is; see [Map data](#map-data).

The traffic table under the map shows callsign, type, altitude, ground
speed, track, distance and squawk, sortable by column (nearest first by
default), and scrolls within its screen. Selecting a row and selecting a
blip are the same action. The "collapses to a single summary line" of
earlier drafts was not built: the wall's fixed rows already give the table
its own screen. Since 2026-11-12 (decision 7) the focused aircraft is the
table's first row however it was focused, and sorting orders the rest
beneath it; see "Click an aircraft to focus it" under Visual language.

**The table since 2026-11-13 (phase G).**

* **Columns are chosen.** `columns.js` holds all fifteen (CALLSIGN,
  TYPE, REG, ALT, VS, GS, TRK, DIST, BRG, SQWK, HEX, CAT, AGE, LAT, LON;
  DESC and OPER until 2026-11-14), each with its title, its text, its sort value and its filter
  kind; the table and the radar's data box both read an aircraft through
  it, so a value reads the same in each. A figure not reported sorts
  below every real one. The table shows `track_cols` in that order,
  chosen in CONFIG or from a COLUMNS checklist in the title bar (a
  popover, so the pane does not clip it). The last column shown cannot be
  unchecked.
* **Filters belong to the table** (decision 4). A row under the header
  holds one per column: a substring in any case for text columns, a MIN
  and a MAX for number columns (`GND` is 0; once a bound is set an
  aircraft that reports nothing is left out). CLEAR empties them. They
  hide rows and never touch the radar, and they are the page's, not
  prefs: gone on a reload, so nothing is hidden at the next launch for a
  reason nobody remembers. The focused aircraft passes every filter.
* **The sort belongs to both** (decisions 4 and 5). `track_sort` and
  `track_desc` are prefs: a header click sends both, and the table sorts
  on the server's answer, so every tab sorts alike. The sort, with no
  filter applied and the focus first, ranks every aircraft for the radar:
  `store.state.rank`, hex to 0 for the first and 1 for the last, with a
  `rank` event when it changes. A sort on a column not shown is named in
  the title bar (`SORT GS KT ▼`).
* **The header stays.** The header row and the filter row are sticky and
  opaque, so the table scrolls under them.
* **The pane resizes and folds** (decision 18). Its top edge is a grip, a
  `separator` 6 px tall, dragged or moved by the arrow keys (2 %), Page Up
  and Down (10 %), Home and End; a drag previews on the page and sends
  `tracks_pct` on release, and Escape puts it back. `tracks_pct` is the
  pane's share of the page's content box, not of `vh`, so it holds under
  UI zoom in both engines. The row is `minmax(0, N%)`: a share too tall
  for the window, as a stored 80 from a taller one, shortens the pane and
  never lengthens the page. A drag stops at the larger of 10 % and the
  header, the filters and two rows, and where the radar would be left
  under 48 px. A button in the title bar sends `tracks_open`; folded, the
  pane is its title bar and the radar takes the rest, and with the
  teletype shown the two title bars stay level. Under 1100 px there is no
  grip, and folding works. Rows are rebuilt only on traffic, the table's
  prefs, the focus and the filters: 600 aircraft take 4 to 5 ms of
  script.

So the "collapses to a single summary line" of earlier drafts, not built
in phase D, now is, as a fold to the title bar.

### Transport

**HTTP** for things that happen once:

| Route | Does |
|---|---|
| `GET /` | the cockpit page, served `no-cache` so an edit shows on a plain reload |
| `GET /static/…` | the page's stylesheet, ES modules and fonts, also `no-cache` (phase C) |
| `GET /debug` | phase B's bare page, kept because it shows the raw protocol (phase C) |
| `GET /api/geo?icao=` | the radar's map for that airport: every line, place and runway within 320 nm (200 until 2026-11-12, when the range grew to 250), `404` for an unknown airport (phase D) |
| `GET /api/health` | `200` with version, protocol, airport and `loading`; used by the launcher |
| `GET /api/airports?q=` | `search()` results |
| `POST /api/airport` | `{"icao": "KSEA"}`; answers `202` at once, `404` for an unknown airport, `400` for anything malformed. The change itself reaches pages over the socket |
| `GET /api/feeds/available` | `picker_feeds()` for the feed picker, each marked `open` or not. Kept when the page's picker went on 2026-11-12; `/debug` uses it |
| `POST /api/shutdown` | stop the server; asks nothing (the page asks first) |

**One WebSocket** at `/ws` for everything live. Every frame is a JSON
object with a `t`. Server to page:

| `t` | Carries | When |
|---|---|---|
| `snapshot` | `protocol`, `airport`, `loading`, `feeds` (stack order), `volume`, `max_streams`, `audio_ok`, `log`, `prefs`; since 2026-11-13 `muted` (the master mute) and `boot` | the first frame on every connect, always; after an airport change, once with `loading: true` and again with the feeds |
| `feed` | one feed view; since 2026-11-13 it carries `title`, the name without the airport when `short_names` is on | its state, mute, solo, ambient or connection changed; every feed again when `short_names` changes |
| `added` | one feed view | a feed opened from the picker |
| `order` | `idents`, the new stack order | any reorder |
| `levels` | `v`: ident to dBFS, one decimal | 25 Hz, only while a page is open; droppable |
| `chatter` | `v`: ident to five-minute fraction | every resort tick; droppable |
| `volume` | `value`; since 2026-11-13 `muted` | the volume or the master mute changed |
| `message` | `z` (Zulu, `1955Z`), `text` | a line added to the log |
| `prefs` | every setting: `palette`, `glow`, `display` (phase C) and, since 2026-11-12, the eleven more listed under Themes; since 2026-11-13 the fifty-four of `kcgx.prefs.SCHEMA`, `map` whole | any page changed one; every tab follows |
| `error` | `text` | this page sent something the protocol does not have |
| `aircraft` | `ok`, `error`, `age` (seconds since the last good poll), `refresh`, `range`, and `ac`: per aircraft `hex`, `label`, `type`, `lat`, `lon`, `alt` (feet or `GND`), `gs`, `trk`, `sq`, `age`, `dist`, `brg`; since 2026-11-13 also `reg`, `vs`, `cat` and `still` (and `desc` and `oper` until 2026-11-14) | each poll, success or refusal, and on an airport change (empty); the snapshot carries the latest as `radar` (phase D) |

Page to server: `mute`, `solo`, `ambient` and `open_feed`, each with an
`ident`; `volume` with a `value`, clamped to 0..1; `input`, the "you
have touched the stack" signal that keeps reordering away from the pointer;
and `prefs` with one or more of `palette`, `glow` and `display`, each
exactly one of its known names (phase C). Since 2026-11-12 a `prefs`
message may carry any of the fourteen settings in `kcgx.prefs.SCHEMA`,
each checked as its kind allows (a choice by name, a flag as a JSON
boolean, a number as a whole number in its range, a subset as a list of
known names); a bad value is refused naming the setting, and so is a
setting the schema does not have, even beside ones it does. The new keys
are additive, so `protocol` is still 1. Since the same date the page sends
no `open_feed`; the message stays for `/debug`.

Since 2026-11-13 (phase G): `select` with an `ident` picks the one feed
heard, and `master_mute` with `on`, a JSON boolean, silences the output.
The page sends no `mute` or `solo`; both stay, for `/debug`. A `prefs`
message may carry any of the fifty-four settings, and a table (`map`)
**partially**: any rows, any of each row's own columns
(`{"map": {"COAST": {"alpha": 60}}}`). The server lays it over what is
set a cell at a time (`prefs.merge`), so two tabs changing two cells both
land; the file and every frame hold the table whole. A cell that fails,
or a row or column the table does not have, refuses the whole message
and the refusal names it (`map.COAST.alpha`). All of it is additive:
`protocol` is still 1.

**The boot is told once** (decision 1). The snapshot's `boot` is true for
the first cockpit page the hub welcomes after the server starts, and
false for every other, a reconnect included. Only the cockpit uses it up:
the page connects to `/ws?page=cockpit`, and anything else (`/debug`, the
self check, an older page) is told false without spending it, so a self
check run before the window opens cannot take the animation from it.
The parser is strict: a wrong type, an ident that is not lower case letters,
digits and underscores, a non-finite volume, or an unknown `t` gets an
`error` frame back, so a page bug shows up rather than a control that
silently does nothing. **`open_feed` names an ident only, and only from the
picker's last list;** the server never takes a feed's label from a page.

**Feeds are addressed by ident everywhere, including in `levels` and
`chatter`.** Those two are keyed by ident rather than given in stack order,
because the order can change between two frames, and a positional list
would hand one frame's levels to the wrong rows for 40 ms. Thirty feeds
keyed by ident at 25 Hz is about 15 KB/s on localhost, which needs no
binary framing.

**Levels are the only high rate stream.** 25 Hz matches `LEVEL_INTERVAL`
today. Every feed's level is sent, muted or not, because every feed meters
today and a row that expands should already have its history. The browser
keeps that history; the server keeps none. The levels loop reads
`session.level` exactly as `_tick_levels` does: polled from the event loop,
never pushed from the audio callback, which stays a real time context that
touches nothing else.

**The server ticks the resort**, every 5 s as `SquelchApp`'s timer does, and
sends a `chatter` frame with each tick so pages can show the five-minute
figures moving. Pages only ever see the order the server applied.

**One slow tab never holds up the others.** The hub gives each open page its
own bounded queue (64 frames) and its own sender task. When a page's queue
is full, a `levels` or `chatter` frame is skipped, because the next one
replaces it anyway; anything else that does not fit means the page has
fallen hopelessly behind, and it is disconnected with code 1013. It
reconnects and gets a fresh snapshot, which is cheaper and more honest than
a page quietly out of step with the server.

### Threads

Sessions keep their own threads; the mixer keeps PortAudio's. The server
adds one asyncio event loop, uvicorn's, and **everything else runs on it**:
the hub, the station, every `Cockpit` call. Session threads reach it only
through `Station`'s `post`, which is `loop.call_soon_threadsafe`; that is the
direct replacement for `call_from_thread`, with the same rule: a call that
arrives after shutdown is dropped silently, not raised into a session
thread. The two slow fetches, an airport's feed list and the picker's list,
run in the loop's default executor and come back to the loop before they
touch anything. So the `Cockpit`'s single-threaded contract from phase A
holds without a lock anywhere.

uvicorn runs with `ws="websockets-sansio"`: 0.54 deprecates its plain
`websockets` implementation.

### Front end

No build step and no Node. The page is plain HTML, CSS and ES modules served
from `src/kcgx/web/`. Nothing is vendored but two fonts, Share Tech Mono for display text and B612 Mono for small
dense text, both SIL OFL, as Latin woff2 files taken from Fontsource 5.3.0
with their licences beside them in `web/static/fonts/` (phase C). This keeps the install's promise that `uv` is the only
toolchain, and it keeps the front end readable in the same repo by the same
person who reads the Python.

If the UI outgrows that, Preact with `htm` can be vendored the same way
without introducing a build. Choosing a framework now is not needed to start.

Since 2026-11-13 (phase G decision 17) five fonts are vendored: the two
above, and IBM Plex Mono, JetBrains Mono and VT323, each Latin 400 WOFF2
from the Fontsource 5 packages with its OFL text beside it (`cba4122`).
All five are monospaced and OFL, and none is fetched at run time. Still
no build step and no npm.

**One frame clock** (2026-11-13, P0.4a, Task 4). `frames.js` is the page's
only `requestAnimationFrame` loop; the radar, the feed traces and the boot
animation hang off it through `onFrame(fn)`. It runs its callbacks when at
least `1000 / fps_max` ms, less 1 ms of slack, have passed since the last
run, on the display's own frame times; 120 means every frame. "The last
run" is when it was due rather than when it came, by up to one interval,
so the cap holds on average where frames come late or unevenly (headless
WebKit's come 1 to 35 ms apart; counted from arrival, a cap of 15 gave 12
a second). An error from one callback goes to the console once and the
others still run.

### Visual language

The reference is the NORAD wall in *WarGames*: four stills in
`war_games_examples/`. What makes it read as that, and so what the page
must do:

**Everything is a line.** Coastlines, borders, rivers, airspace, waypoints,
aircraft and most of the text are strokes on pure black. No fills, no
gradients, no imagery, no rounded cards. Where a panel needs a boundary it
gets a thin frame, never a background.

One exception, asked for on 2026-11-12 and off unless chosen (decision 9):
**label boxes.** A label on the radar may be given a black box behind it,
so it reads over the lines it sits on. The items are AIRCRAFT (flight
tags), HOME (the airport's name), AIRPORTS, NAVAIDS, CITIES, PEAKS, STATES,
RINGS (the ring numbers) and HUD (the readouts in the radar's corners).
One fill opacity (default 70 %), one padding (4 px), one border opacity
(50 %) and one border width (1 px, up to 5) serve every boxed item; the
fill is black and the border takes the label's own colour. Turning a box
on, or changing its size, never moves the label's text. How boxes are
painted and placed is under [Rendering](#rendering).

Two more fills since 2026-11-13, both asked for. **Runways close in**
(decision 14): once a runway's true width on the screen is wider than its
line, it is drawn as a solid quadrilateral that wide, white as before.
**The focused aircraft's data box** (decision 11) is black behind its
text, like a label box.

**Lines glow.** Each stroke is drawn twice with additive blending: a wide,
faint, blurred pass and a thin bright core. That is the phosphor look, and
it is cheap. On top of the glow sits a display effects layer, CRT by
default; see [Display effects](#display-effects).

**Glow is three numbers** (2026-11-13, decision 15): `glow_map` for the
map, `glow_traffic` for the aircraft, their tails and tags and the feed
traces, and `glow_text` for the page's text, frames and lamps, each 0 to
100, which is 0 to 12 px of blur. The phase F choice became them: a
stored `glow` of OFF, LOW or FULL is read as 0, 33 or 75 in all three,
unless the file has the new one already. 33 is 3.96 px on the canvases,
not quite LOW's 4; on the text it is exactly LOW's shadow and 75
exactly FULL's, with the halo growing between and beyond.

**Colour is meaning, not decoration.** One palette, used the same way on
every screen:

| Colour | Means | Used for |
|---|---|---|
| Cyan | ours, nominal | home country coastline and borders, aircraft, labels, feed traces |
| Blue, dashed | structure | airways and the lines joining navaids |
| Green | elsewhere | foreign coastlines and borders |
| Red orange, dashed | restricted or alarm | class B and C airspace, emergency squawks, errors |
| Pink | focus | the ring round the airport, its name, the selected aircraft |
| White | structure on the ground | screen titles, the home airport's runways |
| Amber | places | cities and other airports as small open circles |

**Shapes from the film, given jobs here.** Waypoints and navaids are
diamonds; other airports are triangles; aircraft are chevrons pointing along
track, trailing a line of their last positions (the film's missile
tracks); the home airport sits in a pink ring with its name set large
beside it, exactly as the stills label each base. Labels are callsign and
altitude, `ASA412 6172`. An aircraft with no callsign is labelled `UNK1`,
`UNK2` in order of first sighting, and an emergency squawk (`7500`, `7600`,
`7700`) turns that aircraft red orange.

**The flight tag is chosen** (decided 2026-11-12, decision 8). The owner
asked to choose which flight information shows. The fields are CALLSIGN
(the label above), TYPE, SQWK, ALT (feet, or `GND`), GS (`230KT`), TRK
(`030°`) and DIST (`12.4NM`), set in CONFIG as the pref `tag_fields`. The
default, CALLSIGN and ALT, is the one line drawn until then. With two or
fewer fields chosen the tag is one line; with more it is two, identity
(callsign, type, squawk) over numbers (altitude, speed, track, distance),
the numbers where the one line has always been. What an aircraft does not
report is left out. No fields chosen means no tag: the chevron alone, and
it still takes the click.

**Tags go over everything** (2026-11-13, decision 8). The owner asked for
labels and their boxes over every map element. A tag had been light added
to the moving layer, so a trail crossing it brightened its letters and it
left a persistence ghost. Tags are now drawn last, on a layer of their
own cleared every frame and laid over the map and the aircraft
`source-over`: each tag's box, then its letters, so a tag and its box sit
over map lines, other aircraft and other tails, and leave no ghost. They
go down in the sort's order, the last ranked first, so the table's first
row's tag is on top, and the focused aircraft's above all. Their size is
`tag_px` (16 px) at the range's view, and it follows the zoom as labels
do.

Decided 2026-10-19 from the mockup review:

* **A trail is part of its aircraft:** the same colour and stroke width as
  the arrow (cyan, red orange for an emergency, pink when focused), and it
  fades smoothly from full strength at the arrow to nothing at its oldest
  point, so the line reads as time passing rather than as a second object.
* **Place names sit back.** Town, city, peak, navaid and airport labels,
  the state names, and the home airport's large name are drawn at about 40%
  opacity, and come up to full while the pointer is over them. Aircraft
  labels are never dimmed this way: they are the point of the screen.
* **Click an aircraft to focus it.** Clicking its arrow, trail or label
  turns it pink with a ring and dims every other aircraft to about 15%;
  clicking it again restores them all. At most one aircraft is focused. The
  callsign in the TRACKS table is a button that does the same thing, and
  the table follows: the focused row is pink and outlined, the rest dim.
  Focus belongs to the page, not the server; each tab has its own.
  *Since 2026-11-12 (decision 7):* the focused aircraft is pinned to the
  top of the table, 20 % larger in every cell, however it was focused: by
  a click on the radar or on its callsign. There is one focus, so there is
  one place to look for it. Sorting orders the other rows beneath it, and
  letting it go returns it to its sorted place. The table scrolls to its
  top on focus; in the one column page, where the page scrolls and not the
  table, a callsign pressed far down brings the first row into view, and a
  click on the radar leaves the page where it is.

Changed 2026-11-13 (phase G), from the second list:

* **A tail is time, and its strength is speed** (decision 7). A trail is
  now where the aircraft was in the last `tail_secs` (180 s; 0 to 600),
  not its last twelve positions, so its length holds when the poll
  interval changes. The page keeps each aircraft's `[lat, lon, t]` for
  600 s whatever is set, `t` being when the position was reported, so
  lengthening the tail shows history at once; the tail's old end is cut
  where the aircraft was `tail_secs` ago. Its strength is one of three
  bands: `tail_alpha_min` (35 %) under `tail_gs_low` (40 kt),
  `tail_alpha_max` (95 %) over `tail_gs_high` (250 kt), and `tail_alpha`
  (95 %) between or with no speed. The fade along it stays.
* **Aircraft may step** (decision 21). `motion` GLIDE dead reckons between
  polls as before; STEP draws each aircraft where it was last reported
  until the next poll, and cuts its tail by that report's time, so a
  stepped tail holds still too.
* **Parked traffic fades or hides** (decision 9). Once an aircraft's
  `still` (see Radar) passes `ground_min` minutes (2), `ground_mode` FADE
  draws it, chevron, tail and tag, at `ground_alpha` (25 %); HIDE leaves
  it out of the picture, the hits and the HUD's count; SHOW changes
  nothing. The focused aircraft is never faded or hidden. The table is
  not touched: its filters are for that.
* **The sort shades the radar** (decision 5). The table's rank sets each
  aircraft's strength, linearly from full for the first row to
  `sort_floor` (40 %) for the last, and its place in the stack: within a
  colour, the last ranked is drawn first. The glow is still drawn a
  colour at a time, so between colours the order is cyan under alarm
  under pink, as before; tags, on their own layer, follow the rank
  exactly. The focused aircraft is always first. One alpha is reckoned
  per aircraft per frame: stale × focus dim × rank × parked, and for its
  tail also the speed band.
* **Focusing goes to the aircraft and follows it** (decision 10). From
  the radar or the table, focusing eases the view to `follow_nm` (10 nm)
  from the aircraft to the nearer edge, centred on it, and keeps it
  centred on where each frame drew it. The wheel zooms about it and keeps
  following; a drag ends the following and keeps the focus; a double
  click recentres on the airport, ends the following and forgets the
  view from before. Unfocusing eases back to the view from before the
  focus, unless a drag or a click on a place has moved it since: the
  view is the user's then, and stays.
* **The focused aircraft has a data box** (decision 11): a `<dl>` over
  the radar with a `NAME: VALUE` line for each column the table shows,
  in the table's order, read through the table's own columns. It is a
  page element, not a drawing, so it is sharp at any render scale and in
  the page's font. It sits left of the chevron, its right edge 12 px
  clear of the chevron's reach and its middle level with it; where that
  would leave the radar, right of it and 12 px under it, clear of the
  tag, which runs up and right. It is placed after every frame from
  where that frame drew the aircraft, and hidden with `info_box` off,
  with nothing focused, and while the aircraft is off the screen. It is
  always boxed, with the label box settings but never under 80 % black, a
  1 px border at 50 % and 4 px of padding. The plan boxed it only when
  AIRCRAFT was boxed; Task 12's review made it always boxed.
* **A click on a place centres it** (decision 12). A click that is on no
  aircraft tries the labels placed, then the nearest symbol within 10 px
  (the home ring's reach being the ring), and eases the view to centre
  it at the same zoom. Places are the home ring, airports, navaids,
  cities, peaks and state names; lines are not targets.
* **What a click is on is what is on top.** Since the tags went over
  everything, a tag whose box is filled (AIRCRAFT boxed, `box_fill` over
  0) wins over the chevrons it covers, and otherwise chevrons come first
  as before; tags are tried top first, then trails. Phase F's "a click
  tries every chevron before any tag" holds only for unboxed tags.

**Text.** Two faces, both OFL, both vendored:

* **Share Tech Mono** for anything large or on a screen: the airport name,
  panel titles, clocks, chatter figures, and every label on the radar,
  drawn on the canvas with the same glow as the lines. Earlier drafts
  called for Hershey Simplex stroked glyphs here; the approved mockup used
  Share Tech Mono throughout and read right, so phase D kept it and
  vendors no glyph data.
* **B612 Mono** for small, dense text (the traffic table, the config sheet,
  the log). Tabular figures throughout, so nothing jitters as it updates.

All caps everywhere, as on the wall.

**The face, its size and the page's zoom are settings** (2026-11-13,
decision 17). `font` CLASSIC is the pair above; B612, SHARETECH, PLEX,
JETBRAINS and VT323 each set one face for everything; SYSTEM is
`ui-monospace, Menlo`. All are monospaced, so the tables keep their
columns. They are two custom properties, `--font-text` and
`--font-display`; the radar reads the second for its labels and draws
again when a font loads. `font_px` (13 px) is the body's size, and the
buttons, the airport's name and the tracks table follow it; titles, the
big figures and the radar's readouts stay fixed. `ui_zoom` (50 to 200 %)
is CSS `zoom` on `.page` and on each dialog. Neither changes the radar's
labels, which have sizes of their own (Rendering). The clocks are three
flags: `clock_24h` (12-hour local reads `3:07 PM`), `clock_seconds`
(`:SS` on both, set smaller, as is AM/PM, so the longest, `11:07:42 AM
PST`, stays on the ICAO's row at every size) and `clock_zone`.

**The wall, not a dashboard.** Each region of the page is a framed screen
with a title set in caps along its bottom edge (`TRAFFIC`, `FREQUENCIES`,
like `MISSILE WARNING` in the still). Between the screens runs a **lamp
bar**: one small lamp per feed, lit in that feed's state colour (cyan live,
amber reconnecting, red offline, dark parked), then a gap and lamps for the
radar poll (`RADAR`), the connection to the server (`SERVER`) and the
audio device (`AUDIO`), then an **emergency lamp** (`EMERG`), dark until an aircraft in range squawks `7500`, `7600`
or `7700`, then lit red orange and labelled with the code. It is the whole field's health at a glance, the way
`●◐○` was on each row, and it stays visible when the stack is scrolled.

Changed 2026-11-12 (phase F), from the owner's list:

* **The lamp bar is hidden unless asked for** (the pref `lamps`, STATUS
  LAMPS in CONFIG; default off). When shown it sits under the radar, at
  the radar's width (decision 5): it can no longer span the page, because
  the frequencies screen now runs the full height of the right column.
* **The teletype is hidden unless asked for** (the pref `teletype`;
  default off), and the frequencies screen takes its room. When shown it
  sits under the frequencies, level with the tracks.
* **The status screen has no title.** STATUS is gone; the screen is the
  ICAO and the clocks, and beneath them the airport's name and place on
  the left and a search icon on the right, bottom right of the screen,
  which opens the airport search. To a screen reader it is "Airport".
* **Everything is tighter.** The padding round the page, between screens
  and inside them came down by about a third (16/20/20 px round the page
  to 10/12/12; 14 px between screens to 10), set by four custom
  properties (`--gap`, `--page-pad`, `--pad-x`, `--pad-y`) so the density
  is changed in one place. Buttons went from 40 px high to 30. Font sizes
  did not change, but for the chatter figure below.
* **The header is two icons** and no words: see
  [Every action is a click](#every-action-is-a-click).

**The feed stack in this language.** An expanded row's meter becomes a
scrolling vector trace, an oscilloscope line of the last few seconds' level,
rather than a bar strip. Its controls are two small framed buttons labelled
**M** and **S**, bare letters with no brackets, in that order (decided
2026-10-19). M replaces the terminal's `[ON]`/`[OFF]` toggle and lights
when the feed is muted, as a mute button does on a mixing desk; S lights
when the feed is soloed. Each carries an `aria-label`
naming its feed ("Mute Tower (Both)"), because a bare letter says nothing
to a screen reader. There is no ambient control (see Feature parity). The
chatter figure is a two digit stroked number, the way the
wall numbers its sectors (`27`). Compact rows are a name, a figure and a
state glyph on one line.

Changed 2026-11-12 (phase F): the chatter figure is smaller and says what
it is, a percentage, in both shapes of row: `27%` at 18 px in an expanded
row (it was 30) and 14 px in a compact one (it was 18), with no leading
zero, four characters wide and right aligned so it does not shift as it
changes. M and S are 28 px wide and 24 high (they were 44 and 34), and a
compact row is 32 px high (it was 44).

Changed 2026-11-13 (phase G decision 3), from the second list: **one feed
at a time, and no M or S.** The expanded row is the feed that is not
muted, and there is one. Its head reads title, chatter (`34%`) and state
glyph, left to right, the chatter's right edge as near the glyph as in a
compact row, with no CHATTER label; its trace is 60 px tall, twice what it
was, drawn at the render scale with the traffic's glow. Every compact row
is a button that sends `select`; the expanded one is no button, since
picking what plays does nothing. A compact row whose feed is audible
anyway (only `/debug` or `open_feed` can make two) is marked playing. The
titles are tighter (`letter-spacing: 0.04em`). The line of feed counts at
the top became the master mute (a speaker, crossed when muted;
`aria-pressed`) and the volume slider with its figure, moved there from
CONFIG.

**Feed titles leave out the airport** (2026-11-13, decision 19).
`kcgx.names.short_feed_name` drops, as whole words anywhere in the title,
the airport's name where it heads it (its words up to the first of
International, Regional, Airport, Field or Municipal: `Chicago O'Hare`,
`Seattle–Tacoma`), its city (the part of `where` before the comma), both
in any case, and its ICAO and IATA codes, in capitals only, since many
codes are words (`LAS` in Las Vegas, `SAN` in San Diego, `AND`). The ICAO
goes first and the IATA after the city. Hyphens and dashes are one dash,
and a dash with no space joins words, so `SEA-TAC Ground` stays whole.
Dangling dashes and slashes, doubled separators and empty brackets are
tidied. If nothing would be left, the title stays as it was; `ZSE Seattle
Center` at KPDX names another city and stays. The server sends it as each
feed's `title`, and `short_names` turns it off.

**The log is a teletype.** New messages type out a character at a time, in
caps, with a block cursor, each prefixed with its Zulu time (`1955Z`).
Fast enough never to delay a warning (the whole line inside 400 ms), and
instant under reduced motion.

**Hiding the teletype must not hide errors** (decided 2026-11-12,
decision 4). It is off by default since that date, and it goes on
collecting while hidden, so turning it on shows the history, opened on its
newest line. While it is hidden, a line that comes from the page itself
(an airport search that failed, a message the server refused, a shut down
that did not go through) also shows in the banner under the header for
8 s. The server's notes do not: they are history, not errors, and wait in
the teletype. That includes the two the log exists for, a feed list that
could not be fetched and an emergency squawk, which with the teletype and
the lamps both off are seen only as a short stack and a red orange
aircraft.

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
black for every palette colour at the sizes it is used. (Since
2026-11-13 the glow is three numbers, above; reduced motion also skips
the boot animation, and view moves jump rather than ease.)

### Themes

The six adsb-tui names (`default`, `color`, `amber`, `ocean`, `matrix`,
`mono`) existed to match a radar that is going away. In their place the
vector style has **four palettes**, which the header's PALETTE button cycles
through: **WOPR** (the table above, the default), **AMBER** and **MATRIX**,
single phosphor monochromes that suit the look well, and **MONO**, white on
black. `default`, `color` and `ocean` were dropped in phase C: next to WOPR
they were the same idea in a weaker colour. Palettes are CSS custom
properties set by `data-palette` on `<html>`, read by both the DOM and the
canvases.

The Textual specific half of `themes.py` and all of `radar_theme.py` go with
the terminal UI. The chosen palette, glow and display are **prefs** the
server remembers in `prefs.json` beside the airport file (so
`KCGX_STATE_PATH` moves both), in `kcgx.prefs`. A page changes one with a
`prefs` message; the server checks it against the known names, saves it,
and sends a `prefs` frame so every tab changes together. An unreadable
file or an unknown name falls back to the default.

**"Theme" is the palette, and a dropdown** (decided 2026-11-12, decision
11). The owner asked for the theme as a dropdown and for PALETTE to leave
the header. The row in CONFIG is labelled THEME and is a `<select>` of the
four; glow and display stay as segments. Nothing cycles any more.

**One schema for every setting** (2026-11-12, phase F). The three prefs
became fourteen, all described once in `kcgx.prefs.SCHEMA` as one of four
kinds: a choice, a flag, a whole number in a range, or a subset of named
items. The file is read leniently through it (a bad value falls back to
that setting's own default and disturbs no other), the protocol strictly
(a bad value refuses the message). The page's controls are declared in
`index.html` as `[data-pref]` elements and bound by kind, so `sheets.js`
knows no setting by name; a test holds the markup to the schema.

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

**The config sheet docks to the right edge with a clear backdrop**
(decision 10), so scanlines, boxes and the range are seen changing while
they are set. Its sections are OUTPUT (master volume), LOOK, LAYOUT and
RADAR; LIMITS, which showed the stream limit and changed nothing, is gone.
**The page changes nothing itself:** every control sends a `prefs`
message and the page redraws from the server's `prefs` frame. A slider
shows its value at once, sends it 80 ms after it last moved, and is not
moved by a `prefs` frame while it is in hand. The sheet is still a modal
dialog: the page behind is not darkened, but it takes no clicks until the
sheet is closed. *Superseded on 2026-11-13; see below.*

**A fifth kind, the table** (2026-11-13, phase G). The second list asked
for show, opacity, line type and label size on every map marking. That is
a grid, not a row, so `kcgx.prefs` gained `Table`: named rows of cells,
each row having only the columns that mean something for it, each cell
checked by its column's own kind. A page may send part of a table, any
rows and any of a row's own columns, and `merge` lays it over what is
set a cell at a time, so two tabs changing two cells both land; the file
and every frame hold it whole. Read from the file, a bad cell is dropped
and the rest kept; on the wire it refuses the message, naming
`ROW.column`. The one table is `map`:

| row | show | alpha | line | width (tenths of a px) | label (px) |
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
| AIRPORTS, NAVAIDS, CITIES, PEAKS | on | 85 | | 13 | 13 |
| STATE_NAMES | on | 100 | | | 14 |

The columns' ranges: alpha 0 to 100 %, line SOLID, DASH or DOT, width 5
to 80, label 8 to 32. `Number` also gained a step, counted from its low
end, so a value off its slider's step (a hand-edited range of 45) is
refused on the wire and dropped from the file.

**The schema since 2026-11-13.** Fifty-four settings: thirty-two numbers,
ten flags, eight choices, three subsets and the table. `glow` left it
(above, under Visual language). The phase F table above holds for every
key it lists but `glow`; the new keys, by the CONFIG tab that holds them:

| key | kind | values | default | CONFIG row |
|---|---|---|---|---|
| `boot_anim` | flag | | true | BOOT ANIMATION |
| `ui_zoom` | number | 50 to 200 (%), step 5 | 100 | UI ZOOM |
| `font` | choice | CLASSIC, B612, SHARETECH, PLEX, JETBRAINS, VT323, SYSTEM | CLASSIC | FONT |
| `font_px` | number | 10 to 20 (px) | 13 | FONT SIZE |
| `clock_24h`, `clock_seconds`, `clock_zone` | flag | | true, false, true | 24-HOUR LOCAL, SECONDS, ZONE NAME |
| `glow_map`, `glow_traffic`, `glow_text` | number | 0 to 100 | 33 | GLOW: MAP, TRAFFIC, TEXT |
| `aa` | choice | OFF, ON, SUPER | ON | ANTI-ALIASING |
| `burn_in` | number | 0 to 100 (ms, a half-life) | 19 | BURN-IN |
| `fps_max` | number | 15 to 120 | 60 | MAX FRAME RATE |
| `poll_secs` | number | 15 to 120 (s), step 5 | 15 | RADAR POLL |
| `motion` | choice | GLIDE, STEP | GLIDE | AIRCRAFT MOTION |
| `view_ease` | choice | OFF, QUICK, SMOOTH | QUICK | VIEW MOVES |
| `zoom_speed` | number | 25 to 400 (%) | 100 | ZOOM SPEED |
| `map` | table | above | the map as drawn before | MAP LAYERS |
| `label_min`, `label_max` | number | 6 to 20, 12 to 48 (px) | 9, 26 | LABEL MIN, LABEL MAX |
| `tag_px` | number | 10 to 28 (px) | 16 | TAG SIZE |
| `follow_nm` | number | 1 to 50 | 10 | FOLLOW RADIUS |
| `info_box` | flag | | true | DATA BOX |
| `tail_secs` | number | 0 to 600 (s), step 15 | 180 | TAIL LENGTH |
| `tail_alpha`, `tail_alpha_min`, `tail_alpha_max` | number | 0 to 100 (%) | 95, 35, 95 | TAIL DEFAULT, SLOW, FAST |
| `tail_gs_low`, `tail_gs_high` | number | 0 to 600 (kt) | 40, 250 | SLOW BELOW, FAST ABOVE |
| `ground_mode` | choice | SHOW, FADE, HIDE | FADE | PARKED TRAFFIC |
| `ground_gs` | number | 0 to 50 (kt) | 5 | BELOW SPEED |
| `ground_alt` | number | 0 to 5000 (ft), step 100 | 0 | BELOW ALTITUDE |
| `ground_min` | number | 0 to 30 (min) | 2 | AFTER |
| `ground_alpha` | number | 0 to 100 (%) | 25 | FADE TO |
| `track_cols` | subset | CALLSIGN, TYPE, REG, ALT, VS, GS, TRK, DIST, BRG, SQWK, HEX, CAT, AGE, LAT, LON | CALLSIGN, TYPE, ALT, GS, TRK, DIST, SQWK | COLUMNS |
| `track_sort` | choice | the same names | DIST | SORT BY |
| `track_desc` | flag | | false | DESCENDING |
| `sort_floor` | number | 0 to 100 (%) | 40 | DIMMEST (RADAR) |
| `tracks_open` | flag | | true | (the pane's fold button) |
| `tracks_pct` | number | 10 to 80 (% of the page) | 24 | (the pane's grip) |
| `short_names` | flag | | true | DROP THE AIRPORT FROM NAMES |

`range_nm` gained the step its slider always had, 10. The master mute and
the volume are not prefs: they are audio state, like the volume always
was.

**CONFIG is full-screen, in four tabs** (2026-11-13, decision 2). The
second list asked for it centred and full-screen, and that won over phase
F's reason for docking it. It is the window less a 16 px margin, centred,
over an 85 % black backdrop, so it covers the radar: a change is seen
once the sheet is closed. Its tabs are GENERAL (page, clocks, look,
glow, rendering, radar, layout), TRAFFIC (radar, boxes, the map grid,
labels, focus, tails, parked), TRACKS (table, radar) and FREQUENCIES
(names). They are `role="tab"` buttons; the arrow keys, Home and End move
between them, and the sheet reopens on the last tab used while the page
is open. The panel scrolls; the head and the tabs do not. Every key but
`tracks_open` and `tracks_pct`, which the tracks pane binds itself, has
one `[data-pref]` control in the tab the plan names, and
`tests/test_page_prefs.py` holds that, the table's rows, columns, ranges
and names included. The map's grid is `data-kind="table"`: `data-rows`
lists each row's columns and each column's heading declares its kind and
range, `sheets.js` makes a cell only where a row has that column, bound
with the same binders as single controls, and each sends
`{t: "prefs", map: {ROW: {col: value}}}`. The rest of what was said of
the sheet above holds.

**The airport picker is fixed** (decision 20): `min(840px, 100% - 32px)`
wide, 50 % over its 560, and `min(80vh, 720px)` tall whatever it finds,
centred, its results scrolling inside it.

### Rendering

One full window canvas per screen, Canvas 2D with `globalCompositeOperation
= "lighter"` for the additive glow. Static geography is drawn once per
airport or zoom change into an offscreen canvas and copied each frame;
only aircraft, trails, the selection ring and the feed traces redraw at
display rate. At 40 nm that is a few thousand static segments and a few
hundred dynamic ones, well inside Canvas 2D. WebGL is the escape hatch if
it is ever not, and nothing in the data model would need to change.

**The glow on the aircraft is one shadow for each colour** (2026-11-12,
found by running the page in WebKit for the window). The glow had been a
canvas shadow on every trail segment and every chevron, and a shadow costs
by the draw: in WebKit, and in Chromium drawing on a GPU, that was 25 ms a
frame for eleven aircraft and over 60 ms for thirty. The aircraft's lines are
now drawn bare on a canvas of their own, a colour at a time, and that
canvas is drawn onto the moving layer once with the shadow. Measured
after, in headless browsers and never on a real display: 600 aircraft
with full trails at 250 nm take 10.7 ms a frame in WebKit and 8.3 ms in
Chromium on a GPU, where those two tick every 10.0 and 8.3 ms when
nothing is late. A browser that draws
in software pays for the one large shadow by the pixel: Chromium's
headless shell took 19.2 ms for the same picture at 1x and 45.5 ms at 2x.
Two things are not done: aircraft and trail points that are off the
screen are still drawn, and the static layer still redraws with a shadow
on every map line and symbol while the map is panned, zoomed or drawing
on. *Both were done on 2026-11-13 (phase G Task 5); see below.*

**The radar is four modules on one frame clock** (2026-11-13, phase G
P0.3 and P0.4a). `radar.js` became `radar/`: `index.js` (mounting, the
canvases and their size, the frame and the order its layers are put
together in, the HUD, what the store says), `still.js` (the map, rings,
the home airport, places, label sizes), `moving.js` (aircraft, tails,
tags, culling), `view.js` (the view, the pointer, view moves, following,
hit tests) and two helpers, `draw.js` (the font and label boxes) and
`info.js` (the data box). The split was made so that three people could
work on the radar at once, and was proved a pure move: twelve frozen
screenshots in both engines, 0 pixels different. Each module's
`init(radar)` adds its own part of one shared object and binds its own
listeners, and may return `tick`, `post` and `debug` hooks; `index.js`
runs the inits in a fixed order (view, still, moving), each `tick` before
drawing and each `post` after it, and builds `debug()` from every
module's, a key given twice being an error. Objects on `radar` are
changed in place, never replaced, so a module may hold one. The frame is
one `onFrame` callback of `frames.js` (Front end), so `fps_max` caps it.

**A frame is three canvases put together:** the static layer (`still`)
copied, the moving layer (`trace`) added to it (`lighter`), and since
2026-11-13 the tags' layer (`tags`) laid over both as it is
(`source-over`; see "Tags go over everything" under Visual language).
Scratch canvases (`bare`, `stillBare`) hold lines drawn without a glow,
for the glow to be put on once.

**The map's glow is one shadow for each colour too** (2026-11-13, Task
5a), as the aircraft's has been since phase F: every line, ring and
symbol of a colour is drawn bare on `stillBare`, and that is drawn onto
`still` once, with the shadow, only over what it inked and the glow's
reach (WebKit puts an image's shadow only inside the rectangle it is
drawn to). A label's box hides what is under it, so the glow waiting is
drawn before each box; a box with no fill and no border hides nothing,
and only keeps its room, since flushing for it split a colour's blur in
two and changed some 900 nearly clear pixels. Labels have no glow. The
picture is not quite what a shadow on each line drew: over black, at
most 0.02 % of pixels differ by more than 16 of 255, and none is visible
side by side.

**While the view moves, the map is moved, not drawn** (Task 5a). A drag,
the wheel, an eased move and following each say when the view last moved
(`radar.movedAt`). While it moves, `still` is the last full drawing
(`radar.stillWas`) moved and scaled to the view, by whole pixels when not
scaled, and what it placed (labels, marks, rings, the home ring) is moved
the same way, so hover and clicks land on what is on the screen. It is
drawn anew 120 ms after the view stops; at once when a drag is let go,
when a move gets there, when the view jumps, and when anything else it
is drawn from changes; and while the view moves on, once the moved
drawing would be scaled outside 0.8 to 1.5 times, or leave more than 5 %
of the screen's shorter side bare. (At 0.8 the screen's outer third keeps
about 0.6 of its light; at the 0.67 a review asked for, 0.38.) Measured
on 2026-11-13, headless, 1440 by 900, mean ms between radar frames,
before and after: the static layer redrawn at 250 nm, Chromium 1x 383 to
70 and WebKit 1x 42 to 20; a drag at 40 nm, 83 to 17 and 19 to 10;
following at 10 nm, Chromium 2x 367 to 53 and WebKit 2x 97 to 11. A fast
drag (15 px a frame) is drawn anew about every second frame: WebKit holds
16.7 ms, software Chromium at 2x falls to 113. WebKit is what the window
uses, so that was accepted.

**What is off the screen is not drawn, and what has not changed is not
reckoned again** (2026-11-13, Task 5b). A chevron, a tail segment or a
tag wholly off the screen is left out; a tag is given its own width of
margin (one em a letter until it is measured), and its box and glow.
Aircraft off the screen stay in the hits, without a tag. Each tail's
points are kept in nm until the projection or the trail changes, so a
view moving every frame projects nothing again. Chevrons of a colour are
one path for each strength. Tails are still stroked a segment at a time:
batching runs of equal strength saved WebKit a fifth at 600 s tails and
changed 0.7 % of the picture, so it was dropped. Measured, median ms a
frame, 600 aircraft with 600 s tails, CRT, headless: at 250 nm, where
nothing is culled, Chromium 1x 49 to 55 and WebKit 1x 24 to 23 (Chromium's
shell pays by the pixel for the glow and the tails, which this did not
touch); at 40 nm, where most is off the screen, Chromium 1x 31 to 22 and
WebKit 1x 20 to 6.

**The render scale** (2026-11-13, decision 6). The owner asked for
anti-aliasing as a setting, but Canvas 2D has no switch for it on lines,
so `aa` is the resolution the canvases are drawn at: OFF half the
display's, scaled up stepped (`image-rendering: pixelated`), ON the
display's own, SUPER twice, scaled down by the browser. `theme.js`
`renderScale()` gives 0.5, 1 or 2; every radar canvas, the feed traces
and the boot's canvas are `devicePixelRatio × renderScale()` pixels to a
CSS pixel. `size()` returns that ratio, and pointer and hit maths take it
from there and never from `devicePixelRatio`, so the scale reaches them.
**No radar canvas is over 8 megapixels:** SUPER on a 2x display gives 4
pixels to a point, and at 1440 by 900 five canvases of some 9.6 million
each. Where the ratio would make one so, it is cut, the same both ways,
to the ratio that comes to 8 million, and `size()` returns the ratio cut
(3.645 at that size), so everything drawn by it follows.

**The page's zoom and the canvas** (2026-11-13). Under CSS `zoom` on
`.page` (`ui_zoom`), the engines disagree: Chromium's
`getBoundingClientRect` gives the canvas's box as zoomed, WebKit's as
not, while `clientX` is the window's in both. `view.js` exports
`cssZoomFix(canvas, box)`, the zoom over the canvas (the product of every
ancestor's computed `zoom`) over how much of it the box already has: 1 in
Chromium, the zoom in WebKit. The pointer is `(clientX / k − box.left) ×
canvas.width / box.width`, and `size()` sizes the backing store from the
box times `k`, so the radar is as sharp and a click lands at any zoom in
both. The data box is placed in the canvas's own CSS pixels
(`offsetWidth`), which need no fix. The tracks pane does the like for its
grip and its COLUMNS popover. KCGX.app's own WKWebView zoom is separate
and not used.

**The radar fills its screen** (decided 2026-10-19). The top row of the
wall (radar, status, frequencies) has a set height: the window's, less the
header, the lamp bar and the tracks row below. The radar canvas is sized to
its screen, not to a fixed aspect ratio, and the projection scales so the
outer range ring fits the shorter side; the longer side shows more
geography rather than black bars. The frequency stack never stretches the
row: past what fits, it scrolls inside its own screen, with the selected
feed kept in view. Below 1100 px wide the wall stacks into one column and
each screen takes its natural height, the radar a fixed 440 px.

The top row is a CSS grid (radar, then a 340 to 400 px frequencies column),
not a wrapping flex row, so **no two screens can ever overlap** at any
window size; each screen clips its own content (`overflow: hidden` and
`contain: paint`), so nothing the radar draws, glow included, can paint
over a neighbour. Decided 2026-10-19 after the panels overlapped in the
mockup.

**One grid for the whole page** (2026-11-12, phase F). The top row, the
column and the bottom row became one CSS grid of eight named parts: the
bar, the banner, the radar, the airport, the frequencies, the lamps, the
tracks and the teletype. The right column is 320 to 380 px. The radar
takes the left of the first two rows; the frequencies run from under the
airport to the bottom of the page, or to the top of the teletype when it
is shown; the lamps, when shown, are a row of their own under the radar.
Which of the four layouts is drawn is two attributes on `<html>`,
`data-lamps` and `data-teletype`, both OFF at first paint so the page
opens in the default layout. The page fits any window from 640 px high,
in all four; below 1100 px wide it is one column in the order radar,
airport, frequencies, lamps, tracks, teletype. No two screens overlap in
any of them, which the browser tests hold at five sizes by four layouts.
Since 2026-11-13 (decision 18) the tracks row is `--tracks-row`, which
`tracks.js` sets from `tracks_pct` and `tracks_open` (see the table under
Radar), so the radar is what the tracks pane leaves, and is never under
48 px.

The radar pans by dragging and zooms with the wheel about the pointer,
from a quarter (160 nm across the shorter side) to six times; a RECENTRE
button in its title strip snaps back to the airport. While the pointer is
over the radar the title strip reads its bearing and distance from the
field (`275° 12.4 NM`). Range rings label themselves in nautical miles.

**The view is held in nautical miles** (decided 2026-11-12, decision 6),
in place of the zoom factor and the RECENTRE button of the paragraph
above. The view is "N nm from the centre to the
nearer edge" (less an 18 px margin). It starts at the range, and returns
to it, centred, on a new range, a new airport or a double click. The
wheel runs from **2.5 nm**, the closer zoom the owner asked for, out to
160 nm, or to the range if that is wider.

* **Range rings are computed**, not the fixed 10, 20, 30 and 40. The step
  is the first of 0.5, 1, 2, 5, 10, 20 and 50 nm that puts no more than
  five rings between the centre and the nearer edge. Every multiple of it
  short of the range that crosses the screen is drawn dim, then the range
  itself, bright, whether or not it is a multiple. So two to five show
  between the centre and the nearer edge (the plan said three to five),
  and more towards the corners of a wide screen. A ring's number is
  placed, not just drawn: the range's first, and a number that would run
  into it or into the home ring is left off, its ring kept; with the
  airport panned off the screen the numbers move to where each ring
  passes nearest the middle.
* **The home ring** is 2.5 nm in radius, held between 24 and 64 px on
  screen, so that it neither vanishes at 250 nm nor fills the screen at
  2.5. At the closest views the runways, drawn at their true size, run
  outside it.
* **A double click on the radar recentres it** (decision 3). The RECENTRE
  button went with the owner's list, and without something in its place
  there is no way back from a pan short of changing airport. A double
  click whose two presses moved (two quick pans from one spot) is not
  one.
* **A new range resets the view on every open page**, since the range is
  the server's and the view is drawn from it.

Changed 2026-11-13 (phase G):

* **The wheel closes in to 0.25 nm** (decision 14), from 2.5, near enough
  for a runway to fill the screen. The ring steps gained 0.05, 0.1 and
  0.2 nm, so at 0.25 nm five rings still lie between the airport and the
  nearer edge. The home ring keeps its 24 to 64 px.
* **The view moves** (decision 21). `goTo` eases the view in and out
  (cubic, the distance on a log scale) over `view_ease`'s time: OFF 0,
  QUICK 250 ms, SMOOTH 600 ms. (Decision 10 said 400 ms; decision 21's
  three settings replaced it.) A wheel or a drag ends a move, and reduced
  motion makes every move a jump. `zoom_speed` scales the wheel's rate,
  25 to 400 % of phase F's. The view's moves are centring a place,
  focusing an aircraft and coming back, and following.
* **A ring number gives way to the airport's name, boxed or not**
  (decided by the owner at Task 10's review), reversing phase F's "bare
  labels may cross" for ring numbers and the home name only; other
  places are as before. At the default 40 nm view, the 10's number is
  left off.

**Labels never overlap.** Places are labelled in priority order (the home
airport, then peaks, large airports, VORs, medium airports and cities by
Natural Earth's rank, then state names) and a label that would overlap one
already placed is left off, its symbol kept. Navaids on screen are the VOR
family; small airports appear from 1.5 times zoom (since 2026-11-12: from
a 27 nm view inwards, which is the same thing at the 40 nm range).

**Labels follow the zoom** (2026-11-13, decision 13). The owner asked for
a minimum, a maximum and a default size. Each layer's default is its
`label` in the map table (the tags', `tag_px`), and it is the size at the
view the range sets. A view k times closer makes it `k^0.35` times as
big, a view further out smaller the same way, held between `label_min`
(9 px) and `label_max` (26 px): `labelPx(base) = clamp(min(label_min,
base), base × (range / view)^0.35, max(label_max, base))`. The bounds
widen to take in a default outside them, so the range's view always
shows a label at its own size: the home airport's name is 30 px, over
the ceiling. Every still label and every tag goes through it.

**Map layers by setting** (2026-11-13, Task 10). Every map line, the
rings, the runways, the home airport, places and state names are drawn
from their row of `prefs.map`: shown or not (a hidden row counts 0 in
`debug().layers`), a strength that scales each part from its old alpha,
a line pattern, a width and a label size. The default table draws the
map as it was: the five dashed layers keep their old patterns as their
default line's, since DASH as `5w 5w` and DOT as `w 3w` alone would
have changed 11.6 % of Chromium's pixels, the airways most. A line piece
wholly off the screen is left out, and each segment kept is cut to a
margin rectangle (Liang–Barsky), starting its dash a phase back so the
dashes fall where the whole line's would: Chromium stopped dashing an
airway whose segments ran tens of thousands of px off the screen at
0.25 nm, and drew it solid.

**Runways close in** (decision 14). A runway whose true width on the
screen is wider than its row's line is a filled quadrilateral that wide,
and never narrower than the line. The width is OurAirports' `width_ft`,
which `tools/build_geodata.py` keeps as a runway's fifth element since
2026-11-13 and `geodata` passes on, or 150 ft where the map has none.
The map was rebuilt with widths on 2026-11-14 (5,987 of 5,989 runways
have one). A map with widths and one without both draw.

**How a label box is painted and placed** (2026-11-12; the setting is
under Visual language). Both radar layers are light added to light, so
black drawn into them changes nothing. A box is therefore painted
`source-over`, by one function: a still label's on the static layer,
before its text; a flight tag's straight onto the screen, between the
static layer and the moving one, at its aircraft's own alpha, so a dimmed
or stale aircraft's box dims with it; the HUD's in CSS from the same four
settings. The box is the capitals the label inks, then the padding, then
the border outside the padding, on whole pixels; a place's box takes in
its symbol. What a label reserves is its old text rectangle grown to hold
its box, so a label's text never moves. **No box lies across another
still label:** bare labels may cross as they always have, light on light,
but once either of two is boxed they are kept apart and the one placed
later gives way, so a boxed home name can cost the nearest ring its
number. **Flight tags are not placed around one another**, boxed or not;
that is left for later (see the plan's "Not in this plan"). A click tries
every chevron before any tag, so an aircraft under another's tag or box
is still the one focused. The map that ships names no states, so STATES
has nothing to box until one does.

*Changed 2026-11-13 (phase G decision 8, Task 11):* a flight tag's box is
no longer painted between the static layer and the moving one. Tags and
their boxes are on the tags' layer, over both, each box and then its
letters, at its aircraft's own alpha as before. Unboxed tags' letters
glow a colour at a time from the bare canvas, clipped to that colour's
tags; a boxed tag's letters glow one tag at a time, after its own box,
so a box never hides its own glow and is cut only by the boxes above it.
(A glow per tag through the bare canvas cost 105 to 420 ms a frame for
300 tags, and was not used.) A tag whose box is filled now takes the
click over the chevrons it covers; see "What a click is on" under Visual
language.

### Display effects

The film's screens were vector displays, and the effects that make the
mockup feel alive are vector ones: beam flicker, lines drawing on, a little
jitter, glow, phosphor persistence. Scanlines and curvature belong to
raster CRTs, but they read instantly as "old screen" and the mockup was
approved with them on. So there are three settings, and **CRT is the
default**:

| `display` | What it adds |
|---|---|
| `off` | nothing; glow alone, per the `glow` setting (the three glow numbers since 2026-11-13) |
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
  opacity, over every screen. *Since 2026-11-12 (decision 12) both are
  settings,* because the owner asked to set the scanlines' opacity and
  size: `scan_opacity`, 0 to 100 %, default 34, and `scan_size`, the pitch
  from one line to the next, 2 to 8 px, default 3. The dark line is a
  third of the pitch, never under 1 px. They are three custom properties
  the page writes from the prefs. Both apply only with display CRT, and
  their sliders are disabled otherwise. At 100 % and 8 px a black 3 px
  line every 8 px cuts through every row of text and the page is hard to
  read; that is the far end of both sliders, as asked.
* **Corners** (`crt` only). Screens get a 16 px radius.
* **Colour fringe** (`crt` only). The radar gets a one pixel red and cyan
  offset, at 35%.

**Where each effect is done.** Phase D does them without WebGL. Glow is
Canvas 2D's own shadow blur with additive blending, the same on the radar
as on the traces. (Since 2026-11-12 the aircraft take theirs as one
shadow for each colour, not one for each stroke, and since 2026-11-13 the
map does too; see Rendering.) Persistence is a separate layer for the moving things
that fades by 45% a frame instead of being cleared, in `vector` and `crt`
only.

**Burn-in is by time** (2026-11-13, decision 15). A fade of 45 % a frame
is a different afterglow at 60 and 120 Hz, and with a frame rate cap it
would change with the setting. `burn_in` is now the fade's half-life in
ms (0 to 100), and each frame takes `1 − 0.5^(elapsed / burn_in)` of what
is there. The default, 19, is phase F's look at 60 Hz (0.55 left after
16.7 ms is a half-life of 19.3 ms); 0 clears every frame, as do display
OFF and reduced motion. "Elapsed" is the mean of the last 30 frame
intervals, to the half ms, not each frame's own: headless WebKit's frames
came 10 and 20 ms apart in turn, and a fade that changed every frame made
a still picture's edges shimmer. A gap over 100 ms (a hidden tab, a long
frame) clears the layer, since what is on it is of where the traffic was
then, and is left out of the mean; a new `fps_max` starts the mean again.
Measured at the default: 19.2 ms at 60 frames a second and 18.9 at 30 in
Chromium, 17 to 20 in WebKit. The boot animation's canvas fades the same
way. Line draw on traces the coastlines, lakes, rivers and borders over
two seconds when an airport's map arrives. Flicker, jitter, vignette,
scanlines, corners and the colour fringe are CSS, as they already were for
every other screen: an overlay element per screen, with `pointer-events:
none` so it never takes a click. Reduced motion turns off draw on and
persistence. A WebGL pass stays the escape hatch if bloom is ever wanted
beyond what shadow blur gives; nothing in the renderer would need to
change but its last step.

**Our own code, not a library.** [RetroZone](https://github.com/TheMarco/retrozone)
(MIT) is the closest existing match: a WebGL pass over any canvas with a
vector mode (bloom, persistence, beam flicker) and a CRT mode (scanlines,
interlace flicker). It is a good reference for the shaders, credited where
we borrow from it. It is not a dependency, because it ships only through
npm (and this front end has no build step), its flicker and noise are not
adjustable, and at the time of writing it is two commits old. Phase D
found it was not needed.

**Settings, not states.** `display` and `glow` are remembered with the
palette, in the same `prefs.json`, so every tab and every launch agrees.
So, since 2026-11-12, are the two scanline settings and the rest of the
schema under [Themes](#themes).

**Sliders and the dropdown are drawn by the stylesheet** (2026-11-12).
WebKit drew its own: a slider whose track does not show on black and
which ignores `accent-color`, and a rounded dropdown 21 px high whatever
the stylesheet said. Both are `appearance: none` now: a slider is a line
in the dim colour with a block in cyan, the dropdown is square with an
arrow in the text's colour, and they are the same in both engines. The
sliders lost their filled part in Chromium by it, so a value reads by the
thumb's place and the number beside it.

### The boot animation

Decided and built 2026-11-13 (phase G decision 1, Task 14). The owner's
list asked for the cockpit to boot with his Vector Cockpit drawing, in
the last palette, and then fade in and boot normally.

**What it is.** The drawing was a React component inside a design tool's
runtime (`Vector Cockpit Drawing/vector-scene.jsx`, which fetches React
and Babel from unpkg). `boot-scene.js` ports it to a 2D canvas, citing
its lines: the path data, the six scenes (Draw, Takeoff, Turn, Tower,
Lights, Outro) as one pure `frame(ctx, T, colours, options)`, the
engine's clamp, its three easings and its time warp (Lights plays 5
authored seconds over 5.5, Outro 5 over 4), 21.7 s in all. Draw-on is a
dash of each path's length, measured once from a detached
`SVGPathElement`; KCGX on the tower is `strokeText` in `--font-display`
once the fonts are in. Its colours are the page's palette: wall, cyan,
dim, pink, blue, white and amber for the drawing's own, and the runway
edges in `--alarm`, or `--frame` in AMBER and MATRIX, where the alarm
colour is white and broke the one-colour picture. Left out: its four
ghost renders (the canvas fades by `burn_in` instead), its motion blur,
its 24 fps step, its two-blur glow filter and its own phosphor palettes;
its scanlines and vignette are the page's `.ovl` over the cover. The
folder stays out of the repo (decision 22).

**Once a launch, whole, and skippable.** It plays on the first cockpit
page the server welcomes after it starts (`boot` in the snapshot; see
Transport), not on a reload, a second tab or the window reopened. Any key
(not a modifier alone) or press skips it at once. `boot_anim` turns it
off and reduced motion skips it. The page under it connects and fills in
while it plays, so skipping lands on a live cockpit, and the radar is
drawing beneath it before it fades. It plays on `frames.js` at `fps_max`
and `renderScale()`, glows by `glow_map` (a shadow on each stroke in
WebKit; in Chromium, which has canvas filters, a blurred copy at half
the CSS pixels under the sharp scene), and fades out over 600 ms as the
page fades in.

**The first paint is black.** `<html data-booting>` holds `.page`, every
dialog and its backdrop at opacity 0 from the first paint, so the
default palette never flashes before the server's prefs are in. The
first snapshot, or 1.5 s without one, decides once, from its `boot &&
boot_anim` and reduced motion; a later prefs frame changes nothing. A
3 s fallback in `index.html`'s head takes `data-booting` off should
nothing decide (`main.js` failed to load), so an error is never a black
window. What waits for the boot, such as the airport search a `#airport`
link opens, runs once the cover has gone (`afterBoot`). Done, the cover
gives its canvases' backing stores back.

### Map data

Built offline by `tools/build_geodata.py`, the same pattern as
`tools/build_airports.py`, and committed so the map needs no network:

| Layer | Source | Licence |
|---|---|---|
| Coastlines, lakes, rivers | Natural Earth 10 m, release v5.1.2 | public domain |
| Country and state borders, state names | Natural Earth 10 m | public domain |
| Cities, peaks | Natural Earth populated places and elevation points | public domain |
| Navaids, other airports | OurAirports `navaids.csv`, `airports.csv` | public domain |
| Runways of every airport in the dataset | OurAirports `runways.csv` | public domain |
| Class B, C and D airspace (US) | FAA NASR 28 day subscription, `class_airspace_shape_files.zip` | public domain |
| Victor airways (US) | FAA NASR CSV tables (AWY, FIX, NAV) | public domain |

Built in phase D as one file, `src/kcgx/data/geo.json.gz` (4.7 MB). Natural
Earth and OurAirports are fetched from their GitHub repositories, which
every network in this project could reach; the two FAA archives are read
from a folder they were downloaded to (`.geo-sources/`, gitignored), since
the FAA's own servers were not reachable from everywhere. Lines are
simplified to about 165 m, stored as integers in 1e-4 degree, and cut into
pieces of at most 64 points, each with its bounding box, so the server
clips the world to an airport with box tests alone (under 30 ms) and sends
only the 200 nm around it (5 to 60 KB). Since 2026-11-12 it is the 320 nm
around it, one radius for every airport, so that the 250 nm range has
room to pan: 0.11 MB of JSON for KPDX, 0.22 MB for KJFK and 0.30 MB for
EGLL, clipped in under 0.1 s. The build is deterministic: the
same sources give the same bytes. Outside the US there is no airspace or
airway layer; everything else is global.

Natural Earth's towns are sparser than the mockup's invented ones (Portland,
Vancouver, Salem and Longview are there; Gresham is not). That is the price
of public domain data, and accepted. Its coastlines carry no country, so
every coastline is drawn cyan; country borders are green and dashed, the
"elsewhere" colour, and state lines dim.

The home airport's runways are drawn as white lines inside its ring at
close zoom, which is the stills' base outlines put to honest use.

Since 2026-11-13 (phase G Task 10) the build keeps OurAirports'
`width_ft` as a runway's fifth element where the row has one, for the
radar to draw runways at their true width close in. The lane could not
fetch OurAirports, so the map was rebuilt with it on 2026-11-14: the
Natural Earth and FAA layers came out identical (same release, same
cycle), and OurAirports' nightly data moved the rest a little (18,848
airports to 18,814, 4,166 airports with runways to 4,167). 5,987 of
5,989 runways have a width; the other two are drawn 150 ft wide. A map
without widths still loads and draws.

### Every action is a click

Decided 2026-10-19: **the page never needs a keyboard, and never asks for
one.** Every action has a visible control: M and S on each feed row, a click
anywhere else on a compact row to unmute it, and in the header FEEDS,
CONFIG, PALETTE and SHUT DOWN, plus CHANGE AIRPORT on the status screen and
RECENTRE on the radar. No label shows a key: no `[F]`-style prefixes, no
footer of shortcuts.

Changed 2026-11-12 (phase F), from the owner's list. The rule stands; the
controls are fewer:

* **The header is two icons, with no border and no words** (decision 13):
  a gear for CONFIG and a power symbol, in the alarm colour, for SHUT
  DOWN, which still asks first. The airport's CHANGE AIRPORT button is a
  search icon. All three are our own inline SVG line drawings: no icon
  font and no licence to carry, and they take the palette through
  `currentColor`. Each button keeps its id, and has an `aria-label` and a
  `title`, since a drawing says nothing to a screen reader.
* **FEEDS is gone from the page** (decision 2), button and sheet. The
  server keeps `/api/feeds/available` and `open_feed`. When a launch
  falls back to one feed, the log's hint reads "choose the airport again
  to retry".
* **PALETTE is gone**: the palette is THEME in CONFIG (decision 11).
* **RECENTRE is gone; a double click on the radar recentres it**
  (decision 3). It is the one action on the page with no visible control,
  which the list chose; the canvas's label for a screen reader says it.

Changed 2026-11-13 (phase G). The rule stands; the controls moved:

* **A feed row is one button.** M and S are gone; a click anywhere on a
  compact row picks that feed, and the expanded row, the one playing, is
  not a button. The master mute is a button at the top of the
  frequencies screen, beside the volume.
* **The tracks pane has its own controls**, in its title bar: CLEAR (the
  filters), COLUMNS (a checklist) and a fold button, each with an
  `aria-label` or its word, and a grip along its top edge, a
  `separator` that takes the arrow keys, Page Up and Down, Home and End,
  as a slider does. Its headers sort, as before.
* **A click on a place centres it**, and a click on an aircraft also
  takes the view to it. Like the double click, neither has a control of
  its own; the canvas's label still names the double click.
* **Any key skips the boot animation.** That is the one time a key does
  something no control does, and it does nothing a click would not:
  the boot listens for any key or any press, and goes.

**There are no keyboard shortcuts**, which also removes the feed selection
the terminal needed for them: every control acts on its own row, so there
is nothing to select first. Ordinary browser keyboard use still works,
because the controls are real buttons and inputs: Tab moves between them,
Enter and Space press them, Escape closes the open sheet or picker, and
typing goes into the airport and feed searches. That is accessibility, not
shortcuts, and it costs the page nothing.

## The launcher

Built in phase E. `bin/kcgx` stopped being a 480 line tmux script and became a
short wrapper: it resolves its own symlink to find the repo and runs
the `kcgx` console script there with `uv run`. Everything else is
`kcgx.launcher`:

```
kcgx                  start the server if it is not running, then open the page
kcgx go [query]       switch airport, or open the page's airport search
kcgx stop             stop the server
kcgx status           running at http://127.0.0.1:8473/  (KPDX), or not running (exit 3)
kcgx --no-open        start without opening a browser
kcgx --browser        open the page in the default browser, not its own window (2026-11-12)
kcgx --demo           start the demo server
```

Since 2026-11-12 "open the page" means in the cockpit's own window where
there is one; see [Its own window](#its-own-window) below.

The server runs detached (its own session, so it outlives the terminal),
writes its port, pid and whether it is the demo to
`~/.local/state/kcgx/server.json`, and logs to `server.log` beside it
(rolled to `server.log.1` past 1 MB). Both sit beside the remembered
airport, so `KCGX_STATE_PATH` moves them too. "Running" means
`GET /api/health` answers **as kcgx**: the health reply carries
`"app": "kcgx"` so the launcher can tell its server from anything else on
the port. A record whose server does not answer is removed. A kcgx server
nobody recorded (a lost file) is adopted. The default port is `8473`
(`KCGX_PORT` overrides it); if something that is not kcgx holds it, the
server takes a free one and records that.

If the server will not start (no ffmpeg, a config file it refuses), the
launcher sees the process exit, and prints the end of the log rather than
waiting out its 20 s timeout.

`kcgx go`: an exact ICAO, or a query that `search()` resolves to exactly one
airport, is posted to `/api/airport`; if no server is running, the airport is
written to the state file first and the server started there. No query, or
one naming several airports, opens the page at `#airport` or
`#airport=<query>`, which opens CHANGE AIRPORT with the query typed and
clears the fragment. A query matching nothing is an error and changes
nothing. `--open` opens the page after switching. The terminal airport
picker, and Textual with it, are gone (decided 2026-10-22).

`kcgx stop` posts `/api/shutdown`, waits for health to stop answering, and
falls back to SIGTERM to the recorded pid; stopping something that is not
running is not an error.

`kcgx-web` still runs the server in the foreground
(`kcgx-web [--port 8473] [--icao KPDX] [--demo]`), and gained
`--refresh-feeds [--icao]` for setup's step 6.

### Its own window

Decided and built 2026-11-12 (phase F), after the owner asked that the
cockpit "launch in its own dedicated browser/wrapper that isn't Chrome".

**The window is a native WKWebView app on macOS; Linux keeps the default
browser** (decision 14). `KCGX.app` is one Swift file
(`macos/KCGXWindow.swift`: one `NSWindow` holding one `WKWebView`),
compiled by `swiftc` and signed ad hoc by `macos/build.sh`, on the machine
that runs it, so it is never notarised and carries no quarantine flag.
What was weighed: pywebview (adds pywebview and pyobjc, and shows as
"Python" in the Dock unless bundled anyway); Chrome or Edge with `--app=`
(the cheapest, and exactly what was ruled out); Electron (Chromium);
Tauri (a Rust toolchain for one window); Safari's "Add to Dock" (cannot be
scripted, so `kcgx go seattle` could not hand it a search). The
launcher's seam, `pick_opener`, is where a GTK WebKit window for Linux
would later plug in.

**The launcher opens it when it is there.** `kcgx` and `kcgx go` (which
opens a page only for the search, or with `--open`: see The launcher) show
the page in the app when its program exists at `$KCGX_APP` (by default
`~/Applications/KCGX.app`), by running
`open -a <app> kcgx://show?port=<port>&fragment=<quoted fragment>`.
Without the app, on Linux, with `--browser`, or with `KCGX_BROWSER` set to
anything but nothing or `0`, the page opens in the default browser. It
also does when `open` fails, is missing or does not return in 15 s, and
for the two pages the app is known to refuse (a port outside 1024 to
65535, a fragment over 512 bytes). `open` returning is all the launcher
can see: an app that opens and then shows no cockpit is not noticed, and
`kcgx --browser` is the way round it.

**What the app does:**

| Event | What it does |
|---|---|
| a `kcgx://show` link | checks that `http://127.0.0.1:<port>/api/health` says `"app": "kcgx"` (itself: a redirect is not followed), then loads `http://127.0.0.1:<port>/#<fragment>`; if that page is already loaded it only sets the fragment, so the socket is kept. Shows and activates the window |
| launched with no link (Dock, Spotlight) | runs `<repo>/bin/kcgx --no-open` with the `PATH` it was built with, reads `server.json` for the port and loads it; shows the launcher's own words on failure |
| the red close button | hides the app; the audio plays on; the Dock icon or Cmd-Tab shows it again |
| Quit | posts `/api/shutdown`, then exits. While the launcher is still starting the cockpit it waits for it (30 s at most), so that it stops what was started. A cockpit the app started and never got to show (below) is stopped too |
| a link while the launcher is still starting the cockpit | the link takes the window. If its port has no cockpit, the one the launcher started is shown once it is up, so it is not left playing with no window |
| the page's power icon | the page posts shutdown as in a browser, then tells the window (`ended`, to `window.webkit.messageHandlers.kcgx`), and the app exits without asking again |
| a link to anywhere but this server | not loaded in the window; opened in the default browser if it was pressed and is http or https |

**The red close button hides the window and the audio plays on; Quit, and
the power icon, stop the cockpit** (decision 15). That is how a Mac audio
app behaves, and it gives "keep listening" and "stop" one gesture each.
The cost: quitting the window stops a cockpit that was started from a
terminal too, where closing a browser never did.

The window's title follows the page's (`KCGX KPDX`); only its frame is
remembered, and the page is kept in no cache or store on disk, because
every setting is the server's. It has a small menu (Hide and Quit; Cut,
Copy, Paste and Select All, without which the airport search cannot be
pasted into; Reload and Full Screen), and the web inspector is on. When
there is no cockpit to show (the launcher failed, nothing answered, a
link was refused) the window says so in words.

**Not checked by hand when this was written.** The app is compiled and
signed, and what it makes of some forty links is tested through its
`--check` argument, and which ports it takes for a cockpit through
`--answers`; an earlier build was run once for 13 s against a demo
server and its page's socket connected. Nobody has looked at the window,
and no link has been delivered to it through `open`. The checks owed are
listed in the plan's "Built" section.

## Security

A server on localhost is reachable by every web page the browser opens, so
two checks apply to every request and the WebSocket handshake:

* **Host** must be `127.0.0.1:<port>` or `localhost:<port>`. That defeats
  DNS rebinding.
* **Origin**, when present, must be the same. That stops another site's
  page from muting your feeds or shutting the cockpit down.

No authentication beyond that: it is one person's machine.

**The `kcgx:` scheme** (2026-11-12). Any web page can open a `kcgx://`
link once KCGX.app is installed, so a link can ask for very little. It is
`kcgx://show` with a `port` and a `fragment`, once each, and nothing
else: a path, a user, any other parameter, or a port outside 1024 to
65535 refuses it. The host is always `127.0.0.1`. The port's health check
must say kcgx before anything loads, and must say it itself: the app
follows no redirect, on the health check or on the shut down it posts, so
no other place can answer for the port. The fragment is not refused for what
it holds: every byte a URL's fragment may not hold is escaped, so it stays
a fragment whatever was sent, up to 512 bytes. A link that is refused, or
whose port does not answer as kcgx, never starts the cockpit, even when
it is what launched the app: a launch whose Apple event is a GetURL does
not run the launcher. The page's `ended` message is taken only from the
main frame of the page on the port being shown.

## Install changes

Built in phase E. `setup.sh` went from nine steps to seven:

| | Step | Was |
|---|---|---|
| 1 | What you have | no tmux or adsb-tui rows; no terminal width check |
| 2 | System packages: `ffmpeg` and PortAudio | **tmux dropped** |
| 3 | `uv` | unchanged |
| 4 | Python dependencies | lists `starlette`, `uvicorn` and `websockets`; no `textual` |
| 5 | The launcher on `PATH` | unchanged, and no longer critical: no popup depends on it, so declining costs only plain `kcgx` |
| 6 | The feed list | was step 8; runs `kcgx-web --refresh-feeds --icao <remembered airport>` |
| 7 | Checking it works | was step 9; runs `ffmpeg`, imports the five dependencies, runs `python -m kcgx.selfcheck` (starts the demo server on a free port and checks health, the page and the WebSocket's first frame, then stops it), counts audio devices, and probes LiveATC and adsb.lol |

The adsb-tui download and licence prompt (old step 6) and its config file
(old step 7) are **removed**. An `adsb-tui.toml` an earlier setup wrote is
left where it is; nothing reads it now.

Platform support widens: with no adsb-tui binary to download, any processor
will do, and ARM Linux is no longer a stopping point. The adsb.lol
User-Agent setup's probe sends is a literal in `setup.sh` that a test
compares with `kcgx.radar.DEFAULT_UA`, now that `bin/kcgx` has none.

**Step 5 also builds the window, on macOS** (2026-11-12, phase F). Its
title there is "The launcher on your PATH, and its window". After the
link and the `PATH` question (the app keeps the `PATH` it was built with,
and that is the step which settles it) setup runs `macos/build.sh "$APP"`,
where `APP` is `KCGX_APP` or `~/Applications/KCGX.app`, as the launcher
reads it. It does not ask before building, as it does not ask before
linking; the banner and `--help` say that step 5 makes what is kcgx's own
without a question. No `swiftc`, or a build that fails, is said and is
never fatal: the cockpit opens in the browser. On Linux the step keeps
its old title and says nothing of a window. Step 7 gains one advisory
row, `window`: `ok` when the app is there and `codesign --verify` passes;
`none`, which is not counted as a warning, when there is no app; a
warning when one is there and does not verify. `build.sh` refuses a
destination that is not named `something.app`, or that holds anything but
a KCGX.app it built, before it makes or removes a file. `setup.sh` has no
uninstall; `rm -rf ~/Applications/KCGX.app` removes the window. Still
seven steps.

## Components

```
src/squelch/cockpit.py        new: the controller extracted from app.py
src/squelch/app.py            drives Cockpit (until retired)
src/squelch/runtime.py        new: feed loading and session building, from __main__
src/squelch/mixer.py          gains clear_channels()
src/kcgx/protocol.py          new: the wire format
src/kcgx/hub.py               new: open pages and the message log
src/kcgx/station.py           new: the mixer, the cockpit, the airport
src/kcgx/server.py            new: Starlette app, routes, /ws, kcgx-web
src/kcgx/web/debug.html       new in B: a bare page driving every control; at /debug from C
src/kcgx/web/index.html       new in C: the cockpit page
src/kcgx/web/static/          new in C: cockpit.css, js/ modules, fonts/
src/kcgx/prefs.py             new in C: palette, glow, display, beside the airport
src/kcgx/demo.py              new in C: synthetic feeds for kcgx-web --demo
src/kcgx/radar.py             new in D: adsb.lol poller, backoff, the picture, emergencies
src/kcgx/geodata.py           new in D: loads the map once, clips it per airport
src/kcgx/data/geo.json.gz     new in D: the committed map
tools/build_geodata.py        new in D: builds it from the sources above
src/kcgx/web/static/js/       radar.js, tracks.js, focus.js new in D
src/kcgx/launcher.py          new in E: kcgx start/go/stop/status, server.json, health
src/kcgx/selfcheck.py         new in E: setup.sh step 7's server check
bin/kcgx                      rewritten in E: finds the repo, runs kcgx through uv
src/kcgx/prefs.py             rewritten in F: one schema for all fourteen settings
macos/KCGXWindow.swift        new in F: KCGX.app, one WKWebView window on the local server
macos/Info.plist.in           new in F: bundle metadata, the kcgx: scheme
macos/build.sh                new in F: swiftc, the bundle, an ad hoc signature
src/kcgx/names.py             new in G: feed titles without the airport
src/kcgx/web/static/js/radar/ new in G: radar.js as index, still, moving, view, draw, info
src/kcgx/web/static/js/frames.js       new in G: the one frame clock, capped by fps_max
src/kcgx/web/static/js/columns.js      new in G: every tracks column, for the table and the data box
src/kcgx/web/static/js/boot.js         new in G: the boot's cover, playback, skip and fade
src/kcgx/web/static/js/boot-scene.js   new in G: the Vector Cockpit drawing, ported
src/kcgx/web/static/fonts/    + IBM Plex Mono, JetBrains Mono, VT323 in G, each with its OFL
```

Phase F (2026-11-12) otherwise changed files that were there: the page
(`index.html`, `cockpit.css`, and `main.js`, `sheets.js`, `store.js`,
`radar.js`, `tracks.js` and `stack.js`), `protocol.py`, `station.py`,
`server.py`, `radar.py`, `geodata.py`, `demo.py`, `launcher.py`,
`setup.sh` and `squelch/config.py`. It deleted no file: what went (the
page's feeds sheet, the PALETTE and RECENTRE buttons, LIMITS,
`radar_range_nm`) went from inside files that stayed.

Phase G (2026-11-13) otherwise changed `prefs.py` (the table kind and
forty new keys), `protocol.py`, `station.py`, `hub.py`, `server.py`,
`radar.py`, `demo.py`, `geodata.py`, `squelch/cockpit.py`,
`squelch/mixer.py`, `squelch/config.py` (which no longer has
`radar_refresh_secs`), `tools/build_geodata.py`, and the page
(`index.html`, `cockpit.css`, `main.js`, `sheets.js`, `store.js`,
`theme.js`, `status.js`, `stack.js`, `tracks.js`, `connection.js`). It
deleted one file, `radar.js`, which became `radar/`. `geo.json.gz` is
unchanged.

Removed in phase E, with their tests: `bin/kcgx`'s tmux logic,
`bin/kcgx-no-radar`, `kcgx.tmux.conf`, the whole terminal app
(`squelch/app.py`, `__main__.py`, `rows.py`, `config_view.py`, `themes.py`,
`radar_theme.py`, `squelch.tcss`), and the kcgx terminal pieces
(`kcgx/status.py`, `bigtext.py`, `picker.py`, `__main__.py`). The
`squelch`, `kcgx-airport` and `kcgx-status` commands went with them, and
Textual left the dependencies. The terminal app's tests of feed loading and
session building moved to `tests/test_runtime.py`, because the server uses
all of that code.

## Testing

* **Controller.** `test_cockpit.py` covers the rules `test_app.py` covers
  through the terminal: ordering, resort timing, slots, refusal, solo
  restore, open feed. Fake sessions, a fake clock, no Textual. Built in
  phase A.
* **Server.** Starlette's `TestClient` drives routes and the WebSocket
  against a real `Station` with fake sessions and a never-started `Mixer`:
  a mute from one page reaches another as `feed` and `order` frames; Host
  and Origin checks reject what they should. The client needs `httpx2`
  (Starlette 1.9 deprecates `httpx` for it), and its WebSocket sends
  `Host: testserver` for a bare path, so tests connect with a full
  `ws://127.0.0.1:8473/ws` URL. Built in phase B, with `test_protocol.py`,
  `test_hub.py`, `test_station.py` and a guard that no web module imports
  Textual.
* **Radar.** Built in phase D as `tests/test_radar.py`: the poller against
  a fake fetch and clock: success, `429`, `403`, no connection, backoff and
  its cap and reset, the 15 s floor, stale aging, UNK numbering, a late
  reply for the previous airport thrown away, and the User-Agent sent (or
  not, when `KCGX_ADSB_UA` is empty).
* **Geodata.** Built in phase D as `tests/test_geodata.py` and
  `tests/test_build_geodata.py`: the build is deterministic down to the
  gzip header; simplification and pieces round trip; the FAA shapefile
  (Polygon and PolygonZ) and airway tables are read from synthetic copies;
  clipping keeps exactly what meets the box; an airport near the
  antimeridian or a pole does not tear the map.
* **Look.** Screenshot comparisons against committed references are still
  not built. Phase D's browser tests check behaviour instead (below), and
  the look was checked by eye against the mockup at three sizes and two
  palettes. Worth adding once the look stops moving.
* **Emergency squawks.** A fake poll sequence where a squawk appears,
  persists and clears produces exactly two log lines; a new code on the
  same aircraft is a new line; an aircraft that drops out with a squawk is
  cleared. In the browser an emergency frame lights the EMERG lamp with its
  code and turns the row red orange. The demo's N52RT squawks 7600 for one
  minute in five so all of it can be seen.
* **Launcher.** Built in phase E as `tests/test_launcher.py`, against real
  demo servers on free ports with their state in a temporary folder: start,
  second start reuses, a stale `server.json` is replaced, an unrecorded kcgx
  server is adopted, a port held by something else is skipped, a server that
  cannot start says why at once, `stop` and `status` with and without a
  server, every shape of `kcgx go`, the server outliving the command, and
  `bin/kcgx` through a symlink and without uv. `tests/test_selfcheck.py`
  runs setup's server check for real, and `tests/test_setup.py` drives the
  seven step script with a stubbed `PATH`, as before.
* **Browser.** Built in phase C as `tests/test_page.py`: Playwright 1.56.0
  drives Chromium against a real `kcgx-web --demo` subprocess whose state
  lives in a temporary folder. It checks that no two screens overlap and
  nothing scrolls sideways at five window sizes from 1440 by 900 down to a
  phone, that the radar canvas fills its pane, that no label carries a key
  hint, that clicking a compact row unmutes it and M mutes it again, that S
  solos, that a trace draws, the feed picker, an airport change, prefs
  reaching a second tab, and the volume slider. Playwright is its own
  dependency group (`uv sync --group browser`, then `uv run playwright
  install chromium webkit`); without it these tests skip. Since 2026-11-12
  every one of them runs in WebKit as well, and a browser that is not
  installed skips its half. The logic still lives in
  Python where it is cheap to test.
  Phase D adds the radar: the map loads for the airport and places its
  labels, every aircraft on the radar is a row in the table, clicking an
  aircraft focuses it and the table follows (and the table's callsign does
  the same), place names brighten under the pointer, the wheel zooms,
  dragging pans and RECENTRE resets, headers sort, and emergency and
  refused frames light the lamps.
  Phase F (2026-11-12) rewrote these for the page as it now is and added
  to them: the four layouts and their no-overlap check, the icons, every
  control of the config sheet reaching a second tab, the banner's 8 s,
  the chatter figure, the focused row, the wheel's limits and the double
  click, the computed rings, flight tags, and label boxes down to the
  pixels of the canvas. The feed picker's test went with the picker.
  `tests/test_page_prefs.py` needs no browser: it parses `index.html` and
  holds each `[data-pref]` control to `kcgx.prefs.SCHEMA`, which is what
  stops the page and the server drifting apart.
  Phase G (2026-11-13) split the page's tests by the part of the page they
  cover, so that six worktrees could add to them at once: `test_page_audio.py`,
  `_tracks`, `_chrome`, `_map`, `_traffic`, `_seams` (the shared module
  contracts) and `test_boot.py`, all on fixtures in
  `tests/page_fixtures.py`. They hold, in both engines: one expanded feed
  and a click that picks; the tabs, the map grid and a cell reaching a
  second tab; UI zoom with a click still landing on a chevron; columns,
  filters, the sticky header, the grip and the fold; the map's styles
  against a pinned picture of the old one, labels by zoom, the 0.25 nm
  wheel, a drag moving the map and drawing it anew; tags over a trail,
  tails by time and speed, the parked fade, the sort's shading, the
  frame cap, the render scale and the burn-in's half-life; the boot's
  black first paint, its one play per launch, its skip and its palette.
  `test_page_prefs.py` now checks the table's rows, columns, ranges and
  names too, and that each control sits in its tab. `test_names.py`
  holds the feed titles. The page fixture starts each test with
  `boot_anim` off, the sort's shading at 100 % and parked traffic shown,
  so the older pixel tests see the picture they were written for.
  About 2,150 tests; about 26 minutes.
* **The window.** Built in phase F as `tests/test_window.py`. No test
  reaches Swift through a window. One kind reaches the program: on a Mac
  with `swiftc` the real app is built into the test's own folder, checked
  with `codesign --verify`, and asked through its `--check` argument what
  each of some forty links would show, and through `--answers` whether
  stand-ins on a port of this machine (one that says it is kcgx, some that
  do not, one that redirects to one that does) are a cockpit to it; the
  same file drives `build.sh`
  with a fake `swiftc` and `codesign`, which runs anywhere. Nothing in it
  opens a window or registers the app. `tests/test_launcher.py` holds the
  command the launcher would run and never runs it, and
  `tests/test_setup.py` builds with a fake `swiftc` into the test's own
  `KCGX_APP`. What the window does once open is checked by hand or not at
  all.
* **Demo mode.** `kcgx-web --demo` (phase C) runs `kcgx.demo`: synthetic
  feeds for any airport that meter, chatter, reconnect and park like real
  ones, with no network, ffmpeg or audio device, and nothing remembered.
  It is what the browser tests and any look at the page without LiveATC
  use.
* **Manual.** One run against real hardware and a live airport, as the
  mixer work required: audio continuous, meters in step with what is heard,
  radar populated, tab closed and reopened without a gap in the audio.

## Build order

| Phase | What | Gate |
|---|---|---|
| **A** | Extract `Cockpit`; terminal squelch runs on it | all existing squelch tests pass, moved where they belong |
| **B** | Server, routes, WebSocket, levels loop | server tests pass; a fake cockpit is drivable from a script |
| **C** | Page: status header, feed stack, meters, config sheet, feed picker, messages | Playwright tests against `--demo` |
| **D** | Radar: geodata build, vector renderer, poller, aircraft, table, palettes | geodata, radar and browser tests; manual check at a busy airport |
| **E** | Launcher, `setup.sh`, README; remove tmux, adsb-tui and the Textual UI | launcher, self check and setup tests; a fresh `./setup.sh` and `kcgx` on the Mac |
| **F** | The 11/12 tweaks (density, icons, every setting in CONFIG, range to 250 nm, zoom to 2.5, flight tags, label boxes); the page in WebKit; KCGX.app (2026-11-12) | prefs, page and window tests in Chromium and WebKit; by hand on the Mac, against real feeds and with the window open, **still owed** |
| **G** | The second 11/12 list (2026-11-13): the boot animation; CONFIG full-screen in four tabs, the table kind and forty new settings; one feed at a time, a master mute, titles without the airport; the tracks table's columns, filters, sort, header, height and fold; map layers by setting, labels by zoom, 0.25 nm and runways, click to centre, follow and the data box, tags over everything, tails by time and speed, parked traffic, the sort's shading; the radar split in four on one frame clock, glow per colour on the map, culling, burn-in by time, the render scale | page and Python tests in Chromium and WebKit, six lanes merged one by one with the whole suite after each. The map was rebuilt with runway widths and adsb.lol's document read (DESC and OPER dropped) on 2026-11-14. **Still owed:** by hand on the Mac, real feeds at KORD (titles, picking while one is parked, the master mute), real traffic at KPDX (parked fading, follow at 10 nm, 0.25 nm on the runways), and the boot and UI zoom in KCGX.app |

A comes first because it is the only phase that touches working code, and it
leaves the terminal cockpit intact. B through D add new files alongside the
existing cockpit, reachable as `kcgx-web` while they are being built. E is
the switch, and the only phase that deletes anything; the last commit with
the terminal cockpit is tagged `terminal-cockpit`.

## Error handling

* **No audio device.** As today: one warning, every feed still connects and
  meters. The page shows it in the log, as a banner under the header, and
  as the AUDIO lamp lit red orange.
* **ffmpeg missing.** The server refuses to start, with the same message
  squelch prints today; `kcgx` prints it in the terminal it was run from.
* **WebSocket drops** (laptop sleep, server restart). The page shows a
  "reconnecting" bar, retries with backoff, and redraws from a fresh
  `snapshot` on reconnect. Nothing is lost, because the server holds all
  state.
* **Server dies.** The page says so and stops pretending to be live. `kcgx`
  starts a new one.
* **Feed listing refused.** Unchanged behaviour and messages, except that
  the station rewrites squelch's "press f to retry" as "open FEEDS to
  retry": the feed picker fetches the listing afresh every time it opens.
  Since 2026-11-12, with no FEEDS button, it rewrites it as "choose the
  airport again to retry": choosing the airport again reads the list
  again, and fetches it when there is no cache. The line is in the
  teletype, which is hidden unless turned on.
* **adsb.lol refused.** Last good picture, backoff, as above. The radar's
  corner reads `ERR 429, PICTURE 45S OLD`, the RADAR lamp turns amber (red
  orange if there is no picture at all), and the tracks table says the
  radar is not answering when it has nothing to show. Since 2026-11-13
  the corner's first line is the poll, in words: `ERR 429, PICTURE 45
  SECONDS OLD`, and when all is well `5 SECONDS AGO`, with the range
  under it.
* **The boot cannot decide** (2026-11-13). No snapshot in 1.5 s plays no
  animation and shows the page; `main.js` failing before the boot
  decides is caught by `index.html`'s 3 s fallback; a frame of the scene
  that throws is written to the console once and the cover still leaves.

## Open questions

1. **How much of the film to quote.** The palette, shapes and lamp bar
   are in. A `GREETINGS PROFESSOR FALKEN` style line in the teletype on
   first launch, or a DEFCON style status readout, would be fun and is easy
   to overdo. Leaning toward one quiet nod in the splash and none in the
   working UI.
2. **Keep the terminal squelch?** Decided 2026-10-22: **no.** One cockpit
   to maintain; Textual, about 2,000 lines of terminal UI and 400 tests
   went in phase E (30 more, of feed loading, moved to `test_runtime.py`).
   It is all at the `terminal-cockpit` tag. The terminal airport picker
   went too: `kcgx go` with no airport opens the page's search.
3. **Feed reordering under the pointer.** Hovering the stack counts as
   touching it, so rows do not move under a cursor that is about to click.
   That may hold the order still for too long if the mouse just rests there;
   needs a feel test.
4. **Port.** `8473` is arbitrary. Fine unless it collides with something
   you run.
5. **Alarm colour in the monochrome palettes.** In `amber` and `matrix`
   the alarm colour is white rather than red orange, to keep them single
   hue. Worth checking on real hardware that an emergency still reads as
   one at a glance. Since 2026-11-12 the same holds for the header's
   power icon, which is drawn in the alarm colour: in AMBER and MATRIX it
   is white, told from the gear only by its shape, and in every palette
   it turns white under the pointer.
6. **Pressed and not pressed, outside WOPR** (raised 2026-11-12). A
   pressed button is the palette's pink, which in AMBER, MATRIX and MONO
   is within a shade of the text's colour, so only its border changes.
   CONFIG now has 26 such buttons. Older than phase F; for the owner's
   eye. Since 2026-11-13 it has many more, and the tabs are pressed
   buttons too.
7. **Tags that overlap** (raised 2026-11-12). Flight tags are not placed
   around one another, and with many fields or a 250 nm picture they pile
   up. Decluttering was left out of phase F until real traffic at 250 nm
   has been looked at. Phase G left it out too; tags now go over
   everything, so a boxed tag hides what is under it, map and traffic
   alike, and the sort decides which is on top.
8. **Should the config sheet be modal?** (raised 2026-11-12). It has no
   backdrop, so the page behind looks live, but it takes no clicks and a
   click outside does not close the sheet. A click outside closing it, or
   a sheet that is not modal so the radar can be panned while settings
   change, are both open. *Settled 2026-11-13 (decision 2):* the list
   asked for it full-screen and centred, so it covers the page over an
   85 % backdrop and is plainly modal. What is lost is watching a change
   on the radar while it is made.
9. **Parked traffic by altitude above sea level** (raised 2026-11-13).
   The airport dataset has no elevations, so `ground_alt` is above sea
   level and at a high field only 0 (`GND` alone) is safe. Field
   elevation (`elevation_ft` in `airports.csv`, and a rebuild) would fix
   it.
10. **Filters on the radar?** (raised 2026-11-13). Filters hide rows only
    (decision 4). A setting to dim on the radar what the filters hide, and
    filters remembered across a reload, were both left out.
