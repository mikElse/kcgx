# Airport search: retarget the whole cockpit

*2026-08-02*

## The problem

kcgx is fixed to one airport. Moving it means editing two files by hand —
`~/.config/squelch/squelch.toml` for the ICAO and
`~/.config/ads-b-tui/adsb-tui.toml` for latitude and longitude — then
restarting the cockpit. The adsb-tui config currently carries a comment
recording the previous Portland coordinates, which is what doing this by
hand looks like.

Worse, the second edit does not stick: adsb-tui rewrites its whole config
file with defaults on exit, so hand-edits get reordered and can be lost.

## What we are building

A search inside the running cockpit. Press a key, type part of an airport's
name or code, pick it, and both panes move to it. The cockpit never closes,
and neither config file is touched.

The choice persists: the cockpit reopens where you left it.

## Model

kcgx is the parent. squelch and adsb-tui are the two components it drives.
Airport search belongs to the parent, because it is the only thing that
knows how to address both children:

- **adsb-tui takes a location** — `--site-lat` / `--site-lon`
- **squelch takes an ICAO** — `--icao`

Search is the lookup from what you type to both of those at once.

## Layout

```
bin/kcgx              the only thing that talks to tmux
src/kcgx/
  airports.py         dataset + search      (pure data; no Textual, no tmux, no I/O)
  picker.py           the Textual picker    (imports airports)
  state.py            the remembered airport
  __main__.py         `kcgx-airport` entry point
  data/airports.csv   committed dataset
tools/build_airports.py
src/squelch/          unchanged in structure; two behaviour fixes (see Error handling)
```

squelch never reads a coordinate, so the coordinate database does not
belong to it.

## The dataset

`src/kcgx/data/airports.csv`, generated from
[OurAirports](https://davidmegginson.github.io/ourairports-data/airports.csv)
and **committed to the repo**. No build step, no network at runtime, no API
key, no rate limit.

Filter: `type` in (`large_airport`, `medium_airport`) with a four-letter
ICAO code. That is 4,737 rows and 368 KB out of an 85,824-row, 12 MB
source.

Columns: `icao,iata,name,city,region,country,lat,lon`.

`tools/build_airports.py` regenerates it. The source URL, the filter, and
the generation date go in a header comment in the CSV itself, so the file
is reproducible without reading the script.

Small airports are excluded deliberately. LiveATC covers a few hundred
fields, essentially all of them large or medium, and the omission keeps
search results readable.

## Search

```python
search(query: str, airports: list[Airport]) -> list[Airport]
```

Deterministic and tiered — no fuzzy scoring, because ranked exact matching
is predictable and a personal tool benefits more from predictability than
from cleverness:

1. Exact ICAO, then exact IATA
2. ICAO or IATA prefix
3. Every query token appears somewhere in `name + city + region + country`

Both the query and the haystack are normalised the same way: NFKD, drop
combining marks, lowercase, map every non-alphanumeric character to a
space, collapse runs of spaces. This is what lets `seattle-tacoma` find
`Seattle–Tacoma` (the source uses an en dash) and `sa carneiro` find
`Sá Carneiro`.

Multiple tokens are ANDed, so `portland or` separates KPDX from Portland,
Maine. Ties break large-before-medium, then ICAO alphabetically.

`Airport` is a frozen dataclass: `icao, iata, name, city, region, country,
lat, lon`.

## The picker

`kcgx.picker` — a Textual app. An `Input` on top, an `OptionList` below, a
footer hint. The list filters on every keystroke; `enter` selects, `esc`
cancels.

It runs in a tmux popup:

```
bind a display-popup -E -w 64 -h 20 "kcgx go"
```

**The picker cannot return its answer on stdout.** `display-popup -E`
destroys the popup's pty when the command exits, so anything printed there
is unrecoverable by the caller. The retarget therefore happens *inside* the
popup: `kcgx go` runs the picker, reads the selection, issues the tmux
commands itself, and exits — and exiting is what closes the popup. tmux
commands work normally from inside a popup.

`kcgx go [query]` also works typed in the shell pane; it is the same code
path. A query that is an exact ICAO skips the picker and retargets
immediately.

## Entry point

`kcgx-airport`, a console script, is the only interface between the bash
launcher and the Python side. Two modes, both emitting one tab-separated
record: `icao<TAB>lat<TAB>lon<TAB>name, city`.

The record goes to the path given by `--out`, falling back to stdout when
that is omitted.

**The picker needs both standard streams left alone.** Textual's driver
writes its frames to `sys.__stderr__`, and it measures the terminal with
`shutil.get_terminal_size()`, which reads `sys.__stdout__`. Redirect
stderr and the popup is blank. Redirect stdout and it draws in the right
place at the wrong size — it falls back to 80x24 and paints a frame bigger
than the 64x20 popup, so the terminal scrolls and the airport rows end up
off screen. Both failures look the same from outside, and neither stops
the search from answering a keypress: the cockpit moves somewhere the user
never saw.

So `bin/kcgx` redirects neither stream. Nothing is lost by that — keeping
the record off the terminal is `--out`'s job, and `bin/kcgx` always passes
it, so nothing is printed to stdout there at all. stdout stays available
for the modes that draw nothing, which is what makes the tool usable by
hand.

- **`kcgx-airport resolve`** — print the current target, resolved through
  the order under Persistence. No interaction. `bin/kcgx` calls this at
  launch to learn where to point both panes.
- **`kcgx-airport pick [query]`** — run the picker, write the chosen ICAO
  to the state file, print the record. Exits 1 with no output when
  cancelled, which is how `kcgx go` knows to leave the cockpit alone. An
  exact-ICAO query resolves without drawing the picker.

Keeping the split here means `bin/kcgx` never parses the CSV and
`src/kcgx/` never runs a tmux command.

## Retarget

Two shell functions in `bin/kcgx` build the pane commands:

```bash
adsb_cmd()    { printf '%s --site-lat %s --site-lon %s' "$ADSB_CMD" "$1" "$2"; }
squelch_cmd() { printf "uv run --project '%s' squelch --icao %s" "$REPO" "$1"; }
```

The initial `new-session` / `split-window` and the retarget
`respawn-pane -k` both call these. **Launch and switch cannot drift.**
That is deliberate: three separate bugs in this project came from a test
path and a real path diverging, and a second way to spell the pane command
would be a fourth.

Verified empirically before adopting: with `--site-lat 41.979974
--site-lon -87.909816` and a `url_template` pointed at a local listener,
adsb-tui requested `/point/41.979974/-87.909816/20`. The flags drive the
data query, not merely the map centre, and the config file is never
written.

Retargeting restarts both panes. adsb-tui loses its trails and squelch
reconnects its streams — both recover in about a second, and the
alternative (an IPC channel into a running Textual app) is not worth that.

## Persistence

`~/.local/state/kcgx/airport` holds **one line: the ICAO.**

Coordinates are re-resolved from the CSV at launch, so there is exactly one
source of truth and no possibility of stale coordinates outliving a dataset
update.

Resolution order at startup:

1. the state file
2. `icao` in `~/.config/squelch/squelch.toml`
3. `KPDX`

An ICAO in the state file that is no longer in the dataset falls back to
the next source and warns, rather than failing to launch.

There is no "go home" command. Typing the home ICAO into the picker is
already the shortest path to it.

## Error handling

### squelch must not play the wrong airport

Today, when `load_feeds` cannot reach LiveATC and has no cache, it falls
back to `Feed(ident=config.feed)` — `kpdx3_twr`. Switch to KORD, hit a 403,
and the result is Portland tower audio under a Chicago radar, with the
header reading `KORD`. Confidently wrong is worse than silent.

Fix: use the `config.feed` fallback only when that ident belongs to the
requested airport (`kpdx3_twr` starts with `kpdx`). Otherwise open with no
feeds, distinguishing the two reasons there might be none:

```
KORD — could not reach LiveATC's listing; press f to retry
KBDN — LiveATC has no feeds for this airport
```

An empty pane is the correct answer here. The first case is worth retrying
and the second is not, so the pane should not describe them the same way.

### A first visit has no cache

LiveATC's listing page sits behind Cloudflare bot protection that refuses
roughly three requests in four. At the current five attempts that is about
76% success, so roughly one cold switch in four lands on an empty pane.

Mitigation: raise the attempt count when there is no cached list for that
ICAO at all — eight attempts reaches about 90%. Retries stay bounded, and
the pane says it is still trying rather than sitting blank.

Every subsequent visit to that airport reads the week-long cache and needs
no request.

### Arriving at a new airport

Prefer a tower feed when unmuting. Currently the first listed feed is
unmuted when the configured ident matches nothing, which at a new airport
is arbitrary. Preferring an ident or label mentioning tower makes a switch
land on the interesting channel.

No effect at the home airport, where the configured feed still wins.

## Testing

**`test_airports.py`** — ranking order, accent and dash folding, multi-token
AND, empty results. Plus a guard that the committed CSV parses and contains
known ICAOs, so a bad regeneration fails loudly.

**`test_airport_picker.py`** — via `run_test`: typing filters the list,
`enter` yields the airport, `esc` yields nothing, the no-match state
renders.

**`test_kcgx_launcher.py`** — build a real session on a private socket, run
the retarget, and assert each pane's actual `#{pane_start_command}` carries
the new coordinates and ICAO. Also: launch and retarget produce identical
commands; state file round-trips; an unknown ICAO falls back.

This last one is the point. Every kcgx bug so far passed its tests because
the tests exercised a convenient configuration instead of the real one.
Asserting on `pane_start_command` from a live server tests what actually
runs.

**`test_main.py`** — the cross-airport fallback fix and the tower
preference.

## Out of scope

- Any airport search inside squelch itself. squelch takes an ICAO; the
  parent decides what it is.
- Location-biased ranking. Deterministic order is easier to trust.
- Retargeting without restarting the panes.
- Airports smaller than medium.
