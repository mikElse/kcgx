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
import time
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
#
# The three carry different markers on purpose. They used to be the identical
# string, which meant a pane running the wrong role's command was invisible
# unless that command also happened to carry a distinguishing flag -- and the
# status pane's never does, so "the status pane was not retargeted" could not
# be told apart from "the status pane was handed the status command again".
FAKE_ADSB = "sh -c 'sleep 300' kcgx-fake-adsb"
FAKE_SQUELCH = "sh -c 'sleep 300' kcgx-fake-squelch"
FAKE_STATUS = "sh -c 'sleep 300' kcgx-fake-status"

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


@pytest.fixture(scope="session")
def socket_dir():
    """Where tmux keeps its sockets, asked of tmux rather than guessed.

    Needed because the per-test teardown cannot ask: `display -p` requires
    a running server, and the `kcgx stop` tests deliberately end with none
    -- killing the last session ends the server, which still leaves its
    socket file behind. One throwaway server at the start of the run
    answers the question once for every test.
    """
    name = f"kcgx-test-probe-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["tmux", "-L", name, "new-session", "-d", "-s", "probe", "sleep 30"],
        capture_output=True,
        timeout=30,
    )
    path = subprocess.run(
        ["tmux", "-L", name, "display", "-p", "#{socket_path}"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    subprocess.run(["tmux", "-L", name, "kill-server"], capture_output=True, timeout=30)
    assert path, "tmux would not say where its sockets live"
    Path(path).unlink(missing_ok=True)
    return Path(path).parent


@pytest.fixture
def cockpit(tmp_path, socket_dir):
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
            "KCGX_STATUS_CMD": FAKE_STATUS,
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

    # A server that stops -- killed here, or by `kcgx stop` taking its last
    # session -- leaves its socket file behind, and every test uses a fresh
    # uuid, so the suite was depositing one dead socket per test in
    # /tmp/tmux-$UID, unbounded, forever. Unlink unconditionally: whether a
    # server is still up at this point varies by test, but the file is only
    # ever ours.
    subprocess.run(
        ["tmux", "-L", socket, "kill-server"], capture_output=True, timeout=30
    )
    (socket_dir / socket).unlink(missing_ok=True)


def panes(tmux, session, fmt):
    result = tmux("list-panes", "-t", f"={session}:cockpit", "-F", fmt)
    assert result.returncode == 0, result.stderr
    # splitlines() alone, not strip().splitlines(): when the *first* field of
    # the format is empty -- an untagged pane under "#{@kcgx_role}\t..." --
    # strip() eats that line's leading tab, so the second field slides into
    # the first and an absent role reads back as a role named "%0". That made
    # a correctly stripped session look like a tagged one.
    return result.stdout.splitlines()


def role_field(tmux, session, field):
    """Map @kcgx_role -> field value.

    Keyed on role, not on pane index: inserting the status pane moved
    squelch from index 1 to index 2 while its pane id stayed put, so an
    assertion keyed on 1 would silently describe a different pane. The
    index-keyed version this replaced is gone; nothing called it.
    """
    out = {}
    for line in panes(tmux, session, "#{@kcgx_role}\t#{" + field + "}"):
        role, _, value = line.partition("\t")
        if role.strip():
            out[role.strip()] = value.strip()
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
    widths = {r: int(v) for r, v in role_field(tmux, session, "pane_width").items()}
    assert widths["squelch"] == 48, f"squelch pane is {widths['squelch']} columns"
    assert widths["status"] == 48, f"status pane is {widths['status']} columns"
    assert widths["adsb"] > 48, "adsb-tui should get the remaining width"


def test_status_pane_is_short_so_squelch_keeps_the_column(cockpit):
    """The status pane shares squelch's column, so it must stay out of the way.

    Was the shell pane at 12 rows; the status line needs four and everything
    left over belongs to squelch's feed list and transcript.
    """
    run, tmux, session = cockpit
    run()
    heights = {r: int(v) for r, v in role_field(tmux, session, "pane_height").items()}
    assert heights["squelch"] > 4 * heights["status"], (
        f"status took {heights['status']} rows and left squelch "
        f"{heights['squelch']}; squelch should keep the column"
    )


def test_commands_land_in_the_right_panes(cockpit):
    run, tmux, session = cockpit
    run()
    commands = role_field(tmux, session, "pane_start_command")
    # tmux reports the start command quoted.
    assert FAKE_ADSB in commands["adsb"]
    assert FAKE_SQUELCH in commands["squelch"]
    assert FAKE_STATUS in commands["status"]


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
        "KCGX_STATUS_CMD": FAKE_STATUS,
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
    widths = {r: int(v) for r, v in role_field(tmux, session, "pane_width").items()}
    assert widths["adsb"] + widths["squelch"] + 1 == 222, (
        f"session not sized to the pty: {widths}"
    )
    assert widths["squelch"] == 48


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


def pane_command(tmux, session, role):
    """The start command of the pane tagged `role`.

    Keyed by role rather than by index, for the same reason bin/kcgx is:
    `cockpit.1` used to mean squelch and now means status, so an index-keyed
    assertion would go on passing while describing the wrong pane.
    """
    return role_field(tmux, session, "pane_start_command")[role]


def test_launch_points_both_panes_at_the_resolved_airport(
    cockpit, airport_stub
):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KORD\t41.9786\t-87.9048\tChicago O'Hare",
    )
    adsb = pane_command(tmux, session, "adsb")
    squelch = pane_command(tmux, session, "squelch")
    assert "--site-lat 41.9786" in adsb
    assert "--site-lon -87.9048" in adsb
    assert "--icao KORD" in squelch


def test_go_moves_both_panes_to_the_new_airport(cockpit, airport_stub):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    assert "--site-lat 45.5887" in pane_command(tmux, session, "adsb")

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    assert result.returncode == 0, result.stderr

    adsb = pane_command(tmux, session, "adsb")
    squelch = pane_command(tmux, session, "squelch")
    assert "--site-lat 47.4479" in adsb and "--site-lon -122.3102" in adsb
    assert "--icao KSEA" in squelch
    assert "45.5887" not in adsb, "the old airport is still on screen"


def test_launch_and_go_build_the_same_command(cockpit, airport_stub):
    """The two paths must not drift; that is how three earlier bugs happened."""
    run, tmux, session = cockpit
    record = "KSEA\t47.4479\t-122.3102\tSeattle-Tacoma"
    run(KCGX_AIRPORT_CMD=str(airport_stub), KCGX_TEST_RECORD=record)
    at_launch = (pane_command(tmux, session, "adsb"), pane_command(tmux, session, "squelch"))

    run(args=("go",), KCGX_AIRPORT_CMD=str(airport_stub), KCGX_TEST_RECORD=record)
    after_go = (pane_command(tmux, session, "adsb"), pane_command(tmux, session, "squelch"))

    assert at_launch == after_go


def test_a_cancelled_pick_leaves_the_cockpit_alone(cockpit, airport_stub):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    before = pane_command(tmux, session, "adsb")

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="unused",
        KCGX_TEST_FAIL="1",
    )
    assert result.returncode == 0, "cancelling is not an error"
    assert pane_command(tmux, session, "adsb") == before


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
    before = pane_command(tmux, session, "adsb")

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="unused",
        KCGX_TEST_FAIL="2",
    )
    assert result.returncode != 0
    assert result.stderr.strip(), "a silent failure reads exactly like a cancel"
    assert pane_command(tmux, session, "adsb") == before, "and still change nothing"


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
    before = pane_command(tmux, session, "adsb")

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5",  # no lon, no label
    )
    assert result.returncode != 0, "a short record is not a cancelled pick"
    assert result.stderr.strip(), "and it must say so"
    assert pane_command(tmux, session, "adsb") == before


def test_a_failed_mktemp_is_an_error_not_a_cancel(cockpit, airport_stub, tmp_path):
    """`go` needs a temp file to receive the record. Not getting one is a
    failure — but `mktemp` exits 1, and 1 is the code reserved for "the user
    pressed escape". Passing it straight through would make an unwritable
    temp directory look exactly like a cancelled search: silent, and
    successful.

    TMPDIR is not the lever: BSD mktemp with no template ignores it. So put a
    failing mktemp on PATH, the way the missing-tmux test stubs PATH.
    """
    run, tmux, session = cockpit
    assert run().returncode == 0
    before = pane_command(tmux, session, "adsb")

    stub_bin = tmp_path / "mktemp-fails"
    stub_bin.mkdir()
    for tool in ("bash", "env", "tmux", "grep", "awk", "head", "dirname"):
        found = shutil.which(tool)
        if found:
            (stub_bin / tool).symlink_to(found)
    failing = stub_bin / "mktemp"
    failing.write_text("#!/bin/sh\nexit 1\n")
    failing.chmod(0o755)

    result = run(
        args=("go",),
        PATH=str(stub_bin),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    assert result.returncode != 0, "a temp file it could not create is not a cancel"
    # Name the message, not just "something on stderr". The loop above skips
    # any tool shutil.which cannot find, so on a machine missing one of them
    # bin/kcgx would die earlier -- "tmux not found" is also non-zero with
    # non-empty stderr, and would satisfy a vaguer assertion for the wrong
    # reason. Exit 2 is the code this test exists to pin down.
    assert "airport search failed (exit 2)" in result.stderr, result.stderr
    assert pane_command(tmux, session, "adsb") == before


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


def test_the_default_resolver_really_works(cockpit, tmp_path):
    """Every other test stubs the resolver, so all of them would still pass
    if `uv run ... kcgx-airport resolve` were broken — the launcher would
    quietly fall back to unconfigured panes. Run the real one once and
    require that it produced the right coordinates.

    The state file is one this test wrote, not the developer's: reading the
    real one would make this test red whenever it happened to hold an ICAO
    the dataset does not have — a failure that says nothing about the
    resolver. A known ICAO also lets this assert exact coordinates instead
    of merely "some".
    """
    run, tmux, session = cockpit
    state = tmp_path / "resolver-state" / "airport"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("KORD\n")

    assert run(KCGX_AIRPORT_CMD="", KCGX_STATE_PATH=str(state)).returncode == 0

    adsb = pane_command(tmux, session, "adsb")
    squelch = pane_command(tmux, session, "squelch")
    assert "--site-lat 41.9786" in adsb, (
        "the real resolver produced no coordinates: " + adsb
    )
    assert "--site-lon -87.9048" in adsb, adsb
    assert "--icao KORD" in squelch, squelch


def test_an_unknown_remembered_icao_falls_back_instead_of_failing(cockpit, tmp_path):
    """The spec: "An ICAO in the state file that is no longer in the dataset
    falls back to the next source and warns, rather than failing to launch."

    It did fail: `resolve` exited 2, and the launcher's degrade path built
    the cockpit with no --site-lat/--site-lon and no --icao — on every
    launch after, until the user happened to run `kcgx go`. Reachable from
    a hand-edited state file, or from OurAirports reclassifying a field out
    of the committed subset on the next regeneration.

    Runs the real resolver, because a stub cannot get this wrong.
    """
    run, tmux, session = cockpit
    state = tmp_path / "gone" / "airport"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("ZZZZ\n")

    result = run(KCGX_AIRPORT_CMD="", KCGX_STATE_PATH=str(state))
    assert result.returncode == 0, result.stderr

    adsb = pane_command(tmux, session, "adsb")
    squelch = pane_command(tmux, session, "squelch")
    assert "--site-lat 45.588699" in adsb, (
        "an unknown remembered airport cost the cockpit its coordinates: " + adsb
    )
    assert "--icao KPDX" in squelch, squelch
    assert "ZZZZ" in result.stderr, (
        "fell back in silence, which is the degradation this replaces: "
        + repr(result.stderr)
    )


def test_a_real_pick_moves_the_cockpit_and_is_remembered(cockpit, tmp_path):
    """The one test that runs the whole chain: bin/kcgx -> uv -> the real
    kcgx-airport pick -> a record -> tmux panes -> the state file.

    Everything else asserts the record format on one side only. bin/kcgx has
    its own idea of the format and src/kcgx/ has its own, and until this test
    existed nothing ever compared them. KORD's coordinates below are the
    dataset's, so a change to either side's spelling of the record shows up
    here as a wrong pane command rather than as two suites that still agree
    with themselves.

    KCGX_STATE_PATH keeps the real `pick`'s write inside tmp_path; `pick KORD`
    is an exact code, so it short-circuits the picker and never opens Textual.
    """
    run, tmux, session = cockpit
    state = tmp_path / "state" / "airport"
    assert run(KCGX_STATE_PATH=str(state)).returncode == 0

    result = run(
        args=("go", "KORD"),
        KCGX_AIRPORT_CMD="",  # empty -> fall through to the real resolver
        KCGX_STATE_PATH=str(state),
    )
    assert result.returncode == 0, result.stderr

    adsb = pane_command(tmux, session, "adsb")
    squelch = pane_command(tmux, session, "squelch")
    assert "--site-lat 41.9786" in adsb, adsb
    assert "--site-lon -87.9048" in adsb, adsb
    assert "--icao KORD" in squelch, squelch
    # The label is free text and shares the record with the coordinates. If a
    # separator ever goes wrong it arrives here, welded to a --site-lon value.
    assert "Chicago" not in adsb and "O'Hare" not in adsb, adsb

    assert state.read_text().strip() == "KORD", "the pick was not remembered"


STDERR_SENTINEL = "PICKER-DREW-THIS"

# Stands in for the picker's *rendering*, not its record: it writes a marker
# to stderr the way Textual writes its frames there, and delivers the record
# through --out the way the real thing does.
DRAWING_STUB = f"""#!/bin/sh
printf '{STDERR_SENTINEL}\\n' >&2
out=""
while [ $# -gt 0 ]; do
    case "$1" in
        --out) out="$2"; shift 2 ;;
        *) shift ;;
    esac
done
printf 'KSEA\t47.4479\t-122.3102\tSeattle-Tacoma\\n' > "$out"
"""


# The popup the prefix+a binding opens: `display-popup -w 64 -h 20`.
POPUP_COLS, POPUP_ROWS = 64, 20

# Every "move the cursor to row N" the app emitted. A frame laid out for a
# terminal taller than the one it was given addresses rows that do not exist.
_CURSOR_ROW = re.compile(r"\x1b\[(\d+);\d+H")


def rows_addressed(seen):
    return {int(match.group(1)) for match in _CURSOR_ROW.finditer(seen)}


def drive_on_a_pty(launcher, args, env, *, rows, cols, until=None, timeout=45):
    """Run `launcher` with a real terminal on all three standard fds, and
    return (exit code, everything the terminal saw).

    A pipe would not do, and neither would redirecting one stream. On a
    terminal stdout and stderr are one device, and the picker needs both:
    Textual's driver writes its frames to sys.__stderr__ and *measures* the
    terminal with shutil.get_terminal_size(), which reads sys.__stdout__.
    Only a real tty puts both in play at once, which is the situation the
    popup has to survive.

    `until` waits for that text to appear and then sends escape, so an
    interactive picker gets dismissed instead of hanging until `timeout`.
    """
    import fcntl
    import select
    import signal
    import struct
    import termios
    import time

    controller, follower = os.openpty()
    fcntl.ioctl(follower, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    pid = os.fork()
    if pid == 0:  # pragma: no cover - child process
        os.setsid()
        fcntl.ioctl(follower, termios.TIOCSCTTY, 0)
        for target in (0, 1, 2):
            os.dup2(follower, target)
        os.close(controller)
        os.close(follower)
        os.execve(str(launcher), [str(launcher), *args], env)
    os.close(follower)

    output = b""
    deadline = time.monotonic() + timeout
    dismissed = until is None
    while time.monotonic() < deadline:
        ready, _, _ = select.select([controller], [], [], 0.25)
        if ready:
            try:
                chunk = os.read(controller, 65536)
            except OSError:  # EIO: the child let go of the pty
                break
            if not chunk:
                break
            output += chunk
        if not dismissed and until.encode() in output:
            os.write(controller, b"\x1b")
            dismissed = True

    status = None
    for _ in range(60):
        reaped, reaped_status = os.waitpid(pid, os.WNOHANG)
        if reaped:
            status = reaped_status
            break
        time.sleep(0.05)
    if status is None:  # pragma: no cover - only on a hang
        os.kill(pid, signal.SIGKILL)
        _, status = os.waitpid(pid, 0)
    os.close(controller)
    return os.waitstatus_to_exitcode(status), output.decode(errors="replace")


def test_the_picker_can_draw_on_the_terminal(cockpit, tmp_path):
    """Regression: `go` ran the airport command as `>/dev/null 2>&1`, on the
    documented belief that Textual draws on stdout. It draws on *stderr*
    (textual/drivers/linux_driver.py: `self._file = sys.__stderr__`), so
    `2>&1` sent the entire popup to /dev/null and the picker opened blank.
    stdin was never redirected, so blind keypresses still worked: pressing
    enter on the invisible list selected the first airport alphabetically
    and retargeted the cockpit to Honiara, Solomon Islands.

    Nothing in the suite pinned that redirection in either direction, which
    is how nine task reviews walked past it. stdout stays redirected on
    purpose -- that is what keeps a record printed to stdout out of the
    popup -- so this asserts only that stderr reaches the terminal.
    """
    run, tmux, session = cockpit
    assert run().returncode == 0

    stub = tmp_path / "kcgx-airport-drawing"
    stub.write_text(DRAWING_STUB)
    stub.chmod(0o755)

    env = {
        **os.environ,
        "KCGX_SOCKET": run.socket,
        "KCGX_SESSION": session,
        "KCGX_DETACHED": "1",
        "KCGX_ADSB_CMD": FAKE_ADSB,
        "KCGX_SQUELCH_CMD": FAKE_SQUELCH,
        "KCGX_STATUS_CMD": FAKE_STATUS,
        "KCGX_AIRPORT_CMD": str(stub),
        "TERM": "xterm-256color",
    }
    env.pop("KCGX_SIZE", None)
    env.pop("TMUX", None)

    code, seen = drive_on_a_pty(
        LAUNCHER, ("go",), env, rows=POPUP_ROWS, cols=POPUP_COLS
    )
    assert code == 0, seen
    assert STDERR_SENTINEL in seen, (
        "the picker's rendering never reached the terminal, so the popup is "
        "blank and any keypress is blind: " + repr(seen)
    )
    # And the record still arrived, i.e. the retarget was not paid for by
    # letting the record leak into the popup.
    assert "--icao KSEA" in pane_command(tmux, session, "squelch")


def test_the_real_picker_fills_the_popup_it_was_given(cockpit, tmp_path):
    """The end-to-end assertion, and the one that would have caught both
    halves of the blank-popup bug: run the *real* picker through
    `bin/kcgx go` on a pty the size of the popup, and require it to draw
    airport rows that fit.

    The stub-and-sentinel test above pins stderr, and that was only half of
    it. Textual writes its frames to sys.__stderr__ but measures the
    terminal with shutil.get_terminal_size(), which reads sys.__stdout__ --
    so `>/dev/null` on stdout left the driver drawing to the right place at
    the wrong size. It fell back to 80x24, painted a frame taller and wider
    than the popup, the terminal scrolled, and what stayed on screen was the
    blank bottom of an over-tall frame. Selection still worked blind, which
    is what made it dangerous: the cockpit moved somewhere the user could
    not see.

    So "KSEA appears" is not enough on its own -- the rows were emitted in
    the broken case too, just laid out for a terminal nobody had. The
    geometry is what discriminates.
    """
    run, tmux, session = cockpit
    assert run().returncode == 0

    state = tmp_path / "picker-state" / "airport"
    env = {
        **os.environ,
        "KCGX_SOCKET": run.socket,
        "KCGX_SESSION": session,
        "KCGX_ADSB_CMD": FAKE_ADSB,
        "KCGX_SQUELCH_CMD": FAKE_SQUELCH,
        "KCGX_STATUS_CMD": FAKE_STATUS,
        "KCGX_AIRPORT_CMD": "",  # empty -> the real kcgx-airport
        "KCGX_STATE_PATH": str(state),
        "TERM": "xterm-256color",
    }
    for leftover in ("KCGX_SIZE", "KCGX_DETACHED", "TMUX", "COLUMNS", "LINES"):
        env.pop(leftover, None)
    # COLUMNS/LINES go too: shutil.get_terminal_size() consults them before it
    # measures stdout, so inheriting them from the developer's shell would let
    # the picker size itself correctly for the wrong reason.

    code, seen = drive_on_a_pty(
        LAUNCHER, ("go", "seattle"), env,
        rows=POPUP_ROWS, cols=POPUP_COLS, until="KSEA",
    )

    assert "KSEA" in seen, (
        "the picker drew no airport rows at all, so the popup is blank and "
        "any keypress is blind: " + repr(seen[-2000:])
    )
    overflowing_rows = sorted(row for row in rows_addressed(seen) if row > POPUP_ROWS)
    assert overflowing_rows == [], (
        f"the picker laid itself out for a terminal taller than the "
        f"{POPUP_ROWS}-row popup and addressed rows {overflowing_rows}; the "
        "excess scrolls the airport rows off screen and leaves it looking blank"
    )
    assert code == 0, f"escape should cancel cleanly, got {code}: {seen[-2000:]}"
    assert not state.exists(), "a cancelled pick must not be remembered"


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
    adsb = pane_command(tmux, session, "adsb")
    assert "--site-lat" not in adsb, "no coordinates means fall back to its config"
    assert "sleep 300" in adsb


# -- the status pane -------------------------------------------------------


def roles(tmux, session):
    """Map role -> pane id, the same lookup bin/kcgx does."""
    out = {}
    for line in panes(tmux, session, "#{@kcgx_role}\t#{pane_id}"):
        role, _, pane_id = line.partition("\t")
        if role.strip():
            out[role.strip()] = pane_id.strip()
    return out


def test_the_cockpit_has_three_panes_and_no_shell(cockpit):
    run, tmux, session = cockpit
    run(KCGX_STATUS_CMD=FAKE_STATUS)
    commands = panes(tmux, session, "#{pane_start_command}")
    assert len(commands) == 3
    assert not any(c.strip() == "" for c in commands), (
        "an empty pane command is the shell pane that should be gone"
    )


def test_every_pane_carries_its_role(cockpit):
    run, tmux, session = cockpit
    run(KCGX_STATUS_CMD=FAKE_STATUS)
    assert set(roles(tmux, session)) == {"adsb", "status", "squelch"}


def test_the_status_pane_sits_above_squelch_and_is_four_rows(cockpit):
    run, tmux, session = cockpit
    run(KCGX_STATUS_CMD=FAKE_STATUS)
    by_id = {}
    for line in panes(tmux, session, "#{pane_id}\t#{pane_top}\t#{pane_height}"):
        pane_id, top, height = line.split("\t")
        by_id[pane_id] = (int(top), int(height))
    r = roles(tmux, session)
    assert by_id[r["status"]][1] == 4, "status pane should be four rows"
    assert by_id[r["status"]][0] < by_id[r["squelch"]][0], "status sits above"


def test_retarget_still_finds_both_panes_after_the_layout_change(cockpit, airport_stub):
    """The whole point of the role tags."""
    run, tmux, session = cockpit
    run(
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    # The status pane's pid, before. Its *command* cannot show a redundant
    # respawn -- respawning it with status_cmd() reproduces the same string --
    # so the process identity is what discriminates "left alone" from "killed
    # and rebuilt with the same thing", and only the first of those is
    # flicker-free, which is the reason the status pane is skipped at all.
    status_pid_before = role_field(tmux, session, "pane_pid")["status"]

    result = run(
        args=("go",),
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    assert result.returncode == 0, result.stderr

    by_id = {}
    for line in panes(tmux, session, "#{pane_id}\t#{pane_start_command}"):
        pane_id, _, cmd = line.partition("\t")
        by_id[pane_id] = cmd
    r = roles(tmux, session)
    assert "--site-lat 47.4479" in by_id[r["adsb"]]
    assert "--icao KSEA" in by_id[r["squelch"]]
    assert "--icao" not in by_id[r["status"]], "the status pane is not retargeted"
    # Named markers, so a pane handed another role's command is caught even
    # when that command carries no flag to give it away.
    assert "kcgx-fake-status" in by_id[r["status"]], by_id[r["status"]]
    assert "kcgx-fake-squelch" not in by_id[r["status"]], by_id[r["status"]]
    assert role_field(tmux, session, "pane_pid")["status"] == status_pid_before, (
        "the status pane was respawned; it re-reads the airport on its own "
        "tick and respawning it only costs a flicker"
    )


def test_go_leaves_squelch_selected(cockpit, airport_stub):
    """After a switch, the keys must drive squelch's feed list.

    The active pane has to be moved off squelch first, or this test proves
    nothing: the launch already lands on squelch, so `go` can omit its
    select-pane entirely and the assertion still passes. Selecting the
    status pane is what a *click* on it does, and clicking it is the
    documented way to open the search -- so this is the real path, not a
    contrivance to make the test bite.
    """
    run, tmux, session = cockpit
    run(
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    tmux("select-pane", "-t", roles(tmux, session)["status"])
    assert (
        tmux(
            "display-message", "-p", "-t", f"={session}:cockpit", "#{pane_id}"
        ).stdout.strip()
        == roles(tmux, session)["status"]
    ), "the click did not take, so the rest of this test would prove nothing"

    run(
        args=("go",),
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    active = tmux(
        "display-message", "-p", "-t", f"={session}:cockpit", "#{pane_id}"
    ).stdout.strip()
    assert active == roles(tmux, session)["squelch"]


def test_launch_leaves_squelch_selected(cockpit):
    run, tmux, session = cockpit
    run(KCGX_STATUS_CMD=FAKE_STATUS)
    active = tmux(
        "display-message", "-p", "-t", f"={session}:cockpit", "#{pane_id}"
    ).stdout.strip()
    assert active == roles(tmux, session)["squelch"]


def test_go_refuses_a_cockpit_whose_panes_carry_no_roles(cockpit, airport_stub):
    """A cockpit built before the role tags existed must fail loudly.

    tmux does not treat an empty target as an error: `respawn-pane -t ""`
    resolves to the *active* pane and exits 0. So when `pane_for_role` found
    nothing, `kcgx go` rebuilt whichever pane the user last clicked -- twice,
    once per respawn, the second overwriting the first -- while both real
    panes kept the old airport, and still printed the new one and exited 0.
    Reproduced end to end against a session built by the previous bin/kcgx:
    the radar and the audio both stayed in Portland, a third pane quietly
    became a second squelch on Seattle, and the launcher reported success.

    Every other test builds its session with the current launcher, so every
    pane always carries a role and this branch is unreachable from the suite
    by construction. Stripping the tags is what makes it reachable -- and an
    upgrade over a running cockpit is not hypothetical, it is what happens to
    anyone who has one open when they pull.
    """
    run, tmux, session = cockpit
    run(
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    before = dict(
        line.partition("\t")[::2]
        for line in panes(tmux, session, "#{pane_id}\t#{pane_start_command}")
    )
    assert len(before) == 3

    for pane_id in before:
        assert tmux("set", "-pu", "-t", pane_id, "@kcgx_role").returncode == 0
    assert roles(tmux, session) == {}, "the tags were not actually stripped"

    result = run(
        args=("go",),
        KCGX_STATUS_CMD=FAKE_STATUS,
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    assert result.returncode != 0, (
        "reported success against a cockpit it could not address: "
        + repr(result.stdout)
    )
    assert "kcgx stop" in result.stderr, (
        "the message must say how to fix it, not just that something failed: "
        + repr(result.stderr)
    )
    assert "KSEA" not in result.stdout, "it must not claim the move happened"

    after = dict(
        line.partition("\t")[::2]
        for line in panes(tmux, session, "#{pane_id}\t#{pane_start_command}")
    )
    assert after == before, (
        "a pane was respawned anyway; an empty tmux target is the active pane, "
        "not nothing"
    )


# -- the radar pane id -----------------------------------------------------


def _await_file(path, timeout=10.0):
    """Wait for a pane's command to write its recording.

    The pane is spawned asynchronously, so the launcher returning does not
    mean the command inside it has run yet.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    return path.read_text().strip() if path.exists() else None


def _env_recorder(tmp_path, name, variable):
    """A pane command that records one environment variable and then idles."""
    out = tmp_path / f"{name}.value"
    script = tmp_path / name
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s" "${variable}" > "{out}"\n'
        "sleep 300\n"
    )
    script.chmod(0o755)
    return script, out


def test_the_squelch_pane_knows_the_radar_pane_id(cockpit, tmp_path):
    """squelch samples the radar pane's colours, so it needs its id.

    Asserted on the variable as the pane's own process sees it, not on the
    launcher's copy: `split-window -e` is what has to carry it across, and
    a value that never reaches the child is exactly the failure that would
    leave squelch silently unthemed.
    """
    run, tmux, session = cockpit
    script, out = _env_recorder(tmp_path, "record-radar", "KCGX_RADAR_PANE")
    run(KCGX_SQUELCH_CMD=str(script))
    value = _await_file(out)
    assert value, "KCGX_RADAR_PANE must be exported into the squelch pane"
    assert value.startswith("%"), "tmux pane ids look like %0, %1, ..."


def test_the_radar_pane_id_matches_the_adsb_pane(cockpit, tmp_path):
    run, tmux, session = cockpit
    script, out = _env_recorder(tmp_path, "record-radar", "KCGX_RADAR_PANE")
    run(KCGX_SQUELCH_CMD=str(script))
    exported = _await_file(out)
    assert exported == role_field(tmux, session, "pane_id")["adsb"]


def test_the_radar_pane_id_survives_a_retarget(cockpit, tmp_path, airport_stub):
    """`kcgx go` respawns the squelch pane, and must re-export the id.

    This is the silent kind of failure: the audio pane simply stops
    following the radar's theme afterwards, and nothing else changes.
    """
    run, tmux, session = cockpit
    script, out = _env_recorder(tmp_path, "record-radar", "KCGX_RADAR_PANE")
    run(KCGX_SQUELCH_CMD=str(script))
    first = _await_file(out)
    assert first, "the launch path must export it before this proves anything"

    out.unlink()
    run(
        args=("go",),
        KCGX_SQUELCH_CMD=str(script),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KORD\t41.9786\t-87.9048\tChicago O'Hare",
    )
    assert _await_file(out) == first
