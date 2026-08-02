"""Tests for the kcgx-airport console script.

This is the whole contract between bin/kcgx and the Python side, so the
record format is asserted precisely: bash splits it on tabs.
"""

from __future__ import annotations

import inspect

from kcgx.__main__ import format_record, main, write_airport
from kcgx.airports import Airport

PDX = Airport("KPDX", "PDX", "Portland International Airport", "Portland",
              "OR", "US", 45.5887, -122.598, "large")
ORD = Airport("KORD", "ORD", "Chicago O'Hare International Airport", "Chicago",
              "IL", "US", 41.9786, -87.9048, "large")
AIRPORTS = [PDX, ORD]


def run(argv, *, picker=None, state_writer=None, airports_loader=None, **kwargs):
    """Never let a test reach the real write_airport: default state_writer
    to a no-op unless a test explicitly wants to observe it. A test that
    monkeypatches kcgx.__main__.write_airport instead of going through this
    seam is exactly the mistake that leaked into the user's real
    ~/.local/state/kcgx/airport -- this default is the fix, not a
    convention callers have to remember."""
    return main(
        argv,
        airports_loader=airports_loader or (lambda: AIRPORTS),
        picker=picker or (lambda airports, initial="": None),
        state_writer=state_writer or (lambda icao: None),
        **kwargs,
    )


# -- unexpected failures ----------------------------------------------------


def test_an_unexpected_exception_exits_2_not_1(capsys):
    """Python's default exit code for an unhandled exception is 1 -- the code
    this CLI's contract reserves for "the user declined". bin/kcgx reads 1 as
    a cancel and exits 0 in silence, so a crash anywhere in here would leave
    `kcgx go portland` printing nothing, changing nothing, and reporting
    success. That is exactly the failure
    test_go_reports_a_failed_search_instead_of_calling_it_a_cancel exists to
    prevent, reached by a route that test cannot see.
    """
    def boom():
        raise RuntimeError("the dataset caught fire")

    assert run(["pick", "portland"], airports_loader=boom) == 2

    err = capsys.readouterr().err
    assert "the dataset caught fire" in err, "a silent failure reads as a cancel"
    assert "RuntimeError" in err, "name the failure, or it cannot be diagnosed"


def test_an_unexpected_exception_does_not_surface_as_a_traceback(capsys):
    """The popup is 20 rows and disappears when the command exits; a
    traceback there is unreadable. Type and message are what survive."""
    def boom():
        raise ValueError("nope")

    assert run(["resolve"], airports_loader=boom) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_argparse_still_gets_to_exit_on_its_own_terms(capsys):
    """`--help` and a bad mode raise SystemExit. Swallowing those would turn
    the usage text into "ValueError: 0"."""
    import pytest

    with pytest.raises(SystemExit) as exit_info:
        run(["--help"])
    assert exit_info.value.code == 0

    with pytest.raises(SystemExit) as exit_info:
        run(["frobnicate"])
    assert exit_info.value.code == 2


def test_an_interrupt_is_a_decline_not_a_crash(capsys):
    """Ctrl-C is the user saying no. Exit 1 is what says that; the default
    KeyboardInterrupt handling would say it with a traceback and exit 130."""
    def boom():
        raise KeyboardInterrupt

    assert run(["pick"], airports_loader=boom) == 1
    assert capsys.readouterr().err == ""


# -- the state_writer seam --------------------------------------------------


def test_the_real_write_airport_is_wired_by_default():
    """Every test in this file goes through run(), which always overrides
    state_writer -- so nothing else here would notice if main()'s real
    default silently stopped persisting picks for the actual console
    script. Check the wiring directly instead."""
    default = inspect.signature(main).parameters["state_writer"].default
    assert default is write_airport


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


def test_whitespace_in_the_label_cannot_shift_fields():
    """A literal tab or newline in a future dataset regeneration must not
    shift lat/lon into a name fragment -- bin/kcgx reads this with
    IFS=$'\\t' and feeds the lat field straight to `adsb-tui --site-lat`."""
    weird = Airport("KWEI", "WEI", "Weird\tName\nWith\tWhitespace", "Somewhere",
                     "OR", "US", 1.0, 2.0, "small")
    record = format_record(weird)
    assert record.count("\t") == 3
    assert len(record.split("\t")) == 4


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


def test_a_multi_word_query_reaches_the_picker_as_one_string(tmp_path):
    """`kcgx go chicago heights` arrives as separate words. usage() invites
    exactly that, so argparse must not reject the extras -- bin/kcgx would
    report the resulting exit 2 as "airport search failed"."""
    seen = {}

    def picker(airports, initial=""):
        seen["initial"] = initial
        return ORD

    code = run(
        ["pick", "chicago", "heights", "--out", str(tmp_path / "record")],
        picker=picker,
    )
    assert code == 0
    assert seen["initial"] == "chicago heights"


def test_cancelling_the_picker_exits_1_and_writes_nothing(tmp_path):
    out = tmp_path / "record"
    assert run(["pick", "--out", str(out)], picker=lambda a, initial="": None) == 1
    assert not out.exists(), "a cancelled pick must leave no record to act on"


def test_an_unwritable_out_exits_2_not_1(tmp_path, capsys):
    """A write failure must report as an error (2), never as a cancelled
    pick (1) -- bin/kcgx treats exit 1 as 'stay quiet', which would
    swallow a genuine failure -- and never as a bare traceback."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    out = blocker / "record"

    assert run(["pick", "KORD", "--out", str(out)]) == 2

    err = capsys.readouterr().err
    assert str(out) in err
    assert "Traceback" not in err


def test_a_failed_record_write_does_not_remember_the_airport(tmp_path):
    """Exit 2 says nothing happened; the state file must agree."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    remembered = []
    code = run(
        ["pick", "KORD", "--out", str(blocker / "record")],
        state_writer=remembered.append,
    )
    assert code == 2
    assert remembered == [], "persisted an airport it then reported as a failure"


def test_a_successful_pick_is_remembered(tmp_path):
    remembered = []
    run(
        ["pick", "KORD", "--out", str(tmp_path / "r")],
        picker=lambda a, initial="": None,
        state_writer=remembered.append,
    )
    assert remembered == ["KORD"]


def test_a_cancelled_pick_is_not_remembered(tmp_path):
    remembered = []
    run(
        ["pick", "--out", str(tmp_path / "r")],
        picker=lambda a, initial="": None,
        state_writer=remembered.append,
    )
    assert remembered == []
