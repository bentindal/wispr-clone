"""ASR backends behind a single swappable interface."""

from wispr_clone.asr.base import ASRBackend, TranscriptionResult

__all__ = ["ASRBackend", "TranscriptionResult", "create_backend"]


def create_backend(name: str, model: str | None = None, language: str | None = None) -> ASRBackend:
    """Instantiate an ASR backend by config name ("parakeet" or "whisper").

    Imports lazily so that e.g. parakeet-mlx (Apple Silicon only) is not
    required when the whisper backend is selected.
    """
    if name == "parakeet":
        from wispr_clone.asr.parakeet import ParakeetBackend

        return ParakeetBackend(model=model, language=language)
    if name == "whisper":
        from wispr_clone.asr.whisper import WhisperBackend

        return WhisperBackend(model=model, language=language)
    raise ValueError(f"Unknown ASR backend {name!r} (expected 'parakeet' or 'whisper')")
