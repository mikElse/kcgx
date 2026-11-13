"""The station: loading an airport, changing it, and acting for pages.

Fake sessions and a fake feed listing; a real Mixer that is never started,
so its channel list is the real one; the real airport dataset.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from kcgx.hub import Client, Hub
from kcgx.prefs import DEFAULTS
from kcgx.station import Station, UnknownAirport
from squelch.config import Config
from squelch.mixer import Mixer
from squelch.runtime import AUDIO_FAILED
from station_fakes import AIRPORTS, LISTINGS, Builder, listing, picker

def make(loader=listing, *, mixer=None, prefs=None, remembered_prefs=None):
    loop = asyncio.get_running_loop()
    hub = Hub()
    builder = Builder()
    remembered = []
    remembered_prefs = [] if remembered_prefs is None else remembered_prefs
    station = Station(
        Config(icao="KPDX", feed="kpdx3_twr"),
        hub,
        post=lambda fn, *args: loop.call_soon_threadsafe(fn, *args),
        airports=AIRPORTS,
        mixer=mixer or Mixer(),
        feeds_loader=loader,
        sessions_builder=builder,
        picker_loader=picker,
        remember=remembered.append,
        prefs=prefs,
        remember_prefs=lambda p: remembered_prefs.append(dict(p)),
    )
    return station, hub, builder, remembered


def watch(hub):
    async def send(text):
        pass

    client = Client(send, size=1000)
    hub.add(client)
    return client


def frames(client, kind=None):
    out = []
    while not client.queue.empty():
        frame = json.loads(client.queue.get_nowait())
        if kind is None or frame["t"] == kind:
            out.append(frame)
    return out


def idents(station):
    return [s.feed.ident for s in station.cockpit.sessions]


# -- opening and changing airport ------------------------------------------


async def test_opening_loads_the_airport_and_starts_its_feeds():
    station, _, _, remembered = make()
    await station.open("KPDX")
    assert idents(station) == ["kpdx3_twr", "kpdx3_gnd", "kpdx3_atis"]
    assert all(s.connected for s in station.cockpit.sessions)
    assert station.loading is False
    assert remembered == [], "the first airport came from the state file"


async def test_pages_see_loading_then_the_feeds():
    station, hub, _, _ = make()
    page = watch(hub)
    await station.open("KPDX")
    snapshots = frames(page, "snapshot")
    assert [s["loading"] for s in snapshots] == [True, False]
    assert snapshots[0]["feeds"] == []
    assert [f["ident"] for f in snapshots[1]["feeds"]] == idents(station)
    assert snapshots[1]["airport"]["icao"] == "KPDX"


async def test_a_missing_audio_device_is_said_once_on_opening():
    mixer = Mixer()
    mixer.failed = True
    station, hub, _, _ = make(mixer=mixer)
    await station.open("KPDX")
    assert [e["text"] for e in hub.log].count(AUDIO_FAILED) == 1
    assert station.snapshot()["audio_ok"] is False


async def test_listing_warnings_reach_the_log_after_the_feeds():
    def warning_listing(config, *, warn):
        warn("could not refresh the feed list — using the cached list")
        return list(LISTINGS["KPDX"])

    station, hub, _, _ = make(warning_listing)
    page = watch(hub)
    await station.open("KPDX")
    kinds = [f["t"] for f in frames(page)]
    assert kinds.index("message") > max(i for i, k in enumerate(kinds) if k == "snapshot")
    assert "cached list" in hub.log[-1]["text"]


async def test_a_retry_hint_names_what_the_page_can_do_not_a_key():
    def refused(config, *, warn):
        warn("KPDX — LiveATC refused the feed list; press f to retry")
        return []

    station, hub, _, _ = make(refused)
    await station.open("KPDX")
    assert hub.log[-1]["text"].endswith("refused the feed list; choose the airport again to retry")
    assert "FEEDS" not in hub.log[-1]["text"]


async def test_a_listing_that_raises_leaves_an_empty_stack_and_says_so():
    def broken(config, *, warn):
        raise OSError("network down")

    station, hub, _, _ = make(broken)
    await station.open("KPDX")
    assert idents(station) == []
    assert station.loading is False
    assert "network down" in hub.log[-1]["text"]


async def test_an_unknown_airport_is_refused_and_nothing_changes():
    station, _, _, remembered = make()
    await station.open("KPDX")
    before = station.cockpit
    with pytest.raises(UnknownAirport):
        await station.change_airport("ZZZZ")
    assert station.cockpit is before
    assert remembered == []


async def test_changing_airport_stops_the_old_feeds_and_remembers_the_new_one():
    mixer = Mixer()
    station, _, builder, remembered = make(mixer=mixer)
    await station.open("KPDX")
    old = station.cockpit.sessions
    await station.change_airport("ksea")
    assert all(s.stopped for s in old)
    assert idents(station) == ["ksea_twr", "ksea_gnd"]
    assert station.icao == "KSEA"
    assert remembered == ["KSEA"]
    assert len(mixer._channels) == 2, "the old airport's channels must go"


async def test_the_configured_feed_is_audible_only_at_its_own_airport():
    station, _, _, _ = make()
    await station.change_airport("KSEA")
    audible = [s.feed.ident for s in station.cockpit.sessions if not s.muted]
    assert audible == ["ksea_twr"], "falls back to the first feed, never kpdx3_twr"


async def test_a_second_change_while_the_first_is_loading_wins():
    gate = threading.Event()

    def slow_seattle(config, *, warn):
        if config.icao == "KSEA":
            gate.wait(5)
        return list(LISTINGS.get(config.icao, []))

    station, _, builder, _ = make(slow_seattle)
    await station.open("KPDX")
    seattle = asyncio.create_task(station.change_airport("KSEA"))
    await asyncio.sleep(0.05)
    await station.change_airport("KORD")
    gate.set()
    await seattle
    assert station.icao == "KORD"
    assert idents(station) == ["kord_twr"]
    assert not any(s.feed.ident.startswith("ksea") for s in builder.built)


# -- session events --------------------------------------------------------


async def test_a_session_event_from_its_own_thread_reaches_pages():
    station, hub, builder, _ = make()
    await station.open("KPDX")
    page = watch(hub)
    session = station.cockpit.sessions[1]
    session.state = "reconnecting"
    thread = threading.Thread(target=builder.events.on_state, args=(session, "reconnecting"))
    thread.start()
    thread.join()
    await asyncio.sleep(0.05)
    feeds = frames(page, "feed")
    assert feeds and feeds[-1]["feed"]["state"] == "reconnecting"


async def test_a_session_warning_is_logged_with_its_name():
    station, hub, builder, _ = make()
    await station.open("KPDX")
    session = station.cockpit.sessions[0]
    builder.events.on_warn(session, "could not resolve feed")
    await asyncio.sleep(0.05)
    assert hub.log[-1]["text"] == "Tower (Both): could not resolve feed"


async def test_events_from_the_previous_airport_are_ignored():
    station, hub, builder, _ = make()
    await station.open("KPDX")
    stale = station.cockpit.sessions[0]
    await station.change_airport("KSEA")
    page = watch(hub)
    builder.events.on_state(stale, "offline")
    builder.events.on_warn(stale, "gone")
    await asyncio.sleep(0.05)
    assert frames(page) == []


# -- acting for pages ------------------------------------------------------


async def test_mute_from_a_page_moves_the_stack_for_every_page():
    station, hub, _, _ = make()
    await station.open("KPDX")
    page = watch(hub)
    station.handle({"t": "mute", "ident": "kpdx3_atis"})
    sent = frames(page)
    assert [f["t"] for f in sent][-1] == "order"
    # Tower was already audible; ATIS joins it above the muted Ground.
    assert sent[-1]["idents"] == ["kpdx3_twr", "kpdx3_atis", "kpdx3_gnd"]
    assert any(f["t"] == "feed" and f["feed"]["ident"] == "kpdx3_atis" for f in sent)


async def test_solo_and_ambient_from_a_page():
    station, _, _, _ = make()
    await station.open("KPDX")
    station.handle({"t": "solo", "ident": "kpdx3_gnd"})
    assert [s.feed.ident for s in station.cockpit.sessions if not s.muted] == ["kpdx3_gnd"]
    station.handle({"t": "ambient", "ident": "kpdx3_gnd"})
    assert station.cockpit.session("kpdx3_gnd").ambient is True


async def test_volume_reaches_the_mixer_and_every_page():
    station, hub, _, _ = make()
    await station.open("KPDX")
    page = watch(hub)
    station.handle({"t": "volume", "value": 0.35})
    assert station.mixer.volume == pytest.approx(0.35)
    assert frames(page, "volume") == [{"t": "volume", "value": 0.35}]


async def test_input_from_a_page_holds_the_resort():
    station, _, _, _ = make()
    await station.open("KPDX")
    station.handle({"t": "input"})
    assert station.cockpit.resorter._last_input is not None


async def test_opening_a_feed_needs_the_picker_list_first():
    station, hub, _, _ = make()
    await station.open("KPDX")
    station.handle({"t": "open_feed", "ident": "kpdx_del"})
    assert "not in the feed list" in hub.log[-1]["text"]
    assert station.cockpit.session("kpdx_del") is None


async def test_a_feed_from_the_picker_opens_and_every_page_sees_it():
    station, hub, _, _ = make()
    await station.open("KPDX")
    listed = await station.available_feeds()
    assert {"ident": "kpdx_del", "label": "Delivery", "open": False} in listed
    assert {"ident": "kpdx3_twr", "label": "KPDX Tower (Both)", "open": True} in listed
    page = watch(hub)
    station.handle({"t": "open_feed", "ident": "kpdx_del"})
    assert station.cockpit.session("kpdx_del") is not None
    assert [f["feed"]["ident"] for f in frames(page, "added")] == ["kpdx_del"]


async def test_opening_a_feed_that_is_already_open_does_nothing():
    station, hub, _, _ = make()
    await station.open("KPDX")
    await station.available_feeds()
    before = len(hub.log)
    station.handle({"t": "open_feed", "ident": "kpdx3_twr"})
    assert len(station.cockpit.sessions) == 3
    assert len(hub.log) == before


# -- ticking ---------------------------------------------------------------


async def test_levels_go_out_only_when_someone_is_watching():
    station, hub, _, _ = make()
    await station.open("KPDX")
    station.tick_levels()
    page = watch(hub)
    station.cockpit.sessions[0].level = -12.34
    station.tick_levels()
    levels = frames(page, "levels")
    assert len(levels) == 1
    assert levels[0]["v"]["kpdx3_twr"] == -12.3


async def test_the_resort_tick_reorders_and_sends_chatter():
    station, hub, _, _ = make()
    await station.open("KPDX")
    page = watch(hub)
    station.cockpit.sessions[2].activity = 0.9
    for _ in range(3):
        station.tick_resort()
    assert idents(station)[1] == "kpdx3_atis"
    assert frames(page, "chatter")[-1]["v"]["kpdx3_atis"] == 0.9


# -- stopping --------------------------------------------------------------


async def test_stop_stops_every_feed_and_releases_the_mixer_channels():
    mixer = Mixer()
    station, _, _, _ = make(mixer=mixer)
    await station.open("KPDX")
    sessions = station.cockpit.sessions
    station.stop()
    assert all(s.stopped for s in sessions)
    assert mixer._channels == []


# -- how the page looks ------------------------------------------------------


async def test_the_snapshot_carries_the_prefs_the_station_was_given():
    prefs = {**DEFAULTS, "palette": "AMBER", "glow_map": 75, "display": "OFF", "lamps": True}
    station, *_ = make(prefs=prefs)
    assert station.snapshot()["prefs"] == prefs


async def test_without_prefs_the_station_uses_the_defaults():
    station, *_ = make()
    assert station.snapshot()["prefs"] == DEFAULTS


async def test_without_prefs_the_station_has_lists_of_its_own():
    station, *_ = make()
    station.prefs["tag_fields"].append("DIST")
    station.prefs["box_items"].append("HUD")
    assert DEFAULTS["tag_fields"] == ["CALLSIGN", "ALT"]
    assert DEFAULTS["box_items"] == []


async def test_a_prefs_change_is_remembered_and_reaches_every_page():
    saved = []
    station, hub, *_ = make(remembered_prefs=saved)
    page = watch(hub)
    station.handle({"t": "prefs", "palette": "MATRIX"})
    assert saved == [{**DEFAULTS, "palette": "MATRIX"}]
    assert frames(page, "prefs") == [{"t": "prefs", **DEFAULTS, "palette": "MATRIX"}]
    station.handle({"t": "prefs", "glow_text": 0, "teletype": True, "box_items": ["HUD"]})
    assert station.prefs == {
        **DEFAULTS, "palette": "MATRIX", "glow_text": 0, "teletype": True, "box_items": ["HUD"],
    }


async def test_a_partial_table_is_merged_a_cell_at_a_time():
    """Two tabs changing two cells of the map: both land, and what is
    remembered and sent is the whole table."""
    saved = []
    station, hub, *_ = make(remembered_prefs=saved)
    page = watch(hub)
    station.handle({"t": "prefs", "map": {"COAST": {"alpha": 60}}})
    station.handle({"t": "prefs", "map": {"COAST": {"width": 30}, "LAKE": {"show": False}}})
    whole = {
        **DEFAULTS["map"],
        "COAST": {**DEFAULTS["map"]["COAST"], "alpha": 60, "width": 30},
        "LAKE": {**DEFAULTS["map"]["LAKE"], "show": False},
    }
    assert station.prefs["map"] == whole
    assert saved[-1] == {**DEFAULTS, "map": whole}
    assert frames(page, "prefs")[-1] == {"t": "prefs", **DEFAULTS, "map": whole}
    assert DEFAULTS["map"]["COAST"]["alpha"] == 100, "the merge reached the defaults"


async def test_a_stations_given_prefs_with_part_of_a_table_keep_the_rest():
    station, *_ = make(prefs={"map": {"COAST": {"alpha": 60}}})
    assert station.prefs["map"]["COAST"] == {**DEFAULTS["map"]["COAST"], "alpha": 60}
    assert station.prefs["map"]["LAKE"] == DEFAULTS["map"]["LAKE"]


# -- the radar ---------------------------------------------------------------


async def test_changing_airport_points_the_radar_at_it():
    station, hub, *_ = make()
    page = watch(hub)
    await station.change_airport("KSEA")
    assert (station.radar.lat, station.radar.lon) == (station.airport.lat, station.airport.lon)
    aircraft = frames(page, "aircraft")
    assert aircraft and aircraft[-1]["ac"] == []


async def test_the_snapshot_carries_the_radar_picture():
    station, *_ = make()
    await station.open("KPDX")
    station.radar.merge({"ac": [{"hex": "abc", "flight": "ASA1", "lat": 45.6, "lon": -122.5}]})
    assert [ac["label"] for ac in station.snapshot()["radar"]["ac"]] == ["ASA1"]


async def test_radar_frames_and_emergencies_reach_every_page():
    station, hub, *_ = make()
    await station.open("KPDX")
    page = watch(hub)
    station.radar.merge({"ac": [{"hex": "e", "flight": "N52RT", "squawk": "7700", "lat": 45.9, "lon": -122.6}]})
    station.radar.on_frame(station.radar.frame())
    assert frames(page, "aircraft")[-1]["ac"][0]["sq"] == "7700"
    assert hub.log[-1]["text"].startswith("N52RT squawking 7700 (emergency), 19 nm N")


async def test_the_radar_takes_its_pace_from_the_config_and_its_range_from_the_prefs():
    loop = asyncio.get_running_loop()
    station = Station(
        Config(radar_refresh_secs=30, radar_stale_secs=90),
        Hub(),
        post=lambda fn, *args: loop.call_soon_threadsafe(fn, *args),
        airports=AIRPORTS,
        mixer=Mixer(),
        feeds_loader=listing,
        sessions_builder=Builder(),
        picker_loader=picker,
        remember=lambda icao: None,
        prefs={"range_nm": 120},
        remember_prefs=lambda prefs: None,
    )
    assert (station.radar.refresh_secs, station.radar.range_nm, station.radar.stale_secs) == (30, 120, 90)


async def test_without_prefs_the_radar_has_the_default_range():
    station, *_ = make()
    assert station.radar.range_nm == DEFAULTS["range_nm"] == 40


async def test_prefs_that_leave_settings_out_are_filled_from_the_defaults():
    station, *_ = make(prefs={"palette": "AMBER"})
    assert station.prefs == {**DEFAULTS, "palette": "AMBER"}
    assert station.radar.range_nm == 40


NEAR = {"hex": "near", "flight": "ASA1", "lat": 45.6, "lon": -122.3}  # 12 nm E of KPDX
FAR = {"hex": "far", "flight": "DAL2", "lat": 46.6, "lon": -122.6}  # 61 nm N


async def test_a_range_change_retunes_the_radar_and_tells_every_page():
    saved = []
    station, hub, *_ = make(prefs={**DEFAULTS, "range_nm": 120}, remembered_prefs=saved)
    await station.open("KPDX")
    station.radar.merge({"ac": [NEAR, FAR]})
    page = watch(hub)

    station.handle({"t": "prefs", "range_nm": 250})
    assert station.radar.range_nm == 250 and saved[-1]["range_nm"] == 250
    sent = frames(page)
    assert [f["t"] for f in sent] == ["prefs", "aircraft"]
    assert sent[0]["range_nm"] == 250 and sent[1]["range"] == 250
    assert [ac["hex"] for ac in sent[1]["ac"]] == ["far", "near"]

    station.handle({"t": "prefs", "range_nm": 20})
    aircraft = frames(page, "aircraft")
    assert len(aircraft) == 1 and aircraft[0]["range"] == 20
    assert [ac["hex"] for ac in aircraft[0]["ac"]] == ["near"], "beyond the new range: gone at once"


async def test_a_prefs_change_that_leaves_the_range_alone_sends_no_aircraft_frame():
    station, hub, *_ = make()
    await station.open("KPDX")
    page = watch(hub)
    station.handle({"t": "prefs", "palette": "MONO", "lamps": True})
    station.handle({"t": "prefs", "range_nm": 40})  # the range it already has
    assert [f["t"] for f in frames(page)] == ["prefs", "prefs"]
    assert station.radar.range_nm == 40
