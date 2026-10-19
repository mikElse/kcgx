"""Textual UI for squelch, sized for a 48-column side pane.

One row-pair per feed: name and ident above, level meter below, ruled
apart. Every feed meters whether or not it is audible — muting is an audio
gate, not a pause — so a muted feed dims but keeps moving.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from typing import Any
from datetime import datetime

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static
from textual.worker import NoActiveWorker, get_current_worker

from squelch.config import Config
from squelch.config_view import ConfigScreen
from squelch.feeds import Feed
from squelch.radar_theme import POLL_SECONDS, RadarTheme
from squelch.themes import METER_PALETTES, TEXTUAL_THEME_PREFIX, textual_theme
from squelch.cockpit import ADDED, FEED, MESSAGE, ORDER, Cockpit
from squelch.rows import (
    BLOCKS,
    FLOOR_DBFS,
    METER_WIDTH,
    NAME_WIDTH,
    ROW_WIDTH,
    FeedRow,
    RowClicked,
    _fit,
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
    # Ranking is cheap; applying it is what needs to be rare.
    RESORT_INTERVAL = 5.0
    # 25 Hz: fast enough to read as a waveform, and the cost scales with
    # what you are listening to rather than with how many feeds exist.
    LEVEL_INTERVAL = 1 / 25
    BINDINGS = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("space", "toggle_mute", "Mute"),
        ("S", "toggle_solo", "Solo"),
        ("a", "toggle_ambient", "Ambient"),
        ("c", "show_config", "Config"),
        # Still bound, just no longer advertised on the footer: `q` is the
        # only way out, and `f` still opens the feed picker.
        ("f", "show_feeds", "Feeds"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        config: Config,
        sessions: Sequence,
        *,
        feed_loader: Callable[[], list[Feed]] | None = None,
        feed_opener: Callable[[Feed], Any] | None = None,
        radar_theme: RadarTheme | None = None,
        mixer: Any = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._feed_loader = feed_loader
        self._selected = 0
        self._resort_timer = None
        self._level_timer = None
        self._radar_theme = radar_theme
        self._theme_timer = None
        # The config overlay adjusts the audio path through this. None
        # outside a real run, where the overlay is read-only.
        self._mixer = mixer
        # The rules: stream slots, mute, solo, ambient, ordering. The app
        # draws what the cockpit decides and forwards what the viewer does.
        self._cockpit = Cockpit(
            config,
            sessions,
            feed_opener=feed_opener,
            on_change=self._on_cockpit_change,
        )
        # The stack as the widgets show it. Kept in step with the cockpit by
        # _on_cockpit_change; selection is an index into this, because
        # selection belongs to a viewer and the cockpit has no viewers.
        self._shown: list = self._cockpit.sessions
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._header: Static | None = None
        self._footer: Static | None = None
        self._messages: MessageLog | None = None
        self._feed_list: FeedList | None = None
        self._rows: dict[int, FeedRow] = {}
        self._entries: deque[Widget] = deque()
        self._clock_timer = None
        self.on_feed_selected = self.jump_to_feed
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
        self._resort_timer = self.set_interval(
            self.RESORT_INTERVAL, self._tick_resort
        )
        self._level_timer = self.set_interval(
            self.LEVEL_INTERVAL, self._tick_levels
        )
        for name in METER_PALETTES:
            self.register_theme(textual_theme(name))
        if self._radar_theme is not None:
            self.apply_theme(self._radar_theme.initial())
            self._theme_timer = self.set_interval(POLL_SECONDS, self._poll_theme)
        self.on_start()

    def on_unmount(self) -> None:
        # The 1 s clock timer outlives the widgets it refreshes: during
        # teardown it can fire after #header has been unmounted, and the
        # resulting NoMatches propagates out of App.run() -- taking main()'s
        # shutdown with it, so PortAudio streams are never closed.
        if self._clock_timer is not None:
            self._clock_timer.stop()
            self._clock_timer = None
        if self._resort_timer is not None:
            self._resort_timer.stop()
            self._resort_timer = None
        if self._level_timer is not None:
            self._level_timer.stop()
            self._level_timer = None
        if self._theme_timer is not None:
            self._theme_timer.stop()
            self._theme_timer = None
        self._header = self._footer = None
        self._messages = None
        self._feed_list = None
        self._rows = {}
        self._entries.clear()

    # -- the cockpit ---------------------------------------------------

    # tests/test_app.py, tests/test_feed_picker.py and squelch.__main__ read
    # these. They are views of the cockpit now, not state of their own.
    @property
    def _sessions(self) -> list:
        return self._shown

    @property
    def _solo(self):
        return self._cockpit.solo

    @property
    def _feed_opener(self):
        return self._cockpit.feed_opener

    @_feed_opener.setter
    def _feed_opener(self, opener) -> None:
        self._cockpit.feed_opener = opener

    def _on_cockpit_change(self, kind: str, payload) -> None:
        """Turn what the cockpit did into what the widgets show."""
        if kind == FEED:
            self._refresh_row(payload)
            self._refresh_header()
        elif kind == ORDER:
            self._show_order(payload)
        elif kind == ADDED:
            self._shown.append(payload)
            row = FeedRow(payload, classes="feed")
            self._rows[id(payload)] = row
            if self._feed_list is not None:
                self._feed_list.mount(row)
        elif kind == MESSAGE:
            # Looked up at call time: tests replace app.warn with a list's
            # append, and must keep catching these.
            self.warn(payload)

    def _show_order(self, order: list) -> None:
        """Move rows to match the cockpit's order, keeping the selection on
        its feed.

        Moves rather than remounts: remounting would drop every row's meter
        history and its scroll position. `move_child` keeps the same widget
        instances, which is also why `_rows` can stay keyed by
        `id(session)`.
        """
        selected = self.selected_session
        self._shown = list(order)
        feed_list = self._feed_list
        if feed_list is not None:
            for index, session in enumerate(self._shown):
                row = self._rows.get(id(session))
                if row is not None:
                    feed_list.move_child(row, before=index)
        if selected is not None and selected in self._shown:
            # Selection belongs to a feed, not to a position.
            self._selected = self._shown.index(selected)
        self._apply_selection()

    def on_key(self, event) -> None:
        # A row that moves between the decision to press a key and the press
        # itself acts on the wrong feed.
        self._cockpit.note_input()

    def _tick_resort(self) -> None:
        self._cockpit.tick_resort()

    def start_streams(self) -> None:
        """Connect the feeds that get a slot; the cockpit says why the rest
        wait. Called once the app is running, in place of starting every
        session."""
        self._cockpit.start()
        self._refresh_header()

    def reconcile_streams(self) -> None:
        self._cockpit.reconcile_streams()
        self._refresh_header()

    def action_toggle_mute(self) -> None:
        session = self.selected_session
        if session is not None:
            self._cockpit.toggle_mute(session.feed.ident)

    def action_toggle_solo(self) -> None:
        session = self.selected_session
        if session is not None:
            self._cockpit.toggle_solo(session.feed.ident)

    def action_toggle_ambient(self) -> None:
        session = self.selected_session
        if session is not None:
            self._cockpit.toggle_ambient(session.feed.ident)

    def jump_to_feed(self, feed) -> None:
        """Move the selection to `feed`'s row, opening it if it is not open.

        The picker used to exist to report an ident, which stopped making
        sense when the row stopped showing one. What it is good for now is
        finding a frequency quickly -- which matters more once activity
        sorting is moving rows around.

        Opening is the other half, and it is what makes `f` a real recovery
        from a failed startup rather than a suggestion. When LiveATC's
        listing is refused at launch, squelch opens the configured feed
        alone (or nothing) and says "press f to retry". Pressing `f`
        refetches the listing and usually succeeds -- but every feed it
        turned up then answered "is not open", which is true, unhelpful,
        and the end of the road short of restarting the app.
        """
        for index, session in enumerate(self._shown):
            if session.feed.ident == feed.ident:
                self._selected = index
                self._apply_selection()
                return
        self.open_feed(feed)

    def open_feed(self, feed) -> None:
        """Add a feed to the running stack, metering and audible.

        Audible rather than muted: this is only reached by picking a feed
        that is not open, which is an explicit request to hear it -- and
        arriving at a new muted row among a dozen others is indistinguishable
        from nothing having happened.
        """
        session = self._cockpit.open_feed(feed)
        if session is None:
            return
        self._selected = self._shown.index(session)
        self._apply_selection()
        self._refresh_header()

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
            " [↑↓] select  [space] mute  [c] config", layout=False
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

    def apply_theme(self, name: str) -> None:
        """Adopt one of adsb-tui's themes, repainting the meters with it."""
        palette = METER_PALETTES.get(name)
        if palette is None:
            return
        self.theme = f"{TEXTUAL_THEME_PREFIX}{name}"
        for row in self._rows.values():
            row.palette = palette
            row.refresh_meter()

    @work(thread=True, exclusive=True, group="theme")
    def _poll_theme(self) -> None:
        """Sample the radar pane off the event loop.

        `capture-pane` is a subprocess. Called straight from the timer it
        would block Textual's loop for its whole timeout -- and because the
        audio threads reach the UI through call_from_thread, which waits on
        that same loop, playback would stop too.
        """
        assert self._radar_theme is not None
        name = self._radar_theme.poll()
        if name is None:
            return
        try:
            self.call_from_thread(self.apply_theme, name)
        except Exception:
            # The app quit while the capture was in flight.
            pass

    # -- actions -------------------------------------------------------

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

    def _refresh_row(self, session) -> None:
        # refresh_all rather than refresh_name: a mute change flips the row
        # between compact and expanded, so the meter has to be redrawn or
        # cleared along with the text.
        row = self._rows.get(id(session))
        if row is not None:
            row.refresh_all()

    def _refresh_rows(self) -> None:
        for session in self._sessions:
            self._refresh_row(session)

    def on_row_clicked(self, message: RowClicked) -> None:
        self._cockpit.note_input()
        session = message.row.session
        self._selected = self._sessions.index(session)
        self._apply_selection()
        if message.control_name == "solo":
            self.action_toggle_solo()
        elif message.control_name == "ambient":
            self.action_toggle_ambient()
        else:
            # Both an explicit [ON]/[OFF] hit and a click anywhere on the
            # row body mute the feed -- the common action must not require
            # aiming at a 5-cell target.
            self.action_toggle_mute()

    # -- driven by the sessions ----------------------------------------

    def _tick_levels(self) -> None:
        """Read each audible feed's post-compression level.

        Polled rather than pushed: the level is computed inside the audio
        callback, which is a real-time context and may not call into the
        UI. Reading a float from here costs nothing and removes level
        updates from the audio path entirely.
        """
        for session in self._sessions:
            row = self._rows.get(id(session))
            if row is not None and row.expanded:
                row.push_level(session.level)

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

    # -- config --------------------------------------------------------

    def action_show_config(self) -> None:
        self.push_screen(ConfigScreen(self._config, mixer=self._mixer))

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
                        classes="picker-ident",
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
