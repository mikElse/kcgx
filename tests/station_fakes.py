"""Fakes shared by test_station.py and test_server.py: a feed listing, a
picker list, and sessions that behave like FeedSession without ffmpeg."""

from __future__ import annotations

from kcgx.airports import load_airports
from squelch.feeds import Feed

AIRPORTS = load_airports()

LISTINGS = {
    "KPDX": [
        Feed("kpdx3_twr", "KPDX Tower (Both)"),
        Feed("kpdx3_gnd", "KPDX Ground"),
        Feed("kpdx3_atis", "KPDX ATIS"),
    ],
    "KSEA": [Feed("ksea_twr", "KSEA Tower"), Feed("ksea_gnd", "KSEA Ground")],
    "KORD": [Feed("kord_twr", "KORD Tower")],
}


class FakeSession:
    def __init__(self, feed, events, *, muted):
        self.feed = feed
        self.name = feed.label.split(" ", 1)[-1]
        self.events = events
        self.muted = muted
        self.state = "starting"
        self.ambient = False
        self.soloed = False
        self.activity = 0.0
        self.level = -96.0
        self.connected = False
        self.stopped = False

    def start(self):
        self.connected = True
        self.state = "live"

    def park(self):
        self.connected = False
        self.state = "parked"

    def stop(self):
        self.connected = False
        self.stopped = True

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self):
        self.ambient = not self.ambient
        return self.ambient


class Builder:
    """Stands in for squelch.runtime.build_sessions."""

    def __init__(self):
        self.built = []
        self.events = None

    def __call__(self, feeds, config, events, *, mixer=None):
        self.events = events
        out = []
        for feed in feeds:
            if mixer is not None:
                mixer.add_channel()
            out.append(FakeSession(feed, events, muted=feed.ident != config.feed))
        if out and all(s.muted for s in out):
            out[0].muted = False
        self.built.extend(out)
        return out


def listing(config, *, warn):
    return list(LISTINGS.get(config.icao, []))


def picker(config):
    return list(LISTINGS.get(config.icao, [])) + [Feed(f"{config.icao.lower()}_del", "Delivery")]
