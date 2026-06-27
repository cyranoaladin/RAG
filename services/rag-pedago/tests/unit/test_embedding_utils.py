"""Tests for embedding_utils — e5 prefix convention."""
from scrapers.embedding_utils import format_passage, format_query


def test_format_passage_prefix():
    assert format_passage("hello") == "passage: hello"
    assert format_passage("") == "passage: "


def test_format_query_prefix():
    assert format_query("hello") == "query: hello"
    assert format_query("") == "query: "


def test_prefix_has_space():
    """Prefix must end with a space before text."""
    assert format_passage("x").startswith("passage: ")
    assert format_query("x").startswith("query: ")
