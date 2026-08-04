"""Connexion PostgreSQL au schéma ingestion_control (LOT44b)."""
from __future__ import annotations

import os


def get_ingestion_control_dsn() -> str:
    """DSN dédié, distinct de PG_RAG_DSN (rag_chunks) — décision D1 :
    schéma logique séparé, jamais de confusion de connexion par défaut."""
    dsn = os.environ.get("PG_INGESTION_CONTROL_DSN", "").strip()
    if not dsn:
        raise RuntimeError("PG_INGESTION_CONTROL_DSN not configured")
    return dsn


__all__ = ["get_ingestion_control_dsn"]
