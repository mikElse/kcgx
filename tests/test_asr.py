import struct
from types import SimpleNamespace

from squelch.asr import Transcript, WhisperTranscriber, pcm_to_float32


def test_pcm_to_float32_scales_to_unit_range():
    pcm = struct.pack("<4h", 0, 32767, -32768, 16384)
    out = pcm_to_float32(pcm)
    assert out.dtype.name == "float32"
    assert len(out) == 4
    assert abs(out[0]) < 1e-6
    assert 0.99 < out[1] <= 1.0
    assert -1.0 <= out[2] < -0.99


class FakeModel:
    def __init__(self, segments):
        self._segments = segments
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return iter(self._segments), SimpleNamespace(language="en")


def make(segments):
    model = FakeModel(segments)
    tr = WhisperTranscriber("fake-model", loader=lambda *a, **k: model)
    tr.load()
    return tr, model


def test_transcribe_joins_segments():
    tr, _ = make([
        SimpleNamespace(text=" Alaska 412 heavy,", avg_logprob=-0.2),
        SimpleNamespace(text=" cleared to land.", avg_logprob=-0.4),
    ])
    result = tr.transcribe(b"\x00\x00" * 1600)
    assert result.text == "Alaska 412 heavy, cleared to land."
    assert result.avg_logprob == -0.3


def test_empty_result_is_empty_string():
    tr, _ = make([])
    assert tr.transcribe(b"\x00\x00" * 1600) == Transcript(text="", avg_logprob=0.0)


def test_transcribe_requests_english_and_no_internal_vad():
    tr, model = make([SimpleNamespace(text="x", avg_logprob=-0.1)])
    tr.transcribe(b"\x00\x00" * 1600)
    kwargs = model.calls[0]
    assert kwargs["language"] == "en"
    assert kwargs["vad_filter"] is False, "we already segmented; don't re-segment"


def test_not_ready_before_load():
    tr = WhisperTranscriber("fake-model", loader=lambda *a, **k: FakeModel([]))
    assert tr.ready is False
    tr.load()
    assert tr.ready is True
