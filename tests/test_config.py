import pytest

from squelch.config import Config, ConfigError, load_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.icao == "KPDX"
    assert cfg.feed == "kpdx3_twr"
    assert cfg.vad_aggressiveness == 2


def test_file_overrides_defaults(tmp_path):
    p = tmp_path / "squelch.toml"
    p.write_text('icao = "KSEA"\nfeed = "ksea_twr"\nvad_aggressiveness = 3\n')
    cfg = load_config(p)
    assert cfg.icao == "KSEA"
    assert cfg.feed == "ksea_twr"
    assert cfg.vad_aggressiveness == 3
    assert cfg.compute_type == "int8"


def test_unknown_keys_are_ignored(tmp_path):
    p = tmp_path / "squelch.toml"
    p.write_text('icao = "KPDX"\nnonsense = 1\n')
    assert load_config(p) == Config(icao="KPDX")


def test_out_of_range_vad_aggressiveness_is_rejected_with_a_clear_message(tmp_path):
    """Range-check at load time, not deep inside a daemon thread.

    Regression test: `vad_aggressiveness = 7` used to sail through
    load_config untouched and reach `webrtcvad.Vad(7)` on the pipeline
    thread, where `ValueError: 7 is an invalid mode, must be 0-3` killed
    the thread in silence -- the pane kept reading "● LIVE" with an empty
    transcript and no indication anything had gone wrong.
    """
    p = tmp_path / "squelch.toml"
    p.write_text("vad_aggressiveness = 7\n")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    message = str(excinfo.value)
    assert "vad_aggressiveness" in message
    assert "0" in message and "3" in message, "the message must name the range"
    assert str(p) in message, "the message must name the file to edit"


def test_negative_vad_aggressiveness_is_rejected(tmp_path):
    p = tmp_path / "squelch.toml"
    p.write_text("vad_aggressiveness = -1\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_boundary_vad_aggressiveness_values_are_accepted(tmp_path):
    for value in (0, 3):
        p = tmp_path / f"squelch-{value}.toml"
        p.write_text(f"vad_aggressiveness = {value}\n")
        assert load_config(p).vad_aggressiveness == value


def test_wrong_type_is_rejected(tmp_path):
    p = tmp_path / "squelch.toml"
    p.write_text('vad_aggressiveness = "loud"\n')
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    assert "int" in str(excinfo.value)

    p2 = tmp_path / "squelch2.toml"
    p2.write_text("feed = 3\n")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p2)
    assert "str" in str(excinfo.value)


def test_bool_is_not_accepted_as_an_int(tmp_path):
    """`true` is an int in Python, but it is not a VAD mode."""
    p = tmp_path / "squelch.toml"
    p.write_text("vad_aggressiveness = true\n")
    with pytest.raises(ConfigError):
        load_config(p)
