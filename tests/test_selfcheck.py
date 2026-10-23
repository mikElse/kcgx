"""setup.sh step 7's server check (kcgx.selfcheck), for real: it starts a
demo server on a free port and asks it what a page asks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from kcgx import selfcheck


def test_a_working_server_passes_every_check():
    lines = []
    assert selfcheck.run(out=lines.append) == 0
    assert [line.split()[:2] for line in lines[:3]] == [["health", "ok"], ["page", "ok"], ["websocket", "ok"]]
    assert lines[-1] == "selfcheck ok"


def test_the_server_is_stopped_afterwards():
    lines = []
    selfcheck.run(out=lines.append)
    port = int(lines[0].rsplit(" ", 1)[-1])
    assert selfcheck.health(port) is None


def test_a_server_that_will_not_start_fails_with_its_reason():
    config = Path(os.environ["HOME"]) / ".config" / "squelch" / "squelch.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('max_streams = "seven"\n')
    lines = []
    assert selfcheck.run(out=lines.append) == 1
    assert lines[0].startswith("health     FAIL") and "max_streams" in lines[0]
    assert lines[-1] == "selfcheck failed"


def test_it_runs_as_a_module_the_way_setup_runs_it():
    done = subprocess.run([sys.executable, "-m", "kcgx.selfcheck"], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.strip().endswith("selfcheck ok")
