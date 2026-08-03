"""Activity tracking: how busy has this frequency been lately.

A rolling five-minute window over a 10 Hz reading is 3000 samples per feed
and twelve feeds. These tests pin the bucketed approximation that replaces
that, and the clock is always injected -- nothing here sleeps.
"""

from squelch.activity import BUCKET_COUNT, BUCKET_SECONDS, ActivityTracker

LOUD = -20.0
QUIET = -70.0
THRESHOLD = -40.0


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def tracker(clock=None):
    return ActivityTracker(THRESHOLD, clock=clock or FakeClock())


def test_a_cold_tracker_reports_no_activity():
    assert tracker().fraction() == 0.0


def test_a_cold_tracker_does_not_divide_by_zero():
    """A feed that has never delivered a frame must not raise."""
    assert tracker().fraction() == 0.0


def test_all_loud_is_full_activity():
    t = tracker()
    for _ in range(20):
        t.push(LOUD)
    assert t.fraction() == 1.0


def test_all_quiet_is_no_activity():
    t = tracker()
    for _ in range(20):
        t.push(QUIET)
    assert t.fraction() == 0.0


def test_half_loud_is_half_activity():
    t = tracker()
    for _ in range(10):
        t.push(LOUD)
        t.push(QUIET)
    assert t.fraction() == 0.5


def test_a_level_exactly_at_the_threshold_is_not_busy():
    """Strictly greater than, so the threshold itself is the quiet side."""
    t = tracker()
    t.push(THRESHOLD)
    assert t.fraction() == 0.0


def test_just_above_the_threshold_is_busy():
    t = tracker()
    t.push(THRESHOLD + 0.1)
    assert t.fraction() == 1.0


def test_readings_older_than_the_window_are_evicted():
    clock = FakeClock()
    t = tracker(clock)
    for _ in range(10):
        t.push(LOUD)
    assert t.fraction() == 1.0
    clock.advance(BUCKET_SECONDS * BUCKET_COUNT + 1)
    for _ in range(10):
        t.push(QUIET)
    assert t.fraction() == 0.0, "the loud minute has aged out entirely"


def test_the_window_is_five_minutes():
    assert BUCKET_SECONDS * BUCKET_COUNT == 300.0


def test_a_partially_aged_window_blends_old_and_new():
    clock = FakeClock()
    t = tracker(clock)
    for _ in range(10):
        t.push(LOUD)
    clock.advance(150.0)  # half the window
    for _ in range(10):
        t.push(QUIET)
    assert t.fraction() == 0.5, "both halves are still inside the window"


def test_a_long_silence_decays_to_zero_without_new_readings():
    """An offline feed stops pushing entirely and must still sink."""
    clock = FakeClock()
    t = tracker(clock)
    for _ in range(10):
        t.push(LOUD)
    clock.advance(BUCKET_SECONDS * BUCKET_COUNT + 1)
    assert t.fraction() == 0.0


def test_memory_is_bounded_by_the_bucket_count():
    clock = FakeClock()
    t = tracker(clock)
    for _ in range(1000):
        t.push(LOUD)
        clock.advance(1.0)
    assert len(t._buckets) == BUCKET_COUNT


from squelch.activity import SETTLE_ROUNDS, Resorter, rank


def test_rank_puts_the_busiest_first():
    busy = {"a": 0.1, "b": 0.9, "c": 0.5}
    assert rank(["a", "b", "c"], busy.__getitem__) == ["b", "c", "a"]


def test_rank_breaks_ties_by_discovery_order():
    """Two equally idle feeds must not swap places every five seconds."""
    busy = {"a": 0.0, "b": 0.0, "c": 0.0}
    assert rank(["a", "b", "c"], busy.__getitem__) == ["a", "b", "c"]
    assert rank(["c", "b", "a"], busy.__getitem__) == ["c", "b", "a"]


def test_rank_leaves_an_empty_list_alone():
    assert rank([], lambda item: 0.0) == []


def resorter(clock):
    return Resorter(clock=clock)


def test_a_new_order_is_held_until_it_settles():
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS - 1):
        assert r.propose(["b", "a"]) is None
    assert r.propose(["b", "a"]) == ["b", "a"]


def test_a_changing_order_never_settles():
    clock = FakeClock(100.0)
    r = resorter(clock)
    assert r.propose(["b", "a"]) is None
    assert r.propose(["a", "b"]) is None
    assert r.propose(["b", "a"]) is None


def test_recent_input_defers_an_otherwise_ready_resort():
    """A row that moves between the decision to click and the click itself
    mutes the wrong frequency."""
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS - 1):
        r.propose(["b", "a"])
    r.note_input()
    assert r.propose(["b", "a"]) is None, "deferred by the keypress"
    clock.advance(2.5)
    assert r.propose(["b", "a"]) == ["b", "a"]


def test_input_does_not_reset_the_settle_count():
    """After the quiet period, exactly one more proposal applies it.

    SETTLE_ROUNDS - 1, not SETTLE_ROUNDS: a full run would *apply* the
    order, after which every later proposal returns None because it already
    is the applied order -- and the assertion below could never pass.

    The discriminating assertion is that a single propose suffices once the
    pane goes quiet. If the deferral had reset the count, it would take
    SETTLE_ROUNDS more.
    """
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS - 1):
        r.propose(["b", "a"])
    r.note_input()
    assert r.propose(["b", "a"]) is None
    clock.advance(2.5)
    assert r.propose(["b", "a"]) == ["b", "a"], "still settled, just delayed"


def test_applying_an_order_does_not_immediately_reapply_it():
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS - 1):
        r.propose(["b", "a"])
    assert r.propose(["b", "a"]) == ["b", "a"]
    assert r.propose(["b", "a"]) is None, "already the applied order"


def test_reverting_to_the_applied_order_is_not_a_change():
    clock = FakeClock(100.0)
    r = resorter(clock)
    for _ in range(SETTLE_ROUNDS):
        r.propose(["b", "a"])
    r.propose(["a", "b"])
    assert r.propose(["b", "a"]) is None


# -- audible feeds first ---------------------------------------------------


def test_audible_feeds_sort_above_muted_ones_whatever_their_activity():
    """The whole point: what you can hear is what you want to look at."""
    busy = {"a": 0.0, "b": 0.9, "c": 0.5}
    audible = {"a"}
    order = rank(["a", "b", "c"], busy.__getitem__, audible_of=audible.__contains__)
    assert order == ["a", "b", "c"], "a is silent but audible, so it leads"


def test_within_each_group_the_busiest_still_comes_first():
    busy = {"a": 0.1, "b": 0.9, "c": 0.5, "d": 0.7}
    audible = {"a", "c"}
    order = rank(
        ["a", "b", "c", "d"], busy.__getitem__, audible_of=audible.__contains__
    )
    assert order == ["c", "a", "b", "d"], "audible by activity, then muted"


def test_muting_returns_a_feed_to_its_activity_ranked_place():
    busy = {"a": 0.1, "b": 0.9, "c": 0.5}
    # `b` audible: it leads despite the others' activity.
    assert rank(["a", "b", "c"], busy.__getitem__, audible_of={"b"}.__contains__) == [
        "b",
        "c",
        "a",
    ]
    # `b` muted again: it drops back in on activity alone, which puts it first
    # of the muted group rather than anywhere arbitrary.
    assert rank(["a", "b", "c"], busy.__getitem__, audible_of=set().__contains__) == [
        "b",
        "c",
        "a",
    ]


def test_ties_still_break_by_discovery_order_inside_a_group():
    busy = {"a": 0.0, "b": 0.0, "c": 0.0}
    audible = {"b", "c"}
    order = rank(["a", "b", "c"], busy.__getitem__, audible_of=audible.__contains__)
    assert order == ["b", "c", "a"]


def test_without_the_predicate_ranking_is_unchanged():
    """Back-compat: activity alone, exactly as before."""
    busy = {"a": 0.1, "b": 0.9, "c": 0.5}
    assert rank(["a", "b", "c"], busy.__getitem__) == ["b", "c", "a"]


def test_adopting_an_order_stops_it_being_proposed_again():
    """The app reorders immediately on a mute change; the Resorter has to
    know, or it spends three rounds proposing what is already on screen."""
    clock = FakeClock(100.0)
    r = resorter(clock)
    r.adopt(["b", "a"])
    assert r.propose(["b", "a"]) is None
    assert r.propose(["b", "a"]) is None
    assert r.propose(["b", "a"]) is None


def test_adopting_does_not_freeze_later_reorders():
    clock = FakeClock(100.0)
    r = resorter(clock)
    r.adopt(["b", "a"])
    for _ in range(SETTLE_ROUNDS - 1):
        assert r.propose(["a", "b"]) is None
    assert r.propose(["a", "b"]) == ["a", "b"]
