"""Phase 0 spike: capture (or load) audio and transcribe it locally.

Usage:
    python scripts/spike_transcribe.py --seconds 5           # record from mic
    python scripts/spike_transcribe.py --wav path/to.wav     # transcribe a file
    python scripts/spike_transcribe.py --wav x.wav --backend whisper

Proves the local ASR path works end-to-end before any pipeline plumbing.
"""

from __future__ import annotations

import argparse
import time
import wave

import numpy as np

SAMPLE_RATE = 16_000


def record(seconds: float) -> np.ndarray:
    """Record mono float32 audio from the default input device."""
    import sounddevice as sd

    print(f"Recording {seconds:.1f}s from the default microphone...")
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    return audio.reshape(-1)


def load_wav(path: str) -> np.ndarray:
    """Load a 16 kHz mono 16-bit WAV file as float32 in [-1, 1]."""
    with wave.open(path, "rb") as wf:
        assert wf.getframerate() == SAMPLE_RATE, f"expected {SAMPLE_RATE} Hz, got {wf.getframerate()}"
        assert wf.getnchannels() == 1, "expected mono"
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_parakeet(audio: np.ndarray) -> str:
    from parakeet_mlx import from_pretrained

    t0 = time.perf_counter()
    model = from_pretrained("mlx-community/parakeet-tdt-0.6b-v3")
    print(f"[parakeet] model loaded in {time.perf_counter() - t0:.2f}s")

    t0 = time.perf_counter()
    result = model.transcribe(audio)
    print(f"[parakeet] transcribed in {time.perf_counter() - t0:.2f}s")
    return result.text


def transcribe_whisper(audio: np.ndarray) -> str:
    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    print(f"[whisper] model loaded in {time.perf_counter() - t0:.2f}s")

    t0 = time.perf_counter()
    segments, _info = model.transcribe(audio, language="en")
    text = " ".join(s.text.strip() for s in segments)
    print(f"[whisper] transcribed in {time.perf_counter() - t0:.2f}s")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--seconds", type=float, help="record N seconds from the mic")
    src.add_argument("--wav", help="transcribe an existing 16 kHz mono WAV file")
    parser.add_argument("--backend", choices=["parakeet", "whisper"], default="parakeet")
    args = parser.parse_args()

    audio = record(args.seconds) if args.seconds else load_wav(args.wav)
    print(f"Audio: {len(audio) / SAMPLE_RATE:.2f}s, peak {np.abs(audio).max():.3f}")

    text = transcribe_parakeet(audio) if args.backend == "parakeet" else transcribe_whisper(audio)
    print(f"\nTranscript: {text!r}")


if __name__ == "__main__":
    main()
