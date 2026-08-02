from pathlib import Path
from squelch.config import Config, load_config


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.icao == "KPDX"
    assert cfg.feed == "kpdx_twr"
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
