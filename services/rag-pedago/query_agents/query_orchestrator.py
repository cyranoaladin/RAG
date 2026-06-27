"""Query orchestrator — entry point for retrieval queries (ADR-0012).

Signs a profile token (rag-pedago is a trusted signer with PROFILE_SECRET)
and routes through level → subject agents. The profile comes from upstream
auth (simulated for pilot), NEVER self-attributed by the agent.

answer_generation_allowed gate: if false → context_only mode (no prose).
"""
from __future__ import annotations

import os
from typing import Any

from nexus_contracts.profile_auth import sign_profile

from .base import is_answer_generation_allowed, is_answer_without_source_allowed
from .query_level_agent import query_level

PROFILE_SECRET = os.environ.get("PROFILE_SECRET", "")


def query_orchestrator(
    question: str,
    niveau: str,
    audience: str,
    matiere: str,
    top_k: int = 5,
    api_url: str | None = None,
    profile_secret: str | None = None,
) -> dict[str, Any]:
    """Orchestrate a retrieval query.

    The orchestrator:
    1. Checks answer_generation_allowed — if false, enforces context_only.
    2. Signs a profile token with PROFILE_SECRET (trusted service signer).
    3. Routes to level → subject agent.
    4. Returns structured context (never generated prose).

    Args:
        question: User's question.
        niveau: Student's level (from upstream auth, not self-attributed).
        audience: Student's audience (from upstream auth).
        matiere: Subject.
        top_k: Number of results.
        api_url: Override API URL for testing.
        profile_secret: Override secret for testing.

    Returns:
        Context-only result with passages, metadata, and governance info.
    """
    secret = profile_secret or PROFILE_SECRET
    if not secret:
        return {
            "mode": "error",
            "error": "PROFILE_SECRET not configured",
        }

    # Governance gate
    answer_allowed = is_answer_generation_allowed()
    answer_without_source = is_answer_without_source_allowed()

    # Sign the profile token (rag-pedago is trusted signer)
    token = sign_profile(niveau, audience, secret)

    # Route through level → subject
    result = query_level(
        niveau=niveau,
        matiere=matiere,
        question=question,
        token=token,
        top_k=top_k,
        api_url=api_url,
    )

    # Enforce context_only if answer generation not allowed
    if not answer_allowed:
        result["mode"] = "context_only"
        result["answer_generation_allowed"] = False
        result["answer_generation_blocked_reason"] = (
            "answer_generation_allowed is false in pedago contract"
        )
    else:
        result["answer_generation_allowed"] = True

    result["answer_without_source_allowed"] = answer_without_source
    return result
