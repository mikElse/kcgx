# Web Cockpit Phase D: The Radar

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put live traffic on the wall. The server polls adsb.lol for the
current airport, keeps the picture (stale aircraft, UNK numbers, emergency
squawks) and sends it to every page. The page draws it on our own vector
radar: a committed public domain map of coastlines, rivers, borders,
cities, peaks, navaids, airports, runways, class B, C and D airspace and
Victor airways, projected azimuthal equidistant around the field, with
aircraft dead reckoned between polls, fading trails, click to focus, dim
place names that brighten under the pointer, pan and zoom, and a sortable
tracks table. The EMERG lamp and the teletype announce emergency squawks.

**Architecture:**

| Piece | Job |
|---|---|
| `tools/build_geodata.py` | builds `src/kcgx/data/geo.json.gz` from Natural Earth, OurAirports and the FAA, deterministically |
| `kcgx.geodata` | loads the map once; clips it to an airport by box tests; `GET /api/geo?icao=` serves it |
| `kcgx.radar` | the poller (backoff, 15 s floor), the picture (merge, stale, UNK), emergencies, the `aircraft` frame |
| `kcgx.station` | owns a `Radar`, retargets it on every airport change, puts its frame in the snapshot |
| `kcgx.server` | runs the radar's poll loop as a task; `--demo` hands it `kcgx.demo.traffic` |
| `radar.js` | projection, the static layer (map, rings, labels, home), the moving layer (aircraft, trails, focus), pointer handling |
| `tracks.js`, `focus.js` | the table, and the one focused aircraft both share |

**Tech Stack:** as phase C. No new dependency of any kind: the build tool
reads GeoJSON, CSV and shapefiles with the standard library, the radar
uses `urllib`, and the page is Canvas 2D.

**Spec:** `docs/superpowers/specs/2026-10-18-web-cockpit-design.md`, sections
"Radar", "Visual language", "Rendering", "Display effects", "Map data".
The mockup is the design canvas published during planning; where spec and
mockup disagree, the mockup is the intent.

## Decisions this plan makes that the spec did not

All written into the spec on 2026-10-19, in the same commit as this plan.

1. **No WebGL pass.** Glow is Canvas 2D shadow blur with additive blending;
   persistence is a separate moving layer that fades 45% a frame instead
   of clearing (VECTOR and CRT only); line draw on traces the map over two
   seconds when it arrives. Flicker, jitter, vignette, scanlines, corners
   and fringe stay CSS, as phase C built them. WebGL stays the escape hatch.
2. **No Hershey glyphs.** Every radar label is Share Tech Mono drawn on the
   canvas, as in the approved mockup. Nothing new is vendored.
3. **The map is one file**, `src/kcgx/data/geo.json.gz` (4.7 MB): integers
   in 1e-4 degree, lines simplified to about 165 m and cut into pieces of at
   most 64 points with their boxes. The server sends the 200 nm around the
   field (5 to 60 KB) from `GET /api/geo?icao=`, asked by ICAO so a page
   never draws one field's map around another.
4. **Sources.** Natural Earth pinned to v5.1.2 and OurAirports, both from
   their GitHub repositories (reachable from every network here). The FAA
   archives are read from `.geo-sources/` (gitignored), where they were
   downloaded on the Mac, because the FAA's servers were not reachable from
   the sandboxes. **The built map is committed with this plan**, like phase
   C's fonts: Task 2 checks it rather than rebuilding it.
5. **Victor airways are a layer**, the blue dashed lines of the palette
   table, chained from the FAA's segment table; jet, RNAV and other routes
   are left off. Navaids on screen are the VOR family; small airports
   appear from 1.5 times zoom.
6. **Labels never overlap**: placed greedily in priority order, and a label
   that does not fit is dropped, its symbol kept.
7. **Coastlines are all cyan** (Natural Earth's carry no country); country
   borders are green and dashed; state lines dim.
8. **The picture is the server's**: UNK numbers, stale drops (60 s; the page
   starts fading at 30), emergency lines, distance and bearing. A late reply
   for the previous airport is thrown away.
9. **Config keys are whole numbers**: `radar_refresh_secs` (15, and never
   less), `radar_range_nm` (40), `radar_stale_secs` (60).
10. **Pan and zoom**: drag to pan, wheel to zoom about the pointer from 0.25
    to 6 times, RECENTRE resets; the title strip shows the pointer's bearing
    and distance from the field.
11. **The table scrolls; it does not collapse** to a summary line.
12. **Screenshot comparisons are still not built**; the browser tests check
    behaviour, and the look was checked by eye against the mockup.
13. **The page exposes `window.kcgx = { radar, store }`** for the browser
    tests: the radar's `debug()` and a way to hand the store a frame.

## Global Constraints

- Work in the `feat/web-cockpit` worktree at `/Users/mikelse/kcgx_web`.
- **No new dependency.**
- **The web modules never import Textual**: `kcgx.geodata` and
  `kcgx.radar` join `WEB_MODULES`.
- **No test touches the network.** The radar's fetch is injected; the
  server tests run with `radar=False` or a fake fetch; the browser tests'
  server is `--demo`, whose traffic is synthetic.
- **Nothing polls adsb.lol faster than every 15 s**, whatever the config says.
- **No test writes to `~/.local/state/kcgx/` or `~/.cache/squelch/`.**
- **Every action is a click** (spec): no keyboard shortcuts.
- Run everything through uv from the repo root, with the browser group:
  `cd /Users/mikelse/kcgx_web && uv run --group dev --group browser pytest -q`
- The suite is **930 tests** at the start (on the Mac, where the root-only
  setup test runs) and **1008** at the end.
- **Existing tests change in two places only:** `test_web_imports.py` gains
  two module names, and `test_server.py`'s `app()` adds `radar=False` to
  its options so no server test polls. Everything else is new tests at the
  ends of files. Check with `git diff main -- tests/`.
- **Revert-check every new test.**
- Commit after every task. End each message with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```

---

## File Structure

**Create:** `tools/build_geodata.py`, `src/kcgx/geodata.py`, `src/kcgx/radar.py`,
`src/kcgx/web/static/js/focus.js`, `src/kcgx/web/static/js/tracks.js`,
`tests/test_build_geodata.py`, `tests/test_geodata.py`, `tests/test_radar.py`.
`src/kcgx/data/geo.json.gz` is **already committed with this plan**.

**Modify:** `src/squelch/config.py` and `tests/test_config.py` (Task 1),
`.gitignore` (Task 2), `tests/test_web_imports.py` (Tasks 3 and 4),
`src/kcgx/protocol.py`, `src/kcgx/station.py` and `tests/test_station.py`
(Task 5), `src/kcgx/demo.py` and `tests/test_demo.py` (Task 6),
`src/kcgx/server.py` and `tests/test_server.py` (Task 7), the page (Task 8),
`tests/test_page.py` (Task 9), `docs/README.md` (Task 11).

## The protocol at the end of phase D

| Direction | What | Carries |
|---|---|---|
| server to page | `snapshot` | gains `radar`: the latest `aircraft` frame, or null |
| server to page | `aircraft` | `ok`, `error` (`ERR 429`, `ERR 403`, `NO CONNECTION`, `BAD REPLY` or empty), `age` (s since the last good poll, null before one), `refresh`, `range`, `ac`: `hex`, `label`, `type`, `lat`, `lon`, `alt` (ft or `GND`), `gs`, `trk`, `sq`, `age`, `dist`, `brg` |
| HTTP | `GET /api/geo?icao=` | `q`, `center`, `radius_nm`, `lines` (per layer, `[x0, y0, dx, dy, ...]`), `points`, `labels`, `runways`; 404 for an unknown airport |

---

### Task 1: The radar's config keys

**Files:** `src/squelch/config.py`, `tests/test_config.py`.

- [ ] **Step 1: Tests.** Apply:

```diff
diff --git a/tests/test_config.py b/tests/test_config.py
index 2bda36b..3523d1d 100644
--- a/tests/test_config.py
+++ b/tests/test_config.py
@@ -164,3 +164,22 @@ def test_the_buffer_can_be_tuned(tmp_path):
     path = tmp_path / "squelch.toml"
     path.write_text("buffer_seconds = 8.0\n")
     assert load_config(path).buffer_seconds == 8.0
+
+
+def test_the_radar_keys_default_to_adsb_lols_pace():
+    cfg = Config()
+    assert (cfg.radar_refresh_secs, cfg.radar_range_nm, cfg.radar_stale_secs) == (15, 40, 60)
+
+
+def test_the_radar_keys_can_be_configured(tmp_path):
+    path = tmp_path / "squelch.toml"
+    path.write_text("radar_refresh_secs = 30\nradar_range_nm = 25\nradar_stale_secs = 90\n")
+    cfg = load_config(path)
+    assert (cfg.radar_refresh_secs, cfg.radar_range_nm, cfg.radar_stale_secs) == (30, 25, 90)
+
+
+def test_a_fractional_radar_range_is_rejected(tmp_path):
+    path = tmp_path / "squelch.toml"
+    path.write_text("radar_range_nm = 40.5\n")
+    with pytest.raises(ConfigError, match="radar_range_nm"):
+        load_config(path)
```

- [ ] **Step 2:** They fail: `AttributeError: 'Config' object has no attribute 'radar_refresh_secs'`.
- [ ] **Step 3:** Apply:

```diff
diff --git a/src/squelch/config.py b/src/squelch/config.py
index 0aecb03..c200f3a 100644
--- a/src/squelch/config.py
+++ b/src/squelch/config.py
@@ -46,6 +46,13 @@ class Config:
     # past seven; feeds beyond this are parked instead of left knocking.
     # See slots.py for the measurement.
     max_streams: int = 7
+    # The web cockpit's radar (kcgx.radar). adsb.lol asks for no more than
+    # one request every 15 s per address; a refused poll backs off from
+    # there. The range is the circle asked for, in nautical miles, and an
+    # aircraft not heard from for radar_stale_secs drops off the screen.
+    radar_refresh_secs: int = 15
+    radar_range_nm: int = 40
+    radar_stale_secs: int = 60
 
 
 def load_config(path: Path | None = None) -> Config:
```

- [ ] **Step 4:** Suite: **933 passed**. Commit `feat(config): the radar's interval, range and stale time`.

---

### Task 2: The map's build tool, and the map

**Files:** Create `tools/build_geodata.py`, `tests/test_build_geodata.py`;
modify `.gitignore`. `src/kcgx/data/geo.json.gz` is already committed.

- [ ] **Step 1: Tests.** Create `tests/test_build_geodata.py`:

```python
"""The map's build tool (tools/build_geodata.py), without the network."""

from __future__ import annotations

import gzip
import importlib.util
import io
import struct
import zipfile
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "build_geodata.py"


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("build_geodata", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_simplify_keeps_the_ends_and_drops_points_on_the_line(build):
    line = [(0.0, 0.0), (0.5, 0.0001), (1.0, 0.0)]
    assert build.simplify(line, 0.001) == [(0.0, 0.0), (1.0, 0.0)]


def test_simplify_keeps_a_corner(build):
    line = [(0.0, 0.0), (0.5, 0.5), (1.0, 0.0)]
    assert build.simplify(line, 0.001) == line


def test_quantize_rounds_and_drops_repeats(build):
    assert build.quantize([(1.00001, 2.0), (1.00002, 2.0), (1.0003, 2.0)]) == [(10000, 20000), (10003, 20000)]


def test_pieces_overlap_by_one_point_and_carry_their_boxes(build):
    points = [(i, i % 3) for i in range(100)]
    out = build.pieces(points)
    assert len(out) == 2
    first, second = out
    assert first[:4] == [0, 0, 63, 2]
    assert second[4:6] == [63, 63 % 3]  # starts where the first ended
    # decoding the deltas gives the points back
    x, y, decoded = first[4], first[5], [(first[4], first[5])]
    for dx, dy in zip(first[6::2], first[7::2], strict=True):
        x, y = x + dx, y + dy
        decoded.append((x, y))
    assert decoded == points[:64]


def test_a_single_point_makes_no_piece(build):
    assert build.pieces([(1, 1)]) == []


def test_the_output_is_the_same_bytes_every_time(build, tmp_path):
    geo = {"format": 1, "lines": {"coast": [[0, 0, 1, 1, 0, 0, 1, 1]]}}
    build.write(geo, tmp_path / "a.json.gz")
    build.write(geo, tmp_path / "b.json.gz")
    a, b = (tmp_path / "a.json.gz").read_bytes(), (tmp_path / "b.json.gz").read_bytes()
    assert a == b
    assert a[4:8] == b"\0\0\0\0", "the gzip header carries a timestamp"
    assert gzip.decompress(a) == b'{"format":1,"lines":{"coast":[[0,0,1,1,0,0,1,1]]}}'


def test_small_airports_with_numbers_are_left_out(build, tmp_path):
    path = tmp_path / "airports.csv"
    path.write_text(
        "ident,type,local_code,iata_code,latitude_deg,longitude_deg\n"
        "KTTD,small_airport,TTD,,45.55,-122.40\n"
        "OR12,small_airport,OR12,,45.0,-122.0\n"
        "KPDX,large_airport,PDX,PDX,45.59,-122.60\n"
        "X1,heliport,,,45.0,-122.0\n"
    )
    assert [row[2] for row in build.airports(path)] == ["PDX", "TTD"]


def _shapefile(rings, shape_type=5):
    """A one-record polygon shapefile and its dbf, in memory. The FAA's is
    PolygonZ (15): x and y come first, the z values after, which the reader
    never needs."""
    coords = [p for ring in rings for p in ring]
    parts = [0]
    for ring in rings[:-1]:
        parts.append(parts[-1] + len(ring))
    body = struct.pack("<i", shape_type) + struct.pack("<4d", 0, 0, 0, 0)
    body += struct.pack("<ii", len(rings), len(coords)) + struct.pack(f"<{len(parts)}i", *parts)
    body += b"".join(struct.pack("<dd", *p) for p in coords)
    if shape_type == 15:
        body += struct.pack("<2d", 0, 0) + b"".join(struct.pack("<d", 0) for _ in coords)
    shp = b"\0" * 100 + struct.pack(">II", 1, len(body) // 2) + body
    field = b"CLASS".ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([1]) + b"\0" * 15
    header = struct.pack("<BBBBIHH", 3, 0, 0, 0, 1, 32 + 32 + 1, 2) + b"\0" * 20
    dbf = header + field + b"\x0d" + b" B" + b"\x1a"
    return shp, dbf


@pytest.mark.parametrize("shape_type", [5, 15])
def test_faa_airspace_is_read_from_its_shapefile(build, tmp_path, shape_type):
    ring = [(-122.7, 45.5), (-122.5, 45.5), (-122.5, 45.7), (-122.7, 45.5)]
    shp, dbf = _shapefile([ring], shape_type)
    with zipfile.ZipFile(tmp_path / build.FAA_ZIP, "w") as z:
        z.writestr("Shape_Files/Class_Airspace.shp", shp)
        z.writestr("Shape_Files/Class_Airspace.dbf", dbf)
    layers = build.airspace(tmp_path)
    assert len(layers["airspace_b"]) == 1 and layers["airspace_c"] == []
    assert layers["airspace_b"][0][4:6] == [-1227000, 455000]


def test_without_the_faa_files_there_is_no_airspace(build, tmp_path):
    assert build.airspace(tmp_path) is None


def _nasr_csv(path, segments):
    """A cycle's CSV zip with just the three tables airways need."""
    def table(header, rows):
        out = io.StringIO()
        out.write(",".join(header) + "\n")
        for row in rows:
            out.write(",".join(row) + "\n")
        return out.getvalue()

    with zipfile.ZipFile(path, "w") as z:
        z.writestr("NAV_BASE.csv", table(
            ["NAV_ID", "NAV_TYPE", "LAT_DECIMAL", "LONG_DECIMAL"],
            [["BTG", "NDB", "1", "1"], ["BTG", "VORTAC", "45.75", "-122.59"], ["UBG", "VOR/DME", "45.35", "-122.97"]],
        ))
        z.writestr("FIX_BASE.csv", table(
            ["FIX_ID", "LAT_DECIMAL", "LONG_DECIMAL"], [["OSWEG", "45.5", "-122.8"], ["LONLY", "44.0", "-121.0"]],
        ))
        z.writestr("AWY_SEG_ALT.csv", table(
            ["AWY_LOCATION", "AWY_ID", "POINT_SEQ", "FROM_POINT", "FROM_PT_TYPE", "TO_POINT", "AWY_SEG_GAP_FLAG"],
            segments,
        ))


def test_victor_airways_are_chained_from_their_segments(build, tmp_path):
    _nasr_csv(tmp_path / "01_Oct_2026_CSV.zip", [
        ["C", "V23", "20", "OSWEG", "RP", "UBG", "N"],
        ["C", "V23", "10", "BTG", "VORTAC", "OSWEG", "N"],
        ["C", "J5", "10", "BTG", "VORTAC", "UBG", "N"],  # a jet route: not drawn
    ])
    lines = build.airways(tmp_path)
    assert len(lines) == 1
    line = lines[0]
    assert line[4:6] == [-1225900, 457500]  # BTG the VORTAC, not BTG the NDB
    assert len(line) == 4 + 2 + 2 * 2  # box, start, two more points


def test_a_gap_or_an_unknown_point_breaks_the_airway(build, tmp_path):
    _nasr_csv(tmp_path / "01_Oct_2026_CSV.zip", [
        ["C", "V1", "10", "BTG", "VORTAC", "OSWEG", "N"],
        ["C", "V1", "20", "OSWEG", "RP", "NOWHERE", "N"],
        ["C", "V1", "30", "UBG", "VOR/DME", "LONLY", "Y"],
        ["C", "V1", "40", "LONLY", "RP", "UBG", "N"],
    ])
    lines = build.airways(tmp_path)
    assert [len(line) for line in lines] == [8, 8]  # BTG-OSWEG, then LONLY-UBG


def test_without_the_csv_zip_there_are_no_airways(build, tmp_path):
    assert build.airways(tmp_path) is None
```

- [ ] **Step 2:** They fail: `FileNotFoundError` for `tools/build_geodata.py`.
- [ ] **Step 3: The tool.** Create `tools/build_geodata.py`:

```python
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
```

- [ ] **Step 4:** Apply to `.gitignore`:

```diff
diff --git a/.gitignore b/.gitignore
index 2921a90..f719039 100644
--- a/.gitignore
+++ b/.gitignore
@@ -15,3 +15,6 @@ src/squelch/assets/audio/*.mp3
 
 # Reference stills for the web cockpit spec; not ours to publish.
 war_games_examples/
+
+# Downloaded map sources for tools/build_geodata.py; the built map is committed.
+.geo-sources/
```

- [ ] **Step 5:** `uv run pytest -q tests/test_build_geodata.py`: 13 passed.
- [ ] **Step 6: The map.** It is already in place. Check it is the one the
  dry run tested:

```
shasum -a 256 src/kcgx/data/geo.json.gz
47d7a2c6fe58acf5d79e9ad1fe1921ddf954159f7e9c45914b950598fdd0aa03  src/kcgx/data/geo.json.gz
```

  It was built on 2026-10-19 with Natural Earth v5.1.2, that day's
  OurAirports, and the FAA's 2026-10-01 cycle (`class_airspace_shape_files.zip`
  and `01_Oct_2026_CSV.zip` in `.geo-sources/`). Rebuilding it is
  `uv run python tools/build_geodata.py`; with the same sources it gives the
  same bytes, and a later OurAirports gives a slightly different, equally
  valid file. Do not rebuild it in this task.
- [ ] **Step 7:** Suite: **946 passed**. Commit `feat(radar): the map's build tool`.

---

### Task 3: `kcgx.geodata`

**Files:** Create `src/kcgx/geodata.py`, `tests/test_geodata.py`; add
`"kcgx.geodata"` to `WEB_MODULES` in `tests/test_web_imports.py`.

- [ ] **Step 1: Tests.** Create `tests/test_geodata.py`:

```python
"""The radar's map: the committed world clipped to one airport (kcgx.geodata)."""

from __future__ import annotations

import json

from kcgx import geodata

Q = 10_000


def world(lines=None, points=None, labels=None, runways=None):
    return {
        "q": Q,
        "lines": lines or {},
        "points": points or {},
        "labels": labels or {},
        "runways": runways or {},
    }


def piece(x0, y0, *deltas):
    """A line piece in file form: its box, its start, its deltas."""
    xs, ys, x, y = [x0], [y0], x0, y0
    for dx, dy in zip(deltas[::2], deltas[1::2], strict=True):
        x, y = x + dx, y + dy
        xs.append(x)
        ys.append(y)
    return [min(xs), min(ys), max(xs), max(ys), x0, y0, *deltas]


def test_a_piece_inside_the_box_is_kept_without_its_box():
    near = piece(-1226000, 455000, 100, 100)
    out = geodata.clip(45.59, -122.60, radius_nm=40, data=world(lines={"coast": [near]}))
    assert out["lines"]["coast"] == [[-1226000, 455000, 100, 100]]


def test_a_piece_outside_the_box_is_dropped():
    far = piece(-1000000, 455000, 100, 0)  # 100 E of the field: far outside 40 nm
    out = geodata.clip(45.59, -122.60, radius_nm=40, data=world(lines={"coast": [far]}))
    assert out["lines"]["coast"] == []


def test_a_long_line_crossing_the_box_is_kept_by_its_box():
    across = piece(-1240000, 450000, 30000, 12000)  # one segment straight through
    out = geodata.clip(45.59, -122.60, radius_nm=40, data=world(lines={"coast": [across]}))
    assert len(out["lines"]["coast"]) == 1


def test_points_and_labels_are_clipped_the_same_way():
    data = world(
        points={"city": [[-1226800, 455200, "PORTLAND", 3], [-1100000, 400000, "FAR", 3]]},
        labels={"state": [[-1220000, 440000, "OREGON"], [0, 0, "NOWHERE"]]},
    )
    out = geodata.clip(45.59, -122.60, radius_nm=120, data=data)
    assert [p[2] for p in out["points"]["city"]] == ["PORTLAND"]
    assert [p[2] for p in out["labels"]["state"]] == ["OREGON"]


def test_only_the_home_airports_runways_are_sent():
    data = world(runways={"KPDX": [[1, 2, 3, 4]], "KSEA": [[5, 6, 7, 8]]})
    assert geodata.clip(45.59, -122.60, icao="kpdx", data=data)["runways"] == [[1, 2, 3, 4]]
    assert geodata.clip(45.59, -122.60, icao="KXYZ", data=data)["runways"] == []


def test_across_the_antimeridian_features_are_shifted_into_the_airports_frame():
    """A field at 179.9 E must see land at 179.9 W beside it, not a world away:
    the piece comes back a whole turn east so the page draws it adjacent."""
    west = piece(-1799000, -160000, 10, 10)  # 179.9 W
    point = [-1799500, -160000, "TAVEUNI", 8]
    data = world(lines={"coast": [west]}, points={"city": [point]})
    out = geodata.clip(-16.0, 179.9, radius_nm=40, data=data)
    assert out["lines"]["coast"] == [[-1799000 + 360 * Q, -160000, 10, 10]]
    assert out["points"]["city"][0][0] == -1799500 + 360 * Q


def test_near_a_pole_the_box_takes_every_longitude():
    minx, _, maxx, _ = geodata.box(89.5, 0.0, 40, Q)
    assert minx <= -180 * Q and maxx >= 180 * Q


def test_the_committed_map_loads_and_has_every_layer():
    data = geodata.world()
    assert data["format"] == 1 and data["q"] == Q
    assert {"coast", "lake", "river", "country", "state"} <= set(data["lines"])
    assert {"airspace_b", "airspace_c", "airspace_d"} <= set(data["lines"])
    assert {"city", "peak", "navaid", "airport"} <= set(data["points"])
    assert data["runways"]["KPDX"]


def test_portland_has_its_coast_rivers_and_landmarks():
    out = geodata.clip(45.5887, -122.5975, icao="KPDX")
    assert out["lines"]["coast"] and out["lines"]["river"]
    assert "BTG" in {p[2] for p in out["points"]["navaid"]}
    assert "PORTLAND" in {p[2] for p in out["points"]["city"]}
    assert "MT HOOD" in {p[2] for p in out["points"]["peak"]}
    assert len(out["runways"]) == 3


def test_an_airports_map_is_small_and_cached():
    first = geodata.clipped_json("KJFK", 40.6398, -73.7789)
    assert len(first) < 150_000
    assert geodata.clipped_json("KJFK", 40.6398, -73.7789) is first
    assert json.loads(first)["center"] == [-737789, 406398]
```

- [ ] **Step 2:** They fail: `ImportError: cannot import name 'geodata' from 'kcgx'`.
- [ ] **Step 3: The module.** Create `src/kcgx/geodata.py`:

```python
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
```

- [ ] **Step 4:** Suite: **957 passed** (10 here, 1 import guard). Commit `feat(radar): the map clipped per airport`.

---

### Task 4: `kcgx.radar`

**Files:** Create `src/kcgx/radar.py`, `tests/test_radar.py`; add
`"kcgx.radar"` to `WEB_MODULES`.

- [ ] **Step 1: Tests.** Create `tests/test_radar.py`:

```python
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
```

- [ ] **Step 2:** They fail: `ImportError: cannot import name 'radar' from 'kcgx'`.
- [ ] **Step 3: The module.** Create `src/kcgx/radar.py`:

```python
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
```

- [ ] **Step 4:** Suite: **987 passed** (29 here, 1 import guard). Commit `feat(radar): the poller and the picture`.

---

### Task 5: The station owns a radar

**Files:** `src/kcgx/protocol.py`, `src/kcgx/station.py`, `tests/test_station.py`.

- [ ] **Step 1: Tests.** Apply:

```diff
diff --git a/tests/test_station.py b/tests/test_station.py
index 859a2b0..73c4f3d 100644
--- a/tests/test_station.py
+++ b/tests/test_station.py
@@ -348,3 +348,49 @@ async def test_a_prefs_change_is_remembered_and_reaches_every_page():
     assert frames(page, "prefs") == [{"t": "prefs", "palette": "MATRIX", "glow": "LOW", "display": "CRT"}]
     station.handle({"t": "prefs", "glow": "OFF"})
     assert station.prefs == {"palette": "MATRIX", "glow": "OFF", "display": "CRT"}
+
+
+# -- the radar ---------------------------------------------------------------
+
+
+async def test_changing_airport_points_the_radar_at_it():
+    station, hub, *_ = make()
+    page = watch(hub)
+    await station.change_airport("KSEA")
+    assert (station.radar.lat, station.radar.lon) == (station.airport.lat, station.airport.lon)
+    aircraft = frames(page, "aircraft")
+    assert aircraft and aircraft[-1]["ac"] == []
+
+
+async def test_the_snapshot_carries_the_radar_picture():
+    station, *_ = make()
+    await station.open("KPDX")
+    station.radar.merge({"ac": [{"hex": "abc", "flight": "ASA1", "lat": 45.6, "lon": -122.5}]})
+    assert [ac["label"] for ac in station.snapshot()["radar"]["ac"]] == ["ASA1"]
+
+
+async def test_radar_frames_and_emergencies_reach_every_page():
+    station, hub, *_ = make()
+    await station.open("KPDX")
+    page = watch(hub)
+    station.radar.merge({"ac": [{"hex": "e", "flight": "N52RT", "squawk": "7700", "lat": 45.9, "lon": -122.6}]})
+    station.radar.on_frame(station.radar.frame())
+    assert frames(page, "aircraft")[-1]["ac"][0]["sq"] == "7700"
+    assert hub.log[-1]["text"].startswith("N52RT squawking 7700 (emergency), 19 nm N")
+
+
+async def test_the_radar_takes_its_settings_from_the_config():
+    loop = asyncio.get_running_loop()
+    station = Station(
+        Config(radar_refresh_secs=30, radar_range_nm=25, radar_stale_secs=90),
+        Hub(),
+        post=lambda fn, *args: loop.call_soon_threadsafe(fn, *args),
+        airports=AIRPORTS,
+        mixer=Mixer(),
+        feeds_loader=listing,
+        sessions_builder=Builder(),
+        picker_loader=picker,
+        remember=lambda icao: None,
+        remember_prefs=lambda prefs: None,
+    )
+    assert (station.radar.refresh_secs, station.radar.range_nm, station.radar.stale_secs) == (30, 25, 90)
```

- [ ] **Step 2:** They fail: `AttributeError: 'Station' object has no attribute 'radar'`.
- [ ] **Step 3:** Apply both:

```diff
diff --git a/src/kcgx/protocol.py b/src/kcgx/protocol.py
index 3f5166e..8d6e3db 100644
--- a/src/kcgx/protocol.py
+++ b/src/kcgx/protocol.py
@@ -78,6 +78,7 @@ def snapshot(
     audio_ok: bool,
     log: Iterable[dict],
     prefs: dict | None = None,
+    radar: dict | None = None,
 ) -> dict:
     """Everything a page needs to draw from nothing: sent on connect and
     after every airport change."""
@@ -92,6 +93,7 @@ def snapshot(
         "audio_ok": bool(audio_ok),
         "log": list(log),
         "prefs": dict(prefs or DEFAULTS),
+        "radar": radar,
     }
 
 
diff --git a/src/kcgx/station.py b/src/kcgx/station.py
index 562e7e2..2ffe13e 100644
--- a/src/kcgx/station.py
+++ b/src/kcgx/station.py
@@ -23,6 +23,7 @@ from kcgx import protocol
 from kcgx.airports import Airport, find
 from kcgx.hub import Hub
 from kcgx.prefs import DEFAULTS, write_prefs
+from kcgx.radar import Fetch, Radar, fetch_adsb_lol
 from kcgx.state import write_airport
 from squelch.cockpit import ADDED, FEED, MESSAGE, ORDER, Cockpit
 from squelch.config import Config
@@ -52,6 +53,7 @@ class Station:
         remember: Callable[[str], None] = write_airport,
         prefs: dict | None = None,
         remember_prefs: Callable[[dict], None] = write_prefs,
+        radar_fetch: Fetch = fetch_adsb_lol,
     ) -> None:
         self.config = config
         self.hub = hub
@@ -64,6 +66,16 @@ class Station:
         self._remember = remember
         self._remember_prefs = remember_prefs
         self.prefs = dict(prefs or DEFAULTS)
+        # Polled by the server's radar task (kcgx.server), retargeted here
+        # on every airport change.
+        self.radar = Radar(
+            on_frame=self.hub.broadcast,
+            on_note=self.hub.note,
+            fetch=radar_fetch,
+            refresh_secs=config.radar_refresh_secs,
+            range_nm=config.radar_range_nm,
+            stale_secs=config.radar_stale_secs,
+        )
         self._events = SessionEvents(
             on_state=lambda session, state: self._post(self._session_changed, session),
             on_warn=lambda session, message: self._post(
@@ -110,6 +122,7 @@ class Station:
         self._discard()
         config = replace(self.config, icao=airport.icao)
         self.icao, self.airport, self.loading = airport.icao, airport, True
+        self.radar.retarget(airport.lat, airport.lon)
         self._picker = {}
         self.cockpit = self._new_cockpit(config, [])
         self.hub.broadcast(self.snapshot())
@@ -217,6 +230,7 @@ class Station:
             audio_ok=not getattr(self.mixer, "failed", False),
             log=self.hub.log,
             prefs=self.prefs,
+            radar=self.radar.frame(),
         )
 
     # -- shutting down -----------------------------------------------------
```

- [ ] **Step 4:** Suite: **991 passed**. Commit `feat(radar): the station keeps the picture and retargets it`.

---

### Task 6: Demo traffic

**Files:** `src/kcgx/demo.py`, `tests/test_demo.py`.

- [ ] **Step 1: Tests.** Apply:

```diff
diff --git a/tests/test_demo.py b/tests/test_demo.py
index 70633de..e0dfeb6 100644
--- a/tests/test_demo.py
+++ b/tests/test_demo.py
@@ -107,3 +107,42 @@ def test_the_demo_mixer_needs_no_device():
     mixer.clear_channels()
     mixer.stop()
     assert mixer.volume == 0.5 and not mixer.failed
+
+
+# -- demo traffic ------------------------------------------------------------
+
+
+def test_demo_traffic_is_shaped_like_adsb_lol_and_stays_near_the_field():
+    from kcgx.radar import Radar, distance_bearing
+
+    reply = demo.traffic(45.5887, -122.5975, 40, clock=lambda: 1_000_000.0)
+    assert reply["ac"] and len({ac["hex"] for ac in reply["ac"]}) == len(reply["ac"])
+    for ac in reply["ac"]:
+        distance, _ = distance_bearing(45.5887, -122.5975, ac["lat"], ac["lon"])
+        assert distance < 80
+    radar = Radar(on_frame=lambda f: None, on_note=lambda n: None, clock=lambda: 1_000_000.0)
+    radar.retarget(45.5887, -122.5975)
+    radar.merge(reply)
+    labels = {ac["label"] for ac in radar.frame()["ac"]}
+    assert "UNK1" in labels  # the one with no callsign
+
+
+def test_demo_traffic_moves():
+    a = demo.traffic(45.5887, -122.5975, 40, clock=lambda: 1_000_000.0)
+    b = demo.traffic(45.5887, -122.5975, 40, clock=lambda: 1_000_015.0)
+    moved = {x["hex"] for x in a["ac"]} & {x["hex"] for x in b["ac"]}
+    pos = lambda reply: {x["hex"]: (x["lat"], x["lon"]) for x in reply["ac"]}
+    assert any(pos(a)[h] != pos(b)[h] for h in moved)
+
+
+def test_one_demo_aircraft_squawks_7600_for_one_minute_in_five():
+    def squawk(t):
+        reply = demo.traffic(45.5887, -122.5975, 40, clock=lambda: t)
+        return {x["flight"].strip(): x["squawk"] for x in reply["ac"] if x["flight"]}.get("N52RT")
+
+    base = 1_000_200.0 - (1_000_200.0 % 300)
+    assert squawk(base + 60) in ("1200", None)
+    assert squawk(base + 150) in ("7600", None)
+    assert squawk(base + 200) in ("1200", None)
+    window = [squawk(base + 120 + s) for s in range(0, 60, 5)]
+    assert "7600" in window
```

- [ ] **Step 2:** They fail: `AttributeError: module 'kcgx.demo' has no attribute 'traffic'`.
- [ ] **Step 3:** Apply:

```diff
diff --git a/src/kcgx/demo.py b/src/kcgx/demo.py
index c584be9..95a7151 100644
--- a/src/kcgx/demo.py
+++ b/src/kcgx/demo.py
@@ -177,3 +177,67 @@ class DemoMixer:
 
     def clear_channels(self) -> None:
         pass
+
+
+# -- demo traffic ------------------------------------------------------------
+#
+# A dozen aircraft on fixed paths around whatever airport is open, shaped
+# like adsb.lol's reply so the real poller handles them. Each flies a
+# straight leg (start bearing and distance from the field, heading, length)
+# at constant speed, climbing or descending linearly, and starts again when
+# the leg ends. N52RT squawks 7600 for the middle minute of every five, so
+# the emergency lamp and the log can be seen working.
+
+NM_PER_DEG_LAT = 60.0
+
+# callsign, type, start bearing, start nm, heading, leg nm, kt, alt from, alt to, squawk
+LEGS = [
+    ("ASA412", "B39M", 90, 38, 270, 36, 230, 9000, 1200, "4512"),
+    ("DAL1388", "A321", 30, 6, 30, 40, 310, 3000, 17000, "2251"),
+    ("UAL1650", "B738", 350, 10, 350, 34, 330, 8000, 26000, "6011"),
+    ("SWA2183", "B737", 300, 36, 125, 32, 250, 12000, 2500, "3305"),
+    ("QXE2041", "DH8D", 260, 30, 80, 28, 200, 6000, 1500, "4471"),
+    ("N7243K", "C172", 200, 8, 160, 18, 105, 2500, 2500, "1200"),
+    ("", "PA28", 120, 18, 270, 20, 95, 1800, 1800, "1200"),
+    ("N52RT", "BE36", 320, 34, 120, 40, 150, 7500, 6500, "1200"),
+    ("FDX1207", "B763", 180, 40, 0, 36, 260, 11000, 2000, "5213"),
+    ("AAL2210", "A320", 60, 40, 245, 80, 450, 33000, 33000, "3466"),
+    ("N911PD", "AS50", 150, 12, 330, 16, 110, 1500, 1500, "1200"),
+]
+
+
+def _offset(lat: float, lon: float, bearing: float, nm: float) -> tuple[float, float]:
+    b = math.radians(bearing)
+    dlat = nm * math.cos(b) / NM_PER_DEG_LAT
+    dlon = nm * math.sin(b) / (NM_PER_DEG_LAT * max(0.01, math.cos(math.radians(lat))))
+    return lat + dlat, lon + dlon
+
+
+def traffic(lat: float, lon: float, range_nm: int, *, clock=time.time) -> dict:
+    """Stands in for kcgx.radar.fetch_adsb_lol."""
+    now = clock()
+    aircraft = []
+    for index, (callsign, kind, bearing, start, heading, leg, kt, alt0, alt1, squawk) in enumerate(LEGS):
+        period = leg / kt * 3600 + 20
+        phase = (now + index * 97) % period
+        flown = min(leg, phase / 3600 * kt)
+        if flown >= leg:
+            continue  # between legs: off the screen for a moment, as aircraft are
+        x_lat, x_lon = _offset(lat, lon, bearing, start)
+        a_lat, a_lon = _offset(x_lat, x_lon, heading, flown)
+        alt = round((alt0 + (alt1 - alt0) * flown / leg) / 100) * 100
+        if callsign == "N52RT" and 120 <= now % 300 < 180:
+            squawk = "7600"
+        aircraft.append({
+            "hex": f"de{index:04x}",
+            "flight": callsign.ljust(8) if callsign else None,
+            "t": kind,
+            "alt_baro": alt,
+            "gs": kt,
+            "track": heading,
+            "lat": round(a_lat, 5),
+            "lon": round(a_lon, 5),
+            "squawk": squawk,
+            "seen_pos": 0.4,
+        })
+    return {"ac": aircraft, "msg": "No error", "now": int(now * 1000)}
```

- [ ] **Step 4:** Suite: **994 passed**. Commit `feat(demo): synthetic traffic, with an emergency`.

---

### Task 7: Serving the map and running the radar

**Files:** `src/kcgx/server.py`, `tests/test_server.py`.

- [ ] **Step 1: Tests.** Apply (the one change to an existing line is
  `radar=False` in `app()`'s options):

```diff
diff --git a/tests/test_server.py b/tests/test_server.py
index d30d87b..3806ed7 100644
--- a/tests/test_server.py
+++ b/tests/test_server.py
@@ -41,7 +41,7 @@ def app(**kwargs):
             remember_prefs=lambda prefs: None,
         )
 
-    options = dict(level_hz=0, resort_seconds=0)
+    options = dict(level_hz=0, resort_seconds=0, radar=False)
     options.update(kwargs)
     return create_app(
         station_factory=factory, initial_icao="KPDX", on_exit=lambda: exits.append(True), **options
@@ -397,3 +397,61 @@ def test_prefs_are_read_at_startup(monkeypatch, tmp_path):
          serve=lambda asgi, port, on_server: served.setdefault("app", asgi), out=lambda line: None)
     with TestClient(served["app"], base_url=BASE) as http, http.websocket_connect(WS) as ws:
         assert ready(ws)["prefs"] == {"palette": "MATRIX", "glow": "OFF", "display": "VECTOR"}
+
+
+# -- the radar -----------------------------------------------------------------
+
+
+def test_the_map_for_an_airport_is_served():
+    asgi, _ = app()
+    with client(asgi) as http:
+        response = http.get("/api/geo?icao=kpdx")
+    assert response.status_code == 200
+    assert response.headers["cache-control"] == "no-cache"
+    geo = response.json()
+    pdx = next(a for a in AIRPORTS if a.icao == "KPDX")
+    assert geo["center"] == [round(pdx.lon * 10_000), round(pdx.lat * 10_000)]
+    assert len(geo["runways"]) == 3
+    assert geo["lines"]["coast"]
+
+
+@pytest.mark.parametrize("query", ["?icao=ZZZZ", "", "?icao="])
+def test_the_map_of_an_unknown_airport_is_a_404(query):
+    asgi, _ = app()
+    with client(asgi) as http:
+        assert http.get(f"/api/geo{query}").status_code == 404
+
+
+def radar_app(fetch, **options):
+    def factory(hub, post):
+        return Station(
+            Config(icao="KPDX", feed="kpdx3_twr"),
+            hub,
+            post=post,
+            airports=AIRPORTS,
+            mixer=Mixer(),
+            feeds_loader=listing,
+            sessions_builder=Builder(),
+            picker_loader=picker,
+            remember=lambda icao: None,
+            remember_prefs=lambda prefs: None,
+            radar_fetch=fetch,
+        )
+
+    return create_app(station_factory=factory, initial_icao="KPDX", level_hz=0, resort_seconds=0, **options)
+
+
+def test_the_radar_polls_from_startup_and_every_page_sees_it():
+    def fetch(lat, lon, range_nm):
+        return {"ac": [{"hex": "abc", "flight": "ASA412", "lat": lat + 0.1, "lon": lon, "alt_baro": 5000}]}
+
+    with client(radar_app(fetch)) as http, http.websocket_connect(WS) as ws:
+        frame = until(ws, lambda f: f["t"] == "aircraft" and f["ac"])
+    assert frame["ac"][0]["label"] == "ASA412" and frame["ok"]
+
+
+def test_radar_off_means_no_polling():
+    calls = []
+    with client(radar_app(lambda *a: calls.append(a) or {"ac": []}, radar=False)) as http, http.websocket_connect(WS) as ws:
+        ready(ws)
+    assert calls == []
```

- [ ] **Step 2:** They fail: `/api/geo` is a 404 and `create_app()` has no `radar` argument.
- [ ] **Step 3:** Apply:

```diff
diff --git a/src/kcgx/server.py b/src/kcgx/server.py
index a701c20..5603ed2 100644
--- a/src/kcgx/server.py
+++ b/src/kcgx/server.py
@@ -27,12 +27,12 @@ from typing import Any
 
 from starlette.applications import Starlette
 from starlette.requests import Request
-from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
+from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
 from starlette.routing import Mount, Route, WebSocketRoute
 from starlette.staticfiles import StaticFiles
 from starlette.websockets import WebSocket, WebSocketDisconnect
 
-from kcgx import protocol
+from kcgx import geodata, protocol
 from kcgx.airports import find, load_airports, search
 from kcgx.hub import Client, Hub
 from kcgx.prefs import read_prefs
@@ -112,10 +112,12 @@ def create_app(
     on_exit: Callable[[], None] = lambda: None,
     level_hz: float = LEVEL_HZ,
     resort_seconds: float = RESORT_SECONDS,
+    radar: bool = True,
 ) -> Any:
     """The ASGI app. `station_factory(hub, post)` builds the Station once
     the event loop is running; `on_exit` is what POST /api/shutdown calls.
-    A zero `level_hz` or `resort_seconds` turns that loop off (tests)."""
+    A zero `level_hz` or `resort_seconds` turns that loop off, and
+    `radar=False` keeps the radar from polling (tests)."""
 
     @contextlib.asynccontextmanager
     async def lifespan(app):
@@ -135,6 +137,8 @@ def create_app(
             tasks.append(asyncio.create_task(_every(1 / level_hz, station.tick_levels)))
         if resort_seconds:
             tasks.append(asyncio.create_task(_every(resort_seconds, station.tick_resort)))
+        if radar:
+            tasks.append(asyncio.create_task(_guarded(hub, station.radar.run())))
         try:
             yield
         finally:
@@ -186,6 +190,17 @@ def create_app(
         asyncio.create_task(_guarded(station.hub, station.change_airport(airport.icao)))
         return JSONResponse({"icao": airport.icao}, status_code=202)
 
+    async def geo(request: Request):
+        """The radar's map for one airport: everything within 200 nm. Asked
+        for by ICAO so a page never draws one field's map around another."""
+        station = request.app.state.station
+        try:
+            airport = station.check_airport(request.query_params.get("icao", ""))
+        except UnknownAirport:
+            return JSONResponse({"error": "no such airport"}, status_code=404)
+        body = await asyncio.to_thread(geodata.clipped_json, airport.icao, airport.lat, airport.lon)
+        return Response(body, media_type="application/json", headers=NO_CACHE)
+
     async def available(request: Request):
         return JSONResponse(await request.app.state.station.available_feeds())
 
@@ -230,6 +245,7 @@ def create_app(
             Route("/api/airports", airports),
             Route("/api/airport", set_airport, methods=["POST"]),
             Route("/api/feeds/available", available),
+            Route("/api/geo", geo),
             Route("/api/shutdown", shutdown, methods=["POST"]),
             WebSocketRoute("/ws", live),
         ],
@@ -339,6 +355,7 @@ def main(
             "picker_loader": demo.picker,
             "remember": lambda icao: None,
             "remember_prefs": lambda prefs: None,
+            "radar_fetch": demo.traffic,
         }
     else:
         options = {}
```

- [ ] **Step 4:** Suite: **1000 passed**. Commit `feat(radar): serve the map; poll from startup`.

---

### Task 8: The radar on the page

**Files:** Create `src/kcgx/web/static/js/focus.js`, `src/kcgx/web/static/js/tracks.js`;
replace `src/kcgx/web/static/js/radar.js`; modify `store.js`, `theme.js`,
`lamps.js`, `main.js`, `index.html`, `cockpit.css`. No tests in this task;
Task 9 drives it.

- [ ] **Step 1:** Create `src/kcgx/web/static/js/focus.js`:

```javascript
// Which aircraft is focused (spec, Visual language: click an aircraft to
// focus it). Belongs to the page, not the server: each tab has its own.
// The radar and the tracks table both read and set it.

let current = null;
const listeners = new Set();

export const focus = {
  get hex() { return current; },
  toggle(hex) { this.set(current === hex ? null : hex); },
  set(hex) {
    if (hex === current) return;
    current = hex;
    for (const fn of listeners) fn(current);
  },
  subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
};
```

- [ ] **Step 2:** Create `src/kcgx/web/static/js/tracks.js`:

```javascript
// The tracks table under the radar (spec, Radar): callsign, type, altitude,
// ground speed, track, distance and squawk, sortable by any column. The
// callsign is a button that focuses the aircraft, exactly as clicking it on
// the radar does; the focused row is pink and outlined, the rest dim.

import { focus } from "./focus.js";

const EMERGENCY = new Set(["7500", "7600", "7700"]);
const COLUMNS = [
  { key: "label", title: "CALLSIGN", text: (a) => a.label },
  { key: "type", title: "TYPE", text: (a) => a.type || "" },
  { key: "alt", title: "ALT FT", num: true, text: (a) => (a.alt === null ? "" : String(a.alt)), sort: (a) => (a.alt === "GND" ? 0 : a.alt ?? -1) },
  { key: "gs", title: "GS KT", num: true, text: (a) => (a.gs === null ? "" : String(a.gs)), sort: (a) => a.gs ?? -1 },
  { key: "trk", title: "TRK", num: true, text: (a) => (a.trk === null ? "" : String(a.trk).padStart(3, "0")), sort: (a) => a.trk ?? -1 },
  { key: "dist", title: "DIST NM", num: true, text: (a) => a.dist.toFixed(1), sort: (a) => a.dist },
  { key: "sq", title: "SQWK", num: true, text: (a) => a.sq || "" },
];

export function mountTracks({ head, body, empty }, store) {
  let sortKey = "dist";
  let ascending = true;

  head.replaceChildren(...COLUMNS.map((column) => {
    const th = document.createElement("th");
    if (column.num) th.className = "num";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sort";
    button.textContent = column.title;
    button.dataset.key = column.key;
    button.addEventListener("click", () => {
      if (sortKey === column.key) ascending = !ascending;
      else { sortKey = column.key; ascending = true; }
      render();
    });
    th.append(button);
    return th;
  }));

  function render() {
    const radar = store.state.radar;
    const list = radar ? [...radar.ac] : [];
    const column = COLUMNS.find((c) => c.key === sortKey);
    const value = column.sort || column.text;
    list.sort((a, b) => {
      const x = value(a);
      const y = value(b);
      const order = x < y ? -1 : x > y ? 1 : a.hex < b.hex ? -1 : 1;
      return ascending ? order : -order;
    });
    for (const th of head.querySelectorAll("th")) {
      const key = th.firstChild.dataset.key;
      th.setAttribute("aria-sort", key === sortKey ? (ascending ? "ascending" : "descending") : "none");
    }
    const focused = focus.hex;
    body.replaceChildren(...list.map((ac) => {
      const tr = document.createElement("tr");
      tr.dataset.hex = ac.hex;
      if (EMERGENCY.has(ac.sq)) tr.classList.add("emergency");
      if (focused) tr.classList.add(ac.hex === focused ? "focused" : "dimmed");
      COLUMNS.forEach((c, i) => {
        const td = document.createElement("td");
        if (c.num) td.className = "num";
        if (i === 0) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "callsign";
          button.textContent = c.text(ac);
          button.setAttribute("aria-pressed", String(ac.hex === focused));
          button.setAttribute("aria-label", `Focus ${c.text(ac)} on the radar`);
          button.addEventListener("click", () => focus.toggle(ac.hex));
          td.append(button);
        } else {
          td.textContent = c.text(ac);
        }
        tr.append(td);
      });
      return tr;
    }));
    empty.hidden = list.length > 0;
    empty.textContent = !radar || radar.age === null
      ? (radar && radar.error ? `THE RADAR IS NOT ANSWERING (${radar.error})` : "WAITING FOR THE RADAR")
      : "NO TRAFFIC IN RANGE";
  }

  store.subscribe((kind) => { if (kind === "all" || kind === "aircraft") render(); });
  focus.subscribe((hex) => {
    render();
    const row = hex && body.querySelector(`tr[data-hex="${CSS.escape(hex)}"]`);
    if (row) row.scrollIntoView({ block: "nearest" });
  });
  render();
}
```

- [ ] **Step 3:** Replace `src/kcgx/web/static/js/radar.js` entirely. Its new content:

```javascript
// The radar (spec, Radar; Visual language; Rendering). Our own vector
// renderer on one canvas: an azimuthal equidistant projection centred on
// the airport, so range rings are true circles and distance reads straight
// off the screen.
//
// Two layers. The static one (map, rings, labels, the home airport) is
// drawn into an offscreen canvas once per airport, resize, pan, zoom,
// palette or hover change, and copied each frame. The moving one (aircraft,
// trails, the focus ring) is drawn every frame, dead reckoned between polls
// from ground speed and track. With display VECTOR or CRT the moving layer
// fades instead of clearing, which is the phosphor persistence.

import { colours, glowBlur, reducedMotion } from "./theme.js";
import { focus } from "./focus.js";

const NM_PER_RADIAN = 3440.065;
const RANGE_NM = 40;
const RINGS_NM = [10, 20, 30, 40];
const ZOOM_MIN = 0.25; // 160 nm across the shorter side
const ZOOM_MAX = 6;
const DRAW_ON_MS = 2000;
const LABEL_ALPHA = 0.4;
const DIM_ALPHA = 0.15;
const STALE_FADE_FROM = 30; // seconds without a position before an aircraft fades
const EMERGENCY = new Set(["7500", "7600", "7700"]);
const VOR = new Set(["VOR", "VOR-DME", "VORTAC", "TACAN"]);
const FONT = '"Share Tech Mono", monospace';

const DRAWN_ON = new Set(["coast", "lake", "river", "country", "state"]);

// -- the projection --------------------------------------------------------------

export function projector(lat0, lon0) {
  const p0 = (lat0 * Math.PI) / 180;
  const sin0 = Math.sin(p0);
  const cos0 = Math.cos(p0);
  return (lat, lon) => {
    const p = (lat * Math.PI) / 180;
    let dl = ((lon - lon0 + 540) % 360) - 180; // across the antimeridian too
    dl = (dl * Math.PI) / 180;
    const sinp = Math.sin(p);
    const cosp = Math.cos(p);
    const cosc = Math.max(-1, Math.min(1, sin0 * sinp + cos0 * cosp * Math.cos(dl)));
    const c = Math.acos(cosc);
    const k = c < 1e-9 ? 1 : c / Math.sin(c);
    const x = k * cosp * Math.sin(dl) * NM_PER_RADIAN;
    const y = k * (cos0 * sinp - sin0 * cosp * Math.cos(dl)) * NM_PER_RADIAN;
    return [x, -y]; // nm east, nm south: screen orientation
  };
}

// Where an aircraft will be `seconds` after its last position.
export function reckon(lat, lon, gs, trk, seconds) {
  if (!gs || trk === null || trk === undefined || seconds <= 0) return [lat, lon];
  const nm = (gs * seconds) / 3600;
  const b = (trk * Math.PI) / 180;
  const dlat = (nm * Math.cos(b)) / 60;
  const dlon = (nm * Math.sin(b)) / (60 * Math.max(0.01, Math.cos((lat * Math.PI) / 180)));
  return [lat + dlat, lon + dlon];
}

// -- the map, decoded once per airport -------------------------------------------

function decode(geo, project) {
  const q = geo.q;
  const lines = {};
  for (const [layer, pieces] of Object.entries(geo.lines)) {
    lines[layer] = pieces.map((piece) => {
      const out = new Float32Array(piece.length);
      let x = piece[0];
      let y = piece[1];
      for (let i = 0; i < piece.length; i += 2) {
        if (i) { x += piece[i]; y += piece[i + 1]; }
        const [px, py] = project(y / q, x / q);
        out[i] = px;
        out[i + 1] = py;
      }
      return out;
    });
  }
  const at = (row) => project(row[1] / q, row[0] / q);
  const points = {};
  for (const [kind, rows] of Object.entries(geo.points)) points[kind] = rows.map((row) => ({ xy: at(row), row }));
  const labels = {};
  for (const [kind, rows] of Object.entries(geo.labels)) labels[kind] = rows.map((row) => ({ xy: at(row), row }));
  const runways = geo.runways.map((r) => [project(r[1] / q, r[0] / q), project(r[3] / q, r[2] / q)]);
  return { lines, points, labels, runways };
}

// -- the screen ------------------------------------------------------------------

export function mountRadar(canvas, store, { hud = {} } = {}) {
  const view = { zoom: 1, panX: 0, panY: 0 }; // pan in nm
  let map = null; // decoded geo for the current airport
  let mapFor = "";
  let project = null;
  let drawOnFrom = 0;
  let staticDirty = true;
  let hovered = null; // a placed label's key
  let placed = []; // [{ key, x, y, w, h }]
  let hits = []; // [{ hex, x, y, label: {x, y, w, h}, trail: [[x, y]] }]
  const still = document.createElement("canvas");
  const trace = document.createElement("canvas"); // the moving layer, for persistence

  // -- sizes and the transform --

  function size() {
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(box.width * ratio));
    const height = Math.max(1, Math.round(box.height * ratio));
    for (const c of [canvas, still, trace]) {
      if (c.width !== width || c.height !== height) { c.width = width; c.height = height; staticDirty = true; }
    }
    return { ratio, width, height };
  }

  // Pixels per nm: the 40 nm ring fits the shorter side, times the zoom.
  function scale(width, height, ratio) {
    return (Math.max(0, Math.min(width, height) / 2 - 18 * ratio) / RANGE_NM) * view.zoom;
  }

  function toScreen(xy, s, width, height) {
    return [width / 2 + (xy[0] - view.panX) * s, height / 2 + (xy[1] - view.panY) * s];
  }

  // -- the map --

  async function loadMap(airport) {
    const key = airport.icao;
    mapFor = key;
    map = null;
    project = airport.lat === null ? null : projector(airport.lat, airport.lon);
    staticDirty = true;
    if (!project) return;
    try {
      const response = await fetch(`/api/geo?icao=${encodeURIComponent(key)}`);
      if (!response.ok) throw new Error(`${response.status}`);
      const geo = await response.json();
      if (mapFor !== key) return; // the airport changed while we were asking
      map = decode(geo, project);
      drawOnFrom = reducedMotion() ? 0 : performance.now();
      staticDirty = true;
    } catch {
      map = null;
    }
  }

  function strokeLines(ctx, lines, s, width, height, progress) {
    ctx.beginPath();
    const ox = width / 2 - view.panX * s;
    const oy = height / 2 - view.panY * s;
    for (const line of lines) {
      const n = line.length / 2;
      const upto = progress >= 1 ? n : Math.max(2, Math.ceil(n * progress));
      ctx.moveTo(ox + line[0] * s, oy + line[1] * s);
      for (let i = 1; i < upto; i += 1) ctx.lineTo(ox + line[2 * i] * s, oy + line[2 * i + 1] * s);
    }
    ctx.stroke();
  }

  function glow(ctx, colour, ratio) {
    ctx.shadowColor = colour;
    ctx.shadowBlur = glowBlur() * ratio;
  }

  function drawStatic(now) {
    const { ratio, width, height } = size();
    const ctx = still.getContext("2d");
    const c = colours();
    const s = scale(width, height, ratio);
    const centre = toScreen([0, 0], s, width, height);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.globalCompositeOperation = "lighter";
    const progress = drawOnFrom ? Math.min(1, (now - drawOnFrom) / DRAW_ON_MS) : 1;

    if (map) {
      const layers = [
        ["airway", c.blue, 1.2, [3 * ratio, 6 * ratio], 0.7],
        ["state", c.dim, 1, [], 0.55],
        ["country", c.green, 1.2, [6 * ratio, 4 * ratio], 0.9],
        ["river", c.cyan, 1, [], 0.5],
        ["lake", c.cyan, 1.2, [], 0.75],
        ["coast", c.cyan, 1.8, [], 1],
        ["airspace_d", c.alarm, 1, [3 * ratio, 5 * ratio], 0.45],
        ["airspace_c", c.alarm, 1.3, [5 * ratio, 5 * ratio], 0.8],
        ["airspace_b", c.alarm, 1.4, [5 * ratio, 5 * ratio], 0.9],
      ];
      for (const [layer, colour, w, dash, alpha] of layers) {
        const lines = map.lines[layer];
        if (!lines || !lines.length) continue;
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = colour;
        ctx.lineWidth = w * ratio;
        ctx.setLineDash(dash);
        glow(ctx, colour, ratio);
        strokeLines(ctx, lines, s, width, height, DRAWN_ON.has(layer) ? progress : 1);
        ctx.restore();
      }
    }

    // Range rings, labelled along the north east diagonal.
    ctx.save();
    ctx.strokeStyle = c.cyan;
    ctx.lineWidth = ratio;
    glow(ctx, c.cyan, ratio);
    for (const nm of RINGS_NM) {
      ctx.globalAlpha = nm === RANGE_NM ? 0.8 : 0.35;
      ctx.beginPath();
      ctx.arc(centre[0], centre[1], nm * s, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
    ctx.save();
    ctx.fillStyle = c.dim;
    ctx.font = `${12 * ratio}px ${FONT}`;
    for (const nm of RINGS_NM) {
      const d = nm * s * Math.SQRT1_2;
      ctx.fillText(`${nm}`, centre[0] + d + 4 * ratio, centre[1] - d - 4 * ratio);
    }
    ctx.restore();

    // The home airport first, so its name is reserved before anything else
    // looks for room.
    placed = [];
    drawHome(ctx, centre, s, ratio, c);
    if (map) drawPlaces(ctx, s, width, height, ratio, c);
    staticDirty = progress < 1;
  }

  // Symbols and labels, placed greedily by priority so no two labels
  // overlap; a label that does not fit is left off, its symbol stays.
  function drawPlaces(ctx, s, width, height, ratio, c) {
    const onScreen = ([x, y]) => x > -40 && y > -40 && x < width + 40 && y < height + 40;
    const items = [];
    for (const { xy, row } of map.points.navaid || []) {
      if (!VOR.has(row[3])) continue;
      items.push({ kind: "navaid", xy, text: row[2], colour: c.cyan, priority: 30 });
    }
    for (const { xy, row } of map.points.airport || []) {
      if (row[3] === "small" && view.zoom < 1.5) continue;
      items.push({ kind: "airport", xy, text: row[2], colour: c.cyan, priority: row[3] === "large" ? 25 : row[3] === "medium" ? 35 : 60 });
    }
    for (const { xy, row } of map.points.city || []) {
      items.push({ kind: "city", xy, text: row[2], colour: c.amber, priority: row[3] });
    }
    for (const { xy, row } of map.points.peak || []) {
      items.push({ kind: "peak", xy, text: row[2], colour: c.amber, priority: 20 });
    }
    items.sort((a, b) => a.priority - b.priority);

    // The home airport's own name and ring are reserved first.
    const home = toScreen([0, 0], s, width, height);
    const taken = [{ x: home[0] - 26 * ratio, y: home[1] - 26 * ratio, w: 52 * ratio, h: 52 * ratio }, ...placed];
    const free = (r) => taken.every((t) => r.x + r.w < t.x || t.x + t.w < r.x || r.y + r.h < t.y || t.y + t.h < r.y);

    ctx.save();
    ctx.lineWidth = 1.3 * ratio;
    ctx.font = `${13 * ratio}px ${FONT}`;
    ctx.letterSpacing = `${1.5 * ratio}px`;
    for (const item of items) {
      const p = toScreen(item.xy, s, width, height);
      if (!onScreen(p)) continue;
      // Airports within the home ring are the home airport itself.
      if (item.kind === "airport" && Math.hypot(p[0] - home[0], p[1] - home[1]) < 8 * ratio) continue;
      ctx.globalAlpha = 0.85;
      ctx.strokeStyle = item.colour;
      glow(ctx, item.colour, ratio);
      symbol(ctx, item.kind, p, ratio);
      const w = ctx.measureText(item.text).width;
      const h = 13 * ratio;
      const box = { x: p[0] + 8 * ratio, y: p[1] - h / 2 - 2 * ratio, w, h: h + 4 * ratio };
      if (!free(box)) continue;
      taken.push(box);
      const key = `${item.kind}:${item.text}`;
      placed.push({ key, ...box });
      ctx.shadowBlur = 0;
      ctx.globalAlpha = hovered === key ? 1 : LABEL_ALPHA;
      ctx.fillStyle = item.colour;
      ctx.fillText(item.text, box.x, p[1] + h / 2 - 2 * ratio);
    }

    // State names: large, spaced, dim, and the first thing given up.
    ctx.font = `${14 * ratio}px ${FONT}`;
    ctx.letterSpacing = `${6 * ratio}px`;
    ctx.fillStyle = c.dim;
    for (const { xy, row } of map.labels.state || []) {
      const p = toScreen(xy, s, width, height);
      if (!onScreen(p)) continue;
      const w = ctx.measureText(row[2]).width;
      const box = { x: p[0] - w / 2, y: p[1] - 10 * ratio, w, h: 18 * ratio };
      if (!free(box)) continue;
      taken.push(box);
      const key = `state:${row[2]}`;
      placed.push({ key, ...box });
      ctx.globalAlpha = hovered === key ? 1 : LABEL_ALPHA;
      ctx.fillText(row[2], box.x, p[1] + 5 * ratio);
    }
    ctx.restore();
  }

  function symbol(ctx, kind, [x, y], ratio) {
    const r = 6 * ratio;
    ctx.beginPath();
    if (kind === "navaid") {
      ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath();
      ctx.rect(x - 2.5 * ratio, y - 2.5 * ratio, 5 * ratio, 5 * ratio);
    } else if (kind === "airport") {
      ctx.moveTo(x, y - r); ctx.lineTo(x + r, y + r * 0.85); ctx.lineTo(x - r, y + r * 0.85); ctx.closePath();
    } else if (kind === "peak") {
      ctx.moveTo(x, y - r); ctx.lineTo(x + r * 0.9, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r * 0.9, y); ctx.closePath();
    } else {
      ctx.arc(x, y, 3.5 * ratio, 0, Math.PI * 2);
    }
    ctx.stroke();
  }

  function drawHome(ctx, centre, s, ratio, c) {
    const airport = store.state.airport;
    if (!airport) return;
    ctx.save();
    // Runways in white inside the ring, at their true size.
    if (map && map.runways.length) {
      ctx.strokeStyle = c.white;
      ctx.lineWidth = 1.6 * ratio;
      glow(ctx, c.white, ratio);
      ctx.beginPath();
      for (const [a, b] of map.runways) {
        const p = toScreen(a, s, ctx.canvas.width, ctx.canvas.height);
        const q = toScreen(b, s, ctx.canvas.width, ctx.canvas.height);
        ctx.moveTo(p[0], p[1]);
        ctx.lineTo(q[0], q[1]);
      }
      ctx.stroke();
    }
    ctx.strokeStyle = c.pink;
    ctx.lineWidth = 1.8 * ratio;
    glow(ctx, c.pink, ratio);
    const ring = Math.max(24 * ratio, 2.5 * s);
    ctx.beginPath();
    ctx.arc(centre[0], centre[1], ring, 0, Math.PI * 2);
    ctx.stroke();
    // The name, large, above and right of the ring on a short leader, as
    // the film labels its bases.
    const lines = nameLines(airport);
    const size = 30 * ratio;
    const step = size + 2 * ratio;
    const foot = [centre[0] + ring * 0.7, centre[1] - ring * 0.7];
    const x = foot[0] + 12 * ratio;
    const last = foot[1] - 14 * ratio; // the bottom line's baseline
    const top = last - (lines.length - 1) * step;
    ctx.beginPath();
    ctx.lineWidth = 1.2 * ratio;
    ctx.moveTo(foot[0], foot[1]);
    ctx.lineTo(x - 4 * ratio, last + 6 * ratio);
    ctx.stroke();
    ctx.font = `${size}px ${FONT}`;
    ctx.letterSpacing = `${3 * ratio}px`;
    ctx.fillStyle = c.pink;
    ctx.shadowBlur = 0;
    let widest = 0;
    for (const line of lines) widest = Math.max(widest, ctx.measureText(line).width);
    const box = { x, y: top - size, w: widest, h: lines.length * step };
    placed.push({ key: "home", ...box });
    ctx.globalAlpha = hovered === "home" ? 1 : LABEL_ALPHA;
    lines.forEach((line, i) => ctx.fillText(line, x, top + i * step));
    ctx.restore();
  }

  function nameLines(airport) {
    const name = (airport.name || airport.icao).toUpperCase().replace(/\s+AIRPORT$/, "");
    const words = name.split(/\s+/);
    if (name.length <= 16 || words.length < 2) return [name];
    const half = Math.ceil(words.length / 2);
    return [words.slice(0, half).join(" "), words.slice(half).join(" ")];
  }

  // -- aircraft --

  function aircraftNow() {
    const frame = store.state.radar;
    if (!frame || !project) return [];
    const since = (performance.now() - store.state.radarAt) / 1000;
    return frame.ac.map((ac) => {
      const age = ac.age + since;
      const [lat, lon] = reckon(ac.lat, ac.lon, ac.gs, ac.trk, age);
      return { ...ac, now: project(lat, lon), age };
    });
  }

  function drawMoving(ctx, width, height, ratio, s, c) {
    hits = [];
    const focused = focus.hex;
    const list = aircraftNow();
    if (focused && !list.some((ac) => ac.hex === focused)) focus.set(null);
    for (const ac of list) {
      const emergency = EMERGENCY.has(ac.sq);
      const isFocus = ac.hex === focused;
      const colour = isFocus ? c.pink : emergency ? c.alarm : c.cyan;
      const stale = Math.max(0, Math.min(1, (ac.age - STALE_FADE_FROM) / 30));
      let alpha = 1 - 0.7 * stale;
      if (focused && !isFocus) alpha *= DIM_ALPHA;
      const head = toScreen(ac.now, s, width, height);
      const trail = (store.state.trails.get(ac.hex) || [])
        .map((p) => toScreen(project(p.lat, p.lon), s, width, height))
        .reverse();
      const points = [head, ...trail];

      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.lineWidth = 1.8 * ratio;
      ctx.strokeStyle = colour;
      glow(ctx, colour, ratio);
      // The trail fades from full at the arrow to nothing at its oldest point.
      for (let i = 1; i < points.length; i += 1) {
        ctx.globalAlpha = alpha * 0.95 * (1 - (i - 1) / (points.length - 1));
        ctx.beginPath();
        ctx.moveTo(points[i - 1][0], points[i - 1][1]);
        ctx.lineTo(points[i][0], points[i][1]);
        ctx.stroke();
      }
      ctx.globalAlpha = alpha;
      // The chevron, pointing along track.
      ctx.save();
      ctx.translate(head[0], head[1]);
      ctx.rotate(((ac.trk || 0) * Math.PI) / 180);
      ctx.beginPath();
      const u = ratio;
      ctx.moveTo(0, -9 * u); ctx.lineTo(0, 9 * u);
      ctx.moveTo(-7 * u, 4 * u); ctx.lineTo(0, -9 * u); ctx.lineTo(7 * u, 4 * u);
      ctx.stroke();
      ctx.restore();
      if (isFocus) {
        ctx.lineWidth = 1.4 * ratio;
        ctx.beginPath();
        ctx.arc(head[0], head[1], 16 * ratio, 0, Math.PI * 2);
        ctx.stroke();
      }
      const text = `${ac.label} ${ac.alt === null ? "" : ac.alt}`.trim();
      ctx.font = `${16 * ratio}px ${FONT}`;
      ctx.letterSpacing = `${1.5 * ratio}px`;
      ctx.fillStyle = colour;
      ctx.shadowBlur = 0;
      const w = ctx.measureText(text).width;
      const left = head[0] + 14 * ratio;
      ctx.fillText(text, left, head[1] - 10 * ratio);
      ctx.restore();
      hits.push({ hex: ac.hex, x: head[0], y: head[1], label: { x: left, y: head[1] - 26 * ratio, w, h: 20 * ratio }, trail: points });
    }
    return list;
  }

  // -- the frame loop --

  function persistence() {
    const display = document.documentElement.dataset.display;
    return display !== "OFF" && !reducedMotion();
  }

  let lastHud = 0;
  function frame(now) {
    const { ratio, width, height } = size();
    if (staticDirty) drawStatic(now);
    const c = colours();
    const s = scale(width, height, ratio);

    const t = trace.getContext("2d");
    t.setTransform(1, 0, 0, 1, 0, 0);
    t.globalCompositeOperation = "source-over";
    if (persistence()) {
      t.globalCompositeOperation = "destination-out";
      t.fillStyle = "rgba(0,0,0,0.45)";
      t.fillRect(0, 0, width, height);
      t.globalCompositeOperation = "source-over";
    } else {
      t.clearRect(0, 0, width, height);
    }
    const list = drawMoving(t, width, height, ratio, s, c);

    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(still, 0, 0);
    ctx.globalCompositeOperation = "lighter";
    ctx.drawImage(trace, 0, 0);
    ctx.globalCompositeOperation = "source-over";

    if (now - lastHud > 500) { lastHud = now; drawHud(list); }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  function drawHud(list) {
    const radar = store.state.radar;
    if (hud.tracks) hud.tracks.textContent = `${list.length} TRACK${list.length === 1 ? "" : "S"}`;
    if (!hud.poll) return;
    if (!radar || radar.age === null) {
      hud.poll.textContent = radar && radar.error ? `RADAR ${radar.error}` : "RADAR WAITING";
      return;
    }
    const age = Math.round(radar.age + (performance.now() - store.state.radarAt) / 1000);
    hud.poll.textContent = radar.error ? `${radar.error}, PICTURE ${age}S OLD` : `POLLED ${age}S AGO`;
  }

  // -- pointing, panning, zooming, focusing --

  const pointer = { down: null, moved: false };

  function local(event) {
    const ratio = window.devicePixelRatio || 1;
    const box = canvas.getBoundingClientRect();
    return [(event.clientX - box.left) * ratio, (event.clientY - box.top) * ratio];
  }

  function hitAircraft([x, y]) {
    const ratio = window.devicePixelRatio || 1;
    for (const hit of hits) {
      if (Math.hypot(hit.x - x, hit.y - y) < 14 * ratio) return hit.hex;
      const l = hit.label;
      if (x >= l.x && x <= l.x + l.w && y >= l.y && y <= l.y + l.h) return hit.hex;
      for (let i = 1; i < hit.trail.length; i += 1) {
        if (nearSegment(x, y, hit.trail[i - 1], hit.trail[i]) < 6 * ratio) return hit.hex;
      }
    }
    return null;
  }

  canvas.addEventListener("pointerdown", (event) => {
    pointer.down = { at: local(event), panX: view.panX, panY: view.panY };
    pointer.moved = false;
    canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const at = local(event);
    if (pointer.down) {
      const { ratio, width, height } = size();
      const s = scale(width, height, ratio);
      const dx = at[0] - pointer.down.at[0];
      const dy = at[1] - pointer.down.at[1];
      if (Math.hypot(dx, dy) > 4 * ratio) pointer.moved = true;
      if (pointer.moved) {
        view.panX = pointer.down.panX - dx / s;
        view.panY = pointer.down.panY - dy / s;
        staticDirty = true;
      }
      return;
    }
    const over = placed.find((p) => at[0] >= p.x && at[0] <= p.x + p.w && at[1] >= p.y && at[1] <= p.y + p.h);
    const key = over ? over.key : null;
    if (key !== hovered) { hovered = key; staticDirty = true; }
    canvas.style.cursor = hitAircraft(at) ? "pointer" : pointer.down ? "grabbing" : "crosshair";
    if (hud.position) hud.position.textContent = positionText(at);
  });

  canvas.addEventListener("pointerup", (event) => {
    const at = local(event);
    if (pointer.down && !pointer.moved) {
      const hex = hitAircraft(at);
      if (hex) focus.toggle(hex);
    }
    pointer.down = null;
  });

  canvas.addEventListener("pointerleave", () => {
    if (hovered) { hovered = null; staticDirty = true; }
    if (hud.position) hud.position.textContent = "";
  });

  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const { ratio, width, height } = size();
    const at = local(event);
    const before = scale(width, height, ratio);
    const factor = Math.exp(-event.deltaY * 0.0015);
    view.zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, view.zoom * factor));
    const after = scale(width, height, ratio);
    // Keep the point under the pointer where it is.
    const nx = view.panX + (at[0] - width / 2) / before;
    const ny = view.panY + (at[1] - height / 2) / before;
    view.panX = nx - (at[0] - width / 2) / after;
    view.panY = ny - (at[1] - height / 2) / after;
    staticDirty = true;
  }, { passive: false });

  function positionText(at) {
    const { ratio, width, height } = size();
    const s = scale(width, height, ratio);
    const x = view.panX + (at[0] - width / 2) / s;
    const y = view.panY + (at[1] - height / 2) / s;
    const nm = Math.hypot(x, y);
    const brg = (Math.round((Math.atan2(x, -y) * 180) / Math.PI) + 360) % 360;
    return `${String(brg).padStart(3, "0")}° ${nm.toFixed(1)} NM`;
  }

  new ResizeObserver(() => { staticDirty = true; }).observe(canvas);
  store.subscribe((kind) => {
    if (kind === "all") {
      const airport = store.state.airport;
      if (airport && airport.icao !== mapFor) {
        view.zoom = 1; view.panX = 0; view.panY = 0;
        loadMap(airport);
      }
      staticDirty = true;
    } else if (kind === "prefs") {
      staticDirty = true;
    }
  });

  return {
    recentre() { view.zoom = 1; view.panX = 0; view.panY = 0; staticDirty = true; },
    redraw() { staticDirty = true; },
    // For tests: what is on screen, in screen pixels.
    debug() {
      return {
        hits: hits.map((h) => ({ hex: h.hex, x: h.x, y: h.y })),
        placed, hovered, view: { ...view }, mapFor, loaded: Boolean(map),
        layers: map ? Object.fromEntries(Object.entries(map.lines).map(([k, v]) => [k, v.length])) : {},
      };
    },
  };
}

function nearSegment(x, y, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const length = dx * dx + dy * dy;
  const t = length ? Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / length)) : 0;
  return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
}
```

- [ ] **Step 4:** Apply to the rest of the page:

```diff
diff --git a/src/kcgx/web/index.html b/src/kcgx/web/index.html
index 742ea0b..730a3e0 100644
--- a/src/kcgx/web/index.html
+++ b/src/kcgx/web/index.html
@@ -29,8 +29,8 @@
     <section class="screen screen-radar" aria-label="Radar">
       <div class="ovl" aria-hidden="true"></div>
       <div class="radar-wrap">
-        <canvas id="radar" class="radar jit" role="img" aria-label="Radar: range rings around the airport; aircraft arrive in phase D"></canvas>
-        <div class="hud hud-left" aria-hidden="true"><span>RNG 40 NM</span><span id="radar-poll">RADAR NOT YET RUNNING</span></div>
+        <canvas id="radar" class="radar jit" role="img" aria-label="Radar: the map and traffic around the airport. Drag to pan, scroll to zoom, click an aircraft to focus it; the tracks table lists the same aircraft."></canvas>
+        <div class="hud hud-left" aria-hidden="true"><span>RNG 40 NM</span><span id="radar-poll">RADAR WAITING</span></div>
         <div class="hud hud-right" aria-hidden="true"><span id="radar-tracks">0 TRACKS</span></div>
       </div>
       <div class="screen-title">
@@ -79,11 +79,11 @@
       <div class="tracks-body">
         <table class="tracks">
           <thead>
-            <tr><th>CALLSIGN</th><th>TYPE</th><th class="num">ALT FT</th><th class="num">GS KT</th><th class="num">TRK</th><th class="num">DIST NM</th><th class="num">SQWK</th></tr>
+            <tr id="tracks-head"></tr>
           </thead>
           <tbody id="tracks-body"></tbody>
         </table>
-        <p class="muted small empty" id="tracks-empty">NO TRACKS. THE RADAR ARRIVES IN PHASE D.</p>
+        <p class="muted small empty" id="tracks-empty">WAITING FOR THE RADAR</p>
       </div>
       <div class="screen-title"><span class="title-text">TRACKS</span></div>
     </section>
diff --git a/src/kcgx/web/static/cockpit.css b/src/kcgx/web/static/cockpit.css
index c2e9322..4ec7ec6 100644
--- a/src/kcgx/web/static/cockpit.css
+++ b/src/kcgx/web/static/cockpit.css
@@ -177,6 +177,7 @@ button, input { font: inherit; letter-spacing: inherit; color: inherit; }
 .lamp.on .lamp-light { background: var(--lamp); border-color: var(--lamp); }
 .lamp.warn { --lamp: var(--amber); }
 .lamp.fault { --lamp: var(--alarm); }
+.lamp.emerg .lamp-label { color: var(--alarm); }
 [data-glow="LOW"] .lamp.on .lamp-light, [data-glow="FULL"] .lamp.on .lamp-light { box-shadow: 0 0 10px var(--lamp); }
 
 /* tracks */
@@ -185,6 +186,19 @@ button, input { font: inherit; letter-spacing: inherit; color: inherit; }
 .tracks th { padding: 6px 8px; font-weight: 400; color: var(--muted); text-align: left; }
 .tracks th.num { text-align: right; }
 .empty { padding: 8px; }
+.tracks td { padding: 5px 8px; border-top: 1px solid var(--rule); white-space: nowrap; }
+.tracks td.num { text-align: right; }
+.tracks th .sort { all: unset; cursor: pointer; letter-spacing: inherit; }
+.tracks th .sort:focus-visible { outline: 2px solid var(--pink); outline-offset: 2px; }
+.tracks th[aria-sort="ascending"] .sort::after { content: " ▲"; color: var(--pink); }
+.tracks th[aria-sort="descending"] .sort::after { content: " ▼"; color: var(--pink); }
+.tracks .callsign { all: unset; cursor: pointer; color: var(--cyan); letter-spacing: 0.06em; }
+.tracks .callsign:focus-visible { outline: 2px solid var(--pink); outline-offset: 2px; }
+.tracks tr.emergency td, .tracks tr.emergency .callsign { color: var(--alarm); }
+.tracks tr.dimmed { opacity: 0.35; }
+.tracks tr.focused td { outline: 1px solid var(--pink); outline-offset: -1px; }
+.tracks tr.focused td, .tracks tr.focused .callsign { color: var(--pink); }
+.radar { cursor: crosshair; touch-action: none; }
 
 /* teletype */
 .log { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 12px 16px; display: flex; flex-direction: column; gap: 8px;
diff --git a/src/kcgx/web/static/js/lamps.js b/src/kcgx/web/static/js/lamps.js
index 37469e4..e7f88f9 100644
--- a/src/kcgx/web/static/js/lamps.js
+++ b/src/kcgx/web/static/js/lamps.js
@@ -1,6 +1,8 @@
 // The lamp bar (spec, Visual language): one lamp per feed, lit in its state
 // colour (cyan live, amber reconnecting, red offline, dark parked), then the
-// system lamps. RADAR and EMERG stay dark until phase D.
+// system lamps: RADAR (cyan polling, amber refused but holding a picture,
+// red orange refused with nothing), SERVER, AUDIO, and EMERG, dark until an
+// aircraft squawks 7500, 7600 or 7700, then red orange with the code.
 
 const SHORT = [
   [/clearance delivery/i, "DEL"], [/delivery/i, "DEL"], [/approach/i, "APP"], [/departure/i, "DEP"],
@@ -13,6 +15,8 @@ export function shortLabel(name) {
   return name.replace(/^[A-Z]{3,4}\s+/, "").slice(0, 4).toUpperCase();
 }
 
+const EMERGENCY = new Set(["7500", "7600", "7700"]);
+
 const LIT = { live: "live", starting: "warn", reconnecting: "warn", offline: "fault" };
 
 function lamp(label, colour, title) {
@@ -49,13 +53,32 @@ export function mountLamps(row, store) {
     gap.className = "lamp-gap";
     lamps.push(
       gap,
-      lamp("RADAR", null, "Radar, arrives in phase D"),
+      lamp("RADAR", radarColour(state.radar), radarTitle(state.radar)),
       lamp("SERVER", state.connected ? "live" : "fault", "Connection to the KCGX server"),
       lamp("AUDIO", state.connected ? (state.audioOk ? "live" : "fault") : null, "Audio output on the server"),
-      lamp("EMERG", null, "Emergency squawk, arrives in phase D"),
+      emergencyLamp(state.radar),
     );
     row.replaceChildren(...lamps);
   }
+  function radarColour(radar) {
+    if (!radar) return null;
+    if (!radar.error) return radar.age === null ? null : "live";
+    return radar.age === null ? "fault" : "warn";
+  }
+
+  function radarTitle(radar) {
+    if (!radar) return "Radar";
+    return radar.error ? `Radar refused: ${radar.error}` : "Radar polling adsb.lol";
+  }
+
+  function emergencyLamp(radar) {
+    const codes = [...new Set((radar ? radar.ac : []).map((a) => a.sq).filter((sq) => EMERGENCY.has(sq)))].sort();
+    if (!codes.length) return lamp("EMERG", null, "Emergency squawks: none");
+    const node = lamp(codes.join(" "), "fault", `Emergency squawk ${codes.join(", ")}`);
+    node.classList.add("emerg");
+    return node;
+  }
+
   store.subscribe((kind) => {
     if (kind !== "levels" && kind !== "chatter" && kind !== "message" && kind !== "volume") render();
   });
diff --git a/src/kcgx/web/static/js/main.js b/src/kcgx/web/static/js/main.js
index 8ea6bec..c0258b0 100644
--- a/src/kcgx/web/static/js/main.js
+++ b/src/kcgx/web/static/js/main.js
@@ -9,6 +9,7 @@ import { mountStatus } from "./status.js";
 import { mountLamps } from "./lamps.js";
 import { mountLog } from "./log.js";
 import { mountRadar } from "./radar.js";
+import { mountTracks } from "./tracks.js";
 import {
   CHOICES, mountAirportSheet, mountConfigSheet, mountFeedsSheet, mountShutdownSheet,
 } from "./sheets.js";
@@ -34,7 +35,10 @@ mountStatus({
   icao: $("icao"), name: $("airport-name"), where: $("airport-where"), zulu: $("zulu"), local: $("local"),
 }, store);
 mountLamps($("lamps"), store);
-const radar = mountRadar($("radar"), store);
+const radar = mountRadar($("radar"), store, {
+  hud: { poll: $("radar-poll"), tracks: $("radar-tracks"), position: $("radar-position") },
+});
+mountTracks({ head: $("tracks-head"), body: $("tracks-body"), empty: $("tracks-empty") }, store);
 
 const airportSheet = mountAirportSheet(
   { sheet: $("airport-sheet"), query: $("airport-query"), results: $("airport-results") }, store, log,
@@ -62,7 +66,8 @@ $("next-palette").addEventListener("click", () => {
   const next = all[(all.indexOf(store.state.prefs.palette) + 1) % all.length];
   send({ t: "prefs", palette: next });
 });
-$("recentre").addEventListener("click", () => radar.redraw());
+$("recentre").addEventListener("click", () => radar.recentre());
+window.kcgx = { radar, store }; // for the browser tests
 
 function banner() {
   const { state } = store;
diff --git a/src/kcgx/web/static/js/store.js b/src/kcgx/web/static/js/store.js
index 210f2c6..eba2950 100644
--- a/src/kcgx/web/static/js/store.js
+++ b/src/kcgx/web/static/js/store.js
@@ -4,6 +4,7 @@
 
 export const HISTORY = 160; // level samples kept per feed: 6.4 s at 25 Hz
 export const SILENT = -96;
+export const TRAIL = 12; // positions kept per aircraft: three minutes of polls
 
 export function createStore() {
   const state = {
@@ -19,6 +20,9 @@ export function createStore() {
     prefs: { palette: "WOPR", glow: "LOW", display: "CRT" },
     log: [],
     history: new Map(), // ident -> { samples: Float32Array, next: number }
+    radar: null, // the last aircraft frame
+    radarAt: 0, // performance.now() when it arrived
+    trails: new Map(), // hex -> [{ lat, lon }], oldest first
   };
   const listeners = new Set();
   const emit = (kind, detail) => { for (const fn of listeners) fn(kind, detail, state); };
@@ -32,9 +36,28 @@ export function createStore() {
     return h;
   }
 
+  // Each poll adds the aircraft's reported position to its trail; the page
+  // dead reckons from there between polls. An aircraft that drops out of
+  // the frame loses its trail.
+  function takeRadar(frame) {
+    state.radar = frame;
+    state.radarAt = performance.now();
+    const seen = new Set();
+    for (const ac of frame.ac) {
+      seen.add(ac.hex);
+      const trail = state.trails.get(ac.hex) || [];
+      const last = trail[trail.length - 1];
+      if (!last || last.lat !== ac.lat || last.lon !== ac.lon) trail.push({ lat: ac.lat, lon: ac.lon });
+      if (trail.length > TRAIL) trail.shift();
+      state.trails.set(ac.hex, trail);
+    }
+    for (const hex of [...state.trails.keys()]) if (!seen.has(hex)) state.trails.delete(hex);
+  }
+
   function apply(frame) {
     switch (frame.t) {
       case "snapshot":
+        if (!state.airport || !frame.airport || state.airport.icao !== frame.airport.icao) state.trails.clear();
         state.airport = frame.airport;
         state.loading = frame.loading;
         state.feeds = new Map(frame.feeds.map((f) => [f.ident, f]));
@@ -44,6 +67,7 @@ export function createStore() {
         state.audioOk = frame.audio_ok;
         state.prefs = { ...state.prefs, ...(frame.prefs || {}) };
         state.log = frame.log.slice(-200);
+        if (frame.radar) takeRadar(frame.radar);
         for (const ident of [...state.history.keys()]) {
           if (!state.feeds.has(ident)) state.history.delete(ident);
         }
@@ -77,6 +101,10 @@ export function createStore() {
         }
         emit("chatter");
         break;
+      case "aircraft":
+        takeRadar(frame);
+        emit("aircraft");
+        break;
       case "volume":
         state.volume = frame.value;
         emit("volume");
diff --git a/src/kcgx/web/static/js/theme.js b/src/kcgx/web/static/js/theme.js
index 0e0e50b..3a9c60f 100644
--- a/src/kcgx/web/static/js/theme.js
+++ b/src/kcgx/web/static/js/theme.js
@@ -10,6 +10,7 @@ export function colours() {
     cache = {
       cyan: read("--cyan"), dim: read("--dim"), pink: read("--pink"), white: read("--white"),
       amber: read("--amber"), alarm: read("--alarm"), muted: read("--muted"), text: read("--text"),
+      blue: read("--blue"), green: read("--green"), frame: read("--frame"),
     };
   }
   return cache;
```

- [ ] **Step 5:** `uv run kcgx-web --demo`, open it: the coast, the Columbia,
  rings, airways, Portland's class C rings, a dozen aircraft with trails,
  and the table sorted nearest first. Click an aircraft: it turns pink with
  a ring, the rest dim, and its row is outlined. Ctrl-C.
- [ ] **Step 6:** Suite: **1000 passed**, unchanged. Commit `feat(radar): the vector radar and the tracks table`.

---

### Task 9: The radar in a browser

**Files:** `tests/test_page.py`.

- [ ] **Step 1:** Apply:

```diff
diff --git a/tests/test_page.py b/tests/test_page.py
index 2bcfe68..819fc83 100644
--- a/tests/test_page.py
+++ b/tests/test_page.py
@@ -206,3 +206,129 @@ def test_the_volume_slider_reaches_the_server(page):
     page.fill("#volume", "100")
     page.dispatch_event("#volume", "input")
     page.wait_for_function("document.getElementById('freq-counts').textContent.includes('VOL 100%')")
+
+
+# -- the radar -----------------------------------------------------------------
+
+
+def radar_debug(page):
+    return page.evaluate("window.kcgx.radar.debug()")
+
+
+def on_screen(page, x, y):
+    """A canvas pixel position as a page position."""
+    box = page.eval_on_selector("#radar", "e => { const r = e.getBoundingClientRect(); return [r.left, r.top]; }")
+    ratio = page.evaluate("devicePixelRatio")
+    return box[0] + x / ratio, box[1] + y / ratio
+
+
+def wait_for_traffic(page):
+    """Until a frame has been drawn with the map and the aircraft on it: the
+    map arrives between two frames, and the labels are placed on the next."""
+    page.wait_for_function(
+        """() => { const d = window.kcgx.radar.debug();
+                   return d.loaded && d.hits.length > 0 && d.placed.some(p => p.key.startsWith('navaid:')); }"""
+    )
+
+
+def test_the_map_loads_for_the_airport_and_draws_its_places(page):
+    wait_for_traffic(page)
+    debug = radar_debug(page)
+    assert debug["mapFor"] == "KPDX"
+    assert debug["layers"]["coast"] > 0 and debug["layers"]["river"] > 0
+    keys = {p["key"] for p in debug["placed"]}
+    assert "home" in keys
+    assert any(k.startswith("navaid:") for k in keys) and any(k.startswith("city:") for k in keys)
+
+
+def test_every_aircraft_on_the_radar_is_a_row_in_the_table(page):
+    wait_for_traffic(page)
+    # Compared inside one evaluation, and retried, so a poll arriving between
+    # reading the radar and reading the table cannot make them disagree.
+    page.wait_for_function(
+        """() => {
+            const radar = window.kcgx.radar.debug().hits.map(h => h.hex).sort();
+            const rows = [...document.querySelectorAll('#tracks-body tr')].map(r => r.dataset.hex).sort();
+            const hud = document.getElementById('radar-tracks').textContent;
+            return rows.length >= 5 && radar.join() === rows.join() && hud === `${rows.length} TRACKS`;
+        }"""
+    )
+
+
+def test_clicking_an_aircraft_focuses_it_and_the_table_follows(page):
+    wait_for_traffic(page)
+    hits = radar_debug(page)["hits"]
+    # One with no other aircraft within 40 px, so the click cannot land on a neighbour.
+    hit = next(
+        h for h in hits
+        if all(o is h or abs(o["x"] - h["x"]) + abs(o["y"] - h["y"]) > 40 for o in hits)
+    )
+    page.mouse.click(*on_screen(page, hit["x"], hit["y"]))
+    page.wait_for_selector(f'#tracks-body tr.focused[data-hex="{hit["hex"]}"]')
+    assert page.eval_on_selector_all("#tracks-body tr.dimmed", "rs => rs.length") >= 4
+    # the callsign in the table is the same switch
+    page.click(f'#tracks-body tr[data-hex="{hit["hex"]}"] .callsign')
+    page.wait_for_function("document.querySelectorAll('#tracks-body tr.focused, #tracks-body tr.dimmed').length === 0")
+
+
+def test_place_names_brighten_under_the_pointer(page):
+    wait_for_traffic(page)
+    size = page.eval_on_selector("#radar", "c => [c.width, c.height]")
+    label = next(
+        p for p in radar_debug(page)["placed"]
+        if p["key"].startswith(("city:", "navaid:")) and p["x"] > 0 and p["y"] > 0
+        and p["x"] + p["w"] < size[0] and p["y"] + p["h"] < size[1]
+    )
+    page.mouse.move(*on_screen(page, label["x"] + label["w"] / 2, label["y"] + label["h"] / 2))
+    page.wait_for_function(f"window.kcgx.radar.debug().hovered === {label['key']!r}")
+    page.mouse.move(5, 5)
+    page.wait_for_function("window.kcgx.radar.debug().hovered === null")
+
+
+def test_the_wheel_zooms_dragging_pans_and_recentre_resets(page):
+    wait_for_traffic(page)
+    x, y = on_screen(page, 300, 300)
+    page.mouse.move(x, y)
+    page.mouse.wheel(0, -500)
+    page.wait_for_function("window.kcgx.radar.debug().view.zoom > 1.5")
+    page.mouse.down()
+    page.mouse.move(x + 120, y + 60, steps=6)
+    page.mouse.up()
+    view = radar_debug(page)["view"]
+    assert view["panX"] != 0 and view["panY"] != 0
+    page.click("#recentre")
+    assert radar_debug(page)["view"] == {"zoom": 1, "panX": 0, "panY": 0}
+
+
+def test_a_column_header_sorts_the_table(page):
+    wait_for_traffic(page)
+    page.wait_for_selector("#tracks-body tr")
+    page.click("#tracks-head button:text-is('ALT FT')")
+    alts = page.eval_on_selector_all(
+        "#tracks-body tr td:nth-child(3)", "cells => cells.map(c => c.textContent === 'GND' ? 0 : Number(c.textContent))"
+    )
+    assert alts == sorted(alts)
+    page.click("#tracks-head button:text-is('ALT FT')")
+    alts = page.eval_on_selector_all("#tracks-body tr td:nth-child(3)", "cells => cells.map(c => Number(c.textContent))")
+    assert alts == sorted(alts, reverse=True)
+
+
+def test_an_emergency_squawk_lights_the_lamp_and_turns_the_row_red(page):
+    wait_for_traffic(page)
+    page.evaluate(
+        """window.kcgx.store.apply({t: "aircraft", ok: true, error: "", age: 0, refresh: 15, range: 40,
+            ac: [{hex: "e1", label: "N52RT", type: "BE36", lat: 45.9, lon: -123.0, alt: 7500, gs: 150,
+                  trk: 120, sq: "7600", age: 0, dist: 25.2, brg: 315}]})"""
+    )
+    page.wait_for_selector(".lamp.emerg .lamp-label:text-is('7600')")
+    assert page.get_attribute('#tracks-body tr[data-hex="e1"]', "class") == "emergency"
+
+
+def test_a_refused_radar_says_so_and_dims_its_lamp(page):
+    wait_for_traffic(page)
+    page.evaluate(
+        """window.kcgx.store.apply({t: "aircraft", ok: false, error: "ERR 429", age: 40, refresh: 15,
+            range: 40, ac: []})"""
+    )
+    page.wait_for_function("document.getElementById('radar-poll').textContent.startsWith('ERR 429')")
+    assert "warn" in page.get_attribute(".lamp:has(.lamp-label:text-is('RADAR'))", "class")
```

- [ ] **Step 2:** `uv run --group dev --group browser pytest -q tests/test_page.py`:
  24 passed in about 45 s. Suite: **1008 passed**.
- [ ] **Step 3:** Commit `test(radar): the radar in a browser`.

---

### Task 10: By hand, on the Mac, with real traffic

Stop the terminal cockpit first (`kcgx stop` in `/Users/mikelse/kcgx`):
adsb-tui polls adsb.lol from the same address.

- [ ] `uv run kcgx-web`. Within 15 s the RADAR lamp lights and aircraft
  appear; the corner reads `POLLED nS AGO`.
- [ ] They move between polls and line up with the next poll without a jump
  of more than an aircraft's width.
- [ ] The map matches the real geography: the Columbia and Willamette, the
  coast, Portland's class C, the airways out of Battle Ground.
- [ ] Click an aircraft, then its callsign in the table, then another.
  Hover a city name. Wheel, drag, RECENTRE.
- [ ] CHANGE AIRPORT to KSEA: the map redraws itself over two seconds, the
  old traffic is gone, Seattle's class B appears, and traffic arrives.
- [ ] Turn off Wi-Fi for a minute: the corner reads `NO CONNECTION`, the
  RADAR lamp turns amber, the picture stays and fades; turn it back on and
  it recovers within two minutes.
- [ ] CONFIG: DISPLAY OFF stops the persistence; reduced motion (System
  Settings) stops the draw on.

---

### Task 11: Documentation

- [ ] **Step 1:** In `docs/README.md`, phase D links this plan and is marked built.
- [ ] **Step 2:** Add an Execution record section to this plan.
- [ ] **Step 3:** Commit `docs: phase D done`.

---

## Execution record

Built 2026-10-19 on `feat/web-cockpit`, one commit per task (73e032f to
6e332cd), from the dry-run files; before any change, every file the plan
modifies matched the dry run's base. On the branch, in the Mac's sandbox
without the browser tests: 984 passed, which is 1008 less the 24 in
`test_page.py`. Those passed against the same files in the cloud sandbox;
their first run on the branch is on the Mac. Task 10, by hand on the Mac,
is pending.

## Self-Review Notes

- **Dry run, 2026-10-19.** Every file and diff above was built in a scratch
  copy of the branch and run before this plan was written; the plan is
  generated from those files and rebuilds them byte for byte. Full suite
  **1007 passed, 1 skipped** in the Linux sandbox, where the skip is the
  existing root-only setup test (on the Mac: 1008). The browser tests ran
  twelve times in a row clean after the fixes below. The page was checked by
  eye against the mockup at 1440 by 900 and 820 by 1000, in WOPR and AMBER,
  zoomed and panned, with an aircraft focused, and through the demo's
  emergency minute.
- **What the dry run caught.** The map box near a pole took 38 degrees of
  longitude when the circle covers the pole itself, and widened by the
  latitude at its middle rather than its poleward edge. The FAA's airspace
  file is PolygonZ, which a Polygon-only reader skipped silently. The
  airport's big name sat over its ring with its leader through the text,
  and was placed after the other labels, so they could take its room. The
  focused row could be scrolled out of view. Three test races: reading the
  radar and the table at different moments, reading labels between the
  map's arrival and its first frame, and a gzip timestamp test that passed
  when both files were written in the same second. Two of my test
  expectations were wrong (a distance of 24 nm that is 25.2, and KPDX's
  longitude); the tests were corrected, not the code.
- **Revert checks, all run, each failing its named test:**

| Break | Test | Result |
|---|---|---|
| no pole case in the map box | `test_geodata.py -k pole` | 1 failed |
| no antimeridian shift | `test_geodata.py -k antimeridian` | 1 failed |
| no backoff | `test_radar.py -k backs_off` | 1 failed |
| no 15 s floor | `test_radar.py -k faster` | 1 failed |
| the old airport's late reply kept | `test_radar.py -k previous_airport` | 1 failed |
| an emergency line every poll | `test_radar.py -k logged_once` | 1 failed |
| nothing ever stale | `test_radar.py -k stale` | 1 failed |
| no User-Agent | `test_radar.py -k identifies` | 1 failed |
| UNK numbers not in order | `test_radar.py -k numbered` | 1 failed |
| no retarget on airport change | `test_station.py -k points_the_radar` | 1 failed |
| `radar=False` ignored | `test_server.py -k radar_off` | 1 failed |
| `--demo` polls adsb.lol | `test_page.py -k every_aircraft` | 1 failed |
| a timestamp in the gzip header | `test_build_geodata.py -k same_bytes` | 1 failed |
| PolygonZ refused | `test_build_geodata.py -k shapefile` | 1 failed, 1 passed |
| an NDB's position for a VOR's ident | `test_build_geodata.py -k chained` | 1 failed |
| airway gaps ignored | `test_build_geodata.py -k gap` | 1 failed |
| a click does not focus | `test_page.py -k focuses_it` | 1 failed |
| no hover | `test_page.py -k brighten` | 1 failed |
| sorting ignored | `test_page.py -k sorts` | 1 failed |
| the EMERG lamp stays dark | `test_page.py -k emergency` | 1 failed |
| the wheel ignored | `test_page.py -k wheel` | 1 failed |
| the map never decoded | `test_page.py -k map_loads` | 1 failed |

- **Lint.** `ruff check` reports nothing new on any touched file.
- **Not in this phase, on purpose:** screenshot references; airways outside
  the US; jet and RNAV routes; the launcher and the end of the terminal
  cockpit (E).
- **Test count:** 930 → 933 (T1) → 946 (T2) → 957 (T3) → 987 (T4) → 991
  (T5) → 994 (T6) → 1000 (T7) → 1000 (T8) → 1008 (T9), each measured by
  rebuilding the branch from this plan task by task.
