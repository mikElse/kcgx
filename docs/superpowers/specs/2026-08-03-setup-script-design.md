# One script that ends with the cockpit open

*2026-08-03*

## The problem

Handing kcgx to somebody else does not currently work.

`README.md` says the install is `cd squelch && uv sync`, which is wrong on
three counts: the repo is `kcgx`, not `squelch`; `uv sync` installs the
Python dependencies but not the three binaries the cockpit needs; and
nothing tells you that `bin/kcgx` has to be linked onto your `PATH` before
`kcgx` is a command you can type.

The real dependency surface is wider than the README admits:

| Needed | Why | Checked today |
|---|---|---|
| `uv` | runs everything; also supplies Python 3.14 | no |
| `tmux` | `bin/kcgx` builds the pane layout with it | yes, at line 65 |
| `ffmpeg` | decodes every feed to PCM | yes, in `squelch/__main__.py` |
| `adsb-tui` | the radar pane | **no** |
| `bin/kcgx` on `PATH` | so `kcgx` is a command | no |

Two of those fail silently. A missing `adsb-tui` gives a cockpit whose
left two-thirds is a dead pane, and an unlinked `bin/kcgx` gives no cockpit
at all with no explanation.

`adsb-tui` also needs a *data source*. Its default is
`http://adsb.local/data/aircraft.json` — a receiver on your own network.
Anybody without one gets an empty radar even after installing it
correctly.

## What we are building

`setup.sh` at the repo root. Run it, answer one prompt, and the cockpit
opens. Run it again and it is a no-op that opens the cockpit — every phase
is idempotent, because the second run is the one people do when they think
something went wrong.

Audience is a friend on macOS. The script explains itself, asks before
touching anything system-wide, and fails with a remediation rather than a
stack trace.

## Findings that shaped this

These were measured on 2026-08-03 rather than assumed, and they are the
reason the design is as small as it is.

**`adsb-tui` needs no `aircraft.json`.** The first instinct was to have
setup synthesise one, or proxy a public API into tar1090 shape. It is
unnecessary: `adsb-tui` already parses the ADSBExchange v2 response that
the public aggregators return, despite that shape using a top-level `ac`
key where tar1090 uses `aircraft`. Verified by running the real binary
against `api.adsb.lol` in an isolated tmux socket — 119 aircraft, radar
drawing blips. So setup writes a config file and nothing more.

**The provider is `airplanes.live`.** Both free keyless aggregators were
probed at a 2-second refresh:

| Provider | Result |
|---|---|
| `api.airplanes.live/v2/point/{lat}/{lon}/{range}` | `OK` |
| `api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{range}` | `ERR 429` |
| `api.adsb.one` | HTTP 403 |

Both are documented as 1 request/second; only airplanes.live tolerated it
in practice. Its path shape also maps exactly onto `adsb-tui`'s
`url_template` placeholders, and `bin/kcgx` already passes
`--site-lat`/`--site-lon` per launch, so the config needs no coordinates.

**`adsb-tui` is [`j4v3l/ADS-B_TUI`](https://github.com/j4v3l/ADS-B_TUI).**
Release v0.2.1 ships `adsb-tui-macos-arm64.tar.gz` (3 MB),
`adsb-tui-macos-x64.tar.gz`, and a Linux x64 build. The copy on the
original development machine is 10 MB — an unstripped local
`cargo build --release` — which is why no `cargo install` record exists
and why the project was initially hard to identify.

Its licence is a custom **"ADS-B TUI Non-Commercial License"**, not
OSI-approved. Setup therefore downloads it from upstream and never
redistributes it, and prints the restriction where the user will see it.

**Setup must not need a Rust toolchain.** The development machine had
`rust`, `llvm`, `z3`, `libgit2`, `libssh2`, `llhttp`, `pkgconf` and
Homebrew's `python@3.14` installed on 2026-08-01 — **4,103 MB** of build
toolchain, present for exactly one reason: `adsb-tui` was compiled from
source because the prebuilt releases had not been found yet. (That is also
why the binary there is 10 MB rather than the release's 3 MB — an
unstripped local build.) `brew uses --installed python@3.14` reports
`llvm rust speedtest-cli`, confirming Homebrew's Python is not a kcgx
dependency at all; it arrived underneath Rust.

Downloading the release costs 3 MB and no toolchain. Nothing in setup may
invoke `cargo`.

**`.python-version` stays, and is not the pyenv trap it looks like.**
Inside the repo, `python --version` fails on any machine where pyenv's
shims precede `uv` on `PATH`:

    pyenv: version `3.14' is not installed (set by .../.python-version)

The obvious fix — delete the file, since `requires-python = ">=3.14"` in
`pyproject.toml` already governs resolution — was tested and does not
work. With the file removed, `uv sync` still resolves 3.14.6 correctly,
but bare `python` fails anyway with `pyenv: python: command not found`,
because pyenv's global is `system` and macOS ships no `python` there. The
file is redundant for uv and irrelevant to the failure; removing it only
replaces an error naming the offending file with one that names nothing.

So the trap is real but belongs to the user's `PATH`, not to the repo.
Setup detects the condition and says so, rather than pretending to fix
it. Every documented command already goes through `uv run`, which ignores
pyenv entirely.

**The ambience stems are out of scope.** `tools/fetch_ambience.py` exists,
but nothing under `src/` reads `assets/` — the bed is still only
`AMBIENCE-PLAN.md`. Fetching 3.4 MB of audio that no code loads would be
setup doing work for a feature that does not exist. When plan E lands, it
adds its own step.

## The five phases

Each prints what it is about to do before doing it.

**1. Preflight.** Establish the platform (`uname -s`, `uname -m`) and probe
for `uv`, `ffmpeg`, `tmux` (**and its version — `bin/kcgx` refuses below
3.1**), `curl`, `adsb-tui`, and whether `~/.local/bin` is on `PATH`. Print
the full table of found/missing *before* changing anything, so the whole
picture is visible up front rather than revealed one failure at a time.
Nothing is modified in this phase.

Two advisory checks that are not pass/fail:

- **pyenv shims ahead of `uv`.** If `command -v python` resolves inside a
  `.pyenv/shims` directory, note that bare `python` will not work in this
  repo and that every documented command uses `uv run`. This is a
  property of the user's `PATH`, not something setup should change.
- **Terminal width.** `bin/kcgx` refuses below 100 columns. Better to say
  so during setup than at the moment the cockpit was supposed to open.

**2. Prerequisites, after one prompt.** A single `[y/N]` listing exactly
what will be installed. `ffmpeg` and `tmux` via Homebrew; `uv` via its
official installer script.

If Homebrew itself is missing, the script stops and prints the one-line
install command rather than running it. Installing a package manager
unattended on somebody's machine is more than a setup script for a hobby
project has any business doing.

Declining the prompt is not an error. The script continues to phase 3, and
whether it ultimately launches depends on *which* dependency is still
missing — see the launch gate below. Declining is how you inspect what
setup would do without letting it do it.

**3. Python dependencies.** `uv sync` in the repo root. `uv` provisions
Python 3.14 itself, so the interpreter is not a separate step.

**4. Wiring.** Three idempotent actions:

- Symlink `bin/kcgx` → `~/.local/bin/kcgx`. `~/.local/bin` rather than
  `~/bin`: it is the XDG convention and is already on `PATH` on the
  development machine, whereas `~/bin` is not. Created if the directory
  does not exist. If the link exists and points at this repo, leave it. If
  it exists and points elsewhere, stop and say so rather than overwrite
  it.

  **`kcgx` being resolvable by name is load-bearing, not a convenience.**
  `kcgx.tmux.conf` binds `Ctrl-b a` to
  `display-popup -E "kcgx go"` — resolved by *name*, through a shell,
  against the **tmux server's** environment. Without `~/.local/bin` on
  `PATH`, the cockpit opens correctly and the airport picker then fails
  silently, which is worse than not launching at all.

  Worse, the tmux server captures its environment when it *starts*. Adding
  the directory to a shell profile after a server is already running does
  not reach the popup until the server is restarted.

  So this is a warning with teeth: setup prints the `export PATH=...` line
  and explicitly says `Ctrl-b a` will not work until it is applied and any
  running tmux server is restarted. It still does not edit the profile
  itself — silently rewriting someone's shell config is beyond what a
  setup script for a hobby project should do.
- Install `adsb-tui` into `~/.local/bin` from the v0.2.1 release matching
  the detected architecture, after printing the licence notice. Skipped
  entirely if it is already on `PATH`.
- Write `~/.config/ads-b-tui/adsb-tui.toml` **only if it does not exist**,
  containing `url_template` for airplanes.live and `refresh_secs = 2`. An
  existing config is never modified — `adsb-tui` rewrites that file with
  its own defaults on exit, so it is the user's, not ours.

**5. Launch.** A gate, then `exec` the launcher by absolute path — not by
command name, so a `PATH` the user has not reloaded yet cannot stop the
cockpit opening on the first run.

The gate re-checks the fatal dependencies from phase 1. If any is still
missing — because Homebrew was absent, or the prompt was declined — the
script stops here and prints the list with the command that would fix it,
rather than launching into a failure.

## Failure and degradation

`set -euo pipefail`. Every failure names the phase and what to do about
it.

The distinction that matters is fatal versus degraded:

- **Fatal:** no `tmux`, no `ffmpeg`, `uv sync` failing, or the symlink
  target being occupied by something else. Without these there is either
  no cockpit or no audio, so the script stops and explains.
- **Degraded:** `adsb-tui` missing, or its download failing. The cockpit
  still opens with working audio and status panes. The script says the
  radar is unavailable and how to add it later, then launches anyway.

The degraded path is the point. "Run this and kcgx opens" has to remain
true on a machine where the one non-installable dependency did not
install.

## Testing

The launcher's existing seams make this testable without installing
anything or touching the network, matching how `tests/test_kcgx_launcher.py`
already fakes `tmux` through `PATH`.

`setup.sh --check` runs phase 1 and exits, printing the detection table.
That gives the suite a way to assert detection logic directly.

Everything with an external effect goes through a named shell function —
`have_command`, `brew_install`, `download_release`, `write_adsb_config`,
`link_launcher` — so a test can stub it. Tests cover:

- the detection table against a `PATH` stubbed to contain, and to lack,
  each dependency;
- both architectures selecting the right release asset;
- an existing `adsb-tui.toml` being left byte-identical;
- an existing correct symlink being a no-op, and a symlink pointing
  elsewhere being fatal;
- a failed `adsb-tui` download still reaching the launch phase;
- a missing `tmux` being stopped by the launch gate;
- a `tmux` older than 3.1 being stopped by the launch gate;
- declining the install prompt with everything already present still
  launching;
- a `PATH` without `~/.local/bin` producing the `Ctrl-b a` warning, and
  one with it producing no warning;
- a `PATH` whose `python` resolves into `.pyenv/shims` producing the
  advisory, and one that does not staying silent;
- setup never invoking `cargo` — asserted directly, because building
  `adsb-tui` from source is what dragged 4 GB of toolchain onto the
  development machine and the release download exists to prevent it.

No test runs Homebrew, downloads a release, or opens a socket.

## Also in scope

`README.md`'s "Install" section is replaced with `./setup.sh`. It is the
source of the wrong instructions, so leaving it would mean shipping two
contradictory answers to the same question.

## Out of scope

- Linux and Intel-Mac support beyond selecting the right release asset.
  The design detects the architecture because the release provides one,
  not because the other paths can be tested here.
- Installing Homebrew.
- Fetching the ambience stems.
- Any change to `bin/kcgx` itself. Setup wires the launcher; it does not
  modify it.
