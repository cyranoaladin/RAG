"""Chargement du périmètre de validation réel, encore dormant."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Any, TypeVar

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PrivateAttr, StrictBool
from pydantic_core import PydanticSerializationError

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
_MAX_YAML_BYTES = 1024 * 1024
_MAX_YAML_DEPTH = 64
_DocumentT = TypeVar("_DocumentT", bound=BaseModel)


class _BoundedUniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader borné qui refuse les clés dupliquées récursivement."""

    def __init__(self, stream: str | bytes) -> None:
        super().__init__(stream)
        self._composition_depth = 0

    def compose_node(
        self,
        parent: yaml.Node | None,
        index: int,
    ) -> yaml.Node | None:
        if self._composition_depth >= _MAX_YAML_DEPTH:
            raise yaml.YAMLError("maximum YAML nesting depth exceeded")
        self._composition_depth += 1
        try:
            return super().compose_node(parent, index)
        finally:
            self._composition_depth -= 1

    def construct_mapping(
        self,
        node: yaml.MappingNode,
        deep: bool = False,
    ) -> dict[object, object]:
        self.flatten_mapping(node)
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key ({key!r})",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _parse_yaml_bytes(raw: bytes) -> Any:
    """Parse un document YAML local borné, sûr et non ambigu."""

    if len(raw) > _MAX_YAML_BYTES:
        raise yaml.YAMLError("maximum YAML document size exceeded")
    try:
        return yaml.load(raw, Loader=_BoundedUniqueKeySafeLoader)
    except RuntimeError as error:
        raise yaml.YAMLError("YAML parser runtime failure") from error


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
    _source_bytes: bytes | None = PrivateAttr(default=None)
    _source_sha256: str | None = PrivateAttr(default=None)
    _source_fingerprint: str | None = PrivateAttr(default=None)

    @property
    def collections(self) -> tuple[str, ...]:
        return tuple(subject.collection for subject in self.subjects)


class ValidationCapabilities(BaseModel):
    """Capacités privées du seul environnement de validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validation_real_documents_allowed: StrictBool
    validation_pipeline_allowed: StrictBool
    validation_answer_generation_allowed: StrictBool
    validation_openrouter_allowed: StrictBool


class PublicLocks(BaseModel):
    """Valeurs attendues des verrous publics historiques."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    real_documents_allowed: StrictBool
    ui_runtime_allowed: StrictBool
    answer_generation_allowed: StrictBool
    curated_ingestion_allowed: StrictBool


class ValidationEnvironment(BaseModel):
    """Intention d'isolation, sans secret ni preuve d'activation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    environment_id: str
    isolation_status: str
    public_routes_allowed: StrictBool
    credentials_ref_env: str
    dsn_ref_env: str
    bucket_ref_env: str
    network_ref_env: str


class AuthorizationOperation(BaseModel):
    """Capacités et appelants requis pour une opération de validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capabilities: tuple[str, ...]
    allowed_callers: tuple[str, ...]
    quality_chain_required: StrictBool | None = None


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
    scope_digest_required: StrictBool
    policy_digest_required: StrictBool
    expiry_required: StrictBool
    rights_verification_required: StrictBool
    pii_absence_required: StrictBool
    rollback_proof_required: StrictBool


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
    _source_bytes: bytes | None = PrivateAttr(default=None)
    _source_sha256: str | None = PrivateAttr(default=None)
    _source_fingerprint: str | None = PrivateAttr(default=None)


class AuthorizedIdentity(BaseModel):
    """Profil exhaustif couvert par une autorisation LOT41A."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str
    level: str
    track: str
    teaching_status: str
    audience: str
    candidates: tuple[str, ...]
    subjects: tuple[str, ...]
    school_year: str


class RollbackProof(BaseModel):
    """Preuve versionnée et datée d'un rollback testé."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_ref: str
    tested: StrictBool
    tested_at: AwareDatetime


class ValidationAuthorization(BaseModel):
    """Décision humaine proposée, sans autorité auto-déclarée."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authorization_id: str
    decision: str
    status: str
    scope_ref: str
    scope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    activation_policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lot41_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    environment_id: str
    collections: tuple[str, ...]
    identity: AuthorizedIdentity
    rights_verified: StrictBool
    provenance_verified: StrictBool
    pii_absence_verified: StrictBool
    rollback: RollbackProof
    pull_request: int = Field(strict=True, gt=0)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    _source_bytes: bytes | None = PrivateAttr(default=None)
    _source_sha256: str | None = PrivateAttr(default=None)
    _source_fingerprint: str | None = PrivateAttr(default=None)


class GitHubApprovalEvidence(BaseModel):
    """Readback GitHub indépendant de la proposition d'autorisation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_kind: str
    repository: str
    pull_request: int = Field(strict=True, gt=0)
    base_branch: str
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    approved_head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    referenced_lot41_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    authorization_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_login: str = Field(pattern=r".*\S.*")
    reviewer_role: str
    reviewer_human: StrictBool
    approved_at: AwareDatetime
    merged_at: AwareDatetime
    readback_at: AwareDatetime
    revoked: StrictBool
    merge_sha: str = Field(pattern=r"^[0-9a-f]{40}$")


class PublicationPackage(BaseModel):
    """Package de publication dont le contenu est adressé par SHA-256."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    package_id: str
    content_ref: str
    content: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    quality: str
    gate: str
    review: str
    quarantine: StrictBool
    revoked: StrictBool
    publisher: str


class ValidationRequest(BaseModel):
    """Requête pure évaluée avant tout accès au plan de données."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: str
    caller: str
    environment_id: str
    collection: str
    tenant: str
    level: str
    track: str
    teaching_status: str
    audience: str
    candidate: str
    subject: str
    school_year: str


class AuthorizationDecision(BaseModel):
    """Résultat déterministe et sans effet de bord du garde."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: StrictBool
    reasons: tuple[str, ...]


def _model_fingerprint(model: BaseModel) -> str:
    canonical = json.dumps(
        model.model_dump(mode="json", warnings="error"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def load_scope(path: Path) -> PilotValidationScope:
    """Charge un document de scope strict depuis le disque local."""

    raw = path.read_bytes()
    payload = _parse_yaml_bytes(raw)
    scope = PilotValidationScope.model_validate(payload)
    scope._source_bytes = raw
    scope._source_sha256 = sha256(raw).hexdigest()
    scope._source_fingerprint = _model_fingerprint(scope)
    return scope


def load_policy(path: Path) -> PilotValidationPolicy:
    """Charge une politique stricte sans lui conférer aucune autorisation."""

    raw = path.read_bytes()
    payload = _parse_yaml_bytes(raw)
    policy = PilotValidationPolicy.model_validate(payload)
    policy._source_bytes = raw
    policy._source_sha256 = sha256(raw).hexdigest()
    policy._source_fingerprint = _model_fingerprint(policy)
    return policy


def _load_strict_document(path: Path, model: type[_DocumentT]) -> _DocumentT:
    raw = path.read_bytes()
    payload = _parse_yaml_bytes(raw)
    return model.model_validate(payload)


def load_authorization(path: Path) -> ValidationAuthorization:
    """Charge une proposition d'autorisation stricte."""

    raw = path.read_bytes()
    payload = _parse_yaml_bytes(raw)
    authorization = ValidationAuthorization.model_validate(payload)
    authorization._source_bytes = raw
    authorization._source_sha256 = sha256(raw).hexdigest()
    authorization._source_fingerprint = _model_fingerprint(authorization)
    return authorization


def load_approval_evidence(path: Path) -> GitHubApprovalEvidence:
    """Charge un readback GitHub strict, sans le vérifier implicitement."""

    return _load_strict_document(path, GitHubApprovalEvidence)


def load_publication_package(path: Path) -> PublicationPackage:
    """Charge un package strict, sans autoriser sa publication."""

    return _load_strict_document(path, PublicationPackage)


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
            taxonomy_payload = _parse_yaml_bytes(raw_taxonomy)
        except (RuntimeError, yaml.YAMLError):
            reasons.append(f"scope.taxonomy_invalid:{subject.subject}")
            continue
        taxonomy_notions = _taxonomy_notions(taxonomy_payload)
        if taxonomy_notions != subject.notions or len(taxonomy_notions) != len(
            set(taxonomy_notions)
        ):
            reasons.append(f"scope.notions_mismatch:{subject.subject}")
    return tuple(reasons)


def _safe_document(
    value: _DocumentT | Path | None,
    *,
    model: type[_DocumentT],
) -> _DocumentT | None:
    if isinstance(value, model):
        return _revalidate_instance(value, model=model)
    if not isinstance(value, Path):
        return None
    try:
        return _load_strict_document(value, model)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return None


def _revalidate_instance(
    value: BaseModel,
    *,
    model: type[_DocumentT],
) -> _DocumentT | None:
    try:
        payload = value.model_dump(mode="python", warnings="error")
        return model.model_validate(payload, strict=True)
    except (PydanticSerializationError, TypeError, ValueError):
        return None


def _restore_source_attestation(
    clean: PilotValidationScope | PilotValidationPolicy | ValidationAuthorization,
    source: PilotValidationScope | PilotValidationPolicy | ValidationAuthorization,
) -> bool:
    raw_digest = _raw_digest(source)
    raw = source._source_bytes
    if raw_digest is None or not isinstance(raw, bytes):
        return False
    clean._source_bytes = raw
    clean._source_sha256 = raw_digest
    clean._source_fingerprint = _model_fingerprint(clean)
    return True


def _safe_scope(value: PilotValidationScope | Path) -> PilotValidationScope | None:
    if isinstance(value, PilotValidationScope):
        if _raw_digest(value) is None:
            return None
        clean = _revalidate_instance(value, model=PilotValidationScope)
        if clean is None:
            return None
        if not _restore_source_attestation(clean, value):
            return None
        return clean
    try:
        return load_scope(value)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return None


def _safe_policy(value: PilotValidationPolicy | Path) -> PilotValidationPolicy | None:
    if isinstance(value, PilotValidationPolicy):
        if _raw_digest(value) is None:
            return None
        clean = _revalidate_instance(value, model=PilotValidationPolicy)
        if clean is None:
            return None
        if not _restore_source_attestation(clean, value):
            return None
        return clean
    try:
        return load_policy(value)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return None


def _safe_authorization(
    value: ValidationAuthorization | Path | None,
) -> ValidationAuthorization | None:
    if isinstance(value, ValidationAuthorization):
        if _raw_digest(value) is None:
            return None
        clean = _revalidate_instance(value, model=ValidationAuthorization)
        if clean is None:
            return None
        if not _restore_source_attestation(clean, value):
            return None
        return clean
    if not isinstance(value, Path):
        return None
    try:
        return load_authorization(value)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return None


def _safe_request(value: object) -> ValidationRequest | None:
    if not isinstance(value, ValidationRequest):
        return None
    return _revalidate_instance(value, model=ValidationRequest)


def _safe_ref(value: str) -> bool:
    if "\0" in value:
        return False
    try:
        path = Path(value)
        windows_path = PureWindowsPath(value)
        return (
            bool(path.parts)
            and not path.is_absolute()
            and not windows_path.is_absolute()
            and not windows_path.drive
            and not windows_path.root
            and not windows_path.anchor
            and ".." not in path.parts
            and ".." not in windows_path.parts
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _load_public_contract(service_root: Path) -> Mapping[str, object] | None:
    path = service_root / "configs" / "pedago_interface_contract.yml"
    try:
        raw = path.read_bytes()
        payload = _parse_yaml_bytes(raw)
    except (OSError, RuntimeError, UnicodeError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return payload


def _raw_digest(
    value: PilotValidationScope | PilotValidationPolicy | ValidationAuthorization,
) -> str | None:
    raw = value._source_bytes
    if not isinstance(raw, bytes):
        return None
    try:
        payload = _parse_yaml_bytes(raw)
        if type(value) is PilotValidationScope:
            reparsed: BaseModel = PilotValidationScope.model_validate(payload)
        elif type(value) is PilotValidationPolicy:
            reparsed = PilotValidationPolicy.model_validate(payload)
        elif type(value) is ValidationAuthorization:
            reparsed = ValidationAuthorization.model_validate(payload)
        else:
            return None
        source_fingerprint = _model_fingerprint(reparsed)
        received_fingerprint = _model_fingerprint(value)
    except (
        OSError,
        PydanticSerializationError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
        yaml.YAMLError,
    ):
        return None
    if source_fingerprint != received_fingerprint:
        return None
    return sha256(raw).hexdigest()


def evaluate_authorization(
    *,
    scope: PilotValidationScope | Path,
    base_policy: PilotValidationPolicy | Path,
    activation_policy: PilotValidationPolicy | Path,
    authorization: ValidationAuthorization | Path | None,
    approval_evidence: GitHubApprovalEvidence | Path | None,
    publication_package: PublicationPackage | Path | None,
    request: ValidationRequest,
    now: object,
    service_root: Path | None = None,
) -> AuthorizationDecision:
    """Refuse par défaut toute transition qui n'est pas prouvée intégralement."""

    reasons: list[str] = []
    root = (service_root or Path(__file__).resolve().parents[2]).resolve()
    public_contract = _load_public_contract(root)
    loaded_scope = _safe_scope(scope)
    loaded_base = _safe_policy(base_policy)
    loaded_activation = _safe_policy(activation_policy)
    loaded_request = _safe_request(request)
    loaded_approval = _safe_document(
        approval_evidence,
        model=GitHubApprovalEvidence,
    )
    loaded_package = _safe_document(
        publication_package,
        model=PublicationPackage,
    )

    evaluated_now: datetime | None = None
    if isinstance(now, datetime):
        try:
            if now.tzinfo is not None and now.utcoffset() is not None:
                evaluated_now = now
        except (OverflowError, ValueError):
            evaluated_now = None

    if not isinstance(loaded_scope, PilotValidationScope):
        reasons.append("scope.invalid")
    else:
        reasons.extend(
            f"scope.invalid:{reason}"
            for reason in validate_scope_integrity(loaded_scope, service_root=root)
        )
    if not isinstance(loaded_base, PilotValidationPolicy):
        reasons.append("base_policy.invalid")
    else:
        reasons.extend(
            f"base_policy.invalid:{reason}"
            for reason in validate_policy_integrity(loaded_base, public_contract)
        )
        reasons.extend(
            f"base_policy.not_dormant:{reason}"
            for reason in validate_dormant_policy(loaded_base)
        )
    if not isinstance(loaded_activation, PilotValidationPolicy):
        reasons.append("activation_policy.invalid")
    else:
        reasons.extend(
            f"activation_policy.invalid:{reason}"
            for reason in validate_policy_integrity(loaded_activation, public_contract)
        )

    loaded_authorization = _safe_authorization(authorization)
    auth = (
        loaded_authorization
        if isinstance(loaded_authorization, ValidationAuthorization)
        else None
    )

    if auth is not None and loaded_scope is not None:
        if auth.scope_digest != _raw_digest(loaded_scope):
            reasons.append("scope.digest_mismatch")
    if auth is not None and loaded_base is not None:
        if auth.base_policy_digest != _raw_digest(loaded_base):
            reasons.append("base_policy.digest_mismatch")
    if auth is not None and loaded_activation is not None:
        if auth.activation_policy_digest != _raw_digest(loaded_activation):
            reasons.append("activation_policy.digest_mismatch")
        if auth.base_policy_digest == auth.activation_policy_digest:
            reasons.append("policy.digests_not_distinct")

    operation = None
    if loaded_activation is not None and loaded_request is not None and hasattr(
        loaded_activation.authorization_matrix, loaded_request.operation
    ):
        candidate_operation = getattr(
            loaded_activation.authorization_matrix, loaded_request.operation
        )
        if isinstance(candidate_operation, AuthorizationOperation):
            operation = candidate_operation
            for capability in candidate_operation.capabilities:
                if getattr(loaded_activation.capabilities, capability, False) is not True:
                    reasons.append(f"capability.closed:{capability}")

    if authorization is None:
        reasons.append("authorization.missing")
    elif auth is None:
        reasons.append("authorization.invalid")
    else:
        if auth.decision != "AUTHORIZE_VALIDATION_PIPELINE":
            reasons.append("authorization.decision_invalid")
        if auth.status != "approved":
            reasons.append("authorization.status_invalid")
        if auth.scope_ref != _EXPECTED_SCOPE_ID:
            reasons.append("authorization.scope_ref_mismatch")
        if auth.lot41_sha == "0" * 40:
            reasons.append("authorization.lot41_sha_invalid")
        if auth.issued_at >= auth.expires_at:
            reasons.append("authorization.expiration_incoherent")
        if not isinstance(now, datetime):
            reasons.append("authorization.now_invalid")
        elif evaluated_now is None:
            reasons.append("authorization.now_naive")
        elif evaluated_now >= auth.expires_at:
            reasons.append("authorization.expired")

    approval = (
        loaded_approval
        if isinstance(loaded_approval, GitHubApprovalEvidence)
        else None
    )
    if approval_evidence is None:
        reasons.append("approval.missing")
    elif approval is None:
        reasons.append("approval.invalid")
    else:
        if approval.evidence_kind != "github_pr_approval":
            reasons.append("approval.kind_mismatch")
        if approval.repository != "cyranoaladin/RAG":
            reasons.append("approval.repository_mismatch")
        if auth is not None and approval.pull_request != auth.pull_request:
            reasons.append("approval.pull_request_mismatch")
        if approval.base_branch != "main":
            reasons.append("approval.base_branch_mismatch")
        if approval.reviewer_role != "lead" or approval.reviewer_human is not True:
            reasons.append("approval.reviewer_not_human_lead")
        if approval.head_sha == "0" * 40:
            reasons.append("approval.head_sha_null")
        if approval.approved_head_sha == "0" * 40:
            reasons.append("approval.approved_head_sha_null")
        if approval.approved_head_sha != approval.head_sha:
            reasons.append("approval.approved_head_mismatch")
        if auth is not None:
            if approval.referenced_lot41_sha != auth.lot41_sha:
                reasons.append("approval.referenced_lot41_mismatch")
            if approval.head_sha == auth.lot41_sha:
                reasons.append("approval.head_not_distinct_from_lot41")
            if approval.authorization_digest != _raw_digest(auth):
                reasons.append("approval.authorization_digest_mismatch")
        if approval.revoked is not False:
            reasons.append("approval.revoked")
        forbidden_merge_shas = {
            "0" * 40,
            approval.head_sha,
            approval.approved_head_sha,
            approval.referenced_lot41_sha,
        }
        if auth is not None:
            forbidden_merge_shas.add(auth.lot41_sha)
        if approval.merge_sha in forbidden_merge_shas:
            reasons.append("approval.merge_sha_not_distinct")
        if not (
            approval.approved_at <= approval.merged_at < approval.readback_at
        ):
            reasons.append("approval.timeline_incoherent")
        if evaluated_now is not None and approval.readback_at > evaluated_now.astimezone(UTC):
            reasons.append("approval.readback_in_future")
        if auth is not None and not (
            auth.issued_at <= approval.approved_at < auth.expires_at
        ):
            reasons.append("approval.outside_authorization_window")

    if auth is not None and loaded_activation is not None:
        expected_environment = loaded_activation.validation_environment.environment_id
        if auth.environment_id != expected_environment:
            reasons.append("environment.authorization_mismatch")
        if (
            loaded_request is not None
            and loaded_request.environment_id != expected_environment
        ):
            reasons.append("environment.request_mismatch")

    if auth is not None and loaded_scope is not None:
        if tuple(sorted(auth.collections)) != tuple(sorted(loaded_scope.collections)):
            reasons.append("collections.authorization_mismatch")
        if (
            loaded_request is not None
            and loaded_request.collection not in loaded_scope.collections
        ):
            reasons.append("collections.request_out_of_scope")

        expected_identity = loaded_scope.identity
        for field in ("tenant", "level", "track", "teaching_status", "audience"):
            if getattr(auth.identity, field) != getattr(expected_identity, field):
                reasons.append(f"identity.authorization_mismatch:{field}")
        if auth.identity.candidates != expected_identity.candidates:
            reasons.append("identity.authorization_mismatch:candidates")
        if auth.identity.school_year != loaded_scope.school_year:
            reasons.append("identity.authorization_mismatch:school_year")
        expected_subjects = tuple(sorted(subject.subject for subject in loaded_scope.subjects))
        if tuple(sorted(auth.identity.subjects)) != expected_subjects:
            reasons.append("identity.authorization_mismatch:subjects")

        if loaded_request is not None:
            for field in ("tenant", "level", "track", "teaching_status", "audience"):
                if getattr(loaded_request, field) != getattr(expected_identity, field):
                    reasons.append(f"identity.request_mismatch:{field}")
            if loaded_request.candidate not in expected_identity.candidates:
                reasons.append("identity.request_mismatch:candidate")
            if loaded_request.school_year != loaded_scope.school_year:
                reasons.append("identity.request_mismatch:school_year")
            if loaded_request.subject not in expected_subjects:
                reasons.append("identity.request_mismatch:subject")
            else:
                subject_collection = next(
                    subject.collection
                    for subject in loaded_scope.subjects
                    if subject.subject == loaded_request.subject
                )
                if loaded_request.collection != subject_collection:
                    reasons.append("identity.request_collection_mismatch")

    if auth is not None:
        if auth.rights_verified is not True:
            reasons.append("rights.not_verified")
        if auth.provenance_verified is not True:
            reasons.append("provenance.not_verified")
        if auth.pii_absence_verified is not True:
            reasons.append("pii.not_verified")

        if not _safe_ref(auth.rollback.plan_ref):
            reasons.append("rollback.path_invalid")
        if auth.rollback.tested is not True:
            reasons.append("rollback.not_tested")
        if auth.rollback.tested_at > auth.issued_at:
            reasons.append("rollback.timeline_incoherent")

    if loaded_request is None:
        reasons.append("request.invalid")
    elif operation is None:
        reasons.append("operation.unknown")
    elif loaded_request.caller in _PUBLIC_CALLERS:
        reasons.append(f"caller.public_forbidden:{loaded_request.caller}")
    elif loaded_request.caller not in operation.allowed_callers:
        reasons.append("caller.not_allowed")

    if loaded_request is not None and loaded_request.operation == "publish_reviewed_chunks":
        package = (
            loaded_package
            if isinstance(loaded_package, PublicationPackage)
            else None
        )
        if publication_package is None:
            reasons.append("package.missing")
        elif package is None:
            reasons.append("package.invalid")
        else:
            if not _safe_ref(package.content_ref):
                reasons.append("package.path_invalid")
            if sha256(package.content.encode("utf-8")).hexdigest() != package.content_sha256:
                reasons.append("package.digest_mismatch")
            if package.quality != "passed":
                reasons.append("package.quality_not_passed")
            if package.gate != "passed":
                reasons.append("package.gate_not_passed")
            if package.review != "reviewed":
                reasons.append("package.review_not_reviewed")
            if package.quarantine is not False:
                reasons.append("package.quarantined")
            if package.revoked is not False:
                reasons.append("package.revoked")
            if package.publisher != "rag-engine":
                reasons.append("package.publisher_mismatch")

    return AuthorizationDecision(allowed=not reasons, reasons=tuple(reasons))
