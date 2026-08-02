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
