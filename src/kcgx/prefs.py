"""Every setting the page has, and the one schema that describes them.

How the page looks (palette, glow, display, scanlines), what it shows (the
lamp bar, the teletype) and how the radar draws (range, flight tags, label
boxes). Remembered on the server, beside the airport, so every tab and
every launch agrees. A page changes them with a `prefs` message.

Each setting is one of five kinds, and each kind has a `check(value)` that
returns the value as it is stored and sent, or raises ValueError saying
what it must be. The file is read through `clean`, which drops what fails;
the protocol refuses what fails. Either way nothing a page sends, and
nothing a hand edited file holds, reaches the page unless SCHEMA allows it.

A table (the map's layers) is rows of cells. A page sends only the cells it
changes, and `merge` lays them over what is set a cell at a time, so two
tabs changing two cells both land; the file and every frame hold it whole.
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
    """A whole number from `low` to `high`, `step` apart counting from `low`.
    true is not 1, and 3.0 is not 3."""

    low: int
    high: int
    default: int
    step: int = 1

    def check(self, value: Any) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not self.low <= value <= self.high
            or (value - self.low) % self.step
        ):
            steps = f" in steps of {self.step}" if self.step != 1 else ""
            raise ValueError(f"must be a whole number from {self.low} to {self.high}{steps}")
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


class CellError(ValueError):
    """A table's cell that fails, or a row or column the table does not have.
    `where` names it, as ROW or ROW.column; the message is `where` and then
    what is wrong with it."""

    def __init__(self, where: str, reason: str):
        super().__init__(f"{where} {reason}")
        self.where = where
        self.reason = reason


@dataclass(frozen=True)
class Table:
    """Named rows of cells. Each row has only the columns that mean something
    for it (its defaults' keys), and each cell is checked by its column."""

    columns: dict[str, Choice | Flag | Number]
    rows: dict[str, dict[str, Any]]  # row -> its defaults; its keys are the columns it has

    def check(self, value: Any) -> dict:
        """A partial table: any rows, any of each row's own columns."""
        if not isinstance(value, dict):
            raise ValueError("must be an object of rows")
        out = {}
        for row, cells in value.items():
            if row not in self.rows:
                raise CellError(row, "is not a row")
            if not isinstance(cells, dict):
                raise CellError(row, "must be an object of cells")
            out[row] = {}
            for col, cell in cells.items():
                if col not in self.rows[row]:
                    raise CellError(f"{row}.{col}", f"is not a column of {row}")
                try:
                    out[row][col] = self.columns[col].check(cell)
                except ValueError as reason:
                    raise CellError(f"{row}.{col}", str(reason)) from None
        return out

    @property
    def default(self) -> dict:
        return {row: dict(cells) for row, cells in self.rows.items()}

    def clean(self, value: Any) -> dict:
        """The cells of `value` that pass, as `clean` takes a file: a bad
        cell is dropped, not refused, and a choice in lower case is taken
        as meant."""
        if not isinstance(value, dict):
            return {}
        out = {}
        for row, cells in value.items():
            if row not in self.rows or not isinstance(cells, dict):
                continue
            out[row] = {}
            for col, cell in cells.items():
                if col not in self.rows[row]:
                    continue
                spec = self.columns[col]
                if isinstance(spec, Choice) and isinstance(cell, str):
                    cell = cell.upper()
                try:
                    out[row][col] = spec.check(cell)
                except ValueError:
                    pass
        return out


Kind = Choice | Flag | Number | Subset | Table

PALETTES = ("WOPR", "AMBER", "MATRIX", "MONO")
DISPLAYS = ("OFF", "VECTOR", "CRT")
FONTS = ("CLASSIC", "B612", "SHARETECH", "PLEX", "JETBRAINS", "VT323", "SYSTEM")
TAG_FIELDS = ("CALLSIGN", "TYPE", "SQWK", "ALT", "GS", "TRK", "DIST")
BOX_ITEMS = ("AIRCRAFT", "HOME", "AIRPORTS", "NAVAIDS", "CITIES", "PEAKS", "STATES", "RINGS", "HUD")
TRACK_COLS = (
    "CALLSIGN", "TYPE", "REG", "ALT", "VS", "GS", "TRK", "DIST", "BRG", "SQWK",
    "HEX", "CAT", "AGE", "LAT", "LON",
)
LINES = ("SOLID", "DASH", "DOT")

# The map's layers, each as radar/still.js draws it now. A row has only the
# columns that mean something for it.
MAP = Table(
    columns={
        "show": Flag(True),
        "alpha": Number(0, 100, 100),  # %
        "line": Choice(LINES, "SOLID"),
        "width": Number(5, 80, 10),  # tenths of a pixel
        "label": Number(8, 32, 13),  # px
    },
    rows={
        "COAST": {"show": True, "alpha": 100, "line": "SOLID", "width": 18},
        "LAKE": {"show": True, "alpha": 75, "line": "SOLID", "width": 12},
        "RIVER": {"show": True, "alpha": 50, "line": "SOLID", "width": 10},
        "COUNTRY": {"show": True, "alpha": 90, "line": "DASH", "width": 12},
        "STATE": {"show": True, "alpha": 55, "line": "SOLID", "width": 10},
        "AIRWAY": {"show": True, "alpha": 70, "line": "DASH", "width": 12},
        "CLASS_B": {"show": True, "alpha": 90, "line": "DASH", "width": 14},
        "CLASS_C": {"show": True, "alpha": 80, "line": "DASH", "width": 13},
        "CLASS_D": {"show": True, "alpha": 45, "line": "DOT", "width": 10},
        "RUNWAYS": {"show": True, "alpha": 100, "width": 16},
        "RINGS": {"show": True, "alpha": 35, "line": "SOLID", "width": 10, "label": 12},
        "HOME": {"show": True, "alpha": 100, "width": 18, "label": 30},
        "AIRPORTS": {"show": True, "alpha": 85, "width": 13, "label": 13},
        "NAVAIDS": {"show": True, "alpha": 85, "width": 13, "label": 13},
        "CITIES": {"show": True, "alpha": 85, "width": 13, "label": 13},
        "PEAKS": {"show": True, "alpha": 85, "width": 13, "label": 13},
        "STATE_NAMES": {"show": True, "alpha": 100, "label": 14},
    },
)

# In the order of the plan's tables: General, Traffic, Tracks, Frequencies.
SCHEMA: dict[str, Kind] = {
    # General
    "boot_anim": Flag(True),
    "ui_zoom": Number(50, 200, 100, step=5),  # %
    "font": Choice(FONTS, "CLASSIC"),
    "font_px": Number(10, 20, 13),
    "clock_24h": Flag(True),
    "clock_seconds": Flag(False),
    "clock_zone": Flag(True),
    "palette": Choice(PALETTES, "WOPR"),
    "display": Choice(DISPLAYS, "CRT"),
    "scan_opacity": Number(0, 100, 34),  # %
    "scan_size": Number(2, 8, 3),  # px
    "glow_map": Number(0, 100, 33),  # 0 to 12 px of blur
    "glow_traffic": Number(0, 100, 33),
    "glow_text": Number(0, 100, 33),
    "aa": Choice(("OFF", "ON", "SUPER"), "ON"),  # the render scale: half, the display's, twice
    # The half-life of the moving layer's fade, in ms: 19 is what fading
    # 0.45 a frame does at 60 Hz (0.55 ** (19 / 16.7) is a half).
    "burn_in": Number(0, 100, 19),
    "fps_max": Number(15, 120, 60),  # 120 is the display's own rate
    "poll_secs": Number(15, 120, 15, step=5),  # adsb.lol: no more than one request every 15 s
    "motion": Choice(("GLIDE", "STEP"), "GLIDE"),
    "view_ease": Choice(("OFF", "QUICK", "SMOOTH"), "QUICK"),
    "zoom_speed": Number(25, 400, 100),  # % of the phase F wheel rate
    "lamps": Flag(False),
    "teletype": Flag(False),
    # Traffic
    "range_nm": Number(10, 250, 40, step=10),  # as its slider has, since phase F
    "tag_fields": Subset(TAG_FIELDS, ("CALLSIGN", "ALT")),
    "box_items": Subset(BOX_ITEMS, ()),
    "box_fill": Number(0, 100, 70),  # %
    "box_pad": Number(0, 12, 4),  # px
    "box_border": Number(0, 100, 50),  # %
    "box_width": Number(1, 5, 1),  # px
    "map": MAP,
    "label_min": Number(6, 20, 9),  # px
    "label_max": Number(12, 48, 26),  # px
    "tag_px": Number(10, 28, 16),  # px
    "follow_nm": Number(1, 50, 10),
    "info_box": Flag(True),
    "tail_secs": Number(0, 600, 180, step=15),
    "tail_alpha": Number(0, 100, 95),  # %
    "tail_alpha_min": Number(0, 100, 35),
    "tail_alpha_max": Number(0, 100, 95),
    "tail_gs_low": Number(0, 600, 40),  # kt
    "tail_gs_high": Number(0, 600, 250),  # kt
    "ground_mode": Choice(("SHOW", "FADE", "HIDE"), "FADE"),
    "ground_gs": Number(0, 50, 5),  # kt
    "ground_alt": Number(0, 5000, 0, step=100),  # ft above sea level; 0 is GND only
    "ground_min": Number(0, 30, 2),  # minutes
    "ground_alpha": Number(0, 100, 25),  # %
    # Tracks
    "track_cols": Subset(TRACK_COLS, ("CALLSIGN", "TYPE", "ALT", "GS", "TRK", "DIST", "SQWK")),
    "track_sort": Choice(TRACK_COLS, "DIST"),
    "track_desc": Flag(False),
    "sort_floor": Number(0, 100, 40),  # %
    "tracks_open": Flag(True),
    "tracks_pct": Number(10, 80, 24),  # % of the page
    # Frequencies
    "short_names": Flag(True),
}

# The phase F glow, one choice, as the three numbers it became.
OLD_GLOW = {"OFF": 0, "LOW": 33, "FULL": 75}
GLOW_KEYS = ("glow_map", "glow_traffic", "glow_text")

# Subset defaults are lists here, as they are in the file and on the wire;
# a table's is every row, whole.
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
        if isinstance(spec, Table):
            if isinstance(value, dict):
                out[key] = spec.clean(value)
            continue
        if isinstance(spec, Choice) and isinstance(value, str):
            value = value.upper()
        try:
            out[key] = spec.check(value)
        except ValueError:
            pass
    return out


def merge(prefs: dict, changes: dict) -> dict:
    """`prefs` with `changes` over them, as a new dict: a table a cell at a
    time, so a page can send one cell and leave the rest; anything else
    whole. Neither argument is changed, and no row of the result is shared
    with either."""
    out = dict(prefs)
    for key, value in changes.items():
        if isinstance(SCHEMA.get(key), Table):
            table = {row: dict(cells) for row, cells in prefs.get(key, {}).items()}
            for row, cells in value.items():
                table.setdefault(row, {}).update(cells)
            out[key] = table
        else:
            out[key] = value
    return out


def migrate(stored: dict) -> dict:
    """A file from before phase G: its `glow` (OFF, LOW or FULL) becomes the
    three glow numbers, each unless the file has that one already, and one
    its check accepts: a bad one would be dropped and leave the default."""
    glow = stored.get("glow")
    if not isinstance(glow, str) or glow.upper() not in OLD_GLOW:
        return stored
    level = OLD_GLOW[glow.upper()]
    out = dict(stored)
    for key in GLOW_KEYS:
        try:
            SCHEMA[key].check(stored[key])
        except (KeyError, ValueError):
            out[key] = level
    return out


def defaults() -> dict:
    """DEFAULTS for a caller to keep and change: a dict, lists and table
    rows of its own, so nothing done to it reaches the module's."""
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
    return merge(defaults(), clean(migrate(stored)))


def write_prefs(prefs: dict, *, path: Path | None = None) -> None:
    """Remember `prefs`. Failing to is a lost convenience, not an error."""
    path = prefs_path() if path is None else path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merge(DEFAULTS, clean(prefs)), indent=2) + "\n")
    except OSError:
        pass
