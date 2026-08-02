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
    # icao/lat/lon are structurally safe; label is the only free-text
    # field. bin/kcgx splits this record on tabs (IFS=$'\t'), so a stray
    # tab here -- however unlikely in today's dataset -- would shift
    # every field after it, feeding a name fragment to a --site-lat flag.
    # Collapsing all whitespace, not just tabs, keeps the record one line.
    label = " ".join(label.split())
    return f"{airport.icao}\t{airport.lat}\t{airport.lon}\t{label}"


def emit(record: str, out: str | None) -> bool:
    """Write `record`. Returns False instead of raising if `out` can't be
    written (bad permissions, missing parent) so the caller can report a
    real error -- never let a write failure surface as a bare traceback or
    collide with exit 1, which the CLI contract reserves for 'cancelled'."""
    if out is None:
        print(record)
        return True
    try:
        Path(out).write_text(record + "\n")
    except OSError:
        return False
    return True


def _write_record(record: str, out: str | None) -> int:
    """Emit `record`, returning the exit code for it: 0 on success, or 2
    (with a stderr message naming the path) if `out` couldn't be written."""
    if emit(record, out):
        return 0
    print(f"kcgx-airport: could not write to {out}", file=sys.stderr)
    return 2


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
        return _write_record(format_record(airport), args.out)

    # pick: an exact code is an answer, not a search.
    chosen = find(args.query, airports) if args.query else None
    if chosen is None:
        chosen = picker(airports, initial=args.query)
    if chosen is None:
        return 1

    state_writer(chosen.icao)
    return _write_record(format_record(chosen), args.out)


if __name__ == "__main__":
    sys.exit(main())
