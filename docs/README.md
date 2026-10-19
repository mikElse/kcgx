# Design docs

Each piece of work gets a **spec** (what and why, agreed before any code) and a
**plan** (task-by-task TDD steps, agreed before implementation). Specs live in
`superpowers/specs/`, plans in `superpowers/plans/`.

## Web cockpit: phases A, B and C built

The cockpit as a local web app: audio stays on the server, the browser is
the display and the controls, and our own vector radar in a WarGames style
replaces `adsb-tui`. Built on `feat/web-cockpit`.

Start with the [spec](superpowers/specs/2026-10-18-web-cockpit-design.md).

| Phase | What | Plan | State |
|---|---|---|---|
| **A** | extract `Cockpit` from `SquelchApp`; terminal squelch runs on it | [plan](superpowers/plans/2026-10-18-web-cockpit-a-controller.md) | built |
| **B** | server, routes, WebSocket, levels loop | [plan](superpowers/plans/2026-10-18-web-cockpit-b-server.md) | built; audio confirmed on the Mac |
| **C** | page: status, feed stack, meters, config, feed picker, log | [plan](superpowers/plans/2026-10-19-web-cockpit-c-page.md) | built; checked by hand on the Mac |
| **D** | radar: geodata, vector renderer, poller, palettes, display effects | | not started |
| **E** | launcher, `setup.sh`, README; remove tmux, adsb-tui, Textual UI | | not started |

## Audio pane upgrades — planned, not started

A batch of upgrades to `squelch`. Decomposed into four phases because the UI
work is an increment on the existing design while the audio work replaces it:
today each feed owns its own PortAudio stream and CoreAudio mixing those twelve
streams is the entire mixer, which no bus, pan, or shared reverb can be built
on.

Start with the [batch overview](superpowers/specs/2026-08-02-audio-pane-upgrades-design.md).

| Phase | Spec | Plan | Tasks |
|---|---|---|---|
| **A** — row restructure | [spec](superpowers/specs/2026-08-02-audio-pane-rows-design.md) | [plan](superpowers/plans/2026-08-02-audio-pane-a-rows.md) | 10 |
| **B** — activity ranking | [spec](superpowers/specs/2026-08-02-audio-pane-activity-design.md) | [plan](superpowers/plans/2026-08-02-audio-pane-b-activity.md) | 7 |
| **C** — theme sync | [spec](superpowers/specs/2026-08-02-audio-pane-theme-design.md) | [plan](superpowers/plans/2026-08-02-audio-pane-c-theme.md) | 6 |
| **D** — mixing engine | [spec](superpowers/specs/2026-08-02-audio-mixer-design.md) | [plan](superpowers/plans/2026-08-02-audio-pane-d-mixer.md) | 10 |

**Build order: A → B → C → D.** B and C both depend on A's widgets; C supplies
the palettes B's meter gradient reads. D is independent of all three and could
be built in parallel — its only contact with the UI is the meaning of the `[A]`
control that A introduces.

Read before executing:

- **D supersedes part of B.** B routes the meter's level through the pipeline;
  D moves it to a polled post-compression read, because compression happens
  inside the audio callback. B's *activity* tap is pre-compression and survives
  intact. D's Tasks 6 and 9 name the exact symbols and tests to delete.
- **D adds `numpy`**, the batch's only new runtime dependency. A, B, and C add
  none.
- **D's Task 10 has a manual step** needing real hardware and a live airport.
  Everything else in all four plans runs headless.

## Earlier work — built

| Spec | Plan |
|---|---|
| [squelch](superpowers/specs/2026-08-02-squelch-design.md) | [plan](superpowers/plans/2026-08-02-squelch.md) |
| [airport search](superpowers/specs/2026-08-02-airport-search-design.md) | [plan](superpowers/plans/2026-08-02-airport-search.md) |

The squelch spec still describes live transcription. That was removed after it
was written — see "History" in the top-level `README.md`. The spec is kept as
the record of the original design, not as a description of the current code.
