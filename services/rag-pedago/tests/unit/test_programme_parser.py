"""Tests for programme_parser — proximity matching and bidirectional report."""
from __future__ import annotations

from scrapers.programme_parser import _tokenize_words, find_notion_in_text


def test_dispersed_words_not_counted_as_found():
    """'Loi normale' must NOT match text with 'loi des grands nombres' + 'fonction normale' far apart."""
    text = (
        "La loi des grands nombres est un théorème fondamental. "
        "Elle s'applique aux variables aléatoires indépendantes. "
        "Par ailleurs, la fonction normale est utilisée en statistiques."
    )
    words = _tokenize_words(text)
    result = find_notion_in_text("loi_normale", "Loi normale", words)
    assert result == "not_found", f"Expected not_found, got {result}"


def test_exact_match_in_proximity():
    """'Loi normale' must match when the words appear together."""
    text = "La loi normale est une distribution de probabilité."
    words = _tokenize_words(text)
    result = find_notion_in_text("loi_normale", "Loi normale", words)
    assert result == "found_exact"


def test_partial_match():
    """When half the words are found but not in proximity."""
    text = "Les suites arithmétiques et les suites géométriques."
    words = _tokenize_words(text)
    # "suites_monotones" has "suites" (found) and "monotones" (not found) — partial at best
    result = find_notion_in_text("suites_monotones", "Suites monotones", words)
    assert result in ("found_partial", "not_found")


def test_not_found():
    """A notion completely absent from text."""
    text = "Le théorème de Pythagore s'applique aux triangles rectangles."
    words = _tokenize_words(text)
    result = find_notion_in_text("loi_normale", "Loi normale", words)
    assert result == "not_found"
