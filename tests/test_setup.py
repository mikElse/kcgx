"""The kcgx setup script.

Drives the real setup.sh as a subprocess with a stubbed PATH, the same way
tests/test_kcgx_launcher.py drives bin/kcgx. Nothing here installs
software, downloads a file, or opens a socket.
"""

from __future__ import annotations

import fcntl
import os
import pty
import shutil
import struct
import subprocess
import termios
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SETUP = REPO / "setup.sh"

# Every tool setup.sh itself needs in order to run at all.
BASE_TOOLS = ("bash", "sh", "env", "uname", "grep", "awk", "sed", "head",
              "dirname", "basename", "pwd", "mkdir", "ln", "rm", "cat",
              "printf", "tr", "sort", "id", "stty", "tar", "chmod")

# `uv` is ALWAYS a stub, never the real binary, and asking for "uv" in
# `tools` gets you this rather than a symlink.
#
# setup.sh runs `uv sync --project $REPO`. Symlinking the real uv would make
# every test that reaches phase 3 write to the actual repo's .venv while
# HOME points at tmp_path -- so uv would find no cache, re-download the
# whole 3.14 toolchain per test, and mutate the working tree the suite is
# running from. Tests never install software or hit the network.
UV_STUB = """#!/bin/sh
exit 0
"""


def stub_path(tmp_path, *, tools=(), scripts=None):
    """A directory to use as the entire PATH.

    `tools` are symlinked from the real system; `scripts` is a mapping of
    name -> shell source for fakes and wins over both. Anything not named
    is absent, which is how "ffmpeg is missing" is expressed.
    """
    d = tmp_path / "stub_bin"
    d.mkdir(exist_ok=True)
    for tool in (*BASE_TOOLS, *tools):
        if tool == "uv":
            continue  # never the real one; handled below
        found = shutil.which(tool)
        if found and not (d / tool).exists():
            (d / tool).symlink_to(found)
    if "uv" in tools and "uv" not in (scripts or {}):
        p = d / "uv"
        p.write_text(UV_STUB)
        p.chmod(0o755)
    for name, body in (scripts or {}).items():
        p = d / name
        if p.exists() or p.is_symlink():
            # A BASE_TOOLS/tools symlink may already occupy this name (e.g.
            # `stty`, needed just to run setup.sh at all). write_text()
            # follows a symlink rather than replacing it, which for a
            # system binary means writing through to the real file --
            # unlink first so `scripts` genuinely "wins over both".
            p.unlink()
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


def run_setup_with_pty(tmp_path, path_dir, *args, cols, rows=24, timeout=30,
                        **env):
    """Run setup.sh with a real pseudo-tty as its controlling terminal,
    sized `cols` x `rows`.

    `check_width` tries `stty size </dev/tty` before falling back to
    $COLUMNS. Exercising that preferred branch for real -- not the
    fallback -- needs an actual controlling terminal. Stubbing `stty` on
    PATH is not enough: `</dev/tty` is a shell redirection that bash
    resolves before it ever looks up which `stty` to run, so if the
    process doing the redirecting has no controlling terminal at all
    (headless CI, a piped command, this project's own test sandbox), the
    redirect fails and the stub is never reached -- regardless of what it
    would have printed.

    Allocating our own pty and making it setup.sh's controlling terminal
    -- via a `preexec_fn` that calls `setsid()` then claims the pty
    (already dup'd onto fd 0 by the time preexec_fn runs) with
    `TIOCSCTTY` -- sidesteps the test runner's own terminal status
    entirely. The result is identical whether this suite runs from an
    interactive shell, a pipe, or CI. Only stdin is the pty; stdout and
    stderr stay on ordinary pipes, so captured output is exact -- no tty
    echo or CRLF translation to account for.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    environ = {
        "PATH": str(path_dir),
        "HOME": str(home),
        "KCGX_SETUP_NO_LAUNCH": "1",
    }
    environ.update({k: str(v) for k, v in env.items()})

    master_fd, slave_fd = pty.openpty()
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0))

    def _make_ctty():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(
        [str(SETUP), *args],
        env=environ,
        stdin=slave_fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, preexec_fn=_make_ctty, close_fds=True,
    )
    os.close(slave_fd)
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    finally:
        os.close(master_fd)
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout)


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
    """bin/kcgx refuses below 100 columns. Better said now than at launch.

    `stty` is stubbed to fail outright, standing in for "no usable
    controlling terminal" -- the case $COLUMNS exists to cover. Without
    forcing that failure, this test's outcome would depend on whether the
    machine running pytest happens to have a real controlling terminal:
    `check_width` tries `stty size` first, so on an interactive box the
    genuine terminal width would answer before $COLUMNS is ever consulted,
    and if that terminal is >= 100 columns the advisory would silently
    never fire.
    """
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"),
        scripts={"stty": "#!/bin/sh\nexit 1\n"},
    )
    result = run_setup(tmp_path, path_dir, "--check", COLUMNS="80")
    assert result.returncode == 0
    assert "100" in result.stdout


def test_stty_narrow_terminal_is_flagged(tmp_path):
    """The preferred path, exercised for real: a controlling tty that is
    genuinely narrow, with no $COLUMNS fallback available at all.
    """
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup_with_pty(tmp_path, path_dir, "--check", cols=80)
    assert result.returncode == 0
    assert "100" in result.stdout


def test_stty_wide_terminal_stays_quiet(tmp_path):
    """The advisory must be capable of staying quiet on the preferred
    path too, or it says nothing -- a `check_width` that always printed
    the note would otherwise pass every other test in this file. $COLUMNS
    is set narrow on purpose, to prove it's the real, wide `stty` answer
    keeping this quiet, not a coincidental fallback.
    """
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup_with_pty(
        tmp_path, path_dir, "--check", cols=120, COLUMNS="40",
    )
    assert result.returncode == 0
    assert "note: this terminal" not in result.stdout


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
