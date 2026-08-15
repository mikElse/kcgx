"""Tests for the block-capital font the status pane renders the ICAO in.

The font is stored as an explicit per-letter table rather than parsed from
a pasted alphabet block. The block it came from has no separator columns --
glyphs sit edge to edge, and the widths are not uniform (M N Q V W X Y Z
are six columns, the rest five), so nothing can recover the letters from it
without already knowing those widths. A literal table is reviewable, and a
re-paste cannot silently shift every letter by a column.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from kcgx.bigtext import GLYPHS, HEIGHT, render, width

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# The rendering that came with the request, used here as an oracle: it was
# produced by the same font, so a table that reproduces it exactly is the
# right table. Any drift in a glyph or a width shows up as a diff here.
KCGX = [
    "▗▖ ▗▖ ▗▄▄▖ ▗▄▄▖▗▖  ▗▖",
    "▐▌▗▞▘▐▌   ▐▌    ▝▚▞▘ ",
    "▐▛▚▖ ▐▌   ▐▌▝▜▌  ▐▌  ",
    "▐▌ ▐▌▝▚▄▄▖▝▚▄▞▘▗▞▘▝▚▖",
]


def test_the_sample_rendering_is_reproduced_exactly():
    assert render("KCGX") == KCGX


def test_every_letter_is_present():
    assert set(GLYPHS) == set(ALPHABET)


def test_every_glyph_is_four_rows_of_one_width():
    for letter, rows in GLYPHS.items():
        assert len(rows) == HEIGHT, f"{letter} is not {HEIGHT} rows"
        assert len(set(len(r) for r in rows)) == 1, (
            f"{letter} has ragged rows: {rows}"
        )


def test_q_is_not_w():
    """The alphabet as supplied had them byte-identical, which would have
    rendered 553 of the 4,737 airports -- Ottawa and Kelowna among them --
    under a letter they are not spelled with."""
    assert GLYPHS["Q"] != GLYPHS["W"], "Q is still W's glyph"


def test_width_agrees_with_what_render_produces():
    for text in ("KCGX", "KPDX", "WWWW", "AAAA", "Q"):
        assert all(len(line) == width(text) for line in render(text)), text


def test_every_airport_in_the_dataset_renders():
    """The font covers A-Z and every ICAO in the dataset is four letters,
    so there is no airport this cannot draw. Pinned because a dataset
    regeneration could introduce a code with a digit in it."""
    data = Path("src/kcgx/data/airports.csv")
    lines = [l for l in data.read_text().splitlines(True) if not l.startswith("#")]
    codes = [r["icao"] for r in csv.DictReader(io.StringIO("".join(lines)))]
    assert codes, "no airports read"
    for code in codes:
        assert len(render(code)) == HEIGHT, code


@pytest.mark.parametrize("text", ["", "  ", "K9", "kcgx", "K-X"])
def test_unrenderable_input_is_survivable(text):
    """current_icao() reads squelch.toml, which can hold anything at all.
    A pane that raises is worse than one that draws a gap."""
    out = render(text)
    assert len(out) == HEIGHT
    assert len(set(len(line) for line in out)) == 1
