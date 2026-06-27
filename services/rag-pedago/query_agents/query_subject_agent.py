"""Subject-level query agent — calls the retrieval API and assembles context.

The agent receives a signed HMAC token (from the orchestrator) and uses it
to call the retrieval API. It NEVER generates the token itself.
Filtering is imposed by the API via the token — the agent cannot widen access.
"""
from __future__ import annotations

from typing import Any

import requests

from .base import RETRIEVAL_API_URL


def search_api(
    query: str,
    token: str,
    top_k: int = 5,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Call the retrieval API and return raw response.

    The token carries the signed profile (niveau, audience).
    The agent passes it through — it cannot modify the profile.
    """
    url = f"{api_url or RETRIEVAL_API_URL}/search"
    resp = requests.post(
        url,
        json={"query": query, "top_k": top_k},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def assemble_context(api_response: dict[str, Any]) -> dict[str, Any]:
    """Assemble a structured context from the API response.

    Returns context_only output — NO generated prose.
    """
    results = api_response.get("results", [])
    passages = [
        {
            "chunk_id": r["chunk_id"],
            "doc_id": r["doc_id"],
            "matiere": r["matiere"],
            "notions": r["notions"],
            "niveau": r["niveau"],
            "similarity": r["similarity"],
            "text": r["preview"],
        }
        for r in results
    ]
    return {
        "mode": "context_only",
        "passages": passages,
        "profile_niveau": api_response.get("profile_niveau", ""),
        "profile_audience": api_response.get("profile_audience", ""),
        "count": len(passages),
    }


def query_subject(
    matiere: str,
    question: str,
    token: str,
    top_k: int = 5,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Execute a subject-level query: call API → assemble context.

    Args:
        matiere: Subject filter (informational — actual filtering by API).
        question: User's question.
        token: Signed HMAC token (from orchestrator, not self-generated).
        top_k: Number of results.
        api_url: Override API URL for testing.

    Returns:
        Context-only result with passages and metadata.
    """
    api_response = search_api(question, token, top_k=top_k, api_url=api_url)
    context = assemble_context(api_response)
    context["matiere"] = matiere
    context["question"] = question
    return context
