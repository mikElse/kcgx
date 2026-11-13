from page_fixtures import *  # noqa: F403  (fixtures and helpers)

# The page's chrome, phase G Task 3 and Task 4's text glow: UI zoom on the
# page and the sheets, the font and its size, the clock formats, and the
# text glow from `glow_text`.

# Browser tests against the demo server, in Chromium and then WebKit.

import contextlib
import datetime
import re
import struct
import zlib
from pathlib import Path

import pytest

from kcgx.prefs import DEFAULTS

from page_fixtures import (
    SIZES,
    config_tab,
    radar_debug,
    rows,
    set_prefs,
    wait_for_traffic,
)

pytestmark = pytest.mark.browser

FONTS_DIR = Path(__file__).parent.parent / "src" / "kcgx" / "web" / "static" / "fonts"

# FONT's choices (phase G decision 17): the first family of the text and of
# the display (titles, big figures, the radar), and the file each face needs.
FAMILIES = {
    "CLASSIC": ("B612 Mono", "Share Tech Mono"),
    "B612": ("B612 Mono", "B612 Mono"),
    "SHARETECH": ("Share Tech Mono", "Share Tech Mono"),
    "PLEX": ("IBM Plex Mono", "IBM Plex Mono"),
    "JETBRAINS": ("JetBrains Mono", "JetBrains Mono"),
    "VT323": ("VT323", "VT323"),
    "SYSTEM": ("ui-monospace", "ui-monospace"),
}
FILES = {
    "B612 Mono": "b612-mono-latin-400-normal.woff2",
    "Share Tech Mono": "share-tech-mono-latin-400-normal.woff2",
    "IBM Plex Mono": "ibm-plex-mono-latin-400-normal.woff2",
    "JetBrains Mono": "jetbrains-mono-latin-400-normal.woff2",
    "VT323": "vt323-latin-400-normal.woff2",
}
LICENCES = {
    "B612 Mono": "OFL-B612Mono.txt",
    "Share Tech Mono": "OFL-ShareTechMono.txt",
    "IBM Plex Mono": "OFL-IBMPlexMono.txt",
    "JetBrains Mono": "OFL-JetBrainsMono.txt",
    "VT323": "OFL-VT323.txt",
}


def owed(choice):
    """The vendored files a choice needs that are not in static/fonts yet."""
    names = {name for name in FAMILIES[choice] if name in FILES}
    return sorted(file for name in names for file in (FILES[name], LICENCES[name]) if not (FONTS_DIR / file).exists())


def font_choice(choice):
    """A FONT choice as a test parameter, skipped while its font file is owed:
    the page asks for a face's file when the choice is made, and a missing
    one is a 404 on the console, which the `page` fixture fails on."""
    missing = owed(choice)
    return pytest.param(
        choice,
        marks=pytest.mark.skipif(
            bool(missing),
            reason=f"{choice}'s font is not vendored yet (no network to fetch it): owed {', '.join(missing)}",
        ),
    )


def first_family(page, selector):
    stack = page.eval_on_selector(selector, "e => getComputedStyle(e).fontFamily")
    return stack.split(",")[0].strip().strip("\"'")


def height(page, selector):
    """As painted: Playwright's box is the screen's in both engines, where
    WebKit's getBoundingClientRect leaves out a CSS zoom."""
    return page.locator(selector).bounding_box()["height"]


# -- UI zoom ----------------------------------------------------------------------


def test_ui_zoom_scales_the_page(page):
    before = height(page, "#icao")
    set_prefs(page, ui_zoom=150)
    page.wait_for_function("getComputedStyle(document.querySelector('.page')).zoom === '1.5'")
    assert height(page, "#icao") == pytest.approx(before * 1.5, abs=1)
    set_prefs(page, ui_zoom=75)
    assert height(page, "#icao") == pytest.approx(before * 0.75, abs=1)


def test_ui_zoom_scales_the_sheets_and_config_still_fills_the_window(page):
    config_tab(page, "ui_zoom")
    before = height(page, "#config-title")
    set_prefs(page, ui_zoom=150)
    assert height(page, "#config-title") == pytest.approx(before * 1.5, abs=1)
    sheet = page.locator("#config-sheet").bounding_box()
    assert sheet["x"] == pytest.approx(16, abs=1) and sheet["y"] == pytest.approx(16, abs=1)
    assert sheet["width"] == pytest.approx(1440 - 32, abs=1) and sheet["height"] == pytest.approx(900 - 32, abs=1)


@pytest.mark.parametrize("zoom", [75, 150])
def test_a_click_on_a_chevron_focuses_it_under_ui_zoom(page, zoom, request):
    if request.node.callspec.params["browser"] == "webkit":
        request.applymarker(pytest.mark.xfail(
            reason="WebKit gives getBoundingClientRect in unzoomed CSS px under CSS zoom while clientX/Y are the "
            "viewport's: radar/view.js local() must divide clientX/clientY by ui_zoom/100 there (MAP's file)",
            strict=True,
        ))
    set_prefs(page, ui_zoom=zoom)
    wait_for_traffic(page)
    page.wait_for_function("document.querySelectorAll('#tracks-body tr').length >= 5")
    # Drawn at the zoomed size: the canvas's backing store matches its box.
    page.wait_for_function(
        """() => { const c = document.getElementById("radar"); const box = c.getBoundingClientRect();
                   return c.width === Math.round(box.width * devicePixelRatio); }"""
    )
    # Where a canvas pixel is on the screen, from the canvas's painted box.
    box = page.locator("#radar").bounding_box()
    width, height_ = page.eval_on_selector("#radar", "c => [c.width, c.height]")
    leading = {row["hex"] for row in rows(page)[:2]}
    hits = radar_debug(page)["hits"]

    def screen(h):
        return box["x"] + h["x"] * box["width"] / width, box["y"] + h["y"] * box["height"] / height_

    hit = next(
        h for h in hits
        if h["hex"] not in leading
        and 0 < screen(h)[1] < 900 - 20 and 0 < screen(h)[0] < 1440
        and all(o is h or abs(o["x"] - h["x"]) + abs(o["y"] - h["y"]) > 40 for o in hits)
    )
    page.mouse.click(*screen(hit))
    page.wait_for_selector(f'#tracks-body tr.focused[data-hex="{hit["hex"]}"]', timeout=3000)


# -- the font and its size ------------------------------------------------------------


def test_font_size_sets_the_text_and_leaves_titles_and_figures(page):
    page.wait_for_selector("#tracks-body td")
    fixed = lambda: [  # noqa: E731
        page.eval_on_selector(s, "e => getComputedStyle(e).fontSize") for s in (".title-text", "#icao", "#zulu")
    ]
    before = fixed()
    set_prefs(page, font_px=16)
    sizes = set(page.eval_on_selector_all("#tracks-body td", "tds => tds.map(td => getComputedStyle(td).fontSize)"))
    assert sizes <= {"16px", "19.2px"} and "16px" in sizes, sizes  # the focused row is a fifth larger
    assert page.eval_on_selector("body", "e => getComputedStyle(e).fontSize") == "16px"
    assert fixed() == before
    set_prefs(page, font_px=11)
    assert page.eval_on_selector("#tracks-body td", "e => getComputedStyle(e).fontSize") == "11px"


@pytest.mark.parametrize("choice", [font_choice(c) for c in FAMILIES])
def test_each_font_is_the_page_s_and_the_radar_s(page, choice):
    text, display = FAMILIES[choice]
    set_prefs(page, font=choice)
    assert first_family(page, "body") == text
    assert first_family(page, "#tracks-body") == text
    assert first_family(page, ".title-text") == display
    assert first_family(page, "#icao") == display
    # The faces load from static/fonts (a system family has none to load).
    for name in {text, display}:
        page.wait_for_function(
            "name => document.fonts.ready.then(() => document.fonts.check(`16px \"${name}\"`))", arg=name, timeout=5000,
        )
    page.wait_for_function("name => window.kcgx.radar.debug().font.includes(name)", arg=display)


def test_the_vendored_fonts_are_all_declared(page):
    """Every face the page declares points at a file in static/fonts, and the
    files that are there each come with their licence."""
    css = (FONTS_DIR.parent / "cockpit.css").read_text()
    for name, file in FILES.items():
        assert f'font-family: "{name}"; src: url("fonts/{file}")' in css, name
        if (FONTS_DIR / file).exists():
            assert (FONTS_DIR / LICENCES[name]).exists(), f"{file} has no {LICENCES[name]}"


# -- the clocks ------------------------------------------------------------------------


@contextlib.contextmanager
def tab_at(browser, server, when, width=1440, height=900):
    """A tab in Los Angeles with its clock held at `when`. Its own context,
    so it collects its own errors."""
    context = browser.new_context(viewport={"width": width, "height": height}, timezone_id="America/Los_Angeles")
    tab = context.new_page()
    errors = []
    tab.on("pageerror", lambda error: errors.append(str(error)))
    tab.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    tab.clock.set_fixed_time(when)
    tab.goto(server + "/")
    tab.wait_for_selector(".feed.expanded")
    set_prefs(tab, **DEFAULTS)
    yield tab
    set_prefs(tab, **DEFAULTS)
    context.close()
    assert errors == [], errors


@pytest.fixture
def at_a_known_time(browser, server):
    """At 23:07:42Z on 13 November 2026 (15:07:42 PST)."""
    with tab_at(browser, server, datetime.datetime(2026, 11, 13, 23, 7, 42, tzinfo=datetime.timezone.utc)) as tab:
        yield tab


def clocks(tab):
    return tab.text_content("#zulu"), tab.text_content("#local")


@pytest.mark.parametrize(
    ("prefs", "zulu", "local"),
    [
        ({}, "2307Z", "15:07 PST"),
        ({"clock_24h": False}, "2307Z", "3:07 PM PST"),
        ({"clock_seconds": True}, "2307:42Z", "15:07:42 PST"),
        ({"clock_24h": False, "clock_seconds": True}, "2307:42Z", "3:07:42 PM PST"),
        ({"clock_zone": False}, "2307Z", "15:07"),
        ({"clock_24h": False, "clock_zone": False}, "2307Z", "3:07 PM"),
    ],
)
def test_the_clocks_read_as_set(at_a_known_time, prefs, zulu, local):
    tab = at_a_known_time
    set_prefs(tab, **prefs)
    # At once, not at the next tick.
    tab.wait_for_function("([z, l]) => zulu.textContent === z && local.textContent === l", arg=[zulu, local], timeout=900)
    assert clocks(tab) == (zulu, local)


# The widest clocks: two-digit hours, so 10, 11 or 12 o'clock, with AM/PM,
# seconds and the zone. 19:07:42Z is 11:07:42 AM PST.
LONGEST = datetime.datetime(2026, 11, 13, 19, 7, 42, tzinfo=datetime.timezone.utc)


@pytest.mark.parametrize("width, height", SIZES)
def test_the_longest_clocks_keep_beside_the_icao(browser, server, width, height):
    """On the ICAO's row and inside the pane at every size, both columns and
    the narrow layout, so the status pane keeps its height whatever the
    hour: the clocks going under the ICAO at 10 o'clock would grow it."""
    with tab_at(browser, server, LONGEST, width, height) as tab:
        pane_before = tab.locator(".screen-status").bounding_box()
        set_prefs(tab, clock_24h=False, clock_seconds=True)
        tab.wait_for_function("local.textContent === '11:07:42 AM PST' && zulu.textContent === '1907:42Z'")
        icao, clocks_, zulu, local, pane = (
            tab.locator(s).bounding_box() for s in ("#icao", ".clocks", "#zulu", "#local", ".screen-status")
        )
        assert clocks_["y"] < icao["y"] + icao["height"], f"the clocks went under the ICAO: {clocks_} {icao}"
        for clock in (zulu, local):
            assert clock["x"] >= icao["x"] + icao["width"], (clock, icao)
            assert clock["x"] + clock["width"] <= pane["x"] + pane["width"], (clock, pane)
        assert pane["height"] == pytest.approx(pane_before["height"], abs=0.5)


# -- the text glow ---------------------------------------------------------------------


def shadow(page, selector=".title-text"):
    return page.eval_on_selector(selector, "e => getComputedStyle(e).textShadow")


def test_the_text_glow_is_glow_text_alone(page):
    assert page.evaluate("document.documentElement.dataset.glow") is None, "the data-glow bridge is still there"
    default = shadow(page)
    assert "px" in default and default != "none"
    set_prefs(page, glow_map=0, glow_traffic=0)
    assert shadow(page) == default, "the map's or the traffic's glow moved the text's"
    set_prefs(page, glow_text=0)
    assert shadow(page) == "none"
    assert page.eval_on_selector(".screen", "e => getComputedStyle(e).boxShadow") == "none"
    set_prefs(page, glow_text=100)
    full = shadow(page)
    assert full not in ("none", default)
    blurs = lambda text: [float(n) for n in re.findall(r"([\d.]+)px", text)]  # noqa: E731
    assert max(blurs(full)) > max(blurs(default))


def as_shadow(page, selector, css):
    """`css` as the engine computes it for the element's text-shadow."""
    return page.eval_on_selector(
        selector,
        """(e, css) => { const before = e.style.textShadow; e.style.textShadow = css;
                         const text = getComputedStyle(e).textShadow; e.style.textShadow = before; return text; }""",
        css,
    )


# Phase F's steps, which glow_text's 33 and 75 are (phase G decision 15).
LOW = "0 0 7px currentColor"
FULL = "0 0 4px currentColor, 0 0 16px currentColor"


@pytest.mark.parametrize("selector", [".title-text", "#icao", "#zulu"])
def test_the_text_glow_at_33_and_75_is_phase_f_s_low_and_full(page, selector):
    assert shadow(page, selector) == as_shadow(page, selector, LOW), "the default, 33, is not LOW"
    set_prefs(page, glow_text=75)
    assert shadow(page, selector) == as_shadow(page, selector, FULL)
    set_prefs(page, glow_text=33)
    assert shadow(page, selector) == as_shadow(page, selector, LOW)


def test_the_text_glow_s_first_paint_is_low(page):
    """The stylesheet's own --glow, before main.js writes one, is LOW too."""
    first = page.eval_on_selector(
        "#icao",
        """e => { const root = document.documentElement.style, glow = root.getPropertyValue("--glow");
                  root.removeProperty("--glow"); const text = getComputedStyle(e).textShadow;
                  root.setProperty("--glow", glow); return text; }""",
    )
    assert first == as_shadow(page, "#icao", LOW)


def light(page, size):
    """How much light the page's glow paints around white text `size` px
    high: the sum of every channel of every pixel of a probe, the text on
    the wall with room for the widest glow around it, over everything else."""
    page.evaluate(
        """size => { const box = document.createElement("div"); box.id = "glow-probe";
                     box.style.cssText = "position: fixed; left: 0; top: 0; z-index: 99999; padding: 64px;"
                       + "background: var(--wall); color: var(--white); text-shadow: var(--glow);"
                       + `font: ${size}px/1 var(--font-display); letter-spacing: 0.12em;`;
                     box.textContent = "KPDX 1907Z"; document.body.append(box); }""",
        size,
    )
    png = page.locator("#glow-probe").screenshot(animations="disabled")
    page.evaluate("document.getElementById('glow-probe').remove()")
    at, packed, head = 8, b"", None
    while at < len(png):
        length, kind = struct.unpack(">I4s", png[at:at + 8])
        body = png[at + 8:at + 8 + length]
        if kind == b"IHDR":
            head = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            packed += body
        at += 12 + length
    width, height_, depth, colour = head
    assert depth == 8 and colour in (2, 6), head
    step = 3 if colour == 2 else 4
    data, stride = zlib.decompress(packed), width * step
    total, above = 0, bytearray(stride)
    for row in range(height_):
        kind, line = data[row * (stride + 1)], bytearray(data[row * (stride + 1) + 1:(row + 1) * (stride + 1)])
        for i in range(stride):  # undo the row's PNG filter
            left = line[i - step] if i >= step else 0
            up, corner = above[i], (above[i - step] if i >= step else 0)
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
        total += sum(line[i] for i in range(stride) if i % step < 3)
        above = line
    return total


@pytest.mark.parametrize("size", [64, 20])  # the ICAO's, a title's
def test_the_text_glow_brightens_as_it_rises(page, size):
    set_prefs(page, display="OFF")
    levels = [0, 10, 20, 33, 40, 50, 60, 75, 90, 100]
    seen = []
    for level in levels:
        set_prefs(page, glow_text=level)
        seen.append(light(page, size))
    assert all(a < b for a, b in zip(seen, seen[1:])), list(zip(levels, seen))


def lamp_blur(page):
    """The lit lamp's glow, in px of blur."""
    text = page.eval_on_selector(".lamp.on .lamp-light", "e => getComputedStyle(e).boxShadow")
    return 0.0 if text == "none" else [float(n) for n in re.findall(r"(-?[\d.]+)px", text)][2]


def test_the_lamps_glow_with_the_text(page):
    set_prefs(page, lamps=True)
    page.evaluate("document.querySelector('.lamp').classList.add('on')")
    assert lamp_blur(page) == 10
    set_prefs(page, glow_text=0)
    assert lamp_blur(page) == 0
