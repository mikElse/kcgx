# audio pane D — the mixing engine

**Date:** 2026-08-02
**Status:** approved, pending implementation plan
**Batch:** [audio pane upgrades](2026-08-02-audio-pane-upgrades-design.md)
**Depends on:** nothing. Reads the `ambient` flag introduced by
[spec A](2026-08-02-audio-pane-rows-design.md).

## Summary

Replace twelve independent mono output streams with one stereo mixing engine:
per-feed ring buffers, upward compression, a dry bus and a panned ambient bus,
and a shared reverb on the ambient sum.

## Motivation

Two things are wanted from the audio path. Quiet feeds should be as audible as
loud ones without riding a gain control, and feeds you are not focused on should
be *present* without being distracting — audible as a room rather than as a
voice.

Neither is reachable from the current architecture. Today each feed owns a
`sounddevice.RawOutputStream` and writes mono, blocking; CoreAudio mixing those
twelve streams is the entire mixer. A relative bus gain, coordinated panning,
and a *shared* reverb all require squelch to do its own summing.

## The clock problem

Twelve ffmpeg processes decode twelve independent network streams. They share no
clock: each delivers frames at its own slightly-wrong rate, and each drops out
and reconnects independently.

Today this is invisible, because each feed blocks on its own device write and
CoreAudio resamples each stream separately. The moment they are summed into one
bus, twelve drifting producers must be reconciled against one 16 kHz consumer.

The engine handles this with a **ring buffer per feed**. Each feed's existing
thread writes decoded frames into its own buffer; the callback pulls one block
from each. A starved buffer contributes silence for that block; an overfull one
drops its oldest block. Drift becomes a bounded, per-feed, inaudible correction
rather than a global failure — and, critically, it keeps the codebase's
per-feed isolation rule intact: a dead feed is a silent ring buffer, exactly as
it is a dead dot today.

This also removes the backpressure that the blocking write currently provides.
The reader thread will now run at network pace rather than device pace, which is
correct for a live stream, and the drop-oldest policy bounds the damage when a
reconnecting ffmpeg bursts.

## Signal chain

```
ffmpeg ─► ring buffer ─► gate ─► upward comp ─┬─► dry bus (0 dB, centre) ─────────────────┐
        (per feed)                            │                                           ├─► stereo out
                                              └─► ambient bus (−8 dB, panned) ─► reverb ──┘
```

Per feed, per block: gate → upward compressor → route to whichever bus its
`[ON]` / `[A]` state selects. A feed may be on the dry bus, the ambient bus, or
neither.

The ambient sum passes through **one shared reverb**, not one per feed. That is
what makes it a bus.

## Upward compressor

Applied per feed, pre-bus.

| parameter | default |
|-----------|---------|
| threshold | −12 dBFS |
| ratio | 4:1 |
| knee | 6 dB (soft, quadratic) |
| makeup gain | +6 dB |
| range limit | 12 dB |
| gate threshold | −40 dBFS |
| attack | 5 ms |
| release | 150 ms |

Gain for an envelope level `L` below threshold `T`:

```
gain_dB = min(range_limit, (T − L) × (1 − 1/ratio))
```

### Why the range limit and gate exist

They were not in the original request and are not optional. ATC feeds sit on a
constant noise floor around −50 dBFS. Unbounded, 4:1 upward compression below
−12 dBFS boosts that floor by `(−12 − −50) × 0.75` ≈ **28 dB**, before the +6 dB
makeup. Hiss would become the loudest thing in the pane and the ambient bus a
wall of static.

The 12 dB range limit caps upward gain, which saturates at −28 dBFS input and
below. The −40 dBFS gate stops silence being boosted at all.

### Gate smoothing

A hard gate at −40 dBFS would step between 0 dB and +12 dB of upward gain at the
threshold, chattering audibly on any signal hovering there — which is exactly
what a squelch tail does.

The gate therefore produces a smoothed 0..1 multiplier on the *upward gain*,
with hysteresis (opens at −40 dBFS, closes at −46 dBFS) and ramped with the
release time constant. Gain glides; it never steps. The gate attenuates the
boost, never the signal itself, so a gated feed is quiet rather than absent.

## Ambient bus

**Relative gain.** −8 dB against the dry bus.

**Reverb.** 100 ms RT60, 100% wet, one-pole low-pass at 1.2 kHz in the feedback
path, stereo width from decorrelated delay-line lengths per channel. A Schroeder
topology — four parallel combs into two series allpasses — is sufficient at this
decay length and rate; an FDN buys nothing for a 100 ms tail.

At 16 kHz, RT60 = 100 ms is 1600 samples, so comb feedback is
`g = 10^(−3D/1600)` for a delay of `D` samples. The low-pass coefficient is
`a = exp(−2π × 1200 / 16000) ≈ 0.624`.

100% wet means ambient feeds are heard *only* as reverb — no direct signal at
all. Combined with the 1.2 kHz roll-off and the short tail, the result is dark,
diffuse, and not intelligible as speech. That is the intent: presence without
attention.

**Panning.** For `N` ambient feeds, positions spread symmetrically across ±0.5:

```
±i × 0.5 / ⌊N/2⌋    for i = 1..⌊N/2⌋
```

plus a centre position when `N` is odd. This reproduces the specified N=4 case
of 50%L, 25%L, 25%R, 50%R.

When `N` is 1, `⌊N/2⌋` is 0 and the range `1..0` is empty, so the expression is
never evaluated and the single feed takes the centre position. The
implementation must guard the division rather than relying on that reading.

| N | positions |
|---|-----------|
| 1 | centre |
| 2 | ±0.5 |
| 3 | ±0.5, centre |
| 4 | ±0.25, ±0.5 |
| 5 | ±0.25, ±0.5, centre |
| 6 | ±0.167, ±0.333, ±0.5 |

The centre feed is **phase-inverted and attenuated 6 dB**, as specified.

Equal-power (−3 dB) pan law: `L = cos θ`, `R = sin θ` with
`θ = (pos + 1) × π/4`.

Positions are assigned in feed discovery order among the ambient feeds, so the
assignment is deterministic. Toggling `[A]` on any feed changes `N` and
therefore reassigns positions; the new gains are crossfaded over one block to
avoid a click.

## Real-time discipline

The callback is a real-time context. It must not allocate, take a lock, log, or
raise.

- All scratch buffers are preallocated at construction, sized for the maximum
  feed count and block size. NumPy operations use `out=` parameters throughout.
- Mute, solo, and `[A]` state are plain attribute reads. Under CPython these are
  atomic and need no synchronisation; a state change taking effect one block
  late is inaudible and acceptable.
- The callback wraps its body so that any unexpected exception yields a block of
  silence rather than propagating into PortAudio.

**Parameters.** 16 kHz, 2 channels, `float32` internally, 512-sample blocks
(32 ms). Ring buffers hold 500 ms (8000 samples) per feed.

## Components

- `src/squelch/dsp.py` — new. Compressor, gate, reverb, panner. Pure functions
  and small stateful classes over NumPy arrays. No audio device, no threads.
- `src/squelch/ringbuffer.py` — new. Single-producer single-consumer ring
  buffer with drop-oldest overflow.
- `src/squelch/mixer.py` — new. Owns the output stream and the callback; holds
  the per-feed chain and the two buses.
- `src/squelch/audio.py` — `Player` is replaced. `StreamReader` is unchanged;
  it now writes frames to a ring buffer instead of a device.
- `src/squelch/session.py` — a session no longer owns a player; it owns a ring
  buffer and registers with the mixer.
- `src/squelch/config.py` — compressor, ambient gain, and reverb parameters,
  all defaulting as above.
- `pyproject.toml` — add `numpy`.

## Error handling

The mixer is the one change in this batch that threatens per-feed isolation:
twelve output streams become one, so a device failure that used to cost one row
now costs all audio.

- **Output stream will not open** → warn once, keep every feed decoding and
  metering. Sound is lost; the pane is not. This preserves today's "no audio
  device" behaviour, hoisted from per-session to one place.
- **Ring buffer starved** → that feed contributes silence for the block. The
  other eleven are unaffected. The row already shows `◐` or `○` from the
  existing state machine.
- **Ring buffer overfull** → drop the oldest block. Bounded latency and memory,
  one inaudible discontinuity.
- **Callback raises** → a block of silence, and the exception is recorded for
  the UI thread to surface. Nothing is logged from the callback itself.
- **Feed dies or reconnects** → unchanged. The reader's existing backoff,
  partial-frame discard, and `None` heartbeat all still apply; the heartbeat
  continues to drive state reporting and is never written to a buffer.

## Testing

Choosing NumPy DSP over hosted AudioUnits was largely to make this section
possible: essentially all of it runs headless.

| unit | test |
|------|------|
| Compressor gain curve | known input levels produce the computed gain, including in the knee |
| Range limit | gain clamps at exactly 12 dB; saturates at −28 dBFS and below |
| Makeup | +6 dB applied above threshold as well as below |
| Gate | fully closed below −46 dBFS; hysteresis prevents chatter at −40 |
| Gate smoothing | a step across the threshold ramps rather than steps |
| Attack/release | time constants measured from a step input |
| Reverb decay | impulse response falls 60 dB in ~100 ms |
| Reverb low-pass | spectral energy above 1.2 kHz attenuated as expected |
| Reverb width | L and R impulse responses are decorrelated |
| Reverb wetness | no direct signal present in the output |
| Panner power | `L² + R²` constant across position |
| Panner positions | each `N` in the table above yields the listed positions |
| Panner centre | odd `N` inverts phase and attenuates 6 dB on the centre feed |
| Panner crossfade | a change in `N` does not produce a discontinuity |
| Ring buffer | write/read round trip; starved read returns silence; overfull write drops oldest |
| Mixer sum | synthetic buffers produce the asserted block; bus gains correct |
| Bus routing | a feed appears on the dry bus, the ambient bus, or neither, per its flags |
| Callback allocation | `tracemalloc` delta across N invocations is zero |
| Callback safety | a chain that raises yields silence, not a propagated exception |
| Device failure | a stream that will not open warns once and leaves metering running |

**Manual verification.** One step needs hardware and closes out the spec:
twelve feeds audible through a single stereo stream, with several routed to the
ambient bus, confirming the panning spread and that the ambient wash sits behind
the dry feeds without masking them.
