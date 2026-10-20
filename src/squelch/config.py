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
    ambient_gain_db: float = -8.0
    # Applied to the summed stereo output, before the clip. 1.0 is unity;
    # the overlay shows it as a percentage. The only gain in the signal
    # path: the per-feed gate and compressor were removed on 2026-08-02,
    # along with the five `compressor_*` keys and the two `gate_*` keys that
    # configured them. Unknown keys are ignored, so an old config file that
    # still sets them loads without complaint.
    master_volume: float = 1.0
    # Off by default. [A] still marks a feed, and the mixer still ignores
    # it -- no pan, no reverb.
    ambient_enabled: bool = False
    # How much audio each feed may hold before the ring buffer drops to
    # catch up -- effectively how far behind live you are willing to sit.
    # LiveATC delivers in ~1.2 s bursts, so a buffer under that discards
    # most of the feed and stutters; see the note beside BUFFER_SECONDS in
    # mixer.py for the measurements. Raise it for a lossier connection at
    # the cost of lag, lower it to stay closer to live at the cost of
    # dropouts.
    buffer_seconds: float = 4.0
    # How many streams to hold open at once. LiveATC cuts an address off
    # past seven; feeds beyond this are parked instead of left knocking.
    # See slots.py for the measurement.
    max_streams: int = 7
    # The web cockpit's radar (kcgx.radar). adsb.lol asks for no more than
    # one request every 15 s per address; a refused poll backs off from
    # there. The range is the circle asked for, in nautical miles, and an
    # aircraft not heard from for radar_stale_secs drops off the screen.
    radar_refresh_secs: int = 15
    radar_range_nm: int = 40
    radar_stale_secs: int = 60


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
