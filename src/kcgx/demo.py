"""A station with nothing real behind it: synthetic feeds for any airport.

`kcgx-web --demo` runs on this. No LiveATC, no ffmpeg, no audio device, no
writes to the state directory: the page can be built, tested and looked at
without spending any of LiveATC's seven streams or hearing anything. The
browser tests run against it too.

Every feed meters, chatters and changes state the way a real one does, so
the page cannot tell the difference except that nothing plays.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections.abc import Callable
from functools import lru_cache

from kcgx.airports import find, load_airports
from kcgx.radar import distance_bearing
from squelch.config import Config
from squelch.feeds import Feed

# (suffix, label, how busy: the fraction of 1.5 s slots with someone talking)
POSITIONS = [
    ("twr", "Tower", 0.38),
    ("app", "Approach", 0.30),
    ("atis", "ATIS", 0.95),
    ("gnd", "Ground", 0.22),
    ("del", "Clearance Delivery", 0.08),
    ("dep", "Departure", 0.18),
    ("twr_n", "Tower (North)", 0.12),
    ("ctr", "{city} Center", 0.10),  # as LiveATC names some: "Seattle Center"
    ("gnd_ramp", "Ground (Ramp)", 0.04),
]

# In the picker but not opened at start, so opening a feed can be tried.
EXTRA = [
    ("app_final", "Approach (Final)", 0.20),
    ("guard", "Emergency Guard 121.5", 0.01),
]

SLOT_SECONDS = 1.5
SILENT_DBFS = -96.0


@lru_cache(maxsize=None)
def _city(icao: str) -> str:
    airport = find(icao, load_airports())
    return airport.city if airport else ""


def _feeds(icao: str, positions) -> list[Feed]:
    return [
        Feed(f"{icao.lower()}_{suffix}", " ".join(f"{icao.upper()} {label.format(city=_city(icao))}".split()))
        for suffix, label, _ in positions
    ]


def listing(config: Config, *, warn: Callable[[str], None]) -> list[Feed]:
    """Stands in for squelch.runtime.load_feeds."""
    return _feeds(config.icao, POSITIONS)


def picker(config: Config) -> list[Feed]:
    """Stands in for squelch.runtime.picker_feeds."""
    return _feeds(config.icao, POSITIONS + EXTRA)


def _busy_for(ident: str) -> float:
    for suffix, _, busy in POSITIONS + EXTRA:
        if ident.endswith("_" + suffix):
            return busy
    return 0.1


class DemoSession:
    """Behaves like squelch.session.FeedSession, minus the network."""

    def __init__(self, feed: Feed, events, *, muted: bool, icao: str, clock=time.monotonic):
        self.feed = feed
        prefix = f"{icao.upper()} "
        self.name = feed.label[len(prefix):] if feed.label.upper().startswith(prefix) else feed.label
        self.events = events
        self.muted = muted
        self.state = "starting"
        self.ambient = False
        self.soloed = False
        self.connected = False
        self._busy = _busy_for(feed.ident)
        self._seed = sum(map(ord, feed.ident))
        self._clock = clock
        self._timer: threading.Timer | None = None

    # -- what the station reads ------------------------------------------------

    @property
    def level(self) -> float:
        if not self.connected or self.state != "live":
            return SILENT_DBFS
        now = self._clock()
        slot = int(now / SLOT_SECONDS)
        talking = random.Random(self._seed * 100_003 + slot).random() < self._busy
        jitter = random.Random(self._seed * 7 + int(now * 25)).random()
        if talking:
            return -24.0 + 14.0 * jitter
        return -66.0 + 8.0 * jitter

    @property
    def activity(self) -> float:
        if self._busy <= 0:
            return 0.0
        drift = 0.85 + 0.15 * math.sin(self._clock() / 45.0 + self._seed)
        return max(0.0, min(1.0, self._busy * drift))

    # -- what the cockpit drives -----------------------------------------------

    def start(self) -> None:
        if self.connected:
            return
        self.connected = True
        # The Center feed reconnects once on its way up, so the page's amber
        # state is visible in the demo; the event arrives from another thread,
        # as a real feed's does.
        if self.feed.ident.endswith("_ctr"):
            self._set("reconnecting")
            self._timer = threading.Timer(3.0, self._set, args=("live",))
            self._timer.daemon = True
            self._timer.start()
        else:
            self._set("live")

    def park(self) -> None:
        self._cancel()
        self.connected = False
        self._set("parked")

    def stop(self) -> None:
        self._cancel()
        self.connected = False

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self) -> bool:
        self.ambient = not self.ambient
        return self.ambient

    def _set(self, state: str) -> None:
        if state == "live" and not self.connected:
            return
        self.state = state
        self.events.on_state(self, state)

    def _cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def build(feeds, config: Config, events, *, mixer=None) -> list[DemoSession]:
    """Stands in for squelch.runtime.build_sessions: everything muted but the
    configured feed, or the first feed when that is not here."""
    sessions = [
        DemoSession(feed, events, muted=feed.ident != config.feed, icao=config.icao)
        for feed in feeds
    ]
    if sessions and all(s.muted for s in sessions):
        sessions[0].muted = False
    return sessions


class DemoMixer:
    """The parts of squelch.mixer.Mixer the station touches. Plays nothing."""

    failed = False

    def __init__(self, *, volume: float = 1.0, **_ignored) -> None:
        self.volume = volume

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def clear_channels(self) -> None:
        pass


# -- demo traffic ------------------------------------------------------------
#
# Eleven aircraft on fixed paths around whatever airport is open, shaped
# like adsb.lol's reply so the real poller handles them. Each flies a
# straight leg (start bearing and distance from the field, heading, length)
# at constant speed, climbing or descending linearly, and starts again when
# the leg ends. As adsb.lol does, it sends only the aircraft inside the
# range asked for at that moment, so a shorter range visibly thins the
# picture. N52RT squawks 7600 for the middle minute of every five, so the
# emergency lamp and the log can be seen working. Two more are parked at the
# field (GND, 0 kt) from the first poll on, so parked traffic's fade can be
# seen once `ground_min` has passed. Every aircraft carries every field the
# radar keeps (registration, vertical rate, category), with made-up
# registrations.

NM_PER_DEG_LAT = 60.0

# callsign, type, start bearing, start nm, heading, leg nm, kt, alt from, alt to, squawk,
# then readsb's r and category
LEGS = [
    ("ASA412", "B39M", 90, 38, 270, 36, 230, 9000, 1200, "4512",
     "N915AK", "A3"),
    ("DAL1388", "A321", 30, 6, 30, 40, 310, 3000, 17000, "2251",
     "N391DN", "A3"),
    ("UAL1650", "B738", 350, 10, 350, 34, 330, 8000, 26000, "6011",
     "N37267", "A3"),
    ("SWA2183", "B737", 300, 36, 125, 32, 250, 12000, 2500, "3305",
     "N7718B", "A3"),
    ("QXE2041", "DH8D", 260, 30, 80, 28, 200, 6000, 1500, "4471",
     "N441QX", "A2"),
    ("N7243K", "C172", 200, 8, 160, 18, 105, 2500, 2500, "1200",
     "N7243K", "A1"),
    ("", "PA28", 120, 18, 270, 20, 95, 1800, 1800, "1200",
     "N8113J", "A1"),
    ("N52RT", "BE36", 320, 34, 120, 40, 150, 7500, 6500, "1200",
     "N52RT", "A1"),
    ("FDX1207", "B763", 180, 40, 0, 36, 260, 11000, 2000, "5213",
     "N119FE", "A5"),
    ("AAL2210", "A320", 60, 40, 245, 80, 450, 33000, 33000, "3466",
     "N653AW", "A3"),
    ("N911PD", "AS50", 150, 12, 330, 16, 110, 1500, 1500, "1200",
     "N911PD", "A7"),
]

# Parked: callsign, type, bearing and nm from the field, heading, squawk, r, category
PARKED = [
    ("ASA1022", "B739", 300, 0.4, 120, "2000",
     "N413AS", "A3"),
    ("N3842C", "C182", 140, 0.6, 90, "1200",
     "N3842C", "A1"),
]


def _offset(lat: float, lon: float, bearing: float, nm: float) -> tuple[float, float]:
    b = math.radians(bearing)
    dlat = nm * math.cos(b) / NM_PER_DEG_LAT
    dlon = nm * math.sin(b) / (NM_PER_DEG_LAT * max(0.01, math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


def traffic(lat: float, lon: float, range_nm: int, *, clock=time.time) -> dict:
    """Stands in for kcgx.radar.fetch_adsb_lol."""
    now = clock()
    aircraft = []
    for index, (callsign, kind, bearing, start, heading, leg, kt, alt0, alt1, squawk,
                reg, cat) in enumerate(LEGS):
        period = leg / kt * 3600 + 20
        phase = (now + index * 97) % period
        flown = min(leg, phase / 3600 * kt)
        if flown >= leg:
            continue  # between legs: off the screen for a moment, as aircraft are
        x_lat, x_lon = _offset(lat, lon, bearing, start)
        a_lat, a_lon = _offset(x_lat, x_lon, heading, flown)
        a_lat, a_lon = round(a_lat, 5), round(a_lon, 5)
        # Measured as the radar measures it, on the position as sent, so the
        # two never disagree about an aircraft at the edge.
        if distance_bearing(lat, lon, a_lat, a_lon)[0] > range_nm:
            continue
        alt = round((alt0 + (alt1 - alt0) * flown / leg) / 100) * 100
        if callsign == "N52RT" and 120 <= now % 300 < 180:
            squawk = "7600"
        aircraft.append({
            "hex": f"de{index:04x}",
            "flight": callsign.ljust(8) if callsign else None,
            "t": kind,
            "alt_baro": alt,
            "gs": kt,
            "track": heading,
            "lat": a_lat,
            "lon": a_lon,
            "squawk": squawk,
            "seen_pos": 0.4,
            "r": reg,
            "baro_rate": round((alt1 - alt0) / (leg / kt * 60)),  # ft/min over the leg
            "category": cat,
        })
    for offset, (callsign, kind, bearing, nm, heading, squawk, reg, cat) in enumerate(PARKED):
        p_lat, p_lon = (round(x, 5) for x in _offset(lat, lon, bearing, nm))
        if distance_bearing(lat, lon, p_lat, p_lon)[0] > range_nm:
            continue
        aircraft.append({
            "hex": f"de{len(LEGS) + offset:04x}",
            "flight": callsign.ljust(8),
            "t": kind,
            "alt_baro": "ground",
            "gs": 0,
            "track": heading,
            "lat": p_lat,
            "lon": p_lon,
            "squawk": squawk,
            "seen_pos": 0.4,
            "r": reg,
            "baro_rate": 0,
            "category": cat,
        })
    return {"ac": aircraft, "msg": "No error", "now": int(now * 1000)}
