"""Textual UI for squelch, sized for a 48-column side pane."""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from squelch.config import Config
from squelch.pipeline import Block

BLOCKS = "▁▂▃▄▅▆▇█"
FLOOR_DBFS = -60.0
METER_WIDTH = 20


def _glyph_for(dbfs: float) -> str:
    """Quantise one level reading to a single block glyph."""
    fraction = max(0.0, min(1.0, (dbfs - FLOOR_DBFS) / -FLOOR_DBFS))
    index = max(0, min(len(BLOCKS) - 1, int(fraction * len(BLOCKS))))
    return BLOCKS[index]


def meter_bar(history: Sequence[float], width: int = METER_WIDTH) -> str:
    """Render a rolling history of levels as one glyph per sample.

    Oldest sample at the left, newest at the right -- this is meant to be
    called with an ever-growing history and read like a scrolling waveform,
    not a single quantised value. Only the most recent `width` samples are
    shown (older ones have "scrolled off"); if fewer than `width` samples
    exist yet, the left is padded with the idle glyph so a fresh or silent
    meter reads as a flat low line rather than a partial bar or empty gap.
    """
    recent = list(history)[-width:]
    pad = width - len(recent)
    return BLOCKS[0] * pad + "".join(_glyph_for(level) for level in recent)


class SquelchApp(App):
    CSS_PATH = "squelch.tcss"
    BINDINGS = [
        ("space", "toggle_mute", "Mute"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self, config: Config, *, feed_label: str, frequency: str = ""
    ) -> None:
        super().__init__()
        self._config = config
        self._feed_label = feed_label
        self._frequency = frequency
        self._state = "LIVE"
        self._muted = False
        self._level = FLOOR_DBFS
        self._history: deque[float] = deque(maxlen=METER_WIDTH)
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._pending: Static | None = None
        self.on_mute_change = lambda muted: None

    def compose(self) -> ComposeResult:
        # markup=False everywhere: none of our content (feed labels, key
        # hints in brackets, ASR transcript text) is meant to be parsed as
        # Rich console markup. Without it, literal text like "[space]" is
        # silently swallowed as an unrecognized style tag instead of shown.
        yield Static(id="header", markup=False)
        yield Static(id="meter", markup=False)
        yield VerticalScroll(id="transcript")
        yield Static(id="footer", markup=False)

    def on_mount(self) -> None:
        self._refresh_header()
        self._refresh_meter()
        self._refresh_footer()
        # The clock has its own slow cadence, independent of how often audio
        # frames arrive -- see _refresh_meter's docstring note below.
        self.set_interval(1.0, self._tick_clock)

    # -- rendering ---------------------------------------------------
    #
    # Each chrome widget (header/meter/footer) has a fixed CSS height and
    # never changes size, so every update below passes layout=False: there is
    # no layout pass worth triggering, only the (cheap) repaint of that one
    # line. What actually matters is that each setter below touches only the
    # one widget it changed, rather than one _refresh_chrome() doing
    # 3x query_one + 3x Static.update() on every call. Wired through the
    # pipeline (Task 9), set_level fires at the ~20ms audio frame cadence --
    # roughly 50 times a second, sustained for the app's entire runtime -- so
    # touching the header and footer on every level tick was wasted work for
    # two widgets that were not changing.

    def _refresh_header(self) -> None:
        left = f" {self._feed_label}  {self._frequency}".rstrip()
        right = f"● {self._state} "
        # Hard-truncate rather than pad-and-hope: the 48-column budget is the
        # premise of the layout, and the state text changes width at runtime.
        room = 48 - len(right)
        if len(left) > room:
            # Truncate visibly: an ellipsis and a separating space before the
            # state glyph, so a long label reads as deliberately cut off
            # rather than colliding straight into "●" like a rendering
            # glitch. Degrades gracefully (no ellipsis, just blank) in the
            # pathological case where room is too small to fit one.
            if room >= 2:
                left = left[: room - 2] + "… "
            else:
                left = " " * max(room, 0)
        self.query_one("#header", Static).update(
            left.ljust(room) + right, layout=False
        )

    def _refresh_meter(self) -> None:
        bar = meter_bar(self._history, width=METER_WIDTH)
        # _clock_text is refreshed on its own 1s timer (_tick_clock), not
        # recomputed here -- this method runs at audio-frame cadence and
        # datetime.now().strftime(...) fifty times a second for a value that
        # only needs to change once a second is wasted work.
        self.query_one("#meter", Static).update(
            f" {bar} {self._level:6.1f}dB  {self._clock_text}", layout=False
        )

    def _refresh_footer(self) -> None:
        hint = "MUTED" if self._muted else "mute"
        self.query_one("#footer", Static).update(
            f" [space] {hint}  [f] feeds  [q] quit", layout=False
        )

    def _tick_clock(self) -> None:
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._refresh_meter()

    # -- public API driven by the pipeline ---------------------------

    def add_block(self, block: Block) -> None:
        self._clear_pending()
        stamp = block.started_at.strftime("%H:%M:%S")
        widget = Static(f"{stamp}\n  {block.text}", classes="block", markup=False)
        self.query_one("#transcript", VerticalScroll).mount(widget)
        self.query_one("#transcript", VerticalScroll).scroll_end(animate=False)

    def mark_pending(self) -> None:
        if self._pending is not None:
            return
        self._pending = Static("░ transcribing…", classes="block", markup=False)
        self.query_one("#transcript", VerticalScroll).mount(self._pending)

    def mark_dropped(self) -> None:
        self._clear_pending()
        self.query_one("#transcript", VerticalScroll).mount(
            Static("⚠ transmission lost", classes="block", markup=False)
        )

    def _clear_pending(self) -> None:
        if self._pending is not None:
            self._pending.remove()
            self._pending = None

    def set_level(self, dbfs: float) -> None:
        self._level = dbfs
        self._history.append(dbfs)
        self._refresh_meter()

    def set_state(self, state: str) -> None:
        self._state = "RECONNECTING" if state == "reconnecting" else "LIVE"
        self._refresh_header()

    # -- actions -----------------------------------------------------

    def action_toggle_mute(self) -> None:
        self._muted = not self._muted
        self.on_mute_change(self._muted)
        self._refresh_footer()
