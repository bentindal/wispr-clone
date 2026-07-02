"""Parakeet ASR backend: NVIDIA Parakeet TDT 0.6b v3 on Apple Silicon via MLX.

Sub-100ms transcription latency for short utterances on M-series chips.
"""

from __future__ import annotations

import time

import numpy as np

from wispr_clone.asr.base import SAMPLE_RATE, ASRBackend, TranscriptionResult

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"


class ParakeetBackend(ASRBackend):
    """parakeet-mlx backend (Apple Silicon only)."""

    name = "parakeet"

    def __init__(self, model: str | None = None, language: str | None = None) -> None:
        self.model_id = model or DEFAULT_MODEL
        # Parakeet TDT v3 is multilingual and auto-detects; the hint is unused
        # but kept for interface symmetry.
        self.language = language or None
        self._model = None

    def load(self) -> None:
        from parakeet_mlx import from_pretrained

        self._model = from_pretrained(self.model_id)

    def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> TranscriptionResult:
        if self._model is None:
            self.load()

        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        t0 = time.perf_counter()
        # Feed raw 16 kHz audio in-memory (model.transcribe() only accepts file
        # paths and shells out to ffmpeg). parakeet-mlx has no hotword-biasing
        # API (as of 0.5.x), so vocabulary biasing for this backend relies on
        # the post-ASR fuzzy corrector.
        mel = get_logmel(mx.array(np.ascontiguousarray(audio, dtype=np.float32)), self._model.preprocessor_config)
        results = self._model.generate(mel)
        latency = time.perf_counter() - t0

        return TranscriptionResult(
            text=results[0].text.strip() if results else "",
            language=self.language,
            duration_seconds=len(audio) / SAMPLE_RATE,
            latency_seconds=latency,
        )
