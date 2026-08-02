"""The airport dataset, and searching it.

Pure data: no Textual, no tmux, no network. Everything here is a function
of the committed CSV.
"""

from __future__ import annotations

from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "airports.csv"

import csv
from dataclasses import dataclass

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
