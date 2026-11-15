"""The tracks table, phase G Task 8: the columns chosen from the title bar,
a row of filters under the header that the radar follows too, the sort as a
setting every tab shares, the rank the radar shades by, and a header that
stays as the table scrolls.

Browser tests against the demo server, in Chromium and then WebKit.
"""

from __future__ import annotations

import pytest

from kcgx.prefs import DEFAULTS, SCHEMA
from page_fixtures import *  # noqa: F403  (fixtures and helpers)
from page_fixtures import (
    box_of, frames, hold_traffic, on_screen, pixel, plane, pref_is, radar_debug, rows, set_prefs, spy_on_sends,
    wait_for_traffic,
)

pytestmark = pytest.mark.browser

NAMES = list(SCHEMA["track_cols"].names)
TITLES = {
    "CALLSIGN": "CALLSIGN", "TYPE": "TYPE", "REG": "REG", "ALT": "ALT FT", "VS": "V/S FPM", "GS": "GS KT",
    "TRK": "TRK", "DIST": "DIST NM", "BRG": "BRG", "SQWK": "SQWK", "HEX": "HEX",
    "CAT": "CAT", "AGE": "AGE S", "LAT": "LAT", "LON": "LON",
}


def head(tab):
    return tab.eval_on_selector_all("#tracks-head th", "ths => ths.map(th => th.textContent)")


def hexes(tab):
    return [row["hex"] for row in rows(tab)]


def wait_for_hexes(tab, expected):
    tab.wait_for_function(
        "want => [...document.querySelectorAll('#tracks-body tr')].map(tr => tr.dataset.hex).join() === want.join()",
        arg=list(expected),
    )


def text_filter(key):
    return f"#tracks-filters input[data-key={key}]"


def number_filter(key, bound):
    return f"#tracks-filters input[data-key={key}][data-bound={bound}]"


def checklist(tab):
    """The checklist's buttons and which of them are pressed."""
    return tab.eval_on_selector_all(
        "#tracks-columns button",
        "bs => bs.map(b => [b.dataset.key, b.getAttribute('aria-pressed') === 'true'])",
    )


def ranks(tab):
    return tab.evaluate("Object.fromEntries(window.kcgx.store.state.rank)")


def sorted_by(tab, key):
    """The aria-sort of the column titled for `key`, and of every other."""
    return tab.eval_on_selector_all(
        "#tracks-head th", "ths => ths.map(th => [th.textContent, th.getAttribute('aria-sort')])"
    )


def wait_for_sort(tab, key, direction):
    tab.wait_for_selector(f"#tracks-head th[aria-sort={direction}]:has(button:text-is('{TITLES[key]}'))")


def column_figures(tab, key):
    """One column of the table as the figures it sorts by."""
    index = head(tab).index(TITLES[key])
    return [
        0.0 if row["cells"][index] == "GND" else float(row["cells"][index]) if row["cells"][index] else float("-inf")
        for row in rows(tab)
    ]


# Three aircraft east, north and west of the airport, by distance r1, r2, r3.
THREE = (
    plane("r2", 0, 10, label="UAL22", type="B739", dist=10.0, alt=12000),
    plane("r1", 5, 0, label="DAL1388", type="A321", dist=5.0, alt=3000),
    plane("r3", -20, 0, label="N1DAL", type="C172", dist=20.0, alt="GND"),
)


# -- the columns ---------------------------------------------------------------


def test_the_header_shows_exactly_track_cols_in_the_schema_order(page):
    hold_traffic(page, *THREE)
    page.evaluate("window.kcgx.send({t: 'prefs', track_cols: ['LON', 'CALLSIGN', 'REG']})")
    pref_is(page, "track_cols", ["CALLSIGN", "REG", "LON"])
    page.wait_for_function("document.querySelectorAll('#tracks-head th').length === 3")
    assert head(page) == ["CALLSIGN", "REG", "LON"]
    assert page.eval_on_selector_all("#tracks-filters td", "tds => tds.length") == 3
    assert all(len(row["cells"]) == 3 for row in rows(page))
    set_prefs(page, track_cols=DEFAULTS["track_cols"])
    assert head(page) == ["CALLSIGN", "TYPE", "ALT FT", "GS KT", "TRK", "DIST NM", "SQWK"]


def test_the_columns_button_opens_a_checklist_that_round_trips_track_cols(page, other):
    page.wait_for_selector("#open-columns[aria-expanded=false]")
    page.click("#open-columns")
    page.wait_for_selector("#tracks-columns", state="visible")
    page.wait_for_selector("#open-columns[aria-expanded=true]")
    assert checklist(page) == [[name, name in DEFAULTS["track_cols"]] for name in NAMES]
    page.click("#tracks-columns button[data-key=REG]")
    with_reg = [name for name in NAMES if name in DEFAULTS["track_cols"] or name == "REG"]
    pref_is(page, "track_cols", with_reg)
    page.wait_for_selector("#tracks-columns button[data-key=REG][aria-pressed=true]")
    # The checklist stays open for the next, and a second tab shows the same.
    assert page.is_visible("#tracks-columns")
    page.click("#tracks-columns button[data-key=CAT]")
    pref_is(page, "track_cols", [name for name in NAMES if name in with_reg or name == "CAT"])
    pref_is(other, "track_cols", [name for name in NAMES if name in with_reg or name == "CAT"])
    other.wait_for_function("[...document.querySelectorAll('#tracks-head th')].some(th => th.textContent === 'CAT')")
    assert "REG" in head(other)
    page.click("#tracks-columns button[data-key=REG]")
    page.click("#tracks-columns button[data-key=CAT]")
    pref_is(page, "track_cols", DEFAULTS["track_cols"])
    page.keyboard.press("Escape")
    page.wait_for_selector("#tracks-columns", state="hidden")
    page.wait_for_selector("#open-columns[aria-expanded=false]")


def test_the_last_column_cannot_be_unchecked(page):
    set_prefs(page, track_cols=["DIST"])
    page.click("#open-columns")
    page.wait_for_selector("#tracks-columns button[data-key=DIST][aria-pressed=true]:disabled")
    assert head(page) == ["DIST NM"]


def test_an_empty_checklist_falls_back_to_the_callsign_and_says_so(page):
    set_prefs(page, track_cols=[])
    assert head(page) == ["CALLSIGN"]
    page.click("#open-columns")
    page.wait_for_selector("#tracks-columns button[data-key=CALLSIGN][aria-pressed=true]:disabled")
    assert checklist(page) == [[name, name == "CALLSIGN"] for name in NAMES]
    # The next box checked adds to what is shown, not to the empty list.
    page.click("#tracks-columns button[data-key=REG]")
    pref_is(page, "track_cols", ["CALLSIGN", "REG"])


def test_a_first_cell_with_nothing_to_say_shows_the_callsign_muted(page):
    hold_traffic(
        page,
        plane("r1", 5, 0, label="DAL1388", reg="N101DQ", dist=5.0),
        plane("r2", 0, 10, label="UAL22", dist=10.0),
        plane("r3", -20, 0, label="", dist=20.0),
    )
    set_prefs(page, track_cols=["REG", "ALT"])
    wait_for_hexes(page, ["r1", "r2", "r3"])
    first = page.eval_on_selector_all(
        "#tracks-body tr",
        """trs => trs.map(tr => { const b = tr.querySelector("td:first-child button"), r = b.getBoundingClientRect();
            const ch = parseFloat(getComputedStyle(b).fontSize) * 0.5;
            return { text: b.textContent, standIn: b.classList.contains("stand-in"), colour: getComputedStyle(b).color,
                     w: r.width, h: r.height, row: tr.getBoundingClientRect().height, ch }; })""",
    )
    assert [(f["text"], f["standIn"]) for f in first] == [("N101DQ", False), ("UAL22", True), ("—", True)]
    assert first[1]["colour"] != first[0]["colour"]
    assert first[1]["colour"] == page.evaluate("getComputedStyle(document.querySelector('.muted')).color")
    for f in first:
        assert f["w"] >= 2 * f["ch"] - 0.5 and f["h"] >= f["row"] - 1.5, f
    page.click('#tracks-body tr[data-hex="r3"] td:first-child button')
    page.wait_for_selector('#tracks-body tr.focused[data-hex="r3"]')
    assert hexes(page)[0] == "r3"


def test_with_the_callsign_hidden_the_first_cell_still_focuses(page):
    hold_traffic(page, *THREE)
    set_prefs(page, track_cols=["ALT", "DIST"])
    page.click('#tracks-body tr[data-hex="r3"] td:first-child button')
    page.wait_for_selector('#tracks-body tr.focused[data-hex="r3"]')
    assert hexes(page)[0] == "r3"


def test_the_checklist_opens_below_its_button_when_there_is_no_room_above(page):
    page.set_viewport_size({"width": 390, "height": 844})
    # Room below the page, so its last pane's title bar can be scrolled up near the top.
    page.evaluate("document.body.append(Object.assign(document.createElement('div'), {style: 'height: 1200px'}))")
    page.evaluate("scrollBy(0, document.getElementById('open-columns').getBoundingClientRect().top - 20)")
    button = box_of(page, "#open-columns")
    assert 0 <= button["y"] < 60, button
    page.click("#open-columns")
    page.wait_for_selector("#tracks-columns", state="visible")
    pop = page.eval_on_selector("#tracks-columns", "e => e.getBoundingClientRect().toJSON()")
    assert pop["top"] >= button["y"] + button["height"], (pop, button)
    assert pop["left"] >= 0 and pop["right"] <= 390 and pop["bottom"] <= 844, pop
    # It closes when the page scrolls, the button moving away from it ...
    page.evaluate("scrollBy(0, -200)")
    page.wait_for_selector("#tracks-columns", state="hidden")
    page.wait_for_selector("#open-columns[aria-expanded=false]")
    # ... and when the window changes size.
    page.click("#open-columns")
    page.wait_for_selector("#tracks-columns", state="visible")
    page.set_viewport_size({"width": 400, "height": 844})
    page.wait_for_selector("#tracks-columns", state="hidden")


def test_the_checklist_still_opens_above_its_button_where_there_is_room(page):
    page.click("#open-columns")
    page.wait_for_selector("#tracks-columns", state="visible")
    button = box_of(page, "#open-columns")
    pop = page.eval_on_selector("#tracks-columns", "e => e.getBoundingClientRect().toJSON()")
    assert pop["bottom"] <= button["y"] and pop["top"] >= 0, (pop, button)
    assert abs(pop["right"] - (button["x"] + button["width"])) <= 1, (pop, button)
    # Scrolling its own list does not close it.
    page.eval_on_selector("#tracks-columns", "e => e.dispatchEvent(new Event('scroll'))")
    page.wait_for_timeout(100)
    assert page.is_visible("#tracks-columns")


# -- filters --------------------------------------------------------------------


def test_the_filter_cells_are_data_cells_sticky_and_opaque(page):
    cells = page.eval_on_selector_all(
        "#tracks-filters > *",
        "cs => cs.map(c => [c.tagName, getComputedStyle(c).position, getComputedStyle(c).backgroundColor])",
    )
    assert cells and all(cell == ["TD", "sticky", "rgb(0, 0, 0)"] for cell in cells), cells
    labels = page.eval_on_selector_all("#tracks-filters input", "is => is.map(i => i.getAttribute('aria-label'))")
    assert labels and all(labels), labels


def test_a_columns_change_from_another_tab_keeps_the_box_being_typed_in(page, other):
    hold_traffic(page, *THREE)
    page.click(text_filter("CALLSIGN"))
    page.keyboard.type("da")
    page.keyboard.press("ArrowLeft")
    page.evaluate("window.oldBox = document.activeElement")
    other.evaluate("window.kcgx.send({t: 'prefs', track_cols: [...window.kcgx.store.state.prefs.track_cols, 'REG']})")
    page.wait_for_function("[...document.querySelectorAll('#tracks-head th')].some(th => th.textContent === 'REG')")
    assert page.evaluate("document.activeElement !== window.oldBox")  # the row was built again
    now = page.evaluate(
        "(({dataset: d, value, selectionStart: s}) => [d.key, d.bound || null, value, s])(document.activeElement)"
    )
    assert now == ["CALLSIGN", None, "da", 1]
    page.keyboard.type("x")
    assert page.input_value(text_filter("CALLSIGN")) == "dxa"
    # A number box keeps its bound too.
    page.click(number_filter("ALT", "max"))
    page.keyboard.type("50")
    other.evaluate("window.kcgx.send({t: 'prefs', track_cols: window.kcgx.store.state.prefs.track_cols.filter(c => c !== 'REG')})")
    page.wait_for_function("![...document.querySelectorAll('#tracks-head th')].some(th => th.textContent === 'REG')")
    assert page.evaluate("[document.activeElement.dataset.key, document.activeElement.dataset.bound]") == ["ALT", "max"]


def on_the_radar(tab):
    return sorted(hit["hex"] for hit in radar_debug(tab)["hits"])


def wait_for_radar(tab, expected):
    tab.wait_for_function(
        "want => window.kcgx.radar.debug().hits.map(h => h.hex).sort().join() === want.join()",
        arg=sorted(expected),
    )


def test_a_text_filter_matches_a_substring_in_any_case(page):
    hold_traffic(page, *THREE)
    page.fill(text_filter("CALLSIGN"), "dal")
    wait_for_hexes(page, ["r1", "r3"])
    page.fill(text_filter("TYPE"), "a3")
    wait_for_hexes(page, ["r1"])
    page.fill(text_filter("CALLSIGN"), "")
    page.fill(text_filter("TYPE"), "")
    wait_for_hexes(page, ["r1", "r2", "r3"])


def test_a_number_filter_takes_a_minimum_and_a_maximum(page):
    hold_traffic(page, *THREE, plane("r4", 0, -30, label="NOALT", dist=30.0, alt=None))
    every = ["r1", "r2", "r3", "r4"]
    wait_for_hexes(page, every)
    # GND is 0, and an aircraft that reports nothing is left out once a bound is set.
    page.fill(number_filter("ALT", "min"), "0")
    page.fill(number_filter("ALT", "max"), "5000")
    wait_for_hexes(page, ["r1", "r3"])
    page.fill(number_filter("ALT", "min"), "")
    wait_for_hexes(page, ["r1", "r3"])
    page.fill(number_filter("ALT", "max"), "")
    page.fill(number_filter("ALT", "min"), "10000")
    wait_for_hexes(page, ["r2"])
    page.fill(number_filter("ALT", "min"), "")
    wait_for_hexes(page, every)
    page.fill(number_filter("ALT", "max"), "gnd")
    wait_for_hexes(page, ["r3"])
    page.fill(number_filter("ALT", "max"), "")
    page.fill(number_filter("DIST", "min"), "6")
    page.fill(number_filter("DIST", "max"), "25")
    wait_for_hexes(page, ["r2", "r3"])
    # Something that is not a figure sets no bound, and says so.
    page.fill(number_filter("DIST", "max"), "far")
    wait_for_hexes(page, ["r2", "r3", "r4"])
    assert page.get_attribute(number_filter("DIST", "max"), "aria-invalid") == "true"


def test_clear_empties_every_filter(page):
    hold_traffic(page, *THREE)
    page.fill(text_filter("CALLSIGN"), "dal")
    page.fill(number_filter("ALT", "max"), "5000")
    wait_for_hexes(page, ["r1", "r3"])
    page.click("#tracks-clear")
    wait_for_hexes(page, ["r1", "r2", "r3"])
    values = page.eval_on_selector_all("#tracks-filters input", "is => is.map(i => i.value)")
    assert values and all(value == "" for value in values)
    assert page.is_disabled("#tracks-clear")
    assert page.text_content("#tracks-empty") and page.is_hidden("#tracks-empty")


def test_filters_are_the_pages_own_and_gone_on_a_reload(page):
    hold_traffic(page, *THREE)
    spy_on_sends(page)
    page.fill(text_filter("CALLSIGN"), "dal")
    page.fill(number_filter("ALT", "max"), "5000")
    wait_for_hexes(page, ["r1", "r3"])
    assert page.evaluate("window.sent") == []
    page.fill(text_filter("CALLSIGN"), "zzz")
    page.wait_for_selector("#tracks-empty:text-is('NO TRAFFIC MATCHES THE FILTERS')")
    page.reload()
    page.wait_for_selector(".feed.expanded")
    values = page.eval_on_selector_all("#tracks-filters input", "is => is.map(i => i.value)")
    assert values and all(value == "" for value in values)


# -- the filters on the radar ------------------------------------------------------


def hidden(tab):
    return sorted(tab.evaluate("[...window.kcgx.store.state.hidden]"))


def test_what_the_filters_hide_is_left_off_the_radar_and_cannot_be_clicked(page):
    wait_for_traffic(page)
    hold_traffic(page, *THREE)
    wait_for_radar(page, ["r1", "r2", "r3"])
    assert hidden(page) == []
    where = next(hit for hit in radar_debug(page)["hits"] if hit["hex"] == "r2")
    page.evaluate(
        """() => { window.hid = 0;
                   window.kcgx.store.subscribe(kind => { if (kind === "hidden") window.hid += 1; }); }"""
    )
    page.fill(text_filter("CALLSIGN"), "dal")
    wait_for_hexes(page, ["r1", "r3"])
    wait_for_radar(page, ["r1", "r3"])
    assert hidden(page) == ["r2"]
    assert page.evaluate("window.hid") == 1
    debug = radar_debug(page)
    assert "r2" not in debug["tag_order"] and "r2" not in debug["line_order"]
    page.wait_for_function("document.getElementById('radar-tracks').textContent === '2 TRACKS'")
    # Where it was is a place now: a click there focuses nothing.
    page.mouse.click(*on_screen(page, where["x"], where["y"]))
    frames(page)
    assert page.evaluate("import('/static/js/focus.js').then(({ focus }) => focus.hex)") is None
    # A filter that matches nothing leaves the radar empty.
    page.fill(text_filter("TYPE"), "zzz")
    wait_for_radar(page, [])
    assert hidden(page) == ["r1", "r2", "r3"]
    # CLEAR puts every one back.
    page.click("#tracks-clear")
    wait_for_radar(page, ["r1", "r2", "r3"])
    assert hidden(page) == []
    page.wait_for_function("document.getElementById('radar-tracks').textContent === '3 TRACKS'")


def test_a_number_filter_hides_on_the_radar_as_in_the_table(page):
    hold_traffic(page, *THREE)
    page.fill(number_filter("ALT", "max"), "5000")
    wait_for_hexes(page, ["r1", "r3"])
    wait_for_radar(page, ["r1", "r3"])
    # Traffic that arrives later is judged by the same filters.
    hold_traffic(page, *THREE, plane("r4", 0, -30, label="LOW1", dist=30.0, alt=2000), plane("r5", 0, 30, alt=30000),
                 drawn=["r1", "r3", "r4"])
    wait_for_hexes(page, ["r1", "r3", "r4"])
    wait_for_radar(page, ["r1", "r3", "r4"])
    assert hidden(page) == ["r2", "r5"]


def test_the_focused_aircraft_stays_on_the_radar_whatever_the_filters(page):
    hold_traffic(page, *THREE)
    page.click('#tracks-body tr[data-hex="r2"] .callsign')
    page.wait_for_selector('#tracks-body tr.focused[data-hex="r2"]')
    page.fill(text_filter("CALLSIGN"), "dal")
    wait_for_hexes(page, ["r2", "r1", "r3"])
    wait_for_radar(page, ["r1", "r2", "r3"])
    assert hidden(page) == []
    # Unfocused, it is filtered like the rest.
    page.click('#tracks-body tr[data-hex="r2"] .callsign')
    wait_for_hexes(page, ["r1", "r3"])
    wait_for_radar(page, ["r1", "r3"])


def test_the_filters_are_this_tabs_radar_alone(page, other):
    hold_traffic(page, *THREE)
    hold_traffic(other, *THREE)
    page.fill(text_filter("CALLSIGN"), "dal")
    wait_for_radar(page, ["r1", "r3"])
    wait_for_radar(other, ["r1", "r2", "r3"])
    assert hidden(other) == []


def test_the_focused_aircraft_leads_and_passes_every_filter(page):
    hold_traffic(page, *THREE)
    page.click('#tracks-body tr[data-hex="r3"] .callsign')
    page.wait_for_selector('#tracks-body tr.focused[data-hex="r3"]')
    wait_for_hexes(page, ["r3", "r1", "r2"])
    page.fill(text_filter("CALLSIGN"), "ual")
    wait_for_hexes(page, ["r3", "r2"])
    page.fill(number_filter("ALT", "min"), "50000")
    wait_for_hexes(page, ["r3"])
    assert rows(page)[0]["focused"]


# -- the sort -----------------------------------------------------------------------


def test_a_header_sends_the_sort_and_a_second_tab_sorts_the_same(page, other):
    page.wait_for_selector("#tracks-body tr")
    wait_for_sort(page, "DIST", "ascending")
    spy_on_sends(page)
    page.click("#tracks-head button:text-is('ALT FT')")
    for tab in (page, other):
        wait_for_sort(tab, "ALT", "ascending")
    assert page.evaluate("window.sent") == [{"t": "prefs", "track_sort": "ALT", "track_desc": False}]
    other.wait_for_selector("#tracks-body tr")
    alts = column_figures(other, "ALT")
    assert alts == sorted(alts)
    page.click("#tracks-head button:text-is('ALT FT')")
    for tab in (page, other):
        wait_for_sort(tab, "ALT", "descending")
    assert page.evaluate("window.sent")[-1] == {"t": "prefs", "track_sort": "ALT", "track_desc": True}
    alts = column_figures(other, "ALT")
    assert alts == sorted(alts, reverse=True)
    assert [s for _, s in sorted_by(other, "ALT")].count("none") == len(head(other)) - 1


def test_a_sort_by_a_hidden_column_still_orders_the_rows(page):
    hold_traffic(page, *THREE)
    set_prefs(page, track_cols=["CALLSIGN"], track_sort="ALT", track_desc=True)
    wait_for_hexes(page, ["r2", "r1", "r3"])
    assert [s for _, s in sorted_by(page, "ALT")] == ["none"]


def test_a_sort_by_a_hidden_column_is_named_in_the_title_bar(page):
    set_prefs(page, track_cols=["CALLSIGN"], track_sort="ALT", track_desc=True)
    page.wait_for_selector("#tracks-sort:text-is('SORT ALT FT ▼')")
    assert page.is_visible("#tracks-sort")
    assert page.eval_on_selector("#tracks-sort", "e => e.closest('.tracks-tools') !== null && e.matches('.muted.small')")
    set_prefs(page, track_desc=False)
    page.wait_for_selector("#tracks-sort:text-is('SORT ALT FT ▲')")
    set_prefs(page, track_cols=["CALLSIGN", "ALT"])
    page.wait_for_selector("#tracks-sort", state="hidden")
    set_prefs(page, track_cols=["CALLSIGN"], track_sort="CALLSIGN")
    page.wait_for_selector("#tracks-sort", state="hidden")


# -- the rank -------------------------------------------------------------------------


def test_the_rank_follows_the_sort_of_the_rows_shown_with_the_focus_first(page):
    page.evaluate(
        """() => { window.rankMap = window.kcgx.store.state.rank; window.ranked = 0;
                   window.kcgx.store.subscribe(kind => { if (kind === "rank") window.ranked += 1; }); }"""
    )
    hold_traffic(page, *THREE)
    page.wait_for_function("Object.keys(Object.fromEntries(window.kcgx.store.state.rank)).sort().join() === 'r1,r2,r3'")
    assert ranks(page) == {"r1": 0, "r2": 0.5, "r3": 1}
    assert page.evaluate("window.ranked") >= 1
    set_prefs(page, track_desc=True)
    page.wait_for_function("window.kcgx.store.state.rank.get('r3') === 0")
    assert ranks(page) == {"r3": 0, "r2": 0.5, "r1": 1}
    # Filtered, the rows shown are ranked among themselves, so the radar
    # shades what it shows from first to last.
    page.fill(text_filter("CALLSIGN"), "dal")
    wait_for_hexes(page, ["r3", "r1"])
    page.wait_for_function("window.kcgx.store.state.rank.size === 2")
    assert ranks(page) == {"r3": 0, "r1": 1}
    # The focus is first.
    page.click('#tracks-body tr[data-hex="r1"] .callsign')
    page.wait_for_function("window.kcgx.store.state.rank.get('r1') === 0")
    assert ranks(page) == {"r1": 0, "r3": 1}
    page.click("#tracks-clear")
    page.wait_for_function("window.kcgx.store.state.rank.size === 3")
    assert ranks(page) == {"r1": 0, "r3": 0.5, "r2": 1}
    # The same Map all along, changed in place.
    assert page.evaluate("window.rankMap === window.kcgx.store.state.rank")
    hold_traffic(page, plane("solo", 4, 4))
    page.wait_for_function("window.kcgx.store.state.rank.size === 1")
    assert ranks(page) == {"solo": 0}


# -- the header stays ------------------------------------------------------------------


def test_in_one_column_the_table_scrolls_in_its_pane_and_the_header_stays(page):
    page.set_viewport_size({"width": 820, "height": 1000})
    many = [plane(f"s{n:03}", east=(n % 20) - 10, north=(n // 20) - 5, dist=n / 10) for n in range(200)]
    hold_traffic(page, *many)
    page.wait_for_function("document.querySelectorAll('#tracks-body tr').length === 200")
    size = page.eval_on_selector(".tracks-body", "e => [e.clientHeight, e.scrollHeight]")
    assert size[0] <= 700 + 1 and size[1] > size[0], size
    scrolled = page.eval_on_selector(".tracks-body", "e => { e.scrollTop = 500; return e.scrollTop; }")
    assert scrolled == 500
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    body = page.eval_on_selector(".tracks-body", "e => e.getBoundingClientRect().toJSON()")
    th = page.eval_on_selector("#tracks-head th", "e => e.getBoundingClientRect().toJSON()")
    filters = page.eval_on_selector("#tracks-filters td", "e => e.getBoundingClientRect().toJSON()")
    assert abs(th["top"] - body["top"]) <= 1, (th, body)
    assert abs(filters["top"] - th["bottom"]) <= 1, (filters, th)


def test_scrolled_down_the_header_stays_on_top_and_hides_the_rows(page):
    set_prefs(page, display="OFF")  # no scanlines over the pixels read
    many = [plane(f"s{n:03}", east=(n % 20) - 10, north=(n // 20) - 5, dist=n / 10) for n in range(200)]
    hold_traffic(page, *many)
    page.wait_for_function("document.querySelectorAll('#tracks-body tr').length === 200")
    scrolled = page.eval_on_selector(".tracks-body", "e => { e.scrollTop = 500; return e.scrollTop; }")
    assert scrolled == 500
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    body = page.eval_on_selector(".tracks-body", "e => e.getBoundingClientRect().toJSON()")
    th = page.eval_on_selector("#tracks-head th", "e => e.getBoundingClientRect().toJSON()")
    filters = page.eval_on_selector("#tracks-filters td", "e => e.getBoundingClientRect().toJSON()")
    assert abs(th["top"] - body["top"]) <= 1, (th, body)
    assert abs(filters["top"] - th["bottom"]) <= 1, (filters, th)
    background = page.eval_on_selector("#tracks-head th", "e => getComputedStyle(e).backgroundColor")
    assert background == "rgb(0, 0, 0)"
    # A row's rule passes under the header every row's height: down the
    # header's left padding, no pixel of it shows through. (The filter row's
    # own rule is its last pixel or two, by engine.)
    x = int(th["left"]) + 2
    for y in range(int(th["top"]) + 1, int(filters["bottom"]) - 3):
        assert pixel(page, x, y) == (0, 0, 0), y
    # And the rows are there, under it: a rule shows just below.
    below = [pixel(page, x, y) for y in range(int(filters["bottom"]) + 1, int(filters["bottom"]) + 24)]
    assert any(p != (0, 0, 0) for p in below), below


# -- the pane's height and its fold (Task 9) --------------------------------------------------
#
# tracks_pct is the tracks row, the pane and the gap above it, as a percent of
# the page's content box (the window's height, or the page's least, less its
# padding). UI zoom (prefs ui_zoom) is CSS zoom on .page; it is simulated
# here as the CHROME lane sets it, zoom on .page and its height 100 %.

# An element's box in the window's px in either engine: getBoundingClientRect
# is in the window's px in Chromium and in the element's own under a zoomed
# ancestor in WebKit; offsetWidth is in the element's own in both.
WINDOW_BOX = """sel => { const el = document.querySelector(sel), r = el.getBoundingClientRect();
    let k = 1; for (let e = el; e; e = e.parentElement) k *= parseFloat(getComputedStyle(e).zoom) || 1;
    const s = el.offsetWidth ? r.width / el.offsetWidth : 1, f = Math.abs(s - k) < Math.abs(s - 1) ? 1 : k;
    return { left: r.left * f, top: r.top * f, right: r.right * f, bottom: r.bottom * f,
             width: r.width * f, height: r.height * f }; }"""

PANES = {"radar": ".screen-radar", "freq": ".screen-freq", "tracks": ".screen-tracks", "log": ".screen-log"}


def window_box(tab, selector):
    return tab.evaluate(WINDOW_BOX, selector)


def panes(tab):
    return {name: window_box(tab, selector) for name, selector in PANES.items()
            if tab.eval_on_selector(selector, "e => e.getClientRects().length > 0")}


def settle(tab):
    tab.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


def zoom_page(tab, zoom):
    if zoom != 1:
        tab.evaluate("k => { const p = document.querySelector('.page'); p.style.zoom = String(k); p.style.height = '100%'; }", zoom)
    settle(tab)


def content_px(tab):
    """The page's content box's height, in the window's px."""
    return tab.evaluate(
        """() => { const p = document.querySelector('.page'), s = getComputedStyle(p);
                   return (p.clientHeight - parseFloat(s.paddingTop) - parseFloat(s.paddingBottom)) * (parseFloat(s.zoom) || 1); }"""
    )


def grab(tab):
    """Press on the middle of the grip; returns where."""
    grip = window_box(tab, "#tracks-grip")
    x, y = grip["left"] + grip["width"] / 2, grip["top"] + grip["height"] / 2
    tab.mouse.move(x, y)
    tab.mouse.down()
    return x, y


def wait_for_sent(tab, count=1):
    tab.wait_for_function("n => window.sent.length >= n", arg=count)
    return tab.evaluate("window.sent")


@pytest.mark.parametrize("zoom", [1, 1.5])
def test_dragging_the_top_edge_up_100_px_makes_tracks_100_px_taller_and_reaches_a_second_tab(page, other, zoom):
    for tab in (page, other):
        tab.set_viewport_size({"width": 1440, "height": 1000})
        zoom_page(tab, zoom)
    before = panes(page)
    content = content_px(page)
    spy_on_sends(page)
    x, y = grab(page)
    page.mouse.move(x, y - 100, steps=8)
    settle(page)
    during = panes(page)
    assert abs(during["tracks"]["height"] - before["tracks"]["height"] - 100) <= 2, (before, during)
    assert abs(before["radar"]["height"] - during["radar"]["height"] - 100) <= 2, (before, during)
    assert abs(during["tracks"]["bottom"] - before["tracks"]["bottom"]) <= 1
    assert abs(during["freq"]["bottom"] - during["tracks"]["bottom"]) <= 1
    assert page.evaluate("window.sent") == []  # a drag previews here, and sends on release
    page.mouse.up()
    expected = round(24 + 100 / content * 100)
    assert wait_for_sent(page) == [{"t": "prefs", "tracks_pct": expected}]
    for tab in (page, other):
        pref_is(tab, "tracks_pct", expected)
        tab.wait_for_selector(f"#tracks-grip[aria-valuenow='{expected}']")
        settle(tab)
    after, there = panes(page), panes(other)
    # Whole percents: the release lands within half of one of where it was dropped.
    assert abs(after["tracks"]["height"] - during["tracks"]["height"]) <= content / 200 + 1, (during, after)
    assert abs(after["tracks"]["height"] - there["tracks"]["height"]) <= 1, (after, there)
    assert abs(after["freq"]["bottom"] - after["tracks"]["bottom"]) <= 1


def test_in_a_tall_window_the_drag_stops_at_10_and_80_percent(page):
    # Tall enough that 80 % leaves the other rows their room, and 10 % holds
    # the header, the filter row and two rows of the table.
    page.set_viewport_size({"width": 1440, "height": 1700})
    hold_traffic(page, *THREE)
    settle(page)
    content = content_px(page)
    spy_on_sends(page)
    x, _ = grab(page)
    page.mouse.move(x, 2, steps=6)
    settle(page)
    row = window_box(page, ".screen-tracks")["height"] + 10  # the row is the pane and the gap above it
    assert abs(row - 0.8 * content) <= 2, (row, content)
    page.mouse.up()
    assert wait_for_sent(page) == [{"t": "prefs", "tracks_pct": 80}]
    pref_is(page, "tracks_pct", 80)
    x, _ = grab(page)
    page.mouse.move(x, 1698, steps=6)
    settle(page)
    row = window_box(page, ".screen-tracks")["height"] + 10
    assert abs(row - 0.1 * content) <= 2, (row, content)
    page.mouse.up()
    assert wait_for_sent(page, 2)[-1] == {"t": "prefs", "tracks_pct": 10}
    pref_is(page, "tracks_pct", 10)


def radar_row(tab):
    """The radar's own row, under the airport status's: the radar's bottom less the status's."""
    shown = panes(tab)
    return shown["radar"]["bottom"] - window_box(tab, ".screen-status")["bottom"]


def no_overflow(tab, height, why):
    assert tab.evaluate("document.documentElement.scrollHeight") <= height, why
    assert tab.evaluate("document.documentElement.scrollWidth") <= tab.evaluate("innerWidth"), why
    assert radar_row(tab) >= 48 - 1, (why, radar_row(tab))  # the radar row's floor (cockpit.css)


@pytest.mark.parametrize("size", [(1440, 900), (1280, 720)])
@pytest.mark.parametrize("lamps, teletype", [(False, False), (True, False), (False, True), (True, True)])
def test_at_its_tallest_the_pane_leaves_the_other_rows_their_room(page, size, lamps, teletype):
    width, height = size
    page.set_viewport_size({"width": width, "height": height})
    set_prefs(page, lamps=lamps, teletype=teletype)
    settle(page)
    content = content_px(page)
    spy_on_sends(page)
    x, _ = grab(page)
    page.mouse.move(x, 2, steps=6)
    settle(page)
    no_overflow(page, height, "dragged")
    # As tall as fits: the radar's row is at its floor, within a whole percent.
    assert radar_row(page) <= 48 + content / 100 + 2, radar_row(page)
    page.mouse.up()
    most = wait_for_sent(page)[-1]["tracks_pct"]
    assert most < 80, most
    pref_is(page, "tracks_pct", most)
    page.wait_for_selector(f"#tracks-grip[aria-valuenow='{most}']")
    settle(page)
    no_overflow(page, height, "released")
    # End goes as far, and an arrow key no farther.
    set_prefs(page, tracks_pct=24)
    page.evaluate("window.sent = []")
    page.focus("#tracks-grip")
    page.keyboard.press("End")
    assert wait_for_sent(page) == [{"t": "prefs", "tracks_pct": most}]
    pref_is(page, "tracks_pct", most)
    page.keyboard.press("ArrowUp")
    page.keyboard.press("PageUp")
    page.wait_for_timeout(200)
    assert page.evaluate("window.sent") == [{"t": "prefs", "tracks_pct": most}]
    # A stored 80, from a taller window, overflows no window either.
    set_prefs(page, tracks_pct=80)
    settle(page)
    no_overflow(page, height, "stored 80")


@pytest.mark.parametrize("height", [900, 720])
def test_at_its_shortest_the_pane_shows_the_header_the_filters_and_two_rows(page, height):
    page.set_viewport_size({"width": 1440, "height": height})
    hold_traffic(page, *THREE)
    settle(page)
    content = content_px(page)
    spy_on_sends(page)
    x, _ = grab(page)
    page.mouse.move(x, height - 2, steps=6)
    settle(page)

    def two_rows_show():
        scroller = window_box(page, "#tracks-scroll")
        second = window_box(page, "#tracks-body tr:nth-child(2)")
        head = window_box(page, "#tracks-head")
        assert head["top"] >= scroller["top"] - 0.5, (head, scroller)
        assert second["bottom"] <= scroller["bottom"] + 0.5, (second, scroller)
        # And no more than a percent besides: the floor is theirs, not 10 %'s.
        assert scroller["bottom"] - second["bottom"] <= content / 100 + 3, (second, scroller)

    two_rows_show()
    page.mouse.up()
    least = wait_for_sent(page)[-1]["tracks_pct"]
    assert least > 10, least
    pref_is(page, "tracks_pct", least)
    settle(page)
    two_rows_show()
    # An arrow key goes no lower; Home goes as low.
    page.evaluate("window.sent = []")
    page.focus("#tracks-grip")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("PageDown")
    page.wait_for_timeout(200)
    assert page.evaluate("window.sent") == []
    set_prefs(page, tracks_pct=50)
    page.evaluate("window.sent = []")
    page.keyboard.press("Home")
    assert wait_for_sent(page) == [{"t": "prefs", "tracks_pct": least}]
    pref_is(page, "tracks_pct", least)


def test_page_keys_move_the_grip_10_percent_and_home_and_end_to_its_ends(page):
    page.set_viewport_size({"width": 1440, "height": 1700})
    hold_traffic(page, *THREE)
    settle(page)
    spy_on_sends(page)
    page.focus("#tracks-grip")
    page.keyboard.press("PageUp")
    pref_is(page, "tracks_pct", 34)
    page.keyboard.press("PageDown")
    page.keyboard.press("PageDown")
    pref_is(page, "tracks_pct", 14)
    page.keyboard.press("End")
    pref_is(page, "tracks_pct", 80)
    page.keyboard.press("Home")
    pref_is(page, "tracks_pct", 10)
    page.wait_for_selector("#tracks-grip[aria-valuenow='10']")
    assert [m["tracks_pct"] for m in page.evaluate("window.sent")] == [34, 24, 14, 80, 10]


def test_escape_during_a_drag_puts_the_pane_back_and_sends_nothing(page):
    before = panes(page)
    spy_on_sends(page)
    x, y = grab(page)
    page.mouse.move(x, y - 100, steps=6)
    settle(page)
    assert panes(page)["tracks"]["height"] > before["tracks"]["height"] + 90
    page.keyboard.press("Escape")
    settle(page)
    assert abs(panes(page)["tracks"]["height"] - before["tracks"]["height"]) <= 1
    assert page.get_attribute("#tracks-grip", "aria-valuenow") == "24"
    assert not page.eval_on_selector("#tracks-grip", "g => g.classList.contains('dragging')")
    # The pointer is let go of: moving it and releasing changes nothing.
    page.mouse.move(x, y - 200, steps=4)
    page.mouse.up()
    page.wait_for_timeout(200)
    assert page.evaluate("window.sent") == []
    assert abs(panes(page)["tracks"]["height"] - before["tracks"]["height"]) <= 1
    pref_is(page, "tracks_pct", 24)


# What is sent goes nowhere: as if the server never answered.
SWALLOW = "() => { window.sent = []; WebSocket.prototype.send = function (data) { window.sent.push(JSON.parse(data)); }; }"
# The socket is closed, as connection.js sees it: it drops what it is given.
CLOSE = """() => { window.readyState = Object.getOwnPropertyDescriptor(WebSocket.prototype, 'readyState');
                   Object.defineProperty(WebSocket.prototype, 'readyState', { configurable: true, get: () => 3 }); }"""
REOPEN = "() => Object.defineProperty(WebSocket.prototype, 'readyState', window.readyState)"


def drag_by(tab, dy):
    x, y = grab(tab)
    tab.mouse.move(x, y + dy, steps=6)
    tab.mouse.up()
    settle(tab)


def test_a_release_that_sends_nothing_shows_the_server_s_value(page):
    before = panes(page)["tracks"]["height"]
    content = content_px(page)
    # The socket closed: connection.js drops the release's message.
    page.evaluate(CLOSE)
    drag_by(page, -100)
    assert page.get_attribute("#tracks-grip", "aria-valuenow") == "24"
    assert abs(panes(page)["tracks"]["height"] - before) <= 1
    page.evaluate(REOPEN)
    # Sent and not answered, a release shows what it sent...
    page.evaluate(SWALLOW)
    drag_by(page, -100)
    held = int(page.get_attribute("#tracks-grip", "aria-valuenow"))
    assert held > 24 and page.evaluate("window.sent") == [{"t": "prefs", "tracks_pct": held}]
    # ...until one at the server's value, which sends nothing and shows it.
    drag_by(page, -(24 - held) * content / 100)
    assert page.evaluate("window.sent") == [{"t": "prefs", "tracks_pct": held}]
    assert page.get_attribute("#tracks-grip", "aria-valuenow") == "24"
    assert abs(panes(page)["tracks"]["height"] - before) <= 1


def test_a_key_that_sends_nothing_shows_the_server_s_value(page):
    before = panes(page)["tracks"]["height"]
    page.evaluate(SWALLOW)
    # A release sent and not answered: the pane shows it, at the most.
    x, _ = grab(page)
    page.mouse.move(x, 2, steps=6)
    page.mouse.up()
    held = int(page.get_attribute("#tracks-grip", "aria-valuenow"))
    assert held > 24
    # An arrow key at the most sends nothing, and the server's value shows.
    page.focus("#tracks-grip")
    page.keyboard.press("ArrowUp")
    assert page.evaluate("window.sent") == [{"t": "prefs", "tracks_pct": held}]
    assert page.get_attribute("#tracks-grip", "aria-valuenow") == "24"
    settle(page)
    assert abs(panes(page)["tracks"]["height"] - before) <= 1
    # Again from a release held, with the socket closed: the key's message is dropped.
    drag_by(page, -100)
    assert int(page.get_attribute("#tracks-grip", "aria-valuenow")) > 24
    page.evaluate(CLOSE)
    page.keyboard.press("ArrowUp")
    assert page.get_attribute("#tracks-grip", "aria-valuenow") == "24"
    page.evaluate(REOPEN)
    # And what the dropped key asked for is not built on: the next asks for 26.
    page.evaluate("window.sent = []")
    page.keyboard.press("ArrowUp")
    assert page.evaluate("window.sent") == [{"t": "prefs", "tracks_pct": 26}]


@pytest.mark.parametrize("lines", [0, 40])
def test_folded_with_the_teletype_both_title_bars_are_level_and_whole(page, lines):
    set_prefs(page, teletype=True)
    page.evaluate(
        """n => { document.getElementById('log').replaceChildren();
                  for (let i = 0; i < n; i++) window.kcgx.store.apply({t: 'message', z: '1200Z', text: 'line ' + i}); }""",
        lines,
    )
    set_prefs(page, tracks_open=False)
    page.wait_for_selector("#tracks-scroll", state="hidden")
    settle(page)
    shown = panes(page)
    log_title = window_box(page, ".screen-log .screen-title")
    tracks_title = window_box(page, ".screen-tracks .screen-title")
    assert abs(log_title["top"] - tracks_title["top"]) <= 1, (log_title, tracks_title)
    assert abs(log_title["bottom"] - tracks_title["bottom"]) <= 1, (log_title, tracks_title)
    for title, pane in ((log_title, shown["log"]), (tracks_title, shown["tracks"])):
        assert title["top"] >= pane["top"] - 0.5 and title["bottom"] <= pane["bottom"] + 0.5, (title, pane)
    text = window_box(page, ".screen-log .title-text")
    assert log_title["top"] - 0.5 <= text["top"] and text["bottom"] <= log_title["bottom"] + 0.5, (text, log_title)
    assert abs(shown["log"]["bottom"] - shown["tracks"]["bottom"]) <= 1, shown
    assert page.evaluate("document.documentElement.scrollHeight") <= 900
    # Open again, the teletype shows its last line.
    set_prefs(page, tracks_open=True)
    page.wait_for_selector("#tracks-scroll", state="visible")
    settle(page)
    if lines:
        last = window_box(page, "#log > :last-child")
        log = window_box(page, "#log")
        assert last["bottom"] <= log["bottom"] + 1 and last["top"] >= log["top"] - 1, (last, log)


def test_the_grip_is_a_separator_and_arrow_keys_move_it_2_percent(page):
    grip = page.eval_on_selector(
        "#tracks-grip",
        """g => ({ role: g.getAttribute('role'), orientation: g.getAttribute('aria-orientation'), tab: g.tabIndex,
                  min: g.getAttribute('aria-valuemin'), max: g.getAttribute('aria-valuemax'),
                  now: g.getAttribute('aria-valuenow'), cursor: getComputedStyle(g).cursor,
                  height: g.getBoundingClientRect().height, width: g.getBoundingClientRect().width,
                  pane: g.closest('.screen-tracks').getBoundingClientRect().width })""",
    )
    assert grip["role"] == "separator" and grip["orientation"] == "horizontal" and grip["tab"] == 0, grip
    assert (grip["min"], grip["max"], grip["now"]) == ("10", "80", "24"), grip
    assert grip["cursor"] == "row-resize" and grip["height"] == 6 and grip["width"] >= grip["pane"] - 2, grip
    spy_on_sends(page)
    page.focus("#tracks-grip")
    page.keyboard.press("ArrowUp")
    pref_is(page, "tracks_pct", 26)
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    pref_is(page, "tracks_pct", 22)
    page.wait_for_selector("#tracks-grip[aria-valuenow='22']")
    assert [m["tracks_pct"] for m in page.evaluate("window.sent")] == [26, 24, 22]
    page.keyboard.press("End")
    most = wait_for_sent(page, 4)[-1]["tracks_pct"]
    pref_is(page, "tracks_pct", most)
    page.evaluate("window.sent = []")
    page.keyboard.press("ArrowUp")
    page.wait_for_timeout(200)
    assert page.evaluate("window.sent") == []


def test_the_fold_leaves_only_the_title_bar_and_a_second_tab_folds_too(page, other):
    open_ = panes(page)
    assert page.get_attribute("#tracks-fold", "aria-expanded") == "true"
    page.click("#tracks-fold")
    for tab in (page, other):
        pref_is(tab, "tracks_open", False)
        tab.wait_for_selector("#tracks-fold[aria-expanded=false]")
        tab.wait_for_selector("#tracks-scroll", state="hidden")
        tab.wait_for_selector("#tracks-grip", state="hidden")
    settle(page)
    folded = panes(page)
    title = window_box(page, ".screen-tracks .screen-title")
    assert abs(folded["tracks"]["height"] - title["height"] - 2) <= 1, (folded, title)  # and the two borders
    assert abs(folded["tracks"]["top"] - folded["radar"]["bottom"] - 10) <= 1, folded  # one gap
    assert folded["radar"]["height"] > open_["radar"]["height"] + 100
    assert abs(folded["freq"]["bottom"] - folded["tracks"]["bottom"]) <= 1
    page.click("#tracks-fold")
    pref_is(other, "tracks_open", True)
    page.wait_for_selector("#tracks-fold[aria-expanded=true]")
    settle(page)
    again = panes(page)
    assert abs(again["tracks"]["height"] - open_["tracks"]["height"]) <= 1


@pytest.mark.parametrize("lamps, teletype", [(False, False), (True, False), (False, True), (True, True)])
def test_frequencies_and_the_teletype_stay_level_with_tracks_in_every_state(page, lamps, teletype):
    set_prefs(page, lamps=lamps, teletype=teletype)
    for state in ({"tracks_pct": 24}, {"tracks_pct": 60}, {"tracks_pct": 10}, {"tracks_open": False}):
        set_prefs(page, **state)
        settle(page)
        shown = panes(page)
        tracks = shown["tracks"]
        right = shown["log"] if teletype else shown["freq"]
        assert abs(right["bottom"] - tracks["bottom"]) <= 1, (state, shown)
        if teletype:
            assert abs(shown["log"]["top"] - tracks["top"]) <= 1, (state, shown)
        assert shown["radar"]["bottom"] <= tracks["top"], (state, shown)
        assert page.evaluate("document.documentElement.scrollHeight") <= 900, state


def test_in_one_column_there_is_no_grip_and_the_fold_still_works(page):
    page.set_viewport_size({"width": 820, "height": 1000})
    settle(page)
    assert page.is_hidden("#tracks-grip")
    assert page.is_visible("#tracks-fold")
    page.click("#tracks-fold")
    page.wait_for_selector("#tracks-fold[aria-expanded=false]")
    page.wait_for_selector("#tracks-scroll", state="hidden")
    settle(page)
    folded = window_box(page, ".screen-tracks")
    title = window_box(page, ".screen-tracks .screen-title")
    assert abs(folded["height"] - title["height"] - 2) <= 1, (folded, title)
    page.click("#tracks-fold")
    page.wait_for_selector("#tracks-scroll", state="visible")
    assert page.is_hidden("#tracks-grip")


def test_a_drag_redraws_the_radar_at_most_once_a_frame(page):
    page.evaluate(
        """() => { window.statics = 0; window.ticks = 0;
                   window.kcgx.radar.hook((radar) => {
                     const ctx = radar.still.getContext('2d'), clear = ctx.clearRect;
                     ctx.clearRect = function (...args) { window.statics += 1; return clear.apply(this, args); };
                     return { tick() { window.ticks += 1; } }; }); }"""
    )
    frames(page, 3)
    x, y = grab(page)
    page.evaluate("window.statics = 0; window.ticks = 0")
    page.mouse.move(x, y - 150, steps=20)
    frames(page, 2)
    statics, ticks = page.evaluate("[window.statics, window.ticks]")
    page.mouse.up()
    assert 1 <= statics <= ticks, (statics, ticks)


@pytest.mark.parametrize("zoom", [1, 1.5])
def test_under_zoom_the_checklist_opens_over_its_button_and_the_filters_stay_under_the_header(page, zoom):
    page.set_viewport_size({"width": 1440, "height": 1000})
    zoom_page(page, zoom)
    page.click("#open-columns")
    page.wait_for_selector("#tracks-columns", state="visible")
    button = window_box(page, "#open-columns")
    pop = window_box(page, "#tracks-columns")
    assert pop["bottom"] <= button["top"] + 0.5 and button["top"] - pop["bottom"] <= 4 * zoom + 1, (pop, button)
    assert abs(pop["right"] - button["right"]) <= 1, (pop, button)
    assert pop["top"] >= 0 and pop["left"] >= 0, pop
    page.keyboard.press("Escape")
    th = window_box(page, "#tracks-head th")
    filters = window_box(page, "#tracks-filters td")
    assert abs(filters["top"] - th["bottom"]) <= 1, (filters, th)
