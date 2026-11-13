"""The kcgx setup script.

Drives the real setup.sh as a subprocess with a stubbed PATH. Nothing here
installs software, downloads a file, or opens a socket.

Phase E (2026-10-22) took tmux, adsb-tui, its config and download, and the
terminal width check out of setup.sh, and their tests with them; step 7 now
starts the server (kcgx.selfcheck, tested for real in tests/test_selfcheck.py)
instead of running adsb-tui.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SETUP = REPO / "setup.sh"

# Every tool setup.sh itself needs in order to run at all.
BASE_TOOLS = ("bash", "sh", "env", "uname", "grep", "awk", "sed", "head",
              "dirname", "basename", "pwd", "mkdir", "ln", "rm", "cat",
              "printf", "tr", "sort", "id", "chmod", "readlink",
              # For the shell-profile backup in link_launcher.
              "cp")

# setup.sh runs `uv sync --project $REPO`. Symlinking the real uv would make
# every test that reaches phase 3 write to the actual repo's .venv while
# HOME points at tmp_path -- so uv would find no cache, re-download the
# whole 3.14 toolchain per test, and mutate the working tree the suite is
# running from.
# Step 7 reads two answers off uv's stdout: the server self check's last line,
# and the count of audio output devices. A silent stub fails the first and
# warns about the second, so every otherwise-clean run would end badly. The
# other uv calls' output is discarded or harmless ("Fetch the feed list for
# 2 now?" in step 6 is a stub's airport, nobody's real one).
UV_STUB = """#!/bin/sh
case "$*" in
    *kcgx.selfcheck*) echo "selfcheck ok"; exit 0 ;;
esac
echo 2
exit 0
"""

# Step 1 prints a version column, which means it runs `curl --version`.
# A stub that answers every invocation with its payload therefore writes a
# gzip tarball into the middle of the dependency table -- which surfaces
# only as a UnicodeDecodeError inside subprocess.run, three steps away from
# the line that caused it. Every curl stub below answers --version first.
ANSWER_VERSION = """
case "${1:-}" in --version) echo "curl 8.0.0 (kcgx test stub)"; exit 0 ;; esac
"""


# setup.sh's uses of curl are `curl | sh` (the uv installer) and step 7's two
# reachability probes. A real curl on the stubbed PATH would reach the
# network -- it once downloaded genuine adsb-tui binaries into the tests' tmp
# HOMEs, before adsb-tui left setup. The suite must pass with no network at
# all.
#
# So this fails, loudly and non-fatally, exactly as an offline machine
# would. A test that needs curl to *do* something passes its own fake in
# `scripts`, which wins over this.
CURL_STUB = """#!/bin/sh
""" + ANSWER_VERSION + """echo "curl stub: tests never reach the network (tests/test_setup.py)" >&2
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


def setup_env(tmp_path, path_dir, **env):
    """The environment every invocation of setup.sh in this file gets.

    The platform is pinned rather than detected. setup.sh branches on the
    real machine -- which package manager, whether PortAudio is a separate
    package -- so an unpinned suite would assert
    macOS behaviour on a macOS developer's laptop and Linux behaviour in
    CI, from the same source. macOS is the default because it is what the
    bulk of these tests were written against; the Linux tests set the seams
    themselves and say so in their names.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True, parents=True)
    environ = {
        "PATH": str(path_dir),
        "HOME": str(home),
        "KCGX_SETUP_NO_LAUNCH": "1",
        "KCGX_SETUP_OS": "macos",
        "KCGX_SETUP_PKG": "brew",
        # Step 7 probes liveatc.net and api.adsb.lol. The suite must
        # pass with no network at all, and a probe that has to time out is
        # 8 seconds per test besides.
        "KCGX_SETUP_SKIP_NET": "1",
    }
    environ.update({k: str(v) for k, v in env.items()})
    return environ


def complete_env(tmp_path, **scripts):
    """A PATH on which a full run reaches the launch.

    Everything present, and the real ffmpeg so step 7's version probe has
    something to read.
    """
    base = {"brew": BREW_RECORDER}
    base.update(scripts)
    return stub_path(
        tmp_path, tools=("uv", "ffmpeg", "curl"), scripts=base,
    )


def run_setup(tmp_path, path_dir, *args, **env):
    environ = setup_env(tmp_path, path_dir, **env)
    return subprocess.run(
        [str(SETUP), *args],
        env=environ, capture_output=True, text=True, timeout=120,
    )


def test_check_reports_every_dependency(tmp_path):
    """The table is the whole point of --check: one look, whole picture."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, "--check")
    assert result.returncode == 0
    for tool in ("uv", "ffmpeg", "curl"):
        assert tool in result.stdout, f"{tool} missing from the table"
    for gone in ("tmux", "adsb-tui"):
        assert gone not in result.stdout, f"{gone} is still in the table"


def test_check_says_how_to_install_what_is_missing(tmp_path):
    """A table naming tools and no way to get any of them restates the
    "which prerequisites do I need?" problem rather than answering it. The
    gate prints remedies too, but only once you have committed to an install
    -- three phases past where --check exits.
    """
    path_dir = stub_path(tmp_path, tools=("curl",))
    result = run_setup(tmp_path, path_dir, "--check")
    assert result.returncode == 0
    assert "brew install" in result.stdout, result.stdout
    assert "ffmpeg" in result.stdout.split("brew install")[1], result.stdout
    assert "astral.sh/uv/install.sh" in result.stdout, result.stdout


def test_check_offers_no_remedies_when_nothing_is_missing(tmp_path):
    """Advice for a machine that needs none reads as a problem, and the whole
    value of the table is that it can say "you are ready" in one look.
    """
    path_dir = stub_path(
        tmp_path,
        tools=("uv", "ffmpeg", "curl"),
    )
    result = run_setup(tmp_path, path_dir, "--check")
    assert result.returncode == 0
    assert "missing" not in result.stdout, result.stdout
    assert "brew install" not in result.stdout, result.stdout
    assert "astral.sh" not in result.stdout, result.stdout


def test_check_changes_nothing(tmp_path):
    """Preflight is a probe. It must not create the symlink or touch a profile."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, "--check", SHELL="/bin/zsh")
    assert result.returncode == 0, "preflight did not run to completion"
    assert "ffmpeg" in result.stdout, "preflight did not print its table"
    home = tmp_path / "home"
    assert not (home / ".local" / "bin" / "kcgx").exists()
    assert not (home / ".zshrc").exists()


def test_help_explains_itself_and_installs_nothing(tmp_path):
    """--help used to fall through to the full install and an exec into the
    cockpit, which is a surprising amount of machine to change in response
    to asking a question."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, "--help")
    assert result.returncode == 0
    assert "--check" in result.stdout, "the other flag is not documented"
    home = tmp_path / "home"
    assert not (home / ".local" / "bin" / "kcgx").exists(), "it installed anyway"


def test_an_unknown_argument_is_refused(tmp_path):
    """A typo must not be read as consent to install and launch."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, "--chekc")
    assert result.returncode != 0, "an unrecognised flag exited 0"
    assert "--chekc" in result.stderr, "the offending argument is not named"
    assert "Usage" in result.stderr
    home = tmp_path / "home"
    assert not (home / ".local" / "bin" / "kcgx").exists(), "it installed anyway"


def test_a_stray_extra_argument_is_refused(tmp_path):
    """`./setup.sh --check please` is not a check, and not an install."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, "--check", "please")
    assert result.returncode != 0
    assert "please" in result.stderr
    assert not (tmp_path / "home" / ".local" / "bin" / "kcgx").exists()


def test_a_missing_tool_is_reported_as_missing(tmp_path):
    """ffmpeg absent from PATH — the table must say so, not claim success."""
    path_dir = stub_path(tmp_path, tools=("uv", "curl"))
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
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))

    result = subprocess.run(
        [str(SETUP), "--check"],
        env=setup_env(tmp_path, f"{shims}:{path_dir}"),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, "an advisory must not fail the check"
    assert "pyenv" in result.stdout


def test_no_pyenv_no_advisory(tmp_path):
    """The guard must be capable of staying quiet, or it says nothing."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, "--check")
    # --check is only `preflight; exit 0`, so returncode == 0 proves preflight
    # ran start to finish (a die anywhere inside it, including check_pyenv
    # itself, would exit nonzero under set -e) -- not just that it never got
    # far enough to print "pyenv".
    assert result.returncode == 0, "preflight did not run to completion"
    assert "ffmpeg" in result.stdout, "preflight did not print its table"
    assert "pyenv" not in result.stdout


BREW_RECORDER = """#!/bin/sh
echo "$@" >> "$BREW_LOG"
exit 0
"""

# Every Linux machine that can install anything has sudo, so a Linux test
# that omits it is not testing Linux -- it is testing the no-root branch,
# and stops six steps before whatever it meant to assert.
#
# A stub rather than a symlink to the real thing, always: a suite that can
# reach /usr/bin/sudo can escalate, and would block on a password prompt
# the moment it did. This one drops sudo's own flags and runs the rest.
SUDO_PASSTHROUGH = """#!/bin/sh
while [ $# -gt 0 ]; do
    case "$1" in
        -*) shift ;;
        *) break ;;
    esac
done
exec "$@"
"""

# ldconfig reporting PortAudio already there, for Linux tests whose subject
# is some later step: without it step 2 tries to install it and the run
# stops there, nowhere near what the test meant to assert.
LDCONFIG_WITH_PORTAUDIO = (
    "#!/bin/sh\n"
    "echo '\tlibportaudio.so.2 (libc6,x86-64) => "
    "/lib/x86_64-linux-gnu/libportaudio.so.2'\n"
)


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
    assert "tmux" not in calls, "tmux is no longer needed"


def test_nothing_is_installed_when_everything_is_present(tmp_path):
    """Idempotence: the second run must be a no-op."""
    log = tmp_path / "brew.log"
    path_dir = complete_env(tmp_path)
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", BREW_LOG=str(log))
    assert result.returncode == 0
    link = tmp_path / "home" / ".local" / "bin" / "kcgx"
    assert link.is_symlink(), "setup did not run to completion"
    assert not log.exists(), "brew ran with nothing to install"


def test_no_homebrew_stops_with_the_install_line(tmp_path):
    """Installing a package manager unattended is beyond setup's remit."""
    path_dir = stub_path(tmp_path, tools=("uv", "curl"))  # no brew, no ffmpeg
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", KCGX_SETUP_PKG="none",
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "brew.sh" in combined, "the user needs the actual install command"


def test_no_package_manager_on_linux_names_the_packages(tmp_path):
    """The Linux sibling of the test above. There is no one command to
    print -- apt, dnf and pacman spell it three ways and the machine has
    none of them -- so the packages themselves are the answer, and telling
    somebody to install Homebrew on Linux would not be one.
    """
    path_dir = stub_path(tmp_path, tools=("uv", "curl"))
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1",
        KCGX_SETUP_OS="linux", KCGX_SETUP_PKG="none",
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "brew.sh" not in combined, "Homebrew is not the answer on Linux"
    assert "ffmpeg" in combined
    for manager in ("apt-get", "dnf", "pacman"):
        assert manager in combined, f"{manager} not named among what was looked for"


@pytest.mark.skipif(
    os.getuid() == 0,
    reason="as root there is nothing for sudo to provide, and the branch "
           "under test is the one that needs it",
)
def test_no_sudo_on_linux_is_explained_rather_than_dying_silently(tmp_path):
    """A Linux box with no sudo used to exit 1 having printed the banner.

    `detect_sudo` ended in `have_command sudo && SUDO="sudo"`, which made a
    missing sudo the function's own exit status. An `&&` list does not trip
    `set -e` inside a function, but the unguarded `detect_sudo` in preflight
    is a plain command, so the script died there -- before step 1, with
    nothing on stdout or stderr to say why.

    install_packages has always had the right message for this case; it
    could just never be reached. macOS never saw any of it, because
    PKG=brew returns from detect_sudo two lines earlier.
    """
    path_dir = stub_path(
        # No sudo, and no apt-get either: if this run ever gets as far as
        # attempting the install, that is the bug back again.
        tmp_path, tools=("uv", "ffmpeg", "curl"),
        scripts={
            # Nothing in its output, so PortAudio is genuinely missing and
            # root is genuinely required.
            "ldconfig": "#!/bin/sh\nexit 0\n",
        },
    )
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1",
        KCGX_SETUP_OS="linux", KCGX_SETUP_PKG="apt",
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, "a package it cannot install is fatal"
    # The regression itself: dying inside preflight leaves only the banner,
    # so reaching step 1 at all is the thing being pinned.
    assert "Step 1/7" in combined, f"died before preflight finished: {combined!r}"
    assert "sudo is not available" in combined, combined
    assert "libportaudio2" in combined, "never named what has to be installed"


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
    # took the decline branch via the "Nothing installed" message that only
    # it prints. Declining is fatal rather than merely skipped: ffmpeg is
    # genuinely absent here, and carrying on to install a launcher for a
    # cockpit that cannot play anything is worse than stopping.
    combined = result.stdout + result.stderr
    assert "Nothing installed" in combined
    assert result.returncode != 0, "declining left the cockpit unopenable"
    assert not log.exists(), "declining still installed something"


CURL_FOR_UV_INSTALL = """#!/bin/sh
""" + ANSWER_VERSION + """echo "$@" >> "$CURL_LOG"
# Concatenated, not an f-string: the install script below is full of shell
# ${...} expansions that Python would read as format fields.
#
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
printf '#!/bin/sh\ncase "$*" in *kcgx.selfcheck*) echo "selfcheck ok" ;; esac\nexit 0\n' > "$HOME/.local/bin/uv"
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
        tmp_path, tools=("ffmpeg",),
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
        tmp_path, tools=("ffmpeg",),
        scripts={"curl": CURL_FOR_UV_INSTALL},
    )
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", CURL_LOG=str(log))
    assert result.returncode == 0
    assert "INSTALLER_NO_MODIFY_PATH=1" in log.read_text(), (
        "the astral installer was not told to leave shell profiles alone"
    )


def test_a_missing_uv_is_named_rather_than_blamed_on_the_sync(tmp_path):
    """A fresh Mac where the uv prompt was declined: uv was never installed.

    Dying inside `uv sync` at step 4 would be both wrong (there was no
    sync) and useless -- it does not say uv is missing, or how to get it.
    Step 3 owns that failure and has to say so itself.
    """
    path_dir = stub_path(tmp_path, tools=("ffmpeg", "curl"))
    result = subprocess.run(
        [str(SETUP)], input="n\n",
        env=setup_env(tmp_path, path_dir),
        capture_output=True, text=True, timeout=120,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Install uv now?" in result.stdout, "never reached the decline branch"
    assert "uv is required" in combined, "the missing dependency is not named"
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
        tmp_path, tools=("ffmpeg", "curl"),
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
        tmp_path, tools=("ffmpeg", "curl"),
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
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    link = tmp_path / "home" / ".local" / "bin" / "kcgx"
    assert link.is_symlink(), "must be a symlink"
    assert link.resolve() == (REPO / "bin" / "kcgx").resolve()


def test_relinking_is_a_no_op(tmp_path):
    path_dir = complete_env(tmp_path)
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

    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    assert result.returncode != 0
    assert (prefix / "kcgx").resolve() == stranger.resolve(), "it clobbered it"


def test_a_path_without_the_prefix_says_what_that_costs(tmp_path):
    """Without the prefix on PATH the cockpit still starts by its full path,
    and setup says so rather than leaving plain `kcgx` to fail later."""
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1")
    combined = result.stdout + result.stderr
    assert "is NOT on your PATH" in combined
    assert "bin/kcgx" in combined and "not as plain `kcgx`" in combined, combined


def test_a_path_with_the_prefix_does_not_warn(tmp_path):
    home = tmp_path / "home"
    prefix = home / ".local" / "bin"
    prefix.mkdir(parents=True)
    path_dir = complete_env(tmp_path)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1",
        PATH=f"{prefix}:{path_dir}",
    )
    assert result.returncode == 0
    assert (prefix / "kcgx").is_symlink(), "link_launcher did not run to completion"
    assert "is NOT on your PATH" not in result.stdout + result.stderr


def test_a_complete_environment_reaches_the_launch(tmp_path):
    """The end-to-end shape of a good install: no failures, no warnings.

    SHELL is set because step 5 needs to know which profile to offer to
    edit; without it setup cannot put $PREFIX on PATH, and step 7 warns
    that kcgx is not on it -- which is correct behaviour and not what this
    test is about.
    """
    path_dir = stub_path(tmp_path, tools=("uv", "ffmpeg", "curl"))
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh")
    assert result.returncode == 0, result.stdout + result.stderr
    # The hand-off message, not merely the string "kcgx" -- which appears in
    # the symlink line two steps earlier and would pass either way. And "Everything checks out", so a run that limped to the end on
    # warnings cannot be mistaken for a clean one.
    assert "Setup complete" in result.stdout
    assert "Everything checks out" in result.stdout


def test_exec_hands_off_by_absolute_path(tmp_path):
    """Load-bearing, not cosmetic: a user who has not reloaded their shell
    profile yet must still get a cockpit on this first run, which only
    works if the hand-off resolves `bin/kcgx` by absolute path rather than
    trusting PATH to contain it already.

    No test exercises the `exec` line itself -- every test in this file
    sets KCGX_SETUP_NO_LAUNCH=1, so the script always exits before
    reaching it. This is the cheap, static substitute: assert the source
    on disk, comments stripped first, so a comment mentioning the bare name
    cannot trip it.
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


# ---------------------------------------------------------------------------
# Step 5's second half: KCGX.app, the cockpit's own window (macOS)
#
# setup.sh runs macos/build.sh, which tests/test_window.py covers on its own.
# Here the real build.sh runs with a fake swiftc and a fake codesign, so
# nothing is compiled, and the app goes where KCGX_APP says or under the
# test's own HOME: never into anybody's ~/Applications.

# Writes the "binary" where -o says, as build.sh expects of a compiler.
FAKE_SWIFTC = """#!/bin/sh
printf '%s\\n' "$*" >> "$SWIFTC_LOG"
while [ $# -gt 0 ]; do
    if [ "$1" = "-o" ]; then printf 'compiled\\n' > "$2"; fi
    shift
done
"""
SWIFTC_FAILS = """#!/bin/sh
printf '%s\\n' "$*" >> "$SWIFTC_LOG"
echo "error: no such module 'Cocoa'" >&2
exit 1
"""
# Signs anything, and verifies whatever still holds what the fake compiler wrote.
FAKE_CODESIGN = """#!/bin/sh
case "$1" in
    --verify) for last; do :; done; grep compiled "$last/Contents/MacOS/KCGX" >/dev/null 2>&1 ;;
    *) exit 0 ;;
esac
"""


def window_env(tmp_path, *, swiftc=FAKE_SWIFTC, **scripts):
    """complete_env, with what build.sh runs beside setup.sh's own tools.
    `swiftc=None` is a Mac without the command line tools."""
    fakes = {"codesign": FAKE_CODESIGN, **scripts}
    if swiftc is not None:
        fakes["swiftc"] = swiftc
    path_dir = complete_env(tmp_path, **fakes)
    (path_dir / "mv").symlink_to(shutil.which("mv"))
    return path_dir


def run_setup_for_the_window(tmp_path, path_dir, *args, **env):
    env.setdefault("KCGX_APP", tmp_path / "apps" / "KCGX.app")
    return run_setup(
        tmp_path, path_dir, *args,
        **{"KCGX_SETUP_YES": "1", "SHELL": "/bin/zsh", "SWIFTC_LOG": tmp_path / "swiftc.log", **env},
    )


def step(result, number):
    """What a run printed for one step, the warnings of the whole run with it."""
    after = result.stdout.split(f"Step {number}/7", 1)[1]
    return after.split(f"Step {number + 1}/7", 1)[0] + result.stderr


def test_step_five_builds_the_window_where_kcgx_app_says(tmp_path):
    app = tmp_path / "apps" / "KCGX.app"
    result = run_setup_for_the_window(tmp_path, window_env(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Step 5/7  The launcher on your PATH, and its window" in result.stdout
    assert (app / "Contents" / "MacOS" / "KCGX").read_text() == "compiled\n"
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == "com.kcgx.cockpit"
    assert info["KCGXRepo"] == str(REPO)
    assert str(app) in step(result, 5)
    assert "browser" not in step(result, 5)
    assert not (tmp_path / "home" / "Applications").exists(), "built somewhere KCGX_APP did not say"
    assert (tmp_path / "home" / ".local" / "bin" / "kcgx").is_symlink(), "the window replaced the link"
    assert "Setup complete" in result.stdout and "Everything checks out" in result.stdout


def test_the_window_goes_where_the_launcher_will_look_for_it(tmp_path, monkeypatch):
    """Two programs in two languages agree on one default, as with the
    User-Agent: setup builds the app where kcgx.launcher looks when nobody
    has said. The home folder here is the test's own."""
    from kcgx import launcher

    path_dir = window_env(tmp_path)
    env = setup_env(tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh", SWIFTC_LOG=tmp_path / "swiftc.log")
    assert "KCGX_APP" not in env
    result = subprocess.run([str(SETUP)], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    built = tmp_path / "home" / "Applications" / "KCGX.app"
    assert (built / "Contents" / "MacOS" / "KCGX").exists()

    monkeypatch.delenv("KCGX_APP", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert launcher.app_path() == built


def test_the_window_knows_the_path_that_finds_uv(tmp_path):
    """A Dock launch has no shell PATH; the app runs bin/kcgx with the one
    it was built with. Built after the PATH question, so it holds the answer."""
    app = tmp_path / "apps" / "KCGX.app"
    path_dir = window_env(tmp_path)
    assert run_setup_for_the_window(tmp_path, path_dir).returncode == 0
    built_with = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())["KCGXPath"].split(":")
    assert built_with == [str(tmp_path / "home" / ".local" / "bin"), str(path_dir)]


def test_building_the_window_again_replaces_it(tmp_path):
    app = tmp_path / "apps" / "KCGX.app"
    path_dir = window_env(tmp_path)
    assert run_setup_for_the_window(tmp_path, path_dir).returncode == 0
    stale = app / "Contents" / "old.txt"
    stale.write_text("from the build before")
    second = run_setup_for_the_window(tmp_path, path_dir)
    assert second.returncode == 0, second.stdout + second.stderr
    assert not stale.exists() and (app / "Contents" / "MacOS" / "KCGX").exists()
    assert len((tmp_path / "swiftc.log").read_text().splitlines()) == 2


def test_without_swiftc_the_cockpit_opens_in_the_browser_and_setup_carries_on(tmp_path):
    app = tmp_path / "apps" / "KCGX.app"
    result = run_setup_for_the_window(tmp_path, window_env(tmp_path, swiftc=None))
    assert result.returncode == 0, result.stdout + result.stderr
    said = step(result, 5)
    assert "swiftc" in said and "browser" in said, said
    assert "xcode-select --install" in said, "no way to get a window later is offered"
    assert not app.exists() and not app.parent.exists()
    # Not having a window is not something wrong with the install.
    assert "Setup complete" in result.stdout and "Everything checks out" in result.stdout
    assert result.stderr == ""


def test_a_window_that_will_not_build_is_a_warning_and_never_fatal(tmp_path):
    app = tmp_path / "apps" / "KCGX.app"
    result = run_setup_for_the_window(tmp_path, window_env(tmp_path, swiftc=SWIFTC_FAILS))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no such module" in result.stderr, "the compiler's own words were swallowed"
    assert "setup: KCGX.app was not built" in result.stderr and "browser" in result.stderr
    assert not app.exists()
    for n in (6, 7):
        assert f"Step {n}/7" in result.stdout, "setup stopped at the failed build"
    assert "Setup complete" in result.stdout


def test_something_else_where_the_window_goes_is_left_alone(tmp_path):
    """build.sh replaces only an app it built. Setup passes that on as a
    warning and neither removes the stranger nor stops."""
    app = tmp_path / "apps" / "KCGX.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text("somebody else's app")
    result = run_setup_for_the_window(tmp_path, window_env(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (app / "Contents" / "Info.plist").read_text() == "somebody else's app"
    assert not (tmp_path / "swiftc.log").exists(), "compiled for a place it may not use"
    assert "setup: KCGX.app was not built" in result.stderr
    assert "Setup complete" in result.stdout


def test_linux_is_not_offered_a_window(tmp_path):
    """Even with a swiftc to hand (Swift runs on Linux; Cocoa does not)."""
    app = tmp_path / "apps" / "KCGX.app"
    path_dir = window_env(tmp_path, ldconfig=LDCONFIG_WITH_PORTAUDIO)
    result = run_setup_for_the_window(tmp_path, path_dir, KCGX_SETUP_OS="linux", KCGX_SETUP_PKG="apt")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "swiftc.log").exists() and not app.exists()
    combined = result.stdout + result.stderr
    for word in ("KCGX.app", "window", "swiftc"):
        assert word not in combined, f"Linux was told about {word}: {combined}"
    assert "Step 5/7  The launcher on your PATH\n" in result.stdout
    assert "Setup complete" in result.stdout and "Everything checks out" in result.stdout


# `--verify` alone links nothing, so plain `kcgx` has to be on the PATH
# already, or its own warning is counted among the ones these tests count.
KCGX_ON_PATH = "#!/bin/sh\nexit 0\n"


def test_verify_says_the_window_is_there_and_signed(tmp_path):
    app = tmp_path / "apps" / "KCGX.app"
    path_dir = window_env(tmp_path, kcgx=KCGX_ON_PATH)
    assert run_setup_for_the_window(tmp_path, path_dir).returncode == 0
    result = run_setup_for_the_window(tmp_path, path_dir, "--verify")
    assert result.returncode == 0, result.stdout + result.stderr
    [row] = [line for line in result.stdout.splitlines() if line.startswith("  window")]
    assert row.split()[1] == "ok" and str(app) in row, row
    assert "Everything checks out" in result.stdout


def test_verify_warns_about_a_window_whose_signature_does_not_hold(tmp_path):
    """macOS will not start an app whose signature is broken, so `kcgx`
    would fall back to the browser every time with nothing to say why."""
    app = tmp_path / "apps" / "KCGX.app"
    path_dir = window_env(tmp_path, kcgx=KCGX_ON_PATH)
    assert run_setup_for_the_window(tmp_path, path_dir).returncode == 0
    (app / "Contents" / "MacOS" / "KCGX").write_text("tampered with\n")
    result = run_setup_for_the_window(tmp_path, path_dir, "--verify")
    assert result.returncode == 0, "the window is advisory: the cockpit still opens in the browser"
    [row] = [line for line in result.stdout.splitlines() if line.startswith("  window")]
    assert row.split()[1] == "warn" and "macos/build.sh" in row, row
    # The command it offers rebuilds this app: build.sh alone builds the one
    # in ~/Applications, which is not the one KCGX_APP has the launcher open.
    assert row.endswith(f"rebuild it: {REPO}/macos/build.sh {app}"), row
    assert "1 warning(s) above" in result.stdout


def test_setup_does_not_promise_a_question_before_everything(tmp_path):
    """Step 5 links the launcher and builds the window without asking (the
    plan's choice), so the banner and --help may not say every step asks."""
    path_dir = window_env(tmp_path)
    result = run_setup_for_the_window(tmp_path, path_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    banner = " ".join(result.stdout.split("Step 1/7", 1)[0].split())
    assert "asks before it changes anything" not in banner, banner
    assert "Step 5" in banner and "without asking" in banner, banner
    assert "idempotent" in banner
    usage = " ".join(run_setup(tmp_path, path_dir, "--help").stdout.split())
    assert "asking before each step that changes anything" not in usage, usage
    assert "without asking" in usage, usage


def test_verify_without_a_window_says_so_and_does_not_count_it_against_the_install(tmp_path):
    path_dir = window_env(tmp_path, swiftc=None, kcgx=KCGX_ON_PATH)
    result = run_setup_for_the_window(tmp_path, path_dir, "--verify")
    assert result.returncode == 0, result.stdout + result.stderr
    [row] = [line for line in result.stdout.splitlines() if line.startswith("  window")]
    assert row.split()[1] not in ("ok", "warn", "FAIL") and "browser" in row, row
    assert "Everything checks out" in result.stdout


def test_verify_on_linux_has_no_window_row(tmp_path):
    path_dir = window_env(tmp_path, ldconfig=LDCONFIG_WITH_PORTAUDIO, kcgx=KCGX_ON_PATH)
    result = run_setup_for_the_window(tmp_path, path_dir, "--verify", KCGX_SETUP_OS="linux", KCGX_SETUP_PKG="apt")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "window" not in result.stdout and "Everything checks out" in result.stdout


# ---------------------------------------------------------------------------
# Platform detection
#
# With no adsb-tui release to download there is no asset to match, so any
# processor will do: the row reports what setup sees, and ARM Linux, which
# used to stop the install, goes through.

def uname_stub(system, machine):
    return f"""#!/bin/sh
case "${{1:-}}" in
    -s) echo "{system}" ;;
    -m) echo "{machine}" ;;
    *)  echo "{system}" ;;
esac
"""


@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Darwin", "arm64", "macos arm64"),
        ("Darwin", "x86_64", "macos x86_64"),
        ("Linux", "x86_64", "linux x86_64"),
        ("Linux", "aarch64", "linux aarch64"),
        ("OpenBSD", "amd64", "unsupported amd64"),
    ],
)
def test_the_platform_row_says_what_setup_sees(tmp_path, system, machine, expected):
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "curl"),
        scripts={"uname": uname_stub(system, machine)},
    )
    env = setup_env(tmp_path, path_dir)
    del env["KCGX_SETUP_OS"]  # the point is what setup.sh works out
    result = subprocess.run(
        [str(SETUP), "--check"], env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0
    platform_row = next(line for line in result.stdout.splitlines() if "platform" in line)
    assert expected in platform_row, platform_row


def test_arm_linux_installs_rather_than_stopping(tmp_path):
    """It used to stop: adsb-tui published no ARM Linux build. Nothing here
    is processor specific any more."""
    path_dir = complete_env(
        tmp_path,
        uname=uname_stub("Linux", "aarch64"),
        ldconfig=LDCONFIG_WITH_PORTAUDIO,
    )
    env = setup_env(tmp_path, path_dir, KCGX_SETUP_YES="1", KCGX_SETUP_PKG="apt", SHELL="/bin/zsh")
    del env["KCGX_SETUP_OS"]
    result = subprocess.run([str(SETUP)], env=env, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Setup complete" in result.stdout


# ---------------------------------------------------------------------------
# PortAudio: the dependency that was never written down

def test_portaudio_is_installed_on_linux(tmp_path):
    """`import sounddevice` raises OSError("PortAudio library not found")
    without it, so the server cannot play anything at all. The macOS wheel bundles its own copy, which
    is why this went unnoticed: the only machine that needs the package is
    the only one nobody installed on.
    """
    log = tmp_path / "apt.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "curl"),
        scripts={
            "apt-get": f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n',
            "sudo": SUDO_PASSTHROUGH,
            # No libportaudio in its output: the missing case.
            "ldconfig": "#!/bin/sh\nexit 0\n",
        },
    )
    run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1",
        KCGX_SETUP_OS="linux", KCGX_SETUP_PKG="apt",
    )
    assert log.exists(), "apt-get was never called"
    assert "libportaudio2" in log.read_text(), log.read_text()


def test_portaudio_is_not_a_package_on_macos(tmp_path):
    """Asking Homebrew for it would be wrong, not merely redundant: the
    wheel loads the copy it ships with, so a brew portaudio is a second
    library that nothing reads.
    """
    log = tmp_path / "brew.log"
    path_dir = complete_env(tmp_path)
    run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", BREW_LOG=str(log))
    installed = log.read_text() if log.exists() else ""
    assert "portaudio" not in installed, installed


def test_a_present_portaudio_is_not_reinstalled(tmp_path):
    log = tmp_path / "apt.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "ffmpeg", "curl"),
        scripts={
            "apt-get": f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n',
            "ldconfig": LDCONFIG_WITH_PORTAUDIO,
        },
    )
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1",
        KCGX_SETUP_OS="linux", KCGX_SETUP_PKG="apt",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not log.exists(), "installed a PortAudio that was already there"


# ---------------------------------------------------------------------------
# The PATH, and the shell profile
#
# setup.sh used to refuse to touch a shell profile on principle, print the
# export line, and leave it there -- which meant plain `kcgx` did nothing
# for anyone who did not act on a message several steps up. It now asks. Asking is the whole difference: the edit is visible, declinable,
# backed up, and applied once.

def profile_of(tmp_path, name=".zshrc"):
    return tmp_path / "home" / name


def test_the_profile_edit_is_offered_and_applied(tmp_path):
    path_dir = complete_env(tmp_path)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh",
    )
    assert result.returncode == 0
    profile = profile_of(tmp_path)
    assert profile.exists(), "the profile was never written"
    body = profile.read_text()
    assert "added by kcgx setup.sh" in body, body
    assert ".local/bin" in body, body


def test_declining_the_profile_edit_leaves_it_alone(tmp_path):
    """Answering no has to mean no, and the run must still finish: an
    un-edited PATH costs you plain `kcgx`, not the cockpit.
    """
    path_dir = complete_env(tmp_path)
    env = setup_env(tmp_path, path_dir, SHELL="/bin/zsh")
    # Everything is already installed here, so steps 2 and 3 ask nothing.
    # The three prompts that remain, in order: sync (4), the profile edit
    # (5), the feed list (6). Answered explicitly rather than with
    # KCGX_SETUP_YES, which would take the default on the one prompt this
    # test is about.
    result = subprocess.run(
        [str(SETUP)], input="y\nn\ny\n",
        env=env, capture_output=True, text=True, timeout=120,
    )
    combined = result.stdout + result.stderr
    assert "Append it to" in combined, "never offered the edit"
    assert not profile_of(tmp_path).exists(), "edited the profile anyway"
    assert "Not appended" in combined, combined


def test_the_profile_edit_is_not_repeated(tmp_path):
    """The second run is the one you do when you think something went
    wrong, and two export lines is how a PATH ends up with duplicates
    nobody can account for.
    """
    path_dir = complete_env(tmp_path)
    first = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh")
    assert first.returncode == 0
    after_first = profile_of(tmp_path).read_text()
    second = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh")
    assert second.returncode == 0
    assert profile_of(tmp_path).read_text() == after_first, "appended twice"


def test_an_existing_profile_is_backed_up_before_it_is_touched(tmp_path):
    profile = profile_of(tmp_path)
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("alias ll='ls -l'\n")
    path_dir = complete_env(tmp_path)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh",
    )
    assert result.returncode == 0
    backup = profile.with_suffix(profile.suffix + ".kcgx-backup")
    assert backup.exists(), "no backup was taken"
    assert backup.read_text() == "alias ll='ls -l'\n", "backup is not the original"
    assert "alias ll='ls -l'" in profile.read_text(), "clobbered what was there"


def test_fish_gets_fish_syntax(tmp_path):
    """`export PATH=...` is a syntax error in fish, so a profile edit that
    ignored the shell would break the login it was meant to fix.
    """
    path_dir = complete_env(tmp_path)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/usr/local/bin/fish",
    )
    assert result.returncode == 0
    profile = tmp_path / "home" / ".config" / "fish" / "config.fish"
    assert profile.exists(), "fish config was never written"
    body = profile.read_text()
    assert "fish_add_path" in body, body
    assert "export PATH=" not in body, body


def test_an_unknown_shell_is_told_rather_than_guessed_at(tmp_path):
    path_dir = complete_env(tmp_path)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/ksh",
    )
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "no profile setup.sh knows how to" in combined, combined
    assert not profile_of(tmp_path).exists()
    assert not profile_of(tmp_path, ".profile").exists()


# ---------------------------------------------------------------------------
# Step 7, which is the whole "it works when I am done" claim

def test_verify_starts_the_server_rather_than_stat_ing_it(tmp_path):
    """A server that will not serve the page fails the install, with the
    self check's own reason shown under it."""
    uv = """#!/bin/sh
case "$*" in
    *kcgx.selfcheck*) echo "health     ok    kcgx 0.1.0"; echo "websocket  FAIL  the first frame was None"; echo "selfcheck failed"; exit 1 ;;
esac
echo 2
exit 0
"""
    path_dir = complete_env(tmp_path, uv=uv)
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh")
    combined = result.stdout + result.stderr
    assert result.returncode != 0, "a server that will not serve was called fine"
    assert "server" in combined and "FAIL" in combined
    assert "the first frame was None" in combined, "the reason was not shown"
    assert "Setup complete" not in combined


def test_verify_runs_the_self_check_in_the_repo(tmp_path):
    log = tmp_path / "uv.log"
    uv = f"""#!/bin/sh
echo "$@" >> "{log}"
case "$*" in
    *kcgx.selfcheck*) echo "selfcheck ok" ;;
esac
echo 2
exit 0
"""
    path_dir = complete_env(tmp_path, uv=uv)
    result = run_setup(tmp_path, path_dir, "--verify", SHELL="/bin/zsh")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = log.read_text()
    assert f"run --project {REPO} python -m kcgx.selfcheck" in calls, calls
    assert "health, page and WebSocket answer" in result.stdout


def test_verify_catches_dependencies_that_will_not_import(tmp_path):
    """uv sync exiting 0 is not the same claim as `import sounddevice`
    working -- PortAudio is a system library the sync knows nothing about.
    """
    uv = """#!/bin/sh
case "$*" in
    *"import numpy"*) exit 1 ;;
esac
echo 2
exit 0
"""
    path_dir = complete_env(tmp_path, uv=uv)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh",
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "python deps" in combined and "FAIL" in combined
    assert "import sounddevice" in combined, "no way to reproduce it by hand"


def test_verify_warns_about_a_missing_audio_device_without_blocking(tmp_path):
    """Headless boxes, containers and unplugged docks are real, and not
    something setup can fix. The radar and the meters still work.
    """
    uv = """#!/bin/sh
case "$*" in
    *kcgx.selfcheck*) echo "selfcheck ok"; exit 0 ;;
    *max_output_channels*) echo 0; exit 0 ;;
esac
exit 0
"""
    path_dir = complete_env(tmp_path, uv=uv)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh",
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, "a missing speaker is not a failed install"
    assert "audio output" in combined and "warn" in combined
    assert "Setup complete" in combined


def test_verify_alone_changes_nothing(tmp_path):
    path_dir = complete_env(tmp_path)
    result = run_setup(tmp_path, path_dir, "--verify", SHELL="/bin/zsh")
    home = tmp_path / "home"
    assert "Checking it works" in result.stdout
    assert not (home / ".local" / "bin" / "kcgx").exists()
    assert not (home / ".zshrc").exists()


# ---------------------------------------------------------------------------

def test_every_step_that_changes_the_machine_asks_first(tmp_path):
    """The contract, stated as a test: nothing significant happens without
    a question. Driven by declining the very first prompt and checking that
    the machine is untouched -- a step that acted before asking would leave
    its evidence behind regardless of the answer.
    """
    log = tmp_path / "brew.log"
    path_dir = stub_path(
        tmp_path, tools=("uv", "curl"),   # ffmpeg missing
        scripts={"brew": BREW_RECORDER},
    )
    result = subprocess.run(
        [str(SETUP)], input="n\n",
        env=setup_env(tmp_path, path_dir, BREW_LOG=str(log), SHELL="/bin/zsh"),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode != 0
    home = tmp_path / "home"
    assert not log.exists(), "installed before asking"
    assert not (home / ".local" / "bin" / "kcgx").exists(), "linked before asking"
    assert not (home / ".zshrc").exists(), "edited the profile before asking"


def test_the_steps_are_numbered_and_counted(tmp_path):
    """"Poking around to figure out what it wants" was the original
    complaint. A run that says which of how many steps it is on answers
    that continuously rather than once at the top.
    """
    path_dir = complete_env(tmp_path)
    result = run_setup(tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh")
    assert result.returncode == 0
    for n in range(1, 8):
        assert f"Step {n}/7" in result.stdout, f"step {n} never announced"
    assert "Step 8" not in result.stdout


# ---------------------------------------------------------------------------
# Step 6: the feed cache
#
# LiveATC refuses roughly three requests in four, so the server's eight
# start-time attempts fail about 10% of the time -- and when they do the
# stack opens on the single configured feed with no sign the airport has
# eleven others. Filling the cache here is the fix, because out here nobody
# is waiting on a page and it can afford twenty tries.

def test_the_feed_cache_is_warmed_before_the_launch(tmp_path):
    log = tmp_path / "uv.log"
    uv = f"""#!/bin/sh
echo "$@" >> "{log}"
case "$*" in
    *kcgx.selfcheck*) echo "selfcheck ok"; exit 0 ;;
    *current_icao*) echo KPDX ;;
esac
echo 2
exit 0
"""
    path_dir = complete_env(tmp_path, uv=uv)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "kcgx-web --refresh-feeds --icao KPDX" in log.read_text(), log.read_text()
    assert "The LiveATC feed list" in result.stdout


def test_a_refused_feed_list_does_not_fail_the_install(tmp_path):
    """It is a week-long cache, not a dependency. LiveATC being unreachable
    right now is no reason to refuse to install the cockpit -- and it tries
    again when it starts anyway.
    """
    uv = """#!/bin/sh
case "$*" in
    *kcgx.selfcheck*) echo "selfcheck ok"; exit 0 ;;
    *current_icao*) echo KPDX; exit 0 ;;
    *--refresh-feeds*) echo "Could not reach LiveATC" >&2; exit 1 ;;
esac
echo 2
exit 0
"""
    path_dir = complete_env(tmp_path, uv=uv)
    result = run_setup(
        tmp_path, path_dir, KCGX_SETUP_YES="1", SHELL="/bin/zsh",
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "could not cache the feed list" in combined, combined
    assert "Setup complete" in result.stdout


def test_the_feed_fetch_can_be_declined(tmp_path):
    log = tmp_path / "uv.log"
    uv = f"""#!/bin/sh
echo "$@" >> "{log}"
case "$*" in
    *kcgx.selfcheck*) echo "selfcheck ok"; exit 0 ;;
    *current_icao*) echo KPDX ;;
esac
echo 2
exit 0
"""
    path_dir = complete_env(tmp_path, uv=uv)
    # Prompts, in order: sync (4), profile (5), feeds (6).
    result = subprocess.run(
        [str(SETUP)], input="y\ny\nn\n",
        env=setup_env(tmp_path, path_dir, SHELL="/bin/zsh"),
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--refresh-feeds" not in log.read_text()
    assert "Skipped" in result.stdout, result.stdout
    # The page has no FEEDS button to send anyone to: the retry is the airport.
    assert "open FEEDS" not in result.stdout, result.stdout
    assert "choose the airport again" in result.stdout, result.stdout


def test_setup_and_the_radar_send_the_same_user_agent():
    """One User-Agent, spelled in two languages that cannot share a constant.

    The server's radar sends kcgx.radar.DEFAULT_UA to adsb.lol on every poll;
    step 7 probes adsb.lol with setup.sh's ADSB_UA. A check that sends a
    different request than the radar does proves nothing about the radar,
    which is the whole reason step 7 sends a UA at all -- so make the drift
    fail here, where it is cheap.
    """
    from kcgx.radar import DEFAULT_UA

    setup_ua = re.search(r'^ADSB_UA="([^"]+)"$', SETUP.read_text(), re.M)
    assert setup_ua, "setup.sh no longer spells ADSB_UA where this can read it"
    assert setup_ua.group(1) == DEFAULT_UA, (
        f"setup.sh and the radar disagree about the User-Agent: {setup_ua.group(1)!r} vs {DEFAULT_UA!r}"
    )
    # adsb.lol's 403 is "User-Agent too generic; include valid contact info",
    # so a bare product token is refused exactly like no header at all.
    assert "http" in DEFAULT_UA or "@" in DEFAULT_UA, "no contact in the User-Agent"


def test_nothing_left_in_setup_mentions_what_phase_e_removed():
    """Comments may tell the history; commands and messages may not ask for
    tmux, adsb-tui or its config, or squelch, which no longer exist here."""
    code = [
        line for line in SETUP.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for gone in ("tmux", "adsb-tui", "ads-b-tui", "squelch", "Ctrl-b"):
        offending = [line for line in code if gone in line]
        assert not offending, f"setup.sh still uses {gone!r}: {offending}"
