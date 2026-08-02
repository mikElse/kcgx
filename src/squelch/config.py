"""Configuration loading for squelch."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config" / "squelch" / "squelch.toml"
DEFAULT_MODEL = "jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper"


@dataclass(frozen=True)
class Config:
    icao: str = "KPDX"
    feed: str = "kpdx_twr"
    model: str = DEFAULT_MODEL
    compute_type: str = "int8"
    vad_aggressiveness: int = 2


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, falling back to defaults.

    Unknown keys are ignored so a newer config file does not crash an
    older binary.
    """
    path = DEFAULT_PATH if path is None else path
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    known = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in data.items() if k in known})
