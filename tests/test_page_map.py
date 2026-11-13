"""The map lane's page tests (plan phase G, Tasks 10 and 12, and 4d): every
map layer styled by the `map` table, still labels that follow the zoom,
runways at their true width up close, the map's own glow; a click on a place
centres it, the focused aircraft is followed and has a data box beside it,
view moves ease by `view_ease` and the wheel turns at `zoom_speed`."""

from __future__ import annotations

import copy
import math
import re
import subprocess
from pathlib import Path

import pytest

from kcgx.prefs import DEFAULTS
from page_fixtures import *  # noqa: F403  (fixtures and helpers)

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parent.parent
FT_PER_NM = 6076.12

# The static layer as it was before Task 10 (the last commit of phase G's
# Phase 0), with its glow moved to the map's own number as 4d moves it and
# its ring numbers kept off the airport's name, bare too, as the owner has
# them since: the picture the default `map` table must reproduce. still.js is served with
# the draw.js and view.js of the same commit, under names of their own
# (`draw.before.js`, `view.before.js`) so that the rest of today's page
# keeps today's: a later change to either (Task 12 edits view.js) moves
# neither picture's reference. What is still shared is the rest of the
# page: theme.js (the palette and glowBlur), focus.js, which view.js
# imports, and radar/index.js, which calls the old still.js's init,
# loadMap and drawStatic. The test must be re-pinned to a later commit, or
# retired, when
# - a task means the default table to draw other pixels than these (5a,
#   the map's glow by colour, does: retire it there, or re-pin to 5a's
#   commit and compare later work with that);
# - index.js changes what it asks of still.js, so the old one no longer
#   draws (the test fails on a page error or an empty map, not a picture);
# - draw.js or view.js stop being what still.js imports.
BEFORE = "2bc8561"
RADAR_JS = "src/kcgx/web/static/js/radar"


def before(name):
    """`name` (still, draw or view) as it was at BEFORE."""
    try:
        return subprocess.run(
            ["git", "show", f"{BEFORE}:{RADAR_JS}/{name}.js"], cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        pytest.skip(f"no git history to take the picture from before Task 10: {error}")


def modules_before():
    """The old still.js, draw.js and view.js, by the path each is served at."""
    still = before("still")
    for name in ("draw", "view"):
        line = f'from "./{name}.js";'
        assert still.count(line) == 1, name
        still = still.replace(line, f'from "./{name}.before.js";')
    assert "glowBlur() * ratio" in still
    still = still.replace("glowBlur() * ratio", 'glowBlur("map") * ratio')
    # And a ring number gives way to the airport's name, bare too (the
    # owner's decision in phase G's Task 10 review), as today's does.
    keep_off = 'const keepOff = name && (radar.boxed("HOME") || radar.boxed("RINGS")) ? name.label : null;'
    assert still.count(keep_off) == 1
    still = still.replace(keep_off, "const keepOff = name ? name.label : null;")
    return {"still.js": still, "draw.before.js": before("draw"), "view.before.js": before("view")}


# -- helpers --------------------------------------------------------------------


def set_map(page, **rows):
    """Change cells of the `map` table, as its grid does: only those cells
    are sent, and the server merges them into the table."""
    page.evaluate("map => window.kcgx.send({t: 'prefs', map})", rows)
    expected = copy.deepcopy(DEFAULTS["map"])
    for row, cells in rows.items():
        expected[row].update(cells)
    page.wait_for_function(
        "map => JSON.stringify(window.kcgx.store.state.prefs.map) === JSON.stringify(map)", arg=expected,
    )


HIDDEN = {row: {"show": False} for row in DEFAULTS["map"]}

# The radar's shared state, for a test to look at the static layer itself.
GRAB = "() => { if (!window.still) window.kcgx.radar.hook((radar) => { window.still = radar; }); }"

# Wait until the static layer has drawn itself on in full (the coast, the
# lakes, rivers, borders and states draw on over DRAW_ON_MS, 2 s, from the
# map's arrival) with the fonts loaded. Its pixels are read only after
# this: read during the draw-on, they are of a part-drawn map.
DRAWN_ON = """async () => {
    const radar = window.still;
    const frame = () => new Promise(requestAnimationFrame);
    await document.fonts.ready;
    for (let tries = 0; tries < 600; tries += 1) {
        if (radar.map && performance.now() - radar.drawOnFrom > 2100 && !radar.staticDirty) return;
        await frame();
    }
    throw new Error("the static layer never finished drawing on");
}"""

# As DRAWN_ON, then draw it once more and return it as a PNG data URL.
STILL_PICTURE = f"""async () => {{
    const radar = window.still;
    const frame = () => new Promise(requestAnimationFrame);
    await ({DRAWN_ON})();
    radar.staticDirty = true;
    while (radar.staticDirty) await frame();
    return radar.still.toDataURL();
}}"""

# The share of pixels of two pictures (data URLs of the same size) that
# differ by more than `over` in any channel.
DIFFER = """async ([a, b, over]) => {
    const load = (url) => new Promise((done) => { const i = new Image(); i.onload = () => done(i); i.src = url; });
    const [ia, ib] = await Promise.all([load(a), load(b)]);
    const read = (image) => {
        const c = document.createElement("canvas");
        c.width = image.width; c.height = image.height;
        const ctx = c.getContext("2d");
        ctx.drawImage(image, 0, 0);
        return ctx.getImageData(0, 0, c.width, c.height).data;
    };
    const pa = read(ia), pb = read(ib);
    if (pa.length !== pb.length) throw new Error("the pictures differ in size");
    let differ = 0, lit = 0;
    for (let i = 0; i < pa.length; i += 4) {
        let d = 0;
        for (let k = 0; k < 4; k += 1) d = Math.max(d, Math.abs(pa[i + k] - pb[i + k]));
        if (d > over) differ += 1;
        if (pa[i + 3] || pb[i + 3]) lit += 1;
    }
    return { differ: differ / (pa.length / 4), lit: lit / (pa.length / 4) };
}"""


def still_picture(page):
    page.evaluate(GRAB)
    return page.evaluate(STILL_PICTURE)


def drawn_on(page):
    """Let the radar draw what was just set, then wait out the draw-on."""
    page.evaluate(GRAB)
    frames(page)
    radar_drawn(page)
    page.evaluate(DRAWN_ON)


def differ(page, a, b, over=0):
    return page.evaluate(DIFFER, [a, b, over])


# What the static layer inks: how many pixels have any alpha.
INKED = """() => { const c = window.still.still;
    const data = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let n = 0; for (let i = 3; i < data.length; i += 4) if (data[i]) n += 1; return n; }"""


def styles(page):
    """Each row's style as the radar draws it now: a setting just changed
    is drawn on the next frame."""
    frames(page)
    return radar_drawn(page)["styles"]


def set_view(page, nm, pan_x=0.0, pan_y=0.0):
    """Put the view at `nm` about (pan_x, pan_y) nm, as a wheel and a drag
    would, and wait until the radar has drawn it."""
    page.evaluate(GRAB)
    page.evaluate(
        """([nm, x, y]) => { const r = window.still;
            r.view.nm = nm; r.view.panX = x; r.view.panY = y; r.staticDirty = true; }""",
        [nm, pan_x, pan_y],
    )
    frames(page)
    return radar_drawn(page)


def label_px(page, base):
    """still.js's labelPx for the radar as it is now."""
    page.evaluate(GRAB)
    return page.evaluate(
        "base => import('/static/js/radar/still.js').then((still) => still.labelPx(base, window.still))", base,
    )


def expected_label(base, range_nm, view_nm, low=9, high=26):
    """Decision 13: the row's size at the range's view, times the zoom to
    the 0.35, held between the floor and the ceiling, or at the row's own
    size where that is outside them."""
    return min(max(base * (range_nm / view_nm) ** 0.35, min(low, base)), max(high, base))


# -- the default table is today's look ----------------------------------------


def test_at_the_default_table_the_static_layer_is_as_it_was(page, browser, server):
    """Pixel for pixel, within 0.1 %, the picture still.js drew before the
    table. The reference is drawn with the map's own glow (3.96 px, where
    phase F's LOW was 4, which alone moves 24 % of Chromium's pixels and 5 %
    of WebKit's). A pixel differs when a channel is off by more than 2 of
    255: Chromium anti-aliases a path a level or two differently once the
    pieces off the screen are left out of it (0.18 % of pixels, 0.05 % by
    more than 2); WebKit draws it the same."""
    wait_for_traffic(page)
    now = still_picture(page)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    try:
        before = context.new_page()
        def serve(source):
            return lambda route: route.fulfill(status=200, content_type="text/javascript", body=source)

        for path, source in modules_before().items():
            before.route(f"**/static/js/radar/{path}", serve(source))
        errors = []
        before.on("pageerror", lambda error: errors.append(str(error)))
        before.goto(server + "/")
        before.wait_for_selector(".feed.expanded")
        wait_for_traffic(before)
        then = still_picture(before)
        served = before.evaluate(
            "() => performance.getEntriesByType('resource').map((e) => e.name.split('/').pop())"
        )
        assert {"draw.before.js", "view.before.js"} <= set(served), "the old still.js is drawn with its own modules"
        assert errors == [], errors
    finally:
        context.close()
    result = differ(page, now, then, over=2)
    assert result["lit"] > 0.05, "the test wants a picture with a map on it"
    assert result["differ"] < 0.001, result


def test_the_debug_reports_every_rows_style_at_the_default(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    found = styles(page)
    assert set(found) == set(DEFAULTS["map"])
    assert found["COAST"] == {"show": True, "alpha": 1, "dash": [], "width": pytest.approx(1.8 * ratio)}
    # Each dashed layer's default is its old pattern, scaled with its width.
    assert found["AIRWAY"]["dash"] == [3 * ratio, 6 * ratio]
    assert found["COUNTRY"]["dash"] == [6 * ratio, 4 * ratio]
    assert found["CLASS_B"]["dash"] == [5 * ratio, 5 * ratio]
    assert found["CLASS_C"]["dash"] == [5 * ratio, 5 * ratio]
    assert found["CLASS_D"]["dash"] == [3 * ratio, 5 * ratio]
    assert found["CITIES"]["label"] == 13 * ratio
    assert found["HOME"]["label"] == 30 * ratio


# -- each row's cells ----------------------------------------------------------


def test_with_every_row_hidden_the_static_layer_is_empty_and_coast_alone_draws(page):
    wait_for_traffic(page)
    page.evaluate(GRAB)
    set_map(page, **HIDDEN)
    frames(page)
    debug = radar_drawn(page)
    assert page.evaluate(INKED) == 0
    assert debug["layers"]["coast"] == 0
    assert debug["placed"] == [] and debug["rings"] == []
    set_map(page, **{**HIDDEN, "COAST": {"show": True}})
    drawn_on(page)
    debug = radar_drawn(page)
    assert debug["layers"]["coast"] > 0
    assert page.evaluate(INKED) > 1000


def test_coast_hidden_leaves_no_coast(page):
    wait_for_traffic(page)
    frames(page)
    assert radar_drawn(page)["layers"]["coast"] > 0
    set_map(page, COAST={"show": False})
    frames(page)
    debug = radar_drawn(page)
    assert debug["layers"]["coast"] == 0
    assert debug["styles"]["COAST"]["show"] is False


@pytest.mark.parametrize(
    ("row", "cells", "expected"),
    [
        ("COAST", {"alpha": 40}, {"alpha": 0.4}),
        ("COAST", {"line": "DASH", "width": 30}, {"dash": [15, 15], "width": 3}),
        ("AIRWAY", {"line": "DOT", "width": 20}, {"dash": [2, 6], "width": 2}),
        ("CLASS_B", {"line": "SOLID"}, {"dash": []}),
        ("CLASS_D", {"line": "DASH", "width": 20}, {"dash": [10, 10]}),
        ("CLASS_D", {"width": 20}, {"dash": [6, 10]}),  # its own dots, twice the size
        ("AIRWAY", {"width": 24}, {"dash": [6, 12]}),
        ("RINGS", {"width": 25, "alpha": 70}, {"width": 2.5, "alpha": 0.7}),
        ("RUNWAYS", {"width": 40}, {"width": 4}),
    ],
)
def test_alpha_line_and_width_change_what_a_layer_draws_with(page, row, cells, expected):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    set_map(page, **{row: cells})
    frames(page)
    radar_drawn(page)
    found = styles(page)[row]
    for key, value in expected.items():
        want = value if key == "alpha" else ([v * ratio for v in value] if isinstance(value, list) else value * ratio)
        assert found[key] == pytest.approx(want), (key, found)
    # and the others are as they were
    assert styles(page)["LAKE"] == {"show": True, "alpha": 0.75, "dash": [], "width": pytest.approx(1.2 * ratio)}


def test_a_lighter_layer_draws_brighter(page):
    """Alpha is the strength of the pixels, not only of the report: the
    picture with the coast alone at 100 is brighter than at 30."""
    wait_for_traffic(page)
    page.evaluate(GRAB)
    lone = {**HIDDEN, "COAST": {"show": True, "alpha": 100}}
    set_map(page, **lone)
    drawn_on(page)  # the coast draws on: the sums are of the whole of it
    total = """() => { const c = window.still.still;
        const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
        let n = 0; for (let i = 3; i < d.length; i += 4) n += d[i]; return n; }"""
    bright = page.evaluate(total)
    set_map(page, **{**lone, "COAST": {"show": True, "alpha": 30}})
    drawn_on(page)
    assert 0 < page.evaluate(total) < 0.5 * bright


def test_a_places_label_size_is_its_rows_label(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    cities = lambda debug: [p for p in debug["placed"] if p["key"].startswith("city:")]  # noqa: E731
    frames(page)
    assert {p["h"] for p in cities(radar_drawn(page))} == {(13 + 4) * ratio}
    set_map(page, CITIES={"label": 20})
    frames(page)
    debug = radar_drawn(page)
    assert debug["styles"]["CITIES"]["label"] == 20 * ratio
    assert cities(debug) and {p["h"] for p in cities(debug)} == {(20 + 4) * ratio}
    # the other kinds keep theirs
    assert {p["h"] for p in debug["placed"] if p["key"].startswith("navaid:")} == {(13 + 4) * ratio}


# -- labels follow the zoom ----------------------------------------------------


def test_at_the_ranges_view_a_label_is_its_rows_size(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    assert radar_drawn(page)["view"]["nm"] == 40
    assert styles(page)["CITIES"]["label"] == 13 * ratio
    assert label_px(page, 13) == 13


@pytest.mark.parametrize("base", [13, 20])
def test_zoomed_in_4x_a_label_grows_by_4_to_the_0_35_up_to_label_max(page, base):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    set_map(page, CITIES={"label": base})
    set_view(page, 10)
    want = min(base * 4 ** 0.35, 26)
    assert label_px(page, base) == pytest.approx(want)
    assert styles(page)["CITIES"]["label"] == pytest.approx(want * ratio)
    assert (base == 20) == (want == 26), "one case grows freely, the other reaches the ceiling"


def test_zoomed_out_to_160_nm_a_label_is_no_less_than_label_min(page):
    wait_for_traffic(page)
    page.mouse.move(*centre_of_the_radar(page))
    for _ in range(4):
        turn_wheel(page, 600)
    assert radar_drawn(page)["view"]["nm"] == 160
    assert 13 * 0.25 ** 0.35 < 9, "the test wants a size that would fall under the floor"
    assert label_px(page, 13) == 9
    set_prefs(page, label_min=6)
    assert label_px(page, 13) == pytest.approx(13 * 0.25 ** 0.35)


def test_the_floor_and_ceiling_are_settings(page):
    wait_for_traffic(page)
    set_view(page, 10)
    set_prefs(page, label_max=18)
    assert label_px(page, 13) == 18
    set_prefs(page, label_max=48)
    assert label_px(page, 13) == pytest.approx(13 * 4 ** 0.35)


def test_a_size_set_outside_the_floor_and_ceiling_holds_at_the_ranges_view(page):
    """The home airport's name is 30 px by default, over the 26 px ceiling:
    at the range's view it is still 30, and zooming never makes it larger."""
    wait_for_traffic(page)
    assert label_px(page, 30) == 30
    set_view(page, 10)
    assert label_px(page, 30) == 30
    set_view(page, 160)
    assert label_px(page, 30) == pytest.approx(30 * 0.25 ** 0.35)
    assert label_px(page, 30) == pytest.approx(expected_label(30, 40, 160))


def test_tags_follow_the_zoom_from_the_tag_size(page):
    """labelPx is TRAFFIC's for the tags (Task 11): the same rule from tag_px."""
    wait_for_traffic(page)
    tag_px = DEFAULTS["tag_px"]
    assert label_px(page, tag_px) == tag_px
    set_view(page, 10)
    assert label_px(page, tag_px) == pytest.approx(min(tag_px * 4 ** 0.35, 26))


def test_every_still_labels_size_follows_the_zoom(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    set_view(page, 20)
    found = styles(page)
    for row in ("RINGS", "AIRPORTS", "NAVAIDS", "CITIES", "PEAKS", "STATE_NAMES", "HOME"):
        base = DEFAULTS["map"][row]["label"]
        assert found[row]["label"] == pytest.approx(expected_label(base, 40, 20) * ratio), row


# -- runways up close ----------------------------------------------------------


# The wheel's quarter mile: test_page.py's test_the_wheel_zooms_in_to_a_quarter_mile_and_no_further.


def test_at_a_quarter_mile_the_rings_are_a_twentieth_apart(page):
    """At 0.1 nm apart only two and a half rings would lie between the
    airport and the nearer edge; at 0.05, five do."""
    wait_for_traffic(page)
    debug = set_view(page, 0.25)
    shown = [ring["text"] for ring in debug["rings"]]
    assert shown[:2] == ["0.05", "0.1"]
    within = [ring for ring in debug["rings"] if ring["nm"] <= 0.25 + 1e-9]
    assert 3 <= len(within) <= 5, shown
    assert [ring["nm"] for ring in within] == pytest.approx([0.05 * n for n in range(1, len(within) + 1)])


def test_at_half_a_mile_the_rings_are_a_tenth_apart(page):
    wait_for_traffic(page)
    shown = [ring["text"] for ring in set_view(page, 0.5)["rings"]]
    assert shown[:2] == ["0.1", "0.2"]


# Along the airway that runs longest across the screen, sampled a pixel
# apart: how many samples the static layer has lit, and how many there are.
ALONG_AN_AIRWAY = """() => {
    const r = window.still, c = r.still, { width, height } = c;
    const ratio = r.size().ratio;
    const s = (Math.min(width, height) / 2 - 18 * ratio) / r.view.nm;
    const at = ([x, y]) => [width / 2 + (x - r.view.panX) * s, height / 2 + (y - r.view.panY) * s];
    const alpha = c.getContext("2d").getImageData(0, 0, width, height).data;
    let best = [0, 0];
    for (const line of r.map.lines.airway) {
        for (let i = 2; i < line.length; i += 2) {
            const a = at([line[i - 2], line[i - 1]]), b = at([line[i], line[i + 1]]);
            const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
            let lit = 0, total = 0;
            for (let d = 0; d < length; d += 1) {
                const x = Math.round(a[0] + ((b[0] - a[0]) * d) / length);
                const y = Math.round(a[1] + ((b[1] - a[1]) * d) / length);
                if (x < 10 || y < 10 || x > width - 10 || y > height - 10) continue;
                total += 1;
                if (alpha[(y * width + x) * 4 + 3]) lit += 1;
            }
            if (total > best[1]) best = [lit, total];
        }
    }
    return best;
}"""


@pytest.mark.parametrize("nm", [40, 0.5, 0.25])
def test_an_airway_is_dashed_far_out_and_up_close(page, nm):
    """Up close an airway runs many thousands of px off the screen, and a
    path that long was drawn solid: only what reaches the screen is drawn.
    At 0.25 nm a single segment of a piece runs tens of thousands of px, so
    each segment is cut to the screen, not only each piece left out."""
    wait_for_traffic(page)
    page.evaluate(GRAB)
    set_prefs(page, glow_map=0)
    set_map(page, **{**HIDDEN, "AIRWAY": {"show": True}})
    set_view(page, nm)
    lit, total = page.evaluate(ALONG_AN_AIRWAY)
    assert total > 200, "the test wants an airway across the screen"
    assert 0.25 < lit / total < 0.75, (lit, total)


# -- the rings' line -----------------------------------------------------------


def test_the_rings_line_is_drawn(page):
    """RINGS.line dashes the rings; SOLID draws them as they were drawn."""
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    set_prefs(page, glow_map=0)  # a glow inks about the gaps as well
    lone = {**HIDDEN, "RINGS": {"show": True}}
    set_map(page, **lone)
    solid = still_picture(page)
    solid_inked = page.evaluate(INKED)
    set_map(page, **{**lone, "RINGS": {"show": True, "line": "DASH"}})
    assert styles(page)["RINGS"]["dash"] == [5 * ratio, 5 * ratio]
    dashed = still_picture(page)
    assert differ(page, solid, dashed)["differ"] > 0.002
    assert page.evaluate(INKED) < 0.8 * solid_inked, "a dashed ring inks less of itself"
    set_map(page, **{**lone, "RINGS": {"show": True, "line": "SOLID"}})
    assert still_picture(page) == solid


# -- ring numbers and the home name (the owner's decision) --------------------


def meets(a, b):
    """draw.js's meets: two rectangles meet, touching is meeting."""
    return not (
        a["x"] + a["w"] < b["x"] or b["x"] + b["w"] < a["x"] or a["y"] + a["h"] < b["y"] or b["y"] + b["h"] < a["y"]
    )


def numbers_and_name(debug):
    home = next(p for p in debug["placed"] if p["key"] == "home")
    return {ring["text"]: ring["label"] for ring in debug["rings"]}, home


def test_up_close_no_bare_ring_number_crosses_the_home_name(page):
    """Phase F let a bare ring number and the airport's name cross; the
    owner has the number give way to the name, boxed or not."""
    wait_for_traffic(page)
    assert not DEFAULTS["box_items"]
    numbers, home = numbers_and_name(set_view(page, 0.5))
    assert [text for text, label in numbers.items() if label], "the test wants ring numbers drawn"
    assert not [text for text, label in numbers.items() if label and meets(label, home)]


def test_at_the_ranges_view_only_a_ring_number_on_the_home_name_is_left_off(page):
    """With the name hidden, the numbers go where they always went; shown,
    those that would meet it are left off and the rest are just as they were."""
    wait_for_traffic(page)
    set_map(page, HOME={"show": False})
    frames(page)
    free = {ring["text"]: ring["label"] for ring in radar_drawn(page)["rings"]}
    set_map(page, HOME={"show": True})
    frames(page)
    numbers, home = numbers_and_name(radar_drawn(page))
    assert list(numbers) == list(free), "every ring is still drawn"
    crossing = {text for text, label in free.items() if label and meets(label, home)}
    assert numbers == {text: None if text in crossing else label for text, label in free.items()}


def runways_drawn(page):
    return styles(page)["RUNWAYS"]["drawn"]


def across(runway, width, height, margin=40):
    """For a runway on screen, a function from an offset in px to the canvas
    point that far to one side of a point on its centre line, the point
    being one well inside the screen; None when no such point is."""
    (ax, ay), (bx, by) = runway["ends"]
    length = math.hypot(bx - ax, by - ay)
    nx, ny = -(by - ay) / length, (bx - ax) / length
    for t in (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8):
        x, y = ax + (bx - ax) * t, ay + (by - ay) * t
        if margin < x < width - margin and margin < y < height - margin:
            return lambda offset, x=x, y=y: (x + nx * offset, y + ny * offset)
    return None


def test_at_the_ranges_view_a_runway_is_a_line_of_the_rows_width(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    drawn = runways_drawn(page)
    assert len(drawn) == 3
    assert all(r["px"] == pytest.approx(1.6 * ratio) and not r["filled"] for r in drawn)


def test_at_half_a_mile_a_runway_is_filled_and_150_ft_wide(page):
    wait_for_traffic(page)
    set_prefs(page, glow_map=0)
    debug = set_view(page, 0.5)
    s = fit(page) / 0.5
    drawn = runways_drawn(page)
    assert drawn and all(r["filled"] and r["ft"] == 150 for r in drawn)
    assert all(r["px"] == pytest.approx(150 / FT_PER_NM * s) for r in drawn)
    assert drawn[0]["px"] > 10, "the test wants a runway many pixels wide"
    # The layer is lit across the runway's width and dark beyond: filled, not outlined.
    width, height = canvas_size(page)
    page.evaluate(GRAB)
    pixel_at = """([x, y]) => [...window.still.still.getContext("2d").getImageData(Math.round(x), Math.round(y), 1, 1).data]"""
    on = [(r, at) for r in drawn if (at := across(r, width, height))]
    assert on, debug["view"]
    for r, at in on:
        for offset in (0, r["px"] / 4, -r["px"] / 4, r["px"] / 2 - 3, -(r["px"] / 2 - 3)):
            assert page.evaluate(pixel_at, at(offset))[3] > 200, (r, offset)
        for offset in (r["px"] / 2 + 6, -(r["px"] / 2 + 6)):
            assert page.evaluate(pixel_at, at(offset))[3] < 60, (r, offset)


def test_a_runway_is_never_narrower_than_the_rows_width(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    set_map(page, RUNWAYS={"width": 80})
    set_view(page, 2.5)
    s = fit(page) / 2.5
    assert 150 / FT_PER_NM * s < 8 * ratio, "the test wants a view where 150 ft is under 8 px"
    assert all(r["px"] == pytest.approx(8 * ratio) and not r["filled"] for r in runways_drawn(page))
    set_view(page, 0.5)
    assert all(r["px"] == pytest.approx(max(8 * ratio, 150 / FT_PER_NM * fit(page) / 0.5)) for r in runways_drawn(page))


def test_a_runways_width_from_the_map_is_drawn_and_a_map_without_one_still_draws(page):
    """The committed map has no widths yet: give the first runway one."""
    def widen(route):
        geo = route.fetch().json()
        first, *rest = geo["runways"]
        route.fulfill(json={**geo, "runways": [[*first[:4], 300], *rest]})

    page.route("**/api/geo*", widen)
    page.reload()
    page.wait_for_selector(".feed.expanded")
    wait_for_traffic(page)
    set_view(page, 0.5)
    s = fit(page) / 0.5
    by_ft = sorted(runways_drawn(page), key=lambda r: r["ft"])
    assert [r["ft"] for r in by_ft] == [150, 150, 300]
    assert by_ft[-1]["px"] == pytest.approx(300 / FT_PER_NM * s)
    assert by_ft[0]["px"] == pytest.approx(150 / FT_PER_NM * s)


# -- the map's glow (4d) -------------------------------------------------------


def test_the_maps_glow_is_its_own_number(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    frames(page)
    assert radar_debug(page)["blur_map"] == pytest.approx(3.96 * ratio)
    set_prefs(page, glow_map=50, glow_traffic=0, glow_text=0)
    frames(page)
    assert radar_debug(page)["blur_map"] == pytest.approx(6 * ratio)
    set_prefs(page, glow_map=0, glow_traffic=100, glow_text=100)
    frames(page)
    assert radar_debug(page)["blur_map"] == 0


def test_with_no_map_glow_the_static_layer_is_sharper(page):
    wait_for_traffic(page)
    glowing = still_picture(page)
    set_prefs(page, glow_map=0)
    sharp = still_picture(page)
    set_prefs(page, glow_map=0, glow_traffic=100, glow_text=100)
    assert still_picture(page) == sharp, "only the map's number reaches the static layer"
    assert differ(page, glowing, sharp)["differ"] > 0.01


# -- Task 12: view moves, following, places, the data box ---------------------

# Decision 21: how long a view move takes, by prefs.view_ease.
EASE_MS = {"OFF": 0, "QUICK": 250, "SMOOTH": 600}
REACH = 9  # px: the chevron reaches this far from its point, whichever way it points
GAP = 12  # px between the data box and the chevron


def view_of(page):
    return radar_debug(page)["view"]


def hit_of(page, hex_):
    return next(h for h in radar_debug(page)["hits"] if h["hex"] == hex_)


def from_centre(page, hex_):
    """How far, in canvas px, the aircraft was drawn from the radar's centre."""
    width, height = canvas_size(page)
    hit = hit_of(page, hex_)
    return math.hypot(hit["x"] - width / 2, hit["y"] - height / 2)


# Until the view is at `nm` and the aircraft drawn within `px` canvas px of the centre.
FOLLOWED = """([hex, nm, px]) => { const d = window.kcgx.radar.debug(), c = document.getElementById("radar");
    const hit = d.hits.find(h => h.hex === hex);
    return hit && d.view.nm === nm && Math.hypot(hit.x - c.width / 2, hit.y - c.height / 2) <= px; }"""


def wait_followed(page, hex_, nm=10, px=2):
    page.wait_for_function(FOLLOWED, arg=[hex_, nm, px * page.evaluate("devicePixelRatio")])


def focus_set(page, hex_):
    """Focus (or, with None, unfocus) as the page's own focus.js does."""
    page.evaluate("hex => import('/static/js/focus.js').then(m => m.focus.set(hex))", hex_)


def click_row(page, hex_):
    page.click(f'#tracks-body tr[data-hex="{hex_}"] .callsign')


def nothing_to_hit(page):
    """No places on the map, so a click away from the aircraft is on nothing."""
    set_map(page, **{row: {"show": False} for row in ("HOME", "AIRPORTS", "NAVAIDS", "CITIES", "PEAKS", "STATE_NAMES")})
    frames(page)


def a_city(page):
    """A city on screen with its label placed, well away from the centre and
    from the rest of the map's labels and symbols: its placed entry."""
    width, height = canvas_size(page)
    ratio = page.evaluate("devicePixelRatio")
    debug = radar_drawn(page)
    for city in debug["placed"]:
        if not city["key"].startswith("city:"):
            continue
        x, y = city["point"]
        if not (80 * ratio < x < width - 300 * ratio and 80 * ratio < y < height - 80 * ratio):
            continue
        if math.hypot(x - width / 2, y - height / 2) < 120 * ratio:
            continue
        others = [p for p in debug["placed"] if p is not city]
        if any(p["x"] <= x <= p["x"] + p["w"] and p["y"] <= y <= p["y"] + p["h"] for p in others):
            continue
        if any(m["key"] != city["key"] and math.hypot(m["point"][0] - x, m["point"][1] - y) < 30 * ratio
               for m in debug["marks"]):
            continue
        return city
    raise AssertionError("the test wants a city clear of the rest of the map")


# From here on, `window.views` is the view each frame drew.
RECORD_VIEWS = """() => { window.views = [];
    window.kcgx.radar.hook((radar) => ({ post() { window.views.push({ ...radar.shown }); } })); }"""


def record_views(page):
    page.evaluate(RECORD_VIEWS)


def mark_of(page, key):
    return next(m for m in radar_drawn(page)["marks"] if m["key"] == key)


@pytest.mark.parametrize("on", ["symbol", "label"])
def test_clicking_a_city_eases_it_to_the_centre_and_keeps_the_zoom(page, on):
    wait_for_traffic(page)
    hold_traffic(page)  # nothing in the way
    set_prefs(page, view_ease="SMOOTH")
    frames(page)
    city = a_city(page)
    start = view_of(page)
    where = city["point"] if on == "symbol" else (city["x"] + city["w"] - 3, city["y"] + city["h"] / 2)
    page.mouse.click(*on_screen(page, *where))
    frames(page, 4)
    midway = view_of(page)
    assert midway["nm"] == start["nm"]
    assert (midway["panX"], midway["panY"]) != (start["panX"], start["panY"]), "it has begun to move"
    assert (midway["panX"], midway["panY"]) != tuple(city["xy"]), "and eases, rather than jumps"
    page.wait_for_function(
        "xy => { const v = window.kcgx.radar.debug().view; return v.panX === xy[0] && v.panY === xy[1]; }",
        arg=city["xy"],
    )
    assert view_of(page)["nm"] == start["nm"]
    frames(page)
    width, height = canvas_size(page)
    x, y = mark_of(page, city["key"])["point"]
    ratio = page.evaluate("devicePixelRatio")
    assert abs(x - width / 2) <= ratio and abs(y - height / 2) <= ratio


def test_with_view_moves_off_a_click_centres_a_city_in_one_frame(page):
    wait_for_traffic(page)
    hold_traffic(page)
    set_prefs(page, view_ease="OFF")
    frames(page)
    city = a_city(page)
    nm = view_of(page)["nm"]
    page.mouse.click(*on_screen(page, *city["point"]))
    frames(page, 1)
    assert view_of(page) == {"nm": nm, "panX": city["xy"][0], "panY": city["xy"][1]}


# The ms from a click on the radar to the frame that finished the view's
# move to `xy`: the first frame whose view is there.
MOVE_TIME = """async (xy) => {
    const radar = window.kcgx.radar, frame = () => new Promise(requestAnimationFrame);
    while (window.upAt === undefined) await frame();
    for (let tries = 0; tries < 600; tries += 1) {
        const v = radar.debug().shown;
        if (v && v.panX === xy[0] && v.panY === xy[1]) return performance.now() - window.upAt;
        await frame();
    }
    throw new Error("the view never got there");
}"""


@pytest.mark.parametrize("ease", ["QUICK", "SMOOTH"])
def test_a_view_move_takes_its_settings_time(page, ease):
    wait_for_traffic(page)
    hold_traffic(page)
    set_prefs(page, view_ease=ease)
    frames(page)
    city = a_city(page)
    page.evaluate(
        """() => document.getElementById("radar").addEventListener(
               "pointerup", () => { window.upAt = performance.now(); }, { once: true })"""
    )
    page.mouse.click(*on_screen(page, *city["point"]))
    took = page.evaluate(MOVE_TIME, city["xy"])
    assert EASE_MS[ease] - 20 <= took <= EASE_MS[ease] + 400


def test_a_wheel_during_a_view_move_ends_it(page):
    wait_for_traffic(page)
    hold_traffic(page)
    set_prefs(page, view_ease="SMOOTH")
    frames(page)
    city = a_city(page)
    page.mouse.click(*on_screen(page, *city["point"]))
    frames(page, 3)
    turn_wheel(page, -100)
    stopped = view_of(page)
    page.wait_for_timeout(800)
    assert view_of(page) == stopped
    assert (stopped["panX"], stopped["panY"]) != tuple(city["xy"])


def test_the_home_ring_and_the_home_name_are_places_too(page):
    """(State names are placed as the rest are; the test map has none.)"""
    wait_for_traffic(page)
    hold_traffic(page)
    set_prefs(page, view_ease="OFF")
    set_view(page, 40, 15, -10)
    home = mark_of(page, "home")
    assert home["xy"] == [0, 0]
    page.mouse.click(*on_screen(page, *home["point"]))
    frames(page, 1)
    assert view_of(page) == {"nm": 40, "panX": 0, "panY": 0}
    name = next(p for p in set_view(page, 40, 15, -10)["placed"] if p["key"] == "home")
    page.mouse.click(*on_screen(page, name["x"] + name["w"] - 3, name["y"] + name["h"] / 2))
    frames(page, 1)
    assert view_of(page) == {"nm": 40, "panX": 0, "panY": 0}


def test_a_click_on_nothing_leaves_the_view(page):
    wait_for_traffic(page)
    hold_traffic(page)
    nothing_to_hit(page)
    set_prefs(page, view_ease="OFF")
    before = view_of(page)
    page.mouse.click(*on_screen(page, 200, 200))
    frames(page)
    assert view_of(page) == before


# -- following -----------------------------------------------------------------

MOVING = [plane("a1", -12, 8, gs=360, trk=90), plane("a2", 15, -10, gs=200, trk=180)]


def test_focusing_on_the_radar_eases_to_the_follow_radius_on_it(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    assert radar_debug(page)["following"] is False
    hit = hit_of(page, "a1")
    record_views(page)
    page.mouse.click(*on_screen(page, hit["x"], hit["y"]))
    page.wait_for_selector('#tracks-body tr.focused[data-hex="a1"]')
    wait_followed(page, "a1")
    assert radar_debug(page)["following"] is True
    assert any(10 < v["nm"] < 40 for v in page.evaluate("window.views")), "it eases there"


def test_focusing_from_the_table_follows_at_the_set_radius(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    set_prefs(page, follow_nm=5)
    click_row(page, "a2")
    wait_followed(page, "a2", nm=5)


def test_after_a_poll_and_two_seconds_it_is_still_at_the_centre(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    click_row(page, "a1")
    wait_followed(page, "a1")
    # The next poll has it half a mile on, and further than reckoning had it.
    hold_traffic(page, plane("a1", -11, 8, gs=360, trk=90), MOVING[1])
    page.wait_for_timeout(2000)
    frames(page)
    assert from_centre(page, "a1") <= 2 * page.evaluate("devicePixelRatio")
    assert view_of(page)["nm"] == 10


def test_a_drag_ends_following_and_keeps_the_focus(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    nothing_to_hit(page)
    click_row(page, "a1")
    wait_followed(page, "a1")
    pan(page, *on_screen(page, 200, 200))
    assert radar_debug(page)["following"] is False
    dragged = view_of(page)
    page.wait_for_timeout(500)
    frames(page)
    assert view_of(page) == dragged, "the view stays where the drag left it"
    assert page.locator('#tracks-body tr.focused[data-hex="a1"]').count() == 1


def test_unfocusing_eases_back_to_the_view_before_the_focus(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    before = set_view(page, 25, 3, -4)["view"]
    click_row(page, "a1")
    wait_followed(page, "a1")
    record_views(page)
    click_row(page, "a1")
    page.wait_for_selector("#tracks-body tr.focused", state="detached")
    page.wait_for_function(
        "v => JSON.stringify(window.kcgx.radar.debug().view) === JSON.stringify(v)", arg=before,
    )
    assert radar_debug(page)["following"] is False
    assert any(10 < v["nm"] < 25 for v in page.evaluate("window.views")), "it eases back"


def test_focusing_another_follows_it_and_unfocusing_still_goes_back_to_before_the_first(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    set_prefs(page, view_ease="OFF")
    before = view_of(page)
    click_row(page, "a1")
    wait_followed(page, "a1")
    click_row(page, "a2")
    wait_followed(page, "a2")
    focus_set(page, None)
    frames(page, 1)
    assert view_of(page) == before


def test_a_double_click_recentres_on_the_airport_and_ends_following(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    nothing_to_hit(page)
    click_row(page, "a1")
    wait_followed(page, "a1")
    page.mouse.dblclick(*on_screen(page, 200, 200))
    assert view_of(page) == {"nm": 40, "panX": 0, "panY": 0}
    assert radar_debug(page)["following"] is False
    page.wait_for_timeout(500)
    assert view_of(page) == {"nm": 40, "panX": 0, "panY": 0}
    assert page.locator('#tracks-body tr.focused[data-hex="a1"]').count() == 1
    # And, the view chosen since, unfocusing leaves it.
    focus_set(page, None)
    frames(page, 3)
    assert view_of(page) == {"nm": 40, "panX": 0, "panY": 0}


def test_the_wheel_while_following_zooms_about_the_aircraft(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    click_row(page, "a1")
    wait_followed(page, "a1")
    page.mouse.move(*on_screen(page, 200, 200))
    turn_wheel(page, -200)
    assert view_of(page)["nm"] < 10
    assert radar_debug(page)["following"] is True
    page.wait_for_timeout(300)
    frames(page)
    assert from_centre(page, "a1") <= 2 * page.evaluate("devicePixelRatio")


# -- the wheel's rate (4d) -----------------------------------------------------


def wheel_step(page, speed):
    """How many times closer one wheel step at the centre takes the view."""
    set_prefs(page, zoom_speed=speed)
    set_view(page, 40)
    page.mouse.move(*centre_of_the_radar(page))
    turn_wheel(page, -100)
    return 40 / view_of(page)["nm"]


def test_zoom_speed_scales_the_wheels_rate(page):
    wait_for_traffic(page)
    hold_traffic(page)
    nothing_to_hit(page)
    at_100 = wheel_step(page, 100)
    assert at_100 > 1.05
    assert math.log(wheel_step(page, 200)) == pytest.approx(2 * math.log(at_100))
    assert math.log(wheel_step(page, 25)) == pytest.approx(0.25 * math.log(at_100))


# -- which aircraft a click is on, as the tags are drawn -------------------------

# As the traffic's tags layer says it laid the tags (radar.tagOrder, the one
# on top last), every frame from here on. On a branch without that layer the
# radar has no tagOrder, and this gives it one.
LAY_TAGS = """order => {
    if (window.unlay) window.unlay();
    window.unlay = window.kcgx.radar.hook((radar) => ({ post() {
        if (!radar.tagOrder) radar.tagOrder = [];
        radar.tagOrder.splice(0, radar.tagOrder.length, ...order);
    } }));
}"""


def lay_tags(page, order):
    page.evaluate(LAY_TAGS, order)
    frames(page)


def per_nm(page):
    ring = radar_drawn(page)["rings"][0]
    return ring["r"] / ring["nm"]


def clicked(page, x, y):
    """The aircraft a click at this canvas point focuses, focus then cleared."""
    page.mouse.click(*on_screen(page, x, y))
    frames(page, 1)
    hex_ = page.evaluate("import('/static/js/focus.js').then(m => m.focus.hex)")
    focus_set(page, None)
    frames(page, 2)
    return hex_


def test_tags_are_tried_top_first_in_the_order_they_were_laid(page):
    wait_for_traffic(page)
    set_prefs(page, view_ease="OFF")
    ratio = page.evaluate("devicePixelRatio")
    k = per_nm(page)
    # a2 12 px under a1: their tags overlap in a band 8 px high.
    hold_traffic(page, plane("a1", -10, 5), plane("a2", -10, 5 - 12 * ratio / k))
    one, two = hit_of(page, "a1"), hit_of(page, "a2")
    x, y = one["x"] + 40 * ratio, one["y"] - 10 * ratio
    for hit in (one, two):
        tag = hit["tag"]
        assert tag["x"] <= x <= tag["x"] + tag["w"] and tag["y"] <= y <= tag["y"] + tag["h"]
        assert math.hypot(hit["x"] - x, hit["y"] - y) > 20 * ratio
    lay_tags(page, ["a1", "a2"])
    assert clicked(page, x, y) == "a2"
    lay_tags(page, ["a2", "a1"])
    assert clicked(page, x, y) == "a1"
    lay_tags(page, [])  # none said: the frame's order
    assert clicked(page, x, y) == "a1"


@pytest.mark.parametrize(("fill", "expected"), [(100, "a1"), (DEFAULTS["box_fill"], "a1"), (0, "a2")])
def test_a_filled_box_on_the_tags_layer_covers_the_chevron_under_it(page, fill, expected):
    """Fully exercised once the traffic lays its tags over the aircraft
    (Task 11): until then the test lays them, as that layer will say."""
    wait_for_traffic(page)
    set_prefs(page, view_ease="OFF", box_items=["AIRCRAFT"], box_pad=12, box_fill=fill)
    ratio = page.evaluate("devicePixelRatio")
    k = per_nm(page)
    hold_traffic(page, plane("a1", -10, 5))
    first = hit_of(page, "a1")
    box = first["tag"]["box"]
    x, y = box["x"] + box["w"] - 8 * ratio, box["y"] + box["h"] / 2
    hold_traffic(page, plane("a1", -10, 5), plane("a2", -10 + (x - first["x"]) / k, 5 - (y - first["y"]) / k))
    second = hit_of(page, "a2")
    assert math.hypot(second["x"] - first["x"], second["y"] - first["y"]) > 30 * ratio
    box = hit_of(page, "a1")["tag"]["box"]
    assert box["x"] < second["x"] < box["x"] + box["w"] and box["y"] < second["y"] < box["y"] + box["h"]
    lay_tags(page, ["a2", "a1"])
    assert clicked(page, second["x"], second["y"]) == expected


# -- the data box --------------------------------------------------------------

# Each line of the data box, [name, value], and what the table's own column
# functions say of the focused aircraft for the visible columns.
INFO = """async () => {
    const { COLUMN } = await import('/static/js/columns.js');
    const { focus } = await import('/static/js/focus.js');
    const { prefs, radar } = window.kcgx.store.state;
    const ac = radar.ac.find(a => a.hex === focus.hex);
    const box = document.getElementById("ac-info");
    return {
        shown: [...box.querySelectorAll("dt")].map(dt => [dt.textContent, dt.nextElementSibling.textContent]),
        table: prefs.track_cols.map(name => [COLUMN[name].title, COLUMN[name].text(ac)]),
    };
}"""


def info_box(page):
    return page.locator("#ac-info")


def info_place(page, hex_):
    """The data box's page rectangle and the chevron's page point, read
    together after a frame."""
    frames(page, 1)
    rect = box_of(page, "#ac-info")
    hit = hit_of(page, hex_)
    return rect, on_screen(page, hit["x"], hit["y"])


def test_the_data_box_shows_the_tables_visible_columns_in_order(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    assert not info_box(page).is_visible()
    click_row(page, "a1")
    info_box(page).wait_for(state="visible")
    lines = page.evaluate(INFO)
    assert lines["shown"] == lines["table"]
    assert [name for name, _ in lines["shown"]] == ["CALLSIGN", "TYPE", "ALT FT", "GS KT", "TRK", "DIST NM", "SQWK"]
    assert ["CALLSIGN", "A1"] in lines["shown"]
    # Each name and its value on one line.
    tops = page.eval_on_selector_all("#ac-info > div", "ds => ds.map(d => [d.children[0].offsetTop, d.children[1].offsetTop])")
    assert len(tops) == 7 and all(a == b for a, b in tops) and len({a for a, _ in tops}) == 7
    set_prefs(page, track_cols=["ALT", "SQWK", "HEX"])  # a subset is kept in the schema's order
    frames(page)
    lines = page.evaluate(INFO)
    assert lines["shown"] == lines["table"] == [["ALT FT", "12000"], ["SQWK", "4512"], ["HEX", "A1"]]


def test_the_data_box_sits_left_of_the_chevron_and_follows_it(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    click_row(page, "a1")
    wait_followed(page, "a1")
    rect, (x, y) = info_place(page, "a1")
    assert rect["x"] + rect["width"] == pytest.approx(x - REACH - GAP, abs=1)
    assert rect["y"] + rect["height"] / 2 == pytest.approx(y, abs=1)
    # Not followed, it still keeps beside the aircraft as it moves.
    nothing_to_hit(page)
    pan(page, *on_screen(page, 200, 200))
    first, at = info_place(page, "a1")
    page.wait_for_timeout(1000)
    later, there = info_place(page, "a1")
    assert there[0] - at[0] > 1, "the aircraft moved east"
    for rect, (x, y) in ((first, at), (later, there)):
        assert rect["x"] + rect["width"] == pytest.approx(x - REACH - GAP, abs=1)
        assert rect["y"] + rect["height"] / 2 == pytest.approx(y, abs=1)


def test_near_the_left_edge_the_data_box_is_right_of_the_chevron(page):
    wait_for_traffic(page)
    hold_traffic(page, plane("a1", -12, 8))
    set_prefs(page, view_ease="OFF")
    click_row(page, "a1")
    wait_followed(page, "a1")
    nothing_to_hit(page)
    radar = box_of(page, "#radar")
    rect, (x, y) = info_place(page, "a1")
    # Drag the aircraft to 40 px from the radar's left edge.
    page.mouse.move(x, y + 80)
    page.mouse.down()
    page.mouse.move(radar["x"] + 40, y + 80, steps=8)
    page.mouse.up()
    rect, (x, y) = info_place(page, "a1")
    assert x == pytest.approx(radar["x"] + 40, abs=2)
    assert rect["x"] == pytest.approx(x + REACH + GAP, abs=1)
    assert rect["y"] > y, "under the aircraft's tag"


def test_the_data_box_hides_with_its_setting_and_with_no_focus(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    click_row(page, "a1")
    info_box(page).wait_for(state="visible")
    set_prefs(page, info_box=False)
    info_box(page).wait_for(state="hidden")
    set_prefs(page, info_box=True)
    info_box(page).wait_for(state="visible")
    focus_set(page, None)
    info_box(page).wait_for(state="hidden")


INFO_STYLE = "e => { const s = getComputedStyle(e); return [s.borderTopWidth, s.backgroundColor, s.paddingTop]; }"


def alpha(colour):
    """The alpha of a computed rgb() or rgba() colour."""
    numbers = [float(n) for n in re.findall(r"[\d.]+", colour)]
    return numbers[3] if len(numbers) > 3 else 1.0


def test_the_data_box_is_boxed_whether_or_not_the_tags_are(page):
    """The label box settings, with a floor: never less than 80 % black,
    a 1 px edge and 4 px of padding."""
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    click_row(page, "a1")
    info_box(page).wait_for(state="visible")
    set_prefs(page, box_items=[], box_fill=0, box_pad=0, box_border=0)
    # box_width's least setting is 1 px: under it the floor still holds.
    page.evaluate("document.documentElement.style.setProperty('--box-width', '0px')")
    frames(page)
    width, background, padding = page.eval_on_selector("#ac-info", INFO_STYLE)
    assert (width, padding) == ("1px", "4px")
    assert background.startswith("rgba(0, 0, 0") and alpha(background) == pytest.approx(0.8, abs=0.01)
    set_prefs(page, box_fill=100, box_pad=6, box_width=2)
    frames(page)
    width, background, padding = page.eval_on_selector("#ac-info", INFO_STYLE)
    assert (width, padding) == ("2px", "6px")
    assert background in ("rgb(0, 0, 0)", "rgba(0, 0, 0, 1)")
    assert page.eval_on_selector("#ac-info", "e => getComputedStyle(e).pointerEvents") == "none"


# -- the page's zoom (prefs.ui_zoom, CSS zoom on .page) --------------------------


def zoom_page(page, zoom):
    """The page zoomed as prefs.ui_zoom zooms it; returns once the radar has
    drawn at the size that leaves it."""
    page.evaluate("z => { document.querySelector('.page').style.zoom = z; }", zoom)
    frames(page, 2)
    radar_drawn(page)


def page_point(page, x, y):
    """A canvas pixel position as a page position, whatever the zoom: from
    where the browser says the canvas is on the page."""
    box = page.locator("#radar").bounding_box()
    width, height = canvas_size(page)
    return box["x"] + x * box["width"] / width, box["y"] + y * box["height"] / height


@pytest.mark.parametrize("zoom", [1, 1.5])
def test_under_the_pages_zoom_a_click_focuses_the_chevron_and_the_data_box_is_beside_it(page, zoom):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    set_prefs(page, view_ease="OFF")
    zoom_page(page, zoom)
    hit = hit_of(page, "a2")
    x, y = page_point(page, hit["x"], hit["y"])
    assert 0 < x < 1440 and 0 < y < 900, "the test wants the chevron on screen"
    page.mouse.click(x, y)
    page.wait_for_selector('#tracks-body tr.focused[data-hex="a2"]')
    wait_followed(page, "a2")
    info_box(page).wait_for(state="visible")
    frames(page, 1)
    rect = page.locator("#ac-info").bounding_box()
    hit = hit_of(page, "a2")
    x, y = page_point(page, hit["x"], hit["y"])
    # In the page's CSS px, which the zoom scales on screen.
    assert (x - rect["x"] - rect["width"]) / zoom == pytest.approx(REACH + GAP, abs=1)
    assert (rect["y"] + rect["height"] / 2 - y) / zoom == pytest.approx(0, abs=1)


# -- unfocusing after the view was moved -----------------------------------------


def test_after_a_drag_unfocusing_keeps_the_view_the_drag_left(page):
    wait_for_traffic(page)
    hold_traffic(page, *MOVING)
    nothing_to_hit(page)
    set_prefs(page, view_ease="OFF")
    set_view(page, 25, 3, -4)
    click_row(page, "a1")
    wait_followed(page, "a1")
    pan(page, *on_screen(page, 200, 200))
    dragged = view_of(page)
    focus_set(page, None)
    page.wait_for_selector("#tracks-body tr.focused", state="detached")
    frames(page, 3)
    assert view_of(page) == dragged


def test_after_a_place_click_unfocusing_keeps_the_place_at_the_centre(page):
    wait_for_traffic(page)
    hold_traffic(page, plane("a1", -1, 1))
    set_prefs(page, view_ease="OFF", follow_nm=40)  # wide enough for a city clear of the rest
    set_view(page, 25, 3, -4)
    click_row(page, "a1")
    wait_followed(page, "a1", nm=40)
    frames(page)
    city = a_city(page)
    page.mouse.click(*on_screen(page, *city["point"]))
    frames(page, 1)
    placed = view_of(page)
    assert (placed["panX"], placed["panY"]) == tuple(city["xy"])
    focus_set(page, None)
    page.wait_for_selector("#tracks-body tr.focused", state="detached")
    frames(page, 3)
    assert view_of(page) == placed


def test_after_a_wheel_a_click_on_the_focused_aircraft_unfocuses_and_goes_back(page):
    wait_for_traffic(page)
    hold_traffic(page, plane("a1", -12, 8))
    set_prefs(page, view_ease="OFF")
    before = set_view(page, 25, 3, -4)["view"]
    click_row(page, "a1")
    wait_followed(page, "a1")
    page.mouse.move(*on_screen(page, 200, 200))
    turn_wheel(page, -200)
    assert view_of(page)["nm"] < 10
    frames(page)
    hit = hit_of(page, "a1")
    page.mouse.click(*on_screen(page, hit["x"], hit["y"]))
    page.wait_for_selector("#tracks-body tr.focused", state="detached")
    frames(page, 1)
    assert view_of(page) == before
