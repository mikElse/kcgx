"""Tests for the wiring in `__main__`.

`main()` is where every module is joined up, and it runs the pipeline on a
daemon thread where an unhandled exception is invisible. Nothing here
touches the network, ffmpeg, a real model, or an audio device: the app, the
runner, and every pipeline collaborator are injected.
"""

import threading

import pytest

from squelch.__main__ import (
    FFMPEG_MISSING,
    MODEL_LOADING,
    build_pipeline_runner,
    feed_selection_hint,
    main,
    parse_args,
    safe_call,
    try_start,
)
from squelch.app import SquelchApp
from squelch.asr import Transcript
from squelch.config import Config
from squelch.feeds import Feed


@pytest.fixture(autouse=True)
def no_user_config(tmp_path, monkeypatch):
    """main() reads the real ~/.config path; keep these tests hermetic."""
    import squelch.config as config_module

    monkeypatch.setattr(config_module, "DEFAULT_PATH", tmp_path / "absent.toml")


def test_defaults_come_from_config():
    args = parse_args([])
    assert args.feed is None
    assert args.icao is None


def test_feed_override():
    args = parse_args(["--feed", "ksea_twr"])
    assert args.feed == "ksea_twr"


def test_icao_override():
    args = parse_args(["--icao", "KSEA"])
    assert args.icao == "KSEA"


def test_try_start_reports_success_and_stays_quiet():
    warnings = []
    assert try_start(lambda: None, warnings.append, "boom") is True
    assert warnings == []


def test_try_start_degrades_instead_of_raising():
    """A model that will not load must not take the app down."""
    warnings = []

    def explode():
        raise RuntimeError("no such model")

    assert try_start(explode, warnings.append, "transcription unavailable") is False
    assert warnings == ["transcription unavailable"]


# -- safe_call -------------------------------------------------------------


def test_safe_call_swallows_app_not_running():
    """The guard that used to be unreachable in a test.

    While the pipeline thread was started *before* App.run(), every warn()
    hit this path and was silently dropped; now that the thread starts from
    on_mount the path is only reached during teardown -- but it must still
    never raise back onto the pipeline thread.
    """
    app = SquelchApp(Config(), feed_label="Portland Tower")
    with pytest.raises(RuntimeError):
        app.call_from_thread(app.warn, "direct call raises")
    safe_call(app, app.warn, "but safe_call does not")


# -- build_pipeline_runner -------------------------------------------------


class Recorder:
    def __init__(self):
        self.warnings = []
        self.states = []

    @property
    def joined(self):
        return "\n".join(self.warnings)


class StubTranscriber:
    def __init__(self):
        self.loaded = False

    def load(self):
        self.loaded = True

    def transcribe(self, pcm):
        return Transcript(text="", avg_logprob=0.0)


class StubPlayer:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.muted = False

    def start(self):
        self.started = True

    def write(self, pcm):
        pass

    def stop(self):
        self.stopped = True


def make_runner(rec, **overrides):
    kwargs = dict(
        warn=rec.warnings.append,
        set_state=rec.states.append,
        player=StubPlayer(),
        transcriber=StubTranscriber(),
        events=None,
        resolve=lambda ident: "https://example.test/stream",
        reader_factory=lambda url: object(),
        segmenter_factory=lambda **kw: object(),
        pipeline_factory=lambda *a, **kw: _NoopPipeline(),
        which=lambda name: f"/usr/bin/{name}",
    )
    kwargs.update(overrides)
    return build_pipeline_runner(overrides.pop("config", Config()), **kwargs)


class _NoopPipeline:
    def run(self):
        return None


def test_runner_reports_a_missing_ffmpeg_with_an_actionable_message():
    """A very plausible first-run failure that used to be a silent death.

    `StreamReader.frames()` spawns ffmpeg lazily, so a missing binary raised
    FileNotFoundError deep inside the pipeline thread; the thread died and
    the pane sat at its last state with an empty transcript forever.
    """
    rec = Recorder()
    make_runner(rec, which=lambda name: None)()
    assert FFMPEG_MISSING in rec.warnings
    assert "brew install ffmpeg" in rec.joined, "must say how to fix it"
    assert rec.states == ["offline"], "the header must not keep claiming LIVE"


def test_runner_survives_an_invalid_vad_mode():
    """`webrtcvad.Vad(7)` raises ValueError; that used to kill the thread."""

    def bad_segmenter(**kwargs):
        raise ValueError("7 is an invalid mode, must be 0-3")

    rec = Recorder()
    make_runner(rec, segmenter_factory=bad_segmenter)()
    assert "invalid mode" in rec.joined
    assert rec.states == ["offline"]


def test_runner_survives_a_reader_that_cannot_start():
    """FileNotFoundError from Popen, OSError from a broken pipe: same fate."""

    class ExplodingPipeline:
        def run(self):
            raise FileNotFoundError(2, "No such file or directory: 'ffmpeg'")

    rec = Recorder()
    make_runner(rec, pipeline_factory=lambda *a, **kw: ExplodingPipeline())()
    assert "ffmpeg" in rec.joined
    assert rec.states == ["offline"]


def test_runner_survives_a_mid_run_read_error():
    class FailingPipeline:
        def run(self):
            raise OSError("stream closed by peer")

    rec = Recorder()
    make_runner(rec, pipeline_factory=lambda *a, **kw: FailingPipeline())()
    assert "stream closed by peer" in rec.joined
    assert rec.states == ["offline"]


def test_runner_announces_the_model_download_before_loading_it():
    rec = Recorder()
    transcriber = StubTranscriber()
    make_runner(rec, transcriber=transcriber)()
    assert rec.warnings[0] == MODEL_LOADING
    assert transcriber.loaded


def test_runner_reports_a_feed_that_cannot_be_resolved():
    def boom(ident):
        raise RuntimeError("404")

    rec = Recorder()
    make_runner(rec, resolve=boom)()
    assert "could not resolve feed" in rec.joined
    assert rec.states == ["offline"]


def test_runner_degrades_to_audio_only_when_the_model_will_not_load():
    class BrokenTranscriber(StubTranscriber):
        def load(self):
            raise RuntimeError("no such model")

    rec = Recorder()
    seen = {}
    make_runner(
        rec,
        transcriber=BrokenTranscriber(),
        pipeline_factory=lambda reader, seg, transcriber, player, events: (
            seen.__setitem__("transcriber", transcriber) or _NoopPipeline()
        ),
    )()
    assert "audio only" in rec.joined
    assert seen["transcriber"].transcribe(b"") == Transcript(text="", avg_logprob=0.0)
    assert rec.states == []


# -- main() ----------------------------------------------------------------


class FakeApp:
    """A stand-in for SquelchApp that never touches a terminal."""

    def __init__(self, config, *, feed_label, feed_loader=None, run_error=None):
        self.config = config
        self.feed_label = feed_label
        self.feed_loader = feed_loader
        self.run_error = run_error
        self.warnings = []
        self.states = []
        self.ran = False
        self.on_mute_change = lambda muted: None
        self.on_feed_selected = lambda feed: None
        self.on_start = lambda: None

    def run(self):
        self.ran = True
        # Textual invokes on_mount only once the app is running; this is the
        # only point at which call_from_thread would have worked.
        self.on_start()
        if self.run_error is not None:
            raise self.run_error

    def call_from_thread(self, func, *args):
        return func(*args)

    def warn(self, message):
        self.warnings.append(message)

    def set_state(self, state):
        self.states.append(state)


def run_main(*, run_error=None, argv=None):
    """Run main() with a fake app and a runner that just records."""
    started = threading.Event()
    holder = {}

    def app_factory(config, **kwargs):
        app = FakeApp(config, run_error=run_error, **kwargs)
        holder["app"] = app
        return app

    def runner_factory(config, **kwargs):
        holder["runner_kwargs"] = kwargs

        def run():
            holder["ran_while"] = holder["app"].ran
            started.set()

        return run

    holder["exit"] = main(argv or [], app_factory=app_factory,
                          runner_factory=runner_factory)
    assert started.wait(timeout=5), "the pipeline runner never ran"
    return holder


def test_main_starts_the_pipeline_only_once_the_app_is_running():
    """The pipeline thread must be started from on_mount, not before run().

    Regression test: `main()` started the thread and *then* called
    `app.run()`. The runner's first act is a warn(), which reached
    `call_from_thread` before the loop existed, raised "App is not running"
    and was swallowed -- so on a first run the user watched a blank pane
    falsely reading "● LIVE" for the minutes it takes to download 1.5 GB.
    Reproduced 5/5 before the fix.
    """
    holder = run_main()
    assert holder["ran_while"] is True, (
        "the pipeline started before App.run(); anything it says at startup "
        "is lost"
    )
    assert holder["exit"] == 0


def test_main_wires_the_feed_picker_to_a_usable_message():
    """Selecting a feed must not be a silent dead end."""
    holder = run_main()
    app = holder["app"]
    app.on_feed_selected(Feed(ident="ksea_twr", label="Seattle Tower"))
    assert app.warnings, "selecting a feed produced no feedback at all"
    message = app.warnings[-1]
    assert "ksea_twr" in message
    assert "--feed ksea_twr" in message


def test_feed_selection_hint_names_ident_and_flag():
    hint = feed_selection_hint(Feed(ident="kpdx3_twr", label="Portland Tower"))
    assert "kpdx3_twr" in hint
    assert "--feed kpdx3_twr" in hint


def test_main_stops_the_player_even_when_the_app_run_raises():
    """A crash escaping the UI must not leave the PortAudio stream open.

    Regression test: `player.stop()` sat after `app.run()` with no
    try/finally, so the NoMatches that `_tick_clock` could raise during
    teardown skipped it entirely.
    """
    stopped = []

    class TrackingPlayer:
        def __init__(self):
            self.muted = False

        def start(self):
            pass

        def write(self, pcm):
            pass

        def stop(self):
            stopped.append(True)

    import squelch.__main__ as main_module

    original = main_module.Player
    main_module.Player = TrackingPlayer
    try:
        with pytest.raises(RuntimeError, match="teardown exploded"):
            run_main(run_error=RuntimeError("teardown exploded"))
    finally:
        main_module.Player = original

    assert stopped, "player.stop() was skipped when App.run() raised"


def test_main_rejects_an_invalid_config_before_starting_the_ui(tmp_path, monkeypatch):
    """A bad config must produce a message, not a dead pipeline thread."""
    bad = tmp_path / "squelch.toml"
    bad.write_text("vad_aggressiveness = 9\n")
    import squelch.config as config_module

    monkeypatch.setattr(config_module, "DEFAULT_PATH", bad)
    started = []

    def app_factory(config, **kwargs):
        started.append(config)
        raise AssertionError("the UI must not start with an unusable config")

    assert main([], app_factory=app_factory) == 2
    assert started == []
