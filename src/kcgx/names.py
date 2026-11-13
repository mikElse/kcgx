"""Feed titles without the airport (phase G decision 19).

LiveATC names a feed with the airport two ways: its ICAO (`KPDX Tower
(Both)`) and its city (`Chicago Approach (10R/28C)`, `Seattle Center`).
On a page that already says which airport it is, both are noise. The
title drops them as whole words, anywhere, and tidies what they leave:
spaces, dangling dashes and slashes, empty brackets. A title that would be
left empty stays as it was.

The city and the airport's name match in any case. The ICAO and IATA
match only in capitals, since many codes are words (`LAS` in "Las Vegas",
`SAN` in "San Diego", `AND`), and the IATA goes after the city, so that
"LAS VEGAS" goes whole rather than leaving "VEGAS".

The airport's own name is dropped too, but only where it heads the title
(once a leading ICAO is gone): its words up to the first of International,
Regional, Airport, Field or Municipal (`Chicago O'Hare`, `Seattle–Tacoma`).
It is tried before the city, so that the longer match wins: the city alone
would leave `–Tacoma Ground`.

Hyphen, en dash, em dash and minus are one dash. A dash with no space
either side joins words, so a term glued to a word by one is not a whole
word: `SEA-TAC Ground` stays, rather than leaving `TAC Ground`.

`ZSE Seattle Center` at KPDX names another city and keeps it.
"""

from __future__ import annotations

import re

# Where an airport's name stops being its place and starts being its kind.
NAME_ENDS = ("international", "regional", "airport", "field", "municipal")

# Hyphen, en dash, em dash, minus; and the same, escaped for a [class].
DASHES = "-\u2013\u2014\u2212"
_IN_CLASS = r"\-\u2013\u2014\u2212"
_DASH = f"[{_IN_CLASS}]"
# What a dropped term can leave hanging: dashes and slashes.
_SEP = f"[{_IN_CLASS}/]"


def _word(term: str) -> str:
    """`term` as a whole word, any dash in it matching any dash: no letter,
    digit or joining dash right before or after."""
    body = "".join(_DASH if ch in DASHES else re.escape(ch) for ch in term)
    return rf"(?<![\w{_IN_CLASS}]){body}(?![\w{_IN_CLASS}])"


def _tidy(text: str) -> str:
    """Spaces, separators and brackets left behind, tidied."""
    previous = None
    while text != previous:
        previous = text
        text = " ".join(text.split())
        # Separators next to each other, once one term between them is gone.
        text = re.sub(rf"({_SEP})(?:\s*{_SEP})+", r"\1", text)
        # A separator just inside a bracket.
        text = re.sub(rf"([(\[])\s*{_SEP}\s*", r"\1", text)
        text = re.sub(rf"\s*{_SEP}\s*([)\]])", r"\1", text)
        # Brackets with nothing in them.
        text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)
        # Separators at either end.
        text = re.sub(rf"^[\s{_IN_CLASS}/]+|[\s{_IN_CLASS}/]+$", "", text)
    return text


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

    def drop(text: str, term: str, flags: int = 0) -> str:
        term = term.strip()
        return re.sub(_word(term), " ", text, flags=flags) if term else text

    text = _tidy(drop(label, icao))
    head = name_head(name)
    if head:
        text = re.sub("^" + _word(head), " ", text, flags=re.IGNORECASE)
    city = where.split(",", 1)[0]
    text = drop(text, city, re.IGNORECASE)
    text = _tidy(drop(text, iata))
    return text or label
