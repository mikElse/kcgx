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
