"""The config overlay.

The table is a pure function of a Config, so most of this needs no app.
The point of the screen is honesty about which keys are actually honoured,
so that is what most of these assert.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from textual.geometry import Size

from squelch.app import SquelchApp
from squelch.config import Config
from squelch.config_view import (
    CONTENT_WIDTH,
    FIXED,
    OFF,
    INERT,
    LIVE,
    VOLUME_KEY,
    VOLUME_STEP,
    ConfigScreen,
    Live,
    adjust,
    config_rows,
    flatten,
    group_heading,
    row_text,
)
from squelch.mixer import Mixer

SIZE = (48, 42)


def live(config=None, **kwargs):
    """The live state as the app would build it, with overrides.

    Via Live.of rather than the dataclass defaults: those default the
    ambient bus on, while a real Config now defaults it off, and a helper
    that disagreed with the app made every status assertion test the
    helper instead of the overlay.
    """
    return replace(Live.of(config or Config()), **kwargs)


def settings(config=None, **kwargs):
    return flatten(config_rows(live(config, **kwargs)))


def statuses(config=None, **kwargs):
    return {s.label: s.status for s in settings(config, **kwargs)}


def values(config=None, **kwargs):
    return {s.label: s.value for s in settings(config, **kwargs)}


# -- the table -------------------------------------------------------------


def test_every_row_fits_the_overlay_exactly():
    for setting in settings():
        assert len(row_text(setting)) == CONTENT_WIDTH, setting.label
        assert len(row_text(setting, selected=True)) == CONTENT_WIDTH, setting.label


def test_every_group_heading_fits_too():
    for group in config_rows(live()):
        assert len(group_heading(group.title)) == CONTENT_WIDTH


def test_a_long_label_cannot_widen_a_row():
    from squelch.config_view import Setting

    line = row_text(Setting("x" * 80, "y" * 80, INERT))
    assert len(line) == CONTENT_WIDTH


def test_the_chatter_threshold_is_honoured():
    """build_sessions passes it to every FeedSession."""
    assert statuses()["Chatter threshold"] == LIVE


def test_the_table_shows_configured_values_not_just_defaults():
    shown = values(Config(activity_threshold_dbfs=-35.5, ambient_gain_db=-11.5))
    assert "-35.5" in shown["Chatter threshold"]
    assert "-11.5" in shown["Bus level"]


def test_the_removed_shaping_has_no_rows_left():
    """The gate and the compressor are gone, not shown as bypassed.

    A row reporting a setting that no code reads is the failure mode this
    whole change was about, so their absence is asserted rather than
    assumed. `settings()` covers every group.
    """
    labels = [s.label for s in settings()]
    assert not [label for label in labels if "Gate" in label]
    assert not [label for label in labels if "Comp" in label]


def test_the_volume_row_shows_the_mixer_s_live_value_when_there_is_one():
    """Once it is running the mixer is the authority, not Config."""
    mixer = Mixer(volume=0.35)
    shown = {s.label: s.value for s in flatten(config_rows(Live.of(Config(), mixer)))}
    assert "35%" in shown["Master volume"]


# -- grouping --------------------------------------------------------------


def test_the_settings_are_grouped_by_what_they_shape():
    titles = [group.title for group in config_rows(live())]
    assert titles == ["Output", "Chatter", "Ambient"]


def test_the_ambient_group_holds_only_ambient_settings():
    groups = {g.title: [s.label for s in g.settings] for g in config_rows(live())}
    assert groups["Ambient"] == [
        "Ambient bus",
        "Bus level",
        "Reverb decay",
        "Reverb roll-off",
    ]


def test_the_chatter_group_holds_the_chatter_threshold():
    groups = {g.title: [s.label for s in g.settings] for g in config_rows(live())}
    assert groups["Chatter"] == ["Chatter threshold"]


def test_master_volume_is_alone_at_the_top():
    first = config_rows(live())[0]
    assert first.title == "Output"
    assert [s.label for s in first.settings] == ["Master volume"]


# -- adjustment ------------------------------------------------------------


def test_raising_the_volume():
    after = adjust(live(Config(master_volume=0.5)), VOLUME_KEY, 1)
    assert after.config.master_volume == pytest.approx(0.5 + VOLUME_STEP)


def test_the_volume_stops_at_unity():
    after = adjust(live(Config(master_volume=1.0)), VOLUME_KEY, 1)
    assert after.config.master_volume == 1.0


def test_the_volume_stops_at_silence():
    after = adjust(live(Config(master_volume=0.0)), VOLUME_KEY, -1)
    assert after.config.master_volume == 0.0


def test_the_volume_does_not_drift_off_the_step():
    """Repeated presses must not land on 0.30000000000000004 and make the
    percentage flicker between 30 and 31."""
    state = live(Config(master_volume=0.0))
    for _ in range(7):
        state = adjust(state, VOLUME_KEY, 1)
    for _ in range(3):
        state = adjust(state, VOLUME_KEY, -1)
    assert state.config.master_volume == pytest.approx(0.20)
    assert "20%" in values(state.config)["Master volume"]


def test_an_unknown_key_changes_nothing():
    before = live()
    assert adjust(before, "nonsense", 1) == before


# -- the screen ------------------------------------------------------------


def make_app():
    return SquelchApp(Config(icao="KPDX"), [])


def rendered(app):
    strips = app.screen._compositor.render_strips(Size(*SIZE))
    return [s.text for s in strips], strips


@pytest.mark.asyncio
async def test_c_opens_the_config_overlay():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        assert isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_the_overlay_lists_the_audio_settings():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert "Master volume" in joined
        assert "Chatter threshold" in joined
        assert "Reverb decay" in joined


@pytest.mark.asyncio
async def test_the_overlay_says_which_settings_do_nothing():
    """Almost the whole table is bypassed. A modal that did not say so
    would be claiming a signal chain that is not running."""
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert OFF in joined
        assert "bypassed" in joined
        assert "not applied" in joined


@pytest.mark.asyncio
async def test_only_the_volume_can_be_moved():
    """Everything else reports; it does not control."""
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        assert app.screen.selected.label == "Master volume"
        for _ in range(8):
            await pilot.press("down")
        await pilot.pause()
        assert app.screen.selected.label == "Master volume"


@pytest.mark.asyncio
async def test_escape_closes_the_overlay():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_c_closes_it_again():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()
        assert not isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_the_overlay_stays_within_the_pane():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        too_wide = [
            (w.__class__.__name__, w.id, w.outer_size.width)
            for w in app.screen.query("*")
            if w.outer_size.width > SIZE[0]
        ]
        assert too_wide == []


@pytest.mark.asyncio
async def test_no_row_wraps_onto_a_second_line():
    """Regression guard: getting the width wrong wraps rather than clips.

    The overlay is 44 wide with a border *and* `padding: 0 1`, so the usable
    width is 40, not 42. Sizing rows to 42 turned every one of them into two
    lines and left a column of orphaned status words -- and it still
    contained every string the other tests look for, so only a check on the
    painted line itself catches it.
    """
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        painted = [line for line in rendered(app)[0] if "│" in line]
        orphans = [
            line
            for line in painted
            if line.split("│")[1].strip() in (INERT, FIXED, LIVE)
        ]
        assert orphans == [], f"rows wrapped: {orphans}"
        for setting in settings():
            assert any(
                setting.label in line and setting.status in line for line in painted
            ), f"{setting.label} and its marker are not on one line"


# -- the overlay drives the mixer ------------------------------------------


def app_with_mixer(mixer=None):
    return SquelchApp(Config(icao="KPDX"), [], mixer=mixer or Mixer())


@pytest.mark.asyncio
async def test_right_raises_the_master_volume_on_the_mixer():
    mixer = Mixer(volume=0.5)
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("right")
        await pilot.pause()
        assert mixer.volume == pytest.approx(0.5 + VOLUME_STEP)


@pytest.mark.asyncio
async def test_left_lowers_it():
    mixer = Mixer(volume=0.5)
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("left")
        await pilot.pause()
        assert mixer.volume == pytest.approx(0.5 - VOLUME_STEP)


@pytest.mark.asyncio
async def test_the_overlay_shows_the_new_value_as_it_changes():
    mixer = Mixer(volume=0.5)
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        assert any("50%" in line for line in rendered(app)[0])
        await pilot.press("right")
        await pilot.pause()
        assert any("55%" in line for line in rendered(app)[0])


@pytest.mark.asyncio
async def test_adjusting_without_a_mixer_does_not_raise():
    """The overlay opens outside a real run too."""
    app = SquelchApp(Config(icao="KPDX"), [])
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("right")
        await pilot.press("down")
        await pilot.press("right")
        await pilot.pause()
        assert isinstance(app.screen, ConfigScreen)


@pytest.mark.asyncio
async def test_a_mixer_that_raises_does_not_take_the_pane_down():
    class Angry(Mixer):
        # A property, because volume is a plain attribute on the real mixer
        # and the previous version of this test overrode `set_gate` -- which
        # no longer exists, so it raised nothing and proved nothing. Armed
        # only after __init__, which assigns volume itself.
        armed = False

        @property
        def volume(self):
            return 1.0

        @volume.setter
        def volume(self, _value):
            if self.armed:
                raise RuntimeError("no")

    mixer = Angry()
    mixer.armed = True
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("right")
        await pilot.pause()
        assert isinstance(app.screen, ConfigScreen)

