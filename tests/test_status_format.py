"""Tests for the status pane's two lines.

These are pure functions on purpose: everything the pane decides to show is
decided here, where it can be checked without a terminal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kcgx.airports import Airport
from kcgx.status import (
    CONTENT_WIDTH,
    PICKER_HINT,
    PICKER_HINT_SHORT,
    airport_line,
    clock_text,
    fit,
    hint_for_width,
)

PDX = Airport("KPDX", "PDX", "Portland International Airport", "Portland",
              "OR", "US", 45.5887, -122.598, "large")

PDT = timezone(timedelta(hours=-7), "PDT")
UTC_NOON = datetime(2026, 8, 2, 19, 55, tzinfo=timezone.utc)
LOCAL_NOON = UTC_NOON.astimezone(PDT)


def test_fit_pads_short_text_and_marks_real_cuts():
    assert fit("ab", 5) == "ab   "
    assert fit("abcdef", 4) == "abc…"
    assert fit("abcd", 4) == "abcd"
    assert fit("abc", 0) == ""


# -- line 1 ----------------------------------------------------------------


def test_the_airport_line_carries_the_code_and_the_name():
    line = airport_line(PDX, "KPDX", CONTENT_WIDTH)
    assert line.startswith("KPDX")
    assert "Portland International Airport" in line


def test_the_airport_line_is_exactly_the_width_asked_for():
    assert len(airport_line(PDX, "KPDX", CONTENT_WIDTH)) == CONTENT_WIDTH


def test_a_long_name_is_cut_visibly():
    long = Airport("XXXX", "", "A" * 90, "Nowhere", "ZZ", "US", 0.0, 0.0, "large")
    assert "…" in airport_line(long, "XXXX", CONTENT_WIDTH)


def test_an_airport_missing_from_the_dataset_still_shows_its_code():
    """The airport-search work made an unknown ICAO survivable; so does this."""
    line = airport_line(None, "ZZZZ", CONTENT_WIDTH)
    assert line.startswith("ZZZZ")
    assert len(line) == CONTENT_WIDTH


# -- line 2 ----------------------------------------------------------------


def test_the_clock_shows_zulu_then_local():
    text = clock_text(UTC_NOON, LOCAL_NOON)
    assert text.startswith("1955Z")
    assert "12:55" in text
    assert "PDT" in text


def test_zulu_is_four_digits_and_a_z():
    """'1955Z' is what ATC says; '19:55Z' is not."""
    assert clock_text(UTC_NOON, LOCAL_NOON).split()[0] == "1955Z"


def test_midnight_zulu_keeps_its_leading_zeros():
    utc = datetime(2026, 8, 2, 0, 5, tzinfo=timezone.utc)
    assert clock_text(utc, utc.astimezone(PDT)).startswith("0005Z")


def test_the_hint_is_shown_in_full_when_it_fits():
    assert hint_for_width(len(PICKER_HINT)) == PICKER_HINT
    assert hint_for_width(CONTENT_WIDTH) == PICKER_HINT


def test_the_hint_degrades_rather_than_pushing_the_clock_off():
    """The clocks win; the keybinding still works without the words."""
    assert hint_for_width(len(PICKER_HINT) - 1) == PICKER_HINT_SHORT
    assert hint_for_width(1) == PICKER_HINT_SHORT


def test_both_line_two_fields_fit_the_real_width():
    clocks = clock_text(UTC_NOON, LOCAL_NOON)
    hint = hint_for_width(CONTENT_WIDTH - len(clocks) - 1)
    assert hint == PICKER_HINT, "at 46 columns the full hint should fit"
    assert len(clocks) + 1 + len(hint) <= CONTENT_WIDTH
