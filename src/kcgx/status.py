"""The cockpit's status pane: which airport, what time, how to change it.

Four rows in the top of the right column, above squelch. The two lines it
shows are built by the pure functions here so that what the pane says can
be checked without a terminal.

`fit` is deliberately a local copy rather than an import from
kcgx.picker -- these are two independently-sized surfaces, and coupling
them would mean a change to the picker's row layout could silently reflow
the status line.
"""

from __future__ import annotations

from datetime import datetime

from kcgx.airports import Airport

# The right column is 48 columns; one cell of padding each side leaves 46.
STATUS_WIDTH = 48
CONTENT_WIDTH = STATUS_WIDTH - 2
# One row of padding, two content lines, one row of padding.
STATUS_ROWS = 4

PICKER_HINT = "▾ airport (^b a)"
PICKER_HINT_SHORT = "▾"


def fit(text: str, width: int) -> str:
    """Pad to `width`, or truncate with a visible ellipsis."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def airport_line(airport: Airport | None, icao: str, width: int) -> str:
    """Code and name -- or the bare code when the dataset has no such field.

    `airport` is None when the remembered ICAO is not in the dataset, which
    a dataset regeneration can cause. Showing the code alone is honest and
    keeps the pane alive; the airport-search work made the same choice.
    """
    if airport is None:
        return fit(icao, width)
    return fit(f"{airport.icao}  {airport.name}", width)


def clock_text(now_utc: datetime, now_local: datetime) -> str:
    """Zulu first, because that is what you are hearing on the feed."""
    return f"{now_utc:%H%M}Z   {now_local:%H:%M %Z}"


def hint_for_width(available: int) -> str:
    """The picker affordance, shrunk rather than dropped.

    When the pane is too narrow for both, the clocks win: the keybinding
    still works without the words next to it, but a clock that silently
    disappears is worse than a hint that shrinks.
    """
    if available >= len(PICKER_HINT):
        return PICKER_HINT
    return PICKER_HINT_SHORT
