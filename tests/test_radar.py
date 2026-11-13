"""The radar's poller and picture (kcgx.radar), with no network."""

from __future__ import annotations

import asyncio
import contextlib
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


def test_every_field_adsb_lol_gives_is_kept_under_a_short_key():
    radar, *_ = make()
    radar.merge({"ac": [plane(r="n412as ", desc="boeing 737 max 9", ownOp="Alaska Airlines Inc",
                              baro_rate=-704.4, category="a3")]})
    ac = radar.frame()["ac"][0]
    assert (ac["reg"], ac["desc"], ac["oper"], ac["vs"], ac["cat"]) == (
        "N412AS", "BOEING 737 MAX 9", "ALASKA AIRLINES INC", -704, "A3")


def test_a_field_not_given_is_none():
    radar, *_ = make()
    radar.merge({"ac": [plane("a"), plane("b", r="  ", desc="", ownOp=None, baro_rate="fast", category=7)]})
    for ac in radar.frame()["ac"]:
        assert (ac["reg"], ac["desc"], ac["oper"], ac["vs"], ac["cat"]) == (None,) * 5, ac


# -- parked traffic ------------------------------------------------------------


def parked(hex_="p", **fields):
    return plane(hex_, **{"alt_baro": "ground", "gs": 0.0, "seen_pos": 0.0, **fields})


def test_a_track_on_the_ground_and_slow_counts_up_from_the_poll_it_first_qualified():
    radar, _, _, clock = make(ground_gs=5)
    radar.merge({"ac": [parked()]})
    assert radar.frame()["ac"][0]["still"] == 0
    clock.now += 15
    radar.merge({"ac": [parked(gs=4.9)]})
    clock.now += 7
    assert radar.frame()["ac"][0]["still"] == 22, "counted on our clock, between polls too"
    assert isinstance(radar.frame()["ac"][0]["still"], int)


def test_one_poll_that_fails_the_test_resets_it():
    radar, _, _, clock = make(ground_gs=5)
    radar.merge({"ac": [parked()]})
    clock.now += 30
    radar.merge({"ac": [parked(gs=6)]})  # taxiing
    assert radar.frame()["ac"][0]["still"] == 0
    clock.now += 15
    radar.merge({"ac": [parked()]})
    clock.now += 15
    assert radar.frame()["ac"][0]["still"] == 15, "from the poll it qualified again"


def test_a_poll_that_misses_a_parked_track_does_not_reset_it():
    radar, _, _, clock = make(ground_gs=5)
    radar.merge({"ac": [parked()]})
    clock.now += 15
    radar.merge({"ac": []})  # not heard this time, not yet stale
    clock.now += 15
    radar.merge({"ac": [parked()]})
    assert radar.frame()["ac"][0]["still"] == 30


def test_airborne_or_of_unknown_speed_is_never_still():
    radar, *_ = make(ground_gs=5)
    radar.merge({"ac": [plane("air", gs=0.0), parked("nogs", gs=None), parked("noalt", alt_baro=None)]})
    assert {ac["hex"]: ac["still"] for ac in radar.frame()["ac"]} == {"air": 0, "nogs": 0, "noalt": 0}


def test_an_altitude_under_ground_alt_counts_as_on_the_ground():
    radar, _, _, clock = make(ground_gs=5, ground_alt=100)
    radar.merge({"ac": [parked("low", alt_baro=25), parked("high", alt_baro=100)]})
    clock.now += 15
    radar.merge({"ac": [parked("low", alt_baro=25), parked("high", alt_baro=100)]})
    assert {ac["hex"]: ac["still"] for ac in radar.frame()["ac"]} == {"low": 15, "high": 0}


def test_at_ground_alt_zero_only_gnd_counts():
    radar, _, _, clock = make(ground_gs=5, ground_alt=0)
    radar.merge({"ac": [parked("gnd"), parked("zero", alt_baro=0), parked("below", alt_baro=-50)]})
    clock.now += 15
    radar.merge({"ac": [parked("gnd"), parked("zero", alt_baro=0), parked("below", alt_baro=-50)]})
    assert {ac["hex"]: ac["still"] for ac in radar.frame()["ac"]} == {"gnd": 15, "zero": 0, "below": 0}


def test_new_ground_thresholds_apply_from_the_next_poll_and_send_nothing():
    radar, frames, _, clock = make(ground_gs=5)
    radar.merge({"ac": [parked(gs=8)]})
    radar.set_ground(10, 0)
    assert (radar.ground_gs, radar.ground_alt) == (10, 0) and frames == []
    assert radar.frame()["ac"][0]["still"] == 0
    clock.now += 15
    radar.merge({"ac": [parked(gs=8)]})
    clock.now += 15
    assert radar.frame()["ac"][0]["still"] == 15


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


@pytest.mark.parametrize(
    ("refresh", "expected"),
    [(15, [15, 30, 60, 120, 120]), (120, [120, 240, 480, 480])],
)
def test_the_backoff_cap_is_two_minutes_or_four_refreshes_whichever_is_longer(refresh, expected):
    """At the slowest poll rate a refusal must still back off: the cap is
    max(two minutes, four refreshes), so failures double at least twice."""
    radar, *_ = make(refresh_secs=refresh)
    delays = []
    for failures in range(len(expected)):
        radar.failures = failures
        delays.append(radar.delay())
    assert delays == expected


def test_a_config_cannot_poll_faster_than_adsb_lol_asks():
    radar, *_ = make(refresh_secs=5)
    assert radar.delay() == 15
    radar.refresh_secs = 30
    assert radar.delay() == 30


async def test_a_new_refresh_sets_the_base_delay_and_keeps_the_backoff():
    answers = [RadarRefused("ERR 429")] * 3

    def fetch(*args):
        raise answers.pop(0)

    radar, frames, *_ = make(fetch)
    radar.set_refresh(30)
    assert radar.refresh_secs == 30 and radar.delay() == 30
    assert frames == []
    delays = []
    for _ in range(3):
        await radar.poll()
        delays.append(radar.delay())
    assert delays == [60, 120, 120]
    radar.set_refresh(5)
    radar.failures = 0
    assert radar.delay() == 15, "never faster than adsb.lol asks"


async def test_a_new_refresh_never_triggers_a_poll():
    asked = []
    radar, *_ = make(lambda lat, lon, range_nm: asked.append(range_nm) or {"ac": []})
    task = asyncio.create_task(radar.run())
    for _ in range(100):
        if asked:
            break
        await asyncio.sleep(0.01)
    assert asked, "the first poll never ran"
    for secs in (60, 15, 120, 20):
        radar.set_refresh(secs)
        await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert asked == [40] and radar.refresh_secs == 20


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


# -- the range -----------------------------------------------------------------

FAR = {"lat": 45.9, "lon": -123.0}  # 25 nm NW; plane() itself is 12 nm E


def test_a_new_range_drops_what_is_beyond_it_and_tells_pages_once():
    radar, frames, *_ = make()
    radar.merge({"ac": [plane("near"), plane("far", **FAR)]})
    radar.set_range(20)
    assert radar.range_nm == 20
    assert set(radar.tracks) == {"near"}
    assert len(frames) == 1 and frames[0]["range"] == 20
    assert [ac["hex"] for ac in frames[0]["ac"]] == ["near"]


def test_a_wider_range_keeps_every_aircraft():
    radar, frames, *_ = make()
    radar.merge({"ac": [plane("near"), plane("far", **FAR)]})
    radar.set_range(250)
    assert len(frames) == 1 and frames[0]["range"] == 250
    assert [ac["hex"] for ac in frames[0]["ac"]] == ["far", "near"]


def test_the_range_it_already_has_sends_nothing():
    radar, frames, *_ = make()
    radar.set_range(40)
    assert frames == []


def test_a_new_range_before_there_is_an_airport_is_only_remembered():
    frames = []
    radar = Radar(on_frame=frames.append, on_note=lambda note: None)
    radar.set_range(120)
    assert radar.range_nm == 120 and frames[-1]["range"] == 120 and frames[-1]["ac"] == []


async def test_the_next_poll_asks_for_the_new_range():
    asked = []
    radar, frames, *_ = make(lambda lat, lon, range_nm: asked.append(range_nm) or {"ac": []})
    await radar.poll()
    radar.set_range(20)
    await radar.poll()
    assert asked == [40, 20] and frames[-1]["range"] == 20


async def test_a_new_range_waits_for_the_next_scheduled_poll():
    """A dragged slider must not become a burst against adsb.lol's 15 s ask:
    unlike a new airport, a new range never wakes the poller."""
    asked = []
    radar, *_ = make(lambda lat, lon, range_nm: asked.append(range_nm) or {"ac": []})
    task = asyncio.create_task(radar.run())
    for _ in range(100):
        if asked:
            break
        await asyncio.sleep(0.01)
    assert asked, "the first poll never ran"
    for range_nm in (30, 20, 250, 20):
        radar.set_range(range_nm)
        await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert asked == [40]
    assert radar.delay() == 15, "and it is still waiting out the full refresh"


async def test_a_reply_asked_for_at_a_wider_range_is_cut_to_the_new_one():
    started, release = threading.Event(), threading.Event()

    def fetch(*args):
        started.set()
        release.wait(5)
        return {"ac": [plane("near"), plane("far", **FAR)]}

    radar, frames, *_ = make(fetch)
    task = asyncio.create_task(radar.poll())
    await asyncio.to_thread(started.wait, 5)
    radar.set_range(20)
    release.set()
    await task
    assert [ac["hex"] for ac in frames[-1]["ac"]] == ["near"]
    assert set(radar.tracks) == {"near"}


def test_an_emergency_beyond_a_shorter_range_is_not_said_to_have_stopped():
    """It is still squawking, only out of range. Brought back by a wider
    range, it is new to the picture and is announced as any arrival is."""
    radar, _, notes, _ = make()
    radar.merge({"ac": [plane("near"), plane("far", flight="N52RT", squawk="7700", **FAR)]})
    assert len(notes) == 1 and notes[0].startswith("N52RT squawking 7700")
    radar.set_range(20)
    radar.merge({"ac": [plane("near")]})
    assert len(notes) == 1, notes
    radar.set_range(40)
    radar.merge({"ac": [plane("near"), plane("far", flight="N52RT", squawk="7700", **FAR)]})
    assert len(notes) == 2 and notes[1].startswith("N52RT squawking 7700")
    radar.merge({"ac": [plane("near"), plane("far", flight="N52RT", squawk="1200", **FAR)]})
    assert notes[2:] == ["N52RT no longer squawking 7700"]


async def test_a_reply_cut_to_a_new_range_announces_and_numbers_only_what_is_kept():
    """Asked for at 40 nm, landed at 20: the emergency 25 nm out never was in
    the picture, so it is not announced and takes no UNK number, and an
    aircraft that has flown beyond 20 nm does not stay where it was last seen."""
    started, release = threading.Event(), threading.Event()

    def fetch(*args):
        started.set()
        release.wait(5)
        return {"ac": [
            plane("far", flight=None, squawk="7700", **FAR),
            plane("left", **FAR),
            plane("near", flight=None),
        ]}

    radar, frames, notes, _ = make(fetch)
    radar.merge({"ac": [plane("left")]})  # 12 nm E, before it flew out
    task = asyncio.create_task(radar.poll())
    await asyncio.to_thread(started.wait, 5)
    radar.set_range(20)
    release.set()
    await task
    assert notes == []
    assert [(ac["hex"], ac["label"]) for ac in frames[-1]["ac"]] == [("near", "UNK1")]


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
