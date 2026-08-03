"""The config overlay: what the audio path is set to, and what is honoured.

Two settings are adjustable here — master volume and the gate — because
those are the two the mixer can actually change while it is running. The
rest are shown with an honesty marker instead:

    live   read from the config and actually applied
    inert  read from the config and not yet wired to the audio path
    fixed  compiled in; not settable at all

Five compressor and ambient keys are `inert`: `Config` parses them and
`Channel` builds its `Compressor` from the `dsp.py` defaults regardless.
A modal that let you edit those would be a modal that lied, so it does not.

Adjustments apply to the running session only. Nothing here writes to
`squelch.toml` -- editing a user's config file is not something a volume
key should do behind their back.

The table is a pure function of a Config plus the mixer's live gate, so the
whole thing can be checked without a running app -- the same split
`rows.py` uses.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static

from squelch import dsp
from squelch.config import Config
from squelch.mixer import AMBIENT_GAIN_DB

LIVE = "live"
INERT = "inert"
FIXED = "fixed"
# Adjustable rows carry no marker: the value moving under the arrow keys
# says more than a word would.
ADJUSTABLE = ""

# The overlay is 44 wide with a solid border *and* `padding: 0 1`, so the
# usable width is 44 - 2 (border) - 2 (padding) = 40. Getting this wrong
# does not clip, it wraps: every row becomes two, and the table turns into
# a column of orphaned status words.
WIDTH = 44
CONTENT_WIDTH = WIDTH - 4
LABEL_WIDTH = 21
VALUE_WIDTH = 12

VOLUME_KEY = "master_volume"
GATE_KEY = "gate_dbfs"

# Step, floor, and ceiling for each adjustable setting.
VOLUME_STEP = 0.05
GATE_STEP = 1.0
GATE_FLOOR = -96.0
GATE_CEILING = 0.0


@dataclass(frozen=True)
class Setting:
    label: str
    value: str
    status: str
    key: str | None = None

    @property
    def adjustable(self) -> bool:
        return self.key is not None


@dataclass(frozen=True)
class Group:
    title: str
    settings: tuple[Setting, ...]


def config_rows(config: Config, *, gate_dbfs: float | None = None) -> list[Group]:
    """Every audio setting the design defines, grouped by what it shapes.

    `gate_dbfs` is the mixer's live value when there is one; without a
    mixer the config's own value is shown, which is what it would start on.
    """
    gate = config.gate_dbfs if gate_dbfs is None else gate_dbfs
    return [
        Group(
            "Output",
            (
                Setting(
                    "Master volume",
                    f"{round(config.master_volume * 100)}%",
                    ADJUSTABLE,
                    key=VOLUME_KEY,
                ),
            ),
        ),
        Group(
            "Chatter",
            (
                Setting("Gate", f"{gate:.1f} dBFS", ADJUSTABLE, key=GATE_KEY),
                Setting(
                    "Chatter threshold",
                    f"{config.activity_threshold_dbfs:.1f} dBFS",
                    LIVE,
                ),
                Setting(
                    "Comp threshold",
                    f"{config.compressor_threshold_dbfs:.1f} dBFS",
                    INERT,
                ),
                Setting("Comp ratio", f"{config.compressor_ratio:.1f}:1", INERT),
                Setting("Comp makeup", f"+{config.compressor_makeup_db:.1f} dB", INERT),
                Setting(
                    "Comp range limit", f"{config.compressor_range_db:.1f} dB", INERT
                ),
            ),
        ),
        Group(
            "Ambient",
            (
                # Both, because this is the clearest illustration of what
                # `inert` means: the first is what squelch.toml asked for,
                # the second is what the mixer is actually running.
                Setting("Bus level (set)", f"{config.ambient_gain_db:.1f} dB", INERT),
                Setting("Bus level (in use)", f"{AMBIENT_GAIN_DB:.1f} dB", FIXED),
                Setting("Reverb decay", f"{dsp.RT60_S * 1000:.0f} ms", FIXED),
                Setting("Reverb roll-off", f"{dsp.LOWPASS_HZ:.0f} Hz", FIXED),
            ),
        ),
    ]


def flatten(groups: list[Group]) -> list[Setting]:
    return [setting for group in groups for setting in group.settings]


def adjustable_settings(groups: list[Group]) -> list[Setting]:
    return [setting for setting in flatten(groups) if setting.adjustable]


def adjust(
    config: Config, key: str, delta: int, *, gate_dbfs: float
) -> tuple[Config, float]:
    """Move one setting by `delta` steps.

    Returns `(config, gate_dbfs)`: the gate lives on the mixer rather than
    only in the config, so a caller has to be told both. Clamped here
    rather than in the widget, so the bounds are testable without an app.
    """
    if key == VOLUME_KEY:
        volume = min(1.0, max(0.0, config.master_volume + delta * VOLUME_STEP))
        # Snapped back to the step, or repeated presses drift into
        # 0.30000000000000004 and the readout flickers between 30% and 31%.
        volume = round(volume / VOLUME_STEP) * VOLUME_STEP
        return replace(config, master_volume=volume), gate_dbfs
    if key == GATE_KEY:
        moved = gate_dbfs + delta * GATE_STEP
        return config, min(GATE_CEILING, max(GATE_FLOOR, moved))
    return config, gate_dbfs


def row_text(setting: Setting, *, selected: bool = False) -> str:
    """One line of the table, exactly CONTENT_WIDTH cells."""
    marker = "›" if selected else " "
    label = setting.label[: LABEL_WIDTH - 1].ljust(LABEL_WIDTH - 1)
    value = setting.value[:VALUE_WIDTH].rjust(VALUE_WIDTH)
    trailing = "◂ ▸" if setting.adjustable and selected else setting.status
    line = f"{marker}{label}{value} {trailing}"
    return line[:CONTENT_WIDTH].ljust(CONTENT_WIDTH)


def group_heading(title: str) -> str:
    return f" {title}".ljust(CONTENT_WIDTH)


class ConfigScreen(ModalScreen):
    """What the audio path is set to. See the module docstring."""

    BINDINGS = [
        Binding("escape", "close", "close", show=False),
        Binding("c", "close", "close", show=False),
        # priority=True for the same reason the airport picker uses it:
        # nothing in this DOM competes for the arrows today, and a
        # focusable container quietly eating them is how selection froze in
        # the feed stack.
        Binding("up", "move(-1)", "up", show=False, priority=True),
        Binding("down", "move(1)", "down", show=False, priority=True),
        Binding("left", "adjust(-1)", "quieter", show=False, priority=True),
        Binding("right", "adjust(1)", "louder", show=False, priority=True),
    ]

    def __init__(self, config: Config, *, mixer=None) -> None:
        super().__init__()
        self._mixer = mixer
        # Both live values come from the mixer when there is one, not from
        # the config: the overlay has to show what is running, and the two
        # diverge as soon as anyone adjusts anything. Seeding the gate from
        # the mixer but the volume from the config made every gate change
        # also write the config's stale volume back over the live one.
        self._gate = config.gate_dbfs if mixer is None else mixer.gate_dbfs
        volume = config.master_volume if mixer is None else mixer.volume
        self._config = replace(config, master_volume=volume)
        self._selected = 0
        self._body: Static | None = None

    @property
    def groups(self) -> list[Group]:
        return config_rows(self._config, gate_dbfs=self._gate)

    @property
    def selected(self) -> Setting:
        return adjustable_settings(self.groups)[self._selected]

    def compose(self) -> ComposeResult:
        # Built with its content rather than filled in on_mount: a Static
        # constructed empty has no visual and raises out of the compositor
        # before on_mount ever runs.
        yield Static(self._body_text(), id="configbox", markup=False)

    def on_mount(self) -> None:
        self._body = self.query_one("#configbox", Static)

    def _refresh_body(self) -> None:
        # Not `_render`: Textual's Widget._render() is internal API that
        # returns the widget's visual, and overriding it with something
        # that returns None crashes the compositor with a bare
        # "'NoneType' object has no attribute 'render_strips'".
        if self._body is not None:
            self._body.update(self._body_text())

    def _body_text(self) -> str:
        chosen = self.selected
        lines: list[str] = []
        for group in self.groups:
            if lines:
                lines.append("")
            lines.append(group_heading(group.title))
            for setting in group.settings:
                lines.append(row_text(setting, selected=setting == chosen))
        lines += [
            "",
            " ◂ ▸ adjust    inert = not yet applied".ljust(CONTENT_WIDTH),
            " esc close     fixed = not settable".ljust(CONTENT_WIDTH),
        ]
        return "\n".join(lines)

    def action_move(self, delta: int) -> None:
        count = len(adjustable_settings(self.groups))
        self._selected = max(0, min(count - 1, self._selected + delta))
        self._refresh_body()

    def action_adjust(self, delta: int) -> None:
        self._config, self._gate = adjust(
            self._config, self.selected.key, delta, gate_dbfs=self._gate
        )
        self._apply()
        self._refresh_body()

    def _apply(self) -> None:
        """Push the new values at the mixer, if there is one.

        Guarded: a mixer whose device never opened is still a mixer, and a
        config overlay must not be the thing that takes the pane down.
        """
        if self._mixer is None:
            return
        try:
            self._mixer.volume = self._config.master_volume
            self._mixer.set_gate(self._gate)
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss(None)
