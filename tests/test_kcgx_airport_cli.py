"""Tests for the kcgx-airport console script.

This is the whole contract between bin/kcgx and the Python side, so the
record format is asserted precisely: bash splits it on tabs.
"""

from __future__ import annotations

from kcgx.__main__ import format_record, main
from kcgx.airports import Airport

PDX = Airport("KPDX", "PDX", "Portland International Airport", "Portland",
              "OR", "US", 45.5887, -122.598, "large")
ORD = Airport("KORD", "ORD", "Chicago O'Hare International Airport", "Chicago",
              "IL", "US", 41.9786, -87.9048, "large")
AIRPORTS = [PDX, ORD]


def run(argv, *, picker=None, **kwargs):
    return main(
        argv,
        airports_loader=lambda: AIRPORTS,
        picker=picker or (lambda airports, initial="": None),
        **kwargs,
    )


# -- the record format -----------------------------------------------------


def test_a_record_is_four_tab_separated_fields():
    fields = format_record(PDX).split("\t")
    assert len(fields) == 4
    assert fields[0] == "KPDX"
    assert float(fields[1]) == 45.5887
    assert float(fields[2]) == -122.598
    assert fields[3] == "Portland International Airport, Portland, OR"


def test_a_record_contains_no_tabs_inside_its_label():
    """bash reads this with IFS=$'\\t'; a tab in the label would shift fields."""
    assert format_record(ORD).count("\t") == 3


# -- resolve ---------------------------------------------------------------


def test_resolve_writes_the_current_airport(tmp_path, monkeypatch):
    import kcgx.__main__ as cli

    monkeypatch.setattr(cli, "current_icao", lambda: "KORD")
    out = tmp_path / "record"
    assert run(["resolve", "--out", str(out)]) == 0
    assert out.read_text().split("\t")[0] == "KORD"


def test_resolve_prints_to_stdout_without_out(capsys, monkeypatch):
    """KORD, not KPDX: KPDX is also state.FALLBACK_ICAO and Config's default
    icao, so a regression that ignored current_icao() and fell through to
    that default would produce the same output and this test would not
    catch it. KORD can only come from the monkeypatched current_icao."""
    import kcgx.__main__ as cli

    monkeypatch.setattr(cli, "current_icao", lambda: "KORD")
    assert run(["resolve"]) == 0
    assert capsys.readouterr().out.startswith("KORD\t")


def test_resolve_fails_loudly_on_an_airport_not_in_the_dataset(capsys, monkeypatch):
    import kcgx.__main__ as cli

    monkeypatch.setattr(cli, "current_icao", lambda: "ZZZZ")
    assert run(["resolve"]) == 2
    assert "ZZZZ" in capsys.readouterr().err


# -- pick ------------------------------------------------------------------


def test_pick_with_an_exact_icao_never_draws_the_picker(tmp_path):
    def explode(airports, initial=""):
        raise AssertionError("the picker must not open for an exact code")

    out = tmp_path / "record"
    assert run(["pick", "KORD", "--out", str(out)], picker=explode) == 0
    assert out.read_text().startswith("KORD\t")


def test_pick_opens_the_picker_for_a_vague_query(tmp_path):
    seen = {}

    def picker(airports, initial=""):
        seen["initial"] = initial
        return ORD

    out = tmp_path / "record"
    assert run(["pick", "chicago", "--out", str(out)], picker=picker) == 0
    assert seen["initial"] == "chicago", "the query should prefilter the picker"
    assert out.read_text().startswith("KORD\t")


def test_cancelling_the_picker_exits_1_and_writes_nothing(tmp_path):
    out = tmp_path / "record"
    assert run(["pick", "--out", str(out)], picker=lambda a, initial="": None) == 1
    assert not out.exists(), "a cancelled pick must leave no record to act on"


def test_a_successful_pick_is_remembered(tmp_path, monkeypatch):
    import kcgx.__main__ as cli

    remembered = []
    monkeypatch.setattr(cli, "write_airport", lambda icao: remembered.append(icao))
    run(["pick", "KORD", "--out", str(tmp_path / "r")], picker=lambda a, initial="": None)
    assert remembered == ["KORD"]


def test_a_cancelled_pick_is_not_remembered(tmp_path, monkeypatch):
    import kcgx.__main__ as cli

    remembered = []
    monkeypatch.setattr(cli, "write_airport", lambda icao: remembered.append(icao))
    run(["pick", "--out", str(tmp_path / "r")], picker=lambda a, initial="": None)
    assert remembered == []
