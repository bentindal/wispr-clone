"""Tests for the ASR interface and backend factory (no real models loaded)."""

import numpy as np
import pytest

from wispr_clone.asr import create_backend
from wispr_clone.asr.base import SAMPLE_RATE, ASRBackend, TranscriptionResult


class FakeBackend(ASRBackend):
    """Minimal conforming implementation used to exercise the interface."""

    name = "fake"

    def __init__(self) -> None:
        self._model = None
        self.seen_hotwords: list[str] | None = None

    def load(self) -> None:
        self._model = object()

    def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> TranscriptionResult:
        if self._model is None:
            self.load()
        self.seen_hotwords = hotwords
        return TranscriptionResult(text="fake text", duration_seconds=len(audio) / SAMPLE_RATE)


def test_interface_contract():
    backend = FakeBackend()
    assert not backend.is_loaded
    backend.load()
    assert backend.is_loaded

    audio = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
    result = backend.transcribe(audio, hotwords=["Kubernetes"])
    assert result.text == "fake text"
    assert result.duration_seconds == pytest.approx(2.0)
    assert backend.seen_hotwords == ["Kubernetes"]


def test_factory_selects_parakeet():
    backend = create_backend("parakeet")
    assert backend.name == "parakeet"
    assert backend.model_id == "mlx-community/parakeet-tdt-0.6b-v3"
    assert not backend.is_loaded, "factory must not eagerly load models"


def test_factory_selects_whisper_with_model_override():
    backend = create_backend("whisper", model="small", language="en")
    assert backend.name == "whisper"
    assert backend.model_id == "small"
    assert backend.language == "en"


def test_factory_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown ASR backend"):
        create_backend("siri")
