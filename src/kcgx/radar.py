"""The radar's traffic: adsb.lol polled from the server for every open page.

Polled here and not in the browser because adsb.lol refuses a request with
no contactable User-Agent and a browser may not set one, because one poller
serves every tab, and because the polling discipline (15 s, backing off
when refused) is per address (spec, Radar).

`Radar` owns the picture for the current airport: the aircraft seen, when
each was last seen, the UNK numbers given to aircraft with no callsign, and
which emergency squawks have been announced. A refused poll keeps the last
good picture and backs off: 15, 30, 60, then 120 s, reset by the first
success. Aircraft not seen for `stale_secs` drop out.

Everything but the fetch runs on the event loop. The fetch is a plain
blocking function, run in a worker thread, so tests and the demo can hand
in their own.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

URL = "https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{range}"
# The same identifying string bin/kcgx and setup.sh send. KCGX_ADSB_UA
# replaces it; set empty, no User-Agent is sent (and adsb.lol refuses).
DEFAULT_UA = "kcgx/0.1 (+https://github.com/mikElse/kcgx)"
BACKOFF_CAP_SECS = 120
# adsb.lol's own ask. A config file can lengthen the interval, never shorten it.
MIN_REFRESH_SECS = 15
EMERGENCIES = {"7500": "HIJACK", "7600": "RADIO FAILURE", "7700": "EMERGENCY"}
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
NM_PER_RADIAN = 3440.065

Fetch = Callable[[float, float, int], dict]


class RadarRefused(Exception):
    """adsb.lol, or the network on the way to it, said no. `label` is what
    the page shows: ERR 429, ERR 403, NO CONNECTION."""

    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.label = label


def user_agent() -> str:
    return os.environ.get("KCGX_ADSB_UA", DEFAULT_UA)


def fetch_adsb_lol(lat: float, lon: float, range_nm: int) -> dict:
    """One poll. Blocking: run it in a thread."""
    headers = {"Accept": "application/json"}
    ua = user_agent()
    if ua:
        headers["User-Agent"] = ua
    request = urllib.request.Request(URL.format(lat=lat, lon=lon, range=range_nm), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RadarRefused(f"ERR {error.code}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise RadarRefused("NO CONNECTION") from error
    except ValueError as error:
        raise RadarRefused("BAD REPLY") from error


def distance_bearing(lat0: float, lon0: float, lat1: float, lon1: float) -> tuple[float, float]:
    """Great circle distance in nm and initial bearing in degrees true."""
    p0, p1 = math.radians(lat0), math.radians(lat1)
    dl = math.radians(lon1 - lon0)
    a = math.sin((p1 - p0) / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(dl / 2) ** 2
    distance = 2 * NM_PER_RADIAN * math.asin(min(1.0, math.sqrt(a)))
    y = math.sin(dl) * math.cos(p1)
    x = math.cos(p0) * math.sin(p1) - math.sin(p0) * math.cos(p1) * math.cos(dl)
    return distance, (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(bearing: float) -> str:
    return COMPASS[round(bearing / 45) % 8]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


@dataclass
class Track:
    hex: str
    lat: float
    lon: float
    seen_at: float  # our clock, when the position was current
    callsign: str = ""
    type: str = ""
    alt: int | str | None = None  # feet, or "GND"
    gs: float | None = None
    track: float | None = None
    squawk: str = ""
    unk: int = 0


@dataclass
class Radar:
    """The current airport's picture. Call `retarget` on an airport change,
    `poll` to take one picture (or let `run` do it on its schedule)."""

    on_frame: Callable[[dict], None]
    on_note: Callable[[str], None]
    fetch: Fetch = fetch_adsb_lol
    refresh_secs: int = 15
    range_nm: int = 40
    stale_secs: int = 60
    clock: Callable[[], float] = time.time
    lat: float | None = None
    lon: float | None = None
    tracks: dict[str, Track] = field(default_factory=dict)
    error: str = ""
    last_good: float | None = None
    failures: int = 0
    _unk_next: int = 1
    _unks: dict[str, int] = field(default_factory=dict)
    _announced: dict[str, str] = field(default_factory=dict)
    _generation: int = 0
    _wake: asyncio.Event | None = None

    # -- the airport -----------------------------------------------------------

    def retarget(self, lat: float | None, lon: float | None) -> None:
        """A new airport: forget everything and poll it at once."""
        self._generation += 1
        self.lat, self.lon = lat, lon
        self.tracks.clear()
        self._unks.clear()
        self._unk_next = 1
        self._announced.clear()
        self.error, self.last_good, self.failures = "", None, 0
        self.on_frame(self.frame())
        if self._wake is not None:
            self._wake.set()

    # -- polling -----------------------------------------------------------------

    def delay(self) -> float:
        """Seconds until the next poll: the refresh, doubled per failure in a
        row, capped at two minutes."""
        refresh = max(MIN_REFRESH_SECS, self.refresh_secs)
        if not self.failures:
            return float(refresh)
        return float(min(BACKOFF_CAP_SECS, refresh * 2 ** self.failures))

    async def poll(self) -> None:
        if self.lat is None or self.lon is None:
            return
        generation, lat, lon = self._generation, self.lat, self.lon
        try:
            data = await asyncio.to_thread(self.fetch, lat, lon, self.range_nm)
        except RadarRefused as refused:
            if generation == self._generation:
                self.failures += 1
                self.error = refused.label
                self._expire()
                self.on_frame(self.frame())
            return
        if generation != self._generation:
            return  # the airport changed while we were asking
        self.failures, self.error = 0, ""
        self.last_good = self.clock()
        self.merge(data)
        self.on_frame(self.frame())

    async def run(self) -> None:
        """Poll forever on the schedule. Cancel the task to stop."""
        self._wake = asyncio.Event()
        while True:
            await self.poll()
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.delay())
            except TimeoutError:
                pass

    # -- the picture -------------------------------------------------------------

    def merge(self, data: dict) -> None:
        now = self.clock()
        for raw in data.get("ac") or []:
            hex_ = str(raw.get("hex") or "").lower().strip()
            lat, lon = _number(raw.get("lat")), _number(raw.get("lon"))
            if not hex_ or lat is None or lon is None:
                continue
            seen_pos = _number(raw.get("seen_pos")) or 0.0
            track = self.tracks.get(hex_) or Track(hex=hex_, lat=lat, lon=lon, seen_at=0.0)
            track.lat, track.lon = lat, lon
            track.seen_at = now - seen_pos
            track.callsign = str(raw.get("flight") or "").strip().upper()
            track.type = str(raw.get("t") or "").strip().upper()
            alt = raw.get("alt_baro")
            track.alt = "GND" if alt == "ground" else (int(alt) if _number(alt) is not None else None)
            track.gs = _number(raw.get("gs"))
            track.track = _number(raw.get("track"))
            track.squawk = str(raw.get("squawk") or "").strip()
            if not track.callsign and hex_ not in self._unks:
                self._unks[hex_] = self._unk_next
                self._unk_next += 1
            track.unk = self._unks.get(hex_, 0)
            self.tracks[hex_] = track
        self._expire()
        self._announce()

    def _expire(self) -> None:
        now = self.clock()
        for hex_ in [h for h, t in self.tracks.items() if now - t.seen_at > self.stale_secs]:
            del self.tracks[hex_]

    def label(self, track: Track) -> str:
        return track.callsign or f"UNK{track.unk}"

    def _announce(self) -> None:
        """One log line when an aircraft first squawks an emergency code, one
        when it stops: never one per poll (spec, The log is a teletype)."""
        current = {h: t.squawk for h, t in self.tracks.items() if t.squawk in EMERGENCIES}
        for hex_, code in current.items():
            if self._announced.get(hex_) != code:
                track = self.tracks[hex_]
                distance, bearing = distance_bearing(self.lat, self.lon, track.lat, track.lon)
                self.on_note(
                    f"{self.label(track)} squawking {code} ({EMERGENCIES[code].lower()}), "
                    f"{round(distance)} nm {compass(bearing)}"
                )
                self._announced[hex_] = code
        for hex_ in [h for h in self._announced if h not in current]:
            code = self._announced.pop(hex_)
            track = self.tracks.get(hex_)
            name = self.label(track) if track else hex_.upper()
            self.on_note(f"{name} no longer squawking {code}")

    def frame(self) -> dict:
        now = self.clock()
        aircraft = []
        for track in sorted(self.tracks.values(), key=lambda t: t.hex):
            distance, bearing = (
                distance_bearing(self.lat, self.lon, track.lat, track.lon)
                if self.lat is not None else (0.0, 0.0)
            )
            aircraft.append({
                "hex": track.hex,
                "label": self.label(track),
                "type": track.type,
                "lat": round(track.lat, 5),
                "lon": round(track.lon, 5),
                "alt": track.alt,
                "gs": None if track.gs is None else round(track.gs),
                "trk": None if track.track is None else round(track.track),
                "sq": track.squawk,
                "age": round(now - track.seen_at, 1),
                "dist": round(distance, 1),
                "brg": round(bearing),
            })
        return {
            "t": "aircraft",
            "ok": not self.error,
            "error": self.error,
            "age": None if self.last_good is None else round(now - self.last_good, 1),
            "refresh": self.refresh_secs,
            "range": self.range_nm,
            "ac": aircraft,
        }
