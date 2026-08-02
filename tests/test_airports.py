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
