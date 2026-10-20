"""The demo feeds behind kcgx-web --demo (kcgx.demo)."""

from __future__ import annotations

from kcgx import demo
from squelch.config import Config


class Events:
    def __init__(self):
        self.states = []

    def on_state(self, session, state):
        self.states.append((session.feed.ident, state))


def sessions(icao="KPDX", feed="kpdx_twr", clock=None):
    config = Config(icao=icao, feed=feed)
    feeds = demo.listing(config, warn=lambda line: None)
    built = demo.build(feeds, config, Events())
    if clock is not None:
        for session in built:
            session._clock = clock
    return built


def test_the_listing_is_named_for_the_airport():
    feeds = demo.listing(Config(icao="KSEA"), warn=lambda line: None)
    assert feeds[0].ident == "ksea_twr"
    assert feeds[0].label == "KSEA Tower"
    assert len(feeds) == len(demo.POSITIONS)


def test_the_picker_offers_more_than_the_listing():
    config = Config(icao="KPDX")
    listed = {f.ident for f in demo.listing(config, warn=lambda line: None)}
    offered = {f.ident for f in demo.picker(config)}
    assert listed < offered


def test_only_the_configured_feed_is_audible():
    built = sessions(feed="kpdx_app")
    assert [s.feed.ident for s in built if not s.muted] == ["kpdx_app"]


def test_the_first_feed_is_audible_when_the_configured_one_is_elsewhere():
    built = sessions(feed="ksea_twr")
    assert [s.muted for s in built][:2] == [False, True]


def test_names_drop_the_airport():
    assert sessions()[0].name == "Tower"


def test_a_feed_is_silent_until_it_is_live():
    session = sessions(clock=lambda: 10.0)[0]
    assert session.level == demo.SILENT_DBFS
    session.start()
    assert session.state == "live"
    assert -70 < session.level < -9


def test_levels_are_the_same_for_the_same_moment():
    a = sessions(clock=lambda: 123.4)[0]
    b = sessions(clock=lambda: 123.4)[0]
    a.start()
    b.start()
    assert a.level == b.level


def test_a_busy_feed_talks_more_than_a_quiet_one():
    def talking(ident):
        session = next(s for s in sessions() if s.feed.ident == ident)
        session.start()
        count = 0
        for slot in range(400):
            session._clock = lambda t=slot * demo.SLOT_SECONDS: t
            count += session.level > -40
        return count

    assert talking("kpdx_atis") > talking("kpdx_twr") > talking("kpdx_gnd_ramp")


def test_center_reconnects_before_it_goes_live():
    session = next(s for s in sessions() if s.feed.ident == "kpdx_ctr")
    session.start()
    assert session.state == "reconnecting"
    session._timer.cancel()
    session._set("live")
    assert session.state == "live"


def test_parking_cancels_a_pending_reconnect():
    session = next(s for s in sessions() if s.feed.ident == "kpdx_ctr")
    session.start()
    timer = session._timer
    session.park()
    assert session.state == "parked"
    assert session._timer is None and timer.finished.is_set()
    session._set("live")  # a late timer firing changes nothing
    assert session.state == "parked"


def test_the_demo_mixer_needs_no_device():
    mixer = demo.DemoMixer(volume=0.5)
    mixer.start()
    mixer.clear_channels()
    mixer.stop()
    assert mixer.volume == 0.5 and not mixer.failed


# -- demo traffic ------------------------------------------------------------


def test_demo_traffic_is_shaped_like_adsb_lol_and_stays_near_the_field():
    from kcgx.radar import Radar, distance_bearing

    reply = demo.traffic(45.5887, -122.5975, 40, clock=lambda: 1_000_000.0)
    assert reply["ac"] and len({ac["hex"] for ac in reply["ac"]}) == len(reply["ac"])
    for ac in reply["ac"]:
        distance, _ = distance_bearing(45.5887, -122.5975, ac["lat"], ac["lon"])
        assert distance < 80
    radar = Radar(on_frame=lambda f: None, on_note=lambda n: None, clock=lambda: 1_000_000.0)
    radar.retarget(45.5887, -122.5975)
    radar.merge(reply)
    labels = {ac["label"] for ac in radar.frame()["ac"]}
    assert "UNK1" in labels  # the one with no callsign


def test_demo_traffic_moves():
    a = demo.traffic(45.5887, -122.5975, 40, clock=lambda: 1_000_000.0)
    b = demo.traffic(45.5887, -122.5975, 40, clock=lambda: 1_000_015.0)
    moved = {x["hex"] for x in a["ac"]} & {x["hex"] for x in b["ac"]}
    pos = lambda reply: {x["hex"]: (x["lat"], x["lon"]) for x in reply["ac"]}
    assert any(pos(a)[h] != pos(b)[h] for h in moved)


def test_one_demo_aircraft_squawks_7600_for_one_minute_in_five():
    def squawk(t):
        reply = demo.traffic(45.5887, -122.5975, 40, clock=lambda: t)
        return {x["flight"].strip(): x["squawk"] for x in reply["ac"] if x["flight"]}.get("N52RT")

    base = 1_000_200.0 - (1_000_200.0 % 300)
    assert squawk(base + 60) in ("1200", None)
    assert squawk(base + 150) in ("7600", None)
    assert squawk(base + 200) in ("1200", None)
    window = [squawk(base + 120 + s) for s in range(0, 60, 5)]
    assert "7600" in window
