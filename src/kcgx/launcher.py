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
