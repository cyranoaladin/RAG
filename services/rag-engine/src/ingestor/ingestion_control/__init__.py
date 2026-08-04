"""Primitives de concurrence du plan de contrôle d'ingestion (LOT44b).

Périmètre strict : quatre primitives atomiques (claim, transition CAS,
retry/backoff, lease reaper) opérant sur le schéma PostgreSQL
``ingestion_control`` (LOT44b, décision D1). Aucun worker, aucun
scheduler, aucun agent, aucun endpoint — ces primitives sont des fonctions
pures/transactionnelles, jamais des boucles ni des processus autonomes.

La machine d'état réutilisée ici est exactement celle de
``nexus_contracts.resource_state`` (LOT44a, ADR-0024) — aucune seconde
machine d'état n'est définie dans ce module.
"""
from __future__ import annotations

from ingestor.ingestion_control.claim import CLAIMABLE_STATES, Claim, claim_resource
from ingestor.ingestion_control.db import get_ingestion_control_dsn
from ingestor.ingestion_control.lease_reaper import ReapedLease, reap_expired_leases
from ingestor.ingestion_control.retry import (
    RetryOutcome,
    compute_backoff_seconds,
    record_retry,
)
from ingestor.ingestion_control.transitions import (
    InvalidTransitionError,
    TransitionConflictError,
    TransitionResult,
    cas_transition,
)

__all__ = [
    "CLAIMABLE_STATES",
    "Claim",
    "claim_resource",
    "get_ingestion_control_dsn",
    "ReapedLease",
    "reap_expired_leases",
    "RetryOutcome",
    "compute_backoff_seconds",
    "record_retry",
    "InvalidTransitionError",
    "TransitionConflictError",
    "TransitionResult",
    "cas_transition",
]
