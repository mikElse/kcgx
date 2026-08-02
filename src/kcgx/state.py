"""The airport the cockpit reopens on.

One line, one ICAO. Coordinates are deliberately *not* stored: they are
re-resolved from the dataset at every launch, so a dataset update can
never leave the cockpit pointing at stale coordinates.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

from squelch.config import Config, load_config

STATE_PATH = Path.home() / ".local" / "state" / "kcgx" / "airport"
FALLBACK_ICAO = "KPDX"


def default_path() -> Path:
    """Where the ICAO is remembered, unless a caller says otherwise.

    KCGX_STATE_PATH relocates it. That seam exists so a test can drive the
    *real* `kcgx-airport pick` -- through bin/kcgx, through uv, all the way
    to a written record -- without any of it landing in the developer's own
    ~/.local/state/kcgx. Read at call time, not import time, so a subprocess
    inheriting the variable is enough.

    The `path=` keyword on read_airport/write_airport stays the more
    specific override: an explicit argument always beats the environment.
    """
    override = os.environ.get("KCGX_STATE_PATH")
    return Path(override) if override else STATE_PATH


def read_airport(*, path: Path | None = None) -> str | None:
    path = default_path() if path is None else path
    try:
        value = path.read_text().strip().upper()
    except (OSError, UnicodeDecodeError):
        # Unreadable and undecodable are the same story: nothing usable was
        # remembered. UnicodeDecodeError is a ValueError, not an OSError --
        # a truncated write, disk corruption, or a stray binary must fall
        # through to the next source exactly like a missing file, not raise
        # past the caller.
        return None
    return value or None


def write_airport(icao: str, *, path: Path | None = None) -> None:
    """Remember `icao`. Failing to is a lost convenience, not an error."""
    path = default_path() if path is None else path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{icao.strip().upper()}\n")
    except OSError:
        pass


def _sources(
    path: Path | None, config_loader: Callable[[], Config]
) -> Iterator[tuple[str, str | None]]:
    """(where it came from, ICAO) most specific first, evaluated lazily.

    Lazily because a launch the state file already answered should not pay
    to read squelch.toml, and — more to the point — should not be affected
    by a squelch.toml that cannot be parsed.
    """
    yield "the state file", read_airport(path=path)
    try:
        yield "squelch.toml", config_loader().icao
    except Exception:
        # A malformed squelch.toml is squelch's problem to report; it is
        # not a reason for the launcher to refuse to pick an airport.
        yield "squelch.toml", None
    yield "the built-in default", FALLBACK_ICAO


def current_icao(
    *,
    path: Path | None = None,
    config_loader: Callable[[], Config] = load_config,
    known: Callable[[str], bool] | None = None,
    warn: Callable[[str], None] = lambda _message: None,
) -> str:
    """Where the cockpit should point, most specific source first:
    the state file, then `icao` in squelch.toml, then KPDX.

    `known` says whether a candidate still exists in the airport dataset;
    one that does not is skipped, reported through `warn`, and the next
    source is tried. Reachable whenever OurAirports reclassifies a field
    out of the committed subset on regeneration, or from a hand-edited
    state file — and the alternative is that `resolve` exits 2 and the
    cockpit launches with no coordinates and no ICAO, silently degraded on
    every launch until the user happens to run `kcgx go`.

    The validation lives *here*, rather than in the caller, because the
    resolution order lives here: a caller that checked the answer
    afterwards would have to re-implement the order to know what to try
    next, and two spellings of one order is precisely how the launch and
    retarget paths drifted apart earlier in this project. Passing `known`
    in keeps state.py knowing nothing about the dataset — it is supplied by
    whoever already loaded it.

    With nothing validating, FALLBACK_ICAO comes back anyway: `resolve`
    then reports "KPDX is not in the airport dataset", which names the real
    problem rather than inventing a silent success.
    """
    for source, candidate in _sources(path, config_loader):
        if not candidate:
            continue
        if known is None or known(candidate):
            return candidate
        warn(f"{candidate} (from {source}) is not in the airport dataset")
    return FALLBACK_ICAO
