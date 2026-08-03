"""Summing twelve feeds into one stereo bus.

The mixer is the one change that threatens the codebase's per-feed
isolation rule -- twelve output streams become one -- so most of these
tests are about a single feed failing without taking the others with it.
"""

import numpy as np
import pytest

from squelch.dsp import BLOCK, block_dbfs
from squelch.mixer import AMBIENT_GAIN_DB, Mixer


def frame(value=0.5, n=BLOCK):
    return np.full(n, value, dtype=np.float32)


def out_buffer():
    return np.zeros((BLOCK, 2), dtype=np.float32)


def render(mixer, blocks=1):
    out = out_buffer()
    for _ in range(blocks):
        mixer.render(out)
    return out


def test_a_mixer_with_no_channels_renders_silence():
    assert not render(Mixer()).any()


def test_a_muted_channel_is_silent():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = True
    channel.buffer.write(frame())
    assert not render(mixer).any()


def test_an_audible_channel_reaches_both_output_channels():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame())
    out = render(mixer)
    assert out[:, 0].any() and out[:, 1].any()


def test_the_dry_bus_is_centred():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame())
    out = render(mixer)
    assert np.allclose(out[:, 0], out[:, 1])


def test_a_starved_channel_contributes_silence_not_a_crash():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    assert channel.buffer.available == 0
    render(mixer)


def test_one_starved_channel_does_not_silence_the_others():
    """Per-feed isolation, which is the codebase's governing rule."""
    mixer = Mixer()
    starved = mixer.add_channel()
    healthy = mixer.add_channel()
    starved.muted = healthy.muted = False
    healthy.buffer.write(frame())
    assert render(mixer).any()


def test_two_audible_channels_sum():
    mixer = Mixer()
    out = out_buffer()
    one = mixer.add_channel()
    one.muted = False
    one.buffer.write(frame(0.2))
    mixer.render(out)
    single = float(np.abs(out[:, 0]).max())

    mixer = Mixer()
    for _ in range(2):
        channel = mixer.add_channel()
        channel.muted = False
        channel.buffer.write(frame(0.2))
    mixer.render(out)
    assert float(np.abs(out[:, 0]).max()) > single


# -- the ambient bus -------------------------------------------------------


def test_an_ambient_only_channel_is_audible():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = True
    channel.ambient = True
    channel.buffer.write(frame())
    assert render(mixer, blocks=4).any(), "ambient routing is independent of mute"


def test_the_ambient_bus_sits_below_the_dry_bus():
    def peak(*, ambient):
        mixer = Mixer()
        channel = mixer.add_channel()
        channel.muted = ambient
        channel.ambient = ambient
        channel.buffer.write(frame())
        out = out_buffer()
        best = 0.0
        for _ in range(8):
            channel.buffer.write(frame())
            mixer.render(out)
            best = max(best, float(np.abs(out).max()))
        return best

    assert peak(ambient=True) < peak(ambient=False)


def test_the_ambient_gain_is_minus_eight_db():
    assert AMBIENT_GAIN_DB == -8.0


def test_two_ambient_feeds_are_panned_apart():
    mixer = Mixer()
    for _ in range(2):
        channel = mixer.add_channel()
        channel.muted = True
        channel.ambient = True
    mixer._channels[0].buffer.write(frame())
    out = render(mixer, blocks=4)
    assert not np.allclose(out[:, 0], out[:, 1]), "one feed left of centre"


def test_a_feed_can_be_on_both_buses():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.ambient = True
    channel.buffer.write(frame())
    assert render(mixer, blocks=4).any()


# -- metering --------------------------------------------------------------


def test_the_channel_reports_its_post_compression_level():
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame(0.05))
    render(mixer)
    assert channel.level_dbfs > block_dbfs(frame(0.05)), "makeup gain is included"


def test_a_muted_channel_still_meters():
    """Muting is an audio gate, not a pause."""
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = True
    channel.buffer.write(frame())
    render(mixer)
    assert channel.level_dbfs > -96.0


# -- real-time discipline --------------------------------------------------


class _NoTemporaries(np.ndarray):
    """An array that refuses to be an input to a ufunc without `out=`.

    Catches what a tracemalloc snapshot cannot. Snapshots measure *live*
    memory, and a per-block temporary is freed before the next snapshot is
    taken -- so `amb_l += shaped * gain` shows no growth at all and the
    leak test below passes with the scratch buffer removed entirely.
    """

    def __array_ufunc__(self, ufunc, method, *inputs, **kwargs):
        if kwargs.get("out") is None:
            raise AssertionError(
                f"{ufunc.__name__} was called without out=, allocating a "
                f"temporary in the audio callback"
            )
        # Drop back to plain ndarrays before delegating; a ufunc handed a
        # subclass it does not know returns NotImplemented.
        plain = [
            x.view(np.ndarray) if isinstance(x, _NoTemporaries) else x
            for x in inputs
        ]
        kwargs["out"] = tuple(
            o.view(np.ndarray) if isinstance(o, _NoTemporaries) else o
            for o in kwargs["out"]
        )
        return getattr(ufunc, method)(*plain, **kwargs)


def test_render_creates_no_temporaries():
    """The callback is a real-time context. Allocation there is a bug."""
    mixer = Mixer()
    for index in range(4):
        channel = mixer.add_channel()
        channel.muted = False
        channel.ambient = index % 2 == 0
        # Both buses, so the pan path is exercised as well as the dry sum.
        channel._raw = channel._raw.view(_NoTemporaries)
        channel._shaped = channel._shaped.view(_NoTemporaries)
    out = out_buffer()
    for _ in range(4):
        for channel in mixer._channels:
            channel.buffer.write(frame())
        mixer.render(out)


def test_render_retains_nothing():
    """A per-block allocation that is *kept* is a leak over a long session."""
    import tracemalloc

    mixer = Mixer()
    for index in range(12):
        channel = mixer.add_channel()
        channel.muted = False
        # Half on the ambient bus too: the pan path is where a temporary is
        # most likely to creep in (`shaped * scalar` allocates one per feed
        # per block), and a test with no ambient channels never runs it --
        # it passes with the scratch buffer removed entirely.
        channel.ambient = index % 2 == 0
    out = out_buffer()
    for _ in range(20):
        for channel in mixer._channels:
            channel.buffer.write(frame())
        mixer.render(out)

    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    for _ in range(50):
        for channel in mixer._channels:
            channel.buffer.write(frame())
        mixer.render(out)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    grown = sum(s.size_diff for s in after.compare_to(before, "filename"))
    assert grown < 16_000, f"render allocated {grown} bytes"


def test_render_writes_in_place():
    mixer = Mixer()
    out = out_buffer()
    before = out.__array_interface__["data"][0]
    mixer.render(out)
    assert out.__array_interface__["data"][0] == before


def test_a_channel_whose_chain_raises_does_not_break_the_block():
    mixer = Mixer()
    broken = mixer.add_channel()
    healthy = mixer.add_channel()
    broken.muted = healthy.muted = False
    healthy.buffer.write(frame())

    def explode(_block, _out):
        raise RuntimeError("boom")

    broken._compressor.process = explode
    out = out_buffer()
    mixer.render(out)
    assert out.any(), "the healthy feed must still be heard"


# -- the stream ------------------------------------------------------------


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        pass


def test_start_opens_a_stereo_stream_at_the_engine_rate():
    made = {}

    def factory(**kwargs):
        made.update(kwargs)
        return FakeStream(**kwargs)

    mixer = Mixer()
    mixer.start(stream_factory=factory)
    assert made["channels"] == 2
    assert made["samplerate"] == 16_000
    assert made["blocksize"] == BLOCK
    assert mixer.failed is False


def test_a_device_that_will_not_open_is_recorded_not_raised():
    """Losing sound must not stop the pane metering."""

    def factory(**kwargs):
        raise RuntimeError("no device")

    mixer = Mixer()
    mixer.start(stream_factory=factory)
    assert mixer.failed is True


def test_stop_is_safe_before_start_and_twice():
    mixer = Mixer()
    mixer.stop()
    mixer.start(stream_factory=lambda **kw: FakeStream(**kw))
    mixer.stop()
    mixer.stop()


class RecordingStream:
    """A PortAudio-ish stream that records the order of operations."""

    def __init__(self, **kwargs):
        self.calls = []

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")


def test_stop_detaches_the_stream_before_closing_it():
    """A concurrent callback must see None, not a stream mid-close.

    Carried over from Player, which owned one stream per feed before the
    mixer owned one for all of them. The race is the same and the stakes
    are higher: the callback can be inside render() when the UI thread
    calls stop(), and PortAudio is not obliged to survive being closed
    underneath it. The check runs from inside the stream's own stop(),
    which is the exact instant the window used to be open.
    """
    mixer = Mixer()
    stream = RecordingStream()
    observed = {}

    def stop():
        observed["stream_attr"] = mixer._stream
        stream.calls.append("stop")

    stream.stop = stop
    mixer._stream = stream
    mixer.stop()

    assert observed["stream_attr"] is None, (
        "the stream reference must be cleared before the stream is stopped, "
        "so a callback racing this call short-circuits instead of rendering "
        "into a stream being torn down"
    )
    assert stream.calls == ["stop", "close"]


def test_stop_is_idempotent_and_never_raises():
    """stop() runs from main()'s finally clause; it must not add a crash."""

    class ExplodingStream(RecordingStream):
        def stop(self):
            raise RuntimeError("PortAudio is unhappy")

    mixer = Mixer()
    mixer.stop()  # never started
    mixer._stream = ExplodingStream()
    mixer.stop()
    mixer.stop()
    assert mixer._stream is None


# -- master volume ---------------------------------------------------------


def loud_channel(mixer):
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame())
    return channel


def test_unity_volume_is_the_default():
    assert Mixer().volume == 1.0


def test_volume_scales_the_output():
    quiet, loud = Mixer(volume=0.25), Mixer(volume=1.0)
    for mixer in (quiet, loud):
        loud_channel(mixer)
    out_q, out_l = out_buffer(), out_buffer()
    quiet.render(out_q)
    loud.render(out_l)
    assert float(np.abs(out_q).max()) < float(np.abs(out_l).max())


def test_zero_volume_is_silence():
    mixer = Mixer(volume=0.0)
    loud_channel(mixer)
    assert not render(mixer).any()


def test_volume_can_be_changed_at_runtime():
    mixer = Mixer()
    channel = loud_channel(mixer)
    before = float(np.abs(render(mixer)).max())
    mixer.volume = 0.1
    channel.buffer.write(frame())
    after = float(np.abs(render(mixer)).max())
    assert after < before


def test_volume_cannot_push_the_output_past_full_scale():
    """Applied before the clip, so turning it up cannot exceed the range."""
    mixer = Mixer(volume=8.0)
    for _ in range(4):
        loud_channel(mixer)
    out = render(mixer)
    assert float(np.abs(out).max()) <= 1.0


def test_volume_does_not_allocate_in_the_callback():
    mixer = Mixer(volume=0.5)
    for _ in range(3):
        channel = loud_channel(mixer)
        channel._raw = channel._raw.view(_NoTemporaries)
        channel._shaped = channel._shaped.view(_NoTemporaries)
    out = out_buffer()
    for _ in range(3):
        for channel in mixer._channels:
            channel.buffer.write(frame())
        mixer.render(out)


# -- the gate --------------------------------------------------------------


def test_the_gate_defaults_to_the_dsp_value():
    from squelch.dsp import GATE_OPEN_DBFS

    assert Mixer().gate_dbfs == GATE_OPEN_DBFS


def test_a_configured_gate_reaches_new_channels():
    mixer = Mixer(gate_dbfs=-30.0)
    channel = mixer.add_channel()
    assert channel._compressor.gate_dbfs == -30.0


def test_setting_the_gate_reaches_channels_that_already_exist():
    mixer = Mixer()
    channel = mixer.add_channel()
    mixer.set_gate(-25.0)
    assert channel._compressor.gate_dbfs == -25.0
    assert mixer.gate_dbfs == -25.0


def test_setting_the_gate_also_reaches_channels_added_afterwards():
    """Feeds start on their own threads, so some arrive after the change."""
    mixer = Mixer()
    mixer.set_gate(-25.0)
    late = mixer.add_channel()
    assert late._compressor.gate_dbfs == -25.0


def test_the_gate_threshold_changes_what_is_boosted():
    """A -35 dBFS signal is gated at -30 and open at -50."""
    from squelch.dsp import BLOCK as DSP_BLOCK
    from squelch.dsp import Compressor, block_dbfs as level

    def gain_after(threshold):
        comp = Compressor(gate_open=threshold, gate_close=threshold)
        out = np.zeros(DSP_BLOCK, dtype=np.float32)
        tone = np.full(DSP_BLOCK, 10 ** (-35.0 / 20), dtype=np.float32)
        for _ in range(60):
            comp.process(tone, out)
        return comp.gain_db

    assert gain_after(-50.0) > gain_after(-30.0)


def test_the_gate_is_enabled_by_default():
    assert Mixer().gate_enabled is True


def test_a_disabled_gate_reaches_new_channels():
    mixer = Mixer(gate_enabled=False)
    assert mixer.add_channel()._compressor.gate_enabled is False


def test_disabling_reaches_channels_both_sides_of_the_call():
    mixer = Mixer()
    early = mixer.add_channel()
    mixer.set_gate_enabled(False)
    late = mixer.add_channel()
    assert early._compressor.gate_enabled is False
    assert late._compressor.gate_enabled is False


def test_a_disabled_gate_stops_holding_the_boost_back():
    """The whole point: a quiet signal is lifted instead of gated."""
    from squelch.dsp import BLOCK as DSP_BLOCK
    from squelch.dsp import Compressor

    def gain_after(**kw):
        comp = Compressor(**kw)
        out = np.zeros(DSP_BLOCK, dtype=np.float32)
        tone = np.full(DSP_BLOCK, 10 ** (-70.0 / 20), dtype=np.float32)
        for _ in range(120):
            comp.process(tone, out)
        return comp.gain_db

    assert gain_after(gate_enabled=False) > gain_after(gate_enabled=True)


def test_switching_the_gate_off_does_not_step_the_gain():
    """It rides the existing ramp, so toggling mid-transmission cannot click."""
    from squelch.dsp import BLOCK as DSP_BLOCK
    from squelch.dsp import Compressor

    comp = Compressor()
    out = np.zeros(DSP_BLOCK, dtype=np.float32)
    tone = np.full(DSP_BLOCK, 10 ** (-70.0 / 20), dtype=np.float32)
    for _ in range(120):
        comp.process(tone, out)
    before = comp.gain_db
    comp.set_gate_enabled(False)
    comp.process(tone, out)
    assert abs(comp.gain_db - before) < 12.0, "one block cannot jump the range"


# -- bypassing the compressor ----------------------------------------------


def test_the_compressor_is_enabled_by_default():
    assert Mixer().compressor_enabled is True


def test_a_bypassed_compressor_reaches_channels_both_sides_of_the_call():
    mixer = Mixer()
    early = mixer.add_channel()
    mixer.set_compressor_enabled(False)
    late = mixer.add_channel()
    assert early._compressor.enabled is False
    assert late._compressor.enabled is False


def test_a_configured_bypass_reaches_new_channels():
    assert Mixer(compressor_enabled=False).add_channel()._compressor.enabled is False


def test_bypassed_is_unity_not_makeup_only():
    """The point of the switch is to hear the feed untouched."""
    from squelch.dsp import BLOCK as DSP_BLOCK
    from squelch.dsp import Compressor, block_dbfs

    tone = np.full(DSP_BLOCK, 10 ** (-20.0 / 20), dtype=np.float32)
    comp = Compressor(enabled=False)
    out = np.zeros(DSP_BLOCK, dtype=np.float32)
    for _ in range(60):
        comp.process(tone, out)
    assert comp.gain_db == 0.0
    assert block_dbfs(out) == pytest.approx(-20.0, abs=0.2)


def test_bypassed_gain_never_moves():
    """Static by construction: this is what a choppy compressor is not."""
    from squelch.dsp import BLOCK as DSP_BLOCK
    from squelch.dsp import Compressor

    comp = Compressor(enabled=False)
    out = np.zeros(DSP_BLOCK, dtype=np.float32)
    gains = []
    for level in (-60.0, -10.0, -45.0, -5.0, -80.0):
        tone = np.full(DSP_BLOCK, 10 ** (level / 20), dtype=np.float32)
        for _ in range(10):
            comp.process(tone, out)
            gains.append(comp.gain_db)
    assert set(gains) == {0.0}


def test_switching_the_compressor_off_does_not_step_the_gain():
    """It rides the ramp, so an A/B mid-transmission cannot click."""
    from squelch.dsp import BLOCK as DSP_BLOCK
    from squelch.dsp import Compressor

    comp = Compressor()
    out = np.zeros(DSP_BLOCK, dtype=np.float32)
    tone = np.full(DSP_BLOCK, 10 ** (-30.0 / 20), dtype=np.float32)
    for _ in range(60):
        comp.process(tone, out)
    before = comp.gain_db
    comp.set_enabled(False)
    comp.process(tone, out)
    assert abs(comp.gain_db - before) < 12.0


def test_the_envelope_keeps_tracking_while_bypassed():
    """So coming back on picks up from a current reading, not a stale one."""
    from squelch.dsp import BLOCK as DSP_BLOCK
    from squelch.dsp import Compressor

    comp = Compressor(enabled=False)
    out = np.zeros(DSP_BLOCK, dtype=np.float32)
    loud = np.full(DSP_BLOCK, 10 ** (-6.0 / 20), dtype=np.float32)
    for _ in range(60):
        comp.process(loud, out)
    comp.set_enabled(True)
    comp.process(loud, out)
    # A stale -96 envelope would ask for the full range limit here.
    assert comp.gain_db < 10.0
