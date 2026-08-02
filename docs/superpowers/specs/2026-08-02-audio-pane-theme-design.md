# audio pane C — theme sync with the radar pane

**Date:** 2026-08-02
**Status:** approved, pending implementation plan
**Batch:** [audio pane upgrades](2026-08-02-audio-pane-upgrades-design.md)
**Depends on:** [spec A](2026-08-02-audio-pane-rows-design.md)

## Summary

Make the audio pane adopt the colour scheme of the radar pane beside it, and
keep it in step when that theme changes at runtime.

## Motivation

The cockpit is one screen split into panes. `adsb-tui` ships six themes and a
`t` key to cycle them; squelch uses Textual's defaults and matches none of them.
Two adjacent panes in unrelated palettes read as two applications sharing a
terminal rather than one instrument.

## Why the theme is sampled, not read

The obvious approach — read `theme` from `~/.config/ads-b-tui/adsb-tui.toml` —
only reports the theme adsb-tui *launched* with.

Verified empirically against the real binary: adsb-tui does not persist the
theme. Two `t` presses followed by a clean quit left the config file
byte-identical (same md5), while the rendered pane background demonstrably
changed from `rgb(14,20,24)` to `rgb(24,18,10)`. A file watcher would sit there
observing nothing for the life of the session.

The rendered pane is the ground truth, and tmux will hand it over.

## Mechanism

`kcgx` exports `KCGX_RADAR_PANE` into squelch's environment, carrying the tmux
pane id of the adsb-tui pane.

squelch polls, every 3 s on a worker thread:

```
tmux capture-pane -e -p -t $KCGX_RADAR_PANE
```

and extracts the first `ESC[48;2;r;g;b m` background sequence. That RGB triple
identifies the theme.

### Measured backgrounds

Captured from the real binary, one run per theme:

| theme | background |
|-------|------------|
| `default` | `rgb(22, 26, 32)` |
| `color` | `rgb(14, 20, 24)` |
| `amber` | `rgb(24, 18, 10)` |
| `ocean` | `rgb(10, 18, 24)` |
| `matrix` | `rgb(0, 16, 0)` |
| `mono` | `rgb(8, 8, 8)` |

All six are distinct, so an exact match on the triple is sufficient. Matching is
exact rather than nearest-colour: an unrecognised background means adsb-tui has
changed or something else is in that pane, and silently snapping to the closest
of six is worse than leaving the theme alone.

### Applying the theme

On a change, swap `App.theme` to a matching `Theme` registered at startup.
Textual 8.2.8 supports first-class `Theme` objects, so this is a palette swap
rather than rewriting CSS.

### Harvesting the full palettes

The background alone identifies a theme; it does not supply the accent, text,
and dim colours the palettes need. Those are harvested during implementation by
the same capture method — run adsb-tui under each of the six themes with
`--demo-mode`, capture with `-e`, and collect the distinct `38;2;r;g;b`
foreground triples. The result is a static table of six palettes in
`src/squelch/themes.py`. This is a one-time discovery step, not runtime
behaviour.

## Fallbacks

In order:

1. `KCGX_RADAR_PANE` set and `tmux capture-pane` succeeds → sampled theme.
2. Otherwise, read `theme` from `adsb-tui.toml` once at startup and use that
   palette statically.
3. Otherwise, `default`.

So standalone `squelch`, outside the cockpit, still themes sensibly — it just
does not track changes. The config path is the documented one
(`$XDG_CONFIG_HOME/ads-b-tui/adsb-tui.toml`, falling back to
`~/.config/ads-b-tui/adsb-tui.toml`).

## Components

- `src/squelch/themes.py` — new. The six palettes, the RGB → theme-name
  mapping, and the ANSI background extraction. All pure functions.
- `src/squelch/radar_theme.py` — new. The poller: subprocess invocation,
  worker thread, change detection.
- `src/squelch/app.py` — register the themes, apply on change.
- `bin/kcgx` — export `KCGX_RADAR_PANE` when building the squelch pane.

Spec B's meter gradient reads its four ramp stops from the active theme.

## Error handling

Nothing here may affect audio or the event loop.

- The poll runs on a worker thread, as the feed fetch already does.
- `tmux` missing, the pane gone, a non-zero exit, or a timeout → leave the
  current theme in place and try again next tick. No warning is logged, because
  a pane that has been closed would otherwise warn every 3 s for hours.
- An unrecognised background → leave the current theme in place.
- The subprocess gets a short timeout (2 s) so a hung tmux cannot leak threads
  over a multi-hour session.
- Theme application is marshalled onto the UI thread through the existing
  `call_from_thread` path and is guarded like the other cross-thread calls.

## Testing

None of this needs tmux or adsb-tui to be running; the subprocess is injected.

| behaviour | test |
|-----------|------|
| Background extraction | first `48;2;r;g;b` pulled from a captured-pane fixture |
| Extraction — none present | returns `None` rather than raising |
| Mapping | each of the six measured triples maps to its theme |
| Mapping — unknown | an unmeasured triple returns `None` |
| Change detection | the same background twice applies the theme once |
| Poll failure | non-zero exit, timeout, and missing binary all leave the theme unchanged |
| Fallback chain | no env var → TOML; unreadable TOML → `default` |
| Palette completeness | every registered theme defines all four gradient stops spec B needs |
| Application | a detected change swaps `App.theme` |
