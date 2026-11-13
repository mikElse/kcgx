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


def test_a_boxed_tags_letters_glow_over_its_own_box(page):
    """Boxed and filled, a tag's glow goes down over its own box, under its
    letters: the box's padding just above the capitals is lit in the tag's
    colour, and with the glow off it is black."""
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    cyan = css_colour(page, "--cyan")
    set_prefs(page, display="OFF", box_items=["AIRCRAFT"], box_fill=100, box_border=0, box_pad=8)

    def padding():
        tag = hold_traffic(page, plane("a1", -10, 5))["a1"]
        assert tag["boxed"] and tag["box"]
        box = tag["box"]
        # Inside the box, clear of its border, between its top and the
        # letters, whose capitals start a padding and a border in.
        margin = 8 * ratio + max(1, round(ratio))
        band = {
            "x": box["x"] + margin + 2 * ratio, "y": box["y"] + margin - 3 * ratio,
            "w": box["w"] - 2 * margin - 4 * ratio, "h": 2 * ratio,
        }
        assert holds(box, band)
        picture(page)
        return list(block_of(page, band).values())

    draw(page, **glow(75))
    lit_ = [p for p in padding() if max(p[:3]) > 8]
    assert lit_, "the box hides its own letters' glow"
    brightest = max(lit_, key=lambda p: max(p[:3]))
    # The tag's colour, dimmed: each channel cyan's in the same proportion.
    share = max(brightest[:3]) / max(cyan)
    assert all(abs(got - want * share) <= 4 for got, want in zip(brightest[:3], cyan)), (brightest, cyan)
    draw(page, **glow(0))
    dark = padding()
    assert dark == [BLACK] * len(dark), "glow over the box with the glow off"


def test_a_bigger_tag_size_draws_a_bigger_tag_and_claims_more_for_the_pointer(page):
    wait_for_traffic(page)
    ratio = page.evaluate("devicePixelRatio")
    small = hold_traffic(page, plane("a1", -10, 5), plane("a2", 10, -5))["a1"]
    draw(page, tag_px=28)
    big = tags(page)["a1"]
    assert big["h"] == pytest.approx(small["h"] * 28 / 16)
    assert big["w"] > small["w"] * 1.5
    # Its last line stays where it was over the chevron; it grows up and right.
    assert big["x"] == pytest.approx(small["x"])
    # A point in the big tag that the small one did not reach focuses its aircraft.
    x, y = big["x"] + big["w"] - 3 * ratio, big["y"] + 3 * ratio
    assert not (small["x"] <= x <= small["x"] + small["w"] and small["y"] <= y <= small["y"] + small["h"])
    page.mouse.click(*on_screen(page, x, y))
    page.wait_for_selector('#tracks-body tr.focused[data-hex="a1"]')


def test_the_tags_order_and_boxes_are_there_for_the_pointer(page):
    """radar.tagOrder (debug tag_order) is bottom first, the one on top
    last; each hit's tag says whether it is boxed and where its box is."""
    wait_for_traffic(page)
    hold_traffic(page, plane("a1", -10, 5), plane("a2", 10, -5))
    set_rank(page, {"a1": 0, "a2": 1})
    assert radar_debug(page)["tag_order"] == ["a2", "a1"]
    assert all(tag["boxed"] is False and tag["box"] is None for tag in tags(page).values())
    draw(page, box_items=["AIRCRAFT"])
    for tag in tags(page).values():
        assert tag["boxed"] is True and holds(tag, tag["box"])


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


# -- tails by time and speed; parked traffic; the sort's shading (Task 13) ----


def ago(page, hex_, *steps, nm=1, **over):
    """Fly `hex_` north along a line 10 nm west of the airport, a poll at each
    of `steps` (seconds ago, oldest first), `nm` a poll from `nm` north,
    standing still on the radar (no ground speed) unless given one."""
    for n, age in enumerate(steps, 1):
        hold_traffic(page, plane(hex_, -10, n * nm, trk=0, gs=None, age=age, **over))


def hit_of(page, hex_):
    return next(h for h in radar_debug(page)["hits"] if h["hex"] == hex_)


def stored(page, hex_):
    return page.evaluate("hex => window.kcgx.store.state.trails.get(hex)", hex_)


def test_the_store_keeps_ten_minutes_of_positions_with_their_times(page):
    wait_for_traffic(page)
    set_prefs(page, tail_secs=60)
    ago(page, "a1", 700, 500, 300, 100, 40, 20, 0)
    points = stored(page, "a1")
    # The one from 700 s ago is gone; every other is kept, whatever tail_secs says.
    assert len(points) == 6
    assert all(len(p) == 3 and all(isinstance(n, (int, float)) for n in p) for p in points)
    now = page.evaluate("performance.now() / 1000")
    assert [round(now - p[2]) for p in points] == pytest.approx([500, 300, 100, 40, 20, 0], abs=5)
    # Lat rising, oldest first.
    assert [p[0] for p in points] == sorted(p[0] for p in points)


def test_a_tail_is_as_long_as_tail_secs_and_lengthening_it_shows_history_at_once(page):
    wait_for_traffic(page)
    draw(page, tail_secs=60)
    ago(page, "a1", 500, 300, 100, 40, 20, 0)
    frames(page)
    _, s = scale(page)
    hit = hit_of(page, "a1")
    trail = hit["trail"]
    # The chevron, the positions of 0, 20 and 40 s ago, and where it was 60 s
    # ago, between 40 and 100 s ago's: the tail is cut at its length in time.
    assert len(trail) == 5
    assert trail[0] == pytest.approx([hit["x"], hit["y"]])
    y40 = hit["y"] + 2 * s  # a nm a poll, north up: older is lower
    y100 = hit["y"] + 3 * s
    assert y40 < trail[-1][1] < y100
    assert trail[-1][1] == pytest.approx(y40 + (y100 - y40) / 3, abs=0.2 * s)
    # Ten minutes: every position the store has, at once.
    draw(page, tail_secs=600)
    assert len(hit_of(page, "a1")["trail"]) == 7
    # None: no tail at all.
    draw(page, tail_secs=0)
    assert hit_of(page, "a1")["trail"] == []


def test_no_tail_is_drawn_with_tail_secs_0(page):
    wait_for_traffic(page)
    draw(page, **glow(0), display="OFF", tag_fields=[], tail_secs=180)
    hold_traffic(page)
    home, s = scale(page)
    # Between where it was 40 and 20 s ago: 10 to 15 nm north, 10 west,
    # and well clear of its chevron, at 20.
    x, y = home["x"] - 10 * s, home["y"] - 12.5 * s
    band = {"x": x - 4, "y": y - s, "w": 8, "h": 2 * s}
    picture(page)
    bare = shine(canvas_block(page, band))
    ago(page, "a1", 60, 40, 20, 0, nm=5)
    picture(page)
    tailed = shine(canvas_block(page, band))
    assert sum(a > b + 60 for a, b in zip(tailed, bare)) >= 3, "no tail drawn"
    draw(page, tail_secs=0)
    picture(page)
    assert shine(canvas_block(page, band)) == bare


TAIL_BANDS = {"tail_alpha": 60, "tail_alpha_min": 20, "tail_alpha_max": 90, "tail_gs_low": 40, "tail_gs_high": 250}


def test_a_tails_brightness_is_its_speeds_band(page):
    """Under tail_gs_low, tail_alpha_min; over tail_gs_high, tail_alpha_max;
    between, or with no speed, tail_alpha: each the aircraft's own alpha
    times that, at the tail's newest segment."""
    wait_for_traffic(page)
    set_prefs(page, **TAIL_BANDS)
    speeds = {"a1": 20, "a2": 300, "a3": 100, "a4": None, "a5": 40, "a6": 250}
    for north in (0, 2):
        hold_traffic(page, *[plane(h, -20 + 6 * i, north, trk=0, gs=gs) for i, (h, gs) in enumerate(speeds.items())])
    frames(page)
    hits = {h["hex"]: h for h in radar_debug(page)["hits"]}
    assert {h: hits[h]["alpha"] for h in speeds} == {h: 1 for h in speeds}
    assert {h: hits[h]["tail"] for h in speeds} == pytest.approx(
        {"a1": 0.2, "a2": 0.9, "a3": 0.6, "a4": 0.6, "a5": 0.6, "a6": 0.6}
    )
    # And the focus's dimming over that.
    focus_on(page, "a3")
    hits = {h["hex"]: h for h in radar_debug(page)["hits"]}
    assert hits["a3"]["tail"] == pytest.approx(0.6)
    assert hits["a1"]["tail"] == pytest.approx(0.2 * 0.15)
    assert hits["a2"]["tail"] == pytest.approx(0.9 * 0.15)
    focus_on(page, None)


def test_a_stale_aircrafts_tail_fades_with_it(page):
    wait_for_traffic(page)
    set_prefs(page, **TAIL_BANDS)
    for north in (0, 2):
        hold_traffic(page, plane("a1", -10, north, trk=0, gs=300, age=45))
    frames(page)
    hit = hit_of(page, "a1")
    assert hit["alpha"] < 0.7
    assert hit["tail"] == pytest.approx(hit["alpha"] * 0.9, rel=0.02)


LAYER_BLOCK = """([layer, x, y, w, h]) => {
    if (!window.radarParts) window.kcgx.radar.hook((radar) => { window.radarParts = radar; });
    return [...window.radarParts[layer].getContext("2d").getImageData(x, y, w, h).data];
}"""


def light_of(page, rect, layer="trace"):
    """How much an aircraft's lines (`trace`) or its tag (`tags`) put down
    within a block: the sum of the layer's alpha there, the layer alone, with
    no map under it and no persistence (display OFF)."""
    left, top = int(rect["x"]), int(rect["y"])
    right, bottom = -int(-(rect["x"] + rect["w"])), -int(-(rect["y"] + rect["h"]))
    flat = page.evaluate(LAYER_BLOCK, [layer, left, top, right - left, bottom - top])
    return sum(flat[3::4])


def chevron_block(page, east, north):
    home, s = scale(page)
    ratio = page.evaluate("devicePixelRatio")
    x, y = home["x"] + east * s, home["y"] - north * s
    return {"x": x - 12 * ratio, "y": y - 12 * ratio, "w": 24 * ratio, "h": 24 * ratio}


def test_the_slow_tail_is_dimmer_than_the_fast_one_on_the_screen(page):
    wait_for_traffic(page)
    draw(page, **glow(0), display="OFF", tag_fields=[], **TAIL_BANDS)
    home, s = scale(page)
    # Along each's older segment, which the reckoning does not move, and
    # clear of its chevron.
    spots = {h: {"x": home["x"] + e * s - 4, "y": home["y"] - 8 * s, "w": 8, "h": 4 * s} for h, e in (("a1", -10), ("a2", 10))}
    for north in (0, 20):
        hold_traffic(page, plane("a1", -10, north, trk=0, gs=20), plane("a2", 10, north, trk=0, gs=300))
    frames(page)
    slow, fast = (light_of(page, spots[h]) for h in ("a1", "a2"))
    assert fast > 0
    assert slow / fast == pytest.approx(20 / 90, abs=0.06)


PARKED = 200  # seconds standing still: over ground_min's 2 minutes


def parked_and_not(page):
    hold_traffic(
        page,
        plane("a1", -10, 5, still=PARKED),
        plane("a2", 10, 5, still=0),
        plane("a3", 0, -8),
        plane("a4", 10, -8, still=120),  # just the two minutes: not over them
    )


def test_parked_traffic_fades_to_ground_alpha(page):
    wait_for_traffic(page)
    set_prefs(page, ground_mode="FADE", ground_min=2, ground_alpha=25, **TAIL_BANDS)
    parked_and_not(page)
    parked_and_not(page)  # a second poll, for a tail
    frames(page)
    hits = {h["hex"]: h for h in radar_debug(page)["hits"]}
    assert {h: hits[h]["alpha"] for h in hits} == pytest.approx({"a1": 0.25, "a2": 1, "a3": 1, "a4": 1})
    assert hits["a1"]["tail"] == pytest.approx(0.25 * 0.2)  # standing still: the slow band
    # SHOW changes nothing.
    draw(page, ground_mode="SHOW")
    assert hit_of(page, "a1")["alpha"] == 1
    draw(page, ground_mode="FADE", ground_min=4)
    assert hit_of(page, "a1")["alpha"] == 1
    draw(page, ground_min=2)
    # The focused aircraft is never faded.
    focus_on(page, "a1")
    assert hit_of(page, "a1")["alpha"] == 1
    focus_on(page, None)


def test_a_parked_aircraft_is_faded_on_the_screen_chevron_and_tag(page):
    wait_for_traffic(page)
    draw(page, **glow(0), display="OFF", tag_fields=[], ground_mode="SHOW", ground_alpha=25)
    blocks = {"a1": chevron_block(page, -10, 5), "a2": chevron_block(page, 10, 5)}
    hold_traffic(page, plane("a1", -10, 5, still=PARKED), plane("a2", 10, 5, still=PARKED))
    frames(page)
    shown = {h: light_of(page, r) for h, r in blocks.items()}
    assert shown["a1"] == pytest.approx(shown["a2"], rel=0.1)
    draw(page, ground_mode="FADE")
    faded = {h: light_of(page, r) for h, r in blocks.items()}
    assert faded["a1"] / shown["a1"] == pytest.approx(0.25, abs=0.03)
    assert faded["a2"] / shown["a2"] == pytest.approx(0.25, abs=0.03)
    # The tag as well.
    draw(page, tag_fields=["CALLSIGN"])
    hold_traffic(page, plane("a1", -10, 5, still=PARKED, label="AB"), plane("a2", 10, 5, still=0, label="AB"))
    lit_ = {h: light_of(page, hit_of(page, h)["tag"], "tags") for h in ("a1", "a2")}
    assert lit_["a1"] / lit_["a2"] == pytest.approx(0.25, abs=0.03)


def test_hidden_parked_traffic_is_not_drawn_and_cannot_be_clicked(page):
    wait_for_traffic(page)
    set_prefs(page, ground_mode="SHOW")
    parked_and_not(page)
    where = hit_of(page, "a1")
    set_prefs(page, ground_mode="HIDE")
    page.wait_for_function("() => !window.kcgx.radar.debug().hits.some(h => h.hex === 'a1')")
    debug = radar_debug(page)
    assert sorted(h["hex"] for h in debug["hits"]) == ["a2", "a3", "a4"]
    assert "a1" not in debug["tag_order"] and "a1" not in debug["line_order"]
    page.mouse.click(*on_screen(page, where["x"], where["y"]))
    frames(page)
    assert page.evaluate("import('/static/js/focus.js').then(({ focus }) => focus.hex)") is None
    # The table's choice brings it back, unfaded, while it is focused.
    focus_on(page, "a1")
    assert hit_of(page, "a1")["alpha"] == 1
    focus_on(page, None)
    page.wait_for_function("() => !window.kcgx.radar.debug().hits.some(h => h.hex === 'a1')")


def test_the_sorts_first_is_brightest_and_on_top_its_last_at_the_floor(page):
    """Sorted by DIST, as tracks.js ranks it: the nearest at full alpha and
    drawn last within its colour, the farthest at sort_floor; reversed, the
    other way about."""
    wait_for_traffic(page)
    set_prefs(page, sort_floor=40)
    hold_traffic(
        page,
        plane("a1", -10, 5, dist=5), plane("a2", 0, 5, dist=10), plane("a3", 10, 5, dist=20),
        plane("a4", 0, -5, dist=15, sq="7700"),
    )
    set_rank(page, {"a1": 0, "a2": 1 / 3, "a4": 2 / 3, "a3": 1})
    debug = radar_debug(page)
    alphas = {h["hex"]: h["alpha"] for h in debug["hits"]}
    assert alphas == pytest.approx({"a1": 1, "a2": 0.8, "a4": 0.6, "a3": 0.4})
    # Within a colour, the sort's last first; the colours as ever.
    assert debug["line_order"] == ["a3", "a2", "a1", "a4"]
    assert debug["tag_order"] == ["a3", "a4", "a2", "a1"]
    set_rank(page, {"a3": 0, "a4": 1 / 3, "a2": 2 / 3, "a1": 1})
    debug = radar_debug(page)
    alphas = {h["hex"]: h["alpha"] for h in debug["hits"]}
    assert alphas == pytest.approx({"a3": 1, "a4": 0.8, "a2": 0.6, "a1": 0.4})
    assert debug["line_order"] == ["a1", "a2", "a3", "a4"]
    assert debug["tag_order"] == ["a1", "a2", "a4", "a3"]
    # The floor is a setting; at 100 the sort shades nothing.
    draw(page, sort_floor=100)
    assert {h["hex"]: h["alpha"] for h in radar_debug(page)["hits"]} == {"a1": 1, "a2": 1, "a3": 1, "a4": 1}
    # The focused aircraft is first, at full alpha, and on top of its colour.
    draw(page, sort_floor=0)
    focus_on(page, "a1")
    debug = radar_debug(page)
    assert {h["hex"]: h["alpha"] for h in debug["hits"]}["a1"] == 1
    assert debug["line_order"][-1] == "a1" and debug["tag_order"][-1] == "a1"
    focus_on(page, None)


def test_the_sorts_last_chevron_is_dimmed_on_the_screen(page):
    wait_for_traffic(page)
    draw(page, **glow(0), display="OFF", tag_fields=[], sort_floor=40)
    blocks = {"a1": chevron_block(page, -10, 5), "a3": chevron_block(page, 10, 5)}
    hold_traffic(page, plane("a1", -10, 5, dist=5), plane("a3", 10, 5, dist=20))
    set_rank(page, {"a1": 0, "a3": 1})
    light = {h: light_of(page, r) for h, r in blocks.items()}
    assert light["a3"] / light["a1"] == pytest.approx(0.4, abs=0.03)
    set_rank(page, {"a1": 1, "a3": 0})
    light = {h: light_of(page, r) for h, r in blocks.items()}
    assert light["a1"] / light["a3"] == pytest.approx(0.4, abs=0.03)


def focused(page):
    return page.evaluate("import('/static/js/focus.js').then(({ focus }) => focus.hex)")


def test_a_click_on_overlapping_chevrons_focuses_the_one_drawn_on_top(page):
    """radar.hits is topmost first, the reverse of line_order (the focused
    aircraft first), so a chevron over another is the one a click takes."""
    wait_for_traffic(page)
    hold_traffic(page, plane("a1", -10, 5), plane("a2", -10, 5), plane("a3", 10, -5, sq="7700"))
    for top, under in (("a1", "a2"), ("a2", "a1")):
        set_rank(page, {top: 0, under: 1, "a3": 0.5})
        debug = radar_debug(page)
        assert debug["line_order"] == [under, top, "a3"]
        assert [h["hex"] for h in debug["hits"]] == ["a3", top, under]
        where = hit_of(page, top)
        page.mouse.click(*on_screen(page, where["x"], where["y"]))
        frames(page)
        assert focused(page) == top
        # Focused, the one underneath is drawn last of all, and is first.
        focus_on(page, under)
        debug = radar_debug(page)
        assert debug["line_order"][-1] == under
        assert [h["hex"] for h in debug["hits"]] == [under, "a3", top]
        focus_on(page, None)


def test_the_hud_counts_the_tracks_drawn_not_those_hidden(page):
    wait_for_traffic(page)
    said = "words => document.getElementById('radar-tracks').textContent === words"
    set_prefs(page, ground_mode="SHOW")
    parked_and_not(page)
    page.wait_for_function(said, arg="4 TRACKS")
    set_prefs(page, ground_mode="HIDE")
    page.wait_for_function(said, arg="3 TRACKS")
    # The table's choice brings it back, and it counts while it is shown.
    focus_on(page, "a1")
    page.wait_for_function(said, arg="4 TRACKS")
    focus_on(page, None)
    page.wait_for_function(said, arg="3 TRACKS")
