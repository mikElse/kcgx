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
METER_ROWS = 3
# One glyph per row of vertical resolution, so a sample spans 3 x 8 steps.
# At a single row a colour gradient has too few cells to read as a gradient,
# which is the whole reason the expanded meter is worth its height.
METER_STEPS = METER_ROWS * len(BLOCKS)  # 24
# The meter row carries nothing else, so it gets the full content width.
METER_WIDTH = 46

_STATE_DOTS = {
    "live": "●",
    "reconnecting": "◐",
    "offline": "○",
    "starting": "◌",
}


def level_step(dbfs: float) -> int:
    """Quantise one level reading to 0..METER_STEPS-1."""
    fraction = max(0.0, min(1.0, (dbfs - FLOOR_DBFS) / -FLOOR_DBFS))
    return max(0, min(METER_STEPS - 1, int(fraction * METER_STEPS)))


def _column(step: int) -> tuple[str, str, str]:
    """Top, middle, and bottom glyphs for one sample.

    Rows below the level read as full blocks, the row containing it gets a
    partial glyph, and rows above it are blank -- so the three rows compose
    into one tall bar rather than three independent meters.
    """
    glyphs = []
    for row in range(METER_ROWS):  # 0 = bottom
        base = row * len(BLOCKS)
        if step >= base + len(BLOCKS) - 1:
            glyphs.append(BLOCKS[-1])
        elif step < base:
            glyphs.append(" ")
        else:
            glyphs.append(BLOCKS[step - base])
    glyphs.reverse()  # top first
    return glyphs[0], glyphs[1], glyphs[2]


def meter_rows(
    history: Sequence[float], width: int = METER_WIDTH
) -> tuple[str, str, str]:
    """Render a rolling history of levels as one bar per sample.

    Oldest sample at the left, newest at the right. Only the most recent
    `width` samples are shown; if fewer exist, the left is padded with the
    idle column so a fresh meter reads as a flat low line rather than a gap.
    """
    recent = list(history)[-width:]
    columns = [_column(0)] * (width - len(recent))
    columns += [_column(level_step(level)) for level in recent]
    return (
        "".join(c[0] for c in columns),
        "".join(c[1] for c in columns),
        "".join(c[2] for c in columns),
    )


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
        self._meter_widget.update("\n".join(meter_rows(self._history)), layout=False)
