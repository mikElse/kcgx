"""Rendering for one feed's row.

Every layout decision here is a pure function over strings and integers, so
the 48-column budget can be tested without a running app. `app.py` owns the
application shell; this module owns what a row looks like.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

BLOCKS = "▁▂▃▄▅▆▇█"
FLOOR_DBFS = -60.0

# The pane is 48 wide; rows carry `padding: 0 1`, leaving 46 content cells.
ROW_WIDTH = 46
# Dropping the ident buys the name 10 cells compact and 20 expanded. The
# ident was never typed at runtime; `feed` in squelch.toml and the picker
# are where it is still needed.
NAME_WIDTH = 34
NAME_WIDTH_EXPANDED = 44
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


# Both states of the mute toggle are 5 cells, so nothing beside it shifts
# when it flips.
_ON = "[ ON]"
_OFF = "[OFF]"
_SOLO = "[S]"
_AMBIENT = "[A]"


def _toggle(muted: bool) -> str:
    return _OFF if muted else _ON


def compact_line(name: str, *, muted: bool, ambient: bool, state: str) -> str:
    """Name, controls, and state dot on one line.

    A muted feed is compact, and a compact row still has to offer a way back
    -- so the toggle lives here as well as on the expanded control line.
    """
    dot = _STATE_DOTS.get(state, "●")
    return f"{_fit(name, NAME_WIDTH)} {_AMBIENT} {_toggle(muted)} {dot}"


def expanded_name_line(name: str, *, state: str) -> str:
    """Name and state dot. The controls get their own line below the meter."""
    dot = _STATE_DOTS.get(state, "●")
    return f"{_fit(name, NAME_WIDTH_EXPANDED)} {dot}"


def control_line(
    *, muted: bool, ambient: bool, soloed: bool, activity: float | None
) -> str:
    """The expanded row's control strip, with activity right-aligned."""
    controls = f"{_SOLO}  {_toggle(muted)}  {_AMBIENT}"
    readout = "" if activity is None else f"busy {round(activity * 100)}%"
    return controls + readout.rjust(ROW_WIDTH - len(controls))


# Cell spans of each control, as half-open [start, stop) ranges within the
# 46-cell content area. Derived from the format strings above -- compact is
# `name(34) SP [A](3) SP [xx](5) SP dot`, expanded's control line is
# `[S](3) SP SP [xx](5) SP SP [A](3)`.
_COMPACT_AMBIENT = (NAME_WIDTH + 1, NAME_WIDTH + 4)          # 35..38
_COMPACT_TOGGLE = (NAME_WIDTH + 5, NAME_WIDTH + 10)          # 39..44
_EXPANDED_SOLO = (0, 3)
_EXPANDED_TOGGLE = (5, 10)
_EXPANDED_AMBIENT = (12, 15)

# Row-relative line indices when expanded: name, meter x3, controls.
CONTROL_LINE_Y = 4


def _within(x: int, span: tuple[int, int]) -> bool:
    return span[0] <= x < span[1]


def control_at(x: int, y: int, *, expanded: bool) -> str | None:
    """Which control, if any, sits at a content-relative cell.

    `None` means "no control here", which the caller treats as a click on
    the row body -- and a click on the row body toggles mute, so the common
    action never requires aiming at a 5-cell target.
    """
    if expanded:
        if y != CONTROL_LINE_Y:
            return None
        if _within(x, _EXPANDED_SOLO):
            return "solo"
        if _within(x, _EXPANDED_TOGGLE):
            return "mute"
        if _within(x, _EXPANDED_AMBIENT):
            return "ambient"
        return None
    if y != 0:
        return None
    if _within(x, _COMPACT_AMBIENT):
        return "ambient"
    if _within(x, _COMPACT_TOGGLE):
        return "mute"
    return None


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


@dataclass(frozen=True)
class MeterPalette:
    """The four colour stops the meter climbs through.

    Supplied by the active theme, so the meter recolours when the radar
    pane's theme changes. Rich style strings, not Textual CSS: these are
    applied per cell, which stylesheets cannot express.
    """

    dim: str
    text: str
    accent: str
    peak: str


# Rich style strings, resolved by Rich itself -- *not* Textual CSS
# variables. `$text-disabled` and friends mean nothing here and raise
# MissingStyle at render time, because these are applied per cell through
# rich.Text rather than through the stylesheet.
#
# These values are adsb-tui's `default` theme, so squelch already matches
# the radar pane before any theme sampling exists to tell it otherwise.
DEFAULT_PALETTE = MeterPalette(
    dim="#8c96a0",
    text="#c6eee8",
    accent="#6cddd6",
    peak="#ff6666",
)

# Step boundaries for each stop, over METER_STEPS (24). Roughly: the bottom
# third is noise floor, the middle is ordinary speech, the top is a strong
# signal, and the last few steps are approaching clipping.
_GRADIENT_STOPS = ((8, "dim"), (16, "text"), (21, "accent"), (METER_STEPS, "peak"))


def gradient_style(step: int, palette: MeterPalette) -> str:
    for boundary, name in _GRADIENT_STOPS:
        if step < boundary:
            return getattr(palette, name)
    return palette.peak


def meter_text(
    history: Sequence[float],
    palette: MeterPalette,
    width: int = METER_WIDTH,
) -> Text:
    """The three meter rows, with each column coloured by its own level.

    Built as one `Text` with per-cell spans rather than three styled
    widgets: the colour has to follow the sample, and a sample spans all
    three rows.
    """
    recent = list(history)[-width:]
    steps = [0] * (width - len(recent)) + [level_step(level) for level in recent]
    rows = meter_rows(history, width=width)
    text = Text(no_wrap=True)
    for row_index, row in enumerate(rows):
        if row_index:
            text.append("\n")
        for column, glyph in enumerate(row):
            text.append(glyph, style=gradient_style(steps[column], palette))
    return text


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


class RowClicked(Message):
    """A click landed on a row, on `control_name` or on its body (`None`).

    Not `self.control` -- Textual reserves that name on Message for the
    originating widget, which is what `@on` selectors match against, and
    shadowing it with a string would break them.
    """

    def __init__(self, row: "FeedRow", control_name: str | None) -> None:
        super().__init__()
        self.row = row
        self.control_name = control_name

    @property
    def control(self) -> "FeedRow":
        return self.row


class FeedRow(Vertical):
    """One feed. Compact when muted, expanded when audible.

    Expansion follows audibility rather than selection so the pane gives its
    height to what you can actually hear -- and so the tall meter and its
    redraw cost scale with the number of audible feeds, not the number of
    feeds that exist.
    """

    def __init__(
        self, session, *, palette: MeterPalette = DEFAULT_PALETTE, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.session = session
        self.palette = palette
        self._history: deque[float] = deque(maxlen=METER_WIDTH)
        self._name_widget: Static | None = None
        self._meter_widget: Static | None = None
        self._controls_widget: Static | None = None

    @property
    def expanded(self) -> bool:
        return not self.session.muted

    def compose(self) -> ComposeResult:
        # markup=False: feed labels are arbitrary third-party text and must
        # never be parsed as Rich console markup.
        yield Static(classes="feed-name", markup=False)
        yield Static(classes="feed-meter", markup=False)
        yield Static(classes="feed-controls", markup=False)

    def on_mount(self) -> None:
        self._name_widget = self.query_one(".feed-name", Static)
        self._meter_widget = self.query_one(".feed-meter", Static)
        self._controls_widget = self.query_one(".feed-controls", Static)
        self.refresh_all()

    def on_click(self, event) -> None:
        """Route a click to a control, or to the row body.

        Coordinates come from the screen and are rebased on `content_region`
        rather than on hardcoded offsets, so the border and padding in the
        stylesheet stay the single source of truth for where content starts.
        """
        content = self.content_region
        self.post_message(
            RowClicked(
                self,
                control_at(
                    event.screen_x - content.x,
                    event.screen_y - content.y,
                    expanded=self.expanded,
                ),
            )
        )

    def push_level(self, dbfs: float) -> None:
        self._history.append(dbfs)
        self.refresh_meter()

    def refresh_all(self) -> None:
        self.refresh_name()
        self.refresh_meter()

    def refresh_name(self) -> None:
        if self._name_widget is None or self._controls_widget is None:
            return
        session = self.session
        expanded = self.expanded
        self.set_class(expanded, "expanded")
        self.set_class(not expanded, "compact")
        # Dimming is a class, not a colour written into the string: the
        # meter must keep its full contrast relationship while the whole row
        # reads as inactive.
        self.set_class(session.muted, "muted")
        self.set_class(bool(getattr(session, "ambient", False)), "ambient")
        self.set_class(bool(getattr(session, "soloed", False)), "soloed")

        if expanded:
            self._name_widget.update(
                expanded_name_line(session.name, state=session.state),
                layout=False,
            )
            self._controls_widget.update(
                control_line(
                    muted=session.muted,
                    ambient=bool(getattr(session, "ambient", False)),
                    soloed=bool(getattr(session, "soloed", False)),
                    activity=session.activity,
                ),
                layout=False,
            )
        else:
            self._name_widget.update(
                compact_line(
                    session.name,
                    muted=session.muted,
                    ambient=bool(getattr(session, "ambient", False)),
                    state=session.state,
                ),
                layout=False,
            )
        self._meter_widget.display = expanded
        self._controls_widget.display = expanded

    def refresh_meter(self) -> None:
        if self._meter_widget is None or not self.expanded:
            return
        self._meter_widget.update(
            meter_text(self._history, self.palette), layout=False
        )
