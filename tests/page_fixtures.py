"""What every page test file shares: the demo server, the two browsers, a
tab on the cockpit, and the helpers that work it (plan phase G, P0.4b).

A page test file takes all of it with

    from page_fixtures import *  # noqa: F403  (fixtures and helpers)

and so gets its own server: `server` (like `page_state` in conftest.py, which
it uses) is module scoped, and pytest keeps one of a module-scoped fixture
for each module that has it in its namespace. `browser` is module scoped too,
and runs the file in Chromium and then in WebKit. Without Playwright the
import skips the whole file.
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
import weakref
import zlib

import pytest

from kcgx.prefs import DEFAULTS
from test_page_prefs import TAB_OF

playwright_api = pytest.importorskip("playwright.sync_api")

__all__ = [
    "SIZES",
    "_free_port",
    "server",
    "browser",
    "page",
    "page_errors",
    "other",
    "RADAR_DRAWN",
    "radar_drawn",
    "feed_names",
    "glow",
    "set_prefs",
    "parts",
    "config_tab",
    "pref_is",
    "pressed",
    "readout",
    "pixel",
    "css_colour",
    "spy_on_sends",
    "box_of",
    "radar_debug",
    "on_screen",
    "wait_for_traffic",
    "rows",
    "focus_on_the_radar",
    "canvas_size",
    "centre_of_the_radar",
    "fit",
    "turn_wheel",
    "zoom_right_in",
    "lit",
    "pan",
    "plane",
    "RADAR_FRAME",
    "frames",
    "tags",
    "hold_traffic",
    "draw",
    "canvas_pixels",
    "inside_corners",
    "edge_middles",
    "canvas_block",
    "ink",
    "holds",
    "picture",
]


# -- the server, the browsers, the tabs ---------------------------------------


SIZES = [(1440, 900), (1280, 720), (1100, 760), (820, 1000), (390, 844)]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(page_state):
    state = page_state
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


@pytest.fixture(scope="module", params=["chromium", "webkit"])
def browser(request):
    """Each browser in turn, one at a time: every test of the page runs in
    Chromium and then in WebKit. One that is not installed skips its tests."""
    with playwright_api.sync_playwright() as p:
        try:
            launched = getattr(p, request.param).launch()
        except playwright_api.Error as error:  # this browser is not installed
            pytest.skip(f"no {request.param} for Playwright: {error}")
        yield launched
        launched.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = _errors[page] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(server + "/")
    page.wait_for_selector(".feed.expanded")
    # The server outlives each test, and so do its prefs: start from the defaults.
    set_prefs(page, **DEFAULTS)
    # A range left by the test before is a view left by it: the radar is
    # drawn at this test's on its next frame, and until then says the old.
    radar_drawn(page)
    yield page
    context.close()
    assert errors == [], errors


_errors = weakref.WeakKeyDictionary()  # page -> what `page_errors` gives


def page_errors(page, wait_for=None, timeout=3.0):
    """The errors the page has reported so far, as the `page` fixture collects
    them (one thrown and not caught, or one written to the console) and fails
    the test on. A test that means to cause one checks it here and clears the
    list. With `wait_for`, first waits until one of them contains it."""
    errors = _errors[page]
    deadline = time.monotonic() + timeout
    while wait_for and not any(wait_for in e for e in errors) and time.monotonic() < deadline:
        page.wait_for_timeout(50)
    return errors


@pytest.fixture
def other(browser, server, page):
    """A second tab on the same cockpit. It asks for `page` so that it opens
    after the prefs are back at their defaults."""
    tab = browser.new_page()
    tab.goto(server + "/")
    tab.wait_for_selector(".feed.expanded")
    yield tab
    tab.close()


# Whether the radar's last frame was of the view it holds and the range that is set.
RADAR_DRAWN = """() => { const d = window.kcgx.radar.debug();
                         const now = { ...d.view, range: window.kcgx.store.state.prefs.range_nm };
                         return JSON.stringify(d.shown) === JSON.stringify(now); }"""


def radar_drawn(page):
    """Wait until the radar has drawn the view it holds, at the range that is
    set; returns what it drew."""
    page.wait_for_function(RADAR_DRAWN)
    return page.evaluate("window.kcgx.radar.debug()")


def feed_names(page, shape):
    return page.eval_on_selector_all(f".feed.{shape} .feed-name", "els => els.map(e => e.textContent)")


def glow(level):
    """All three glow numbers at one level. The phase F choice's OFF, LOW and
    FULL are 0, 33 and 75 (phase G decision 15)."""
    return {"glow_map": level, "glow_traffic": level, "glow_text": level}


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


# -- the config sheet ----------------------------------------------------------


def config_tab(page, key=None, tab=None):
    """Open the config sheet, if it is not open, on the tab that holds `key`'s
    control (or on `tab`), and wait until that tab shows."""
    if not page.evaluate("document.getElementById('config-sheet').open"):
        page.click("#open-config")
        page.wait_for_selector("#config-sheet[open]")
    name = tab or TAB_OF[key]
    page.click(f"#config-sheet [role=tab]:text-is('{name}')")
    page.wait_for_selector(f"#config-sheet [role=tab][aria-selected=true]:text-is('{name}')")


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


# -- pixels and boxes -----------------------------------------------------------


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


def box_of(page, selector):
    return page.eval_on_selector(selector, "e => e.getBoundingClientRect().toJSON()")


# -- the radar and the table ---------------------------------------------------


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


def rows(page):
    """The tracks table as it stands, read in one go: [{hex, focused, cells}]."""
    return page.eval_on_selector_all(
        "#tracks-body tr",
        """trs => trs.map(tr => ({hex: tr.dataset.hex, focused: tr.classList.contains("focused"),
                                  cells: [...tr.cells].map(td => td.textContent)}))""",
    )


def focus_on_the_radar(page):
    """Click an aircraft on the radar that the table does not already list
    first, and that has no other within 40 px; returns its hex."""
    wait_for_traffic(page)
    page.wait_for_function("document.querySelectorAll('#tracks-body tr').length >= 5")
    # A window just resized is drawn at its new size on the next frame, and
    # until then the radar's positions are the old size's.
    page.wait_for_function(
        """() => { const c = document.getElementById("radar"); const box = c.getBoundingClientRect();
                   return c.width === Math.round(box.width * devicePixelRatio)
                       && c.height === Math.round(box.height * devicePixelRatio); }"""
    )
    leading = {row["hex"] for row in rows(page)[:2]}
    hits = radar_debug(page)["hits"]
    hit = next(
        h for h in hits
        if h["hex"] not in leading
        and all(o is h or abs(o["x"] - h["x"]) + abs(o["y"] - h["y"]) > 40 for o in hits)
    )
    page.mouse.click(*on_screen(page, hit["x"], hit["y"]))
    page.wait_for_selector(f'#tracks-body tr.focused[data-hex="{hit["hex"]}"]')
    return hit["hex"]


def canvas_size(page):
    return page.eval_on_selector("#radar", "c => [c.width, c.height]")


def centre_of_the_radar(page):
    """The middle of the canvas, as a page position."""
    width, height = canvas_size(page)
    return on_screen(page, width / 2, height / 2)


def fit(page):
    """How far from the centre, in canvas pixels, the view's own distance is
    drawn: the shorter half side less 18 px."""
    width, height = canvas_size(page)
    return min(width, height) / 2 - 18 * page.evaluate("devicePixelRatio")


def turn_wheel(page, delta):
    """Turn the wheel where the pointer is; returns once the radar has had it."""
    page.evaluate(
        """() => { if (window.wheels !== undefined) return;
                   window.wheels = 0;
                   document.getElementById("radar").addEventListener("wheel", () => { window.wheels += 1; }); }"""
    )
    before = page.evaluate("window.wheels")
    page.mouse.wheel(0, delta)
    page.wait_for_function("before => window.wheels > before", arg=before)


def zoom_right_in(page):
    """To the closest view, about the airport."""
    page.mouse.move(*centre_of_the_radar(page))
    for _ in range(6):
        turn_wheel(page, -600)
    radar_drawn(page)


def lit(page, x, y):
    """The brightest channel of the canvas within a pixel of (x, y)."""
    return page.evaluate(
        """([x, y]) => Math.max(...document.getElementById("radar").getContext("2d")
                                    .getImageData(Math.round(x) - 1, Math.round(y) - 1, 3, 3).data
                                    .filter((_, i) => i % 4 !== 3))""",
        [x, y],
    )


def pan(page, x, y, **press):
    """Drag the radar from (x, y); `press` is how the browser counts the press."""
    page.mouse.move(x, y)
    page.mouse.down(**press)
    page.mouse.move(x + 120, y + 60, steps=6)
    page.mouse.up(**press)


# -- traffic of a test's own ----------------------------------------------------


def plane(hex_, east=0.0, north=0.0, **over):
    """An aircraft for `hold_traffic`: `east` and `north` of the airport in
    nm, and standing still unless it is given a ground speed."""
    return {
        "hex": hex_, "label": hex_.upper(), "type": "B738", "east": east, "north": north, "alt": 12000,
        "gs": 0, "trk": 270, "sq": "4512", "age": 0, "dist": 12.4, "brg": 270, **over,
    }


# One frame of the radar's from now, not of the browser's: the frame rate cap
# passes over browser frames that come too soon (headless WebKit's come 10 ms
# apart). The radar's clock asks for each frame before a test does, so it has
# drawn by the time the test looks. A radar that draws none for 2 s is broken,
# and the wait says so rather than hang (page.evaluate has no timeout).
RADAR_FRAME = """async () => {
    const drawn = window.kcgx.radar.debug().frames, since = performance.now();
    while (window.kcgx.radar.debug().frames === drawn) {
        if (performance.now() - since > 2000) throw new Error(`the radar drew no frame in 2 s (frames ${drawn})`);
        await new Promise(requestAnimationFrame);
    }
}"""


def frames(page, count=2):
    """Let the radar draw: returns `count` of its frames from now."""
    page.evaluate(
        f"async count => {{ const frame = {RADAR_FRAME}; for (let n = 0; n < count; n += 1) await frame(); }}",
        count,
    )


def tags(page):
    """Each aircraft's tag as the radar last drew it, by hex."""
    return {hit["hex"]: hit["tag"] for hit in radar_debug(page)["hits"]}


def hold_traffic(page, *aircraft):
    """Put these aircraft on the radar, and no others, for the rest of the
    test: the demo's own polls are dropped from here on. Returns their tags."""
    page.evaluate(
        """planes => {
            const store = window.kcgx.store;
            if (!window.heard) {
                window.heard = store.apply;
                store.apply = frame => { if (frame.t !== "aircraft") window.heard(frame); };
            }
            const { lat, lon } = store.state.airport;
            const ac = planes.map(({ east, north, ...rest }) => ({
                ...rest, lat: lat + north / 60, lon: lon + east / (60 * Math.cos(lat * Math.PI / 180)) }));
            window.heard({t: "aircraft", ok: true, error: "", age: 0, refresh: 15, range: 40, ac});
        }""",
        list(aircraft),
    )
    page.wait_for_function(
        "hexes => window.kcgx.radar.debug().hits.map(h => h.hex).join() === hexes.join()",
        arg=[a["hex"] for a in aircraft],
    )
    return tags(page)


def draw(page, **prefs):
    """Change settings and let the radar draw with them; returns what it drew."""
    set_prefs(page, **prefs)
    frames(page)
    return radar_drawn(page)


def canvas_pixels(page, *points):
    """The radar canvas's own pixels at these points, each (r, g, b, a). The
    canvas, not the page: no scanlines, no jitter."""
    found = page.evaluate(
        """points => { const ctx = document.getElementById("radar").getContext("2d");
                       return points.map(([x, y]) => [...ctx.getImageData(x, y, 1, 1).data]); }""",
        [[round(x), round(y)] for x, y in points],
    )
    return [tuple(p) for p in found]


def inside_corners(box):
    """The pixels just inside a box's corners, within a 1 px border."""
    left, top, right, bottom = box["x"] + 1, box["y"] + 1, box["x"] + box["w"] - 2, box["y"] + box["h"] - 2
    return [(left, top), (right, top), (left, bottom), (right, bottom)]


def edge_middles(box):
    """The pixels at the middle of each of a box's edges: top, bottom, left, right."""
    x, y = box["x"] + box["w"] // 2, box["y"] + box["h"] // 2
    return [(x, box["y"]), (x, box["y"] + box["h"] - 1), (box["x"], y), (box["x"] + box["w"] - 1, y)]


def canvas_block(page, rect):
    """Every pixel of the radar canvas that a rectangle touches, as one flat
    list of r, g, b, a."""
    left, top = int(rect["x"]), int(rect["y"])
    right, bottom = -int(-(rect["x"] + rect["w"])), -int(-(rect["y"] + rect["h"]))
    return page.evaluate(
        """([x, y, w, h]) => [...document.getElementById("radar").getContext("2d").getImageData(x, y, w, h).data]""",
        [left, top, right - left, bottom - top],
    )


def ink(block):
    """How many of a block's pixels are lit."""
    return sum(max(block[i:i + 3]) > 100 for i in range(0, len(block), 4))


def holds(outer, inner):
    return (
        outer["x"] <= inner["x"] and outer["y"] <= inner["y"]
        and outer["x"] + outer["w"] >= inner["x"] + inner["w"] and outer["y"] + outer["h"] >= inner["y"] + inner["h"]
    )


def picture(page):
    """The radar canvas, once two looks at it two of its frames apart agree:
    the map draws itself on over two seconds, and a setting takes a frame to
    show. For a picture that holds still: aircraft with no ground speed."""
    return page.evaluate(
        """async () => { const canvas = document.getElementById("radar");
                         const frame = """ + RADAR_FRAME + """;
                         let last = "";
                         for (let tries = 0; tries < 400; tries += 1) {
                             await frame(); await frame();
                             const now = canvas.toDataURL();
                             if (now === last) return now;
                             last = now;
                         }
                         throw new Error("the radar never held still"); }"""
    )
