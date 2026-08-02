"""Tests for the airport kcgx remembers between launches."""

from __future__ import annotations

from kcgx.state import (
    STATE_PATH,
    current_icao,
    default_path,
    read_airport,
    write_airport,
)
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


# -- the KCGX_STATE_PATH seam ----------------------------------------------


def test_kcgx_state_path_relocates_the_state_file(tmp_path, monkeypatch):
    """The seam that lets a test drive the real `pick` without writing to
    the developer's own ~/.local/state/kcgx."""
    path = tmp_path / "elsewhere" / "airport"
    monkeypatch.setenv("KCGX_STATE_PATH", str(path))

    write_airport("KORD")
    assert path.read_text().strip() == "KORD"
    assert read_airport() == "KORD"


def test_the_default_is_the_home_state_file_when_the_seam_is_unset(monkeypatch):
    monkeypatch.delenv("KCGX_STATE_PATH", raising=False)
    assert default_path() == STATE_PATH


def test_an_explicit_path_beats_the_environment(tmp_path, monkeypatch):
    """`path=` is the more specific override; the env must not win over it."""
    monkeypatch.setenv("KCGX_STATE_PATH", str(tmp_path / "from-the-env"))
    explicit = tmp_path / "explicit"

    write_airport("KSEA", path=explicit)
    assert explicit.read_text().strip() == "KSEA"
    assert not (tmp_path / "from-the-env").exists()
    assert read_airport(path=explicit) == "KSEA"


def test_the_seam_is_read_at_call_time_not_import_time(tmp_path, monkeypatch):
    """A subprocess inheriting the variable is enough; nothing has to be
    imported after it is set."""
    first, second = tmp_path / "first", tmp_path / "second"
    monkeypatch.setenv("KCGX_STATE_PATH", str(first))
    write_airport("KORD")
    monkeypatch.setenv("KCGX_STATE_PATH", str(second))
    write_airport("KSEA")

    assert first.read_text().strip() == "KORD"
    assert second.read_text().strip() == "KSEA"


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
