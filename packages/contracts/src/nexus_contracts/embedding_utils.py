"""Shared utilities for e5 embedding model prefix convention.

The intfloat/multilingual-e5-large model requires:
- "passage: " prefix for documents/chunks being indexed
- "query: " prefix for search queries at retrieval time

These functions MUST be used consistently across embedding (Lot 13)
and retrieval (Lot 14) to ensure coherent vector space.
"""
from __future__ import annotations


def format_passage(text: str) -> str:
    """Prefix text for embedding as a passage (document/chunk)."""
    return f"passage: {text}"


def format_query(text: str) -> str:
    """Prefix text for embedding as a query (retrieval search)."""
    return f"query: {text}"
