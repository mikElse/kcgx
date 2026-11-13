"""Phase G, the TRAFFIC lane, in the browser: flight tags on a layer of their
own, drawn last and drawn normally over every map element, aircraft and
trail (decision 8, Task 11), and the HUD's two readouts (Task 11)."""

from __future__ import annotations

import pytest

from page_fixtures import *  # noqa: F403  (fixtures and helpers)

pytestmark = pytest.mark.browser

BLACK = (0, 0, 0, 255)


# -- a map and traffic of the test's own --------------------------------------


def scale(page):
    """The airport on the canvas and canvas pixels to the nm, as last drawn."""
    debug = radar_drawn(page)
    ring = debug["rings"][0]
    return debug["home"], ring["r"] / ring["nm"]


def north_of(page, y):
    """How far north of the airport, in nm, a canvas row is."""
    home, s = scale(page)
    return (home["y"] - y) / s


def east_of(page, x):
    home, s = scale(page)
    return (x - home["x"]) / s


def coast_along(page, north):
    """Reload the page on a map whose only line is a coast running east and
    west `north` nm north of the airport, under whatever stands there."""
    lat, lon = page.evaluate("[window.kcgx.store.state.airport.lat, window.kcgx.store.state.airport.lon]")

    def routed(route):
        response = route.fetch()
        geo = response.json()
        q = geo["q"]
        # Many short steps: the map draws itself on a point at a time, and
        # with few points `picture` would take a pause in that for the end.
        step = round(0.005 * q)
        geo["lines"] = {"coast": [[round((lon - 1) * q), round((lat + north / 60) * q)] + [step, 0] * 400]}
        route.fulfill(response=response, json=geo)

    page.route("**/api/geo*", routed)
    page.reload()
    page.wait_for_selector(".feed.expanded")
    wait_for_traffic(page)
    assert radar_debug(page)["layers"] == {"coast": 1}


def crossing(page, x, top, bottom, hex_="b1", **over):
    """An aircraft that has flown north along canvas column `x`, from below
    canvas row `bottom` to above `top`: its trail crosses every row between.
    Returns its positions, one a poll, for `hold_traffic`."""
    east = east_of(page, x)
    south, north = north_of(page, bottom), north_of(page, top)
    return [plane(hex_, east, n, trk=0, **over) for n in (south - 4, south - 2, north + 5)]


def text_rows(tag, ratio):
    """A tag of one line, unboxed: its baseline and the top of its capitals."""
    baseline = tag["y"] + 16 * ratio
    return baseline, baseline - 0.7 * 16 * ratio


def shine(block):
    """A block's pixels as the light each puts on the screen: its brightest
    channel as strong as it is opaque. Persistence leaves pixels at an alpha
    of 1 / 255 that never fade further; they put no light on the screen."""
    return [max(block[i:i + 3]) * block[i + 3] // 255 for i in range(0, len(block), 4)]


def block_of(page, rect):
    """The radar canvas's pixels a rectangle touches, as rows of (r, g, b, a)."""
    flat = canvas_block(page, rect)
    left, top = int(rect["x"]), int(rect["y"])
    width = -int(-(rect["x"] + rect["w"])) - left
    pixels = [tuple(flat[i:i + 4]) for i in range(0, len(flat), 4)]
    return {(left + i % width, top + i // width): p for i, p in enumerate(pixels)}


# -- tags over everything -----------------------------------------------------


def test_a_tags_text_is_its_colour_where_a_map_line_and_a_trail_cross_it(page):
    """Drawn normally, not added: where a coast and another aircraft's trail
    run through a tag's letters, the letters are the tag's colour and no
    brighter."""
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    cyan = (*css_colour(page, "--cyan"), 255)
    tag = hold_traffic(page, plane("a1", -10, 5))["a1"]
    baseline, cap = text_rows(tag, ratio)
    letters = {"x": tag["x"], "y": cap, "w": tag["w"], "h": baseline - cap}
    picture(page)
    # The letters' own pixels: those that are the tag's colour through and through.
    alone = block_of(page, letters)
    full = {xy for xy, p in alone.items() if p == cyan}
    middle = round((baseline + cap) / 2)
    columns = {}
    for x, y in full:
        columns[x] = columns.get(x, 0) + 1
    column = max(columns, key=columns.get)  # the letters' stoutest stroke

    coast_along(page, north_of(page, middle))
    hold_traffic(page, plane("a1", -10, 5))
    for at in crossing(page, column, tag["y"], tag["y"] + tag["h"], sq="7700"):
        hold_traffic(page, plane("a1", -10, 5), at)
    picture(page)
    # The coast and the trail are there, either side of the letters.
    assert lit(page, tag["x"] + tag["w"] + 12 * ratio, middle) > 100, "no coast beside the tag"
    assert lit(page, column, tag["y"] - 4 * ratio) > 100, "no trail above the tag"
    crossed = block_of(page, letters)
    under_coast = [xy for xy in full if abs(xy[1] - middle) <= 1]
    under_trail = [xy for xy in full if abs(xy[0] - column) <= 1]
    assert len(under_coast) >= 2 and len(under_trail) >= 2, (under_coast, under_trail)
    # Within a step of the colour: WebKit's letters are not quite opaque.
    assert {xy: crossed[xy] for xy in full if max(abs(a - b) for a, b in zip(crossed[xy], cyan)) > 2} == {}


def test_a_tags_box_is_black_over_a_map_line_and_over_another_aircrafts_trail(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    set_prefs(page, **glow(0), display="OFF", box_items=["AIRCRAFT"], box_fill=0, box_border=0, box_pad=12)
    box = hold_traffic(page, plane("a1", -10, 5))["a1"]["box"]
    border = max(1, round(ratio))
    # The coast through the padding above the letters, the trail down the
    # padding right of them.
    row = box["y"] + border + 6 * ratio
    column = box["x"] + box["w"] - border - 6 * ratio
    coast_along(page, north_of(page, row))
    assert hold_traffic(page, plane("a1", -10, 5))["a1"]["box"] == box
    for at in crossing(page, column, box["y"], box["y"] + box["h"], sq="7700"):
        hold_traffic(page, plane("a1", -10, 5), at)
    picture(page)
    on_coast = [(box["x"] + box["w"] * f, row + dy) for f in (0.5, 0.75) for dy in (-1, 0, 1)]
    on_trail = [(column + dx, box["y"] + box["h"] * f) for f in (0.35, 0.65) for dx in (-1, 0, 1)]
    assert max(max(p[:3]) for p in canvas_pixels(page, *on_coast)) > 100, "the coast does not cross the box"
    assert max(p[0] for p in canvas_pixels(page, *on_trail)) > 100, "the trail does not cross the box"
    draw(page, box_fill=100)
    assert canvas_pixels(page, *on_coast) == [BLACK] * len(on_coast)
    assert canvas_pixels(page, *on_trail) == [BLACK] * len(on_trail)


def test_a_tag_that_moves_leaves_no_ghost_with_persistence_on(page):
    wait_for_traffic(page)
    set_prefs(page, display="VECTOR")
    tag = hold_traffic(page, plane("a1", -10, 5))["a1"]
    hold_traffic(page)
    picture(page)
    bare = shine(canvas_block(page, tag))
    hold_traffic(page, plane("a1", -10, 5))
    picture(page)
    drawn = shine(canvas_block(page, tag))
    assert sum(a > b + 100 for a, b in zip(drawn, bare)) > 20, "no tag drawn"
    # South, so that the trail it leaves runs away from where its tag was;
    # and one frame, the next, which is the first to draw it there.
    hold_traffic(page, plane("a1", -10, -3))
    frames(page, 1)
    after = shine(canvas_block(page, tag))
    assert max(abs(a - b) for a, b in zip(after, bare)) <= 2, "the tag left a ghost of itself"


def set_rank(page, rank):
    page.evaluate(
        """rank => { const r = window.kcgx.store.state.rank;
                    r.clear();
                    for (const [hex, at] of Object.entries(rank)) r.set(hex, at); }""",
        rank,
    )
    frames(page)


def focus_on(page, hex_):
    page.evaluate("hex => import('/static/js/focus.js').then(({ focus }) => focus.set(hex))", hex_)
    frames(page)


def test_tags_are_drawn_in_rank_order_the_first_on_top(page):
    """Two tags one over the other, boxed and filled: the one on top hides
    the other's letters under its box."""
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    set_prefs(page, **glow(0), display="OFF", box_items=["AIRCRAFT"], box_fill=100, box_border=0, box_pad=4)
    _, s = scale(page)
    drawn = hold_traffic(page, plane("a1", -10, 5), plane("a2", -10, 5 - 7 * ratio / s))
    upper, lower = drawn["a1"]["box"], drawn["a2"]["box"]
    border, pad = max(1, round(ratio)), 4 * ratio
    # The padding above the lower tag's letters, across the upper tag's letters.
    band = {
        "x": upper["x"] + border + pad, "y": lower["y"] + border + 1,
        "w": upper["w"] - 2 * (border + pad), "h": pad - 2,
    }
    assert upper["y"] + border + pad <= band["y"] and band["y"] + band["h"] <= upper["y"] + upper["h"] - border - pad

    set_rank(page, {"a1": 0, "a2": 1})
    assert radar_debug(page)["tag_order"] == ["a2", "a1"]
    assert ink(canvas_block(page, band)) > 0, "the first's letters are under the last's box"
    set_rank(page, {"a1": 1, "a2": 0})
    assert radar_debug(page)["tag_order"] == ["a1", "a2"]
    assert ink(canvas_block(page, band)) == 0
    # One the sort has not ranked counts as first.
    set_rank(page, {"a1": 0.5})
    assert radar_debug(page)["tag_order"] == ["a1", "a2"]
    # The focused aircraft is first whatever its rank.
    focus_on(page, "a1")
    assert radar_debug(page)["tag_order"] == ["a2", "a1"]
    assert ink(canvas_block(page, band)) > 0
    focus_on(page, None)


def test_a_tags_letters_glow_with_the_traffic_and_not_with_the_glow_off(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")

    def added():
        """The light the tag adds just above its capitals, where it has no ink."""
        tag = hold_traffic(page, plane("a1", -10, 5))["a1"]
        _, cap = text_rows(tag, ratio)
        above = {"x": tag["x"], "y": cap - 4 * ratio, "w": tag["w"], "h": 2 * ratio}
        picture(page)
        with_it = canvas_block(page, above)
        hold_traffic(page)
        picture(page)
        without = canvas_block(page, above)
        return max(a - b for a, b in zip(with_it, without))

    draw(page, **glow(33), display="OFF")
    assert added() > 8, "the tag's letters do not glow"
    draw(page, **glow(0))
    assert added() == 0, "the tag's letters glow with the glow off"


# -- the HUD ------------------------------------------------------------------

HEAR = """frame => {
    const store = window.kcgx.store;
    if (!window.heard) {
        window.heard = store.apply;
        store.apply = f => { if (f.t !== "aircraft") window.heard(f); };
    }
    window.heard({t: "aircraft", refresh: 15, range: 40, ac: [], ...frame});
}"""


def test_the_huds_first_line_is_the_poll_and_the_second_the_range(page):
    assert page.eval_on_selector_all(".hud-left span", "els => els.map(e => e.id)") == ["radar-poll", "radar-range"]
    poll, range_ = (box_of(page, f"#{name}") for name in ("radar-poll", "radar-range"))
    assert poll["y"] + poll["height"] <= range_["y"]


@pytest.mark.parametrize(
    "polled, age, words",
    [
        ({"error": ""}, 5, "5 SECONDS AGO"),
        ({"error": ""}, 1, "1 SECOND AGO"),
        ({"error": ""}, 0, "0 SECONDS AGO"),
        ({"error": "NO CONNECTION"}, 40, "NO CONNECTION, PICTURE 40 SECONDS OLD"),
        ({"error": "ERR 429"}, 1, "ERR 429, PICTURE 1 SECOND OLD"),
        ({"error": "NO CONNECTION"}, None, "RADAR NO CONNECTION"),
        (None, None, "RADAR WAITING"),
    ],
)
def test_the_poll_reads_in_seconds(page, polled, age, words):
    said = page.evaluate(
        "([polled, age]) => import('/static/js/radar/index.js').then((radar) => radar.pollWords(polled, age))",
        [polled, age],
    )
    assert said == words


def test_the_hud_says_how_many_seconds_ago_the_radar_was_polled(page):
    """The HUD is written every 500 ms or so, so a second may have gone by."""
    said = "words => new RegExp(words).test(document.getElementById('radar-poll').textContent)"
    page.evaluate(HEAR, {"ok": True, "error": "", "age": 5})
    page.wait_for_function(said, arg="^[56] SECONDS AGO$")
    page.evaluate(HEAR, {"ok": False, "error": "NO CONNECTION", "age": 40})
    page.wait_for_function(said, arg="^NO CONNECTION, PICTURE 4[01] SECONDS OLD$")
