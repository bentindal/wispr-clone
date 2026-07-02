"""Tests for the vocabulary dictionary and fuzzy/phonetic correction."""

import json

import pytest

from wispr_clone.vocabulary import Vocabulary


@pytest.fixture
def vocab(tmp_path):
    return Vocabulary(path=tmp_path / "vocabulary.json")


def test_add_list_remove_roundtrip(vocab):
    assert vocab.add("Kubernetes", category="term")
    assert vocab.add("Siobhan", phonetic="shiv-awn", category="name")
    assert not vocab.add("kubernetes"), "case-insensitive duplicate rejected"
    assert vocab.terms() == ["Kubernetes", "Siobhan"]

    assert vocab.remove("KUBERNETES")
    assert vocab.terms() == ["Siobhan"]
    assert not vocab.remove("never-added")


def test_persistence(tmp_path):
    path = tmp_path / "vocabulary.json"
    v1 = Vocabulary(path=path)
    v1.add("Acme Widgets", category="company")
    v2 = Vocabulary(path=path)
    assert v2.terms() == ["Acme Widgets"]
    data = json.loads(path.read_text())
    assert data["entries"][0]["term"] == "Acme Widgets"


def test_corrupt_file_degrades_gracefully(tmp_path):
    path = tmp_path / "vocabulary.json"
    path.write_text("{not json")
    vocab = Vocabulary(path=path)
    assert vocab.terms() == []
    assert vocab.add("Recovered")  # still usable


def test_fuzzy_correction_near_miss(vocab):
    vocab.add("Kubernetes")
    assert vocab.correct("we deployed it on kubernetties last week") == \
        "we deployed it on Kubernetes last week"


def test_exact_match_normalizes_casing(vocab):
    vocab.add("PostgreSQL")
    assert vocab.correct("switch to postgresql for this") == "switch to PostgreSQL for this"


def test_phonetic_match(vocab):
    vocab.add("Siobhan", phonetic="shivon")
    assert vocab.correct("ask shivon about it") == "ask Siobhan about it"


def test_multiword_term(vocab):
    vocab.add("Acme Widgets")
    assert vocab.correct("the acme widgets contract is signed") == \
        "the Acme Widgets contract is signed"


def test_common_words_never_rewritten(vocab):
    vocab.add("Ware")  # dangerously close to "were"/"where"
    text = "where were you when we did that"
    assert vocab.correct(text) == text


def test_unrelated_text_untouched(vocab):
    vocab.add("Kubernetes")
    text = "let's grab lunch tomorrow at noon."
    assert vocab.correct(text) == text


def test_threshold_is_respected(vocab):
    vocab.add("Anthropic")
    # "anthropology" is a real word only moderately similar
    text = "she studies anthropology"
    assert vocab.correct(text, threshold=95) == text


def test_punctuation_preserved_around_replacement(vocab):
    vocab.add("Kubernetes")
    assert vocab.correct("is kubernetties ready?") == "is Kubernetes ready?"


def test_empty_inputs(vocab):
    assert vocab.correct("") == ""
    vocab.add("Something")
    assert vocab.correct("") == ""
