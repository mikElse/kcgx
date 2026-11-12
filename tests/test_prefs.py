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
    clean,
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


def test_the_defaults_are_the_plans_table():
    assert DEFAULTS == {
        "palette": "WOPR",
        "glow": "LOW",
        "display": "CRT",
        "scan_opacity": 34,
        "scan_size": 3,
        "lamps": False,
        "teletype": False,
        "range_nm": 40,
        "tag_fields": ["CALLSIGN", "ALT"],
        "box_items": [],
        "box_fill": 70,
        "box_pad": 4,
        "box_border": 50,
        "box_width": 1,
    }
    assert list(DEFAULTS) == list(SCHEMA)


def test_the_schema_is_the_plans_table():
    assert SCHEMA["palette"] == Choice(("WOPR", "AMBER", "MATRIX", "MONO"), "WOPR")
    assert SCHEMA["glow"] == Choice(("OFF", "LOW", "FULL"), "LOW")
    assert SCHEMA["display"] == Choice(("OFF", "VECTOR", "CRT"), "CRT")
    assert SCHEMA["scan_opacity"] == Number(0, 100, 34)
    assert SCHEMA["scan_size"] == Number(2, 8, 3)
    assert SCHEMA["lamps"] == Flag(False)
    assert SCHEMA["teletype"] == Flag(False)
    assert SCHEMA["range_nm"] == Number(10, 250, 40)
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


def test_every_default_passes_its_own_check():
    for key, spec in SCHEMA.items():
        assert spec.check(DEFAULTS[key]) == DEFAULTS[key], key


def test_choices_are_still_exported():
    assert CHOICES == {
        "palette": ("WOPR", "AMBER", "MATRIX", "MONO"),
        "glow": ("OFF", "LOW", "FULL"),
        "display": ("OFF", "VECTOR", "CRT"),
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


def test_a_subset_comes_back_without_repeats_in_schema_order():
    spec = Subset(("A", "B", "C"), ("A",))
    assert spec.check(["C", "A", "C"]) == ["A", "C"]
    assert spec.check([]) == []
    for bad in (["A", "D"], "A", ("A",), None, [1], [["A"]], {"A": True}):
        with pytest.raises(ValueError, match="must be a list drawn from A, B, C"):
            spec.check(bad)


# -- the file ----------------------------------------------------------------


def test_nothing_remembered_gives_the_defaults(tmp_path):
    assert read_prefs(path=tmp_path / "prefs.json") == DEFAULTS


def test_written_prefs_read_back(tmp_path):
    path = tmp_path / "prefs.json"
    write_prefs({"palette": "AMBER", "glow": "FULL", "display": "VECTOR"}, path=path)
    assert read_prefs(path=path) == {
        **DEFAULTS, "palette": "AMBER", "glow": "FULL", "display": "VECTOR",
    }


def test_a_stored_flag_number_and_subset_read_back(tmp_path):
    path = tmp_path / "prefs.json"
    chosen = {"lamps": True, "range_nm": 250, "tag_fields": ["CALLSIGN", "TYPE", "GS"]}
    write_prefs(chosen, path=path)
    assert json.loads(path.read_text()) == {**DEFAULTS, **chosen}
    assert read_prefs(path=path) == {**DEFAULTS, **chosen}


def test_unknown_values_and_keys_fall_back_to_the_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"palette": "PLAID", "glow": "full", "evil": "<script>"}))
    assert read_prefs(path=path) == {**DEFAULTS, "glow": "FULL"}


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
    ],
)
def test_one_bad_value_falls_back_without_disturbing_the_others(tmp_path, key, bad):
    good = {
        "palette": "MONO",
        "glow": "OFF",
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
    }
    assert stored(tmp_path, good) == good
    assert stored(tmp_path, {**good, key: bad}) == {**good, key: DEFAULTS[key]}


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


def test_a_broken_file_gives_the_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{not json")
    assert read_prefs(path=path) == DEFAULTS
    path.write_text("[1, 2]")
    assert read_prefs(path=path) == DEFAULTS


def test_clean_keeps_only_known_names():
    assert clean({"palette": "mono", "display": 3, "glow": "BRIGHT"}) == {"palette": "MONO"}


def test_clean_keeps_only_what_passes_its_check():
    assert clean({"lamps": True, "range_nm": 1000, "box_items": ["HUD", "HOME"], "theme": "WOPR"}) == {
        "lamps": True, "box_items": ["HOME", "HUD"],
    }


def test_only_a_choice_is_upper_cased():
    assert clean({"glow": "full", "tag_fields": ["callsign"]}) == {"glow": "FULL"}


def test_failing_to_write_is_not_an_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    write_prefs(DEFAULTS, path=blocker / "prefs.json")  # parent is a file


def test_prefs_live_beside_the_remembered_airport(tmp_path, monkeypatch):
    monkeypatch.setenv("KCGX_STATE_PATH", str(tmp_path / "state" / "airport"))
    assert prefs_path() == tmp_path / "state" / "prefs.json"


# -- the page ----------------------------------------------------------------


def test_the_page_starts_from_the_same_defaults():
    """store.js draws from its own copy until the first snapshot arrives."""
    literal = re.search(r"^\s*prefs: (\{.*?\n?\s*\}),$", STORE_JS.read_text(), re.M | re.S)
    assert literal, "store.js has no default prefs object"
    as_json = re.sub(r"(\w+):", r'"\1":', literal.group(1))
    as_json = re.sub(r",(\s*[}\]])", r"\1", as_json)  # trailing commas
    assert json.loads(as_json) == DEFAULTS
