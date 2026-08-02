"""Chargement fail-closed et hors-ligne du reranker canonique v2."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

CANONICAL_RERANK_MODEL: Final = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class RerankerContractError(RuntimeError):
    """Le reranker canonique ne peut pas être prouvé disponible hors-ligne."""


def load_reranker_model() -> Any:
    """Charger exclusivement l'artefact local, sans téléchargement implicite."""
    configured = os.environ.get("RAG_RERANKER_MODEL_CACHE_DIR", "").strip()
    model_source = configured or CANONICAL_RERANK_MODEL
    if configured and not Path(configured).is_dir():
        raise RerankerContractError("RERANKER_MODEL_ARTIFACT_PATH_MISSING")

    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(
            model_source,
            max_length=512,
            local_files_only=True,
        )
    except RerankerContractError:
        raise
    except Exception as exc:
        raise RerankerContractError("RERANKER_MODEL_UNAVAILABLE") from exc


__all__ = [
    "CANONICAL_RERANK_MODEL",
    "RerankerContractError",
    "load_reranker_model",
]
