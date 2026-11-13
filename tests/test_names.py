"""Feed titles without the airport (phase G decision 19, Task 6).

The labels are LiveATC's, copied as literals from cached listings (no test
reads the cache); the last two rows of the table are made up, for the
airport's own name heading a title.
"""

from __future__ import annotations

import pytest

from kcgx.names import name_head, short_feed_name

AIRPORTS = {
    "KORD": {"icao": "KORD", "iata": "ORD", "name": "Chicago O'Hare International Airport", "where": "Chicago, IL"},
    "KPDX": {"icao": "KPDX", "iata": "PDX", "name": "Portland International Airport", "where": "Portland, OR"},
    "KSEA": {"icao": "KSEA", "iata": "SEA", "name": "Seattle–Tacoma International Airport", "where": "Seattle, WA"},
}


@pytest.mark.parametrize(
    "label, icao, expected",
    [
        ("Chicago Approach (10R/28C)", "KORD", "Approach (10R/28C)"),
        ("ZAU Chicago Center", "KORD", "ZAU Center"),
        ("KPDX Tower (Both)", "KPDX", "Tower (Both)"),
        ("Seattle Center", "KSEA", "Center"),
        ("ZSE Seattle Center", "KPDX", "ZSE Seattle Center"),
        ("Chicago", "KORD", "Chicago"),
        ("Chicago O'Hare Tower", "KORD", "Tower"),
        ("Seattle–Tacoma Ground", "KSEA", "Ground"),
    ],
)
def test_the_title_drops_the_airport(label, icao, expected):
    assert short_feed_name(label, **AIRPORTS[icao]) == expected


def test_case_is_ignored_and_spaces_are_tidied():
    assert short_feed_name("kpdx  PORTLAND   Tower", **AIRPORTS["KPDX"]) == "Tower"


def test_the_iata_goes_as_a_whole_word_only():
    kpdx = AIRPORTS["KPDX"]
    assert short_feed_name("PDX Ground", **kpdx) == "Ground"
    assert short_feed_name("PDXN Ground", **kpdx) == "PDXN Ground"


def test_the_airports_name_goes_only_where_it_heads_the_title():
    assert short_feed_name("Tower Chicago O'Hare", **AIRPORTS["KORD"]) == "Tower O'Hare"


def test_an_unknown_place_leaves_only_the_code_to_drop():
    assert short_feed_name("ZZZZ Tower", icao="ZZZZ") == "Tower"


@pytest.mark.parametrize(
    "name, head",
    [
        ("Chicago O'Hare International Airport", "Chicago O'Hare"),
        ("Seattle–Tacoma International Airport", "Seattle–Tacoma"),
        ("Boeing Field King County International Airport", "Boeing"),
        ("Hillsboro Airport", "Hillsboro"),
        ("Aurora Municipal Airport", "Aurora"),
        ("Rogue Valley Regional", "Rogue Valley"),
        ("Somewhere", "Somewhere"),
        ("International Airport", ""),
        ("", ""),
    ],
)
def test_the_name_head_runs_to_the_first_word_for_the_kind_of_field(name, head):
    assert name_head(name) == head
