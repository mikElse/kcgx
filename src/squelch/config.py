"""Configuration loading for squelch."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config" / "squelch" / "squelch.toml"
DEFAULT_MODEL = "jacktol/whisper-medium.en-fine-tuned-for-ATC-faster-whisper"


VAD_AGGRESSIVENESS_RANGE = (0, 3)


class ConfigError(ValueError):
    """A config file was found but could not be used as written."""


@dataclass(frozen=True)
class Config:
    icao: str = "KPDX"
    feed: str = "kpdx3_twr"
    model: str = DEFAULT_MODEL
    compute_type: str = "int8"
    vad_aggressiveness: int = 2


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, falling back to defaults.

    Unknown keys are ignored so a newer config file does not crash an
    older binary. Known keys are type- and range-checked here, at startup,
    where the message can name the file and the key: an unchecked value
    surfaces much later and much worse -- `vad_aggressiveness = 7` reaches
    `webrtcvad.Vad(7)` inside a daemon thread as
    `ValueError: 7 is an invalid mode, must be 0-3`, which kills the
    pipeline silently and leaves the pane reading "● LIVE" forever.
    """
    path = DEFAULT_PATH if path is None else path
    if not path.exists():
        return Config()
    data = tomllib.loads(path.read_text())
    values = {}
    for field in fields(Config):
        if field.name not in data:
            continue
        values[field.name] = _checked(path, field.name, data[field.name],
                                      type(field.default))
    return Config(**values)


def _checked(path: Path, key: str, value: object, expected: type) -> object:
    # bool is a subclass of int, so `vad_aggressiveness = true` would sail
    # through a bare isinstance check and then be used as 1.
    mismatched = not isinstance(value, expected) or (
        expected is not bool and isinstance(value, bool)
    )
    if mismatched:
        raise ConfigError(
            f"{path}: '{key}' must be {expected.__name__}, got "
            f"{type(value).__name__} ({value!r})"
        )
    if key == "vad_aggressiveness":
        low, high = VAD_AGGRESSIVENESS_RANGE
        if not low <= value <= high:
            raise ConfigError(
                f"{path}: 'vad_aggressiveness' must be between {low} and "
                f"{high} (0 = least aggressive filtering, {high} = most), "
                f"got {value!r}"
            )
    return value
