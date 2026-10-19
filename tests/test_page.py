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
