# Web Cockpit Phase E: The Switch

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the browser cockpit the only cockpit. A `kcgx` command that
starts the server in the background (or finds the running one), opens the
page, switches airport and stops it; `bin/kcgx` as its thin wrapper;
`setup.sh` in seven steps with no tmux or adsb-tui, proving the install by
starting the server; a README for the browser cockpit; and the terminal
app, tmux and Textual removed.

**Architecture:**

| Piece | Job |
|---|---|
| `kcgx.launcher` | `kcgx`, `go`, `stop`, `status`; `server.json`; "running" means health answers as kcgx |
| `bin/kcgx` | finds the repo through its symlink, runs `kcgx` there with `uv run` |
| `kcgx.selfcheck` | setup step 7: a demo server on a free port, asked for health, the page and the WebSocket |
| `kcgx-web --refresh-feeds` | setup step 6, in place of `squelch --refresh-feeds` |
| the page | `#airport` and `#airport=<query>` open CHANGE AIRPORT with the query typed |

**Tech Stack:** as phase D, less Textual. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-18-web-cockpit-design.md`, sections
"The launcher", "Install changes", "Components", "Testing", "Open questions".

## Decisions this plan makes that the spec did not

All written into the spec on 2026-10-22, in the same commit as this plan.

1. **The terminal app goes entirely** (the owner's choice, 2026-10-22), and
   with it Textual, the status pane, the airport picker, and the `squelch`,
   `kcgx-airport` and `kcgx-status` commands. Everything is at the
   `terminal-cockpit` tag, which Task 11 makes on `main`.
2. **`kcgx go` with no airport opens the page's search** (the owner's
   choice), and so does a query that names several airports, with the query
   typed. An exact ICAO or a query naming one airport switches at once,
   starting the server there if it is not running.
3. **Health says `"app": "kcgx"`**, so a server is recognised by what it
   says, not by having answered. An unrecorded kcgx server on the port is
   adopted; anything else on it is skipped for a free port.
4. **`kcgx status`** reports where it is running and at which airport, and
   exits 3 when it is not. **`kcgx --demo`** starts the demo server.
5. **A server that will not start is reported at once**, with the end of
   its log, rather than after the 20 s timeout.
6. **Setup's step 7 starts the real server**, as the demo on a free port,
   through `python -m kcgx.selfcheck`, rather than checking files.
7. **The User-Agent setup probes adsb.lol with** stays a literal in
   `setup.sh`, now tested against `kcgx.radar.DEFAULT_UA`, since `bin/kcgx`
   no longer has one.
8. **The terminal app's tests of the runtime are kept**, as
   `tests/test_runtime.py`: the server uses that code.

## Global Constraints

- Work in the `feat/web-cockpit` worktree at `/Users/mikelse/kcgx_web`.
- **No new dependency**; Textual leaves.
- **No test touches the network, ffmpeg or an audio device**, and none
  writes to `~/.local/state/kcgx/` or `~/.cache/squelch/`: the launcher
  tests' servers are `--demo`, on free ports, with `KCGX_STATE_PATH` and
  `HOME` in a temporary folder (the conftest backstop), and every server a
  test starts is stopped when it ends.
- **Every action is a click** on the page; the terminal has `kcgx` only.
- Run everything through uv from the repo root, with the browser group:
  `cd /Users/mikelse/kcgx_web && uv run --group dev --group browser pytest -q`
- The suite is **1008 tests** at the start (on the Mac) and **650** at the
  end: 400 go (all but a few rewritten setup tests with the code they
  test), 42 arrive, and 30 move to `tests/test_runtime.py`.
- **The old terminal cockpit must not be running** while this is built:
  stop it with `kcgx stop` in `/Users/mikelse/kcgx` first. Its tmux session
  would keep running under a launcher that no longer knows it.
- **Revert-check every new test.**
- Commit after every task. End each message with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

---

### Task 1: The health reply says it is kcgx

The launcher tells its own server from anything else that happens to answer on the port by an `app` field in `/api/health`.

- [ ] **Step 1: Tests.** Apply to `tests/test_server.py`:

```diff
diff --git a/tests/test_server.py b/tests/test_server.py
index 3806ed7..7606ead 100644
--- a/tests/test_server.py
+++ b/tests/test_server.py
@@ -84,6 +84,12 @@ def test_health_answers_once_up():
     assert body["protocol"] == 1
 
 
+def test_health_names_the_app_so_the_launcher_knows_its_own_server():
+    asgi, _ = app()
+    with client(asgi) as http:
+        assert http.get("/api/health").json()["app"] == "kcgx"
+
+
 @pytest.mark.parametrize("base", ["http://evil.example:8473", "http://192.168.1.20:8473"])
 def test_a_request_naming_another_host_is_refused(base):
     asgi, _ = app()
```

- [ ] **Step 2:** Run them. Health has no `app` field: `KeyError: 'app'`.

- [ ] **Step 3: Code.** Apply to `src/kcgx/server.py`:

```diff
diff --git a/src/kcgx/server.py b/src/kcgx/server.py
index 5603ed2..d97ee47 100644
--- a/src/kcgx/server.py
+++ b/src/kcgx/server.py
@@ -158,6 +158,7 @@ def create_app(
         return JSONResponse(
             {
                 "ok": True,
+                "app": "kcgx",  # how the launcher tells this server from anything else on the port
                 "version": _version(),
                 "protocol": protocol.PROTOCOL,
                 "icao": station.icao,
```

- [ ] **Step 4:** Suite: **1009 passed** (+1). Commit `feat(web): health says it is kcgx`.

---

### Task 2: `kcgx-web --refresh-feeds`

Setup's feed cache step ran `squelch --refresh-feeds`, which goes with the terminal app in Task 8. `refresh_feeds` moves into `squelch.runtime` beside the rest of feed loading (the terminal app's copy stays until Task 8), and `kcgx-web` runs it before its ffmpeg check.

- [ ] **Step 1: Tests.** Apply to `tests/test_server.py`:

```diff
diff --git a/tests/test_server.py b/tests/test_server.py
index 7606ead..dce8941 100644
--- a/tests/test_server.py
+++ b/tests/test_server.py
@@ -461,3 +461,28 @@ def test_radar_off_means_no_polling():
     with client(radar_app(lambda *a: calls.append(a) or {"ac": []}, radar=False)) as http, http.websocket_connect(WS) as ws:
         ready(ws)
     assert calls == []
+
+
+# -- --refresh-feeds -------------------------------------------------------------
+
+
+def test_refresh_feeds_fills_the_cache_without_ffmpeg_or_a_server(monkeypatch, tmp_path):
+    """setup.sh runs it, possibly before the audio path is complete: it has
+    no business starting a mixer or a server to fill a JSON file."""
+    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
+    asked = []
+    monkeypatch.setattr("squelch.runtime.refresh_feeds", lambda config, out: asked.append(config.icao) or 0)
+    code = main(["--refresh-feeds", "--icao", "ksea"], which=lambda n: None, serve=pytest.fail,
+                mixer_factory=pytest.fail, out=lambda line: None)
+    assert code == 0 and asked == ["KSEA"]
+
+
+def test_refresh_feeds_defaults_to_the_remembered_airport(monkeypatch, tmp_path):
+    from kcgx.state import write_airport
+
+    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
+    write_airport("KORD")
+    asked = []
+    monkeypatch.setattr("squelch.runtime.refresh_feeds", lambda config, out: asked.append(config.icao) or 1)
+    assert main(["--refresh-feeds"], which=lambda n: None, serve=pytest.fail, out=lambda line: None) == 1
+    assert asked == ["KORD"]
```

- [ ] **Step 2:** Run them. `--refresh-feeds` is an unrecognised argument.

- [ ] **Step 3: Code.** Apply to `src/kcgx/server.py`:

```diff
diff --git a/src/kcgx/server.py b/src/kcgx/server.py
index d97ee47..d015ce2 100644
--- a/src/kcgx/server.py
+++ b/src/kcgx/server.py
@@ -306,6 +306,11 @@ def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
         action="store_true",
         help="synthetic feeds: no network, no ffmpeg, no audio, nothing remembered",
     )
+    parser.add_argument(
+        "--refresh-feeds",
+        action="store_true",
+        help="fetch and cache the airport's LiveATC feed list, then exit; no server, no audio",
+    )
     return parser.parse_args(argv)
 
 
@@ -327,10 +332,22 @@ def main(
     mixer_factory: Callable[..., Any] | None = None,
     out: Callable[[str], None] = print,
 ) -> int:
+    from dataclasses import replace
+
     from squelch.config import ConfigError, load_config
-    from squelch.runtime import FFMPEG_MISSING
+    from squelch.runtime import FFMPEG_MISSING, refresh_feeds
 
     args = parse_args(argv)
+    if args.refresh_feeds:
+        # Before the ffmpeg check: filling the cache needs no decoder, and a
+        # machine part way through setup should still be able to warm it.
+        try:
+            config = load_config()
+        except ConfigError as exc:
+            print(f"kcgx-web: {exc}", file=sys.stderr)
+            return 2
+        icao = (args.icao or current_icao(known=lambda i: True, warn=out)).upper()
+        return refresh_feeds(replace(config, icao=icao), out=out)
     if not args.demo and which("ffmpeg") is None:
         print(f"kcgx-web: {FFMPEG_MISSING}", file=sys.stderr)
         return 2
```

- [ ] **Step 4: Code.** Apply to `src/squelch/feeds.py`:

```diff
diff --git a/src/squelch/feeds.py b/src/squelch/feeds.py
index f2157f7..037042b 100644
--- a/src/squelch/feeds.py
+++ b/src/squelch/feeds.py
@@ -151,7 +151,7 @@ FETCH_ATTEMPTS = 5
 # four getting through, five attempts succeed about 76% of the time and
 # eight about 90% -- worth a few extra seconds exactly once per airport.
 COLD_FETCH_ATTEMPTS = 8
-# For `squelch --refresh-feeds`, which runs with nobody waiting on a UI --
+# For `kcgx-web --refresh-feeds`, which runs with nobody waiting on a page --
 # from setup.sh, or by hand. At roughly one request in four getting through,
 # twenty attempts fail about 0.3% of the time against eight's 10%, and the
 # only thing it costs is a wall clock nobody is watching. Launch keeps the
```

- [ ] **Step 5: Code.** Apply to `src/squelch/runtime.py`:

```diff
diff --git a/src/squelch/runtime.py b/src/squelch/runtime.py
index 082e060..1a462d4 100644
--- a/src/squelch/runtime.py
+++ b/src/squelch/runtime.py
@@ -1,8 +1,7 @@
-"""Loading an airport's feeds and building their sessions, with no UI.
-
-Moved out of squelch.__main__ so the web server can use exactly what the
-terminal app uses without importing Textual. squelch.__main__ re-exports
-every name here, so nothing that imported them from there has to change.
+"""Loading an airport's feeds, building their sessions, and filling the feed
+cache, with no UI. The web server's station uses all of it; it was moved
+here from the terminal app's __main__ in phase B, and the terminal app was
+retired in phase E.
 """
 
 from __future__ import annotations
@@ -14,6 +13,7 @@ from typing import Any
 from squelch.config import Config
 from squelch.feeds import (
     CACHE_TTL_SECONDS,
+    REFRESH_ATTEMPTS,
     Feed,
     FeedError,
     cached_age_seconds,
@@ -30,7 +30,7 @@ AUDIO_FAILED = (
 
 FFMPEG_MISSING = (
     "ffmpeg not found on PATH — squelch decodes feeds with it. "
-    "Install it (macOS: brew install ffmpeg) and start squelch again."
+    "Install it (macOS: brew install ffmpeg) and start kcgx again."
 )
 
 
@@ -185,6 +185,48 @@ def picker_feeds(
     return read_cached_feeds(config.icao, directory=cache_dir) or []
 
 
+def refresh_feeds(
+    config: Config,
+    *,
+    out: Callable[[str], None] = print,
+    fetch: Callable[..., list[Feed]] = fetch_feeds,
+    cache_dir: Path | None = None,
+) -> int:
+    """Fill the feed cache for `config.icao` from outside the cockpit.
+
+    This exists because of where the waiting can happen. LiveATC fronts its
+    listing with Cloudflare and refuses roughly three requests in four, so a
+    cold start is a coin flip: the station tries eight times and then opens
+    the single configured feed, which at the default airport reads as "kcgx
+    only found KPDX tower" and gives no sign that the other eleven feeds
+    exist. More attempts at start is not the answer: that trades a wrong
+    stack for one that takes a minute to appear.
+
+    Out here nobody is waiting on a page, so it can afford to be patient.
+    Once this has run, starts read the cache and make no request at all.
+    `kcgx-web --refresh-feeds` runs it; setup.sh step 6 calls that.
+    """
+    out(f"Fetching the LiveATC feed list for {config.icao}...")
+    try:
+        feeds = fetch(config.icao, cache_dir=cache_dir, attempts=REFRESH_ATTEMPTS)
+    except FeedError:
+        out(f"LiveATC publishes no feeds for {config.icao}.")
+        return 1
+    except Exception as exc:  # noqa: BLE001 -- anything here is one more refusal to report
+        out(f"Could not reach LiveATC's listing for {config.icao}: {exc}")
+        out("This is usually its bot protection rather than anything local.")
+        out("Nothing was cached; try again, or just start kcgx.")
+        return 1
+    if not feeds:
+        out(f"LiveATC publishes no feeds for {config.icao}.")
+        return 1
+    write_cached_feeds(config.icao, feeds, directory=cache_dir)
+    out(f"Cached {len(feeds)} feed(s) for {config.icao}:")
+    for feed in feeds:
+        out(f"  {feed.ident:<18} {feed.label}")
+    return 0
+
+
 def preferred_index(feeds: list[Feed]) -> int:
     """Which feed to leave audible when the configured one matched nothing.
```

- [ ] **Step 6:** Suite: **1011 passed** (+2). Commit `feat(web): kcgx-web --refresh-feeds`.

---

### Task 3: `kcgx.launcher`

The new `kcgx` command. Its tests drive real demo servers on free ports with their state in a temporary folder, and stop every server they start. The wrapper's own tests come in Task 6, with the wrapper.

- [ ] **Step 1: Tests.** Create `tests/test_launcher.py`:

```python
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
```

- [ ] **Step 2:** Run them. `ImportError: cannot import name 'launcher' from 'kcgx'`.

- [ ] **Step 3: Code.** Create `src/kcgx/launcher.py`:

```python
"""kcgx: the cockpit's one command (spec, The launcher).

    kcgx                  start the server if it is not running, then open the page
    kcgx go [query]       point the cockpit at an airport
    kcgx stop             stop the server
    kcgx status           say whether it is running, and where
    kcgx --no-open        start without opening a browser
    kcgx --demo           start the demo (synthetic feeds and traffic, no audio)

The server runs detached, writes where it is to `server.json` beside the
remembered airport, and logs to `server.log` there. "Running" means its
`/api/health` answers as kcgx, never that the file exists: a file left by a
crash is replaced, and a port answered by something else is skipped for a
free one.

`kcgx go` with an exact ICAO, or a query that names one airport, switches
the cockpit there (starting it at that airport if it is not running). Any
other query, or none, opens the page with the airport search showing and
the query already typed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kcgx.airports import find, load_airports, search
from kcgx.state import default_path, write_airport

HOST = "127.0.0.1"
DEFAULT_PORT = 8473
START_TIMEOUT_SECS = 20.0
STOP_TIMEOUT_SECS = 10.0
LOG_ROLL_BYTES = 1_000_000

Opener = Callable[[str], Any]


def state_dir() -> Path:
    """Beside the remembered airport, so KCGX_STATE_PATH moves all three."""
    return default_path().parent


def info_path() -> Path:
    return state_dir() / "server.json"


def log_path() -> Path:
    return state_dir() / "server.log"


def say(text: str) -> None:
    print(f"kcgx: {text}")


def fail(text: str) -> int:
    print(f"kcgx: {text}", file=sys.stderr)
    return 1


# -- is it running? ------------------------------------------------------------


def health(port: int, *, timeout: float = 1.0) -> dict | None:
    """The server's health if a kcgx server answers on `port`, else None."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=timeout) as response:
            body = json.loads(response.read())
    except (OSError, ValueError):
        return None
    if isinstance(body, dict) and body.get("app") == "kcgx" and body.get("ok"):
        return body
    return None


def read_info() -> dict | None:
    try:
        info = json.loads(info_path().read_text())
    except (OSError, ValueError):
        return None
    if isinstance(info, dict) and isinstance(info.get("port"), int):
        return info
    return None


def running() -> dict | None:
    """The recorded server, if it really is answering. A stale record (a
    crash, a reboot) is removed so nothing trusts it again."""
    info = read_info()
    if info is None:
        return None
    if health(info["port"]) is not None:
        return info
    with contextlib.suppress(OSError):
        info_path().unlink()
    return None


def port_free(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def url(info: dict, fragment: str = "") -> str:
    return f"http://{HOST}:{info['port']}/" + (f"#{fragment}" if fragment else "")


# -- starting and stopping -------------------------------------------------------


def _roll_log() -> None:
    path = log_path()
    with contextlib.suppress(OSError):
        if path.stat().st_size > LOG_ROLL_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))


def _log_tail(lines: int = 8) -> str:
    try:
        text = log_path().read_text(errors="replace")
    except OSError:
        return ""
    return "\n".join(text.strip().splitlines()[-lines:])


def start(*, demo: bool = False, timeout: float = START_TIMEOUT_SECS) -> tuple[dict | None, str]:
    """Start a detached server and wait for it to answer. Returns its record,
    or None and the reason it did not come up."""
    port = int(os.environ.get("KCGX_PORT", DEFAULT_PORT))
    if health(port) is not None:
        # A kcgx server nobody recorded (a lost file): adopt it.
        info = {"port": port, "pid": None, "demo": demo}
        _write_info(info)
        return info, ""
    if not port_free(port):
        port = free_port()  # something else has the port: take another
    state_dir().mkdir(parents=True, exist_ok=True)
    _roll_log()
    command = [sys.executable, "-m", "kcgx.server", "--port", str(port)]
    if demo:
        command.append("--demo")
    with log_path().open("ab") as log:
        log.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(command[1:])}\n".encode())
        log.flush()
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # survives the terminal it was started from
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health(port, timeout=0.5) is not None:
            info = {"port": port, "pid": process.pid, "demo": demo}
            _write_info(info)
            return info, ""
        if process.poll() is not None:
            return None, _log_tail() or f"the server exited with code {process.returncode}"
        time.sleep(0.1)
    with contextlib.suppress(OSError):
        process.terminate()
    return None, f"the server did not answer within {timeout:.0f} s\n{_log_tail()}".strip()


def _write_info(info: dict) -> None:
    path = info_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(info) + "\n")
    os.replace(temporary, path)


def _post(info: dict, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else b""
    request = urllib.request.Request(
        f"http://{HOST}:{info['port']}{path}",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except ValueError:
            return error.code, {}


def stop(info: dict, *, timeout: float = STOP_TIMEOUT_SECS) -> bool:
    """Ask the server to shut down, and make sure it has. Falls back to a
    signal to the recorded process if it will not go."""
    with contextlib.suppress(OSError):
        _post(info, "/api/shutdown")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health(info["port"], timeout=0.5) is None:
            break
        time.sleep(0.1)
    else:
        pid = info.get("pid")
        if pid:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
    with contextlib.suppress(OSError):
        info_path().unlink()
    return health(info["port"], timeout=0.5) is None


def ensure(*, demo: bool = False) -> tuple[dict | None, bool, str]:
    """The running server, starting one if need be: (record, started, why not)."""
    info = running()
    if info is not None:
        return info, False, ""
    info, why = start(demo=demo)
    return info, info is not None, why


# -- commands --------------------------------------------------------------------


def cmd_open(args, opener: Opener) -> int:
    info, started, why = ensure(demo=args.demo)
    if info is None:
        return fail(f"could not start the server.\n{why}")
    if args.demo and not info.get("demo"):
        say("a cockpit is already running; showing it (stop it first for the demo)")
    page = url(info)
    say(f"{'started' if started else 'running'} at {page}")
    if not args.no_open:
        opener(page)
    return 0


def cmd_go(args, opener: Opener) -> int:
    query = " ".join(args.query).strip()
    airports = load_airports()
    airport = find(query, airports) if query else None
    if query and airport is None:
        matches = search(query, airports)
        if not matches:
            return fail(f"no airport matches {query!r}")
        if len(matches) == 1:
            airport = matches[0]

    if airport is None:
        # No query, or one that names several airports: let the page's
        # search take it from here.
        info, _, why = ensure()
        if info is None:
            return fail(f"could not start the server.\n{why}")
        fragment = "airport" + (f"={urllib.parse.quote(query)}" if query else "")
        page = url(info, fragment)
        say(f"choose an airport at {page}" if not args.no_open else f"search at {page}")
        if not args.no_open:
            opener(page)
        return 0

    info = running()
    if info is None:
        # Not running: remember the airport first, so it starts there.
        write_airport(airport.icao)
        info, why = start()
        if info is None:
            return fail(f"could not start the server.\n{why}")
    else:
        status, body = _post(info, "/api/airport", {"icao": airport.icao})
        if status != 202:
            return fail(body.get("error") or f"the server refused {airport.icao} ({status})")
    say(f"{airport.icao}  {airport.name}")
    if not args.no_open and args.open:
        opener(url(info))
    return 0


def cmd_stop(args, opener: Opener) -> int:
    info = running()
    if info is None:
        say("not running.")
        return 0
    if stop(info):
        say("stopped.")
        return 0
    return fail(f"the server on port {info['port']} would not stop")


def cmd_status(args, opener: Opener) -> int:
    info = running()
    if info is None:
        say("not running.")
        return 3
    body = health(info["port"]) or {}
    demo = ", demo" if info.get("demo") else ""
    say(f"running at {url(info)}  ({body.get('icao', '?')}{demo})")
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kcgx",
        description="The KCGX cockpit: live ATC audio and traffic, in your browser.",
    )
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    parser.add_argument("--demo", action="store_true", help="synthetic feeds and traffic, no audio")
    commands = parser.add_subparsers(dest="command")
    go = commands.add_parser("go", help="point the cockpit at an airport")
    go.add_argument("query", nargs="*", help="an ICAO, or text to search for")
    go.add_argument("--no-open", action="store_true", help="do not open a browser")
    go.add_argument("--open", action="store_true", help="open the page after switching")
    commands.add_parser("stop", help="stop the server")
    commands.add_parser("status", help="say whether it is running")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, opener: Opener = webbrowser.open) -> int:
    args = parse_args(argv)
    handler = {None: cmd_open, "go": cmd_go, "stop": cmd_stop, "status": cmd_status}[args.command]
    return handler(args, opener)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Code.** Apply to `pyproject.toml`:

```diff
diff --git a/pyproject.toml b/pyproject.toml
index eed5d6a..d6c7bf2 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -21,6 +21,7 @@ squelch = "squelch.__main__:main"
 kcgx-airport = "kcgx.__main__:main"
 kcgx-status = "kcgx.status:main"
 kcgx-web = "kcgx.server:main"
+kcgx = "kcgx.launcher:main"
 
 [build-system]
 requires = ["uv_build>=0.11.14,<0.12.0"]
```

- [ ] **Step 5:** Suite: **1030 passed** (+19). Commit `feat(launcher): kcgx starts, finds, switches and stops the server`.

---

### Task 4: Setup's server check, `kcgx.selfcheck`

Starts the demo server on a free port, checks health, the page and the WebSocket's first frame the way a page would, and stops it. Setup reads its last line.

- [ ] **Step 1: Tests.** Create `tests/test_selfcheck.py`:

```python
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
```

- [ ] **Step 2:** Run them. `ImportError: cannot import name 'selfcheck' from 'kcgx'`.

- [ ] **Step 3: Code.** Create `src/kcgx/selfcheck.py`:

```python
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
```

- [ ] **Step 4:** Suite: **1034 passed** (+4). Commit `feat(setup): a server self check for step 7`.

---

### Task 5: `setup.sh` in seven steps

tmux, the adsb-tui download and licence prompt, its config file and the terminal width check go; the feed list is step 6 and the checks step 7, which runs the self check. `tests/test_setup.py` loses 24 tests (what went, and the old forms of a few rewritten), keeps the rest with tmux out of their PATH stubs, and gains 11, of the self check, ARM Linux, the platform row, the User-Agent against `kcgx.radar.DEFAULT_UA`, and that nothing removed is still asked for.

- [ ] **Step 1: Tests.** Replace `tests/test_setup.py` entirely with:

```python
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
```

- [ ] **Step 2:** Run them. Several fail: the old script still says `Step 1/9`, wants tmux, and has no server check.

- [ ] **Step 3: Code.** Replace `setup.sh` entirely with:

```bash
#!/usr/bin/env bash
# setup.sh — install everything kcgx needs, prove it works, open the cockpit.
#
# Seven steps. Each announces itself, each asks before changing anything, and
# each is idempotent -- so the second run, the one you do when you think
# something went wrong, ends exactly where the first did.
#
# The contract is that reaching the end means the cockpit works: every
# dependency installed, and step 7 having actually started the server and
# asked it for the page and its WebSocket, rather than having checked that a
# file exists. A setup script that finishes and leaves you with a broken
# page has not finished.
#
# Phase E of the web cockpit (2026-10-22) took out tmux, adsb-tui and its
# config, and the terminal width check: the cockpit is a page in your
# browser now, and the radar is the server's own.
#
# Test seams (all default to production behaviour when unset):
#   KCGX_SETUP_YES         non-empty takes every prompt's default answer
#   KCGX_SETUP_NO_LAUNCH   non-empty stops before exec'ing the launcher
#   KCGX_SETUP_OS          override the detected operating system
#   KCGX_SETUP_PKG         override the detected package manager
#   KCGX_SETUP_SKIP_NET    non-empty skips the two reachability probes

set -euo pipefail

REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set by resolve_platform, read by nearly every step. Declared here so the
# ordering is explicit rather than a happy accident of which step runs first.
OS=""        # macos | linux | unsupported
PKG=""       # brew | apt | dnf | pacman | none
SUDO=""      # "" when root or on brew, else "sudo"

PREFIX="$HOME/.local/bin"
# adsb.lol 403s a request that carries no User-Agent. Step 7's probe sends the
# one the server's radar sends (kcgx.radar.DEFAULT_UA): a check that proves a
# different request than the app sends proves nothing. The two are literals
# in two languages, and tests/test_setup.py fails the moment they disagree.
ADSB_UA="kcgx/0.1 (+https://github.com/mikElse/kcgx)"
STEPS=7

say()  { printf '%s\n' "$*"; }
warn() { printf 'setup: %s\n' "$*" >&2; }
die()  { printf 'setup: %s\n' "$*" >&2; exit 1; }

have_command() { command -v "$1" >/dev/null 2>&1; }

step() { say ""; say "── Step $1/$STEPS  $2"; say ""; }
row()  { printf '  %-12s %s\n' "$1" "$2"; }
vrow() { printf '  %-16s %-6s %s\n' "$1" "$2" "${3:-}"; }

# Every prompt reads from stdin rather than /dev/tty. setup.sh is always a
# file, so stdin is free -- and a /dev/tty read is untestable: under pytest
# there is no controlling terminal, so the read would fail open regardless of
# what the test typed, making the decline test pass for the wrong reason.
confirm() {  # $1=question $2=default(y|n); returns 0 to proceed
    local reply default="${2:-y}" hint
    if [ "$default" = "y" ]; then hint="[Y/n]"; else hint="[y/N]"; fi
    if [ -n "${KCGX_SETUP_YES:-}" ]; then
        say "$1 $hint $default"
        [ "$default" = "y" ]
        return
    fi
    printf '%s %s ' "$1" "$hint"
    read -r reply || reply=""
    [ -z "$reply" ] && reply="$default"
    case "$reply" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

# -- platform ---------------------------------------------------------------
#
# Any processor will do. Setup used to key a release download on the machine
# (adsb-tui published macOS and x86_64 Linux binaries only), which made ARM
# Linux a stopping point; with nothing to download there is nothing to match.

detect_os() {
    case "$(uname -s)" in
        Darwin) printf 'macos' ;;
        Linux)  printf 'linux' ;;
        *)      printf 'unsupported' ;;
    esac
}

detect_pkg() {
    have_command brew && { printf 'brew'; return; }
    if [ "$OS" = "linux" ]; then
        have_command apt-get && { printf 'apt'; return; }
        have_command dnf     && { printf 'dnf'; return; }
        have_command pacman  && { printf 'pacman'; return; }
    fi
    printf 'none'
}

# One place that settles all three, so `--verify` and a full run cannot
# disagree about what machine they are on.
resolve_platform() {
    OS="${KCGX_SETUP_OS:-$(detect_os)}"
    PKG="${KCGX_SETUP_PKG:-$(detect_pkg)}"
    detect_sudo
}

# Homebrew installs as the invoking user and refuses to run under sudo.
detect_sudo() {
    [ "$PKG" = "brew" ] && return 0
    [ "$(id -u)" = "0" ] && return 0
    if have_command sudo; then SUDO="sudo"; fi
    # Explicit: the `&&` form this replaced made a missing sudo the
    # function's own exit status, and under `set -e` an unguarded call
    # then killed the script after the banner and before step 1 -- no
    # message, exit 1. install_packages owns that case (it dies with
    # something to act on), and can only own it if we return here.
    return 0
}

# $1 = ffmpeg | portaudio. Empty output means "not a package here".
pkg_name() {
    case "$1" in
        ffmpeg) printf '%s' "$1" ;;
        portaudio)
            # Only Linux. The sounddevice wheel bundles its own PortAudio on
            # macOS, which is why this dependency stayed invisible for so
            # long: on Linux the same wheel ships no library at all and
            # `import sounddevice` dies with "PortAudio library not found"
            # before the server can play anything.
            case "$PKG" in
                apt)        printf 'libportaudio2' ;;
                dnf|pacman) printf 'portaudio' ;;
            esac
            ;;
    esac
}

pkg_install_cmd() {  # $* = packages
    case "$PKG" in
        brew)   printf 'brew install %s' "$*" ;;
        apt)    printf '%sapt-get install -y %s' "${SUDO:+$SUDO }" "$*" ;;
        dnf)    printf '%sdnf install -y %s' "${SUDO:+$SUDO }" "$*" ;;
        pacman) printf '%spacman -S --needed --noconfirm %s' "${SUDO:+$SUDO }" "$*" ;;
    esac
}

# -- what is present --------------------------------------------------------

# Every version probe below reads its input to the end, and none of them
# terminates a pipeline early. `set -o pipefail` is on, and a `| head -1` or a
# `| grep -q` sends SIGPIPE upstream the moment it has what it wants: the
# pipeline then reports 141 and the whole probe reads as a missing tool. It
# fires on output long enough to still be flowing, which `ffmpeg -version`
# is.

# The install decision only. The truth is `import sounddevice` in step 7:
# ldconfig can be absent or unreadable, and a false "missing" here costs one
# no-op package install, while a false "present" costs a silent audio failure.
portaudio_present() {
    local ldconfig
    [ "$OS" != "linux" ] && return 0
    ldconfig="$(command -v ldconfig || true)"
    [ -n "$ldconfig" ] || ldconfig="/sbin/ldconfig"
    [ -x "$ldconfig" ] || return 1
    # Not `grep -q`: it exits on the first match, and the SIGPIPE that sends
    # upstream fails the pipeline under pipefail -- reporting a PortAudio
    # that is plainly installed as missing.
    "$ldconfig" -p 2>/dev/null | grep 'libportaudio\.so' >/dev/null
}

version_of() {  # best-effort, for the table only
    case "$1" in
        uv)     uv --version 2>/dev/null | awk 'NR == 1 { v = $2 } END { print v }' ;;
        ffmpeg) ffmpeg -version 2>/dev/null | awk 'NR == 1 { v = $3 } END { print v }' ;;
        curl)   curl --version 2>/dev/null | awk 'NR == 1 { v = $2 } END { print v }' ;;
    esac
}

# Everything still missing, as a package list for the detected manager.
missing_packages() {
    local needed=""
    have_command ffmpeg  || needed="$needed $(pkg_name ffmpeg)"
    portaudio_present    || needed="$needed $(pkg_name portaudio)"
    # shellcheck disable=SC2086
    set -- $needed
    printf '%s' "$*"
}

# -- advisory ---------------------------------------------------------------

check_pyenv() {
    local python_path
    python_path="$(command -v python 2>/dev/null || true)"
    case "$python_path" in
        */.pyenv/shims/*)
            say ""
            say "  note: pyenv shims come before uv on your PATH, so bare"
            say "        \`python\` will not work inside this repo. That is"
            say "        expected -- every kcgx command uses \`uv run\`,"
            say "        which ignores pyenv entirely."
            ;;
    esac
}

# What to do about whatever the table reported as missing. It belongs beside
# the finding rather than only in the steps that follow: `--check` exits
# straight after this, so for anyone reading the table first -- which is the
# point of --check -- a remedy printed three steps later is no remedy. A table
# naming tools and no way to get any of them restates the "which
# prerequisites do I need?" problem instead of answering it.
missing_advice() {
    local packages
    packages="$(missing_packages)"
    [ -z "$packages" ] && have_command uv && return 0

    say ""
    say "To install what is missing:"
    if [ -n "$packages" ]; then
        if [ "$PKG" = "none" ]; then
            say "  (no supported package manager found) $packages"
        else
            say "  $(pkg_install_cmd "$packages")"
        fi
    fi
    have_command uv ||
        say "  curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh"
    say ""
    say "Or run ./setup.sh, which does all of it, asking before each step."
}

# -- step 1 -----------------------------------------------------------------

preflight() {
    resolve_platform
    step 1 "What you have"

    row "platform" "$OS $(uname -m)"
    row "packages" "$PKG"
    say ""
    have_command uv     && row uv     "found    $(version_of uv)"     || row uv     "missing"
    have_command ffmpeg && row ffmpeg "found    $(version_of ffmpeg)" || row ffmpeg "missing"
    have_command curl   && row curl   "found    $(version_of curl)"   || row curl   "missing"
    if [ "$OS" = "linux" ]; then
        portaudio_present && row portaudio "found" || row portaudio "missing"
    fi

    check_pyenv
    missing_advice
}

# -- step 2 -----------------------------------------------------------------

install_packages() {
    local packages cmd
    step 2 "System packages"

    packages="$(missing_packages)"
    if [ -z "$packages" ]; then
        say "ffmpeg and PortAudio are both present. Nothing to install."
        return 0
    fi

    if [ "$PKG" = "none" ]; then
        if [ "$OS" = "macos" ]; then
            die "Homebrew is needed to install: $packages
Install it first, then run this again:
  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"
See https://brew.sh"
        fi
        die "no supported package manager found (looked for brew, apt-get, dnf, pacman).
Install these with whatever your system uses, then run this again:
  $packages"
    fi

    if [ "$PKG" != "brew" ] && [ "$(id -u)" != "0" ] && [ -z "$SUDO" ]; then
        die "these need root to install, and sudo is not available:
  $packages
Install them as root, then run this again."
    fi

    cmd="$(pkg_install_cmd "$packages")"
    say "Missing: $packages"
    say ""
    say "  $cmd"
    say ""
    case " $packages " in
        *" libportaudio2 "*|*" portaudio "*)
            say "PortAudio is what the cockpit plays sound through. Without it"
            say "\`import sounddevice\` fails outright and nothing can be heard"
            say "-- on macOS the Python wheel carries its own copy, on Linux it"
            say "does not."
            say ""
            ;;
    esac
    confirm "Run that now?" y || die "Nothing installed. Install them yourself and run this again."

    if [ "$PKG" = "apt" ]; then
        # A stale index is the usual reason apt cannot find a package that
        # plainly exists, and it is a confusing failure to hand somebody
        # three steps into an install. Non-fatal: the install itself may
        # still succeed against what is already cached.
        ${SUDO:+$SUDO }apt-get update || warn "apt-get update failed; trying the install anyway."
    fi
    # Word splitting is intended: $cmd is a whole command line.
    # shellcheck disable=SC2086
    if ! $cmd; then
        if [ "$PKG" = "dnf" ]; then
            warn "dnf could not install $packages.
Fedora ships no ffmpeg of its own -- it comes from RPM Fusion:
  sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-\$(rpm -E %fedora).noarch.rpm"
        fi
        die "installing $packages failed; nothing else was changed."
    fi
}

# -- step 3 -----------------------------------------------------------------

install_uv() {
    step 3 "uv, and the Python it supplies"

    if have_command uv; then
        say "uv $(version_of uv) is already installed."
        return 0
    fi

    say "uv runs everything here, and supplies the Python 3.14 this project"
    say "needs -- there is no system Python involved and nothing to install"
    say "by hand afterwards."
    say ""
    say "  curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh"
    say ""
    say "INSTALLER_NO_MODIFY_PATH=1 stops that installer appending to your"
    say "~/.zshrc, ~/.bash_profile and ~/.profile behind your back. Step 5"
    say "asks about your PATH in the open instead."
    say ""
    confirm "Install uv now?" y || die "uv is required; there is no cockpit without it."

    have_command curl || die "curl is needed to fetch uv, and is not installed."
    # (Verified against the installer source: it reads UV_NO_MODIFY_PATH
    # first, then INSTALLER_NO_MODIFY_PATH.)
    curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh ||
        die "the uv installer failed; nothing else was changed."
    # The profile is untouched by design, so this process has to put the new
    # uv on its own PATH itself.
    PATH="$PREFIX:$PATH"
    have_command uv || die "uv installed but is still not on PATH; expected it in $PREFIX."
    say "Installed uv $(version_of uv)."
}

# -- step 4 -----------------------------------------------------------------

sync_project() {
    step 4 "Python dependencies"

    have_command uv || die "uv is missing, so there is nothing to sync with."

    say "uv sync downloads the Python 3.14 interpreter if you do not have it,"
    say "creates .venv/ in this repo, and installs the dependencies at the"
    say "versions pinned in uv.lock:"
    say ""
    say "  numpy        the mixer's sum and scale"
    say "  sounddevice  the output stream (PortAudio, from step 2)"
    say "  starlette    the cockpit's local web server"
    say "  uvicorn      what runs it"
    say "  websockets   the page's live connection"
    say ""
    say "Nothing is installed outside this directory."
    say ""
    confirm "Run uv sync now?" y || die "The Python dependencies are required; stopping here."

    uv sync --project "$REPO" || die "uv sync failed; nothing was wired up."
}

# -- step 5 -----------------------------------------------------------------

# The line appended to a shell profile, and the marker that keeps a second
# run from appending it twice.
PATH_MARKER="# added by kcgx setup.sh"

profile_file() {
    case "$(basename "${SHELL:-/bin/sh}")" in
        zsh)  printf '%s/.zshrc' "$HOME" ;;
        bash) if [ "$OS" = "macos" ]; then printf '%s/.bash_profile' "$HOME"
              else printf '%s/.bashrc' "$HOME"; fi ;;
        fish) printf '%s/fish/config.fish' "${XDG_CONFIG_HOME:-$HOME/.config}" ;;
    esac
}

profile_line() {
    if [ "$(basename "${SHELL:-/bin/sh}")" = "fish" ]; then
        printf 'fish_add_path "%s"' "$PREFIX"
    else
        printf 'export PATH="%s:$PATH"' "$PREFIX"
    fi
}

path_has_prefix() {
    case ":$PATH:" in *":$PREFIX:"*) return 0 ;; *) return 1 ;; esac
}

link_launcher() {
    local target="$REPO/bin/kcgx" link="$PREFIX/kcgx" profile
    step 5 "The launcher on your PATH"

    mkdir -p "$PREFIX"

    if [ -L "$link" ]; then
        # Already ours? Nothing to do. Somebody else's? Never clobber it.
        #
        # A plain string compare against what we would write, deliberately:
        # resolving the link through `cd`/`pwd` inside a test is a command
        # substitution that can fail under `set -e`, and anything that does
        # not match exactly is treated as foreign. Conservative in the safe
        # direction -- the cost of a false "foreign" is one message, the cost
        # of a false "ours" is destroying somebody's launcher.
        if [ "$(readlink "$link")" = "$target" ]; then
            say "Launcher already linked: $link"
        else
            die "$link already exists and points somewhere else.
Remove it yourself if you want setup to manage it."
        fi
    elif [ -e "$link" ]; then
        die "$link already exists and is not a symlink.
Remove it yourself if you want setup to manage it."
    else
        # A symlink rather than a copy: bin/kcgx resolves its own repo root
        # through symlinks, and a copy would look for the project in
        # ~/.local/.
        ln -s "$target" "$link"
        say "Linked $link -> $target"
    fi

    if path_has_prefix; then
        say "$PREFIX is already on your PATH."
        return 0
    fi

    profile="$(profile_file)"
    say ""
    say "$PREFIX is NOT on your PATH."
    say ""
    say "Without it the cockpit still starts as $REPO/bin/kcgx, but"
    say "not as plain \`kcgx\` from any terminal."
    say ""
    say "  $(profile_line)"
    say ""

    if [ -z "$profile" ]; then
        warn "your shell (${SHELL:-unknown}) has no profile setup.sh knows how to
edit. Add the line above to it yourself."
        return 0
    fi

    say "That line can go in $profile."
    if ! confirm "Append it to $profile?" y; then
        say ""
        say "Not appended. Add it yourself to type plain \`kcgx\`."
        return 0
    fi

    if [ -f "$profile" ] && grep -qF "$PATH_MARKER" "$profile"; then
        say "$profile already carries it; leaving it alone."
        return 0
    fi
    if [ -f "$profile" ]; then
        cp "$profile" "$profile.kcgx-backup" ||
            die "could not back up $profile; refusing to edit it."
        say "Backed up $profile -> $profile.kcgx-backup"
    fi
    mkdir -p "$(dirname "$profile")"
    printf '\n%s\n%s\n' "$PATH_MARKER" "$(profile_line)" >> "$profile"
    say "Appended to $profile."
    # This shell, so step 7's checks and the launch below see it too.
    PATH="$PREFIX:$PATH"
    say "Open a new terminal (or source $profile) for it to reach other shells."
}

# -- step 6 -----------------------------------------------------------------

# LiveATC fronts its listing with Cloudflare and refuses roughly three
# requests in four. kcgx handles that by caching the result for a week, so
# the start you actually do makes no request at all -- but the *first* start
# at an airport has no cache to read, tries eight times, and then opens the
# single configured feed. At the default airport that reads as "kcgx could
# only find KPDX tower", with no sign that eleven other feeds exist and
# nothing said about why.
#
# Filling the cache here is the fix, because here is where waiting is free.
# Nobody is looking at a page, so it can try twenty times.
#
# Not fatal: the feed list is a week-long cache, not a dependency, and
# LiveATC being unreachable at this moment is no reason to refuse to install
# the cockpit.
warm_feed_cache() {
    local icao
    step 6 "The LiveATC feed list"

    icao="$(uv run --project "$REPO" python -c '
from kcgx.state import current_icao
print(current_icao(known=lambda icao: True, warn=lambda line: None))
' 2>/dev/null || true)"
    if [ -z "$icao" ]; then
        warn "could not work out which airport to prefetch; skipping."
        return 0
    fi

    say "The cockpit opens every feed an airport publishes, which means asking"
    say "LiveATC for the list. That request is behind Cloudflare and is"
    say "refused about three times in four, so kcgx caches the answer for a"
    say "week -- but the first start at a new airport has nothing cached,"
    say "gives up after eight tries, and opens one feed instead of twelve."
    say ""
    say "Fetching it now avoids that: out here it can retry twenty times and"
    say "nobody is waiting. Takes a minute or two if it is being refused."
    say ""
    if ! confirm "Fetch the feed list for $icao now?" y; then
        say "Skipped. Run \`uv run --project '$REPO' kcgx-web --refresh-feeds\`"
        say "later, or just start kcgx and open FEEDS if it opens short."
        return 0
    fi

    uv run --project "$REPO" kcgx-web --refresh-feeds --icao "$icao" ||
        warn "could not cache the feed list; kcgx will try again when it starts."
}

# -- step 7 -----------------------------------------------------------------

VERIFY_FAILED=0
VERIFY_WARNED=0

ok()    { vrow "$1" "ok" "${2:-}"; }
bad()   { vrow "$1" "FAIL" "${2:-}"; VERIFY_FAILED=$((VERIFY_FAILED + 1)); }
meh()   { vrow "$1" "warn" "${2:-}"; VERIFY_WARNED=$((VERIFY_WARNED + 1)); }

# `reachable` only proves that something answered, and a 403 answers. Both
# providers refuse a request shape rather than going down, so the checks that
# matter send exactly what the app sends and insist on a 200. Reporting
# "adsb.lol reachable" over a radar stuck on ERR 403 is how this once went
# unnoticed for a fortnight.
serves() {  # $1=url $2=user-agent (optional)
    local code
    if [ -n "${2:-}" ]; then
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
            -A "$2" "$1" 2>/dev/null || true)"
    else
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 \
            "$1" 2>/dev/null || true)"
    fi
    [ "$code" = "200" ]
}

verify() {
    local version devices check
    step 7 "Checking it works"

    say "Running each moving part rather than checking that a file exists --"
    say "an install that reports success and then opens a broken page has"
    say "not succeeded."
    say ""

    version="$(version_of ffmpeg || true)"
    if [ -n "$version" ]; then
        ok "ffmpeg" "$version"
    else
        bad "ffmpeg" "not runnable; the cockpit decodes every feed with it"
    fi

    # The one check that proves step 2 and step 4 landed together: sounddevice
    # imports only if PortAudio is installed *and* the venv is synced.
    if uv run --project "$REPO" python -c 'import numpy, sounddevice, starlette, uvicorn, websockets' \
        >/dev/null 2>&1; then
        ok "python deps" "numpy, sounddevice, starlette, uvicorn, websockets"
    else
        bad "python deps" "import failed -- run: uv run --project '$REPO' python -c 'import sounddevice'"
    fi

    # Starts the real server, as the demo (no network, no audio, nothing
    # remembered), on a free port, and asks it for what a page asks for: its
    # health, the page, and the WebSocket's first frame; then stops it.
    # kcgx.selfcheck prints a row per check and a last line saying how it went.
    check="$(uv run --project "$REPO" python -m kcgx.selfcheck 2>&1 || true)"
    case "$check" in
        *"selfcheck ok"*)
            ok "server" "health, page and WebSocket answer"
            ;;
        *)
            bad "server" "would not serve the cockpit:"
            printf '%s\n' "$check" | sed -n '/FAIL/s/^/      /p'
            ;;
    esac

    # A machine with PortAudio but no output device is a real state (headless
    # boxes, containers, an unplugged dock) and not one setup can fix, so it
    # warns rather than blocking a cockpit whose radar and meters still work.
    devices="$(uv run --project "$REPO" python -c '
import sounddevice
print(sum(1 for d in sounddevice.query_devices() if d["max_output_channels"] > 0))
' 2>/dev/null || true)"
    case "$devices" in
        ''|0)   meh "audio output" "no output device; meters will run, nothing will be audible" ;;
        *)      ok  "audio output" "$devices device(s)" ;;
    esac

    if have_command kcgx; then
        ok "kcgx on PATH" "$(command -v kcgx)"
    else
        meh "kcgx on PATH" "start it as $REPO/bin/kcgx until it is (step 5)"
    fi

    if [ -z "${KCGX_SETUP_SKIP_NET:-}" ]; then
        # /play/*.pls is the path audio actually comes from, and it is not
        # the one behind the Cloudflare challenge -- so it is the one worth
        # checking. The listing at /search/ refuses most requests even when
        # everything is working; failing the install over it would be noise.
        if serves "https://www.liveatc.net/play/kpdx_twr.pls"; then
            ok "liveatc.net" "streaming reachable"
        else
            meh "liveatc.net" "refused /play/; feeds will not play"
        fi
        if serves "https://api.adsb.lol/v2/point/45.6/-122.6/5" "$ADSB_UA"; then
            ok "adsb.lol" "serving aircraft"
        else
            meh "adsb.lol" "refused the request; the radar will stay empty"
        fi
    fi

    say ""
    if [ "$VERIFY_FAILED" -gt 0 ]; then
        die "$VERIFY_FAILED check(s) failed. Fix those and run this again --
opening the cockpit now would only show you the same failure with fewer
words."
    fi
    if [ "$VERIFY_WARNED" -gt 0 ]; then
        say "$VERIFY_WARNED warning(s) above. Nothing there stops the cockpit"
        say "opening, but the parts named will not work until you deal with"
        say "them."
    else
        say "Everything checks out."
    fi
}

# -- entry ------------------------------------------------------------------

usage() {
    say "Usage: ./setup.sh [--check | --verify | --yes | --help]"
    say ""
    say "  (no arguments)  install everything kcgx needs and open the cockpit,"
    say "                  asking before each step that changes anything"
    say "  --check         print what you have and what is missing, then exit"
    say "  --verify        run the step 7 checks against this machine, then exit"
    say "  --yes           take every prompt's default (including appending to"
    say "                  your shell profile); for unattended installs"
    say "  --help, -h      this message"
}

# An unrecognised argument used to fall through to the full install and an
# exec into the cockpit -- so a typo, or a flag this script does not have,
# silently did the most consequential thing it can do.
if [ "$#" -gt 1 ]; then
    warn "unexpected argument: $2"
    usage >&2
    exit 2
fi

case "${1:-}" in
    "") ;;
    --yes)     KCGX_SETUP_YES=1 ;;
    --check)   preflight; say ""; exit 0 ;;
    --verify)  resolve_platform; verify; exit 0 ;;
    --help|-h) usage; exit 0 ;;
    *)
        warn "unknown argument: $1"
        usage >&2
        exit 2
        ;;
esac

say "kcgx setup"
say ""
say "$STEPS steps. Each one asks before it changes anything, and running this"
say "again is safe -- every step is idempotent."

preflight
install_packages
install_uv
sync_project
link_launcher
warm_feed_cache
verify

say ""
say "Setup complete. Opening the cockpit in your browser..."

if [ -n "${KCGX_SETUP_NO_LAUNCH:-}" ]; then
    exit 0
fi

# By absolute path, not by name: a PATH the user has not reloaded yet must
# not stop the cockpit opening on this first run. bin/kcgx starts the server
# in the background and opens the page.
exec "$REPO/bin/kcgx"
```

- [ ] **Step 4:** Suite: **1021 passed** (-13). Commit `feat(setup): seven steps; no tmux, no adsb-tui`.

---

### Task 6: `bin/kcgx` becomes the launcher's wrapper; tmux goes

`bin/kcgx` finds the repo through its symlink and runs `kcgx` with `uv run`. The tmux script's 61 tests, `kcgx.tmux.conf` and `bin/kcgx-no-radar` go with it, and so do the status pane's two tests of how tmux shows it: that its click and the `^b a` binding run the same popup, and that the pane height matches the launcher's.

- [ ] **Step 1: Remove.**

```bash
git rm -q \
    bin/kcgx-no-radar \
    kcgx.tmux.conf \
    tests/test_kcgx_launcher.py
```

- [ ] **Step 2: Tests.** Apply to `tests/test_launcher.py`:

```diff
diff --git a/tests/test_launcher.py b/tests/test_launcher.py
index ac96637..8631b76 100644
--- a/tests/test_launcher.py
+++ b/tests/test_launcher.py
@@ -260,3 +260,43 @@ def test_the_server_keeps_running_after_the_command_exits(port, tmp_path):
         if info:
             launcher.stop(info, timeout=5)
 
+
+# -- bin/kcgx ------------------------------------------------------------------------
+
+WRAPPER = Path(__file__).resolve().parent.parent / "bin" / "kcgx"
+
+
+def test_the_wrapper_finds_this_repo_through_a_symlink(tmp_path):
+    """setup.sh installs bin/kcgx as a symlink on PATH: the link must lead
+    back to this repo, not to the folder the link sits in. A uv that records
+    its arguments says exactly which project the wrapper named."""
+    link = tmp_path / "bin" / "kcgx"
+    link.parent.mkdir()
+    link.symlink_to(WRAPPER)
+    fake = tmp_path / "fake"
+    fake.mkdir()
+    record = tmp_path / "uv-args"
+    (fake / "uv").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}"\n')
+    (fake / "uv").chmod(0o755)
+    done = subprocess.run([str(link), "go", "KSEA"], capture_output=True, text=True, timeout=30, check=False,
+                          env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"})
+    assert done.returncode == 0, done.stderr
+    assert record.read_text().split("\n")[:6] == ["run", "--quiet", "--project", str(WRAPPER.parent.parent), "kcgx", "go"]
+
+
+def test_the_wrapper_runs_the_real_launcher(port):
+    done = subprocess.run([str(WRAPPER), "status"], capture_output=True, text=True, timeout=120, check=False,
+                          env={**os.environ, "KCGX_PORT": str(port)})
+    assert done.returncode == 3, done.stderr
+    assert done.stdout.strip() == "kcgx: not running."
+
+
+def test_the_wrapper_says_how_to_get_uv_when_it_is_missing(tmp_path):
+    bare = tmp_path / "bare"
+    bare.mkdir()
+    for tool in ("bash", "dirname", "readlink"):
+        found = subprocess.run(["bash", "-c", f"command -v {tool}"], capture_output=True, text=True, check=True).stdout.strip()
+        (bare / tool).symlink_to(found)
+    done = subprocess.run([str(WRAPPER)], capture_output=True, text=True, env={"PATH": str(bare)}, check=False)
+    assert done.returncode == 1
+    assert "uv not found" in done.stderr and "setup.sh" in done.stderr
```

- [ ] **Step 3: Tests.** Apply to `tests/test_status_app.py`:

```diff
diff --git a/tests/test_status_app.py b/tests/test_status_app.py
index dc990c8..1e89fe1 100644
--- a/tests/test_status_app.py
+++ b/tests/test_status_app.py
@@ -421,32 +421,6 @@ async def test_no_widget_is_wider_than_the_pane():
         assert too_wide == []
 
 
-def test_the_click_and_the_keybinding_run_the_same_popup():
-    """One spelling, or the hint text drifts from what the key does.
-
-    Token lists, not substrings. `token in bind` asked only whether each
-    character sequence appeared *somewhere* in the line, which every digit
-    and short flag does by accident: a 6x2 popup passed, because "6" and
-    "2" are inside "64" and "20", and so did running bare `kcgx` instead of
-    `kcgx go`, because "kcgx" is a prefix of it. Either one leaves the hint
-    reading "^b a" while the click does something else, or nothing usable
-    -- exactly what this test exists to rule out. shlex, not .split(), so
-    the quoted "kcgx go" stays one argument on both sides.
-    """
-    import shlex
-    from pathlib import Path
-
-    conf = (Path(__file__).resolve().parent.parent / "kcgx.tmux.conf").read_text()
-    bind = next(
-        line for line in conf.splitlines() if line.strip().startswith("bind a ")
-    )
-    tokens = shlex.split(bind)
-    assert tokens[:2] == ["bind", "a"], bind
-    assert tokens[2:] == list(PICKER_POPUP), (
-        f"kcgx.tmux.conf runs {tokens[2:]}, the click runs {list(PICKER_POPUP)}"
-    )
-
-
 def test_open_picker_shells_out_to_tmux():
     calls = []
     open_picker(run=lambda argv, **kw: calls.append(argv))
@@ -461,14 +435,9 @@ def test_open_picker_shells_out_to_tmux():
 # code is no longer on screen as text, and the pane needs four rows for the
 # banner where it used to need one line for the whole airport.
 
-from pathlib import Path            # noqa: E402
-import re                           # noqa: E402
-
 from kcgx import bigtext            # noqa: E402
 from kcgx.status import banner_text, detail_line   # noqa: E402
 
-REPO = Path(__file__).resolve().parents[1]
-
 
 @pytest.mark.asyncio
 async def test_the_code_is_drawn_as_block_capitals():
@@ -526,15 +495,3 @@ def test_an_unknown_code_leaves_the_detail_line_blank():
     """The banner still spells the code, so there is nothing to add."""
     assert detail_line(None, "ZZZZ", CONTENT_WIDTH, banner="drawn").strip() == ""
 
-
-def test_the_launcher_and_the_app_agree_about_the_pane_height():
-    """The height is declared twice -- here and in bin/kcgx -- and tmux
-    believes the launcher. If they drift, the pane the app formats for is
-    not the pane it gets and the banner clips with nothing to show for it.
-    """
-    source = (REPO / "bin" / "kcgx").read_text()
-    match = re.search(r'STATUS_ROWS="\$\{KCGX_STATUS_ROWS:-(\d+)\}"', source)
-    assert match, "could not find the launcher's STATUS_ROWS default"
-    assert int(match.group(1)) == STATUS_ROWS, (
-        f"bin/kcgx defaults to {match.group(1)} rows, status.py says {STATUS_ROWS}"
-    )
```

- [ ] **Step 4:** Run them. The wrapper tests fail: `bin/kcgx` is still the tmux script.

- [ ] **Step 5: Code.** Replace `bin/kcgx` entirely with:

```bash
#!/usr/bin/env bash
# kcgx: the cockpit's command, from anywhere.
#
#   kcgx                start the cockpit if it is not running, then open it
#   kcgx go [airport]   switch airport, or open the page's airport search
#   kcgx stop           stop the cockpit
#   kcgx status         say whether it is running, and where
#   kcgx --demo         the demo: synthetic feeds and traffic, no audio
#
# Everything is in kcgx.launcher; this only finds the repo and runs it with
# the repo's own Python, through uv. The intended install is a symlink in a
# directory on PATH (setup.sh step 5), so the link is resolved first.
# `readlink -f` is not portable to older macOS, hence the loop.

set -euo pipefail

self="${BASH_SOURCE[0]}"
while [ -L "$self" ]; do
    target="$(readlink "$self")"
    case "$target" in
        /*) self="$target" ;;
        *) self="$(cd -P "$(dirname "$self")" && pwd)/$target" ;;
    esac
done
REPO="$(cd -P "$(dirname "$self")/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
    printf 'kcgx: uv not found. Run %s/setup.sh, or install uv from https://docs.astral.sh/uv/\n' "$REPO" >&2
    exit 1
fi

exec uv run --quiet --project "$REPO" kcgx "$@"
```

- [ ] **Step 6: Code.** Apply to `src/kcgx/radar.py`:

```diff
diff --git a/src/kcgx/radar.py b/src/kcgx/radar.py
index 3076b6b..a2595a5 100644
--- a/src/kcgx/radar.py
+++ b/src/kcgx/radar.py
@@ -30,7 +30,7 @@ from dataclasses import dataclass, field
 from typing import Any
 
 URL = "https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{range}"
-# The same identifying string bin/kcgx and setup.sh send. KCGX_ADSB_UA
+# The same identifying string setup.sh's check sends. KCGX_ADSB_UA
 # replaces it; set empty, no User-Agent is sent (and adsb.lol refuses).
 DEFAULT_UA = "kcgx/0.1 (+https://github.com/mikElse/kcgx)"
 BACKOFF_CAP_SECS = 120
```

- [ ] **Step 7:** Suite: **961 passed** (-60). Commit `feat(launcher): bin/kcgx runs the launcher; the tmux cockpit goes`.

---

### Task 7: The page opens its search from a link

`kcgx go` with no airport, or a query naming several, opens `#airport` or `#airport=<query>`: CHANGE AIRPORT opens with the query typed, and the fragment is cleared.

- [ ] **Step 1: Tests.** Apply to `tests/test_page.py`:

```diff
diff --git a/tests/test_page.py b/tests/test_page.py
index 819fc83..228d8a9 100644
--- a/tests/test_page.py
+++ b/tests/test_page.py
@@ -332,3 +332,24 @@ def test_a_refused_radar_says_so_and_dims_its_lamp(page):
     )
     page.wait_for_function("document.getElementById('radar-poll').textContent.startsWith('ERR 429')")
     assert "warn" in page.get_attribute(".lamp:has(.lamp-label:text-is('RADAR'))", "class")
+
+
+# -- opened from kcgx go -------------------------------------------------------------
+
+
+def test_a_link_to_airport_opens_the_search(browser, server):
+    page = browser.new_page()
+    page.goto(server + "/#airport")
+    page.wait_for_selector("#airport-sheet[open]")
+    assert page.input_value("#airport-query") == ""
+    assert page.evaluate("location.hash") == ""
+    page.close()
+
+
+def test_a_link_with_a_query_opens_the_search_with_it_typed(browser, server):
+    page = browser.new_page()
+    page.goto(server + "/#airport=san%20francisco")
+    page.wait_for_selector("#airport-sheet[open]")
+    assert page.input_value("#airport-query") == "san francisco"
+    page.wait_for_selector("#airport-results .choice:has-text('KSFO')")
+    page.close()
```

- [ ] **Step 2:** Run them. The two link tests time out waiting for `#airport-sheet[open]`.

- [ ] **Step 3: Code.** Apply to `src/kcgx/web/static/js/main.js`:

```diff
diff --git a/src/kcgx/web/static/js/main.js b/src/kcgx/web/static/js/main.js
index c0258b0..432cdbb 100644
--- a/src/kcgx/web/static/js/main.js
+++ b/src/kcgx/web/static/js/main.js
@@ -67,6 +67,17 @@ $("next-palette").addEventListener("click", () => {
   send({ t: "prefs", palette: next });
 });
 $("recentre").addEventListener("click", () => radar.recentre());
+
+// `kcgx go` with no airport, or one that names several, opens the page at
+// #airport or #airport=<query>: the search opens with the query typed.
+function fromLink() {
+  const match = /^#airport(?:=(.*))?$/.exec(location.hash);
+  if (!match) return;
+  history.replaceState(null, "", location.pathname + location.search);
+  airportSheet.open(match[1] ? decodeURIComponent(match[1]) : "");
+}
+window.addEventListener("hashchange", fromLink);
+fromLink();
 window.kcgx = { radar, store }; // for the browser tests
 
 function banner() {
```

- [ ] **Step 4: Code.** Apply to `src/kcgx/web/static/js/sheets.js`:

```diff
diff --git a/src/kcgx/web/static/js/sheets.js b/src/kcgx/web/static/js/sheets.js
index 969bc92..83e07a5 100644
--- a/src/kcgx/web/static/js/sheets.js
+++ b/src/kcgx/web/static/js/sheets.js
@@ -74,11 +74,13 @@ export function mountAirportSheet({ sheet, query, results }, store, log) {
 
   query.addEventListener("input", search);
   return {
-    open() {
-      query.value = "";
+    // `text` prefills the search: `kcgx go seattle` opens the page this way.
+    open(text = "") {
+      query.value = text;
       results.replaceChildren();
-      sheet.showModal();
+      if (!sheet.open) sheet.showModal();
       query.focus();
+      if (text) search();
     },
   };
 }
```

- [ ] **Step 5:** Suite: **963 passed** (+2). Commit `feat(web): #airport opens the airport search`.

---

### Task 8: The terminal app and Textual go

The squelch Textual app, the status pane, the airport picker and the `squelch`, `kcgx-airport` and `kcgx-status` commands, with their tests. `tests/test_main.py` becomes `tests/test_runtime.py`: its 30 tests of feed loading and session building stay, because the server uses that code. The Textual import guards go, since Textual is no longer installed. Textual leaves `pyproject.toml` and `uv.lock`.

- [ ] **Step 1: Remove.**

```bash
git rm -q \
    src/kcgx/__main__.py \
    src/kcgx/bigtext.py \
    src/kcgx/picker.py \
    src/kcgx/status.py \
    src/squelch/__main__.py \
    src/squelch/app.py \
    src/squelch/config_view.py \
    src/squelch/radar_theme.py \
    src/squelch/rows.py \
    src/squelch/squelch.tcss \
    src/squelch/themes.py \
    tests/test_airport_picker.py \
    tests/test_app.py \
    tests/test_bigtext.py \
    tests/test_config_view.py \
    tests/test_feed_picker.py \
    tests/test_kcgx_airport_cli.py \
    tests/test_radar_theme.py \
    tests/test_rows.py \
    tests/test_status_app.py \
    tests/test_status_format.py \
    tests/test_themes.py \
    tests/test_web_imports.py
```

- [ ] **Step 2: Rename** (history follows):

```bash
git mv tests/test_main.py tests/test_runtime.py
```

  Then replace its content entirely with:

```python
"""squelch.runtime: discovering an airport's feeds, building sessions, and
filling the feed cache. Moved here from the terminal app's test_main.py when
the terminal app was retired in phase E; the server uses all of it."""

from __future__ import annotations

from squelch.config import Config
from squelch.feeds import (
    COLD_FETCH_ATTEMPTS,
    REFRESH_ATTEMPTS,
    Feed,
    read_cached_feeds,
)
from squelch.mixer import Mixer
from squelch.runtime import (
    build_sessions,
    load_feeds,
    refresh_feeds,
)
from squelch.session import FeedSession

FEEDS = [
    Feed(ident="kpdx3_twr", label="KPDX Tower (Both)"),
    Feed(ident="kpdx3_gnd", label="KPDX Ground"),
    Feed(ident="kpdx3_atis", label="KPDX ATIS"),
]


# -- arguments -------------------------------------------------------------


# -- feed discovery --------------------------------------------------------


def test_load_feeds_returns_everything_the_airport_publishes(tmp_path):
    warnings = []
    feeds = load_feeds(
        Config(), warn=warnings.append, fetch=lambda icao, **_: FEEDS, cache_dir=tmp_path
    )
    assert feeds == FEEDS
    assert warnings == []


def test_load_feeds_falls_back_to_the_configured_feed_when_discovery_fails(tmp_path):
    """An empty pane is worse than one known-good feed."""

    def boom(icao, **_):
        raise RuntimeError("network down")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=boom,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    assert warnings and "network down" in warnings[0]
    assert "kpdx3_twr" in warnings[0], "say what it opened instead"


def test_load_feeds_falls_back_when_the_airport_lists_nothing(tmp_path):
    warnings = []
    feeds = load_feeds(
        Config(feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=lambda i, **_: [],
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    assert warnings


# -- sessions --------------------------------------------------------------


class StubSession:
    def __init__(self, feed, events, *, muted=True, icao="",
                 activity_threshold=-40.0, channel=None):
        self.feed = feed
        self.events = events
        self.muted = muted
        self.icao = icao
        self.activity_threshold = activity_threshold
        self.channel = channel
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def build(feeds=FEEDS, config=None):
    return build_sessions(
        feeds,
        config or Config(icao="KPDX", feed="kpdx3_twr"),
        events=None,
        session_factory=StubSession,
    )


def test_one_session_is_built_per_feed():
    assert [s.feed.ident for s in build()] == [f.ident for f in FEEDS]


def test_exactly_one_feed_starts_unmuted():
    """Everything meters; one thing is audible."""
    sessions = build()
    unmuted = [s.feed.ident for s in sessions if not s.muted]
    assert unmuted == ["kpdx3_twr"]


def test_the_configured_feed_is_the_unmuted_one():
    sessions = build(config=Config(icao="KPDX", feed="kpdx3_atis"))
    assert [s.feed.ident for s in sessions if not s.muted] == ["kpdx3_atis"]


def test_an_unmatched_configured_feed_still_leaves_something_audible():
    """Opening entirely silent reads as broken."""
    sessions = build(config=Config(icao="KPDX", feed="does_not_exist"))
    assert sum(1 for s in sessions if not s.muted) == 1


def test_the_icao_is_passed_through_for_label_stripping():
    assert all(s.icao == "KPDX" for s in build())


def test_building_no_sessions_does_not_crash():
    assert build(feeds=[]) == []


# -- misc ------------------------------------------------------------------


# -- feed discovery, cached ------------------------------------------------
#
# LiveATC's listing page sits behind Cloudflare bot protection that refuses
# roughly three requests in four. A cache means a launch usually needs no
# request at all, and a launch that does can fall back to a stale list
# rather than to a single feed.


def test_a_fresh_cache_is_used_without_hitting_the_network(tmp_path):
    from squelch.feeds import write_cached_feeds

    write_cached_feeds("KPDX", FEEDS, directory=tmp_path)
    calls = []

    def fetch(icao, **_):
        calls.append(icao)
        raise AssertionError("must not fetch when the cache is fresh")

    feeds = load_feeds(
        Config(icao="KPDX"), warn=[].append, fetch=fetch, cache_dir=tmp_path
    )
    assert feeds == FEEDS
    assert calls == []


def test_a_successful_fetch_populates_the_cache(tmp_path):
    from squelch.feeds import read_cached_feeds

    load_feeds(
        Config(icao="KPDX"),
        warn=[].append,
        fetch=lambda icao, **_: FEEDS,
        cache_dir=tmp_path,
    )
    assert read_cached_feeds("KPDX", directory=tmp_path) == FEEDS


def test_a_stale_cache_beats_falling_back_to_one_feed(tmp_path):
    """The whole point of the app is the whole airport."""
    import os
    import time

    from squelch.feeds import cache_path, write_cached_feeds

    write_cached_feeds("KPDX", FEEDS, directory=tmp_path)
    path = cache_path("KPDX", directory=tmp_path)
    ancient = time.time() - (30 * 24 * 60 * 60)
    os.utime(path, (ancient, ancient))

    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert feeds == FEEDS, "a stale list is far better than a single feed"
    assert warnings and "cached" in warnings[0].lower()


def test_no_cache_and_a_blocked_fetch_still_opens_the_configured_feed(tmp_path):
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    assert warnings


# -- the picker's loader ---------------------------------------------------


def test_picker_refreshes_but_falls_back_to_the_cache(tmp_path):
    """Pressing `f` is an explicit refresh, so it tries the network first.

    But the listing is refused three times in four, and a picker that
    usually says "could not load feeds" is useless — the cache is a far
    better answer than an error.
    """
    from squelch.feeds import write_cached_feeds
    from squelch.runtime import picker_feeds

    write_cached_feeds("KPDX", FEEDS, directory=tmp_path)

    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    assert (
        picker_feeds(Config(icao="KPDX"), fetch=blocked, cache_dir=tmp_path) == FEEDS
    )


def test_picker_prefers_a_successful_refresh_and_recaches_it(tmp_path):
    from squelch.feeds import read_cached_feeds, write_cached_feeds
    from squelch.runtime import picker_feeds

    write_cached_feeds("KPDX", [Feed("old", "Old")], directory=tmp_path)
    fresh = picker_feeds(
        Config(icao="KPDX"), fetch=lambda icao, **_: FEEDS, cache_dir=tmp_path
    )
    assert fresh == FEEDS
    assert read_cached_feeds("KPDX", directory=tmp_path) == FEEDS


def test_picker_returns_empty_when_there_is_no_cache_and_no_network(tmp_path):
    """Empty is what makes the app say 'could not load feeds'."""
    from squelch.runtime import picker_feeds

    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    assert picker_feeds(Config(icao="KPDX"), fetch=blocked, cache_dir=tmp_path) == []


# -- switching airports ----------------------------------------------------
#
# The cockpit can now retarget squelch at any airport, so a feed lookup
# that fails at KORD must not quietly fall back to a KPDX feed. Audio from
# the wrong airport under a header reading KORD is worse than silence.


def test_a_failed_lookup_at_a_new_airport_opens_nothing(tmp_path):
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KORD", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert feeds == [], "kpdx3_twr is not a KORD feed"
    assert warnings and "KORD" in warnings[0]


def test_the_configured_feed_is_still_used_at_its_own_airport(tmp_path):
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]


def test_an_empty_icao_does_not_trust_any_feed_as_its_own(tmp_path):
    """`"anything".startswith("")` is True, so a blank icao must be

    excluded explicitly -- otherwise every configured feed would look like
    it belonged to the (nonexistent) airport, reopening the wrong-airport-
    audio hole this task exists to close. A hand-edited config file can
    reach this: `_checked` only validates that `icao` is a string, not
    that it's non-empty.
    """
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert feeds == []


def test_an_unreachable_listing_says_it_can_be_retried(tmp_path):
    def blocked(icao, **_):
        raise RuntimeError("HTTP 403")

    warnings = []
    load_feeds(
        Config(icao="KORD", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert "retry" in warnings[0].lower()


def test_an_airport_liveatc_does_not_cover_does_not_suggest_retrying(tmp_path):
    """Retrying a field with no feeds will never produce one."""
    from squelch.feeds import FeedError

    def empty(icao, **_):
        raise FeedError("no feeds found on page")

    warnings = []
    feeds = load_feeds(
        Config(icao="KBDN", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=empty,
        cache_dir=tmp_path,
    )
    assert feeds == []
    assert "no feeds" in warnings[0].lower()
    assert "retry" not in warnings[0].lower()


def test_a_page_with_no_feeds_falls_back_to_the_cache(tmp_path):
    """No feeds on a page that loaded is also what a markup change looks
    like -- LiveATC's 2026-10 one blanked a cached thirty-feed airport."""
    from squelch.feeds import FeedError, write_cached_feeds

    def empty(icao, **_):
        raise FeedError("no feeds found on page")

    write_cached_feeds("KORD", [Feed(ident="kord_twr", label="KORD Tower")],
                       directory=tmp_path)
    warnings = []
    feeds = load_feeds(
        Config(icao="KORD", feed="kord_twr"),
        warn=warnings.append,
        fetch=empty,
        cache_dir=tmp_path,
        ttl_seconds=0,  # stale, so the listing is asked for
    )
    assert [f.ident for f in feeds] == ["kord_twr"]
    assert "cached" in warnings[0].lower()


# -- which feed comes up audible ------------------------------------------


def test_a_tower_feed_is_preferred_when_nothing_matches_the_config():
    """Arriving somewhere new should land on the interesting channel."""
    feeds = [
        Feed(ident="kord_atis", label="KORD ATIS"),
        Feed(ident="kord_gnd", label="KORD Ground"),
        Feed(ident="kord_twr", label="KORD Tower"),
    ]
    sessions = build_sessions(
        feeds,
        Config(icao="KORD", feed="kpdx3_twr"),
        events=None,
        session_factory=StubSession,
    )
    assert [s.feed.ident for s in sessions if not s.muted] == ["kord_twr"]


# Pins the index-0 default and would catch preferred_index returning some
# other constant, but neither feed here contains "twr"/"tower", so this
# cannot detect the matching loop being deleted -- it is not evidence that
# tower-matching works; see test_a_tower_feed_is_preferred_when_nothing_
# matches_the_config for that.
def test_the_first_feed_is_used_when_there_is_no_tower():
    feeds = [
        Feed(ident="kord_atis", label="KORD ATIS"),
        Feed(ident="kord_gnd", label="KORD Ground"),
    ]
    sessions = build_sessions(
        feeds,
        Config(icao="KORD", feed="kpdx3_twr"),
        events=None,
        session_factory=StubSession,
    )
    assert [s.feed.ident for s in sessions if not s.muted] == ["kord_atis"]


# -- the mixer -------------------------------------------------------------


def test_every_session_gets_a_channel():
    mixer = Mixer()
    feeds = [Feed(ident="a_twr", label="A Tower"), Feed(ident="a_gnd", label="A Ground")]
    sessions = build_sessions(
        feeds, Config(feed="a_twr"), events=None, mixer=mixer,
        session_factory=FeedSession,
    )
    assert len(mixer._channels) == 2
    assert all(s._channel is not None for s in sessions)


def test_the_configured_feed_starts_audible_on_its_channel():
    mixer = Mixer()
    feeds = [Feed(ident="a_twr", label="A Tower"), Feed(ident="a_gnd", label="A Ground")]
    build_sessions(
        feeds, Config(feed="a_twr"), events=None, mixer=mixer,
        session_factory=FeedSession,
    )
    assert mixer._channels[0].muted is False
    assert mixer._channels[1].muted is True


# ---------------------------------------------------------------------------
# --refresh-feeds
#
# The cold-launch problem, moved somewhere it can be solved. LiveATC refuses
# roughly three requests in four, so squelch's eight attempts fail about 10%
# of the time -- and when they do, the pane opens on the single configured
# feed with nothing said about the other eleven. Raising the launch budget
# trades a wrong pane for a slow one. This runs where nobody is waiting.

def test_refresh_feeds_caches_what_it_finds(tmp_path):
    out = []
    code = refresh_feeds(
        Config(icao="KPDX"),
        out=out.append,
        fetch=lambda icao, **_: FEEDS,
        cache_dir=tmp_path,
    )
    assert code == 0
    assert read_cached_feeds("KPDX", directory=tmp_path) == FEEDS
    printed = "\n".join(out)
    for feed in FEEDS:
        assert feed.ident in printed, printed


def test_refresh_feeds_asks_for_more_attempts_than_a_launch_does(tmp_path):
    """The whole reason it exists. Eight attempts fail ~10% of the time at
    one-in-four; twenty fail ~0.3%, and the cost is a wall clock nobody is
    watching.
    """
    seen = {}

    def record(icao, **kwargs):
        seen.update(kwargs)
        return FEEDS

    refresh_feeds(
        Config(icao="KPDX"), out=lambda _: None, fetch=record, cache_dir=tmp_path
    )
    assert seen.get("attempts") == REFRESH_ATTEMPTS
    assert REFRESH_ATTEMPTS > COLD_FETCH_ATTEMPTS


def test_refresh_feeds_reports_a_refusal_without_caching_anything(tmp_path):
    def blocked(icao, **_):
        raise OSError("HTTP Error 403: Forbidden")

    out = []
    code = refresh_feeds(
        Config(icao="KPDX"), out=out.append, fetch=blocked, cache_dir=tmp_path
    )
    assert code != 0
    assert read_cached_feeds("KPDX", directory=tmp_path) is None
    printed = "\n".join(out).lower()
    assert "403" in printed, "the actual error is what tells you whose fault it is"
    assert "bot protection" in printed, "no hint that this is usually not local"


# ---------------------------------------------------------------------------

def test_the_fallback_to_one_feed_still_says_how_to_retry(tmp_path):
    """The case that actually happens on a first launch: default config,
    default airport, listing refused. It opened kpdx3_twr and said so, and
    that was the entire message -- one feed out of twelve, no reason given
    for the other eleven, and nothing to suggest the listing was worth
    asking for again.
    """
    def blocked(icao, **_):
        raise OSError("HTTP Error 403: Forbidden")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]
    message = " ".join(warnings)
    assert "kpdx3_twr" in message, message
    assert "press f to retry" in message, message
    assert "403" in message, message
```

- [ ] **Step 3: Tests.** Apply to `tests/conftest.py`:

```diff
diff --git a/tests/conftest.py b/tests/conftest.py
index 3030f4e..897d435 100644
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -29,7 +29,7 @@ def isolate_kcgx_state(tmp_path, monkeypatch):
     So all three levers are redirected, not one:
 
     - KCGX_STATE_PATH, which is what a test normally overrides, and what
-      reaches Python through a subprocess (bin/kcgx -> uv -> kcgx-airport);
+      reaches Python through a subprocess (the launcher's server, the self check);
     - kcgx.state.STATE_PATH, for anything in-process that ignores the env
       var -- the constant is bound at import, so patching HOME cannot
       reach it;
```

- [ ] **Step 4: Tests.** Apply to `tests/test_cockpit.py`:

```diff
diff --git a/tests/test_cockpit.py b/tests/test_cockpit.py
index 2ad347d..ad98155 100644
--- a/tests/test_cockpit.py
+++ b/tests/test_cockpit.py
@@ -9,9 +9,6 @@ the terminal UI is retired.
 
 from __future__ import annotations
 
-import subprocess
-import sys
-
 import pytest
 
 from squelch.activity import QUIET_SECONDS, SETTLE_ROUNDS
@@ -119,13 +116,6 @@ def ident(cockpit, index):
 # -- shape -----------------------------------------------------------------
 
 
-def test_importing_the_cockpit_does_not_import_textual():
-    """The point of the module. A stray import would make the browser
-    server pay for Textual, and would be the first step back to rules that
-    only a terminal app can reach."""
-    probe = "import sys, squelch.cockpit; sys.exit('textual' in sys.modules)"
-    result = subprocess.run([sys.executable, "-c", probe])
-    assert result.returncode == 0, "squelch.cockpit pulled in textual"
 
 
 def test_sessions_keep_the_order_given():
```

- [ ] **Step 5:** Run them. Nothing to see fail first: this task only removes.

- [ ] **Step 6: Code.** Apply to `pyproject.toml`:

```diff
diff --git a/pyproject.toml b/pyproject.toml
index d6c7bf2..d15a5ab 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,7 +1,7 @@
 [project]
 name = "squelch"
 version = "0.1.0"
-description = "Add your description here"
+description = "KCGX: live ATC audio and traffic around an airport, in your browser"
 readme = "README.md"
 authors = [
     { name = "Mike Else", email = "melse@jellyvision.com" }
@@ -11,17 +11,13 @@ dependencies = [
     "numpy>=2.5.1",
     "sounddevice>=0.5.5",
     "starlette>=1.9.0,<2",
-    "textual>=8.2.8,<9",
     "uvicorn>=0.54.0,<0.55",
     "websockets>=17.2,<18",
 ]
 
 [project.scripts]
-squelch = "squelch.__main__:main"
-kcgx-airport = "kcgx.__main__:main"
-kcgx-status = "kcgx.status:main"
-kcgx-web = "kcgx.server:main"
 kcgx = "kcgx.launcher:main"
+kcgx-web = "kcgx.server:main"
 
 [build-system]
 requires = ["uv_build>=0.11.14,<0.12.0"]
```

- [ ] **Step 7: Code.** Replace `src/kcgx/__init__.py` entirely with:

```python
"""The kcgx cockpit: a local web server for live ATC audio and traffic, and its launcher."""
```

- [ ] **Step 8: Code.** Apply to `src/kcgx/state.py`:

```diff
diff --git a/src/kcgx/state.py b/src/kcgx/state.py
index 33291b8..0d7740b 100644
--- a/src/kcgx/state.py
+++ b/src/kcgx/state.py
@@ -20,11 +20,11 @@ FALLBACK_ICAO = "KPDX"
 def default_path() -> Path:
     """Where the ICAO is remembered, unless a caller says otherwise.
 
-    KCGX_STATE_PATH relocates it. That seam exists so a test can drive the
-    *real* `kcgx-airport pick` -- through bin/kcgx, through uv, all the way
-    to a written record -- without any of it landing in the developer's own
-    ~/.local/state/kcgx. Read at call time, not import time, so a subprocess
-    inheriting the variable is enough.
+    KCGX_STATE_PATH relocates it, and with it everything kept beside it
+    (prefs.json, server.json, server.log). That seam exists so a test can
+    drive the real launcher and server, as subprocesses, without any of it
+    landing in the developer's own ~/.local/state/kcgx. Read at call time,
+    not import time, so a subprocess inheriting the variable is enough.
 
     The `path=` keyword on read_airport/write_airport stays the more
     specific override: an explicit argument always beats the environment.
```

- [ ] **Step 9: Code.** Apply to `src/squelch/cockpit.py`:

```diff
diff --git a/src/squelch/cockpit.py b/src/squelch/cockpit.py
index fd885c9..f91d0ac 100644
--- a/src/squelch/cockpit.py
+++ b/src/squelch/cockpit.py
@@ -2,17 +2,17 @@
 
 Which feeds hold one of LiveATC's streams, what solo restores, when the
 stack may reorder, what opening a feed does. All of it used to live inside
-SquelchApp, where only a running Textual app could reach it. The browser
-front end needs exactly the same rules, so they live here and both front
-ends drive them.
+the terminal app, where only a running Textual app could reach it; it was
+pulled out here in phase A so the browser front end could drive the same
+rules, and the terminal app was retired in phase E.
 
 Feeds are addressed by ident, never by position or by id(session): a
 browser cannot hold a Python object id, and a position is exactly what
 reordering changes.
 
-Single threaded by contract. Every call comes from one thread: Textual's
-event loop today, the server's asyncio loop later. Session threads never
-call in; their state changes still reach the UI through SessionEvents.
+Single threaded by contract. Every call comes from one thread: the server's
+asyncio loop. Session threads never call in; their state changes reach it
+through SessionEvents.
 """
 
 from __future__ import annotations
```

- [ ] **Step 10: Code.** `uv lock`. It removes Textual and what only Textual needed; nothing is added.

- [ ] **Step 11:** Suite: **650 passed** (-313). Commit `refactor: retire the terminal app and Textual`.

---

### Task 9: The README

Rewritten for the browser cockpit: install in seven steps, running it, the page, the radar and its data, configuration with the radar keys, and the history, keeping every section that is still true.

- [ ] **Step 1: Code.** Replace `README.md` entirely with:

````markdown
# kcgx

A cockpit for watching and listening to air traffic, in your browser,
named for Meigs Field — the Chicago lakefront strip that a generation of
flight-sim pilots took off from, bulldozed in the middle of the night in
2003.

It plays **every** ATC feed an airport publishes at once, one metered row
each, beside its own vector radar of the traffic around the field, on a
page drawn like the NORAD wall in *WarGames*. Everything runs on your own
machine: a small local server plays the audio and polls the radar, and the
page at `http://127.0.0.1:8473/` is the display and the controls.

```
kcgx              # start the cockpit if it is not running, and open it
kcgx go [query]   # switch airport, or open the page's airport search
kcgx stop         # shut it down
kcgx status       # is it running, and where
kcgx --demo       # the demo: synthetic feeds and traffic, no audio
```

[Install](#install) · [Running it](#running-it) · [The cockpit](#the-cockpit) ·
[The radar](#the-radar) · [Configuration](#configuration) ·
[Feed discovery](#feed-discovery-and-liveatcs-bot-protection) ·
[Buffering](#buffering) · [History](#history)

---

## Install

```bash
git clone https://github.com/mikElse/kcgx.git
cd kcgx
./setup.sh --check   # what you have and what you are missing; changes nothing
./setup.sh           # install the missing pieces, then open the cockpit
```

That is the whole install, on **macOS or Linux**, on any processor.
`setup.sh` works through seven steps, asks before each one that changes
anything, and finishes by starting the server and asking it for the page
and its live connection, to prove the cockpit will open. It is idempotent,
so the second run — the one you do when you think something went wrong —
ends where the first did.

### What it needs

| Tool | Why | Required? |
|---|---|---|
| [`uv`](https://docs.astral.sh/uv/) | runs everything, and supplies Python 3.14 itself | yes |
| [`ffmpeg`](https://ffmpeg.org/) | decodes each feed to PCM | yes |
| **PortAudio** | what `sounddevice` plays through | on Linux |
| a web browser | the cockpit is a page | yes |

`setup.sh` installs them: Homebrew on macOS, `apt`/`dnf`/`pacman` on Linux.
It never installs a package manager — if there is none it stops and prints
the packages instead.

**PortAudio is the one that bites on Linux.** The `sounddevice` wheel bundles
its own copy on macOS and ships none on Linux, so without `libportaudio2`
(or `portaudio`, depending on the distro) `import sounddevice` raises
`OSError: PortAudio library not found` and nothing can be heard. That is a
system library `uv sync` knows nothing about, which is why it is a step of
its own rather than a line in `pyproject.toml`.

**There is no Python to install.** `uv` supplies the 3.14 the project
requires: no system Python is read, no virtualenv is yours to create, and
there is no `pip install` step. See [A note on `python`](#a-note-on-python).

### The seven steps

| | Step | Asks before |
|---|---|---|
| 1 | What you have | — |
| 2 | System packages — `ffmpeg`, PortAudio | running your package manager |
| 3 | `uv`, and the Python it supplies | fetching the installer |
| 4 | Python dependencies (`uv sync`) | downloading anything |
| 5 | The launcher on your `PATH` | appending to your shell profile |
| 6 | The LiveATC feed list | fetching it |
| 7 | Checking it works | — |

```bash
./setup.sh --check     # step 1 alone, then exit
./setup.sh --verify    # step 7 alone, against this machine
./setup.sh --yes       # take every default; for unattended installs
./setup.sh --help
```

**Step 6 fills the feed cache** before the first start needs it. LiveATC
refuses roughly three requests in four, and a cold start that loses that
coin flip opens on a single feed — see
[when it opens on one feed](#when-it-opens-on-one-feed). Out here nobody is
waiting on a page, so it can retry twenty times instead of eight. It is not
fatal: the feed list is a week-long cache, not a dependency.

**Step 7 runs things rather than looking for files.** It runs `ffmpeg`,
imports `numpy`, `sounddevice`, `starlette`, `uvicorn` and `websockets`
through the project's own interpreter, starts the real server (as the
demo, on a free port) and asks it for its health, the page and the
WebSocket's first frame, counts audio output devices, and asks LiveATC and
adsb.lol for the exact thing the cockpit asks them for, insisting on a
`200` — "something answered" is not the same claim, and a `403` answers.

Anything it cannot fix but you can live without — no audio device, an
unreachable feed host, `kcgx` not yet on your `PATH` — is a warning and the
cockpit still opens. Anything that means a broken page stops the run, with
the command that fixes it.

### About your shell profile

**`setup.sh` will offer to edit it, and will not do so without asking.**
Step 5 links `bin/kcgx` into `~/.local/bin`, and if that is not on your
`PATH` it offers this line:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

It detects your shell (`zsh`, `bash`, `fish` — `fish` gets `fish_add_path`
instead), shows you the line, names the file, and asks. If you say yes it
backs the file up to `<profile>.kcgx-backup` first and marks what it added;
a second run recognises the marker and does not append again. If you say no
it carries on: the cockpit still starts as `<repo>/bin/kcgx`, just not as
plain `kcgx`. An unrecognised shell is told, not guessed at. `--yes` takes
this default along with all the others.

### Doing it by hand

```bash
# macOS
brew install ffmpeg
# Debian/Ubuntu — libportaudio2 is not optional, see above
sudo apt-get install ffmpeg libportaudio2
# Fedora (ffmpeg comes from RPM Fusion, not Fedora itself)
sudo dnf install ffmpeg portaudio
# Arch
sudo pacman -S --needed ffmpeg portaudio

curl -LsSf https://astral.sh/uv/install.sh | INSTALLER_NO_MODIFY_PATH=1 sh   # if you don't have uv

git clone https://github.com/mikElse/kcgx.git
cd kcgx
uv sync
mkdir -p ~/.local/bin && ln -s "$PWD/bin/kcgx" ~/.local/bin/kcgx
```

`INSTALLER_NO_MODIFY_PATH=1` stops uv's installer appending to `~/.zshrc`,
`~/.bash_profile` *and* `~/.profile` without asking. Link `bin/kcgx`
rather than copying it: it finds the repo through the symlink.
`./setup.sh --verify` checks a hand-built install and changes nothing.

### A note on `python`

`uv sync` reads `.python-version` (3.14), downloads that interpreter if you
do not have it, creates `.venv/` in the repo, and installs the dependencies
into it. Every command goes through `uv run`, which uses that interpreter
and **finds the project from your working directory**, so run them from
the repo or pass `--project`:

```bash
uv run pytest                           # the test suite
uv run --project ~/src/kcgx kcgx-web    # the server in the foreground, from anywhere
```

`bin/kcgx` always passes `--project` at its own repo root, which is why
`kcgx` works from any directory.

If [pyenv](https://github.com/pyenv/pyenv) shims come first on your `PATH`,
bare `python` fails *inside this repo* (`pyenv: version '3.14' is not
installed`). That is expected and harmless — `uv run` ignores pyenv
entirely, and `setup.sh` says so rather than changing your `PATH`.

## Running it

```bash
kcgx                    # start it (or find the running one) and open the page
kcgx --no-open          # start it without opening a browser
kcgx go KSEA            # switch airport: an exact ICAO
kcgx go seattle tacoma  # ...or any search that names one airport
kcgx go portland        # names several: opens the page's search with it typed
kcgx go                 # opens the page's airport search
kcgx status             # running at http://127.0.0.1:8473/  (KPDX)
kcgx stop               # stop the server, and the audio with it
kcgx --demo             # the demo: synthetic feeds and traffic, no audio
```

**The server runs in the background** and outlives the terminal you started
it from: close the tab and the audio keeps playing; run `kcgx` again and it
opens a new tab on the running server rather than starting another. It
writes where it is to `~/.local/state/kcgx/server.json` and logs to
`server.log` beside it. "Running" means its health check answers, never
that the file exists, so a file left by a crash or a reboot is replaced. The
port is `8473` (`KCGX_PORT` changes it); if something that is not kcgx has
it, the server takes a free one and records that.

**Stopping**: `kcgx stop`, or SHUT DOWN on the page (it asks first). Either
stops every feed and the server; the page says COCKPIT SHUT DOWN.

**The demo** (`kcgx --demo`, or `kcgx-web --demo`) runs synthetic feeds that
meter, chatter, reconnect and park like real ones, and a dozen aircraft on
fixed paths around whatever airport is open, one of which squawks 7600 for
a minute in every five. No network, no `ffmpeg`, no audio, and nothing is
remembered. It is what the tests run against, and a way to look at the page
anywhere.

**`kcgx-web`** is the server itself, in the foreground: `kcgx-web [--port
8473] [--icao KPDX] [--demo]`, Ctrl-C to stop. `kcgx-web --refresh-feeds
[--icao KSEA]` fills the feed cache and exits.

The server listens on `127.0.0.1` only and refuses requests that name
another host or come from another site's page.

## The cockpit

The page is a wall of framed screens with their names along the bottom:

| Screen | Shows |
|---|---|
| TRAFFIC | the radar (see [The radar](#the-radar)) |
| STATUS | the airport, Zulu and your local time, CHANGE AIRPORT |
| FREQUENCIES | every feed, with a trace of its level |
| TRACKS | the traffic table: callsign, type, altitude, speed, track, distance, squawk |
| TELETYPE | the message log, typed out |

Between them runs a **lamp bar**: one lamp per feed in its state colour
(cyan live, amber reconnecting, red orange offline, dark parked), then
RADAR, SERVER and AUDIO, then EMERG, which lights red orange with the code
when an aircraft in range squawks 7500, 7600 or 7700.

**Every action is a click.** There are no keyboard shortcuts and no labels
naming keys. The header has FEEDS (open any feed the airport publishes),
CONFIG (volume, palette, glow, display), PALETTE (cycles WOPR, AMBER,
MATRIX and MONO) and SHUT DOWN. Tab, Enter, Space and Escape work as they
do on any page.

**The feed stack.** An audible feed is an expanded row: its name, an
oscilloscope trace of its level, **M** (mute; lit when muted) and **S**
(solo; lit when soloed, press again to restore the mix), and its chatter
figure. A muted feed is one compact line, and clicking it unmutes it.
Every feed meters whether or not you can hear it.

Audible feeds sit at the top. Everything below is ordered by how busy it
has been over the last five minutes — the fraction of that window spent
above `activity_threshold_dbfs`. A new order is applied only once it has
held for fifteen seconds and the pointer has been off the stack for two,
because a row that moves while you reach for it silences the wrong
frequency. Muting and unmuting move the row at once.

**LiveATC streams seven feeds at once from one address.** Past that the
quietest muted feeds are parked (dark lamp, `‖`); unmute one and the
quietest muted feed gives up its place.

**The look is remembered.** Palette, glow (off, low, full) and display (off;
vector, with flicker and jitter; CRT, adding scanlines and rounded screens)
are kept by the server, so every tab and every start agrees. Reduced motion
in your system settings turns off every animation.

## The radar

Our own vector renderer, not a map library: line art on black, an
azimuthal equidistant projection centred on the airport, so the range
rings are true circles at 10, 20, 30 and 40 nm and distance reads straight
off the screen. The 40 nm ring fits the shorter side of the screen; the
longer side shows more map.

- **Aircraft** are chevrons along their track, labelled with callsign and
  altitude (`ASA412 6200`), with a trail that fades from the arrow back.
  Positions are dead reckoned between polls, an aircraft fades after 30 s
  without a position and drops at `radar_stale_secs`, and one with no
  callsign is `UNK1`, `UNK2` in order of first sighting. An emergency squawk
  turns it red orange and prints one line in the teletype.
- **Click an aircraft** (arrow, trail or label) to focus it: it turns pink
  with a ring and the rest dim. Its row in TRACKS does the same, and the
  table follows. Click again to restore them.
- **Drag** to pan, **scroll** to zoom (a quarter to six times), RECENTRE to
  come back. The title strip shows the pointer's bearing and distance from
  the field.
- **Place names** sit back at about 40% and come up under the pointer.
  Labels never overlap: one that does not fit is left off, its symbol kept.

The map is coastlines, lakes and rivers, country borders (green, dashed)
and state lines, cities, peaks, VORs (diamonds), other airports
(triangles), the home airport's runways in white inside its pink ring, and
in the US the class B, C and D airspace (red orange, dashed) and the Victor
airways (blue, dashed).

**Where the traffic comes from.** The server polls
[adsb.lol](https://adsb.lol) for the 40 nm around the field every 15 s and
sends the picture to every open tab, so two tabs do not double the rate.
Fifteen seconds is deliberate: adsb.lol says its [rate limits are dynamic
based on the environment load](https://github.com/adsblol/api), and from
one address 2 s and 5 s polling drew a steady stream of `429`s that
persisted through slower intervals once tripped. A config file can lengthen
the interval, never shorten it below 15 s. A refused poll keeps the last
picture and backs off (30 s, 60 s, then 120 s); the radar's corner says
`ERR 429, PICTURE 45S OLD` and the RADAR lamp turns amber.

adsb.lol refuses a request with no `User-Agent` (`403 User-Agent too
generic; include valid contact info.`), so the server sends
`kcgx/0.1 (+https://github.com/mikElse/kcgx)`. `KCGX_ADSB_UA` replaces it;
set it empty to send none. Put your own contact in if you fork this —
being reachable is what adsb.lol is asking for. (This was
`api.airplanes.live` until 2026-08-13, when it began refusing every
unauthenticated client.)

**The map is committed**, in `src/kcgx/data/geo.json.gz` (4.7 MB), so it
needs no network. The server sends each page the 200 nm around its airport.
All of it is public domain:

| Layer | Source |
|---|---|
| coastlines, lakes, rivers, borders, cities, peaks | [Natural Earth](https://www.naturalearthdata.com/) 10 m, v5.1.2 |
| navaids, airports, runways | [OurAirports](https://ourairports.com/data/) |
| class B, C and D airspace; Victor airways (US) | FAA [NASR 28 day subscription](https://www.faa.gov/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/) |

To rebuild it, download the FAA cycle's `class_airspace_shape_files.zip`
and `<DD_Mon_YYYY>_CSV.zip` into `.geo-sources/`, then:

```bash
uv run python tools/build_geodata.py
```

It fetches the rest itself into the same folder, and the same sources give
the same bytes. Without the FAA files the airspace and airway layers are
empty and it says so.

## Configuration

kcgx reads TOML from `~/.config/squelch/squelch.toml` (the name is the
audio engine's, from before the cockpit had a page). **Nothing creates it
for you**:

```bash
mkdir -p ~/.config/squelch
$EDITOR ~/.config/squelch/squelch.toml
```

Every key is optional. Unknown keys are ignored, so an older version can
read a newer file; known keys are type-checked at start, and a bad value
stops the server with a message naming the file and the key.

| Key | Default | Meaning |
|---|---|---|
| `icao` | `"KPDX"` | The airport to open when none has been chosen yet |
| `feed` | `"kpdx3_twr"` | The one feed left unmuted at start |
| `activity_threshold_dbfs` | `-40.0` | Level above which a feed counts as busy for the five-minute ranking. A decimal (`-40.0`, not `-40`). |
| `master_volume` | `1.0` | Output gain, 0.0 to 1.0; CONFIG's slider changes it while running |
| `buffer_seconds` | `4.0` | How far behind live a feed may fall before it drops audio; see [Buffering](#buffering) |
| `max_streams` | `7` | Streams held open at once; LiveATC's limit |
| `radar_refresh_secs` | `15` | Seconds between radar polls; never less than 15 |
| `radar_range_nm` | `40` | The circle asked of adsb.lol |
| `radar_stale_secs` | `60` | An aircraft not heard from for this long drops off |

The airport you choose is remembered in `~/.local/state/kcgx/airport`, and
the cockpit reopens there; `icao` is only the fallback. `ambient_enabled`
and `ambient_gain_db` are still read, for the mixer's ambient bus, which
the page has no control for.

## Feed discovery and LiveATC's bot protection

LiveATC fronts its airport listing page with Cloudflare bot protection.
Measured against the live site: a browser `User-Agent` does not help,
spacing requests out does not help, and roughly **one request in four is
allowed through anyway**. (The `/play/*.pls` endpoints the audio comes from
are not protected, which is why audio works regardless.)

kcgx therefore treats a 403 on the listing as a coin flip to re-flip, not
an answer, and caches the result for a week under `~/.cache/squelch/`. **A
normal start makes no request at all.** The retry budget depends on what a
failure costs:

| | Attempts | Failure rate | Because |
|---|---|---|---|
| Start, cache present | 5 | ~24% | costs a week-old list |
| Start, no cache | 8 | ~10% | costs an empty or one-feed stack |
| `kcgx-web --refresh-feeds` | 20 | ~0.3% | costs a wall clock nobody is watching |

When a refresh is due and every attempt is refused, it falls back to the
cached list, and only opens the single configured feed if there is no cache
at all. Each fallback says so in the teletype.

### When it opens on one feed

On a **first** start at an airport there is no cache, so a run of refusals
leaves nothing to open but `feed` from the config. At the default airport
that is `kpdx3_twr`, so the stack comes up showing KPDX Tower and nothing
else, as though that were all LiveATC had:

```
KPDX — could not reach LiveATC's listing (HTTP Error 403: Forbidden);
opening kpdx3_twr only; open FEEDS to retry
```

Open FEEDS: it fetches the listing afresh, and any feed it finds opens with
a click. Or fill the cache from outside, as setup's step 6 does:

```bash
uv run kcgx-web --refresh-feeds               # the remembered airport
uv run kcgx-web --refresh-feeds --icao KSEA   # any other
```

The cache is per ICAO, so a new airport is a cold one.

**kcgx never falls back to a different airport's audio.** The one-feed
fallback only fires when the configured feed's ident starts with the
airport's ICAO, so switching to KORD and losing the listing gives you an
empty stack with a message rather than Portland tower under a KORD header.

## What it does, and does not, do

- Opens every feed the airport publishes, each with its own `ffmpeg`
  process and ring buffer, into one stereo output.
- Starts with everything muted except the configured feed: you see the
  whole field at once, but hear one frequency until you choose otherwise.
- Isolates failures per feed: one that cannot resolve, or whose `ffmpeg`
  dies, goes offline on its own row and says why. The others keep going.
- Does **not** record, save, or redistribute any audio. Playback is local
  only, for personal listening, consistent with LiveATC.net's terms of use.
- Does **not** transcribe; see [History](#history).

## Cost

One `ffmpeg` process, one ring buffer, and one thread per feed — twelve of
each at KPDX, seven of them streaming — feeding **one** stereo output
stream. Bandwidth is roughly 16–32 kbps per feed; the CPU is mostly
`ffmpeg` decode plus one mixing callback every 16 ms. The server adds a
radar poll every 15 s and about 15 KB/s of levels to each open tab. The
page's radar redraws only what moves; the map is drawn once per airport,
pan or zoom.

## Audio shaping

**There is none.** What reaches the device is the decoded feed scaled by
master volume:

```
ffmpeg ─► ring buffer ─► sum ─► master volume ─► stereo
```

A per-feed noise gate and an upward compressor were **removed** on
2026-08-02. The gate never had anything to reject — LiveATC squelches at
the source, so 87% of blocks arrive at exactly −96 dBFS with a ~70 dB gap
up to speech — and a gain that moves continuously is the wrong thing to
have in the path when the complaint is choppy audio. A test asserts that a
mixer built from the shipped config returns output equal to input, sample
for sample.

## Buffering

This is the number that decides whether the audio sounds continuous, and it
is not obvious, so it is written down.

**LiveATC does not trickle.** 93% of `ffmpeg`'s reads arrive less than a
millisecond after the previous one, in bursts separated by gaps of up to
2.5 seconds, each carrying roughly 1.2 seconds of audio. The stream also
runs about 1.05× the device clock.

Each feed's ring buffer absorbs that. When a burst is larger than the
buffer, the *oldest* samples are dropped; the buffer then drains and pads
with silence until the next burst. So the capacity is a ceiling on **how far
behind live a feed may fall before it starts discarding audio**. Measured
against a live KPDX tower feed:

| `buffer_seconds` | audio kept | blocks reaching the device as silence | typical lag |
|---|---|---|---|
| 0.5 | 36% | 61% | 0.0 s |
| 2.0 | 90% | 6% | ~1.0 s |
| **4.0** | **95%** | **0.6%** | **~1.5 s** |
| 8.0 | 99% | 0% | ~5.0 s |

4 seconds is the knee: three times the typical burst, so overflow is rare,
while staying close enough to live to sit beside a radar showing the same
aircraft. Raise it on a lossy connection; expect dropouts below about 2.5.
`tests/test_mixer.py` replays a synthetic burst source matching the
measurement and fails if the capacity goes back under a burst.

## Known limitations

- Feeds are discovered once per airport; a feed that appears on LiveATC
  later needs FEEDS or a change of airport to show up.
- All feeds share one output device.
- Ranking is by level, not speech detection: a feed with a noisy carrier
  ranks above a quiet but busy one.
- Outside the US the map has no airspace and no airways.
- Natural Earth's towns are sparse: Portland, Vancouver, Salem and Longview,
  but not Gresham.
- The page is for one person on one machine: the server listens on
  `127.0.0.1` only, and has no accounts.

## Development

```bash
uv run pytest -q                                   # the suite
uv sync --group dev --group browser                # once, for the page's own tests
uv run playwright install chromium                 # once
```

Without the browser group, `tests/test_page.py` skips. Specs and plans for
everything here are in [`docs/`](docs/README.md).

## History

The cockpit began in a terminal: `squelch`, a Textual audio player in a
48-column pane, beside [`adsb-tui`](https://github.com/j4v3l/ADS-B_TUI) for
the radar and a status pane, arranged by a tmux script. It moved to the
browser in five phases in October 2026 (the plans are in
[`docs/`](docs/README.md)); the last one removed tmux, adsb-tui and the
terminal UI. The last commit with the terminal cockpit is tagged
`terminal-cockpit`:

```bash
git show terminal-cockpit:bin/kcgx
git checkout terminal-cockpit -- src/squelch/app.py   # to look, not to keep
```

Before that, squelch transcribed the audio live, using an ATC-fine-tuned
Whisper model
([`jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper`](https://huggingface.co/jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper))
with WebRTC VAD segmenting the audio into whole transmissions. That was
removed: it cost a 1.5 GB first-run download that blocked audio startup,
and CPU-bound inference running for the life of the session. It is tagged
`squelch-with-transcription`:

```bash
git show squelch-with-transcription:src/squelch/asr.py
```
````

- [ ] **Step 2:** Suite: **650 passed** (+0). Commit `docs: the README for the browser cockpit`.

---

### Task 10: By hand, on the Mac

- [ ] Stop the old cockpit: `kcgx stop` in `/Users/mikelse/kcgx` (the old
  tmux launcher, if `~/.local/bin/kcgx` still points there).
- [ ] In the worktree: `./setup.sh --check`, then `./setup.sh`. Seven steps,
  no tmux or adsb-tui anywhere; step 7 shows the `server` row ok; it ends by
  opening the cockpit in the browser. Close the tab: the audio keeps going.
- [ ] `bin/kcgx status`, `bin/kcgx` (a new tab on the same server),
  `bin/kcgx go KSEA`, `bin/kcgx go portland` (the search opens, typed),
  `bin/kcgx go` (the search opens, empty), `bin/kcgx stop`.
- [ ] `bin/kcgx --demo`, then stop it.
- [ ] `~/.local/bin/kcgx` points at `/Users/mikelse/kcgx/bin/kcgx` until the
  branch is merged; that is expected, and the merge is what moves it.

---

### Task 11: Documentation and the tag

- [ ] **Step 1:** Tag the terminal cockpit on `main`, before anything merges:
  `git -C /Users/mikelse/kcgx tag -a terminal-cockpit main -m "The terminal cockpit, before the browser replaced it"`.
- [ ] **Step 2:** In `docs/README.md`, phase E links this plan and is marked
  built, and the web cockpit section says all five phases are built.
- [ ] **Step 3:** Add an Execution record section to this plan. Commit `docs: phase E done`.

---

## Self-Review Notes

- **Dry run, 2026-10-22.** Every file above was built in a scratch copy of
  the branch, then laid down again as one commit per task from this plan's
  own content in a clean clone, with the full suite run after every task:
  the counts above are those runs (the sandbox skips one root-only setup
  test that runs on the Mac, added back here). The rebuilt tree is identical
  to the dry run. `setup.sh --verify` ran for real against the sandbox and
  failed exactly as it should on its missing PortAudio, then passed with a
  stand-in; `bin/kcgx` ran through a symlink from start to stop.
- **What the dry run caught.** Two status pane tests read `kcgx.tmux.conf` and the old `bin/kcgx`, so they go with tmux in Task 6 rather than with the status pane in Task 8. `squelch --refresh-feeds` lived in the
  terminal app, so setup's feed step would have broken with it: it moved to
  `kcgx-web`. Most of `tests/test_main.py` tests the runtime the server
  uses, not the terminal app, so deleting the file would have lost them.
  `kcgx go seattle` names three airports, not one. A test of a server that
  cannot start assumed an unknown remembered airport fails; it falls back
  to KPDX, which is right. The wrapper's symlink test passed with the link
  unresolved, because the sandbox's `uv` found the environment anyway: it
  now records the arguments a fake `uv` receives.
- **Revert checks, all run, each failing its named test:**

| Break | Test | Result |
|---|---|---|
| any health reply counts as kcgx | `test_launcher.py -k something_else_answering` | 1 failed |
| a stale record is kept | `test_launcher.py -k stale` | 1 failed |
| a taken port is reused | `test_launcher.py -k held_by` | 1 failed |
| a dead server is waited out | `test_launcher.py -k cannot_start` | 1 failed |
| `go` starts without remembering the airport | `test_launcher.py -k not_running_starts` | 1 failed |
| the query is left out of the link | `test_launcher.py -k several` | 1 failed |
| a second `kcgx` starts a second server | `test_launcher.py -k reuses` | 1 failed |
| `stop` leaves the record | `test_launcher.py -k forgets_it` | 1 failed |
| the symlink is not resolved | `test_launcher.py -k finds_this_repo` | 1 failed |
| health has no `app` | `test_server.py -k names_the_app` | 1 failed |
| `--refresh-feeds` needs ffmpeg | `test_server.py -k refresh_feeds_fills` | 1 failed |
| refresh asks for 8 attempts | `test_runtime.py -k more_attempts` | 1 failed |
| the WebSocket goes unchecked | `test_selfcheck.py -k working` | 1 failed |
| the check leaves its server running | `test_selfcheck.py -k stopped` | 1 failed |
| the page ignores the link | `test_page.py -k link` | 2 failed |
| the query is dropped | `test_page.py -k typed` | 1 failed |
| setup ignores the server check | `test_setup.py -k starts_the_server` | 1 failed |
| setup wants tmux again | `test_setup.py -k via_brew` | 1 failed |
| the feed list for the wrong airport | `test_setup.py -k warmed` | 1 failed |
| the User-Agent drifts | `test_setup.py -k user_agent` | 1 failed |
| nine steps | `test_setup.py -k numbered` | 1 failed |

- **Not revert-checked:** that the server outlives the terminal
  (`start_new_session`). A pytest run cannot close the terminal it runs in;
  `test_the_server_keeps_running_after_the_command_exits` shows it outlives
  the command, and Task 10 shows the rest.
- **Lint.** `ruff check` reports nothing new on any touched file.
- **Test count:** 1008 → 1009 (T1) → 1011 (T2) → 1030 (T3) → 1034 (T4) → 1021 (T5) → 961 (T6) → 963 (T7) → 650 (T8) → 650 (T9).
