"""Custom vocabulary: storage, ASR biasing, fuzzy correction, auto-learn.

Three complementary mechanisms keep the user's names/jargon spelled right:

1. A human-editable dictionary at ~/.config/wispr-clone/vocabulary.json.
2. ASR biasing: terms are passed to backends that support hotwords (Whisper).
3. Post-ASR fuzzy correction: transcript tokens that nearly match a dictionary
   term (RapidFuzz ratio and/or Metaphone phonetic equality) are rewritten.

Correction is deliberately conservative: common English words are never
rewritten, thresholds are configurable, and multi-word terms are matched
against n-grams of the same length.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import jellyfish
from rapidfuzz import fuzz

from wispr_clone.config import VOCABULARY_PATH

logger = logging.getLogger(__name__)

# Words we refuse to rewrite even on a strong fuzzy match: rewriting these is
# almost always a false positive ("their" -> some company name, etc.).
_COMMON_WORDS = frozenset(
    """
    the be to of and a in that have i it for not on with he as you do at this
    but his by from they we say her she or an will my one all would there what
    so up out if about who get which go me when make can like time no just him
    know take people into year your good some could them see other than then
    now look only come its over think also back after use two how our work
    first well way even new want because any these give day most us is are was
    were been being has had did done said got made went its it's im i'm dont
    don't cant can't wont won't
    """.split()
)

_TOKEN_RE = re.compile(r"[\w']+|[^\w\s]", re.UNICODE)


@dataclass
class VocabEntry:
    """One user-dictionary term."""

    term: str  # correct spelling, e.g. "Kubernetes"
    phonetic: str = ""  # optional hint, e.g. "koo-ber-net-eez"
    category: str = ""  # optional: "name" | "company" | "term"

    def variants(self) -> list[str]:
        """Strings a misrecognition may resemble (term + phonetic hint)."""
        out = [self.term]
        if self.phonetic:
            out.append(self.phonetic)
        return out


class Vocabulary:
    """The user's personal dictionary, persisted as JSON."""

    def __init__(self, path: Path = VOCABULARY_PATH) -> None:
        self.path = path
        self.entries: list[VocabEntry] = []
        self.load()

    # -- storage -----------------------------------------------------------

    def load(self) -> None:
        if not self.path.exists():
            self.entries = []
            return
        try:
            data = json.loads(self.path.read_text())
            self.entries = [VocabEntry(**item) for item in data.get("entries", [])]
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Could not parse %s (%s); starting with empty vocabulary", self.path, exc)
            self.entries = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"entries": [asdict(entry) for entry in self.entries]}
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    # -- editing -----------------------------------------------------------

    def add(self, term: str, phonetic: str = "", category: str = "") -> bool:
        """Add *term*; returns False if it already exists (case-insensitive)."""
        term = term.strip()
        if not term or any(entry.term.lower() == term.lower() for entry in self.entries):
            return False
        self.entries.append(VocabEntry(term=term, phonetic=phonetic.strip(), category=category.strip()))
        self.save()
        return True

    def remove(self, term: str) -> bool:
        """Remove *term* (case-insensitive); returns False if absent."""
        before = len(self.entries)
        self.entries = [entry for entry in self.entries if entry.term.lower() != term.lower()]
        if len(self.entries) == before:
            return False
        self.save()
        return True

    def terms(self) -> list[str]:
        """All correct spellings, for ASR biasing and the cleanup prompt."""
        return [entry.term for entry in self.entries]

    # -- fuzzy correction ----------------------------------------------------

    def correct(self, text: str, threshold: int = 82) -> str:
        """Rewrite near-miss tokens in *text* to their dictionary spelling.

        A candidate n-gram is rewritten when, against any entry variant:
        - RapidFuzz ratio >= *threshold*, or
        - Metaphone codes match exactly and ratio >= threshold - 15 (phonetic
          match rescues cases like "shivon" -> "Siobhan" that string
          similarity alone misses).

        Single common English words are never rewritten, and exact matches
        (differing only in case) are normalized to the dictionary casing.
        """
        if not self.entries or not text:
            return text

        tokens = _TOKEN_RE.findall(text)
        max_words = max(len(entry.term.split()) for entry in self.entries)

        result: list[str] = []
        i = 0
        while i < len(tokens):
            match = self._best_match(tokens, i, max_words, threshold)
            if match is None:
                result.append(tokens[i])
                i += 1
            else:
                replacement, consumed = match
                result.append(replacement)
                i += consumed
        return _detokenize(result)

    def _best_match(
        self, tokens: list[str], start: int, max_words: int, threshold: int
    ) -> tuple[str, int] | None:
        """Best (replacement, tokens_consumed) at *start*, or None."""
        if not tokens[start][0].isalnum():
            return None

        best: tuple[float, str, int] | None = None  # (score, term, consumed)
        for n in range(max_words, 0, -1):
            span = [t for t in tokens[start : start + n]]
            if len(span) < n or any(not t[0].isalnum() for t in span):
                continue
            candidate = " ".join(span)
            if n == 1 and candidate.lower() in _COMMON_WORDS:
                continue

            for entry in self.entries:
                for variant in entry.variants():
                    if len(variant.split()) != n:
                        continue
                    if candidate.lower() == entry.term.lower():
                        # exact match: normalize casing, highest priority
                        return entry.term, n
                    score = fuzz.ratio(candidate.lower(), variant.lower())
                    phonetic_equal = _metaphone(candidate) == _metaphone(variant)
                    ok = score >= threshold or (phonetic_equal and score >= threshold - 15)
                    if ok and (best is None or score > best[0]):
                        best = (score, entry.term, n)

        if best is None:
            return None
        return best[1], best[2]


def _metaphone(text: str) -> str:
    return " ".join(jellyfish.metaphone(word) for word in text.split())


def _detokenize(tokens: list[str]) -> str:
    """Join tokens, attaching punctuation to the preceding word."""
    out = ""
    for token in tokens:
        if out and (token[0].isalnum() or token[0] in "'\"([{"):
            out += " " + token
        else:
            out += token
    return out


# -- CLI ---------------------------------------------------------------------


def cli_main(argv: list[str] | None = None) -> int:
    """`wispr-vocab` CLI: add/list/remove dictionary terms."""
    parser = argparse.ArgumentParser(prog="wispr-vocab", description="Manage the wispr-clone custom vocabulary.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add a term")
    p_add.add_argument("term")
    p_add.add_argument("--phonetic", default="", help="how the term sounds, e.g. 'koo-ber-net-eez'")
    p_add.add_argument("--category", default="", choices=["", "name", "company", "term"])

    sub.add_parser("list", help="list all terms")

    p_rm = sub.add_parser("remove", help="remove a term")
    p_rm.add_argument("term")

    p_test = sub.add_parser("test", help="run fuzzy correction over a sample text")
    p_test.add_argument("text")
    p_test.add_argument("--threshold", type=int, default=82)

    args = parser.parse_args(argv)
    vocab = Vocabulary()

    if args.command == "add":
        if vocab.add(args.term, phonetic=args.phonetic, category=args.category):
            print(f"Added {args.term!r} ({len(vocab.entries)} terms)")
            return 0
        print(f"{args.term!r} is already in the vocabulary")
        return 1
    if args.command == "list":
        if not vocab.entries:
            print("Vocabulary is empty. Add terms with: wispr-vocab add 'Acme Widgets'")
        for entry in vocab.entries:
            extras = ", ".join(x for x in (entry.phonetic, entry.category) if x)
            print(f"  {entry.term}" + (f"  ({extras})" if extras else ""))
        return 0
    if args.command == "remove":
        if vocab.remove(args.term):
            print(f"Removed {args.term!r}")
            return 0
        print(f"{args.term!r} not found")
        return 1
    if args.command == "test":
        print(vocab.correct(args.text, threshold=args.threshold))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(cli_main())
