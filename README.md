# kcgx

A cockpit for watching and listening to air traffic, in a window of its
own on a Mac or in your browser, named for Meigs Field — the Chicago
lakefront strip that a generation of flight-sim pilots took off from,
bulldozed in the middle of the night in 2003.

It plays **every** ATC feed an airport publishes at once, one metered row
each, beside its own vector radar of the traffic around the field, on a
page drawn like the NORAD wall in *WarGames*. Everything runs on your own
machine: a small local server plays the audio and polls the radar, and the
page at `http://127.0.0.1:8473/` is the display and the controls.

```
kcgx              # start the cockpit if it is not running, and open it
kcgx go [query]   # switch airport, or open the page's airport search
kcgx stop         # shut it down
kcgx status       # is it running, and where
kcgx --browser    # open it in your browser, not in its own window
kcgx --demo       # the demo: synthetic feeds and traffic, no audio
```

[Install](#install) · [Running it](#running-it) · [The cockpit](#the-cockpit) ·
[The radar](#the-radar) · [Configuration](#configuration) ·
[Feed discovery](#feed-discovery-and-liveatcs-bot-protection) ·
[Buffering](#buffering) · [History](#history)

---

## Install

```bash
git clone https://github.com/mikElse/kcgx.git
cd kcgx
./setup.sh --check   # what you have and what you are missing; changes nothing
./setup.sh           # install the missing pieces, then open the cockpit
```

That is the whole install, on **macOS or Linux**, on any processor.
`setup.sh` works through seven steps, asks before it installs anything or
edits a file of yours, and finishes by starting the server and asking it
for the page and its live connection, to prove the cockpit will open. Step
5 alone makes things without a question of its own: the launcher's link,
and on a Mac the cockpit's window, both kcgx's own and both named as they
are made. It is idempotent, so the second run — the one you do when you
think something went wrong — ends where the first did.

### What it needs

| Tool | Why | Required? |
|---|---|---|
| [`uv`](https://docs.astral.sh/uv/) | runs everything, and supplies Python 3.14 itself | yes |
| [`ffmpeg`](https://ffmpeg.org/) | decodes each feed to PCM | yes |
| **PortAudio** | what `sounddevice` plays through | on Linux |
| a web browser | the cockpit is a page | yes |
| `swiftc` | builds KCGX.app, the cockpit's own window | no; macOS only |

`setup.sh` installs the first three: Homebrew on macOS, `apt`/`dnf`/`pacman`
on Linux. It never installs a package manager — if there is none it stops
and prints the packages instead. `swiftc` comes with the Xcode command line
tools (`xcode-select --install`), which Homebrew already needs; setup does
not install it, and without it the cockpit opens in your browser.

**PortAudio is the one that bites on Linux.** The `sounddevice` wheel bundles
its own copy on macOS and ships none on Linux, so without `libportaudio2`
(or `portaudio`, depending on the distro) `import sounddevice` raises
`OSError: PortAudio library not found` and nothing can be heard. That is a
system library `uv sync` knows nothing about, which is why it is a step of
its own rather than a line in `pyproject.toml`.

**There is no Python to install.** `uv` supplies the 3.14 the project
requires: no system Python is read, no virtualenv is yours to create, and
there is no `pip install` step. See [A note on `python`](#a-note-on-python).

### The seven steps

| | Step | Asks before |
|---|---|---|
| 1 | What you have | — |
| 2 | System packages — `ffmpeg`, PortAudio | running your package manager |
| 3 | `uv`, and the Python it supplies | fetching the installer |
| 4 | Python dependencies (`uv sync`) | downloading anything |
| 5 | The launcher on your `PATH`, and on macOS its window | appending to your shell profile |
| 6 | The LiveATC feed list | fetching it |
| 7 | Checking it works | — |

```bash
./setup.sh --check     # step 1 alone, then exit
./setup.sh --verify    # step 7 alone, against this machine
./setup.sh --yes       # take every default; for unattended installs
./setup.sh --help
```

**Step 5 builds the window on a Mac** (since 2026-11-12). After the link
and the `PATH` question it runs `macos/build.sh`, which compiles one Swift
file with `swiftc`, puts it in a bundle and signs it for this Mac alone:
`~/Applications/KCGX.app`, or wherever `KCGX_APP` says. It does not ask
first, as it does not ask before making the link; it builds beside the
destination and moves the app into place only once it is whole, and it
refuses a destination that is not a KCGX.app it built. The app keeps the
`PATH` it was built with, because a launch from the Dock has no shell.
With no `swiftc`, or a build that fails, setup says so and carries on, and
the cockpit opens in your browser. Linux is not offered a window. To build
it later, run `macos/build.sh`; to remove it, `rm -rf
~/Applications/KCGX.app`.

**Step 6 fills the feed cache** before the first start needs it. LiveATC
refuses roughly three requests in four, and a cold start that loses that
coin flip opens on a single feed — see
[when it opens on one feed](#when-it-opens-on-one-feed). Out here nobody is
waiting on a page, so it can retry twenty times instead of eight. It is not
fatal: the feed list is a week-long cache, not a dependency.

**Step 7 runs things rather than looking for files.** It runs `ffmpeg`,
imports `numpy`, `sounddevice`, `starlette`, `uvicorn` and `websockets`
through the project's own interpreter, starts the real server (as the
demo, on a free port) and asks it for its health, the page and the
WebSocket's first frame, counts audio output devices, and asks LiveATC and
adsb.lol for the exact thing the cockpit asks them for, insisting on a
`200` — "something answered" is not the same claim, and a `403` answers.
On a Mac it also has a `window` row: `ok` when KCGX.app is there and
`codesign --verify` passes, `none` when there is no app (not a warning:
the cockpit opens in your browser), and a warning when an app is there and
does not verify, since macOS will not start it.

Anything it cannot fix but you can live without — no audio device, an
unreachable feed host, `kcgx` not yet on your `PATH` — is a warning and the
cockpit still opens. Anything that means a broken page stops the run, with
the command that fixes it.

### About your shell profile

**`setup.sh` will offer to edit it, and will not do so without asking.**
Step 5 links `bin/kcgx` into `~/.local/bin`, and if that is not on your
`PATH` it offers this line:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

It detects your shell (`zsh`, `bash`, `fish` — `fish` gets `fish_add_path`
instead), shows you the line, names the file, and asks. If you say yes it
backs the file up to `<profile>.kcgx-backup` first and marks what it added;
a second run recognises the marker and does not append again. If you say no
it carries on: the cockpit still starts as `<repo>/bin/kcgx`, just not as
plain `kcgx`. An unrecognised shell is told, not guessed at. `--yes` takes
this default along with all the others.

### Doing it by hand

```bash
# macOS
brew install ffmpeg
# Debian/Ubuntu — libportaudio2 is not optional, see above
sudo apt-get install ffmpeg libportaudio2
# Fedora (ffmpeg comes from RPM Fusion, not Fedora itself)
sudo dnf install ffmpeg portaudio
# Arch
sudo pacman -S --needed ffmpeg portaudio

curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh   # if you don't have uv

git clone https://github.com/mikElse/kcgx.git
cd kcgx
uv sync
mkdir -p ~/.local/bin && ln -s "$PWD/bin/kcgx" ~/.local/bin/kcgx
macos/build.sh   # macOS, optional: ~/Applications/KCGX.app, the cockpit's own window
```

`INSTALLER_NO_MODIFY_PATH=1` stops uv's installer appending to `~/.zshrc`,
`~/.bash_profile` *and* `~/.profile` without asking. Link `bin/kcgx`
rather than copying it: it finds the repo through the symlink.
`./setup.sh --verify` checks a hand-built install and changes nothing.

### A note on `python`

`uv sync` reads `.python-version` (3.14), downloads that interpreter if you
do not have it, creates `.venv/` in the repo, and installs the dependencies
into it. Every command goes through `uv run`, which uses that interpreter
and **finds the project from your working directory**, so run them from
the repo or pass `--project`:

```bash
uv run pytest                           # the test suite
uv run --project ~/src/kcgx kcgx-web    # the server in the foreground, from anywhere
```

`bin/kcgx` always passes `--project` at its own repo root, which is why
`kcgx` works from any directory.

If [pyenv](https://github.com/pyenv/pyenv) shims come first on your `PATH`,
bare `python` fails *inside this repo* (`pyenv: version '3.14' is not
installed`). That is expected and harmless — `uv run` ignores pyenv
entirely, and `setup.sh` says so rather than changing your `PATH`.

## Running it

```bash
kcgx                    # start it (or find the running one) and open its window
kcgx --no-open          # start it without opening anything
kcgx --browser          # open the page in your default browser instead
kcgx go KSEA            # switch airport: an exact ICAO
kcgx go seattle tacoma  # ...or any search that names one airport
kcgx go --open KSEA     # switch, and show the cockpit as well
kcgx go portland        # names several: opens the page's search with it typed
kcgx go                 # opens the page's airport search
kcgx status             # running at http://127.0.0.1:8473/  (KPDX)
kcgx stop               # stop the server, and the audio with it
kcgx --demo             # the demo: synthetic feeds and traffic, no audio
```

**Its own window** (since 2026-11-12). On a Mac where setup has built
KCGX.app, `kcgx` and `kcgx go` show the cockpit there, when they show it
at all: a small WebKit app with one window, in the Dock as KCGX, and not a
tab in Chrome. `kcgx go` with an airport it can settle on (an ICAO, or a
search that names one) switches the cockpit and opens nothing, so a hidden
window stays hidden; `kcgx go --open KSEA` switches and shows it. With no
airport, or a search that names several, `kcgx go` opens the page's search,
as above.

The launcher looks for the app at `~/Applications/KCGX.app` (`KCGX_APP`
names another place) and hands it the page with `open`. Where there is no app,
on Linux, with `--browser`, or with `KCGX_BROWSER=1` in the environment
(anything but empty or `0` counts), the page opens in your default browser
as it always did; it does the same, and says so, if `open` fails. Opening
KCGX from the Dock or Spotlight with nothing running starts the cockpit
and shows it.

**Closing is not quitting.** The window's red button hides it and the
audio plays on; the Dock icon or Cmd-Tab brings it back. Quit (Cmd-Q)
stops the cockpit, whichever way it was started, and so does the power
icon on the page. That is the one difference from a browser: closing a
tab, or the browser itself, never stopped the cockpit, and quitting the
window does.

**If the window misbehaves, `kcgx --browser` is the way back.** The
launcher only knows that `open` took the link, not that the window then
showed the cockpit. `rm -rf ~/Applications/KCGX.app` puts everything back
in the browser for good. When this was written the app had been built,
signed and tested through its links, and nobody had yet watched the window
do what this section says; the checks still owed are listed under "Built"
in [the plan](docs/superpowers/plans/2026-11-12-cockpit-tweaks.md#built).

**The server runs in the background** and outlives the terminal you started
it from: close the window or the tab and the audio keeps playing; run
`kcgx` again and it shows the running cockpit rather than starting
another. It writes where it is to `~/.local/state/kcgx/server.json` and
logs to `server.log` beside it. "Running" means its health check answers,
never that the file exists, so a file left by a crash or a reboot is
replaced. The port is `8473` (`KCGX_PORT` changes it); if something that is
not kcgx has it, the server takes a free one and records that.

**Stopping**: `kcgx stop`, the power icon on the page (it asks first), or
Quit in the window. Each stops every feed and the server; the page says
COCKPIT SHUT DOWN.

**The demo** (`kcgx --demo`, or `kcgx-web --demo`) runs synthetic feeds that
meter, chatter, reconnect and park like real ones, and a dozen aircraft on
fixed paths around whatever airport is open (fewer of them at a short
range), one of which squawks 7600 for a minute in every five. No network, no `ffmpeg`, no audio, and nothing is
remembered. It is what the tests run against, and a way to look at the page
anywhere.

**`kcgx-web`** is the server itself, in the foreground: `kcgx-web [--port
8473] [--icao KPDX] [--demo]`, Ctrl-C to stop. `kcgx-web --refresh-feeds
[--icao KSEA]` fills the feed cache and exits.

The server listens on `127.0.0.1` only and refuses requests that name
another host or come from another site's page.

## The cockpit

The page is a wall of framed screens with their names along the bottom:

| Screen | Shows |
|---|---|
| TRAFFIC | the radar (see [The radar](#the-radar)) |
| the airport (it has no title) | the ICAO, Zulu and your local time, the airport's name and place, and a search icon, bottom right, that opens CHANGE AIRPORT |
| FREQUENCIES | every feed, with a trace of its level; it runs the full height of the right column |
| TRACKS | the traffic table: callsign, type, altitude, speed, track, distance, squawk |
| TELETYPE | the message log, typed out; **off until you turn it on** in CONFIG |

The page was tightened on 2026-11-12: less padding round everything, and
two parts that are shown only when asked for, both under LAYOUT in CONFIG.

The **lamp bar** (STATUS LAMPS) sits under the radar, at the radar's
width: one lamp per feed in its state colour (cyan live, amber
reconnecting, red orange offline, dark parked), then RADAR, SERVER and
AUDIO, then EMERG, which lights red orange with the code when an aircraft
in range squawks 7500, 7600 or 7700.

The **teletype** sits under FREQUENCIES, beside TRACKS. It collects its
lines while it is hidden, so turning it on shows what was said. Hiding it
does not hide an error: while it is off, an error from the page itself (a
failed airport search, a setting the server refused, a shut down that did
not go through) shows in the banner under the header for eight seconds.
The server's own notes (a feed list it could not fetch, an emergency
squawk) are not put in the banner: they wait in the teletype.

Under 1100 px wide the page is one column: radar, airport, frequencies,
lamps, tracks, teletype.

**Every action is a click.** There are no keyboard shortcuts and no labels
naming keys. The header has two icons: a gear, which opens CONFIG (see
[Configuration](#configuration)), and a power symbol, which shuts the
cockpit down after asking. Each has a tooltip and a name for a screen
reader. FEEDS and PALETTE left the header on 2026-11-12: every feed an
airport publishes opens at launch already, and the palette is THEME in
CONFIG. Tab, Enter, Space and Escape work as they do on any page.

**The feed stack.** An audible feed is an expanded row: its name, an
oscilloscope trace of its level, **M** (mute; lit when muted) and **S**
(solo; lit when soloed, press again to restore the mix), and its chatter
figure, a percentage (`27%`). A muted feed is one compact line, and
clicking it unmutes it. Every feed meters whether or not you can hear it.

Audible feeds sit at the top. Everything below is ordered by how busy it
has been over the last five minutes — the fraction of that window spent
above `activity_threshold_dbfs`. A new order is applied only once it has
held for fifteen seconds and the pointer has been off the stack for two,
because a row that moves while you reach for it silences the wrong
frequency. Muting and unmuting move the row at once.

**LiveATC streams seven feeds at once from one address.** Past that the
quietest muted feeds are parked (dark lamp, `‖`); unmute one and the
quietest muted feed gives up its place.

**The focused track leads the table.** Click an aircraft on the radar, or
its callsign in TRACKS, and its row moves to the top of the table, a fifth
larger in every cell, with the rest dimmed; sorting orders the others
beneath it. Click again and it goes back to its place.

**Every setting is remembered.** The theme, glow (off, low, full), display
(off; vector, with flicker and jitter; CRT, adding scanlines and rounded
screens) and everything else in CONFIG are kept by the server, so every
tab, the window and every start agree. Reduced motion in your system
settings turns off every animation.

## The radar

Our own vector renderer, not a map library: line art on black, an
azimuthal equidistant projection centred on the airport, so the range
rings are true circles and distance reads straight off the screen. The
range fits the shorter side of the screen; the longer side shows more map.

- **The range** is how far out traffic is asked for: 40 nm unless you
  change it, and anything from 10 to 250 nm on CONFIG's RANGE slider. 250
  is the most adsb.lol will answer for. The range's own ring is drawn
  bright and the readout in the radar's corner names it (`RNG 40 NM`). A
  new range resets the view to it.
- **Aircraft** are chevrons along their track, each with a flight tag and
  a trail that fades from the arrow back. Positions are dead reckoned
  between polls, an aircraft fades after 30 s without a position and drops
  at `radar_stale_secs`, and one with no callsign is `UNK1`, `UNK2` in
  order of first sighting. An emergency squawk turns it red orange and
  adds one line to the teletype.
- **The flight tag** shows the fields chosen under FLIGHT TAG in CONFIG:
  callsign, type, squawk, altitude, ground speed, track and distance. With
  two or fewer it is one line, and the default, callsign and altitude, is
  `ASA412 6200`. With more it is two: who it is over what it is doing,
  `ASA412 B39M 4512` over `3100 230KT 270° 11.0NM`. What an aircraft does
  not report is left out, and with no field chosen there is no tag, only
  the chevron.
- **Click an aircraft** (arrow, trail or tag) to focus it: it turns pink
  with a ring and the rest dim, and its row leads the TRACKS table. Click
  again to restore them.
- **Drag** to pan, **scroll** to zoom, **double click** to come back to
  the airport at the range. The closest view is 2.5 nm from the centre to
  the nearer edge, near enough to read the runways; the widest is 160 nm,
  or the range if that is more. The title strip shows the pointer's
  bearing and distance from the field. (There was a RECENTRE button until
  2026-11-12.)
- **Range rings** follow the view: every 0.5, 1, 2, 5, 10, 20 or 50 nm,
  whichever puts no more than five between the centre and the nearer
  edge, out to the range, each numbered where its number has room.
- **Place names** sit back at about 40% and come up under the pointer.
  Labels never overlap: one that does not fit is left off, its symbol
  kept. Small airports appear from a 27 nm view inwards.
- **Label boxes** put a black box behind the labels you choose under
  LABEL BOXES in CONFIG: flight tags, the home airport's name, other
  airports, navaids, cities, peaks, state names, ring numbers, and the
  readouts in the radar's corners. One fill, padding, border and border
  width serve them all; the border takes the label's colour. None is
  boxed unless you choose it. A boxed label is never laid across another
  label of the map, so with boxes on a ring number or a place name that
  no longer fits is left off.

The map is coastlines, lakes and rivers, country borders (green, dashed)
and state lines, cities, peaks, VORs (diamonds), other airports
(triangles), the home airport's runways in white, its pink ring (2.5 nm
in radius, held between 24 and 64 px on screen so the name stays beside
it), and in the US the class B, C and D airspace (red orange, dashed) and
the Victor airways (blue, dashed).

**Where the traffic comes from.** The server polls
[adsb.lol](https://adsb.lol) for the range around the field every 15 s and
sends the picture to every open tab, so two tabs do not double the rate.
Changing the range never causes a poll: the new range is asked for at the
next one that was due anyway, so a wider picture fills in up to 15 s
later, while a narrower one drops what is beyond it at once.
Fifteen seconds is deliberate: adsb.lol says its [rate limits are dynamic
based on the environment load](https://github.com/adsblol/api), and from
one address 2 s and 5 s polling drew a steady stream of `429`s that
persisted through slower intervals once tripped. A config file can lengthen
the interval, never shorten it below 15 s. A refused poll keeps the last
picture and backs off (30 s, 60 s, then 120 s); the radar's corner says
`ERR 429, PICTURE 45S OLD` and the RADAR lamp turns amber.

adsb.lol refuses a request with no `User-Agent` (`403 User-Agent too
generic; include valid contact info.`), so the server sends
`kcgx/0.1 (+https://github.com/mikElse/kcgx)`. `KCGX_ADSB_UA` replaces it;
set it empty to send none. Put your own contact in if you fork this —
being reachable is what adsb.lol is asking for. (This was
`api.airplanes.live` until 2026-08-13, when it began refusing every
unauthenticated client.)

**The map is committed**, in `src/kcgx/data/geo.json.gz` (4.7 MB), so it
needs no network. The server sends each page the 320 nm around its airport
(200 until 2026-11-12), which leaves room to pan at the widest range.
All of it is public domain:

| Layer | Source |
|---|---|
| coastlines, lakes, rivers, borders, cities, peaks | [Natural Earth](https://www.naturalearthdata.com/) 10 m, v5.1.2 |
| navaids, airports, runways | [OurAirports](https://ourairports.com/data/) |
| class B, C and D airspace; Victor airways (US) | FAA [NASR 28 day subscription](https://www.faa.gov/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/) |

To rebuild it, download the FAA cycle's `class_airspace_shape_files.zip`
and `<DD_Mon_YYYY>_CSV.zip` into `.geo-sources/`, then:

```bash
uv run python tools/build_geodata.py
```

It fetches the rest itself into the same folder, and the same sources give
the same bytes. Without the FAA files the airspace and airway layers are
empty and it says so.

## Configuration

There are two places: CONFIG on the page, for everything about the look
and the radar, and a TOML file, for the audio engine and the poller.

### CONFIG, on the page

The gear in the header opens a sheet docked to the right edge. It does not
darken the page, so each control is seen working as it moves; the page
behind takes no clicks until the sheet is closed, with CLOSE or Escape. A
change
goes to the server, which checks it, saves it and tells every open page,
so every tab and the window agree. The settings live in
`~/.local/state/kcgx/prefs.json`; a value there that is not one of those
below falls back to its own default and disturbs no other. The demo never
writes the file.

MASTER VOLUME is at the top, under OUTPUT. The rest:

| Section | Row | Values | Default | In `prefs.json` |
|---|---|---|---|---|
| LOOK | THEME (a dropdown) | WOPR, AMBER, MATRIX, MONO | WOPR | `palette` |
| | GLOW | OFF, LOW, FULL | LOW | `glow` |
| | DISPLAY | OFF, VECTOR, CRT | CRT | `display` |
| | SCANLINE OPACITY | 0 to 100 % | 34 | `scan_opacity` |
| | SCANLINE SIZE | 2 to 8 px from one line to the next | 3 | `scan_size` |
| LAYOUT | STATUS LAMPS | OFF, ON | OFF | `lamps` |
| | TELETYPE | OFF, ON | OFF | `teletype` |
| RADAR | RANGE | 10 to 250 nm, in tens | 40 | `range_nm` |
| | FLIGHT TAG | any of CALLSIGN, TYPE, SQWK, ALT, GS, TRK, DIST | CALLSIGN, ALT | `tag_fields` |
| | LABEL BOXES | any of AIRCRAFT, HOME, AIRPORTS, NAVAIDS, CITIES, PEAKS, STATES, RINGS, HUD | none | `box_items` |
| | BOX FILL | 0 to 100 % black | 70 | `box_fill` |
| | BOX PADDING | 0 to 12 px | 4 | `box_pad` |
| | BOX BORDER | 0 to 100 % of the label's colour | 50 | `box_border` |
| | BORDER WIDTH | 1 to 5 px | 1 | `box_width` |

The two scanline sliders work only with DISPLAY at CRT, and are greyed
otherwise; the dark line is a third of the size. In the file, ON and OFF
are `true` and `false`, numbers are whole, and the two lists are JSON
lists. The sheet used to end with LIMITS, which showed the stream limit
and changed nothing; it went on 2026-11-12.

### `squelch.toml`

kcgx reads TOML from `~/.config/squelch/squelch.toml` (the name is the
audio engine's, from before the cockpit had a page). **Nothing creates it
for you**:

```bash
mkdir -p ~/.config/squelch
$EDITOR ~/.config/squelch/squelch.toml
```

Every key is optional. Unknown keys are ignored, so an older version can
read a newer file; known keys are type-checked at start, and a bad value
stops the server with a message naming the file and the key.

| Key | Default | Meaning |
|---|---|---|
| `icao` | `"KPDX"` | The airport to open when none has been chosen yet |
| `feed` | `"kpdx3_twr"` | The one feed left unmuted at start |
| `activity_threshold_dbfs` | `-40.0` | Level above which a feed counts as busy for the five-minute ranking. A decimal (`-40.0`, not `-40`). |
| `master_volume` | `1.0` | Output gain, 0.0 to 1.0; CONFIG's slider changes it while running |
| `buffer_seconds` | `4.0` | How far behind live a feed may fall before it drops audio; see [Buffering](#buffering) |
| `max_streams` | `7` | Streams held open at once; LiveATC's limit |
| `radar_refresh_secs` | `15` | Seconds between radar polls; never less than 15 |
| `radar_stale_secs` | `60` | An aircraft not heard from for this long drops off |

**`radar_range_nm` was retired on 2026-11-12.** The range is CONFIG's
RANGE now, changed while running and remembered with the other settings.
A file that still sets the key loads as before; the key is ignored, as any
unknown key is.

The airport you choose is remembered in `~/.local/state/kcgx/airport`, and
the cockpit reopens there; `icao` is only the fallback. `ambient_enabled`
and `ambient_gain_db` are still read, for the mixer's ambient bus, which
the page has no control for.

## Feed discovery and LiveATC's bot protection

LiveATC fronts its airport listing page with Cloudflare bot protection.
Measured against the live site: a browser `User-Agent` does not help,
spacing requests out does not help, and roughly **one request in four is
allowed through anyway**. (The `/play/*.pls` endpoints the audio comes from
are not protected, which is why audio works regardless.)

kcgx therefore treats a 403 on the listing as a coin flip to re-flip, not
an answer, and caches the result for a week under `~/.cache/squelch/`. **A
normal start makes no request at all.** The retry budget depends on what a
failure costs:

| | Attempts | Failure rate | Because |
|---|---|---|---|
| Start, cache present | 5 | ~24% | costs a week-old list |
| Start, no cache | 8 | ~10% | costs an empty or one-feed stack |
| `kcgx-web --refresh-feeds` | 20 | ~0.3% | costs a wall clock nobody is watching |

When a refresh is due and every attempt is refused, it falls back to the
cached list, and only opens the single configured feed if there is no cache
at all. Each fallback says so in the teletype.

### When it opens on one feed

On a **first** start at an airport there is no cache, so a run of refusals
leaves nothing to open but `feed` from the config. At the default airport
that is `kpdx3_twr`, so the stack comes up showing KPDX Tower and nothing
else, as though that were all LiveATC had:

```
KPDX — could not reach LiveATC's listing (HTTP Error 403: Forbidden);
opening kpdx3_twr only; choose the airport again to retry
```

That line is a note in the teletype, which is off unless you turn it on
in CONFIG; with it off, the only sign is a stack with one feed in it.

Choose the airport again: the search icon in the airport pane, then the
same airport, or `kcgx go KPDX`. With no cache to read it fetches the
listing afresh and opens every feed it finds. (Until 2026-11-12 a FEEDS
button did this; it went because it had no other use, every feed being
open already once the listing has been read.) Or fill the cache from
outside, as setup's step 6 does, and then choose the airport again:

```bash
uv run kcgx-web --refresh-feeds               # the remembered airport
uv run kcgx-web --refresh-feeds --icao KSEA   # any other
```

The cache is per ICAO, so a new airport is a cold one.

**kcgx never falls back to a different airport's audio.** The one-feed
fallback only fires when the configured feed's ident starts with the
airport's ICAO, so switching to KORD and losing the listing gives you an
empty stack with a message rather than Portland tower under a KORD header.

## What it does, and does not, do

- Opens every feed the airport publishes, each with its own `ffmpeg`
  process and ring buffer, into one stereo output.
- Starts with everything muted except the configured feed: you see the
  whole field at once, but hear one frequency until you choose otherwise.
- Isolates failures per feed: one that cannot resolve, or whose `ffmpeg`
  dies, goes offline on its own row and says why. The others keep going.
- Does **not** record, save, or redistribute any audio. Playback is local
  only, for personal listening, consistent with LiveATC.net's terms of use.
- Does **not** transcribe; see [History](#history).

## Cost

One `ffmpeg` process, one ring buffer, and one thread per feed — twelve of
each at KPDX, seven of them streaming — feeding **one** stereo output
stream. Bandwidth is roughly 16–32 kbps per feed; the CPU is mostly
`ffmpeg` decode plus one mixing callback every 16 ms. The server adds a
radar poll every 15 s and about 15 KB/s of levels to each open tab. The
page's radar redraws only what moves; the map is drawn once per airport,
pan or zoom.

## Audio shaping

**There is none.** What reaches the device is the decoded feed scaled by
master volume:

```
ffmpeg ─► ring buffer ─► sum ─► master volume ─► stereo
```

A per-feed noise gate and an upward compressor were **removed** on
2026-08-02. The gate never had anything to reject — LiveATC squelches at
the source, so 87% of blocks arrive at exactly −96 dBFS with a ~70 dB gap
up to speech — and a gain that moves continuously is the wrong thing to
have in the path when the complaint is choppy audio. A test asserts that a
mixer built from the shipped config returns output equal to input, sample
for sample.

## Buffering

This is the number that decides whether the audio sounds continuous, and it
is not obvious, so it is written down.

**LiveATC does not trickle.** 93% of `ffmpeg`'s reads arrive less than a
millisecond after the previous one, in bursts separated by gaps of up to
2.5 seconds, each carrying roughly 1.2 seconds of audio. The stream also
runs about 1.05× the device clock.

Each feed's ring buffer absorbs that. When a burst is larger than the
buffer, the *oldest* samples are dropped; the buffer then drains and pads
with silence until the next burst. So the capacity is a ceiling on **how far
behind live a feed may fall before it starts discarding audio**. Measured
against a live KPDX tower feed:

| `buffer_seconds` | audio kept | blocks reaching the device as silence | typical lag |
|---|---|---|---|
| 0.5 | 36% | 61% | 0.0 s |
| 2.0 | 90% | 6% | ~1.0 s |
| **4.0** | **95%** | **0.6%** | **~1.5 s** |
| 8.0 | 99% | 0% | ~5.0 s |

4 seconds is the knee: three times the typical burst, so overflow is rare,
while staying close enough to live to sit beside a radar showing the same
aircraft. Raise it on a lossy connection; expect dropouts below about 2.5.
`tests/test_mixer.py` replays a synthetic burst source matching the
measurement and fails if the capacity goes back under a burst.

## Known limitations

- Feeds are discovered once per airport and the list is kept for a week;
  a feed that appears on LiveATC later shows up when the list is next
  fetched (`kcgx-web --refresh-feeds` does it now) and the airport is
  chosen again or the cockpit restarted.
- Flight tags are not placed around one another. Where aircraft are close
  their tags overlap, more so with every field chosen, and a boxed tag
  hides the one under it. At 250 nm a busy picture will be crowded.
- STATES under LABEL BOXES has nothing to box: the map that ships names
  no states.
- The window is macOS only, and KCGX.app has the generic icon.
- All feeds share one output device.
- Ranking is by level, not speech detection: a feed with a noisy carrier
  ranks above a quiet but busy one.
- Outside the US the map has no airspace and no airways.
- Natural Earth's towns are sparse: Portland, Vancouver, Salem and Longview,
  but not Gresham.
- The page is for one person on one machine: the server listens on
  `127.0.0.1` only, and has no accounts.

## Development

```bash
uv run pytest -q                                   # the suite
uv sync --group dev --group browser                # once, for the page's own tests
uv run playwright install chromium webkit          # once
```

`tests/test_page.py` drives the page in a real browser, and runs each of
its tests twice: in Chromium and in WebKit, Safari's engine and the one
KCGX.app shows the page in. Without the browser group it skips; without
one of the two browsers, that browser's half skips. With both, the suite
is about 1,290 tests and takes about ten minutes:

```bash
uv run --group browser pytest -q
```

`tests/test_page_prefs.py` needs no browser: it holds the CONFIG sheet's
controls to `kcgx.prefs.SCHEMA`, the one description of every setting.
`tests/test_window.py` builds the real KCGX.app into the test's own folder
(on a Mac with `swiftc`; elsewhere that part skips) and asks its program,
with `--check`, what each of some forty links would show, and with
`--answers`, whether what is on a port says it is kcgx. Nothing in the
suite opens a window: what the window does once it is open has no test.
Nothing in it starts the real cockpit either: every server is the demo.
Specs and plans for everything here are in [`docs/`](docs/README.md).

## History

The cockpit began in a terminal: `squelch`, a Textual audio player in a
48-column pane, beside [`adsb-tui`](https://github.com/j4v3l/ADS-B_TUI) for
the radar and a status pane, arranged by a tmux script. It moved to the
browser in five phases in October 2026 (the plans are in
[`docs/`](docs/README.md)); the last one removed tmux, adsb-tui and the
terminal UI. A sixth, on 2026-11-12, tightened the page, moved every
setting into CONFIG, took the radar's range to 250 nm and its zoom to
2.5, and gave the cockpit a window of its own on macOS. The last commit
with the terminal cockpit is tagged `terminal-cockpit`:

```bash
git show terminal-cockpit:bin/kcgx
git checkout terminal-cockpit -- src/squelch/app.py   # to look, not to keep
```

Before that, squelch transcribed the audio live, using an ATC-fine-tuned
Whisper model
([`jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper`](https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper))
with WebRTC VAD segmenting the audio into whole transmissions. That was
removed: it cost a 1.5 GB first-run download that blocked audio startup,
and CPU-bound inference running for the life of the session. It is tagged
`squelch-with-transcription`:

```bash
git show squelch-with-transcription:src/squelch/asr.py
```
