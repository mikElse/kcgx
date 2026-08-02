"""Tests for the kcgx cockpit launcher.

These drive a real tmux, but on a private socket and with harmless stand-in
commands, so they never touch the user's tmux sessions and never launch
adsb-tui, squelch, ffmpeg, or an ASR model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "bin" / "kcgx"

pytestmark = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux is not installed"
)

# Stand-ins that sit still and exit cleanly when killed.
FAKE_ADSB = "sleep 300"
FAKE_SQUELCH = "sleep 300"


@pytest.fixture
def cockpit():
    """Give each test its own tmux socket and session, and tear both down."""
    socket = f"kcgx-test-{uuid.uuid4().hex[:8]}"
    session = f"kcgx-test-{uuid.uuid4().hex[:8]}"

    def run(size="200x50", detached=True, **overrides):
        env = {
            **os.environ,
            "KCGX_SOCKET": socket,
            "KCGX_SESSION": session,
            "KCGX_DETACHED": "1",
            "KCGX_SIZE": size,
            "KCGX_ADSB_CMD": FAKE_ADSB,
            "KCGX_SQUELCH_CMD": FAKE_SQUELCH,
        }
        if size is None:  # exercise the real size-detection path
            del env["KCGX_SIZE"]
        if not detached:  # let it reach the exec/attach branch
            del env["KCGX_DETACHED"]
        env.pop("TMUX", None)
        env.update({k: str(v) for k, v in overrides.items()})
        return subprocess.run(
            [str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=30
        )

    def tmux(*args):
        return subprocess.run(
            ["tmux", "-L", socket, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    run.tmux = tmux
    run.session = session
    run.socket = socket
    yield run

    subprocess.run(
        ["tmux", "-L", socket, "kill-server"], capture_output=True, timeout=30
    )


def panes(cockpit, fmt):
    result = cockpit.tmux("list-panes", "-t", f"={cockpit.session}:cockpit", "-F", fmt)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()


def pane_field(cockpit, field):
    """Map pane index -> field value. Handles panes whose field is empty."""
    out = {}
    for line in panes(cockpit, "#{pane_index}\t#{" + field + "}"):
        index, _, value = line.partition("\t")
        out[int(index)] = value.strip()
    return out


def test_launcher_is_executable():
    assert os.access(LAUNCHER, os.X_OK), "bin/kcgx must be executable"


def test_builds_three_panes(cockpit):
    assert cockpit().returncode == 0
    assert len(panes(cockpit, "#{pane_index}")) == 3


def test_squelch_column_is_exactly_48_wide(cockpit):
    """48 is squelch's design width; narrower and its header truncates."""
    cockpit()
    widths = {i: int(v) for i, v in pane_field(cockpit, "pane_width").items()}
    assert widths[1] == 48, f"squelch pane is {widths[1]} columns, want 48"
    assert widths[2] == 48, f"shell pane is {widths[2]} columns, want 48"
    assert widths[0] > 48, "adsb-tui should get the remaining width"


def test_shell_pane_is_short_so_squelch_keeps_the_column(cockpit):
    cockpit()
    heights = {i: int(v) for i, v in pane_field(cockpit, "pane_height").items()}
    assert heights[2] == 12, f"shell pane is {heights[2]} rows, want 12"
    assert heights[1] > heights[2], "squelch should get more height than the shell"


def test_commands_land_in_the_right_panes(cockpit):
    cockpit()
    commands = pane_field(cockpit, "pane_start_command")
    # tmux reports the start command quoted.
    assert FAKE_ADSB in commands[0]
    assert FAKE_SQUELCH in commands[1]
    assert commands[2] == "", "pane 2 should be a plain shell, not a command"


def test_second_invocation_attaches_instead_of_duplicating(cockpit):
    """squelch keeps its transcript; you don't pay the model load twice."""
    assert cockpit().returncode == 0
    first = panes(cockpit, "#{pane_id}")

    assert cockpit().returncode == 0
    assert panes(cockpit, "#{pane_id}") == first, "panes were rebuilt, not reattached"

    sessions = cockpit.tmux("list-sessions", "-F", "#{session_name}")
    assert sessions.stdout.count(cockpit.session) == 1


def test_refuses_a_terminal_too_narrow_to_be_useful(cockpit):
    result = cockpit(size="80x50")
    assert result.returncode != 0
    assert "80 columns" in result.stderr
    assert "at least 100" in result.stderr
    assert cockpit.tmux("has-session", "-t", f"={cockpit.session}").returncode != 0


def test_narrow_terminal_message_names_squelch_width(cockpit):
    """The error should say why 100, not just assert it."""
    assert "48" in cockpit(size="80x50").stderr


def test_config_applies_even_when_a_tmux_server_is_already_running(cockpit):
    """Regression: `tmux -f` is only read when it *starts* the server.

    With a server already up, -f is ignored, so mouse mode and remain-on-exit
    silently never applied — the two things the cockpit exists for. Every other
    test uses a private socket and therefore always got a fresh server, which
    is exactly why the suite missed this.
    """
    pre = subprocess.run(
        ["tmux", "-L", cockpit.socket, "new-session", "-d", "-s", "pre", "sleep 60"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert pre.returncode == 0, pre.stderr

    assert cockpit().returncode == 0
    assert cockpit.tmux("show-options", "-g", "mouse").stdout.split() == ["mouse", "on"]
    assert "on" in cockpit.tmux("show-options", "-g", "remain-on-exit").stdout


def test_config_is_reapplied_so_edits_take_effect_without_killing_the_server(cockpit):
    """Editing kcgx.tmux.conf should not require killing a running server."""
    assert cockpit().returncode == 0
    cockpit.tmux("set-option", "-g", "mouse", "off")
    assert cockpit().returncode == 0  # reattach path
    assert cockpit.tmux("show-options", "-g", "mouse").stdout.split() == ["mouse", "on"]


def test_session_config_enables_mouse(cockpit):
    """Mouse mode is the feature; verify the config actually reached tmux."""
    cockpit()
    result = cockpit.tmux("show-options", "-g", "mouse")
    assert result.stdout.split() == ["mouse", "on"], result.stdout


def test_session_config_keeps_dead_panes_visible(cockpit):
    result_setup = cockpit()
    assert result_setup.returncode == 0
    result = cockpit.tmux("show-options", "-g", "remain-on-exit")
    assert "on" in result.stdout, result.stdout


def test_says_there_is_no_terminal_rather_than_inventing_a_width(cockpit):
    """Regression: `tput cols` does not fail without a tty — it silently
    returns terminfo's default (80 for xterm-256color), which looks like a
    real measurement. That produced "terminal is 80 columns" for a user whose
    window was 222 wide. Without a terminal there is also nothing to attach
    to, so the honest answer is to say that.
    """
    result = cockpit(size=None)
    assert result.returncode != 0
    assert "80 columns" not in result.stderr, (
        "reported a fabricated width instead of admitting there is no terminal: "
        + result.stderr
    )
    assert "terminal" in result.stderr.lower()


def test_accepts_a_real_wide_terminal(cockpit):
    """The user's actual case: a 222x48 terminal must not be refused.

    Runs the launcher under a genuine pty sized 222x48, so the size-detection
    path is exercised for real rather than via KCGX_SIZE.
    """
    import fcntl
    import struct
    import termios

    env = {
        **os.environ,
        "KCGX_SOCKET": cockpit.socket,
        "KCGX_SESSION": cockpit.session,
        "KCGX_DETACHED": "1",
        "KCGX_ADSB_CMD": FAKE_ADSB,
        "KCGX_SQUELCH_CMD": FAKE_SQUELCH,
        "TERM": "xterm-256color",
    }
    env.pop("KCGX_SIZE", None)

    # Size the pty BEFORE the child execs. Setting it afterwards races the
    # child, which then reads an unset size and falls back to 80 — that would
    # make this test pass for the wrong reason.
    controller, follower = os.openpty()
    fcntl.ioctl(follower, termios.TIOCSWINSZ, struct.pack("HHHH", 48, 222, 0, 0))

    pid = os.fork()
    if pid == 0:  # pragma: no cover - child process
        os.setsid()
        fcntl.ioctl(follower, termios.TIOCSCTTY, 0)
        for target in (0, 1, 2):
            os.dup2(follower, target)
        os.close(controller)
        os.close(follower)
        os.execve(str(LAUNCHER), [str(LAUNCHER)], env)
    os.close(follower)
    fd = controller

    output = b""
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            output += chunk
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    text = output.decode(errors="replace")

    assert os.waitstatus_to_exitcode(status) == 0, text
    assert "80 columns" not in text
    widths = {i: int(v) for i, v in pane_field(cockpit, "pane_width").items()}
    assert widths[0] + widths[1] + 1 == 222, f"session not sized to the pty: {widths}"
    assert widths[1] == 48


def test_attach_path_runs_tmux_rather_than_a_shell_function(cockpit):
    """Regression: the attach branch used `exec tm ...`, but `exec` bypasses
    shell functions and searches PATH, so it died with `exec: tm: not found`.

    Run without a tty so tmux refuses to attach — a *tmux* failure is fine and
    expected here; a shell "not found" is the bug.
    """
    assert cockpit().returncode == 0  # build the session first
    result = cockpit(detached=False)
    assert "not found" not in result.stderr, result.stderr
    assert "tm:" not in result.stderr, result.stderr


def test_switch_client_path_runs_tmux_rather_than_a_shell_function(cockpit):
    """Same bug on the other branch: running kcgx from inside tmux."""
    assert cockpit().returncode == 0
    result = cockpit(detached=False, TMUX="/tmp/fake-tmux-socket,1234,0")
    assert "not found" not in result.stderr, result.stderr
    assert "tm:" not in result.stderr, result.stderr


def test_reports_missing_tmux_with_an_actionable_message(tmp_path):
    """PATH without tmux — the user should be told how to fix it."""
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    for tool in ("bash", "env", "grep", "awk", "tput", "dirname", "pwd", "head"):
        found = shutil.which(tool)
        if found:
            (stub_bin / tool).symlink_to(found)

    result = subprocess.run(
        [str(LAUNCHER)],
        env={"PATH": str(stub_bin), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "tmux not found" in result.stderr
    assert "brew install tmux" in result.stderr
