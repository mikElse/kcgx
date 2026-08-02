"""Tests for the airport kcgx remembers between launches."""

from __future__ import annotations

from kcgx.state import current_icao, read_airport, write_airport
from squelch.config import Config


def test_write_then_read_round_trips(tmp_path):
    path = tmp_path / "airport"
    write_airport("KORD", path=path)
    assert read_airport(path=path) == "KORD"


def test_the_icao_is_stored_uppercase_and_trimmed(tmp_path):
    path = tmp_path / "airport"
    write_airport("  kord \n", path=path)
    assert read_airport(path=path) == "KORD"


def test_reading_a_missing_state_file_is_not_an_error(tmp_path):
    assert read_airport(path=tmp_path / "nope") is None


def test_reading_an_empty_state_file_is_not_an_error(tmp_path):
    path = tmp_path / "airport"
    path.write_text("\n")
    assert read_airport(path=path) is None


def test_writing_creates_the_parent_directory(tmp_path):
    path = tmp_path / "deep" / "deeper" / "airport"
    write_airport("KSEA", path=path)
    assert read_airport(path=path) == "KSEA"


def test_an_unwritable_state_file_does_not_raise(tmp_path):
    """Forgetting where you were is not a reason to refuse to switch."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    write_airport("KSEA", path=blocker / "airport")  # must not raise


def test_the_state_file_wins_when_present(tmp_path):
    path = tmp_path / "airport"
    write_airport("KORD", path=path)
    assert current_icao(path=path, config_loader=lambda: Config(icao="KPDX")) == "KORD"


def test_the_squelch_config_is_the_first_run_default(tmp_path):
    assert current_icao(
        path=tmp_path / "nope", config_loader=lambda: Config(icao="KSEA")
    ) == "KSEA"


def test_a_broken_config_still_yields_an_airport(tmp_path):
    """An unusable squelch.toml must not stop the cockpit from opening."""
    def boom():
        raise ValueError("bad toml")

    assert current_icao(path=tmp_path / "nope", config_loader=boom) == "KPDX"
