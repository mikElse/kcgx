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
from textual.widget import Widget
from textual.widgets import Static

from kcgx.airports import Airport, find, load_airports
from kcgx import bigtext
from kcgx.state import current_icao

# The right column starts at 48 columns; one cell of padding each side
# leaves 46. A starting position, not a constraint -- the splitter is
# drag-resizable, so this is the default the pane formats to only until a
# layout tells it how wide it really is. See content_width().
STATUS_WIDTH = 48
CONTENT_WIDTH = STATUS_WIDTH - 2
# #body pads one cell on every side, so two of these rows are padding and
# the rest are content: bigtext.HEIGHT rows of banner, the name, the clock.
# Derived rather than written down -- one too few drops the clock line, and
# the layout does that silently rather than complaining.
#
# bin/kcgx declares this height too, and tmux believes the launcher rather
# than the app. test_the_launcher_and_the_app_agree_about_the_pane_height
# welds the two -- drift means formatting for a pane you did not get.
BODY_PADDING_ROWS = 2
CONTENT_ROWS = bigtext.HEIGHT + 2      # banner, the name, the clock line
STATUS_ROWS = BODY_PADDING_ROWS + CONTENT_ROWS

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


def banner_text(icao: str, width: int) -> str:
    """The code as block capitals, or "" when `width` cannot hold them.

    Empty rather than clipped: tmux cuts without an ellipsis, and half a
    letter reads as a different letter. The caller treats "" as "no banner"
    and puts the code back on the detail line, which is exactly what the
    pane showed before the banner existed.
    """
    if not icao or bigtext.width(icao) > width:
        return ""
    return "\n".join(bigtext.render(icao))


def detail_line(
    airport: Airport | None, icao: str, width: int, banner: str
) -> str:
    """The line under the banner.

    With a banner the code is already the largest thing in the pane, so
    this is the name alone; without one it falls back to `airport_line`
    and carries the code itself. An unknown code leaves it blank -- the
    banner spells the code, and there is no name to add.
    """
    if not banner:
        return airport_line(airport, icao, width)
    if airport is None:
        return fit("", width)
    return fit(airport.name, width)


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


def content_width(widget: Widget) -> int:
    """How wide `widget` really is, or CONTENT_WIDTH before it knows.

    The first paint happens in on_mount, which runs before the first
    layout: every widget reports width 0 there, and formatting to 0 would
    blank the pane for the first frame. So 0 means "not laid out yet" and
    the design width stands in until the real one arrives, one tick later.

    There is deliberately no on_resize handler feeding this. Inside
    on_resize the children still report 0 -- the event arrives before they
    are laid out -- so it would have to defer to call_after_refresh, and
    a mouse drag delivers a storm of resize events, each of which would
    then re-run the resolver and its file read. The periodic tick already
    repaints at the new width within TICK_SECONDS, which for a surface
    whose finest reading is minutes is soon enough.
    """
    return widget.size.width or CONTENT_WIDTH


def now_pair() -> tuple[datetime, datetime]:
    """UTC and local from one instant, so the two clocks cannot disagree."""
    utc = datetime.now(timezone.utc)
    return utc, utc.astimezone()


def open_picker(run: Callable[..., object] = subprocess.run) -> None:
    # No check=True: a popup that runs but exits non-zero fails silently.
    # Accepted tradeoff -- the caller already swallows every exception this
    # can raise (see StatusPane.on_click), so a raised CalledProcessError
    # would buy no more feedback than this does.
    run(("tmux", *PICKER_POPUP))


class StatusPane(App[None]):
    """The four-row pane itself.

    `resolver` must accept a `known` keyword -- tick() always passes one,
    because the pane owns the dataset the resolver validates against (see
    _known). A zero-argument resolver raises TypeError on every tick,
    including on_mount's first one, so line 1 is never painted at all and
    the pane shows a permanently blank airport line rather than a stale
    one. The guard in tick() catches it, by design: its whole job is that
    this pane never dies. Only the tests pass anything but the default
    here, so the contract is documented rather than enforced.
    """

    CSS = f"""
    Screen {{ background: $surface; }}
    #body {{ padding: 1; }}
    #banner {{ height: {bigtext.HEIGHT}; }}
    #airport {{ height: 1; }}
    #line2 {{ height: 1; }}
    #clock {{ width: auto; }}
    #hint {{ width: 1fr; text-align: right; color: $text-muted; }}
    #hint:hover {{ color: $text; }}
    """

    def __init__(
        self,
        *,
        resolver: Callable[..., str] = current_icao,
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

    def _known(self, code: str) -> bool:
        """Is `code` in the dataset this pane loaded?

        Passed to the resolver on every tick, because the resolver's answer
        depends on it: an ICAO the dataset does not have is skipped in
        favour of the next source. bin/kcgx's `resolve` mode has always
        passed this; the pane did not, and the two disagreed. With ZZZZ
        remembered, the launcher pointed adsb-tui and squelch at the
        fallback airport while the pane -- the one surface whose whole job
        is to say which airport you are hearing -- displayed ZZZZ.

        Calling one function two different ways is a second spelling of the
        resolution order, which is exactly what current_icao() exists to
        prevent. The predicate has to be supplied by the caller rather than
        wired in, because state.py deliberately knows nothing about the
        dataset -- so it is supplied here, by the caller that loaded it.
        """
        return find(code, self._airports) is not None

    def compose(self) -> ComposeResult:
        with Vertical(id="body"):
            yield Static("", id="banner")
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

        The two halves are wrapped independently: a resolver that raises (an
        unreadable or undecodable state file, say) must not skip the clock
        update, and a clock that raises must not skip the airport update.
        Either way `tick()` itself must never raise -- that is the one
        guarantee the pane exists to make -- so each half leaves its own
        last-known value on screen rather than propagating.

        Both halves lay out against the width the widget *actually has*,
        not CONTENT_WIDTH. Every splitter in this cockpit is drag-resizable
        -- that is what kcgx.tmux.conf exists for -- so the constant is a
        starting position, not a constraint. Formatting to it regardless
        meant a narrowed pane cut line 1 with no ellipsis (tmux clips; only
        `fit` can put the "…" there) and clipped the hint mid-string
        instead of degrading to "▾", which made PICKER_HINT_SHORT
        unreachable at runtime however narrow the pane got. A widened one
        stopped line 1 at 46 columns while line 2 stretched.

        Asking the widget being written to, rather than the screen, is what
        keeps this honest: it already accounts for #body's padding, and it
        costs no query that was not being made anyway.
        """
        try:
            icao = self._resolver(known=self._known)
            airport = find(icao, self._airports)
        except Exception:
            pass
        else:
            line1 = self.query_one("#airport", Static)
            banner = self.query_one("#banner", Static)
            drawn = banner_text(icao, content_width(banner))
            banner.update(drawn, layout=False)
            line1.update(
                detail_line(airport, icao, content_width(line1), drawn),
                layout=False,
            )

        try:
            utc, local = self._now()
            clocks = clock_text(utc, local)
        except Exception:
            pass
        else:
            available = content_width(self.query_one("#line2")) - len(clocks) - 1
            self.query_one("#clock", Static).update(clocks, layout=False)
            self.query_one("#hint", Static).update(
                hint_for_width(available), layout=False
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
