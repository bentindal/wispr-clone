"""The dictation pipeline: audio -> VAD -> ASR -> vocabulary -> cleanup -> inject.

Owns all pipeline stages, keeps models warm, and reports state transitions
(idle / recording / transcribing) to the UI layer.
"""

from __future__ import annotations

import difflib
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

from wispr_clone.asr import ASRBackend, create_backend
from wispr_clone.audio import AudioError, Recorder, SileroVAD
from wispr_clone.cleanup import CleanupError, OllamaCleaner, strip_fillers
from wispr_clone.config import Config
from wispr_clone.context import frontmost_app, style_for_app
from wispr_clone.inject import InjectionError, inject
from wispr_clone.vocabulary import _COMMON_WORDS, Vocabulary

logger = logging.getLogger(__name__)


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class DictationPipeline:
    """Wires the five stages together behind start()/stop().

    ``start()``/``stop()`` are called from the hotkey listener thread and
    return immediately; transcription and injection happen on a worker thread
    so the next dictation can begin while UI state settles.
    """

    def __init__(self, config: Config, on_state: Callable[[State, str], None] | None = None) -> None:
        self.config = config
        self.on_state = on_state or (lambda state, detail: None)
        self.recorder = Recorder(device=config.audio.device, max_seconds=config.audio.max_seconds)
        self.vad = SileroVAD()
        self.asr: ASRBackend = create_backend(
            config.asr.backend, model=config.asr.model or None, language=config.asr.language or None
        )
        self.vocabulary = Vocabulary()
        self.cleaner = OllamaCleaner(
            url=config.cleanup.ollama_url,
            model=config.cleanup.model,
            timeout_seconds=config.cleanup.timeout_seconds,
        )
        self.cleanup_available = False
        self.last_raw: str = ""  # vocabulary-corrected ASR output
        self.last_final: str = ""  # what was actually injected
        self._state = State.IDLE
        # All ASR work (load, warm-up, transcribe) runs on this one thread:
        # MLX streams are per-thread state, so hopping threads between load
        # and inference raises "There is no Stream(gpu, 0) in current thread".
        self._asr_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")

    # -- startup ------------------------------------------------------------

    def load_models(self, progress: Callable[[str], None] | None = None) -> None:
        """Load ASR + VAD and warm the cleanup LLM. Called once at startup."""
        say = progress or (lambda msg: None)
        say(f"Loading ASR model ({self.asr.name})...")
        t0 = time.perf_counter()
        self._asr_thread.submit(self.asr.load).result()
        say(f"ASR ready in {time.perf_counter() - t0:.1f}s")

        say("Loading Silero VAD...")
        self.vad.load()

        if self.config.cleanup.enabled:
            ok, message = self.cleaner.check_available()
            self.cleanup_available = ok
            say(message)
            if ok:
                threading.Thread(target=self.cleaner.warm, daemon=True).start()
        else:
            say("Cleanup disabled in config; injecting raw transcripts.")

    def warm_up(self) -> None:
        """Run a dummy transcription so the first real one isn't cold."""
        import numpy as np

        try:
            self._asr_thread.submit(self.asr.transcribe, np.zeros(16_000, dtype=np.float32)).result()
        except Exception:
            logger.exception("warm-up transcription failed (continuing)")

    # -- hotkey entry points --------------------------------------------------

    def start(self) -> None:
        """Begin recording (hotkey pressed)."""
        if self._state == State.RECORDING:
            return
        try:
            self.recorder.start()
        except AudioError as exc:
            self._set_state(State.IDLE, str(exc))
            return
        self._set_state(State.RECORDING, "")

    def stop(self) -> None:
        """Stop recording (hotkey released) and process on a worker thread."""
        if self._state != State.RECORDING:
            return
        audio = self.recorder.stop()
        self._set_state(State.TRANSCRIBING, "")
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    # -- the pipeline ---------------------------------------------------------

    def _process(self, audio) -> None:
        try:
            self._process_inner(audio)
        except Exception as exc:
            logger.exception("pipeline failed")
            self._set_state(State.IDLE, f"Error: {exc}")
        else:
            pass  # _process_inner sets final state

    def _process_inner(self, audio) -> None:
        t_release = time.perf_counter()

        speech = self.vad.trim(audio)
        if len(speech) == 0:
            self._set_state(State.IDLE, "No speech detected")
            return

        # Capture the target app *before* the (possibly slow) LLM pass; the
        # user's focus at key-release is where the text should land.
        app = frontmost_app()
        style = style_for_app(app, self.config.apps)

        hotwords = self.vocabulary.terms() or None
        result = self._asr_thread.submit(self.asr.transcribe, speech, hotwords).result()
        raw = result.text
        if not raw:
            self._set_state(State.IDLE, "Heard nothing intelligible")
            return

        corrected = self.vocabulary.correct(raw, threshold=self.config.vocabulary.fuzzy_threshold)
        self.last_raw = corrected

        final = corrected
        use_llm = self.config.cleanup.enabled and self.cleanup_available
        if style == "code" and not self.config.cleanup.llm_for_code_style:
            # Deterministic path for editors/terminals: a small LLM rewriting a
            # shell command is the one place hallucination does real damage.
            final = strip_fillers(corrected)
        elif use_llm:
            try:
                cleaned = self.cleaner.clean(corrected, style=style, vocabulary=self.vocabulary.terms())
                final = cleaned if cleaned else corrected
            except CleanupError as exc:
                logger.warning("cleanup fell back to raw transcript: %s", exc)

        try:
            inject(final, method=self.config.injection.method, restore_delay=self.config.injection.restore_delay)
        except InjectionError as exc:
            self._set_state(State.IDLE, str(exc))
            return

        self.last_final = final
        elapsed = time.perf_counter() - t_release
        logger.info(
            "dictation done in %.2fs (asr %.2fs, %.1fs audio, style=%s, app=%s): %r",
            elapsed, result.latency_seconds, result.duration_seconds, style, app.name, final,
        )
        self._set_state(State.IDLE, f"Done in {elapsed:.1f}s")

    def cancel(self) -> None:
        """Discard the current recording without transcribing."""
        if self._state == State.RECORDING:
            self.recorder.stop()
            self._set_state(State.IDLE, "Cancelled")

    # -- vocabulary learning ---------------------------------------------------

    def learn_from_correction(self, corrected_text: str) -> list[str]:
        """Diff the user's corrected text against the last injection and add
        new terms to the vocabulary.

        Only clearly "vocabulary-like" replacements are learned: changed words
        that are not common English words. Returns the terms added.
        """
        original = self.last_final
        if not original or not corrected_text or corrected_text == original:
            return []

        added: list[str] = []
        matcher = difflib.SequenceMatcher(None, original.split(), corrected_text.split())
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
            if tag not in ("replace", "insert"):
                continue
            phrase = " ".join(corrected_text.split()[j1:j2]).strip(".,;:!?\"'")
            if not phrase:
                continue
            words = phrase.split()
            if len(words) > 4:  # a whole rewritten sentence is not a "term"
                continue
            if all(word.lower().strip(".,;:!?\"'") in _COMMON_WORDS for word in words):
                continue
            if self.vocabulary.add(phrase, category="term"):
                added.append(phrase)

        self.last_final = corrected_text
        return added

    # -- state ---------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    def _set_state(self, state: State, detail: str) -> None:
        self._state = state
        try:
            self.on_state(state, detail)
        except Exception:
            logger.exception("on_state callback failed")
