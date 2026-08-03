"""Summing twelve feeds into one stereo bus.

The mixer is the one change that threatens the codebase's per-feed
isolation rule -- twelve output streams become one -- so most of these
tests are about a single feed failing without taking the others with it.
"""

import numpy as np
import pytest

from squelch.dsp import BLOCK, SAMPLE_RATE, block_dbfs
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


def test_the_channel_reports_the_level_it_contributes():
    """Nothing sits between the buffer and the sum, so the meter reads the
    decoded level exactly -- it used to read it post-makeup."""
    mixer = Mixer()
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame(0.05))
    render(mixer)
    assert channel.level_dbfs == pytest.approx(block_dbfs(frame(0.05)), abs=0.01)


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


def test_a_reverb_that_raises_does_not_break_the_block():
    """The last remaining failure path inside render.

    There used to be a second one, around each channel's compressor. With
    the compressor gone a channel is a ring buffer and nothing else, so the
    reverb is the only thing left in here that can throw -- and a broken
    ambient bus must still cost the dry bus nothing.
    """
    mixer = Mixer()
    dry = mixer.add_channel()
    ambient = mixer.add_channel()
    dry.muted = False
    ambient.muted = True
    ambient.ambient = True
    dry.buffer.write(frame())
    ambient.buffer.write(frame())

    def explode(*_args):
        raise RuntimeError("boom")

    mixer._reverb.process = explode
    out = out_buffer()
    mixer.render(out)
    assert out.any(), "the dry feed must still be heard"


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
    out = out_buffer()
    for _ in range(3):
        for channel in mixer._channels:
            channel.buffer.write(frame())
        mixer.render(out)


# -- the ambient bus bypass ------------------------------------------------


def test_a_bypassed_ambient_bus_stays_silent_even_when_a_feed_is_routed():
    """[A] still marks a feed; the mixer just does not act on it."""
    mixer = Mixer(ambient_enabled=False)
    channel = mixer.add_channel()
    channel.muted = True
    channel.ambient = True
    for _ in range(8):
        channel.buffer.write(frame())
    assert not render(mixer, blocks=8).any()


def test_the_ambient_bus_can_be_switched_back_on():
    mixer = Mixer(ambient_enabled=False)
    channel = mixer.add_channel()
    channel.muted = True
    channel.ambient = True
    mixer.set_ambient_enabled(True)
    for _ in range(8):
        channel.buffer.write(frame())
    assert render(mixer, blocks=8).any()


def test_bypassing_the_ambient_bus_leaves_the_dry_bus_alone():
    mixer = Mixer(ambient_enabled=False)
    channel = mixer.add_channel()
    channel.muted = False
    channel.buffer.write(frame())
    assert render(mixer).any()


def test_with_everything_bypassed_the_output_is_the_input():
    """The whole point: what reaches the device is the decoded feed.

    No ambient bus, unity volume -- so a block written in comes back out
    sample for sample. There is no longer anything else it could pass
    through.
    """
    mixer = Mixer(ambient_enabled=False, volume=1.0)
    channel = mixer.add_channel()
    channel.muted = False
    written = frame(0.3)
    channel.buffer.write(written)
    out = render(mixer)
    assert np.allclose(out[:, 0], written, atol=1e-6)
    assert np.allclose(out[:, 1], written, atol=1e-6)


def test_master_volume_is_the_only_thing_left_shaping_it():
    mixer = Mixer(ambient_enabled=False, volume=0.5)
    channel = mixer.add_channel()
    channel.muted = False
    written = frame(0.4)
    channel.buffer.write(written)
    out = render(mixer)
    assert np.allclose(out[:, 0], written * 0.5, atol=1e-6)


def test_a_mixer_built_from_the_shipped_config_does_nothing_to_the_signal():
    """End to end against the real defaults, not hand-passed flags."""
    from squelch.config import Config as RealConfig

    config = RealConfig()
    mixer = Mixer(
        volume=config.master_volume,
        ambient_enabled=config.ambient_enabled,
    )
    channel = mixer.add_channel()
    channel.muted = False
    channel.ambient = True  # routed, and still ignored
    written = frame(0.25)
    channel.buffer.write(written)
    out = render(mixer)
    assert np.allclose(out[:, 0], written, atol=1e-6)
    assert np.allclose(out[:, 1], written, atol=1e-6)


# -- how much audio survives the buffer ------------------------------------
#
# The mixer replaced twelve blocking `RawOutputStream.write` calls with one
# callback pulling from a ring buffer. That moved the elasticity that used
# to live in the device's own buffer into `BUFFER_SECONDS`, and it was set
# to 0.5 -- about a third of what a LiveATC burst carries. The result was
# 61% of blocks reaching the device as silence. These pin the fix.


# Gaps between bursts, in seconds, cycled deterministically. Shaped after
# the measured feed: a median around a second with occasional long gaps,
# the worst observed being 2.5 s.
BURST_GAPS = (0.6, 1.0, 2.5, 0.8, 1.4, 0.7, 2.0, 1.1)
# The feed sends slightly faster than the device clock, which is what lets
# a buffer build the backlog that covers the next gap. Measured at 1.049x.
SOURCE_RATE = 1.05


def burst_source(seconds):
    """Arrival times and sizes matching a measured LiveATC feed.

    93% of ffmpeg's reads arrive less than 1 ms after the previous one, so
    a burst is modelled as instantaneous -- at a 16 ms block rate it is.

    Each burst carries the audio that accumulated since the last one, which
    is the detail that matters: a source delivering less than that is
    simply slower than realtime and starves at *any* buffer size, which is
    what an earlier version of this helper accidentally modelled.
    """
    events = []
    at = 0.0
    index = 0
    while at < seconds:
        gap = BURST_GAPS[index % len(BURST_GAPS)]
        index += 1
        at += gap
        events.append((at, int(gap * SOURCE_RATE * SAMPLE_RATE)))
    return events


def drain(mixer, channel, events, seconds, *, settle_s=20.0):
    """Run the real callback cadence against a bursty producer.

    Returns (blocks, silent_blocks, samples_dropped). No wall clock and no
    device: block N stands for time N * BLOCK / SAMPLE_RATE.

    The first `settle_s` is excluded from the counts. The source runs only
    5% faster than the device clock, so backlog accrues at 0.05 s per
    second and covering a 2.5 s gap takes the better part of a minute from
    an empty buffer -- whereas the real feed opens with a multi-second
    burst that seeds it at once. Counting the ramp would measure a startup
    artefact of this helper rather than whether the audio stutters.
    """
    period = BLOCK / SAMPLE_RATE
    out = out_buffer()
    pending = list(events)
    dropped = blocks = silent = 0
    for index in range(int(seconds / period)):
        now = index * period
        while pending and pending[0][0] <= now:
            _at, count = pending.pop(0)
            written = channel.buffer.write(frame(0.5, count))
            if now >= settle_s:
                dropped += written
        counting = now >= settle_s
        if counting:
            blocks += 1
            if channel.buffer.available == 0:
                silent += 1
        mixer.render(out)
    return blocks, silent, dropped


def test_the_buffer_holds_more_than_one_burst():
    """The governing constraint, stated directly.

    A buffer smaller than a burst cannot do anything but discard most of
    it -- no arrival timing, no prefill, and no drop policy can rescue it.
    """
    from squelch.mixer import BUFFER_SECONDS

    assert BUFFER_SECONDS >= 2.4, "a burst is ~1.2 s; hold at least two"


def test_a_bursty_feed_is_not_chopped_into_silence():
    mixer = Mixer(ambient_enabled=False)
    channel = mixer.add_channel()
    channel.muted = False
    blocks, silent, _dropped = drain(mixer, channel, burst_source(90.0), 90.0)
    # The gaps between bursts are covered by the backlog the burst left.
    assert silent / blocks < 0.01, (
        f"{100 * silent / blocks:.0f}% of blocks reached the device as silence"
    )


def test_a_bursty_feed_does_not_have_most_of_it_thrown_away():
    mixer = Mixer(ambient_enabled=False)
    channel = mixer.add_channel()
    channel.muted = False
    _blocks, _silent, dropped = drain(mixer, channel, burst_source(90.0), 90.0)
    written = sum(count for at, count in burst_source(90.0) if at >= 20.0)
    assert dropped / written < 0.06, (
        f"{100 * dropped / written:.0f}% of the audio was dropped on overflow"
    )


def test_half_a_second_of_buffer_would_still_fail_both():
    """The regression, reproduced -- so the two tests above are known to be
    capable of failing, rather than passing on a technicality."""
    mixer = Mixer(ambient_enabled=False, buffer_seconds=0.5)
    channel = mixer.add_channel()
    channel.muted = False
    blocks, silent, dropped = drain(mixer, channel, burst_source(90.0), 90.0)
    written = sum(count for at, count in burst_source(90.0) if at >= 20.0)
    assert silent / blocks > 0.30
    assert dropped / written > 0.30


def test_the_capacity_follows_the_configured_seconds():
    assert Mixer(buffer_seconds=2.0).add_channel().buffer.capacity == 2 * SAMPLE_RATE


def test_a_capacity_below_one_block_is_floored():
    """Otherwise every read starves and the feed is silence, not audio."""
    channel = Mixer(buffer_seconds=0.0).add_channel()
    assert channel.buffer.capacity >= BLOCK
