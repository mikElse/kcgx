"""The radar's map: the committed world map clipped to one airport.

`tools/build_geodata.py` writes `data/geo.json.gz`. The server loads it once,
on the first airport that asks, and from then on clips it per airport by
bounding boxes alone: every line piece and point whose box meets the
airport's box goes to the page, nothing else. The page projects and draws;
the server never does geometry beyond the box test.

Coordinates stay in the file's integer units (1e-4 degree) all the way to
the page, which knows `q`. Longitudes near the antimeridian are shifted by
a whole turn so a field at 179.9 E sees the land at 179.9 W beside it
rather than a world away.
"""

from __future__ import annotations

import gzip
import json
import math
import threading
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "geo.json.gz"
NM_PER_DEGREE = 60.0
# The radar shows 40 nm and can zoom out to 160; send a margin past that so
# panning at full zoom out never runs off the map.
DEFAULT_RADIUS_NM = 200.0

_lock = threading.Lock()
_world: dict | None = None


def load(path: Path = DATA) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()))


def world() -> dict:
    """The whole map, loaded once. Thread safe: the server loads it in a
    worker thread so the event loop never waits on the parse."""
    global _world
    with _lock:
        if _world is None:
            _world = load()
        return _world


def box(lat: float, lon: float, radius_nm: float, q: int) -> tuple[int, int, int, int]:
    """The airport's box in file units. Longitude widens with latitude, and
    near a pole the box takes every longitude."""
    dlat = radius_nm / NM_PER_DEGREE
    if abs(lat) + dlat >= 90.0:
        dlon = 180.0  # the circle covers the pole: every longitude is in it
    else:
        dlon = min(180.0, dlat / math.cos(math.radians(abs(lat) + dlat)))
    return (
        round((lon - dlon) * q),
        round(max(-90.0, lat - dlat) * q),
        round((lon + dlon) * q),
        round(min(90.0, lat + dlat) * q),
    )


def _shifts(minx: int, maxx: int, q: int) -> tuple[int, ...]:
    """The whole-turn offsets that bring features across the antimeridian
    into the airport's frame."""
    turn = 360 * q
    out = [0]
    if minx < -180 * q:
        out.append(-turn)
    if maxx > 180 * q:
        out.append(turn)
    return tuple(out)


def clip(lat: float, lon: float, *, radius_nm: float = DEFAULT_RADIUS_NM, icao: str = "", data: dict | None = None) -> dict:
    data = world() if data is None else data
    q = data["q"]
    minx, miny, maxx, maxy = box(lat, lon, radius_nm, q)
    shifts = _shifts(minx, maxx, q)

    lines = {}
    for layer, pieces in data["lines"].items():
        kept = []
        for piece in pieces:
            if piece[1] > maxy or piece[3] < miny:
                continue
            for shift in shifts:
                if piece[0] + shift <= maxx and piece[2] + shift >= minx:
                    kept.append(piece[4:] if not shift else [piece[4] + shift, *piece[5:]])
                    break
        lines[layer] = kept

    def points(rows):
        kept = []
        for row in rows:
            x, y = row[0], row[1]
            if not miny <= y <= maxy:
                continue
            for shift in shifts:
                if minx <= x + shift <= maxx:
                    kept.append([x + shift, *row[1:]])
                    break
        return kept

    return {
        "q": q,
        "center": [round(lon * q), round(lat * q)],
        "radius_nm": radius_nm,
        "lines": lines,
        "points": {kind: points(rows) for kind, rows in data["points"].items()},
        "labels": {kind: points(rows) for kind, rows in data["labels"].items()},
        "runways": data["runways"].get(icao.upper(), []),
    }


@lru_cache(maxsize=8)
def clipped_json(icao: str, lat: float, lon: float) -> bytes:
    """The page's map for one airport, encoded once and kept for the next
    tab or the next visit to the same field."""
    return json.dumps(clip(lat, lon, icao=icao), separators=(",", ":")).encode("utf-8")
