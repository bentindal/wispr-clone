"""Configuration: load/create ~/.config/wispr-clone/config.toml with defaults."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "wispr-clone"
CONFIG_PATH = CONFIG_DIR / "config.toml"
VOCABULARY_PATH = CONFIG_DIR / "vocabulary.json"

# Written verbatim on first run so the user gets a commented, editable file.
DEFAULT_CONFIG_TOML = """\
# wispr-clone configuration. Delete this file to regenerate defaults.

[hotkey]
# pynput key name for the global dictation key. Good choices are keys you
# don't otherwise use: "alt_r" (right Option), "cmd_r", "ctrl_r", "f13".."f19".
key = "alt_r"
# "hold" = press-and-hold to talk, release to transcribe.
# "toggle" = tap once to start, tap again to stop.
mode = "hold"

[asr]
# "parakeet" (Apple Silicon, fastest) or "whisper" (faster-whisper, portable).
backend = "parakeet"
# Model id override. Empty = backend default:
#   parakeet -> mlx-community/parakeet-tdt-0.6b-v3
#   whisper  -> large-v3-turbo
model = ""
# Language hint (e.g. "en"). Empty = auto-detect where supported.
language = ""

[cleanup]
# Polish the transcript with a local LLM via Ollama. If Ollama or the model
# is unavailable, the raw (vocabulary-corrected) transcript is injected instead.
enabled = true
ollama_url = "http://localhost:11434"
model = "llama3.2:3b"
# Max seconds to wait for the LLM before falling back to the raw transcript.
timeout_seconds = 10.0
# Apps mapped to the "code" style (editors, terminals) get deterministic
# filler-stripping instead of the LLM - a small model rewriting a shell
# command is where hallucination does real damage. Set true to use the LLM.
llm_for_code_style = false

[injection]
# "paste" = save clipboard, set result, synthetic Cmd+V, restore clipboard (fast).
# "type"  = type character-by-character (slower, preserves clipboard, works in
#           paste-hostile apps).
method = "paste"
# Seconds the dictated text stays on the clipboard before the original
# clipboard is restored (paste method; restore happens in the background and
# is skipped if you copy something new first). Raise this if a slow app
# sometimes pastes your old clipboard instead of the dictation.
restore_delay = 2.0

[vocabulary]
# When true, the "Correct last transcription" menu action adds corrected terms
# to the dictionary automatically.
auto_learn = false
# Fuzzy-match score (0-100) required before a transcript word is rewritten to a
# dictionary term. Higher = more conservative.
fuzzy_threshold = 82

[audio]
# Input device name substring. Empty = system default microphone.
device = ""
# Hard cap on a single dictation, in seconds.
max_seconds = 120

# Per-app formatting styles, keyed by macOS bundle id.
# Styles: "default", "chat" (terse, casual), "email" (full sentences,
# greeting/sign-off aware), "code" (verbatim, no prose formatting).
[apps]
"com.tinyspeck.slackmacgap" = "chat"
"com.apple.MobileSMS" = "chat"
"com.hnc.Discord" = "chat"
"net.whatsapp.WhatsApp" = "chat"
"com.apple.mail" = "email"
"com.microsoft.Outlook" = "email"
"com.google.Chrome.app.mail" = "email"
"com.microsoft.VSCode" = "code"
"com.apple.Terminal" = "code"
"com.googlecode.iterm2" = "code"
"com.jetbrains.intellij" = "code"
"dev.zed.Zed" = "code"
"com.sublimetext.4" = "code"
"""


@dataclass
class HotkeyConfig:
    key: str = "alt_r"
    mode: str = "hold"  # "hold" | "toggle"


@dataclass
class ASRConfig:
    backend: str = "parakeet"  # "parakeet" | "whisper"
    model: str = ""  # empty -> backend default
    language: str = ""  # empty -> auto


@dataclass
class CleanupConfig:
    enabled: bool = True
    ollama_url: str = "http://localhost:11434"
    model: str = "llama3.2:3b"
    timeout_seconds: float = 10.0
    # "code"-style apps (editors/terminals) use deterministic filler-stripping
    # by default; set true to run the LLM there too.
    llm_for_code_style: bool = False


@dataclass
class InjectionConfig:
    method: str = "paste"  # "paste" | "type"
    # Seconds the dictated text stays on the clipboard before the original
    # clipboard is restored (in the background; skipped if you copy something
    # new first). Raise if a slow/busy app pastes stale contents.
    restore_delay: float = 2.0


@dataclass
class VocabularyConfig:
    auto_learn: bool = False
    fuzzy_threshold: int = 82


@dataclass
class AudioConfig:
    device: str = ""
    max_seconds: int = 120


@dataclass
class Config:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    vocabulary: VocabularyConfig = field(default_factory=VocabularyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    apps: dict[str, str] = field(default_factory=dict)


class ConfigError(Exception):
    """Raised when config.toml exists but contains invalid values."""


def _validate(config: Config) -> None:
    if config.hotkey.mode not in ("hold", "toggle"):
        raise ConfigError(f"hotkey.mode must be 'hold' or 'toggle', got {config.hotkey.mode!r}")
    if config.asr.backend not in ("parakeet", "whisper"):
        raise ConfigError(f"asr.backend must be 'parakeet' or 'whisper', got {config.asr.backend!r}")
    if config.injection.method not in ("paste", "type"):
        raise ConfigError(f"injection.method must be 'paste' or 'type', got {config.injection.method!r}")
    if not 0 <= config.vocabulary.fuzzy_threshold <= 100:
        raise ConfigError("vocabulary.fuzzy_threshold must be between 0 and 100")
    if config.cleanup.timeout_seconds <= 0:
        raise ConfigError("cleanup.timeout_seconds must be positive")
    valid_styles = {"default", "chat", "email", "code"}
    for bundle_id, style in config.apps.items():
        if style not in valid_styles:
            raise ConfigError(f"apps.{bundle_id!r}: unknown style {style!r} (expected one of {sorted(valid_styles)})")


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from *path*, creating it with commented defaults on first run."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CONFIG_TOML)

    with path.open("rb") as f:
        raw = tomllib.load(f)

    def section(name: str) -> dict:
        value = raw.get(name, {})
        if not isinstance(value, dict):
            raise ConfigError(f"[{name}] must be a table")
        return value

    try:
        config = Config(
            hotkey=HotkeyConfig(**section("hotkey")),
            asr=ASRConfig(**section("asr")),
            cleanup=CleanupConfig(**section("cleanup")),
            injection=InjectionConfig(**section("injection")),
            vocabulary=VocabularyConfig(**section("vocabulary")),
            audio=AudioConfig(**section("audio")),
            apps=dict(section("apps")),
        )
    except TypeError as exc:  # unknown key in a section
        raise ConfigError(f"Invalid config key: {exc}") from exc

    _validate(config)
    return config
