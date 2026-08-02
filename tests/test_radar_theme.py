"""Following the radar pane's theme.

Nothing here runs tmux or adsb-tui: the subprocess runner is injected and
the config path is a tmp_path. The failure modes matter more than the happy
path -- a pane that has been closed must not warn every three seconds for
the rest of a multi-hour session.
"""

import subprocess

from squelch.radar_theme import (
    CAPTURE_TIMEOUT,
    PANE_ENV,
    RadarTheme,
    adsb_config_path,
    capture_command,
    configured_theme,
)

ESC = "\x1b"


def paint(r, g, b, n=10):
    return f"{ESC}[48;2;{r};{g};{b}mXX" * n


AMBER = paint(24, 18, 10)
OCEAN = paint(10, 18, 24)


class FakeRunner:
    """Stands in for subprocess.run."""

    def __init__(self, *results):
        self._results = list(results)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        result = self._results.pop(0) if self._results else self._results
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(argv, 0, stdout=result, stderr="")


def theme(runner, environ=None, **kwargs):
    return RadarTheme(
        environ=environ if environ is not None else {PANE_ENV: "%3"},
        runner=runner,
        **kwargs,
    )


# -- the command -----------------------------------------------------------


def test_the_capture_command_targets_the_pane_and_keeps_escapes():
    argv = capture_command("%3")
    assert argv[:2] == ["tmux", "capture-pane"]
    assert "-e" in argv, "without -e there are no colours to read"
    assert "-p" in argv
    assert argv[-2:] == ["-t", "%3"]


# -- polling ---------------------------------------------------------------


def test_a_capture_identifies_the_theme():
    assert theme(FakeRunner(AMBER)).poll() == "amber"


def test_the_same_theme_twice_reports_a_change_only_once():
    t = theme(FakeRunner(AMBER, AMBER))
    assert t.poll() == "amber"
    assert t.poll() is None, "no change, nothing to apply"


def test_a_changed_theme_is_reported():
    t = theme(FakeRunner(AMBER, OCEAN))
    assert t.poll() == "amber"
    assert t.poll() == "ocean"


def test_the_subprocess_gets_a_timeout():
    runner = FakeRunner(AMBER)
    theme(runner).poll()
    assert runner.calls[0][1]["timeout"] == CAPTURE_TIMEOUT


# -- failure ---------------------------------------------------------------


def test_a_timeout_leaves_the_theme_alone():
    t = theme(FakeRunner(AMBER, subprocess.TimeoutExpired("tmux", 2.0)))
    assert t.poll() == "amber"
    assert t.poll() is None


def test_a_missing_tmux_leaves_the_theme_alone():
    assert theme(FakeRunner(FileNotFoundError("tmux"))).poll() is None


def test_a_closed_pane_leaves_the_theme_alone():
    assert theme(FakeRunner(subprocess.CalledProcessError(1, "tmux"))).poll() is None


def test_an_unrecognised_background_leaves_the_theme_alone():
    t = theme(FakeRunner(AMBER, paint(123, 45, 67)))
    assert t.poll() == "amber"
    assert t.poll() is None, "an unknown fill is not a reason to restyle"


def test_polling_without_a_pane_id_does_nothing():
    runner = FakeRunner(AMBER)
    assert theme(runner, environ={}).poll() is None
    assert runner.calls == [], "no pane means no subprocess at all"


# -- the config fallback ---------------------------------------------------


def test_the_config_path_honours_xdg(tmp_path):
    path = adsb_config_path({"XDG_CONFIG_HOME": str(tmp_path)})
    assert path == tmp_path / "ads-b-tui" / "adsb-tui.toml"


def test_the_config_path_falls_back_to_dot_config():
    path = adsb_config_path({})
    assert path.parts[-3:] == (".config", "ads-b-tui", "adsb-tui.toml")


def test_the_configured_theme_is_read(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text('layout = "radar"\ntheme = "ocean"\n')
    assert configured_theme(path) == "ocean"


def test_a_missing_config_yields_nothing(tmp_path):
    assert configured_theme(tmp_path / "nope.toml") is None


def test_an_unparseable_config_yields_nothing(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text("this is not = = toml")
    assert configured_theme(path) is None


def test_an_unknown_configured_theme_yields_nothing(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text('theme = "chartreuse"\n')
    assert configured_theme(path) is None


# -- the fallback chain ----------------------------------------------------


def test_initial_prefers_the_live_pane(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text('theme = "ocean"\n')
    t = theme(FakeRunner(AMBER), config_path=path)
    assert t.initial() == "amber"


def test_initial_falls_back_to_the_config(tmp_path):
    path = tmp_path / "adsb-tui.toml"
    path.write_text('theme = "ocean"\n')
    t = theme(FakeRunner(FileNotFoundError("tmux")), config_path=path)
    assert t.initial() == "ocean"


def test_initial_falls_back_to_default(tmp_path):
    t = theme(
        FakeRunner(FileNotFoundError("tmux")),
        config_path=tmp_path / "nope.toml",
    )
    assert t.initial() == "default"


def test_initial_outside_the_cockpit_still_reads_the_config(tmp_path):
    """Standalone squelch themes statically rather than not at all."""
    path = tmp_path / "adsb-tui.toml"
    path.write_text('theme = "matrix"\n')
    t = theme(FakeRunner(), environ={}, config_path=path)
    assert t.initial() == "matrix"
