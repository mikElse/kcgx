"""Tests for the airport kcgx remembers between launches."""

from __future__ import annotations

import kcgx.state
from kcgx.state import current_icao, default_path, read_airport, write_airport
from squelch.config import Config


def test_write_then_read_round_trips(tmp_path):
    path = tmp_path / "airport"
    write_airport("KORD", path=path)
    assert read_airport(path=path) == "KORD"


def test_the_icao_is_stored_uppercase_and_trimmed(tmp_path):
    """Read the raw file, not read_airport(): read_airport strips and
    upper-cases too, so a round-trip is satisfied whether or not the write
    side normalises anything -- removing write_airport's `.strip().upper()`
    left the whole suite green. What is on disk matters on its own. It is a
    file a human reads and hand-edits (that is one of the ways an ICAO the
    dataset no longer has gets in there), and `cat` should show KORD."""
    path = tmp_path / "airport"
    write_airport("  kord \n", path=path)
    assert path.read_text() == "KORD\n"
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


def test_the_default_is_the_state_path_constant_when_the_seam_is_unset(monkeypatch):
    """Read through the module, not a from-import: conftest redirects
    kcgx.state.STATE_PATH, and a name bound at import time would still point
    at the real ~/.local/state/kcgx and make this assert the wrong thing."""
    monkeypatch.delenv("KCGX_STATE_PATH", raising=False)
    assert default_path() == kcgx.state.STATE_PATH


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


# -- an ICAO the dataset no longer has --------------------------------------


def test_an_unknown_remembered_icao_falls_back_to_the_config(tmp_path):
    """The spec: "An ICAO in the state file that is no longer in the dataset
    falls back to the next source and warns, rather than failing to launch."

    Reachable whenever OurAirports reclassifies a field out of the committed
    subset on regeneration, or from a hand-edited state file. Without the
    fallback, `resolve` exits 2 and the cockpit launches with no coordinates
    and no ICAO -- silently degraded on every launch until the user happens
    to run `kcgx go`.
    """
    path = tmp_path / "airport"
    write_airport("ZZZZ", path=path)

    assert current_icao(
        path=path,
        config_loader=lambda: Config(icao="KSEA"),
        known=lambda icao: icao in {"KSEA", "KPDX"},
    ) == "KSEA"


def test_falling_back_says_which_icao_it_dropped(tmp_path):
    """Silent degradation is the failure mode this replaces; a fallback the
    user cannot see is the same bug with a different airport."""
    path = tmp_path / "airport"
    write_airport("ZZZZ", path=path)
    warnings = []

    current_icao(
        path=path,
        config_loader=lambda: Config(icao="KSEA"),
        known=lambda icao: icao != "ZZZZ",
        warn=warnings.append,
    )

    assert len(warnings) == 1
    assert "ZZZZ" in warnings[0]


def test_an_unknown_config_icao_falls_back_to_the_default(tmp_path):
    """The chain is state -> squelch.toml -> KPDX, and every link is checked
    -- a hand-edited squelch.toml is no more trustworthy than a hand-edited
    state file."""
    assert current_icao(
        path=tmp_path / "nope",
        config_loader=lambda: Config(icao="ZZZZ"),
        known=lambda icao: icao == "KPDX",
    ) == "KPDX"


def test_a_known_icao_is_not_warned_about(tmp_path):
    path = tmp_path / "airport"
    write_airport("KORD", path=path)
    warnings = []

    assert current_icao(
        path=path,
        config_loader=lambda: Config(icao="KSEA"),
        known=lambda icao: True,
        warn=warnings.append,
    ) == "KORD"
    assert warnings == []


def test_the_last_resort_is_returned_even_if_it_is_unknown(tmp_path):
    """If nothing validates, hand back KPDX rather than an empty string or a
    None: `resolve` then reports "KPDX is not in the airport dataset", which
    names the real problem. Inventing a silent success would not."""
    assert current_icao(
        path=tmp_path / "nope",
        config_loader=lambda: Config(icao="ZZZZ"),
        known=lambda icao: False,
    ) == "KPDX"


def test_the_config_is_not_read_when_the_state_file_answers(tmp_path):
    """The sources are evaluated lazily. A squelch.toml that cannot be
    parsed should cost nothing on a launch that never needed it."""
    path = tmp_path / "airport"
    write_airport("KORD", path=path)
    reads = []

    def config_loader():
        reads.append(1)
        return Config(icao="KSEA")

    assert current_icao(path=path, config_loader=config_loader,
                        known=lambda icao: True) == "KORD"
    assert reads == [], "read squelch.toml for an answer it already had"
