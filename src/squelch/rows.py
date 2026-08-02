"""Rendering for one feed's row.

Every layout decision here is a pure function over strings and integers, so
the 48-column budget can be tested without a running app. `app.py` owns the
application shell; this module owns what a row looks like.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

BLOCKS = "▁▂▃▄▅▆▇█"
FLOOR_DBFS = -60.0

# The pane is 48 wide; rows carry `padding: 0 1`, leaving 46 content cells.
ROW_WIDTH = 46
# Name row: marker + space + name + space + ident + space + dot.
NAME_WIDTH = 24
IDENT_WIDTH = 16
# Meter row is otherwise empty, so the meter gets nearly the whole width --
# roughly double the history the single-feed layout could show.
METER_WIDTH = 44

_STATE_DOTS = {
    "live": "●",
    "reconnecting": "◐",
    "offline": "○",
    "starting": "◌",
}


def _glyph_for(dbfs: float) -> str:
    """Quantise one level reading to a single block glyph."""
    fraction = max(0.0, min(1.0, (dbfs - FLOOR_DBFS) / -FLOOR_DBFS))
    index = max(0, min(len(BLOCKS) - 1, int(fraction * len(BLOCKS))))
    return BLOCKS[index]


def meter_bar(history: Sequence[float], width: int = METER_WIDTH) -> str:
    """Render a rolling history of levels as one glyph per sample.

    Oldest sample at the left, newest at the right -- meant to be read as a
    scrolling waveform, not a single quantised value. Only the most recent
    `width` samples are shown; if fewer exist yet, the left is padded with
    the idle glyph so a fresh or silent meter reads as a flat low line
    rather than a partial bar or an empty gap.
    """
    recent = list(history)[-width:]
    pad = width - len(recent)
    return BLOCKS[0] * pad + "".join(_glyph_for(level) for level in recent)


def _fit(text: str, width: int) -> str:
    """Fit `text` into exactly `width` cells, marking truncation visibly.

    A bare slice reads as silent data loss; a real cut gets a trailing
    ellipsis instead.
    """
    if width <= 0:
        return ""
    if len(text) <= width:
        return text.ljust(width)
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


class FeedRow(Vertical):
    """One feed: a name row and a meter row, ruled off from its neighbours."""

    def __init__(self, session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._history: deque[float] = deque(maxlen=METER_WIDTH)
        self._name_widget: Static | None = None
        self._meter_widget: Static | None = None

    def compose(self) -> ComposeResult:
        # markup=False: feed labels are arbitrary third-party text and must
        # never be parsed as Rich console markup.
        yield Static(id=None, classes="feed-name", markup=False)
        yield Static(id=None, classes="feed-meter", markup=False)

    def on_mount(self) -> None:
        self._name_widget = self.query_one(".feed-name", Static)
        self._meter_widget = self.query_one(".feed-meter", Static)
        self.refresh_all()

    def push_level(self, dbfs: float) -> None:
        self._history.append(dbfs)
        self.refresh_meter()

    def refresh_all(self) -> None:
        self.refresh_name()
        self.refresh_meter()

    def refresh_name(self) -> None:
        if self._name_widget is None:
            return
        session = self.session
        marker = "·" if session.muted else "♪"
        dot = _STATE_DOTS.get(session.state, "●")
        line = (
            f"{marker} {_fit(session.name, NAME_WIDTH)} "
            f"{_fit(session.feed.ident, IDENT_WIDTH)} {dot}"
        )
        self._name_widget.update(_fit(line, ROW_WIDTH), layout=False)
        # Dimming is a class, not a colour written into the string: the
        # meter must keep its full contrast relationship while the whole row
        # reads as inactive.
        self.set_class(session.muted, "muted")

    def refresh_meter(self) -> None:
        if self._meter_widget is None:
            return
        self._meter_widget.update(
            _fit(meter_bar(self._history, width=METER_WIDTH), ROW_WIDTH),
            layout=False,
        )
