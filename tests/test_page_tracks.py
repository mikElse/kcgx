"""The tracks table, phase G Task 8: the columns chosen from the title bar,
a row of filters under the header, the sort as a setting every tab shares,
the rank the radar shades by, and a header that stays as the table scrolls.

Browser tests against the demo server, in Chromium and then WebKit.
"""

from __future__ import annotations

import pytest

from kcgx.prefs import DEFAULTS, SCHEMA
from page_fixtures import *  # noqa: F403  (fixtures and helpers)
from page_fixtures import box_of, hold_traffic, pixel, plane, pref_is, radar_debug, rows, set_prefs, spy_on_sends

pytestmark = pytest.mark.browser

NAMES = list(SCHEMA["track_cols"].names)
TITLES = {
    "CALLSIGN": "CALLSIGN", "TYPE": "TYPE", "REG": "REG", "ALT": "ALT FT", "VS": "V/S FPM", "GS": "GS KT",
    "TRK": "TRK", "DIST": "DIST NM", "BRG": "BRG", "SQWK": "SQWK", "HEX": "HEX", "DESC": "DESC", "OPER": "OPER",
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
    page.click("#tracks-columns button[data-key=OPER]")
    pref_is(page, "track_cols", [name for name in NAMES if name in with_reg or name == "OPER"])
    pref_is(other, "track_cols", [name for name in NAMES if name in with_reg or name == "OPER"])
    other.wait_for_function("[...document.querySelectorAll('#tracks-head th')].some(th => th.textContent === 'OPER')")
    assert "REG" in head(other)
    page.click("#tracks-columns button[data-key=REG]")
    page.click("#tracks-columns button[data-key=OPER]")
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


def test_a_text_filter_matches_a_substring_in_any_case_and_hides_rows_only(page):
    hold_traffic(page, *THREE)
    page.fill(text_filter("CALLSIGN"), "dal")
    wait_for_hexes(page, ["r1", "r3"])
    assert sorted(hit["hex"] for hit in radar_debug(page)["hits"]) == ["r1", "r2", "r3"]
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


def test_the_rank_follows_the_sort_unfiltered_with_the_focus_first(page):
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
    # Filters hide rows, not rank.
    page.fill(text_filter("CALLSIGN"), "dal")
    wait_for_hexes(page, ["r3", "r1"])
    assert ranks(page) == {"r3": 0, "r2": 0.5, "r1": 1}
    # The focus is first.
    page.click('#tracks-body tr[data-hex="r1"] .callsign')
    page.wait_for_function("window.kcgx.store.state.rank.get('r1') === 0")
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
