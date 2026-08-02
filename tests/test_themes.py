"""Identifying the radar pane's theme from what it painted.

adsb-tui never writes its theme to disk -- verified: two `t` presses and a
clean quit left the config byte-identical while the pane background changed.
The rendered pane is the only source of truth, so these tests work on
captured escape sequences.
"""

from squelch.themes import (
    THEME_BACKGROUNDS,
    THEME_NAMES,
    backgrounds,
    dominant_background,
    theme_for,
)

ESC = "\x1b"


def paint(*triples):
    """A capture-pane-shaped string with the given backgrounds."""
    return "".join(f"{ESC}[48;2;{r};{g};{b}mXX" for r, g, b in triples)


def test_backgrounds_are_extracted_in_order():
    assert backgrounds(paint((1, 2, 3), (4, 5, 6))) == [(1, 2, 3), (4, 5, 6)]


def test_a_capture_with_no_backgrounds_yields_nothing():
    assert backgrounds("plain text, no escapes") == []
    assert dominant_background("plain text") is None
    assert theme_for("plain text") is None


def test_foreground_sequences_are_not_mistaken_for_backgrounds():
    capture = f"{ESC}[38;2;10;20;30mtext"
    assert backgrounds(capture) == []


def test_the_dominant_background_is_the_most_frequent():
    capture = paint((1, 1, 1), (2, 2, 2), (2, 2, 2))
    assert dominant_background(capture) == (2, 2, 2)


def test_a_tie_is_broken_by_first_appearance():
    """Deterministic, so a theme cannot flicker between two equal fills."""
    capture = paint((1, 1, 1), (2, 2, 2))
    assert dominant_background(capture) == (1, 1, 1)


def test_every_theme_is_identified_by_its_own_backgrounds():
    for name, triples in THEME_BACKGROUNDS.items():
        for triple in triples:
            assert theme_for(paint(triple)) == name, f"{name} {triple}"


def test_the_theme_survives_a_layout_change():
    """`default` fills with (22,26,32) in radar layout and (28,32,38) in
    full layout. Both must identify the same theme."""
    assert theme_for(paint((22, 26, 32))) == "default"
    assert theme_for(paint((28, 32, 38))) == "default"


def test_an_unknown_background_identifies_nothing():
    assert theme_for(paint((123, 45, 67))) is None


def test_a_stray_highlight_does_not_outvote_the_pane_fill():
    capture = paint(*([(14, 20, 24)] * 70), *([(198, 238, 232)] * 3))
    assert theme_for(capture) == "color"


def test_the_background_sets_are_pairwise_disjoint():
    """Any single recognised triple must identify exactly one theme."""
    seen = {}
    for name, triples in THEME_BACKGROUNDS.items():
        for triple in triples:
            assert triple not in seen, f"{triple} in both {seen.get(triple)} and {name}"
            seen[triple] = name


def test_all_six_adsb_tui_themes_are_covered():
    assert set(THEME_NAMES) == {
        "default",
        "color",
        "amber",
        "ocean",
        "matrix",
        "mono",
    }
    assert set(THEME_BACKGROUNDS) == set(THEME_NAMES)
