"""Level-routing query agent — routes to the subject agent.

Receives the signed token and passes it through to the subject agent.
Does NOT generate tokens or modify the profile.
"""
from __future__ import annotations

from typing import Any

from .query_subject_agent import query_subject


def query_level(
    niveau: str,
    matiere: str,
    question: str,
    token: str,
    top_k: int = 5,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Route a query through the level agent to the subject agent.

    Args:
        niveau: Level (informational — actual filtering by API via token).
        matiere: Subject.
        question: User's question.
        token: Signed HMAC token (from orchestrator).
        top_k: Number of results.
        api_url: Override API URL for testing.

    Returns:
        Context-only result from the subject agent.
    """
    result = query_subject(
        matiere=matiere,
        question=question,
        token=token,
        top_k=top_k,
        api_url=api_url,
    )
    result["routed_niveau"] = niveau
    return result
