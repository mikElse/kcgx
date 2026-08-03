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


def test_the_activity_threshold_defaults_to_minus_forty():
    assert Config().activity_threshold_dbfs == -40.0


def test_the_activity_threshold_can_be_configured(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text("activity_threshold_dbfs = -35.5\n")
    assert load_config(path).activity_threshold_dbfs == -35.5


def test_a_non_numeric_activity_threshold_is_rejected(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text('activity_threshold_dbfs = "loud"\n')
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "activity_threshold_dbfs" in str(exc.value)


def test_the_audio_defaults_match_the_dsp_module():
    from squelch import dsp

    config = Config()
    assert config.compressor_threshold_dbfs == dsp.THRESHOLD_DBFS
    assert config.compressor_ratio == dsp.RATIO
    assert config.compressor_makeup_db == dsp.MAKEUP_DB
    assert config.compressor_range_db == dsp.RANGE_LIMIT_DB


def test_the_audio_parameters_can_be_configured(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text(
        "compressor_threshold_dbfs = -18.0\n"
        "compressor_ratio = 2.0\n"
        "ambient_gain_db = -12.0\n"
    )
    config = load_config(path)
    assert config.compressor_threshold_dbfs == -18.0
    assert config.compressor_ratio == 2.0
    assert config.ambient_gain_db == -12.0


def test_a_non_numeric_ratio_is_rejected(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text('compressor_ratio = "hard"\n')
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "compressor_ratio" in str(exc.value)


def test_the_audio_shaping_ships_disabled():
    """The signal path is the decoded feed plus master volume, nothing else.

    Pinned as an explicit default rather than left to follow from the
    overlay's rendering: every status in the config overlay is derived from
    these flags, so flipping them flips the whole table consistently and no
    test over there would notice.
    """
    config = Config()
    assert config.compressor_enabled is False
    assert config.ambient_enabled is False


def test_the_shaping_can_be_switched_back_on(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text("compressor_enabled = true\nambient_enabled = true\n")
    config = load_config(path)
    assert config.compressor_enabled is True
    assert config.ambient_enabled is True


def test_a_non_boolean_switch_is_rejected(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text('compressor_enabled = "yes"\n')
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "compressor_enabled" in str(exc.value)
