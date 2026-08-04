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

REPO = Path(__file__).resolve().parent.parent
SETUP = REPO / "setup.sh"

# Every tool setup.sh itself needs in order to run at all.
BASE_TOOLS = ("bash", "sh", "env", "uname", "grep", "awk", "sed", "head",
              "dirname", "basename", "pwd", "mkdir", "ln", "rm", "cat",
              "printf", "tr", "sort", "id", "stty", "tar", "chmod",
              "readlink",
              # For `tar xzf` in install_adsb. macOS's bsdtar decompresses
              # in-process and never looks for it, so the two download tests
              # passed there while failing on Linux, where GNU tar shells out
              # to gzip and a stubbed PATH without it makes every archive
              # look corrupt.
              "gzip")

# setup.sh runs `uv sync --project $REPO`. Symlinking the real uv would make
# every test that reaches phase 3 write to the actual repo's .venv while
# HOME points at tmp_path -- so uv would find no cache, re-download the
# whole 3.14 toolchain per test, and mutate the working tree the suite is
# running from.
UV_STUB = """#!/bin/sh
exit 0
"""

# setup.sh's only two uses of curl are `curl | sh` (the uv installer) and
# `curl | tar` (the 9.6 MB adsb-tui release). A real curl on the stubbed
# PATH therefore means a test that reaches phase 4 downloads that release
# from github.com -- which it did, for ten tests, until this stub existed:
# genuine Mach-O arm64 binaries turned up in the tests' tmp HOMEs. The
# suite must pass with no network at all.
#
# So this fails, loudly and non-fatally, exactly as an offline machine
# would. A test that needs curl to *do* something passes its own fake in
# `scripts`, which wins over this.
CURL_STUB = """#!/bin/sh
echo "curl stub: tests never reach the network (tests/test_setup.py)" >&2
exit 1
"""

# Names that are ALWAYS a stub, never the real binary, however `tools`
# asks for them. Being in `tools` still means "this tool is present on
# PATH", which is what preflight reports and what install_prerequisites
# branches on -- only the behaviour is faked.
NEVER_REAL = {"uv": UV_STUB, "curl": CURL_STUB}


def stub_path(tmp_path, *, tools=(), scripts=None):
    """A directory to use as the entire PATH.

    `tools` are symlinked from the real system, except for the NEVER_REAL
    names which get a stub; `scripts` is a mapping of name -> shell source
    for fakes and wins over both. Anything not named is absent, which is
    how "ffmpeg is missing" is expressed.

    A tool that cannot be found on the host is an error rather than a
    silent omission: "present" and "absent" select opposite branches of
    setup.sh, so quietly dropping an unavailable tool would flip a test to
    the branch it was written to prove is *not* taken, and pass.
    """
    d = tmp_path / "stub_bin"
    d.mkdir(exist_ok=True)
    for tool in (*BASE_TOOLS, *tools):
        if tool in NEVER_REAL:
            continue
        found = shutil.which(tool)
        if found is None:
            raise RuntimeError(
                f"stub_path: {tool!r} is not installed on this host, so "
                f"this test cannot express 'setup.sh sees {tool}'. Install "
                f"it, or the test silently exercises the missing-tool "
                f"branch instead."
            )
        if not (d / tool).exists():
            (d / tool).symlink_to(found)
    for tool in tools:
        if tool in NEVER_REAL and tool not in (scripts or {}):
            p = d / tool
            p.write_text(NEVER_REAL[tool])
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


# The braces to CURL_STUB's belt, and the only user of setup.sh's
# KCGX_SETUP_RELEASE_URL seam. Every invocation in this file points the
# release download at a host that does not exist, so even a curl that got
# onto PATH by some future accident cannot fetch anything from github.com.
# `.invalid` is reserved by RFC 2606 and can never resolve, and the scheme
# stays https so the URL keeps the shape the recorder stubs match on.
OFFLINE_RELEASE_URL = "https://kcgx-tests.invalid/never-fetched"


def setup_env(tmp_path, path_dir, **env):
    """The environment every invocation of setup.sh in this file gets."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True, parents=True)
    environ = {
        "PATH": str(path_dir),
        "HOME": str(home),
        "KCGX_SETUP_NO_LAUNCH": "1",
        "KCGX_SETUP_RELEASE_URL": OFFLINE_RELEASE_URL,
    }
    environ.update({k: str(v) for k, v in env.items()})
    return environ


def run_setup(tmp_path, path_dir, *args, **env):
    environ = setup_env(tmp_path, path_dir, **env)
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
    environ = setup_env(tmp_path, path_dir, **env)

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


def test_check_says_how_to_install_what_is_missing(tmp_path):
    """A table naming four tools and no way to get any of them restates the
    "which prerequisites do I need?" problem rather than answering it. The
    gate prints remedies too, but only once you have committed to an install
    -- three phases past where --check exits.
    """
    path_dir = stub_path(tmp_path, tools=("curl",))
    result = run_setup(tmp_path, path_dir, "--check")
    assert result.returncode == 0
    assert "brew install" in result.stdout, result.stdout
    for formula in ("ffmpeg", "tmux"):
        assert formula in result.stdout.split("brew install")[1], result.stdout
    assert "astral.sh/uv/install.sh" in result.stdout, result.stdout
    # The one optional dependency is also the only one nothing else offers a
    # fix for, so it gets named with setup.sh as its answer.
    assert "adsb-tui" in result.stdout, result.stdout


def test_check_offers_no_remedies_when_nothing_is_missing(tmp_path):
    """Advice for a machine that needs none reads as a problem, and the whole
    value of the table is that it can say "you are ready" in one look.
    """
    path_dir = stub_path(
        tmp_path,
        tools=("uv", "ffmpeg", "tmux", "curl"),
        scripts={"adsb-tui": "#!/bin/sh\nexit 0\n"},
    )
    result = run_setup(tmp_path, path_dir, "--check")
    assert result.returncode == 0
    assert "missing" not in result.stdout, result.stdout
    assert "brew install" not in result.stdout, result.stdout
    assert "astral.sh" not in result.stdout, result.stdout


def test_check_changes_nothing(tmp_path):
    """Preflight is a probe. It must not create the symlink or the config."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, "--check")
    assert result.returncode == 0, "preflight did not run to completion"
    assert "adsb-tui" in result.stdout, "preflight did not print its table"
    home = tmp_path / "home"
    assert not (home / ".local" / "bin" / "kcgx").exists()
    assert not (home / ".config" / "ads-b-tui" / "adsb-tui.toml").exists()


def test_help_explains_itself_and_installs_nothing(tmp_path):
    """--help used to fall through to the full install and an exec into the
    cockpit, which is a surprising amount of machine to change in response
    to asking a question."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, "--help")
    assert result.returncode == 0
    assert "--check" in result.stdout, "the other flag is not documented"
    home = tmp_path / "home"
    assert not (home / ".local" / "bin" / "kcgx").exists(), "it installed anyway"
    assert not (home / ".config" / "ads-b-tui" / "adsb-tui.toml").exists()


def test_an_unknown_argument_is_refused(tmp_path):
    """A typo must not be read as consent to install and launch."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, "--chekc")
    assert result.returncode != 0, "an unrecognised flag exited 0"
    assert "--chekc" in result.stderr, "the offending argument is not named"
    assert "Usage" in result.stderr
    home = tmp_path / "home"
    assert not (home / ".local" / "bin" / "kcgx").exists(), "it installed anyway"


def test_a_stray_extra_argument_is_refused(tmp_path):
    """`./setup.sh --check please` is not a check, and not an install."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    result = run_setup(tmp_path, path_dir, "--check", "please")
    assert result.returncode != 0
    assert "please" in result.stderr
    assert not (tmp_path / "home" / ".local" / "bin" / "kcgx").exists()


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
        env=setup_env(tmp_path, f"{shims}:{path_dir}"),
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
        env=setup_env(tmp_path, path_dir, BREW_LOG=str(log)),
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


CURL_FOR_UV_INSTALL = """#!/bin/sh
echo "$@" >> "$CURL_LOG"
# Emit an install script for sh to execute. This preserves the two-stage
# pipeline: curl fetches, sh installs. Matches `curl ... | sh` in production.
# sync_project runs unconditionally after install_prerequisites, so this test
# must leave a working uv behind or the script dies at the next phase.
#
# The install script also reports the environment it was handed, because
# that is the only place the real installer reads INSTALLER_NO_MODIFY_PATH
# from -- see test_the_uv_installer_may_not_edit_shell_profiles.
cat << 'INSTALL_SCRIPT'
echo "INSTALLER_NO_MODIFY_PATH=${INSTALLER_NO_MODIFY_PATH:-unset}" >> "$CURL_LOG"
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


def test_the_uv_installer_may_not_edit_shell_profiles(tmp_path):
    """kcgx never edits a shell profile, including by delegation.

    Left to itself, astral's installer appends `. "$HOME/.local/bin/env"`
    to ~/.zshrc, ~/.bash_profile AND ~/.profile. link_launcher prints the
    export line and explicitly leaves applying it to the user, so having
    somebody else's installer make that edit three phases earlier would
    make the promise a lie.

    Asserted where it actually has to be true: inside the process that
    runs the install script, which is the only thing that reads the
    variable. `INSTALLER_NO_MODIFY_PATH=1 sh` sets it for that process
    alone, so a source-level grep would not prove it arrived.
    """
    log = tmp_path / "curl.log"
    path_dir = stub_path(
        tmp_path, tools=("ffmpeg", "tmux"),
        scripts={"curl": CURL_FOR_UV_INSTALL},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", CURL_LOG=str(log))
    assert result.returncode == 0
    assert "INSTALLER_NO_MODIFY_PATH=1" in log.read_text(), (
        "the astral installer was not told to leave shell profiles alone"
    )


def test_a_missing_uv_is_named_rather_than_blamed_on_the_sync(tmp_path):
    """A fresh Mac where the prompt was declined: uv was never installed.

    Dying inside `uv sync` would be both wrong (there was no sync) and
    useless (it does not say uv is missing, or how to get it). Route it
    through the same gate as every other fatal dependency instead.
    """
    path_dir = stub_path(tmp_path, tools=("ffmpeg", "tmux"))
    result = subprocess.run(
        [str(SETUP)], input="n\n",
        env=setup_env(tmp_path, path_dir),
        capture_output=True, text=True, timeout=120,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Nothing installed." in result.stdout, "never reached the decline branch"
    assert "still missing: uv" in combined, "the missing dependency is not named"
    assert "astral.sh/uv/install.sh" in combined, "no way to fix it is offered"
    assert "uv sync failed" not in combined, (
        "blamed the sync for a uv that was never installed"
    )


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
    """Without dependencies there is no cockpit; carrying on would lie.

    uv is present here and the sync itself fails, which is a different
    failure from uv never having been installed (see
    test_a_missing_uv_is_named_rather_than_blamed_on_the_sync) and must
    not be described as that one: telling somebody who has uv to go and
    install uv is worse than saying nothing.
    """
    path_dir = stub_path(
        tmp_path, tools=("ffmpeg", "tmux", "curl"),
        scripts={"uv": UV_FAILS},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "uv sync failed" in combined
    assert "still missing" not in combined, "reported a present uv as missing"


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
    """adsb-tui is degraded, never fatal: the cockpit must still open, and
    it must say why the radar will be empty.

    "radar" alone is not enough to prove the second half: install_adsb
    prints "the radar pane" as its own banner *before* attempting the
    download, so that substring is already on stdout whatever happens
    next. Assert on "could not download", which only the failure branch
    emits.
    """
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={"curl": CURL_FAILS},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    combined = (result.stdout + result.stderr).lower()
    assert result.returncode == 0, "a missing radar must not fail setup"
    assert "could not download" in combined, "the degradation was never explained"
    assert "everything else still works" in combined, "no reassurance, no re-run"


CURL_EMPTY_ARCHIVE = """#!/bin/sh
# A tarball that unpacks cleanly and contains no adsb-tui: `tar` exits 0,
# so "the download worked" is true and "adsb-tui is installed" is not.
d=$(mktemp -d)
printf 'not a binary\\n' > "$d/RELEASE-NOTES"
tar czf - -C "$d" RELEASE-NOTES
"""


def test_an_archive_with_no_binary_is_not_called_installed(tmp_path):
    """`chmod ... || true` swallows the one signal that anything is wrong,
    so without a check on the binary itself setup would print "Installed
    ~/.local/bin/adsb-tui" for a file that does not exist."""
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "tmux", "mktemp"),
        scripts={"curl": CURL_EMPTY_ARCHIVE},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    combined = result.stdout + result.stderr
    assert result.returncode == 0, "still degraded, not fatal"
    assert not (tmp_path / "home" / ".local" / "bin" / "adsb-tui").exists()
    assert "Installed" not in combined, "claimed an install that did not happen"
    assert "no usable binary" in combined, "said nothing about the empty archive"


def test_preflight_and_install_agree_about_an_installed_adsb(tmp_path):
    """~/.local/bin is where setup puts adsb-tui and is not necessarily on
    PATH, so on the second run preflight used to report "missing
    (optional)" and install_adsb then said "already installed" -- about the
    same file, in the same run. One question, asked once."""
    prefix = tmp_path / "home" / ".local" / "bin"
    prefix.mkdir(parents=True)
    binary = prefix / "adsb-tui"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "tmux", "curl"))
    check = run_setup(tmp_path, path_dir, "--check")
    assert check.returncode == 0
    row = [l for l in check.stdout.splitlines() if "adsb-tui" in l]
    assert row, "no adsb-tui row at all"
    assert "found" in row[0], f"preflight does not see the installed binary: {row[0]}"

    full = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert full.returncode == 0
    assert "already installed" in full.stdout, "install_adsb disagreed"


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
    """Declining the prompt with tmux absent must not reach the launcher.

    `preflight` runs unconditionally, before the gate, and always prints a
    tmux row -- so a bare "tmux" (or "3.1") substring check would pass
    even if the gate were deleted outright, or if the script died for an
    unrelated reason anywhere after preflight. Assert on the gate's own
    die message instead: "cannot open without these" is text only
    `launch_gate` emits, and "tmux(3.1+)" is the literal token it builds
    into `$blocked` -- distinct from preflight's row text ("missing" / "too
    old (needs 3.1+)", with a space before the parenthesis, not glued to
    "tmux").
    """
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl", "mktemp"))
    result = subprocess.run(
        [str(SETUP)], input="n\n",
        env=setup_env(tmp_path, path_dir),
        capture_output=True, text=True, timeout=120,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "cannot open without these" in combined
    assert "tmux(3.1+)" in combined


def test_an_old_tmux_is_stopped_by_the_gate(tmp_path):
    """bin/kcgx refuses below 3.1, so setup must not hand off to it.

    See the sibling test above for why the assertions target the gate's
    own die message rather than a substring preflight's row already
    prints.
    """
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "curl", "mktemp"),
        scripts={"tmux": "#!/bin/sh\necho 'tmux 2.8'\n"},
    )
    result = subprocess.run(
        [str(SETUP)], input="n\n",
        env=setup_env(tmp_path, path_dir),
        capture_output=True, text=True, timeout=120,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "cannot open without these" in combined
    assert "tmux(3.1+)" in combined


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


def test_exec_hands_off_by_absolute_path(tmp_path):
    """Load-bearing, not cosmetic: a user who has not reloaded their shell
    profile yet must still get a cockpit on this first run, which only
    works if the hand-off resolves `bin/kcgx` by absolute path rather than
    trusting PATH to contain it already.

    No test exercises the `exec` line itself -- every test in this file
    sets KCGX_SETUP_NO_LAUNCH=1, so the script always exits before
    reaching it. This is the cheap, static substitute: assert the source
    on disk, comments stripped first exactly as in the cargo test above,
    so a comment mentioning the bare name cannot trip it.
    """
    code = [
        line for line in SETUP.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    exec_lines = [line for line in code if line.strip().startswith("exec ")]
    assert exec_lines, "no exec line found in setup.sh"
    assert all('"$REPO/' in line for line in exec_lines), (
        f"exec must hand off by absolute $REPO path, not a bare command "
        f"name resolved through PATH: {exec_lines}"
    )
