"""Tests for the airport dataset and the search over it."""

from __future__ import annotations

import pytest

from kcgx.airports import DATA_PATH, Airport, find, load_airports, normalize, search, squash


def test_the_committed_dataset_is_present_and_substantial():
    """A bad regeneration should fail loudly, not silently ship 12 airports."""
    text = DATA_PATH.read_text()
    assert text.startswith("#"), "the provenance header is the only record of how this was built"
    rows = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert len(rows) > 4000, f"only {len(rows)} rows — did the filter change?"
    assert rows[0].startswith("icao,iata,name,city,region,country,lat,lon,size")


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
    """The ICAO tiebreak deliberately opposes size here: if _order stopped
    ranking by size, alphabetical order alone would return XAAA first and
    this test would catch it."""
    fixture = [
        Airport("XAAA", "", "Springfield Regional", "Springfield", "XX", "US",
                0.0, 0.0, "medium"),
        Airport("XZZZ", "", "Springfield International", "Springfield", "XX", "US",
                0.0, 0.0, "large"),
    ]
    assert [a.icao for a in search("springfield", fixture)] == ["XZZZ", "XAAA"]


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
