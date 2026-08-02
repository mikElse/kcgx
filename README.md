# kcgx

A terminal cockpit for watching and listening to air traffic, named for
Meigs Field — the Chicago lakefront strip that a generation of flight-sim
pilots took off from, bulldozed in the middle of the night in 2003.

Two pieces live here:

- **`squelch`** — an ATC audio player with a live signal meter, built to
  fit a narrow **48 × 42** pane.
- **`kcgx`** — a launcher that arranges `adsb-tui`, `squelch`, and a shell
  into one mouse-resizable tmux session.

```
kcgx          # open the cockpit (or reattach to a running one)
kcgx stop     # shut it down
kcgx --help
```

---

## The cockpit (`kcgx`)

`kcgx` starts a tmux session laid out like this, with every splitter
draggable by mouse:

```
┌────────────────┬───────────┐
│                │  squelch  │
│    adsb-tui    │           │
│                ├───────────┤
│                │  ~ $      │
└────────────────┴───────────┘
```

The right column starts at exactly 48 columns because that is `squelch`'s
design width; below it the header truncates and the level meter loses
resolution. The shell starts short so squelch keeps most of the column.
These are starting positions, not constraints — drag them.

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

**When something dies**, its pane stays visible with its final output and
exit status instead of silently collapsing the layout. `Ctrl-b` then `r`
respawns the pane under the cursor.

`kcgx` refuses to start below 100 columns, where there isn't room for both
a readable traffic table and a 48-column pane.

---

## squelch

A terminal ATC audio player: it streams a LiveATC.net feed, plays it
through your speakers, and shows a scrolling level meter so you can see at
a glance whether the frequency is busy.

Transcription was removed — see "History" at the end.

To run it on its own, outside the cockpit:

```
tmux split-window -h -l 48 'uv run squelch --feed kpdx3_twr'
```

## What it does, and does not, do

- Plays a live LiveATC.net audio feed through your default output device.
- Shows a scrolling level meter — one glyph per recent sample, so a busy
  frequency reads as a waveform and an idle one as a flat line.
- Keeps the header honest about what is actually happening: `STARTING`,
  `LIVE`, `RECONNECTING`, `OFFLINE`.
- Degrades rather than refusing to start: no audio device, an unresolvable
  feed, or a missing `ffmpeg` each produce a message in the pane instead of
  a dead pane or a stack trace.
- Does **not** restart the stream when you pick a different feed from the
  `f` picker in this version — see "Feed picker" below.
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

Startup is immediate — squelch resolves the feed, opens the audio device,
and starts playing. There is no model to download or load.

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
| `feed`               | `"kpdx3_twr"`                                                    | LiveATC feed ident to stream on startup |

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
| `space` | Mute/unmute audio playback. The meter keeps running while muted. |
| `f`     | Open the feed picker for the configured airport (`icao`). |
| `escape`| (in the feed picker) Close it without choosing anything. |
| `q`     | Quit. |

### Feed picker

Pressing `f` fetches the list of feeds LiveATC publishes for the configured
airport and shows them in an overlay. You can navigate and select a row,
but **selecting a feed does not restart the stream in this version** — the
running pipeline keeps listening to whatever URL it originally resolved at
startup. Selecting a row prints the command that would start it, e.g.
`selected ksea_twr — restart with: squelch --feed ksea_twr`. Live feed
switching is intentionally out of scope for v1. If the feed list can't be
loaded (network trouble, or the airport has no feeds LiveATC exposes), a
warning appears in the message log instead of a crash. The fetch runs
off the event loop, so a slow or hanging LiveATC request never stalls
playback or the UI.

## Known limitations

- Selecting a feed in the picker does not restart the stream (see above).
- No transcription (see "History").
- The message log only carries warnings, so the pane is mostly empty at
  rest. Retention is capped at the most recent 200 messages so memory and
  redraw cost stay flat over a multi-hour session.

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
