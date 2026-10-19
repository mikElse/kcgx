"""How the page looks: palette, glow and display effects.

Remembered on the server, beside the airport, so every tab and every launch
agrees. A page changes them with a `prefs` message; the server checks every
value against the names below, so nothing a page sends can end up in the
file unless it is one of them.
"""

from __future__ import annotations

import json
from pathlib import Path

from kcgx.state import default_path

PALETTES = ("WOPR", "AMBER", "MATRIX", "MONO")
GLOWS = ("OFF", "LOW", "FULL")
DISPLAYS = ("OFF", "VECTOR", "CRT")

CHOICES = {"palette": PALETTES, "glow": GLOWS, "display": DISPLAYS}

DEFAULTS = {"palette": "WOPR", "glow": "LOW", "display": "CRT"}


def prefs_path() -> Path:
    """Beside the remembered airport, so KCGX_STATE_PATH relocates both."""
    return default_path().parent / "prefs.json"


def clean(values: dict) -> dict:
    """Only the known keys, each only if it is one of its allowed names."""
    out = {}
    for key, allowed in CHOICES.items():
        value = values.get(key)
        if isinstance(value, str) and value.upper() in allowed:
            out[key] = value.upper()
    return out


def read_prefs(*, path: Path | None = None) -> dict:
    """The remembered prefs over the defaults. Anything unreadable, or any
    value that is not a known name, quietly falls back to its default."""
    path = prefs_path() if path is None else path
    try:
        stored = json.loads(path.read_text())
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return {**DEFAULTS, **clean(stored)}


def write_prefs(prefs: dict, *, path: Path | None = None) -> None:
    """Remember `prefs`. Failing to is a lost convenience, not an error."""
    path = prefs_path() if path is None else path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**DEFAULTS, **clean(prefs)}, indent=2) + "\n")
    except OSError:
        pass
