"""The airport dataset, and searching it.

Pure data: no Textual, no tmux, no network. Everything here is a function
of the committed CSV.
"""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "airports.csv"

# The state is what a US or Canadian pilot says; elsewhere the ISO region is
# an opaque code ("PT-13"), so the country reads better.
_REGION_COUNTRIES = {"US", "CA"}


@dataclass(frozen=True)
class Airport:
    icao: str
    iata: str
    name: str
    city: str
    region: str
    country: str
    lat: float
    lon: float
    size: str

    @property
    def where(self) -> str:
        tail = self.region if self.country in _REGION_COUNTRIES else self.country
        return ", ".join(part for part in (self.city, tail) if part)


def load_airports(path: Path | None = None) -> list[Airport]:
    """Parse the committed dataset.

    Comment lines carry the provenance header, and csv.DictReader would
    otherwise take the first of them as the field names.
    """
    path = DATA_PATH if path is None else path
    lines = [
        line for line in path.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    return [
        Airport(
            icao=row["icao"],
            iata=row["iata"],
            name=row["name"],
            city=row["city"],
            region=row["region"],
            country=row["country"],
            lat=float(row["lat"]),
            lon=float(row["lon"]),
            size=row["size"],
        )
        for row in csv.DictReader(lines)
    ]


def find(icao: str, airports: list[Airport]) -> Airport | None:
    """Exact ICAO lookup, case-insensitive."""
    wanted = icao.strip().upper()
    if len(wanted) != 4:
        return None
    for airport in airports:
        if airport.icao == wanted:
            return airport
    return None


SEARCH_LIMIT = 50


def normalize(text: str) -> str:
    """Fold a string to something two spellings of it can both reach.

    The dataset uses an en dash in "Seattle–Tacoma" and an acute in "Sá
    Carneiro"; nobody types either. Mapping every non-alphanumeric to a
    space also means an apostrophe stops hiding "O'Hare" from "o hare".
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    spaced = "".join(c.lower() if c.isalnum() else " " for c in stripped)
    return " ".join(spaced.split())


def squash(text: str) -> str:
    return normalize(text).replace(" ", "")


# Below this length, a token must match the start of a word. "or" is a
# substring of "portland", so allowing short fragments to match anywhere
# would let Portland, Maine answer the query "portland or" -- which makes
# the AND across tokens meaningless. Longer tokens are allowed to match the
# separator-free form, which is the only way "ohare" reaches "O'Hare".
SQUASH_MIN = 4


@lru_cache(maxsize=None)
def _haystack(airport: Airport) -> tuple[tuple[str, ...], str]:
    """The searchable text for one airport, computed once.

    Cached because the picker re-searches all 4,737 airports on every
    keystroke, and normalising each of them every time is pure waste.
    """
    raw = f"{airport.name} {airport.city} {airport.region} {airport.country}"
    spaced = normalize(raw)
    return tuple(spaced.split()), spaced.replace(" ", "")


def _token_matches(token: str, words: tuple[str, ...], squashed: str) -> bool:
    if any(word.startswith(token) for word in words):
        return True
    return len(token) >= SQUASH_MIN and token in squashed


def _order(airport: Airport) -> tuple[int, str]:
    return (0 if airport.size == "large" else 1, airport.icao)


def _tier(airport: Airport, squashed_query: str, tokens: list[str]) -> int | None:
    """Which match tier this airport falls in, or None for no match."""
    icao = airport.icao.lower()
    iata = airport.iata.lower()
    if squashed_query == icao:
        return 0
    if iata and squashed_query == iata:
        return 1
    if icao.startswith(squashed_query) or (iata and iata.startswith(squashed_query)):
        return 2
    words, squashed = _haystack(airport)
    if all(_token_matches(token, words, squashed) for token in tokens):
        return 3
    return None


def search(
    query: str, airports: list[Airport], *, limit: int = SEARCH_LIMIT
) -> list[Airport]:
    """Airports matching `query`, best first.

    Tiered rather than fuzzy-scored: exact code, then code prefix, then
    every query token appearing somewhere in the name, city, region or
    country. Deterministic order is worth more here than cleverness --
    you learn where KPDX sits in the results and it stays there.
    """
    normalized = normalize(query)
    if not normalized:
        return sorted(airports, key=_order)[:limit]

    tokens = normalized.split()
    squashed_query = normalized.replace(" ", "")

    matches = []
    for airport in airports:
        tier = _tier(airport, squashed_query, tokens)
        if tier is not None:
            matches.append((tier, _order(airport), airport))
    matches.sort(key=lambda item: (item[0], item[1]))
    return [airport for _tier_, _order_, airport in matches[:limit]]
