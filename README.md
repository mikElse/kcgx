# squelch

A terminal ATC audio player: it streams a LiveATC.net feed, plays it through
your speakers, and shows a live speech-to-text transcript alongside it. The
whole UI is built to fit in a fixed **48 columns × 42 rows**, so it can sit
as a narrow side pane next to something else in a terminal multiplexer —
an ADS-B radar TUI such as `adsb-tui` or `radascii`, for example, showing
you the traffic on radar while you listen to the tower talk to it.

```
tmux split-window -h -l 48 'uv run squelch --feed kpdx3_twr'
```

## What it does, and does not, do

- Plays a live LiveATC.net audio feed through your default output device.
- Runs the same audio through an ATC-tuned Whisper model
  ([`jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper`](https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper))
  and renders each recognized transmission as a timestamped block of text.
- Degrades gracefully rather than refusing to start: if the model can't be
  loaded, audio still plays (silently, with a warning); if no audio output
  device is available, transcription still runs.
- Does **not** restart the stream when you pick a different feed from the
  `f` picker in this version — see "Feed picker" below.
- Does **not** log transcripts to disk, offer in-pane search/scrollback, or
  label speakers (a LiveATC feed is one mixed channel; there is no reliable
  way to attribute a transmission to an aircraft or the tower).
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

**First run downloads the ASR model** (roughly 1.5 GB of CTranslate2
weights) before transcription starts; this can take several minutes on a
slow connection. Audio playback does not wait on this — if you want to
listen immediately, ignore the transcript pane until it fills in. Inference
itself runs on CPU (CTranslate2 has no Metal backend), so expect a few
seconds of lag between a transmission ending and its transcript appearing.

If you resize your terminal, note the UI is laid out for exactly 48×42 and
does not reflow past that.

## Configuration

squelch reads TOML from `~/.config/squelch/squelch.toml`. Every key is
optional; anything not set (or the whole file, if it doesn't exist) falls
back to the defaults below. Unknown keys in the file are ignored rather
than treated as an error, so an older binary can still read a newer config.

| Key                 | Default                                                        | Meaning |
|----------------------|----------------------------------------------------------------|---------|
| `icao`               | `"KPDX"`                                                        | Airport used by the feed picker (`f`) to look up feeds on LiveATC.net |
| `feed`               | `"kpdx3_twr"`                                                    | LiveATC feed ident to stream on startup |
| `model`              | `"jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper"`  | Hugging Face model ID for transcription |
| `compute_type`       | `"int8"`                                                         | CTranslate2 compute type (passed to `faster-whisper`) |
| `vad_aggressiveness` | `2`                                                              | WebRTC VAD aggressiveness, `0`–`3`; higher trims more non-speech |

Example:

```toml
icao = "KSEA"
feed = "ksea_twr"
vad_aggressiveness = 3
```

`--feed` and `--icao` on the command line override the config file for that
run.

## Key bindings

| Key     | Action |
|---------|--------|
| `space` | Mute/unmute audio playback. Transcription keeps running while muted. |
| `f`     | Open the feed picker for the configured airport (`icao`). |
| `escape`| (in the feed picker) Close it without choosing anything. |
| `q`     | Quit. |

### Feed picker

Pressing `f` fetches the list of feeds LiveATC publishes for the configured
airport and shows them in an overlay. You can navigate and select a row,
but **selecting a feed does not restart the stream in this version** — the
selection hook fires, but the running pipeline keeps listening to whatever
URL it originally resolved at startup. Live feed switching is intentionally
out of scope for v1; use `--feed` (or the config file) and restart squelch
to change feeds. If the feed list can't be loaded (network trouble, or the
airport has no feeds LiveATC exposes), a warning appears in the transcript
pane instead of a crash.

## Known limitations

- Selecting a feed in the picker does not restart the stream (see above).
- No transcript logging to disk, no in-pane search or scrollback.
- No speaker labelling.
- Inference is CPU-bound; there is no Metal/GPU acceleration path today.
