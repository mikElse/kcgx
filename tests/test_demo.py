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


def test_every_demo_aircraft_carries_every_field_the_radar_keeps():
    from kcgx.radar import Radar

    for t in range(1_000_000, 1_003_600, 60):
        reply = demo.traffic(45.5887, -122.5975, 250, clock=lambda: float(t))
        for ac in reply["ac"]:
            for key in ("r", "desc", "ownOp", "baro_rate", "category"):
                assert ac.get(key) not in (None, ""), (key, ac)
    radar = Radar(on_frame=lambda f: None, on_note=lambda n: None, clock=lambda: 1_000_000.0)
    radar.retarget(45.5887, -122.5975)
    radar.merge(demo.traffic(45.5887, -122.5975, 250, clock=lambda: 1_000_000.0))
    for ac in radar.frame()["ac"]:
        assert None not in (ac["reg"], ac["desc"], ac["oper"], ac["vs"], ac["cat"]), ac
    climbing = {ac["label"]: ac["vs"] for ac in radar.frame()["ac"]}
    assert climbing.get("DAL1388", 1) > 0 and climbing.get("ASA412", -1) < 0


def test_two_demo_aircraft_are_parked_at_the_field_from_the_first_poll():
    from kcgx.radar import Radar, distance_bearing

    field = (45.5887, -122.5975)
    for t in (1_000_000.0, 1_000_015.0, 1_234_567.0):
        reply = demo.traffic(*field, 10, clock=lambda: t)
        parked = [ac for ac in reply["ac"] if ac["alt_baro"] == "ground" and ac["gs"] == 0]
        assert len(parked) == 2
        assert all(distance_bearing(*field, ac["lat"], ac["lon"])[0] < 1 for ac in parked)

    now = [1_000_000.0]
    radar = Radar(on_frame=lambda f: None, on_note=lambda n: None, clock=lambda: now[0],
                  fetch=lambda lat, lon, nm: demo.traffic(lat, lon, nm, clock=lambda: now[0]))
    radar.retarget(*field)
    radar.merge(demo.traffic(*field, 40, clock=lambda: now[0]))
    now[0] += 150
    radar.merge(demo.traffic(*field, 40, clock=lambda: now[0]))
    still = [ac for ac in radar.frame()["ac"] if ac["still"]]
    assert len(still) == 2 and all(ac["still"] == 150 for ac in still)


def test_a_shorter_range_thins_the_demo_traffic():
    """adsb.lol sends only what is inside the circle asked for, by where each
    aircraft is now. The demo does the same, so the range can be seen
    working: a departure leaves the picture as it flies out, an arrival
    joins it as it flies in."""
    from kcgx.radar import distance_bearing

    field = (45.5887, -122.5975)

    def distances(range_nm, t):
        reply = demo.traffic(*field, range_nm, clock=lambda: t)
        return {ac["hex"]: distance_bearing(*field, ac["lat"], ac["lon"])[0] for ac in reply["ac"]}

    starts = {f"de{index:04x}": leg[3] for index, leg in enumerate(demo.LEGS)}
    starts.update({f"de{len(demo.LEGS) + i:04x}": p[3] for i, p in enumerate(demo.PARKED)})
    thinned = flown_out = flown_in = False
    for t in range(1_000_000, 1_001_200, 15):
        everything = distances(250, t)  # no leg in the demo reaches 80 nm
        for range_nm in (10, 20, 40):
            shown = distances(range_nm, t)
            assert set(shown) == {h for h, nm in everything.items() if nm <= range_nm}
            thinned = thinned or len(shown) < len(everything)
        at_10 = distances(10, t)
        flown_out = flown_out or any(starts[h] <= 10 and h not in at_10 for h in everything)
        flown_in = flown_in or any(starts[h] > 10 for h in at_10)
    assert thinned and flown_out and flown_in


async def test_what_the_radar_drops_at_a_shorter_range_stays_dropped_in_the_demo():
    """The demo and Radar.set_range agree on what is in range: an aircraft
    dropped by a shorter range does not come back with the next poll."""
    from kcgx.radar import Radar

    now = [1_000_000.0]
    clock = lambda: now[0]
    radar = Radar(on_frame=lambda f: None, on_note=lambda n: None, clock=clock,
                  fetch=lambda lat, lon, nm: demo.traffic(lat, lon, nm, clock=clock))
    radar.retarget(45.5887, -122.5975)
    seen_far = False
    for _ in range(40):
        radar.set_range(40)
        await radar.poll()
        seen_far = seen_far or any(ac["dist"] > 10 for ac in radar.frame()["ac"])
        radar.set_range(10)
        now[0] += 15
        await radar.poll()
        assert all(ac["dist"] <= 10 for ac in radar.frame()["ac"]), radar.frame()["ac"]
        now[0] += 15
    assert seen_far


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
