"""Connexions PostgreSQL au schéma ingestion_control (LOT44b).

Remédiation GATE H1 (item K) : **trois** variables distinctes, jamais une
seule réutilisée par commodité. Le DSN applicatif (worker de longue durée)
et les DSN d'autorité/attestation (outils ponctuels d'opérateur) ne se
recouvrent jamais — un outil d'autorité qui retomberait silencieusement
sur ``PG_INGESTION_CONTROL_DSN`` s'exécuterait sous le rôle worker et
ferait exactement ce que la séparation des rôles interdit. L'absence de la
variable dédiée est donc une erreur explicite, jamais un repli.
"""
from __future__ import annotations

import os

APP_DSN_ENV = "PG_INGESTION_CONTROL_DSN"
AUTHORITY_DSN_ENV = "PG_INGESTION_CONTROL_AUTHORITY_DSN"
ATTESTOR_DSN_ENV = "PG_INGESTION_CONTROL_ATTESTOR_DSN"


def _require_dsn(name: str, *, role_hint: str) -> str:
    dsn = os.environ.get(name, "").strip()
    if not dsn:
        raise RuntimeError(
            f"{name} not configured — this entry point requires the "
            f"{role_hint} role and never falls back to another DSN"
        )
    return dsn


def get_ingestion_control_dsn() -> str:
    """DSN du rôle applicatif ``ingestion_control_app`` (worker), distinct
    de PG_RAG_DSN (rag_chunks) — décision D1 : schéma logique séparé,
    jamais de confusion de connexion par défaut."""
    return _require_dsn(APP_DSN_ENV, role_hint="ingestion_control_app")


def get_authority_dsn() -> str:
    """DSN du rôle ``ingestion_control_authority`` — seul habilité à écrire
    ``scope_authorizations`` (LOT41A). Jamais présent dans l'environnement
    du worker de longue durée."""
    return _require_dsn(AUTHORITY_DSN_ENV, role_hint="ingestion_control_authority")


def get_attestor_dsn() -> str:
    """DSN du rôle ``ingestion_control_attestor`` — seul habilité à écrire
    ``publication_attestations`` (LOT42). Jamais présent dans
    l'environnement du worker de longue durée."""
    return _require_dsn(ATTESTOR_DSN_ENV, role_hint="ingestion_control_attestor")


__all__ = [
    "APP_DSN_ENV",
    "ATTESTOR_DSN_ENV",
    "AUTHORITY_DSN_ENV",
    "get_attestor_dsn",
    "get_authority_dsn",
    "get_ingestion_control_dsn",
]
