"""Tests for the Ollama cleanup stage (LLM mocked via httpx transport)."""

import httpx
import pytest

from wispr_clone.cleanup import (
    CleanupError,
    OllamaCleaner,
    _sanity_check,
    build_messages,
    build_system_prompt,
    strip_fillers,
)


def make_cleaner(handler) -> OllamaCleaner:
    """OllamaCleaner whose HTTP layer is a mock transport."""
    cleaner = OllamaCleaner(url="http://mock:11434", model="test-model", timeout_seconds=5)
    cleaner._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    return cleaner


def chat_response(content: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": content}})

    return handler


# -- prompt assembly -----------------------------------------------------------


def test_system_prompt_contains_core_rules():
    prompt = build_system_prompt()
    assert "NEVER answer" in prompt
    assert "filler" in prompt.lower()
    assert "new paragraph" in prompt


def test_vocabulary_is_injected_into_prompt():
    prompt = build_system_prompt(vocabulary=["Kubernetes", "Acme Widgets"])
    assert "- Kubernetes" in prompt
    assert "- Acme Widgets" in prompt


def test_style_addenda():
    assert "chat app" in build_system_prompt(style="chat")
    assert "email" in build_system_prompt(style="email")
    assert "literal" in build_system_prompt(style="code")
    assert build_system_prompt(style="default") == build_system_prompt(style="unknown-style")


def test_messages_include_fewshot_and_transcript_last():
    messages = build_messages("hello there", style="chat")
    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "hello there"}
    # few-shot pairs alternate user/assistant between system and final user
    middle = messages[1:-1]
    assert len(middle) >= 8 and len(middle) % 2 == 0
    assert all(m["role"] == ("user" if i % 2 == 0 else "assistant") for i, m in enumerate(middle))


# -- strip_fillers (deterministic code-style path) ------------------------------


def test_strip_fillers_basic():
    assert strip_fillers("um so git push uh origin main") == "so git push origin main"


def test_strip_fillers_with_punctuation():
    assert strip_fillers("Um, run the tests, uh, again.") == "run the tests, again."


def test_strip_fillers_preserves_um_inside_words():
    assert strip_fillers("sum the numbers") == "sum the numbers"
    assert strip_fillers("the album uhh cover") == "the album cover"


# -- clean() --------------------------------------------------------------------


def test_clean_returns_llm_output():
    cleaner = make_cleaner(chat_response("Hello, world."))
    assert cleaner.clean("um hello world") == "Hello, world."


def test_clean_empty_transcript_skips_llm():
    def exploding(request):  # any HTTP call fails the test
        raise AssertionError("LLM should not be called for empty input")

    cleaner = make_cleaner(exploding)
    assert cleaner.clean("   ") == ""


def test_clean_raises_on_http_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    cleaner = make_cleaner(handler)
    with pytest.raises(CleanupError):
        cleaner.clean("hello there")


def test_clean_raises_on_timeout():
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    cleaner = make_cleaner(handler)
    with pytest.raises(CleanupError):
        cleaner.clean("hello there")


def test_check_available_when_ollama_down():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    cleaner = make_cleaner(handler)
    ok, message = cleaner.check_available()
    assert not ok
    assert "ollama" in message.lower()


def test_check_available_when_model_missing():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "other-model:7b"}]})

    cleaner = make_cleaner(handler)
    ok, message = cleaner.check_available()
    assert not ok
    assert "pull" in message


def test_check_available_ok():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "test-model:latest"}]})

    cleaner = make_cleaner(handler)
    ok, _ = cleaner.check_available()
    assert ok


# -- sanity check (anti-hallucination guard) -----------------------------------


def test_sanity_check_accepts_normal_shrinkage():
    raw = "um so I think we should uh meet on Tuesday"
    cleaned = "I think we should meet on Tuesday."
    assert _sanity_check(raw, cleaned) == cleaned


def test_sanity_check_rejects_ballooned_output():
    raw = "write an email to the team about the launch"
    answered = (
        "Subject: Launch Update\n\nHi team,\n\nI wanted to share some exciting news about our "
        "upcoming launch. We have been working hard and I am thrilled to announce that everything "
        "is on track for next week. Please review the attached materials and let me know if you "
        "have questions.\n\nBest,\nBen"
    )
    assert _sanity_check(raw, answered) == raw


def test_sanity_check_rejects_vanished_output():
    raw = "please send the quarterly report to finance by Friday"
    assert _sanity_check(raw, "") == raw


def test_sanity_check_allows_empty_for_noise():
    assert _sanity_check("uh", "") == ""
