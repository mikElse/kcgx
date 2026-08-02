# squelch — design

**Date:** 2026-08-02
**Status:** approved, pending implementation plan

## Summary

`squelch` is a terminal application that plays a LiveATC.net air traffic control
audio feed while transcribing it live. It is designed to occupy a narrow side
pane — nominally 48 columns by 42 rows — next to the existing `adsb-tui` and
`radascii` tools in `~/bin`.

## Motivation

No maintained terminal player exists for LiveATC. The available projects are an
archive downloader (`andrewda/liveatc-downloader`), web UIs (`ClearTower`), and
desktop apps (`freqscope`). The practical fallback today is `mpv` on a `.pls`
URL, which plays audio but shows nothing.

The pane earns its screen space by displaying the transcript, not by displaying
a player. Audio alone needs no UI.

## Constraints

- Target pane: 48 columns × 42 rows. Narrower text column than most TUIs assume;
  every layout decision is subordinate to it.
- Runs for hours unattended, so per-minute cost and slow resource leaks matter.
- Runs alongside `adsb-tui` and `radascii`, so it must not monopolise CPU.
- Host is an M1 Max (32 GB unified, 32-core GPU).

## Non-goals for v1

- Transcript logging to disk.
- In-pane search and scrollback.
- Speaker diarization (see "Speaker identification" below).
- Any cross-referencing against `adsb-tui` state.
- Re-streaming or redistributing audio.

## Architecture

A single Python process running three concurrent stages fed by one network
connection:

```
LiveATC .pls → ffmpeg → 16 kHz mono PCM ─┬→ ring buffer → sounddevice (playback)
                                         └→ VAD segmenter → queue → faster-whisper → Textual
```

### One decode, two consumers

Playback and transcription share a single ffmpeg decode. The alternative —
`mpv` for audio plus a second fetch for ASR — doubles bandwidth and allows the
two streams to drift, so displayed text stops corresponding to audible speech.
A single decode keeps them locked to the same sample clock.

16 kHz mono is both Whisper's native input rate and sufficient for a VHF voice
feed already band-limited to roughly 3.5 kHz.

### Segmentation

ATC audio is squelch-gated: hard digital silence between transmissions rather
than continuous room tone. This makes voice activity detection unusually
reliable, and lets the pipeline transcribe whole transmissions as units instead
of Whisper's blind 30-second windows.

This is the largest single quality lever in the pipeline. It is also why
transcript blocks correspond to real radio calls.

WebRTC VAD (via the `webrtcvad-wheels` fork, which ships prebuilt binaries) is
sufficient and costs almost no CPU. A neural VAD such as Silero would be the
choice for continuous conversational audio, but squelch-gated transmissions make
the discrimination easy enough that the extra model is not justified.

Segmenter behaviour:

- Frame the PCM at the VAD's native frame size.
- Open an utterance on speech onset.
- Close it after a silence hangover, so a speaker pausing mid-clearance does
  not split into two blocks.
- Guard with a minimum duration (reject squelch clicks) and a maximum duration
  (force-flush a stuck-open transmission).

### Transcription

`faster-whisper` (CTranslate2) with the published ATC-fine-tuned model
`jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper`.

Chosen over `whisper.cpp` + Metal because the fine-tuned weights ship in
CTranslate2 format already. The whisper.cpp path would require converting
fine-tuned HF weights to ggml, which is documented as unreliable, and would add
subprocess plumbing per audio segment. CTranslate2 has no Metal backend, so
inference runs on CPU cores; for short ATC bursts on an M1 Max this is
approximately realtime, which is sufficient given LiveATC's own 15–30 second
buffering delay.

Vanilla Whisper is not adequate here. ATC audio combines clipped VHF bandwidth,
heavy accent variety, rapid alphanumeric callsigns, and constant noise —
conditions under which stock models produce fluent, confident, wrong text. The
fine-tuned model is materially better on callsigns and standard phraseology.

Inference runs on a single worker thread so it cannot starve playback.

### Speaker identification

Not attempted. A LiveATC feed is a single mixed channel from one ground
receiver; controller and aircraft transmissions arrive on the same audio with no
distinguishing metadata. Labelling them would require either an SNR heuristic
(frequently wrong) or a second continuously-running diarization model
(disproportionate cost).

Transcript blocks are therefore timestamp plus text. Phraseology makes the
speaker obvious in practice — an instruction reads differently from a readback.

## Components

| Module | Responsibility |
|---|---|
| `feeds.py` | Resolve ICAO to feed list; parse `.pls` to stream URL |
| `audio.py` | ffmpeg lifecycle, PCM pump, playback, reconnect and backoff |
| `vad.py` | PCM frames to discrete utterances |
| `asr.py` | faster-whisper wrapper, model load and cache, `Transcriber` protocol |
| `app.py` | Textual app: layout, feed-picker overlay, key bindings |
| `config.py` | TOML config at `~/.config/squelch/squelch.toml` |

Boundaries are drawn so that `vad.py` accepts bytes and returns spans, and
`feeds.py` accepts HTML and returns feed records. Neither imports Textual. The
UI layer consumes an `Utterance(timestamp, text)` stream and knows nothing about
ffmpeg or model internals.

## Layout

48 columns, transcript-dominant. The transcript region expands to fill available
height; all other regions are fixed.

```
┌─ KPDX TWR ────────────────────────── ● LIVE ─┐
│ 118.10  Portland Tower                       │
│ ▂▄▆█▆▄▂▁▁▂▄▆▅▃▁▁▁▁▂▁  -18dB   14:32:07       │
├─ TRANSCRIPT ─────────────────────────────────┤
│                                              │
│ 14:31:42                                     │
│   Alaska 412 heavy, wind two eight zero      │
│   at one two, runway two eight left,         │
│   cleared to land.                           │
│                                              │
│ 14:31:51                                     │
│   Cleared to land two eight left,            │
│   Alaska 412 heavy.                          │
│                                              │
│ 14:32:03                                     │
│   Horizon 2451, line up and wait             │
│   two eight right.                           │
│                                              │
│ 14:32:07  ░ transcribing…                    │
│                                              │
├──────────────────────────────────────────────┤
│ [space] mute  [f] feeds  [q] quit            │
└──────────────────────────────────────────────┘
```

Header shows the selected feed and connection state. The meter row shows a live
level bar, current dB, and wall clock. The in-progress utterance appears as a
placeholder block so the pane does not look frozen while inference runs.

### Key bindings

- `space` — mute playback. Transcription continues.
- `f` — open feed picker overlay.
- `q` — quit.

## Feed selection

`f` opens a searchable overlay listing feeds for a configured ICAO, scraped from
LiveATC's airport page, so switching from Tower to Ground does not require
editing config. The config file supplies the default ICAO and feed, plus
audio device and model preferences.

## Error handling

Feed dropouts are routine rather than exceptional, so reconnection is part of
the main loop:

- ffmpeg exit or stall watchdog triggers exponential backoff, 1 s doubling to a
  30 s cap, with the header showing `⟳ RECONNECTING`. The pane never silently
  freezes.
- ASR queue backpressure drops the oldest pending segment and marks the gap
  visibly in the transcript. Stale text must never be presented as live.
- Model load failure degrades to audio-only with a persistent banner rather than
  refusing to start.
- Missing or unavailable audio output device degrades to transcribe-only.

## Testing

Fixture-driven; no live network access in tests.

- `feeds.py` — saved `.pls` files and airport-page HTML.
- `vad.py` — synthetic PCM of tone bursts and silence with known boundaries;
  assert utterance spans, hangover merging, and min/max duration guards.
- `asr.py` — short recorded ATC clip for a smoke test; mocked elsewhere.
- `app.py` — Textual pilot snapshot at exactly 48×42, asserting no overflow or
  unintended wrapping. The width constraint is the premise of the project, so it
  is covered by an explicit test.
- Reconnect logic — simulated ffmpeg failure, assert backoff schedule and
  header state transitions.

## Dependencies

- Python, managed with `uv` and `pyproject.toml`.
- `textual` — TUI framework.
- `faster-whisper` — ASR.
- `sounddevice` — PortAudio playback.
- `webrtcvad-wheels` — voice activity detection.
- `ffmpeg` — external binary, already present on the host.

First run downloads roughly 1.5 GB of model weights.

## Legal

LiveATC's terms permit personal listening but not redistribution. `squelch`
plays locally and does not re-stream, record, or republish audio.
