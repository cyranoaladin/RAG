"""Chargement fail-closed et hors-ligne du reranker canonique v2."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final

try:
    from .model_artifact import ModelArtifactError, verify_model_artifact
except ImportError:  # Image Docker aplatie sous /app.
    from model_artifact import (  # type: ignore[no-redef]
        ModelArtifactError,
        verify_model_artifact,
    )

CANONICAL_RERANK_MODEL: Final = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class RerankerContractError(RuntimeError):
    """Le reranker canonique ne peut pas être prouvé disponible hors-ligne."""


def verify_reranker_artifact(
    artifact_root: Path,
    *,
    expected_inventory_sha256: str,
) -> Path:
    """Vérifier le modèle contre l'empreinte d'inventaire externe attendue."""
    try:
        return verify_model_artifact(
            artifact_root,
            expected_inventory_sha256=expected_inventory_sha256,
            expected_manifest={"model_id": CANONICAL_RERANK_MODEL},
            required_files=frozenset({"config.json"}),
            require_model_weights=True,
        )
    except ModelArtifactError as exc:
        reason = (
            "RERANKER_MODEL_ARTIFACT_PATH_MISSING"
            if str(exc) == "MODEL_ARTIFACT_PATH_MISSING"
            else "RERANKER_MODEL_ARTIFACT_INVALID"
        )
        raise RerankerContractError(reason) from exc


def verify_configured_reranker_artifact() -> Path:
    """Vérifier le répertoire explicitement monté par le déploiement."""
    configured = os.environ.get("RAG_RERANKER_MODEL_CACHE_DIR", "").strip()
    if not configured:
        raise RerankerContractError("RERANKER_MODEL_ARTIFACT_PATH_REQUIRED")
    inventory_sha256 = os.environ.get(
        "RAG_RERANKER_MODEL_INVENTORY_SHA256", ""
    ).strip()
    if not inventory_sha256:
        raise RerankerContractError("RERANKER_MODEL_INVENTORY_SHA256_REQUIRED")
    return verify_reranker_artifact(
        Path(configured),
        expected_inventory_sha256=inventory_sha256,
    )


def load_reranker_model(
    *,
    verified_artifact_root: Path | None = None,
) -> Any:
    """Charger exclusivement l'artefact local, sans téléchargement implicite."""
    if verified_artifact_root is None:
        model_source = verify_configured_reranker_artifact()
    else:
        try:
            if verified_artifact_root.is_symlink():
                raise OSError("symlinked artifact root")
            model_source = verified_artifact_root.resolve(strict=True)
            if not model_source.is_dir():
                raise OSError("artifact root is not a directory")
        except OSError as exc:
            raise RerankerContractError(
                "RERANKER_MODEL_ARTIFACT_PATH_MISSING"
            ) from exc

    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(
            str(model_source),
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
    "verify_configured_reranker_artifact",
    "verify_reranker_artifact",
]
