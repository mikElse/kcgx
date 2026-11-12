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
import subprocess
import sys
import time
import urllib.request

import pytest

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
    # The server outlives each test, and so do its prefs: start from the default layout.
    set_prefs(page, lamps=False, teletype=False)
    yield page
    context.close()
    assert errors == [], errors


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


def test_the_feed_picker_adds_a_feed(page):
    page.click("#open-feeds")
    page.wait_for_selector("#feeds-results .choice")
    page.click("#feeds-results .choice:has-text('GUARD')")
    page.wait_for_selector(".feed:has-text('Emergency Guard')")
    page.click("#open-feeds")
    page.wait_for_selector("#feeds-results .choice:has-text('GUARD') .tag.on")


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


def test_prefs_apply_to_every_tab(page, browser, server):
    other = browser.new_page()
    other.goto(server + "/")
    other.wait_for_selector(".feed.expanded")
    page.click("#next-palette")
    other.wait_for_function("document.documentElement.dataset.palette === 'AMBER'")
    page.click("#open-config")
    page.click(".segments[data-pref=display] button:text-is('VECTOR')")
    other.wait_for_function("document.documentElement.dataset.display === 'VECTOR'")
    page.click(".segments[data-pref=display] button:text-is('CRT')")
    page.click(".segments[data-pref=palette] button:text-is('WOPR')")
    other.wait_for_function("document.documentElement.dataset.palette === 'WOPR'")
    assert other.get_attribute("html", "data-display") == "CRT"
    other.close()


def test_the_volume_slider_reaches_the_server(page):
    page.click("#open-config")
    page.fill("#volume", "40")
    page.dispatch_event("#volume", "input")
    page.wait_for_function("document.getElementById('freq-counts').textContent.includes('VOL 40%')")
    page.fill("#volume", "100")
    page.dispatch_event("#volume", "input")
    page.wait_for_function("document.getElementById('freq-counts').textContent.includes('VOL 100%')")


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


def test_the_wheel_zooms_dragging_pans_and_recentre_resets(page):
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
    page.click("#recentre")
    assert radar_debug(page)["view"] == {"zoom": 1, "panX": 0, "panY": 0}


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
