"""kcgx-airport: the bridge between bin/kcgx and the airport dataset.

Two modes, both emitting one tab-separated record:

    icao<TAB>lat<TAB>lon<TAB>label

The record goes to --out when given, stdout otherwise. Textual draws on
stdout, so a caller capturing the record with $(...) would swallow the
picker's own rendering and show an empty popup -- bin/kcgx always passes
--out. stdout stays available for the modes that draw nothing, which is
what keeps this usable by hand.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from kcgx.airports import Airport, find, load_airports
from kcgx.picker import pick
from kcgx.state import current_icao, write_airport


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kcgx-airport", description=__doc__)
    parser.add_argument("mode", choices=("resolve", "pick"))
    parser.add_argument(
        "query", nargs="?", default="", help="ICAO, or text to prefilter the picker"
    )
    parser.add_argument("--out", help="write the record here instead of stdout")
    return parser.parse_args(argv)


def format_record(airport: Airport) -> str:
    label = airport.name
    if airport.where:
        label = f"{label}, {airport.where}"
    return f"{airport.icao}\t{airport.lat}\t{airport.lon}\t{label}"


def emit(record: str, out: str | None) -> None:
    if out is None:
        print(record)
        return
    Path(out).write_text(record + "\n")


def main(
    argv: list[str] | None = None,
    *,
    airports_loader: Callable[[], list[Airport]] = load_airports,
    picker: Callable[..., Airport | None] = pick,
    state_writer: Callable[[str], None] = write_airport,
) -> int:
    args = parse_args(argv)
    airports = airports_loader()

    if args.mode == "resolve":
        icao = current_icao()
        airport = find(icao, airports)
        if airport is None:
            print(
                f"kcgx-airport: {icao} is not in the airport dataset",
                file=sys.stderr,
            )
            return 2
        emit(format_record(airport), args.out)
        return 0

    # pick: an exact code is an answer, not a search.
    chosen = find(args.query, airports) if args.query else None
    if chosen is None:
        chosen = picker(airports, initial=args.query)
    if chosen is None:
        return 1

    state_writer(chosen.icao)
    emit(format_record(chosen), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
