# audio pane upgrades — batch overview

**Date:** 2026-08-02
**Status:** approved, pending implementation plans

## Summary

A batch of upgrades to `squelch`, the audio pane of the kcgx cockpit, covering
both its user interface and its audio path. The batch is too large for one
spec, so it is decomposed into four, each with its own implementation plan and
build cycle.

## The decomposition

The UI work is an increment on the existing design. The audio work is a
replacement of it.

Today each feed owns its own PortAudio `RawOutputStream` and writes mono,
blocking (`src/squelch/audio.py`). CoreAudio mixing the twelve streams *is* the
entire mixer. Every audio request in this batch — a dry bus and an ambient bus
at a relative gain, per-feed panning, phase inversion, a shared reverb —
requires squelch to do its own mixing: one stereo output stream, per-feed ring
buffers, and a callback that sums the buses. That is a rewrite of the playback
half of `audio.py` plus a new module, not a patch, which is why it is a
separate spec built last.

| Spec | Contents | Depends on |
|------|----------|------------|
| [A — row restructure](2026-08-02-audio-pane-rows-design.md) | Drop the ident, compact/expanded rows tied to audibility, inline clickable control strip, click-to-mute, solo | — |
| [B — activity ranking](2026-08-02-audio-pane-activity-design.md) | 5-minute rolling activity metric, debounced resort, high-FPS expanded meter, VU gradient | A |
| [C — theme sync](2026-08-02-audio-pane-theme-design.md) | Sample the radar pane's live colours, map to six palettes, restyle live | A; supplies B's gradient colours |
| [D — audio engine](2026-08-02-audio-mixer-design.md) | Callback mixer, ring buffers, upward compressor, ambient bus, reverb, panning | independent |

Build order is **A → B → C → D**. A is pure UI and lands fast; B and C make it
look right; D is the one that can fail quietly, so it benefits from a stable UI
to hear it through. D is independent of A–C and could be built in parallel by a
separate effort; its only contact with the UI is the meaning of the `[A]`
control that spec A introduces.

## Constraints inherited by every spec

- The pane is 48 columns wide. Rows carry `padding: 0 1`, leaving 46 content
  cells. There is no reflow past that.
- The pane is nominally 42 rows tall.
- Per-feed failure isolation is the codebase's governing rule: one feed that
  cannot resolve, or whose ffmpeg dies, becomes a dead dot on its own row and
  nothing more. No change in this batch may weaken that.
- squelch runs for hours unattended, so per-minute cost and slow leaks matter.
- Audio thread callbacks reach the UI through `call_from_thread`, so UI work is
  billed to the audio threads. Redraw cost is an audio concern, not just a
  cosmetic one.

## Dependencies added by this batch

`numpy`, by spec D only. Specs A–C add none.

## Decisions taken during design

**DSP is written in Python/NumPy**, not hosted Apple AudioUnits and not a
third-party DSP library. The sources are 16 kHz mono, so the cost is trivial,
and pure block functions over NumPy arrays are testable offline with no audio
device. Hosting AUs via pyobjc would require AVAudioEngine to own the output
device, would be macOS-only, and would be close to untestable.

**Solo mutes all other feeds and restores the prior mute state** when pressed
again. The original request said "unmuting all others"; confirmed as a slip.

**Expansion follows audibility, not selection.** Unmuted feeds are expanded;
muted feeds are compact. See spec A for how the `[ON]`/`[OFF]` control is kept
reachable given this.

**adsb-tui never persists its theme.** Verified empirically: two `t` presses
and a clean quit left `adsb-tui.toml` byte-identical, while the pane background
demonstrably changed from `rgb(14,20,24)` to `rgb(24,18,10)`. Watching the TOML
would therefore observe nothing. Spec C samples the rendered pane instead.

**The upward compressor needs a range limit and a gate**, which the original
request did not specify. Without them, 4:1 upward compression below a −12 dBFS
threshold boosts a −50 dBFS noise floor by roughly 28 dB before makeup gain,
making hiss the loudest thing in the pane. See spec D.

## Out of scope for this batch

- Switching airports at runtime. The launcher work already on this branch
  (`src/kcgx/airports.py`, `src/kcgx/state.py`) addresses the related "feeds are
  discovered once at startup" limitation and is its own effort.
- Recording, saving, or redistributing audio. Unchanged from the original
  design and constrained by LiveATC's terms of use.
- Transcription. Removed previously; not revisited here.
