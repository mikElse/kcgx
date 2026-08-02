"""Segment a PCM stream into discrete radio transmissions.

ATC audio is squelch-gated: hard silence between transmissions rather than
continuous room tone. That makes voice activity detection easy and lets us
transcribe whole transmissions as units instead of fixed-size windows.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass

import webrtcvad

SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * 2                 # 640
SILENCE_FLOOR_DBFS = -96.0
GATE_DBFS = -70.0


def rms_dbfs(pcm: bytes) -> float:
    """Frame energy in dBFS, floored at SILENCE_FLOOR_DBFS."""
    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return SILENCE_FLOOR_DBFS
    mean_square = sum(s * s for s in samples) / len(samples)
    if mean_square <= 0:
        return SILENCE_FLOOR_DBFS
    return max(
        SILENCE_FLOOR_DBFS, 20 * math.log10(math.sqrt(mean_square) / 32768.0)
    )


@dataclass(frozen=True)
class Utterance:
    start_s: float
    end_s: float
    pcm: bytes

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


class Segmenter:
    """Turn 20 ms PCM frames into utterances.

    An utterance opens on the first speech frame and closes after
    `hangover_ms` of continuous silence, so a mid-sentence pause does not
    split one transmission into two. Utterances shorter than `min_ms` are
    discarded as squelch clicks; one running longer than `max_ms` is
    force-flushed so a stuck carrier cannot buffer forever.
    """

    def __init__(
        self,
        *,
        aggressiveness: int = 2,
        hangover_ms: int = 600,
        min_ms: int = 400,
        max_ms: int = 20_000,
        gate_dbfs: float = GATE_DBFS,
    ) -> None:
        self._vad = webrtcvad.Vad(aggressiveness)
        self._gate_dbfs = gate_dbfs
        self._hangover_frames = max(1, hangover_ms // FRAME_MS)
        self._min_frames = max(1, min_ms // FRAME_MS)
        self._max_frames = max(1, max_ms // FRAME_MS)
        self._buffer: list[bytes] = []
        self._silence_run = 0
        self._frame_index = 0
        self._start_frame = 0

    def feed(self, frame: bytes) -> Utterance | None:
        if len(frame) != FRAME_BYTES:
            raise ValueError(f"expected {FRAME_BYTES} bytes, got {len(frame)}")

        index = self._frame_index
        self._frame_index += 1
        is_speech = self._is_speech(frame)

        if is_speech:
            if not self._buffer:
                self._start_frame = index
            self._buffer.append(frame)
            self._silence_run = 0
            if len(self._buffer) >= self._max_frames:
                return self._close(index + 1, enforce_min=False)
            return None

        if not self._buffer:
            return None

        # Silence while an utterance is open: keep it as possible interior
        # pause until the hangover expires.
        self._buffer.append(frame)
        self._silence_run += 1
        # A buffer that has been idling through the hangover countdown can
        # keep growing past max_frames just as easily as one that is still
        # actively voiced. Bound it here too, so max_ms is a hard cap on
        # buffer residency regardless of which branch is executing, not
        # only while continuous speech is being fed.
        if len(self._buffer) >= self._max_frames:
            end = index + 1 - self._silence_run
            return self._close(end, enforce_min=False)
        if self._silence_run >= self._hangover_frames:
            end = index + 1 - self._silence_run
            return self._close(end, enforce_min=True)
        return None

    def _is_speech(self, frame: bytes) -> bool:
        """Energy-gated VAD.

        WebRTC's VAD adapts to recent input, so immediately after loud audio
        it reports pure silence as speech for a hundred milliseconds or so.
        Gating on frame energy first removes that tail, and suits
        squelch-gated ATC audio where the silence is digitally clean.
        """
        if rms_dbfs(frame) <= self._gate_dbfs:
            return False
        return self._vad.is_speech(frame, SAMPLE_RATE)

    def flush(self) -> Utterance | None:
        if not self._buffer:
            return None
        return self._close(self._frame_index - self._silence_run, enforce_min=False)

    def _close(self, end_frame: int, *, enforce_min: bool) -> Utterance | None:
        voiced = self._buffer[: len(self._buffer) - self._silence_run] or self._buffer
        buffered = list(voiced)
        self._buffer.clear()
        self._silence_run = 0
        if enforce_min and len(buffered) < self._min_frames:
            return None
        return Utterance(
            start_s=_seconds(self._start_frame),
            end_s=_seconds(end_frame),
            pcm=b"".join(buffered),
        )


def _seconds(frames: int) -> float:
    return frames * FRAME_MS / 1000.0
