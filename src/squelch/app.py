"""Textual UI for squelch, sized for a 48-column side pane.

One row-pair per feed: name and ident above, level meter below, ruled
apart. Every feed meters whether or not it is audible — muting is an audio
gate, not a pause — so a muted feed dims but keeps moving.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static
from textual.worker import NoActiveWorker, get_current_worker

from squelch.config import Config
from squelch.feeds import Feed
from squelch.rows import (
    BLOCKS,
    FLOOR_DBFS,
    IDENT_WIDTH,
    METER_WIDTH,
    NAME_WIDTH,
    ROW_WIDTH,
    FeedRow,
    _fit,
    _glyph_for,
    meter_bar,
)

# Messages are mounted widgets and Textual never reclaims them on its own.
# squelch runs for hours, and a dozen feeds can warn repeatedly: with no
# cap, RSS grows linearly and every level update gets slower, because a
# refresh scales with the number of mounted children -- a cost billed to the
# audio threads, which block inside call_from_thread waiting for it.
MAX_MESSAGES = 200


class FeedList(VerticalScroll):
    """The scrollable stack of feed rows.

    `can_focus = False` is load-bearing. A VerticalScroll becomes focusable
    once its content overflows, and a focused scroll container answers the
    arrow keys itself -- so with few enough feeds to fit, arrows moved the
    selection, and with enough feeds to scroll they silently scrolled the
    container instead and the selection froze at the top. That is precisely
    the case this stack exists for. Scrolling here is driven by the
    selection (see _apply_selection), never by the container.
    """

    can_focus = False


class MessageLog(VerticalScroll):
    """A scroll region that stays pinned to the newest entry.

    Textual's own `anchor()` looks like the tool for this, but the
    compositor applies an anchor with an *unvalidated* `set_reactive`, so
    while the content is shorter than the viewport it drives `scroll_y` to
    a negative offset the pane then renders as blank. Scrolling from the
    mount site does not work either: a freshly `mount()`ed child has not
    been laid out when the next statement runs, so `max_scroll_y` is still
    the *previous* value and the scroll lands one entry short -- which is
    precisely how warnings ended up below the fold.

    `_size_updated` is the compositor's post-layout hook, the first point
    at which `max_scroll_y` reflects what was just mounted. Following is
    suspended as soon as the user scrolls away and resumes when they scroll
    back to the bottom.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._follow = True

    def release_anchor(self) -> None:
        super().release_anchor()
        self._follow = False

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if new_value >= self.max_scroll_y:
            self._follow = True

    def _size_updated(self, size, virtual_size, container_size, layout=True):
        changed = super()._size_updated(size, virtual_size, container_size, layout)
        if self._follow and self.scroll_y < self.max_scroll_y:
            self._scroll_to(y=self.max_scroll_y, animate=False, release_anchor=False)
        return changed


class SquelchApp(App):
    CSS_PATH = "squelch.tcss"
    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("space", "toggle_mute", "Mute"),
        ("f", "show_feeds", "Feeds"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        config: Config,
        sessions: Sequence,
        *,
        feed_loader: Callable[[], list[Feed]] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._sessions = list(sessions)
        self._feed_loader = feed_loader
        self._selected = 0
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._header: Static | None = None
        self._footer: Static | None = None
        self._messages: MessageLog | None = None
        self._feed_list: FeedList | None = None
        self._rows: dict[int, FeedRow] = {}
        self._entries: deque[Widget] = deque()
        self._clock_timer = None
        self.on_feed_selected = lambda feed: None
        # Called once the app is actually running (from on_mount). Sessions
        # must not be started before this: their first act can be a warning,
        # and a call_from_thread issued before App.run() has the loop up
        # raises "App is not running" and is lost.
        self.on_start = lambda: None

    def compose(self) -> ComposeResult:
        yield Static(id="header", markup=False)
        with FeedList(id="feeds"):
            for session in self._sessions:
                yield FeedRow(session, classes="feed")
        yield MessageLog(id="messages")
        yield Static(id="footer", markup=False)

    def on_mount(self) -> None:
        self._header = self.query_one("#header", Static)
        self._footer = self.query_one("#footer", Static)
        self._messages = self.query_one("#messages", MessageLog)
        self._feed_list = self.query_one("#feeds", FeedList)
        self._rows = {id(row.session): row for row in self.query(FeedRow)}
        self._refresh_header()
        self._refresh_footer()
        self._apply_selection()
        self._clock_timer = self.set_interval(1.0, self._tick_clock)
        self.on_start()

    def on_unmount(self) -> None:
        # The 1 s clock timer outlives the widgets it refreshes: during
        # teardown it can fire after #header has been unmounted, and the
        # resulting NoMatches propagates out of App.run() -- taking main()'s
        # shutdown with it, so PortAudio streams are never closed.
        if self._clock_timer is not None:
            self._clock_timer.stop()
            self._clock_timer = None
        self._header = self._footer = None
        self._messages = None
        self._feed_list = None
        self._rows = {}
        self._entries.clear()

    # -- rendering -----------------------------------------------------

    def _refresh_header(self) -> None:
        if self._header is None:
            return
        live = sum(1 for s in self._sessions if s.state == "live")
        left = f" {self._config.icao}  {len(self._sessions)} feeds"
        right = f"{self._clock_text}  {live} live "
        room = 48 - len(right)
        if room < 1:
            self._header.update(right[:48], layout=False)
            return
        self._header.update(_fit(left, room) + right, layout=False)

    def _refresh_footer(self) -> None:
        if self._footer is None:
            return
        self._footer.update(
            " [↑↓] select  [space] mute  [f] feeds  [q] quit", layout=False
        )

    def _tick_clock(self) -> None:
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._refresh_header()

    # -- selection -----------------------------------------------------

    @property
    def selected_session(self):
        if not self._sessions:
            return None
        return self._sessions[self._selected]

    def _apply_selection(self) -> None:
        for index, session in enumerate(self._sessions):
            row = self._rows.get(id(session))
            if row is not None:
                row.set_class(index == self._selected, "selected")
        row = self._rows.get(id(self.selected_session))
        if row is not None and self._feed_list is not None:
            # Keep the selection on screen when it moves past the viewport --
            # the whole point of a scrollable stack.
            self._feed_list.scroll_to_widget(row, animate=False)

    def action_cursor_down(self) -> None:
        if not self._sessions:
            return
        self._selected = min(self._selected + 1, len(self._sessions) - 1)
        self._apply_selection()

    def action_cursor_up(self) -> None:
        if not self._sessions:
            return
        self._selected = max(self._selected - 1, 0)
        self._apply_selection()

    def action_toggle_mute(self) -> None:
        session = self.selected_session
        if session is None:
            return
        session.toggle_mute()
        row = self._rows.get(id(session))
        if row is not None:
            row.refresh_name()

    # -- driven by the sessions ----------------------------------------

    def set_level(self, session, dbfs: float) -> None:
        row = self._rows.get(id(session))
        if row is not None:
            row.push_level(dbfs)

    def set_state(self, session, state: str) -> None:
        row = self._rows.get(id(session))
        if row is not None:
            row.refresh_name()
        self._refresh_header()

    def warn(self, message: str) -> None:
        """Surface a problem in the message log.

        Deliberately not `self.notify` -- a toast is styled and positioned
        by Textual, which makes it awkward to assert against and easy to
        render outside the 48-column budget.
        """
        self._mount_message(
            Static(f"⚠ {message}", classes="block block-text", markup=False)
        )

    def warn_for(self, session, message: str) -> None:
        """A warning that belongs to one feed, named so it can be placed."""
        self.warn(f"{session.name}: {message}")

    def _mount_message(self, widget: Widget) -> None:
        log = self._messages
        if log is None:
            return
        log.mount(widget)
        self._entries.append(widget)
        while len(self._entries) > MAX_MESSAGES:
            self._drop(self._entries.popleft())

    def _drop(self, widget: Widget) -> None:
        try:
            widget.remove()
        except Exception:
            pass

    # -- feed picker ---------------------------------------------------

    def action_show_feeds(self) -> None:
        if self._feed_loader is None:
            return
        self._load_feeds()

    @work(thread=True, exclusive=True, group="feeds")
    def _load_feeds(self) -> None:
        """Fetch the feed list off the event loop.

        The production loader is an HTTP GET with a 15 s timeout. Called
        straight from the action handler it blocks Textual's event loop for
        the whole timeout -- and because the audio threads reach the UI via
        call_from_thread, which waits on that same loop, *playback* stops
        too.

        `exclusive=True` marks a superseded worker cancelled, but Textual
        cannot interrupt a running thread -- the body keeps running
        regardless, so without the check below a stack of `f` presses
        against a slow fetch each marshalled their own result back and
        stacked one FeedPicker per press.
        """
        assert self._feed_loader is not None
        try:
            feeds = self._feed_loader()
        except Exception:
            feeds = []
        try:
            cancelled = get_current_worker().is_cancelled
        except NoActiveWorker:
            cancelled = False
        if cancelled:
            return
        try:
            self.call_from_thread(self._present_feeds, feeds)
        except Exception:
            # Pressing `f` then `q` while the fetch is in flight leaves this
            # worker holding a result for an app that has already gone.
            pass

    def _present_feeds(self, feeds: list[Feed]) -> None:
        if not feeds:
            self.warn("could not load feeds")
            return

        def handle(feed: Feed | None) -> None:
            if feed is not None:
                self.on_feed_selected(feed)

        self.push_screen(FeedPicker(feeds), handle)


_PICKER_LABEL_WIDTH = 26
_PICKER_IDENT_WIDTH = 15
# FeedPicker > ListView is `width: 44` with a `solid` border (squelch.tcss),
# leaving exactly 42 content columns -- _PICKER_LABEL_WIDTH + 1 (separator)
# + _PICKER_IDENT_WIDTH must never exceed that, or a row silently clips
# inside the border with no indication anything was lost.


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
