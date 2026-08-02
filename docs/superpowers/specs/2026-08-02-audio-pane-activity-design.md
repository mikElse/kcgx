# audio pane B — activity ranking and the VU meter

**Date:** 2026-08-02
**Status:** approved, pending implementation plan
**Batch:** [audio pane upgrades](2026-08-02-audio-pane-upgrades-design.md)
**Depends on:** [spec A](2026-08-02-audio-pane-rows-design.md)

## Summary

Rank feeds by how busy they have been over the trailing five minutes and order
the stack accordingly, debounced so rows do not move under the user's hand.
Drive spec A's three-row expanded meter at a higher frame rate with a VU-style
colour gradient.

## Motivation

A dozen feeds in a 42-row pane means most of them are off screen most of the
time. Which frequency is worth listening to changes through the day — ground is
busy at pushback, tower at the rush, approach in between — and there is
currently no way to see that without watching every meter.

Ranking by measured activity puts the busy frequencies where you can see them.

## The activity metric

**Definition.** The fraction of the trailing five minutes during which the
feed's level exceeded `activity_threshold_dbfs`.

**Threshold.** Default −40 dBFS, configurable. ATC feeds sit on a constant
noise floor around −50 dBFS with speech peaking −20 to −10, so −40 separates
speech from hiss with margin on both sides.

**Sample rate.** The pipeline already emits a decimated level at 10 Hz
(`LEVEL_DECIMATION = 5` over 20 ms frames). Activity reuses that reading rather
than adding a second tap at frame rate.

**Storage.** Sixty buckets of five seconds each, rotated in place. Each bucket
holds `(busy_count, total_count)`. Activity is the ratio of the sums. This is
O(1) per reading and 60 integer pairs per feed — as against a 3000-element
deque per feed for a naive rolling window — and five-second granularity is far
finer than a five-minute average needs.

**Measured pre-compression.** This is load-bearing once spec D lands. D's
upward compressor exists specifically to raise quiet signals; metering after it
would push every feed toward the same activity number and destroy the ranking
this spec exists to produce. Activity therefore taps the raw decoded frame.

The *displayed* meter shows post-compression level, because that is what the
user hears. These become two different taps of the same frame, and the
distinction must survive spec D's rewrite of the audio path.

Until spec D lands there is no compression and the two taps read identically.

## Resort policy

Ranking is recomputed every 5 s. A new order is **applied** only when both hold:

- it has been the computed order for three consecutive computations (15 s), and
- no click or keypress has landed in the last 2 s.

Without this, rows move while the user is reaching for one — which matters
because spec A makes the whole row a mute target, so a row that moves between
the decision to click and the click itself mutes the wrong frequency.

**Selection tracks the session, not the row index.** A resort never moves the
selection to a different feed. This is why `SquelchApp._rows` is already keyed
by `id(session)` rather than by position; that keying must be preserved.

**Offline feeds** produce no readings, decay to 0%, and sink to the bottom
naturally. No special case is needed.

**Order is descending** by activity. Ties break by the feed's original
discovery order, so the order is deterministic and does not churn between two
equally idle feeds.

## The expanded meter

**Height.** Three rows, from spec A. Each sample is rendered across 24 vertical
steps (3 rows × 8 block glyphs) rather than 8.

**Frame rate.** Compact rows do not render a meter at all. Expanded rows raise
their update rate above the current 10 Hz. The pipeline's `LEVEL_DECIMATION`
becomes per-session and switchable: expanded feeds decimate by 2 (25 Hz),
compact feeds stop emitting levels for display entirely and only feed the
activity buckets.

This is close to cost-neutral against today. Currently all twelve feeds emit at
10 Hz — 120 marshalled updates per second. Under this spec, with three feeds
audible, it is 3 × 25 = 75. The cost scales with what you are listening to
rather than with how many feeds exist, which is the right dependency.

The existing peak-hold behaviour is retained, so a short transient is still seen
rather than missed between samples.

**Colour gradient.** Sample level maps to a colour ramp: low levels in the
theme's dim colour, mid in its text colour, high in its accent colour, peaks in
a warning colour. The four stops come from the active theme registered by
[spec C](2026-08-02-audio-pane-theme-design.md), so the meter recolours when the
radar pane's theme changes.

Until spec C lands, the ramp uses Textual's default `$text-disabled` / `$text` /
`$primary` / `$warning` variables, which is also the fallback when no theme can
be resolved.

## Components

- `src/squelch/activity.py` — new. Bucketed activity tracker and the ranking
  function. Pure, clock-injected, no UI or audio dependencies.
- `src/squelch/pipeline.py` — per-session switchable decimation; separate taps
  for activity (pre-compression) and display (post-compression).
- `src/squelch/session.py` — owns its activity tracker; exposes `activity` as a
  fraction.
- `src/squelch/rows.py` — three-row gradient meter rendering.
- `src/squelch/app.py` — the resort timer, debounce state, and reordering.
- `src/squelch/config.py` — `activity_threshold_dbfs`, default −40.0.

## Error handling

- A feed with no readings yet reports 0% rather than dividing by zero.
- Reordering is a reorder of existing mounted widgets, not a remount, so it
  cannot lose meter history or drop a row.
- If a resort is computed while the app is tearing down, the existing
  `on_unmount` teardown path applies and the timer is stopped there, as the
  clock timer already is.

## Testing

| behaviour | test |
|-----------|------|
| Bucket rotation | injected clock; buckets older than 5 min are evicted |
| Activity fraction | known busy/idle sequence yields the expected ratio |
| Threshold | a level exactly at the threshold is classified consistently |
| Cold start | a feed with no readings reports 0%, does not raise |
| Ranking | descending by activity; ties break by discovery order |
| Debounce — stability | an order that holds for 2 computations is not applied; 3 applies it |
| Debounce — input | a keypress within 2 s defers an otherwise-ready resort |
| Selection | selection stays on the same session across a resort |
| Decimation | expanded sessions emit at 25 Hz, compact sessions emit no display levels |
| Pre/post tap | with a stub compressor applying gain, activity is unchanged and the displayed level rises |
| Gradient | level maps to the expected ramp stop, including at both extremes |
