# Setup Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `setup.sh` at the repo root that installs every dependency, wires
the launcher onto `PATH`, and ends by opening the cockpit.

**Architecture:** One bash script, five phases, every phase idempotent.
Each externally-visible effect goes through a named shell function so tests
can replace it. Tests drive the real script as a subprocess with a stubbed
`PATH`, exactly as `tests/test_kcgx_launcher.py` already drives `bin/kcgx` —
no test installs software, downloads anything, or opens a socket.

**Tech Stack:** bash, pytest 9.1.1, the `uv` toolchain. No new Python
dependencies.

**Spec:** `docs/superpowers/specs/2026-08-03-setup-script-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **macOS only.** Architecture is detected because the upstream release
  provides both, not because other platforms are supported.
- **Never invoke `cargo`.** Building `adsb-tui` from source drags in
  4,103 MB of Rust toolchain for a 3 MB binary. Task 7 asserts this.
- **Never install Homebrew.** If absent, print the one-line command and
  stop.
- **Never edit a shell profile.** Print the `export` line instead.
- **Never modify an existing `~/.config/ads-b-tui/adsb-tui.toml`.**
  `adsb-tui` rewrites that file with its own defaults on exit, so it is
  the user's.
- **`tmux` 3.1 or newer**, matching `bin/kcgx:69`.
- **`adsb-tui` pinned to `v0.2.1`**, downloaded from upstream, never
  redistributed. Licence is a custom non-commercial one.
- **Radar config is exactly** `url_template =
  "https://api.airplanes.live/v2/point/{lat}/{lon}/{range_nm}"` and
  `refresh_secs = 2`. No `site_lat`/`site_lon` — `bin/kcgx` passes those
  per launch.
- **Idempotent.** Re-running is always safe and always ends at the same
  place.
- **`adsb-tui` is degraded, not fatal.** Its absence must never stop the
  cockpit opening.

## Test seams

`setup.sh` reads these so the suite never touches the real machine. All
default to production behaviour when unset.

| Variable | Default | Purpose |
|---|---|---|
| `HOME` | inherited | all install paths derive from it |
| `KCGX_SETUP_YES` | unset | non-empty skips the install prompt |
| `KCGX_SETUP_NO_LAUNCH` | unset | non-empty stops before `exec` |
| `KCGX_SETUP_RELEASE_URL` | GitHub releases base | where the tarball comes from |

`--check` runs phase 1 and exits 0.

## File structure

| File | Responsibility |
|---|---|
| `setup.sh` (create) | the whole script; ~200 lines of bash |
| `tests/test_setup.py` (create) | drives `setup.sh` as a subprocess |
| `README.md` | **already done** in commits `d87103d` and `b3d854f`; no task needed |

---

### Task 1: Skeleton and the preflight table

**Files:**
- Create: `setup.sh`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: nothing
- Produces: `have_command <name>` (exit 0 if on `PATH`); `REPO` (absolute
  repo root); `ARCH` (`macos-arm64` or `macos-x64`); `--check` exiting 0
  after printing the table

- [ ] **Step 1: Write the failing test**

```python
"""The kcgx setup script.

Drives the real setup.sh as a subprocess with a stubbed PATH, the same way
tests/test_kcgx_launcher.py drives bin/kcgx. Nothing here installs
software, downloads a file, or opens a socket.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SETUP = REPO / "setup.sh"

# Every tool setup.sh itself needs in order to run at all.
BASE_TOOLS = ("bash", "sh", "env", "uname", "grep", "awk", "sed", "head",
              "dirname", "basename", "pwd", "mkdir", "ln", "rm", "cat",
              "printf", "tr", "sort", "id", "stty", "tar", "chmod")


def stub_path(tmp_path, *, tools=(), scripts=None):
    """A directory to use as the entire PATH.

    `tools` are symlinked from the real system; `scripts` is a mapping of
    name -> shell source for fakes. Anything not named is absent, which is
    how "ffmpeg is missing" is expressed.
    """
    d = tmp_path / "stub_bin"
    d.mkdir(exist_ok=True)
    for tool in (*BASE_TOOLS, *tools):
        found = shutil.which(tool)
        if found and not (d / tool).exists():
            (d / tool).symlink_to(found)
    for name, body in (scripts or {}).items():
        p = d / name
        p.write_text(body)
        p.chmod(0o755)
    return d


def run_setup(tmp_path, path_dir, *args, **env):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    environ = {
        "PATH": str(path_dir),
        "HOME": str(home),
        "KCGX_SETUP_NO_LAUNCH": "1",
    }
    environ.update({k: str(v) for k, v in env.items()})
    return subprocess.run(
        [str(SETUP), *args],
        env=environ, capture_output=True, text=True, timeout=120,
    )


def test_check_reports_every_dependency(tmp_path):
    """The table is the whole point of --check: one look, whole picture."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, "--check")
    assert result.returncode == 0
    for tool in ("uv", "ffmpeg", "tmux", "curl", "adsb-tui"):
        assert tool in result.stdout, f"{tool} missing from the table"


def test_check_changes_nothing(tmp_path):
    """Preflight is a probe. It must not create the symlink or the config."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    run_setup(tmp_path, path_dir, "--check")
    home = tmp_path / "home"
    assert not (home / ".local" / "bin" / "kcgx").exists()
    assert not (home / ".config" / "ads-b-tui" / "adsb-tui.toml").exists()


def test_a_missing_tool_is_reported_as_missing(tmp_path):
    """ffmpeg absent from PATH — the table must say so, not claim success."""
    path_dir = stub_path(tmp_path, tools=("uv", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, "--check")
    ffmpeg_line = [l for l in result.stdout.splitlines() if "ffmpeg" in l]
    assert ffmpeg_line, "no ffmpeg row at all"
    assert "missing" in ffmpeg_line[0].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -v`
Expected: FAIL — `setup.sh` does not exist, so `subprocess.run` raises
`FileNotFoundError`.

- [ ] **Step 3: Write the minimal implementation**

Create `setup.sh` and `chmod +x setup.sh`:

```bash
#!/usr/bin/env bash
# setup.sh — install everything kcgx needs, wire it up, and open the cockpit.
#
# Idempotent: running it twice is safe and ends in the same place. Every
# phase says what it is about to do before doing it.
#
# Test seams (all default to production behaviour when unset):
#   KCGX_SETUP_YES         non-empty skips the install prompt
#   KCGX_SETUP_NO_LAUNCH   non-empty stops before exec'ing the launcher
#   KCGX_SETUP_RELEASE_URL base URL for the adsb-tui release tarball

set -euo pipefail

REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ADSB_VERSION="v0.2.1"
RELEASE_URL="${KCGX_SETUP_RELEASE_URL:-https://github.com/j4v3l/ADS-B_TUI/releases/download}"
PREFIX="$HOME/.local/bin"
ADSB_CONFIG="$HOME/.config/ads-b-tui/adsb-tui.toml"
MIN_COLS=100

say()  { printf '%s\n' "$*"; }
warn() { printf 'setup: %s\n' "$*" >&2; }
die()  { printf 'setup: %s\n' "$*" >&2; exit 1; }

have_command() { command -v "$1" >/dev/null 2>&1; }

# macos-arm64 / macos-x64, matching the upstream release asset names.
detect_arch() {
    case "$(uname -m)" in
        arm64|aarch64) printf 'macos-arm64' ;;
        x86_64)        printf 'macos-x64' ;;
        *)             printf 'unsupported' ;;
    esac
}

# tmux 3.1+ is required by bin/kcgx:69 for `split-window -l <cells>`.
tmux_new_enough() {
    local version
    have_command tmux || return 1
    version="$(tmux -V | grep -oE '[0-9]+\.[0-9]+' | head -1)"
    awk -v v="$version" 'BEGIN {
        split(v, p, ".");
        exit !(p[1] > 3 || (p[1] == 3 && p[2] >= 1))
    }'
}

row() { printf '  %-12s %s\n' "$1" "$2"; }

preflight() {
    ARCH="$(detect_arch)"
    say "kcgx setup"
    say ""
    say "Checking what you have:"
    have_command uv     && row uv "found" || row uv "missing"
    have_command ffmpeg && row ffmpeg "found" || row ffmpeg "missing"
    if have_command tmux; then
        if tmux_new_enough; then
            row tmux "found"
        else
            row tmux "too old (needs 3.1+)"
        fi
    else
        row tmux "missing"
    fi
    have_command curl     && row curl "found" || row curl "missing"
    have_command adsb-tui && row adsb-tui "found" || row adsb-tui "missing (optional)"
    say ""
}

if [ "${1:-}" = "--check" ]; then
    preflight
    exit 0
fi

preflight
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
chmod +x setup.sh
git add setup.sh tests/test_setup.py
git commit -m "feat(setup): preflight table behind --check"
```

---

### Task 2: Advisory checks — pyenv shims and terminal width

**Files:**
- Modify: `setup.sh` (extend `preflight`)
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `preflight`, `have_command`, `row` from Task 1
- Produces: advisory lines in the `--check` output; no new exit codes —
  advisories never change the exit status

- [ ] **Step 1: Write the failing test**

```python
def test_pyenv_shims_are_flagged(tmp_path):
    """Bare `python` fails inside this repo when pyenv shims come first.

    Not setup's to fix -- it belongs to the user's PATH -- but silently
    letting them hit `pyenv: version 3.14 is not installed` is worse.
    """
    shims = tmp_path / ".pyenv" / "shims"
    shims.mkdir(parents=True)
    fake_python = shims / "python"
    fake_python.write_text("#!/bin/sh\nexit 1\n")
    fake_python.chmod(0o755)
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))

    result = subprocess.run(
        [str(SETUP), "--check"],
        env={
            "PATH": f"{shims}:{path_dir}",
            "HOME": str(tmp_path / "home"),
            "KCGX_SETUP_NO_LAUNCH": "1",
        },
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, "an advisory must not fail the check"
    assert "pyenv" in result.stdout


def test_no_pyenv_no_advisory(tmp_path):
    """The guard must be capable of staying quiet, or it says nothing."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, "--check")
    assert "pyenv" not in result.stdout


def test_a_narrow_terminal_is_flagged(tmp_path):
    """bin/kcgx refuses below 100 columns. Better said now than at launch."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, "--check", COLUMNS="80")
    assert result.returncode == 0
    assert "100" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -k "pyenv or narrow" -v`
Expected: FAIL — "pyenv" is not in stdout; "100" is not in stdout.

- [ ] **Step 3: Write the implementation**

In `setup.sh`, add these two functions above `preflight`:

```bash
# Advisory only. Both describe the user's environment rather than anything
# setup installs, so neither changes the exit status.

check_pyenv() {
    local python_path
    python_path="$(command -v python 2>/dev/null || true)"
    case "$python_path" in
        */.pyenv/shims/*)
            say "  note: pyenv shims come before uv on your PATH, so bare"
            say "        \`python\` will not work inside this repo. That is"
            say "        expected -- every kcgx command uses \`uv run\`,"
            say "        which ignores pyenv entirely."
            ;;
    esac
}

check_width() {
    local cols=""
    if winsize="$(stty size 2>/dev/null </dev/tty)"; then
        cols="${winsize##* }"
    elif [ -n "${COLUMNS:-}" ]; then
        cols="$COLUMNS"
    fi
    case "$cols" in
        ''|*[!0-9]*) return 0 ;;
    esac
    if [ "$cols" -lt "$MIN_COLS" ]; then
        say "  note: this terminal is $cols columns; kcgx needs $MIN_COLS."
    fi
}
```

Then call them at the end of `preflight`, before its trailing `say ""`:

```bash
    check_pyenv
    check_width
    say ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add setup.sh tests/test_setup.py
git commit -m "feat(setup): advise on pyenv shims and a narrow terminal"
```

---

### Task 3: Install prerequisites, after one prompt

**Files:**
- Modify: `setup.sh`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `have_command`, `tmux_new_enough`, `say`, `die`
- Produces: `missing_formulae` (echoes the Homebrew formulae still
  needed); `install_prerequisites` (prompts once, then installs)

- [ ] **Step 1: Write the failing test**

```python
BREW_RECORDER = """#!/bin/sh
echo "$@" >> "$BREW_LOG"
exit 0
"""


def test_missing_tools_are_installed_via_brew(tmp_path):
    log = tmp_path / "brew.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "curl"),
        scripts={"brew": BREW_RECORDER},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", BREW_LOG=str(log))
    assert log.exists(), "brew was never called"
    calls = log.read_text()
    assert "ffmpeg" in calls
    assert "tmux" in calls


def test_nothing_is_installed_when_everything_is_present(tmp_path):
    """Idempotence: the second run must be a no-op."""
    log = tmp_path / "brew.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"),
        scripts={"brew": BREW_RECORDER},
    )
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", BREW_LOG=str(log))
    assert not log.exists(), "brew ran with nothing to install"


def test_no_homebrew_stops_with_the_install_line(tmp_path):
    """Installing a package manager unattended is beyond setup's remit."""
    path_dir = stub_path(tmp_path, tools=("uv", "curl"))  # no brew, no ffmpeg
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "brew.sh" in combined, "the user needs the actual install command"


def test_declining_the_prompt_installs_nothing(tmp_path):
    log = tmp_path / "brew.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "curl"),
        scripts={"brew": BREW_RECORDER},
    )
    result = subprocess.run(
        [str(SETUP)], input="n\n",
        env={
            "PATH": str(path_dir), "HOME": str(tmp_path / "home"),
            "KCGX_SETUP_NO_LAUNCH": "1", "BREW_LOG": str(log),
        },
        capture_output=True, text=True, timeout=120,
    )
    assert not log.exists(), "declining still installed something"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -k "brew or homebrew or declining" -v`
Expected: FAIL — no `brew.log`, and the no-Homebrew case exits 0.

- [ ] **Step 3: Write the implementation**

Append to `setup.sh`:

```bash
# Homebrew formulae still needed, space separated. tmux counts as missing
# when it is present but older than 3.1 -- upgrading is the same command.
missing_formulae() {
    local needed=""
    have_command ffmpeg || needed="$needed ffmpeg"
    tmux_new_enough || needed="$needed tmux"
    printf '%s' "${needed# }"
}

install_prerequisites() {
    local needed reply
    needed="$(missing_formulae)"

    if [ -z "$needed" ] && have_command uv; then
        return 0
    fi

    say "Setup wants to install:"
    [ -n "$needed" ] && say "  via Homebrew:  $needed"
    have_command uv || say "  via astral.sh: uv"
    say ""

    if [ -z "${KCGX_SETUP_YES:-}" ]; then
        printf 'Proceed? [y/N] '
        # From stdin, not /dev/tty. setup.sh is always a file, so stdin is
        # free -- and a /dev/tty read is untestable: under pytest there is
        # no controlling terminal, so it would fail open and "decline"
        # regardless of what the test typed, making the decline test pass
        # for the wrong reason.
        read -r reply || reply=""
        case "$reply" in
            [yY]|[yY][eE][sS]) ;;
            *) say "Nothing installed."; return 0 ;;
        esac
    fi

    if [ -n "$needed" ]; then
        have_command brew || die \
"Homebrew is needed to install:$needed
Install it first, then run this again:
  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
See https://brew.sh"
        # Word splitting is intended: $needed is a list of formulae.
        # shellcheck disable=SC2086
        brew install $needed
    fi

    if ! have_command uv; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
        PATH="$HOME/.local/bin:$PATH"
    fi
}

install_prerequisites
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add setup.sh tests/test_setup.py
git commit -m "feat(setup): install prerequisites behind one prompt"
```

---

### Task 4: `uv sync`

**Files:**
- Modify: `setup.sh`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `REPO`, `die`
- Produces: `sync_project` — runs `uv sync` in `$REPO`, fatal on failure

- [ ] **Step 1: Write the failing test**

```python
UV_RECORDER = """#!/bin/sh
echo "$@" >> "$UV_LOG"
exit 0
"""

UV_FAILS = """#!/bin/sh
echo "resolution impossible" >&2
exit 1
"""


def test_uv_sync_runs_in_the_repo(tmp_path):
    log = tmp_path / "uv.log"
    path_dir = stub_path(
        tmp_path, tools=("ffmpeg", "tmux", "curl"),
        scripts={"uv": UV_RECORDER},
    )
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", UV_LOG=str(log))
    assert "sync" in log.read_text()


def test_a_failing_uv_sync_is_fatal(tmp_path):
    """Without dependencies there is no cockpit; carrying on would lie."""
    path_dir = stub_path(
        tmp_path, tools=("ffmpeg", "tmux", "curl"),
        scripts={"uv": UV_FAILS},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert result.returncode != 0
    assert "uv sync" in result.stdout + result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -k "uv_sync" -v`
Expected: FAIL — `uv.log` does not exist.

- [ ] **Step 3: Write the implementation**

Append to `setup.sh`:

```bash
sync_project() {
    say "Installing Python dependencies (uv provides Python 3.14 itself)..."
    uv sync --project "$REPO" || die "uv sync failed; nothing was wired up."
}

sync_project
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add setup.sh tests/test_setup.py
git commit -m "feat(setup): install the Python dependencies"
```

---

### Task 5: Link the launcher, and warn about `PATH` with teeth

**Files:**
- Modify: `setup.sh`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `REPO`, `PREFIX`, `say`, `die`
- Produces: `link_launcher` — creates `$PREFIX/kcgx` → `$REPO/bin/kcgx`

- [ ] **Step 1: Write the failing test**

```python
def test_the_launcher_is_linked_not_copied(tmp_path):
    """bin/kcgx resolves its own repo root through the symlink; a copy
    would resolve REPO to the link's directory and break."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    link = tmp_path / "home" / ".local" / "bin" / "kcgx"
    assert link.is_symlink(), "must be a symlink"
    assert link.resolve() == (REPO / "bin" / "kcgx").resolve()


def test_relinking_is_a_no_op(tmp_path):
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    second = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert second.returncode == 0
    link = tmp_path / "home" / ".local" / "bin" / "kcgx"
    assert link.resolve() == (REPO / "bin" / "kcgx").resolve()


def test_a_foreign_kcgx_is_never_overwritten(tmp_path):
    """Someone else's kcgx on PATH is theirs. Stop, do not clobber."""
    home = tmp_path / "home"
    prefix = home / ".local" / "bin"
    prefix.mkdir(parents=True)
    stranger = tmp_path / "other-kcgx"
    stranger.write_text("#!/bin/sh\nexit 0\n")
    stranger.chmod(0o755)
    (prefix / "kcgx").symlink_to(stranger)

    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert result.returncode != 0
    assert (prefix / "kcgx").resolve() == stranger.resolve(), "it clobbered it"


def test_a_path_without_the_prefix_warns_about_the_picker(tmp_path):
    """Ctrl-b a is bound to `display-popup -E "kcgx go"`, resolved by name
    through the tmux server's environment. Without the prefix on PATH the
    cockpit opens and the picker silently does nothing."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    combined = result.stdout + result.stderr
    assert "PATH" in combined
    assert "Ctrl-b a" in combined, "the consequence must be named"


def test_a_path_with_the_prefix_does_not_warn(tmp_path):
    home = tmp_path / "home"
    prefix = home / ".local" / "bin"
    prefix.mkdir(parents=True)
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1",
        PATH=f"{prefix}:{path_dir}",
    )
    assert "Ctrl-b a" not in result.stdout + result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -k "link or path_with or path_without or foreign" -v`
Expected: FAIL — no symlink is created.

- [ ] **Step 3: Write the implementation**

Append to `setup.sh`:

```bash
link_launcher() {
    local target="$REPO/bin/kcgx" link="$PREFIX/kcgx"
    mkdir -p "$PREFIX"

    if [ -L "$link" ]; then
        # Already ours? Nothing to do. Somebody else's? Never clobber it.
        #
        # A plain string compare against what we would write, deliberately:
        # resolving the link through `cd`/`pwd` inside a test is a command
        # substitution that can fail under `set -e`, and anything that does
        # not match exactly is treated as foreign. Conservative in the safe
        # direction -- the cost of a false "foreign" is one message, the
        # cost of a false "ours" is destroying somebody's launcher.
        if [ "$(readlink "$link")" = "$target" ]; then
            say "Launcher already linked."
        else
            die "$link already exists and points somewhere else.
Remove it yourself if you want setup to manage it."
        fi
    elif [ -e "$link" ]; then
        die "$link already exists and is not a symlink.
Remove it yourself if you want setup to manage it."
    else
        ln -s "$target" "$link"
        say "Linked $link -> $target"
    fi

    case ":$PATH:" in
        *":$PREFIX:"*) ;;
        *)
            say ""
            say "WARNING: $PREFIX is not on your PATH."
            say "  Add this to your shell profile:"
            say "      export PATH=\"\$HOME/.local/bin:\$PATH\""
            say ""
            say "  This is not just about typing \`kcgx\`. Ctrl-b a (the"
            say "  airport picker) is bound to \`display-popup -E \"kcgx go\"\`,"
            say "  which resolves kcgx by name through the tmux server's own"
            say "  environment -- so without this the cockpit opens fine and"
            say "  the picker silently does nothing."
            say ""
            say "  A running tmux server captured its environment when it"
            say "  started, so restart it (kcgx stop) after changing PATH."
            say ""
            ;;
    esac
}

link_launcher
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add setup.sh tests/test_setup.py
git commit -m "feat(setup): link the launcher, and say what PATH costs"
```

---

### Task 6: Install `adsb-tui` and write its radar config

**Files:**
- Modify: `setup.sh`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: `ARCH`, `PREFIX`, `ADSB_CONFIG`, `RELEASE_URL`, `ADSB_VERSION`
- Produces: `install_adsb` (downloads and extracts, non-fatal on failure);
  `write_adsb_config` (writes only when the file is absent)

- [ ] **Step 1: Write the failing test**

```python
CURL_RECORDER = """#!/bin/sh
# Record the URL, then emit a tarball containing a fake adsb-tui.
for a in "$@"; do case "$a" in https://*) echo "$a" >> "$CURL_LOG";; esac; done
d=$(mktemp -d)
printf '#!/bin/sh\\nexit 0\\n' > "$d/adsb-tui"
chmod +x "$d/adsb-tui"
tar czf - -C "$d" adsb-tui
"""

CURL_FAILS = """#!/bin/sh
echo "404" >&2
exit 22
"""


def test_adsb_is_downloaded_and_made_executable(tmp_path):
    log = tmp_path / "curl.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={"curl": CURL_RECORDER},
    )
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", CURL_LOG=str(log))
    binary = tmp_path / "home" / ".local" / "bin" / "adsb-tui"
    assert binary.exists()
    assert os.access(binary, os.X_OK)


def test_the_release_url_names_the_pinned_version(tmp_path):
    log = tmp_path / "curl.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={"curl": CURL_RECORDER},
    )
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", CURL_LOG=str(log))
    url = log.read_text()
    assert "v0.2.1" in url
    assert "macos-" in url, "the arch-specific asset must be selected"


def test_a_failed_download_still_reaches_the_end(tmp_path):
    """adsb-tui is degraded, never fatal: the cockpit must still open."""
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={"curl": CURL_FAILS},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert result.returncode == 0, "a missing radar must not fail setup"
    assert "radar" in (result.stdout + result.stderr).lower()


def test_the_radar_config_is_written(tmp_path):
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={"curl": CURL_RECORDER},
    )
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", CURL_LOG=str(tmp_path / "c.log"))
    config = tmp_path / "home" / ".config" / "ads-b-tui" / "adsb-tui.toml"
    text = config.read_text()
    assert "api.airplanes.live/v2/point/{lat}/{lon}/{range_nm}" in text
    assert "refresh_secs = 2" in text
    assert "site_lat" not in text, "kcgx passes coordinates per launch"


def test_an_existing_config_is_never_touched(tmp_path):
    """adsb-tui rewrites this file itself on exit, so it is the user's."""
    config = tmp_path / "home" / ".config" / "ads-b-tui" / "adsb-tui.toml"
    config.parent.mkdir(parents=True)
    config.write_text("theme = \"mono\"\n")
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={"curl": CURL_RECORDER},
    )
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", CURL_LOG=str(tmp_path / "c.log"))
    assert config.read_text() == "theme = \"mono\"\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -k "adsb or radar_config or release_url or existing_config" -v`
Expected: FAIL — no binary, no config file.

- [ ] **Step 3: Write the implementation**

Append to `setup.sh`:

```bash
install_adsb() {
    if have_command adsb-tui || [ -x "$PREFIX/adsb-tui" ]; then
        say "adsb-tui already installed."
        return 0
    fi
    if [ "$ARCH" = "unsupported" ]; then
        warn "no adsb-tui release for $(uname -m); the radar pane will be empty."
        return 0
    fi

    say ""
    say "Installing adsb-tui $ADSB_VERSION (the radar pane)."
    say "  From https://github.com/j4v3l/ADS-B_TUI"
    say "  Licence: ADS-B TUI Non-Commercial License -- not OSI-approved."
    say "  Downloading the published release; nothing is built from source."
    say ""

    # Non-fatal by design: a cockpit with working audio beats no cockpit.
    if curl -fL "$RELEASE_URL/$ADSB_VERSION/adsb-tui-$ARCH.tar.gz" \
        | tar xzf - -C "$PREFIX" 2>/dev/null; then
        chmod +x "$PREFIX/adsb-tui" 2>/dev/null || true
        say "Installed $PREFIX/adsb-tui"
    else
        warn "could not download adsb-tui; the radar pane will be empty."
        warn "Everything else still works. Re-run setup.sh to try again."
    fi
}

# adsb-tui defaults to http://adsb.local/data/aircraft.json -- a receiver on
# your own network. Without one the radar is empty, so point it at a public
# aggregator. 2 s because both free providers rate-limit near 1 req/s and
# api.adsb.lol returned 429 at that rate where api.airplanes.live did not.
write_adsb_config() {
    if [ -e "$ADSB_CONFIG" ]; then
        say "adsb-tui config already exists; leaving it alone."
        return 0
    fi
    mkdir -p "$(dirname "$ADSB_CONFIG")"
    cat > "$ADSB_CONFIG" <<'TOML'
# Written by kcgx setup.sh. Safe to edit -- setup never overwrites it.
#
# Live aircraft with no receiver hardware and no API key. kcgx fills in
# {lat}/{lon} per launch from the airport you pick, so do not set
# site_lat/site_lon here.
url_template = "https://api.airplanes.live/v2/point/{lat}/{lon}/{range_nm}"
refresh_secs = 2
TOML
    say "Wrote $ADSB_CONFIG"
}

install_adsb
write_adsb_config
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add setup.sh tests/test_setup.py
git commit -m "feat(setup): install adsb-tui and point it at a live feed"
```

---

### Task 7: The launch gate, and proof that `cargo` is never called

**Files:**
- Modify: `setup.sh`
- Test: `tests/test_setup.py`

**Interfaces:**
- Consumes: everything above
- Produces: `launch_gate` (re-checks fatal deps); the final `exec`

- [ ] **Step 1: Write the failing test**

```python
def test_missing_tmux_is_stopped_by_the_gate(tmp_path):
    """Declining the prompt with tmux absent must not reach the launcher."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl", "mktemp"))
    result = subprocess.run(
        [str(SETUP)], input="n\n",
        env={"PATH": str(path_dir), "HOME": str(tmp_path / "home"),
             "KCGX_SETUP_NO_LAUNCH": "1"},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode != 0
    assert "tmux" in result.stdout + result.stderr


def test_an_old_tmux_is_stopped_by_the_gate(tmp_path):
    """bin/kcgx refuses below 3.1, so setup must not hand off to it."""
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "curl", "mktemp"),
        scripts={"tmux": "#!/bin/sh\necho 'tmux 2.8'\n"},
    )
    result = subprocess.run(
        [str(SETUP)], input="n\n",
        env={"PATH": str(path_dir), "HOME": str(tmp_path / "home"),
             "KCGX_SETUP_NO_LAUNCH": "1"},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode != 0
    assert "3.1" in result.stdout + result.stderr


def test_a_complete_environment_reaches_the_launch(tmp_path):
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={"curl": CURL_RECORDER},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1",
                       CURL_LOG=str(tmp_path / "c.log"))
    assert result.returncode == 0
    # The gate's own message, not merely the string "kcgx" -- which appears
    # in the symlink line long before the gate and would pass either way.
    assert "Setup complete" in result.stdout


def test_setup_never_invokes_cargo(tmp_path):
    """Building adsb-tui from source pulled 4,103 MB of Rust toolchain onto
    the development machine. The published release exists to prevent that,
    so a cargo call is a regression, not a fallback."""
    log = tmp_path / "cargo.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={
            "curl": CURL_FAILS,   # worst case: the download failed
            "cargo": f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n',
            "rustc": f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n',
        },
    )
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert not log.exists(), "setup fell back to building from source"


def test_no_cargo_appears_in_the_script_at_all(tmp_path):
    """Belt and braces: the test above only covers paths it exercises."""
    source = SETUP.read_text()
    assert "cargo" not in source
    assert "rustc" not in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_setup.py -k "gate or launch or cargo" -v`
Expected: FAIL — the gate does not exist, so a missing `tmux` exits 0.

- [ ] **Step 3: Write the implementation**

Append to `setup.sh`:

```bash
# Re-checked rather than trusted from phase 1: the prompt may have been
# declined, or Homebrew may have failed. Launching into a failure the
# script already knew about would be worse than stopping here.
launch_gate() {
    local blocked=""
    have_command ffmpeg || blocked="$blocked ffmpeg"
    tmux_new_enough || blocked="$blocked tmux(3.1+)"
    [ -z "$blocked" ] && return 0

    say ""
    die "still missing:$blocked
The cockpit cannot open without these. Install them and run this again:
  brew install$blocked"
}

launch_gate

say ""
say "Setup complete. Opening the cockpit..."

if [ -n "${KCGX_SETUP_NO_LAUNCH:-}" ]; then
    exit 0
fi

# By absolute path, not by name: a PATH the user has not reloaded yet must
# not stop the cockpit opening on this first run.
exec "$REPO/bin/kcgx"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_setup.py -v`
Expected: 27 passed.

- [ ] **Step 5: Run the whole suite and commit**

```bash
uv run pytest -q          # expect 627 passed
git add setup.sh tests/test_setup.py
git commit -m "feat(setup): gate the launch, and never build from source"
```

---

## Self-review

**Spec coverage.** Every section maps to a task:

| Spec requirement | Task |
|---|---|
| Preflight table before any change | 1 |
| Architecture detection | 1 |
| tmux 3.1 floor | 1 (detect), 7 (gate) |
| pyenv advisory | 2 |
| Terminal width advisory | 2 |
| One prompt, then install | 3 |
| Homebrew absent → stop with the command | 3 |
| Declining is not an error | 3 |
| `uv sync` | 4 |
| Symlink, never copy | 5 |
| Foreign symlink is fatal | 5 |
| `PATH` warning naming `Ctrl-b a` | 5 |
| adsb-tui from the pinned release | 6 |
| Licence notice | 6 |
| Download failure is degraded | 6, 7 |
| Config written only if absent | 6 |
| airplanes.live + refresh 2, no site_lat | 6 |
| Launch gate | 7 |
| `exec` by absolute path | 7 |
| Never invokes cargo | 7 |
| Idempotent re-run | 3, 5, 6 |
| README | already done (`d87103d`, `b3d854f`) |

**Placeholder scan.** No TBD/TODO. Every code step carries real content.

**Type consistency.** Function names are used identically throughout:
`have_command`, `detect_arch`, `tmux_new_enough`, `row`, `preflight`,
`check_pyenv`, `check_width`, `missing_formulae`, `install_prerequisites`,
`sync_project`, `link_launcher`, `install_adsb`, `write_adsb_config`,
`launch_gate`. Variables `REPO`, `ARCH`, `PREFIX`, `ADSB_CONFIG`,
`RELEASE_URL`, `ADSB_VERSION`, `MIN_COLS` are set once in Task 1 (except
`ARCH`, set by `preflight`) and read thereafter.

**One known gap, deliberate.** `ARCH` is assigned inside `preflight`, so
`install_adsb` in Task 6 depends on `preflight` having run. That holds
because the top-level calls run in order, but an implementer reordering
them would break it silently. Task 6's `install_adsb` guards with the
`unsupported` branch rather than assuming a value.
