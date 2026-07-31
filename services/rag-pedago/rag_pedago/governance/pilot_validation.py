"""Chargement du périmètre de validation réel, encore dormant."""

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

_EXPECTED_SCOPE_ID = "libre_terminale_maths_nsi_real_v1"
_DORMANT_STATUS = "eligible_for_promotion"
_EXPECTED_SCHOOL_YEAR = "2026-2027"
_EXPECTED_IDENTITY = {
    "tenant": "libre_terminale",
    "level": "terminale",
    "track": "generale",
    "teaching_status": "specialite",
    "audience": "libre",
    "candidates": ("cned_libre", "individuel", "libre"),
}
_EXPECTED_COLLECTIONS = (
    "rag_nexus_maths_terminale_gen_specialite",
    "rag_nexus_nsi_terminale_specialite",
)
_EXPECTED_SUBJECTS = {
    "maths": {
        "collection": "rag_nexus_maths_terminale_gen_specialite",
        "taxonomy_path": "taxonomy/maths/terminale_gen_specialite.yml",
        "taxonomy_sha256": "4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6",
        "programme_version": "BOEN_special_8_2019-07-25",
    },
    "nsi": {
        "collection": "rag_nexus_nsi_terminale_specialite",
        "taxonomy_path": "taxonomy/nsi/terminale.yml",
        "taxonomy_sha256": "b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f",
        "programme_version": "BOEN_special_8_2019-07-25",
    },
}
_EXPECTED_POLICY_ID = "libre_terminale_validation_policy_v1"
_EXPECTED_POLICY_SCOPE_REF = _EXPECTED_SCOPE_ID
_EXPECTED_ACTIVATION_BOUNDARY = "LOT41A"
_EXPECTED_ENVIRONMENT = {
    "environment_id": "nexus-validation-1",
    "isolation_status": "intended_pending_lot41a",
    "public_routes_allowed": False,
    "credentials_ref_env": "NEXUS_VALIDATION_CREDENTIALS_REF",
    "dsn_ref_env": "NEXUS_VALIDATION_DATABASE_URL",
    "bucket_ref_env": "NEXUS_VALIDATION_BUCKET",
    "network_ref_env": "NEXUS_VALIDATION_NETWORK",
}
_EXPECTED_MATRIX: dict[str, dict[str, object]] = {
    "read_real_documents": {
        "capabilities": ("validation_real_documents_allowed",),
        "allowed_callers": ("lot42_publisher", "lot43_evaluator"),
        "quality_chain_required": None,
    },
    "publish_reviewed_chunks": {
        "capabilities": (
            "validation_real_documents_allowed",
            "validation_pipeline_allowed",
        ),
        "allowed_callers": ("rag-engine",),
        "quality_chain_required": True,
    },
    "generate_grounded_answer": {
        "capabilities": (
            "validation_answer_generation_allowed",
            "validation_openrouter_allowed",
        ),
        "allowed_callers": ("rag-engine",),
        "quality_chain_required": None,
    },
}
_EXPECTED_AUTHORIZATION = {
    "decision": "AUTHORIZE_VALIDATION_PIPELINE",
    "authority_role": "lead",
    "evidence_kind": "github_pr_approval",
    "scope_digest_required": True,
    "policy_digest_required": True,
    "expiry_required": True,
    "rights_verification_required": True,
    "pii_absence_required": True,
    "rollback_proof_required": True,
}
_PUBLIC_CALLERS = frozenset({"cockpit", "public_bff"})


class PilotIdentity(BaseModel):
    """Identité contractuelle admise par le pilote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str
    level: str
    track: str
    teaching_status: str
    audience: str
    candidates: tuple[str, ...]


class PilotSubject(BaseModel):
    """Matière, collection et taxonomie immuables du pilote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str
    collection: str
    taxonomy_path: str
    taxonomy_sha256: str
    programme_version: str
    notions: tuple[str, ...]


class PilotValidationScope(BaseModel):
    """Périmètre canonique du pilote Mathématiques + NSI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope_id: str
    status: str
    school_year: str
    identity: PilotIdentity
    subjects: tuple[PilotSubject, ...]

    @property
    def collections(self) -> tuple[str, ...]:
        return tuple(subject.collection for subject in self.subjects)


class ValidationCapabilities(BaseModel):
    """Capacités privées du seul environnement de validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validation_real_documents_allowed: bool
    validation_pipeline_allowed: bool
    validation_answer_generation_allowed: bool
    validation_openrouter_allowed: bool


class PublicLocks(BaseModel):
    """Valeurs attendues des verrous publics historiques."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    real_documents_allowed: bool
    ui_runtime_allowed: bool
    answer_generation_allowed: bool
    curated_ingestion_allowed: bool


class ValidationEnvironment(BaseModel):
    """Intention d'isolation, sans secret ni preuve d'activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment_id: str
    isolation_status: str
    public_routes_allowed: bool
    credentials_ref_env: str
    dsn_ref_env: str
    bucket_ref_env: str
    network_ref_env: str


class AuthorizationOperation(BaseModel):
    """Capacités et appelants requis pour une opération de validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capabilities: tuple[str, ...]
    allowed_callers: tuple[str, ...]
    quality_chain_required: bool | None = None


class AuthorizationMatrix(BaseModel):
    """Matrice exhaustive des opérations admises par la politique."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    read_real_documents: AuthorizationOperation
    publish_reviewed_chunks: AuthorizationOperation
    generate_grounded_answer: AuthorizationOperation


class RequiredAuthorization(BaseModel):
    """Preuves externes exigées avant toute future promotion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: str
    authority_role: str
    evidence_kind: str
    scope_digest_required: bool
    policy_digest_required: bool
    expiry_required: bool
    rights_verification_required: bool
    pii_absence_required: bool
    rollback_proof_required: bool


class PilotValidationPolicy(BaseModel):
    """Politique de validation privée, chargeable sans l'activer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str
    status: str
    scope_ref: str
    activation_boundary: str
    capabilities: ValidationCapabilities
    public_locks: PublicLocks
    validation_environment: ValidationEnvironment
    authorization_matrix: AuthorizationMatrix
    required_authorization: RequiredAuthorization


def load_scope(path: Path) -> PilotValidationScope:
    """Charge un document de scope strict depuis le disque local."""

    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PilotValidationScope.model_validate(payload)


def load_policy(path: Path) -> PilotValidationPolicy:
    """Charge une politique stricte sans lui conférer aucune autorisation."""

    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PilotValidationPolicy.model_validate(payload)


def validate_dormant_policy(policy: PilotValidationPolicy) -> tuple[str, ...]:
    """Exige que les quatre capacités privées restent exactement fermées."""

    reasons: list[str] = []
    for capability, value in policy.capabilities.model_dump().items():
        if value is not False:
            reasons.append(f"policy.capability_not_dormant:{capability}")
    return tuple(reasons)


def validate_policy_integrity(
    policy: PilotValidationPolicy,
    public_contract: object,
) -> tuple[str, ...]:
    """Valide l'identité et les frontières fermées de la politique."""

    reasons: list[str] = []
    if policy.policy_id != _EXPECTED_POLICY_ID:
        reasons.append("policy.id_mismatch")
    if policy.status != _DORMANT_STATUS:
        reasons.append("policy.status_not_dormant")
    if policy.scope_ref != _EXPECTED_POLICY_SCOPE_REF:
        reasons.append("policy.scope_ref_mismatch")
    if policy.activation_boundary != _EXPECTED_ACTIVATION_BOUNDARY:
        reasons.append("policy.activation_boundary_mismatch")

    for field, expected in _EXPECTED_ENVIRONMENT.items():
        if getattr(policy.validation_environment, field) != expected:
            reasons.append(f"policy.validation_environment_mismatch:{field}")

    for operation_name, expected in _EXPECTED_MATRIX.items():
        operation = getattr(policy.authorization_matrix, operation_name)
        for field, expected_value in expected.items():
            if getattr(operation, field) != expected_value:
                reasons.append(f"policy.authorization_matrix_mismatch:{operation_name}:{field}")
        for caller in operation.allowed_callers:
            if caller in _PUBLIC_CALLERS:
                reasons.append(f"policy.public_caller_forbidden:{operation_name}:{caller}")

    for field, expected in _EXPECTED_AUTHORIZATION.items():
        if getattr(policy.required_authorization, field) != expected:
            reasons.append(f"policy.required_authorization_mismatch:{field}")

    if not isinstance(public_contract, Mapping):
        reasons.append("policy.public_contract_invalid")
        return tuple(reasons)
    for lock, expected in policy.public_locks.model_dump().items():
        if expected is not False:
            reasons.append(f"policy.public_lock_not_closed:{lock}")
        if public_contract.get(lock) is not expected:
            reasons.append(f"policy.public_lock_mismatch:{lock}")
    return tuple(reasons)


def _taxonomy_notions(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()

    notions: list[str] = []
    themes = payload.get("themes", ())
    if not isinstance(themes, list):
        return ()
    for theme in themes:
        if not isinstance(theme, dict):
            continue
        theme_notions = theme.get("notions", ())
        if not isinstance(theme_notions, list):
            continue
        for notion in theme_notions:
            if isinstance(notion, dict) and isinstance(notion.get("id"), str):
                notions.append(notion["id"])
    return tuple(notions)


def _is_confined_taxonomy_path(path: str, *, taxonomy_root: Path) -> bool:
    try:
        relative_path = Path(path)
        if (
            relative_path.is_absolute()
            or not relative_path.parts
            or relative_path.parts[0] != "taxonomy"
            or ".." in relative_path.parts
        ):
            return False

        resolved_taxonomy_root = taxonomy_root.resolve()
        resolved_path = (resolved_taxonomy_root.parent / relative_path).resolve()
    except (OSError, RuntimeError, ValueError):
        return False

    return resolved_path.is_relative_to(resolved_taxonomy_root)


def _scope_metadata_reasons(
    scope: PilotValidationScope,
    *,
    taxonomy_root: Path,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if scope.scope_id != _EXPECTED_SCOPE_ID:
        reasons.append("scope.id_mismatch")
    if scope.status != _DORMANT_STATUS:
        reasons.append("scope.status_not_dormant")
    if scope.school_year != _EXPECTED_SCHOOL_YEAR:
        reasons.append("scope.school_year_mismatch")

    for field, expected in _EXPECTED_IDENTITY.items():
        if getattr(scope.identity, field) != expected:
            reasons.append(f"scope.identity_mismatch:{field}")

    if tuple(sorted(scope.collections)) != _EXPECTED_COLLECTIONS:
        reasons.append("scope.collections_mismatch")
        return tuple(reasons)

    if tuple(sorted(subject.subject for subject in scope.subjects)) != tuple(
        sorted(_EXPECTED_SUBJECTS)
    ):
        reasons.append("scope.subjects_mismatch")
        return tuple(reasons)

    for subject in sorted(scope.subjects, key=lambda item: item.subject):
        if not _is_confined_taxonomy_path(subject.taxonomy_path, taxonomy_root=taxonomy_root):
            reasons.append(f"scope.taxonomy_path_not_confined:{subject.subject}")
            continue

        expected_subject = _EXPECTED_SUBJECTS[subject.subject]
        for field in ("collection", "taxonomy_path", "programme_version"):
            if getattr(subject, field) != expected_subject[field]:
                reasons.append(f"scope.{field}_mismatch:{subject.subject}")
        if subject.taxonomy_sha256 != expected_subject["taxonomy_sha256"]:
            reasons.append(f"scope.taxonomy_sha256_mismatch:{subject.subject}")

    return tuple(reasons)


def validate_scope_integrity(
    scope: PilotValidationScope,
    *,
    service_root: Path | None = None,
) -> tuple[str, ...]:
    """Vérifie l'adressage brut et les notions déclarées par matière."""

    root = (service_root or Path(__file__).resolve().parents[2]).resolve()
    taxonomy_root = root / "taxonomy"
    metadata_reasons = _scope_metadata_reasons(scope, taxonomy_root=taxonomy_root)
    if metadata_reasons:
        return metadata_reasons

    reasons: list[str] = []
    for subject in sorted(scope.subjects, key=lambda item: item.subject):
        taxonomy = root / subject.taxonomy_path
        try:
            raw_taxonomy = taxonomy.read_bytes()
        except OSError:
            reasons.append(f"scope.taxonomy_unreadable:{subject.subject}")
            continue
        if sha256(raw_taxonomy).hexdigest() != subject.taxonomy_sha256:
            reasons.append(f"scope.taxonomy_sha256_mismatch:{subject.subject}")
            continue
        try:
            taxonomy_payload = yaml.safe_load(raw_taxonomy)
        except yaml.YAMLError:
            reasons.append(f"scope.taxonomy_invalid:{subject.subject}")
            continue
        taxonomy_notions = _taxonomy_notions(taxonomy_payload)
        if taxonomy_notions != subject.notions or len(taxonomy_notions) != len(
            set(taxonomy_notions)
        ):
            reasons.append(f"scope.notions_mismatch:{subject.subject}")
    return tuple(reasons)
