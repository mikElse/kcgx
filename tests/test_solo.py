"""The solo state machine.

Solo has to be reversible: engaging records the mix so one press of `S`
returns to it. Everything here is about that recording surviving -- or
being correctly discarded -- as the user keeps pressing things.
"""

from squelch.solo import Solo

# Three feeds: the first audible, the others muted.
MIX = {"a": False, "b": True, "c": True}


def test_a_fresh_solo_is_inactive():
    solo = Solo()
    assert solo.active is False
    assert solo.target is None


def test_engaging_mutes_everything_except_the_target():
    solo = Solo()
    assert solo.engage("b", MIX) == {"a": True, "b": False, "c": True}
    assert solo.active is True
    assert solo.target == "b"


def test_disengaging_restores_the_recorded_mix_exactly():
    solo = Solo()
    solo.engage("b", MIX)
    assert solo.disengage() == MIX
    assert solo.active is False
    assert solo.target is None


def test_disengaging_when_inactive_returns_nothing():
    assert Solo().disengage() is None


def test_soloing_a_second_feed_keeps_the_original_recording():
    """One disengage must still return to the pre-solo mix."""
    solo = Solo()
    solo.engage("b", MIX)
    moved = solo.engage("c", {"a": True, "b": False, "c": True})
    assert moved == {"a": True, "b": True, "c": False}
    assert solo.target == "c"
    assert solo.disengage() == MIX


def test_cancel_discards_the_recording_without_restoring():
    solo = Solo()
    solo.engage("b", MIX)
    solo.cancel()
    assert solo.active is False
    assert solo.disengage() is None


def test_is_soloed_names_only_the_target():
    solo = Solo()
    solo.engage("b", MIX)
    assert solo.is_soloed("b") is True
    assert solo.is_soloed("a") is False


def test_nothing_is_soloed_when_inactive():
    assert Solo().is_soloed("a") is False


def test_engaging_does_not_mutate_the_caller_s_mix():
    solo = Solo()
    original = dict(MIX)
    solo.engage("b", MIX)
    assert MIX == original


def test_soloing_the_only_feed_leaves_it_audible():
    solo = Solo()
    assert solo.engage("a", {"a": True}) == {"a": False}
