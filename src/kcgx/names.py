"""Feed titles without the airport (phase G decision 19).

LiveATC names a feed with the airport two ways: its ICAO (`KPDX Tower
(Both)`) and its city (`Chicago Approach (10R/28C)`, `Seattle Center`).
On a page that already says which airport it is, both are noise. The
title drops them as whole words, anywhere, ignoring case, and tidies the
spaces left behind. A title that would be left empty stays as it was.

The airport's own name is dropped too, but only where it heads the title:
its words up to the first of International, Regional, Airport, Field or
Municipal (`Chicago O'Hare`, `Seattle–Tacoma`). It is tried before the
city, so that the longer match wins: the city alone would leave
`–Tacoma Ground`.

`ZSE Seattle Center` at KPDX names another city and keeps it.
"""

from __future__ import annotations

import re

# Where an airport's name stops being its place and starts being its kind.
NAME_ENDS = ("international", "regional", "airport", "field", "municipal")


def _word(term: str) -> str:
    """`term` as a whole word: no letter or digit right before or after."""
    return rf"(?<!\w){re.escape(term)}(?!\w)"


def name_head(name: str) -> str:
    """An airport's name up to the first word that says what kind of field
    it is. The whole name when no word does; empty when the name starts
    with one."""
    words = name.split()
    for at, word in enumerate(words):
        if word.lower() in NAME_ENDS:
            return " ".join(words[:at])
    return " ".join(words)


def short_feed_name(label: str, *, icao: str, iata: str = "", name: str = "", where: str = "") -> str:
    """`label` without the airport's code, city or name. `where` is the
    dataset's place, `City, ST`; the city is the part before the comma."""
    text = label
    head = name_head(name)
    if head:
        text = re.sub(r"^\s*" + _word(head), "", text, flags=re.IGNORECASE)
    city = where.split(",", 1)[0].strip()
    for term in (icao, iata, city):
        if term.strip():
            text = re.sub(_word(term.strip()), " ", text, flags=re.IGNORECASE)
    text = " ".join(text.split())
    return text or label
