"""The kcgx setup script.

Drives the real setup.sh as a subprocess with a stubbed PATH, the same way
tests/test_kcgx_launcher.py drives bin/kcgx. Nothing here installs
software, downloads a file, or opens a socket.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
