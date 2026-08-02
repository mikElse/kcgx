"""Textual UI for squelch, sized for a 48-column side pane."""

from __future__ import annotations

from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from squelch.config import Config
from squelch.pipeline import Block

BLOCKS = "▁▂▃▄▅▆▇█"
FLOOR_DBFS = -60.0


def meter_bar(dbfs: float, width: int = 20) -> str:
    """Render a level as block characters. -60 dBFS and below reads as idle."""
    fraction = max(0.0, min(1.0, (dbfs - FLOOR_DBFS) / -FLOOR_DBFS))
    filled = int(fraction * len(BLOCKS))
    index = max(0, min(len(BLOCKS) - 1, filled))
    if fraction <= 0.0:
        return BLOCKS[0] * width
    return BLOCKS[index] * width


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
        self._refresh_chrome()

    # -- rendering ---------------------------------------------------

    def _refresh_chrome(self) -> None:
        left = f" {self._feed_label}  {self._frequency}".rstrip()
        right = f"● {self._state} "
        # Hard-truncate rather than pad-and-hope: the 48-column budget is the
        # premise of the layout, and the state text changes width at runtime.
        room = 48 - len(right)
        self.query_one("#header", Static).update(left[:room].ljust(room) + right)
        bar = meter_bar(self._level, width=20)
        clock = datetime.now().strftime("%H:%M:%S")
        self.query_one("#meter", Static).update(
            f" {bar} {self._level:6.1f}dB  {clock}"
        )
        hint = "MUTED" if self._muted else "mute"
        self.query_one("#footer", Static).update(
            f" [space] {hint}  [f] feeds  [q] quit"
        )

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
        self._refresh_chrome()

    def set_state(self, state: str) -> None:
        self._state = "RECONNECTING" if state == "reconnecting" else "LIVE"
        self._refresh_chrome()

    # -- actions -----------------------------------------------------

    def action_toggle_mute(self) -> None:
        self._muted = not self._muted
        self.on_mute_change(self._muted)
        self._refresh_chrome()
