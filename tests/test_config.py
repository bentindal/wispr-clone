"""Tests for config loading, defaults, and validation."""

import pytest

from wispr_clone.config import ConfigError, load_config


def test_first_run_creates_default_config(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path)
    assert path.exists(), "default config.toml should be written on first run"
    assert config.hotkey.key == "alt_r"
    assert config.hotkey.mode == "hold"
    assert config.asr.backend == "parakeet"
    assert config.cleanup.enabled is True
    assert config.cleanup.model == "llama3.2:3b"
    assert config.injection.method == "paste"
    assert config.vocabulary.fuzzy_threshold == 82
    assert config.apps["com.tinyspeck.slackmacgap"] == "chat"


def test_default_config_is_reloadable(tmp_path):
    path = tmp_path / "config.toml"
    first = load_config(path)
    second = load_config(path)
    assert first == second


def test_user_overrides(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
[hotkey]
key = "f19"
mode = "toggle"

[asr]
backend = "whisper"
model = "small"

[cleanup]
enabled = false

[apps]
"com.example.app" = "email"
"""
    )
    config = load_config(path)
    assert config.hotkey.key == "f19"
    assert config.hotkey.mode == "toggle"
    assert config.asr.backend == "whisper"
    assert config.asr.model == "small"
    assert config.cleanup.enabled is False
    assert config.apps == {"com.example.app": "email"}
    # unspecified sections keep defaults
    assert config.injection.method == "paste"


@pytest.mark.parametrize(
    "body,fragment",
    [
        ("[hotkey]\nmode = 'sideways'", "hotkey.mode"),
        ("[asr]\nbackend = 'siri'", "asr.backend"),
        ("[injection]\nmethod = 'telepathy'", "injection.method"),
        ("[vocabulary]\nfuzzy_threshold = 150", "fuzzy_threshold"),
        ("[cleanup]\ntimeout_seconds = -1", "timeout_seconds"),
        ("[apps]\n'com.x' = 'haiku'", "unknown style"),
        ("[hotkey]\nbanana = true", "Invalid config key"),
    ],
)
def test_invalid_values_raise(tmp_path, body, fragment):
    path = tmp_path / "config.toml"
    path.write_text(body)
    with pytest.raises(ConfigError, match=fragment):
        load_config(path)
