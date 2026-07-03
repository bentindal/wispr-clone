"""Tests for pipeline orchestration and context mapping (all stages mocked)."""

from unittest.mock import patch

import numpy as np
import pytest

from wispr_clone.config import Config
from wispr_clone.context import AppContext, style_for_app
from wispr_clone.pipeline import DictationPipeline


@pytest.fixture
def pipeline(tmp_path):
    config = Config()
    config.cleanup.enabled = False  # unit tests never talk to Ollama
    with patch("wispr_clone.vocabulary.VOCABULARY_PATH", tmp_path / "vocab.json"):
        p = DictationPipeline(config)
        p.vocabulary.path = tmp_path / "vocab.json"
        yield p


# -- learn_from_correction ---------------------------------------------------


def test_learns_changed_proper_noun(pipeline):
    pipeline.last_final = "I spoke with shivon about the deal"
    added = pipeline.learn_from_correction("I spoke with Siobhan about the deal")
    assert added == ["Siobhan"]
    assert "Siobhan" in pipeline.vocabulary.terms()
    assert pipeline.last_final == "I spoke with Siobhan about the deal"


def test_learns_multiword_company(pipeline):
    pipeline.last_final = "the acne widgets contract"
    added = pipeline.learn_from_correction("the Acme Widgets contract")
    assert added == ["Acme Widgets"]


def test_does_not_learn_common_words(pipeline):
    pipeline.last_final = "I think we could go their"
    added = pipeline.learn_from_correction("I think we could go there")
    assert added == []
    assert pipeline.vocabulary.terms() == []


def test_ignores_wholesale_rewrites(pipeline):
    pipeline.last_final = "short note"
    added = pipeline.learn_from_correction(
        "short note plus an entirely new appended sentence that is way too long to be a term"
    )
    assert added == []


def test_no_learning_without_prior_dictation(pipeline):
    assert pipeline.learn_from_correction("anything") == []


# -- app-context styles ---------------------------------------------------------


def test_style_known_apps_builtin():
    assert style_for_app(AppContext("Slack", "com.tinyspeck.slackmacgap")) == "chat"
    assert style_for_app(AppContext("Mail", "com.apple.mail")) == "email"
    assert style_for_app(AppContext("Code", "com.microsoft.VSCode")) == "code"
    assert style_for_app(AppContext("Safari", "com.apple.Safari")) == "default"


def test_style_user_override_wins():
    ctx = AppContext("Slack", "com.tinyspeck.slackmacgap")
    assert style_for_app(ctx, overrides={"com.tinyspeck.slackmacgap": "email"}) == "email"


def test_style_unknown_context():
    assert style_for_app(AppContext()) == "default"


# -- state machine ----------------------------------------------------------------


def test_stop_without_start_is_noop(pipeline):
    states = []
    pipeline.on_state = lambda s, d: states.append(s)
    pipeline.stop()
    assert states == []


def test_process_skips_when_vad_finds_no_speech(pipeline):
    events = []
    pipeline.on_state = lambda s, d: events.append((s.value, d))
    pipeline.vad.trim = lambda audio: np.zeros(0, dtype=np.float32)
    pipeline._process(np.zeros(16000, dtype=np.float32))
    assert events == [("idle", "No speech detected")]
