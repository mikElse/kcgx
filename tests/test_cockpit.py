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
