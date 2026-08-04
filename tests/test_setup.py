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
              "printf", "tr", "sort", "id", "stty", "tar", "chmod",
              "readlink")

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
    result = run_setup(tmp_path, path_dir, "--check")
    assert result.returncode == 0, "preflight did not run to completion"
    assert "adsb-tui" in result.stdout, "preflight did not print its table"
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
    # --check is only `preflight; exit 0`, so returncode == 0 proves preflight
    # ran start to finish (a die anywhere inside it, including check_pyenv
    # itself, would exit nonzero under set -e) -- not just that it never got
    # far enough to print "pyenv".
    assert result.returncode == 0, "preflight did not run to completion"
    assert "adsb-tui" in result.stdout, "preflight did not print its table"
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
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", BREW_LOG=str(log))
    assert result.returncode == 0
    link = tmp_path / "home" / ".local" / "bin" / "kcgx"
    assert link.is_symlink(), "setup did not run to completion"
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
    # An absent brew.log alone is also what a premature die/exit before the
    # `read` would look like. Pin down that the script actually reached and
    # took the decline branch via the "Nothing installed." message that
    # only it prints -- not the exit code: ffmpeg and tmux are genuinely
    # absent from this PATH, so declining leaves them missing and the run
    # now correctly fails later, at the launch gate (see
    # test_missing_tmux_is_stopped_by_the_gate). That downstream failure is
    # the gate doing its job, not evidence against the decline branch.
    assert "Nothing installed." in result.stdout
    assert result.returncode != 0, "the gate should catch what decline left missing"
    assert not log.exists(), "declining still installed something"


CURL_RECORDER = """#!/bin/sh
echo "$@" >> "$CURL_LOG"
echo ":"
"""

CURL_FOR_UV_INSTALL = """#!/bin/sh
echo "$@" >> "$CURL_LOG"
# Emit an install script for sh to execute. This preserves the two-stage
# pipeline: curl fetches, sh installs. Matches `curl ... | sh` in production.
# sync_project runs unconditionally after install_prerequisites, so this test
# must leave a working uv behind or the script dies at the next phase.
cat << 'INSTALL_SCRIPT'
mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\nexit 0\n' > "$HOME/.local/bin/uv"
chmod +x "$HOME/.local/bin/uv"
INSTALL_SCRIPT
"""


def test_missing_uv_is_installed_via_astral_curl(tmp_path):
    """The uv-install branch (`curl ... | sh`) is a separate code path from
    the brew branch and every other test always stubs `uv` into `tools`,
    so without this test the branch never runs at all.

    `curl` is stubbed to record the URL it was asked for and to simulate
    installing uv by creating a dummy binary in $HOME/.local/bin -- the real
    installer must never run and the network must never be reached. `sh`
    itself is left alone: it is in BASE_TOOLS and other things depend on
    it.
    """
    log = tmp_path / "curl.log"
    path_dir = stub_path(
        tmp_path, tools=("ffmpeg", "tmux"),
        scripts={"curl": CURL_FOR_UV_INSTALL},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", CURL_LOG=str(log))
    assert result.returncode == 0
    assert log.exists(), "curl was never called"
    assert "https://astral.sh/uv/install.sh" in log.read_text()


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
    log_text = log.read_text()
    assert "sync" in log_text
    assert "--project" in log_text
    # REPO is computed as $(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd),
    # which resolves to the repo root where setup.sh lives.
    repo_root = str(SETUP.parent)
    assert repo_root in log_text


def test_a_failing_uv_sync_is_fatal(tmp_path):
    """Without dependencies there is no cockpit; carrying on would lie."""
    path_dir = stub_path(
        tmp_path, tools=("ffmpeg", "tmux", "curl"),
        scripts={"uv": UV_FAILS},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert result.returncode != 0
    assert "uv sync" in result.stdout + result.stderr


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
    assert result.returncode == 0
    assert (prefix / "kcgx").is_symlink(), "link_launcher did not run to completion"
    assert "Ctrl-b a" not in result.stdout + result.stderr


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
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", CURL_LOG=str(tmp_path / "c.log"),
    )
    # Read-only-file assertions pass for free if the script died before
    # write_adsb_config ever ran. Pin down that it actually reached and
    # took the "leave it alone" branch: exit 0, plus the message only
    # that branch prints.
    assert result.returncode == 0, "setup did not run to completion"
    combined = (result.stdout + result.stderr).lower()
    assert "leaving it alone" in combined, "write_adsb_config never ran"
    assert config.read_text() == "theme = \"mono\"\n"


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
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    # An absent cargo.log alone is also what a premature die/exit before
    # install_adsb ever ran would look like. Pin down that the script
    # actually ran far enough to have called cargo if it were going to.
    assert result.returncode == 0, "setup did not run to completion"
    assert "Setup complete" in result.stdout
    assert not log.exists(), "setup fell back to building from source"


def test_no_cargo_call_appears_in_the_script(tmp_path):
    """Belt and braces: the test above only covers paths it exercises.

    Comments are stripped first. The whole point of this constraint is
    worth writing down in the script, and a naive substring check would
    turn documenting it into a test failure.
    """
    code = [
        line for line in SETUP.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    source = "\n".join(code)
    assert "cargo" not in source
    assert "rustc" not in source
