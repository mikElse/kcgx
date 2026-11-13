"""The boot animation (phase G Task 14, decisions 1 and 6): the vector scene
from `Vector Cockpit Drawing/vector-scene.jsx`, played once per launch over
a page that connects and fills in beneath it.

Only the first page a server serves after it starts is told to boot (its
snapshot's `boot`), and the page fixtures' module server has served one by
the time a test gets its tab, with `boot_anim` off besides (conftest). So
each test here starts a demo server of its own (`fresh`), with the prefs it
asks for, and its first tab is the test's. That is a second or so a test,
in each browser. `browser`, `pixel`, `css_colour` and `_free_port` are the
page fixtures'; their `server` and `page` are not used.

Nothing here waits on the wall clock to be quick: what must happen before a
timer fires is held back by Playwright's clock (`tab(clock=True)`), and what
must not yet have happened is checked against the page's own state.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

import pytest

from page_fixtures import *  # noqa: F403  (fixtures and helpers)
from page_fixtures import _free_port, css_colour, pixel

pytestmark = pytest.mark.browser

LENGTH = 21.7  # the animation's playback length in s (Vector Cockpit.dc.html's scenes)
FADE_MS = 600
FALLBACK_MS = 3000  # index.html: the page shows by then whatever main.js does
STATIC = pathlib.Path(__file__).resolve().parents[1] / "src" / "kcgx" / "web" / "static"


@pytest.fixture
def fresh(tmp_path):
    """`fresh(**prefs)` starts a demo server with these prefs stored, and
    gives its address; every one started is stopped after the test."""
    started = []

    def start(**prefs):
        state = tmp_path / f"state-{len(started)}"
        state.mkdir()
        (state / "prefs.json").write_text(json.dumps({"boot_anim": True, **prefs}) + "\n")
        port = _free_port()
        env = {**os.environ, "KCGX_STATE_PATH": str(state / "airport"), "HOME": str(state / "home")}
        # Its output goes to a file, which nothing has to keep reading.
        output = state / "server.log"
        with output.open("wb") as sink:
            process = subprocess.Popen(
                [sys.executable, "-m", "kcgx.server", "--demo", "--icao", "KPDX", "--port", str(port)],
                env=env, stdout=sink, stderr=subprocess.STDOUT,
            )
        started.append(process)
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"{base}/api/health", timeout=1) as response:
                    if json.load(response)["ok"]:
                        return base
            except OSError:
                time.sleep(0.1)
        process.kill()
        process.wait(timeout=10)
        pytest.fail("kcgx-web --demo never answered: " + output.read_text(errors="replace"))

    yield start
    for process in started:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def tab(browser):
    """`tab(url, **context)` opens a page in a context of its own (a
    viewport of 1440 by 900 unless given), and fails the test on any error
    it reports. `path` is what to open (the cockpit, unless given); `hold`
    holds back what the server sends (HOLD); `clock` installs Playwright's
    clock, paused, so no timer on the page fires until the test moves it on;
    `before(page)` runs before it is opened. A test that means to cause an
    error checks `tab.errors` and clears it."""
    contexts, errors = [], []

    def open_(url, path="/", hold=False, clock=False, before=None, **options):
        context = browser.new_context(**{"viewport": {"width": 1440, "height": 900}, **options})
        contexts.append(context)
        if hold:
            context.add_init_script(HOLD)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        if clock:
            page.clock.install(time=1_000_000)
            page.clock.pause_at(1_001_000)
        if before:
            before(page)
        page.goto(url + path)
        return page

    open_.errors = errors
    yield open_
    for context in contexts:
        context.close()
    assert errors == [], errors


# Holds every frame the server sends until `window.release()`: the page's
# socket opens and the server's snapshot is on its way, but the page has
# not heard it.
HOLD = """(() => {
  const Real = window.WebSocket, held = [];
  window.holding = true;
  window.release = () => { window.holding = false; for (const go of held.splice(0)) go(); };
  window.WebSocket = class extends Real {
    addEventListener(type, fn, ...rest) {
      if (type !== "message") return super.addEventListener(type, fn, ...rest);
      return super.addEventListener(type, (event) => window.holding ? held.push(() => fn(event)) : fn(event), ...rest);
    }
  };
})()"""


def boot_state(page):
    return page.evaluate("window.kcgx.boot.state")


def opacity(page, selector):
    return float(page.eval_on_selector(selector, "e => getComputedStyle(e).opacity"))


def playing(page):
    page.wait_for_function("window.kcgx && window.kcgx.boot.state === 'playing'")


def gone(page):
    """Until the cover has faded and removed itself, and the page shows."""
    page.wait_for_function(
        "window.kcgx.boot.state === 'done' && !document.getElementById('boot')"
        " && !document.documentElement.hasAttribute('data-booting')"
        " && getComputedStyle(document.querySelector('.page')).opacity === '1'",
        timeout=5000,
    )


def no_cover(page):
    page.wait_for_selector(".feed.expanded")
    page.wait_for_function("window.kcgx.boot.state === 'none'")
    assert not page.evaluate("document.documentElement.hasAttribute('data-booting')")
    assert page.evaluate("!document.getElementById('boot') || document.getElementById('boot').hidden")
    assert opacity(page, ".page") == 1


def held_at(page, t):
    """Stop the animation at `t` s of playback, and wait until 16 frames
    have been drawn there: the burn-in fades what was drawn before by 0.45 a
    frame, and in 16 frames to nothing."""
    page.evaluate("t => window.kcgx.boot.hold(t)", t)
    page.evaluate(
        """async () => { const boot = window.kcgx.boot, from = boot.frames;
                         while (boot.frames < from + 16) await new Promise(requestAnimationFrame); }"""
    )


# -- once per launch -----------------------------------------------------------


def test_the_first_page_boots_under_the_cover_while_the_cockpit_fills_in(fresh, tab):
    page = tab(fresh())
    playing(page)
    assert page.is_visible("#boot")
    cover = page.eval_on_selector("#boot", "e => getComputedStyle(e).backgroundColor")
    assert [int(n) for n in cover.replace("rgb(", "").rstrip(")").split(",")] == list(css_colour(page, "--wall"))
    assert opacity(page, "#boot") == 1
    assert opacity(page, ".page") == 0
    first = page.evaluate("window.kcgx.boot.t")
    page.wait_for_timeout(300)
    assert page.evaluate("window.kcgx.boot.t") > first
    # Beneath it the page is live: connected, the radar drawing, the HUD's
    # poll written, before anything fades.
    page.wait_for_function(
        "window.kcgx.store.state.connected && window.kcgx.radar.debug().frames > 3"
        " && document.getElementById('radar-poll').textContent !== 'RADAR WAITING'"
    )
    page.wait_for_selector(".feed.expanded")
    assert boot_state(page) == "playing"
    # index.html's fallback, which shows the page if nothing has decided by
    # 3 s, was called off when the snapshot decided: the page stays hidden.
    page.wait_for_function(f"performance.now() > {FALLBACK_MS + 300}", timeout=FALLBACK_MS + 2000)
    assert boot_state(page) == "playing"
    assert page.evaluate("document.documentElement.hasAttribute('data-booting')")
    assert opacity(page, ".page") == 0


def test_it_fades_out_by_itself_at_the_end(fresh, tab):
    page = tab(fresh())
    playing(page)
    page.evaluate("t => window.kcgx.boot.seek(t)", LENGTH - 0.3)
    assert boot_state(page) == "playing"
    page.wait_for_function("window.kcgx.boot.state === 'leaving'", timeout=3000)
    assert page.evaluate("window.kcgx.boot.t") >= LENGTH
    durations = page.evaluate(
        "() => [getComputedStyle(document.getElementById('boot')).transitionDuration,"
        "       getComputedStyle(document.querySelector('.page')).transitionDuration]"
    )
    assert durations == ["0.6s", "0.6s"]
    gone(page)


@pytest.mark.parametrize("how", ["key", "click"])
def test_a_key_or_a_click_skips_it_at_once(fresh, tab, how):
    page = tab(fresh())
    playing(page)
    page.wait_for_function("window.kcgx.boot.frames > 3")
    canvases = page.evaluate("window.kcgx.boot.canvases")
    assert canvases and all(w > 0 and h > 0 for w, h in canvases[:1]), canvases
    page.evaluate("window.coverCanvas = document.querySelector('#boot canvas')")
    started = time.monotonic()
    if how == "key":
        page.keyboard.press("Space")
    else:
        page.mouse.click(700, 400)
    assert boot_state(page) == "leaving"
    assert page.evaluate("window.kcgx.boot.t") < 5
    gone(page)
    assert time.monotonic() - started >= FADE_MS / 1000
    # The press was the skip's, not the cockpit's: nothing opened under it.
    assert not page.evaluate("[...document.querySelectorAll('dialog')].some(d => d.open)")
    # Done, it holds no canvas: their backing stores are given back.
    assert page.evaluate("window.kcgx.boot.canvases") == []
    assert page.evaluate("[window.coverCanvas.width, window.coverCanvas.height]") == [0, 0]
    assert page.evaluate("window.kcgx.boot.t") < 5


def test_a_modifier_key_alone_does_not_skip_it(fresh, tab):
    """Shift, Control, Alt, Meta and Caps Lock are half a shortcut, or
    nothing at all, rather than a press."""
    page = tab(fresh())
    playing(page)
    for key in ["Shift", "Control", "Alt", "Meta", "CapsLock"]:
        page.keyboard.press(key)
        assert boot_state(page) == "playing", key
    page.keyboard.press("KeyA")
    assert boot_state(page) == "leaving"
    gone(page)


def test_a_scene_that_fails_to_draw_still_ends(fresh, tab):
    """A frame that throws, every frame, neither keeps the cover up nor fills
    the console: it is written once, and the cover leaves at the end."""
    page = tab(fresh())
    playing(page)
    page.evaluate(
        """() => Object.defineProperty(document.getElementById('boot'), 'clientWidth',
                                       { get() { throw new Error('forced draw failure'); } })"""
    )
    page.wait_for_function(f"window.kcgx.boot.frames > {page.evaluate('window.kcgx.boot.frames') + 5}")
    page.evaluate("t => window.kcgx.boot.seek(t)", LENGTH - 0.3)
    page.wait_for_function("window.kcgx.boot.state !== 'playing'", timeout=3000)
    gone(page)
    failures = [e for e in tab.errors if "forced draw failure" in e]
    assert len(failures) == 1, tab.errors
    tab.errors.clear()


def test_the_debug_page_does_not_use_up_the_boot(fresh, tab):
    """Only the cockpit page plays it, so only the cockpit is told to: a
    /debug opened first leaves it for the cockpit after."""
    url = fresh()
    debug = tab(url, path="/debug")
    debug.wait_for_function("document.getElementById('status').textContent === 'live'")
    page = tab(url)
    playing(page)


def screen_at(page, x, y, reach=4):
    """Where on the screen (CSS px) the scene canvas's most opaque pixel
    within `reach` of the scene's point (x, y) is."""
    return page.evaluate(
        """([x, y, reach]) => {
            const canvas = document.querySelector('#boot canvas'), ctx = canvas.getContext('2d');
            const [cx, cy] = window.kcgx.boot.at(x, y);
            const x0 = Math.round(cx) - reach, y0 = Math.round(cy) - reach, side = 2 * reach + 1;
            const d = ctx.getImageData(x0, y0, side, side).data;
            let best = 0;
            for (let i = 0; i < d.length; i += 4) if (d[i + 3] > d[best + 3]) best = i;
            const k = canvas.width / canvas.getBoundingClientRect().width, rect = canvas.getBoundingClientRect();
            return [rect.left + (x0 + (best / 4) % side + 0.5) / k, rect.top + (y0 + Math.floor(best / 4 / side) + 0.5) / k];
        }""",
        [x, y, reach],
    )


def test_a_link_to_the_airport_search_opens_it_after_the_boot(fresh, tab):
    """`kcgx go` with no airport opens /#airport: the boot plays at full
    brightness, with no sheet's backdrop over it, and the search opens, with
    the query in it and focused, once the cover has gone."""
    page = tab(fresh(glow_map=0), path="/#airport=sea")
    playing(page)
    # Record what the boot was doing when the sheet opened.
    page.evaluate(
        """() => { const sheet = document.getElementById('airport-sheet');
                   new MutationObserver(() => { if (sheet.open && window.openedWhen === undefined)
                     window.openedWhen = window.kcgx.boot.state; })
                     .observe(sheet, { attributes: true, attributeFilter: ['open'] }); }"""
    )
    assert not page.evaluate("document.getElementById('airport-sheet').open")
    held_at(page, 12.0)
    x, y = screen_at(page, 540, 330)  # the cab's floor line, in --white
    assert max(pixel(page, x, y)) > 150, pixel(page, x, y)
    page.evaluate("window.kcgx.boot.hold(null)")
    page.evaluate("t => window.kcgx.boot.seek(t)", LENGTH - 0.1)
    gone(page)
    page.wait_for_selector("#airport-sheet[open]")
    assert page.evaluate("window.openedWhen") == "done"
    assert page.input_value("#airport-query") == "sea"
    assert page.evaluate("document.activeElement.id") == "airport-query"


def test_the_page_shows_by_itself_if_the_cockpit_never_starts(fresh, tab):
    """An error before boot.js decides (here main.js fails to load) leaves
    nothing to take data-booting off: index.html's own script does, at 3 s."""
    url = fresh()
    page = tab(url, before=lambda p: p.route("**/static/js/main.js", lambda route: route.fulfill(status=500)))
    page.wait_for_function(
        "!document.documentElement.hasAttribute('data-booting')"
        " && getComputedStyle(document.querySelector('.page')).opacity === '1'",
        timeout=3500,
    )
    assert page.evaluate("typeof window.kcgx") == "undefined"
    tab.errors.clear()  # the failed load


def test_a_second_page_on_the_same_server_gets_no_cover(fresh, tab):
    url = fresh()
    first = tab(url)
    playing(first)
    second = tab(url)
    no_cover(second)
    assert boot_state(first) == "playing"


def test_with_the_setting_off_there_is_no_cover_and_turning_it_on_later_shows_none(fresh, tab):
    page = tab(fresh(boot_anim=False))
    no_cover(page)
    page.evaluate("window.kcgx.send({t: 'prefs', boot_anim: true})")
    page.wait_for_function("window.kcgx.store.state.prefs.boot_anim === true")
    page.wait_for_timeout(300)
    no_cover(page)


def test_reduced_motion_gives_no_cover(fresh, tab):
    page = tab(fresh(), reduced_motion="reduce")
    no_cover(page)


# -- the first paint -----------------------------------------------------------


def dark(rgb):
    return max(rgb) <= 12


def test_the_page_is_black_until_the_first_snapshot(fresh, tab):
    """No flash of the default palette: until the server has said which
    palette and whether to boot, nothing of the page shows."""
    page = tab(fresh(palette="AMBER"), hold=True, clock=True)
    page.wait_for_function("window.kcgx !== undefined")
    assert page.evaluate("document.documentElement.hasAttribute('data-booting')")
    assert opacity(page, ".page") == 0
    brand = page.eval_on_selector(".brand-name", "e => e.getBoundingClientRect().toJSON()")
    frame = page.eval_on_selector(".screen-radar", "e => e.getBoundingClientRect().toJSON()")
    points = [
        (brand["x"] + brand["width"] / 2, brand["y"] + brand["height"] / 2),
        (frame["x"] + 1, frame["y"] + frame["height"] / 2),
        (frame["x"] + frame["width"] / 2, frame["y"] + 1),
        (700, 450),
    ]
    assert all(dark(pixel(page, x, y)) for x, y in points), [pixel(page, x, y) for x, y in points]
    assert page.evaluate("document.documentElement.hasAttribute('data-booting')")  # the clock held
    page.evaluate("window.release()")
    page.clock.resume()
    playing(page)
    assert page.evaluate("document.documentElement.dataset.palette") == "AMBER"


def test_with_no_snapshot_in_1_5_s_the_page_shows_without_a_cover(fresh, tab):
    page = tab(fresh(), hold=True, clock=True)
    page.wait_for_function("window.kcgx !== undefined")
    page.clock.run_for(1400)
    assert page.evaluate("document.documentElement.hasAttribute('data-booting')")
    assert boot_state(page) == "waiting"
    page.clock.run_for(200)
    assert not page.evaluate("document.documentElement.hasAttribute('data-booting')")
    assert boot_state(page) == "none"
    # Decided once: the snapshot that comes later says boot, and is too late.
    page.evaluate("window.release()")
    page.clock.resume()
    no_cover(page)


# -- the scene ----------------------------------------------------------------


def brightest(page, x, y, reach=4):
    """The scene canvas's most opaque pixel within `reach` of the scene's
    point (x, y): (r, g, b, a)."""
    return tuple(page.evaluate(
        """([x, y, reach]) => {
            const canvas = document.querySelector('#boot canvas'), ctx = canvas.getContext('2d');
            const [cx, cy] = window.kcgx.boot.at(x, y);
            const d = ctx.getImageData(Math.round(cx) - reach, Math.round(cy) - reach, 2 * reach + 1, 2 * reach + 1).data;
            let best = 0;
            for (let i = 0; i < d.length; i += 4) if (d[i + 3] > d[best + 3]) best = i;
            return [d[best], d[best + 1], d[best + 2], d[best + 3]];
        }""",
        [x, y, reach],
    ))


@pytest.mark.parametrize("palette", ["WOPR", "AMBER"])
def test_the_tower_is_drawn_in_the_palette_s_white(fresh, tab, palette):
    page = tab(fresh(palette=palette, glow_map=0))
    playing(page)
    held_at(page, 12.0)  # the tower is whole; KCGX not begun
    *rgb, alpha = brightest(page, 540, 330)  # the cab's floor line
    assert alpha > 200
    white = css_colour(page, "--white")
    assert all(abs(a - b) <= 3 for a, b in zip(rgb, white)), (rgb, white)
    if palette == "AMBER":
        assert abs(rgb[2] - 255) > 30, "drawn in WOPR's white"


def test_the_scene_moves_through_its_six_parts(fresh, tab):
    """A few things vector-scene.jsx draws at known times: the horizon at
    once, the skyline whole by the end of Draw, the runway gone with the turn
    and the tower whole before the lights."""
    page = tab(fresh(glow_map=0))
    playing(page)
    held_at(page, 2.95)
    assert brightest(page, 1000, 408)[3] > 150  # the horizon line, right of the runway
    assert brightest(page, 17.4, 206.4)[3] > 150  # the top of the tallest tower in the skyline
    held_at(page, 12.0)
    assert brightest(page, 325, 500)[3] > 150  # the tower's left side
    held_at(page, 0.0)
    assert brightest(page, 325, 500)[3] <= 1  # what quantising leaves of the faded


def test_kcgx_fades_in_letter_by_letter(fresh, tab):
    """At 14 s of playback K is whole and G has only begun
    (vector-scene.jsx:92-97), with the glow on: WebKit draws text with a
    shadow at full alpha unless the fade is in the colour."""
    page = tab(fresh())
    playing(page)
    page.evaluate("document.fonts.ready")
    held_at(page, 14.0)
    assert brightest(page, 405, 490, reach=40)[3] > 200  # K
    assert brightest(page, 585, 490, reach=40)[3] < 60  # G


@pytest.mark.parametrize(("palette", "edge"), [("WOPR", "--alarm"), ("AMBER", "--frame")])
def test_the_runway_edges_are_the_alarm_colour_unless_that_is_white(fresh, tab, palette, edge):
    page = tab(fresh(palette=palette, glow_map=0))
    playing(page)
    held_at(page, 2.95)
    *rgb, alpha = brightest(page, 1030, 810, reach=6)  # the right edge's near end, M551 410 L1030 810
    assert alpha > 150
    assert all(abs(a - b) <= 3 for a, b in zip(rgb, css_colour(page, edge))), (rgb, css_colour(page, edge))


def serve_static(route):
    """The page's own scripts from the source tree, and a blank page."""
    path = route.request.url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
    if path.startswith("static/"):
        route.fulfill(path=STATIC / path.removeprefix("static/"), content_type="text/javascript")
    else:
        route.fulfill(body="<!doctype html><title>boot.js</title>", content_type="text/html")


def test_burn_in_is_a_half_life_in_ms(tab):
    """Decision 15: the canvas fades by 1 - 0.5 ** (ms / burn_in) a frame,
    so 19, the default, is the radar's old 0.45 a frame at 60 Hz. A pure
    function: boot.js is loaded on its own, with no server."""
    page = tab("http://kcgx.test", before=lambda p: p.route("http://kcgx.test/**", serve_static))
    fade = lambda ms, half: page.evaluate(  # noqa: E731
        "([ms, half]) => import('/static/js/boot.js').then((boot) => boot.fadeFor(ms, half))", [ms, half]
    )
    assert fade(1000 / 60, 19) == pytest.approx(0.45, abs=0.01)
    assert fade(1000 / 30, 19) == pytest.approx(1 - 0.55**2, abs=0.01)
    assert fade(16, 0) == 1
