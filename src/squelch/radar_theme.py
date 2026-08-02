"""Following the radar pane's theme, one `capture-pane` at a time.

Every failure here is silent by design. A pane that has been closed, a tmux
that is not running, a capture that times out -- all of them mean "keep the
theme you have". Warning about any of them would put a message in the log
every three seconds for the rest of the session.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

from squelch.themes import THEME_NAMES, theme_for

POLL_SECONDS = 3.0
# Short, because a hung tmux must not accumulate worker threads over a
# multi-hour session.
CAPTURE_TIMEOUT = 2.0
PANE_ENV = "KCGX_RADAR_PANE"
DEFAULT_THEME = "default"


def capture_command(pane: str) -> list[str]:
    # -e keeps the escape sequences, which are the entire point; -p writes
    # to stdout rather than a paste buffer.
    return ["tmux", "capture-pane", "-e", "-p", "-t", pane]


def adsb_config_path(environ) -> Path:
    root = environ.get("XDG_CONFIG_HOME")
    base = Path(root) if root else Path.home() / ".config"
    return base / "ads-b-tui" / "adsb-tui.toml"


def configured_theme(path: Path) -> str | None:
    """The theme adsb-tui launched with, if the config names a known one."""
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, ValueError):
        return None
    name = data.get("theme")
    return name if name in THEME_NAMES else None


class RadarTheme:
    def __init__(
        self,
        *,
        environ=None,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        config_path: Path | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._runner = runner
        self._config_path = config_path
        self._current: str | None = None

    def initial(self) -> str:
        """The theme to start on: sampled, else configured, else default."""
        sampled = self._sample()
        if sampled is not None:
            self._current = sampled
            return sampled
        path = self._config_path
        if path is None:
            path = adsb_config_path(self._environ)
        configured = configured_theme(path)
        self._current = configured or DEFAULT_THEME
        return self._current

    def poll(self) -> str | None:
        """The new theme name, or `None` if nothing changed or nothing could
        be read."""
        sampled = self._sample()
        if sampled is None or sampled == self._current:
            return None
        self._current = sampled
        return sampled

    def _sample(self) -> str | None:
        pane = self._environ.get(PANE_ENV)
        if not pane:
            return None
        try:
            result = self._runner(
                capture_command(pane),
                capture_output=True,
                text=True,
                timeout=CAPTURE_TIMEOUT,
                check=True,
            )
        except Exception:
            # tmux missing, pane gone, non-zero exit, timeout. All of them
            # mean the same thing to us: keep what we have.
            return None
        return theme_for(result.stdout or "")
