"""The server end to end, through Starlette's test client.

The station underneath is real; its feeds, listing and mixer are the same
fakes test_station.py uses, so nothing here touches the network, ffmpeg or
an audio device.
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from kcgx.server import HOST, LocalOnly, create_app, main, parse_args
from kcgx.station import Station
from squelch.config import Config
from squelch.mixer import Mixer
from station_fakes import AIRPORTS, Builder, listing, picker

BASE = "http://127.0.0.1:8473"
# A full URL: the test client sends Host: testserver for a bare path.
WS = "ws://127.0.0.1:8473/ws"


def app(**kwargs):
    exits = []

    def factory(hub, post):
        return Station(
            Config(icao="KPDX", feed="kpdx3_twr"),
            hub,
            post=post,
            airports=AIRPORTS,
            mixer=Mixer(),
            feeds_loader=listing,
            sessions_builder=Builder(),
            picker_loader=picker,
            remember=lambda icao: None,
        )

    options = dict(level_hz=0, resort_seconds=0)
    options.update(kwargs)
    return create_app(
        station_factory=factory, initial_icao="KPDX", on_exit=lambda: exits.append(True), **options
    ), exits


def client(asgi, base=BASE):
    return TestClient(asgi, base_url=base)


def until(ws, predicate, limit=200):
    for _ in range(limit):
        frame = json.loads(ws.receive_text())
        if predicate(frame):
            return frame
    raise AssertionError("frame never arrived")


def loaded(frame):
    return frame["t"] == "snapshot" and not frame["loading"]


def ready(ws):
    """The snapshot with the feeds in it: the first frame, or a later one if
    the page connected while the airport was still loading."""
    first = json.loads(ws.receive_text())
    assert first["t"] == "snapshot", "the first frame must be a snapshot"
    return first if not first["loading"] else until(ws, loaded)


# -- answering local pages only ----------------------------------------------


def test_health_answers_once_up():
    asgi, _ = app()
    with client(asgi) as http:
        body = http.get("/api/health").json()
    assert body["ok"] is True
    assert body["icao"] == "KPDX"
    assert body["protocol"] == 1


@pytest.mark.parametrize("base", ["http://evil.example:8473", "http://192.168.1.20:8473"])
def test_a_request_naming_another_host_is_refused(base):
    asgi, _ = app()
    with client(asgi, base) as http:
        assert http.get("/api/health").status_code == 403


def test_localhost_is_this_machine_too():
    asgi, _ = app()
    with client(asgi, "http://localhost:8473") as http:
        assert http.get("/api/health").status_code == 200


def test_a_request_from_another_sites_page_is_refused():
    asgi, exits = app()
    with client(asgi) as http:
        response = http.post("/api/shutdown", headers={"origin": "http://evil.example"})
    assert response.status_code == 403
    assert exits == [], "a foreign page must not be able to shut the cockpit down"


def test_a_request_from_our_own_page_is_allowed():
    asgi, _ = app()
    with client(asgi) as http:
        assert http.get("/api/health", headers={"origin": BASE}).status_code == 200


def test_a_websocket_from_another_sites_page_is_refused():
    asgi, _ = app()
    with client(asgi) as http:
        with pytest.raises(WebSocketDisconnect):
            with http.websocket_connect(WS, headers={"origin": "http://evil.example"}) as ws:
                ws.receive_text()


def test_a_websocket_naming_another_host_is_refused():
    asgi, _ = app()
    with client(asgi) as http:
        with pytest.raises(WebSocketDisconnect):
            with http.websocket_connect("/ws") as ws:  # Host: testserver
                ws.receive_text()


def test_the_server_binds_to_this_machine_only():
    assert HOST == "127.0.0.1"


def test_the_guard_wraps_the_whole_app():
    asgi, _ = app()
    assert isinstance(asgi, LocalOnly)


# -- the WebSocket -------------------------------------------------------------


def test_the_first_frame_is_a_snapshot():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        frame = ready(ws)
        assert [f["ident"] for f in frame["feeds"]] == ["kpdx3_twr", "kpdx3_gnd", "kpdx3_atis"]


def test_a_mute_from_one_page_reaches_another():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as a, http.websocket_connect(WS) as b:
        ready(a)
        ready(b)
        a.send_text(json.dumps({"t": "mute", "ident": "kpdx3_gnd"}))
        order = until(b, lambda f: f["t"] == "order")
        assert order["idents"] == ["kpdx3_twr", "kpdx3_gnd", "kpdx3_atis"]


def test_a_bad_message_gets_an_error_and_the_connection_stays():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ws.send_text("not json")
        error = until(ws, lambda f: f["t"] == "error")
        assert error["text"] == "not JSON"
        ws.send_text(json.dumps({"t": "volume", "value": 0.5}))
        assert until(ws, lambda f: f["t"] == "volume")["value"] == 0.5


def test_levels_stream_while_a_page_is_open():
    asgi, _ = app(level_hz=50)
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ready(ws)
        levels = until(ws, lambda f: f["t"] == "levels")
        assert set(levels["v"]) == {"kpdx3_twr", "kpdx3_gnd", "kpdx3_atis"}


# -- HTTP ----------------------------------------------------------------------


def test_the_debug_page_is_served():
    asgi, _ = app()
    with client(asgi) as http:
        response = http.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/ws" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_airport_search_uses_the_dataset():
    asgi, _ = app()
    with client(asgi) as http:
        results = http.get("/api/airports", params={"q": "portland or"}).json()
    assert results[0]["icao"] == "KPDX"


def test_changing_airport_reaches_every_page():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ready(ws)
        assert http.post("/api/airport", json={"icao": "ksea"}).json() == {"icao": "KSEA"}
        frame = until(ws, lambda f: loaded(f) and f["airport"]["icao"] == "KSEA")
        assert [f["ident"] for f in frame["feeds"]] == ["ksea_twr", "ksea_gnd"]


def test_an_unknown_airport_is_a_404():
    asgi, _ = app()
    with client(asgi) as http:
        response = http.post("/api/airport", json={"icao": "ZZZZ"})
    assert response.status_code == 404


@pytest.mark.parametrize("body", [{}, {"icao": 7}, [1]])
def test_a_malformed_airport_request_is_a_400(body):
    asgi, _ = app()
    with client(asgi) as http:
        assert http.post("/api/airport", json=body).status_code == 400


def test_the_feed_picker_list_says_which_are_open():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ready(ws)
        listed = http.get("/api/feeds/available").json()
    assert {"ident": "kpdx_del", "label": "Delivery", "open": False} in listed


def test_shutdown_asks_the_server_to_exit():
    asgi, exits = app()
    with client(asgi) as http:
        assert http.post("/api/shutdown").status_code == 202
    assert exits == [True]


# -- the command ---------------------------------------------------------------


class FakeMixer:
    failed = False
    volume = 1.0

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def clear_channels(self):
        pass


def test_the_port_defaults_to_8473_and_follows_the_environment(monkeypatch):
    monkeypatch.delenv("KCGX_PORT", raising=False)
    assert parse_args([]).port == 8473
    monkeypatch.setenv("KCGX_PORT", "9000")
    assert parse_args([]).port == 9000


def test_no_ffmpeg_is_refused_before_anything_starts(capsys):
    assert main([], which=lambda name: None, serve=pytest.fail) == 2
    assert "ffmpeg" in capsys.readouterr().err


def test_an_unknown_airport_is_refused_before_anything_starts(capsys):
    code = main(["--icao", "ZZZZ"], which=lambda n: "/usr/bin/ffmpeg", serve=pytest.fail)
    assert code == 2
    assert "ZZZZ" in capsys.readouterr().err


def test_the_command_serves_and_closes_the_mixer_afterwards(monkeypatch, tmp_path):
    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
    served = {}
    mixers = []

    def factory(**kwargs):
        mixers.append(FakeMixer(**kwargs))
        return mixers[-1]

    def serve(asgi, port, on_server):
        served["port"] = port
        served["app"] = asgi

    code = main(
        ["--icao", "kpdx", "--port", "9100"],
        which=lambda n: "/usr/bin/ffmpeg",
        serve=serve,
        mixer_factory=factory,
        out=lambda line: None,
    )
    assert code == 0
    assert served["port"] == 9100
    assert isinstance(served["app"], LocalOnly)
    assert mixers[0].started and mixers[0].stopped
