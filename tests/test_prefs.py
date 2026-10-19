"""The page's look, remembered on the server (kcgx.prefs)."""

from __future__ import annotations

import json

from kcgx.prefs import DEFAULTS, clean, prefs_path, read_prefs, write_prefs


def test_nothing_remembered_gives_the_defaults(tmp_path):
    assert read_prefs(path=tmp_path / "prefs.json") == DEFAULTS


def test_written_prefs_read_back(tmp_path):
    path = tmp_path / "prefs.json"
    write_prefs({"palette": "AMBER", "glow": "FULL", "display": "VECTOR"}, path=path)
    assert read_prefs(path=path) == {"palette": "AMBER", "glow": "FULL", "display": "VECTOR"}


def test_unknown_values_and_keys_fall_back_to_the_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"palette": "PLAID", "glow": "full", "evil": "<script>"}))
    assert read_prefs(path=path) == {**DEFAULTS, "glow": "FULL"}


def test_a_broken_file_gives_the_defaults(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{not json")
    assert read_prefs(path=path) == DEFAULTS
    path.write_text("[1, 2]")
    assert read_prefs(path=path) == DEFAULTS


def test_clean_keeps_only_known_names():
    assert clean({"palette": "mono", "display": 3, "glow": "BRIGHT"}) == {"palette": "MONO"}


def test_failing_to_write_is_not_an_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    write_prefs(DEFAULTS, path=blocker / "prefs.json")  # parent is a file


def test_prefs_live_beside_the_remembered_airport(tmp_path, monkeypatch):
    monkeypatch.setenv("KCGX_STATE_PATH", str(tmp_path / "state" / "airport"))
    assert prefs_path() == tmp_path / "state" / "prefs.json"
