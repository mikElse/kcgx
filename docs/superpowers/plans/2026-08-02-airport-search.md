# Cockpit-wide Airport Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search for an airport from inside the running kcgx cockpit and
retarget both squelch and adsb-tui to it, remembering the choice across
restarts.

**Architecture:** A new `kcgx` Python package (sibling to `squelch` in the
same repo) owns an offline airport dataset, the search over it, a Textual
picker, and a `kcgx-airport` console script. `bin/kcgx` remains the only
thing that talks to tmux; it calls `kcgx-airport` to learn the target and
issues `respawn-pane` to move both children. squelch gains two correctness
fixes so that a failed feed lookup at a new airport never plays a different
airport's audio.

**Tech Stack:** Python 3.14, Textual 8.2.8, pytest (`asyncio_mode = "auto"`),
bash, tmux 3.7b, uv / `uv_build`.

**Spec:** `docs/superpowers/specs/2026-08-02-airport-search-design.md`

## Global Constraints

- Python `>=3.14`; Textual pinned `>=8.2.8,<9`. Do not add runtime
  dependencies — the dataset is committed, not fetched.
- Run everything through uv: `uv run --project /Users/mikelse/kcgx pytest`.
- The repo is at `/Users/mikelse/kcgx`, git branch `build-squelch`, no remote.
- **Textual widget capture in tests must use
  `app.screen._compositor.render_strips(Size(w, h))`, never
  `screen.render_lines()`** — the latter returns blank fill for child
  widgets in Textual 8.2.8, which makes width assertions pass vacuously.
- **Every new test must be revert-checked**: comment out or revert the
  implementation, confirm the test *fails*, then restore it and confirm it
  passes. Three separate bugs in this project shipped green because a test
  asserted something that was true with the feature removed.
- Commit after every task. Message style: `feat(kcgx): ...`,
  `fix(squelch): ...`, `test: ...`, `docs: ...`. End commit messages with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- Existing suite is 153 tests and must stay green.

---

## File Structure

**Create:**

| Path | Responsibility |
|---|---|
| `src/kcgx/__init__.py` | empty package marker |
| `src/kcgx/airports.py` | `Airport` model, CSV loading, normalisation, `find`, `search`. No Textual, no tmux, no network. |
| `src/kcgx/state.py` | the remembered ICAO, and the resolution order that produces the current target |
| `src/kcgx/picker.py` | the Textual picker and its row rendering |
| `src/kcgx/__main__.py` | `kcgx-airport` console script: `resolve` and `pick` modes |
| `src/kcgx/data/airports.csv` | committed dataset, 4,737 rows |
| `tools/build_airports.py` | regenerates the dataset from OurAirports |
| `tests/test_airports.py` | model, loading, normalisation, search ranking |
| `tests/test_airport_state.py` | state file and resolution order |
| `tests/test_airport_picker.py` | the Textual picker |
| `tests/test_kcgx_airport_cli.py` | the console script's two modes |

**Modify:**

| Path | Change |
|---|---|
| `pyproject.toml` | second module + second console script |
| `bin/kcgx` | `adsb_cmd`/`squelch_cmd`/`retarget`, launch-time resolve, `go` subcommand |
| `kcgx.tmux.conf` | `bind a` popup |
| `src/squelch/feeds.py` | `COLD_FETCH_ATTEMPTS`, seams on `fetch_feeds` |
| `src/squelch/__main__.py` | cross-airport fallback fix, tower preference |
| `tests/test_kcgx_launcher.py` | stand-ins tolerate flags; retarget tests |
| `tests/test_main.py` | fallback and tower-preference tests |
| `README.md` | document `kcgx go` and `prefix + a` |

---

### Task 1: The `kcgx` package and its dataset

Establishes the second package, the build script, and the committed CSV.
Nothing else can be written until `import kcgx` works and the data file
ships alongside the module.

**Files:**
- Create: `src/kcgx/__init__.py`, `src/kcgx/data/airports.csv`, `tools/build_airports.py`
- Modify: `pyproject.toml`
- Test: `tests/test_airports.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable `kcgx` package; `src/kcgx/data/airports.csv` with
  header `icao,iata,name,city,region,country,lat,lon,size` and `#`-prefixed
  comment lines above it.

- [ ] **Step 1: Add the second module and console script to `pyproject.toml`**

`uv_build` defaults to a single module named after the project (`squelch`).
Declaring `module-name` as a list is what makes a second one build. This
was verified working against the pinned `uv_build>=0.11.14,<0.12.0`.

```toml
[project.scripts]
squelch = "squelch.__main__:main"
kcgx-airport = "kcgx.__main__:main"

[tool.uv.build-backend]
module-name = ["squelch", "kcgx"]
```

Add the `[tool.uv.build-backend]` table; edit the existing
`[project.scripts]` table in place.

- [ ] **Step 2: Create the package marker**

```bash
mkdir -p /Users/mikelse/kcgx/src/kcgx/data /Users/mikelse/kcgx/tools
printf '"""The kcgx cockpit: airport search that retargets squelch and adsb-tui."""\n' \
  > /Users/mikelse/kcgx/src/kcgx/__init__.py
```

- [ ] **Step 3: Write the dataset build script**

Create `tools/build_airports.py`:

```python
"""Regenerate src/kcgx/data/airports.csv from OurAirports.

Run with:  uv run --project . python tools/build_airports.py

The result is committed, so this runs about once a year. Keeping it in the
repo is what makes the data file reproducible rather than mysterious.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import urllib.request
from pathlib import Path

SOURCE = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUT = Path(__file__).resolve().parent.parent / "src" / "kcgx" / "data" / "airports.csv"

# LiveATC covers a few hundred fields, essentially all of them large or
# medium. Including the ~80,000 smaller entries would swamp every search
# result without ever adding an airport you could listen to.
KEEP_TYPES = {"large_airport", "medium_airport"}
SIZES = {"large_airport": "large", "medium_airport": "medium"}


def build(rows: list[dict[str, str]]) -> list[list[str]]:
    out = []
    for row in rows:
        icao = row["icao_code"].strip().upper()
        if row["type"] not in KEEP_TYPES or len(icao) != 4:
            continue
        region = row["iso_region"].split("-", 1)[-1] if row["iso_region"] else ""
        out.append([
            icao,
            row["iata_code"].strip().upper(),
            row["name"].strip(),
            row["municipality"].strip(),
            region,
            row["iso_country"].strip().upper(),
            row["latitude_deg"].strip(),
            row["longitude_deg"].strip(),
            SIZES[row["type"]],
        ])
    out.sort(key=lambda r: r[0])
    return out


def main() -> None:
    with urllib.request.urlopen(SOURCE, timeout=120) as response:
        text = response.read().decode("utf-8")
    rows = build(list(csv.DictReader(io.StringIO(text))))

    buffer = io.StringIO()
    buffer.write(f"# Generated by tools/build_airports.py on {dt.date.today()}\n")
    buffer.write(f"# Source: {SOURCE}\n")
    buffer.write("# Filter: type in (large_airport, medium_airport) with a 4-letter ICAO\n")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["icao", "iata", "name", "city", "region", "country", "lat", "lon", "size"]
    )
    writer.writerows(rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(buffer.getvalue())
    print(f"wrote {len(rows)} airports to {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate the dataset**

```bash
cd /Users/mikelse/kcgx && uv run --project . python tools/build_airports.py
```

Expected: `wrote 4737 airports to .../src/kcgx/data/airports.csv`
(a small drift in the count is fine — OurAirports changes). Confirm the
file is roughly 370 KB and starts with three `#` lines then the header.

- [ ] **Step 5: Write the failing dataset guard test**

Create `tests/test_airports.py`:

```python
"""Tests for the airport dataset and the search over it."""

from __future__ import annotations

from kcgx.airports import DATA_PATH


def test_the_committed_dataset_is_present_and_substantial():
    """A bad regeneration should fail loudly, not silently ship 12 airports."""
    text = DATA_PATH.read_text()
    assert text.startswith("#"), "the provenance header is the only record of how this was built"
    rows = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert len(rows) > 4000, f"only {len(rows)} rows — did the filter change?"
    assert rows[0].startswith("icao,iata,name,city,region,country,lat,lon,size")
```

- [ ] **Step 6: Run it to verify it fails**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airports.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kcgx.airports'`

- [ ] **Step 7: Create the minimal `airports.py` to satisfy it**

Create `src/kcgx/airports.py`:

```python
"""The airport dataset, and searching it.

Pure data: no Textual, no tmux, no network. Everything here is a function
of the committed CSV.
"""

from __future__ import annotations

from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "airports.csv"
```

- [ ] **Step 8: Run it to verify it passes**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airports.py -v
```

Expected: PASS

- [ ] **Step 9: Revert-check**

Temporarily rename `src/kcgx/data/airports.csv` to `airports.csv.bak`, run
the test, confirm it FAILS, then rename it back and confirm it PASSES.
A guard test that passes without its data is worthless.

- [ ] **Step 10: Commit**

```bash
cd /Users/mikelse/kcgx
git add pyproject.toml src/kcgx tools/build_airports.py tests/test_airports.py
git commit -m "feat(kcgx): add the kcgx package and a committed airport dataset

4,737 large and medium airports with ICAO codes, filtered from
OurAirports and committed so search needs no network and no API key.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The `Airport` model and loading

**Files:**
- Modify: `src/kcgx/airports.py`
- Test: `tests/test_airports.py`

**Interfaces:**
- Consumes: `kcgx.airports.DATA_PATH` (Task 1).
- Produces:
  - `Airport` — frozen dataclass with fields `icao: str, iata: str,
    name: str, city: str, region: str, country: str, lat: float,
    lon: float, size: str`, and a `where: str` property.
  - `load_airports(path: Path | None = None) -> list[Airport]`
  - `find(icao: str, airports: list[Airport]) -> Airport | None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_airports.py`:

```python
import pytest

from kcgx.airports import Airport, find, load_airports


@pytest.fixture(scope="module")
def airports():
    return load_airports()


def test_loading_skips_the_comment_header(airports):
    assert all(a.icao != "#" for a in airports)
    assert len(airports) > 4000


def test_known_airports_load_with_usable_coordinates(airports):
    pdx = find("KPDX", airports)
    assert pdx is not None
    assert pdx.name == "Portland International Airport"
    assert pdx.city == "Portland"
    assert pdx.region == "OR"
    assert pdx.country == "US"
    assert pdx.iata == "PDX"
    assert pdx.size == "large"
    assert pdx.lat == pytest.approx(45.5887, abs=0.01)
    assert pdx.lon == pytest.approx(-122.598, abs=0.01)


def test_coordinates_are_floats_not_strings(airports):
    """bin/kcgx interpolates these into a URL path; a stray quote breaks it."""
    pdx = find("KPDX", airports)
    assert isinstance(pdx.lat, float)
    assert isinstance(pdx.lon, float)


def test_find_is_case_insensitive_and_returns_none_for_unknown(airports):
    assert find("kpdx", airports).icao == "KPDX"
    assert find("ZZZZ", airports) is None
    assert find("", airports) is None


def test_where_uses_the_state_domestically_and_the_country_abroad():
    """'Portland, OR' is how a US pilot says it; 'London, PT-13' is nonsense."""
    us = Airport("KPDX", "PDX", "Portland International Airport", "Portland",
                 "OR", "US", 45.5887, -122.598, "large")
    pt = Airport("LPPR", "OPO", "Francisco Sá Carneiro Airport", "Porto",
                 "13", "PT", 41.24, -8.68, "large")
    assert us.where == "Portland, OR"
    assert pt.where == "Porto, PT"


def test_where_survives_a_missing_city():
    """125 rows in the dataset have no municipality."""
    a = Airport("XXXX", "", "Somewhere Field", "", "", "GB", 0.0, 0.0, "medium")
    assert a.where == "GB"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airports.py -v
```

Expected: FAIL — `ImportError: cannot import name 'Airport'`

- [ ] **Step 3: Implement the model and loader**

Append to `src/kcgx/airports.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airports.py -v
```

Expected: PASS (7 tests)

- [ ] **Step 5: Revert-check the `where` logic**

Change `_REGION_COUNTRIES` to `{"US", "CA", "PT"}` and confirm
`test_where_uses_the_state_domestically_and_the_country_abroad` FAILS.
Restore it and confirm PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/mikelse/kcgx
git add src/kcgx/airports.py tests/test_airports.py
git commit -m "feat(kcgx): load airports from the committed dataset

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Search ranking

The heart of the feature. Tiered and deterministic rather than fuzzy —
a personal tool benefits more from predictable ordering than from
cleverness.

**Files:**
- Modify: `src/kcgx/airports.py`
- Test: `tests/test_airports.py`

**Interfaces:**
- Consumes: `Airport`, `load_airports` (Task 2).
- Produces:
  - `normalize(text: str) -> str` — NFKD, combining marks dropped,
    lowercased, non-alphanumerics collapsed to single spaces, stripped.
  - `squash(text: str) -> str` — `normalize` with all spaces removed.
  - `search(query: str, airports: list[Airport], *, limit: int = 50) -> list[Airport]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_airports.py`:

```python
from kcgx.airports import normalize, search, squash


def test_normalize_folds_accents_dashes_and_case():
    assert normalize("Seattle–Tacoma International") == "seattle tacoma international"
    assert normalize("Francisco Sá Carneiro") == "francisco sa carneiro"
    assert normalize("Chicago O'Hare") == "chicago o hare"
    assert normalize("   KPDX  ") == "kpdx"


def test_squash_removes_the_separators_normalize_leaves():
    assert squash("Chicago O'Hare") == "chicagoohare"
    assert squash("Seattle–Tacoma") == "seattletacoma"


def test_an_exact_icao_always_ranks_first(airports):
    assert search("KORD", airports)[0].icao == "KORD"
    assert search("kord", airports)[0].icao == "KORD"


def test_an_exact_iata_ranks_first(airports):
    assert search("PDX", airports)[0].icao == "KPDX"


def test_a_prefix_matches_before_a_name_match(airports):
    results = search("KPD", airports)
    assert results[0].icao.startswith("KPD")


def test_a_city_name_finds_the_airport(airports):
    icaos = [a.icao for a in search("portland", airports)]
    assert "KPDX" in icaos
    assert "KPWM" in icaos, "Portland, Maine is a real answer to 'portland'"


def test_multiple_tokens_are_anded(airports):
    """'portland or' should separate Oregon from Maine."""
    icaos = [a.icao for a in search("portland or", airports)]
    assert "KPDX" in icaos
    assert "KPWM" not in icaos


def test_a_short_token_matches_a_word_not_a_fragment(airports):
    """The trap under the previous test.

    'or' is a substring of 'portland', so plain substring matching lets
    Portland, Maine satisfy the token 'or' and the AND above becomes
    meaningless. Tokens must match the *start of a word*.
    """
    icaos = [a.icao for a in search("or", airports)]
    assert "KPWM" not in icaos, "'or' matched inside the word 'Portland'"
    assert "KPDX" in icaos, "'or' should still match the region OR"


def test_a_dash_in_the_query_matches_an_en_dash_in_the_data(airports):
    assert "KSEA" in [a.icao for a in search("seattle-tacoma", airports)]


def test_a_squashed_query_matches_a_separated_name(airports):
    """Nobody types the space in O'Hare."""
    assert "KORD" in [a.icao for a in search("ohare", airports)]


def test_an_accented_name_is_reachable_without_the_accent(airports):
    assert "LPPR" in [a.icao for a in search("sa carneiro", airports)]


def test_large_airports_outrank_medium_ones_on_an_equal_match():
    fixture = [
        Airport("XMED", "", "Springfield Regional", "Springfield", "XX", "US",
                0.0, 0.0, "medium"),
        Airport("XBIG", "", "Springfield International", "Springfield", "XX", "US",
                0.0, 0.0, "large"),
    ]
    assert [a.icao for a in search("springfield", fixture)] == ["XBIG", "XMED"]


def test_no_match_returns_empty(airports):
    assert search("qqqqzzzz", airports) == []


def test_an_empty_query_lists_everything_large_first(airports):
    results = search("", airports, limit=10)
    assert len(results) == 10
    assert all(a.size == "large" for a in results), (
        "an empty picker should open on somewhere worth looking at"
    )


def test_limit_is_respected(airports):
    assert len(search("a", airports, limit=5)) == 5
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airports.py -v
```

Expected: FAIL — `ImportError: cannot import name 'normalize'`

- [ ] **Step 3: Implement normalisation and search**

Append to `src/kcgx/airports.py`:

```python
import unicodedata
from functools import lru_cache

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
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airports.py -v
```

Expected: PASS (21 tests)

- [ ] **Step 5: Check search is fast enough for per-keystroke filtering**

```bash
cd /Users/mikelse/kcgx && uv run --project . python -c "
import time
from kcgx.airports import load_airports, search
a = load_airports()
search('x', a)                      # warm the haystack cache
t = time.perf_counter()
for _ in range(20):
    search('portland', a)
print(f'{(time.perf_counter()-t)/20*1000:.1f} ms per search')
"
```

Expected: comfortably under 20 ms. If it is slower, the `lru_cache` on
`_haystack` is not being hit — check that `Airport` is still `frozen=True`
and therefore hashable.

- [ ] **Step 6: Revert-check the tiering**

In `_tier`, temporarily `return None` for tier 0 (exact ICAO). Confirm
`test_an_exact_icao_always_ranks_first` FAILS. Restore and confirm PASS.
Then temporarily drop the `or token in squashed` clause and confirm
`test_a_squashed_query_matches_a_separated_name` FAILS. Restore.

- [ ] **Step 7: Commit**

```bash
cd /Users/mikelse/kcgx
git add src/kcgx/airports.py tests/test_airports.py
git commit -m "feat(kcgx): tiered airport search over the committed dataset

Exact code, then code prefix, then all query tokens present in the name,
city, region or country. Accent- and separator-folded on both sides so
'seattle-tacoma' and 'ohare' both land.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The remembered airport

**Files:**
- Create: `src/kcgx/state.py`, `tests/test_airport_state.py`

**Interfaces:**
- Consumes: `squelch.config.load_config` (existing;
  `Config(icao: str = "KPDX", feed: str = "kpdx3_twr")`).
- Produces:
  - `STATE_PATH: Path` — `~/.local/state/kcgx/airport`
  - `read_airport(*, path: Path | None = None) -> str | None`
  - `write_airport(icao: str, *, path: Path | None = None) -> None`
  - `current_icao(*, path: Path | None = None, config_loader=load_config) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_airport_state.py`:

```python
"""Tests for the airport kcgx remembers between launches."""

from __future__ import annotations

from kcgx.state import current_icao, read_airport, write_airport
from squelch.config import Config


def test_write_then_read_round_trips(tmp_path):
    path = tmp_path / "airport"
    write_airport("KORD", path=path)
    assert read_airport(path=path) == "KORD"


def test_the_icao_is_stored_uppercase_and_trimmed(tmp_path):
    path = tmp_path / "airport"
    write_airport("  kord \n", path=path)
    assert read_airport(path=path) == "KORD"


def test_reading_a_missing_state_file_is_not_an_error(tmp_path):
    assert read_airport(path=tmp_path / "nope") is None


def test_reading_an_empty_state_file_is_not_an_error(tmp_path):
    path = tmp_path / "airport"
    path.write_text("\n")
    assert read_airport(path=path) is None


def test_writing_creates_the_parent_directory(tmp_path):
    path = tmp_path / "deep" / "deeper" / "airport"
    write_airport("KSEA", path=path)
    assert read_airport(path=path) == "KSEA"


def test_an_unwritable_state_file_does_not_raise(tmp_path):
    """Forgetting where you were is not a reason to refuse to switch."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory")
    write_airport("KSEA", path=blocker / "airport")  # must not raise


def test_the_state_file_wins_when_present(tmp_path):
    path = tmp_path / "airport"
    write_airport("KORD", path=path)
    assert current_icao(path=path, config_loader=lambda: Config(icao="KPDX")) == "KORD"


def test_the_squelch_config_is_the_first_run_default(tmp_path):
    assert current_icao(
        path=tmp_path / "nope", config_loader=lambda: Config(icao="KSEA")
    ) == "KSEA"


def test_a_broken_config_still_yields_an_airport(tmp_path):
    """An unusable squelch.toml must not stop the cockpit from opening."""
    def boom():
        raise ValueError("bad toml")

    assert current_icao(path=tmp_path / "nope", config_loader=boom) == "KPDX"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airport_state.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kcgx.state'`

- [ ] **Step 3: Implement `state.py`**

Create `src/kcgx/state.py`:

```python
"""The airport the cockpit reopens on.

One line, one ICAO. Coordinates are deliberately *not* stored: they are
re-resolved from the dataset at every launch, so a dataset update can
never leave the cockpit pointing at stale coordinates.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from squelch.config import Config, load_config

STATE_PATH = Path.home() / ".local" / "state" / "kcgx" / "airport"
FALLBACK_ICAO = "KPDX"


def read_airport(*, path: Path | None = None) -> str | None:
    path = STATE_PATH if path is None else path
    try:
        value = path.read_text().strip().upper()
    except OSError:
        return None
    return value or None


def write_airport(icao: str, *, path: Path | None = None) -> None:
    """Remember `icao`. Failing to is a lost convenience, not an error."""
    path = STATE_PATH if path is None else path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{icao.strip().upper()}\n")
    except OSError:
        pass


def current_icao(
    *,
    path: Path | None = None,
    config_loader: Callable[[], Config] = load_config,
) -> str:
    """Where the cockpit should point, most specific source first."""
    remembered = read_airport(path=path)
    if remembered:
        return remembered
    try:
        return config_loader().icao
    except Exception:
        # A malformed squelch.toml is squelch's problem to report; it is
        # not a reason for the launcher to refuse to pick an airport.
        return FALLBACK_ICAO
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airport_state.py -v
```

Expected: PASS (9 tests)

- [ ] **Step 5: Revert-check**

Remove the `except OSError: pass` from `write_airport` and confirm
`test_an_unwritable_state_file_does_not_raise` FAILS. Restore, confirm PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/mikelse/kcgx
git add src/kcgx/state.py tests/test_airport_state.py
git commit -m "feat(kcgx): remember the airport between launches

Stores the ICAO only; coordinates are re-resolved from the dataset so a
dataset update cannot leave stale coordinates behind.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The Textual picker

**Files:**
- Create: `src/kcgx/picker.py`, `tests/test_airport_picker.py`

**Interfaces:**
- Consumes: `Airport`, `search` (Tasks 2–3).
- Produces:
  - `fit(text: str, width: int) -> str` — pad or truncate with `…`
  - `row_text(airport: Airport, width: int) -> str`
  - `AirportPicker(airports: list[Airport], *, initial: str = "")` — a
    Textual `App`; `run()` returns `Airport | None`.
  - `POPUP_WIDTH = 64`, `POPUP_HEIGHT = 20`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_airport_picker.py`:

```python
"""Tests for the airport picker.

Capture uses the compositor, not screen.render_lines(): in Textual 8.2.8 a
container renders Blank and its children are painted separately, so
render_lines() reports blank fill for every child widget and every width
assertion below would pass vacuously.
"""

from __future__ import annotations

import pytest
from textual.geometry import Size

from kcgx.airports import Airport
from kcgx.picker import POPUP_HEIGHT, POPUP_WIDTH, AirportPicker, fit, row_text

SIZE = (POPUP_WIDTH, POPUP_HEIGHT)

AIRPORTS = [
    Airport("KPDX", "PDX", "Portland International Airport", "Portland",
            "OR", "US", 45.5887, -122.598, "large"),
    Airport("KTTD", "TTD", "Portland-Troutdale Airport", "Troutdale",
            "OR", "US", 45.5494, -122.401, "medium"),
    Airport("KORD", "ORD", "Chicago O'Hare International Airport", "Chicago",
            "IL", "US", 41.9786, -87.9048, "large"),
    Airport("KSEA", "SEA", "Seattle–Tacoma International Airport", "Seattle",
            "WA", "US", 47.4479, -122.310, "large"),
]


def rendered(app):
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


# -- row rendering ---------------------------------------------------------


def test_fit_pads_short_text_and_marks_real_cuts():
    assert fit("ab", 5) == "ab   "
    assert fit("abcdef", 4) == "abc…"
    assert fit("abcd", 4) == "abcd"
    assert fit("abc", 0) == ""


def test_a_row_carries_the_code_the_name_and_the_place():
    line = row_text(AIRPORTS[0], 58)
    assert line.startswith("KPDX")
    assert "Portland International" in line
    assert "Portland, OR" in line


def test_a_row_is_exactly_the_width_asked_for():
    for airport in AIRPORTS:
        assert len(row_text(airport, 58)) == 58


def test_a_long_name_is_cut_visibly_not_silently():
    long = Airport("XXXX", "", "A" * 90, "Nowhere", "ZZ", "US", 0.0, 0.0, "large")
    assert "…" in row_text(long, 58)


# -- the app ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_sees_mounted_widget_content():
    """Guards the capture helper itself against silently returning blank fill."""
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE):
        text, _ = rendered(app)
        assert any("KPDX" in line for line in text)


@pytest.mark.asyncio
async def test_it_opens_showing_everything():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE):
        joined = "\n".join(rendered(app)[0])
        assert "KPDX" in joined and "KORD" in joined


@pytest.mark.asyncio
async def test_typing_filters_the_list():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"portland")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "KPDX" in joined
        assert "KORD" not in joined, "typing must actually narrow the list"


@pytest.mark.asyncio
async def test_enter_returns_the_highlighted_airport():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"kord")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value is not None
    assert app.return_value.icao == "KORD"


@pytest.mark.asyncio
async def test_arrows_move_the_highlight_while_typing():
    """Focus stays in the input, so the app must forward up/down itself."""
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"portland")
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value.icao == "KTTD", (
        "down did not move the highlight off the first match"
    )


@pytest.mark.asyncio
async def test_escape_cancels_with_no_selection():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("escape")
        await pilot.pause()
    assert app.return_value is None


@pytest.mark.asyncio
async def test_enter_on_no_matches_does_not_select_anything():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"qqqqzz")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "no airports match" in joined.lower()
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running, "enter with nothing highlighted must not exit"
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_an_initial_query_prefilters():
    app = AirportPicker(AIRPORTS, initial="seattle")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "KSEA" in joined
        assert "KPDX" not in joined


@pytest.mark.asyncio
async def test_the_popup_never_overflows_its_width():
    app = AirportPicker(AIRPORTS)
    async with app.run_test(size=SIZE):
        _text, strips = rendered(app)
        assert all(s.cell_length == POPUP_WIDTH for s in strips)
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airport_picker.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kcgx.picker'`

- [ ] **Step 3: Implement the picker**

Create `src/kcgx/picker.py`:

```python
"""The airport picker: type, arrow, enter.

Sized for `tmux display-popup -w 64 -h 20`, which is where it actually
runs. The `fit` helper is deliberately a local copy rather than an import
from squelch.app -- kcgx drives squelch, it does not depend on squelch's
UI internals.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from kcgx.airports import Airport, search

POPUP_WIDTH = 64
POPUP_HEIGHT = 20

# Popup width less the border tmux draws and our own padding.
ROW_WIDTH = POPUP_WIDTH - 6
CODE_WIDTH = 4
PLACE_WIDTH = 18


def fit(text: str, width: int) -> str:
    """Pad to `width`, or truncate with a visible ellipsis."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def row_text(airport: Airport, width: int) -> str:
    """One line: code, name, place -- name yields the space."""
    name_width = max(0, width - CODE_WIDTH - PLACE_WIDTH - 2)
    return (
        f"{fit(airport.icao, CODE_WIDTH)} "
        f"{fit(airport.name, name_width)} "
        f"{fit(airport.where, PLACE_WIDTH)}"
    )


class AirportPicker(App[Airport | None]):
    CSS = """
    Screen { background: $surface; }
    #query { border: none; padding: 0 1; height: 3; }
    #results { border: none; padding: 0 1; height: 1fr; }
    #hint { color: $text-muted; padding: 0 1; height: 1; }
    """

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        # The input keeps focus so typing always filters; without priority
        # the Input would swallow these before the option list saw them.
        Binding("down", "move(1)", "down", show=False, priority=True),
        Binding("up", "move(-1)", "up", show=False, priority=True),
    ]

    def __init__(self, airports: list[Airport], *, initial: str = "") -> None:
        super().__init__()
        self._airports = airports
        self._initial = initial
        self._matches: list[Airport] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(placeholder="airport, city, or code", id="query")
            yield OptionList(id="results")
            yield Static("↑↓ select   ↵ go   esc cancel", id="hint")

    def on_mount(self) -> None:
        query = self.query_one("#query", Input)
        query.value = self._initial
        query.focus()
        self._refilter(self._initial)

    def _refilter(self, query: str) -> None:
        self._matches = search(query, self._airports)
        results = self.query_one("#results", OptionList)
        results.clear_options()
        if not self._matches:
            results.add_option(Option("no airports match", disabled=True))
            return
        results.add_options(
            [Option(row_text(a, ROW_WIDTH), id=a.icao) for a in self._matches]
        )
        results.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refilter(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._choose()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        self._choose(event.option_index)

    def _choose(self, index: int | None = None) -> None:
        if not self._matches:
            return
        if index is None:
            index = self.query_one("#results", OptionList).highlighted
        if index is None or not (0 <= index < len(self._matches)):
            return
        self.exit(self._matches[index])

    def action_move(self, delta: int) -> None:
        if not self._matches:
            return
        results = self.query_one("#results", OptionList)
        current = results.highlighted or 0
        results.highlighted = max(0, min(len(self._matches) - 1, current + delta))

    def action_cancel(self) -> None:
        self.exit(None)


def pick(airports: list[Airport], *, initial: str = "") -> Airport | None:
    """Run the picker and return the choice, or None if cancelled."""
    return AirportPicker(airports, initial=initial).run()
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_airport_picker.py -v
```

Expected: PASS (14 tests)

If `test_arrows_move_the_highlight_while_typing` fails, the `priority=True`
bindings are not winning over `Input`. Do not delete the test — it is
guarding the exact class of bug that froze feed selection at 20 feeds in
the multi-feed work (a focusable container quietly eating arrow keys).

- [ ] **Step 5: Revert-check**

Remove `priority=True` from both arrow bindings and confirm
`test_arrows_move_the_highlight_while_typing` FAILS. Restore, confirm PASS.
Then make `_refilter` ignore its `query` argument (always search `""`) and
confirm `test_typing_filters_the_list` FAILS. Restore.

- [ ] **Step 6: Look at it**

```bash
cd /Users/mikelse/kcgx && uv run --project . python -c "
from kcgx.airports import load_airports
from kcgx.picker import pick
print(pick(load_airports()))
"
```

Type `portland`, arrow down, press enter. Confirm it looks like the mockup
and returns a `KTTD` record. This is a real terminal check — the tests
cannot tell you whether it reads well.

- [ ] **Step 7: Commit**

```bash
cd /Users/mikelse/kcgx
git add src/kcgx/picker.py tests/test_airport_picker.py
git commit -m "feat(kcgx): a Textual airport picker sized for a tmux popup

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The `kcgx-airport` console script

The only interface between bash and Python. `bin/kcgx` never parses the
CSV; `src/kcgx/` never runs a tmux command.

**Files:**
- Create: `src/kcgx/__main__.py`, `tests/test_kcgx_airport_cli.py`

**Interfaces:**
- Consumes: `load_airports`, `find` (Task 2); `current_icao`,
  `write_airport` (Task 4); `pick` (Task 5).
- Produces:
  - `format_record(airport: Airport) -> str` — `icao\tlat\tlon\tlabel`
  - `emit(record: str, out: str | None) -> None`
  - `main(argv: list[str] | None = None, *, airports_loader=load_airports,
    picker=pick) -> int`
  - Exit codes: `0` chose something, `1` cancelled, `2` error.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kcgx_airport_cli.py`:

```python
"""Tests for the kcgx-airport console script.

This is the whole contract between bin/kcgx and the Python side, so the
record format is asserted precisely: bash splits it on tabs.
"""

from __future__ import annotations

from kcgx.__main__ import format_record, main
from kcgx.airports import Airport

PDX = Airport("KPDX", "PDX", "Portland International Airport", "Portland",
              "OR", "US", 45.5887, -122.598, "large")
ORD = Airport("KORD", "ORD", "Chicago O'Hare International Airport", "Chicago",
              "IL", "US", 41.9786, -87.9048, "large")
AIRPORTS = [PDX, ORD]


def run(argv, *, picker=None, **kwargs):
    return main(
        argv,
        airports_loader=lambda: AIRPORTS,
        picker=picker or (lambda airports, initial="": None),
        **kwargs,
    )


# -- the record format -----------------------------------------------------


def test_a_record_is_four_tab_separated_fields():
    fields = format_record(PDX).split("\t")
    assert len(fields) == 4
    assert fields[0] == "KPDX"
    assert float(fields[1]) == 45.5887
    assert float(fields[2]) == -122.598
    assert fields[3] == "Portland International Airport, Portland, OR"


def test_a_record_contains_no_tabs_inside_its_label():
    """bash reads this with IFS=$'\\t'; a tab in the label would shift fields."""
    assert format_record(ORD).count("\t") == 3


# -- resolve ---------------------------------------------------------------


def test_resolve_writes_the_current_airport(tmp_path, monkeypatch):
    import kcgx.__main__ as cli

    monkeypatch.setattr(cli, "current_icao", lambda: "KORD")
    out = tmp_path / "record"
    assert run(["resolve", "--out", str(out)]) == 0
    assert out.read_text().split("\t")[0] == "KORD"


def test_resolve_prints_to_stdout_without_out(capsys, monkeypatch):
    import kcgx.__main__ as cli

    monkeypatch.setattr(cli, "current_icao", lambda: "KPDX")
    assert run(["resolve"]) == 0
    assert capsys.readouterr().out.startswith("KPDX\t")


def test_resolve_fails_loudly_on_an_airport_not_in_the_dataset(capsys, monkeypatch):
    import kcgx.__main__ as cli

    monkeypatch.setattr(cli, "current_icao", lambda: "ZZZZ")
    assert run(["resolve"]) == 2
    assert "ZZZZ" in capsys.readouterr().err


# -- pick ------------------------------------------------------------------


def test_pick_with_an_exact_icao_never_draws_the_picker(tmp_path):
    def explode(airports, initial=""):
        raise AssertionError("the picker must not open for an exact code")

    out = tmp_path / "record"
    assert run(["pick", "KORD", "--out", str(out)], picker=explode) == 0
    assert out.read_text().startswith("KORD\t")


def test_pick_opens_the_picker_for_a_vague_query(tmp_path):
    seen = {}

    def picker(airports, initial=""):
        seen["initial"] = initial
        return ORD

    out = tmp_path / "record"
    assert run(["pick", "chicago", "--out", str(out)], picker=picker) == 0
    assert seen["initial"] == "chicago", "the query should prefilter the picker"
    assert out.read_text().startswith("KORD\t")


def test_cancelling_the_picker_exits_1_and_writes_nothing(tmp_path):
    out = tmp_path / "record"
    assert run(["pick", "--out", str(out)], picker=lambda a, initial="": None) == 1
    assert not out.exists(), "a cancelled pick must leave no record to act on"


def test_a_successful_pick_is_remembered(tmp_path, monkeypatch):
    import kcgx.__main__ as cli

    remembered = []
    monkeypatch.setattr(cli, "write_airport", lambda icao: remembered.append(icao))
    run(["pick", "KORD", "--out", str(tmp_path / "r")], picker=lambda a, initial="": None)
    assert remembered == ["KORD"]


def test_a_cancelled_pick_is_not_remembered(tmp_path, monkeypatch):
    import kcgx.__main__ as cli

    remembered = []
    monkeypatch.setattr(cli, "write_airport", lambda icao: remembered.append(icao))
    run(["pick", "--out", str(tmp_path / "r")], picker=lambda a, initial="": None)
    assert remembered == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_kcgx_airport_cli.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'kcgx.__main__'`

- [ ] **Step 3: Implement the console script**

Create `src/kcgx/__main__.py`:

```python
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

    write_airport(chosen.icao)
    emit(format_record(chosen), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_kcgx_airport_cli.py -v
```

Expected: PASS (10 tests)

- [ ] **Step 5: Check the real console script exists**

```bash
cd /Users/mikelse/kcgx && uv run --project . kcgx-airport resolve
```

Expected: a line like `KPDX	45.5887	-122.598	Portland International Airport, Portland, OR`

- [ ] **Step 6: Revert-check**

Make `main` call `write_airport` before the `if chosen is None: return 1`
guard, and confirm `test_a_cancelled_pick_is_not_remembered` FAILS.
Restore, confirm PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/mikelse/kcgx
git add src/kcgx/__main__.py tests/test_kcgx_airport_cli.py
git commit -m "feat(kcgx): kcgx-airport console script with resolve and pick

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: squelch must not play the wrong airport

Independent of Tasks 1–6, but must land before the launcher wiring so the
first end-to-end switch is correct rather than confidently wrong.

**Files:**
- Modify: `src/squelch/feeds.py`, `src/squelch/__main__.py`
- Test: `tests/test_main.py`, `tests/test_feeds.py`

**Interfaces:**
- Consumes: existing `Config`, `Feed`, `load_feeds`, `build_sessions`.
- Produces:
  - `squelch.feeds.COLD_FETCH_ATTEMPTS = 8`
  - `fetch_feeds(icao, fetch=None, *, cache_dir=None, get=None, sleep=time.sleep)`
  - `squelch.__main__.preferred_index(feeds: list[Feed]) -> int`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
# -- switching airports ----------------------------------------------------
#
# The cockpit can now retarget squelch at any airport, so a feed lookup
# that fails at KORD must not quietly fall back to a KPDX feed. Audio from
# the wrong airport under a header reading KORD is worse than silence.


def test_a_failed_lookup_at_a_new_airport_opens_nothing(tmp_path):
    def blocked(icao):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KORD", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert feeds == [], "kpdx3_twr is not a KORD feed"
    assert warnings and "KORD" in warnings[0]


def test_the_configured_feed_is_still_used_at_its_own_airport(tmp_path):
    def blocked(icao):
        raise RuntimeError("HTTP 403")

    warnings = []
    feeds = load_feeds(
        Config(icao="KPDX", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert [f.ident for f in feeds] == ["kpdx3_twr"]


def test_an_unreachable_listing_says_it_can_be_retried(tmp_path):
    def blocked(icao):
        raise RuntimeError("HTTP 403")

    warnings = []
    load_feeds(
        Config(icao="KORD", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=blocked,
        cache_dir=tmp_path,
    )
    assert "retry" in warnings[0].lower()


def test_an_airport_liveatc_does_not_cover_does_not_suggest_retrying(tmp_path):
    """Retrying a field with no feeds will never produce one."""
    from squelch.feeds import FeedError

    def empty(icao):
        raise FeedError("no feeds found on page")

    warnings = []
    feeds = load_feeds(
        Config(icao="KBDN", feed="kpdx3_twr"),
        warn=warnings.append,
        fetch=empty,
        cache_dir=tmp_path,
    )
    assert feeds == []
    assert "no feeds" in warnings[0].lower()
    assert "retry" not in warnings[0].lower()


# -- which feed comes up audible ------------------------------------------


def test_a_tower_feed_is_preferred_when_nothing_matches_the_config():
    """Arriving somewhere new should land on the interesting channel."""
    feeds = [
        Feed(ident="kord_atis", label="KORD ATIS"),
        Feed(ident="kord_gnd", label="KORD Ground"),
        Feed(ident="kord_twr", label="KORD Tower"),
    ]
    sessions = build_sessions(
        feeds,
        Config(icao="KORD", feed="kpdx3_twr"),
        events=None,
        session_factory=StubSession,
    )
    assert [s.feed.ident for s in sessions if not s.muted] == ["kord_twr"]


def test_the_first_feed_is_used_when_there_is_no_tower():
    feeds = [
        Feed(ident="kord_atis", label="KORD ATIS"),
        Feed(ident="kord_gnd", label="KORD Ground"),
    ]
    sessions = build_sessions(
        feeds,
        Config(icao="KORD", feed="kpdx3_twr"),
        events=None,
        session_factory=StubSession,
    )
    assert [s.feed.ident for s in sessions if not s.muted] == ["kord_atis"]
```

Append to `tests/test_feeds.py`:

```python
def test_a_first_visit_gets_more_coin_flips_than_a_revisit(tmp_path):
    """No cache means no fallback, so it is worth re-flipping more times."""
    import urllib.error

    from squelch.feeds import (
        COLD_FETCH_ATTEMPTS,
        FETCH_ATTEMPTS,
        Feed,
        fetch_feeds,
        write_cached_feeds,
    )

    attempts = []

    def always_blocked(url):
        attempts.append(url)
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    # Cold: no cache for KORD.
    attempts.clear()
    try:
        fetch_feeds("KORD", cache_dir=tmp_path, get=always_blocked,
                    sleep=lambda _s: None)
    except urllib.error.HTTPError:
        pass
    assert len(attempts) == COLD_FETCH_ATTEMPTS

    # Warm: a cache exists, so a failure is survivable.
    write_cached_feeds("KSEA", [Feed("ksea_twr", "KSEA Tower")], directory=tmp_path)
    attempts.clear()
    try:
        fetch_feeds("KSEA", cache_dir=tmp_path, get=always_blocked,
                    sleep=lambda _s: None)
    except urllib.error.HTTPError:
        pass
    assert len(attempts) == FETCH_ATTEMPTS
    assert COLD_FETCH_ATTEMPTS > FETCH_ATTEMPTS
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_main.py tests/test_feeds.py -v
```

Expected: FAIL — the new tests fail; the existing ones still pass.

- [ ] **Step 3: Add the cold-fetch escalation in `feeds.py`**

Replace the `FETCH_ATTEMPTS = 5` line's neighbourhood so it reads:

```python
CHALLENGE_STATUSES = frozenset({403, 429, 503})
FETCH_ATTEMPTS = 5
# A first visit to an airport has no cached list to fall back on, so an
# empty pane is the alternative to trying again. At roughly one request in
# four getting through, five attempts succeed about 76% of the time and
# eight about 90% -- worth a few extra seconds exactly once per airport.
COLD_FETCH_ATTEMPTS = 8
```

Replace `fetch_feeds` with:

```python
def fetch_feeds(
    icao: str,
    fetch: Fetcher | None = None,
    *,
    cache_dir: Path | None = None,
    get: Fetcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Feed]:
    if fetch is not None:
        return parse_airport_page(fetch(airport_url(icao)))
    attempts = (
        FETCH_ATTEMPTS
        if cached_age_seconds(icao, directory=cache_dir) is not None
        else COLD_FETCH_ATTEMPTS
    )
    return parse_airport_page(
        http_get_with_retry(
            airport_url(icao), get=get, sleep=sleep, attempts=attempts
        )
    )
```

- [ ] **Step 4: Fix the fallback and add tower preference in `squelch/__main__.py`**

Add above `load_feeds`:

```python
def _no_feeds(
    config: Config,
    warn: Callable[[str], None],
    reason: str,
    *,
    retryable: bool,
) -> list[Feed]:
    """What to open when the airport's feed list could not be had.

    The configured feed is only a sane fallback at its own airport. Since
    the cockpit can retarget squelch anywhere, falling back to kpdx3_twr at
    KORD would play Portland tower under a header reading KORD -- audio
    from the wrong airport is worse than an empty pane.
    """
    if config.feed and config.feed.lower().startswith(config.icao.lower()):
        warn(f"{config.icao} — {reason}; opening {config.feed}")
        return [Feed(ident=config.feed, label=config.feed)]
    tail = "; press f to retry" if retryable else ""
    warn(f"{config.icao} — {reason}{tail}")
    return []
```

Replace the body of `load_feeds` after the cache check with:

```python
    try:
        feeds = fetch(config.icao)
    except FeedError:
        # The page loaded and had no feeds on it. Retrying will not
        # conjure one, so do not suggest it.
        return _no_feeds(
            config, warn, "LiveATC has no feeds for this airport", retryable=False
        )
    except Exception as exc:
        stale = read_cached_feeds(config.icao, directory=cache_dir)
        if stale:
            days = (age or 0) / 86400
            warn(
                f"could not refresh the feed list for {config.icao} ({exc}) — "
                f"using the cached list from {days:.0f} day(s) ago"
            )
            return stale
        return _no_feeds(
            config,
            warn,
            f"could not reach LiveATC's listing ({exc})",
            retryable=True,
        )

    if not feeds:
        stale = read_cached_feeds(config.icao, directory=cache_dir)
        if stale:
            warn(f"no feeds listed for {config.icao} — using the cached list")
            return stale
        return _no_feeds(
            config, warn, "LiveATC has no feeds for this airport", retryable=False
        )

    write_cached_feeds(config.icao, feeds, directory=cache_dir)
    return feeds
```

Add `FeedError` to the `squelch.feeds` import list at the top of the file.

Add above `build_sessions`:

```python
def preferred_index(feeds: list[Feed]) -> int:
    """Which feed to leave audible when the configured one matched nothing.

    Tower is where the interesting traffic is; LiveATC's listing order is
    arbitrary and often opens on ATIS, which is a recorded loop.
    """
    for index, feed in enumerate(feeds):
        text = f"{feed.ident} {feed.label}".lower()
        if "twr" in text or "tower" in text:
            return index
    return 0
```

In `build_sessions`, replace the trailing block:

```python
    if sessions and all(s.muted for s in sessions):
        # The configured ident matched nothing this airport publishes.
        # Opening entirely silent reads as broken, so unmute the best guess.
        sessions[preferred_index(feeds)].muted = False
    return sessions
```

- [ ] **Step 5: Run the full suite**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest -q
```

Expected: all green, including the pre-existing
`test_load_feeds_falls_back_to_the_configured_feed_when_discovery_fails`,
which still passes because the exception text is kept in the message and
`kpdx3_twr` does start with `kpdx`.

- [ ] **Step 6: Revert-check**

Change `_no_feeds` to always return the configured feed regardless of ICAO
and confirm `test_a_failed_lookup_at_a_new_airport_opens_nothing` FAILS.
Restore, confirm PASS. Then make `preferred_index` always return `0` and
confirm `test_a_tower_feed_is_preferred_when_nothing_matches_the_config`
FAILS. Restore.

- [ ] **Step 7: Commit**

```bash
cd /Users/mikelse/kcgx
git add src/squelch tests/test_main.py tests/test_feeds.py
git commit -m "fix(squelch): never fall back to another airport's feed

The cockpit can now retarget squelch anywhere, so the configured-feed
fallback is only valid at its own airport; elsewhere it would play
Portland tower under a KORD header. Also distinguishes an unreachable
listing from an airport LiveATC does not cover, escalates retries on a
first visit, and prefers a tower feed on arrival.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Retarget the cockpit

**Files:**
- Modify: `bin/kcgx`, `kcgx.tmux.conf`, `tests/test_kcgx_launcher.py`

**Interfaces:**
- Consumes: `kcgx-airport resolve|pick --out FILE` (Task 6).
- Produces: `kcgx go [query]`; env seam `KCGX_AIRPORT_CMD`.

- [ ] **Step 1: Make the existing stand-ins tolerate appended flags**

In `tests/test_kcgx_launcher.py`, the pane commands now carry
`--site-lat`/`--icao`, and `sleep 300 --site-lat 45` is an error. Replace:

```python
# Stand-ins that sit still and exit cleanly when killed. `sh -c` is what
# makes them tolerate the flags kcgx now appends: the extra words land in
# $0/$1/... and are ignored.
FAKE_ADSB = "sh -c 'sleep 300'"
FAKE_SQUELCH = "sh -c 'sleep 300'"
```

Run the existing launcher tests to confirm they still pass:

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_kcgx_launcher.py -q
```

- [ ] **Step 2: Write the failing retarget tests**

Append to `tests/test_kcgx_launcher.py`:

```python
# -- airport retargeting ---------------------------------------------------


AIRPORT_STUB = """#!/bin/sh
# Stand-in for kcgx-airport. Writes a fixed record wherever --out points.
mode="$1"; shift
record="$KCGX_TEST_RECORD"
out=""
while [ $# -gt 0 ]; do
    case "$1" in
        --out) out="$2"; shift 2 ;;
        *) shift ;;
    esac
done
[ -n "$KCGX_TEST_FAIL" ] && exit "$KCGX_TEST_FAIL"
if [ -n "$out" ]; then printf '%s\\n' "$record" > "$out"; else printf '%s\\n' "$record"; fi
"""


@pytest.fixture
def airport_stub(tmp_path):
    path = tmp_path / "kcgx-airport-stub"
    path.write_text(AIRPORT_STUB)
    path.chmod(0o755)
    return path


def pane_command(tmux, session, index):
    return tmux(
        "display-message", "-p", "-t", f"={session}:cockpit.{index}",
        "#{pane_start_command}",
    ).stdout.strip()


def test_launch_points_both_panes_at_the_resolved_airport(
    cockpit, airport_stub
):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KORD\t41.9786\t-87.9048\tChicago O'Hare",
    )
    adsb = pane_command(tmux, session, 0)
    squelch = pane_command(tmux, session, 1)
    assert "--site-lat 41.9786" in adsb
    assert "--site-lon -87.9048" in adsb
    assert "--icao KORD" in squelch


def test_go_moves_both_panes_to_the_new_airport(cockpit, airport_stub):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    assert "--site-lat 45.5887" in pane_command(tmux, session, 0)

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KSEA\t47.4479\t-122.3102\tSeattle-Tacoma",
    )
    assert result.returncode == 0, result.stderr

    adsb = pane_command(tmux, session, 0)
    squelch = pane_command(tmux, session, 1)
    assert "--site-lat 47.4479" in adsb and "--site-lon -122.3102" in adsb
    assert "--icao KSEA" in squelch
    assert "45.5887" not in adsb, "the old airport is still on screen"


def test_launch_and_go_build_the_same_command(cockpit, airport_stub):
    """The two paths must not drift; that is how three earlier bugs happened."""
    run, tmux, session = cockpit
    record = "KSEA\t47.4479\t-122.3102\tSeattle-Tacoma"
    run(KCGX_AIRPORT_CMD=str(airport_stub), KCGX_TEST_RECORD=record)
    at_launch = (pane_command(tmux, session, 0), pane_command(tmux, session, 1))

    run(args=("go",), KCGX_AIRPORT_CMD=str(airport_stub), KCGX_TEST_RECORD=record)
    after_go = (pane_command(tmux, session, 0), pane_command(tmux, session, 1))

    assert at_launch == after_go


def test_a_cancelled_pick_leaves_the_cockpit_alone(cockpit, airport_stub):
    run, tmux, session = cockpit
    run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="KPDX\t45.5887\t-122.598\tPortland International",
    )
    before = pane_command(tmux, session, 0)

    result = run(
        args=("go",),
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="unused",
        KCGX_TEST_FAIL="1",
    )
    assert result.returncode == 0, "cancelling is not an error"
    assert pane_command(tmux, session, 0) == before


def test_go_without_a_running_cockpit_says_so(cockpit, airport_stub):
    run, _tmux, _session = cockpit
    result = run(args=("go",), KCGX_AIRPORT_CMD=str(airport_stub),
                 KCGX_TEST_RECORD="KSEA\t47.4\t-122.3\tSeattle")
    assert result.returncode != 0
    assert "not running" in result.stderr.lower()


def test_a_broken_resolver_still_opens_the_cockpit(cockpit, airport_stub):
    """A Python-side failure must not cost you the traffic display."""
    run, tmux, session = cockpit
    result = run(
        KCGX_AIRPORT_CMD=str(airport_stub),
        KCGX_TEST_RECORD="unused",
        KCGX_TEST_FAIL="2",
    )
    assert result.returncode == 0
    adsb = pane_command(tmux, session, 0)
    assert "--site-lat" not in adsb, "no coordinates means fall back to its config"
    assert "sleep 300" in adsb
```

> **Note for the implementer:** the `cockpit` fixture currently returns
> only `run` and `tmux`. Check its actual return; if it does not already
> yield the session name, extend it to `return run, tmux, session` and
> update the existing tests' unpacking accordingly. Do this as part of this
> step so the new tests can address panes by session name.

- [ ] **Step 3: Run to verify they fail**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_kcgx_launcher.py -v
```

Expected: the new tests FAIL (`unknown command go`, no `--site-lat`).

- [ ] **Step 4: Add the resolver and command builders to `bin/kcgx`**

After the `TMUX_CMD` / `tm` / `apply_config` block, add:

```bash
# The Python side is reached only through this one command, so bin/kcgx
# never parses the airport dataset and src/kcgx/ never runs a tmux command.
if [ -n "${KCGX_AIRPORT_CMD:-}" ]; then
    # Word-split deliberately: this is a test seam holding a whole command.
    # shellcheck disable=SC2206
    AIRPORT_CMD=($KCGX_AIRPORT_CMD)
else
    AIRPORT_CMD=(uv run --project "$REPO" kcgx-airport)
fi

ICAO="" LAT="" LON="" LABEL=""

# Fills ICAO/LAT/LON/LABEL from `kcgx-airport <mode> [query]`. Returns
# non-zero when the mode declined (a cancelled picker) or failed, leaving
# the four variables empty so callers can degrade instead of guessing.
airport_record() {
    local out status
    out="$(mktemp)" || return 1
    if ! "${AIRPORT_CMD[@]}" "$@" --out "$out" >/dev/null 2>&1; then
        status=$?
        rm -f "$out"
        return "$status"
    fi
    IFS=$'\t' read -r ICAO LAT LON LABEL < "$out" || true
    rm -f "$out"
    [ -n "$ICAO" ] && [ -n "$LAT" ] && [ -n "$LON" ]
}

# One spelling of each pane command, used by both the initial build and
# every retarget. A second spelling is how launch and switch drift apart.
adsb_cmd() {  # $1=lat $2=lon
    if [ -n "$1" ] && [ -n "$2" ]; then
        printf '%s --site-lat %s --site-lon %s' "$ADSB_CMD" "$1" "$2"
    else
        printf '%s' "$ADSB_CMD"
    fi
}

squelch_cmd() {  # $1=icao
    if [ -n "$1" ]; then
        printf '%s --icao %s' "$SQUELCH_CMD" "$1"
    else
        printf '%s' "$SQUELCH_CMD"
    fi
}

retarget() {  # $1=icao $2=lat $3=lon
    tm respawn-pane -k -t "=$SESSION:cockpit.0" "$(adsb_cmd "$2" "$3")"
    tm respawn-pane -k -t "=$SESSION:cockpit.1" "$(squelch_cmd "$1")"
}
```

Move the two existing `ADSB_CMD=` / `SQUELCH_CMD=` assignments up so they
sit above this block — they are now used by the functions.

- [ ] **Step 5: Add the `go` subcommand**

In the `case "${1:-}"` block, before the `-h | --help | help)` arm:

```bash
    go)
        shift
        if ! tm has-session -t "=$SESSION" 2>/dev/null; then
            die "not running. Open the cockpit first with: kcgx"
        fi
        if ! airport_record pick "$@"; then
            # Cancelled, or the picker failed. Either way the cockpit is
            # fine as it is; moving it would be worse than doing nothing.
            exit 0
        fi
        retarget "$ICAO" "$LAT" "$LON"
        printf 'kcgx: %s — %s\n' "$ICAO" "$LABEL"
        exit 0
        ;;
```

Update `usage()`:

```bash
usage() {
    cat <<'USAGE'
kcgx — open the cockpit: live traffic, ATC audio, a shell.

  kcgx             open the cockpit, or reattach to a running one
  kcgx go [query]  search for an airport and point both panes at it
  kcgx stop        shut the cockpit down
  kcgx --help      this

Drag any pane border with the mouse to resize. Ctrl-b then a opens the
airport search; Ctrl-b then r respawns a pane that has died.
USAGE
}
```

- [ ] **Step 6: Resolve the airport at launch**

Immediately before the `tm new-session` line, replacing the existing
`ADSB_CMD=`/`SQUELCH_CMD=` assignments there (they moved in Step 4):

```bash
# A resolver failure must not cost you the cockpit: both panes fall back to
# their own configuration, which is what they did before this existed.
if ! airport_record resolve; then
    ICAO="" LAT="" LON=""
fi
```

Then change the two build lines to use the builders:

```bash
tm new-session -d -s "$SESSION" -n cockpit -x "$cols" -y "$rows" "$(adsb_cmd "$LAT" "$LON")"
apply_config
tm split-window -h -l "$SQUELCH_COLS" -t "=$SESSION:cockpit.0" "$(squelch_cmd "$ICAO")"
```

- [ ] **Step 7: Bind the popup**

Append to `kcgx.tmux.conf`:

```
# prefix + a opens the airport search over the cockpit. display-popup -E
# closes the popup when the command exits, and the retarget happens inside
# it — a popup's pty is destroyed on close, so nothing it prints can be
# read by the caller.
bind a display-popup -E -w 64 -h 20 "kcgx go"
```

- [ ] **Step 8: Run the launcher tests**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest tests/test_kcgx_launcher.py -v
```

Expected: PASS, new and old.

- [ ] **Step 9: Revert-check the anti-drift test**

Change `retarget` to spell the adsb command inline as
`"$ADSB_CMD --site-lat $2 --site-lon $3"` instead of calling `adsb_cmd`,
then make `adsb_cmd` emit `--site-latitude` instead. Confirm
`test_launch_and_go_build_the_same_command` FAILS. Restore both.

- [ ] **Step 10: Try it for real**

```bash
kcgx stop; kcgx
```

Then inside the cockpit: `Ctrl-b a`, type `chicago`, enter. Confirm the
radar re-centres on O'Hare and squelch's header reads `KORD`. Then
`kcgx stop; kcgx` and confirm it reopens on KORD. Switch back with
`Ctrl-b a`, `kpdx`, enter.

- [ ] **Step 11: Commit**

```bash
cd /Users/mikelse/kcgx
git add bin/kcgx kcgx.tmux.conf tests/test_kcgx_launcher.py
git commit -m "feat(kcgx): search for an airport and retarget both panes

prefix + a opens a picker over the cockpit; kcgx go [query] does the same
from the shell pane. One spelling of each pane command serves both the
initial build and every retarget, so launch and switch cannot drift.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README**

```bash
cd /Users/mikelse/kcgx && cat README.md
```

- [ ] **Step 2: Document the feature**

Add a section in the style of the surrounding prose covering:

- `Ctrl-b a` opens the airport search over the cockpit; `kcgx go [query]`
  does the same from the shell pane, and `kcgx go KORD` skips the picker.
- Typing matches ICAO, IATA, name, city, region and country; accents and
  dashes are folded, so `seattle-tacoma` and `ohare` both work.
- The choice is remembered in `~/.local/state/kcgx/airport` and the cockpit
  reopens there.
- Neither `squelch.toml` nor `adsb-tui.toml` is modified; adsb-tui is
  retargeted with `--site-lat`/`--site-lon`, which also moves the
  airplanes.live query.
- Airports LiveATC does not cover show an empty squelch pane with a
  message. The radar still works everywhere.
- The dataset is `src/kcgx/data/airports.csv`, regenerated with
  `uv run --project . python tools/build_airports.py`.

- [ ] **Step 3: Run the whole suite one last time**

```bash
cd /Users/mikelse/kcgx && uv run --project . pytest -q
```

Expected: everything green. Roughly 153 + 60 tests.

- [ ] **Step 4: Commit**

```bash
cd /Users/mikelse/kcgx
git add README.md
git commit -m "docs: document airport search

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Notes

**Spec coverage** — every section of the spec maps to a task: dataset →
Task 1; search → Tasks 2–3; persistence → Task 4; picker → Task 5; entry
point → Task 6; error handling (cross-airport fallback, cold-fetch
attempts, tower preference) → Task 7; retarget and layout → Task 8;
out-of-scope items are absent by construction.

**Known deviation from the spec** — the spec's Entry point section was
amended during planning: the record goes to `--out` rather than stdout,
because Textual draws on stdout and `$(...)` would swallow the picker's
rendering.

**Verified at plan time** — the search algorithm in Task 3 was prototyped
against the real 4,737-row dataset and all thirteen of its planned
assertions pass, at 4.9 ms per search (well inside per-keystroke budget).
The two-module `uv_build` configuration in Task 1 and the data file's
availability next to the installed module were both confirmed to work with
the pinned backend. `--site-lat`/`--site-lon` were confirmed to drive the
data query, by pointing `url_template` at a local listener and observing a
request for `/point/41.979974/-87.909816/20`.

The word-anchored token rule (`SQUASH_MIN`) came out of that prototype: the
first draft used plain substring matching, under which `or` matches inside
`portland` and `search("portland or")` returns Portland, Maine — making the
AND across tokens silently useless. The test
`test_a_short_token_matches_a_word_not_a_fragment` exists to pin that down.

**Unverified at plan time** — that `tmux display-popup -E` gives Textual a
usable pty. `display-popup` allocates one, and the picker is checked
directly in a terminal at Task 5 Step 6, so a failure here is isolated to
Task 8 Step 10 and would be visible immediately.
