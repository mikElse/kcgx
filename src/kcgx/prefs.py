"""Every setting the page has, and the one schema that describes them.

How the page looks (palette, glow, display, scanlines), what it shows (the
lamp bar, the teletype) and how the radar draws (range, flight tags, label
boxes). Remembered on the server, beside the airport, so every tab and
every launch agrees. A page changes them with a `prefs` message.

Each setting is one of four kinds, and each kind has a `check(value)` that
returns the value as it is stored and sent, or raises ValueError saying
what it must be. The file is read through `clean`, which drops what fails;
the protocol refuses what fails. Either way nothing a page sends, and
nothing a hand edited file holds, reaches the page unless SCHEMA allows it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kcgx.state import default_path


@dataclass(frozen=True)
class Choice:
    """One of a few names."""

    names: tuple[str, ...]
    default: str

    def check(self, value: Any) -> str:
        if isinstance(value, str) and value in self.names:
            return value
        raise ValueError(f"must be one of {', '.join(self.names)}")


@dataclass(frozen=True)
class Flag:
    """On or off. A JSON boolean: 1 is not true."""

    default: bool

    def check(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        raise ValueError("must be true or false")


@dataclass(frozen=True)
class Number:
    """A whole number from `low` to `high`. true is not 1, and 3.0 is not 3."""

    low: int
    high: int
    default: int

    def check(self, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not self.low <= value <= self.high:
            raise ValueError(f"must be a whole number from {self.low} to {self.high}")
        return value


@dataclass(frozen=True)
class Subset:
    """Any of a few names, none included. Kept as a list in schema order
    without repeats, so the same choice is always the same value."""

    names: tuple[str, ...]
    default: tuple[str, ...]

    def check(self, value: Any) -> list[str]:
        if not isinstance(value, list) or any(v not in self.names for v in value):
            raise ValueError(f"must be a list drawn from {', '.join(self.names)}")
        return [n for n in self.names if n in value]


PALETTES = ("WOPR", "AMBER", "MATRIX", "MONO")
GLOWS = ("OFF", "LOW", "FULL")
DISPLAYS = ("OFF", "VECTOR", "CRT")
TAG_FIELDS = ("CALLSIGN", "TYPE", "SQWK", "ALT", "GS", "TRK", "DIST")
BOX_ITEMS = ("AIRCRAFT", "HOME", "AIRPORTS", "NAVAIDS", "CITIES", "PEAKS", "STATES", "RINGS", "HUD")

SCHEMA: dict[str, Choice | Flag | Number | Subset] = {
    "palette": Choice(PALETTES, "WOPR"),
    "glow": Choice(GLOWS, "LOW"),
    "display": Choice(DISPLAYS, "CRT"),
    "scan_opacity": Number(0, 100, 34),  # %
    "scan_size": Number(2, 8, 3),  # px
    "lamps": Flag(False),
    "teletype": Flag(False),
    "range_nm": Number(10, 250, 40),
    "tag_fields": Subset(TAG_FIELDS, ("CALLSIGN", "ALT")),
    "box_items": Subset(BOX_ITEMS, ()),
    "box_fill": Number(0, 100, 70),  # %
    "box_pad": Number(0, 12, 4),  # px
    "box_border": Number(0, 100, 50),  # %
    "box_width": Number(1, 5, 1),  # px
}

# Subset defaults are lists here, as they are in the file and on the wire.
DEFAULTS: dict[str, Any] = {
    key: list(spec.default) if isinstance(spec, Subset) else spec.default
    for key, spec in SCHEMA.items()
}

# The settings that are one name of a few, and the names.
CHOICES = {key: spec.names for key, spec in SCHEMA.items() if isinstance(spec, Choice)}


def prefs_path() -> Path:
    """Beside the remembered airport, so KCGX_STATE_PATH relocates both."""
    return default_path().parent / "prefs.json"


def clean(values: dict) -> dict:
    """Only the known keys, each only if it passes its check. Lenient where
    the protocol is strict: a bad value is dropped, not refused, and a
    choice written in lower case is taken as meant."""
    out = {}
    for key, spec in SCHEMA.items():
        if key not in values:
            continue
        value = values[key]
        if isinstance(spec, Choice) and isinstance(value, str):
            value = value.upper()
        try:
            out[key] = spec.check(value)
        except ValueError:
            pass
    return out


def defaults() -> dict:
    """DEFAULTS for a caller to keep and change: a dict and lists of its
    own, so nothing done to it reaches the module's."""
    return clean(DEFAULTS)


def read_prefs(*, path: Path | None = None) -> dict:
    """The remembered prefs over the defaults. Anything unreadable, or any
    value its setting does not allow, quietly falls back to its default."""
    path = prefs_path() if path is None else path
    try:
        stored = json.loads(path.read_text())
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return {**defaults(), **clean(stored)}


def write_prefs(prefs: dict, *, path: Path | None = None) -> None:
    """Remember `prefs`. Failing to is a lost convenience, not an error."""
    path = prefs_path() if path is None else path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**DEFAULTS, **clean(prefs)}, indent=2) + "\n")
    except OSError:
        pass
