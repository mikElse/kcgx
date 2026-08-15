# kcgx

A terminal cockpit for watching and listening to air traffic, named for
Meigs Field — the Chicago lakefront strip that a generation of flight-sim
pilots took off from, bulldozed in the middle of the night in 2003.

Two pieces live here:

- **`squelch`** — plays *every* ATC feed an airport publishes at once,
  one metered row each, in a narrow **48 × 42** pane.
- **`kcgx`** — a launcher that arranges `adsb-tui`, a status pane, and
  `squelch` into one mouse-resizable tmux session.

```
kcgx              # open the cockpit (or reattach to a running one)
kcgx go [query]   # search for an airport and point both panes at it
kcgx stop         # shut it down
kcgx --help
```

[Install](#install) · [What it needs](#what-it-needs) ·
[Running it](#running-it) · [Getting out](#getting-out) ·
[The cockpit](#the-cockpit-kcgx) · [squelch](#squelch) ·
[Configuration](#configuration) · [Key bindings](#key-bindings)

---

## Install

```bash
git clone https://github.com/mikElse/kcgx.git
cd kcgx
./setup.sh --check   # what you have and what you are missing; changes nothing
./setup.sh           # install the missing pieces, then open the cockpit
```

That is the whole install, on **macOS or Linux**. `setup.sh` works through
nine steps, asks before each one that changes anything, and finishes by
running every moving part to prove the cockpit will open. It is idempotent,
so the second run — the one you do when you think something went wrong —
ends where the first did.

Start with `--check` if you want to know what you are in for: it prints the
table below filled in for your machine, with the command that installs each
missing piece, and touches nothing.

### What it needs

| Tool | Why | Required? |
|---|---|---|
| [`uv`](https://docs.astral.sh/uv/) | runs everything, and supplies Python 3.14 itself | yes |
| [`ffmpeg`](https://ffmpeg.org/) | decodes each feed to PCM | yes |
| [`tmux`](https://github.com/tmux/tmux) **3.1 or newer** | `kcgx` builds the pane layout with it | for the cockpit |
| **PortAudio** | what `sounddevice` plays through | on Linux |
| [`adsb-tui`](https://github.com/j4v3l/ADS-B_TUI) | the radar pane | yes |

`setup.sh` installs all of them: Homebrew on macOS, `apt`/`dnf`/`pacman` on
Linux, and the published `adsb-tui` release from GitHub. It never installs a
package manager — if there is none it stops and prints the packages instead.

**PortAudio is the one that bites on Linux.** The `sounddevice` wheel bundles
its own copy on macOS and ships none on Linux, so without `libportaudio2`
(or `portaudio`, depending on the distro) `import sounddevice` raises
`OSError: PortAudio library not found` and the audio pane never draws. That
is a system library `uv sync` knows nothing about, which is why it is a step
of its own rather than a line in `pyproject.toml`.

**`adsb-tui` is required**, and its licence is a custom **non-commercial**
one, not OSI-approved — `setup.sh` says so before downloading and asks. It
publishes builds for `macos-arm64`, `macos-x64` and `linux-x64`; on anything
else (ARM Linux, Windows) setup stops rather than installing a binary that
cannot run. Nothing is ever built from source and `cargo` is never invoked.

**There is no Python to install.** This is a Python project, but `uv`
supplies the 3.14 it requires: no system Python is read, no virtualenv is
yours to create, and there is no `pip install` step. `uv sync` — which
`setup.sh` runs for you — downloads the interpreter and the dependencies
into `.venv/` here in the repo. See [A note on `python`](#a-note-on-python)
for what that means if you have pyenv, and for the one place a bare
`python` will surprise you.

### The nine steps

| | Step | Asks before |
|---|---|---|
| 1 | What you have | — |
| 2 | System packages — `ffmpeg`, `tmux`, PortAudio | running your package manager |
| 3 | `uv`, and the Python it supplies | fetching the installer |
| 4 | Python dependencies (`uv sync`) | downloading anything |
| 5 | The launcher on your `PATH` | appending to your shell profile |
| 6 | `adsb-tui` | downloading it, licence named |
| 7 | Where the radar gets its aircraft | writing its config |
| 8 | The LiveATC feed list | fetching it |
| 9 | Checking it works | — |

```bash
./setup.sh --check     # step 1 alone, then exit
./setup.sh --verify    # step 9 alone, against this machine
./setup.sh --yes       # take every default; for unattended installs
./setup.sh --help
```

**Step 8 fills squelch's feed cache** before the first launch needs it.
LiveATC refuses roughly three requests in four, and a cold launch that
loses that coin flip opens on a single feed — see
[when it opens on one feed](#when-it-opens-on-one-feed). Out here nobody is
waiting on a UI, so it can retry twenty times instead of eight. It is not
fatal: the feed list is a week-long cache, not a dependency.

**Step 9 runs things rather than looking for files.** It executes `ffmpeg`,
`tmux` and `adsb-tui`, imports `numpy`/`sounddevice`/`textual` through the
project's own interpreter, starts `squelch`, counts audio output devices,
and reaches LiveATC and adsb.lol. An install that reports success and
then opens a broken pane has not succeeded — and running `adsb-tui --help`
is the only check that catches a binary built for the wrong platform, which
is present, executable, and unable to run.

Anything it cannot fix but you can live without — no audio device, an
unreachable feed host, a terminal under 100 columns — is a warning and the
cockpit still opens. Anything that means a dead pane stops the run, with the
command that fixes it, rather than launching into the failure.

### About your shell profile

**`setup.sh` will offer to edit it, and will not do so without asking.**
This reverses a previous decision, so it is worth being explicit: the script
used to print the `export` line and leave it entirely to you, which meant
that anyone who did not act on a message six steps up got a working cockpit
whose airport picker silently did nothing.

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Step 5 detects your shell (`zsh`, `bash`, `fish` — `fish` gets
`fish_add_path` instead), shows you the line, names the file, and asks. If
you say yes it backs the file up to `<profile>.kcgx-backup` first and marks
what it added; a second run recognises the marker and does not append again.
If you say no it says so and carries on — the cockpit still opens, and the
picker is what you lose. An unrecognised shell is told, not guessed at.

Note that `--yes` takes this default along with all the others.

### Why the `PATH` matters more than it looks

It is not just so you can type `kcgx`. `Ctrl-b a` (the airport picker) is
bound to `display-popup -E "kcgx go"`, which resolves `kcgx` by name through
the tmux server's own environment. Without it the cockpit opens fine and the
picker silently does nothing, which is the least debuggable way for this to
be broken.

If a tmux server is already running, it captured its environment when it
started — restart it (`kcgx stop`, or `tmux kill-server`) before
`Ctrl-b a` will find the launcher.

### Doing it by hand

Everything `setup.sh` does, as the individual steps — for anyone who would
rather run them, or whose platform it stops on. Nothing here is required if
you ran the script.

**Prerequisites.**

```bash
# macOS
brew install ffmpeg tmux

# Debian/Ubuntu — libportaudio2 is not optional, see above
sudo apt-get install ffmpeg tmux libportaudio2

# Fedora (ffmpeg comes from RPM Fusion, not Fedora itself)
sudo dnf install ffmpeg tmux portaudio

# Arch
sudo pacman -S --needed ffmpeg tmux portaudio
```

```bash
curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh   # if you don't have uv
```

`INSTALLER_NO_MODIFY_PATH=1` is what stops that installer appending
`. "$HOME/.local/bin/env"` to `~/.zshrc`, `~/.bash_profile` *and*
`~/.profile` without asking. Drop it if you would rather it managed your
`PATH` for you.

**The project.**

```bash
git clone https://github.com/mikElse/kcgx.git
cd kcgx
uv sync
```

That is enough to run `squelch`. The cockpit needs two more steps.

**Wiring the launcher.** `bin/kcgx` resolves its own repo root through
symlinks, so link it onto your `PATH` rather than copying it:

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/bin/kcgx" ~/.local/bin/kcgx
```

Then put `~/.local/bin` on your `PATH`, as above.

**The radar pane.** `kcgx` opens `adsb-tui` in the left pane. It comes from
[`j4v3l/ADS-B_TUI`](https://github.com/j4v3l/ADS-B_TUI); note its licence is
a custom **non-commercial** one, not OSI-approved.

```bash
# macos-arm64, macos-x64, or linux-x64 — those are the three published
curl -L https://github.com/j4v3l/ADS-B_TUI/releases/download/v0.2.1/adsb-tui-macos-arm64.tar.gz \
  | tar xzf - -C ~/.local/bin
```

Use the release rather than building from source. `cargo build` works, but
it pulls in Rust, LLVM and their dependencies — about **4 GB** of build
toolchain for a 3 MB binary that upstream already publishes. On a platform
with no published build (ARM Linux, Windows) that is your only route, and it
is why `setup.sh` stops there rather than guessing.

Without `adsb-tui` on your `PATH` the cockpit still opens: the left pane
says the radar is missing and how to add it, and `Ctrl-b r` fills it in once
you have. That is a safety net for a hand-built install, not a supported
configuration — `setup.sh` treats a radar it cannot produce as a failure.

**It also needs somewhere to get aircraft from.** Its default is
`http://adsb.local/data/aircraft.json` — a receiver on your own network.
Without one, point it at a public aggregator instead:

```toml
# $XDG_CONFIG_HOME/ads-b-tui/adsb-tui.toml, i.e. ~/.config/... unless you
# have set XDG_CONFIG_HOME. adsb-tui resolves it under XDG and nowhere else.
url_template = "https://api.adsb.lol/v2/point/{lat}/{lon}/{range_nm}"
refresh_secs = 2
layout = "radar"
radar_aspect = 0.49
```

No API key, no receiver hardware. `kcgx` fills in `{lat}`/`{lon}` per
launch from the airport you pick, so don't set `site_lat`/`site_lon` here.

`layout` is set because adsb-tui opens on the table by default and the
radar is the point of the pane. `radar_aspect` goes with it: terminal
cells are about twice as tall as they are wide, so a circular range ring
needs `2 * (rows - 8) / (cols - 2)` measured on the radar pane. 0.49
suits the left pane in a ~197-column terminal; unset, the ring renders
as a clipped ellipse. Both are starting positions: `R` switches to the
radar at runtime, `l` toggles full/compact, `t` cycles themes, and
adsb-tui writes whichever you leave it on back into this file on exit.

Two seconds is deliberate: the free aggregators rate-limit to roughly one
request per second.

**This used to be `api.airplanes.live`.** On 2026-08-13 it began answering
`403` on every endpoint — its own root included — for unauthenticated
clients, with a body directing you to email `contact@airplanes.live` and
describe your project and user base. That is a gate rather than an outage
or a rate-limit ban: the same `403` comes back from unrelated networks and
with a browser `User-Agent`, while their API guide still advertises v2 as
keyless. If you get access, `adsb-tui` takes `api_key` with
`api_key_header = "api-auth"`, which is the header they key feeders on.

One thing `adsb.lol` costs you: route lookups. Its only routeset path,
`/api/0/routeset`, answers `201` with an empty body even for a live
callsign, so origin/destination columns stay blank. Set
`route_enabled = false` to stop the pane asking every 15 s.

`setup.sh` writes exactly that file, and only if it does not already
exist — `adsb-tui` rewrites its own config on exit, so it is yours.

**Checking it.** `./setup.sh --verify` runs step 8 against whatever you have
built by hand, and changes nothing.

### A note on `python`

There is no Python installation step, and that is deliberate rather than
an omission. `uv sync` reads `.python-version` (3.14), downloads that
interpreter if you do not already have it, creates `.venv/` in the repo,
and installs the dependencies into it. One command, no system Python
involved:

```bash
uv sync              # interpreter + dependencies
uv run pytest        # the test suite, in that environment
```

Every documented command goes through `uv run`, which uses that
interpreter. **`uv run` finds the project from your working directory**,
so run these from the repo — or pass `--project` and the path from
anywhere else:

```bash
uv run --project ~/src/kcgx squelch
```

`bin/kcgx` always passes `--project` at its own repo root, which is why the
cockpit works from any directory while a bare `uv run squelch` in your home
directory does not.

**If you would rather not use uv**, a virtualenv works, but you have to
supply Python 3.14 yourself — the project requires it, and `pip` will
refuse to install into anything older:

```bash
python3.14 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/squelch
```

Nothing in the project reads `uv` at runtime; `setup.sh` and the launcher
do. `bin/kcgx` invokes `uv run` unconditionally, so a virtualenv install
gets you `squelch` on its own, not the cockpit.

If you have [pyenv](https://github.com/pyenv/pyenv) and its shims come
first on your `PATH`, bare `python` will fail *inside this repo*:

```
pyenv: version `3.14' is not installed (set by .../.python-version)
```

That is expected and harmless — `uv run` ignores pyenv entirely. Install
3.14 under pyenv if you want a working bare `python` here; nothing in kcgx
needs it. `setup.sh` detects this and says so rather than trying to fix
your `PATH`.

## Running it

The cockpit:

```bash
kcgx          # open it, or reattach to a running one from anywhere
kcgx go       # re-pick the airport in a running cockpit
kcgx stop     # shut this cockpit down
```

The audio pane on its own, without `tmux` or the radar — **from the repo
directory**, since `uv run` locates the project from your working
directory:

```bash
cd kcgx
uv run squelch                       # uses the config file / defaults
uv run squelch --feed kpdx3_twr      # override the feed ident
uv run squelch --icao KSEA           # override the airport used by the feed picker (`f`)
uv run squelch --refresh-feeds       # fill the feed cache and exit; no UI, no audio
```

From anywhere else, name the repo: `uv run --project ~/src/kcgx squelch`.
Without one or the other, `uv` exits with ``Failed to spawn: `squelch` ``,
which is uv telling you it is looking in the wrong project rather than
anything being wrong with the install.

Startup is immediate. Each feed resolves and connects on its own thread,
so a slow or dead feed never holds up the others.

If you resize your terminal, note the UI is laid out for exactly 48×42 and
does not reflow past that.

The header's `●` indicator is always truthful about playback: `STARTING`
before the first audio frame has arrived,
`LIVE` while streaming normally, `RECONNECTING` while the audio process is
being respawned after a dropout, and `OFFLINE` if the stream could not be
started or has stopped for good (in which case a warning also appears in
the message log explaining why). The meter and clock keep running
through a reconnect, so the pane never freezes.

## Getting out

The cockpit is a tmux session, so closing it is not the same keypress as
quitting an ordinary program — and `q` belongs to `squelch`, which is no
help when `squelch` is the thing that died. Three ways out, none of which
need the others to be working:

| Do this | To |
|---|---|
| `Ctrl-b` `q` | shut the cockpit down, from inside it. Asks `y/n` first. |
| `Ctrl-b` `d` | detach and leave it running. Reattach later with `kcgx`. |
| `kcgx stop` | shut it down from any other terminal. |

`Ctrl-b` `q` is the one to reach for when a pane has crashed. It is a
binding from `kcgx.tmux.conf`, so tmux runs it rather than any of the
applications: it keeps working when every one of them is dead, and —
unlike the picker's `^q` — it does not need `kcgx` to be on your `PATH`.
It replaces tmux's own `q` (show pane numbers) inside this session.

**Panes that die stay on screen** rather than collapsing the layout, with
their last output and exit status: for a monitoring cockpit, noticing that
something died is the point. `Ctrl-b` `r` respawns the pane under the
cursor, which is how you restart one without restarting the session.

---

## The cockpit (`kcgx`)

`kcgx` starts a tmux session laid out like this, with every splitter
draggable by mouse:

```
┌────────────────┬───────────┐
│                │  status   │
│    adsb-tui    ├───────────┤
│                │  squelch  │
│                │           │
└────────────────┴───────────┘
```

The right column starts at exactly 48 columns because that is `squelch`'s
design width; below it the header truncates and the level meter loses
resolution. The status pane starts eight rows tall — two of padding and
six of content, four of which are the ICAO banner. These are starting
positions, not constraints — drag them.

**The status pane** sits above squelch and draws the current ICAO in
block capitals, four rows tall:

```
▗▖ ▗▖ ▗▄▄▖ ▗▄▄▖▗▖  ▗▖
▐▌▗▞▘▐▌   ▐▌    ▝▚▞▘
▐▛▚▖ ▐▌   ▐▌▝▜▌  ▐▌
▐▌ ▐▌▝▚▄▄▖▝▚▄▞▘▗▞▘▝▚▖
```

It is the one thing here you read from across the room, so it is drawn
rather than printed. The glyphs are Unicode quadrant blocks, so they need
no font the radar does not already require. Under it sit the airport name,
and the time in Zulu and in your own timezone (`1955Z   12:55 PDT`)
alongside `▾ airport (^b a)`. Clicking that hint opens the same picker
popup as `Ctrl-b a` — both are the same `tmux display-popup` call, pinned
together by a test.

Drag the pane narrower than the banner and the code goes back to being
printed beside the name, exactly as it was before the banner existed —
half a block letter reads as a different letter, so it is dropped whole
rather than clipped.

In the picker: `↵` goes to the highlighted airport, `esc` closes it and
leaves the cockpit where it is, and **`^q` shuts every cockpit down** — all
of them, on every tmux socket, not just this one. It is deliberately wider
than `kcgx stop`, which only ever kills the session it was invoked for.
Cockpits are recognised by their panes' `@kcgx_role` tags rather than by
session name, so a session of your own that happens to be called `kcgx`
survives.

The binding is `^q` and not plain `q` because the search box keeps focus so
that typing always filters: it consumes printable keys before any app
binding sees them, so a bare `q` binding never fires at all — and forcing
one through would cost you every airport starting with the letter, Quito
and Queenstown among them. The pane re-reads
the remembered airport once a second, so `kcgx go` moves it without a
respawn or a flicker. The airport's own local time is deliberately not
shown: the dataset carries no timezone column, and deriving one from
longitude would be wrong across DST and political boundaries anyway.

**Requires tmux 3.1 or newer** (`brew install tmux`). Settings live in
`kcgx.tmux.conf` and are never read from — or written to — your
`~/.tmux.conf`.

The config is both passed with `tmux -f` and sourced explicitly on every
launch. The second part matters: `-f` is only honoured when the command
*starts* the tmux server, and is ignored outright if one is already running.
Sourcing explicitly means the settings apply whether or not a server was up,
and that editing `kcgx.tmux.conf` takes effect on your next `kcgx` rather
than requiring you to kill the server.

**Running it again reattaches** rather than starting a second copy, so
nothing restarts and the audio keeps playing. Closing the terminal
detaches; the session keeps running.

**`kcgx stop`** shuts the cockpit down. It kills only the kcgx session, not
the tmux server, so any other tmux sessions you have keep running. Stopping
something that isn't running is not an error.

**Mouse behaviour.** tmux handles drags on pane borders. Clicks and scrolls
*inside* a pane go to the application if it asked for mouse reporting —
`squelch` does, so its feed picker stays clickable. `adsb-tui` most likely
does not, so scrolling over it enters tmux's copy-mode, which gives you
scrollback over the traffic table.

**Picking an airport.** `Ctrl-b` then `a` opens an airport search in a
popup over the cockpit, and so does clicking `▾ airport (^b a)` in the
status pane; `kcgx go [query]` does the same thing from any terminal — the
cockpit no longer has a pane you could type it into. Typing matches ICAO,
IATA, airport name, city, region and country;
accents and separators are folded on both sides, so `seattle-tacoma`
finds Seattle–Tacoma (the dataset spells it with an en dash) and `ohare`
finds O'Hare. Short query words have to match the start of a word rather
than any substring, which is what lets `portland or` mean Oregon instead
of matching the "or" buried in "portland". `kcgx go KORD` skips the
picker outright — an exact four-letter ICAO is an answer, not a search.
The choice is remembered in `~/.local/state/kcgx/airport` (just the ICAO;
coordinates are looked up again from the dataset on every launch, so a
dataset update can't leave a stale one behind) and the cockpit reopens
there. With nothing ever picked, it falls back to `icao` in
`squelch.toml`, then to `KPDX`.

Neither `squelch.toml` nor `adsb-tui.toml` is
modified — adsb-tui rewrites its own config with defaults on exit, so an
edit made to it by hand would not survive the next launch. Instead
adsb-tui is retargeted with `--site-lat`/`--site-lon`, which also moves
its adsb.lol query. Airports LiveATC doesn't cover still get a
working radar; squelch just shows an empty pane with a message instead —
it will never fall back to playing a different airport's feed under the
wrong header. The search dataset is `src/kcgx/data/airports.csv`, 4,737
large and medium airports with ICAO codes, committed to the repo so
search needs no network and no API key; regenerate it with
`uv run --project . python tools/build_airports.py`.

**When something dies**, its pane stays visible with its final output and
exit status instead of silently collapsing the layout. `Ctrl-b` then `r`
respawns the pane under the cursor, and `Ctrl-b` then `q` shuts the whole
cockpit down — see [Getting out](#getting-out).

**With `adsb-tui` not installed**, the left pane says so, says where to get
it, and says how to leave, rather than leaving the shell's `command not
found` under a dead-pane banner next to two panes that work. Install it
whenever you like and press `Ctrl-b` `r` there; nothing needs restarting.
`setup.sh` will not leave you in this state — it treats a radar it cannot
produce as a failed install — so this is the safety net for a cockpit built
by hand, or one whose binary went missing afterwards.

`kcgx` refuses to start below 100 columns, where there isn't room for both
a readable traffic table and a 48-column pane.

---

## squelch

A terminal ATC audio player. It opens every feed LiveATC publishes for an
airport, stacks them one per row with a scrolling level meter each, and
lets you unmute the ones you want to hear.

```
 KCGX  12 feeds               07:54:29  10 live
────────────────────────────────────────────────
 Tower (Both)                               ●
 ░░░▒▒▓▓▓▓▓▒▓▓▓▓▓▓▒▒░░░░▒▒▓▓▓█▓▓▒▒░░░░░░▒▓▓
 [S]  [ ON]  [A]                    Chatter 34%
────────────────────────────────────────────────
 Ground                            [A] ♪   7% ◐
────────────────────────────────────────────────
 Clearance Delivery                [A] ♪   0% ●
```

An audible feed is **expanded** — a one-row meter and its full controls.
A muted feed collapses to a single **compact** line carrying its chatter
figure behind a `♪`, which is the number the stack is sorted by. There is
no `[OFF]` on a compact row: it is muted by definition, so the toggle could
only ever have read OFF. Clicking anywhere on the row unmutes it. Expansion follows what
you can hear, so the pane spends its height on the frequencies you are
actually listening to. **Every feed meters whether or not it is audible** —
muting is an audio gate, not a pause — a muted feed simply keeps its history
without drawing it. The dot on the right is that feed's connection: `●`
live, `◐` reconnecting, `○` offline.

Feed idents no longer appear on the row. They are still what `feed` in
`squelch.toml` and `--feed` take, and the feed picker (`f`) still shows them.

### Ordering

**Audible feeds sit at the top**, in the order you unmuted-or-not; what you
can hear is what you want to look at. Everything below them is ordered by
how busy it has been over the last five minutes — the fraction of that
window spent above `activity_threshold_dbfs`. An offline feed decays to 0%
and sinks. The expanded row shows the figure as `Chatter 34%`.

Muting a feed drops it straight back into that sort on its chatter alone,
so a busy frequency you have just silenced stays near the top of the muted
group rather than disappearing to the bottom.

Activity-driven reordering does not happen the instant the ranking changes.
A new order is applied only once it has held for fifteen seconds and you
have not touched the pane for two — because clicking a row toggles its
mute, and a row that moves while you are reaching for it silences the wrong
frequency.

**Muting and unmuting are exempt from that delay.** The row moves at once,
because it is the direct result of the key you just pressed rather than
activity drifting underneath you. Selection follows the feed rather than the
position, so `space` keeps acting on the feed you just toggled even though
it has moved. One consequence worth knowing: after a click-to-mute the stack
reshuffles immediately, so a second click at the same spot lands on a
different feed.

Activity is measured on the decoded feed, which is also exactly what you
hear — nothing sits between the two.

### Matching themes

squelch adopts the radar pane's colour scheme, including its meter gradient.
It tracks `adsb-tui`'s `t` key within about three seconds.

It does that by *looking at* the radar pane rather than by reading its
config. `adsb-tui` does not write the theme anywhere when you cycle it —
measured: two `t` presses and a clean quit leave its TOML byte-identical —
so the rendered pane is the only truthful source. `kcgx` passes the pane id
in `KCGX_RADAR_PANE`, and squelch runs `tmux capture-pane -e` every three
seconds and matches the pane's background colour against the six known
themes.

Run outside the cockpit, with no `KCGX_RADAR_PANE` set, squelch reads
`theme` from `adsb-tui.toml` once at startup and stays there. Failing that,
it uses `default`. Nothing about this can fail loudly: an unreadable pane,
a missing tmux, or an unrecognised colour all just leave the current theme
in place.

Transcription was removed — see "History" at the end.

To run it on its own, outside the cockpit:

```
tmux split-window -h -l 48 'uv run squelch --feed kpdx3_twr'
```

## What it does, and does not, do

- Opens every feed the airport publishes, each with its own ffmpeg
  process, output stream, and meter.
- Starts with everything muted except the feed named by `feed` in config
  (or `--feed`) — you see the whole field immediately, but hear one
  frequency until you choose otherwise. A dozen simultaneous voices is not
  something anyone can follow.
- Meters muted feeds exactly as it meters audible ones.
- Isolates failures per feed: one that cannot resolve, or whose ffmpeg
  dies, goes to `○` on its own row and warns. The other eleven keep going.
- Scrolls when there are more feeds than rows; arrows move the selection
  and bring it into view.
- Does **not** transcribe. That was removed; see "History".
- Does **not** record, save, or redistribute any audio. Playback is local
  only, for personal listening — consistent with LiveATC.net's terms of
  use, which govern rebroadcast and redistribution of their feeds.

## Configuration

squelch reads TOML from `~/.config/squelch/squelch.toml`. **Nothing creates
that directory for you** — squelch only ever reads the file, and `setup.sh`
does not write one, so the first thing to do is make it:

```bash
mkdir -p ~/.config/squelch
$EDITOR ~/.config/squelch/squelch.toml
```

Every key is optional; anything not set (or the whole file, if it doesn't
exist) falls back to the defaults below. Unknown keys in the file are ignored rather
than treated as an error, so an older binary can still read a newer config.
Known keys *are* type-checked at startup: a bad value (say `feed = 3`)
exits immediately with a message naming the file and the key, rather than
failing later inside the audio pipeline.

| Key                 | Default                                                        | Meaning |
|----------------------|----------------------------------------------------------------|---------|
| `icao`               | `"KPDX"`                                                        | Airport used by the feed picker (`f`) to look up feeds on LiveATC.net |
| `feed`               | `"kpdx3_twr"`                                                    | The one feed left unmuted at startup |
| `activity_threshold_dbfs` | `-40.0`                                                    | Level above which a feed counts as busy for the five-minute ranking. Must be written as a decimal (`-40.0`, not `-40`). |
| `master_volume` | `1.0` | Output gain, 0.0–1.0. Shown as a percentage in the config overlay. The only gain in the signal path. |
| `ambient_enabled` | `false` | Set `true` for `[A]` routing, panning, and the reverb bus. |
| `ambient_gain_db` | `-8.0` | Ambient bus level, relative to the dry bus |
| `buffer_seconds` | `4.0` | How much audio a feed may hold before the ring buffer drops to catch up — in effect, how far behind live you are willing to sit. See "Buffering" below; do not lower it past about 2.5 without measuring. |

The `model`, `compute_type` and `vad_aggressiveness` keys are gone, and so
are the seven that configured the gate and the compressor — `gate_dbfs`,
`gate_enabled`, `compressor_enabled`, `compressor_threshold_dbfs`,
`compressor_ratio`, `compressor_makeup_db`, `compressor_range_db`. An
existing config that still sets any of them keeps working — unknown keys
are ignored, not rejected.

Example:

```toml
icao = "KSEA"
feed = "ksea_twr"
```

`--feed` and `--icao` on the command line override the config file for that
run.

## Key bindings

**The cockpit**, handled by tmux, so these work even when a pane has died:

| Key | Action |
|---------|--------|
| `Ctrl-b` `a` | Open the airport search over the cockpit. |
| `Ctrl-b` `r` | Respawn the pane under the cursor. |
| `Ctrl-b` `q` | Shut the cockpit down (asks first). |
| `Ctrl-b` `d` | Detach; the session keeps running. |

**squelch**, in its own pane:

| Key     | Action |
|---------|--------|
| `↑` `↓` | Move the selection through the stack. |
| `c`     | Open the config overlay: master volume is adjustable with `◂ ▸`; the rest shows what is honoured. |
| `space` | Mute/unmute the selected feed. Its meter keeps running either way. |
| `S`     | Solo the selected feed — mute every other one. Press again to restore the previous mix. |
| `a`     | Route the selected feed to the ambient bus. |
| `f`     | Open the feed picker and jump to a feed by name. |
| `escape`| (in the feed picker) Close it without choosing anything. |
| `q`     | Quit. |

Every control is also clickable: `[S]`, `[ ON]`/`[OFF]`, and `[A]`. Clicking
anywhere else on a row toggles its mute.

The footer shows only `[↑↓] select`, `[space] mute` and `[c] config`; `f`
and `q` still work, they just no longer spend cells saying so.

The meter is a **shade ramp** — `░▒▓█`, one row — so the level reads as
density rather than as bar height, and each shade carries its own colour
from the active theme: `░` noise floor, `▒` speech, `▓` a strong signal,
`█` approaching clipping. A silent feed shows a flat `░` line rather than
going blank, so a dead feed and a gap in the layout do not look alike.

### The config overlay

`c` opens a table of every audio setting the design defines, grouped by
what it shapes — **Output**, **Chatter**, **Ambient**.

```
 Output
›Master volume               100% ◂ ▸

 Chatter
 Chatter threshold     -40.0 dBFS live

 Ambient
 Ambient bus                  off off
 Bus level                -8.0 dB off
 Reverb decay              100 ms off
 Reverb roll-off          1200 Hz off
```

**Master volume is the only control**, because it is the only gain in the
path: `◂ ▸` moves it in 5% steps and it reaches the running mixer
immediately, scaling the summed output before the clip.

Every other row reports rather than controls, and says which it is:

- **live** — read from `squelch.toml` and actually applied.
- **inert** — read from `squelch.toml`, applied to nothing.
- **fixed** — compiled in; not settable at all.
- **off** — the effect it belongs to is bypassed.

`Chatter threshold` is the one non-audio row and stays **live**: it decides
what counts as busy for the row readout and the stack ordering, not how
anything sounds. Marking it inert would be a lie, and disabling it would
silently break the sort.

Turning the shaping back on is a config-file change, not a keypress — the
overlay reports the audio path, and only offers to change the part of it
that is live.

### Feed picker

Pressing `f` lists the feeds LiveATC publishes for the configured airport
and jumps to the one you choose — the quick way to a specific frequency,
which matters more once activity sorting is moving rows around.

**If the feed you pick is not open, it opens it**, audible, with its own
row and meter. That is what makes `f` a real recovery rather than a
suggestion: when the listing is refused at launch (see below) squelch opens
the configured feed alone and says "press f to retry", and pressing `f`
usually gets through. Before, every feed the retry turned up answered
"kpdx_gnd is not open" — true, and the end of the road short of restarting.

The fetch runs off the event loop, so a slow or hanging LiveATC request
never stalls playback or the UI. If the list can't be loaded at all, a
warning appears in the message log instead of a crash.

## Feed discovery and LiveATC's bot protection

LiveATC fronts its airport listing page with Cloudflare bot protection.
Measured against the live site: a browser `User-Agent` does not help,
spacing requests out does not help, and roughly **one request in four is
allowed through anyway**. (The `/play/*.pls` endpoints squelch actually
streams from are not protected, which is why audio works regardless.)

squelch therefore treats a 403 on the listing as a coin flip to re-flip,
not an answer, and caches the result for a week under `~/.cache/squelch/`.
**A normal launch makes no request at all.** The retry budget depends on
what a failure costs:

| | Attempts | Failure rate | Because |
|---|---|---|---|
| Launch, cache present | 5 | ~24% | costs a week-old list |
| Launch, no cache | 8 | ~10% | costs an empty or one-feed pane |
| `--refresh-feeds` | 20 | ~0.3% | costs a wall clock nobody is watching |

When a refresh is due and every attempt is refused, it falls back to the
cached list — feed lists change on the order of months — and only opens the
single configured feed if there is no cache at all. Each of those fallbacks
says so in the message log.

### When it opens on one feed

This is the failure worth recognising, because it does not look like one.
On a **first** launch at an airport there is no cache, so a run of refusals
leaves squelch with nothing to open but `feed` from the config. At the
default airport that is `kpdx3_twr`, so the pane comes up showing KPDX
Tower and nothing else, as though that were all LiveATC had:

```
⚠ KPDX — could not reach LiveATC's listing (HTTP Error 403: Forbidden);
  opening kpdx3_twr only; press f to retry
```

Press `f`. It refetches the listing, and now that you have the picker open
you can open any feed it found. Or fill the cache from outside the app,
which is what `setup.sh` step 8 does for you:

```bash
uv run --project . squelch --refresh-feeds              # the configured airport
uv run --project . squelch --refresh-feeds --icao KSEA  # any other
```

That is worth running by hand after `kcgx go` points you at a new airport
for the first time — the cache is per-ICAO, so a new airport is a cold one.
It needs no audio device and no `ffmpeg`; it fetches, writes the cache, and
prints what it found.

**squelch will never fall back to a different airport's audio.** The
one-feed fallback only fires when the configured feed's ident starts with
the configured ICAO, so retargeting to KORD and losing the listing gives
you an empty pane with a message rather than Portland tower under a header
reading KORD.

## Cost

One ffmpeg process, one ring buffer, and one thread per feed — twelve of
each at KPDX — feeding **one** stereo output stream. Bandwidth is trivial at
roughly 16–32 kbps per feed; the CPU is mostly ffmpeg decode plus one
mixing callback every 16 ms. That callback is a sum and a multiply — the
reverb, whose comb loops are the only part of it that is not vectorised,
is off by default and does not run at all. Worth watching on battery.

## Audio shaping

**There is none.** What reaches the device is the decoded feed scaled by
master volume:

```
ffmpeg ─► ring buffer ─► sum ─► master volume ─► stereo
```

See "Buffering" below for the one number in that chain that matters.

There was, briefly, a per-feed noise gate and an upward compressor between
the ring buffer and the sum. Both were **removed** on 2026-08-02, along
with their config keys and their controls. The gate never had anything to
reject — LiveATC squelches at the source, so 87% of blocks arrive at
exactly −96 dBFS with a ~70 dB gap up to speech — and a gain that moves
continuously is the wrong thing to have in the path when the complaint is
that the audio sounds choppy. `git log -- src/squelch/dsp.py` has the
measurements.

An unmuted feed now contributes exactly the samples ffmpeg decoded. There
is a test asserting a mixer built from the shipped `Config` returns
output == input, sample for sample.

The ambient bus survives, shipped disabled: `[A]` still marks a feed and
the mixer still ignores it. The reverb is not run at all rather than run
and added as silence, which saves most of the mixer's cost. One config key
brings it back:

```toml
ambient_enabled = true      # [A] routing, panning, reverb
```

**`[A]` routes a feed to the ambient bus**, when enabled: 8 dB down,
panned, and heard only through a short dark reverb — 100 ms, fully wet,
rolled off above 1.2 kHz. Several feeds spread across the stereo field
between 50% left and 50% right; an odd number puts one in the centre,
phase-inverted and 6 dB down so it does not pile up in the middle.

The meter shows the level of what you hear, and the activity ranking
measures the same signal.

## Buffering

This is the number that decides whether the audio sounds continuous, and
it is not obvious, so it is written down.

**LiveATC does not trickle.** 93% of ffmpeg's reads arrive less than a
millisecond after the previous one, in bursts separated by gaps of up to
2.5 seconds, each burst carrying roughly 1.2 seconds of audio. The stream
also runs about 1.05× the device clock — slightly faster than realtime.

Each feed's ring buffer absorbs that. When a burst is larger than the
buffer, `RingBuffer.write` drops the *oldest* samples to make room; the
buffer then drains and pads with silence until the next burst. So the
capacity is really a ceiling on **how far behind live a feed may fall
before it starts discarding audio** — and because the source sends faster
than realtime, it will fill whatever it is given. It behaves less like a
DAW's buffer-size setting and more like a video player's: latency traded
against completeness. CPU is not on the axis at all; the callback copies
the same 256 samples every 16 ms regardless. Memory is 64 KB per second
per feed.

Measured against a live KPDX tower feed:

| `buffer_seconds` | audio kept | blocks reaching the device as silence | typical lag |
|---|---|---|---|
| 0.5 | 36% | 61% | 0.0 s |
| 2.0 | 90% | 6% | ~1.0 s |
| **4.0** | **95%** | **0.6%** | **~1.5 s** |
| 8.0 | 99% | 0% | ~5.0 s |

4 seconds is the knee: three times the typical burst, so overflow is rare,
while staying close enough to live to sit beside a radar pane showing the
same aircraft. Raise it on a lossy connection; lower it to stay tighter to
live, and expect dropouts below about 2.5.

It shipped at 0.5 for a while, which is well under one burst — the result
was that roughly two thirds of every feed was discarded before it reached
the mixer, and words were cut mid-syllable because the drop is
oldest-first. `tests/test_mixer.py` replays a synthetic burst source
matching the measurement above and fails if the capacity goes back under a
burst.

## Known limitations

- Feeds are discovered once at startup; a feed that appears on LiveATC
  later needs a restart to show up.
- The reverb is fixed. Decay, damping, and wetness are not configurable.
- All feeds share one output device; there is no per-feed device routing.
- Ranking is by level crossings, not by speech detection — a feed with a
  noisy carrier will rank above a quiet but busy one.
- No transcription (see "History").
- The message log only carries warnings, so the pane is mostly empty at
  rest. Retention is capped at the most recent 200 messages so memory and
  redraw cost stay flat over a multi-hour session.

The batch of upgrades these once pointed at — click-to-mute, solo,
activity-ordered feeds, theme matching with the radar pane, and an audio path
with upward compression and an ambient reverb bus — is built. Its specs and
implementation plans are in [`docs/`](docs/README.md).

## History

squelch originally transcribed the audio live, using an ATC-fine-tuned
Whisper model
([`jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper`](https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper))
with WebRTC VAD segmenting the squelch-gated audio into whole
transmissions. That was removed: it cost a 1.5 GB first-run download that
blocked audio startup, and CPU-bound inference running for the life of the
session.

The work is not lost. It is tagged `squelch-with-transcription`, and the
whole of it — `asr.py`, `vad.py`, the transcript UI, the inference worker
and its backpressure handling — can be recovered from there:

```bash
git show squelch-with-transcription:src/squelch/asr.py
git diff squelch-with-transcription    # everything the removal changed
```
