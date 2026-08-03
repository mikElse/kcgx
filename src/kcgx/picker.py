"""The airport picker: type, arrow, enter.

Sized for `tmux display-popup -w 64 -h 20`, which is where it actually
runs. The `fit` helper is deliberately a local copy rather than an import
from squelch.app -- kcgx drives squelch, it does not depend on squelch's
UI internals.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from kcgx.airports import Airport, search

class Quit:
    """The user asked to shut the whole cockpit down, not just this popup.

    A distinct sentinel rather than a second `None`: cancelling and quitting
    are opposite intentions, and the caller turns them into different exit
    codes.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "QUIT"


QUIT = Quit()

POPUP_WIDTH = 64
POPUP_HEIGHT = 20

# Popup width less the border tmux draws and our own padding.
ROW_WIDTH = POPUP_WIDTH - 6
CODE_WIDTH = 4
PLACE_WIDTH = 18


def fit(text: str, width: int) -> str:
    """Pad to `width`, or truncate with a visible ellipsis."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def row_text(airport: Airport, width: int) -> str:
    """One line: code, name, place -- name yields the space."""
    name_width = max(0, width - CODE_WIDTH - PLACE_WIDTH - 2)
    return (
        f"{fit(airport.icao, CODE_WIDTH)} "
        f"{fit(airport.name, name_width)} "
        f"{fit(airport.where, PLACE_WIDTH)}"
    )


class AirportPicker(App[Airport | Quit | None]):
    CSS = """
    Screen { background: $surface; }
    #query { border: none; padding: 0 1; height: 3; }
    #results { border: none; padding: 0 1; height: 1fr; }
    #hint { color: $text-muted; padding: 0 1; height: 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        # ctrl+q, not q. The Input below keeps focus so that typing always
        # filters, and it consumes printable keys before an App binding can
        # see them -- a bare `q` binding never fires at all, at any
        # priority. Forcing one through would also cost the 50 airports
        # whose names start with the letter: Quito, Queenstown, Qingdao.
        Binding("ctrl+q", "quit_all", "quit", show=False),
        # The input keeps focus so typing always filters, and up/down are
        # handled here rather than by the list. priority=True is defensive:
        # in Textual 8.2.8 nothing in this DOM competes for these keys, but
        # a focusable scroll container quietly eating arrow keys is exactly
        # how selection froze in the sibling squelch app.
        Binding("down", "move(1)", "down", show=False, priority=True),
        Binding("up", "move(-1)", "up", show=False, priority=True),
    ]

    def __init__(self, airports: list[Airport], *, initial: str = "") -> None:
        super().__init__()
        self._airports = airports
        self._initial = initial
        self._matches: list[Airport] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(placeholder="airport, city, or code", id="query")
            yield OptionList(id="results")
            yield Static("↑↓ select   ↵ go   esc cancel   ^q quit", id="hint")

    def on_mount(self) -> None:
        query = self.query_one("#query", Input)
        query.value = self._initial
        query.focus()
        self._refilter(self._initial)

    def _refilter(self, query: str) -> None:
        self._matches = search(query, self._airports)
        results = self.query_one("#results", OptionList)
        results.clear_options()
        if not self._matches:
            results.add_option(Option("no airports match", disabled=True))
            return
        results.add_options(
            [Option(row_text(a, ROW_WIDTH), id=a.icao) for a in self._matches]
        )
        results.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refilter(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._choose()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        self._choose(event.option_index)

    # The two range guards below are backstops, not the mechanism. In
    # Textual 8.2.8, OptionList.validate_highlighted already clamps
    # `highlighted` into [0, len(options) - 1] before either of these sees
    # it, so *neither* can be reached by any sequence of keystrokes and no
    # behavioural test can tell them apart -- deleting both leaves the whole
    # suite green. They stay because they are cheap and because
    # `self._matches` and the OptionList's own options are two lists kept in
    # step by hand in _refilter: Textual validates against its list, we index
    # into ours. test_the_highlight_stops_at_both_ends_instead_of_falling_off
    # pins the behaviour, whoever ends up enforcing it.

    def _choose(self, index: int | None = None) -> None:
        if not self._matches:
            return
        if index is None:
            index = self.query_one("#results", OptionList).highlighted
        if index is None or not (0 <= index < len(self._matches)):
            return
        self.exit(self._matches[index])

    def action_move(self, delta: int) -> None:
        if not self._matches:
            return
        results = self.query_one("#results", OptionList)
        current = results.highlighted or 0
        results.highlighted = max(0, min(len(self._matches) - 1, current + delta))

    def action_cancel(self) -> None:
        self.exit(None)

    def action_quit_all(self) -> None:
        self.exit(QUIT)


def pick(
    airports: list[Airport], *, initial: str = ""
) -> Airport | Quit | None:
    """Run the picker: the chosen airport, None if cancelled, QUIT if the
    user asked to shut the cockpit down."""
    return AirportPicker(airports, initial=initial).run()
