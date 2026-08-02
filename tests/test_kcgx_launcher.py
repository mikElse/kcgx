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

    def run(size="200x50", **overrides):
        env = {
            **os.environ,
            "KCGX_SOCKET": socket,
            "KCGX_SESSION": session,
            "KCGX_DETACHED": "1",
            "KCGX_SIZE": size,
            "KCGX_ADSB_CMD": FAKE_ADSB,
            "KCGX_SQUELCH_CMD": FAKE_SQUELCH,
        }
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
