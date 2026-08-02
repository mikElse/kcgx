# audio pane A — row restructure

**Date:** 2026-08-02
**Status:** approved, pending implementation plan
**Batch:** [audio pane upgrades](2026-08-02-audio-pane-upgrades-design.md)

## Summary

Restructure the feed row so that what you can hear is visually obvious and
directly manipulable: drop the feed ident, give each row a compact and an
expanded form driven by whether it is audible, add an inline clickable control
strip, and make the whole row a mute target. Adds solo.

## Motivation

The current row spends 16 of its 46 columns on a machine identifier
(`kpdx3_twr`) that is never typed at runtime and truncates the human-readable
name to fit. Meanwhile every feed renders identically whether or not it is
audible, so the pane gives equal visual weight to the one frequency you are
listening to and the eleven you are not.

Reclaiming the ident's columns and letting audibility drive row height fixes
both at once, and the freed vertical space pays for the taller meter spec B
needs.

## Layout

46 content cells.

### Compact — 2 rows

```
────────────────────────────────────────────────
 Tower (Both)                    [A] [OFF] ●
```

| field | cells |
|-------|-------|
| name | 34 |
| `[A]` | 3 |
| `[OFF]` | 5 |
| state dot | 1 |
| separators | 3 |

Name width rises from 24 to 34, so `Tower (Both)` and similar stop truncating.
`_fit` continues to mark real truncation with an ellipsis.

### Expanded — 6 rows

```
────────────────────────────────────────────────
 Tower (Both)                              ●
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 ▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅▃▂▁▁▂▃▅▇█▇▅
 [S]  [ON]  [A]                    busy 34%
```

The three meter rows are **one waveform three cells tall**, not three meters.
Each column is a single sample rendered across 24 vertical steps (3 rows × 8
block glyphs). One row gives a gradient too few cells to read as a gradient,
which is what makes spec B's VU colouring worth having.

The `busy NN%` readout is populated by spec B. Until B lands, the field is
blank.

## Row state

**Expansion follows audibility.** A feed that is audible on the main bus is
expanded; a feed that is not is compact. Selection is independent of expansion
and continues to be shown by the `selected` class.

This keeps the layout honest — full meters for exactly what you can hear — and
bounds the redraw cost, because only audible feeds run a tall meter.

### Keeping ON/OFF reachable

If muted feeds were compact *and* compact showed no controls, the `[ON]`/`[OFF]`
toggle could only ever render `ON`, and `OFF` would be unreachable. Compact rows
therefore carry a minimal control strip — a dimmed `[OFF]` and `[A]` — on the
same line as the name. The toggle is then always visible and always truthful,
and expansion is purely about the meter and the extra controls.

### Overflow

Twelve feeds at KPDX with four unmuted is 4×6 + 8×2 = 40 rows, inside a pane of
42 less header and footer. The stack scrolls, as it does today, and the existing
`FeedList` selection-driven scrolling brings the selection into view. Nothing
new is required, but the layout is expected to scroll once three or more feeds
are audible and that is acceptable.

## Controls

| control | states | action |
|---------|--------|--------|
| `[ON]` / `[OFF]` | lit when audible, dim when muted | toggle mute |
| `[S]` | lit when this feed is soloed | toggle solo |
| `[A]` | lit when routed to the ambient bus | toggle ambient routing |

All three are clickable. Clicking anywhere else on the row toggles mute, so the
common action does not require aiming at a 5-cell target.

`[A]` is rendered and toggleable in this spec but has no audible effect until
spec D lands; it sets a flag on the session that D's mixer reads.

## Solo

`S` on the selected feed, or a click on `[S]`:

- **Engaging** records the current mute state of every feed, then mutes all
  feeds except this one and unmutes this one.
- **Disengaging** restores exactly the recorded state.
- Soloing a *different* feed while solo is active moves the solo without
  overwriting the recorded state, so one disengage still returns to the
  pre-solo mix.
- Manually toggling mute on any feed while solo is active cancels solo (the
  recorded state is discarded), because the user has expressed a new intent.

## Key bindings

| key | action |
|-----|--------|
| `↑` `↓` | move the selection |
| `space` | toggle mute on the selected feed |
| `S` | toggle solo on the selected feed |
| `a` | toggle ambient routing on the selected feed |
| `f` | open the feed picker |
| `q` | quit |

## Feed picker

Repurposed from an ident-reporting lookup into a **jump list**. It lists feeds
by name; selecting one moves the selection to that row and scrolls it into view.
This becomes genuinely useful once spec B is reordering rows and you want a
specific frequency quickly.

Idents remain in the picker as dim secondary text, since they are still what
`feed` in `squelch.toml` and `--feed` take. Removing them from the row does not
remove the need to look one up occasionally.

The existing off-event-loop fetch, cancellation handling, and stale-cache
fallbacks are unchanged.

## Components

- `src/squelch/app.py` — `FeedRow` gains compact/expanded rendering and a
  control strip; `SquelchApp` gains solo state and click routing. `app.py` is
  already 463 lines and this spec adds meaningfully to it, so the row widget and
  its layout constants move to a new `src/squelch/rows.py`, leaving `app.py`
  responsible for the application shell.
- `src/squelch/session.py` — `FeedSession` gains an `ambient` flag.
- `src/squelch/squelch.tcss` — compact/expanded heights, control lit/dim
  styling.

## Error handling

No new failure modes. Clicks that land on no row are ignored. Solo state is
in-memory only and is not persisted across restarts.

## Testing

Existing `tests/test_app.py` Pilot patterns extend directly.

| behaviour | test |
|-----------|------|
| Ident removed | rendered row contains the name at 34 cells and no ident |
| Compact/expanded | unmuting a feed grows its row to 6; muting shrinks it to 2 |
| Click-to-mute | `pilot.click` on a row body toggles that feed's mute |
| Control hit targets | clicks on `[ON]`, `[S]`, `[A]` hit the right control and not the row body |
| Solo engage | all other feeds muted, this one unmuted |
| Solo restore | prior mute state restored exactly, including feeds that were already unmuted |
| Solo moves | soloing a second feed then disengaging returns to the pre-solo mix |
| Solo cancelled | manual mute during solo clears solo state |
| Picker jump | selecting a picker row moves the selection to that feed |
| Truncation | an over-long name still gets an ellipsis, not a silent cut |
