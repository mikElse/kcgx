"""Tests for the kcgx cockpit launcher.

These drive a real tmux, but on a private socket and with harmless stand-in
commands, so they never touch the user's tmux sessions and never launch
adsb-tui, squelch, ffmpeg, or an ASR model.
"""

from __future__ import annotations

import os
import re
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

# Stand-ins that sit still and exit cleanly when killed. `sh -c` is what
# makes them tolerate the flags kcgx now appends: the extra words land in
# $0/$1/... and are ignored.
FAKE_ADSB = "sh -c 'sleep 300'"
FAKE_SQUELCH = "sh -c 'sleep 300'"

# Every test gets a stand-in resolver by default. Without one, each launch
# would shell out to the real `uv run ... kcgx-airport resolve`, which reads
# the developer's own ~/.local/state/kcgx/airport -- making the suite depend
# on machine state, and paying for a uv invocation per test. The one test
# that *should* run the real thing asks for it explicitly.
FAKE_AIRPORT_RECORD = "KTST\t1.5\t-2.5\tTest Field"
FAKE_AIRPORT = f"""#!/bin/sh
out=""
while [ $# -gt 0 ]; do
    case "$1" in
        --out) out="$2"; shift 2 ;;
        *) shift ;;
    esac
done
if [ -n "$out" ]; then
    printf '%s\\n' "{FAKE_AIRPORT_RECORD}" > "$out"
else
    printf '%s\\n' "{FAKE_AIRPORT_RECORD}"
fi
"""


@pytest.fixture
def cockpit(tmp_path):
    """Give each test its own tmux socket and session, and tear both down.

    Yields `(run, tmux, session)`. The socket name hangs off `run.socket`
    for the few tests that need to plant something on the socket first.
    """
    socket = f"kcgx-test-{uuid.uuid4().hex[:8]}"
    session = f"kcgx-test-{uuid.uuid4().hex[:8]}"

    resolver = tmp_path / "kcgx-airport-default"
    resolver.write_text(FAKE_AIRPORT)
    resolver.chmod(0o755)

    def run(size="200x50", detached=True, launcher=LAUNCHER, args=(), **overrides):
        env = {
            **os.environ,
            "KCGX_SOCKET": socket,
            "KCGX_SESSION": session,
            "KCGX_DETACHED": "1",
            "KCGX_SIZE": size,
            "KCGX_ADSB_CMD": FAKE_ADSB,
            "KCGX_SQUELCH_CMD": FAKE_SQUELCH,
            "KCGX_AIRPORT_CMD": str(resolver),
        }
        if size is None:  # exercise the real size-detection path
            del env["KCGX_SIZE"]
        if not detached:  # let it reach the exec/attach branch
            del env["KCGX_DETACHED"]
        env.pop("TMUX", None)
        env.update({k: str(v) for k, v in overrides.items()})
        return subprocess.run(
            [str(launcher), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def tmux(*args):
        return subprocess.run(
            ["tmux", "-L", socket, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    run.socket = socket
    run.resolver = str(resolver)
    yield run, tmux, session

    subprocess.run(
        ["tmux", "-L", socket, "kill-server"], capture_output=True, timeout=30
    )


def panes(tmux, session, fmt):
    result = tmux("list-panes", "-t", f"={session}:cockpit", "-F", fmt)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()


def pane_field(tmux, session, field):
    """Map pane index -> field value. Handles panes whose field is empty."""
    out = {}
    for line in panes(tmux, session, "#{pane_index}\t#{" + field + "}"):
        index, _, value = line.partition("\t")
        out[int(index)] = value.strip()
    return out


def test_launcher_is_executable():
    assert os.access(LAUNCHER, os.X_OK), "bin/kcgx must be executable"


def test_builds_three_panes(cockpit):
    run, tmux, session = cockpit
    assert run().returncode == 0
    assert len(panes(tmux, session, "#{pane_index}")) == 3


def test_squelch_column_is_exactly_48_wide(cockpit):
    """48 is squelch's design width; narrower and its header truncates."""
    run, tmux, session = cockpit
    run()
    widths = {i: int(v) for i, v in pane_field(tmux, session, "pane_width").items()}
    assert widths[1] == 48, f"squelch pane is {widths[1]} columns, want 48"
    assert widths[2] == 48, f"shell pane is {widths[2]} columns, want 48"
    assert widths[0] > 48, "adsb-tui should get the remaining width"


def test_shell_pane_is_short_so_squelch_keeps_the_column(cockpit):
    run, tmux, session = cockpit
    run()
    heights = {i: int(v) for i, v in pane_field(tmux, session, "pane_height").items()}
    assert heights[2] == 12, f"shell pane is {heights[2]} rows, want 12"
    assert heights[1] > heights[2], "squelch should get more height than the shell"


def test_commands_land_in_the_right_panes(cockpit):
    run, tmux, session = cockpit
    run()
    commands = pane_field(tmux, session, "pane_start_command")
    # tmux reports the start command quoted.
    assert FAKE_ADSB in commands[0]
    assert FAKE_SQUELCH in commands[1]
    assert commands[2] == "", "pane 2 should be a plain shell, not a command"


def test_second_invocation_attaches_instead_of_duplicating(cockpit):
    """squelch keeps its transcript; you don't pay the model load twice."""
    run, tmux, session = cockpit
    assert run().returncode == 0
    first = panes(tmux, session, "#{pane_id}")

    assert run().returncode == 0
    assert panes(tmux, session, "#{pane_id}") == first, (
        "panes were rebuilt, not reattached"
    )

    sessions = tmux("list-sessions", "-F", "#{session_name}")
    assert sessions.stdout.count(session) == 1


def test_refuses_a_terminal_too_narrow_to_be_useful(cockpit):
    run, tmux, session = cockpit
    result = run(size="80x50")
    assert result.returncode != 0
    assert "80 columns" in result.stderr
    assert "at least 100" in result.stderr
    assert tmux("has-session", "-t", f"={session}").returncode != 0


def test_narrow_terminal_message_names_squelch_width(cockpit):
    """The error should say why 100, not just assert it."""
    run, _tmux, _session = cockpit
    assert "48" in run(size="80x50").stderr


def test_config_applies_even_when_a_tmux_server_is_already_running(cockpit):
    """Regression: `tmux -f` is only read when it *starts* the server.

    With a server already up, -f is ignored, so mouse mode and remain-on-exit
    silently never applied — the two things the cockpit exists for. Every other
    test uses a private socket and therefore always got a fresh server, which
    is exactly why the suite missed this.
    """
    run, tmux, _session = cockpit
    pre = subprocess.run(
        ["tmux", "-L", run.socket, "new-session", "-d", "-s", "pre", "sleep 60"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert pre.returncode == 0, pre.stderr

    assert run().returncode == 0
    assert tmux("show-options", "-g", "mouse").stdout.split() == ["mouse", "on"]
    assert "on" in tmux("show-options", "-g", "remain-on-exit").stdout


def test_config_is_reapplied_so_edits_take_effect_without_killing_the_server(cockpit):
    """Editing kcgx.tmux.conf should not require killing a running server."""
    run, tmux, _session = cockpit
    assert run().returncode == 0
    tmux("set-option", "-g", "mouse", "off")
    assert run().returncode == 0  # reattach path
    assert tmux("show-options", "-g", "mouse").stdout.split() == ["mouse", "on"]


def test_session_config_enables_mouse(cockpit):
    """Mouse mode is the feature; verify the config actually reached tmux."""
    run, tmux, _session = cockpit
    run()
    result = tmux("show-options", "-g", "mouse")
    assert result.stdout.split() == ["mouse", "on"], result.stdout


def test_session_config_keeps_dead_panes_visible(cockpit):
    run, tmux, _session = cockpit
    result_setup = run()
    assert result_setup.returncode == 0
    result = tmux("show-options", "-g", "remain-on-exit")
    assert "on" in result.stdout, result.stdout


def test_says_there_is_no_terminal_rather_than_inventing_a_width(cockpit):
    """Regression: `tput cols` does not fail without a tty — it silently
    returns terminfo's default (80 for xterm-256color), which looks like a
    real measurement. That produced "terminal is 80 columns" for a user whose
    window was 222 wide. Without a terminal there is also nothing to attach
    to, so the honest answer is to say that.
    """
    run, _tmux, _session = cockpit
    result = run(size=None)
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

    run, tmux, session = cockpit
    env = {
        **os.environ,
        "KCGX_SOCKET": run.socket,
        "KCGX_SESSION": session,
        "KCGX_DETACHED": "1",
        "KCGX_ADSB_CMD": FAKE_ADSB,
        "KCGX_SQUELCH_CMD": FAKE_SQUELCH,
        "KCGX_AIRPORT_CMD": run.resolver,
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
    widths = {i: int(v) for i, v in pane_field(tmux, session, "pane_width").items()}
    assert widths[0] + widths[1] + 1 == 222, f"session not sized to the pty: {widths}"
    assert widths[1] == 48


def test_attach_path_runs_tmux_rather_than_a_shell_function(cockpit):
    """Regression: the attach branch used `exec tm ...`, but `exec` bypasses
    shell functions and searches PATH, so it died with `exec: tm: not found`.

    Run without a tty so tmux refuses to attach — a *tmux* failure is fine and
    expected here; a shell "not found" is the bug.
    """
    run, _tmux, _session = cockpit
    assert run().returncode == 0  # build the session first
    result = run(detached=False)
    assert "not found" not in result.stderr, result.stderr
    assert "tm:" not in result.stderr, result.stderr


def test_switch_client_path_runs_tmux_rather_than_a_shell_function(cockpit):
    """Same bug on the other branch: running kcgx from inside tmux."""
    run, _tmux, _session = cockpit
    assert run().returncode == 0
    result = run(detached=False, TMUX="/tmp/fake-tmux-socket,1234,0")
    assert "not found" not in result.stderr, result.stderr
    assert "tm:" not in result.stderr, result.stderr


def test_works_when_invoked_through_a_symlink(cockpit, tmp_path):
    """Regression: the intended install is a symlink in ~/bin, but
    ${BASH_SOURCE[0]} reports the *invocation* path, not the link target. So
    dirname/.. resolved to ~ instead of the repo, and it died looking for
    ~/kcgx.tmux.conf. Every other test invokes the launcher by its real path,
    which is precisely why the suite missed it.
    """
    run, tmux, session = cockpit
    link = tmp_path / "kcgx"
    link.symlink_to(LAUNCHER)

    result = run(launcher=link)
    assert result.returncode == 0, result.stderr
    assert "No such file" not in result.stderr, result.stderr
    assert len(panes(tmux, session, "#{pane_index}")) == 3


def test_symlinked_invocation_still_applies_the_config(cockpit, tmp_path):
    """The config path is derived from the same resolution, so prove it too."""
    run, tmux, _session = cockpit
    link = tmp_path / "kcgx"
    link.symlink_to(LAUNCHER)

    assert run(launcher=link).returncode == 0
    assert tmux("show-options", "-g", "mouse").stdout.split() == ["mouse", "on"]


def test_stop_kills_a_running_cockpit(cockpit):
    run, tmux, session = cockpit
    assert run().returncode == 0
    assert tmux("has-session", "-t", f"={session}").returncode == 0

    result = run(args=("stop",))
    assert result.returncode == 0, result.stderr
    assert tmux("has-session", "-t", f"={session}").returncode != 0


def test_stop_is_idempotent_when_nothing_is_running(cockpit):
    """Stopping an already-stopped cockpit is not an error."""
    run, _tmux, _session = cockpit
    result = run(args=("stop",))
    assert result.returncode == 0, result.stderr
    assert "not running" in (result.stdout + result.stderr).lower()


def test_stop_leaves_other_tmux_sessions_alone(cockpit):
    """It must kill our session, not the tmux server — you may have others."""
    run, tmux, session = cockpit
    other = subprocess.run(
        ["tmux", "-L", run.socket, "new-session", "-d", "-s", "keepme", "sleep 60"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert other.returncode == 0, other.stderr
    assert run().returncode == 0

    assert run(args=("stop",)).returncode == 0
    assert tmux("has-session", "-t", f"={session}").returncode != 0
    assert tmux("has-session", "-t", "=keepme").returncode == 0


def test_stop_does_not_need_a_terminal(cockpit):
    """Unlike launching, stopping has nothing to attach to."""
    run, _tmux, _session = cockpit
    assert run().returncode == 0
    result = run(args=("stop",), size=None, detached=False)
    assert result.returncode == 0, result.stderr
    assert "terminal" not in result.stderr.lower()


def test_unknown_subcommand_is_rejected_with_usage(cockpit):
    run, _tmux, _session = cockpit
    result = run(args=("frobnicate",))
    assert result.returncode != 0
    assert "frobnicate" in result.stderr
    assert "stop" in result.stderr, "should show what it does accept"


def test_help_lists_the_subcommands(cockpit):
    run, _tmux, _session = cockpit
    result = run(args=("--help",))
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "stop" in combined
    assert "kcgx" in combined


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


# -- airport retargeting ---------------------------------------------------


AIRPORT_STUB = """#!/bin/sh
# Stand-in for kcgx-airport. Writes a fixed record wherever --out points.
mode="$1"; shift
record="$KCGX_TEST_RECORD"
out=""
while [ $# -gt 0 ]; do
    case "$1" in
        --out) out="$2"; shift 2 ;;
        *) shift ;;
    esac
done
[ -n "$KCGX_TEST_FAIL" ] && exit "$KCGX_TEST_FAIL"
if [ -n "$out" ]; then printf '%s\\n' "$record" > "$out"; else printf '%s\\n' "$record"; fi
"""


@pytest.fixture
def airport_stub(tmp_path):
    path = tmp_path / "kcgx-airport-stub"
    path.write_text(AIRPORT_STUB)
    path.chmod(0o755)
    return path


def pane_command(tmux, session, index):
    return tmux(
        "display-message", "-p", "-t", f"={session}:cockpit.{index}",
        "#{pane_start_command}",
    ).stdout.strip()


def test_launch_points_both_panes_at_the_resolved_airport(
    cockpit, airport_stub
):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KORD\t41.9786\t-87.9048\tChicago O'Hare",
    )
    adsb = pane_command(tmux, session, 0)
    squelch = pane_command(tmux, session, 1)
    assert "--site-lat 41.9786" in adsb
    assert "--site-lon -87.9048" in adsb
    assert "--icao KORD" in squelch


def test_go_moves_both_panes_to_the_new_airport(cockpit, airport_stub):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    assert "--site-lat 45.5887" in pane_command(tmux, session, 0)

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    assert result.returncode == 0, result.stderr

    adsb = pane_command(tmux, session, 0)
    squelch = pane_command(tmux, session, 1)
    assert "--site-lat 47.4479" in adsb and "--site-lon -122.3102" in adsb
    assert "--icao KSEA" in squelch
    assert "45.5887" not in adsb, "the old airport is still on screen"


def test_launch_and_go_build_the_same_command(cockpit, airport_stub):
    """The two paths must not drift; that is how three earlier bugs happened."""
    run, tmux, session = cockpit
    record = "KSEA\t47.4479\t-122.3102\tSeattle-Tacoma"
    run(KCGX_AIRPORT_CMD=str(airport_stub), KCGX_TEST_RECORD=record)
    at_launch = (pane_command(tmux, session, 0), pane_command(tmux, session, 1))

    run(args=("go",), KCGX_AIRPORT_CMD=str(airport_stub), KCGX_TEST_RECORD=record)
    after_go = (pane_command(tmux, session, 0), pane_command(tmux, session, 1))

    assert at_launch == after_go


def test_a_cancelled_pick_leaves_the_cockpit_alone(cockpit, airport_stub):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    before = pane_command(tmux, session, 0)

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="unused",
        KCGX_TEST_FAIL="1",
    )
    assert result.returncode == 0, "cancelling is not an error"
    assert pane_command(tmux, session, 0) == before


def test_go_reports_a_failed_search_instead_of_calling_it_a_cancel(
    cockpit, airport_stub
):
    """Exit 1 means the user declined; anything else is a real failure.

    Both leave the cockpit alone, but a failure that says nothing is
    indistinguishable from pressing escape, and the user is left thinking
    the search worked and their airport simply wasn't found.
    """
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    before = pane_command(tmux, session, 0)

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="unused",
        KCGX_TEST_FAIL="2",
    )
    assert result.returncode != 0
    assert result.stderr.strip(), "a silent failure reads exactly like a cancel"
    assert pane_command(tmux, session, 0) == before, "and still change nothing"


def test_a_truncated_record_is_a_failure_not_a_cancel(cockpit, airport_stub):
    """The resolver succeeded but the record is unusable — two fields, no
    longitude. Reporting that as exit 1 would tell bin/kcgx the user had
    pressed escape, and `kcgx go` would exit 0 having done nothing and said
    nothing. Only a decline may look like a decline.
    """
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    before = pane_command(tmux, session, 0)

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5",  # no lon, no label
    )
    assert result.returncode != 0, "a short record is not a cancelled pick"
    assert result.stderr.strip(), "and it must say so"
    assert pane_command(tmux, session, 0) == before


def test_the_popup_binding_actually_runs_the_airport_search(cockpit):
    """prefix + a is how the search is meant to be reached, and nothing else
    in the suite reads that binding: a typo in kcgx.tmux.conf, or renaming
    `kcgx go`, would ship green.
    """
    run, tmux, _session = cockpit
    assert run().returncode == 0  # the launcher is what sources the config

    bound = [
        line
        for line in tmux("list-keys", "-T", "prefix").stdout.splitlines()
        if re.search(r"-T\s+prefix\s+a\s", line)
    ]
    assert len(bound) == 1, f"expected exactly one prefix+a binding, got {bound}"
    assert "display-popup" in bound[0], bound[0]
    assert "kcgx go" in bound[0], bound[0]


def test_the_default_resolver_really_works(cockpit):
    """Every other test stubs the resolver, so all of them would still pass
    if `uv run ... kcgx-airport resolve` were broken — the launcher would
    quietly fall back to unconfigured panes. Run the real one once and
    require that it produced coordinates.

    Read-only: `resolve` never writes ~/.local/state/kcgx/airport (only
    `pick` does), so this leaves the developer's remembered airport alone.
    """
    run, tmux, session = cockpit
    assert run(KCGX_AIRPORT_CMD="").returncode == 0

    adsb = pane_command(tmux, session, 0)
    squelch = pane_command(tmux, session, 1)
    assert "--site-lat" in adsb and "--site-lon" in adsb, (
        "the real resolver produced no coordinates: " + adsb
    )
    assert re.search(r"--icao [A-Z]{4}\b", squelch), squelch


def test_go_without_a_running_cockpit_says_so(cockpit, airport_stub):
    run, _tmux, _session = cockpit
    result = run(args=("go",), KCGX_AIRPORT_CMD=str(airport_stub),
                 KCGX_TEST_RECORD="KSEA\t47.4\t-122.3\tSeattle")
    assert result.returncode != 0
    assert "not running" in result.stderr.lower()


def test_a_broken_resolver_still_opens_the_cockpit(cockpit, airport_stub):
    """A Python-side failure must not cost you the traffic display."""
    run, tmux, session = cockpit
    result = run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="unused",
        KCGX_TEST_FAIL="2",
    )
    assert result.returncode == 0
    adsb = pane_command(tmux, session, 0)
    assert "--site-lat" not in adsb, "no coordinates means fall back to its config"
    assert "sleep 300" in adsb
