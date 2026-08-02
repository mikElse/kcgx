"""Textual UI for squelch, sized for a 48-column side pane."""

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
from squelch.pipeline import Block

BLOCKS = "▁▂▃▄▅▆▇█"
FLOOR_DBFS = -60.0
METER_WIDTH = 20

# Transcript entries (blocks, warnings, dropped markers) are mounted widgets
# and Textual never reclaims them on its own. squelch is meant to run for
# hours against a busy tower feed, which produces thousands of entries: with
# no cap, RSS grows perfectly linearly (measured ~135 MB at 1000 entries,
# ~852 MB at 8000) and every `set_level` gets slower, because the cost of a
# refresh scales with the number of mounted children. That cost lands on the
# *audio* thread, which blocks inside call_from_thread waiting for it. A few
# hundred entries is far more scrollback than anyone reads back through in a
# 48-column pane, so the oldest are dropped once the cap is reached.
MAX_TRANSCRIPT_ENTRIES = 200


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


class TranscriptView(VerticalScroll):
    """A scroll region that stays pinned to the newest entry.

    Textual's own `anchor()` looks like the tool for this, but the
    compositor applies an anchor with an *unvalidated* `set_reactive`
    (`_compositor.py`, "if widget._anchored"), so while the content is
    shorter than the viewport it drives `scroll_y` to
    `content_bottom - viewport_height` -- a negative offset the pane then
    renders as blank. Scrolling from `_mount_entry` does not work either:
    a freshly `mount()`ed child has not been laid out when the next
    statement runs, so `max_scroll_y` is still the *previous* value and the
    scroll lands one entry short -- which is precisely how warn() and
    mark_dropped() ended up below the fold.

    `_size_updated` is the compositor's post-layout hook, the first point
    at which `max_scroll_y` reflects what was just mounted. Following is
    suspended as soon as the user scrolls away (Textual calls
    `release_anchor` on every user-initiated scroll) and resumes when they
    scroll back to the bottom, so nobody reading back through the
    transcript gets yanked to the end by an incoming transmission.
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
            # release_anchor=False: this is our own follow, not the user
            # moving the view, and must not switch following off.
            self._scroll_to(y=self.max_scroll_y, animate=False, release_anchor=False)
        return changed


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
        # Not "LIVE": nothing has been received yet, and the pipeline does
        # not even start until on_mount. Claiming LIVE at construction is a
        # lie for the whole model-load window -- minutes, on a first run --
        # and it is exactly the window in which the user most needs to be
        # told that something is happening rather than nothing.
        self._state = "STARTING"
        self._muted = False
        self._level = FLOOR_DBFS
        self._history: deque[float] = deque(maxlen=METER_WIDTH)
        self._clock_text = datetime.now().strftime("%H:%M:%S")
        self._pending: Static | None = None
        # Cached once at mount rather than re-queried on every update:
        # set_level runs at the meter's cadence for the entire lifetime of
        # the app, and a DOM query per tick is pure overhead billed to the
        # audio thread.
        self._header: Static | None = None
        self._meter: Static | None = None
        self._footer: Static | None = None
        self._transcript: TranscriptView | None = None
        self._entries: deque[Widget] = deque()
        self._clock_timer = None
        self.on_mute_change = lambda muted: None
        self.on_feed_selected = lambda feed: None
        # Called once the app is actually running (from on_mount). The
        # pipeline thread must not be started before this: its very first
        # action is to warn about the model download, and a
        # call_from_thread issued before App.run() raises
        # RuntimeError("App is not running") and is lost.
        self.on_start = lambda: None

    def compose(self) -> ComposeResult:
        # markup=False everywhere: none of our content (feed labels, key
        # hints in brackets, ASR transcript text) is meant to be parsed as
        # Rich console markup. Without it, literal text like "[space]" is
        # silently swallowed as an unrecognized style tag instead of shown.
        yield Static(id="header", markup=False)
        yield Static(id="meter", markup=False)
        yield TranscriptView(id="transcript")
        yield Static(id="footer", markup=False)

    def on_mount(self) -> None:
        self._header = self.query_one("#header", Static)
        self._meter = self.query_one("#meter", Static)
        self._footer = self.query_one("#footer", Static)
        self._transcript = self.query_one("#transcript", TranscriptView)
        # Anchoring, rather than a scroll_end() after each mount: a manual
        # scroll runs before the newly mounted child has been laid out, so
        # it lands one entry short of the bottom and the newest message can
        # sit just below the fold. Textual re-applies an anchor as part of
        # its own refresh cycle, after layout, and releases it if the user
        # deliberately scrolls up -- which is the behaviour wanted anyway.
        self._refresh_header()
        self._refresh_meter()
        self._refresh_footer()
        # The clock has its own slow cadence, independent of how often audio
        # frames arrive -- see _refresh_meter's docstring note below.
        self._clock_timer = self.set_interval(1.0, self._tick_clock)
        self.on_start()

    def on_unmount(self) -> None:
        # The 1 s clock timer outlives the widgets it refreshes: during
        # teardown it can fire after #meter has been unmounted, and the
        # resulting NoMatches propagates out of App.run() -- taking main()'s
        # shutdown with it, so the PortAudio stream is never closed. Stop
        # the timer and drop the cached references so any refresh that is
        # already in flight becomes a no-op.
        if self._clock_timer is not None:
            self._clock_timer.stop()
            self._clock_timer = None
        self._header = self._meter = self._footer = None
        self._transcript = None
        self._entries.clear()
        self._pending = None

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
        if self._header is None:
            return  # not mounted yet, or already torn down
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
            self._header.update(right[:48], layout=False)
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
        self._header.update(left.ljust(content_room) + " " + right, layout=False)

    def _refresh_meter(self) -> None:
        if self._meter is None:
            return
        bar = meter_bar(self._history, width=METER_WIDTH)
        # _clock_text is refreshed on its own 1s timer (_tick_clock), not
        # recomputed here -- this method runs at audio-frame cadence and
        # datetime.now().strftime(...) fifty times a second for a value that
        # only needs to change once a second is wasted work.
        self._meter.update(
            f" {bar} {self._level:6.1f}dB  {self._clock_text}", layout=False
        )

    def _refresh_footer(self) -> None:
        if self._footer is None:
            return
        hint = "MUTED" if self._muted else "mute"
        self._footer.update(
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
        self._mount_entry(widget)

    def _mount_entry(self, widget: Widget) -> None:
        """Mount one transcript entry and enforce the retention cap.

        Every transcript entry goes through here, not just add_block's:
        warn() and mark_dropped() used to mount without scrolling at all,
        so with a transcript already filled their message landed below the
        viewport and was never seen -- pressing `f` with a dead network
        looked exactly like pressing a key that does nothing. Scrolling is
        now the transcript's anchor (see on_mount), which applies to
        everything mounted here uniformly.
        """
        transcript = self._transcript
        if transcript is None:
            return
        transcript.mount(widget)
        self._entries.append(widget)
        while len(self._entries) > MAX_TRANSCRIPT_ENTRIES:
            self._drop(self._entries.popleft())

    def _drop(self, widget: Widget) -> None:
        if widget is self._pending:
            self._pending = None
        try:
            widget.remove()
        except Exception:
            pass

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
        self._mount_entry(self._pending)

    def mark_dropped(self) -> None:
        self._clear_pending()
        self._mount_entry(
            Static("⚠ transmission lost", classes="block block-text", markup=False)
        )

    def mark_blank(self) -> None:
        """The model returned no words for the pending utterance.

        Nothing is mounted: a blank transcription is not a transcript, and
        rendering an empty entry would present "the model heard nothing" as
        though it were something the controller said. All that is required
        is that the placeholder comes back down -- otherwise mark_pending's
        guard silently swallows every later utterance for the rest of the
        run. Routine (squelch clicks transcribe to nothing), and universal
        in the model-unavailable degraded mode.
        """
        self._clear_pending()

    def _clear_pending(self) -> None:
        pending, self._pending = self._pending, None
        if pending is None:
            return
        try:
            self._entries.remove(pending)
        except ValueError:
            pass
        try:
            pending.remove()
        except Exception:
            pass

    def set_level(self, dbfs: float) -> None:
        self._level = dbfs
        self._history.append(dbfs)
        self._refresh_meter()

    # Pipeline-reported states ("live"/"reconnecting") are not the only
    # states the header needs to show truthfully: Task 9's startup path
    # calls set_state("offline") when the feed could not be resolved at
    # all, so the header never claims "● LIVE" while nothing is actually
    # playing. Anything not in this map still falls back to "LIVE", which
    # matches every state the Pipeline itself ever reports.
    _STATE_LABELS = {
        "reconnecting": "RECONNECTING",
        "offline": "OFFLINE",
        "starting": "STARTING",
    }

    def set_state(self, state: str) -> None:
        self._state = self._STATE_LABELS.get(state, "LIVE")
        self._refresh_header()

    # -- actions -----------------------------------------------------

    def action_toggle_mute(self) -> None:
        self._muted = not self._muted
        self.on_mute_change(self._muted)
        self._refresh_footer()

    def action_show_feeds(self) -> None:
        if self._feed_loader is None:
            return
        self._load_feeds()

    @work(thread=True, exclusive=True, group="feeds")
    def _load_feeds(self) -> None:
        """Fetch the feed list off the event loop.

        The production loader is an HTTP GET with a 15 s timeout. Called
        straight from the action handler it blocks Textual's event loop for
        the whole timeout -- and because the audio thread reaches the UI via
        call_from_thread, which waits on that same loop, *playback* stops
        too. Pressing `f` on a flaky network used to freeze the whole app
        for a quarter of a minute. The injected-loader seam is unchanged;
        only where it is called from has moved.

        `exclusive=True, group="feeds"` marks a superseded worker
        cancelled, but Textual cannot interrupt a running thread -- the
        body keeps running regardless, so without this check a stack of
        `f` presses against a slow fetch each marshalled their own result
        back and stacked one FeedPicker per press. Checking
        `is_cancelled` once the (uninterruptible) loader call returns is
        the only point this worker can act on its own cancellation.
        `NoActiveWorker` (no active worker in this thread/task) is treated
        as "not cancelled" -- it only arises when this body is invoked
        directly, outside the @work decorator's context, which is exactly
        how test_feed_worker_never_raises_when_the_app_has_gone drives the
        "app already gone" hazard without spinning up a real thread.
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
            # Pressing `f` and then `q` while the fetch is in flight leaves
            # this worker holding a result for an app that has already gone:
            # call_from_thread then raises "App is not running". There is
            # nobody left to show a picker to, so this is nothing to report
            # -- but uncaught it surfaces as a worker traceback printed
            # after the app has exited.
            pass

    def _present_feeds(self, feeds: list[Feed]) -> None:
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
        self._mount_entry(
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
