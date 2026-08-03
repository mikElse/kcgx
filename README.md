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
resolution. The status pane starts four rows tall so squelch keeps most of
the column. These are starting positions, not constraints — drag them.

**The status pane** sits above squelch and shows, on its first line, the
current ICAO and airport name, and on its second, the time in Zulu and in
your own timezone (`1955Z   12:55 PDT`) alongside `▾ airport (^b a)`.
Clicking that hint opens the same picker popup as `Ctrl-b a` — both are the
same `tmux display-popup` call, pinned together by a test. The pane re-reads
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

Neither `squelch.toml` nor `~/.config/ads-b-tui/adsb-tui.toml` is
modified — adsb-tui rewrites its own config with defaults on exit, so an
edit made to it by hand would not survive the next launch. Instead
adsb-tui is retargeted with `--site-lat`/`--site-lon`, which also moves
its airplanes.live query. Airports LiveATC doesn't cover still get a
working radar; squelch just shows an empty pane with a message instead —
it will never fall back to playing a different airport's feed under the
wrong header. The search dataset is `src/kcgx/data/airports.csv`, 4,737
large and medium airports with ICAO codes, committed to the repo so
search needs no network and no API key; regenerate it with
`uv run --project . python tools/build_airports.py`.

**When something dies**, its pane stays visible with its final output and
exit status instead of silently collapsing the layout. `Ctrl-b` then `r`
respawns the pane under the cursor.

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
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 [S]  [ ON]  [A]
────────────────────────────────────────────────
 Ground                          [A] [OFF] ◐
────────────────────────────────────────────────
 Clearance Delivery              [A] [OFF] ●
```

An audible feed is **expanded** — a three-row meter and its full controls.
A muted feed collapses to a single **compact** line. Expansion follows what
you can hear, so the pane spends its height on the frequencies you are
actually listening to. **Every feed meters whether or not it is audible** —
muting is an audio gate, not a pause — a muted feed simply keeps its history
without drawing it. The dot on the right is that feed's connection: `●`
live, `◐` reconnecting, `○` offline.

Feed idents no longer appear on the row. They are still what `feed` in
`squelch.toml` and `--feed` take, and the feed picker (`f`) still shows them.

### Ordering

Feeds are ordered by how busy they have been over the last five minutes —
the fraction of that window spent above `activity_threshold_dbfs`. The
busiest frequency is at the top, and an offline feed decays to 0% and sinks.
The expanded row shows the figure as `busy 34%`.

The order does not change the instant the ranking does. A new order is
applied only once it has held for fifteen seconds and you have not touched
the pane for two — because clicking a row toggles its mute, and a row that
moves while you are reaching for it silences the wrong frequency.

Activity is measured **before** the compressor, so making quiet feeds louder
does not make them look busier.

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

## Install

Requires Python 3.14+ and [`ffmpeg`](https://ffmpeg.org/) on your `PATH`
(used to decode the stream to PCM).

```bash
cd squelch
uv sync
```

## Running it

```bash
uv run squelch                       # uses the config file / defaults
uv run squelch --feed kpdx3_twr      # override the feed ident
uv run squelch --icao KSEA           # override the airport used by the feed picker (`f`)
```

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

## Configuration

squelch reads TOML from `~/.config/squelch/squelch.toml`. Every key is
optional; anything not set (or the whole file, if it doesn't exist) falls
back to the defaults below. Unknown keys in the file are ignored rather
than treated as an error, so an older binary can still read a newer config.
Known keys *are* type-checked at startup: a bad value (say `feed = 3`)
exits immediately with a message naming the file and the key, rather than
failing later inside the audio pipeline.

| Key                 | Default                                                        | Meaning |
|----------------------|----------------------------------------------------------------|---------|
| `icao`               | `"KPDX"`                                                        | Airport used by the feed picker (`f`) to look up feeds on LiveATC.net |
| `feed`               | `"kpdx3_twr"`                                                    | The one feed left unmuted at startup |
| `activity_threshold_dbfs` | `-40.0`                                                    | Level above which a feed counts as busy for the five-minute ranking. Must be written as a decimal (`-40.0`, not `-40`). |
| `compressor_threshold_dbfs` | `-12.0` | Below this, upward compression applies |
| `compressor_ratio` | `4.0` | Upward compression ratio |
| `compressor_makeup_db` | `6.0` | Gain applied to every feed |
| `compressor_range_db` | `12.0` | Maximum upward gain |
| `ambient_gain_db` | `-8.0` | Ambient bus level, relative to the dry bus |

The `model`, `compute_type` and `vad_aggressiveness` keys are gone. An
existing config that still sets them keeps working — unknown keys are
ignored, not rejected.

Example:

```toml
icao = "KSEA"
feed = "ksea_twr"
```

`--feed` and `--icao` on the command line override the config file for that
run.

## Key bindings

| Key     | Action |
|---------|--------|
| `↑` `↓` | Move the selection through the stack. |
| `space` | Mute/unmute the selected feed. Its meter keeps running either way. |
| `S`     | Solo the selected feed — mute every other one. Press again to restore the previous mix. |
| `a`     | Route the selected feed to the ambient bus. |
| `f`     | Open the feed picker and jump to a feed by name. |
| `escape`| (in the feed picker) Close it without choosing anything. |
| `q`     | Quit. |

Every control is also clickable: `[S]`, `[ ON]`/`[OFF]`, and `[A]`. Clicking
anywhere else on a row toggles its mute.

### Feed picker

Pressing `f` lists the feeds LiveATC publishes for the configured airport.
Since squelch already opens all of them, the picker is a jump list rather
than a switch: selecting a row moves the selection to that feed and scrolls
it into view, which is the quick way to a specific frequency. If the list
can't be loaded, a warning appears in the message log instead of a crash.
The fetch runs off the event loop, so a slow or hanging LiveATC request
never stalls playback or the UI.

## Feed discovery and LiveATC's bot protection

LiveATC fronts its airport listing page with Cloudflare bot protection.
Measured against the live site: a browser `User-Agent` does not help,
spacing requests out does not help, and roughly **one request in four is
allowed through anyway**. (The `/play/*.pls` endpoints squelch actually
streams from are not protected, which is why audio works regardless.)

squelch therefore treats a 403 on the listing as a coin flip to re-flip,
not an answer — up to five attempts with backoff — and caches the result
for a week under `~/.cache/squelch/`. A normal launch needs no request at
all. When a refresh is due and every attempt is refused, it falls back to
the cached list (feed lists change on the order of months) and only opens
the single configured feed if there is no cache at all. Each of those
fallbacks says so in the message log.

## Cost

One ffmpeg process, one ring buffer, and one thread per feed — twelve of
each at KPDX — feeding **one** stereo output stream. Bandwidth is trivial at
roughly 16–32 kbps per feed; the CPU is mostly ffmpeg decode plus one
mixing callback every 16 ms. Worth watching on battery.

## Audio shaping

```
ffmpeg ─► ring buffer ─► gate ─► upward comp ─┬─► dry bus (centre) ───────────────┐
                                              │                                   ├─► stereo
                                              └─► ambient bus (−8 dB, panned) ─► reverb ─┘
```

**Upward compression** lifts quiet feeds instead of you riding a gain
control: 4:1 below −12 dBFS with a 6 dB soft knee and +6 dB makeup. Two
limits keep it honest — a **12 dB range limit**, and a **gate** at −40 dBFS
that closes at −46. Without them, 4:1 upward compression boosts a −50 dBFS
noise floor by about 28 dB and hiss becomes the loudest thing in the pane.
The gate attenuates the *boost*, never the signal, and ramps rather than
steps, so a signal hovering at the threshold does not chatter.

**`[A]` routes a feed to the ambient bus**: 8 dB down, panned, and heard
only through a short dark reverb — 100 ms, fully wet, rolled off above
1.2 kHz. Ambient feeds are present without being intelligible, which is the
point. With several on the bus they spread across the stereo field between
50% left and 50% right; an odd number puts one in the centre, phase-inverted
and 6 dB down so it does not pile up in the middle.

The meter shows the level **after** compression — what you actually hear.
The activity ranking measures **before** it, so making a quiet feed louder
does not make it look busier.

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
