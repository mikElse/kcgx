"""The config overlay.

The table is a pure function of a Config, so most of this needs no app.
The point of the screen is honesty about which keys are actually honoured,
so that is what most of these assert.
"""

from __future__ import annotations

import pytest
from textual.geometry import Size

from squelch import dsp
from squelch.app import SquelchApp
from squelch.config import Config
from squelch.config_view import (
    CONTENT_WIDTH,
    FIXED,
    GATE_ENABLED_KEY,
    GATE_FLOOR,
    GATE_KEY,
    GATE_STEP,
    OFF,
    INERT,
    LIVE,
    VOLUME_KEY,
    VOLUME_STEP,
    ConfigScreen,
    Live,
    adjust,
    adjustable_settings,
    config_rows,
    flatten,
    group_heading,
    row_text,
)
from squelch.mixer import Mixer
from squelch.mixer import AMBIENT_GAIN_DB

SIZE = (48, 42)


def live(config=None, **kwargs):
    return Live(config or Config(),
                kwargs.pop("gate_dbfs", (config or Config()).gate_dbfs),
                kwargs.pop("gate_enabled", True))


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


def test_the_compressor_keys_are_marked_inert():
    """They are read into Config and consumed by nothing: Channel builds its
    Compressor from the dsp module defaults."""
    marks = statuses()
    for label in (
        "Comp threshold",
        "Comp ratio",
        "Comp makeup",
        "Comp range limit",
        "Bus level (set)",
    ):
        assert marks[label] == INERT, label


def test_what_is_compiled_in_is_marked_fixed():
    marks = statuses()
    for label in ("Reverb decay", "Reverb roll-off", "Bus level (in use)"):
        assert marks[label] == FIXED, label


def test_the_table_shows_configured_values_not_just_defaults():
    shown = values(Config(compressor_ratio=2.5, activity_threshold_dbfs=-35.5))
    assert "2.5" in shown["Comp ratio"]
    assert "-35.5" in shown["Chatter threshold"]


def test_the_ambient_rows_show_the_gap_between_asked_and_applied():
    """The clearest illustration of what `inert` means."""
    shown = values(Config(ambient_gain_db=-20.0))
    assert "-20.0" in shown["Bus level (set)"]
    assert f"{AMBIENT_GAIN_DB:.1f}" in shown["Bus level (in use)"]
    assert shown["Bus level (set)"] != shown["Bus level (in use)"]


def test_the_gate_row_defaults_to_the_measured_value():
    assert f"{dsp.GATE_OPEN_DBFS:.1f}" in values()["Gate threshold"]


def test_the_gate_row_shows_the_mixer_s_live_value_when_there_is_one():
    """The gate lives on the mixer once it is running, not in Config."""
    assert "-30.0" in values(gate_dbfs=-30.0)["Gate threshold"]


# -- grouping --------------------------------------------------------------


def test_the_settings_are_grouped_by_what_they_shape():
    titles = [group.title for group in config_rows(live())]
    assert titles == ["Output", "Chatter", "Ambient"]


def test_the_ambient_group_holds_only_ambient_settings():
    groups = {g.title: [s.label for s in g.settings] for g in config_rows(live())}
    assert groups["Ambient"] == [
        "Bus level (set)",
        "Bus level (in use)",
        "Reverb decay",
        "Reverb roll-off",
    ]


def test_the_chatter_group_holds_the_gate_and_the_compressor():
    groups = {g.title: [s.label for s in g.settings] for g in config_rows(live())}
    assert "Gate" in groups["Chatter"]
    assert "Comp ratio" in groups["Chatter"]
    assert "Reverb decay" not in groups["Chatter"]


def test_master_volume_is_alone_at_the_top():
    first = config_rows(live())[0]
    assert first.title == "Output"
    assert [s.label for s in first.settings] == ["Master volume"]


# -- adjustment ------------------------------------------------------------


def test_the_adjustable_settings_are_volume_and_the_gate():
    assert [s.label for s in adjustable_settings(config_rows(live()))] == [
        "Master volume",
        "Gate",
        "Gate threshold",
    ]


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


def test_moving_the_gate():
    assert adjust(live(), GATE_KEY, 1).gate_dbfs == -55.0 + GATE_STEP


def test_the_gate_stops_at_the_floor():
    state = adjust(live(gate_dbfs=GATE_FLOOR), GATE_KEY, -1)
    assert state.gate_dbfs == GATE_FLOOR


def test_adjusting_the_gate_leaves_the_volume_alone():
    state = adjust(live(Config(master_volume=0.6)), GATE_KEY, 1)
    assert state.config.master_volume == 0.6
    assert state.gate_dbfs != -55.0


def test_an_unknown_key_changes_nothing():
    before = live()
    assert adjust(before, "nonsense", 1) == before


# -- switching the gate off ------------------------------------------------


def test_the_gate_starts_on():
    assert values()["Gate"] == "on"


def test_either_direction_flips_it():
    """Two states, so making one arrow inert would just be a dead key."""
    on = live()
    assert adjust(on, GATE_ENABLED_KEY, 1).gate_enabled is False
    assert adjust(on, GATE_ENABLED_KEY, -1).gate_enabled is False
    off = adjust(on, GATE_ENABLED_KEY, 1)
    assert adjust(off, GATE_ENABLED_KEY, 1).gate_enabled is True


def test_the_row_reads_off_when_it_is_off():
    assert values(gate_enabled=False)["Gate"] == OFF


def test_the_threshold_is_marked_off_but_still_readable():
    """The number stays visible so you know what it returns to."""
    shown = settings(gate_enabled=False)
    threshold = next(s for s in shown if s.label == "Gate threshold")
    assert threshold.status == OFF
    assert "-55.0" in threshold.value


def test_the_threshold_can_still_be_moved_while_off():
    state = adjust(live(gate_enabled=False), GATE_KEY, 1)
    assert state.gate_dbfs == -55.0 + GATE_STEP
    assert state.gate_enabled is False


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
        assert "Comp ratio" in joined
        assert "Chatter threshold" in joined


@pytest.mark.asyncio
async def test_the_overlay_says_which_settings_do_nothing_yet():
    """Half the table is inert. A modal that did not say so would lie."""
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.pause()
        joined = "\n".join(rendered(app)[0])
        assert INERT in joined
        assert "not yet applied" in joined


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
async def test_down_twice_then_right_moves_the_threshold_not_the_volume():
    mixer = Mixer(volume=0.5, gate_dbfs=-55.0)
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        # Two down: volume, then the gate on/off row, then the threshold.
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("right")
        await pilot.pause()
        assert mixer.gate_dbfs == -55.0 + GATE_STEP
        assert mixer.volume == 0.5, "the volume must not move with the gate"


@pytest.mark.asyncio
async def test_one_down_then_right_switches_the_gate_off():
    """The control that exists because the gate sounds choppy."""
    mixer = Mixer()
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("down")
        await pilot.press("right")
        await pilot.pause()
        assert mixer.gate_enabled is False


@pytest.mark.asyncio
async def test_switching_the_gate_off_reaches_a_running_feed():
    mixer = Mixer()
    channel = mixer.add_channel()
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("down")
        await pilot.press("right")
        await pilot.pause()
        assert channel._compressor.gate_enabled is False


@pytest.mark.asyncio
async def test_the_overlay_shows_the_gate_as_off():
    mixer = Mixer()
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("down")
        await pilot.press("right")
        await pilot.pause()
        assert any("off" in line for line in rendered(app)[0])


@pytest.mark.asyncio
async def test_the_gate_change_reaches_a_running_feed():
    """The whole point of `adjustable`: it has to touch the audio path."""
    mixer = Mixer(gate_dbfs=-55.0)
    channel = mixer.add_channel()
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("down")
        await pilot.press("down")
        for _ in range(5):
            await pilot.press("right")
        await pilot.pause()
        assert channel._compressor.gate_dbfs == -50.0


@pytest.mark.asyncio
async def test_the_selection_cannot_run_off_either_end():
    mixer = Mixer()
    app = app_with_mixer(mixer)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        for _ in range(6):
            await pilot.press("up")
        await pilot.pause()
        assert app.screen.selected.key == VOLUME_KEY
        for _ in range(6):
            await pilot.press("down")
        await pilot.pause()
        assert app.screen.selected.key == GATE_KEY


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
        def set_gate(self, dbfs):
            raise RuntimeError("no")

    app = app_with_mixer(Angry())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c")
        await pilot.press("right")
        await pilot.pause()
        assert isinstance(app.screen, ConfigScreen)
