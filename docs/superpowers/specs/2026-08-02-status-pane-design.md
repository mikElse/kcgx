# A status pane, and no more shell pane

*2026-08-02*

## The problem

The cockpit's bottom-right pane is a plain shell. It was there to type
`kcgx go` into, and since `Ctrl-b a` opens the picker in a popup, it no
longer earns twelve rows.

Nothing on screen says which airport you are listening to. squelch's header
carries the ICAO, but not the airport's name, and there is no clock — which
matters when the traffic you are hearing is timestamped in Zulu.

## What we are building

The shell pane goes away. A four-row status pane takes the top of the right
column, above squelch:

```
┌─────────────────────┬──────────────────┐
│                     │  KPDX  Portland… │  status, 4 rows
│      adsb-tui       ├──────────────────┤
│                     │     squelch      │
└─────────────────────┴──────────────────┘
```

It shows the current airport, the time in Zulu and locally, and a clickable
way into the picker.

## The pane

```

 KPDX  Portland International
 1955Z   12:55 PDT              ▾ airport (^b a)

```

No border. One cell of padding on every side, which is what the blank first
and last rows above are — four rows total: padding, two content lines,
padding.

**Line 1** is the ICAO and the airport's name, truncated with `…` if it does
not fit the 46 columns left after padding.

**Line 2** carries both clocks on the left and the picker affordance on the
right. `1955Z` is UTC as `%H%MZ`, which is what ATC says on the air, so it
is the one that matches what you are hearing; `12:55 PDT` is `%H:%M %Z` in
the machine's own timezone.

At 46 columns the line is comfortable: the clocks take 17 cells and
`▾ airport (^b a)` takes 16, with the gap between them absorbing the rest.
When the pane is too narrow to hold both, the clocks win and the affordance
degrades to a bare `▾` — the keybinding still works, and a clock that
silently disappears is worse than a hint that shrinks.

The dataset has no timezone column (`icao,iata,name,city,region,country,
lat,lon,size`), so the airport's *local* time is deliberately not shown.
Deriving it from longitude would be wrong by an hour or more across DST and
political boundaries, and a clock that is quietly wrong is worse than one
that is absent.

**`▾ airport (^b a)` is clickable** — the whole field, not just the arrow.
Clicking it runs

```
tmux display-popup -E "kcgx go"
```

— the same popup `Ctrl-b a` opens, so there is one code path and the hint
text cannot drift from what the key does. tmux mouse mode is already on and
forwards clicks to applications that request mouse reporting, which Textual
does.

Clicking a pane also makes it tmux's active pane, so after the popup closes
the arrow keys would drive the status pane instead of squelch's feed list.
So `kcgx go` ends a successful retarget by selecting the squelch pane — by
role, using the same lookup as everything else. That matches what launch
already does (it lands on squelch, the pane you read) and it fixes the
keybinding path too, where `Ctrl-b a` pressed from adsb-tui previously left
you on adsb-tui.

## Pane addressing

`retarget` currently names panes by index: `cockpit.0` for adsb-tui,
`cockpit.1` for squelch. Inserting a pane breaks that, and the final review
of the airport-search work already flagged index addressing as latent risk.

Measured, rather than assumed: after `split-window -v -b`, the status pane
takes index 1 and squelch moves from index 1 to index 2, while pane *ids*
stay `%0`, `%1`, `%2` throughout.

So each pane is tagged at creation with a tmux user option:

```bash
tm set -p -t "$pane_id" @kcgx_role adsb|status|squelch
```

and looked up by role:

```bash
pane_for_role() {
    tm list-panes -t "=$SESSION:cockpit" -F '#{@kcgx_role} #{pane_id}' |
        awk -v r="$1" '$1 == r { print $2; exit }'
}
```

Verified that the tag survives `respawn-pane -k`, which is what `retarget`
issues.

This is more machinery than renumbering two strings. It is worth it because
this is the second time the indices have had to change, and the failure it
prevents is silent: retargeting the wrong pane leaves a cockpit that looks
fine and is pointed somewhere else.

## Components

```
src/kcgx/status.py      the Textual status pane   (imports airports, state)
src/kcgx/__main__.py    unchanged
bin/kcgx                layout, role tags, retarget by role
```

`kcgx-status` becomes a second console script alongside `kcgx-airport`.

The pane's two lines are built by pure functions taking an `Airport | None`,
two `datetime`s and a width — so the formatting is testable without a
terminal, the same split `row_text` uses in the picker.

## Staying current

The pane ticks once a second. On each tick it redraws the clock and re-reads
the airport through `kcgx.state.current_icao()` — the same function
`kcgx-airport resolve` calls, not a second spelling of the resolution order.

That choice has three consequences worth stating:

- `kcgx go` needs no changes at all.
- `retarget` still respawns only two panes, so the status pane never
  flickers during a switch.
- The pane is correct even if the remembered airport changes by some other
  route, such as running `kcgx-airport pick` by hand.

## Error handling

- **No state file** — falls through `current_icao`'s existing chain: the
  squelch config's `icao`, then `KPDX`. Identical to what launch does.
- **An ICAO absent from the dataset** — show the bare code with no name
  rather than crash, matching the fallback behaviour the airport-search work
  established.
- **A pane narrower than expected** — truncate; never wrap. A wrapped line
  costs a row the pane does not have.
- **A failed click** — if the popup command fails, the pane keeps running.
  Losing the mouse shortcut is not a reason to lose the clock.

## Testing

**Pure formatting** — both lines at their real width, a name long enough to
truncate, a missing airport, and a width too small to hold either field.

**The app under `run_test`** — the airport and both clocks render; a click
on the affordance invokes the popup through an **injected runner**, so no
test shells out to tmux; the clock advances on tick; and a changed state
file changes the displayed airport on the next tick.

**The launcher** — three panes, no shell pane, the status pane is four rows,
each pane carries its `@kcgx_role`, and — the one that matters — **retarget
still finds adsb-tui and squelch by role after the layout change**, asserted
on the panes' real `#{pane_start_command}`.

Capture in Textual tests uses `app.screen._compositor.render_strips(...)`,
never `screen.render_lines()`, which returns blank fill for child widgets.
Width assertions use widgets' `outer_size.width`, never `cell_length`, which
is clipped to the screen width and cannot fail.

## Documentation

The README says `kcgx go [query]` works "from the shell pane". That pane
will not exist; the line gets corrected to say it works from any terminal,
and the status pane's click target gets a mention beside `Ctrl-b a`.

`KCGX_SHELL_ROWS` becomes `KCGX_STATUS_ROWS` (default 4), and a
`KCGX_STATUS_CMD` seam is added for tests, matching `KCGX_ADSB_CMD` and
`KCGX_SQUELCH_CMD`.

## Out of scope

- The airport's local time, until there is a timezone source worth adding.
- Any other status content — frequencies, weather, feed counts. squelch's
  own header already carries what it knows.
- Making the shell pane optional. It is being removed, not hidden.
