"""The radar's traffic: adsb.lol polled from the server for every open page.

Polled here and not in the browser because adsb.lol refuses a request with
no contactable User-Agent and a browser may not set one, because one poller
serves every tab, and because the polling discipline (15 s, backing off
when refused) is per address (spec, Radar).

`Radar` owns the picture for the current airport: the aircraft seen, when
each was last seen, the UNK numbers given to aircraft with no callsign, and
which emergency squawks have been announced. A refused poll keeps the last
good picture and backs off: the refresh doubled per failure in a row,
capped at two minutes or four refreshes, whichever is longer (so it backs
off at least twice at any rate: 15, 30, 60, 120 s; at 120, 240, 480 s),
reset by the first success. Aircraft not seen for `stale_secs` drop out.

The range is a setting (kcgx.prefs, `range_nm`), changed while running by
`set_range`. A new airport is polled at once; a new range waits for the
next scheduled poll, so a dragged slider is never a burst of requests. The
poll interval (`poll_secs`, by `set_refresh`) and the two thresholds for
parked traffic (`ground_gs`, `ground_alt`, by `set_ground`) are settings
too, and likewise never poll.

Parked traffic (phase G decision 9): a track is still while its ground
speed is under `ground_gs` and it reports GND or a barometric altitude under
`ground_alt`. The frame's `still` is how many seconds it has been so, counted
from the poll it first qualified; one poll that finds it otherwise resets it
to 0. A poll that does not hear from it at all changes nothing. Counted
here, not in the page, so every tab agrees and a reload keeps the clock.

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
# The same identifying string setup.sh's check sends. KCGX_ADSB_UA
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


def _text(value: Any) -> str | None:
    """A text field as the page shows it: upper case, or None when the reply
    has none (missing, empty, or not text at all)."""
    if not isinstance(value, str):
        return None
    return value.strip().upper() or None


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
    # In adsb.lol's OpenAPI document but optional: None when the reply
    # leaves them out. readsb's names: r, baro_rate (ft/min), category (A0
    # to D7). Its desc and ownOp are in neither the document nor a live
    # /v2/point reply (checked 2026-11-14), so they are not kept.
    reg: str | None = None
    vs: float | None = None
    cat: str | None = None
    still_since: float | None = None  # our clock, the poll it first qualified as parked


@dataclass
class Radar:
    """The current airport's picture. Call `retarget` on an airport change,
    `set_range`, `set_refresh` and `set_ground` when those settings change,
    `poll` to take one picture (or let `run` do it on its schedule)."""

    on_frame: Callable[[dict], None]
    on_note: Callable[[str], None]
    fetch: Fetch = fetch_adsb_lol
    refresh_secs: int = 15
    range_nm: int = 40
    stale_secs: int = 60
    ground_gs: int = 5  # kt: slower than this may be parked
    ground_alt: int = 0  # ft: under this, or GND, is on the ground; 0 is GND only
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

    # -- the range ---------------------------------------------------------------

    def set_range(self, range_nm: int) -> None:
        """A new range, asked for from the next scheduled poll on. It never
        triggers one: adsb.lol asks for no more than a request every 15 s,
        and a slider being dragged sends a change per step. What is beyond
        a shorter range goes at once; what a longer one adds arrives with
        the next poll."""
        if range_nm == self.range_nm:
            return
        self.range_nm = range_nm
        self._trim()
        self.on_frame(self.frame())

    # -- the pace and parked traffic ------------------------------------------------

    def set_refresh(self, secs: int) -> None:
        """A new poll interval. It sets the base of `delay` and nothing
        else: the back-off still doubles it per failure, the 15 s floor and
        the cap (see `delay`) hold, and the wait already begun runs out first.
        It never triggers a poll, for the same reason a new range does not."""
        self.refresh_secs = secs

    def set_ground(self, gs: int, alt: int) -> None:
        """New thresholds for parked traffic, judged from the next poll on.
        Nothing is sent: no track's `still` changes until then."""
        self.ground_gs, self.ground_alt = gs, alt

    def _parked(self, track: Track) -> bool:
        if track.gs is None or not track.gs < self.ground_gs:
            return False
        if track.alt == "GND":
            return True
        # 0 is GND only (kcgx.prefs), even where a field below sea level
        # reports a barometric altitude under it.
        return self.ground_alt > 0 and isinstance(track.alt, int) and track.alt < self.ground_alt

    def _beyond(self, lat: float, lon: float) -> bool:
        return distance_bearing(self.lat, self.lon, lat, lon)[0] > self.range_nm

    def _trim(self) -> None:
        """Drop every aircraft beyond the range."""
        if self.lat is None or self.lon is None:
            return
        for hex_ in [h for h, t in self.tracks.items() if self._beyond(t.lat, t.lon)]:
            self._drop(hex_)

    def _drop(self, hex_: str) -> None:
        """Out of range, and out of the picture. Its emergency squawk, if it
        has one, is forgotten without a word: it has not stopped squawking,
        and it is announced afresh if a wider range brings it back."""
        self.tracks.pop(hex_, None)
        self._announced.pop(hex_, None)

    # -- polling -----------------------------------------------------------------

    def delay(self) -> float:
        """Seconds until the next poll: the refresh, doubled per failure in a
        row, capped at two minutes or four refreshes, whichever is longer."""
        refresh = max(MIN_REFRESH_SECS, self.refresh_secs)
        if not self.failures:
            return float(refresh)
        cap = max(BACKOFF_CAP_SECS, 4 * refresh)
        return float(min(cap, refresh * 2 ** self.failures))

    async def poll(self) -> None:
        if self.lat is None or self.lon is None:
            return
        generation, lat, lon, asked_nm = self._generation, self.lat, self.lon, self.range_nm
        try:
            data = await asyncio.to_thread(self.fetch, lat, lon, asked_nm)
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
        self.merge(data, cut=self.range_nm < asked_nm)  # the range shrank while we were asking
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

    def merge(self, data: dict, *, cut: bool = False) -> None:
        """Take a reply into the picture. `cut` is for a reply asked for at a
        wider range than the one set since: what it holds beyond the range
        is left out before it can be numbered or announced."""
        now = self.clock()
        for raw in data.get("ac") or []:
            hex_ = str(raw.get("hex") or "").lower().strip()
            lat, lon = _number(raw.get("lat")), _number(raw.get("lon"))
            if not hex_ or lat is None or lon is None:
                continue
            if cut and self._beyond(lat, lon):
                self._drop(hex_)  # and not left where it was last seen
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
            track.reg = _text(raw.get("r"))
            track.vs = _number(raw.get("baro_rate"))
            track.cat = _text(raw.get("category"))
            if not self._parked(track):
                track.still_since = None
            elif track.still_since is None:
                track.still_since = now
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
                "reg": track.reg,
                "vs": None if track.vs is None else round(track.vs),
                "cat": track.cat,
                "still": 0 if track.still_since is None else round(now - track.still_since),
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
