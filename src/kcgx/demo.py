"""A station with nothing real behind it: synthetic feeds for any airport.

`kcgx-web --demo` runs on this. No LiveATC, no ffmpeg, no audio device, no
writes to the state directory: the page can be built, tested and looked at
without spending any of LiveATC's seven streams or hearing anything. The
browser tests run against it too.

Every feed meters, chatters and changes state the way a real one does, so
the page cannot tell the difference except that nothing plays.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections.abc import Callable

from squelch.config import Config
from squelch.feeds import Feed

# (suffix, label, how busy: the fraction of 1.5 s slots with someone talking)
POSITIONS = [
    ("twr", "Tower", 0.38),
    ("app", "Approach", 0.30),
    ("atis", "ATIS", 0.95),
    ("gnd", "Ground", 0.22),
    ("del", "Clearance Delivery", 0.08),
    ("dep", "Departure", 0.18),
    ("twr_n", "Tower (North)", 0.12),
    ("ctr", "Center", 0.10),
    ("gnd_ramp", "Ground (Ramp)", 0.04),
]

# In the picker but not opened at start, so opening a feed can be tried.
EXTRA = [
    ("app_final", "Approach (Final)", 0.20),
    ("guard", "Emergency Guard 121.5", 0.01),
]

SLOT_SECONDS = 1.5
SILENT_DBFS = -96.0


def _feeds(icao: str, positions) -> list[Feed]:
    return [Feed(f"{icao.lower()}_{suffix}", f"{icao.upper()} {label}") for suffix, label, _ in positions]


def listing(config: Config, *, warn: Callable[[str], None]) -> list[Feed]:
    """Stands in for squelch.runtime.load_feeds."""
    return _feeds(config.icao, POSITIONS)


def picker(config: Config) -> list[Feed]:
    """Stands in for squelch.runtime.picker_feeds."""
    return _feeds(config.icao, POSITIONS + EXTRA)


def _busy_for(ident: str) -> float:
    for suffix, _, busy in POSITIONS + EXTRA:
        if ident.endswith("_" + suffix):
            return busy
    return 0.1


class DemoSession:
    """Behaves like squelch.session.FeedSession, minus the network."""

    def __init__(self, feed: Feed, events, *, muted: bool, icao: str, clock=time.monotonic):
        self.feed = feed
        prefix = f"{icao.upper()} "
        self.name = feed.label[len(prefix):] if feed.label.upper().startswith(prefix) else feed.label
        self.events = events
        self.muted = muted
        self.state = "starting"
        self.ambient = False
        self.soloed = False
        self.connected = False
        self._busy = _busy_for(feed.ident)
        self._seed = sum(map(ord, feed.ident))
        self._clock = clock
        self._timer: threading.Timer | None = None

    # -- what the station reads ------------------------------------------------

    @property
    def level(self) -> float:
        if not self.connected or self.state != "live":
            return SILENT_DBFS
        now = self._clock()
        slot = int(now / SLOT_SECONDS)
        talking = random.Random(self._seed * 100_003 + slot).random() < self._busy
        jitter = random.Random(self._seed * 7 + int(now * 25)).random()
        if talking:
            return -24.0 + 14.0 * jitter
        return -66.0 + 8.0 * jitter

    @property
    def activity(self) -> float:
        if self._busy <= 0:
            return 0.0
        drift = 0.85 + 0.15 * math.sin(self._clock() / 45.0 + self._seed)
        return max(0.0, min(1.0, self._busy * drift))

    # -- what the cockpit drives -----------------------------------------------

    def start(self) -> None:
        if self.connected:
            return
        self.connected = True
        # The Center feed reconnects once on its way up, so the page's amber
        # state is visible in the demo; the event arrives from another thread,
        # as a real feed's does.
        if self.feed.ident.endswith("_ctr"):
            self._set("reconnecting")
            self._timer = threading.Timer(3.0, self._set, args=("live",))
            self._timer.daemon = True
            self._timer.start()
        else:
            self._set("live")

    def park(self) -> None:
        self._cancel()
        self.connected = False
        self._set("parked")

    def stop(self) -> None:
        self._cancel()
        self.connected = False

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self) -> bool:
        self.ambient = not self.ambient
        return self.ambient

    def _set(self, state: str) -> None:
        if state == "live" and not self.connected:
            return
        self.state = state
        self.events.on_state(self, state)

    def _cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def build(feeds, config: Config, events, *, mixer=None) -> list[DemoSession]:
    """Stands in for squelch.runtime.build_sessions: everything muted but the
    configured feed, or the first feed when that is not here."""
    sessions = [
        DemoSession(feed, events, muted=feed.ident != config.feed, icao=config.icao)
        for feed in feeds
    ]
    if sessions and all(s.muted for s in sessions):
        sessions[0].muted = False
    return sessions


class DemoMixer:
    """The parts of squelch.mixer.Mixer the station touches. Plays nothing."""

    failed = False

    def __init__(self, *, volume: float = 1.0, **_ignored) -> None:
        self.volume = volume

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def clear_channels(self) -> None:
        pass
