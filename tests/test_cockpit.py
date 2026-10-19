"""The cockpit's rules, with no UI anywhere near them.

Everything here used to be reachable only through a running Textual app.
These tests drive the same rules directly, which is what the browser front
end will do in phase B. The terminal app's own tests (tests/test_app.py)
still cover the same behaviour end to end; this file is what remains when
the terminal UI is retired.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from squelch.activity import QUIET_SECONDS, SETTLE_ROUNDS
from squelch.cockpit import ADDED, FEED, MESSAGE, ORDER, Cockpit
from squelch.config import Config
from squelch.feeds import Feed


class FakeSession:
    def __init__(self, ident, label, *, muted=True, state="live"):
        self.feed = Feed(ident=ident, label=label)
        self.name = label.replace("KPDX ", "")
        self.muted = muted
        self.state = state
        self.ambient = False
        self.soloed = False
        self.activity = 0.0
        self.connected = True
        self.starts = 0

    def start(self):
        self.connected = True
        self.state = "live"
        self.starts += 1

    def park(self):
        self.connected = False
        self.state = "parked"

    def toggle_mute(self):
        self.muted = not self.muted
        return self.muted

    def toggle_ambient(self):
        self.ambient = not self.ambient
        return self.ambient


NAMES = [
    ("kpdx3_twr", "KPDX Tower (Both)"),
    ("kpdx3_gnd", "KPDX Ground"),
    ("kpdx_app_124350", "KPDX Approach (Final) #1"),
    ("kpdx3_atis", "KPDX ATIS"),
    ("kpdx3_del", "KPDX Clearance Delivery"),
]


def stack(n, *, audible=(0,), connected=True):
    out = []
    for i in range(n):
        ident, label = NAMES[i % len(NAMES)]
        if i >= len(NAMES):
            ident, label = f"{ident}_{i}", f"{label} #{i}"
        session = FakeSession(ident, label, muted=i not in audible)
        if not connected:
            session.connected = False
            session.state = "starting"
        out.append(session)
    return out


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, kind, payload):
        self.events.append((kind, payload))

    def of(self, kind):
        return [payload for k, payload in self.events if k == kind]

    @property
    def messages(self):
        return self.of(MESSAGE)


def make(n=3, *, limit=7, audible=(0,), connected=True, opener=None):
    rec, clock = Recorder(), Clock()
    cockpit = Cockpit(
        Config(icao="KPDX", feed="kpdx3_twr", max_streams=limit),
        stack(n, audible=audible, connected=connected),
        feed_opener=opener,
        on_change=rec,
        clock=clock,
    )
    return cockpit, rec, clock


def ident(cockpit, index):
    return cockpit.sessions[index].feed.ident


# -- shape -----------------------------------------------------------------


def test_importing_the_cockpit_does_not_import_textual():
    """The point of the module. A stray import would make the browser
    server pay for Textual, and would be the first step back to rules that
    only a terminal app can reach."""
    probe = "import sys, squelch.cockpit; sys.exit('textual' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", probe])
    assert result.returncode == 0, "squelch.cockpit pulled in textual"


def test_sessions_keep_the_order_given():
    cockpit, _, _ = make(3)
    assert [s.feed.ident for s in cockpit.sessions] == [
        "kpdx3_twr", "kpdx3_gnd", "kpdx_app_124350",
    ]


def test_sessions_is_a_copy():
    cockpit, _, _ = make(3)
    cockpit.sessions.reverse()
    assert ident(cockpit, 0) == "kpdx3_twr"


def test_a_feed_is_found_by_ident_and_an_unknown_one_is_none():
    cockpit, _, _ = make(3)
    assert cockpit.session("kpdx3_gnd") is cockpit.sessions[1]
    assert cockpit.session("nope") is None


def test_duplicate_idents_are_refused():
    """Every action is addressed by ident. Two feeds sharing one would make
    a mute ambiguous; parse_airport_page already de-duplicates, so this can
    only be a programming error, and it should be loud."""
    twins = [FakeSession("a", "A"), FakeSession("a", "A again")]
    with pytest.raises(ValueError, match="a"):
        Cockpit(Config(), twins)


def test_a_stream_limit_of_zero_is_treated_as_one():
    """Zero would park everything, including the feed you are listening to,
    and look exactly like a dead network."""
    cockpit, _, _ = make(2, limit=0)
    assert cockpit.max_streams == 1


def test_every_session_starts_unsoloed():
    sessions = stack(2)
    sessions[0].soloed = True
    Cockpit(Config(), sessions)
    assert not any(s.soloed for s in sessions)


# -- stream slots ----------------------------------------------------------


def test_start_connects_no_more_than_the_limit_and_parks_the_rest():
    cockpit, rec, _ = make(5, limit=3, connected=False)
    cockpit.start()
    connected = [s for s in cockpit.sessions if s.connected]
    parked = [s for s in cockpit.sessions if s.state == "parked"]
    assert len(connected) == 3
    assert len(parked) == 2
    assert not any(s.starts for s in parked), "a parked feed was started"
    assert cockpit.session("kpdx3_twr").connected, "the audible feed must play"
    assert any("2 parked" in m for m in rec.messages), rec.messages


def test_no_parking_notice_when_everything_fits():
    cockpit, rec, _ = make(3, limit=7, connected=False)
    cockpit.start()
    assert all(s.connected for s in cockpit.sessions)
    assert not any("parked" in m for m in rec.messages)


def test_parking_and_starting_are_announced_per_feed():
    """The owner has no other way to learn a row changed: park() runs on
    the caller's thread, where the session's own event cannot be
    delivered."""
    cockpit, rec, _ = make(5, limit=3, connected=False)
    cockpit.start()
    announced = rec.of(FEED)
    assert set(map(id, announced)) == set(map(id, cockpit.sessions))


def test_unmuting_a_parked_feed_takes_the_quietest_muted_slot():
    cockpit, _, _ = make(5, limit=3, connected=False)
    cockpit.start()
    held = [s for s in cockpit.sessions if s.connected and s.muted]
    held[0].activity, held[1].activity = 0.5, 0.0
    quietest = held[1]
    target = next(s for s in cockpit.sessions if not s.connected)
    assert cockpit.toggle_mute(target.feed.ident) is True
    assert target.muted is False
    assert target.connected, "an unmuted feed must hold a stream"
    assert not quietest.connected, "the quietest muted feed should yield"
    assert sum(s.connected for s in cockpit.sessions) == 3


def test_unmuting_past_the_limit_is_refused_and_explained():
    cockpit, rec, _ = make(4, limit=2, audible=(0, 1), connected=False)
    cockpit.start()
    target = next(s for s in cockpit.sessions if s.muted)
    assert cockpit.toggle_mute(target.feed.ident) is False
    assert target.muted is True
    assert cockpit.audible_count() == 2
    assert any(
        "2 feeds already audible" in m and target.name in m
        for m in rec.messages
    ), rec.messages


def test_muting_is_never_refused_at_the_limit():
    cockpit, _, _ = make(4, limit=2, audible=(0, 1), connected=False)
    cockpit.start()
    target = next(s for s in cockpit.sessions if not s.muted)
    assert cockpit.toggle_mute(target.feed.ident) is True
    assert target.muted is True


def test_an_unknown_ident_changes_nothing_and_says_nothing():
    cockpit, rec, _ = make(3)
    assert cockpit.toggle_mute("nope") is False
    assert rec.events == []
