"""Fail-closed embedding contract for the RAG v2 pgvector pipeline.

The v2 schema stores ``vector(1024)`` and the certified retrieval pipeline
uses ``intfloat/multilingual-e5-large``.  This module deliberately has no
fallback model and never pads or truncates an embedding: a mismatch must stop
the operation before a vector query or write is attempted.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

import psycopg

CANONICAL_EMBED_MODEL = "intfloat/multilingual-e5-large"
CANONICAL_EMBED_DIM = 1024


class EmbeddingContractError(RuntimeError):
    """Raised when the v2 embedding contract cannot be proven consistent."""


def declared_embedding_model(env: Mapping[str, str] | None = None) -> str:
    """Return the only model allowed by the v2 pgvector contract."""
    configured = (env or os.environ).get("EMBED_MODEL", CANONICAL_EMBED_MODEL).strip()
    if configured != CANONICAL_EMBED_MODEL:
        raise EmbeddingContractError("EMBEDDING_MODEL_CONTRACT_MISMATCH")
    return configured


def declared_embedding_dim(env: Mapping[str, str] | None = None) -> int:
    """Return the only embedding dimension allowed by the v2 schema."""
    raw = (env or os.environ).get("EMBED_DIM", str(CANONICAL_EMBED_DIM))
    try:
        configured = int(raw)
    except (TypeError, ValueError) as exc:
        raise EmbeddingContractError("EMBEDDING_DIMENSION_INVALID") from exc
    if configured != CANONICAL_EMBED_DIM:
        raise EmbeddingContractError("EMBEDDING_DIMENSION_CONTRACT_MISMATCH")
    return configured


def validate_embedding_contract(
    *,
    model: str,
    declared_dim: int,
    runtime_dim: int,
    pgvector_dim: int,
) -> None:
    """Reject every model or dimension mismatch before vector I/O.

    There is intentionally no conversion path here.  A 768d vector cannot be
    made valid for a 1024d index by padding, truncation, or an implicit model
    fallback.
    """
    if model != CANONICAL_EMBED_MODEL:
        raise EmbeddingContractError("EMBEDDING_MODEL_CONTRACT_MISMATCH")
    if declared_dim != CANONICAL_EMBED_DIM:
        raise EmbeddingContractError("EMBEDDING_DIMENSION_CONTRACT_MISMATCH")
    if runtime_dim != declared_dim:
        raise EmbeddingContractError("EMBEDDING_RUNTIME_DIMENSION_MISMATCH")
    if pgvector_dim != declared_dim:
        raise EmbeddingContractError("PGVECTOR_DIMENSION_MISMATCH")


def pgvector_dimension(pg_dsn: str) -> int:
    """Read the declared dimension of ``rag_chunks.vector`` without mutation."""
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute AS a
                JOIN pg_class AS c ON c.oid = a.attrelid
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = 'rag_chunks'
                  AND a.attname = 'vector'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            )
            row = cur.fetchone()
    if not row or not isinstance(row[0], str):
        raise EmbeddingContractError("PGVECTOR_DIMENSION_UNAVAILABLE")
    match = re.fullmatch(r"vector\((\d+)\)", row[0])
    if not match:
        raise EmbeddingContractError("PGVECTOR_DIMENSION_UNAVAILABLE")
    return int(match.group(1))


def load_embedding_model() -> Any:
    """Load the canonical model only from the runtime image/cache.

    ``local_files_only`` prevents a request path from silently downloading or
    switching models.  A deployment must pre-provision this exact model before
    it can serve or ingest v2 vectors.
    """
    model = declared_embedding_model()
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(model, local_files_only=True)
    except Exception as exc:
        raise EmbeddingContractError("EMBEDDING_MODEL_UNAVAILABLE") from exc


def runtime_embedding_dimension(embed_model: Any) -> int:
    """Read the native model dimension and reject unknown model objects."""
    try:
        dimension = int(embed_model.get_sentence_embedding_dimension())
    except Exception as exc:
        raise EmbeddingContractError("EMBEDDING_RUNTIME_DIMENSION_UNAVAILABLE") from exc
    if dimension <= 0:
        raise EmbeddingContractError("EMBEDDING_RUNTIME_DIMENSION_UNAVAILABLE")
    return dimension


def validate_runtime_embedding_contract(embed_model: Any, pg_dsn: str) -> None:
    """Validate model, native output dimension, and pgvector schema together."""
    model = declared_embedding_model()
    declared_dim = declared_embedding_dim()
    validate_embedding_contract(
        model=model,
        declared_dim=declared_dim,
        runtime_dim=runtime_embedding_dimension(embed_model),
        pgvector_dim=pgvector_dimension(pg_dsn),
    )


def embedding_contract_health(
    *,
    model: str,
    declared_dim: int | None,
    runtime_dim: int | None,
    pgvector_dim: int | None,
) -> dict[str, str | int | bool | None]:
    """Build a non-sensitive health payload for the embedding contract."""
    try:
        if declared_dim is None or runtime_dim is None or pgvector_dim is None:
            raise EmbeddingContractError("EMBEDDING_CONTRACT_NOT_FULLY_TESTABLE")
        validate_embedding_contract(
            model=model,
            declared_dim=declared_dim,
            runtime_dim=runtime_dim,
            pgvector_dim=pgvector_dim,
        )
        contract_ok = True
    except EmbeddingContractError:
        contract_ok = False

    return {
        "embedding_model": model,
        "embedding_dim_declared": declared_dim,
        "embedding_dim_runtime": runtime_dim,
        "pgvector_dim": pgvector_dim,
        "embedding_contract_ok": contract_ok,
    }


def embedding_contract_health_from_environment(pg_dsn: str | None) -> dict[str, str | int | bool | None]:
    """Return health data without exposing configuration values such as a DSN.

    The runtime model is intentionally not loaded by ``/health``.  Loading it
    can allocate substantial memory and download artifacts; it is verified by
    the explicit pre-ingestion smoke and by the query/write paths instead.
    """
    model = os.environ.get("EMBED_MODEL", CANONICAL_EMBED_MODEL)
    try:
        declared_dim: int | None = declared_embedding_dim()
        declared_embedding_model()
    except EmbeddingContractError:
        declared_dim = None

    pg_dim: int | None = None
    if pg_dsn:
        try:
            pg_dim = pgvector_dimension(pg_dsn)
        except (EmbeddingContractError, psycopg.Error):
            pg_dim = None

    return embedding_contract_health(
        model=model,
        declared_dim=declared_dim,
        runtime_dim=None,
        pgvector_dim=pg_dim,
    )
