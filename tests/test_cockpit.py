"""The cockpit's rules, with no UI anywhere near them.

Everything here used to be reachable only through a running Textual app.
These tests drive the same rules directly, which is what the browser front
end will do in phase B. The terminal app's own tests (tests/test_app.py)
still cover the same behaviour end to end; this file is what remains when
the terminal UI is retired.
"""

from __future__ import annotations

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

    def stop(self):
        self.connected = False
        self.stopped = True


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


# -- the mix ---------------------------------------------------------------


def mutes(cockpit):
    return [s.muted for s in cockpit.sessions]


def by(cockpit, idents):
    return [cockpit.session(i) for i in idents]


def test_unmuting_lifts_a_feed_to_the_top_at_once():
    cockpit, rec, _ = make(3, audible=())
    target = ident(cockpit, 2)
    cockpit.toggle_mute(target)
    assert rec.of(ORDER), "an unmute must reorder without waiting to settle"
    assert rec.of(ORDER)[-1][0].feed.ident == target
    assert ident(cockpit, 0) == target


def test_muting_drops_it_back_in_on_activity():
    cockpit, _, _ = make(3, audible=(0,))
    s0, s1, s2 = cockpit.sessions
    s0.activity, s1.activity, s2.activity = 0.5, 0.9, 0.1
    cockpit.toggle_mute(s0.feed.ident)
    assert cockpit.sessions == [s1, s0, s2]


def test_the_feed_event_comes_before_the_order_event():
    """The owner redraws the row, then moves it. The other way round, a
    row would be moved to its new place still drawn in its old shape."""
    cockpit, rec, _ = make(3, audible=())
    cockpit.toggle_mute(ident(cockpit, 1))
    kinds = [k for k, _ in rec.events]
    assert kinds.index(FEED) < kinds.index(ORDER)


def test_an_immediate_reorder_is_not_proposed_again():
    cockpit, rec, _ = make(3, audible=(0,))
    cockpit.sessions[1].activity = 0.9
    cockpit.toggle_mute(ident(cockpit, 0))
    after = cockpit.sessions
    for _ in range(SETTLE_ROUNDS + 1):
        cockpit.tick_resort()
    assert len(rec.of(ORDER)) == 1, "the applied order was proposed again"
    assert cockpit.sessions == after


def test_solo_mutes_every_other_feed():
    cockpit, _, _ = make(3, audible=(0,))
    target = ident(cockpit, 1)
    assert cockpit.toggle_solo(target) is True
    assert [s.muted for s in cockpit.sessions if s.feed.ident != target] == [True, True]
    assert cockpit.session(target).muted is False


def test_solo_restores_the_prior_mix_including_other_unmuted_feeds():
    cockpit, _, _ = make(3, audible=(0, 1))
    before = {s.feed.ident: s.muted for s in cockpit.sessions}
    target = "kpdx_app_124350"
    cockpit.toggle_solo(target)
    cockpit.toggle_solo(target)
    assert {s.feed.ident: s.muted for s in cockpit.sessions} == before


def test_moving_the_solo_then_disengaging_returns_to_the_pre_solo_mix():
    cockpit, _, _ = make(4, audible=(0,))
    before = {s.feed.ident: s.muted for s in cockpit.sessions}
    cockpit.toggle_solo("kpdx3_gnd")
    cockpit.toggle_solo("kpdx3_atis")
    cockpit.toggle_solo("kpdx3_atis")
    assert {s.feed.ident: s.muted for s in cockpit.sessions} == before


def test_muting_by_hand_during_solo_cancels_it():
    cockpit, _, _ = make(3, audible=(0,))
    cockpit.toggle_solo("kpdx3_gnd")
    assert cockpit.solo.active is True
    cockpit.toggle_mute("kpdx3_twr")
    assert cockpit.solo.active is False, "a manual mute is a new intent"
    assert not any(s.soloed for s in cockpit.sessions)


def test_only_the_soloed_feed_is_marked():
    cockpit, _, _ = make(3, audible=(0,))
    cockpit.toggle_solo("kpdx3_gnd")
    assert [s.feed.ident for s in cockpit.sessions if s.soloed] == ["kpdx3_gnd"]


def test_solo_puts_the_soloed_feed_on_top():
    cockpit, _, _ = make(3, audible=(0,))
    cockpit.toggle_solo("kpdx_app_124350")
    assert ident(cockpit, 0) == "kpdx_app_124350"


def test_soloing_a_parked_feed_connects_it():
    cockpit, _, _ = make(5, limit=3, connected=False)
    cockpit.start()
    target = next(s for s in cockpit.sessions if not s.connected)
    cockpit.toggle_solo(target.feed.ident)
    assert target.connected
    assert sum(s.connected for s in cockpit.sessions) == 3


# -- select: one feed at a time (phase G decision 3) ------------------------


def test_select_leaves_only_that_feed_audible():
    cockpit, _, _ = make(4, audible=(0, 2))
    assert cockpit.select("kpdx3_gnd") is True
    assert {s.feed.ident: s.muted for s in cockpit.sessions} == {
        "kpdx3_twr": True, "kpdx3_gnd": False, "kpdx_app_124350": True, "kpdx3_atis": True,
    }


def test_select_cancels_a_solo():
    cockpit, _, _ = make(3, audible=(0,))
    cockpit.toggle_solo("kpdx3_gnd")
    cockpit.select("kpdx_app_124350")
    assert cockpit.solo.active is False
    assert not any(s.soloed for s in cockpit.sessions)
    assert [s.feed.ident for s in cockpit.sessions if not s.muted] == ["kpdx_app_124350"]


def test_selecting_a_parked_feed_starts_it_and_parks_another():
    cockpit, _, _ = make(5, limit=3, connected=False)
    cockpit.start()
    target = next(s for s in cockpit.sessions if not s.connected)
    cockpit.select(target.feed.ident)
    assert target.connected and target.state == "live"
    assert sum(s.connected for s in cockpit.sessions) == 3


def test_select_announces_every_changed_feed_and_reorders_at_once():
    cockpit, rec, _ = make(4, audible=(0, 1))
    untouched = cockpit.session("kpdx3_atis")
    rec.events.clear()
    cockpit.select("kpdx_app_124350")
    announced = {s.feed.ident for s in rec.of(FEED)}
    assert announced == {"kpdx3_twr", "kpdx3_gnd", "kpdx_app_124350"}
    assert untouched not in rec.of(FEED)
    assert rec.of(ORDER), "a select must reorder without waiting to settle"
    assert ident(cockpit, 0) == "kpdx_app_124350"
    kinds = [k for k, _ in rec.events]
    assert kinds.index(FEED) < kinds.index(ORDER)


def test_selecting_the_audible_feed_changes_nothing_and_says_nothing():
    cockpit, rec, _ = make(3, audible=(1,))
    before = mutes(cockpit)
    assert cockpit.select("kpdx3_gnd") is False
    assert mutes(cockpit) == before
    assert rec.events == []


def test_selecting_an_unknown_feed_changes_nothing_and_says_nothing():
    cockpit, rec, _ = make(3)
    assert cockpit.select("nope") is False
    assert rec.events == []


def test_ambient_toggles_only_its_feed_and_leaves_mute_alone():
    cockpit, rec, _ = make(3, audible=(0,))
    before = mutes(cockpit)
    assert cockpit.toggle_ambient("kpdx3_gnd") is True
    assert [s.ambient for s in cockpit.sessions] == [False, True, False]
    assert mutes(cockpit) == before
    assert rec.of(FEED) == [cockpit.session("kpdx3_gnd")]


# -- resorting ---------------------------------------------------------------


def test_the_stack_reorders_busiest_first_once_settled():
    cockpit, rec, _ = make(3, audible=())
    s0, s1, s2 = cockpit.sessions
    s0.activity, s1.activity, s2.activity = 0.1, 0.9, 0.5
    for _ in range(SETTLE_ROUNDS):
        cockpit.tick_resort()
    assert cockpit.sessions == [s1, s2, s0]
    assert rec.of(ORDER)[-1] == [s1, s2, s0]


def test_one_tick_is_not_enough_to_reorder():
    cockpit, rec, _ = make(3, audible=())
    original = cockpit.sessions
    cockpit.sessions[1].activity = 0.9
    cockpit.tick_resort()
    assert cockpit.sessions == original
    assert rec.of(ORDER) == []


def test_input_holds_a_settled_resort_until_the_hand_comes_off():
    cockpit, rec, clock = make(3, audible=())
    original = cockpit.sessions
    original[1].activity = 0.9
    for _ in range(SETTLE_ROUNDS - 1):
        cockpit.tick_resort()
    cockpit.note_input()
    cockpit.tick_resort()
    assert cockpit.sessions == original, "the stack must not move under a hand"
    clock.now += QUIET_SECONDS + 0.1
    cockpit.tick_resort()
    assert ident(cockpit, 0) == original[1].feed.ident


# -- opening a feed ----------------------------------------------------------


ATIS = Feed(ident="kpdx3_atis", label="KPDX ATIS")


def late_session(muted=False):
    session = FakeSession("kpdx3_atis", "KPDX ATIS", muted=muted)
    session.connected = False
    session.state = "starting"
    return session


def test_without_an_opener_it_says_so_rather_than_pretending():
    cockpit, rec, _ = make(2)
    assert cockpit.open_feed(ATIS) is None
    assert rec.messages == ["kpdx3_atis is not open"]
    assert rec.of(ADDED) == []


def test_a_feed_that_will_not_open_warns_instead_of_raising():
    def boom(feed):
        raise RuntimeError("boom")

    cockpit, rec, _ = make(2, opener=boom)
    assert cockpit.open_feed(ATIS) is None
    assert rec.messages == ["could not open kpdx3_atis: boom"]


def test_an_opened_feed_is_added_before_it_is_started():
    """The owner needs somewhere to put the feed's first state change, and
    a session's opening act can be a warning."""
    late = late_session()
    cockpit, rec, _ = make(2, opener=lambda feed: late)
    assert cockpit.open_feed(ATIS) is late
    assert cockpit.sessions[-1] is late
    assert late.connected
    added = rec.events.index((ADDED, late))
    started = rec.events.index((FEED, late))
    assert added < started
    assert "opened kpdx3_atis" in rec.messages


def test_a_feed_opened_at_the_audible_limit_opens_muted():
    late = late_session()
    cockpit, rec, _ = make(2, limit=2, audible=(0, 1), opener=lambda f: late)
    cockpit.open_feed(ATIS)
    assert late.muted is True
    assert cockpit.audible_count() == 2
    assert any("Opened ATIS muted" in m for m in rec.messages), rec.messages


def test_an_opened_feed_is_findable_by_ident():
    late = late_session()
    cockpit, _, _ = make(2, opener=lambda feed: late)
    cockpit.open_feed(ATIS)
    assert cockpit.session("kpdx3_atis") is late


# -- stopping --------------------------------------------------------------


def test_stop_stops_every_session_and_says_nothing():
    cockpit, rec, _ = make(3)
    cockpit.stop()
    assert all(getattr(s, "stopped", False) for s in cockpit.sessions)
    assert rec.events == []


def test_one_session_that_will_not_stop_does_not_keep_the_others_running():
    cockpit, _, _ = make(3)
    stubborn = cockpit.sessions[0]

    def refuse():
        raise RuntimeError("will not stop")

    stubborn.stop = refuse
    cockpit.stop()
    assert all(getattr(s, "stopped", False) for s in cockpit.sessions[1:])

