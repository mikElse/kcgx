# kcgx

A cockpit for watching and listening to air traffic, in your browser,
named for Meigs Field — the Chicago lakefront strip that a generation of
flight-sim pilots took off from, bulldozed in the middle of the night in
2003.

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
`setup.sh` works through seven steps, asks before each one that changes
anything, and finishes by starting the server and asking it for the page
and its live connection, to prove the cockpit will open. It is idempotent,
so the second run — the one you do when you think something went wrong —
ends where the first did.

### What it needs

| Tool | Why | Required? |
|---|---|---|
| [`uv`](https://docs.astral.sh/uv/) | runs everything, and supplies Python 3.14 itself | yes |
| [`ffmpeg`](https://ffmpeg.org/) | decodes each feed to PCM | yes |
| **PortAudio** | what `sounddevice` plays through | on Linux |
| a web browser | the cockpit is a page | yes |

`setup.sh` installs them: Homebrew on macOS, `apt`/`dnf`/`pacman` on Linux.
It never installs a package manager — if there is none it stops and prints
the packages instead.

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
| 5 | The launcher on your `PATH` | appending to your shell profile |
| 6 | The LiveATC feed list | fetching it |
| 7 | Checking it works | — |

```bash
./setup.sh --check     # step 1 alone, then exit
./setup.sh --verify    # step 7 alone, against this machine
./setup.sh --yes       # take every default; for unattended installs
./setup.sh --help
```

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
kcgx                    # start it (or find the running one) and open the page
kcgx --no-open          # start it without opening a browser
kcgx go KSEA            # switch airport: an exact ICAO
kcgx go seattle tacoma  # ...or any search that names one airport
kcgx go portland        # names several: opens the page's search with it typed
kcgx go                 # opens the page's airport search
kcgx status             # running at http://127.0.0.1:8473/  (KPDX)
kcgx stop               # stop the server, and the audio with it
kcgx --demo             # the demo: synthetic feeds and traffic, no audio
```

**The server runs in the background** and outlives the terminal you started
it from: close the tab and the audio keeps playing; run `kcgx` again and it
opens a new tab on the running server rather than starting another. It
writes where it is to `~/.local/state/kcgx/server.json` and logs to
`server.log` beside it. "Running" means its health check answers, never
that the file exists, so a file left by a crash or a reboot is replaced. The
port is `8473` (`KCGX_PORT` changes it); if something that is not kcgx has
it, the server takes a free one and records that.

**Stopping**: `kcgx stop`, or SHUT DOWN on the page (it asks first). Either
stops every feed and the server; the page says COCKPIT SHUT DOWN.

**The demo** (`kcgx --demo`, or `kcgx-web --demo`) runs synthetic feeds that
meter, chatter, reconnect and park like real ones, and a dozen aircraft on
fixed paths around whatever airport is open, one of which squawks 7600 for
a minute in every five. No network, no `ffmpeg`, no audio, and nothing is
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
| STATUS | the airport, Zulu and your local time, CHANGE AIRPORT |
| FREQUENCIES | every feed, with a trace of its level |
| TRACKS | the traffic table: callsign, type, altitude, speed, track, distance, squawk |
| TELETYPE | the message log, typed out |

Between them runs a **lamp bar**: one lamp per feed in its state colour
(cyan live, amber reconnecting, red orange offline, dark parked), then
RADAR, SERVER and AUDIO, then EMERG, which lights red orange with the code
when an aircraft in range squawks 7500, 7600 or 7700.

**Every action is a click.** There are no keyboard shortcuts and no labels
naming keys. The header has FEEDS (open any feed the airport publishes),
CONFIG (volume, palette, glow, display), PALETTE (cycles WOPR, AMBER,
MATRIX and MONO) and SHUT DOWN. Tab, Enter, Space and Escape work as they
do on any page.

**The feed stack.** An audible feed is an expanded row: its name, an
oscilloscope trace of its level, **M** (mute; lit when muted) and **S**
(solo; lit when soloed, press again to restore the mix), and its chatter
figure. A muted feed is one compact line, and clicking it unmutes it.
Every feed meters whether or not you can hear it.

Audible feeds sit at the top. Everything below is ordered by how busy it
has been over the last five minutes — the fraction of that window spent
above `activity_threshold_dbfs`. A new order is applied only once it has
held for fifteen seconds and the pointer has been off the stack for two,
because a row that moves while you reach for it silences the wrong
frequency. Muting and unmuting move the row at once.

**LiveATC streams seven feeds at once from one address.** Past that the
quietest muted feeds are parked (dark lamp, `‖`); unmute one and the
quietest muted feed gives up its place.

**The look is remembered.** Palette, glow (off, low, full) and display (off;
vector, with flicker and jitter; CRT, adding scanlines and rounded screens)
are kept by the server, so every tab and every start agrees. Reduced motion
in your system settings turns off every animation.

## The radar

Our own vector renderer, not a map library: line art on black, an
azimuthal equidistant projection centred on the airport, so the range
rings are true circles at 10, 20, 30 and 40 nm and distance reads straight
off the screen. The 40 nm ring fits the shorter side of the screen; the
longer side shows more map.

- **Aircraft** are chevrons along their track, labelled with callsign and
  altitude (`ASA412 6200`), with a trail that fades from the arrow back.
  Positions are dead reckoned between polls, an aircraft fades after 30 s
  without a position and drops at `radar_stale_secs`, and one with no
  callsign is `UNK1`, `UNK2` in order of first sighting. An emergency squawk
  turns it red orange and prints one line in the teletype.
- **Click an aircraft** (arrow, trail or label) to focus it: it turns pink
  with a ring and the rest dim. Its row in TRACKS does the same, and the
  table follows. Click again to restore them.
- **Drag** to pan, **scroll** to zoom (a quarter to six times), RECENTRE to
  come back. The title strip shows the pointer's bearing and distance from
  the field.
- **Place names** sit back at about 40% and come up under the pointer.
  Labels never overlap: one that does not fit is left off, its symbol kept.

The map is coastlines, lakes and rivers, country borders (green, dashed)
and state lines, cities, peaks, VORs (diamonds), other airports
(triangles), the home airport's runways in white inside its pink ring, and
in the US the class B, C and D airspace (red orange, dashed) and the Victor
airways (blue, dashed).

**Where the traffic comes from.** The server polls
[adsb.lol](https://adsb.lol) for the 40 nm around the field every 15 s and
sends the picture to every open tab, so two tabs do not double the rate.
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
needs no network. The server sends each page the 200 nm around its airport.
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
| `radar_range_nm` | `40` | The circle asked of adsb.lol |
| `radar_stale_secs` | `60` | An aircraft not heard from for this long drops off |

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
opening kpdx3_twr only; open FEEDS to retry
```

Open FEEDS: it fetches the listing afresh, and any feed it finds opens with
a click. Or fill the cache from outside, as setup's step 6 does:

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

- Feeds are discovered once per airport; a feed that appears on LiveATC
  later needs FEEDS or a change of airport to show up.
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
uv run playwright install chromium                 # once
```

Without the browser group, `tests/test_page.py` skips. Specs and plans for
everything here are in [`docs/`](docs/README.md).

## History

The cockpit began in a terminal: `squelch`, a Textual audio player in a
48-column pane, beside [`adsb-tui`](https://github.com/j4v3l/ADS-B_TUI) for
the radar and a status pane, arranged by a tmux script. It moved to the
browser in five phases in October 2026 (the plans are in
[`docs/`](docs/README.md)); the last one removed tmux, adsb-tui and the
terminal UI. The last commit with the terminal cockpit is tagged
`terminal-cockpit`:

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
