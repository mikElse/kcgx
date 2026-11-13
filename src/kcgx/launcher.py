"""kcgx: the cockpit's one command (spec, The launcher).

    kcgx                  start the server if it is not running, then open the page
                          in its own window
    kcgx go [query]       point the cockpit at an airport
    kcgx stop             stop the server
    kcgx status           say whether it is running, and where
    kcgx --no-open        start without opening its own window
    kcgx --browser        open the page in the default browser instead
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

"Its own window" is KCGX.app (macos/), which setup.sh builds on a Mac. The
page is shown there when the app exists at `$KCGX_APP` (by default
`~/Applications/KCGX.app`), handed over as a `kcgx://show` link that carries
the port and the page's fragment and nothing else. Without the app, on
Linux, with `--browser`, or with `KCGX_BROWSER=1` in the environment, the
page opens in the default browser, as it does if the window will not open
or the page is one the app would refuse. `KCGX_BROWSER` is on when it is
set to anything but nothing or `0`: `false` and `no` are on as well.

`open` returning is all the launcher can see. An app that opens and then
shows no cockpit is not noticed here; `kcgx --browser` is the way round it.
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
OPEN_TIMEOUT_SECS = 15.0  # `open` hands the link over and returns; it does not wait for the window
# What KCGX.app takes in a link (macos/KCGXWindow.swift, Target). It refuses
# anything else, and `open` exits 0 all the same, so the launcher does not
# send it. tests/test_window.py holds these to the app itself.
WINDOW_PORTS = range(1024, 65536)
WINDOW_FRAGMENT_BYTES = 512
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


# -- where the page is shown ------------------------------------------------------


def app_path() -> Path:
    """KCGX.app, where setup.sh builds it (it reads KCGX_APP the same way)."""
    return Path(os.environ.get("KCGX_APP") or Path.home() / "Applications" / "KCGX.app")


def window_link(page: str) -> str | None:
    """The `kcgx://show` link for a page of this machine's cockpit, or None
    if the app would refuse it (a port under 1024, a fragment over 512 bytes).

    The app takes a port and a fragment (macos/KCGXWindow.swift refuses a
    link that says anything more), so those two are read back out of the
    page's address. The fragment is quoted whole: it is already quoted once
    as part of the page's address, and the app unquotes the link once.
    """
    parts = urllib.parse.urlsplit(page)
    try:
        port = parts.port
    except ValueError:
        return None
    if port not in WINDOW_PORTS or len(parts.fragment.encode()) > WINDOW_FRAGMENT_BYTES:
        return None
    link = f"kcgx://show?port={port}"
    if parts.fragment:
        link += f"&fragment={urllib.parse.quote(parts.fragment, safe='')}"
    return link


def window_opener(app: Path, *, run: Callable[..., Any] = subprocess.run, browser: Opener = webbrowser.open) -> Opener:
    """An opener that shows a page of this machine's cockpit in KCGX.app,
    or in the browser when the app would refuse the page or `open` fails."""

    def show(page: str) -> None:
        link = window_link(page)
        if link is None:
            why = f"{app} does not take this page (a port under 1024, or a search this long)"
        else:
            try:
                opened = run(["open", "-a", str(app), link], check=False, timeout=OPEN_TIMEOUT_SECS).returncode == 0
            except (OSError, subprocess.SubprocessError):
                opened = False
            if opened:
                return
            why = f"{app} would not open"
        print(f"kcgx: {why}; showing the page in the browser instead.", file=sys.stderr)
        browser(page)

    return show


def pick_opener(
    args: argparse.Namespace,
    *,
    platform: str | None = None,
    run: Callable[..., Any] = subprocess.run,
    browser: Opener = webbrowser.open,
) -> Opener:
    """What shows the page: KCGX.app on a Mac that has it, else the browser.
    A window for Linux would be chosen here.

    `KCGX_BROWSER` set to anything but nothing or `0` asks for the browser.
    "Has it" means the bundle's program is there, as macos/build.sh leaves
    it: a `KCGX_APP` that names some other folder is not handed to `open`,
    which would fail on it at every `kcgx`.
    """
    if getattr(args, "browser", False) or os.environ.get("KCGX_BROWSER", "") not in ("", "0"):
        return browser
    if (platform or sys.platform) != "darwin":
        return browser
    app = app_path()
    if not (app / "Contents" / "MacOS" / "KCGX").is_file():
        return browser
    return window_opener(app, run=run, browser=browser)


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


BROWSER_HELP = "open the page in the default browser, not in its own window"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kcgx",
        description="The KCGX cockpit: live ATC audio and traffic, in its own window.",
    )
    parser.add_argument("--no-open", action="store_true", help="do not open its own window")
    parser.add_argument("--browser", action="store_true", help=BROWSER_HELP)
    parser.add_argument("--demo", action="store_true", help="synthetic feeds and traffic, no audio")
    commands = parser.add_subparsers(dest="command")
    go = commands.add_parser("go", help="point the cockpit at an airport")
    go.add_argument("query", nargs="*", help="an ICAO, or text to search for")
    # Neither has a default of its own here, or `kcgx --no-open go` and
    # `kcgx --browser go` would be put back to False.
    go.add_argument("--no-open", action="store_true", default=argparse.SUPPRESS, help="do not open its own window")
    go.add_argument("--browser", action="store_true", default=argparse.SUPPRESS, help=BROWSER_HELP)
    go.add_argument("--open", action="store_true", help="open the page after switching")
    commands.add_parser("stop", help="stop the server")
    commands.add_parser("status", help="say whether it is running")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, opener: Opener | None = None) -> int:
    args = parse_args(argv)
    handler = {None: cmd_open, "go": cmd_go, "stop": cmd_stop, "status": cmd_status}[args.command]
    return handler(args, opener or pick_opener(args))


if __name__ == "__main__":
    sys.exit(main())
