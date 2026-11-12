from dataclasses import fields

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


def test_the_audio_parameters_can_be_configured(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text("ambient_gain_db = -12.0\nmaster_volume = 0.5\n")
    config = load_config(path)
    assert config.ambient_gain_db == -12.0
    assert config.master_volume == 0.5


def test_a_non_numeric_gain_is_rejected(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text('ambient_gain_db = "loud"\n')
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "ambient_gain_db" in str(exc.value)


def test_the_shaping_keys_are_gone_rather_than_ignored():
    """The gate and the compressor were removed on 2026-08-02.

    Pinned as an absence, not left to be noticed: a key that still parses
    but drives nothing is exactly the state this change was made to leave
    behind, and nothing else in the suite fails if one comes back.
    """
    names = {field.name for field in fields(Config)}
    assert not {name for name in names if name.startswith("compressor_")}
    assert not {name for name in names if name.startswith("gate_")}


def test_a_stale_config_file_still_loads(tmp_path):
    """Unknown keys are ignored, so a config written for the old build
    starts rather than dying on keys that no longer exist."""
    path = tmp_path / "squelch.toml"
    path.write_text(
        "icao = \"KSEA\"\n"
        "compressor_enabled = true\n"
        "gate_dbfs = -55.0\n"
        "compressor_ratio = 4.0\n"
    )
    config = load_config(path)
    assert config.icao == "KSEA"


def test_the_ambient_bus_ships_disabled():
    """The signal path is the decoded feed plus master volume, nothing else.

    Pinned as an explicit default rather than left to follow from the
    overlay's rendering: every status in the config overlay is derived from
    this flag, so flipping it flips the whole table consistently and no
    test over there would notice.
    """
    assert Config().ambient_enabled is False


def test_the_ambient_bus_can_be_switched_back_on(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text("ambient_enabled = true\n")
    assert load_config(path).ambient_enabled is True


def test_a_non_boolean_switch_is_rejected(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text('ambient_enabled = "yes"\n')
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "ambient_enabled" in str(exc.value)


def test_the_buffer_is_large_enough_for_a_burst():
    """LiveATC delivers ~1.2 s at a time. A buffer under that discards most
    of the feed -- see the note beside BUFFER_SECONDS in mixer.py."""
    from squelch.mixer import BUFFER_SECONDS

    assert Config().buffer_seconds == BUFFER_SECONDS
    assert Config().buffer_seconds >= 2.4


def test_the_buffer_can_be_tuned(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text("buffer_seconds = 8.0\n")
    assert load_config(path).buffer_seconds == 8.0


def test_the_radar_keys_default_to_adsb_lols_pace():
    cfg = Config()
    assert (cfg.radar_refresh_secs, cfg.radar_stale_secs) == (15, 60)


def test_the_radar_keys_can_be_configured(tmp_path):
    path = tmp_path / "squelch.toml"
    path.write_text("radar_refresh_secs = 30\nradar_stale_secs = 90\n")
    cfg = load_config(path)
    assert (cfg.radar_refresh_secs, cfg.radar_stale_secs) == (30, 90)


def test_the_radar_range_is_gone_rather_than_ignored():
    """The range became a setting of the page on 2026-11-12 (kcgx.prefs,
    `range_nm`), changed live from CONFIG. Pinned as an absence: a key that
    still parses but drives nothing is worse than no key."""
    assert "radar_range_nm" not in {field.name for field in fields(Config)}
    assert not hasattr(Config(), "radar_range_nm")


@pytest.mark.parametrize("value", ["25", "40.5", '"far"'])
def test_a_file_that_still_sets_the_radar_range_loads(tmp_path, value):
    """Unknown keys are ignored, whatever they hold: a squelch.toml written
    before the range moved starts as it always did."""
    path = tmp_path / "squelch.toml"
    path.write_text(f"radar_refresh_secs = 30\nradar_range_nm = {value}\nradar_stale_secs = 90\n")
    assert load_config(path) == Config(radar_refresh_secs=30, radar_stale_secs=90)
