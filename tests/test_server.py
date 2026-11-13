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
from station_fakes import AIRPORTS, Builder, listing, picker

from kcgx.prefs import DEFAULTS
from kcgx.server import HOST, LocalOnly, create_app, main, parse_args
from kcgx.station import Station
from squelch.config import Config
from squelch.mixer import Mixer

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
            remember_prefs=lambda prefs: None,
        )

    options = dict(level_hz=0, resort_seconds=0, radar=False)
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


def test_health_names_the_app_so_the_launcher_knows_its_own_server():
    asgi, _ = app()
    with client(asgi) as http:
        assert http.get("/api/health").json()["app"] == "kcgx"


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


def test_the_cockpit_page_is_served():
    asgi, _ = app()
    with client(asgi) as http:
        response = http.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "/static/js/main.js" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_the_debug_page_is_served():
    asgi, _ = app()
    with client(asgi) as http:
        response = http.get("/debug")
    assert response.status_code == 200
    assert "/ws" in response.text
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "path, kind",
    [
        ("/static/cockpit.css", "text/css"),
        ("/static/js/main.js", "javascript"),
        ("/static/fonts/share-tech-mono-latin-400-normal.woff2", "font/woff2"),
    ],
)
def test_static_files_are_served_uncached(path, kind):
    asgi, _ = app()
    with client(asgi) as http:
        response = http.get(path)
    assert response.status_code == 200
    assert kind in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-cache"


def test_static_files_stay_inside_their_folder():
    asgi, _ = app()
    with client(asgi) as http:
        assert http.get("/static/../server.py").status_code == 404
        assert http.get("/static/%2e%2e/server.py").status_code == 404


def test_every_module_the_page_imports_is_served():
    """A missing or misnamed module is a blank page with no error on the
    server: catch it here."""
    import re

    from kcgx.server import WEB_DIR

    js = WEB_DIR / "static" / "js"
    asgi, _ = app()
    with client(asgi) as http:
        modules = sorted(js.rglob("*.js"))
        assert js / "radar" / "index.js" in modules  # and the folders under js/ are looked in
        for module in modules:
            for name in re.findall(r'from "(\.\.?/[\w./]+)"', module.read_text()):
                target = (module.parent / name).resolve()
                assert target.is_file(), f"{module.relative_to(js)} imports a missing {name}"
                path = target.relative_to(js.resolve()).as_posix()
                assert http.get(f"/static/js/{path}").status_code == 200


def test_prefs_from_one_page_reach_another():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as one, http.websocket_connect(WS) as two:
        assert ready(one)["prefs"]["palette"] == "WOPR"
        ready(two)
        one.send_text(json.dumps({"t": "prefs", "palette": "AMBER"}))
        frame = until(two, lambda f: f["t"] == "prefs")
        assert frame == {"t": "prefs", **DEFAULTS, "palette": "AMBER"}


def test_a_bad_prefs_message_gets_an_error():
    asgi, _ = app()
    with client(asgi) as http, http.websocket_connect(WS) as ws:
        ready(ws)
        ws.send_text(json.dumps({"t": "prefs", "palette": "PLAID"}))
        assert until(ws, lambda f: f["t"] == "error")["text"].startswith("palette")


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


def test_demo_needs_no_ffmpeg_and_remembers_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
    served = {}

    def serve(asgi, port, on_server):
        served["app"] = asgi

    lines = []
    code = main(["--demo", "--icao", "KSEA"], which=lambda n: None, serve=serve, out=lines.append)
    assert code == 0
    assert lines[-1].endswith("(KSEA, demo)")
    with TestClient(served["app"], base_url=BASE) as http, http.websocket_connect(WS) as ws:
        assert ready(ws)["feeds"][0]["ident"] == "ksea_twr"
        ws.send_text(json.dumps({"t": "prefs", "palette": "MONO"}))
        until(ws, lambda f: f["t"] == "prefs")
    from kcgx.prefs import prefs_path
    from kcgx.state import default_path

    assert not prefs_path().exists()
    assert not default_path().exists()


def test_prefs_are_read_at_startup(monkeypatch, tmp_path):
    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
    from kcgx.prefs import prefs_path, write_prefs

    chosen = {"palette": "MATRIX", "glow_map": 0, "display": "VECTOR", "teletype": True, "box_items": ["HUD"]}
    write_prefs(chosen)
    assert prefs_path().exists()
    served = {}
    main(["--demo", "--icao", "KPDX"], which=lambda n: None,
         serve=lambda asgi, port, on_server: served.setdefault("app", asgi), out=lambda line: None)
    with TestClient(served["app"], base_url=BASE) as http, http.websocket_connect(WS) as ws:
        assert ready(ws)["prefs"] == {**DEFAULTS, **chosen}


# -- the radar -----------------------------------------------------------------


def test_the_map_for_an_airport_is_served():
    asgi, _ = app()
    with client(asgi) as http:
        response = http.get("/api/geo?icao=kpdx")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    geo = response.json()
    pdx = next(a for a in AIRPORTS if a.icao == "KPDX")
    assert geo["center"] == [round(pdx.lon * 10_000), round(pdx.lat * 10_000)]
    assert len(geo["runways"]) == 3
    assert geo["lines"]["coast"]


@pytest.mark.parametrize("query", ["?icao=ZZZZ", "", "?icao="])
def test_the_map_of_an_unknown_airport_is_a_404(query):
    asgi, _ = app()
    with client(asgi) as http:
        assert http.get(f"/api/geo{query}").status_code == 404


def radar_app(fetch, **options):
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
            remember_prefs=lambda prefs: None,
            radar_fetch=fetch,
        )

    return create_app(station_factory=factory, initial_icao="KPDX", level_hz=0, resort_seconds=0, **options)


def test_the_radar_polls_from_startup_and_every_page_sees_it():
    def fetch(lat, lon, range_nm):
        return {"ac": [{"hex": "abc", "flight": "ASA412", "lat": lat + 0.1, "lon": lon, "alt_baro": 5000}]}

    with client(radar_app(fetch)) as http, http.websocket_connect(WS) as ws:
        frame = until(ws, lambda f: f["t"] == "aircraft" and f["ac"])
    assert frame["ac"][0]["label"] == "ASA412" and frame["ok"]


def test_radar_off_means_no_polling():
    calls = []
    with client(radar_app(lambda *a: calls.append(a) or {"ac": []}, radar=False)) as http, http.websocket_connect(WS) as ws:
        ready(ws)
    assert calls == []


# -- --refresh-feeds -------------------------------------------------------------


def test_refresh_feeds_fills_the_cache_without_ffmpeg_or_a_server(monkeypatch, tmp_path):
    """setup.sh runs it, possibly before the audio path is complete: it has
    no business starting a mixer or a server to fill a JSON file."""
    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
    asked = []
    monkeypatch.setattr("squelch.runtime.refresh_feeds", lambda config, out: asked.append(config.icao) or 0)
    code = main(["--refresh-feeds", "--icao", "ksea"], which=lambda n: None, serve=pytest.fail,
                mixer_factory=pytest.fail, out=lambda line: None)
    assert code == 0 and asked == ["KSEA"]


def test_refresh_feeds_defaults_to_the_remembered_airport(monkeypatch, tmp_path):
    from kcgx.state import write_airport

    monkeypatch.setattr("squelch.config.DEFAULT_PATH", tmp_path / "missing.toml")
    write_airport("KORD")
    asked = []
    monkeypatch.setattr("squelch.runtime.refresh_feeds", lambda config, out: asked.append(config.icao) or 1)
    assert main(["--refresh-feeds"], which=lambda n: None, serve=pytest.fail, out=lambda line: None) == 1
    assert asked == ["KORD"]
