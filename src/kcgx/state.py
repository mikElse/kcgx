"""The airport the cockpit reopens on.

One line, one ICAO. Coordinates are deliberately *not* stored: they are
re-resolved from the dataset at every launch, so a dataset update can
never leave the cockpit pointing at stale coordinates.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from squelch.config import Config, load_config

STATE_PATH = Path.home() / ".local" / "state" / "kcgx" / "airport"
FALLBACK_ICAO = "KPDX"


def read_airport(*, path: Path | None = None) -> str | None:
    path = STATE_PATH if path is None else path
    try:
        value = path.read_text().strip().upper()
    except OSError:
        return None
    return value or None


def write_airport(icao: str, *, path: Path | None = None) -> None:
    """Remember `icao`. Failing to is a lost convenience, not an error."""
    path = STATE_PATH if path is None else path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{icao.strip().upper()}\n")
    except OSError:
        pass


def current_icao(
    *,
    path: Path | None = None,
    config_loader: Callable[[], Config] = load_config,
) -> str:
    """Where the cockpit should point, most specific source first."""
    remembered = read_airport(path=path)
    if remembered:
        return remembered
    try:
        return config_loader().icao
    except Exception:
        # A malformed squelch.toml is squelch's problem to report; it is
        # not a reason for the launcher to refuse to pick an airport.
        return FALLBACK_ICAO
