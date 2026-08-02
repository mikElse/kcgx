import pytest

from squelch.config import Config, ConfigError, load_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.icao == "KPDX"
    assert cfg.feed == "kpdx3_twr"


def test_file_overrides_defaults(tmp_path):
    p = tmp_path / "squelch.toml"
    p.write_text('icao = "KSEA"\nfeed = "ksea_twr"\n')
    cfg = load_config(p)
    assert cfg.icao == "KSEA"
    assert cfg.feed == "ksea_twr"


def test_unknown_keys_are_ignored(tmp_path):
    """A newer config file must not crash an older binary."""
    p = tmp_path / "squelch.toml"
    p.write_text('icao = "KPDX"\nnonsense = 1\n')
    assert load_config(p) == Config(icao="KPDX")


def test_transcription_keys_are_ignored_rather_than_rejected(tmp_path):
    """Config files written before transcription was removed must still load.

    `model`, `compute_type` and `vad_aggressiveness` were real keys once.
    They are unknown now, and unknown keys are ignored — so an existing
    squelch.toml keeps working instead of failing at startup.
    """
    p = tmp_path / "squelch.toml"
    p.write_text(
        'icao = "KSEA"\n'
        'model = "jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper"\n'
        'compute_type = "int8"\n'
        "vad_aggressiveness = 3\n"
    )
    assert load_config(p) == Config(icao="KSEA")


def test_wrong_type_is_rejected_naming_the_file_and_key(tmp_path):
    """Checked at load time, where the message can name the file to edit.

    A bad value that surfaces later, inside the daemon pipeline thread,
    dies in silence and leaves the pane claiming "● LIVE" forever.
    """
    p = tmp_path / "squelch.toml"
    p.write_text("feed = 3\n")
    with pytest.raises(ConfigError) as excinfo:
        load_config(p)
    message = str(excinfo.value)
    assert "str" in message
    assert "feed" in message
    assert str(p) in message, "the message must name the file to edit"


def test_bool_is_rejected_for_a_string_key(tmp_path):
    p = tmp_path / "squelch.toml"
    p.write_text("icao = true\n")
    with pytest.raises(ConfigError):
        load_config(p)
