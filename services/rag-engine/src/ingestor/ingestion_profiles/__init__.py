"""Profils canoniques et validation déterministe du plan de contrôle d'ingestion (LOT44c).

Périmètre strict : chargement déclaratif des profils (``CollectionProfile``,
LOT44a, ``nexus_contracts.ingestion``, non modifié), sélection explicite et
déterministe, moteur de validation pur (scope vs profil), et une fonction
d'accès minimale au plan de contrôle existant (LOT44b, ``workflow_events``)
pour la persistance éventuelle des résultats. Aucun worker, aucun scheduler,
aucun agent, aucun endpoint, aucune connexion externe — package sibling de
``ingestor.ingestion_control`` (LOT44b), qui n'est jamais modifié.
"""
from __future__ import annotations

from .events import (
    MAX_PAYLOAD_BYTES,
    PROFILE_VALIDATION_EVENT_CONTRACT_VERSION,
    PROFILE_VALIDATION_EVENT_TYPE,
    DriftCheckResult,
    PayloadTooLargeError,
    canonical_json_bytes,
    detect_profile_drift,
    record_validation_result,
)
from .manifest import (
    ManifestVerification,
    ProfileManifestError,
    manifest_fingerprint,
    verify_profile_manifest,
)
from .readiness_gate import (
    ReadinessGateError,
    ReadinessGateResult,
    enforce_readiness_gate,
)
from .registry import (
    PROFILE_VERSION_PATTERN,
    ProfileDisabledError,
    ProfileRegistryError,
    ProfileRegistryLoadError,
    ProfileUnknownError,
    load_profile_registry,
    profile_fingerprint,
    select_profile,
)
from .startup_gate import (
    StartupGateResult,
    enforce_production_manifest_gate,
)
from .validation import (
    SCOPE_DIMENSIONS,
    ValidationIssue,
    ValidationResult,
    validate_scope_against_profile,
)

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "PROFILE_VALIDATION_EVENT_CONTRACT_VERSION",
    "PROFILE_VALIDATION_EVENT_TYPE",
    "PROFILE_VERSION_PATTERN",
    "DriftCheckResult",
    "ManifestVerification",
    "PayloadTooLargeError",
    "ProfileDisabledError",
    "ProfileManifestError",
    "ProfileRegistryError",
    "ProfileRegistryLoadError",
    "ProfileUnknownError",
    "StartupGateResult",
    "canonical_json_bytes",
    "detect_profile_drift",
    "ReadinessGateError",
    "ReadinessGateResult",
    "enforce_production_manifest_gate",
    "enforce_readiness_gate",
    "load_profile_registry",
    "manifest_fingerprint",
    "profile_fingerprint",
    "record_validation_result",
    "select_profile",
    "verify_profile_manifest",
    "SCOPE_DIMENSIONS",
    "ValidationIssue",
    "ValidationResult",
    "validate_scope_against_profile",
]
