"""The map lane's page tests (plan phase G, Task 10 and 4d's glow_map): every
map layer styled by the `map` table, still labels that follow the zoom,
runways at their true width up close, and the map's own glow."""

from __future__ import annotations

import copy
import math
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
