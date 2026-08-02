"""The per-feed buffer between a network-paced writer and a device-paced
reader.

Twelve ffmpeg processes decode twelve independent streams with no common
clock. Reconciling them against one 16 kHz consumer is this class's entire
job, so the interesting cases are starvation and overflow, not the happy
path.
"""

import numpy as np

from squelch.ringbuffer import RingBuffer


def block(value, n):
    return np.full(n, value, dtype=np.float32)


def test_a_fresh_buffer_is_empty():
    assert RingBuffer(100).available == 0


def test_written_samples_come_back_in_order():
    buf = RingBuffer(100)
    buf.write(np.arange(8, dtype=np.float32))
    out = np.zeros(8, dtype=np.float32)
    assert buf.read_into(out) == 8
    assert np.array_equal(out, np.arange(8, dtype=np.float32))


def test_reading_more_than_written_pads_with_silence():
    """A starved feed contributes silence for the block, nothing more."""
    buf = RingBuffer(100)
    buf.write(block(1.0, 4))
    out = np.full(8, 9.0, dtype=np.float32)
    assert buf.read_into(out) == 4
    assert np.array_equal(out[:4], block(1.0, 4))
    assert np.array_equal(out[4:], np.zeros(4, dtype=np.float32))


def test_reading_an_empty_buffer_yields_pure_silence():
    buf = RingBuffer(100)
    out = np.full(8, 9.0, dtype=np.float32)
    assert buf.read_into(out) == 0
    assert not out.any()


def test_reading_consumes():
    buf = RingBuffer(100)
    buf.write(block(1.0, 8))
    out = np.zeros(4, dtype=np.float32)
    buf.read_into(out)
    assert buf.available == 4


def test_writing_past_capacity_drops_the_oldest():
    buf = RingBuffer(8)
    buf.write(np.arange(8, dtype=np.float32))
    dropped = buf.write(np.arange(100, 104, dtype=np.float32))
    assert dropped == 4
    out = np.zeros(8, dtype=np.float32)
    buf.read_into(out)
    assert np.array_equal(out[-4:], np.arange(100, 104, dtype=np.float32))
    assert np.array_equal(out[:4], np.arange(4, 8, dtype=np.float32))


def test_available_never_exceeds_capacity():
    buf = RingBuffer(8)
    for _ in range(10):
        buf.write(block(1.0, 8))
    assert buf.available == 8


def test_a_write_larger_than_capacity_keeps_only_the_newest():
    buf = RingBuffer(4)
    buf.write(np.arange(10, dtype=np.float32))
    out = np.zeros(4, dtype=np.float32)
    buf.read_into(out)
    assert np.array_equal(out, np.arange(6, 10, dtype=np.float32))


def test_wrapping_preserves_order():
    buf = RingBuffer(8)
    out = np.zeros(6, dtype=np.float32)
    buf.write(np.arange(6, dtype=np.float32))
    buf.read_into(out)
    buf.write(np.arange(10, 16, dtype=np.float32))
    buf.read_into(out)
    assert np.array_equal(out, np.arange(10, 16, dtype=np.float32))


def test_read_into_does_not_allocate_a_new_array():
    buf = RingBuffer(100)
    buf.write(block(1.0, 8))
    out = np.zeros(8, dtype=np.float32)
    before = out.__array_interface__["data"][0]
    buf.read_into(out)
    assert out.__array_interface__["data"][0] == before
