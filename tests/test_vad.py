import math
import struct

import pytest

from squelch.vad import (
    FRAME_BYTES,
    SAMPLE_RATE,
    Segmenter,
    Utterance,
    rms_dbfs,
)


def tone_frame(amplitude: int = 12000) -> bytes:
    """One 20 ms frame of 440 Hz tone — reliably detected as speech."""
    samples = [
        int(amplitude * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE))
        for i in range(FRAME_BYTES // 2)
    ]
    return struct.pack(f"<{len(samples)}h", *samples)


def silence_frame() -> bytes:
    return b"\x00" * FRAME_BYTES


def drive(seg: Segmenter, frames: list[bytes]) -> list[Utterance]:
    out = []
    for f in frames:
        u = seg.feed(f)
        if u is not None:
            out.append(u)
    return out


def test_rms_dbfs_silence_is_floor():
    assert rms_dbfs(silence_frame()) <= -90.0


def test_rms_dbfs_full_scale_is_near_zero():
    loud = struct.pack("<h", 32000) * (FRAME_BYTES // 2)
    assert -1.5 < rms_dbfs(loud) <= 0.0


def test_rms_dbfs_orders_signals_correctly():
    assert rms_dbfs(silence_frame()) < rms_dbfs(tone_frame(500)) < rms_dbfs(tone_frame(20000))


def test_rejects_wrong_frame_size():
    seg = Segmenter()
    with pytest.raises(ValueError):
        seg.feed(b"\x00" * 100)


def test_silence_alone_yields_nothing():
    seg = Segmenter()
    assert drive(seg, [silence_frame()] * 100) == []


def test_silence_after_speech_is_not_treated_as_speech():
    """Regression: WebRTC VAD is stateful.

    Measured on this machine, raw is_speech() reports the first 6 frames of
    pure digital silence following 25 loud frames as speech. That tail would
    corrupt every hangover measurement, so the energy gate is mandatory.
    Without the gate this test fails; do not remove it.
    """
    seg = Segmenter(hangover_ms=200, min_ms=100)  # hangover = 10 frames
    out = drive(seg, [tone_frame()] * 25 + [silence_frame()] * 12)
    assert len(out) == 1
    # The utterance must end at the last tone frame (0.5 s), not 120 ms later.
    assert out[0].end_s == pytest.approx(0.5, abs=0.02)


def test_gate_rejects_low_level_hiss():
    """Below-gate noise must never open an utterance."""
    seg = Segmenter(hangover_ms=200, min_ms=100, gate_dbfs=-70.0)
    assert drive(seg, [tone_frame(amplitude=3)] * 100) == []


def test_single_burst_emits_one_utterance():
    seg = Segmenter(hangover_ms=200, min_ms=100)
    # 1 s of tone, then enough silence to close it.
    frames = [tone_frame()] * 50 + [silence_frame()] * 30
    out = drive(seg, frames)
    assert len(out) == 1
    assert out[0].duration_s == pytest.approx(1.0, abs=0.25)
    assert len(out[0].pcm) % FRAME_BYTES == 0


def test_short_pause_does_not_split_utterance():
    """A controller pausing mid-clearance must stay one block."""
    seg = Segmenter(hangover_ms=600, min_ms=100)
    frames = (
        [tone_frame()] * 25
        + [silence_frame()] * 10   # 200 ms gap, under the 600 ms hangover
        + [tone_frame()] * 25
        + [silence_frame()] * 40   # 800 ms, over hangover — closes
    )
    out = drive(seg, frames)
    assert len(out) == 1


def test_long_pause_splits_into_two():
    seg = Segmenter(hangover_ms=300, min_ms=100)
    frames = (
        [tone_frame()] * 25
        + [silence_frame()] * 40
        + [tone_frame()] * 25
        + [silence_frame()] * 40
    )
    assert len(drive(seg, frames)) == 2


def test_squelch_click_below_min_duration_is_dropped():
    seg = Segmenter(hangover_ms=200, min_ms=400)
    frames = [tone_frame()] * 5 + [silence_frame()] * 30  # 100 ms burst
    assert drive(seg, frames) == []


def test_max_duration_force_flushes():
    seg = Segmenter(hangover_ms=600, min_ms=100, max_ms=400)
    out = drive(seg, [tone_frame()] * 100)
    assert out, "a stuck-open transmission must be force-flushed"
    assert out[0].duration_s <= 0.5


def test_flush_returns_pending_audio():
    seg = Segmenter(hangover_ms=600, min_ms=100)
    drive(seg, [tone_frame()] * 30)
    tail = seg.flush()
    assert tail is not None
    assert tail.duration_s > 0
    assert seg.flush() is None, "flush must be idempotent"


def test_timestamps_advance_across_utterances():
    seg = Segmenter(hangover_ms=200, min_ms=100)
    frames = (
        [tone_frame()] * 25 + [silence_frame()] * 20
        + [tone_frame()] * 25 + [silence_frame()] * 20
    )
    first, second = drive(seg, frames)
    assert second.start_s > first.end_s


def test_max_frames_bound_holds_during_hangover():
    """Regression: max_ms must cap buffer residency during the hangover
    countdown too, not only while speech is still being fed.

    The `len(buffer) >= max_frames` check historically only ran in the
    speech branch of feed(). Once speech stopped and the buffer entered the
    silence/hangover branch, nothing re-checked that bound, so a buffer that
    was still under max_frames when speech ended could keep growing
    frame-by-frame for the entire hangover countdown before finally closing
    -- overshooting max_frames by up to hangover_frames. This uses
    hangover_ms > max_ms (600 vs 400) specifically to expose that gap:
    speech stops well before the buffer is full, then hangover silence
    frames accumulate.
    """
    max_ms = 400
    hangover_ms = 600
    seg = Segmenter(hangover_ms=hangover_ms, min_ms=100, max_ms=max_ms)
    max_frames = max_ms // 20  # FRAME_MS = 20 -> 20 frames

    # Fewer speech frames than max_frames, so the speech-branch check never
    # fires and the buffer is still open when silence begins.
    for f in [tone_frame()] * (max_frames - 1):
        assert seg.feed(f) is None

    out = None
    # hangover_frames = 30, comfortably more than needed to overshoot
    # max_frames if the bound is not enforced during silence.
    for _ in range(hangover_ms // 20):
        out = seg.feed(silence_frame())
        assert len(seg._buffer) <= max_frames, (
            f"internal buffer grew to {len(seg._buffer)} frames while "
            f"waiting out the hangover, past the configured "
            f"max_frames={max_frames}"
        )
        if out is not None:
            break

    assert out is not None, (
        "a buffer that hits max_frames during hangover must be "
        "force-flushed immediately, not left to buffer through the full "
        "hangover countdown"
    )
