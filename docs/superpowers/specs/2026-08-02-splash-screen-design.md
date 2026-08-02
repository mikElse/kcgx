# splash screen — design

**Date:** 2026-08-02
**Status:** approved, pending implementation plan

## Summary

`kcgx` prints an ASCII wordmark when it builds a cockpit, held on screen for a
minimum duration that the build itself absorbs. Its sole content is the
wordmark: no version string, no tagline, no progress text.

## Motivation

Opening the cockpit is currently silent. The launcher resolves an airport,
starts a tmux server, builds two panes and a shell, and attaches — and until
tmux paints, the terminal shows nothing but the command you typed. A wordmark
marks the moment as a launch rather than a pause, and the build is already
spending time that has nothing to display.

## The wordmark

Figlet's *3D Diagonal* font, **80 columns × 9 rows**, pure ASCII:

```
__/\\\________/\\\________/\\\\\\\\\_____/\\\\\\\\\\\\__/\\\_______/\\\_
 _\/\\\_____/\\\//______/\\\////////____/\\\//////////__\///\\\___/\\\/__
  _\/\\\__/\\\//_______/\\\/____________/\\\_______________\///\\\\\\/____
   _\/\\\\\\//\\\______/\\\_____________\/\\\____/\\\\\\\_____\//\\\\______
    _\/\\\//_\//\\\____\/\\\_____________\/\\\___\/////\\\______\/\\\\______
     _\/\\\____\//\\\___\//\\\____________\/\\\_______\/\\\______/\\\\\\_____
      _\/\\\_____\//\\\___\///\\\__________\/\\\_______\/\\\____/\\\////\\\___
       _\/\\\______\//\\\____\////\\\\\\\\\_\//\\\\\\\\\\\\/___/\\\/___\///\\\_
        _\///________\///________\/////////___\////////////____\///_______\///__
```

Individual lines run 72 to 80 characters; the slant means each is indented one
further than the last. The 80-wide bounding box is what gets centred, not each
line, because the indentation is part of the glyphs.

## Constraints

- `bin/kcgx` runs under `#!/usr/bin/env bash`, which on this machine is
  **bash 3.2.57** — macOS's system bash. No `$EPOCHREALTIME`, no bash 4+
  features. Verified, not assumed.
- `set -euo pipefail` is in force for the whole script.
- The launcher refuses to start below **100 columns**, so the 80-column
  wordmark always fits when it is printed at all.
- `squelch`'s pane is 48 columns. The wordmark cannot live there, which is why
  this is a launcher feature rather than a `squelch` one.

## Design

### Placement

A `splash()` function in `bin/kcgx`, called on the cold-build path only:

- **After** the terminal-size check. Printing before it would show a wordmark
  and then immediately fail with "terminal is 80 columns; kcgx needs at least
  100", which reads as a crash.
- **Before** `airport_record resolve`, so the resolve's ~0.2 s counts toward
  the display time rather than adding to it.

Every other path is already gone by then: `stop`, `go`, and `--help` all `exit`
inside the `case` block above, and the reattach branch `exec`s into
`attach-session` before the size check is reached. No suppression logic is
needed for any of them — this falls out of where the call sits.

### Minimum display time

Not measured with a clock. A sleep is started in the background before the
build and waited on after it:

```bash
splash
sleep "$SPLASH_SECONDS" &
splash_pid=$!
# ... resolve the airport, build the session, split the panes ...
wait "$splash_pid" 2>/dev/null || true
exec "${TMUX_CMD[@]}" attach-session -t "=$SESSION"
```

Total launch time becomes `max(build, SPLASH_SECONDS)`. On this machine the
build is ~0.3 s, so the splash costs ~0.9 s; on a slow airport resolve or a
cold tmux server it costs nothing.

This shape was chosen specifically because bash 3.2 has no sub-second clock.
Measuring elapsed time would need `date +%s` (whole seconds only, too coarse)
or an external `perl`/`python3` call on the launch path. Racing a sleep needs
neither.

`|| true` is required: `set -e` is on and `wait` reports non-zero if the job
was signalled.

### Rendering

```bash
printf '\033[H\033[2J'
```

clears and homes, then each line is printed with a left pad of
`(cols - 80) / 2`, clamped at zero, using the `cols` the script already
measured with `stty size`.

Clearing is honest here rather than destructive: tmux is about to take the
whole screen a fraction of a second later.

No colour. The wordmark inherits the terminal's own foreground, so it can never
clash with the adsb-tui theme loading immediately behind it, and there is no
`NO_COLOR` handling to get wrong.

### Where the art lives

A quoted heredoc (`<<'ART'`) inside `bin/kcgx`. Quoting is mandatory — the
wordmark is almost entirely backslashes, and an unquoted heredoc would eat
them. Verified to round-trip exactly.

Nine unchanging lines do not earn a data file: a separate file would need path
resolution against `$REPO` and could go missing from a partial install, adding
a failure mode in exchange for nothing.

### Suppression

Following the launcher's existing environment-override convention:

| Variable | Default | Effect |
|---|---|---|
| `KCGX_SPLASH` | unset → on iff `[ -t 1 ]` | `0` disables entirely; `1` forces on even without a tty |
| `KCGX_SPLASH_SECONDS` | `1.2` | Minimum display time |

The `[ -t 1 ]` default is load-bearing, not cosmetic. The existing launcher
tests run `bin/kcgx` with stdout redirected; without it, every one of them
would gain 1.2 s and the suite would slow down for no reason.

When the splash is suppressed, the background sleep is not started and the
`wait` is skipped, so `KCGX_SPLASH=0` costs exactly nothing.

## Error handling

There is nothing here that can fail in a way worth reporting. A splash is
decoration on the way to a cockpit, so every edge case resolves toward "print
less, launch anyway":

- **Not a terminal** → nothing printed, no delay.
- **Terminal narrower than the wordmark** → unreachable, since the 100-column
  floor is enforced first. The pad is clamped at zero regardless, so a wordmark
  printed into a narrow terminal would wrap rather than error.
- **`sleep` killed or unavailable** → `wait ... || true` swallows it and the
  launch continues.
- **Terminal size unavailable** → already fatal before this point; the launcher
  dies in the `stty size` block.

## Testing

`KCGX_SPLASH=1 KCGX_SPLASH_SECONDS=0` gives `tests/test_kcgx_launcher.py` a
deterministic, latency-free seam, matching how `KCGX_SIZE`, `KCGX_DETACHED`,
and `KCGX_SOCKET` are already used there.

| Behaviour | Test |
|---|---|
| Cold build prints it | the wordmark appears in stdout |
| Backslashes survive | a known line matches byte for byte |
| Centred | left pad equals `(cols - 80) / 2` for the measured width |
| Not a tty | absent by default when stdout is redirected |
| Explicitly disabled | `KCGX_SPLASH=0` prints nothing even on a tty |
| Reattach | a second launch against a live session prints nothing |
| `stop` and `go` | print nothing |
| Too-narrow terminal | the size error is printed and the wordmark is not |
| No added latency when disabled | a detached build stays under its current time |

## Out of scope

- Colour, animation, or a progress indicator.
- A version string, tagline, or airport name on the splash. The wordmark is the
  sole content.
- Any splash inside `squelch` or the radar pane.
- Showing it on reattach. Reattach is near-instant, so a wordmark there is a
  flicker rather than an intro.
