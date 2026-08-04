"""Stages déterministes de l'usine d'ingestion agentique (LOT44d).

Périmètre strict : huit stages (Planner, Scout, Fetcher, Extractor,
Classifier, RightsAgent, QualityAgent, CoverageAgent), chacun un cœur pur
(``*_core``) sans E/S implicite plus une couche d'exécution (``run_*``) qui
reçoit ses dépendances par injection (réseau via ``ingestion_agents.
dependencies``, transition d'état via ``ingestion_agents.transitions``).

Aucun scheduler, aucune boucle autonome, aucun worker CLI, aucun câblage à
``/ingest/v2`` ni à ``api.py`` — réservé à LOT44e (cf. ADR-0026, ADR-0027).
Aucune création de run/job/table ``jobs`` : ``job_id`` reste structurellement
``NULL`` (``ingestion_agents.transitions.apply_resource_transition``).
"""
from __future__ import annotations

from ingestor.ingestion_agents.classifier import (
    ConformityResult,
    classify_conformity_core,
    run_classifier,
)
from ingestor.ingestion_agents.coverage_agent import build_coverage_snapshot_core
from ingestor.ingestion_agents.dependencies import (
    ArtifactReader,
    ArtifactStore,
    DestinationValidator,
    SafeFetcher,
    default_safe_fetch,
    default_validate_destination,
)
from ingestor.ingestion_agents.extractor import (
    SUPPORTED_MIME_TYPES,
    UnsupportedMimeTypeError,
    extract_text_core,
    run_extractor,
)
from ingestor.ingestion_agents.fetcher import build_artifact_core, run_fetcher
from ingestor.ingestion_agents.planner import plan_search_core, run_planner
from ingestor.ingestion_agents.quality_agent import (
    build_quality_report_core,
    decide_routing_core,
    run_quality_agent,
)
from ingestor.ingestion_agents.rights_agent import (
    UnknownRightsRejectedError,
    assess_rights_core,
    run_rights_agent,
)
from ingestor.ingestion_agents.scout import (
    DomainNotAllowedError,
    discover_candidate_core,
    run_scout,
)
from ingestor.ingestion_agents.transitions import (
    InvalidTransitionError,
    TransitionConflictError,
    TransitionResult,
    apply_resource_transition,
)

__all__ = [
    "SUPPORTED_MIME_TYPES",
    "ArtifactReader",
    "ArtifactStore",
    "ConformityResult",
    "DestinationValidator",
    "DomainNotAllowedError",
    "InvalidTransitionError",
    "SafeFetcher",
    "TransitionConflictError",
    "TransitionResult",
    "UnknownRightsRejectedError",
    "UnsupportedMimeTypeError",
    "apply_resource_transition",
    "assess_rights_core",
    "build_artifact_core",
    "build_coverage_snapshot_core",
    "build_quality_report_core",
    "classify_conformity_core",
    "decide_routing_core",
    "default_safe_fetch",
    "default_validate_destination",
    "discover_candidate_core",
    "extract_text_core",
    "plan_search_core",
    "run_classifier",
    "run_extractor",
    "run_fetcher",
    "run_planner",
    "run_quality_agent",
    "run_rights_agent",
    "run_scout",
]
