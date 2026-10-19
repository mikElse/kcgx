"""The local web server: HTTP for one-off things, one WebSocket for
everything live.

Binds to 127.0.0.1 and nowhere else, and answers only pages served from
itself (see LocalOnly). Audio plays on this machine through the mixer;
pages only ever receive state and levels.

    kcgx-web [--port 8473] [--icao KPDX]

Until phase C ships the real page, / serves a bare debug page that can
drive every control.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import shutil
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from kcgx import protocol
from kcgx.airports import find, load_airports, search
from kcgx.hub import Client, Hub
from kcgx.state import current_icao
from kcgx.station import Station, UnknownAirport

HOST = "127.0.0.1"
DEFAULT_PORT = 8473
LEVEL_HZ = 25
RESORT_SECONDS = 5.0
WEB_DIR = Path(__file__).parent / "web"

StationFactory = Callable[[Hub, Callable[..., None]], Station]


# -- answering local pages only ----------------------------------------------


def _hostname(host: str) -> str:
    return host.rsplit(":", 1)[0] if ":" in host else host


class LocalOnly:
    """Refuse any request that did not come from a page this server served.

    A server on 127.0.0.1 is reachable by every page the browser opens, so
    two checks run on every HTTP request and WebSocket handshake:

    - Host must name this machine, which defeats DNS rebinding.
    - Origin, when there is one, must be this server itself, which stops
      another site's page muting your feeds or shutting the cockpit down.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket") and not self._allowed(scope):
            if scope["type"] == "http":
                response = PlainTextResponse("kcgx answers its own pages only", status_code=403)
                await response(scope, receive, send)
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _allowed(scope) -> bool:
        headers = dict(scope.get("headers") or [])
        host = headers.get(b"host", b"").decode("latin-1")
        if _hostname(host) not in ("127.0.0.1", "localhost"):
            return False
        origin = headers.get(b"origin")
        return origin is None or origin.decode("latin-1") == f"http://{host}"


# -- the app -------------------------------------------------------------------


def create_app(
    *,
    station_factory: StationFactory,
    initial_icao: str,
    on_exit: Callable[[], None] = lambda: None,
    level_hz: float = LEVEL_HZ,
    resort_seconds: float = RESORT_SECONDS,
) -> Any:
    """The ASGI app. `station_factory(hub, post)` builds the Station once
    the event loop is running; `on_exit` is what POST /api/shutdown calls.
    A zero `level_hz` or `resort_seconds` turns that loop off (tests)."""

    @contextlib.asynccontextmanager
    async def lifespan(app):
        loop = asyncio.get_running_loop()

        def post(fn, *args):
            try:
                loop.call_soon_threadsafe(fn, *args)
            except RuntimeError:
                pass  # the loop has closed: shutting down, nobody to tell

        hub = Hub()
        station = station_factory(hub, post)
        app.state.hub, app.state.station = hub, station
        tasks = [asyncio.create_task(_guarded(hub, station.open(initial_icao)))]
        if level_hz:
            tasks.append(asyncio.create_task(_every(1 / level_hz, station.tick_levels)))
        if resort_seconds:
            tasks.append(asyncio.create_task(_every(resort_seconds, station.tick_resort)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            station.stop()

    async def page(request: Request):
        # no-cache: revalidate on every load, so an edited page shows on a
        # plain reload instead of after the browser's heuristic cache expires.
        return FileResponse(
            WEB_DIR / "debug.html",
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    async def health(request: Request):
        station = request.app.state.station
        return JSONResponse(
            {
                "ok": True,
                "version": _version(),
                "protocol": protocol.PROTOCOL,
                "icao": station.icao,
                "loading": station.loading,
            }
        )

    async def airports(request: Request):
        query = request.query_params.get("q", "")
        station = request.app.state.station
        return JSONResponse(
            [protocol.airport_view(a, a.icao) for a in search(query, station.airports)]
        )

    async def set_airport(request: Request):
        station = request.app.state.station
        try:
            body = await request.json()
            icao = body["icao"]
            if not isinstance(icao, str):
                raise TypeError
        except Exception:
            return JSONResponse({"error": "send {\"icao\": \"KPDX\"}"}, status_code=400)
        try:
            airport = station.check_airport(icao)
        except UnknownAirport:
            return JSONResponse({"error": f"no airport {icao!r}"}, status_code=404)
        # Not awaited: the listing fetch can take seconds of retries, and
        # every page hears about it over the WebSocket.
        asyncio.create_task(_guarded(station.hub, station.change_airport(airport.icao)))
        return JSONResponse({"icao": airport.icao}, status_code=202)

    async def available(request: Request):
        return JSONResponse(await request.app.state.station.available_feeds())

    async def shutdown(request: Request):
        on_exit()
        return JSONResponse({"ok": True}, status_code=202)

    async def live(websocket: WebSocket):
        hub, station = websocket.app.state.hub, websocket.app.state.station
        await websocket.accept()

        def evicted():
            asyncio.create_task(_close(websocket, 1013))

        client = Client(websocket.send_text, on_evict=evicted)
        # Queued before joining the hub, with no await between: the snapshot
        # is always the first frame, and nothing is broadcast in between.
        client.offer(protocol.encode(station.snapshot()))
        hub.add(client)
        pump = asyncio.create_task(client.pump())
        try:
            while True:
                text = await websocket.receive_text()
                try:
                    message = protocol.parse_client(text)
                except protocol.BadMessage as exc:
                    hub.send(client, protocol.error_frame(str(exc)))
                    continue
                station.handle(message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.remove(client)
            pump.cancel()

    app = Starlette(
        routes=[
            Route("/", page),
            Route("/api/health", health),
            Route("/api/airports", airports),
            Route("/api/airport", set_airport, methods=["POST"]),
            Route("/api/feeds/available", available),
            Route("/api/shutdown", shutdown, methods=["POST"]),
            WebSocketRoute("/ws", live),
        ],
        lifespan=lifespan,
    )
    return LocalOnly(app)


async def _every(seconds: float, fn: Callable[[], None]) -> None:
    """Call `fn` every `seconds` until cancelled. A tick that raises is
    dropped, not fatal: one bad frame must not stop the meters for good."""
    while True:
        await asyncio.sleep(seconds)
        try:
            fn()
        except Exception:
            pass


async def _guarded(hub: Hub, work) -> None:
    try:
        await work
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        hub.note(f"{type(exc).__name__}: {exc}")


async def _close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:
        pass


def _version() -> str:
    try:
        return version("squelch")
    except PackageNotFoundError:
        return "unknown"


# -- the command ---------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kcgx-web", description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("KCGX_PORT", DEFAULT_PORT)),
        help=f"port on {HOST} (default {DEFAULT_PORT}, or $KCGX_PORT)",
    )
    parser.add_argument("--icao", help="start at this airport instead of the remembered one")
    return parser.parse_args(argv)


def _serve(app: Any, port: int, on_server: Callable[[Any], None]) -> None:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning", ws="websockets-sansio")
    )
    on_server(server)
    server.run()


def main(
    argv: list[str] | None = None,
    *,
    which: Callable[[str], str | None] = shutil.which,
    serve: Callable[..., None] = _serve,
    mixer_factory: Callable[..., Any] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    from squelch.config import ConfigError, load_config
    from squelch.runtime import FFMPEG_MISSING

    args = parse_args(argv)
    if which("ffmpeg") is None:
        print(f"kcgx-web: {FFMPEG_MISSING}", file=sys.stderr)
        return 2
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"kcgx-web: {exc}", file=sys.stderr)
        return 2

    known = load_airports()
    icao = (args.icao or current_icao(known=lambda i: find(i, known) is not None, warn=out)).upper()
    if find(icao, known) is None:
        print(f"kcgx-web: no airport {icao!r} in the dataset", file=sys.stderr)
        return 2

    if mixer_factory is None:
        from squelch.mixer import Mixer as mixer_factory
    mixer = mixer_factory(
        volume=config.master_volume,
        ambient_enabled=config.ambient_enabled,
        buffer_seconds=config.buffer_seconds,
    )
    mixer.start()

    holder: dict[str, Any] = {}
    app = create_app(
        station_factory=lambda hub, post: Station(
            config, hub, post=post, airports=known, mixer=mixer
        ),
        initial_icao=icao,
        on_exit=lambda: setattr(holder["server"], "should_exit", True),
    )
    out(f"kcgx: http://{HOST}:{args.port}/  ({icao})")
    try:
        serve(app, args.port, lambda server: holder.__setitem__("server", server))
    finally:
        mixer.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
