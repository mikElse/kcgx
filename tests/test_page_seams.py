"""The seams phase G's lanes code to (plan, Phase 0, P0.4a and P0.4b): the
one frame clock and its cap, the theme's render scale and glow by layer, the
radar's debug() put together from its parts, and the tracks columns."""

from __future__ import annotations

import json
import time

import pytest

from kcgx.prefs import SCHEMA
from page_fixtures import *  # noqa: F403  (fixtures and helpers)

pytestmark = pytest.mark.browser

# Radar frames a second, and requestAnimationFrame's own rate and the 5th
# percentile of its intervals in ms, over the same two seconds.
RATES = """async () => {
  const at = [];
  let going = true;
  const count = (now) => { at.push(now); if (going) requestAnimationFrame(count); };
  requestAnimationFrame(count);
  const a = window.kcgx.radar.debug().frames, t0 = performance.now();
  await new Promise((r) => setTimeout(r, 2000));
  going = false;
  const secs = (performance.now() - t0) / 1000;
  const gaps = at.slice(1).map((t, i) => t - at[i]).sort((x, y) => x - y);
  const q = (f) => gaps[Math.min(gaps.length - 1, Math.floor(f * gaps.length))];
  return { radar: (window.kcgx.radar.debug().frames - a) / secs, raf: at.length / secs, p05: q(0.05) };
}"""


def test_the_radar_keeps_to_the_frame_rate_cap(page):
    # The cap is not what is drawn: with no glow and no persistence each frame
    # is cheap, and a loaded machine's software canvas can keep up with 15.
    set_prefs(page, fps_max=15, glow_map=0, glow_traffic=0, glow_text=0, display="OFF")
    page.wait_for_timeout(200)
    rates = page.evaluate(RATES)
    assert 13 <= rates["radar"] <= 16, rates


@pytest.mark.parametrize("fps_max", [60, 120])
def test_at_the_display_rate_or_above_no_frame_is_dropped(page, fps_max):
    """At 60 where the browser gives no frame sooner than 60 Hz would, and at
    120 anywhere, the radar draws every frame it is given (the 1 ms of slack
    takes up the jitter)."""
    set_prefs(page, fps_max=fps_max)
    page.wait_for_timeout(200)
    rates = page.evaluate(RATES)
    # Headless WebKit's frames come 1 to 35 ms apart, and the cap rightly
    # passes over those that come too soon.
    if fps_max == 60 and rates["p05"] < 16:
        pytest.skip(f"frames come faster than 60 Hz here: {rates}")
    assert rates["radar"] >= 0.9 * rates["raf"], rates


THEME = "(call) => import('/static/js/theme.js').then((theme) => eval(call))"


@pytest.mark.parametrize(("aa", "scale"), [("OFF", 0.5), ("ON", 1), ("SUPER", 2)])
def test_render_scale_follows_anti_aliasing(page, aa, scale):
    set_prefs(page, aa=aa)
    assert page.evaluate(THEME, "theme.renderScale()") == scale


def test_glow_is_a_blur_by_layer(page):
    blur = lambda layer: page.evaluate(THEME, f"theme.glowBlur({layer!r})")  # noqa: E731
    assert [blur(layer) for layer in ("map", "traffic", "text")] == [pytest.approx(3.96)] * 3
    set_prefs(page, glow_map=50, glow_traffic=100, glow_text=0)
    assert [blur(layer) for layer in ("map", "traffic", "text")] == [6, 12, 0]
    with pytest.raises(Exception, match="no glow layer"):
        blur("hud")


def test_glow_with_no_layer_is_still_phase_f_s_three_steps(page):
    # Until the lanes move the radar and the traces to the layers: LOW at
    # the default 33, from the data-glow bridge.
    assert page.evaluate(THEME, "theme.glowBlur()") == 4
    set_prefs(page, glow_map=75)
    assert page.evaluate(THEME, "theme.glowBlur()") == 9
    set_prefs(page, glow_map=0)
    assert page.evaluate(THEME, "theme.glowBlur()") == 0


MERGE = """(parts) => import('/static/js/radar/index.js').then((radar) => {
  try { return radar.mergeDebug(parts); } catch (error) { return 'threw: ' + error.message; }
})"""


def test_the_radar_s_debug_is_its_parts_and_two_may_not_give_one_key(page):
    assert page.evaluate(MERGE, [{"a": 1}, {"b": 2}]) == {"a": 1, "b": 2}
    assert page.evaluate(MERGE, [{"a": 1}, {"b": 2, "a": 3}]) == "threw: radar debug(): a is given twice"
    # The core's keys and its parts': a lane adds keys of its own (the plan's
    # cross-lane contracts), and these stay.
    keys = set(page.evaluate("Object.keys(window.kcgx.radar.debug())"))
    assert keys >= {
        "frames", "shown", "view", "placed", "hovered", "mapFor", "loaded", "rings", "home", "symbols",
        "layers", "hits",
    }


def test_a_tick_that_throws_still_counts_as_a_frame_and_is_reported_once(page):
    page.evaluate(
        """() => { window.unhook = window.kcgx.radar.hook(() => ({
                       tick() { throw new Error("a test tick threw"); } })); }"""
    )
    before = radar_debug(page)["frames"]
    try:
        frames(page, 5)  # gave up after 2 s, before the frame was counted first
    finally:
        page.evaluate("window.unhook()")
    assert radar_debug(page)["frames"] >= before + 5
    errors = page_errors(page, wait_for="a test tick threw")
    assert sum("a test tick threw" in e for e in errors) == 1, errors
    errors.clear()


def test_waiting_for_a_radar_frame_gives_up_on_a_radar_that_draws_none(page):
    page.evaluate(
        """() => { const radar = window.kcgx.radar, debug = radar.debug, stuck = debug().frames;
                   window.undo = () => { radar.debug = debug; };
                   radar.debug = () => ({ ...debug(), frames: stuck }); }"""
    )
    started = time.monotonic()
    try:
        with pytest.raises(Exception, match="the radar drew no frame in 2 s"):
            frames(page)
    finally:
        page.evaluate("window.undo()")
    assert time.monotonic() - started < 4


# Two hooks of a test's own, a then b, for six frames: when a's tick and post
# each ran, and the aircraft's positions as `radar.now` had them then.
POST = """async () => {
    const frame = RADAR_FRAME;
    const order = [], seen = [];
    const at = (radar) => JSON.stringify(radar.now.map((ac) => ac.now));
    const off = ["a", "b"].map((name) => window.kcgx.radar.hook((radar) => ({
        tick(now) { if (name === "a") seen.push({ when: "tick", now, at: at(radar) }); },
        post(now) { order.push(name); if (name === "a") seen.push({ when: "post", now, at: at(radar) }); },
    })));
    try { for (let n = 0; n < 6; n += 1) await frame(); } finally { off.forEach((f) => f()); }
    return { order, seen };
}"""


def test_a_post_hook_runs_after_the_frame_is_drawn_in_init_order(page):
    hold_traffic(page, plane("abc001", east=5, gs=400, trk=90))
    found = page.evaluate(POST.replace("RADAR_FRAME", RADAR_FRAME))
    seen = found["seen"]
    assert [s["when"] for s in seen] == ["tick", "post"] * (len(seen) // 2) and len(seen) >= 12, seen
    assert found["order"] == ["a", "b"] * (len(seen) // 2)
    for tick, post in zip(seen[::2], seen[1::2]):
        assert post["now"] == tick["now"]
        assert post["at"] != tick["at"] and post["at"] != "[]"  # the aircraft were moved and drawn between
    for post, tick in zip(seen[1::2], seen[2::2]):
        assert tick["at"] == post["at"]  # and not again until the next frame


# Three callbacks on the page's frame clock for six radar frames: the second
# throws every time, the third every other time after it has counted.
CLOCK = """async () => {
    const { onFrame } = await import("/static/js/frames.js");
    const frame = RADAR_FRAME;
    const ran = { first: 0, last: 0 };
    const off = [
        onFrame(() => { ran.first += 1; }),
        onFrame(() => { throw new Error("one frame callback threw"); }),
        onFrame(() => { ran.last += 1; if (ran.last % 2) throw new Error("another frame callback threw"); }),
    ];
    try { for (let n = 0; n < 6; n += 1) await frame(); } finally { off.forEach((f) => f()); }
    return ran;
}"""


def test_a_frame_callback_that_throws_stops_no_other_and_is_reported_once(page):
    ran = page.evaluate(CLOCK.replace("RADAR_FRAME", RADAR_FRAME))
    assert ran["first"] == ran["last"] >= 6, ran
    page_errors(page, wait_for="one frame callback threw")
    errors = page_errors(page, wait_for="another frame callback threw")
    assert sum("one frame callback threw" in e for e in errors) == 1, errors
    assert sum("another frame callback threw" in e for e in errors) == 1, errors
    errors.clear()


COLUMNS = """() => import('/static/js/columns.js').then(({ COLUMNS, COLUMN }) => ({
  names: COLUMNS.map((c) => c.key),
  byName: COLUMNS.every((c) => COLUMN[c.key] === c),
  columns: COLUMNS.map((c) => ({ key: c.key, title: c.title, filter: c.filter, num: c.num })),
  read: [FULL, {}, { alt: "GND" }, { alt: null, gs: null, trk: null, sq: null }].map(
    (ac) => Object.fromEntries(COLUMNS.map((c) => [c.key, [c.text(ac), c.sort(ac)]]))),
}))"""
FULL = {
    "hex": "a1b2c3", "label": "DAL1388", "type": "A321", "reg": "N123DX", "lat": 45.58899, "lon": -122.5975,
    "alt": 5900, "vs": -640, "gs": 310, "trk": 30, "sq": "2251", "age": 3.4, "dist": 14.3, "brg": 7,
    "desc": "AIRBUS A-321", "oper": "DELTA AIR LINES", "cat": "A3", "still": 0,
}
TITLES = {
    "CALLSIGN": "CALLSIGN", "TYPE": "TYPE", "REG": "REG", "ALT": "ALT FT", "VS": "V/S FPM", "GS": "GS KT",
    "TRK": "TRK", "DIST": "DIST NM", "BRG": "BRG", "SQWK": "SQWK", "HEX": "HEX", "DESC": "DESC", "OPER": "OPER",
    "CAT": "CAT", "AGE": "AGE S", "LAT": "LAT", "LON": "LON",
}
TEXT_FILTERS = {"CALLSIGN", "TYPE", "REG", "SQWK", "HEX", "DESC", "OPER", "CAT"}  # Task 8; the rest are numbers
RIGHT = {"ALT", "VS", "GS", "TRK", "DIST", "BRG", "SQWK", "AGE", "LAT", "LON"}  # figures, set right


def test_every_tracks_column_reads_an_aircraft_and_one_that_reports_nothing(page):
    found = page.evaluate(COLUMNS.replace("FULL", json.dumps(FULL)))
    assert found["names"] == list(SCHEMA["track_cols"].names)
    assert found["byName"]
    assert found["columns"] == [
        {"key": name, "title": TITLES[name], "filter": "text" if name in TEXT_FILTERS else "number",
         "num": name in RIGHT}
        for name in found["names"]
    ]
    full, empty, ground, unknown = found["read"]
    assert {name: text for name, (text, _) in full.items()} == {
        "CALLSIGN": "DAL1388", "TYPE": "A321", "REG": "N123DX", "ALT": "5900", "VS": "-640", "GS": "310",
        "TRK": "030", "DIST": "14.3", "BRG": "007", "SQWK": "2251", "HEX": "A1B2C3", "DESC": "AIRBUS A-321",
        "OPER": "DELTA AIR LINES", "CAT": "A3", "AGE": "3", "LAT": "45.5890", "LON": "-122.5975",
    }
    assert {name: sort for name, (_, sort) in full.items()} == {
        "CALLSIGN": "DAL1388", "TYPE": "A321", "REG": "N123DX", "ALT": 5900, "VS": -640, "GS": 310, "TRK": 30,
        "DIST": 14.3, "BRG": 7, "SQWK": "2251", "HEX": "a1b2c3", "DESC": "AIRBUS A-321",
        "OPER": "DELTA AIR LINES", "CAT": "A3", "AGE": 3.4, "LAT": 45.58899, "LON": -122.5975,
    }
    # Nothing reported, or not yet sent by the server: an empty cell, sorted
    # below every figure (as phase F's table sorted a missing one).
    for read in (empty, unknown):
        assert {name: text for name, (text, _) in read.items()} == {name: "" for name in TITLES}
    assert {name: sort for name, (_, sort) in empty.items()} == {
        name: "" if name in TEXT_FILTERS else -1 for name in TITLES
    }
    assert ground["ALT"] == ["GND", 0]


def test_the_table_shows_phase_f_s_seven_columns_until_tracks_reads_track_cols(page):
    titles = page.eval_on_selector_all("#tracks-head th", "ths => ths.map(th => th.textContent)")
    assert titles == ["CALLSIGN", "TYPE", "ALT FT", "GS KT", "TRK", "DIST NM", "SQWK"]
    assert page.eval_on_selector_all("#tracks-head th", "ths => ths.map(th => th.className)") == [
        "", "", "num", "num", "num", "num", "num",
    ]


def test_the_store_starts_with_no_rank(page):
    assert page.evaluate("window.kcgx.store.state.rank instanceof Map && window.kcgx.store.state.rank.size === 0")
