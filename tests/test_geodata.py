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
