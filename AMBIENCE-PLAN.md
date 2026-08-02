# Audio Pane E — Tower Room Tone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Play a local ambience bed — the sound of the room you are listening *from* — underneath the live feeds. Eight looping and randomly-triggered stems, mixed by squelch at runtime, ducking out of the way when anybody transmits.

**Architecture:** The stems ship in the package. At startup a worker thread decodes them through ffmpeg to 16 kHz mono float32 and hands them to a `Bed`, which owns one voice per stem. The mixer's callback pulls one stereo block from the bed per cycle and sums it into the master after the dry and ambient buses. The bed is pure NumPy over preallocated buffers, so all of it is tested with no audio device and no network.

**Tech Stack:** Python 3.14, NumPy, `sounddevice` 0.5.5 in callback mode, ffmpeg (already a hard runtime dependency), pytest 9.1.1.

**Spec:** none written — this document carries the design. If it grows past one feature, split it into `docs/superpowers/specs/` per the convention in `docs/README.md`.

**Depends on:** **plan D (the mixing engine).** See "Why this comes after D" below.

---

## Why this is worth building

squelch already tells you what the field sounds like. It does not tell you where you are sitting while you listen. A tower cab has a floor: fluorescent hum, a server rack, a slow fan, a clock, and jets going over at intervals. With that bed under the feeds, a quiet airport stops sounding like a broken app and starts sounding like 3 a.m. at a quiet field — which is the actual experience being reproduced.

It is also the cheapest possible use of the engine plan D builds. The bed is eight more sources into a mixer that already sums twelve.

## Why this comes after D

The bed could be built today against the current `Player`, and that would be a trap:

- It would open a **thirteenth** PortAudio output stream, on a codebase whose whole D-phase premise is that independent streams cannot be mixed against each other. There would be no defined gain relationship between the bed and the feeds — the one thing a bed must have.
- Ducking (below) needs to read the feeds' post-gate envelopes. That signal only exists inside D's callback.
- Panning the stems needs D's `dsp.Panner` and its equal-power law. Writing a second one is how two pan laws end up in one binary.
- D **deletes `Player`**. Anything built on it now gets rewritten in a fortnight.

If you want the bed before D lands, do not build this plan — render a fixed stereo file offline (`tools/` can grow a `render_ambience.py`) and play it on one extra stream as a stopgap. That is a different, throwaway piece of work, and it is not what this plan describes.

## Signal chain

```
                                    ┌─ loop voices  ─┐
assets/audio/*.mp3 ─► decode ─► bed ┤                ├─► pan ─► bed gain ─► duck ─┐
   (once, at startup)               └─ random voices ┘                            │
                                                                                  ▼
feeds ─► gate ─► comp ─┬─► dry bus ──────────────────────────────────────────► master ─► stereo out
                       └─► ambient bus ─► reverb ─────────────────────────────►
```

The bed is **not** a feed. It does not pass through the gate, the upward compressor, or the ambient reverb:

- It is already mixed and level-set; compressing it would pump against the feeds and lift its own noise floor, which is exactly the failure D's range limit exists to prevent.
- The ambient reverb is 100 % wet and models *distance*. The bed is the near field. Running it through would put the room you are in further away than the radios.

## Ducking

The bed sits at **−18 dB**. When any feed on the dry bus is transmitting, it drops a further **−6 dB**, ramped over the compressor's release constant (150 ms), and returns when the field goes quiet.

This is the one behaviour that makes a bed usable rather than merely present. Without it, room tone competes with the voices you are running the app to hear. "Transmitting" reuses D's per-feed gate state — no second detector, no new threshold to tune.

## Random voices

Two stems (`Distant Jet 1`, `Distant Jet 2`) are marked `mode: "random"` in the manifest, at 112 and 33 events per hour. Fire them as a **Poisson process** — exponentially distributed inter-arrival times — not on a fixed grid. A grid at 112/hr is a metronome, and a metronome is the one thing ambience must never be.

Interval for rate `r` per hour: `-ln(U) × 3600 / r` seconds, `U` uniform in (0, 1].

The generator takes an injected `random.Random`, so tests seed it and assert the realised rate over a long horizon.

At 112/hr with a 32 s clip, events overlap constantly — expected concurrency is ~1. A random voice must therefore support **multiple simultaneous playheads**, not one. Cap the concurrent count (8 is far above anything the rates produce) so a pathological manifest cannot allocate without bound.

## The assets

Committed at `src/squelch/assets/audio/`, regenerated by `tools/fetch_ambience.py` (verified byte-identical on re-run):

| File | Length | Gain | Balance | Mode |
|---|---|---|---|---|
| `1-ticking-clock.mp3` | 19.4 s | 0.08 | 0 | loop |
| `2-neon-lights-hum.mp3` | 5.4 s | 1.00 | 0 | loop |
| `3-distant-jet-3.mp3` | 28.4 s | 0.24 | 0 | loop |
| `4-server-room-computer-lab.mp3` | 45.1 s | 1.00 | 0 | loop |
| `5-water-pump-engine.mp3` | 3.9 s | 0.03 | 0 | loop |
| `6-huge-slow-metal-fan.mp3` | 56.9 s | 0.17 | +0.10 | loop |
| `7-distant-jet-2.mp3` | 26.4 s | 0.55 | −0.23 | random, 33/hr |
| `8-distant-jet-1.mp3` | 32.1 s | 0.52 | +0.18 | random, 112/hr |

`ambience.json` carries these values plus provenance (ambient-mixer template 444055), a top-level `license` object, and a `credit` string per channel. It is the interface between the asset directory and the code — nothing in `src/` hard-codes a filename, a gain, a rate, or a credit.

Human-readable provenance, and the licence questions that are still open, live in `src/squelch/assets/audio/ATTRIBUTION.md`.

3.3 MB on disk, ~7 MB resident once decoded to float32. Both are acceptable; neither is worth a lazy-loading scheme.

**Two known facts about the source mix**, recorded so they are not rediscovered as bugs:

1. `Distant Jet 3` has a random *counter* of 2/hr but its random flag off, so it loops continuously. The manifest reports it as `loop`, which is what the site actually plays. If the intent was two flyovers an hour, fix it in the mixer UI and re-run the fetch tool — do not special-case it in code.
2. Rendered flat, the mix measures −28 LUFS. That is faithful to the fader positions and quiet by design: it is a floor, not a programme. The −18 dB bed gain is applied *on top* of that, and is the knob to turn if it needs to sit higher.

## Global Constraints

- Sample rate **16 kHz**, block size **256 samples**, **2 channels**, `float32`. Same as D.
- **The callback is a real-time context.** `Bed.mix_into()` is called from it: no allocation, no locks, no logging, no raising. Every buffer preallocated; NumPy ops use `out=`.
- **Decoding happens off the callback thread, before the bed goes live.** A bed that is still loading contributes silence.
- **A missing, unreadable, or undecodable asset disables the bed and warns once.** It must never take down a feed. This is the same isolation rule the sessions already follow.
- `ambience.py` **must not import `textual`**.
- No test may open an audio device, spawn ffmpeg, or hit the network. The decoder is injected.
- Run tests with `uv run pytest`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/squelch/assets/audio/` | **Done.** Eight stems + `ambience.json` |
| `tools/fetch_ambience.py` | **Done.** Regenerates the above from the template |
| `src/squelch/ambience.py` | **New.** Manifest loading, decode, voices, `Bed` |
| `src/squelch/mixer.py` | Holds the bed; sums it into the master; exposes the duck signal |
| `src/squelch/config.py` | `ambience`, `ambience_gain_db`, `ambience_duck_db` |
| `src/squelch/app.py` | `[b]` toggle, footer, one warning path |
| `src/squelch/__main__.py` | Builds the bed, starts the decode thread |
| `tests/test_ambience.py` | **New.** |
| `tests/test_mixer.py`, `tests/test_config.py`, `tests/test_app.py` | Extended |

---

### Task 1: Load and validate the manifest

**Files:** Create `src/squelch/ambience.py`, `tests/test_ambience.py`

**Interfaces:** Produces `Stem` (frozen dataclass: `file`, `name`, `duration_s`, `gain`, `balance`, `mode`, `rate_per_hour`) and `load_manifest(path: Path | None = None) -> list[Stem]`.

- [ ] **Step 1: Write the failing tests.** Cover: the shipped manifest loads and yields eight stems; gains land in 0..1 and balances in −1..1; a `random` stem has a positive `rate_per_hour` and a `loop` stem has `None`; a manifest naming a file that does not exist raises `AmbienceError`; a malformed manifest raises `AmbienceError` rather than `KeyError` or `JSONDecodeError`.

- [ ] **Step 2: Implement.** Resolve paths relative to the manifest, not the CWD. Follow `config.py`'s precedent — validate at load time, where the message can name the file and the key, because a bad value that first surfaces inside the audio callback dies in silence.

- [ ] **Step 3: Verify.** `uv run pytest tests/test_ambience.py`

---

### Task 2: Decode stems to PCM

**Files:** Modify `src/squelch/ambience.py`, `tests/test_ambience.py`

**Interfaces:** Produces `decode_command(path) -> list[str]` and `decode(stem, *, run=subprocess.run) -> np.ndarray` (mono float32 in −1..1 at 16 kHz).

- [ ] **Step 1: Write the failing tests.** With an injected fake runner returning known s16le bytes: output is float32, mono, scaled to −1..1, and length matches the byte count. A runner that fails, or returns empty stdout, raises `AmbienceError` naming the file. Assert `decode_command` requests exactly `-ac 1 -ar 16000 -f s16le`.

- [ ] **Step 2: Implement.** Mirror `audio.ffmpeg_command`'s shape and flags. Downmixing to mono is deliberate: the stems' own stereo image is discarded in favour of the manifest's balance, so the bed is placed by one mechanism (Task 4) rather than two that disagree. 16 kHz also throws away everything above 8 kHz, which for room tone is inaudible and for a bed sitting under 16 kHz voice traffic is correct.

- [ ] **Step 3: Verify.** `uv run pytest tests/test_ambience.py`

---

### Task 3: Loop and random voices

**Files:** Modify `src/squelch/ambience.py`, `tests/test_ambience.py`

**Interfaces:** Produces `LoopVoice(pcm)` and `RandomVoice(pcm, rate_per_hour, rng, max_concurrent=8)`, both with `mix_into(out: np.ndarray, gain: float) -> None` where `out` is one mono block, accumulated into.

- [ ] **Step 1: Write the failing tests.**
  - A loop voice returns the clip, then wraps: reading `len(pcm) + 100` samples in blocks yields the head of the clip again, with **no gap and no discontinuity** at the seam.
  - A loop voice whose clip is shorter than one block still fills the block (the 3.9 s pump is fine, but do not assume clip > block).
  - A random voice with a seeded rng fires ~`rate` events per simulated hour, within a tolerance the test states (a chi-square-free assertion: `0.7 × rate < n < 1.3 × rate` over one hour at 112/hr).
  - Inter-arrival times are not constant — assert the realised set has non-zero variance, which is the whole point of Poisson over a grid.
  - Overlapping events sum: two playheads scheduled 1 block apart both contribute.
  - Concurrency is capped: a rate high enough to exceed `max_concurrent` drops new events rather than growing the playhead list.
  - `mix_into` **accumulates** — it never zeroes `out`.

- [ ] **Step 2: Implement.** Both voices are pure index arithmetic over a preallocated PCM array; no allocation in `mix_into`.

- [ ] **Step 3: Verify.** `uv run pytest tests/test_ambience.py`

---

### Task 4: The bed — panning and summing

**Files:** Modify `src/squelch/ambience.py`, `tests/test_ambience.py`

**Interfaces:** Produces `Bed(stems, pcm_by_file, *, gain_db=-18.0, rng=...)` with `mix_into(out: np.ndarray) -> None` (`out` is `(block, 2)` float32), `enabled: bool`, and `duck(amount_db: float) -> None`.

- [ ] **Step 1: Write the failing tests.**
  - Each stem's manifest `balance` maps through **D's `dsp.Panner` law** to L/R gains — import it, do not reimplement it. A balance of 0 is equal in both channels; +0.10 favours R; −0.23 favours L.
  - Bed output equals the analytically-computed sum of its voices at their gains, for a two-stem synthetic bed.
  - `gain_db` scales the whole bed; `-18.0` yields the expected linear factor.
  - `enabled = False` contributes exact silence and advances no playhead — a disabled bed must not quietly drift, or re-enabling would jump.
  - `mix_into` accumulates into `out` rather than overwriting it.
  - **No allocation:** `tracemalloc` delta across 100 `mix_into` calls is zero. (D establishes this pattern; reuse its helper.)

- [ ] **Step 2: Implement.** Preallocate the mono scratch block and the stereo staging buffer at construction.

- [ ] **Step 3: Verify.** `uv run pytest tests/test_ambience.py`

---

### Task 5: Ducking

**Files:** Modify `src/squelch/ambience.py`, `tests/test_ambience.py`

**Interfaces:** `Bed.set_duck(active: bool)`; internal ramp on the 150 ms release constant.

- [ ] **Step 1: Write the failing tests.** A duck engaging drops the bed by exactly `duck_db` **after** the ramp completes, not on the first block. The ramp is monotonic and continuous — assert no block-to-block step exceeds a stated bound, since a stepped duck is an audible click and is the entire failure mode here. Ducking and un-ducking repeatedly at the block rate does not chatter (the ramp, not the flag, sets the pace). `duck_db = 0` is a no-op.

- [ ] **Step 2: Implement.** Reuse D's coefficient helper for the time constant rather than writing a second one.

- [ ] **Step 3: Verify.** `uv run pytest tests/test_ambience.py`

---

### Task 6: Wire the bed into the mixer

**Files:** Modify `src/squelch/mixer.py`, `tests/test_mixer.py`

**Interfaces:** `Mixer(..., bed=None)`; the callback calls `bed.mix_into(master)` after the buses are summed, and `bed.set_duck(any_gate_open)` before it.

- [ ] **Step 1: Write the failing tests.** With synthetic feeds and a stub bed: the bed's contribution appears in the output block; it is summed **after** the ambient reverb, so no reverb tail is applied to it; a feed above its gate threshold sets the duck and a silent field clears it; `bed=None` produces byte-identical output to D's mixer without a bed (a regression fence — the bed must be genuinely optional); a bed whose `mix_into` raises yields a block of silence from the mixer, not a propagated exception, exactly as D specifies for a chain that raises.

- [ ] **Step 2: Implement.**

- [ ] **Step 3: Verify.** `uv run pytest tests/test_mixer.py`

---

### Task 7: Config

**Files:** Modify `src/squelch/config.py`, `tests/test_config.py`

**Interfaces:** `ambience: bool = True`, `ambience_gain_db: float = -18.0`, `ambience_duck_db: float = -6.0`.

- [ ] **Step 1: Write the failing tests.** Defaults are as above; each key round-trips from TOML; a non-numeric `ambience_gain_db` raises `ConfigError` naming the file and key.

  **Include a test for `ambience_gain_db = -18`** — written without a decimal point, TOML parses that as `int`, and `_checked` compares against `type(field.default)`, which is `float`. Today that raises `ConfigError` on a value any user would consider valid. Fix `_checked` to accept an `int` where a `float` is expected (while still rejecting `bool`, which is an `int` subclass and is already special-cased there), and assert both spellings load.

- [ ] **Step 2: Implement.**

- [ ] **Step 3: Verify.** `uv run pytest tests/test_config.py`

---

### Task 8: UI — the `[b]` toggle

**Files:** Modify `src/squelch/app.py`, `tests/test_app.py`

- [ ] **Step 1: Write the failing tests.** `b` toggles `bed.enabled`; the footer reflects the state; `b` with no bed present is a no-op and does not raise; a bed that failed to load produces exactly **one** warning in the message log, no matter how many times `b` is pressed.

- [ ] **Step 2: Implement.**

  **The footer has no room.** The current string is 47 columns against a 48-column budget:

  ```
   [↑↓] select  [space] mute  [f] feeds  [q] quit
  ```

  Adding `[b] bed` needs 9 more. Shorten first — `[space] mute` → `[spc] mute` and single-spacing the separators buys the room. Whatever you choose, add a test asserting the rendered footer is `<= 48` columns, so the next binding hits a failing test instead of a clipped pane.

- [ ] **Step 3: Verify.** `uv run pytest tests/test_app.py`

---

### Task 9: Startup wiring

**Files:** Modify `src/squelch/__main__.py`, `tests/test_main.py`

- [ ] **Step 1: Write the failing tests.** With an injected decoder: the bed is constructed and handed to the mixer; decoding happens on a **worker thread**, so `main()` does not block on it; the bed is silent until decode completes; a decoder that raises leaves every feed running and yields one warning; `ambience = false` in config skips decode entirely — assert the decoder is never called, since the cost this avoids is the entire point of the flag.

- [ ] **Step 2: Implement.** Follow the existing `pending`-warnings pattern: a decode that fails before the app is running has nowhere to report to yet, so its warning is queued and replayed from `on_start`.

- [ ] **Step 3: Verify.** `uv run pytest`

---

### Task 10: Attribution plumbing and docs

Attribution is **already captured** — the credits and licence are in `ambience.json`, and `ATTRIBUTION.md` records them alongside the open licence questions. This task only keeps them from being silently dropped.

**Files:** Modify `src/squelch/ambience.py`, `tests/test_ambience.py`, `README.md`, `docs/README.md`

- [ ] **Step 1: Write the failing tests.** `Stem` carries `credit`; `load_manifest` exposes the top-level `license` (name and url); a manifest with a stem missing its `credit`, or with no `license`, raises `AmbienceError`. That last one is the point of the task: an asset whose provenance has gone missing must fail loudly at load, not ship silently.

- [ ] **Step 2: Implement.** Parse and expose only — nothing renders yet (see "Deferred: the info modal").

- [ ] **Step 3: Document.** A short README section: what the bed is, `[b]`, the three config keys, where the credits live, and how to swap in a different ambient-mixer template by editing the URL in `tools/fetch_ambience.py` and re-running it.

- [ ] **Step 4: Index.** Add this plan to the table in `docs/README.md` — and if it is still living at the repo root, move it to `docs/superpowers/plans/` first, so there is one place plans live.

---

## Deferred: the info / settings modal

Displaying attribution in-app is a **later iteration**, not part of this plan. It is noted here because the data contract it needs is being fixed now, and getting that wrong is the only part that is expensive to change later.

What a future modal can rely on, once Task 10 lands:

- `load_manifest()` returns stems each carrying `name`, `credit`, `duration_s`, `gain`, `balance`, `mode`, and `rate_per_hour`, plus a `license` with `name` and `url`. Everything needed to render a credits screen is already structured — no scraping, no parsing, no hard-coded strings in the UI.
- `ATTRIBUTION.md` is the long-form version and is **not** what the modal should render. It is a maintainer document; it carries unresolved licence questions that do not belong on a user's screen.
- The pane is 48 columns. `Server Room \ Computer Lab by BugInTheSYS from http://freesound.org` is 64 and will need wrapping or truncation — `app._fit` already exists for the latter, and `FeedPicker` is the working precedent for a `ModalScreen` sized to this budget.
- Credits are third-party text from a scraped page. Render them with `markup=False`, as every other externally-sourced string in `app.py` already is.

The same modal is the natural home for the settings that Task 7 puts in config — bed on/off, bed gain, duck depth — which is why it is worth building as one screen rather than a credits box.

---

## Manual verification

One step needs hardware and closes out the feature: run against a live airport with the bed on, confirm the room tone sits *under* the traffic rather than beside it, that a transmission ducks it audibly without pumping, and that flyovers arrive at irregular intervals rather than on a beat.

## Out of scope

- The info / settings modal — deferred to a later iteration, see above.
- Per-stem faders in the UI. The manifest is the mix; edit it on ambient-mixer.com and re-run the fetch tool.
- Multiple selectable beds. Worth doing once there is a second one; the manifest already has the shape for it.
- Streaming the bed from ambient-mixer.com at runtime. There is no stream to fetch — the site's player downloads these same eight files and mixes them client-side, which is precisely what this plan does locally, minus the network dependency.
