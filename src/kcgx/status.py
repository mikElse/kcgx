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

import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.widgets import Static

from kcgx.airports import Airport, find, load_airports
from kcgx.state import current_icao

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


# The same popup `Ctrl-b a` opens. It is spelled here and in
# kcgx.tmux.conf, and test_the_click_and_the_keybinding_run_the_same_popup
# pins the two together -- a hint that says "^b a" while the click does
# something else would be worse than no hint at all.
PICKER_POPUP = ("display-popup", "-E", "-w", "64", "-h", "20", "kcgx go")

TICK_SECONDS = 1.0


def now_pair() -> tuple[datetime, datetime]:
    """UTC and local from one instant, so the two clocks cannot disagree."""
    utc = datetime.now(timezone.utc)
    return utc, utc.astimezone()


def open_picker(run: Callable[..., object] = subprocess.run) -> None:
    run(("tmux", *PICKER_POPUP))


class StatusPane(App[None]):
    CSS = """
    Screen { background: $surface; }
    #body { padding: 1; }
    #airport { height: 1; }
    #line2 { height: 1; }
    #clock { width: auto; }
    #hint { width: 1fr; text-align: right; color: $text-muted; }
    #hint:hover { color: $text; }
    """

    def __init__(
        self,
        *,
        resolver: Callable[[], str] = current_icao,
        airports_loader: Callable[[], list[Airport]] = load_airports,
        now: Callable[[], tuple[datetime, datetime]] = now_pair,
        opener: Callable[[], None] = open_picker,
    ) -> None:
        super().__init__()
        self._resolver = resolver
        self._airports_loader = airports_loader
        self._now = now
        self._opener = opener
        self._airports: list[Airport] = []
        self._icao = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="body"):
            yield Static("", id="airport")
            with Horizontal(id="line2"):
                yield Static("", id="clock")
                yield Static("", id="hint")

    def on_mount(self) -> None:
        self._airports = self._airports_loader()
        self.tick()
        self.set_interval(TICK_SECONDS, self.tick)

    def tick(self) -> None:
        """Redraw the clock, and pick up an airport that changed underneath.

        Re-reading through the resolver every second is what lets `kcgx go`
        move the cockpit without touching this pane: no respawn, no flicker,
        and it is right even if the remembered airport changes by some other
        route.
        """
        icao = self._resolver()
        airport = find(icao, self._airports)
        self.query_one("#airport", Static).update(
            airport_line(airport, icao, CONTENT_WIDTH), layout=False
        )

        utc, local = self._now()
        clocks = clock_text(utc, local)
        self.query_one("#clock", Static).update(clocks, layout=False)
        self.query_one("#hint", Static).update(
            hint_for_width(CONTENT_WIDTH - len(clocks) - 1), layout=False
        )

    def on_click(self, event: Click) -> None:
        widget = getattr(event, "widget", None)
        if widget is None or widget.id != "hint":
            return
        try:
            self._opener()
        except Exception:
            # Losing the mouse shortcut is not a reason to lose the clock;
            # `Ctrl-b a` still works.
            pass


def main() -> int:
    StatusPane().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
