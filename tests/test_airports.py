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
