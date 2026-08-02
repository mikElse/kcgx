"""Speech recognition using an ATC-fine-tuned Whisper model.

Stock Whisper is not adequate for ATC audio: clipped VHF bandwidth, heavy
accent variety, and rapid alphanumeric callsigns push it into producing
fluent, confident, wrong text. The fine-tuned CTranslate2 weights are
materially better on callsigns and standard phraseology.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

Loader = Callable[..., Any]


@dataclass(frozen=True)
class Transcript:
    text: str
    avg_logprob: float


class Transcriber(Protocol):
    def transcribe(self, pcm: bytes) -> Transcript: ...


def pcm_to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def _default_loader(model: str, *, compute_type: str) -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(model, device="cpu", compute_type=compute_type)


class WhisperTranscriber:
    def __init__(
        self,
        model: str,
        *,
        compute_type: str = "int8",
        loader: Loader | None = None,
    ) -> None:
        self._model_id = model
        self._compute_type = compute_type
        self._loader = loader or _default_loader
        self._model: Any = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Download and load weights. Slow; call off the UI thread."""
        self._model = self._loader(self._model_id, compute_type=self._compute_type)

    def transcribe(self, pcm: bytes) -> Transcript:
        if self._model is None:
            raise RuntimeError("transcriber not loaded")
        segments, _info = self._model.transcribe(
            pcm_to_float32(pcm),
            language="en",
            beam_size=5,
            vad_filter=False,  # already segmented upstream
            condition_on_previous_text=False,  # stops hallucination loops
        )
        segments = list(segments)
        if not segments:
            return Transcript(text="", avg_logprob=0.0)
        text = " ".join(s.text.strip() for s in segments).strip()
        # Round off IEEE-754 summation noise (e.g. averaging -0.2 and -0.4
        # lands on -0.30000000000000004, not -0.3); avg_logprob is a
        # diagnostic score, so 6 decimal digits is far more precision than
        # meaningful while keeping equality comparisons stable.
        avg = round(sum(s.avg_logprob for s in segments) / len(segments), 6)
        return Transcript(text=text, avg_logprob=avg)
