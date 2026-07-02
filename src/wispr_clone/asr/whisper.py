"""Whisper ASR backend via faster-whisper (CTranslate2).

Portable fallback: works on Intel Macs and offers broad language coverage.
Supports vocabulary biasing through hotwords.
"""

from __future__ import annotations

import time

import numpy as np

from wispr_clone.asr.base import SAMPLE_RATE, ASRBackend, TranscriptionResult

DEFAULT_MODEL = "large-v3-turbo"


class WhisperBackend(ASRBackend):
    """faster-whisper backend."""

    name = "whisper"

    def __init__(self, model: str | None = None, language: str | None = None) -> None:
        self.model_id = model or DEFAULT_MODEL
        self.language = language or None
        self._model = None

    def load(self) -> None:
        from faster_whisper import WhisperModel

        # int8 on CPU is the best latency/quality tradeoff without a CUDA GPU.
        self._model = WhisperModel(self.model_id, device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray, hotwords: list[str] | None = None) -> TranscriptionResult:
        if self._model is None:
            self.load()

        t0 = time.perf_counter()
        segments, info = self._model.transcribe(
            np.ascontiguousarray(audio, dtype=np.float32),
            language=self.language,
            # Bias recognition toward the user's vocabulary. faster-whisper
            # feeds hotwords as prompt context when no initial_prompt is set.
            hotwords=" ".join(hotwords) if hotwords else None,
            beam_size=1,  # greedy: fastest, fine for dictation-length audio
            vad_filter=False,  # we already run Silero VAD upstream
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        latency = time.perf_counter() - t0

        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            duration_seconds=len(audio) / SAMPLE_RATE,
            latency_seconds=latency,
            raw={"language_probability": getattr(info, "language_probability", None)},
        )
