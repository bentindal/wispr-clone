"""Microphone capture (sounddevice) and silence trimming (Silero VAD)."""

from __future__ import annotations

import logging
import threading

import numpy as np

SAMPLE_RATE = 16_000

logger = logging.getLogger(__name__)


class AudioError(Exception):
    """Raised when audio capture fails (no mic, no permission, bad device)."""


class Recorder:
    """Start/stop microphone capture into an in-memory buffer.

    Designed for push-to-talk: ``start()`` on key press, ``stop()`` on release
    returns the captured audio. A single instance is reused across dictations;
    the input stream is opened per recording (opening takes ~10ms, well within
    budget, and avoids holding the mic between dictations).
    """

    def __init__(self, device: str = "", max_seconds: int = 120) -> None:
        self.device = device or None
        self.max_seconds = max_seconds
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()

    def _resolve_device(self) -> int | str | None:
        """Map a device-name substring from config to a sounddevice input."""
        if self.device is None:
            return None
        import sounddevice as sd

        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and self.device.lower() in dev["name"].lower():
                return idx
        raise AudioError(f"No input device matching {self.device!r} found")

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        """Open the input stream and begin buffering audio."""
        import sounddevice as sd

        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []
            max_samples = self.max_seconds * SAMPLE_RATE

            def callback(indata: np.ndarray, frames: int, time_info, status) -> None:
                if status:
                    logger.warning("audio status: %s", status)
                total = sum(len(chunk) for chunk in self._chunks)
                if total < max_samples:
                    self._chunks.append(indata[:, 0].copy())

            try:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    device=self._resolve_device(),
                    callback=callback,
                )
                self._stream.start()
            except sd.PortAudioError as exc:
                self._stream = None
                raise AudioError(
                    f"Could not open microphone: {exc}. Check that a mic is connected and "
                    "the Microphone permission is granted (System Settings -> Privacy & "
                    "Security -> Microphone)."
                ) from exc

    def stop(self) -> np.ndarray:
        """Stop capture and return everything recorded as 16 kHz mono float32."""
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            if not self._chunks:
                return np.zeros(0, dtype=np.float32)
            audio = np.concatenate(self._chunks)
            self._chunks = []
            return audio


class SileroVAD:
    """Trim leading/trailing silence with Silero VAD.

    Loaded once at startup (the ONNX model is ~2 MB) and reused per dictation.
    """

    def __init__(self, pad_ms: int = 150) -> None:
        self.pad_ms = pad_ms
        self._model = None
        self._get_speech_timestamps = None

    def load(self) -> None:
        from silero_vad import get_speech_timestamps, load_silero_vad

        self._model = load_silero_vad(onnx=False)
        self._get_speech_timestamps = get_speech_timestamps

    def trim(self, audio: np.ndarray) -> np.ndarray:
        """Return *audio* cut down to the first..last detected speech span.

        Returns an empty array when no speech is detected (caller should skip
        transcription), and the input unchanged if VAD itself fails.
        """
        if self._model is None:
            self.load()
        if len(audio) == 0:
            return audio

        import torch

        try:
            timestamps = self._get_speech_timestamps(
                torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)),
                self._model,
                sampling_rate=SAMPLE_RATE,
            )
        except Exception:
            logger.exception("VAD failed; using untrimmed audio")
            return audio

        if not timestamps:
            return np.zeros(0, dtype=np.float32)

        pad = int(self.pad_ms * SAMPLE_RATE / 1000)
        start = max(0, timestamps[0]["start"] - pad)
        end = min(len(audio), timestamps[-1]["end"] + pad)
        return audio[start:end]
