"""The `kcgx` command (kcgx.launcher), against real servers.

Every server here is `--demo`: no network, no ffmpeg, no audio. Each test
gets its own free port and its own state folder (the conftest backstop puts
KCGX_STATE_PATH in tmp_path), and every server a test starts is stopped
when it ends, whatever happened.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kcgx import launcher
from kcgx.state import read_airport, write_airport


@pytest.fixture
def port(monkeypatch):
    port = launcher.free_port()
    monkeypatch.setenv("KCGX_PORT", str(port))
    return port


@pytest.fixture
def kcgx(port):
    """Run the command in process; every URL it would open is collected."""
    opened = []

    def run(*argv):
        return launcher.main(list(argv), opener=opened.append)

    run.opened = opened
    yield run
    info = launcher.read_info()
    if info:
        launcher.stop(info, timeout=5)


def demo_server(port):
    """A kcgx server started by hand, as if a launcher's record were lost."""
    process = subprocess.Popen(
        [sys.executable, "-m", "kcgx.server", "--demo", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(200):
        if launcher.health(port):
            return process
        time.sleep(0.05)
    process.kill()
    pytest.fail("the demo server never answered")


# -- starting ------------------------------------------------------------------


def test_kcgx_starts_the_server_records_it_and_opens_the_page(kcgx, port, capsys):
    assert kcgx("--demo") == 0
    assert kcgx.opened == [f"http://127.0.0.1:{port}/"]
    info = json.loads(launcher.info_path().read_text())
    assert info["port"] == port and info["pid"] and info["demo"] is True
    assert launcher.health(port)["app"] == "kcgx"
    assert "started at" in capsys.readouterr().out
    assert launcher.log_path().exists()


def test_a_second_kcgx_reuses_the_running_server(kcgx, port, capsys):
    kcgx("--demo", "--no-open")
    first = launcher.read_info()["pid"]
    capsys.readouterr()
    assert kcgx("--demo") == 0
    assert launcher.read_info()["pid"] == first
    assert "running at" in capsys.readouterr().out
    assert kcgx.opened == [f"http://127.0.0.1:{port}/"]


def test_no_open_opens_nothing(kcgx):
    assert kcgx("--demo", "--no-open") == 0
    assert kcgx.opened == []


def test_a_stale_record_is_replaced(kcgx, port):
    launcher.info_path().parent.mkdir(parents=True, exist_ok=True)
    launcher.info_path().write_text(json.dumps({"port": launcher.free_port(), "pid": 999999}))
    assert launcher.running() is None
    assert not launcher.info_path().exists()
    assert kcgx("--demo", "--no-open") == 0
    assert launcher.read_info()["port"] == port


def test_an_unrecorded_kcgx_server_on_the_port_is_adopted(kcgx, port):
    process = demo_server(port)
    try:
        assert kcgx("--no-open") == 0
        assert launcher.read_info() == {"port": port, "pid": None, "demo": False}
    finally:
        process.kill()
        process.wait()


def test_a_port_held_by_something_else_is_skipped_for_a_free_one(kcgx, port):
    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", port))
        squatter.listen()
        assert kcgx("--demo", "--no-open") == 0
        moved = launcher.read_info()["port"]
    assert moved != port and launcher.health(moved)


def test_something_else_answering_health_on_the_port_is_not_taken_for_kcgx(kcgx, port):
    """Another local app may well answer /api/health with {"ok": true}. Only
    a reply that says it is kcgx counts; anything else is skipped like any
    other occupant of the port."""
    import http.server
    import threading

    class Impostor(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"ok": true, "version": "9.9"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    impostor = http.server.HTTPServer(("127.0.0.1", port), Impostor)
    threading.Thread(target=impostor.serve_forever, daemon=True).start()
    try:
        assert launcher.health(port) is None
        assert kcgx("--demo", "--no-open") == 0
        assert launcher.read_info()["port"] != port
    finally:
        impostor.shutdown()
        impostor.server_close()


def test_a_server_that_cannot_start_says_why(kcgx, capsys):
    """A config file kcgx-web refuses: the server exits at once, and the
    command shows the reason from its log rather than waiting it out."""
    config = Path(os.environ["HOME"]) / ".config" / "squelch" / "squelch.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('max_streams = "seven"\n')
    started = time.monotonic()
    assert kcgx("--demo", "--no-open") == 1
    assert time.monotonic() - started < launcher.START_TIMEOUT_SECS / 2
    err = capsys.readouterr().err
    assert "could not start the server" in err and "max_streams" in err
    assert launcher.read_info() is None


# -- stopping and status ---------------------------------------------------------


def test_stop_stops_it_and_forgets_it(kcgx, port, capsys):
    kcgx("--demo", "--no-open")
    capsys.readouterr()
    assert kcgx("stop") == 0
    assert "stopped." in capsys.readouterr().out
    assert launcher.health(port) is None
    assert not launcher.info_path().exists()


def test_stop_when_not_running_is_not_an_error(kcgx, capsys):
    assert kcgx("stop") == 0
    assert "not running." in capsys.readouterr().out


def test_status_says_where_and_which_airport(kcgx, port, capsys):
    assert kcgx("status") == 3
    assert "not running." in capsys.readouterr().out
    write_airport("KSEA")
    kcgx("--demo", "--no-open")
    capsys.readouterr()
    assert kcgx("status") == 0
    assert capsys.readouterr().out.strip() == f"kcgx: running at http://127.0.0.1:{port}/  (KSEA, demo)"


# -- choosing an airport -----------------------------------------------------------


def wait_for_icao(port, icao):
    for _ in range(100):
        if (launcher.health(port) or {}).get("icao") == icao:
            return True
        time.sleep(0.05)
    return False


def test_go_with_an_icao_switches_the_running_cockpit(kcgx, port):
    kcgx("--demo", "--no-open")
    assert kcgx("go", "ksea") == 0
    assert wait_for_icao(port, "KSEA")
    assert kcgx.opened == []


def test_go_with_a_query_naming_one_airport_switches_to_it(kcgx, port, capsys):
    kcgx("--demo", "--no-open")
    capsys.readouterr()
    assert kcgx("go", "seattle", "tacoma") == 0
    assert "KSEA" in capsys.readouterr().out
    assert wait_for_icao(port, "KSEA")


def test_go_when_not_running_starts_at_that_airport(kcgx, port):
    assert kcgx("go", "KSEA") == 0
    assert launcher.health(port)["icao"] == "KSEA"
    assert read_airport() == "KSEA"


def test_go_with_no_airport_opens_the_pages_search(kcgx, port):
    kcgx("--demo", "--no-open")
    assert kcgx("go") == 0
    assert kcgx.opened == [f"http://127.0.0.1:{port}/#airport"]


def test_go_with_a_query_naming_several_opens_the_search_with_it_typed(kcgx, port):
    kcgx("--demo", "--no-open")
    assert kcgx("go", "san", "francisco") == 0
    assert kcgx.opened == [f"http://127.0.0.1:{port}/#airport=san%20francisco"]


def test_go_with_no_match_says_so_and_changes_nothing(kcgx, capsys):
    assert kcgx("go", "qqqqqq") == 1
    assert "no airport matches 'qqqqqq'" in capsys.readouterr().err
    assert launcher.read_info() is None


def test_go_open_opens_the_page_after_switching(kcgx, port):
    kcgx("--demo", "--no-open")
    assert kcgx("go", "--open", "KSEA") == 0
    assert kcgx.opened == [f"http://127.0.0.1:{port}/"]


# -- the server outlives the command --------------------------------------------------


def test_the_server_keeps_running_after_the_command_exits(port, tmp_path):
    """The real command line, in its own process: when it returns, the
    server it started is still answering."""
    env = {**os.environ, "KCGX_PORT": str(port)}
    done = subprocess.run(
        [sys.executable, "-m", "kcgx.launcher", "--demo", "--no-open"],
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr
    try:
        assert launcher.health(port)
    finally:
        info = launcher.read_info()
        if info:
            launcher.stop(info, timeout=5)


# -- bin/kcgx ------------------------------------------------------------------------

WRAPPER = Path(__file__).resolve().parent.parent / "bin" / "kcgx"


def test_the_wrapper_finds_this_repo_through_a_symlink(tmp_path):
    """setup.sh installs bin/kcgx as a symlink on PATH: the link must lead
    back to this repo, not to the folder the link sits in. A uv that records
    its arguments says exactly which project the wrapper named."""
    link = tmp_path / "bin" / "kcgx"
    link.parent.mkdir()
    link.symlink_to(WRAPPER)
    fake = tmp_path / "fake"
    fake.mkdir()
    record = tmp_path / "uv-args"
    (fake / "uv").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\n')
    (fake / "uv").chmod(0o755)
    done = subprocess.run([str(link), "go", "KSEA"], capture_output=True, text=True, timeout=30, check=False,
                          env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
    assert done.returncode == 0, done.stderr
    assert record.read_text().split("\n")[:6] == ["run", "--quiet", "--project", str(WRAPPER.parent.parent), "kcgx", "go"]


def test_the_wrapper_runs_the_real_launcher(port):
    done = subprocess.run([str(WRAPPER), "status"], capture_output=True, text=True, timeout=120, check=False,
                          env={**os.environ, "KCGX_PORT": str(port)})
    assert done.returncode == 3, done.stderr
    assert done.stdout.strip() == "kcgx: not running."


def test_the_wrapper_says_how_to_get_uv_when_it_is_missing(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    for tool in ("bash", "dirname", "readlink"):
        found = subprocess.run(["bash", "-c", f"command -v {tool}"], capture_output=True, text=True, check=True).stdout.strip()
        (bare / tool).symlink_to(found)
    done = subprocess.run([str(WRAPPER)], capture_output=True, text=True, env={"PATH": str(bare)}, check=False)
    assert done.returncode == 1
    assert "uv not found" in done.stderr and "setup.sh" in done.stderr
