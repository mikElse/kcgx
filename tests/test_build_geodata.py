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


def test_runways_keep_their_width_in_feet_when_ourairports_gives_one(build, tmp_path):
    """A fifth element, width_ft, where the row has one; four where it is
    blank or not a number, and the page draws those at 150 ft. Closed
    runways, runways without both ends and airports not in the dataset are
    left out as before."""
    path = tmp_path / "runways.csv"
    path.write_text(
        "id,airport_ref,airport_ident,length_ft,width_ft,surface,lighted,closed,le_ident,"
        "le_latitude_deg,le_longitude_deg,he_ident,he_latitude_deg,he_longitude_deg\n"
        "1,1,KPDX,11000,150,ASP,1,0,10L,45.5938,-122.6062,28R,45.5888,-122.5636\n"
        "2,1,KPDX,9825,,ASP,1,0,10R,45.5824,-122.5969,28L,45.5782,-122.5606\n"
        "3,1,KPDX,6000,100.0,ASP,1,0,03,45.5813,-122.6066,21,45.5958,-122.5982\n"
        "4,1,KPDX,3000,75,ASP,1,1,08,45.5,-122.6,26,45.5,-122.5\n"
        "5,1,KPDX,3000,wide,ASP,1,0,09,45.51,-122.6,27,45.51,-122.5\n"
        "6,2,KTTD,5000,100,ASP,1,0,07,45.5,-122.4,,,\n"
        "7,3,KSEA,11900,150,CON,1,0,16L,47.46,-122.30,34R,47.43,-122.30\n"
    )
    out = build.runways(path, {"KPDX", "KTTD"})
    assert out == {"KPDX": sorted([
        [-1226062, 455938, -1225636, 455888, 150],
        [-1225969, 455824, -1225606, 455782],
        [-1226066, 455813, -1225982, 455958, 100],
        [-1226000, 455100, -1225000, 455100],
    ])}
