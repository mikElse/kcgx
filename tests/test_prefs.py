"""Every setting, its schema, and the file it is remembered in (kcgx.prefs)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kcgx.prefs import (
    CHOICES,
    DEFAULTS,
    SCHEMA,
    Choice,
    Flag,
    Number,
    Subset,
    Table,
    clean,
    defaults,
    merge,
    prefs_path,
    read_prefs,
    write_prefs,
)

STORE_JS = Path(__file__).parent.parent / "src" / "kcgx" / "web" / "static" / "js" / "store.js"


def stored(tmp_path, values):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps(values))
    return read_prefs(path=path)


# -- the schema --------------------------------------------------------------


TRACK_COLS = (
    "CALLSIGN", "TYPE", "REG", "ALT", "VS", "GS", "TRK", "DIST", "BRG", "SQWK",
    "HEX", "CAT", "AGE", "LAT", "LON",
)

# The map table in the plan: a row has only the columns that mean something for it.
MAP = {
    "COAST": {"show": True, "alpha": 100, "line": "SOLID", "width": 18},
    "LAKE": {"show": True, "alpha": 75, "line": "SOLID", "width": 12},
    "RIVER": {"show": True, "alpha": 50, "line": "SOLID", "width": 10},
    "COUNTRY": {"show": True, "alpha": 90, "line": "DASH", "width": 12},
    "STATE": {"show": True, "alpha": 55, "line": "SOLID", "width": 10},
    "AIRWAY": {"show": True, "alpha": 70, "line": "DASH", "width": 12},
    "CLASS_B": {"show": True, "alpha": 90, "line": "DASH", "width": 14},
    "CLASS_C": {"show": True, "alpha": 80, "line": "DASH", "width": 13},
    "CLASS_D": {"show": True, "alpha": 45, "line": "DOT", "width": 10},
    "RUNWAYS": {"show": True, "alpha": 100, "width": 16},
    "RINGS": {"show": True, "alpha": 35, "line": "SOLID", "width": 10, "label": 12},
    "HOME": {"show": True, "alpha": 100, "width": 18, "label": 30},
    "AIRPORTS": {"show": True, "alpha": 85, "width": 13, "label": 13},
    "NAVAIDS": {"show": True, "alpha": 85, "width": 13, "label": 13},
    "CITIES": {"show": True, "alpha": 85, "width": 13, "label": 13},
    "PEAKS": {"show": True, "alpha": 85, "width": 13, "label": 13},
    "STATE_NAMES": {"show": True, "alpha": 100, "label": 14},
}


def test_the_defaults_are_the_plans_tables():
    assert DEFAULTS == {
        # General
        "boot_anim": True,
        "ui_zoom": 100,
        "font": "CLASSIC",
        "font_px": 13,
        "clock_24h": True,
        "clock_seconds": False,
        "clock_zone": True,
        "palette": "WOPR",
        "display": "CRT",
        "scan_opacity": 34,
        "scan_size": 3,
        "glow_map": 33,
        "glow_traffic": 33,
        "glow_text": 33,
        "aa": "ON",
        "burn_in": 19,
        "fps_max": 60,
        "poll_secs": 15,
        "motion": "GLIDE",
        "view_ease": "QUICK",
        "zoom_speed": 100,
        "lamps": False,
        "teletype": False,
        # Traffic
        "range_nm": 40,
        "tag_fields": ["CALLSIGN", "ALT"],
        "box_items": [],
        "box_fill": 70,
        "box_pad": 4,
        "box_border": 50,
        "box_width": 1,
        "map": MAP,
        "label_min": 9,
        "label_max": 26,
        "tag_px": 16,
        "follow_nm": 10,
        "info_box": True,
        "tail_secs": 180,
        "tail_alpha": 95,
        "tail_alpha_min": 35,
        "tail_alpha_max": 95,
        "tail_gs_low": 40,
        "tail_gs_high": 250,
        "ground_mode": "FADE",
        "ground_gs": 5,
        "ground_alt": 0,
        "ground_min": 2,
        "ground_alpha": 25,
        # Tracks
        "track_cols": ["CALLSIGN", "TYPE", "ALT", "GS", "TRK", "DIST", "SQWK"],
        "track_sort": "DIST",
        "track_desc": False,
        "sort_floor": 40,
        "tracks_open": True,
        "tracks_pct": 24,
        # Frequencies
        "short_names": True,
    }
    assert list(DEFAULTS) == list(SCHEMA)
    assert list(DEFAULTS["map"]) == list(MAP), "the map's rows are in the plan's order"


def test_the_schema_is_the_plans_tables():
    # General
    assert SCHEMA["boot_anim"] == Flag(True)
    assert SCHEMA["ui_zoom"] == Number(50, 200, 100, step=5)
    assert SCHEMA["font"] == Choice(("CLASSIC", "B612", "SHARETECH", "PLEX", "JETBRAINS", "VT323", "SYSTEM"), "CLASSIC")
    assert SCHEMA["font_px"] == Number(10, 20, 13)
    assert SCHEMA["clock_24h"] == Flag(True)
    assert SCHEMA["clock_seconds"] == Flag(False)
    assert SCHEMA["clock_zone"] == Flag(True)
    assert SCHEMA["palette"] == Choice(("WOPR", "AMBER", "MATRIX", "MONO"), "WOPR")
    assert SCHEMA["display"] == Choice(("OFF", "VECTOR", "CRT"), "CRT")
    assert SCHEMA["scan_opacity"] == Number(0, 100, 34)
    assert SCHEMA["scan_size"] == Number(2, 8, 3)
    for layer in ("map", "traffic", "text"):
        assert SCHEMA[f"glow_{layer}"] == Number(0, 100, 33)
    assert SCHEMA["aa"] == Choice(("OFF", "ON", "SUPER"), "ON")
    assert SCHEMA["burn_in"] == Number(0, 100, 19)
    assert SCHEMA["fps_max"] == Number(15, 120, 60)
    assert SCHEMA["poll_secs"] == Number(15, 120, 15, step=5)
    assert SCHEMA["motion"] == Choice(("GLIDE", "STEP"), "GLIDE")
    assert SCHEMA["view_ease"] == Choice(("OFF", "QUICK", "SMOOTH"), "QUICK")
    assert SCHEMA["zoom_speed"] == Number(25, 400, 100)
    assert SCHEMA["lamps"] == Flag(False)
    assert SCHEMA["teletype"] == Flag(False)
    # Traffic
    assert SCHEMA["range_nm"] == Number(10, 250, 40, step=10)  # as its slider, since phase F
    assert SCHEMA["tag_fields"] == Subset(
        ("CALLSIGN", "TYPE", "SQWK", "ALT", "GS", "TRK", "DIST"), ("CALLSIGN", "ALT")
    )
    assert SCHEMA["box_items"] == Subset(
        ("AIRCRAFT", "HOME", "AIRPORTS", "NAVAIDS", "CITIES", "PEAKS", "STATES", "RINGS", "HUD"), ()
    )
    assert SCHEMA["box_fill"] == Number(0, 100, 70)
    assert SCHEMA["box_pad"] == Number(0, 12, 4)
    assert SCHEMA["box_border"] == Number(0, 100, 50)
    assert SCHEMA["box_width"] == Number(1, 5, 1)
    table = SCHEMA["map"]
    assert isinstance(table, Table)
    assert list(table.columns) == ["show", "alpha", "line", "width", "label"]
    assert isinstance(table.columns["show"], Flag)
    assert (table.columns["alpha"].low, table.columns["alpha"].high) == (0, 100)
    assert table.columns["line"].names == ("SOLID", "DASH", "DOT")
    assert (table.columns["width"].low, table.columns["width"].high) == (5, 80)  # tenths of a pixel
    assert (table.columns["label"].low, table.columns["label"].high) == (8, 32)  # px
    assert table.rows == MAP
    assert SCHEMA["label_min"] == Number(6, 20, 9)
    assert SCHEMA["label_max"] == Number(12, 48, 26)
    assert SCHEMA["tag_px"] == Number(10, 28, 16)
    assert SCHEMA["follow_nm"] == Number(1, 50, 10)
    assert SCHEMA["info_box"] == Flag(True)
    assert SCHEMA["tail_secs"] == Number(0, 600, 180, step=15)
    assert SCHEMA["tail_alpha"] == Number(0, 100, 95)
    assert SCHEMA["tail_alpha_min"] == Number(0, 100, 35)
    assert SCHEMA["tail_alpha_max"] == Number(0, 100, 95)
    assert SCHEMA["tail_gs_low"] == Number(0, 600, 40)
    assert SCHEMA["tail_gs_high"] == Number(0, 600, 250)
    assert SCHEMA["ground_mode"] == Choice(("SHOW", "FADE", "HIDE"), "FADE")
    assert SCHEMA["ground_gs"] == Number(0, 50, 5)
    assert SCHEMA["ground_alt"] == Number(0, 5000, 0, step=100)
    assert SCHEMA["ground_min"] == Number(0, 30, 2)
    assert SCHEMA["ground_alpha"] == Number(0, 100, 25)
    # Tracks
    assert SCHEMA["track_cols"] == Subset(TRACK_COLS, ("CALLSIGN", "TYPE", "ALT", "GS", "TRK", "DIST", "SQWK"))
    assert SCHEMA["track_sort"] == Choice(TRACK_COLS, "DIST")
    assert SCHEMA["track_desc"] == Flag(False)
    assert SCHEMA["sort_floor"] == Number(0, 100, 40)
    assert SCHEMA["tracks_open"] == Flag(True)
    assert SCHEMA["tracks_pct"] == Number(10, 80, 24)
    # Frequencies
    assert SCHEMA["short_names"] == Flag(True)


def test_glow_the_choice_is_gone():
    assert "glow" not in SCHEMA


def test_every_default_passes_its_own_check():
    for key, spec in SCHEMA.items():
        assert spec.check(DEFAULTS[key]) == DEFAULTS[key], key


def test_every_cell_of_the_maps_defaults_passes_its_column():
    table = SCHEMA["map"]
    for row, cells in table.rows.items():
        for col, value in cells.items():
            assert table.columns[col].check(value) == value, (row, col)


def test_choices_are_still_exported():
    assert CHOICES == {
        "font": ("CLASSIC", "B612", "SHARETECH", "PLEX", "JETBRAINS", "VT323", "SYSTEM"),
        "palette": ("WOPR", "AMBER", "MATRIX", "MONO"),
        "display": ("OFF", "VECTOR", "CRT"),
        "aa": ("OFF", "ON", "SUPER"),
        "motion": ("GLIDE", "STEP"),
        "view_ease": ("OFF", "QUICK", "SMOOTH"),
        "ground_mode": ("SHOW", "FADE", "HIDE"),
        "track_sort": TRACK_COLS,
    }


def test_a_choice_is_one_of_its_names_exactly():
    spec = Choice(("A", "B"), "A")
    assert spec.check("B") == "B"
    for bad in ("b", "C", 1, None, ["A"]):
        with pytest.raises(ValueError, match="must be one of A, B"):
            spec.check(bad)


def test_a_flag_is_a_boolean_and_nothing_else():
    spec = Flag(False)
    assert spec.check(True) is True
    assert spec.check(False) is False
    for bad in (1, 0, "true", None):
        with pytest.raises(ValueError, match="must be true or false"):
            spec.check(bad)


def test_a_number_is_a_whole_number_in_range():
    spec = Number(2, 8, 3)
    assert spec.check(2) == 2
    assert spec.check(8) == 8
    for bad in (1, 9, True, 3.0, 3.5, "3", None):
        with pytest.raises(ValueError, match="must be a whole number from 2 to 8"):
            spec.check(bad)


def test_a_number_moves_in_whole_steps_from_its_low_end():
    assert Number(2, 8, 3).step == 1
    spec = Number(15, 120, 15, step=5)
    assert [spec.check(v) for v in (15, 20, 115, 120)] == [15, 20, 115, 120]
    for bad in (16, 119, 10, 125, 20.0, True, "20"):
        with pytest.raises(ValueError, match="^must be a whole number from 15 to 120 in steps of 5$"):
            spec.check(bad)
    # The steps count from `low`, not from 0.
    assert Number(1, 21, 1, step=10).check(11) == 11
    with pytest.raises(ValueError, match="in steps of 10"):
        Number(1, 21, 1, step=10).check(10)


def test_every_numbers_step_lands_on_both_ends_and_its_default():
    for key, spec in SCHEMA.items():
        if isinstance(spec, Number):
            assert spec.step >= 1, key
            assert (spec.high - spec.low) % spec.step == 0 and (spec.default - spec.low) % spec.step == 0, key


def test_a_subset_comes_back_without_repeats_in_schema_order():
    spec = Subset(("A", "B", "C"), ("A",))
    assert spec.check(["C", "A", "C"]) == ["A", "C"]
    assert spec.check([]) == []
    for bad in (["A", "D"], "A", ("A",), None, [1], [["A"]], {"A": True}):
        with pytest.raises(ValueError, match="must be a list drawn from A, B, C"):
            spec.check(bad)


def small_table():
    return Table(
        columns={"show": Flag(True), "alpha": Number(0, 100, 100), "line": Choice(("SOLID", "DASH"), "SOLID")},
        rows={"A": {"show": True, "alpha": 100, "line": "SOLID"}, "B": {"show": False, "alpha": 50}},
    )


def test_a_table_takes_any_rows_and_any_of_each_rows_own_columns():
    table = small_table()
    assert table.check({"A": {"alpha": 60}}) == {"A": {"alpha": 60}}
    assert table.check({"B": {"show": True, "alpha": 0}, "A": {"line": "DASH"}}) == {
        "B": {"show": True, "alpha": 0}, "A": {"line": "DASH"},
    }
    assert table.check({}) == {}
    assert table.check(table.default) == table.default


def test_a_tables_default_is_every_row_and_a_copy_of_its_own():
    table = small_table()
    assert table.default == {"A": {"show": True, "alpha": 100, "line": "SOLID"}, "B": {"show": False, "alpha": 50}}
    table.default["A"]["alpha"] = 1
    assert table.rows["A"]["alpha"] == 100
    assert table.default["A"] is not table.default["A"]


@pytest.mark.parametrize(
    "bad, said",
    [
        ([], "must be an object of rows"),
        ("A", "must be an object of rows"),
        ({"C": {"alpha": 1}}, "C"),  # an unknown row
        ({"A": 1}, "A"),  # a row that is not an object
        ({"A": {"width": 1}}, "A.width"),  # an unknown column
        ({"B": {"line": "DASH"}}, "B.line"),  # a column the row does not have
        ({"A": {"alpha": 101}}, "A.alpha"),  # a cell that fails its spec
        ({"A": {"alpha": 50.0}}, "A.alpha"),
        ({"A": {"show": 1}}, "A.show"),
        ({"A": {"line": "dash"}}, "A.line"),
    ],
)
def test_a_table_refuses_what_it_does_not_have_naming_the_cell(bad, said):
    with pytest.raises(ValueError) as refused:
        small_table().check(bad)
    assert f"{refused.value} ".startswith(said + " "), str(refused.value)


def test_clean_drops_only_the_cells_of_a_table_that_fail():
    dirty = {
        "map": {
            "COAST": {"alpha": 60, "width": 999, "label": 12},  # too wide; COAST has no label
            "LAKE": {"show": False, "line": "dash"},  # a choice is upper cased, as at the top level
            "NOWHERE": {"alpha": 1},  # no such row
            "RIVER": "on",  # not an object
            "RUNWAYS": {"line": "DOT", "alpha": 20},  # RUNWAYS has no line
        },
    }
    assert clean(dirty) == {
        "map": {"COAST": {"alpha": 60}, "LAKE": {"show": False, "line": "DASH"}, "RUNWAYS": {"alpha": 20}},
    }
    assert clean({"map": "everything"}) == {}
    assert clean({"map": []}) == {}


def test_a_partial_table_stored_reads_back_over_the_defaults(tmp_path):
    prefs = stored(tmp_path, {"map": {"COAST": {"alpha": 60}, "HOME": {"label": 20, "show": False}}})
    assert prefs["map"]["COAST"] == {**DEFAULTS["map"]["COAST"], "alpha": 60}
    assert prefs["map"]["HOME"] == {**DEFAULTS["map"]["HOME"], "label": 20, "show": False}
    assert {row: cells for row, cells in prefs["map"].items() if row not in ("COAST", "HOME")} == {
        row: cells for row, cells in DEFAULTS["map"].items() if row not in ("COAST", "HOME")
    }
    assert list(prefs["map"]) == list(DEFAULTS["map"])


def test_a_table_is_written_whole(tmp_path):
    path = tmp_path / "prefs.json"
    write_prefs({"map": {"CLASS_D": {"line": "DASH"}}}, path=path)
    written = json.loads(path.read_text())["map"]
    assert written == {**DEFAULTS["map"], "CLASS_D": {**DEFAULTS["map"]["CLASS_D"], "line": "DASH"}}
    assert DEFAULTS["map"]["CLASS_D"]["line"] == "DOT", "writing changed the defaults"
    assert read_prefs(path=path)["map"] == written


def test_merge_takes_a_table_a_cell_at_a_time_and_everything_else_whole():
    before = defaults()
    after = merge(before, {"map": {"COAST": {"alpha": 60}}, "tag_fields": ["DIST"], "palette": "MONO"})
    assert after["map"]["COAST"] == {**DEFAULTS["map"]["COAST"], "alpha": 60}
    assert after["map"]["LAKE"] == DEFAULTS["map"]["LAKE"]
    assert after["tag_fields"] == ["DIST"] and after["palette"] == "MONO"
    # Two changes to two cells, one after the other: both land.
    both = merge(after, {"map": {"COAST": {"width": 30}, "LAKE": {"show": False}}})
    assert both["map"]["COAST"] == {**DEFAULTS["map"]["COAST"], "alpha": 60, "width": 30}
    assert both["map"]["LAKE"] == {**DEFAULTS["map"]["LAKE"], "show": False}
    # Neither what it merged into nor what it merged is changed.
    assert before == DEFAULTS
    assert after["map"]["COAST"]["width"] == DEFAULTS["map"]["COAST"]["width"]
    assert after["map"]["LAKE"]["show"] is True


def test_merge_into_a_table_with_rows_missing_adds_them():
    assert merge({"map": {}}, {"map": {"COAST": {"alpha": 60}}}) == {"map": {"COAST": {"alpha": 60}}}
    assert merge({}, {"map": {"COAST": {"alpha": 60}}}) == {"map": {"COAST": {"alpha": 60}}}


# -- the glow, from one choice to three numbers -------------------------------


@pytest.mark.parametrize("glow, level", [("OFF", 0), ("LOW", 33), ("FULL", 75), ("full", 75)])
def test_a_stored_glow_becomes_the_three_glow_numbers(tmp_path, glow, level):
    prefs = stored(tmp_path, {"glow": glow, "palette": "AMBER"})
    assert prefs == {**DEFAULTS, "palette": "AMBER", "glow_map": level, "glow_traffic": level, "glow_text": level}
    assert "glow" not in prefs


def test_a_stored_glow_number_beats_the_migration(tmp_path):
    prefs = stored(tmp_path, {"glow": "FULL", "glow_map": 10})
    assert (prefs["glow_map"], prefs["glow_traffic"], prefs["glow_text"]) == (10, 75, 75)


@pytest.mark.parametrize("bad", [150, "bad", -1, 33.0, True, None])
def test_a_stored_glow_number_that_fails_its_check_does_not_block_the_migration(tmp_path, bad):
    prefs = stored(tmp_path, {"glow": "FULL", "glow_map": bad})
    assert (prefs["glow_map"], prefs["glow_traffic"], prefs["glow_text"]) == (75, 75, 75)


def test_a_bad_stored_glow_number_beside_a_good_one(tmp_path):
    prefs = stored(tmp_path, {"glow": "LOW", "glow_map": "bad", "glow_traffic": 150, "glow_text": 90})
    assert (prefs["glow_map"], prefs["glow_traffic"], prefs["glow_text"]) == (33, 33, 90)


def test_a_stored_glow_that_is_not_one_of_the_three_is_ignored(tmp_path):
    assert stored(tmp_path, {"glow": "BRIGHT"}) == DEFAULTS
    assert stored(tmp_path, {"glow": 2}) == DEFAULTS


def test_the_migrated_glow_is_written_as_the_three_numbers(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"glow": "OFF"}))
    write_prefs(read_prefs(path=path), path=path)
    written = json.loads(path.read_text())
    assert "glow" not in written
    assert (written["glow_map"], written["glow_traffic"], written["glow_text"]) == (0, 0, 0)


# -- the file ----------------------------------------------------------------


def test_nothing_remembered_gives_the_defaults(tmp_path):
    assert read_prefs(path=tmp_path / "prefs.json") == DEFAULTS


def test_written_prefs_read_back(tmp_path):
    path = tmp_path / "prefs.json"
    write_prefs({"palette": "AMBER", "glow_text": 75, "display": "VECTOR"}, path=path)
    assert read_prefs(path=path) == {
        **DEFAULTS, "palette": "AMBER", "glow_text": 75, "display": "VECTOR",
    }


def test_a_stored_flag_number_and_subset_read_back(tmp_path):
    path = tmp_path / "prefs.json"
    chosen = {"lamps": True, "range_nm": 250, "tag_fields": ["CALLSIGN", "TYPE", "GS"]}
    write_prefs(chosen, path=path)
    assert json.loads(path.read_text()) == {**DEFAULTS, **chosen}
    assert read_prefs(path=path) == {**DEFAULTS, **chosen}


def test_unknown_values_and_keys_fall_back_to_the_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"palette": "PLAID", "display": "vector", "evil": "<script>"}))
    assert read_prefs(path=path) == {**DEFAULTS, "display": "VECTOR"}


@pytest.mark.parametrize(
    "key, bad",
    [
        ("range_nm", 251),  # out of range
        ("range_nm", 9),
        ("scan_size", True),  # true is not 1
        ("box_fill", 70.0),  # a float
        ("box_pad", "4"),
        ("lamps", 1),  # 1 is not true
        ("teletype", "true"),
        ("tag_fields", ["CALLSIGN", "COLOUR"]),  # an unknown name
        ("tag_fields", "CALLSIGN"),  # not a list
        ("box_items", {"HUD": True}),
        ("box_items", None),
        ("display", 3),
        ("glow_map", 101),
        ("aa", "MAX"),
        ("poll_secs", 10),  # adsb.lol asks for no more than one request every 15 s
        ("poll_secs", 17),  # off its steps of 5
        ("ui_zoom", 101),
        ("tail_secs", 100),
        ("ground_alt", 150),
        ("range_nm", 45),
        ("track_cols", ["CALLSIGN", "COLOUR"]),
        ("map", "on"),
    ],
)
def test_one_bad_value_falls_back_without_disturbing_the_others(tmp_path, key, bad):
    good = {
        "palette": "MONO",
        "glow_map": 0,
        "display": "VECTOR",
        "scan_opacity": 50,
        "scan_size": 5,
        "lamps": True,
        "teletype": True,
        "range_nm": 120,
        "tag_fields": ["TYPE", "DIST"],
        "box_items": ["HOME", "HUD"],
        "box_fill": 10,
        "box_pad": 0,
        "box_border": 100,
        "box_width": 5,
        "aa": "SUPER",
        "poll_secs": 60,
        "track_cols": ["HEX", "LAT"],
        "map": {**DEFAULTS["map"], "COAST": {**DEFAULTS["map"]["COAST"], "alpha": 10}},
    }
    assert stored(tmp_path, good) == {**DEFAULTS, **good}
    assert stored(tmp_path, {**good, key: bad}) == {**DEFAULTS, **good, key: DEFAULTS[key]}


def test_a_hand_edited_range_off_its_steps_of_ten_reads_as_the_default(tmp_path):
    """Phase F read a hand edited 45 as 45 NM. The range moves in tens now,
    as its slider always has, so 45 is not a setting: it falls back to 40."""
    assert stored(tmp_path, {"range_nm": 45})["range_nm"] == 40
    assert stored(tmp_path, {"range_nm": 50})["range_nm"] == 50
    assert clean({"range_nm": 45, "ui_zoom": 105, "poll_secs": 16}) == {"ui_zoom": 105}


def test_a_subset_is_stored_without_repeats_in_schema_order(tmp_path):
    path = tmp_path / "prefs.json"
    write_prefs({"tag_fields": ["DIST", "ALT", "CALLSIGN", "ALT"]}, path=path)
    assert json.loads(path.read_text())["tag_fields"] == ["CALLSIGN", "ALT", "DIST"]
    assert read_prefs(path=path)["tag_fields"] == ["CALLSIGN", "ALT", "DIST"]


def test_an_empty_subset_is_a_choice_not_a_missing_one(tmp_path):
    path = tmp_path / "prefs.json"
    write_prefs({"tag_fields": []}, path=path)
    assert json.loads(path.read_text())["tag_fields"] == []
    assert read_prefs(path=path)["tag_fields"] == []
    assert clean({"tag_fields": []}) == {"tag_fields": []}


def test_reading_never_hands_out_the_defaults_own_lists(tmp_path):
    first = read_prefs(path=tmp_path / "prefs.json")
    first["tag_fields"].append("DIST")
    first["box_items"].append("HUD")
    assert DEFAULTS["tag_fields"] == ["CALLSIGN", "ALT"]
    assert read_prefs(path=tmp_path / "prefs.json")["box_items"] == []


def test_defaults_are_a_copy_with_lists_of_its_own():
    mine = defaults()
    assert mine == DEFAULTS
    mine["palette"] = "MONO"
    mine["tag_fields"].append("DIST")
    mine["box_items"].append("HUD")
    assert DEFAULTS["palette"] == "WOPR"
    assert DEFAULTS["tag_fields"] == ["CALLSIGN", "ALT"]
    assert DEFAULTS["box_items"] == []
    assert defaults() == DEFAULTS


def test_a_broken_file_gives_the_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{not json")
    assert read_prefs(path=path) == DEFAULTS
    path.write_text("[1, 2]")
    assert read_prefs(path=path) == DEFAULTS


def test_clean_keeps_only_known_names():
    assert clean({"palette": "mono", "display": 3, "glow": "FULL"}) == {"palette": "MONO"}


def test_clean_keeps_only_what_passes_its_check():
    assert clean({"lamps": True, "range_nm": 1000, "box_items": ["HUD", "HOME"], "theme": "WOPR"}) == {
        "lamps": True, "box_items": ["HOME", "HUD"],
    }


def test_only_a_choice_is_upper_cased():
    assert clean({"aa": "super", "tag_fields": ["callsign"], "boot_anim": "true"}) == {"aa": "SUPER"}


def test_failing_to_write_is_not_an_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    write_prefs(DEFAULTS, path=blocker / "prefs.json")  # parent is a file


def test_prefs_live_beside_the_remembered_airport(tmp_path, monkeypatch):
    monkeypatch.setenv("KCGX_STATE_PATH", str(tmp_path / "state" / "airport"))
    assert prefs_path() == tmp_path / "state" / "prefs.json"


# -- the page ----------------------------------------------------------------


def object_literal(text: str, start: int) -> str:
    """The `{...}` that opens at `start`, nested braces and all."""
    depth = 0
    for at in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[at], 0)
        if depth == 0:
            return text[start:at + 1]
    raise AssertionError("an object that never closes")


def test_the_page_starts_from_the_same_defaults():
    """store.js draws from its own copy until the first snapshot arrives."""
    text = STORE_JS.read_text()
    opened = re.search(r"^\s*prefs: \{", text, re.M)
    assert opened, "store.js has no default prefs object"
    literal = object_literal(text, opened.end() - 1)
    literal = re.sub(r"//[^\n]*", "", literal)  # comments
    as_json = re.sub(r"(\w+):", r'"\1":', literal)
    as_json = re.sub(r",(\s*[}\]])", r"\1", as_json)  # trailing commas
    assert json.loads(as_json) == DEFAULTS


def test_the_page_servers_prefs_start_without_the_boot_animation(page_state):
    """Page tests run with the boot animation off (conftest), so that nothing
    covers the cockpit while they work it; the boot tests turn it on."""
    assert json.loads((page_state / "prefs.json").read_text()) == {"boot_anim": False}
    assert read_prefs(path=page_state / "prefs.json") == {**DEFAULTS, "boot_anim": False}
