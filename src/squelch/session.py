"""One feed's runtime: reader, player, pipeline, and the thread they run on.

Each feed is fully independent. Twelve feeds means twelve ffmpeg processes,
twelve PortAudio output streams, and twelve ways to fail — so a session that
cannot resolve its URL, or whose ffmpeg dies, must end up as a dead dot on
its own row and nothing more. It must never stall startup or interfere with
the other eleven, which is why every session owns its own thread and is
guarded end to end.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from squelch.activity import ActivityTracker
from squelch.audio import SILENCE_FLOOR_DBFS, Player, StreamReader
from squelch.feeds import Feed, resolve_stream
from squelch.pipeline import Events, Pipeline

# A compact row draws no meter, so it emits no display levels at all. An
# expanded row decimates by 2 for 25 Hz -- fast enough to read as a
# waveform, and the cost now scales with what you are listening to rather
# than with how many feeds exist.
EXPANDED_DECIMATION = 2
COMPACT_DECIMATION = 0


# Feed labels all start with the airport's ICAO ("KPDX Tower (Both)"), which
# is already in the global header. Stripping it buys five columns back for
# the name itself on a 48-column row.
def strip_icao(label: str, icao: str) -> str:
    prefix = f"{icao.upper()} "
    if label.upper().startswith(prefix):
        return label[len(prefix):]
    return label


@dataclass
class SessionEvents:
    """Callbacks carrying the session that produced them.

    The UI has one row per session, so every signal has to say which row it
    belongs to. Kept separate from `pipeline.Events`, which is per-feed and
    knows nothing about there being more than one.
    """

    on_level: Callable[["FeedSession", float], None]
    on_state: Callable[["FeedSession", str], None]
    on_warn: Callable[["FeedSession", str], None]


class FeedSession:
    """Everything needed to stream, play, and meter one feed."""

    def __init__(
        self,
        feed: Feed,
        events: SessionEvents,
        *,
        muted: bool = True,
        icao: str = "",
        activity_threshold: float = -40.0,
        resolve: Callable[[str], str] = resolve_stream,
        reader_factory: Callable[..., Any] = StreamReader,
        player_factory: Callable[[], Any] = Player,
        pipeline_factory: Callable[..., Any] = Pipeline,
    ) -> None:
        self.feed = feed
        self.name = strip_icao(feed.label, icao) if icao else feed.label
        self.events = events
        self.state = "starting"
        # Routed to the ambient bus. Rendered and toggleable now; the mixer
        # that acts on it arrives with spec D, so this is deliberately inert
        # rather than absent -- the UI is the same either way.
        self.ambient = False
        self.level = SILENCE_FLOOR_DBFS
        self._activity = ActivityTracker(activity_threshold)
        self._player = player_factory()
        self._player.muted = muted
        self._resolve = resolve
        self._reader_factory = reader_factory
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any = None
        self._reader: Any = None
        self._thread: threading.Thread | None = None

    # -- audio ---------------------------------------------------------

    @property
    def muted(self) -> bool:
        return bool(self._player.muted)

    @muted.setter
    def muted(self, value: bool) -> None:
        # Gated at Player.write, so the stream, the reader and the activity
        # count all keep running -- muting silences a feed without making it
        # stop being watched. What it does change is the *display* rate: a
        # muted feed is compact and draws no meter, so emitting levels for
        # it would be marshalling work nobody renders.
        self._player.muted = bool(value)
        self._apply_display_rate()

    def _apply_display_rate(self) -> None:
        if self._pipeline is None:
            return
        # Optional, and deliberately so: the display rate is a redraw
        # optimisation, and a pipeline that cannot change it should keep
        # playing at whatever rate it has. Letting an AttributeError out
        # here would take a whole feed down over a cosmetic knob, which is
        # exactly what per-feed isolation exists to prevent.
        switch = getattr(self._pipeline, "set_level_every", None)
        if switch is None:
            return
        switch(COMPACT_DECIMATION if self.muted else EXPANDED_DECIMATION)

    @property
    def activity(self) -> float:
        return self._activity.fraction()

    def _on_activity(self, dbfs: float) -> None:
        # Stays on this thread: the tracker is arithmetic, and marshalling a
        # 10 Hz reading per feed onto the UI thread would cost more than the
        # ranking is worth.
        self._activity.push(dbfs)

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self) -> bool:
        self.ambient = not self.ambient
        return self.ambient

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            # A daemon thread that dies with an unhandled exception prints
            # nothing and leaves this feed's row frozen at whatever it last
            # said. One feed's failure is its own business, but it has to be
            # visible as such.
            self._fail(f"{type(exc).__name__}: {exc}")

    def _run(self) -> None:
        try:
            url = self._resolve(self.feed.ident)
        except Exception:
            self._fail("could not resolve feed")
            return

        try:
            self._player.start()
        except Exception:
            # Not fatal for this session: the meter is still worth having,
            # and one unavailable output device would otherwise silently
            # take down every feed at once.
            self.events.on_warn(self, "no audio device")

        self._reader = self._reader_factory(url)
        self._pipeline = self._pipeline_factory(
            self._reader,
            self._player,
            Events(
                on_level=lambda dbfs: self._set_level(dbfs),
                on_state=lambda state: self._set_state(state),
                on_activity=self._on_activity,
            ),
        )
        # A session that started unmuted needs its rate now that there is a
        # pipeline to set it on.
        self._apply_display_rate()
        self._pipeline.run()
        # run() only returns when the reader stops, which for a live feed
        # means we asked it to.
        self._set_state("offline")

    def stop(self) -> None:
        if self._pipeline is not None:
            try:
                self._pipeline.stop()
            except Exception:
                pass
        try:
            self._player.stop()
        except Exception:
            pass

    # -- state ---------------------------------------------------------

    def _set_level(self, dbfs: float) -> None:
        self.level = dbfs
        self.events.on_level(self, dbfs)

    def _set_state(self, state: str) -> None:
        self.state = state
        self.events.on_state(self, state)

    def _fail(self, message: str) -> None:
        self._set_state("offline")
        self.events.on_warn(self, message)
