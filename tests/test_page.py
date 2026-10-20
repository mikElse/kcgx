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
    yield page
    context.close()
    assert errors == [], errors


def feed_names(page, shape):
    return page.eval_on_selector_all(f".feed.{shape} .feed-name", "els => els.map(e => e.textContent)")


# -- layout --------------------------------------------------------------------


@pytest.mark.parametrize("width, height", SIZES)
def test_no_two_screens_overlap_and_none_spills_out(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(200)
    boxes = page.eval_on_selector_all(
        ".screen",
        "els => els.map(e => { const r = e.getBoundingClientRect();"
        " return [e.getAttribute('aria-label'), r.left, r.top, r.right, r.bottom]; })",
    )
    assert len(boxes) == 5
    for i, (name, left, top, right, bottom) in enumerate(boxes):
        assert right - left > 100 and bottom - top > 40, f"{name} collapsed at {width}x{height}"
        for other, l2, t2, r2, b2 in boxes[i + 1:]:
            apart = right <= l2 + 0.5 or r2 <= left + 0.5 or bottom <= t2 + 0.5 or b2 <= top + 0.5
            assert apart, f"{name} overlaps {other} at {width}x{height}"
    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    assert scroll_width <= width, f"the page scrolls sideways at {width}x{height}"


@pytest.mark.parametrize("width, height", [(1440, 900), (1100, 760), (820, 1000)])
def test_the_forty_mile_ring_fits_the_shorter_side_of_the_radar(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_timeout(300)
    box = page.eval_on_selector("#radar", "e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }")
    size = page.eval_on_selector("#radar", "e => [e.width / devicePixelRatio, e.height / devicePixelRatio]")
    assert abs(box[0] - size[0]) <= 1 and abs(box[1] - size[1]) <= 1, "the canvas does not fill its pane"


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
    page.evaluate(
        """window.kcgx.store.apply({t: "aircraft", ok: true, error: "", age: 0, refresh: 15, range: 40,
            ac: [{hex: "e1", label: "N52RT", type: "BE36", lat: 45.9, lon: -123.0, alt: 7500, gs: 150,
                  trk: 120, sq: "7600", age: 0, dist: 25.2, brg: 315}]})"""
    )
    page.wait_for_selector(".lamp.emerg .lamp-label:text-is('7600')")
    assert page.get_attribute('#tracks-body tr[data-hex="e1"]', "class") == "emergency"


def test_a_refused_radar_says_so_and_dims_its_lamp(page):
    wait_for_traffic(page)
    page.evaluate(
        """window.kcgx.store.apply({t: "aircraft", ok: false, error: "ERR 429", age: 40, refresh: 15,
            range: 40, ac: []})"""
    )
    page.wait_for_function("document.getElementById('radar-poll').textContent.startsWith('ERR 429')")
    assert "warn" in page.get_attribute(".lamp:has(.lamp-label:text-is('RADAR'))", "class")
