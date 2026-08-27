"""Block capitals for the status pane, four rows tall.

The ICAO code is the one thing in the cockpit you read at a glance from
across the room, so it is drawn rather than printed. The glyphs use the
Unicode quadrant blocks, which means they need no font beyond what any
terminal showing the radar already has.

The table is literal on purpose. It was derived once from a pasted
alphabet block in which the glyphs sit edge to edge -- there is not one
column that is blank in all four rows -- and the widths are not uniform:
M N Q V W X Y Z are six columns wide, the other eighteen are five. Parsing
that at runtime would mean hard-coding those widths anyway, and getting one
wrong shifts every later letter by a column with no error to show for it.

The Q here is not the one that came with that alphabet. That glyph was
byte-identical to W -- see test_q_is_not_w.
"""

from __future__ import annotations

# Rows per glyph. Every entry in GLYPHS is this tall; the widths differ.
HEIGHT = 4

GLYPHS: dict[str, tuple[str, ...]] = {
    "A": (
        " ▗▄▖ ",
        "▐▌ ▐▌",
        "▐▛▀▜▌",
        "▐▌ ▐▌",
    ),
    "B": (
        "▗▄▄▖ ",
        "▐▌ ▐▌",
        "▐▛▀▚▖",
        "▐▙▄▞▘",
    ),
    "C": (
        " ▗▄▄▖",
        "▐▌   ",
        "▐▌   ",
        "▝▚▄▄▖",
    ),
    "D": (
        "▗▄▄▄ ",
        "▐▌  █",
        "▐▌  █",
        "▐▙▄▄▀",
    ),
    "E": (
        "▗▄▄▄▖",
        "▐▌   ",
        "▐▛▀▀▘",
        "▐▙▄▄▖",
    ),
    "F": (
        "▗▄▄▄▖",
        "▐▌   ",
        "▐▛▀▀▘",
        "▐▌   ",
    ),
    "G": (
        " ▗▄▄▖",
        "▐▌   ",
        "▐▌▝▜▌",
        "▝▚▄▞▘",
    ),
    "H": (
        "▗▖ ▗▖",
        "▐▌ ▐▌",
        "▐▛▀▜▌",
        "▐▌ ▐▌",
    ),
    "I": (
        "▗▄▄▄▖",
        "  █  ",
        "  █  ",
        "▗▄█▄▖",
    ),
    "J": (
        "   ▗▖",
        "   ▐▌",
        "   ▐▌",
        "▗▄▄▞▘",
    ),
    "K": (
        "▗▖ ▗▖",
        "▐▌▗▞▘",
        "▐▛▚▖ ",
        "▐▌ ▐▌",
    ),
    "L": (
        "▗▖   ",
        "▐▌   ",
        "▐▌   ",
        "▐▙▄▄▖",
    ),
    "M": (
        "▗▖  ▗▖",
        "▐▛▚▞▜▌",
        "▐▌  ▐▌",
        "▐▌  ▐▌",
    ),
    "N": (
        "▗▖  ▗▖",
        "▐▛▚▖▐▌",
        "▐▌ ▝▜▌",
        "▐▌  ▐▌",
    ),
    "O": (
        " ▗▄▖ ",
        "▐▌ ▐▌",
        "▐▌ ▐▌",
        "▝▚▄▞▘",
    ),
    "P": (
        "▗▄▄▖ ",
        "▐▌ ▐▌",
        "▐▛▀▘ ",
        "▐▌   ",
    ),
    "Q": (
        " ▗▄▖  ",
        "▐▌ ▐▌ ",
        "▐▌ ▐▌ ",
        "▝▚▄▞▚▖",
    ),
    "R": (
        "▗▄▄▖ ",
        "▐▌ ▐▌",
        "▐▛▀▚▖",
        "▐▌ ▐▌",
    ),
    "S": (
        " ▗▄▄▖",
        "▐▌   ",
        " ▝▀▚▖",
        "▗▄▄▞▘",
    ),
    "T": (
        "▗▄▄▄▖",
        "  █  ",
        "  █  ",
        "  █  ",
    ),
    "U": (
        "▗▖ ▗▖",
        "▐▌ ▐▌",
        "▐▌ ▐▌",
        "▝▚▄▞▘",
    ),
    "V": (
        "▗▖  ▗▖",
        "▐▌  ▐▌",
        "▐▌  ▐▌",
        " ▝▚▞▘ ",
    ),
    "W": (
        "▗▄▄▄▖ ",
        "▐▌ ▐▌ ",
        "▐▌ ▐▌ ",
        "▐▙▄▟▙▖",
    ),
    "X": (
        "▗▖  ▗▖",
        " ▝▚▞▘ ",
        "  ▐▌  ",
        "▗▞▘▝▚▖",
    ),
    "Y": (
        "▗▖  ▗▖",
        " ▝▚▞▘ ",
        "  ▐▌  ",
        "  ▐▌  ",
    ),
    "Z": (
        "▗▄▄▄▄▖",
        "   ▗▞▘",
        " ▗▞▘  ",
        "▐▙▄▄▄▖",
    ),
}


def _cells(text: str) -> list[tuple[str, ...]]:
    """The glyphs for `text`, uppercased, skipping what we cannot draw.

    Silently dropping a character is the right failure here. The dataset is
    all four-letter A-Z codes, but current_icao() falls back to whatever is
    in squelch.toml, and a status pane that raises on a stray character is
    worse than one that draws the letters it knows.
    """
    return [GLYPHS[c] for c in text.upper() if c in GLYPHS]


def width(text: str) -> int:
    """Columns `render(text)` will occupy."""
    return sum(len(cell[0]) for cell in _cells(text))


def render(text: str) -> list[str]:
    """`text` as HEIGHT lines of block capitals, all the same length.

    Always HEIGHT lines, even for input with nothing renderable in it, so
    callers can size a widget from the result without a special case.
    """
    cells = _cells(text)
    return ["".join(cell[row] for cell in cells) for row in range(HEIGHT)]
