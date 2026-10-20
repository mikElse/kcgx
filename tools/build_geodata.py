"""Regenerate src/kcgx/data/geo.json.gz, the radar's map, from public domain sources.

Run with:  uv run --project . python tools/build_geodata.py [--faa DIR]

Like airports.csv, the result is committed, so the radar needs no network
for its map and this runs only when the map should be refreshed. Sources
are downloaded into .geo-sources/ (gitignored) and reused from there:

* Natural Earth 10 m, pinned to a release: coastlines, lakes, rivers,
  country and state borders, populated places, peaks, state names.
* OurAirports (refreshed nightly; the build date is recorded): navaids,
  airports, and the runways of every airport in airports.csv.
* FAA NASR, from the 28 day subscription: class B, C and D airspace from
  class_airspace_shape_files.zip, and the Victor airways (the low altitude
  routes between VORs) from the cycle's CSV zip (AWY, FIX and NAV tables).
  The FAA's servers are not reachable from every network, so both are read
  from a folder you downloaded them to (--faa, default .geo-sources/):

      https://nfdc.faa.gov/webContent/28DaySub/<cycle>/class_airspace_shape_files.zip
      https://nfdc.faa.gov/webContent/28DaySub/extra/<DD_Mon_YYYY>_CSV.zip

  Without them those layers are empty and the build says so.

Everything is public domain. The output is deterministic for the same
inputs: no timestamps inside the gzip, sorted keys, fixed rounding.

Format (version 1), all coordinates integers in units of 1e-4 degree:

    lines:   {layer: [[minx, miny, maxx, maxy, x0, y0, dx1, dy1, ...], ...]}
             layers: coast, lake, river, country, state, airway,
                     airspace_b, airspace_c, airspace_d
    points:  {"city": [[x, y, name, rank]], "peak": [[x, y, name]],
              "navaid": [[x, y, ident, type]], "airport": [[x, y, label, size]]}
    labels:  {"state": [[x, y, name]]}
    runways: {icao: [[x1, y1, x2, y2], ...]}

Long lines are cut into pieces of at most PIECE points, each with its own
bounding box, so the server can clip the world to one airport by box tests
alone and never sends a continent's coastline for a 40 nm screen.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import itertools
import json
import math
import struct
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "kcgx" / "data" / "geo.json.gz"
AIRPORTS = ROOT / "src" / "kcgx" / "data" / "airports.csv"
CACHE = ROOT / ".geo-sources"

NATURAL_EARTH = "v5.1.2"
NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    + NATURAL_EARTH + "/geojson/{name}.geojson"
)
OA_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/{name}.csv"
FAA_ZIP = "class_airspace_shape_files.zip"
FAA_CSV_GLOB = "*_CSV.zip"
NAVAID_POINT_TYPES = ("VOR", "TACAN", "NDB", "DME")

Q = 10_000  # units per degree: about 11 m of latitude
TOLERANCE = 0.0015  # degrees, about 165 m: under a pixel at 40 nm on a big screen
PIECE = 64

LINE_LAYERS = {
    "coast": "ne_10m_coastline",
    "lake": "ne_10m_lakes",
    "river": "ne_10m_rivers_lake_centerlines",
    "country": "ne_10m_admin_0_boundary_lines_land",
    "state": "ne_10m_admin_1_states_provinces_lines",
}
VOR_TYPES = {"VOR", "VOR-DME", "VORTAC", "TACAN", "NDB", "NDB-DME", "DME"}
AIRPORT_SIZES = {"large_airport": "large", "medium_airport": "medium", "small_airport": "small"}
AIRSPACE_CLASSES = {"B": "airspace_b", "C": "airspace_c", "D": "airspace_d"}


# -- fetching ------------------------------------------------------------------


def fetch(url: str, cache: Path) -> Path:
    path = cache / url.rsplit("/", 1)[-1]
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        print(f"fetching {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=300) as response:
            path.write_bytes(response.read())
    return path


# -- geometry ------------------------------------------------------------------


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker, iterative, with longitude scaled by cos(latitude) so
    the tolerance is the same distance east-west as north-south."""
    if len(points) < 3:
        return points
    scale = math.cos(math.radians(sum(p[1] for p in points) / len(points)))
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first][0] * scale, points[first][1]
        bx, by = points[last][0] * scale, points[last][1]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        worst, index = 0.0, -1
        for i in range(first + 1, last):
            px, py = points[i][0] * scale, points[i][1]
            if length == 0:
                distance = math.hypot(px - ax, py - ay)
            else:
                distance = abs(dy * px - dx * py + bx * ay - by * ax) / length
            if distance > worst:
                worst, index = distance, i
        if worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))
    return [p for p, k in zip(points, keep, strict=True) if k]


def quantize(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for lon, lat in points:
        q = (round(lon * Q), round(lat * Q))
        if not out or out[-1] != q:
            out.append(q)
    return out


def pieces(points: list[tuple[int, int]]) -> list[list[int]]:
    """Cut a quantized line into overlapping pieces of at most PIECE points,
    each encoded as [minx, miny, maxx, maxy, x0, y0, dx1, dy1, ...]."""
    out = []
    if len(points) < 2:
        return out
    start = 0
    while start < len(points) - 1:
        chunk = points[start : start + PIECE]
        xs = [p[0] for p in chunk]
        ys = [p[1] for p in chunk]
        encoded = [min(xs), min(ys), max(xs), max(ys), chunk[0][0], chunk[0][1]]
        for (x0, y0), (x1, y1) in itertools.pairwise(chunk):
            encoded += [x1 - x0, y1 - y0]
        out.append(encoded)
        start += PIECE - 1
    return out


def lines_of(geometry: dict) -> list[list[tuple[float, float]]]:
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "LineString":
        return [coords]
    if kind == "MultiLineString":
        return list(coords)
    if kind == "Polygon":
        return list(coords)
    if kind == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon]
    return []


def line_layer(path: Path) -> list[list[int]]:
    data = json.loads(path.read_text())
    out = []
    for feature in data["features"]:
        if not feature.get("geometry"):
            continue
        for line in lines_of(feature["geometry"]):
            points = [(float(p[0]), float(p[1])) for p in line]
            out += pieces(quantize(simplify(points, TOLERANCE)))
    return out


# -- points ------------------------------------------------------------------


def q(value: str | float) -> int:
    return round(float(value) * Q)


def cities(path: Path) -> list[list]:
    out = []
    for f in json.loads(path.read_text())["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        out.append([q(lon), q(lat), p["name"].upper(), int(p["scalerank"])])
    return sorted(out, key=lambda r: (r[3], r[2], r[0], r[1]))


def peaks(path: Path) -> list[list]:
    out = []
    for f in json.loads(path.read_text())["features"]:
        p = f["properties"]
        if p.get("featurecla") not in ("mountain", "volcano"):
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        name = (p.get("name") or "").upper().replace("MOUNT ", "MT ")
        if name:
            out.append([q(lon), q(lat), name])
    return sorted(out, key=lambda r: (r[2], r[0], r[1]))


def state_labels(path: Path) -> list[list]:
    """Each state or province's own label point. Only countries that are
    drawn with state lines at a scale where a name helps: the ones Natural
    Earth gives a low label rank."""
    out = []
    for f in json.loads(path.read_text())["features"]:
        p = f["properties"]
        lon, lat = p.get("longitude"), p.get("latitude")
        if lon is None or lat is None or not p.get("name") or (p.get("labelrank") or 9) > 6:
            continue
        out.append([q(lon), q(lat), p["name"].upper()])
    return sorted(out, key=lambda r: (r[2], r[0], r[1]))


def navaids(path: Path) -> list[list]:
    out = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["type"] not in VOR_TYPES or not row["ident"]:
                continue
            out.append([q(row["longitude_deg"]), q(row["latitude_deg"]), row["ident"].upper(), row["type"]])
    return sorted(out, key=lambda r: (r[2], r[0], r[1]))


def airports(path: Path) -> list[list]:
    """Other airports as triangles, labelled the way a chart labels them:
    the local code (FAA LID in the US), else IATA, else the ident."""
    out = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            size = AIRPORT_SIZES.get(row["type"])
            if size is None:
                continue
            label = (row["local_code"] or row["iata_code"] or row["ident"]).strip().upper()
            if size == "small" and not (label.isalpha() and 3 <= len(label) <= 4):
                continue  # strips, heliports with numbers: clutter, not landmarks
            out.append([q(row["longitude_deg"]), q(row["latitude_deg"]), label, size])
    return sorted(out, key=lambda r: (r[2], r[0], r[1]))


def runways(path: Path, keep: set[str]) -> dict[str, list[list[int]]]:
    out: dict[str, list[list[int]]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            icao = row["airport_ident"].upper()
            if icao not in keep or row["closed"] == "1":
                continue
            ends = [row["le_longitude_deg"], row["le_latitude_deg"], row["he_longitude_deg"], row["he_latitude_deg"]]
            if not all(ends):
                continue
            out.setdefault(icao, []).append([q(v) for v in ends])
    return {k: sorted(v) for k, v in sorted(out.items())}


def dataset_icaos() -> set[str]:
    with AIRPORTS.open(encoding="utf-8") as handle:
        rows = csv.reader(line for line in handle if not line.startswith("#"))
        next(rows)
        return {row[0] for row in rows}


# -- FAA airspace ------------------------------------------------------------


def _dbf_records(data: bytes) -> list[dict[str, str]]:
    count, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields = []
    offset = 32
    while data[offset] != 0x0D:
        name = data[offset : offset + 11].split(b"\0", 1)[0].decode("ascii")
        fields.append((name, data[offset + 16]))
        offset += 32
    out = []
    for i in range(count):
        start = header_len + i * record_len + 1
        record, at = {}, start
        for name, length in fields:
            record[name] = data[at : at + length].decode("latin-1").strip()
            at += length
        out.append(record)
    return out


def _shp_polygons(data: bytes) -> list[list[list[tuple[float, float]]]]:
    """Every record's rings from a polygon (type 5) shapefile."""
    out, offset = [], 100
    while offset < len(data):
        _, length = struct.unpack(">II", data[offset : offset + 8])
        body = data[offset + 8 : offset + 8 + length * 2]
        offset += 8 + length * 2
        shape = struct.unpack("<i", body[:4])[0]
        if shape not in (5, 15, 25):  # Polygon, PolygonZ, PolygonM: x, y come first in all three
            out.append([])
            continue
        parts, count = struct.unpack("<ii", body[36:44])
        starts = list(struct.unpack(f"<{parts}i", body[44 : 44 + 4 * parts])) + [count]
        base = 44 + 4 * parts
        coords = [struct.unpack("<dd", body[base + 16 * i : base + 16 * i + 16]) for i in range(count)]
        out.append([coords[starts[j] : starts[j + 1]] for j in range(parts)])
    return out


def airspace(folder: Path) -> dict[str, list[list[int]]] | None:
    archive = folder / FAA_ZIP
    if not archive.exists():
        return None
    layers: dict[str, list[list[int]]] = {name: [] for name in AIRSPACE_CLASSES.values()}
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        shp = next(n for n in names if n.lower().endswith("class_airspace.shp"))
        dbf = shp[:-4] + ".dbf"
        shapes = _shp_polygons(z.read(shp))
        records = _dbf_records(z.read(dbf))
    for rings, record in zip(shapes, records, strict=True):
        layer = AIRSPACE_CLASSES.get(record.get("CLASS", ""))
        if layer is None:
            continue
        for ring in rings:
            layers[layer] += pieces(quantize(simplify(list(ring), TOLERANCE / 3)))
    return layers


def airways(folder: Path) -> list[list[int]] | None:
    """Victor airways as lines, each chained from its segments in order and
    broken wherever the FAA marks a gap. Points are looked up by name: a
    navaid in NAV_BASE when the segment says it starts at one, otherwise a
    fix in FIX_BASE."""
    archives = sorted(folder.glob(FAA_CSV_GLOB))
    if not archives:
        return None
    with zipfile.ZipFile(archives[-1]) as z:
        def table(name):
            with z.open(name) as handle:
                return list(csv.DictReader(io.TextIOWrapper(handle, "latin-1")))

        navs: dict[str, tuple[float, float]] = {}
        for row in table("NAV_BASE.csv"):
            # A VOR and an NDB can share an ident: the VOR is the one airways use.
            if row["NAV_ID"] not in navs or "VOR" in row["NAV_TYPE"]:
                navs[row["NAV_ID"]] = (float(row["LONG_DECIMAL"]), float(row["LAT_DECIMAL"]))
        fixes = {
            row["FIX_ID"]: (float(row["LONG_DECIMAL"]), float(row["LAT_DECIMAL"]))
            for row in table("FIX_BASE.csv")
        }
        segments = table("AWY_SEG_ALT.csv")

    def where(name: str, kind: str) -> tuple[float, float] | None:
        name = name.strip()
        if any(t in kind for t in NAVAID_POINT_TYPES):
            return navs.get(name) or fixes.get(name)
        return fixes.get(name) or navs.get(name)

    out: list[list[int]] = []
    routes: dict[tuple[str, str], list[dict]] = {}
    for row in segments:
        if row["AWY_ID"].startswith("V"):
            routes.setdefault((row["AWY_LOCATION"], row["AWY_ID"]), []).append(row)
    for _, rows in sorted(routes.items()):
        rows.sort(key=lambda r: int(r["POINT_SEQ"]))
        line: list[tuple[float, float]] = []
        for row in rows:
            start = where(row["FROM_POINT"], row["FROM_PT_TYPE"])
            end = where(row["TO_POINT"], "")
            if start is None or end is None or row["AWY_SEG_GAP_FLAG"] == "Y":
                out += pieces(quantize(line))
                line = []
                continue
            if not line or line[-1] != start:
                out += pieces(quantize(line))
                line = [start]
            line.append(end)
        out += pieces(quantize(line))
    return out


# -- the build -----------------------------------------------------------------


def build(cache: Path, faa: Path) -> dict:
    ne = {name: fetch(NE_URL.format(name=name), cache) for name in (
        *LINE_LAYERS.values(),
        "ne_10m_populated_places_simple",
        "ne_10m_geography_regions_elevation_points",
        "ne_10m_admin_1_states_provinces",
    )}
    oa = {name: fetch(OA_URL.format(name=name), cache) for name in ("navaids", "airports", "runways")}

    lines = {layer: line_layer(ne[name]) for layer, name in LINE_LAYERS.items()}
    sky = airspace(faa)
    if sky is None:
        print(f"no {FAA_ZIP} in {faa}: the airspace layers are empty", file=sys.stderr)
        sky = {name: [] for name in AIRSPACE_CLASSES.values()}
    lines.update(sky)
    routes = airways(faa)
    if routes is None:
        print(f"no {FAA_CSV_GLOB} in {faa}: the airway layer is empty", file=sys.stderr)
    lines["airway"] = routes or []

    return {
        "format": 1,
        "built": dt.datetime.now(dt.UTC).date().isoformat(),
        "q": Q,
        "sources": {
            "natural_earth": NATURAL_EARTH,
            "ourairports": OA_URL.format(name="*"),
            "faa_airspace": FAA_ZIP if any(sky.values()) else None,
            "faa_airways": sorted(p.name for p in faa.glob(FAA_CSV_GLOB))[-1:] or None,
        },
        "lines": lines,
        "points": {
            "city": cities(ne["ne_10m_populated_places_simple"]),
            "peak": peaks(ne["ne_10m_geography_regions_elevation_points"]),
            "navaid": navaids(oa["navaids"]),
            "airport": airports(oa["airports"]),
        },
        "labels": {"state": state_labels(ne["ne_10m_admin_1_states_provinces"])},
        "runways": runways(oa["runways"], dataset_icaos()),
    }


def write(geo: dict, out: Path = OUT) -> None:
    text = json.dumps(geo, separators=(",", ":"), sort_keys=True).encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as handle:
        handle.write(text)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buffer.getvalue())


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", type=Path, default=CACHE, help="where sources are downloaded to")
    parser.add_argument("--faa", type=Path, default=CACHE, help=f"folder holding {FAA_ZIP}")
    args = parser.parse_args(argv)
    geo = build(args.cache, args.faa)
    write(geo)
    counts = {k: len(v) for k, v in geo["lines"].items()}
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB): {counts}")


if __name__ == "__main__":
    main()
