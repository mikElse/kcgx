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

from textual.theme import Theme

from squelch.rows import MeterPalette

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


TEXTUAL_THEME_PREFIX = "kcgx-"

# The pane fill each theme is matched to. Picked from THEME_BACKGROUNDS as
# the one adsb-tui uses for the body of the pane, so squelch sits beside it
# in the same shade rather than a neighbouring one.
_FILL = {
    "default": "#161a20",   # rgb(22,26,32)
    "color": "#0e1418",     # rgb(14,20,24)
    "amber": "#18120a",     # rgb(24,18,10)
    "ocean": "#0a1218",     # rgb(10,18,24)
    "matrix": "#001000",    # rgb(0,16,0)
    "mono": "#080808",      # rgb(8,8,8)
}

# Meter gradient stops. `default`, `amber`, `ocean`, and `matrix` are built
# from foregrounds harvested off the live binary; where a theme yielded
# fewer than four distinct foregrounds the gaps are interpolated within its
# harvested hue family, and those are marked. `color` and `mono` emit no
# truecolor foregrounds at all -- they draw with the terminal's own ANSI
# palette, so matching them means naming ANSI colours rather than hex.
METER_PALETTES: dict[str, MeterPalette] = {
    "default": MeterPalette(
        dim="#8c96a0",      # harvested rgb(140,150,160)
        text="#c6eee8",     # harvested rgb(198,238,232)
        accent="#6cddd6",   # harvested rgb(108,221,214)
        peak="#ff6666",     # harvested rgb(255,102,102)
    ),
    "color": MeterPalette(
        dim="bright_black",
        text="white",
        accent="cyan",
        peak="red",
    ),
    "amber": MeterPalette(
        dim="#8c6e28",      # harvested rgb(140,110,40)
        text="#c99518",     # interpolated
        accent="#ffbf00",   # harvested rgb(255,191,0)
        peak="#ffdc78",     # harvested rgb(255,220,120)
    ),
    "ocean": MeterPalette(
        dim="#507882",      # harvested rgb(80,120,130)
        text="#3aa8bb",     # interpolated
        accent="#00c8dc",   # harvested rgb(0,200,220)
        peak="#b9f0f7",     # interpolated
    ),
    "matrix": MeterPalette(
        dim="#007800",      # harvested rgb(0,120,0)
        text="#00b400",     # interpolated
        accent="#00ff00",   # interpolated
        peak="#b4ffb4",     # interpolated
    ),
    "mono": MeterPalette(
        dim="bright_black",
        text="white",
        accent="bright_white",
        peak="bright_yellow",
    ),
}


def textual_theme(name: str) -> Theme:
    """A Textual theme matching one of adsb-tui's.

    Registered under a `kcgx-` prefix so these can never collide with
    Textual's own built-in theme names.
    """
    palette = METER_PALETTES[name]
    fill = _FILL[name]
    return Theme(
        name=f"{TEXTUAL_THEME_PREFIX}{name}",
        primary=palette.accent,
        secondary=palette.text,
        warning=palette.peak,
        error=palette.peak,
        success=palette.accent,
        accent=palette.accent,
        foreground=palette.text,
        background=fill,
        surface=fill,
        panel=fill,
        dark=True,
    )
