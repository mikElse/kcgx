"""The frequencies pane, phase G Task 6: one feed at a time, picked by a
click; the pane's header with the master mute and the volume; titles
without the airport; the traces at the render scale, glowing with the
traffic layer (Task 4).

Browser tests against the demo server, in Chromium and then WebKit.
"""

from __future__ import annotations

import pytest

from page_fixtures import *  # noqa: F403  (fixtures and helpers)
from page_fixtures import box_of, set_prefs, spy_on_sends

pytestmark = pytest.mark.browser


def expanded_ident(page):
    return page.eval_on_selector_all(".feed.expanded", "els => els.map(e => e.dataset.ident)")


def wait_for_master_mute(tab, on):
    tab.wait_for_selector(f"#master-mute[aria-pressed={'true' if on else 'false'}]")


# -- one feed at a time ------------------------------------------------------


def test_there_is_no_m_or_s_and_no_chatter_word(page):
    page.wait_for_selector(".feed.compact")
    buttons = page.eval_on_selector_all("#stack button", "bs => bs.map(b => b.textContent.trim())")
    assert "M" not in buttons and "S" not in buttons, buttons
    assert page.locator("#stack .feed-controls").count() == 0
    assert "CHATTER" not in page.inner_text("#stack").upper()


def test_exactly_one_feed_is_expanded(page):
    page.wait_for_selector(".feed.compact")
    assert len(expanded_ident(page)) == 1


def test_a_click_on_a_compact_feed_selects_it_and_on_the_expanded_one_sends_nothing(page):
    page.wait_for_selector(".feed.compact")
    playing = expanded_ident(page)[0]
    target = page.get_attribute(".feed.compact", "data-ident")
    spy_on_sends(page)
    try:
        page.click(f".feed.compact[data-ident={target}]")
        page.wait_for_selector(f".feed.expanded[data-ident={target}]")
        assert expanded_ident(page) == [target]
        assert {"t": "select", "ident": target} in page.evaluate("window.sent")
        assert not any(m["t"] in ("mute", "solo") for m in page.evaluate("window.sent"))
        # The one playing is first in the stack, and is no button.
        assert page.eval_on_selector("#stack .feed", "e => e.dataset.ident") == target
        assert page.eval_on_selector(".feed.expanded", "e => e.tagName") == "DIV"
        page.evaluate("window.sent = []")
        page.click(f".feed.expanded[data-ident={target}]")
        page.wait_for_timeout(300)
        assert [m for m in page.evaluate("window.sent") if m["t"] != "input"] == []
    finally:
        page.click(f".feed.compact[data-ident={playing}]")
        page.wait_for_selector(f".feed.expanded[data-ident={playing}]")


def test_the_expanded_head_reads_name_chatter_state_as_a_compact_row_does(page):
    page.wait_for_selector(".feed.compact")
    for shape, chatter in (("expanded", "chatter-big"), ("compact", "chatter-small")):
        at = page.eval_on_selector(
            f".feed.{shape}",
            """(row, chatter) => {
                const box = (s) => row.querySelector(s).getBoundingClientRect().toJSON();
                return { name: box(".feed-name"), chatter: box("." + chatter), glyph: box(".feed-state") };
            }""",
            chatter,
        )
        assert at["name"]["right"] <= at["chatter"]["left"] < at["chatter"]["right"] <= at["glyph"]["left"], shape
        gap = at["glyph"]["left"] - at["chatter"]["right"]
        assert 4 <= gap <= 12, f"{shape}: the chatter ends {gap} px before the state"
        assert abs((at["chatter"]["top"] + at["chatter"]["bottom"]) - (at["glyph"]["top"] + at["glyph"]["bottom"])) <= 6


def test_the_trace_is_sixty_px_tall(page):
    assert page.eval_on_selector(".feed.expanded .trace", "c => c.getBoundingClientRect().height") == 60


def test_feed_names_are_spaced_under_six_hundredths_of_an_em(page):
    page.wait_for_selector(".feed.compact")
    spacings = page.eval_on_selector_all(
        ".feed-name",
        "els => els.map(e => { const s = getComputedStyle(e); return parseFloat(s.letterSpacing) / parseFloat(s.fontSize); })",
    )
    assert spacings and all(s < 0.06 for s in spacings), spacings


# -- the header ----------------------------------------------------------------


def test_the_header_holds_the_mute_the_volume_and_its_readout(page):
    assert page.locator("#freq-counts").count() == 0
    assert page.eval_on_selector_all("#freq-head > *", "els => els.map(e => e.id)") == [
        "master-mute", "volume", "volume-value",
    ]
    assert page.get_attribute("#master-mute", "aria-pressed") == "false"
    assert page.locator("#master-mute svg").count() == 1
    assert page.locator(".screen-freq #freq-head").is_visible()
    # Above the stack, as the counts were.
    assert box_of(page, "#freq-head")["bottom"] <= box_of(page, "#stack")["top"] + 1


def test_the_master_mute_reaches_a_second_tab_and_keeps_the_volume(page, other):
    volume = page.evaluate("window.kcgx.store.state.volume")
    playing = expanded_ident(page)
    try:
        page.click("#master-mute")
        wait_for_master_mute(page, True)
        wait_for_master_mute(other, True)
        for tab in (page, other):
            # The speaker is crossed out, its waves gone.
            assert tab.eval_on_selector("#master-mute .cross", "e => getComputedStyle(e).display") != "none"
            assert tab.eval_on_selector("#master-mute .waves", "e => getComputedStyle(e).display") == "none"
            assert tab.evaluate("window.kcgx.store.state.volume") == volume
            assert expanded_ident(tab) == playing
        other.click("#master-mute")
        wait_for_master_mute(page, False)
        wait_for_master_mute(other, False)
        assert page.eval_on_selector("#master-mute .cross", "e => getComputedStyle(e).display") == "none"
    finally:
        page.evaluate("window.kcgx.send({t: 'master_mute', on: false})")
        wait_for_master_mute(page, False)


def test_a_reload_shows_the_master_mute_as_the_server_has_it(page, server):
    try:
        page.click("#master-mute")
        wait_for_master_mute(page, True)
        page.reload()
        page.wait_for_selector(".feed.expanded")
        wait_for_master_mute(page, True)
    finally:
        page.evaluate("window.kcgx.send({t: 'master_mute', on: false})")
        wait_for_master_mute(page, False)


# -- titles --------------------------------------------------------------------


def test_a_feed_named_for_the_city_reads_without_it(page):
    """The demo's centre is "KPDX Portland Center", as LiveATC names some."""
    name = "#stack [data-ident=kpdx_ctr] .feed-name"
    page.wait_for_selector(name)
    assert page.text_content(name) == "Center"
    set_prefs(page, short_names=False)
    page.wait_for_function(f"document.querySelector('{name}').textContent === 'Portland Center'")
    set_prefs(page, short_names=True)
    page.wait_for_function(f"document.querySelector('{name}').textContent === 'Center'")


# -- the traces at the render scale, with the traffic glow (Task 4) -------------


TRACE = ".feed.expanded .trace"


def test_the_trace_is_drawn_at_the_render_scale(page):
    ratio = page.evaluate("window.devicePixelRatio")
    for aa, scale, rendering in (("OFF", 0.5, "pixelated"), ("SUPER", 2, None), ("ON", 1, None)):
        set_prefs(page, aa=aa)
        page.wait_for_function(
            """([selector, scale]) => { const c = document.querySelector(selector);
                   return c.height === Math.max(1, Math.round(c.clientHeight * devicePixelRatio * scale)); }""",
            arg=[TRACE, scale],
        )
        size = page.eval_on_selector(TRACE, "c => [c.width, c.clientWidth, getComputedStyle(c).imageRendering]")
        assert size[0] == max(1, round(size[1] * ratio * scale)), (aa, size)
        if rendering:
            assert size[2] == rendering, aa
        else:
            assert size[2] != "pixelated", aa


SPY_ON_BLUR = """selector => {
    const ctx = document.querySelector(selector).getContext("2d");
    const real = Object.getOwnPropertyDescriptor(CanvasRenderingContext2D.prototype, "shadowBlur");
    window.blurs = [];
    Object.defineProperty(ctx, "shadowBlur", {
        configurable: true,
        get() { return real.get.call(this); },
        set(value) { window.blurs.push(value); real.set.call(this, value); },
    });
}"""


def last_blur_is(page, px):
    page.evaluate("window.blurs = []")
    page.wait_for_function(
        "px => window.blurs.length > 0 && Math.abs(window.blurs[window.blurs.length - 1] - px) < 1e-6", arg=px
    )


def test_the_trace_glows_with_the_traffic_layer_and_no_other(page):
    page.evaluate(SPY_ON_BLUR, TRACE)
    ratio = page.evaluate("window.devicePixelRatio")
    set_prefs(page, glow_traffic=50, glow_map=0, glow_text=0)
    last_blur_is(page, 6 * ratio)
    set_prefs(page, glow_map=100, glow_text=100)
    last_blur_is(page, 6 * ratio)
    set_prefs(page, glow_traffic=0)
    last_blur_is(page, 0)
    set_prefs(page, glow_traffic=100, aa="SUPER")
    last_blur_is(page, 12 * ratio * 2)
