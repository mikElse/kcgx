"""The radar's poller and picture (kcgx.radar), with no network."""

from __future__ import annotations

import asyncio
import io
import threading
import urllib.error

import pytest

from kcgx import radar as radar_module
from kcgx.radar import Radar, RadarRefused, compass, distance_bearing, fetch_adsb_lol

PDX = (45.5887, -122.5975)


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def plane(hex_="a1b2c3", **fields):
    base = {"hex": hex_, "flight": "ASA412  ", "t": "B39M", "alt_baro": 6200, "gs": 250.4,
            "track": 270.2, "lat": 45.6, "lon": -122.3, "squawk": "4512", "seen_pos": 1.0}
    base.update(fields)
    return base


def make(fetch=None, **kwargs):
    frames, notes = [], []
    clock = kwargs.pop("clock", Clock())
    radar = Radar(on_frame=frames.append, on_note=notes.append, fetch=fetch or (lambda *a: {"ac": []}),
                  clock=clock, **kwargs)
    radar.retarget(*PDX)
    frames.clear()
    return radar, frames, notes, clock


# -- the picture -------------------------------------------------------------


def test_a_poll_becomes_a_frame_of_aircraft():
    radar, *_ = make()
    radar.merge({"ac": [plane()]})
    ac = radar.frame()["ac"][0]
    assert ac["label"] == "ASA412" and ac["type"] == "B39M"
    assert ac["alt"] == 6200 and ac["gs"] == 250 and ac["trk"] == 270 and ac["sq"] == "4512"
    assert ac["age"] == 1.0
    assert 10 < ac["dist"] < 15 and ac["brg"] in range(70, 90)


def test_on_the_ground_is_gnd():
    radar, *_ = make()
    radar.merge({"ac": [plane(alt_baro="ground")]})
    assert radar.frame()["ac"][0]["alt"] == "GND"


def test_aircraft_with_no_callsign_are_numbered_in_order_of_first_sighting():
    radar, *_ = make()
    radar.merge({"ac": [plane("b", flight=None), plane("a", flight="  ")]})
    radar.merge({"ac": [plane("c", flight=""), plane("a", flight="  "), plane("b", flight=None)]})
    labels = {ac["hex"]: ac["label"] for ac in radar.frame()["ac"]}
    assert labels == {"a": "UNK2", "b": "UNK1", "c": "UNK3"}


def test_rows_without_a_position_or_hex_are_skipped():
    radar, *_ = make()
    radar.merge({"ac": [plane(lat=None), plane(hex=""), plane("ok"), plane("nan", lon=float("nan"))]})
    assert [ac["hex"] for ac in radar.frame()["ac"]] == ["ok"]


def test_an_aircraft_not_heard_from_for_the_stale_time_drops_out():
    radar, _, _, clock = make(stale_secs=60)
    radar.merge({"ac": [plane("old", seen_pos=0.0)]})
    clock.now += 59
    radar.merge({"ac": [plane("new", seen_pos=0.0)]})
    assert {ac["hex"] for ac in radar.frame()["ac"]} == {"old", "new"}
    clock.now += 2
    radar.merge({"ac": []})
    assert {ac["hex"] for ac in radar.frame()["ac"]} == {"new"}


def test_an_airport_change_forgets_everything_and_tells_pages():
    radar, frames, _, _ = make()
    radar.merge({"ac": [plane("a", flight=None)]})
    radar.retarget(47.45, -122.31)
    assert radar.tracks == {} and frames[-1]["ac"] == [] and frames[-1]["age"] is None
    radar.merge({"ac": [plane("z", flight=None)]})
    assert radar.frame()["ac"][0]["label"] == "UNK1"


# -- emergencies -------------------------------------------------------------


def test_an_emergency_squawk_is_logged_once_and_again_when_it_clears():
    radar, _, notes, _ = make()
    radar.merge({"ac": [plane("e", flight="N52RT", squawk="7600", lat=45.9, lon=-123.0)]})
    radar.merge({"ac": [plane("e", flight="N52RT", squawk="7600", lat=45.9, lon=-123.0)]})
    # 0.311 deg north (18.7 nm) and 0.403 deg west (16.9 nm at 45.7 N): 25.2 nm NW
    assert notes == ["N52RT squawking 7600 (radio failure), 25 nm NW"]
    radar.merge({"ac": [plane("e", flight="N52RT", squawk="1200", lat=45.9, lon=-123.0)]})
    assert notes[-1] == "N52RT no longer squawking 7600"
    assert len(notes) == 2


def test_a_new_code_on_the_same_aircraft_is_a_new_line():
    radar, _, notes, _ = make()
    radar.merge({"ac": [plane("e", squawk="7600")]})
    radar.merge({"ac": [plane("e", squawk="7700")]})
    assert [n.split(" (")[0] for n in notes] == ["ASA412 squawking 7600", "ASA412 squawking 7700"]


def test_an_emergency_that_drops_out_of_range_is_cleared():
    radar, _, notes, clock = make(stale_secs=60)
    radar.merge({"ac": [plane("e", squawk="7500", seen_pos=0.0)]})
    clock.now += 61
    radar.merge({"ac": []})
    assert notes[-1] == "E no longer squawking 7500"


# -- polling and backing off ---------------------------------------------------


async def test_a_good_poll_sends_a_frame_with_its_age():
    calls = []

    def fetch(lat, lon, range_nm):
        calls.append((lat, lon, range_nm))
        return {"ac": [plane()]}

    radar, frames, *_ = make(fetch)
    await radar.poll()
    assert calls == [(PDX[0], PDX[1], 40)]
    assert frames[-1]["ok"] and frames[-1]["age"] == 0 and len(frames[-1]["ac"]) == 1


async def test_a_refused_poll_keeps_the_last_picture_and_backs_off():
    answers = [{"ac": [plane()]}, RadarRefused("ERR 429"), RadarRefused("ERR 429"), RadarRefused("ERR 403")]

    def fetch(*args):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    radar, frames, _, clock = make(fetch, refresh_secs=15)
    await radar.poll()
    assert radar.delay() == 15
    delays = []
    for _ in range(3):
        clock.now += 5
        await radar.poll()
        delays.append(radar.delay())
    assert delays == [30, 60, 120]
    last = frames[-1]
    assert not last["ok"] and last["error"] == "ERR 403"
    assert len(last["ac"]) == 1 and last["age"] == 15


async def test_the_backoff_is_capped_and_reset_by_a_success():
    answers = [RadarRefused("NO CONNECTION")] * 6 + [{"ac": []}]

    def fetch(*args):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    radar, *_ = make(fetch)
    for _ in range(6):
        await radar.poll()
    assert radar.delay() == 120
    await radar.poll()
    assert radar.delay() == 15 and radar.error == ""


def test_a_config_cannot_poll_faster_than_adsb_lol_asks():
    radar, *_ = make(refresh_secs=5)
    assert radar.delay() == 15
    radar.refresh_secs = 30
    assert radar.delay() == 30


async def test_a_reply_for_the_previous_airport_is_thrown_away():
    started, release = threading.Event(), threading.Event()

    def fetch(*args):
        started.set()
        release.wait(5)
        return {"ac": [plane()]}

    radar, frames, _, _ = make(fetch)
    task = asyncio.create_task(radar.poll())
    await asyncio.to_thread(started.wait, 5)
    radar.retarget(47.45, -122.31)
    release.set()
    await task
    assert radar.tracks == {} and frames[-1]["ac"] == []


async def test_run_polls_again_at_once_after_a_retarget():
    polled = []
    radar, *_ = make(lambda lat, lon, r: polled.append(lat) or {"ac": []})
    task = asyncio.create_task(radar.run())
    for _ in range(100):
        if polled:
            break
        await asyncio.sleep(0.01)
    radar.retarget(47.45, -122.31)
    for _ in range(100):
        if len(polled) > 1:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert polled[:2] == [PDX[0], 47.45]


# -- the real fetch, with urllib stood in for -------------------------------------


class Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_fetch_identifies_itself_and_asks_for_the_point(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["url"], seen["ua"], seen["timeout"] = request.full_url, request.get_header("User-agent"), timeout
        return Reply(b'{"ac": []}')

    monkeypatch.delenv("KCGX_ADSB_UA", raising=False)
    monkeypatch.setattr(radar_module.urllib.request, "urlopen", urlopen)
    assert fetch_adsb_lol(45.5887, -122.5975, 40) == {"ac": []}
    assert seen["url"] == "https://api.adsb.lol/v2/point/45.5887/-122.5975/40"
    assert seen["ua"] == radar_module.DEFAULT_UA and seen["timeout"] == 10


def test_an_empty_user_agent_sends_none(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["ua"] = request.get_header("User-agent")
        return Reply(b"{}")

    monkeypatch.setenv("KCGX_ADSB_UA", "")
    monkeypatch.setattr(radar_module.urllib.request, "urlopen", urlopen)
    fetch_adsb_lol(1, 2, 40)
    assert seen["ua"] is None


@pytest.mark.parametrize(
    "error, label",
    [
        (urllib.error.HTTPError("u", 429, "Too Many", {}, None), "ERR 429"),
        (urllib.error.HTTPError("u", 403, "Forbidden", {}, None), "ERR 403"),
        (urllib.error.URLError("no route"), "NO CONNECTION"),
        (TimeoutError(), "NO CONNECTION"),
    ],
)
def test_refusals_are_named_for_the_page(monkeypatch, error, label):
    def urlopen(request, timeout):
        raise error

    monkeypatch.setattr(radar_module.urllib.request, "urlopen", urlopen)
    with pytest.raises(RadarRefused) as caught:
        fetch_adsb_lol(1, 2, 40)
    assert caught.value.label == label


def test_a_reply_that_is_not_json_is_a_bad_reply(monkeypatch):
    monkeypatch.setattr(radar_module.urllib.request, "urlopen", lambda request, timeout: Reply(b"<html>"))
    with pytest.raises(RadarRefused) as caught:
        fetch_adsb_lol(1, 2, 40)
    assert caught.value.label == "BAD REPLY"


# -- geometry ------------------------------------------------------------------


def test_portland_to_seattle():
    distance, bearing = distance_bearing(*PDX, 47.4502, -122.3088)
    assert 110 < distance < 114
    assert compass(bearing) == "N"


@pytest.mark.parametrize("bearing, name", [(0, "N"), (44, "NE"), (91, "E"), (180, "S"), (300, "NW"), (350, "N")])
def test_compass_points(bearing, name):
    assert compass(bearing) == name
