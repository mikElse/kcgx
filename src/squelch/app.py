"""Textual UI for squelch, sized for a 48-column side pane."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from squelch.config import Config
from squelch.feeds import Feed
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
        ("f", "show_feeds", "Feeds"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        config: Config,
        *,
        feed_label: str,
        frequency: str = "",
        feed_loader: Callable[[], list[Feed]] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._feed_label = feed_label
        self._frequency = frequency
        self._feed_loader = feed_loader
        self._state = "LIVE"
        self._muted = False
        self._level = FLOOR_DBFS
        self._history: deque[float] = deque(maxlen=METER_WIDTH)
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._pending: Static | None = None
        self.on_mute_change = lambda muted: None
        self.on_feed_selected = lambda feed: None

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
        if len(right) >= 48:
            # The state text alone can consume the whole budget or more.
            # When it does, there is no room left for the label or even the
            # separator column reserved below, so `content_room` would go to
            # 0 while `right` itself is still >=48 chars -- the old code
            # then emitted `" " + right`, 49+ cells. Truncate `right` itself
            # to the full width and stop; this is unreachable with today's
            # only two state strings ("LIVE", "RECONNECTING") but the
            # 48-cell invariant must hold for any state string structurally,
            # not by luck of the two values currently in use.
            self.query_one("#header", Static).update(right[:48], layout=False)
            return
        # Hard-truncate rather than pad-and-hope: the 48-column budget is the
        # premise of the layout, and the state text changes width at runtime.
        room = 48 - len(right)
        # One column of `room` is reserved, unconditionally, as a separator
        # between the label and the state glyph -- not just when truncation
        # kicks in. Without this, a label whose length exactly matches `room`
        # sails past the `len(left) > room` check untruncated and butts
        # straight into "●" (e.g. "...118.10● LIVE"), since ljust(room) is a
        # no-op on a string that is already `room` chars long.
        content_room = max(room - 1, 0)
        if len(left) > content_room:
            # Truncate visibly: an ellipsis before the mandatory separator,
            # so a long label reads as deliberately cut off rather than
            # colliding straight into "●" like a rendering glitch. Degrades
            # gracefully (no ellipsis, just blank) in the pathological case
            # where content_room is too small to fit one.
            if content_room >= 1:
                left = left[: content_room - 1] + "…"
            else:
                left = ""
        self.query_one("#header", Static).update(
            left.ljust(content_room) + " " + right, layout=False
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
        # The timestamp and text are separate widgets rather than one string
        # joined with "\n  " -- a literal "  " only indents the first line of
        # the text; once it wraps, continuation lines start flush at the
        # left margin because wrapping is unaware of the manually-typed
        # spaces. Giving the text widget its own `padding-left` (see
        # squelch.tcss) makes every wrapped line -- including continuations
        # -- share the same left indent, since padding applies to the box
        # Textual wraps *inside*, not to individual lines of the string.
        widget = Vertical(
            Static(stamp, classes="block-stamp", markup=False),
            Static(block.text, classes="block-text", markup=False),
            classes="block",
        )
        self.query_one("#transcript", VerticalScroll).mount(widget)
        self.query_one("#transcript", VerticalScroll).scroll_end(animate=False)

    def mark_pending(self) -> None:
        if self._pending is not None:
            return
        # "block block-text": the same two classes add_block's text widget
        # gets -- "block" for the margin between entries, "block-text" for
        # the padding-left that keeps wrapped continuation lines indented
        # (see add_block's comment). A single-Static message like this one
        # has no separate stamp widget to carry the indent, so it must carry
        # both classes itself, or a message long enough to wrap reads
        # flush-left and ragged instead of matching the blocks around it.
        self._pending = Static(
            "░ transcribing…", classes="block block-text", markup=False
        )
        self.query_one("#transcript", VerticalScroll).mount(self._pending)

    def mark_dropped(self) -> None:
        self._clear_pending()
        self.query_one("#transcript", VerticalScroll).mount(
            Static("⚠ transmission lost", classes="block block-text", markup=False)
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

    def action_show_feeds(self) -> None:
        if self._feed_loader is None:
            return
        try:
            feeds = self._feed_loader()
        except Exception:
            feeds = []
        if not feeds:
            self.warn("could not load feeds")
            return

        def handle(feed: Feed | None) -> None:
            if feed is not None:
                self.on_feed_selected(feed)

        self.push_screen(FeedPicker(feeds), handle)

    def warn(self, message: str) -> None:
        """Surface a problem in the transcript region.

        Deliberately not `self.notify` -- a toast is styled and positioned by
        Textual, which makes it awkward to assert against and easy to render
        outside the 48-column budget.
        """
        self.query_one("#transcript", VerticalScroll).mount(
            Static(f"⚠ {message}", classes="block block-text", markup=False)
        )


_PICKER_LABEL_WIDTH = 26
_PICKER_IDENT_WIDTH = 15
# FeedPicker > ListView is `width: 44` with a `solid` border (squelch.tcss),
# leaving exactly 42 content columns -- _PICKER_LABEL_WIDTH + 1 (separator)
# + _PICKER_IDENT_WIDTH must never exceed that, or a row silently clips
# inside the border with no indication anything was lost.


def _fit(text: str, width: int) -> str:
    """Fit `text` into exactly `width` cells, marking truncation visibly.

    Mirrors the header's truncation convention (see _refresh_header): a
    bare slice reads as silent data loss -- a real cut here gets a trailing
    ellipsis instead, same principle applied to the same failure mode.
    """
    if width <= 0:
        return ""
    if len(text) <= width:
        return text.ljust(width)
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


class FeedPicker(ModalScreen):
    """Overlay listing the feeds available at an airport."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, feeds: list[Feed]) -> None:
        super().__init__()
        self._feeds = feeds

    def compose(self) -> ComposeResult:
        yield ListView(
            *[
                ListItem(
                    Label(
                        f"{_fit(f.label, _PICKER_LABEL_WIDTH)} "
                        f"{_fit(f.ident, _PICKER_IDENT_WIDTH)}",
                        markup=False,
                    )
                )
                for f in self._feeds
            ],
            id="feedlist",
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(self._feeds[event.list_view.index or 0])

    def action_cancel(self) -> None:
        self.dismiss(None)
