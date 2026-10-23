"""Prove the cockpit's server works on this machine: setup.sh step 7.

Starts `kcgx-web --demo` on a free port (demo, so it needs no network, no
ffmpeg and no audio device, and remembers nothing), then checks what a page
needs, the way a page does:

    health     GET /api/health answers 200, as kcgx
    page       GET / is the cockpit page
    websocket  /ws opens and its first frame is a snapshot

and shuts it down. One line per check, `ok` or `FAIL` and why, then a last
line setup.sh reads: `selfcheck ok` or `selfcheck failed`. Exit 0 only when
every check passed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request

from kcgx.launcher import HOST, free_port, health

START_TIMEOUT_SECS = 20.0


def _page(port: int) -> str:
    with urllib.request.urlopen(f"http://{HOST}:{port}/", timeout=5) as response:
        body = response.read().decode("utf-8", "replace")
    if "/static/js/main.js" not in body:
        raise ValueError("the page does not load the cockpit's script")
    return "the cockpit page"


def _websocket(port: int) -> str:
    from websockets.sync.client import connect

    with connect(f"ws://{HOST}:{port}/ws", open_timeout=5) as socket:
        frame = json.loads(socket.recv(timeout=5))
    if frame.get("t") != "snapshot":
        raise ValueError(f"the first frame was {frame.get('t')!r}, not a snapshot")
    return "first frame is a snapshot"


def run(out=print) -> int:
    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "kcgx.server", "--demo", "--port", str(port)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    failed = 0
    try:
        deadline = time.monotonic() + START_TIMEOUT_SECS
        body = None
        while time.monotonic() < deadline and process.poll() is None:
            body = health(port, timeout=0.5)
            if body:
                break
            time.sleep(0.1)
        if not body:
            reason = process.stdout.read().decode(errors="replace").strip() if process.poll() is not None else ""
            out(f"health     FAIL  the server did not answer{': ' + reason.splitlines()[-1] if reason else ''}")
            out("selfcheck failed")
            return 1
        out(f"health     ok    kcgx {body.get('version', '')} on port {port}".rstrip())
        for name, check in (("page", _page), ("websocket", _websocket)):
            try:
                out(f"{name:<10} ok    {check(port)}")
            except Exception as error:  # noqa: BLE001 -- every failure is a line, not a traceback
                failed += 1
                out(f"{name:<10} FAIL  {error}")
    finally:
        try:
            request = urllib.request.Request(f"http://{HOST}:{port}/api/shutdown", data=b"", method="POST")
            urllib.request.urlopen(request, timeout=5).close()
            process.wait(timeout=10)
        except Exception:  # noqa: BLE001 -- whatever went wrong, the server must not outlive the check
            process.kill()
            process.wait()
    out("selfcheck ok" if not failed else "selfcheck failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(run())
