"""The cockpit page in real browsers, against `kcgx-web --demo`.

Every test that opens the page runs twice, in Chromium and in WebKit. They
need Playwright and its builds of the two (`uv sync --group browser`, then
`uv run playwright install chromium webkit`); without Playwright they all
skip, and without one of the browsers its half does. The server runs as a
subprocess with its state in a temporary folder, so nothing here touches
~/.local/state/kcgx.
"""

from __future__ import annotations

import re
import urllib.request

import pytest

from kcgx.prefs import DEFAULTS, SCHEMA, Choice, Flag, Number, Subset
from page_fixtures import *  # noqa: F403  (the fixtures and the helpers every page test file shares)
from test_page_prefs import DROPDOWNS, ON_THE_PAGE, TABS

pytestmark = pytest.mark.browser


# -- layout --------------------------------------------------------------------


WIDE = [size for size in SIZES if size[0] > 1100]  # two columns
LEAST = (1280, 640)  # two columns, at the page's least height
SHORT = (1280, 600)  # two columns, and less high than that: the page scrolls
LAYOUTS = [(lamps, teletype) for lamps in (False, True) for teletype in (False, True)]


@pytest.mark.parametrize("lamps, teletype", LAYOUTS)
@pytest.mark.parametrize("width, height", SIZES + [LEAST])
def test_no_two_screens_overlap_and_none_spills_out(page, width, height, lamps, teletype):
    page.set_viewport_size({"width": width, "height": height})
    set_prefs(page, lamps=lamps, teletype=teletype)
    page.wait_for_timeout(200)
    where = f"at {width}x{height}, lamps {lamps}, teletype {teletype}"
    shown = parts(page)
    expected = ["radar", "status", "freq"] + ["lamps"] * lamps + ["tracks"] + ["log"] * teletype
    assert list(shown) == expected, where
    boxes = list(shown.items())
    for i, (name, (left, top, right, bottom)) in enumerate(boxes):
        least = 20 if name == "lamps" else 40
        assert right - left > 100 and bottom - top > least, f"{name} collapsed {where}"
        for other, (l2, t2, r2, b2) in boxes[i + 1:]:
            apart = right <= l2 + 0.5 or r2 <= left + 0.5 or bottom <= t2 + 0.5 or b2 <= top + 0.5
            assert apart, f"{name} overlaps {other} {where}"
    scroll_width, scroll_height = page.evaluate(
        "[document.documentElement.scrollWidth, document.documentElement.scrollHeight]"
    )
    assert scroll_width <= width, f"the page scrolls sideways {where}"
    if width > 1100:  # two columns fill the window; one column is read by scrolling
        assert scroll_height <= height, f"the page is {scroll_height} px high {where}"
        padding = page.eval_on_selector(".page", "e => parseFloat(getComputedStyle(e).paddingBottom)")
        lowest = max(bottom for _, _, _, bottom in shown.values())
        assert lowest <= height - padding + 0.5, f"the screens run {lowest - height + padding} px into the margin {where}"


def test_by_default_four_screens_show_and_no_lamps_or_teletype(page):
    assert page.get_attribute("html", "data-lamps") == "OFF"
    assert page.get_attribute("html", "data-teletype") == "OFF"
    assert list(parts(page)) == ["radar", "status", "freq", "tracks"]
    assert not page.is_visible("#lamps")
    assert not page.is_visible(".screen-log")
    assert not page.is_visible("#log")


def test_the_first_paint_is_the_default_layout(server):
    """Before any script has run, the page is already laid out without the
    lamps and the teletype, so they never flash on."""
    with urllib.request.urlopen(server + "/") as response:
        html = response.read().decode()
    tag = re.search(r"<html[^>]*>", html).group(0)
    assert 'data-lamps="OFF"' in tag and 'data-teletype="OFF"' in tag


@pytest.mark.parametrize("lamps", [False, True])
@pytest.mark.parametrize("width, height", WIDE)
def test_frequencies_runs_down_to_the_bottom_of_tracks(page, width, height, lamps):
    page.set_viewport_size({"width": width, "height": height})
    set_prefs(page, lamps=lamps)
    page.wait_for_timeout(200)
    shown = parts(page)
    radar, status, freq, tracks = (shown[name] for name in ("radar", "status", "freq", "tracks"))
    assert abs(freq[3] - tracks[3]) <= 1, f"frequencies ends at {freq[3]}, tracks at {tracks[3]}"
    assert freq[1] >= status[3] and abs(freq[0] - status[0]) <= 1, "frequencies is not under the airport"
    assert tracks[1] >= radar[3] and abs(tracks[0] - radar[0]) <= 1, "tracks is not under the radar"
    assert freq[0] >= radar[2], "frequencies is not beside the radar"


@pytest.mark.parametrize("lamps", [False, True])
@pytest.mark.parametrize("width, height", WIDE + [SHORT])
def test_a_short_window_never_squeezes_the_airport_pane(page, width, height, lamps):
    """Its row is sized by what is in it: a screen clips what overflows it,
    so a squeezed pane would cut off the button that changes the airport.
    At SHORT the page is taller than the window and scrolls instead."""
    page.set_viewport_size({"width": width, "height": height})
    set_prefs(page, lamps=lamps)
    page.wait_for_timeout(200)
    hidden = page.eval_on_selector(".screen-status", "e => e.scrollHeight - e.clientHeight")
    assert hidden <= 0, f"{hidden} px of the airport pane is cut off at {width}x{height}"


@pytest.mark.parametrize("lamps", [False, True])
@pytest.mark.parametrize("width, height", WIDE)
def test_the_teletype_sits_under_frequencies_level_with_tracks(page, width, height, lamps):
    page.set_viewport_size({"width": width, "height": height})
    set_prefs(page, lamps=lamps, teletype=True)
    page.wait_for_timeout(200)
    assert page.get_attribute("html", "data-teletype") == "ON"
    shown = parts(page)
    assert [name for name in shown if name != "lamps"] == ["radar", "status", "freq", "tracks", "log"]
    freq, tracks, log = shown["freq"], shown["tracks"], shown["log"]
    assert log[1] >= freq[3], "the teletype is not under frequencies"
    assert abs(log[0] - freq[0]) <= 1 and abs(log[2] - freq[2]) <= 1, "the teletype is not in frequencies' column"
    assert abs(log[1] - tracks[1]) <= 1 and abs(log[3] - tracks[3]) <= 1, "the teletype is not level with tracks"
    assert page.is_visible("#log")


@pytest.mark.parametrize("teletype", [False, True])
@pytest.mark.parametrize("width, height", WIDE)
def test_the_lamp_bar_sits_between_radar_and_tracks_no_wider_than_the_radar(page, width, height, teletype):
    page.set_viewport_size({"width": width, "height": height})
    set_prefs(page, lamps=True, teletype=teletype)
    page.wait_for_timeout(200)
    assert page.get_attribute("html", "data-lamps") == "ON"
    shown = parts(page)
    radar, lamps, tracks = shown["radar"], shown["lamps"], shown["tracks"]
    assert radar[3] <= lamps[1] and lamps[3] <= tracks[1], "the lamp bar is not between radar and tracks"
    assert lamps[0] >= radar[0] - 0.5 and lamps[2] <= radar[2] + 0.5, "the lamp bar is wider than the radar"
    assert page.locator("#lamps .lamp").count() >= 4


@pytest.mark.parametrize("width, height", [size for size in SIZES if size[0] <= 1100])
def test_a_narrow_page_is_one_column_in_reading_order(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    set_prefs(page, lamps=True, teletype=True)
    page.wait_for_timeout(200)
    shown = parts(page)
    assert list(shown) == ["radar", "status", "freq", "lamps", "tracks", "log"]
    boxes = list(shown.values())
    for above, below in zip(boxes, boxes[1:]):
        assert above[3] <= below[1] + 0.5
        assert abs(above[0] - below[0]) <= 1 and abs(above[2] - below[2]) <= 1


@pytest.mark.parametrize("width, height", [(1440, 900), (1100, 760), (820, 1000)])
def test_the_forty_mile_ring_fits_the_shorter_side_of_the_radar(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(300)
    box = page.eval_on_selector("#radar", "e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }")
    size = page.eval_on_selector("#radar", "e => [e.width / devicePixelRatio, e.height / devicePixelRatio]")
    assert abs(box[0] - size[0]) <= 1 and abs(box[1] - size[1]) <= 1, "the canvas does not fill its pane"


@pytest.mark.parametrize("display", ["CRT", "VECTOR"])
def test_the_screens_do_not_flicker_in_step(page, display):
    """Frequencies and tracks start partway through the flicker, so the wall
    never blinks as one."""
    try:
        set_prefs(page, display=display)
        flicker = page.evaluate(
            """() => Object.fromEntries(["radar", "status", "freq", "tracks"].map(name => {
                const style = getComputedStyle(document.querySelector(`.screen-${name}`));
                return [name, `${style.animationName} ${style.animationDelay}`]; }))"""
        )
    finally:
        set_prefs(page, display="CRT")
    assert flicker == {
        "radar": "flicker 0s", "status": "flicker 0s", "freq": "flicker -4.6s", "tracks": "flicker -2.1s",
    }


def test_no_label_carries_a_key_hint(page):
    text = page.inner_text("body")
    assert not re.search(r"\[[A-Z/]{1,6}\]", text), "a bracketed key hint is on the page"
    assert "AMBIENT" not in text.upper()


# -- the header and the airport pane ---------------------------------------------


@pytest.mark.parametrize("gone", ["#open-feeds", "#next-palette", "#feeds-sheet", "#recentre"])
def test_feeds_palette_and_recentre_are_not_in_the_page(page, gone):
    assert page.locator(gone).count() == 0


def test_the_header_holds_two_buttons_and_no_words(page):
    assert page.eval_on_selector_all(".bar-buttons button", "bs => bs.map(b => b.id)") == [
        "open-config", "open-shutdown",
    ]
    assert page.inner_text(".bar-buttons").strip() == ""


@pytest.mark.parametrize("width, height", [(1440, 900), (820, 1000), (390, 844), (320, 640)])
def test_the_header_icons_stay_top_right_however_narrow_the_page(page, width, height):
    """A narrow page wraps the brand's second line, not the icons, which
    stay level with the name."""
    page.set_viewport_size({"width": width, "height": height})
    at = page.evaluate(
        """() => {
            const box = (s) => document.querySelector(s).getBoundingClientRect().toJSON();
            const bar = document.querySelector(".bar");
            return { bar: box(".bar"), name: box(".brand-name"), sub: box(".brand-sub"), brand: box(".brand"),
                     config: box("#open-config"), power: box("#open-shutdown"),
                     inner: bar.getBoundingClientRect().right - parseFloat(getComputedStyle(bar).paddingRight),
                     wide: document.documentElement.scrollWidth }; }"""
    )
    assert at["wide"] <= width, "the page scrolls sideways"
    assert abs(at["power"]["right"] - at["inner"]) <= 1, "the icons are not at the header's right edge"
    assert at["config"]["right"] <= at["power"]["left"] and abs(at["config"]["top"] - at["power"]["top"]) <= 1
    # beside the name, not on a row of their own beneath it
    middle = lambda box: (box["top"] + box["bottom"]) / 2
    assert abs(middle(at["config"]) - middle(at["name"])) <= 2, "the icons are not level with the name"
    assert abs(at["config"]["top"] - at["bar"]["top"]) <= 1
    assert at["brand"]["right"] <= at["config"]["left"]
    assert at["name"]["right"] <= at["config"]["left"] and at["sub"]["right"] <= at["config"]["left"]
    assert at["config"]["bottom"] <= at["bar"]["bottom"]


ICONS = [("#open-config", "Config"), ("#open-shutdown", "Shut down"), ("#open-airport", "Search airports")]


@pytest.mark.parametrize("selector, name", ICONS)
def test_an_icon_button_is_a_drawing_with_a_name_and_no_border(page, selector, name):
    button = page.locator(selector)
    assert button.inner_text().strip() == "", f"{selector} still shows text"
    assert button.locator("svg").count() == 1
    drawn = button.locator("svg").evaluate("e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }")
    assert drawn[0] >= 16 and drawn[1] >= 16, f"{selector}'s icon is {drawn} px"
    assert button.evaluate("e => getComputedStyle(e).borderTopWidth") == "0px"
    # the accessible name, as a screen reader is given it
    named = page.get_by_role("button", name=name, exact=True)
    assert named.count() == 1 and "#" + named.get_attribute("id") == selector
    assert button.get_attribute("title") == name


def test_shut_down_is_drawn_in_the_alarm_colour(page):
    colours = page.evaluate(
        """() => { const probe = document.createElement("span");
                   probe.style.color = "var(--alarm)"; document.body.append(probe);
                   const alarm = getComputedStyle(probe).color; probe.remove();
                   const svg = document.querySelector("#open-shutdown svg");
                   return [getComputedStyle(svg).stroke, alarm]; }"""
    )
    assert colours[0] == colours[1]


@pytest.mark.parametrize("selector, sheet", [
    ("#open-config", "#config-sheet"), ("#open-shutdown", "#shutdown-sheet"), ("#open-airport", "#airport-sheet"),
])
def test_an_icon_button_opens_its_sheet(page, selector, sheet):
    page.click(selector)
    page.wait_for_selector(f"{sheet}[open]")


def shut_down(page):
    """Press the power icon and confirm. The server's answer is faked: the
    one these tests share has to outlive this one."""
    page.route("**/api/shutdown", lambda route: route.fulfill(status=202, json={"ok": True}))
    page.click("#open-shutdown")
    page.click("#confirm-shutdown")
    page.wait_for_selector("#ended", state="visible")


def test_shutting_down_tells_the_window_it_has_ended(page):
    # KCGX.app gives the page a message handler named kcgx (macos/KCGXWindow.swift).
    page.evaluate("""() => {
        window.told = [];
        const kcgx = { postMessage: (message) => window.told.push(message) };
        Object.defineProperty(window, "webkit", { configurable: true, value: { messageHandlers: { kcgx } } });
    }""")
    shut_down(page)
    assert page.evaluate("window.told") == ["ended"]


def test_shutting_down_in_a_browser_has_no_window_to_tell(page):
    assert page.evaluate("window.webkit?.messageHandlers?.kcgx === undefined")
    shut_down(page)  # and the fixture sees no page error


@pytest.mark.parametrize("width, height", [(1440, 900), (1280, 640), (390, 844)])
def test_the_airport_pane_has_no_title_and_its_search_icon_sits_bottom_right(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_function("document.getElementById('airport-where').textContent !== ''")
    assert page.locator(".screen-status .screen-title").count() == 0
    assert "STATUS" not in page.inner_text(".screen-status")
    assert page.get_attribute(".screen-status", "aria-label") == "Airport"
    at = page.evaluate(
        """() => {
            const box = (e) => e.getBoundingClientRect();
            const pane = document.querySelector(".screen-status");
            const body = document.querySelector(".status-body");
            const names = box(document.getElementById("airport-where").parentElement);
            return {
                icon: box(document.getElementById("open-airport")).toJSON(),
                inner: box(body).right - parseFloat(getComputedStyle(body).paddingRight),
                pane: box(pane).toJSON(),
                names: names.toJSON(),
                name: box(document.getElementById("airport-name")).toJSON(),
                icao: box(document.getElementById("icao")).toJSON(),
                zulu: box(document.getElementById("zulu")).toJSON(),
            };
        }"""
    )
    icon, names = at["icon"], at["names"]
    assert abs(icon["right"] - at["inner"]) <= 1, "the search icon is not at the pane's inner right edge"
    assert abs(icon["bottom"] - names["bottom"]) <= 2, "the search icon is not level with the bottom of the names"
    assert icon["bottom"] <= at["pane"]["bottom"] and icon["right"] <= at["pane"]["right"]
    # the name and the place are one block, under the ICAO and left of the icon
    assert at["name"]["top"] >= names["top"] and at["name"]["bottom"] <= names["bottom"]
    assert names["top"] >= at["icao"]["bottom"] - 1 and abs(names["left"] - at["icao"]["left"]) <= 1
    assert names["right"] <= icon["left"]
    # ICAO and clocks on top, as before
    assert abs(at["icao"]["top"] - at["zulu"]["top"]) <= 2 and at["zulu"]["left"] >= at["icao"]["right"]
    assert icon["top"] >= at["zulu"]["bottom"]


# -- the feed stack ------------------------------------------------------------


def test_the_trace_draws(page):
    page.wait_for_timeout(1500)
    lit = page.eval_on_selector(
        ".feed.expanded .trace",
        "c => { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;"
        " let n = 0; for (let i = 3; i < d.length; i += 4) n += d[i] > 0; return n; }",
    )
    assert lit > 50


def test_chatter_reads_as_a_percentage_in_both_shapes(page):
    page.wait_for_selector(".feed.compact")
    for selector in (".feed.expanded .chatter-big", ".feed.compact .chatter-small"):
        texts = page.eval_on_selector_all(selector, "els => els.map(e => e.textContent)")
        assert texts, selector
        # a number with its sign, not two digits: 0%, 7%, 42%, 100%
        assert all(re.fullmatch(r"(0|[1-9]\d?|100)%", text) for text in texts), texts
    # said aloud, the row gives the number once
    label = page.get_attribute(".feed.compact", "aria-label")
    assert re.search(r", chatter (0|[1-9]\d?|100) percent, ", label), label


def test_the_chatter_figures_are_small_and_do_not_shift_as_they_change(page):
    page.wait_for_selector(".feed.compact")
    sizes = {}
    for name in ("chatter-big", "chatter-small"):
        sizes[name], align, widths = page.eval_on_selector(
            f".{name}",
            """e => {
                const style = getComputedStyle(e);
                const widths = ["0%", "42%", "100%"].map(text => {
                    const copy = e.cloneNode(); copy.textContent = text; e.after(copy);
                    const width = copy.getBoundingClientRect().width; copy.remove(); return width; });
                return [parseFloat(style.fontSize), style.textAlign, widths];
            }""",
        )
        assert align == "right", name
        assert max(widths) - min(widths) <= 0.5, f"{name} is {widths} px wide for 0%, 42% and 100%"
    assert sizes["chatter-big"] < 20
    assert sizes["chatter-small"] < sizes["chatter-big"]


def around(top, sides, bottom=None):
    bottom = top if bottom is None else bottom
    return {"paddingTop": top, "paddingRight": sides, "paddingBottom": bottom, "paddingLeft": sides}


# How close text sits to what holds it: each is at most this many px (the
# 11/12 list's "tighten padding around all text"; the plan's table, Task 6).
# These are ceilings, so the page may be made tighter still, and never looser.
DENSITY = {
    ".page": {**around(10, 12, 12), "columnGap": 10},
    ".page > .screen": {"marginTop": 10},  # the gap between one row of screens and the next
    ".page > .lamps": {"marginTop": 10, **around(6, 10)},
    ".screen-title": around(4, 10),
    ".status-body": {**around(10, 12, 8), "rowGap": 6},
    ".freq-head": around(6, 10, 4),
    ".stack": {**around(4, 8, 8), "rowGap": 4},
    ".feed.expanded": {**around(6, 8), "rowGap": 4},
    ".feed.compact": {**around(0, 8), "minHeight": 32, "height": 32},
    ".tracks-body": around(4, 8, 2),
    ".tracks th": around(3, 6),
    ".tracks td": around(2, 6),
    ".log": {**around(8, 10), "rowGap": 4},
    ".hud": {"top": 8},
    ".hud-left": {"left": 10},
    ".hud-right": {"right": 10},
    ".sheet": around(12, 14),
    ".choice": {**around(4, 8), "minHeight": 32},
    ".btn:not(.btn-small):not(.seg)": {**around(0, 10), "minHeight": 30},
    ".btn-small": {**around(0, 8), "minHeight": 26},
}


def test_text_sits_close_to_its_frame_everywhere(page):
    page.wait_for_selector(".feed.compact")
    page.wait_for_selector("#tracks-body td")
    set_prefs(page, lamps=True, teletype=True)
    page.wait_for_selector(".log-line")
    page.click("#open-airport")
    page.fill("#airport-query", "seattle")
    page.wait_for_selector("#airport-results .choice")
    measured = page.evaluate(
        """wanted => Object.entries(wanted).map(([selector, limits]) => [
            selector,
            [...document.querySelectorAll(selector)].map(e => {
                const style = getComputedStyle(e);
                return Object.keys(limits).map(name =>
                    [name, name === "height" ? e.getBoundingClientRect().height : parseFloat(style[name])]);
            }),
        ])""",
        DENSITY,
    )
    loose = []
    for selector, elements in measured:
        assert elements, f"nothing on the page is {selector}"
        for values in elements:
            for name, value in values:
                # NaN (a value that is not a length) is no pass either.
                if not value <= DENSITY[selector][name] + 0.01:
                    loose.append(f"{selector} {name} is {value}, over {DENSITY[selector][name]}")
    size, line = page.eval_on_selector(
        "body", "e => { const s = getComputedStyle(e); return [parseFloat(s.fontSize), parseFloat(s.lineHeight)]; }"
    )
    if not line <= size * 1.3 + 0.01:
        loose.append(f"body's lines are {line} px high for {size} px text, over 1.3")
    assert not loose, "\n".join(sorted(set(loose)))


# -- sheets --------------------------------------------------------------------


def test_changing_airport_redraws_everything(page):
    page.click("#open-airport")
    page.fill("#airport-query", "seattle")
    page.click("#airport-results .choice:has-text('KSEA')")
    page.wait_for_function("document.getElementById('icao').textContent === 'KSEA'")
    page.wait_for_selector(".feed.expanded")
    assert page.title() == "KCGX KSEA"
    page.click("#open-airport")
    page.fill("#airport-query", "KPDX")
    page.click("#airport-results .choice:has-text('KPDX')")
    page.wait_for_function("document.getElementById('icao').textContent === 'KPDX'")


def test_escape_closes_the_airport_sheet_at_once_whether_or_not_a_query_is_typed(page):
    """Left to itself a browser does as it likes with Escape in a search
    field: Chromium empties the field and leaves the sheet open, WebKit
    closes the sheet. The page closes it, in each, and the next opening
    starts empty."""
    is_open = "document.getElementById('airport-sheet').open"
    page.click("#open-airport")
    page.wait_for_selector("#airport-sheet[open]")
    page.keyboard.press("Escape")
    assert not page.evaluate(is_open), "Escape with nothing typed left the sheet open"
    page.click("#open-airport")
    page.wait_for_selector("#airport-sheet[open]")
    assert page.evaluate("document.activeElement.id") == "airport-query"
    page.keyboard.type("seattle")
    page.wait_for_selector("#airport-results .choice:has-text('KSEA')")
    page.keyboard.press("Escape")
    assert not page.evaluate(is_open), "Escape with a query typed left the sheet open"
    # Where the focus goes is the browser's (the button in Chromium, the page in WebKit); it leaves the field.
    page.wait_for_function("document.activeElement.id !== 'airport-query'")
    assert page.evaluate("document.getElementById('icao').textContent") == "KPDX", "Escape chose an airport"
    page.click("#open-airport")
    page.wait_for_selector("#airport-sheet[open]")
    assert page.input_value("#airport-query") == ""
    assert page.locator("#airport-results .choice").count() == 0


def test_prefs_apply_to_every_tab(page, other):
    theme = "#config-sheet select[data-pref=palette]"
    page.click("#open-config")
    assert page.input_value(theme) == "WOPR"
    page.select_option(theme, "AMBER")
    other.wait_for_function("document.documentElement.dataset.palette === 'AMBER'")
    page.wait_for_function("document.documentElement.dataset.palette === 'AMBER'")
    assert other.input_value(theme) == "AMBER", "the other tab's dropdown did not follow"
    page.click(".segments[data-pref=display] button:text-is('VECTOR')")
    other.wait_for_function("document.documentElement.dataset.display === 'VECTOR'")
    page.click(".segments[data-pref=display] button:text-is('CRT')")
    page.select_option(theme, "WOPR")
    other.wait_for_function("document.documentElement.dataset.palette === 'WOPR'")
    assert other.get_attribute("html", "data-display") == "CRT"
    assert other.input_value(theme) == "WOPR"


def test_the_volume_slider_is_in_the_frequencies_pane_and_reaches_the_server(page):
    """Not a pref, and not in the config sheet: the frequencies pane has it
    (phase G decision 3), its readout beside it."""
    assert page.locator("#config-sheet #volume").count() == 0
    assert page.locator(".screen-freq #volume").is_visible()
    page.fill("#volume", "40")
    assert page.text_content("#volume-value") == "40%"
    page.dispatch_event("#volume", "input")
    page.wait_for_function("window.kcgx.store.state.volume === 0.4")
    page.fill("#volume", "100")
    page.dispatch_event("#volume", "input")
    page.wait_for_function("window.kcgx.store.state.volume === 1")


# -- the config sheet ------------------------------------------------------------

NUMBERS = {key: spec for key, spec in ON_THE_PAGE.items() if isinstance(spec, Number)}
SUBSETS = {key: spec for key, spec in ON_THE_PAGE.items() if isinstance(spec, Subset)}
FLAGS = [key for key, spec in ON_THE_PAGE.items() if isinstance(spec, Flag)]
SEGMENTED = {key: spec for key, spec in ON_THE_PAGE.items() if isinstance(spec, Choice) and key not in DROPDOWNS}
# What a slider's readout says of its value.
READOUTS = {
    "ui_zoom": "{}%", "font_px": "{} PX",
    "scan_opacity": "{}%", "scan_size": "{} PX",
    "glow_map": "{}%", "glow_traffic": "{}%", "glow_text": "{}%",
    "burn_in": "{} MS", "fps_max": "{} FPS", "poll_secs": "{} S", "zoom_speed": "{}%",
    "range_nm": "{} NM",
    "box_fill": "{}%", "box_pad": "{} PX", "box_border": "{}%", "box_width": "{} PX",
    "label_min": "{} PX", "label_max": "{} PX", "tag_px": "{} PX", "follow_nm": "{} NM",
    "tail_secs": "{} S", "tail_alpha": "{}%", "tail_alpha_min": "{}%", "tail_alpha_max": "{}%",
    "tail_gs_low": "{} KT", "tail_gs_high": "{} KT",
    "ground_gs": "{} KT", "ground_alt": "{} FT", "ground_min": "{} MIN", "ground_alpha": "{}%",
    "sort_floor": "{}%",
}
# The settings whose value <html> carries, as data-<key>, for the stylesheet.
ON_HTML = ("display", "lamps", "teletype")


def test_limits_and_the_stream_count_are_gone(page):
    assert page.locator("#max-streams").count() == 0
    said = page.text_content("#config-sheet")
    assert "LIMITS" not in said and "STREAMS AT ONCE" not in said and "OUTPUT" not in said
    assert page.eval_on_selector_all("#config-sheet [role=tab]", "ts => ts.map(t => t.textContent)") == list(TABS)
    assert page.evaluate("'maxStreams' in window.kcgx.store.state") is False, "the page keeps a limit it shows nowhere"


def test_the_sheet_opens_showing_the_defaults(page):
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    for key in DROPDOWNS:
        assert page.input_value(f"#config-sheet select[data-pref={key}]") == DEFAULTS[key], key
    for key in SEGMENTED:
        assert pressed(page, key) == [DEFAULTS[key]], key
    for key in FLAGS:
        assert page.eval_on_selector_all(
            f"#config-sheet [data-pref={key}] button", "bs => bs.map(b => b.textContent)"
        ) == ["OFF", "ON"], key
        assert pressed(page, key) == ["ON" if DEFAULTS[key] else "OFF"], key
    for key, spec in SUBSETS.items():
        assert page.eval_on_selector_all(
            f"#config-sheet [data-pref={key}] button", "bs => bs.map(b => b.textContent)"
        ) == list(spec.names), key
        assert pressed(page, key) == DEFAULTS[key], key
    for key in NUMBERS:
        assert page.input_value(f"#config-sheet input[data-pref={key}]") == str(DEFAULTS[key]), key
        assert readout(page, key) == READOUTS[key].format(DEFAULTS[key]), key
    # every control is one a person can reach and work, on its own tab
    for tab, keys in TABS.items():
        config_tab(page, tab=tab)
        for key in ON_THE_PAGE:
            shown = page.locator(f"#config-sheet [data-pref={key}]").is_visible()
            assert shown == (key in keys), f"{key} on the {tab} tab"


def brightest(page, x, y):
    """The brightest of three pixels of the page, one above the other about
    (x, y): a thin line that does not fall on whole pixels still fills one."""
    return max((pixel(page, round(x), round(y) + dy) for dy in (-1, 0, 1)), key=sum)


def test_the_theme_dropdown_is_drawn_by_the_page_not_by_the_browser(page):
    """A browser's own dropdown is its own shape: WebKit rounds its corners
    and makes it as short as it likes. This one is square, as high as the
    buttons under it, with an arrow in the text's colour."""
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    drawn = page.eval_on_selector(
        "#config-sheet select[data-pref=palette]",
        """e => { const style = getComputedStyle(e); const box = e.getBoundingClientRect();
                  return { appearance: style.appearance, radius: style.borderTopLeftRadius, arrow: style.backgroundImage,
                           height: box.height, right: box.right, middle: box.top + box.height / 2 }; }""",
    )
    button = page.eval_on_selector("#config-sheet .seg", "e => e.getBoundingClientRect().height")
    assert drawn["appearance"] == "none"
    assert drawn["radius"] == "0px"
    assert drawn["height"] == button == 26
    assert drawn["arrow"].count("linear-gradient") == 2, drawn["arrow"]
    # The arrow's top edge runs from 19 to 9 px in from the right; this is its middle.
    assert brightest(page, drawn["right"] - 14, drawn["middle"] - 1.5) == css_colour(page, "--text")
    assert brightest(page, drawn["right"] - 30, drawn["middle"]) == (0, 0, 0), "the arrow's place is not black beside it"


@pytest.mark.parametrize("palette", ["WOPR", "AMBER"])
def test_a_slider_is_drawn_by_the_page_and_its_track_shows_on_black(page, palette):
    """WebKit's own slider draws a track that cannot be seen on black, and
    ignores the accent colour. The track is a line in the dim colour and the
    thumb a block in the bright one, whatever the browser."""
    # No display effects: the volume is in the frequencies pane, under its scanlines.
    set_prefs(page, palette=palette, display="OFF")
    track, thumb = css_colour(page, "--dim"), css_colour(page, "--cyan")
    # The volume first: the sheet covers the pane.
    for key in ("volume", "box_width", "range_nm"):
        if key != "volume":
            config_tab(page, key)
        slider = page.locator("#volume" if key == "volume" else f"#config-sheet input[data-pref={key}]")
        slider.scroll_into_view_if_needed()
        box = slider.bounding_box()
        low, high, value = float(slider.get_attribute("min")), float(slider.get_attribute("max")), float(slider.input_value())
        middle = box["y"] + box["height"] / 2
        # The thumb's middle runs from half its width in at one end to half its width in at the other.
        width = 10
        at = box["x"] + width / 2 + (box["width"] - width) * (value - low) / (high - low)
        assert brightest(page, at, middle) == thumb, f"{key}: no thumb at its value"
        clear = [x for x in (box["x"] + 20, box["x"] + box["width"] / 2, box["x"] + box["width"] - 20) if abs(x - at) > 12]
        for x in clear:
            assert brightest(page, x, middle) == track, f"{key}: no track {x - box['x']:.0f} px along"
        assert brightest(page, clear[0], middle - 7) == (0, 0, 0), f"{key}: the track is more than a line"
        assert box["height"] == 18, key


def test_each_number_slider_reaches_a_second_tab(page, other):
    for key, spec in NUMBERS.items():
        config_tab(page, key)
        value = spec.low if spec.default == spec.high else spec.high
        slider = f"#config-sheet input[data-pref={key}]"
        page.fill(slider, str(value))  # sets it and fires `input`, as a drag does
        assert readout(page, key) == READOUTS[key].format(value), f"{key}: the readout waited for the server"
        pref_is(other, key, value)
        pref_is(page, key, value)
        assert other.input_value(slider) == str(value), f"{key}: the other tab's slider did not follow"
        assert readout(other, key) == READOUTS[key].format(value), key
        assert page.input_value(slider) == str(value), key


def test_a_slider_sends_whole_numbers_and_only_its_own_setting(page):
    spy_on_sends(page)
    config_tab(page, "range_nm")
    page.fill("#config-sheet input[data-pref=range_nm]", "120")
    pref_is(page, "range_nm", 120)
    assert page.evaluate("window.sent") == [{"t": "prefs", "range_nm": 120}]


def test_dragging_a_slider_sends_where_it_stopped_not_every_step(page):
    """The range above all: a drag must not become a burst of messages. The
    steps are 20 ms apart, each inside the 80 ms the slider waits; a timer
    that is due sooner runs sooner, so a busy page cannot reorder them."""
    spy_on_sends(page)
    config_tab(page, "range_nm")
    page.eval_on_selector(
        "#config-sheet input[data-pref=range_nm]",
        """async slider => { for (const value of [50, 60, 70, 80, 90, 100]) {
                                 slider.value = String(value);
                                 slider.dispatchEvent(new Event("input", { bubbles: true }));
                                 await new Promise(done => setTimeout(done, 20)); } }""",
    )
    assert readout(page, "range_nm") == "100 NM"
    pref_is(page, "range_nm", 100)
    page.wait_for_timeout(200)
    assert page.evaluate("window.sent") == [{"t": "prefs", "range_nm": 100}]


def test_each_subset_button_reaches_a_second_tab(page, other):
    for key, spec in SUBSETS.items():
        config_tab(page, key)
        chosen = set(DEFAULTS[key])
        # Twice round: every button is turned on once and off once.
        for name in spec.names * 2:
            page.click(f"#config-sheet [data-pref={key}] button:text-is('{name}')")
            chosen ^= {name}
            expected = [n for n in spec.names if n in chosen]  # the whole list, in schema order
            pref_is(other, key, expected)
            pref_is(page, key, expected)
            assert pressed(page, key) == expected, f"{key} after {name}"
            assert pressed(other, key) == expected, f"{key} after {name}, in the other tab"
        assert chosen == set(DEFAULTS[key])
    # all of a subset's buttons can be off at once
    config_tab(page, "tag_fields")
    for name in DEFAULTS["tag_fields"]:
        page.click(f"#config-sheet [data-pref=tag_fields] button:text-is('{name}')")
    pref_is(other, "tag_fields", [])
    assert pressed(other, "tag_fields") == []


def press_at_once(page, key, *names):
    """Press subset buttons one after another in a single task, so that no
    frame from the server can land between the presses."""
    page.eval_on_selector(
        f"#config-sheet [data-pref={key}]",
        "(group, names) => { for (const name of names) [...group.children].find(b => b.textContent === name).click(); }",
        list(names),
    )


def test_two_subset_buttons_pressed_before_the_server_answers_both_count(page, other):
    """The store only holds what the server has said, so the second press
    must build on what the first asked for, not on the list before it."""
    spy_on_sends(page)
    config_tab(page, "tag_fields")
    press_at_once(page, "tag_fields", "TYPE", "GS")
    both = ["CALLSIGN", "TYPE", "ALT", "GS"]
    pref_is(other, "tag_fields", both)
    pref_is(page, "tag_fields", both)
    assert page.evaluate("window.sent") == [
        {"t": "prefs", "tag_fields": ["CALLSIGN", "TYPE", "ALT"]},
        {"t": "prefs", "tag_fields": both},
    ]
    assert pressed(page, "tag_fields") == both and pressed(other, "tag_fields") == both
    # Answered, the page works from the server's list again: a press here
    # does not undo what another tab has chosen since.
    set_prefs(other, tag_fields=["CALLSIGN"])
    pref_is(page, "tag_fields", ["CALLSIGN"])
    page.click("#config-sheet [data-pref=tag_fields] button:text-is('TRK')")
    pref_is(other, "tag_fields", ["CALLSIGN", "TRK"])
    pref_is(page, "tag_fields", ["CALLSIGN", "TRK"])  # the other tab may be told first
    assert pressed(page, "tag_fields") == ["CALLSIGN", "TRK"]


def test_a_subset_button_pressed_twice_before_the_server_answers_ends_where_it_began(page, other):
    spy_on_sends(page)
    config_tab(page, "box_items")
    press_at_once(page, "box_items", "HUD", "RINGS", "HUD")
    pref_is(other, "box_items", ["RINGS"])
    pref_is(page, "box_items", ["RINGS"])
    assert [message["box_items"] for message in page.evaluate("window.sent")] == [["HUD"], ["RINGS", "HUD"], ["RINGS"]]
    assert pressed(page, "box_items") == ["RINGS"]


def test_a_subset_press_the_server_never_got_is_forgotten_at_the_next_snapshot(page, other):
    """A message sent as the socket dies is lost, and the snapshot after the
    reconnect is the whole truth: the next press builds on that, not on a
    list nobody was sent."""
    config_tab(page, "tag_fields")
    # The next message goes nowhere, and its socket is dropped.
    page.evaluate(
        """() => { const send = WebSocket.prototype.send;
                   WebSocket.prototype.send = function () { WebSocket.prototype.send = send; this.close(); };
                   window.kcgx.store.subscribe(kind => { if (kind === "all") window.again = true; }); }"""
    )
    page.click("#config-sheet [data-pref=tag_fields] button:text-is('TYPE')")
    page.wait_for_function("window.again === true")  # reconnected: the snapshot is in
    assert pressed(page, "tag_fields") == DEFAULTS["tag_fields"]
    page.click("#config-sheet [data-pref=tag_fields] button:text-is('GS')")
    pref_is(other, "tag_fields", ["CALLSIGN", "ALT", "GS"])
    pref_is(page, "tag_fields", ["CALLSIGN", "ALT", "GS"])


@pytest.mark.parametrize("key", FLAGS)
def test_a_flag_is_off_or_on_and_reaches_a_second_tab(page, other, key):
    config_tab(page, key)
    for label, value in (("ON", True), ("OFF", False)):
        page.click(f"#config-sheet [data-pref={key}] button:text-is('{label}')")
        pref_is(other, key, value)
        pref_is(page, key, value)
        assert pressed(page, key) == [label] and pressed(other, key) == [label]
        if key in ON_HTML:
            assert other.get_attribute("html", f"data-{key}") == label
            assert page.get_attribute("html", f"data-{key}") == label


def test_a_choice_segment_group_has_one_pressed_button(page, other):
    for key, spec in SEGMENTED.items():
        config_tab(page, key)
        for name in spec.names:
            page.click(f"#config-sheet [data-pref={key}] button:text-is('{name}')")
            pref_is(other, key, name)
            pref_is(page, key, name)
            assert pressed(page, key) == [name] and pressed(other, key) == [name]
            if key in ON_HTML:
                assert other.get_attribute("html", f"data-{key}") == name
        set_prefs(page, **{key: DEFAULTS[key]})


@pytest.mark.parametrize("key", sorted(DROPDOWNS))
def test_a_dropdown_reaches_a_second_tab(page, other, key):
    config_tab(page, key)
    select = f"#config-sheet select[data-pref={key}]"
    for name in (SCHEMA[key].names[-1], DEFAULTS[key]):
        page.select_option(select, name)
        pref_is(other, key, name)
        pref_is(page, key, name)
        assert other.input_value(select) == name


def test_a_slider_in_hand_is_not_moved_by_another_tab(page, other):
    """As the volume slider: a frame from the server must not pull a slider
    out from under the pointer. It catches up when it is let go."""
    config_tab(page, "box_pad")
    held = "#config-sheet input[data-pref=box_pad]"
    page.focus(held)
    set_prefs(other, box_pad=9, box_width=3)
    pref_is(page, "box_pad", 9)
    pref_is(page, "box_width", 3)
    assert page.input_value(held) == str(DEFAULTS["box_pad"])
    assert page.input_value("#config-sheet input[data-pref=box_width]") == "3", "a slider not in hand did not follow"
    page.focus("#config-sheet input[data-pref=box_width]")
    assert page.input_value(held) == "9"
    assert readout(page, "box_pad") == "9 PX"


def test_a_slider_with_a_send_still_to_go_is_not_moved_by_a_frame(page, other):
    """In hand without the focus: between a drag's last step and the message
    it sends 80 ms later, a frame must not move the slider, or the message
    would carry the frame's value instead of the one dragged to. The frame is
    handed to the store as the socket hands one over, in the task that drags,
    because nothing from a real second tab can be timed to land in that wait."""
    spy_on_sends(page)
    config_tab(page, "box_pad")
    held = "#config-sheet input[data-pref=box_pad]"
    assert not page.evaluate("document.activeElement.matches('[data-pref=box_pad]')")
    # Read back in the same task: the server's answer to the drag follows
    # within moments and says box_width is 1 again.
    dragged, shown, beside = page.eval_on_selector(
        held,
        """slider => { slider.value = "7";
                       slider.dispatchEvent(new Event("input", { bubbles: true }));
                       const { store } = window.kcgx;
                       store.apply({ t: "prefs", ...store.state.prefs, box_pad: 9, box_width: 3 });
                       return [slider.value, slider.parentElement.querySelector("[data-unit]").textContent,
                               document.querySelector("#config-sheet input[data-pref=box_width]").value]; }""",
    )
    assert (dragged, shown) == ("7", "7 PX"), "the frame moved a slider that had not sent yet"
    assert beside == "3", "a slider not in hand did not follow"
    pref_is(other, "box_pad", 7)
    pref_is(page, "box_pad", 7)
    assert page.evaluate("window.sent") == [{"t": "prefs", "box_pad": 7}]
    assert page.input_value(held) == "7" and readout(page, "box_pad") == "7 PX"


def test_the_scanline_sliders_are_disabled_unless_the_display_is_crt(page):
    page.click("#open-config")
    scan = ["scan_opacity", "scan_size"]
    for display in ("CRT", "VECTOR", "OFF", "CRT"):
        page.click(f"#config-sheet [data-pref=display] button:text-is('{display}')")
        pref_is(page, "display", display)
        for key in NUMBERS:
            off = page.is_disabled(f"#config-sheet input[data-pref={key}]")
            assert off == (key in scan and display != "CRT"), f"{key} with display {display}"


def test_a_slider_that_is_off_does_not_offer_itself_to_the_pointer(page):
    """The page draws its own sliders, with a pointer over them. One that is
    disabled must still say so: the rule that draws it must not outrank the
    rule for a control that is off."""
    page.click("#open-config")
    scan = ["scan_opacity", "scan_size"]
    for display in ("VECTOR", "CRT"):
        page.click(f"#config-sheet [data-pref=display] button:text-is('{display}')")
        pref_is(page, "display", display)
        for key in NUMBERS:
            cursor = page.eval_on_selector(f"#config-sheet input[data-pref={key}]", "e => getComputedStyle(e).cursor")
            off = key in scan and display != "CRT"
            assert cursor == ("not-allowed" if off else "pointer"), f"{key} with display {display}"
    assert page.eval_on_selector("#volume", "e => getComputedStyle(e).cursor") == "pointer"


def scan_properties(page):
    return page.evaluate(
        """() => { const css = getComputedStyle(document.documentElement);
                   return ["--scan-alpha", "--scan-size", "--scan-line"].map(n => css.getPropertyValue(n).trim()); }"""
    )


@pytest.mark.parametrize("size, line", [(2, 1), (3, 1), (4, 1), (5, 2), (6, 2), (8, 3)])
def test_the_scanline_size_is_the_pitch_and_the_dark_line_a_third_of_it(page, size, line):
    set_prefs(page, scan_opacity=50, scan_size=size)
    assert scan_properties(page) == ["0.5", f"{size}px", f"{line}px"]
    drawn = page.eval_on_selector(".screen-radar .ovl", "e => getComputedStyle(e).backgroundImage")
    assert "repeating-linear-gradient" in drawn and "0.5)" in drawn, drawn
    assert f"{line}px" in drawn and f"{size}px" in drawn, drawn


@pytest.mark.parametrize("opacity, alpha", [(0, "0"), (34, "0.34"), (100, "1")])
def test_the_scanline_opacity_is_a_percentage(page, opacity, alpha):
    set_prefs(page, scan_opacity=opacity)
    assert scan_properties(page) == [alpha, "3px", "1px"]


def test_the_radars_range_readout_follows_the_setting(page):
    assert page.text_content("#radar-range") == "RNG 40 NM"
    set_prefs(page, range_nm=120)
    page.wait_for_function("document.getElementById('radar-range').textContent === 'RNG 120 NM'")


@pytest.mark.parametrize("width, height", SIZES)
def test_the_config_sheet_fills_the_window_less_a_margin_and_is_centred(page, width, height):
    """Phase G decision 2: full screen, centred, over the radar."""
    page.set_viewport_size({"width": width, "height": height})
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    box = box_of(page, "#config-sheet")
    inner_w, inner_h = page.evaluate("[document.documentElement.clientWidth, window.innerHeight]")
    assert abs(box["width"] - (inner_w - 32)) <= 1 and abs(box["height"] - (inner_h - 32)) <= 1, box
    assert abs(box["left"] - (inner_w - box["right"])) <= 1, "not centred across"
    assert abs(box["top"] - (inner_h - box["bottom"])) <= 1, "not centred down"
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    # Each tab's panel scrolls, and the tab bar and CLOSE stay: the last
    # control of every tab can be reached inside the sheet.
    for tab, keys in TABS.items():
        config_tab(page, tab=tab)
        last = page.locator(f"#config-sheet [data-pref={keys[-1]}]")
        last.scroll_into_view_if_needed()
        at = last.evaluate("e => e.getBoundingClientRect().toJSON()")
        assert at["top"] >= box["top"] and at["bottom"] <= box["bottom"] + 1, f"{tab}: {keys[-1]} is out of the sheet"
        assert at["left"] >= box["left"] - 1 and at["right"] <= box["right"] + 1, f"{tab}: {keys[-1]} is out of the sheet"
        for fixed in ("#config-sheet [role=tablist]", "#config-sheet button[value=close]"):
            stays = box_of(page, fixed)
            assert stays["top"] >= box["top"] and stays["bottom"] <= box["bottom"], f"{tab}: {fixed} scrolled away"
        assert page.evaluate("document.getElementById('config-sheet').scrollTop") == 0, f"{tab}: the sheet itself scrolled"


def test_the_config_sheet_darkens_what_it_covers_as_the_airport_sheet_does(page):
    """It covers the radar now (phase G decision 2), and its backdrop is
    nearly black. The pixel is the radar screen's frame, halfway down its
    left edge, which is in the sheet's 16 px margin: with no display effects
    it is exactly the frame colour."""
    set_prefs(page, display="OFF", **glow(0))
    frame = css_colour(page, "--frame")
    x, y = page.eval_on_selector(
        ".screen-radar", "e => { const r = e.getBoundingClientRect(); return [r.left, Math.round(r.top + r.height / 2)]; }"
    )
    assert x == int(x) and pixel(page, x, y) == frame
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    assert x < box_of(page, "#config-sheet")["left"], "the sheet itself covers the pixel"
    # 85 % black, under the edge of the sheet's own glow, a few px away
    dimmed = pixel(page, x, y)
    assert sum(dimmed) < sum(frame) / 3, f"the config sheet's backdrop left {dimmed}"
    page.click("#config-sheet button[value=close]")
    page.click("#open-airport")
    page.wait_for_selector("#airport-sheet[open]")
    dimmed = pixel(page, x, y)
    assert sum(dimmed) < sum(frame) / 2, f"the airport sheet's backdrop left {dimmed}"


def tabs_state(page):
    """Each tab as [name, selected, tabbable], and the name of the panel shown."""
    return page.evaluate(
        """() => { const sheet = document.getElementById("config-sheet");
                   const tabs = [...sheet.querySelectorAll("[role=tab]")];
                   const shown = [...sheet.querySelectorAll("[role=tabpanel]")].filter(p => p.getClientRects().length);
                   return { tabs: tabs.map(t => [t.textContent, t.getAttribute("aria-selected"), t.tabIndex]),
                            shown: shown.map(p => document.getElementById(p.getAttribute("aria-labelledby")).textContent),
                            focused: document.activeElement.getAttribute("role") === "tab" ? document.activeElement.textContent : null }; }"""
    )


def test_the_config_tabs_open_on_general_and_the_arrow_keys_move_between_them(page):
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    names = list(TABS)
    state = tabs_state(page)
    assert state["tabs"] == [[name, str(i == 0).lower(), 0 if i == 0 else -1] for i, name in enumerate(names)]
    assert state["shown"] == ["GENERAL"]
    page.focus("#config-sheet [role=tab][aria-selected=true]")
    for key, expected in (("ArrowRight", 1), ("ArrowRight", 2), ("ArrowRight", 3), ("ArrowRight", 0),
                          ("ArrowLeft", 3), ("Home", 0), ("End", 3), ("ArrowLeft", 2)):
        page.keyboard.press(key)
        state = tabs_state(page)
        assert state["focused"] == names[expected], key
        assert [t[1] for t in state["tabs"]] == [str(i == expected).lower() for i in range(4)], key
        assert [t[2] for t in state["tabs"]] == [0 if i == expected else -1 for i in range(4)], key
        assert state["shown"] == [names[expected]], key
    # A click picks a tab too, and the sheet reopens on the last one used.
    page.click("#config-sheet [role=tab]:text-is('TRAFFIC')")
    page.keyboard.press("Escape")
    page.wait_for_selector("#config-sheet", state="hidden")
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    assert tabs_state(page)["shown"] == ["TRAFFIC"]
    page.click("#config-sheet button[value=close]")
    page.click("#open-config")
    assert tabs_state(page)["shown"] == ["TRAFFIC"]


def test_a_new_page_opens_the_config_sheet_on_general(page, other):
    config_tab(page, tab="TRACKS")
    other.click("#open-config")
    other.wait_for_selector("#config-sheet[open]")
    assert tabs_state(other)["shown"] == ["GENERAL"]


# -- the map's table ----------------------------------------------------------------

MAP = SCHEMA["map"]


def cell(row, column, part=""):
    return f"#config-sheet [data-pref=map] td[data-row={row}][data-column={column}] {part}".strip()


def test_the_map_grid_has_a_cell_only_where_its_row_has_that_column(page):
    config_tab(page, "map")
    drawn = page.eval_on_selector(
        "#config-sheet [data-pref=map]",
        """table => [...table.tBodies[0].rows].map(tr => [tr.dataset.row,
                       [...tr.querySelectorAll("td[data-column]")].map(td => td.dataset.column),
                       tr.cells.length])""",
    )
    assert [row for row, _, _ in drawn] == list(MAP.rows)
    for row, columns, cells in drawn:
        assert columns == [c for c in MAP.columns if c in MAP.rows[row]], row
        assert cells == 1 + len(MAP.columns), f"{row}: a row's cells do not line up under the headings"
    # each cell shows the default
    for row, cells in MAP.rows.items():
        for column, value in cells.items():
            spec = MAP.columns[column]
            if isinstance(spec, Number):
                assert page.input_value(cell(row, column, "input[type=range]")) == str(value), (row, column)
            else:
                lit = page.eval_on_selector_all(cell(row, column, "button[aria-pressed=true]"), "bs => bs.map(b => b.textContent)")
                assert lit == [value if isinstance(spec, Choice) else ("ON" if value else "OFF")], (row, column)
    assert page.text_content(cell("COAST", "width", "[data-unit]")) == "1.8 PX"  # tenths of a pixel
    assert page.text_content(cell("COAST", "alpha", "[data-unit]")) == "100%"


def test_one_cell_of_the_map_grid_reaches_a_second_tab_and_sends_only_itself(page, other):
    spy_on_sends(page)
    config_tab(page, "map")
    page.fill(cell("CLASS_D", "alpha", "input"), "60")
    assert page.text_content(cell("CLASS_D", "alpha", "[data-unit]")) == "60%"
    other.wait_for_function("window.kcgx.store.state.prefs.map.CLASS_D.alpha === 60")
    assert other.input_value(cell("CLASS_D", "alpha", "input")) == "60"
    page.click(cell("CLASS_D", "line", "button:text-is('DASH')"))
    other.wait_for_function("window.kcgx.store.state.prefs.map.CLASS_D.line === 'DASH'")
    page.click(cell("RIVER", "show", "button:text-is('OFF')"))
    other.wait_for_function("window.kcgx.store.state.prefs.map.RIVER.show === false")
    page.wait_for_function("window.kcgx.store.state.prefs.map.RIVER.show === false")
    assert page.evaluate("window.sent") == [
        {"t": "prefs", "map": {"CLASS_D": {"alpha": 60}}},
        {"t": "prefs", "map": {"CLASS_D": {"line": "DASH"}}},
        {"t": "prefs", "map": {"RIVER": {"show": False}}},
    ]
    assert other.eval_on_selector_all(cell("RIVER", "show", "button[aria-pressed=true]"), "bs => bs.map(b => b.textContent)") == ["OFF"]
    # every other cell is as it was
    final = other.evaluate("window.kcgx.store.state.prefs.map")
    expected = MAP.default
    expected["CLASS_D"].update(alpha=60, line="DASH")
    expected["RIVER"]["show"] = False
    assert final == expected


def test_a_map_slider_in_hand_is_not_moved_by_another_tab(page, other):
    config_tab(page, "map")
    held = cell("COAST", "width", "input")
    page.focus(held)
    set_prefs(other, map={**MAP.default, "COAST": {**MAP.rows["COAST"], "width": 40}, "LAKE": {**MAP.rows["LAKE"], "width": 30}})
    page.wait_for_function("window.kcgx.store.state.prefs.map.COAST.width === 40")
    assert page.input_value(held) == "18"
    assert page.input_value(cell("LAKE", "width", "input")) == "30", "a cell not in hand did not follow"
    page.focus(cell("LAKE", "width", "input"))
    assert page.input_value(held) == "40"
    assert page.text_content(cell("COAST", "width", "[data-unit]")) == "4.0 PX"


# -- the airport picker -----------------------------------------------------------------


@pytest.mark.parametrize("font", [None, "18px"])
@pytest.mark.parametrize("width, height", SIZES)
def test_the_airport_sheet_is_a_fixed_size_centred_whatever_it_finds(page, width, height, font):
    """Phase G decision 20: 840 px wide, min(80vh, 720px) high, whether it
    has found nothing or forty; the results scroll inside it. At any text
    size: the browser's own dialog width cap is in em, and must not apply."""
    page.set_viewport_size({"width": width, "height": height})
    if font:
        page.evaluate(f"document.getElementById('airport-sheet').style.fontSize = '{font}'")
    page.click("#open-airport")
    page.wait_for_selector("#airport-sheet[open]")
    inner_w, inner_h = page.evaluate("[document.documentElement.clientWidth, window.innerHeight]")
    empty = box_of(page, "#airport-sheet")
    assert abs(empty["width"] - min(840, inner_w - 32)) <= 1, empty
    assert abs(empty["height"] - min(0.8 * inner_h, 720)) <= 1, empty
    page.fill("#airport-query", "international")
    page.wait_for_function("document.querySelectorAll('#airport-results .choice').length === 40")
    full = box_of(page, "#airport-sheet")
    assert full == empty, "the sheet changed size with its results"
    assert abs(full["left"] - (inner_w - full["right"])) <= 1 and abs(full["top"] - (inner_h - full["bottom"])) <= 1
    results = page.eval_on_selector("#airport-results", "e => [e.scrollHeight, e.clientHeight, e.getBoundingClientRect().bottom]")
    assert results[0] > results[1], "forty results do not scroll inside their list"
    assert results[2] <= full["bottom"] + 1
    assert page.evaluate("document.getElementById('airport-sheet').scrollTop") == 0
    assert box_of(page, "#airport-query")["top"] >= full["top"], "the search scrolled away"


# -- errors with the teletype hidden ---------------------------------------------


def test_a_page_error_shows_in_the_banner_while_the_teletype_is_hidden(page):
    assert not page.is_visible("#banner")
    # The page's clock is paused, so only the two jumps below move it. Left
    # running, a jump can be lost and the 8 s never come due. pause_at takes
    # seconds.
    page.clock.install()
    page.clock.pause_at(page.evaluate("Date.now()") / 1000 + 1)
    page.evaluate('window.kcgx.store.apply({t: "error", text: "x"})')
    assert page.is_visible("#banner")
    assert page.inner_text("#banner") == "ERROR: X"
    assert "bad" in page.get_attribute("#banner", "class")
    page.clock.fast_forward(7000)
    assert page.is_visible("#banner")
    page.clock.fast_forward(1500)
    assert not page.is_visible("#banner")
    page.clock.resume()  # the waits below poll on the page's timers
    # it was typed on the hidden teletype all the same
    set_prefs(page, teletype=True)
    page.wait_for_function("document.getElementById('log').textContent.includes('ERROR: X')")


def test_a_page_error_leaves_the_banner_alone_while_the_teletype_shows(page):
    set_prefs(page, teletype=True)
    page.evaluate('window.kcgx.store.apply({t: "error", text: "x"})')
    page.wait_for_selector("#log .log-line.alarm:has-text('ERROR: X')")
    assert not page.is_visible("#banner")


def test_a_failed_request_shows_in_the_banner_while_the_teletype_is_hidden(browser, server):
    # Its own page: the browser reports the failed request on the console,
    # which the `page` fixture would count as an error.
    page = browser.new_page()
    try:
        page.goto(server + "/")
        page.wait_for_selector(".feed.expanded")
        set_prefs(page, teletype=False)
        page.route("**/api/airports?*", lambda route: route.fulfill(status=500, json={"error": "no such luck"}))
        page.click("#open-airport")
        page.fill("#airport-query", "seattle")
        page.wait_for_selector("#banner.bad:text-is('AIRPORT SEARCH FAILED: NO SUCH LUCK')")
    finally:
        page.close()


def test_turning_the_teletype_on_clears_a_page_error_from_the_banner(page):
    page.evaluate('window.kcgx.store.apply({t: "error", text: "x"})')
    assert page.is_visible("#banner")
    set_prefs(page, teletype=True)
    page.wait_for_selector("#banner", state="hidden")


def test_a_server_note_does_not_reach_the_banner(page):
    page.evaluate('window.kcgx.store.apply({t: "message", z: "1200Z", text: "tower offline"})')
    page.wait_for_timeout(100)
    assert not page.is_visible("#banner")


def test_the_teletype_opens_on_its_newest_line(page):
    page.evaluate(
        """for (let i = 0; i < 80; i += 1) window.kcgx.store.apply({t: "message", z: "1200Z", text: `line ${i}`})"""
    )
    set_prefs(page, teletype=True)
    page.wait_for_function(
        """() => { const log = document.getElementById('log');
                   return log.scrollHeight > log.clientHeight + 40
                       && log.scrollHeight - log.scrollTop - log.clientHeight < 24; }"""
    )


# -- the radar -----------------------------------------------------------------


def test_the_map_loads_for_the_airport_and_draws_its_places(page):
    wait_for_traffic(page)
    debug = radar_debug(page)
    assert debug["mapFor"] == "KPDX"
    assert debug["layers"]["coast"] > 0 and debug["layers"]["river"] > 0
    keys = {p["key"] for p in debug["placed"]}
    assert "home" in keys
    assert any(k.startswith("navaid:") for k in keys) and any(k.startswith("city:") for k in keys)


def test_every_aircraft_on_the_radar_is_a_row_in_the_table(page):
    wait_for_traffic(page)
    # Compared inside one evaluation, and retried, so a poll arriving between
    # reading the radar and reading the table cannot make them disagree.
    page.wait_for_function(
        """() => {
            const radar = window.kcgx.radar.debug().hits.map(h => h.hex).sort();
            const rows = [...document.querySelectorAll('#tracks-body tr')].map(r => r.dataset.hex).sort();
            const hud = document.getElementById('radar-tracks').textContent;
            return rows.length >= 5 && radar.join() === rows.join() && hud === `${rows.length} TRACKS`;
        }"""
    )


def test_clicking_an_aircraft_focuses_it_and_the_table_follows(page):
    wait_for_traffic(page)
    hits = radar_debug(page)["hits"]
    # One with no other aircraft within 40 px, so the click cannot land on a neighbour.
    hit = next(
        h for h in hits
        if all(o is h or abs(o["x"] - h["x"]) + abs(o["y"] - h["y"]) > 40 for o in hits)
    )
    page.mouse.click(*on_screen(page, hit["x"], hit["y"]))
    page.wait_for_selector(f'#tracks-body tr.focused[data-hex="{hit["hex"]}"]')
    assert page.eval_on_selector_all("#tracks-body tr.dimmed", "rs => rs.length") >= 4
    # the callsign in the table is the same switch
    page.click(f'#tracks-body tr[data-hex="{hit["hex"]}"] .callsign')
    page.wait_for_function("document.querySelectorAll('#tracks-body tr.focused, #tracks-body tr.dimmed').length === 0")


def column(table, title):
    """One column of `rows`, as the numbers the table sorts by."""
    index = ["CALLSIGN", "TYPE", "ALT FT", "GS KT", "TRK", "DIST NM", "SQWK"].index(title)
    return [0.0 if row["cells"][index] == "GND" else float(row["cells"][index] or -1) for row in table]


def test_the_focused_aircraft_leads_the_table_and_the_rest_stay_sorted(page):
    hex_ = focus_on_the_radar(page)
    table = rows(page)
    assert table[0]["hex"] == hex_ and table[0]["focused"]
    assert [row["hex"] for row in table].count(hex_) == 1
    rest = column(table[1:], "DIST NM")
    assert rest == sorted(rest), "the rows under the focused one are not in distance order"
    assert column(table, "DIST NM")[0] > rest[0], "the focused row was first by distance anyway"


def test_the_focused_row_is_set_a_fifth_larger_in_every_cell(page):
    focus_on_the_radar(page)
    sizes = page.eval_on_selector_all(
        "#tracks-body tr",
        """trs => trs.slice(0, 2).map(tr =>
            [...tr.cells, tr.querySelector(".callsign")].map(e => parseFloat(getComputedStyle(e).fontSize)))""",
    )
    focused, neighbour = sizes
    assert len(focused) == 8
    for large, usual in zip(focused, neighbour):
        assert large == pytest.approx(1.2 * usual, abs=0.1)


def test_sorting_leaves_the_focused_row_first_and_sorts_the_rest(page):
    hex_ = focus_on_the_radar(page)
    page.click("#tracks-head button:text-is('ALT FT')")
    # The sort is a setting: the table sorts on the server's answer.
    page.wait_for_selector("#tracks-head th[aria-sort=ascending]:has(button:text-is('ALT FT'))")
    table = rows(page)
    assert table[0]["hex"] == hex_ and table[0]["focused"]
    rest = column(table[1:], "ALT FT")
    assert rest == sorted(rest) and len(set(rest)) > 1
    page.click("#tracks-head button:text-is('ALT FT')")
    page.wait_for_selector("#tracks-head th[aria-sort=descending]:has(button:text-is('ALT FT'))")
    table = rows(page)
    assert table[0]["hex"] == hex_
    rest = column(table[1:], "ALT FT")
    assert rest == sorted(rest, reverse=True)


def test_unfocusing_returns_the_row_to_its_sorted_place(page):
    hex_ = focus_on_the_radar(page)
    assert rows(page)[0]["hex"] == hex_
    page.click(f'#tracks-body tr[data-hex="{hex_}"] .callsign')
    page.wait_for_function("document.querySelectorAll('#tracks-body tr.focused, #tracks-body tr.dimmed').length === 0")
    table = rows(page)
    dists = column(table, "DIST NM")
    assert dists == sorted(dists)
    assert table[0]["hex"] != hex_
    sizes = set(page.eval_on_selector_all("#tracks-body td", "tds => tds.map(td => getComputedStyle(td).fontSize)"))
    assert len(sizes) == 1, "a row is still set larger"


def test_focusing_scrolls_the_table_back_to_its_top(page):
    page.set_viewport_size({"width": 1280, "height": 720})
    wait_for_traffic(page)
    page.wait_for_function("document.querySelectorAll('#tracks-body tr').length >= 5")
    scrolled = page.eval_on_selector(".tracks-body", "e => { e.scrollTop = e.scrollHeight; return e.scrollTop; }")
    assert scrolled > 0, "the table does not scroll at this size, so the test shows nothing"
    hex_ = focus_on_the_radar(page)
    assert page.eval_on_selector(".tracks-body", "e => e.scrollTop") == 0
    assert rows(page)[0]["hex"] == hex_


def first_row_in_the_window(page):
    """Where the table's first row is against the window: (top, bottom, window height)."""
    return page.eval_on_selector(
        "#tracks-body tr", "tr => { const r = tr.getBoundingClientRect(); return [r.top, r.bottom, innerHeight]; }"
    )


def test_a_callsign_pressed_far_down_a_one_column_page_brings_its_row_back_into_view(page):
    # In one column the page scrolls, and since phase G the table scrolls
    # within its pane too (at most 70vh): a window too short to hold the
    # table has its first row out of sight when its last row is in view.
    page.set_viewport_size({"width": 390, "height": 180})
    wait_for_traffic(page)
    page.wait_for_function("document.querySelectorAll('#tracks-body tr').length >= 5")
    hex_ = rows(page)[-1]["hex"]
    callsign = page.locator(f'#tracks-body tr[data-hex="{hex_}"] .callsign')
    callsign.scroll_into_view_if_needed()
    top, _, _ = first_row_in_the_window(page)
    assert top < 0, "the first row is in view already, so the test shows nothing"
    callsign.click()
    page.wait_for_selector(f'#tracks-body tr.focused[data-hex="{hex_}"]')
    assert rows(page)[0]["hex"] == hex_
    top, bottom, window = first_row_in_the_window(page)
    # to the pixel: the page scrolls by whole pixels and the row sits on a fraction of one
    assert top > -1 and bottom < window + 1, f"the focused row is at {top} to {bottom} in a window {window} high"


def test_focusing_on_the_radar_leaves_a_one_column_page_where_it_is(page):
    # The table is below the radar there, and following the row would take
    # the radar, and the aircraft just clicked, out of sight.
    page.set_viewport_size({"width": 390, "height": 844})
    focus_on_the_radar(page)
    top, _, window = first_row_in_the_window(page)
    assert top > window, "the table is in view at this size, so the test shows nothing"
    assert page.evaluate("scrollY") == 0


def test_place_names_brighten_under_the_pointer(page):
    wait_for_traffic(page)
    size = page.eval_on_selector("#radar", "c => [c.width, c.height]")
    label = next(
        p for p in radar_debug(page)["placed"]
        if p["key"].startswith(("city:", "navaid:")) and p["x"] > 0 and p["y"] > 0
        and p["x"] + p["w"] < size[0] and p["y"] + p["h"] < size[1]
    )
    page.mouse.move(*on_screen(page, label["x"] + label["w"] / 2, label["y"] + label["h"] / 2))
    page.wait_for_function(f"window.kcgx.radar.debug().hovered === {label['key']!r}")
    page.mouse.move(5, 5)
    page.wait_for_function("window.kcgx.radar.debug().hovered === null")


def test_the_wheel_zooms_in_to_a_quarter_mile_and_no_further(page):
    wait_for_traffic(page)
    page.mouse.move(*centre_of_the_radar(page))
    turn_wheel(page, -600)
    assert 0.25 < radar_debug(page)["view"]["nm"] < 40
    for _ in range(5):
        turn_wheel(page, -600)
    assert radar_debug(page)["view"]["nm"] == 0.25
    turn_wheel(page, -600)
    assert radar_debug(page)["view"]["nm"] == 0.25


def view_at_2_5_nm(page):
    """The view the wheel closed in to before it went on to a quarter mile
    (phase G Task 10): 2.5 nm about the airport."""
    page.evaluate(
        """() => window.kcgx.radar.hook((radar) => {
            Object.assign(radar.view, { nm: 2.5, panX: 0, panY: 0 }); radar.staticDirty = true; })()"""
    )
    frames(page)


@pytest.mark.parametrize("range_nm, widest", [(40, 160), (250, 250)])
def test_the_wheel_zooms_out_to_160_nm_or_to_the_range_if_that_is_wider(page, range_nm, widest):
    wait_for_traffic(page)
    set_prefs(page, range_nm=range_nm)
    page.wait_for_function("nm => window.kcgx.radar.debug().view.nm === nm", arg=range_nm)
    page.mouse.move(*centre_of_the_radar(page))
    turn_wheel(page, -600)
    assert radar_debug(page)["view"]["nm"] < range_nm
    for _ in range(5):
        turn_wheel(page, 600)
    assert radar_debug(page)["view"]["nm"] == widest
    turn_wheel(page, 600)
    assert radar_debug(page)["view"]["nm"] == widest


def test_the_range_ring_fits_the_shorter_side_less_18_px(page):
    wait_for_traffic(page)
    debug = radar_drawn(page)
    assert debug["view"] == {"nm": 40, "panX": 0, "panY": 0}
    width, height = canvas_size(page)
    assert (debug["home"]["x"], debug["home"]["y"]) == (width / 2, height / 2)
    assert [(ring["nm"], ring["bright"]) for ring in debug["rings"]] == [
        (10, False), (20, False), (30, False), (40, True),
    ]
    assert debug["rings"][-1]["r"] == pytest.approx(fit(page))
    assert [ring["text"] for ring in debug["rings"]] == ["10", "20", "30", "40"]


def test_at_2_5_nm_the_rings_are_half_a_mile_apart_and_numbered_plainly(page):
    wait_for_traffic(page)
    view_at_2_5_nm(page)
    debug = radar_drawn(page)
    assert debug["view"]["nm"] == 2.5
    width, height = canvas_size(page)
    home = debug["home"]
    whole = [
        ring for ring in debug["rings"]
        if home["x"] - ring["r"] >= 0 and home["x"] + ring["r"] <= width
        and home["y"] - ring["r"] >= 0 and home["y"] + ring["r"] <= height
    ]
    assert len(whole) >= 2
    assert [ring["nm"] for ring in whole] == [0.5, 1, 1.5, 2, 2.5]
    assert [ring["text"] for ring in whole] == ["0.5", "1", "1.5", "2", "2.5"]
    assert whole[-1]["r"] == pytest.approx(fit(page))
    # every ring listed is one that crosses the screen
    corner = max(
        ((x - home["x"]) ** 2 + (y - home["y"]) ** 2) ** 0.5 for x in (0, width) for y in (0, height)
    )
    assert all(ring["r"] <= corner for ring in debug["rings"])


def test_a_new_range_resets_the_view_and_draws_its_ring(page):
    wait_for_traffic(page)
    x, y = on_screen(page, 300, 300)
    page.mouse.move(x, y)
    turn_wheel(page, -500)
    pan(page, x, y)
    view = radar_debug(page)["view"]
    assert view["nm"] < 27 and view["panX"] != 0 and view["panY"] != 0
    set_prefs(page, range_nm=120)
    debug = radar_drawn(page)
    assert debug["view"] == {"nm": 120, "panX": 0, "panY": 0}
    assert [(ring["nm"], ring["bright"]) for ring in debug["rings"]] == [(50, False), (100, False), (120, True)]
    r = debug["rings"][-1]["r"]
    assert r == pytest.approx(fit(page))
    # and it is on the canvas, where it is said to be
    home = debug["home"]
    for dx, dy in [(0, -1), (1, 0), (0, 1), (-1, 0)]:
        assert lit(page, home["x"] + dx * r, home["y"] + dy * r) > 60, (dx, dy)


def test_a_new_range_under_a_held_drag_leaves_the_drag_going_from_the_new_view(page):
    """Another tab, or the keyboard on the slider, can change the range while
    the radar is held: the drag carries on from the reset view, not from the
    pan it began with."""
    wait_for_traffic(page)
    x, y = on_screen(page, 300, 300)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 120, y + 60, steps=6)
    held = radar_debug(page)["view"]
    assert held["panX"] != 0 and held["panY"] != 0
    set_prefs(page, range_nm=120)
    assert radar_debug(page)["view"] == {"nm": 120, "panX": 0, "panY": 0}
    page.mouse.move(x + 150, y + 80)
    page.mouse.up()
    per_nm = fit(page) / 120
    ratio = page.evaluate("devicePixelRatio")
    view = radar_debug(page)["view"]
    assert view["nm"] == 120
    assert view["panX"] == pytest.approx(-30 * ratio / per_nm)
    assert view["panY"] == pytest.approx(-20 * ratio / per_nm)
    # and the press that ends it is still the end of a drag, not a click
    page.mouse.dblclick(x, y)
    assert radar_debug(page)["view"] == {"nm": 120, "panX": 0, "panY": 0}


def test_a_new_range_that_is_the_view_already_held_is_not_drawn_until_the_next_frame(page):
    """Zoomed out to 160 about the airport and then given a range of 160, the
    view does not change but the rings do: radar_drawn must wait for them."""
    wait_for_traffic(page)
    page.mouse.move(*centre_of_the_radar(page))
    for _ in range(4):
        turn_wheel(page, 600)
    # About the canvas's middle, which is on half a pixel when its height is
    # odd (the tracks row is a percentage of the page since phase G): a
    # fraction of a nautical mile of pan, which the new range resets.
    held = radar_drawn(page)["view"]
    assert held["nm"] == 160 and abs(held["panX"]) < 0.5 and abs(held["panY"]) < 0.5, held
    page.evaluate(
        """drawn => window.kcgx.store.subscribe((kind) => {
               if (kind === "prefs") window.drawnAtPrefs = new Function("return (" + drawn + ")()")(); })""",
        RADAR_DRAWN,
    )
    set_prefs(page, range_nm=160)
    assert page.evaluate("window.drawnAtPrefs") is False
    debug = radar_drawn(page)
    assert debug["view"] == {"nm": 160, "panX": 0, "panY": 0}
    assert [(ring["nm"], ring["bright"]) for ring in debug["rings"]] == [
        (50, False), (100, False), (150, False), (160, True),
    ]


def overlap(a, b, gap=0):
    return (
        a["x"] < b["x"] + b["w"] + gap and b["x"] < a["x"] + a["w"] + gap
        and a["y"] < b["y"] + b["h"] + gap and b["y"] < a["y"] + a["h"] + gap
    )


def nearest(box, x, y):
    """How far (x, y) is from the nearest point of `box`."""
    dx = max(box["x"] - x, 0, x - box["x"] - box["w"])
    dy = max(box["y"] - y, 0, y - box["y"] - box["h"])
    return (dx * dx + dy * dy) ** 0.5


def test_ring_numbers_sit_on_the_north_east_diagonal_just_outside_their_rings(page):
    """All but the 10's: it would lie on the airport's name, and a ring
    number gives way to the name, bare or boxed (the owner's decision in
    phase G's Task 10 review)."""
    wait_for_traffic(page)
    debug = radar_drawn(page)
    ratio = page.evaluate("devicePixelRatio")
    home = debug["home"]
    assert [ring["text"] for ring in debug["rings"] if ring["label"]] == ["20", "30", "40"]
    for ring in debug["rings"]:
        if not ring["label"]:
            continue
        d = ring["r"] * 0.5**0.5
        label = ring["label"]
        assert label["x"] == pytest.approx(home["x"] + d + 4 * ratio)
        assert label["y"] + label["h"] == pytest.approx(home["y"] - d - 4 * ratio)
        assert label["w"] > 0 and label["h"] == 12 * ratio


@pytest.mark.parametrize(
    "range_nm, dim, unnumbered", [(210, [50, 100, 150, 200], [50, 200]), (120, [50, 100], [50])],
)
def test_a_ring_number_that_would_touch_the_ranges_is_left_off(page, range_nm, dim, unnumbered):
    """Ten miles past a multiple of a 50 nm step, the last dim ring is a few
    pixels inside the range's: its number gives way, the ring stays. (The
    50's gives way to the airport's name.)"""
    wait_for_traffic(page)
    set_prefs(page, range_nm=range_nm)
    debug = radar_drawn(page)
    rings = debug["rings"]
    assert [ring["nm"] for ring in rings] == [*dim, range_nm]
    assert rings[-1]["bright"] and rings[-1]["label"]
    assert [ring["nm"] for ring in rings if not ring["label"]] == unnumbered
    ratio = page.evaluate("devicePixelRatio")
    labels = [ring["label"] for ring in rings if ring["label"]]
    for i, a in enumerate(labels):
        assert not any(overlap(a, b, 2 * ratio) for b in labels[i + 1:]), a


@pytest.mark.parametrize("side", ["above", "below"])
def test_ring_numbers_follow_the_rings_when_the_airport_is_off_the_screen(page, side):
    """Panned so the airport is off the screen, every number goes where its
    ring passes nearest the middle: above, the north east diagonal is off the
    screen too, and below, it is still on it for some rings and is not used."""
    wait_for_traffic(page)
    width, height = canvas_size(page)
    ratio = page.evaluate("devicePixelRatio")
    x, top = on_screen(page, width / 2, 0)
    near, far = top + 40 / ratio, top + (height - 100) / ratio
    start, end = (far, near) if side == "above" else (near, far)
    page.mouse.move(x, start)
    page.mouse.down()
    page.mouse.move(x, end, steps=8)
    page.mouse.up()
    debug = radar_drawn(page)
    home = debug["home"]
    off = home["y"] + home["r"] < 0 if side == "above" else home["y"] - home["r"] > height
    assert off, "the test wants the airport and its ring off the screen"
    assert len(debug["rings"]) >= 2
    for ring in debug["rings"]:
        label = ring["label"]
        assert label, ring
        assert label["x"] >= 0 and label["y"] >= 0, ring
        assert label["x"] + label["w"] <= width and label["y"] + label["h"] <= height, ring
        # beside its own ring, outside it
        assert ring["r"] <= nearest(label, home["x"], home["y"]) <= ring["r"] + 8 * ratio, ring
        # and in line with the airport and the middle of the screen
        assert abs(label["x"] - home["x"]) <= 8 * ratio, ring


def test_a_ring_number_that_would_sit_on_the_home_ring_is_left_off(page):
    """At 2.5 nm the half mile ring is inside the home ring, and its number
    would land on it."""
    wait_for_traffic(page)
    view_at_2_5_nm(page)
    debug = radar_drawn(page)
    ratio = page.evaluate("devicePixelRatio")
    home = debug["home"]
    by_nm = {ring["nm"]: ring for ring in debug["rings"]}
    assert by_nm[0.5]["r"] < home["r"], "the test wants a ring inside the home ring"
    assert by_nm[0.5]["label"] is None
    # (the 1's is left off for the airport's name)
    assert [nm for nm in (1, 1.5, 2, 2.5) if by_nm[nm]["label"]] == [1.5, 2, 2.5]
    for ring in debug["rings"]:
        if ring["label"]:
            assert nearest(ring["label"], home["x"], home["y"]) >= home["r"] + 4 * ratio, ring


def test_a_setting_other_than_the_range_leaves_the_view_alone(page):
    wait_for_traffic(page)
    x, y = on_screen(page, 300, 300)
    page.mouse.move(x, y)
    turn_wheel(page, -500)
    pan(page, x, y)
    view = radar_debug(page)["view"]
    assert view["nm"] < 27 and view["panX"] != 0
    set_prefs(page, **glow(75), range_nm=40)
    assert radar_debug(page)["view"] == view


def test_the_home_ring_is_2_5_nm_held_between_24_and_64_px(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    px_per_nm = fit(page) / 40
    assert 2.5 * px_per_nm < 24 * ratio, "2.5 nm is over 24 px at this size, so the test shows nothing"
    assert radar_drawn(page)["home"]["r"] == 24 * ratio
    page.mouse.move(*centre_of_the_radar(page))
    turn_wheel(page, -600)
    debug = radar_drawn(page)
    true_size = 2.5 * fit(page) / debug["view"]["nm"]
    assert 24 * ratio < true_size < 64 * ratio, "the test wants a view where 2.5 nm is between the limits"
    assert debug["home"]["r"] == pytest.approx(true_size)
    zoom_right_in(page)
    # and the airport's name is still beside the ring, not out at 2.5 nm
    debug = radar_drawn(page)
    assert debug["home"]["r"] == 64 * ratio
    name = next(p for p in debug["placed"] if p["key"] == "home")
    assert 0 < name["x"] - debug["home"]["x"] <= 64 * ratio
    assert 0 < debug["home"]["y"] - (name["y"] + name["h"]) <= 64 * ratio


def test_small_airports_show_from_a_27_nm_view(page):
    wait_for_traffic(page)
    page.mouse.move(*centre_of_the_radar(page))
    turn_wheel(page, -250)
    wide = radar_drawn(page)
    assert 27 < wide["view"]["nm"] < 28
    turn_wheel(page, -20)
    close = radar_drawn(page)
    assert 26 < close["view"]["nm"] <= 27
    # A closer view shows less ground, so more airports on it are new ones.
    assert close["symbols"]["airport"] > wide["symbols"]["airport"]
    assert close["symbols"]["navaid"] <= wide["symbols"]["navaid"]


def test_the_wheel_zooms_dragging_pans_and_a_double_click_recentres(page):
    wait_for_traffic(page)
    set_prefs(page, range_nm=120)
    page.wait_for_function("window.kcgx.radar.debug().view.nm === 120")
    x, y = on_screen(page, 300, 300)
    page.mouse.move(x, y)
    page.mouse.wheel(0, -500)
    page.wait_for_function("window.kcgx.radar.debug().view.nm < 80")
    page.mouse.down()
    page.mouse.move(x + 120, y + 60, steps=6)
    page.mouse.up()
    view = radar_debug(page)["view"]
    assert view["panX"] != 0 and view["panY"] != 0
    page.mouse.dblclick(x, y)
    assert radar_debug(page)["view"] == {"nm": 120, "panX": 0, "panY": 0}


def test_two_quick_pans_from_one_spot_are_not_a_double_click(page):
    """Scrubbing the map: the browser counts the second press as the second
    click of a double click, and the pans must survive it."""
    wait_for_traffic(page)
    x, y = on_screen(page, 300, 300)
    pan(page, x, y)
    once = radar_debug(page)["view"]
    assert once["panX"] != 0 and once["panY"] != 0
    pan(page, x, y, click_count=2)
    twice = radar_debug(page)["view"]
    assert twice["nm"] == 40
    assert twice["panX"] == pytest.approx(2 * once["panX"]) and twice["panY"] == pytest.approx(2 * once["panY"])


def test_a_click_straight_after_a_pan_is_not_a_double_click(page):
    wait_for_traffic(page)
    x, y = on_screen(page, 300, 300)
    pan(page, x, y)
    panned = radar_debug(page)["view"]
    assert panned["panX"] != 0
    # one press, which the browser counts as the second of a double click
    # (mouse.click with click_count=2 would press twice)
    page.mouse.move(x, y)
    page.mouse.down(click_count=2)
    page.mouse.up(click_count=2)
    assert radar_debug(page)["view"] == panned
    # and two clicks after that are a double click again
    page.mouse.dblclick(x, y)
    assert radar_debug(page)["view"] == {"nm": 40, "panX": 0, "panY": 0}


def test_the_readout_follows_a_double_click(page):
    """The bearing and distance under the pointer are for the view on screen,
    without waiting for the pointer to move."""
    wait_for_traffic(page)
    x, y = on_screen(page, 300, 300)
    page.mouse.move(x, y)
    centred = page.inner_text("#radar-position")
    assert re.fullmatch(r"\d{3}° \d+\.\d NM", centred)
    page.mouse.wheel(0, -500)
    page.wait_for_function("window.kcgx.radar.debug().view.nm < 27")
    pan(page, x, y)
    page.mouse.move(x, y)
    assert page.inner_text("#radar-position") != centred
    page.mouse.dblclick(x, y)
    assert radar_debug(page)["view"] == {"nm": 40, "panX": 0, "panY": 0}
    assert page.inner_text("#radar-position") == centred


def test_a_column_header_sorts_the_table(page):
    wait_for_traffic(page)
    page.wait_for_selector("#tracks-body tr")
    page.click("#tracks-head button:text-is('ALT FT')")
    # The sort is a setting: the table sorts on the server's answer.
    page.wait_for_selector("#tracks-head th[aria-sort=ascending]:has(button:text-is('ALT FT'))")
    alts = page.eval_on_selector_all(
        "#tracks-body tr td:nth-child(3)", "cells => cells.map(c => c.textContent === 'GND' ? 0 : Number(c.textContent))"
    )
    assert alts == sorted(alts)
    page.click("#tracks-head button:text-is('ALT FT')")
    page.wait_for_selector("#tracks-head th[aria-sort=descending]:has(button:text-is('ALT FT'))")
    alts = page.eval_on_selector_all("#tracks-body tr td:nth-child(3)", "cells => cells.map(c => Number(c.textContent))")
    assert alts == sorted(alts, reverse=True)


def test_an_emergency_squawk_lights_the_lamp_and_turns_the_row_red(page):
    wait_for_traffic(page)
    set_prefs(page, lamps=True)
    page.evaluate(
        """window.kcgx.store.apply({t: "aircraft", ok: true, error: "", age: 0, refresh: 15, range: 40,
            ac: [{hex: "e1", label: "N52RT", type: "BE36", lat: 45.9, lon: -123.0, alt: 7500, gs: 150,
                  trk: 120, sq: "7600", age: 0, dist: 25.2, brg: 315}]})"""
    )
    page.wait_for_selector(".lamp.emerg .lamp-label:text-is('7600')")
    assert page.get_attribute('#tracks-body tr[data-hex="e1"]', "class") == "emergency"


def test_a_refused_radar_says_so_and_dims_its_lamp(page):
    wait_for_traffic(page)
    set_prefs(page, lamps=True)
    page.evaluate(
        """window.kcgx.store.apply({t: "aircraft", ok: false, error: "ERR 429", age: 40, refresh: 15,
            range: 40, ac: []})"""
    )
    page.wait_for_function("document.getElementById('radar-poll').textContent.startsWith('ERR 429')")
    assert "warn" in page.get_attribute(".lamp:has(.lamp-label:text-is('RADAR'))", "class")


# -- flight tags and label boxes ----------------------------------------------------

FIELDS = list(SCHEMA["tag_fields"].names)
ITEMS = list(SCHEMA["box_items"].names)
BLACK = (0, 0, 0, 255)
EVERY_FIELD = {"label": "DAL1388", "type": "A321", "sq": "2251", "alt": 5900, "gs": 310, "trk": 30, "dist": 14.3}


def test_by_default_a_tag_is_one_line_the_callsign_and_the_altitude(page):
    wait_for_traffic(page)
    drawn = hold_traffic(
        page, plane("a1", -10, 5, label="DAL1388", alt=5900), plane("a2", 10, 5, label="N52RT", alt="GND"),
        plane("a3", 0, -10, label="UNK1", alt=None), plane("a4", 0, 12, label="N7243K", alt=0),
    )
    assert {hex_: tag["lines"] for hex_, tag in drawn.items()} == {
        "a1": ["DAL1388 5900"], "a2": ["N52RT GND"], "a3": ["UNK1"], "a4": ["N7243K 0"],
    }
    assert all(tag["w"] > 0 and tag["h"] > 0 and not tag["boxed"] and tag["box"] is None for tag in drawn.values())


def test_the_demos_own_traffic_is_tagged_with_callsign_and_altitude(page):
    wait_for_traffic(page)
    # Compared inside one evaluation, and retried: a poll can land between two.
    page.wait_for_function(
        """() => { const ac = window.kcgx.store.state.radar.ac;
                   const hits = window.kcgx.radar.debug().hits;
                   return ac.length >= 5 && hits.length === ac.length && hits.every((hit, i) =>
                       hit.tag && hit.tag.lines.join("|") === `${ac[i].label} ${ac[i].alt ?? ""}`.trim()); }"""
    )


@pytest.mark.parametrize("fields, lines", [
    (FIELDS, ["DAL1388 A321 2251", "5900 310KT 030° 14.3NM"]),
    (["CALLSIGN", "ALT", "GS"], ["DAL1388", "5900 310KT"]),
    (["CALLSIGN", "TYPE", "SQWK"], ["DAL1388 A321 2251"]),
    (["ALT", "GS", "TRK", "DIST"], ["5900 310KT 030° 14.3NM"]),
    (["TYPE", "GS"], ["A321 310KT"]),
    (["SQWK", "CALLSIGN"], ["DAL1388 2251"]),
    (["TRK"], ["030°"]),
])
def test_a_tag_is_the_chosen_fields_identity_over_numbers_once_there_are_more_than_two(page, fields, lines):
    wait_for_traffic(page)
    set_prefs(page, tag_fields=[f for f in FIELDS if f in fields])
    assert hold_traffic(page, plane("a1", -10, 5, **EVERY_FIELD))["a1"]["lines"] == lines


def test_a_tag_leaves_out_what_the_aircraft_does_not_report(page):
    wait_for_traffic(page)
    set_prefs(page, tag_fields=FIELDS)
    bare = {"type": None, "sq": None, "alt": None, "gs": None, "trk": None, "dist": 22}
    drawn = hold_traffic(
        page, plane("a1", -10, 5, label="N1", **bare), plane("a2", 10, 5, label="N2", **{**bare, "alt": "GND", "sq": ""}),
        plane("a3", 0, -10, label="N3", **{**bare, "trk": 0, "gs": 0}),
    )
    assert drawn["a1"]["lines"] == ["N1", "22.0NM"]
    assert drawn["a2"]["lines"] == ["N2", "GND 22.0NM"]
    assert drawn["a3"]["lines"] == ["N3", "0KT 000° 22.0NM"]
    set_prefs(page, tag_fields=["TYPE", "SQWK", "ALT"])
    frames(page)
    assert tags(page) == {"a1": None, "a2": {**tags(page)["a2"], "lines": ["GND"]}, "a3": None}


def test_with_no_fields_there_is_no_tag_and_the_chevron_still_focuses(page):
    wait_for_traffic(page)
    tag = hold_traffic(page, plane("a1", -10, 5), plane("a2", 10, -5))["a1"]
    where = on_screen(page, tag["x"] + tag["w"] - 3, tag["y"] + 3)
    set_prefs(page, tag_fields=[])
    frames(page)
    assert tags(page) == {"a1": None, "a2": None}
    page.mouse.click(*where)  # where its tag was
    frames(page)
    assert page.locator("#tracks-body tr.focused").count() == 0
    hit = radar_debug(page)["hits"][0]
    page.mouse.click(*on_screen(page, hit["x"], hit["y"]))
    page.wait_for_selector('#tracks-body tr.focused[data-hex="a1"]')


def test_a_click_on_either_line_of_a_tag_focuses_its_aircraft(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    one = hold_traffic(page, plane("a1", -10, 5, **{**EVERY_FIELD, "gs": 0}), plane("a2", 10, -5))["a1"]
    set_prefs(page, tag_fields=FIELDS)
    frames(page)
    two = tags(page)["a1"]
    assert len(two["lines"]) == 2
    # The second line is where the one line was; the first stands 18 px above it.
    assert two["h"] == pytest.approx(one["h"] + 18 * ratio)
    assert two["y"] == pytest.approx(one["y"] - 18 * ratio)
    assert (two["x"], two["y"] + two["h"]) == pytest.approx((one["x"], one["y"] + one["h"]))
    assert two["w"] > one["w"]
    # Focusing follows the aircraft, which moves the view (Task 12): the
    # tag is read again where each click finds it.
    set_prefs(page, view_ease="OFF")
    for top in (True, False):  # far right, well clear of the chevron
        for focused in ("tr.focused[data-hex=\"a1\"]", None):
            frames(page)
            two = tags(page)["a1"]
            y = two["y"] + 3 if top else two["y"] + two["h"] - 3
            page.mouse.click(*on_screen(page, two["x"] + two["w"] - 3, y))
            if focused:
                page.wait_for_selector(f"#tracks-body {focused}")
            else:
                page.wait_for_function("document.querySelectorAll('#tracks-body tr.focused').length === 0")


@pytest.mark.parametrize(
    "box", [{"box_items": []}, {"box_items": ["AIRCRAFT"], "box_fill": 0}], ids=["unboxed", "unfilled"]
)
def test_a_chevron_under_another_aircrafts_tag_is_the_one_a_click_on_it_focuses(page, box):
    """An unboxed tag, or a box with no fill, lets the chevron under it win.
    (A filled box covers it: test_page_map.py's
    test_a_filled_box_on_the_tags_layer_covers_the_chevron_under_it.)"""
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    ring = draw(page, box_pad=12, **box)["rings"][0]
    per_nm = ring["r"] / ring["nm"]
    tag = hold_traffic(page, plane("a1", -10, 5))["a1"]
    first = radar_debug(page)["hits"][0]
    # A second aircraft in the top right corner of the first one's tag.
    x, y = tag["x"] + tag["w"] - 6 * ratio, tag["y"] + 6 * ratio
    east, north = -10 + (x - first["x"]) / per_nm, 5 - (y - first["y"]) / per_nm
    hold_traffic(page, plane("a1", -10, 5), plane("a2", east, north))
    first, second = radar_debug(page)["hits"]
    assert (first["hex"], second["hex"]) == ("a1", "a2")
    assert nearest(first["tag"], second["x"], second["y"]) == 0, "the test wants a chevron under the other's tag"
    assert nearest({"x": first["x"], "y": first["y"], "w": 0, "h": 0}, second["x"], second["y"]) > 30 * ratio
    set_prefs(page, view_ease="OFF")
    page.mouse.click(*on_screen(page, second["x"], second["y"]))
    page.wait_for_selector('#tracks-body tr.focused[data-hex="a2"]')
    # The rest of the tag is still its own aircraft's, where following a2
    # (Task 12) has moved it.
    frames(page)
    first = radar_debug(page)["hits"][0]
    page.mouse.click(*on_screen(page, first["tag"]["x"] + first["tag"]["w"] / 2, first["tag"]["y"] + first["tag"]["h"] / 2))
    page.wait_for_selector('#tracks-body tr.focused[data-hex="a1"]')


def test_a_tags_box_blacks_out_the_map_under_it_and_is_edged_in_the_tags_colour(page):
    wait_for_traffic(page)
    debug = draw(page, **glow(0), display="OFF", box_items=["AIRCRAFT"], box_fill=0, box_border=0, box_pad=12)
    ring = next(r for r in debug["rings"] if r["nm"] == 20)
    home = debug["home"]
    # West of the airport and outside the 20 nm ring by 60 px, so that the
    # ring runs up through the tag, which begins 14 px right of the aircraft.
    tag = hold_traffic(page, plane("a1", east=-(20 + 60 * 20 / ring["r"])))["a1"]
    box = tag["box"]
    assert tag["boxed"] and holds(tag, box)
    assert all(float(n).is_integer() for n in box.values()), "a box is drawn on whole pixels"
    # Where the ring crosses the padding above the text: lit while the box is clear.
    y = box["y"] + 6
    x = round(home["x"] - (ring["r"] ** 2 - (y - home["y"]) ** 2) ** 0.5)
    assert box["x"] + 14 < x < box["x"] + box["w"] - 2
    under = [(x - 1, y), (x, y), (x + 1, y)]
    assert any(p[3] > 0 and max(p[:3]) > 100 for p in canvas_pixels(page, *under))
    draw(page, box_fill=100)
    assert canvas_pixels(page, *under) == [BLACK] * 3
    # The corners away from the chevron, and the edges away from it.
    top_right, bottom_right = inside_corners(box)[1], inside_corners(box)[3]
    top, _, _, right = edge_middles(box)
    assert canvas_pixels(page, top_right, bottom_right, top, right) == [BLACK] * 4
    draw(page, box_border=100)
    cyan = (*css_colour(page, "--cyan"), 255)
    assert canvas_pixels(page, top_right, bottom_right, top, right) == [BLACK, BLACK, cyan, cyan]
    # Just outside it nothing is painted.
    assert canvas_pixels(page, (box["x"] + box["w"] // 2, box["y"] - 2)) == [(0, 0, 0, 0)]


def test_a_tags_box_is_the_padding_and_the_border_about_the_text(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    plain = hold_traffic(page, plane("a1", -10, 5))["a1"]
    sizes = {}
    for pad, width in [(0, 1), (4, 1), (12, 1), (12, 5)]:
        draw(page, box_items=["AIRCRAFT"], box_pad=pad, box_width=width)
        tag = tags(page)["a1"]
        sizes[pad, width] = tag["box"]
        assert tag["lines"] == plain["lines"] and tag["boxed"] and holds(tag, tag["box"]) and holds(tag, plain)
    for (pad, width), box in sizes.items():
        grown = 2 * (pad + width - 1) * ratio
        assert box["w"] == pytest.approx(sizes[0, 1]["w"] + grown, abs=1)
        assert box["h"] == pytest.approx(sizes[0, 1]["h"] + grown, abs=1)
    # Tight about the capitals: 0.7 of the 16 px text high, and no wider than the text.
    assert sizes[0, 1]["h"] == pytest.approx(0.7 * 16 * ratio + 2, abs=1)
    assert sizes[0, 1]["w"] <= plain["w"] + 2


def test_a_tags_box_dims_with_its_aircraft_and_a_click_on_it_focuses(page):
    wait_for_traffic(page)
    set_prefs(page, **glow(0), display="OFF", box_items=["AIRCRAFT"], box_fill=100, box_border=100, box_pad=12)
    # Focusing follows the aircraft (Task 12): wide enough to keep both on
    # the screen, and at once.
    set_prefs(page, follow_nm=50, view_ease="OFF")
    drawn = hold_traffic(page, plane("a1", -12, 12), plane("a2", 12, -12))
    edges = {hex_: edge_middles(tag["box"]) for hex_, tag in drawn.items()}
    cyan = (*css_colour(page, "--cyan"), 255)
    assert canvas_pixels(page, edges["a1"][0], edges["a2"][0]) == [cyan, cyan]
    # In the padding, top right: no text there, and nowhere near the chevron.
    page.mouse.click(*on_screen(page, *inside_corners(drawn["a1"]["box"])[1]))
    page.wait_for_selector('#tracks-body tr.focused[data-hex="a1"]')
    frames(page)
    edges = {hex_: edge_middles(tag["box"]) for hex_, tag in tags(page).items()}
    pink = (*css_colour(page, "--pink"), 255)
    focused, dimmed = canvas_pixels(page, edges["a1"][0], edges["a2"][0])
    assert focused == pink
    assert 0 < dimmed[3] < 110, "the other aircraft's box is as dim as the aircraft"


# Every draw the radar makes with a shadow on, by its name, in one frame of
# its own. The radar's layers are canvases that are not in the page; the
# waveforms' are. A frame of the radar's (RADAR_FRAME, above).
SHADOWED = """async () => {
    const proto = CanvasRenderingContext2D.prototype;
    const draws = ["stroke", "fill", "fillRect", "strokeRect", "fillText", "strokeText", "drawImage"];
    const kept = Object.fromEntries(draws.map(name => [name, proto[name]]));
    const seen = {};
    for (const name of draws) proto[name] = function (...args) {
        const radars = this.canvas.id === "radar" || !this.canvas.isConnected;
        if (radars && this.shadowBlur > 0) seen[name] = (seen[name] || 0) + 1;
        return kept[name].apply(this, args);
    };
    const frame = """ + RADAR_FRAME + """;
    await frame();
    for (const name of Object.keys(seen)) delete seen[name];
    await frame();
    Object.assign(proto, kept);
    return seen;
}"""


def fleet(count, step=0.0, **over):
    """`count` aircraft in a slanting row across the radar, `step` nm on."""
    return [
        plane(f"a{i}", east=-30 + 60 * i / count + step, north=-14 + 28 * i / count, trk=90, **over.get(f"a{i}", {}))
        for i in range(count)
    ]


@pytest.mark.parametrize("count", [4, 24])
def test_the_traffics_glow_is_a_shadow_for_each_colour_not_one_for_each_stroke(page, count):
    """A canvas shadow costs by the draw: with every trail segment and
    chevron glowing on its own, thirty aircraft took over 60 ms a frame in
    WebKit, and in Chromium drawing on a GPU. So the lines of one colour
    share a shadow, however many aircraft there are."""
    wait_for_traffic(page)
    set_prefs(page, **glow(33), display="OFF")
    for step in (0, 1, 2, 3):  # four polls: a trail of three segments behind each
        hold_traffic(page, *fleet(count, step, a1={"sq": "7700"}))
    picture(page)  # the map has drawn itself on; from here only the traffic is drawn each frame
    shadowed = page.evaluate(SHADOWED)
    assert shadowed == {"drawImage": 2}, f"cyan and the alarm colour, a shadow each: {shadowed}"
    hit = radar_debug(page)["hits"][2]
    page.mouse.click(*on_screen(page, hit["x"], hit["y"]))
    page.wait_for_selector('#tracks-body tr.focused[data-hex="a2"]')
    page.mouse.move(2, 2)  # off the radar: a label brightening under the pointer redraws the map
    picture(page)
    shadowed = page.evaluate(SHADOWED)
    assert shadowed == {"drawImage": 3}, f"cyan, the alarm colour and pink, a shadow each: {shadowed}"
    set_prefs(page, **glow(0))
    picture(page)
    assert page.evaluate(SHADOWED) == {}


def light(pixel):
    """A canvas pixel as the light it puts on the screen: its red, green and
    blue, each as strong as the pixel is opaque."""
    r, g, b, a = pixel
    return [channel * a / 255 for channel in (r, g, b)]


def beside_the_tail(page, hex_, reach):
    """Two canvas pixels level with the tail of this aircraft's chevron, which
    points north: 3 px off its stem, and as far again as the glow reaches."""
    ratio = page.evaluate("devicePixelRatio")
    hit = next(h for h in radar_debug(page)["hits"] if h["hex"] == hex_)
    return [(hit["x"] + 3 * ratio, hit["y"] + 7 * ratio), (hit["x"] + (3 + reach) * ratio, hit["y"] + 7 * ratio)]


@pytest.mark.parametrize("level, reach", [(33, 4), (75, 9)])
def test_an_aircraft_glows_in_its_own_colour_and_not_at_all_with_the_glow_off(page, level, reach):
    """What an aircraft adds to the picture beside its lines: the map's own
    light there is read first, with the aircraft away."""
    wait_for_traffic(page)
    draw(page, **glow(level), display="OFF", tag_fields=[])
    planes = [plane("a1", -25, 14, trk=0), plane("a2", 25, 14, trk=0, sq="7700")]
    hold_traffic(page, *planes)
    spots = beside_the_tail(page, "a1", reach) + beside_the_tail(page, "a2", reach)

    def added():
        hold_traffic(page)
        picture(page)
        without = [light(p) for p in canvas_pixels(page, *spots)]
        hold_traffic(page, *planes)
        picture(page)
        with_them = [light(p) for p in canvas_pixels(page, *spots)]
        return [[now - before for now, before in zip(*pair)] for pair in zip(with_them, without)]

    near, far, alarm_near, alarm_far = added()
    assert near[2] > 12 and near[2] > near[0] + 8, f"no cyan glow beside the cyan aircraft: {near}"
    assert alarm_near[0] > 12 and alarm_near[0] > alarm_near[2] + 8, f"no alarm glow beside the emergency: {alarm_near}"
    # A glow and not a wider line: it falls away.
    assert 0 <= sum(far) < sum(near) / 2 and sum(near) < 300, (near, far)
    assert 0 <= sum(alarm_far) < sum(alarm_near) / 2, (alarm_near, alarm_far)
    draw(page, **glow(0))
    assert added() == [[0, 0, 0]] * 4, "an aircraft lights what is beside it with the glow off"


STILL = [
    ("HOME", "home", "--pink"), ("AIRPORTS", "airport:", "--cyan"), ("NAVAIDS", "navaid:", "--cyan"),
    ("CITIES", "city:", "--amber"), ("PEAKS", "peak:", "--amber"), ("STATES", "state:", "--dim"),
    ("RINGS", "ring:", "--dim"),
]


def name_a_state(page):
    """The map that ships names no states, though the radar draws them where
    a map does. Give this page's map one, south west of the airport."""
    def named(route):
        response = route.fetch()
        geo = response.json()
        geo["labels"]["state"] = [[round(-123.4 * geo["q"]), round(45.2 * geo["q"]), "OREGON"]]
        route.fulfill(response=response, json=geo)

    page.route("**/api/geo*", named)
    page.reload()
    page.wait_for_selector(".feed.expanded")


def still_labels(debug):
    """Every label on the still layer, as {key: rectangle}: the placed ones and the ring numbers."""
    found = {p["key"]: p for p in debug["placed"]}
    found.update({f"ring:{r['text']}": r["label"] for r in debug["rings"] if r["label"]})
    return found


@pytest.mark.parametrize("item, prefix, colour", STILL)
def test_a_boxed_kind_of_label_is_filled_black_and_edged_in_its_own_colour(page, item, prefix, colour):
    if item == "STATES":
        name_a_state(page)
    wait_for_traffic(page)
    hold_traffic(page)  # nothing flying over the labels
    plain = still_labels(draw(page, **glow(0), display="OFF"))
    assert not any(label["boxed"] or label["box"] for label in plain.values())
    debug = draw(page, box_items=[item], box_fill=100, box_border=100)
    width, height = canvas_size(page)
    labels = still_labels(debug)
    mine = {key: label for key, label in labels.items() if key.startswith(prefix)}
    assert mine and all(label["boxed"] and holds(label, label["box"]) for label in mine.values())
    assert not any(label["boxed"] or label["box"] for key, label in labels.items() if key not in mine)
    # The text is where it was: a box is put behind a label, it does not move it.
    assert all(holds(label, plain[key]) for key, label in mine.items() if key in plain)
    whole = [
        label["box"] for label in mine.values()
        if label["box"]["x"] >= 0 and label["box"]["y"] >= 0
        and label["box"]["x"] + label["box"]["w"] <= width and label["box"]["y"] + label["box"]["h"] <= height
    ]
    assert whole
    # A box lies across no other label, boxed or bare: it would hide it.
    assert not [(key, other) for key in mine for other in labels if other != key and overlap(mine[key], labels[other])]
    edge = (*css_colour(page, colour), 255)
    for box in whole:
        # A symbol or a runway may be drawn over one corner or one edge of a
        # box (they go on top, so a box hides none of them), never over most.
        assert canvas_pixels(page, *inside_corners(box)).count(BLACK) >= 3, box
        assert canvas_pixels(page, *edge_middles(box)).count(edge) >= 3, box


def test_a_box_on_the_still_layer_blacks_out_the_ring_it_lies_across(page):
    wait_for_traffic(page)
    hold_traffic(page)
    # At the widest padding a ring number's box reaches back over its own ring.
    debug = draw(page, **glow(0), display="OFF", box_items=["RINGS"], box_fill=0, box_border=0, box_pad=12)
    ring, home = debug["rings"][-1], debug["home"]
    assert ring["bright"] and ring["label"]["boxed"]
    d = ring["r"] * 0.5**0.5
    x, y = round(home["x"] + d), round(home["y"] - d)  # the ring, where its number stands off it
    assert nearest(ring["label"]["box"], x, y) == 0
    on_the_ring = [(x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
    assert any(p[3] > 0 and max(p[:3]) > 100 for p in canvas_pixels(page, *on_the_ring))
    draw(page, box_fill=100)
    assert canvas_pixels(page, *on_the_ring) == [BLACK] * 9


@pytest.mark.parametrize("items", [["HOME"], ["RINGS"], ["HOME", "RINGS"]])
def test_a_ring_number_on_the_airports_name_is_left_off_bare_or_boxed(page, items):
    """The number, placed after the name, is the one to give way: boxed, as
    a box under either would hide the other, and bare too (phase F let the
    two cross; the owner's decision in phase G's Task 10 review)."""
    wait_for_traffic(page)
    hold_traffic(page)
    plain = draw(page, **glow(0), display="OFF")
    assert plain["placed"][0]["key"] == "home"
    bare = {ring["text"]: ring["label"] for ring in plain["rings"]}
    assert [text for text, label in bare.items() if not label] == ["10"]
    assert not [text for text, label in bare.items() if label and overlap(label, plain["placed"][0])]
    picture(page)
    lit = {text: canvas_block(page, label) for text, label in bare.items() if label}
    assert all(ink(block) > 10 for block in lit.values())

    debug = draw(page, box_items=items, box_fill=100, box_border=100)
    name = debug["placed"][0]
    assert name["key"] == "home" and name["boxed"] == ("HOME" in items)
    numbers = {ring["text"]: ring["label"] for ring in debug["rings"]}
    assert list(numbers) == list(bare), "every ring is still drawn"
    assert [text for text, label in numbers.items() if not label] == ["10"]
    kept = {text: label for text, label in numbers.items() if label}
    assert not [text for text, label in kept.items() if overlap(label, name)]
    # The others have not moved, and each still reads.
    assert all(holds(label, bare[text]) for text, label in kept.items())
    picture(page)
    now = {text: canvas_block(page, bare[text]) for text in kept}
    assert all(ink(block) > 10 for block in now.values())
    if "RINGS" not in items:  # with no box of their own, they are just as they were
        assert now == {text: lit[text] for text in kept}


def test_a_ring_number_takes_its_other_place_when_a_boxed_name_has_its_first(page):
    """With the airport dragged off the middle of the screen a ring's number
    has two places to go: the north east diagonal, and where the ring passes
    nearest the middle."""
    wait_for_traffic(page)
    hold_traffic(page)
    draw(page, **glow(0), display="OFF")
    x, y = centre_of_the_radar(page)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 150, y - 100, steps=6)  # the airport goes up and to the left
    page.mouse.up()
    page.mouse.move(5, 5)
    page.wait_for_function("window.kcgx.radar.debug().hovered === null")
    plain = radar_drawn(page)
    home = plain["home"]
    ratio = page.evaluate("devicePixelRatio")
    # Its first place, on the north east diagonal, is on the airport's name:
    # bare too, the number takes its other (the owner's decision in phase
    # G's Task 10 review; phase F let the two cross).
    ring = next(ring for ring in plain["rings"] if ring["text"] == "10")
    d = ring["r"] * 0.5**0.5
    bare = {ring["text"]: ring["label"] for ring in plain["rings"]}
    w, h = bare["10"]["w"], bare["10"]["h"]
    first = {"x": home["x"] + d + 4 * ratio, "y": home["y"] - d - 4 * ratio - h, "w": w, "h": h}
    assert overlap(first, plain["placed"][0]), "the test wants the first place on the name"

    for debug in (plain, draw(page, box_items=["HOME"], box_fill=100, box_border=100)):
        name = debug["placed"][0]
        numbers = {ring["text"]: ring["label"] for ring in debug["rings"]}
        assert all(numbers.values()), numbers
        assert not [text for text, label in numbers.items() if overlap(label, name)]
        # South east of the airport, towards the middle, and still beside its ring.
        ten = numbers["10"]
        assert ten["x"] > home["x"] and ten["y"] > home["y"]
        assert ring["r"] <= nearest(ten, home["x"], home["y"]) <= ring["r"] + 8 * ratio
        picture(page)
        assert ink(canvas_block(page, ten)) > 10
        assert numbers == bare


@pytest.mark.parametrize("range_nm", [120, 250])
def test_a_boxed_place_keeps_off_a_bare_ring_number(page, range_nm):
    """At these ranges a place's name is written across a ring number while
    both are bare. Boxed, the place is the one left off: the numbers were
    there first."""
    wait_for_traffic(page)
    hold_traffic(page)
    places = ["AIRPORTS", "NAVAIDS", "CITIES", "PEAKS"]
    plain = draw(page, **glow(0), display="OFF", range_nm=range_nm)
    # (one, the 50's, is left off for the airport's name)
    numbers = [ring["label"] for ring in plain["rings"] if ring["label"]]
    assert len(numbers) >= 2
    across = {p["key"] for p in plain["placed"][1:] for n in numbers if overlap(p, n)}
    assert across, "the test wants a place's name on a ring number"
    # First with boxes that cannot be seen: the places as they will be, the
    # numbers as nothing but themselves and the map.
    unseen = draw(page, box_items=places, box_fill=0, box_border=0)
    assert [ring["label"] for ring in unseen["rings"] if ring["label"]] == numbers
    placed = unseen["placed"][1:]
    assert len(placed) >= 10 and all(p["boxed"] for p in placed)
    assert not [(p["key"], n) for p in placed for n in numbers if overlap(p, n)]
    assert across.isdisjoint(p["key"] for p in placed)
    picture(page)
    before = [canvas_block(page, n) for n in numbers]
    assert all(ink(block) > 10 for block in before)
    seen = draw(page, box_fill=100, box_border=100)
    assert seen["placed"] == unseen["placed"]
    picture(page)
    assert [canvas_block(page, n) for n in numbers] == before, "no box is painted on a ring number"


def test_a_box_does_not_brighten_with_its_label_under_the_pointer(page):
    wait_for_traffic(page)
    hold_traffic(page)
    debug = draw(page, **glow(0), display="OFF", box_items=["CITIES"], box_fill=100, box_border=50)
    width, height = canvas_size(page)
    label = next(
        p for p in debug["placed"]
        if p["key"].startswith("city:") and p["box"]["x"] > 0 and p["box"]["y"] > 0
        and p["box"]["x"] + p["box"]["w"] < width and p["box"]["y"] + p["box"]["h"] < height
    )
    top, bottom, _, right = edge_middles(label["box"])
    before = canvas_pixels(page, top, bottom, right)
    assert sum(max(p[:3]) > 60 for p in before) >= 2, "the border is drawn"
    # Over the box's padding, not the text: the pointer on a box is on its label.
    page.mouse.move(*on_screen(page, label["box"]["x"] + label["box"]["w"] - 2, label["box"]["y"] + 2))
    page.wait_for_function(f"window.kcgx.radar.debug().hovered === {label['key']!r}")
    frames(page)
    assert canvas_pixels(page, top, bottom, right) == before


def test_boxes_with_no_fill_and_no_border_leave_the_picture_as_it_was(page):
    wait_for_traffic(page)
    hold_traffic(
        page, plane("a1", -12, 5, **{**EVERY_FIELD, "gs": 0}), plane("a2", 9, -7, sq="7700"), plane("a3", 3, 14),
    )
    set_prefs(page, display="OFF", tag_fields=FIELDS)
    before = picture(page)
    kept = [p["key"] for p in radar_debug(page)["placed"]]
    # Tags are not placed around one another, so a box reserves nothing for them.
    set_prefs(page, box_items=["AIRCRAFT", "HUD"], box_fill=0, box_border=0, box_pad=12, box_width=5)
    assert picture(page) == before
    assert all(tag["boxed"] for tag in tags(page).values())
    # Every kind of place, with no padding. A box still reserves a little
    # more than its text did (its border, and a place's symbol), but here no
    # label loses its place for that: the same labels, so the same picture.
    debug = draw(page, box_items=[i for i in ITEMS if i not in ("HOME", "RINGS")], box_pad=0, box_width=1)
    assert [p["key"] for p in debug["placed"]] == kept
    assert all(p["boxed"] for p in debug["placed"][1:]) and all(r["label"] for r in debug["rings"])
    assert picture(page) == before
    # The airport's name and the ring numbers too: the number that the name
    # is written across is left off, and nothing else changes place.
    debug = draw(page, box_items=ITEMS)
    assert [p["key"] for p in debug["placed"]] == kept and all(p["boxed"] for p in debug["placed"])
    assert [r["text"] for r in debug["rings"] if not r["label"]] == ["10"]
    assert all(r["label"]["boxed"] for r in debug["rings"] if r["label"])
    assert picture(page) != before
    set_prefs(page, box_items=[i for i in ITEMS if i not in ("HOME", "RINGS")], box_fill=100)
    assert picture(page) != before


@pytest.mark.parametrize("view", ["whole", "close"])
def test_no_two_boxes_overlap_even_at_the_widest_padding(page, view):
    wait_for_traffic(page)
    hold_traffic(page)
    if view == "close":
        page.mouse.move(*centre_of_the_radar(page))
        turn_wheel(page, -900)  # small airports too
    plain = draw(page, box_items=[])["placed"]
    debug = draw(page, box_items=ITEMS, box_pad=12, box_width=5)
    placed = debug["placed"]
    assert len(placed) >= 4 and placed[0]["key"] == "home"
    assert all(p["boxed"] and holds(p, p["box"]) for p in placed)
    assert not [(a["key"], b["key"]) for i, a in enumerate(placed) for b in placed[i + 1:] if overlap(a, b)]
    # A box takes more room than its text, so fewer labels fit; none is new.
    assert len(placed) <= len(plain) and {p["key"] for p in placed} <= {p["key"] for p in plain}
    # A boxed ring number is room taken too, and takes none of the airport's name.
    numbers = [r["label"] for r in debug["rings"] if r["label"]]
    assert numbers and all(n["boxed"] for n in numbers)
    assert not [(p["key"], n) for p in placed for n in numbers if overlap(p, n)]
    assert not [(a, b) for i, a in enumerate(numbers) for b in numbers[i + 1:] if overlap(a, b)]


def hud_style(page, selector, name):
    return page.eval_on_selector(selector, "(e, name) => getComputedStyle(e)[name]", name)


def bounds(page, selector):
    """An element's box on the page: (left, top, right, bottom)."""
    return tuple(page.eval_on_selector(
        selector, "e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }"
    ))


def test_hud_among_the_boxes_puts_the_radars_readouts_in_boxes(page):
    spans = ["#radar-range", "#radar-poll", "#radar-tracks"]
    assert page.eval_on_selector_all(".hud span", "els => els.map(e => '#' + e.id)") == spans
    set_prefs(page, **glow(0), display="OFF")  # nothing over the readouts but themselves
    for span in spans:
        assert hud_style(page, span, "backgroundColor") == "rgba(0, 0, 0, 0)"
        assert hud_style(page, span, "borderLeftWidth") == "0px" and hud_style(page, span, "paddingLeft") == "0px"
    set_prefs(page, box_items=["HUD"])
    page.wait_for_function("document.documentElement.dataset.boxHud === 'ON'")
    for span in spans:
        assert hud_style(page, span, "backgroundColor") == "rgba(0, 0, 0, 0.7)"
        assert hud_style(page, span, "borderLeftWidth") == "1px" and hud_style(page, span, "borderLeftStyle") == "solid"
        assert hud_style(page, span, "paddingLeft") == "4px" and hud_style(page, span, "paddingTop") == "4px"
    set_prefs(page, box_fill=100, box_pad=12, box_border=100, box_width=3)
    page.wait_for_function("getComputedStyle(document.getElementById('radar-range')).paddingLeft === '12px'")
    muted = css_colour(page, "--muted")
    # The radar writes its readouts 500 ms after the page loads and every
    # 500 ms from then on, and a box is as wide as its words. So: not before
    # the first writing, each box measured as its own two pixels are read,
    # and those read at the edge the box is held by, which stays where it is
    # when the words change (the track count is held by its right).
    page.wait_for_function(
        """() => document.getElementById("radar-poll").textContent.startsWith("POLLED")
                 && document.getElementById("radar-tracks").textContent !== "0 TRACKS" """
    )
    boxes = []
    for span in spans:
        assert hud_style(page, span, "backgroundColor") == "rgb(0, 0, 0)"
        assert hud_style(page, span, "borderLeftWidth") == "3px" and hud_style(page, span, "borderRightWidth") == "3px"
        left, top, right, bottom = bounds(page, span)
        edge, inside = (right - 2, right - 7) if span == "#radar-tracks" else (left + 1, left + 6)
        # As painted: the border in the text's colour, black inside it.
        assert pixel(page, edge, (top + bottom) // 2) == muted
        assert pixel(page, inside, top + 6) == (0, 0, 0)
        boxes.append((left, top, right, bottom))
    # Each box is about its own text, the two on the left one under the
    # other, and all three inside the radar.
    assert boxes[0][3] <= boxes[1][1] and boxes[0][2] != boxes[1][2]
    wrap = bounds(page, ".radar-wrap")
    assert all(wrap[0] <= b[0] and wrap[1] <= b[1] and b[2] <= wrap[2] and b[3] <= wrap[3] for b in boxes)
    set_prefs(page, box_border=0)
    page.wait_for_function("getComputedStyle(document.documentElement).getPropertyValue('--box-border') === '0%'")
    assert pixel(page, boxes[0][0] + 1, (boxes[0][1] + boxes[0][3]) // 2) == (0, 0, 0)
    set_prefs(page, box_items=["AIRCRAFT"])
    page.wait_for_function("document.documentElement.dataset.boxHud === 'OFF'")
    assert hud_style(page, "#radar-range", "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert hud_style(page, "#radar-range", "paddingLeft") == "0px"


# -- opened from kcgx go -------------------------------------------------------------


def test_a_link_to_airport_opens_the_search(browser, server):
    page = browser.new_page()
    page.goto(server + "/#airport")
    page.wait_for_selector("#airport-sheet[open]")
    assert page.input_value("#airport-query") == ""
    assert page.evaluate("location.hash") == ""
    page.close()


def test_a_link_with_a_query_opens_the_search_with_it_typed(browser, server):
    page = browser.new_page()
    page.goto(server + "/#airport=san%20francisco")
    page.wait_for_selector("#airport-sheet[open]")
    assert page.input_value("#airport-query") == "san francisco"
    page.wait_for_selector("#airport-results .choice:has-text('KSFO')")
    page.close()


def test_a_link_with_a_query_that_cannot_be_decoded_still_opens_the_search(browser, server):
    # %E9 alone is no character, and KCGX.app hands a link's escapes on as
    # they came (Target.legal in macos/KCGXWindow.swift). The page takes the
    # text as written, and the rest of it runs.
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server + "/#airport=%E9")
    page.wait_for_selector("#airport-sheet[open]")
    assert page.input_value("#airport-query") == "%E9"
    assert page.evaluate("location.hash") == ""
    page.wait_for_selector(".feed.expanded")  # the page went on to connect and draw
    assert page.evaluate("typeof window.kcgx") == "object"
    # The same link, to a page that is already open (the window sets the fragment).
    page.keyboard.press("Escape")
    page.wait_for_selector("#airport-sheet", state="hidden")
    page.evaluate("location.hash = 'airport=100%'")
    page.wait_for_selector("#airport-sheet[open]")
    assert page.input_value("#airport-query") == "100%"
    assert errors == [], errors
    page.close()


def test_the_volume_slider_takes_the_header_but_the_mute_and_readout(page):
    """The frequencies pane's header is [mute] [volume] [NN%] (phase G Task
    6), with no label: the slider has the width the other two leave."""
    page.set_viewport_size({"width": 1440, "height": 900})
    head, mute, slider, value = (box_of(page, s) for s in ("#freq-head", "#master-mute", "#volume", "#volume-value"))
    assert mute["right"] <= slider["left"] and slider["right"] <= value["left"]
    pad = page.eval_on_selector("#freq-head", "e => parseFloat(getComputedStyle(e).paddingLeft) * 2")
    rest = head["width"] - pad - mute["width"] - value["width"]
    assert slider["width"] >= rest - 2 * 12, (head, mute, slider, value)
