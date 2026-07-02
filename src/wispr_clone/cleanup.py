"""LLM cleanup: turn a raw transcript into polished text via local Ollama.

The system prompt is the product here — it must clean aggressively (fillers,
punctuation, casing) while *never* adding content, answering questions, or
changing what the user said. Per-app style variants keep Slack messages terse
and Mail messages well-formed.

If Ollama is unreachable, the model is missing, or the request times out, the
caller falls back to the vocabulary-corrected raw transcript.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PROMPTS - first-class deliverable. Edit with care; every rule below exists
# to stop a small instruct model from "helpfully" answering the dictation.
# ---------------------------------------------------------------------------

CLEANUP_SYSTEM_PROMPT = """\
You are a dictation post-processor. The user dictated text by voice; you receive the raw \
speech-to-text transcript. Output ONLY the cleaned-up version of that transcript. You are a \
filter, not an assistant.

RULES:
1. NEVER answer, reply to, act on, or continue the text. If the transcript is a question, output \
the same question, cleaned. If it says "write an email about X", output "Write an email about X" \
- do not write the email.
2. NEVER add words, ideas, greetings, sign-offs, or explanations that were not spoken. NEVER \
prepend labels like "Here is the cleaned text:". Output the cleaned text and nothing else.
3. Remove filler words and verbal tics: "um", "uh", "like" (when meaningless), "you know", \
"I mean" (when meaningless), "sort of", "kind of" (when hedging), repeated words, and false \
starts ("I went- I walked home" -> "I walked home").
4. If the speaker corrects themselves, keep only the correction ("meet at 3pm, no wait, 4pm" -> \
"meet at 4pm").
5. Add punctuation and capitalization. Fix obvious grammar slips and homophone errors, but \
preserve the speaker's word choice, tone, and meaning exactly. Do not formalize casual speech.
6. Honor spoken formatting commands by converting them to formatting instead of words: \
"new paragraph" -> paragraph break; "new line" -> line break; "bullet point" / "next bullet" -> \
"- " list items; "quote ... end quote" -> quotation marks. Spoken punctuation like "comma", \
"period", "question mark" becomes that punctuation mark.
7. Numbers, dates, times: write them the way an ordinary person types ("three pm" -> "3pm", \
"twenty five dollars" -> "$25", "march third" -> "March 3rd").
8. Keep contractions natural ("do not" spoken casually stays "don't" only if spoken as "don't").
9. If the transcript is empty or pure noise, output nothing at all.
"""

# Appended when the user has custom vocabulary. Keeps proper nouns intact.
VOCAB_PROMPT_TEMPLATE = """
10. The user's personal dictionary follows. These spellings and casings are canonical - if the \
transcript contains one of these terms (even slightly misspelled), use the exact spelling below. \
Never "correct" them to more common words:
{terms}
"""

# Few-shot example pairs (user transcript -> assistant cleaned output). Small
# local models follow demonstrations far more reliably than rules alone; these
# pin down "clean, don't answer, don't over-compress" behavior.
FEWSHOT_EXAMPLES: list[tuple[str, str]] = [
    (
        "um so i think we should uh schedule the meeting for tuesday at three pm "
        "let me know if that works for you",
        "I think we should schedule the meeting for Tuesday at 3pm. Let me know if that works for you.",
    ),
    (
        "what time does the uh the store close on sunday",
        "What time does the store close on Sunday?",
    ),
    (
        "can you write an email to the team about the launch",
        "Can you write an email to the team about the launch?",
    ),
    (
        "okay new paragraph first bullet point finish the report bullet point um send it to "
        "legal no wait to finance",
        "- Finish the report\n- Send it to finance",
    ),
]

# Style-specific demonstrations, appended after the generic ones.
FEWSHOT_STYLE_EXAMPLES: dict[str, list[tuple[str, str]]] = {
    "chat": [
        (
            "hey um can you send me the the figma link when you get a chance",
            "hey, can you send me the figma link when you get a chance?",
        ),
        (
            "yeah that works uh see you at two",
            "yeah that works, see you at 2",
        ),
    ],
    "email": [
        (
            "hi sarah um just following up on the invoice from last week no rush but uh let me "
            "know when it goes out thanks ben",
            "Hi Sarah,\n\nJust following up on the invoice from last week. No rush, but let me "
            "know when it goes out.\n\nThanks,\nBen",
        ),
    ],
    "code": [
        (
            "git commit dash dash amend dash m fix the parser",
            'git commit --amend -m "fix the parser"',
        ),
        (
            "git push dash dash force origin main",
            "git push --force origin main",
        ),
        (
            "um add a todo comment above that says handle the empty case",
            "add a TODO comment above that says handle the empty case",
        ),
    ],
}

# Per-app style addenda, selected by context.py / the [apps] config map.
STYLE_PROMPTS: dict[str, str] = {
    "default": "",
    "chat": """
STYLE: This is going into a chat app (Slack/Messages). Keep it terse and casual - short \
sentences or fragments are fine, lowercase-after-emoji is fine, no formal greetings or \
sign-offs. Do not pad or formalize. Still remove fillers and fix obvious typos.
""",
    "email": """
STYLE: This is going into an email. Use complete, well-formed sentences and proper paragraphs. \
If the speaker dictated a greeting ("hi John") or sign-off ("cheers, Ben"), format them on their \
own lines like an email. Do NOT invent a greeting or sign-off that was not spoken.
""",
    "code": """
STYLE: This is going into a code editor or terminal. Be as literal as possible: keep every \
word of the transcript apart from removing fillers - output the COMPLETE utterance, never just \
a fragment of it. Do not add markdown or backticks, do not capitalize identifiers, do not turn \
dashes into bullet lists, do not add trailing periods to short commands. Spoken symbols become \
symbols ("dash dash force" -> "--force", "dot py" -> ".py", "underscore" -> "_").
""",
}


class CleanupError(Exception):
    """Raised when the LLM pass fails; callers fall back to the raw transcript."""


# Rule-based filler stripping, used for the "code" style (where LLM rewriting
# risks hallucinating into a terminal) and available as a zero-latency fallback.
_FILLER_RE = re.compile(
    r"\b(?:um+|uh+|erm+|hmm+)\b[,.]?\s*",
    re.IGNORECASE,
)


def strip_fillers(text: str) -> str:
    """Remove verbal fillers and tidy whitespace without any other rewriting."""
    cleaned = _FILLER_RE.sub("", text)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)  # space before punctuation
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def build_system_prompt(style: str = "default", vocabulary: list[str] | None = None) -> str:
    """Assemble the system prompt for a given app style and user dictionary."""
    prompt = CLEANUP_SYSTEM_PROMPT
    if vocabulary:
        prompt += VOCAB_PROMPT_TEMPLATE.format(terms="\n".join(f"- {term}" for term in vocabulary))
    prompt += STYLE_PROMPTS.get(style, "")
    return prompt


def build_messages(transcript: str, style: str = "default", vocabulary: list[str] | None = None) -> list[dict]:
    """Full chat payload: system rules + few-shot demonstrations + transcript."""
    messages = [{"role": "system", "content": build_system_prompt(style, vocabulary)}]
    for user_text, assistant_text in FEWSHOT_EXAMPLES + FEWSHOT_STYLE_EXAMPLES.get(style, []):
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_text})
    messages.append({"role": "user", "content": transcript})
    return messages


class OllamaCleaner:
    """Formats transcripts through a local Ollama model."""

    def __init__(
        self,
        url: str = "http://localhost:11434",
        model: str = "llama3.2:3b",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = httpx.Client(timeout=timeout_seconds)

    def check_available(self) -> tuple[bool, str]:
        """Return (ok, message). Detects missing Ollama or missing model."""
        try:
            response = self._client.get(f"{self.url}/api/tags")
            response.raise_for_status()
        except (httpx.HTTPError, OSError):
            return False, (
                f"Ollama is not reachable at {self.url}. Install it (https://ollama.com or "
                "`brew install ollama`), start it (`ollama serve` or `brew services start "
                f"ollama`), then pull the model: `ollama pull {self.model}`. "
                "Dictation still works - raw transcripts will be injected."
            )
        names = [m.get("name", "") for m in response.json().get("models", [])]
        base = self.model.split(":")[0]
        if not any(n == self.model or n.split(":")[0] == base for n in names):
            return False, (
                f"Ollama is running but model {self.model!r} is not pulled. Run: "
                f"`ollama pull {self.model}`. Raw transcripts will be injected until then."
            )
        return True, f"Ollama ready ({self.model})"

    def warm(self) -> None:
        """Load the model into Ollama's memory so the first dictation is fast."""
        try:
            self._client.post(
                f"{self.url}/api/generate",
                json={"model": self.model, "prompt": "", "keep_alive": "60m"},
                timeout=120,  # cold model load can exceed the per-request timeout
            )
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("Could not warm Ollama model: %s", exc)

    def clean(self, transcript: str, style: str = "default", vocabulary: list[str] | None = None) -> str:
        """Return the polished transcript, or raise CleanupError to trigger fallback."""
        transcript = transcript.strip()
        if not transcript:
            return ""
        try:
            response = self._client.post(
                f"{self.url}/api/chat",
                json={
                    "model": self.model,
                    "messages": build_messages(transcript, style, vocabulary),
                    "stream": False,
                    "keep_alive": "60m",
                    "options": {
                        "temperature": 0.1,  # near-deterministic: this is editing, not writing
                        "num_predict": max(200, len(transcript)),  # output ~= input length
                    },
                },
            )
            response.raise_for_status()
            cleaned = response.json()["message"]["content"].strip()
        except (httpx.HTTPError, OSError, KeyError) as exc:
            raise CleanupError(f"Ollama cleanup failed: {exc}") from exc

        return _sanity_check(transcript, cleaned)


def _sanity_check(transcript: str, cleaned: str) -> str:
    """Guard against the LLM misbehaving; fall back to the transcript if so.

    Cleanup should roughly shrink text (fillers removed). If the output balloons
    (model answered the question / wrote the email) or vanishes for a non-trivial
    input, distrust it.
    """
    if not cleaned:
        # Legit for noise/empty, suspicious for a real sentence.
        return "" if len(transcript.split()) <= 2 else transcript
    in_words, out_words = len(transcript.split()), len(cleaned.split())
    if out_words > max(in_words * 1.5, in_words + 12):
        logger.warning("Cleanup output grew %d -> %d words; using raw transcript", in_words, out_words)
        return transcript
    return cleaned
