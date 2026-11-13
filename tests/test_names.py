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
    # Codes that are words (decision 19): dataset values, as literals.
    "KLAS": {"icao": "KLAS", "iata": "LAS", "name": "Harry Reid International Airport", "where": "Las Vegas, NV"},
    "KSAN": {"icao": "KSAN", "iata": "SAN", "name": "San Diego International Airport", "where": "San Diego, CA"},
    "KAND": {"icao": "KAND", "iata": "AND", "name": "Anderson Regional Airport", "where": "Anderson, SC"},
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
        # A code that is a word is no code in the city's words or in prose.
        ("Las Vegas Approach", "KLAS", "Approach"),
        ("SoCal Approach (San Diego)", "KSAN", "SoCal Approach"),
        ("Ground (Ramp) and Tower", "KAND", "Ground (Ramp) and Tower"),
        ("LAS Tower", "KLAS", "Tower"),
        ("KAND AND Tower", "KAND", "Tower"),
    ],
)
def test_the_title_drops_the_airport(label, icao, expected):
    assert short_feed_name(label, **AIRPORTS[icao]) == expected


def test_the_city_and_name_match_in_any_case_and_spaces_are_tidied():
    assert short_feed_name("KPDX  PORTLAND   Tower", **AIRPORTS["KPDX"]) == "Tower"
    assert short_feed_name("SEATTLE-TACOMA Ground", **AIRPORTS["KSEA"]) == "Ground"


def test_the_codes_match_only_in_capitals():
    assert short_feed_name("kpdx Tower", **AIRPORTS["KPDX"]) == "kpdx Tower"
    assert short_feed_name("Pdx Ground", **AIRPORTS["KPDX"]) == "Pdx Ground"
    assert short_feed_name("Las Vegas Approach", icao="KLAS", iata="LAS") == "Las Vegas Approach"


@pytest.mark.parametrize("dash", ["-", "\u2013", "\u2014", "\u2212"])
def test_every_dash_is_the_same_dash(dash):
    assert short_feed_name(f"Seattle{dash}Tacoma Ground", **AIRPORTS["KSEA"]) == "Ground"
    assert short_feed_name(f"Tower {dash} Portland", **AIRPORTS["KPDX"]) == "Tower"


def test_a_code_joined_to_a_word_by_a_dash_is_part_of_a_name_and_stays():
    """`SEA-TAC` is the airport's nickname: SEA is the IATA, but TAC is no
    code, and taking SEA alone would leave `TAC Ground`. A dash with no
    space joins words, so the code is not a whole word there."""
    assert short_feed_name("SEA-TAC Ground", **AIRPORTS["KSEA"]) == "SEA-TAC Ground"
    assert short_feed_name("SEA - Ground", **AIRPORTS["KSEA"]) == "Ground"


@pytest.mark.parametrize(
    "label, icao, expected",
    [
        ("Tower - Portland", "KPDX", "Tower"),
        ("Portland / Tower", "KPDX", "Tower"),
        ("Tower (Portland)", "KPDX", "Tower"),
        ("Tower [ PDX ]", "KPDX", "Tower"),
        ("Tower - Portland - Ground", "KPDX", "Tower - Ground"),
        ("Tower (Portland - North)", "KPDX", "Tower (North)"),
        ("Approach ( )", "KPDX", "Approach"),
        ("PDX - Portland", "KPDX", "PDX - Portland"),
    ],
)
def test_dangling_dashes_slashes_and_empty_brackets_are_tidied(label, icao, expected):
    assert short_feed_name(label, **AIRPORTS[icao]) == expected


def test_the_icao_goes_before_the_airports_name_is_looked_for():
    assert short_feed_name("KSEA Seattle–Tacoma Ground", **AIRPORTS["KSEA"]) == "Ground"
    assert short_feed_name("KORD Chicago O'Hare Tower", **AIRPORTS["KORD"]) == "Tower"


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
