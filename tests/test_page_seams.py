"""The seams phase G's lanes code to (plan, Phase 0, P0.4a): the one frame
clock and its cap, the theme's render scale and glow by layer, and the
radar's debug() put together from its parts."""

from __future__ import annotations

import pytest

from test_page import browser, page, server, set_prefs  # noqa: F401  (fixtures)

pytest.importorskip("playwright.sync_api")

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
    keys = set(page.evaluate("Object.keys(window.kcgx.radar.debug())"))
    assert keys == {
        "frames", "shown", "view", "placed", "hovered", "mapFor", "loaded", "rings", "home", "symbols",
        "layers", "hits",
    }
