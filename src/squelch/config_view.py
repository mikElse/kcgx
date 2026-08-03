"""The config overlay: what the audio path is set to, and what is honoured.

Read-only on purpose. Five of these keys are read from `squelch.toml` into
`Config` and then consumed by nothing -- the mixer builds its compressor
from the module defaults in `dsp.py` and its ambient gain from a module
constant. A modal that let you edit them would be a modal that lied, so
each row says which of three states it is in instead:

    live   read from the config and actually applied
    inert  read from the config and not yet wired to the audio path
    fixed  compiled in; not configurable at all

The rows are a pure function of a Config so the whole table can be checked
without a running app, which is the same split `rows.py` uses.
"""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from squelch import dsp
from squelch.config import Config
from squelch.mixer import AMBIENT_GAIN_DB

LIVE = "live"
INERT = "inert"
FIXED = "fixed"

# The overlay is 44 wide with a solid border *and* `padding: 0 1`, so the
# usable width is 44 - 2 (border) - 2 (padding) = 40. Getting this wrong
# does not clip, it wraps: every row becomes two, and the table turns into
# a column of orphaned status words.
WIDTH = 44
CONTENT_WIDTH = WIDTH - 4
LABEL_WIDTH = 21
VALUE_WIDTH = 12


@dataclass(frozen=True)
class Setting:
    label: str
    value: str
    status: str


def config_rows(config: Config) -> list[Setting]:
    """Every audio setting the spec defines, with its honesty marker."""
    return [
        Setting("Chatter threshold", f"{config.activity_threshold_dbfs:.1f} dBFS", LIVE),
        Setting("Gate", f"{dsp.GATE_OPEN_DBFS:.1f} dBFS", FIXED),
        Setting(
            "Comp threshold", f"{config.compressor_threshold_dbfs:.1f} dBFS", INERT
        ),
        Setting("Comp ratio", f"{config.compressor_ratio:.1f}:1", INERT),
        Setting("Comp makeup", f"+{config.compressor_makeup_db:.1f} dB", INERT),
        Setting("Comp range limit", f"{config.compressor_range_db:.1f} dB", INERT),
        # Both, because this is the clearest illustration of what `inert`
        # means: the first is what squelch.toml asked for, the second is
        # what the mixer is actually running.
        Setting("Ambient bus (set)", f"{config.ambient_gain_db:.1f} dB", INERT),
        Setting("Ambient bus (in use)", f"{AMBIENT_GAIN_DB:.1f} dB", FIXED),
        Setting("Reverb decay", f"{dsp.RT60_S * 1000:.0f} ms", FIXED),
        Setting("Reverb roll-off", f"{dsp.LOWPASS_HZ:.0f} Hz", FIXED),
    ]


def row_text(setting: Setting) -> str:
    """One line of the table, exactly CONTENT_WIDTH cells."""
    label = setting.label[:LABEL_WIDTH].ljust(LABEL_WIDTH)
    value = setting.value[:VALUE_WIDTH].rjust(VALUE_WIDTH)
    line = f"{label}{value} {setting.status}"
    return line[:CONTENT_WIDTH].ljust(CONTENT_WIDTH)


class ConfigScreen(ModalScreen):
    """What the audio path is set to. Read-only -- see the module docstring."""

    BINDINGS = [("escape", "close", "Close"), ("c", "close", "Close")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        # markup=False throughout: these strings are formatted numbers, but
        # the labels sit beside feed-derived text elsewhere and the habit is
        # worth keeping uniform.
        yield Static(
            "\n".join(
                [
                    " Audio".ljust(CONTENT_WIDTH),
                    "",
                    *(row_text(s) for s in config_rows(self._config)),
                    "",
                    "inert = set here, not yet applied".ljust(CONTENT_WIDTH),
                    "fixed = compiled in, not settable".ljust(CONTENT_WIDTH),
                    "",
                    " esc close".ljust(CONTENT_WIDTH),
                ]
            ),
            id="configbox",
            markup=False,
        )

    def action_close(self) -> None:
        self.dismiss(None)
