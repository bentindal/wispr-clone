"""The ASRBackend interface every speech-to-text backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

SAMPLE_RATE = 16_000


@dataclass
class TranscriptionResult:
    """Output of a single transcription call."""

    text: str
    language: str | None = None
    duration_seconds: float = 0.0  # audio duration
    latency_seconds: float = 0.0  # wall-clock transcription time
    raw: dict = field(default_factory=dict)  # backend-specific extras


class ASRBackend(ABC):
    """A local speech-to-text engine.

    Implementations load their model in :meth:`load` (called once at startup so
    the model stays warm) and transcribe 16 kHz mono float32 audio in
    :meth:`transcribe`.
    """

    #: Human-readable backend name ("parakeet", "whisper").
    name: str = "base"

    @abstractmethod
    def load(self) -> None:
        """Download (if needed) and load the model into memory."""

    @abstractmethod
    def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> TranscriptionResult:
        """Transcribe *audio* (16 kHz mono float32 in [-1, 1]).

        *hotwords* are vocabulary terms to bias recognition toward, where the
        backend supports biasing; backends without support ignore them (the
        post-ASR fuzzy corrector still applies).
        """

    @property
    def is_loaded(self) -> bool:
        """Whether :meth:`load` has completed."""
        return getattr(self, "_model", None) is not None
