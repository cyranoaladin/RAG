"""Worker CLI et scheduler déterministe (LOT44e).

Consomme les jobs créés dans ``ingestion_control.jobs`` (migration 004),
exécute la chaîne de stages LOT44d en propageant ``job_id`` à chaque
transition, ne fait jamais progresser ``resource_state`` en dehors de
``apply_resource_transition`` (validation centralisée + CAS). N'active
jamais ``QUALITY_CHECKED -> ROUTED``. Aucun worker, aucun scheduler, aucun
processus de ce module n'est câblé à un déploiement réel — ``python -m
ingestor.ingestion_worker.cli`` est un point d'entrée autonome, jamais
lancé automatiquement par ``api.py``/``docker-compose.v2.yml``.
"""
from __future__ import annotations

from ingestor.ingestion_worker.runner import (
    IterationOutcome,
    MissingPayloadFieldError,
    WorkerDeps,
    run_worker_iteration,
)

__all__ = [
    "IterationOutcome",
    "MissingPayloadFieldError",
    "WorkerDeps",
    "run_worker_iteration",
]
