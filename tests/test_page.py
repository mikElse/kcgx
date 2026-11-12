"""The cockpit page in a real browser, against `kcgx-web --demo`.

These need Playwright and its Chromium (`uv sync --group browser`, then
`uv run playwright install chromium`); without them they skip. The server
runs as a subprocess with its state in a temporary folder, so nothing here
touches ~/.local/state/kcgx.
"""

from __future__ import annotations

import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import zlib

import pytest

from kcgx.prefs import DEFAULTS, SCHEMA, Choice, Flag, Number, Subset

playwright_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

SIZES = [(1440, 900), (1280, 720), (1100, 760), (820, 1000), (390, 844)]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    state = tmp_path_factory.mktemp("page-state")
    port = _free_port()
    env = {
        **os.environ,
        "KCGX_STATE_PATH": str(state / "airport"),
        "HOME": str(state / "home"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "kcgx.server", "--demo", "--icao", "KPDX", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=1) as response:
                if json.load(response)["ok"]:
                    break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.fail("kcgx-web --demo never answered: " + process.stdout.read().decode())
    yield base
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        try:
            launched = p.chromium.launch()
        except playwright_api.Error as error:  # no browser installed
            pytest.skip(f"no Chromium for Playwright: {error}")
        yield launched
        launched.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(server + "/")
    page.wait_for_selector(".feed.expanded")
    # The server outlives each test, and so do its prefs: start from the defaults.
    set_prefs(page, **DEFAULTS)
    yield page
    context.close()
    assert errors == [], errors


@pytest.fixture
def other(browser, server, page):
    """A second tab on the same cockpit. It asks for `page` so that it opens
    after the prefs are back at their defaults."""
    tab = browser.new_page()
    tab.goto(server + "/")
    tab.wait_for_selector(".feed.expanded")
    yield tab
    tab.close()


def feed_names(page, shape):
    return page.eval_on_selector_all(f".feed.{shape} .feed-name", "els => els.map(e => e.textContent)")


def set_prefs(page, **prefs):
    """Change settings as a control would, through the page's own socket;
    returns once the server's answer has been applied to the page."""
    page.evaluate("prefs => window.kcgx.send({t: 'prefs', ...prefs})", prefs)
    page.wait_for_function(
        """prefs => Object.entries(prefs).every(
            ([key, value]) => JSON.stringify(window.kcgx.store.state.prefs[key]) === JSON.stringify(value))""",
        arg=prefs,
    )


def parts(page):
    """The screens and the lamp bar that are displayed, by name:
    {name: (left, top, right, bottom)}."""
    found = page.eval_on_selector_all(
        ".screen, .lamps",
        """els => els.filter(e => e.getClientRects().length).map(e => {
            const r = e.getBoundingClientRect();
            const name = e.id || [...e.classList].find(c => c.startsWith("screen-")).slice(7);
            return [name, r.left, r.top, r.right, r.bottom]; })""",
    )
    return {name: tuple(box) for name, *box in found}


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


def test_clicking_a_compact_row_unmutes_it_and_m_mutes_it_again(page):
    assert "ATIS" not in feed_names(page, "expanded")
    page.click(".feed.compact:has-text('ATIS')")
    page.wait_for_selector(".feed.expanded:has-text('ATIS')")
    page.click(".feed.expanded:has-text('ATIS') button:text-is('M')")
    page.wait_for_selector(".feed.compact:has-text('ATIS')")
    assert "ATIS" not in feed_names(page, "expanded")


def test_s_solos_and_lights(page):
    solo = ".feed.expanded:has-text('Tower') button:text-is('S')"
    page.click(solo)
    page.wait_for_selector(f"{solo}[aria-pressed=true]")
    page.click(solo)
    page.wait_for_selector(f"{solo}[aria-pressed=false]")


def test_the_trace_draws(page):
    page.wait_for_timeout(1500)
    lit = page.eval_on_selector(
        ".feed.expanded .trace",
        "c => { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;"
        " let n = 0; for (let i = 3; i < d.length; i += 4) n += d[i] > 0; return n; }",
    )
    assert lit > 50


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


def test_the_volume_slider_reaches_the_server(page):
    page.click("#open-config")
    page.fill("#volume", "40")
    page.dispatch_event("#volume", "input")
    page.wait_for_function("document.getElementById('freq-counts').textContent.includes('VOL 40%')")
    page.fill("#volume", "100")
    page.dispatch_event("#volume", "input")
    page.wait_for_function("document.getElementById('freq-counts').textContent.includes('VOL 100%')")


# -- the config sheet ------------------------------------------------------------

NUMBERS = {key: spec for key, spec in SCHEMA.items() if isinstance(spec, Number)}
SUBSETS = {key: spec for key, spec in SCHEMA.items() if isinstance(spec, Subset)}
FLAGS = [key for key, spec in SCHEMA.items() if isinstance(spec, Flag)]
SEGMENTED = {key: spec for key, spec in SCHEMA.items() if isinstance(spec, Choice) and key != "palette"}
READOUTS = {
    "scan_opacity": "{}%", "scan_size": "{} PX", "range_nm": "{} NM",
    "box_fill": "{}%", "box_pad": "{} PX", "box_border": "{}%", "box_width": "{} PX",
}


def pref_is(tab, key, value):
    """Wait until `tab` has been told by the server that `key` is `value`."""
    tab.wait_for_function(
        "([key, value]) => JSON.stringify(window.kcgx.store.state.prefs[key]) === JSON.stringify(value)",
        arg=[key, value],
    )


def pressed(tab, key):
    """The lit buttons of a segment group, as the page has them."""
    return tab.eval_on_selector_all(
        f"#config-sheet [data-pref={key}] button[aria-pressed=true]", "bs => bs.map(b => b.textContent)"
    )


def readout(tab, key):
    return tab.text_content(f"#config-sheet .field-row:has([data-pref={key}]) [data-unit]")


def pixel(page, x, y):
    """One pixel of the page as it is painted: (r, g, b)."""
    png = page.screenshot(clip={"x": x, "y": y, "width": 1, "height": 1}, animations="disabled")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    at, packed, head = 8, b"", None
    while at < len(png):
        length, kind = struct.unpack(">I4s", png[at:at + 8])
        body = png[at + 8:at + 8 + length]
        if kind == b"IHDR":
            head = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            packed += body
        at += 12 + length
    width, height, depth, colour = head
    assert (width, height, depth) == (1, 1, 8) and colour in (2, 6), head
    # One row of one pixel: a filter byte (which has no neighbour to work
    # from, so every filter leaves the bytes as they are), then r, g, b.
    return tuple(zlib.decompress(packed)[1:4])


def css_colour(page, name):
    """A palette colour, as (r, g, b)."""
    text = page.evaluate(
        """name => { const probe = document.createElement("span");
                     probe.style.color = `var(${name})`; document.body.append(probe);
                     const colour = getComputedStyle(probe).color; probe.remove(); return colour; }""",
        name,
    )
    return tuple(int(n) for n in re.findall(r"\d+", text)[:3])


def spy_on_sends(page):
    """From here on, `window.sent` is every message the page sends the server."""
    page.evaluate(
        """() => { window.sent = []; const send = WebSocket.prototype.send;
                   WebSocket.prototype.send = function (data) { window.sent.push(JSON.parse(data)); send.call(this, data); }; }"""
    )


def test_limits_and_the_stream_count_are_gone(page):
    assert page.locator("#max-streams").count() == 0
    said = page.text_content("#config-sheet")
    assert "LIMITS" not in said and "STREAMS AT ONCE" not in said
    assert page.eval_on_selector_all("#config-sheet h3", "hs => hs.map(h => h.textContent)") == [
        "OUTPUT", "LOOK", "LAYOUT", "RADAR",
    ]


def test_the_sheet_opens_showing_the_defaults(page):
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    assert page.input_value("#config-sheet select[data-pref=palette]") == DEFAULTS["palette"]
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
    # every control is one a person can reach and work
    for key in SCHEMA:
        assert page.locator(f"#config-sheet [data-pref={key}]").is_visible(), key


def test_each_number_slider_reaches_a_second_tab(page, other):
    page.click("#open-config")
    for key, spec in NUMBERS.items():
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
    page.click("#open-config")
    page.fill("#config-sheet input[data-pref=range_nm]", "120")
    pref_is(page, "range_nm", 120)
    assert page.evaluate("window.sent") == [{"t": "prefs", "range_nm": 120}]


def test_dragging_a_slider_sends_where_it_stopped_not_every_step(page):
    """The range above all: a drag must not become a burst of messages. The
    steps are 20 ms apart, each inside the 80 ms the slider waits; a timer
    that is due sooner runs sooner, so a busy page cannot reorder them."""
    spy_on_sends(page)
    page.click("#open-config")
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
    page.click("#open-config")
    for key, spec in SUBSETS.items():
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
    for name in DEFAULTS["tag_fields"]:
        page.click(f"#config-sheet [data-pref=tag_fields] button:text-is('{name}')")
    pref_is(other, "tag_fields", [])
    assert pressed(other, "tag_fields") == []


@pytest.mark.parametrize("key", FLAGS)
def test_a_flag_is_off_or_on_and_reaches_a_second_tab(page, other, key):
    page.click("#open-config")
    for label, value in (("ON", True), ("OFF", False)):
        page.click(f"#config-sheet [data-pref={key}] button:text-is('{label}')")
        pref_is(other, key, value)
        pref_is(page, key, value)
        assert pressed(page, key) == [label] and pressed(other, key) == [label]
        assert other.get_attribute("html", f"data-{key}") == label
        assert page.get_attribute("html", f"data-{key}") == label


def test_a_choice_segment_group_has_one_pressed_button(page, other):
    page.click("#open-config")
    for key, spec in SEGMENTED.items():
        for name in spec.names:
            page.click(f"#config-sheet [data-pref={key}] button:text-is('{name}')")
            pref_is(other, key, name)
            pref_is(page, key, name)
            assert pressed(page, key) == [name] and pressed(other, key) == [name]
            assert other.get_attribute("html", f"data-{key}") == name


def test_a_slider_in_hand_is_not_moved_by_another_tab(page, other):
    """As the volume slider: a frame from the server must not pull a slider
    out from under the pointer. It catches up when it is let go."""
    page.click("#open-config")
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


def test_the_scanline_sliders_are_disabled_unless_the_display_is_crt(page):
    page.click("#open-config")
    scan = ["scan_opacity", "scan_size"]
    for display in ("CRT", "VECTOR", "OFF", "CRT"):
        page.click(f"#config-sheet [data-pref=display] button:text-is('{display}')")
        pref_is(page, "display", display)
        for key in NUMBERS:
            off = page.is_disabled(f"#config-sheet input[data-pref={key}]")
            assert off == (key in scan and display != "CRT"), f"{key} with display {display}"


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


@pytest.mark.parametrize("width, height", [(1440, 900), (1280, 640), (390, 844)])
def test_the_config_sheet_docks_to_the_right_edge_at_full_height(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    box = page.eval_on_selector("#config-sheet", "e => e.getBoundingClientRect().toJSON()")
    inner = page.evaluate("document.documentElement.clientWidth")
    assert abs(box["right"] - inner) <= 1, "the sheet is not against the right edge"
    assert abs(box["top"]) <= 1 and abs(box["bottom"] - height) <= 1, "the sheet is not the window's height"
    assert abs(box["width"] - min(420, inner)) <= 1
    # what does not fit scrolls inside the sheet, and the last control can be reached
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    last = page.locator("#config-sheet input[data-pref=box_width]")
    last.scroll_into_view_if_needed()
    at = last.evaluate("e => e.getBoundingClientRect().toJSON()")
    assert at["top"] >= 0 and at["bottom"] <= height and at["left"] >= box["left"] and at["right"] <= box["right"]


def test_the_config_sheet_does_not_darken_the_radar_and_the_airport_sheet_does(page):
    """Decision 10: scanlines, boxes and range are seen changing while they
    are set. The pixel is the radar screen's frame, halfway down its left
    edge: with no display effects it is exactly the frame colour."""
    set_prefs(page, display="OFF", glow="OFF")
    frame = css_colour(page, "--frame")
    x, y = page.eval_on_selector(
        ".screen-radar", "e => { const r = e.getBoundingClientRect(); return [r.left, Math.round(r.top + r.height / 2)]; }"
    )
    assert x == int(x) and pixel(page, x, y) == frame
    page.click("#open-config")
    page.wait_for_selector("#config-sheet[open]")
    sheet = page.eval_on_selector("#config-sheet", "e => e.getBoundingClientRect().left")
    assert x < sheet, "the sheet itself covers the pixel"
    assert pixel(page, x, y) == frame, "the radar is darkened behind the config sheet"
    # The same pixel does show a backdrop: the airport sheet still has one.
    page.click("#config-sheet button[value=close]")
    page.click("#open-airport")
    page.wait_for_selector("#airport-sheet[open]")
    dimmed = pixel(page, x, y)
    assert sum(dimmed) < sum(frame) / 2, f"the airport sheet's backdrop left {dimmed}"


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


def radar_debug(page):
    return page.evaluate("window.kcgx.radar.debug()")


def on_screen(page, x, y):
    """A canvas pixel position as a page position."""
    box = page.eval_on_selector("#radar", "e => { const r = e.getBoundingClientRect(); return [r.left, r.top]; }")
    ratio = page.evaluate("devicePixelRatio")
    return box[0] + x / ratio, box[1] + y / ratio


def wait_for_traffic(page):
    """Until a frame has been drawn with the map and the aircraft on it: the
    map arrives between two frames, and the labels are placed on the next."""
    page.wait_for_function(
        """() => { const d = window.kcgx.radar.debug();
                   return d.loaded && d.hits.length > 0 && d.placed.some(p => p.key.startsWith('navaid:')); }"""
    )


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


def test_the_wheel_zooms_dragging_pans_and_a_double_click_recentres(page):
    wait_for_traffic(page)
    x, y = on_screen(page, 300, 300)
    page.mouse.move(x, y)
    page.mouse.wheel(0, -500)
    page.wait_for_function("window.kcgx.radar.debug().view.zoom > 1.5")
    page.mouse.down()
    page.mouse.move(x + 120, y + 60, steps=6)
    page.mouse.up()
    view = radar_debug(page)["view"]
    assert view["panX"] != 0 and view["panY"] != 0
    page.mouse.dblclick(x, y)
    assert radar_debug(page)["view"] == {"zoom": 1, "panX": 0, "panY": 0}


def pan(page, x, y, **press):
    """Drag the radar from (x, y); `press` is how the browser counts the press."""
    page.mouse.move(x, y)
    page.mouse.down(**press)
    page.mouse.move(x + 120, y + 60, steps=6)
    page.mouse.up(**press)


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
    assert twice["zoom"] == 1
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
    assert radar_debug(page)["view"] == {"zoom": 1, "panX": 0, "panY": 0}


def test_the_readout_follows_a_double_click(page):
    """The bearing and distance under the pointer are for the view on screen,
    without waiting for the pointer to move."""
    wait_for_traffic(page)
    x, y = on_screen(page, 300, 300)
    page.mouse.move(x, y)
    centred = page.inner_text("#radar-position")
    assert re.fullmatch(r"\d{3}° \d+\.\d NM", centred)
    page.mouse.wheel(0, -500)
    page.wait_for_function("window.kcgx.radar.debug().view.zoom > 1.5")
    pan(page, x, y)
    page.mouse.move(x, y)
    assert page.inner_text("#radar-position") != centred
    page.mouse.dblclick(x, y)
    assert radar_debug(page)["view"] == {"zoom": 1, "panX": 0, "panY": 0}
    assert page.inner_text("#radar-position") == centred


def test_a_column_header_sorts_the_table(page):
    wait_for_traffic(page)
    page.wait_for_selector("#tracks-body tr")
    page.click("#tracks-head button:text-is('ALT FT')")
    alts = page.eval_on_selector_all(
        "#tracks-body tr td:nth-child(3)", "cells => cells.map(c => c.textContent === 'GND' ? 0 : Number(c.textContent))"
    )
    assert alts == sorted(alts)
    page.click("#tracks-head button:text-is('ALT FT')")
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
