"""Configuration loading for squelch."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config" / "squelch" / "squelch.toml"


class ConfigError(ValueError):
    """A config file was found but could not be used as written."""


@dataclass(frozen=True)
class Config:
    icao: str = "KPDX"
    feed: str = "kpdx3_twr"
    # Above this, a frame counts as busy for the five-minute activity
    # ranking. ATC feeds sit on a noise floor around -50 dBFS with speech
    # peaking -20 to -10, so this separates the two with margin on both
    # sides. Must be written as a decimal: `_checked` derives the expected
    # type from the default, so a bare `-40` is rejected as an int.
    activity_threshold_dbfs: float = -40.0
    # Audio shaping. The range limit and the gate are not decorative: at
    # 4:1 with no limit, a -50 dBFS noise floor gains ~28 dB and hiss
    # becomes the loudest thing in the pane.
    compressor_threshold_dbfs: float = -12.0
    compressor_ratio: float = 4.0
    compressor_makeup_db: float = 6.0
    compressor_range_db: float = 12.0
    ambient_gain_db: float = -8.0
    # Applied to the summed stereo output, before the clip. 1.0 is unity;
    # the overlay shows it as a percentage.
    master_volume: float = 1.0
    # The gate threshold, in dBFS. Measured against live KPDX audio -- see
    # the note beside GATE_OPEN_DBFS in dsp.py before moving it.
    gate_dbfs: float = -55.0


def load_config(path: Path | None = None) -> Config:
    """Load config from TOML, falling back to defaults.

    Unknown keys are ignored so a newer config file does not crash an
    older binary. Known keys are type-checked here, at startup, where the
    message can name the file and the key -- a bad value that surfaces
    later, inside the daemon pipeline thread, dies in silence and leaves
    the pane claiming "● LIVE" forever.
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
    # bool is a subclass of int, so an integer key given as `true` would
    # sail through a bare isinstance check and then be used as 1.
    mismatched = not isinstance(value, expected) or (
        expected is not bool and isinstance(value, bool)
    )
    if mismatched:
        raise ConfigError(
            f"{path}: '{key}' must be {expected.__name__}, got "
            f"{type(value).__name__} ({value!r})"
        )
    return value
