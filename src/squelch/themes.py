"""The radar pane's colour scheme, read off the radar pane.

adsb-tui ships six themes and a `t` key that cycles them at runtime, and it
never writes the result anywhere: measured on 2026-08-02, two `t` presses
and a clean quit left its TOML byte-identical while the pane background
moved from rgb(14,20,24) to rgb(24,18,10). Watching the file would observe
nothing, so the theme is identified from what the pane actually painted.
"""

from __future__ import annotations

import re
from collections import Counter

# Harvested from ~/bin/adsb-tui on 2026-08-02 across the radar, full, and
# compact layouts. Identification uses the *most frequent* background, not
# the first: the first varies with layout (default paints (22,26,32) in
# radar and (28,32,38) in full), while the most frequent is the pane fill.
# The sets are pairwise disjoint, which a test enforces.
THEME_BACKGROUNDS: dict[str, tuple[tuple[int, int, int], ...]] = {
    "default": ((18, 20, 24), (20, 22, 26), (22, 26, 32), (28, 32, 38), (198, 238, 232)),
    "color": ((10, 16, 20), (14, 20, 24), (16, 22, 26), (20, 26, 30)),
    "amber": ((20, 16, 10), (24, 18, 10), (28, 22, 12), (32, 24, 14), (255, 220, 120)),
    "ocean": ((10, 18, 24), (12, 24, 30)),
    "matrix": ((0, 12, 0), (0, 16, 0), (0, 18, 0), (0, 22, 0)),
    "mono": ((4, 4, 4), (8, 8, 8), (10, 10, 10), (20, 20, 20)),
}

THEME_NAMES = tuple(THEME_BACKGROUNDS)

_BY_BACKGROUND = {
    triple: name
    for name, triples in THEME_BACKGROUNDS.items()
    for triple in triples
}

_BACKGROUND_RE = re.compile(r"\x1b\[48;2;(\d{1,3});(\d{1,3});(\d{1,3})m")


def backgrounds(capture: str) -> list[tuple[int, int, int]]:
    """Every truecolor background in a captured pane, in order."""
    return [
        (int(r), int(g), int(b)) for r, g, b in _BACKGROUND_RE.findall(capture)
    ]


def dominant_background(capture: str) -> tuple[int, int, int] | None:
    """The most frequent background -- the pane fill.

    Ties break by first appearance so the answer is deterministic and a
    theme cannot flicker between two equally common fills.
    """
    found = backgrounds(capture)
    if not found:
        return None
    counts = Counter(found)
    best = max(counts.values())
    for triple in found:
        if counts[triple] == best:
            return triple
    return None


def theme_for(capture: str) -> str | None:
    """Which adsb-tui theme painted this, or `None` if it is not one of ours.

    Deliberately an exact match rather than nearest-colour: an unrecognised
    fill means adsb-tui has changed or something else is in that pane, and
    silently snapping to the closest of six would be worse than doing
    nothing.
    """
    triple = dominant_background(capture)
    if triple is None:
        return None
    return _BY_BACKGROUND.get(triple)
