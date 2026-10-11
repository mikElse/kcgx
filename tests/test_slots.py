"""Which feeds hold one of LiveATC's streams.

The property that matters most is the first: a feed you can hear always
holds a stream. Everything else is about spending the spare ones well and
not churning them.
"""

from __future__ import annotations

from dataclasses import dataclass

from squelch import slots


@dataclass
class F:
    name: str
    audible: bool = False
    connected: bool = False
    activity: float = 0.0


def names(items, limit):
    return [
        item.name
        for item in slots.plan(
            items,
            limit,
            audible_of=lambda i: i.audible,
            connected_of=lambda i: i.connected,
            activity_of=lambda i: i.activity,
        )
    ]


def test_the_measured_limit_is_seven():
    assert slots.MAX_STREAMS == 7


def test_under_the_limit_everything_holds_a_stream():
    items = [F("a", audible=True), F("b"), F("c")]
    assert names(items, 7) == ["a", "b", "c"]


def test_never_more_than_the_limit():
    items = [F(str(i)) for i in range(30)]
    assert len(names(items, 7)) == 7


def test_an_audible_feed_outranks_every_muted_one():
    items = [F(str(i), connected=True, activity=0.9) for i in range(7)]
    items.append(F("unmuted", audible=True))
    assert "unmuted" in names(items, 7)


def test_the_quietest_connected_muted_feed_gives_up_its_place():
    items = [F(f"m{i}", connected=True, activity=i / 10) for i in range(7)]
    items.append(F("unmuted", audible=True))
    planned = names(items, 7)
    assert "m0" not in planned  # activity 0.0, the quietest
    assert set(planned) == {"unmuted", "m1", "m2", "m3", "m4", "m5", "m6"}


def test_connected_muted_feeds_keep_their_place_over_parked_ones():
    # Without this, a parked feed earlier in the list would take a slot
    # from a connected one on every recompute, and slots would churn.
    items = [F("parked")] + [F(f"m{i}", connected=True) for i in range(7)]
    assert "parked" not in names(items, 7)


def test_spare_slots_go_to_parked_feeds_in_order():
    items = [F("a", audible=True, connected=True), F("p1"), F("p2"), F("p3")]
    assert names(items, 3) == ["a", "p1", "p2"]


def test_equally_quiet_feeds_keep_the_order_given():
    items = [F(f"m{i}", connected=True) for i in range(5)]
    assert names(items, 3) == ["m0", "m1", "m2"]


def test_more_audible_feeds_than_the_limit_keeps_the_earliest():
    items = [F(str(i), audible=True) for i in range(9)]
    assert names(items, 7) == [str(i) for i in range(7)]


def test_a_limit_of_zero_plans_nothing():
    assert names([F("a", audible=True)], 0) == []
