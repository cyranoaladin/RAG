"""Préparation pure et fail-closed d'une capture legacy déjà exportée."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from .engine_convergence_policy import (
    EngineConvergencePolicy,
    LegacyCollectionPolicy,
    LegacyDisposition,
)

_CAPTURE_PROTOCOL = "NEXUS-LEGACY-CAPTURE-V1"
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SECRET_ID_HINT = re.compile(r"(?:api[_-]?key|bearer|password|secret|token)", re.IGNORECASE)
_FORBIDDEN_CONTENT_KEYS = frozenset({"text", "document", "embedding", "embeddings"})
_CAPTURE_CONTEXTS = frozenset({"OPERATOR_READ_ONLY_CAPTURE", "SYNTHETIC_TEST"})
_MAX_CAPTURE_VALIDITY = timedelta(hours=24)
_MAX_JSON_DEPTH = 32


class LegacyCaptureError(ValueError):
    """La capture ne satisfait pas le protocole legacy fermé."""


class LegacyReasonCode(StrEnum):
    """Motifs fermés expliquant une disposition sans l'autoriser."""

    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    EMPTY_COLLECTION_VERIFIED = "EMPTY_COLLECTION_VERIFIED"
    NON_PUBLISHABLE = "NON_PUBLISHABLE"
    POLICY_QUARANTINE = "POLICY_QUARANTINE"
    SCOPE_INCOMPLETE = "SCOPE_INCOMPLETE"
    RIGHTS_UNVERIFIED = "RIGHTS_UNVERIFIED"
    PROVENANCE_INCOMPLETE = "PROVENANCE_INCOMPLETE"
    COLLECTION_AMBIGUOUS = "COLLECTION_AMBIGUOUS"
    EXACT_SOURCE_AND_SCOPE = "EXACT_SOURCE_AND_SCOPE"


@dataclass(frozen=True)
class ProducerIdentity:
    """Identité du producteur read-only de la capture."""

    name: str
    version: str
    git_commit: str
    captured_at: str
    valid_until: str
    capture_context: str


@dataclass(frozen=True)
class ChromaCollectionInventory:
    """Compte et scellement déclarés d'une collection Chroma."""

    name: str
    object_count: int
    digest_sha256: str


@dataclass(frozen=True)
class ChromaInventory:
    """Identité et inventaire du stockage Chroma legacy."""

    service_id: str
    volume_id: str
    embedding_dimension: int
    collections: tuple[ChromaCollectionInventory, ...]


@dataclass(frozen=True)
class SQLiteSnapshot:
    """Preuve cohérente d'une sauvegarde SQLite indépendante."""

    identity: str
    schema_version: str
    wal_state: str
    backup_method: str
    integrity_check: str
    digest_sha256: str


@dataclass(frozen=True)
class PgvectorInventory:
    """Identité et scellement déclarés du stockage canonique."""

    service_id: str
    database_id: str
    migration_head: str
    object_count: int
    digest_sha256: str


@dataclass(frozen=True)
class UploadInventory:
    """Inventaire des fichiers nécessaires à la reconstruction."""

    logical_root: str
    file_count: int
    digest_sha256: str


@dataclass(frozen=True)
class ImageArtifact:
    """Image identifiée par digest immuable."""

    name: str
    digest: str


@dataclass(frozen=True)
class ModelArtifact:
    """Modèle local épinglé et dimensionné."""

    name: str
    digest_sha256: str
    dimension: int


@dataclass(frozen=True)
class ReconstructibleAssets:
    """Actifs hors bases requis pour reconstruire le moteur A."""

    uploads: UploadInventory
    config_file_count: int
    configs_digest_sha256: str
    images: tuple[ImageArtifact, ...]
    models: tuple[ModelArtifact, ...]


@dataclass(frozen=True)
class PreparedLegacyItem:
    """Décision de préparation dépourvue de toute autorisation de publication."""

    migration_id: str
    legacy_collection: str
    content_sha256: str
    content_length: int
    source_id: str
    canonical_span_id: str
    source_snapshot_sha256: str
    provenance_evidence_sha256: str
    rights_evidence_sha256: str
    disposition: LegacyDisposition
    reason_code: LegacyReasonCode
    target_collection: str | None
    duplicate_of: str | None


@dataclass(frozen=True)
class EmptyLegacyCollection:
    """Collection dont l'absence d'objet a été réconciliée."""

    legacy_collection: str
    disposition: LegacyDisposition
    reason_code: LegacyReasonCode


@dataclass(frozen=True)
class LegacyMigrationManifest:
    """Manifeste local produit sans accès à un moteur ou une base."""

    producer: ProducerIdentity
    chroma: ChromaInventory
    catalog_sqlite: SQLiteSnapshot
    drive_sync_sqlite: SQLiteSnapshot
    pgvector: PgvectorInventory
    assets: ReconstructibleAssets
    items: tuple[PreparedLegacyItem, ...]
    empty_collections: tuple[EmptyLegacyCollection, ...]
    source_object_count: int
    prepared_object_count: int
    duplicate_count: int
    disposition_counts: tuple[tuple[str, int], ...]
    input_digest_sha256: str
    manifest_sha256: str
    migration_complete: bool


@dataclass(frozen=True)
class _CapturedScope:
    matiere: str | None
    niveau: str | None
    voie: str | None
    statut_enseignement: str | None


@dataclass(frozen=True)
class _CapturedObject:
    migration_id: str
    legacy_collection: str
    content_sha256: str
    content_length: int
    source_id: str
    canonical_span_id: str
    source_snapshot_sha256: str
    provenance_evidence_sha256: str
    rights_evidence_sha256: str
    recoverable: bool
    provenance_complete: bool
    rights_verified: bool
    publishable: bool
    scope: _CapturedScope


def _mapping(
    value: Any,
    *,
    field: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LegacyCaptureError(f"{field} is invalid")
    keys = frozenset(value)
    if not required <= keys or keys - required - optional:
        raise LegacyCaptureError(f"{field} schema is invalid")
    return value


def _reject_forbidden_content(value: Any) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > _MAX_JSON_DEPTH:
            raise LegacyCaptureError("capture nesting is too deep")
        if isinstance(current, dict):
            if _FORBIDDEN_CONTENT_KEYS & set(current):
                raise LegacyCaptureError("capture contains a forbidden content field")
            pending.extend((nested, depth + 1) for nested in current.values())
        elif isinstance(current, list):
            pending.extend((nested, depth + 1) for nested in current)


def _nonempty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LegacyCaptureError(f"{field} is invalid")
    return value


def _opaque_id(value: Any, *, field: str) -> str:
    candidate = _nonempty_string(value, field=field)
    if _OPAQUE_ID.fullmatch(candidate) is None:
        raise LegacyCaptureError(f"{field} is invalid")
    return candidate


def _metadata_id(value: Any, *, field: str) -> str:
    candidate = _opaque_id(value, field=field)
    if _SECRET_ID_HINT.search(candidate) is not None:
        raise LegacyCaptureError(f"{field} is invalid")
    return candidate


def _source_id(value: Any) -> str:
    return _metadata_id(value, field="legacy source id")


def _nonnegative_int(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LegacyCaptureError(f"{field} is invalid")
    return value


def _boolean(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise LegacyCaptureError(f"{field} is invalid")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise LegacyCaptureError(f"{field} is invalid")
    return value


def _utc_instant(value: Any, *, field: str) -> tuple[str, datetime]:
    raw = _nonempty_string(value, field=field)
    try:
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise LegacyCaptureError(f"{field} is invalid") from None
    if not raw.endswith("Z") or instant.tzinfo != UTC:
        raise LegacyCaptureError(f"{field} is invalid")
    return raw, instant


def _producer(header: dict[str, Any], *, now: datetime) -> ProducerIdentity:
    producer = _mapping(
        header.get("producer"),
        field="producer",
        required=frozenset(
            {"name", "version", "git_commit", "captured_at", "valid_until"}
        ),
    )
    name = _metadata_id(producer.get("name"), field="producer name")
    version = _metadata_id(producer.get("version"), field="producer version")
    git_commit = _nonempty_string(producer.get("git_commit"), field="producer commit")
    if _GIT_COMMIT.fullmatch(git_commit) is None:
        raise LegacyCaptureError("producer commit is invalid")
    captured_at, captured = _utc_instant(
        producer.get("captured_at"), field="capture instant"
    )
    valid_until, expiry = _utc_instant(
        producer.get("valid_until"), field="capture expiry"
    )
    context = _nonempty_string(
        header.get("capture_context"), field="capture context"
    )
    if context not in _CAPTURE_CONTEXTS:
        raise LegacyCaptureError("capture context is invalid")
    if now.tzinfo != UTC:
        raise LegacyCaptureError("reference instant is invalid")
    if expiry <= captured or expiry - captured > _MAX_CAPTURE_VALIDITY:
        raise LegacyCaptureError("capture validity window is invalid")
    if context == "OPERATOR_READ_ONLY_CAPTURE" and not captured <= now <= expiry:
        raise LegacyCaptureError("capture is not fresh")
    proof = _mapping(
        header.get("read_only_proof"),
        field="read-only proof",
        required=frozenset({"mode", "writes_disabled", "evidence_sha256"}),
    )
    if proof.get("mode") != "snapshot_export":
        raise LegacyCaptureError("read-only mode is invalid")
    if proof.get("writes_disabled") is not True:
        raise LegacyCaptureError("read-only proof is invalid")
    _sha256(proof.get("evidence_sha256"), field="read-only evidence")
    return ProducerIdentity(
        name=name,
        version=version,
        git_commit=git_commit,
        captured_at=captured_at,
        valid_until=valid_until,
        capture_context=context,
    )


def _chroma(header: dict[str, Any]) -> ChromaInventory:
    document = _mapping(
        header.get("chroma"),
        field="chroma inventory",
        required=frozenset(
            {"service_id", "volume_id", "embedding_dimension", "collections"}
        ),
    )
    service_id = _metadata_id(document.get("service_id"), field="chroma service")
    volume_id = _metadata_id(document.get("volume_id"), field="chroma volume")
    embedding_dimension = _nonnegative_int(
        document.get("embedding_dimension"), field="chroma dimension"
    )
    if embedding_dimension == 0:
        raise LegacyCaptureError("chroma dimension is invalid")
    raw_collections = document.get("collections")
    if not isinstance(raw_collections, list) or not raw_collections:
        raise LegacyCaptureError("chroma collections are invalid")
    collections: list[ChromaCollectionInventory] = []
    names: set[str] = set()
    for raw_collection in raw_collections:
        collection = _mapping(
            raw_collection,
            field="chroma collection",
            required=frozenset({"name", "object_count", "digest_sha256"}),
        )
        name = _nonempty_string(collection.get("name"), field="chroma collection name")
        if name in names:
            raise LegacyCaptureError("chroma collection name is invalid")
        names.add(name)
        collections.append(
            ChromaCollectionInventory(
                name=name,
                object_count=_nonnegative_int(
                    collection.get("object_count"), field="chroma collection count"
                ),
                digest_sha256=_sha256(
                    collection.get("digest_sha256"), field="chroma collection digest"
                ),
            )
        )
    return ChromaInventory(
        service_id=service_id,
        volume_id=volume_id,
        embedding_dimension=embedding_dimension,
        collections=tuple(collections),
    )


def _sqlite_snapshot(value: Any, *, expected_identity: str) -> SQLiteSnapshot:
    document = _mapping(
        value,
        field="sqlite snapshot",
        required=frozenset(
            {
                "identity",
                "schema_version",
                "wal_state",
                "backup_method",
                "integrity_check",
                "digest_sha256",
            }
        ),
    )
    identity = _nonempty_string(document.get("identity"), field="sqlite identity")
    if identity != expected_identity:
        raise LegacyCaptureError("sqlite identity is invalid")
    schema_version = _metadata_id(
        document.get("schema_version"), field="sqlite schema"
    )
    wal_state = _nonempty_string(document.get("wal_state"), field="sqlite WAL state")
    if wal_state not in {"checkpointed", "preserved"}:
        raise LegacyCaptureError("sqlite WAL state is invalid")
    backup_method = _nonempty_string(
        document.get("backup_method"), field="sqlite backup method"
    )
    if backup_method not in {"sqlite_backup_api", "quiesced_checkpoint"}:
        raise LegacyCaptureError("sqlite backup method is invalid")
    if document.get("integrity_check") != "ok":
        raise LegacyCaptureError("sqlite integrity check is invalid")
    return SQLiteSnapshot(
        identity=identity,
        schema_version=schema_version,
        wal_state=wal_state,
        backup_method=backup_method,
        integrity_check="ok",
        digest_sha256=_sha256(document.get("digest_sha256"), field="sqlite digest"),
    )


def _sqlite(header: dict[str, Any]) -> tuple[SQLiteSnapshot, SQLiteSnapshot]:
    document = _mapping(
        header.get("sqlite"),
        field="sqlite inventories",
        required=frozenset({"catalog", "drive_sync"}),
    )
    catalog = _sqlite_snapshot(
        document.get("catalog"), expected_identity="catalog.sqlite"
    )
    drive_sync = _sqlite_snapshot(
        document.get("drive_sync"), expected_identity="drive_sync_state.db"
    )
    return catalog, drive_sync


def _pgvector(header: dict[str, Any]) -> PgvectorInventory:
    document = _mapping(
        header.get("pgvector"),
        field="pgvector inventory",
        required=frozenset(
            {
                "service_id",
                "database_id",
                "migration_head",
                "object_count",
                "digest_sha256",
            }
        ),
    )
    return PgvectorInventory(
        service_id=_metadata_id(
            document.get("service_id"), field="pgvector service"
        ),
        database_id=_metadata_id(
            document.get("database_id"), field="pgvector database"
        ),
        migration_head=_metadata_id(
            document.get("migration_head"), field="pgvector migration head"
        ),
        object_count=_nonnegative_int(
            document.get("object_count"), field="pgvector count"
        ),
        digest_sha256=_sha256(
            document.get("digest_sha256"), field="pgvector digest"
        ),
    )


def _assets(header: dict[str, Any]) -> ReconstructibleAssets:
    uploads_document = _mapping(
        header.get("uploads"),
        field="uploads inventory",
        required=frozenset({"logical_root", "file_count", "digest_sha256"}),
    )
    uploads = UploadInventory(
        logical_root=_metadata_id(
            uploads_document.get("logical_root"), field="uploads root"
        ),
        file_count=_nonnegative_int(
            uploads_document.get("file_count"), field="uploads count"
        ),
        digest_sha256=_sha256(
            uploads_document.get("digest_sha256"), field="uploads digest"
        ),
    )
    configs = _mapping(
        header.get("configs"),
        field="configs inventory",
        required=frozenset({"file_count", "digest_sha256"}),
    )
    config_file_count = _nonnegative_int(
        configs.get("file_count"), field="configs count"
    )
    configs_digest = _sha256(configs.get("digest_sha256"), field="configs digest")

    raw_images = header.get("images")
    if not isinstance(raw_images, list) or not raw_images:
        raise LegacyCaptureError("image inventory is invalid")
    images: list[ImageArtifact] = []
    image_names: set[str] = set()
    for raw_image in raw_images:
        image = _mapping(
            raw_image,
            field="image artifact",
            required=frozenset({"name", "digest"}),
        )
        name = _metadata_id(image.get("name"), field="image name")
        digest = _nonempty_string(image.get("digest"), field="image digest")
        if name in image_names or not digest.startswith("sha256:"):
            raise LegacyCaptureError("image artifact is invalid")
        _sha256(digest.removeprefix("sha256:"), field="image digest")
        image_names.add(name)
        images.append(ImageArtifact(name=name, digest=digest))

    raw_models = header.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise LegacyCaptureError("model inventory is invalid")
    models: list[ModelArtifact] = []
    model_names: set[str] = set()
    for raw_model in raw_models:
        model = _mapping(
            raw_model,
            field="model artifact",
            required=frozenset({"name", "digest_sha256", "dimension"}),
        )
        name = _metadata_id(model.get("name"), field="model name")
        dimension = _nonnegative_int(model.get("dimension"), field="model dimension")
        if name in model_names or dimension == 0:
            raise LegacyCaptureError("model artifact is invalid")
        model_names.add(name)
        models.append(
            ModelArtifact(
                name=name,
                digest_sha256=_sha256(
                    model.get("digest_sha256"), field="model digest"
                ),
                dimension=dimension,
            )
        )
    return ReconstructibleAssets(
        uploads=uploads,
        config_file_count=config_file_count,
        configs_digest_sha256=configs_digest,
        images=tuple(images),
        models=tuple(models),
    )


def _scope(value: Any) -> _CapturedScope:
    if value is None:
        document: dict[str, Any] = {}
    else:
        document = _mapping(
            value,
            field="legacy scope",
            required=frozenset(),
            optional=frozenset(
                {"matiere", "niveau", "voie", "statut_enseignement"}
            ),
        )

    def optional_string(field: str) -> str | None:
        raw = document.get(field)
        return raw if isinstance(raw, str) and raw.strip() else None

    return _CapturedScope(
        matiere=optional_string("matiere"),
        niveau=optional_string("niveau"),
        voie=optional_string("voie"),
        statut_enseignement=optional_string("statut_enseignement"),
    )


def _captured_objects(
    records: tuple[dict[str, Any], ...],
    *,
    policy: EngineConvergencePolicy,
) -> tuple[_CapturedObject, ...]:
    objects: list[_CapturedObject] = []
    migration_ids: set[str] = set()
    for record in records:
        _mapping(
            record,
            field="capture object",
            required=frozenset(
                {
                    "record_type",
                    "migration_id",
                    "legacy_collection",
                    "content_sha256",
                    "content_length",
                    "canonical_span_id",
                    "source",
                }
            ),
            optional=frozenset({"scope"}),
        )
        if record.get("record_type") != "legacy_object":
            raise LegacyCaptureError("capture object is invalid")
        migration_id = _metadata_id(
            record.get("migration_id"), field="migration id"
        )
        if migration_id in migration_ids:
            raise LegacyCaptureError("migration id is duplicated")
        migration_ids.add(migration_id)
        collection_name = _nonempty_string(
            record.get("legacy_collection"), field="legacy collection"
        )
        if collection_name not in policy.discovered_legacy_collections:
            raise LegacyCaptureError("legacy collection is unknown")
        content_length = _nonnegative_int(
            record.get("content_length"), field="capture object length"
        )
        if content_length == 0:
            raise LegacyCaptureError("capture object length is invalid")
        source = _mapping(
            record.get("source"),
            field="legacy source",
            required=frozenset(
                {
                    "source_id",
                    "source_snapshot_sha256",
                    "provenance_evidence_sha256",
                    "rights_evidence_sha256",
                    "recoverable",
                    "provenance_complete",
                    "rights_verified",
                    "publishable",
                }
            ),
        )
        objects.append(
            _CapturedObject(
                migration_id=migration_id,
                legacy_collection=collection_name,
                content_sha256=_sha256(
                    record.get("content_sha256"), field="capture object digest"
                ),
                content_length=content_length,
                source_id=_source_id(source.get("source_id")),
                canonical_span_id=_metadata_id(
                    record.get("canonical_span_id"), field="canonical span id"
                ),
                source_snapshot_sha256=_sha256(
                    source.get("source_snapshot_sha256"),
                    field="source snapshot digest",
                ),
                provenance_evidence_sha256=_sha256(
                    source.get("provenance_evidence_sha256"),
                    field="provenance evidence digest",
                ),
                rights_evidence_sha256=_sha256(
                    source.get("rights_evidence_sha256"),
                    field="rights evidence digest",
                ),
                recoverable=_boolean(
                    source.get("recoverable"), field="source recoverability"
                ),
                provenance_complete=_boolean(
                    source.get("provenance_complete"), field="source provenance"
                ),
                rights_verified=_boolean(
                    source.get("rights_verified"), field="source rights"
                ),
                publishable=_boolean(
                    source.get("publishable"), field="source publication"
                ),
                scope=_scope(record.get("scope")),
            )
        )
    return tuple(objects)


def _prepared_item(
    item: _CapturedObject,
    *,
    collection_policy: LegacyCollectionPolicy,
    duplicate_of: str | None,
) -> PreparedLegacyItem:
    disposition: LegacyDisposition
    reason: LegacyReasonCode
    target: str | None = None
    if not item.recoverable:
        disposition = LegacyDisposition.BLOCKED
        reason = LegacyReasonCode.SOURCE_UNAVAILABLE
    elif not item.publishable:
        disposition = LegacyDisposition.QUARANTINE
        reason = LegacyReasonCode.NON_PUBLISHABLE
    elif collection_policy.default_disposition is LegacyDisposition.QUARANTINE:
        disposition = LegacyDisposition.QUARANTINE
        reason = LegacyReasonCode.POLICY_QUARANTINE
    elif (
        item.scope.matiere != "nsi"
        or item.scope.niveau not in {"premiere", "terminale"}
        or item.scope.voie != "gen"
        or item.scope.statut_enseignement != "specialite"
    ):
        disposition = LegacyDisposition.REVIEW_REQUIRED
        reason = LegacyReasonCode.SCOPE_INCOMPLETE
    elif not item.rights_verified:
        disposition = LegacyDisposition.REVIEW_REQUIRED
        reason = LegacyReasonCode.RIGHTS_UNVERIFIED
    elif not item.provenance_complete:
        disposition = LegacyDisposition.REVIEW_REQUIRED
        reason = LegacyReasonCode.PROVENANCE_INCOMPLETE
    else:
        matching_targets = tuple(
            candidate
            for candidate in collection_policy.allowed_targets
            if f"_{item.scope.niveau}_" in candidate
        )
        if len(matching_targets) != 1:
            disposition = LegacyDisposition.REVIEW_REQUIRED
            reason = LegacyReasonCode.COLLECTION_AMBIGUOUS
        else:
            disposition = LegacyDisposition.REINGEST_GOVERNED
            reason = LegacyReasonCode.EXACT_SOURCE_AND_SCOPE
            target = matching_targets[0]
    return PreparedLegacyItem(
        migration_id=item.migration_id,
        legacy_collection=item.legacy_collection,
        content_sha256=item.content_sha256,
        content_length=item.content_length,
        source_id=item.source_id,
        canonical_span_id=item.canonical_span_id,
        source_snapshot_sha256=item.source_snapshot_sha256,
        provenance_evidence_sha256=item.provenance_evidence_sha256,
        rights_evidence_sha256=item.rights_evidence_sha256,
        disposition=disposition,
        reason_code=reason,
        target_collection=target,
        duplicate_of=duplicate_of,
    )


def _positive_limit(value: int, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LegacyCaptureError(f"{field} is invalid")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise LegacyCaptureError("capture contains a duplicate key")
        document[key] = value
    return document


def _decode_record(raw_line: bytes, *, line_number: int) -> dict[str, Any]:
    invalid = False
    decoded = ""
    try:
        decoded = raw_line.decode("utf-8")
        record = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
    except LegacyCaptureError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        invalid = True
        record = None
    finally:
        decoded = ""
    if invalid:
        raise LegacyCaptureError(f"capture line {line_number} is invalid")
    _reject_forbidden_content(record)
    return _mapping(
        record,
        field=f"capture line {line_number}",
        required=frozenset(),
        optional=frozenset(record) if isinstance(record, dict) else frozenset(),
    )


def _read_records(
    path: Path,
    *,
    max_line_bytes: int,
    max_total_bytes: int,
    max_records: int,
) -> tuple[tuple[dict[str, Any], ...], str]:
    _positive_limit(max_line_bytes, field="line limit")
    _positive_limit(max_total_bytes, field="capture size limit")
    _positive_limit(max_records, field="record limit")
    records: list[dict[str, Any]] = []
    input_hasher = sha256()
    total_bytes = 0
    descriptor = -1
    try:
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise LegacyCaptureError("capture is unavailable")
        if metadata.st_size > max_total_bytes:
            raise LegacyCaptureError("capture is too large")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            line_number = 0
            while raw_line := stream.readline(max_line_bytes + 1):
                line_number += 1
                if len(raw_line) > max_line_bytes:
                    raise LegacyCaptureError("capture line is too large")
                total_bytes += len(raw_line)
                if total_bytes > max_total_bytes:
                    raise LegacyCaptureError("capture is too large")
                if line_number > max_records:
                    raise LegacyCaptureError("capture contains too many records")
                input_hasher.update(raw_line)
                records.append(_decode_record(raw_line, line_number=line_number))
    except LegacyCaptureError:
        raise
    except OSError:
        raise LegacyCaptureError("capture is unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not records:
        raise LegacyCaptureError("capture header is unavailable")
    return tuple(records), input_hasher.hexdigest()


def _prepare_legacy_capture(
    path: Path,
    *,
    policy: EngineConvergencePolicy,
    max_line_bytes: int = 65_536,
    max_total_bytes: int = 64 * 1024 * 1024,
    max_records: int = 1_000_000,
    now: datetime | None = None,
) -> LegacyMigrationManifest:
    """Valider une capture locale sans effectuer aucune mutation externe."""

    records, input_digest_sha256 = _read_records(
        path,
        max_line_bytes=max_line_bytes,
        max_total_bytes=max_total_bytes,
        max_records=max_records,
    )
    header = records[0]
    _mapping(
        header,
        field="capture header",
        required=frozenset(
            {
                "record_type",
                "protocol_version",
                "capture_context",
                "producer",
                "read_only_proof",
                "chroma",
                "sqlite",
                "pgvector",
                "uploads",
                "configs",
                "images",
                "models",
                "discovered_collections",
                "source_object_count",
            }
        ),
    )
    if header.get("record_type") != "capture_header":
        raise LegacyCaptureError("capture header is invalid")
    if header.get("protocol_version") != _CAPTURE_PROTOCOL:
        raise LegacyCaptureError("capture protocol is invalid")
    source_object_count = _nonnegative_int(
        header.get("source_object_count"), field="source object count"
    )
    if source_object_count != len(records) - 1:
        raise LegacyCaptureError("source object count is inconsistent")
    discovered = header.get("discovered_collections")
    if (
        not isinstance(discovered, list)
        or not all(isinstance(name, str) for name in discovered)
        or tuple(discovered) != policy.discovered_legacy_collections
    ):
        raise LegacyCaptureError("legacy collection discovery is inconsistent")
    objects = _captured_objects(records[1:], policy=policy)
    object_counts = {name: 0 for name in policy.discovered_legacy_collections}
    for item in objects:
        object_counts[item.legacy_collection] += 1
    chroma = _chroma(header)
    if tuple(item.name for item in chroma.collections) != tuple(discovered) or any(
        item.object_count != object_counts[item.name] for item in chroma.collections
    ):
        raise LegacyCaptureError("chroma collection inventory is inconsistent")
    catalog_sqlite, drive_sync_sqlite = _sqlite(header)
    policies = {item.name: item for item in policy.legacy_collections}
    canonical_ids: dict[tuple[str | int | bool, ...], str] = {}

    def deduplication_identity(
        item: _CapturedObject,
    ) -> tuple[str | int | bool, ...]:
        collection_policy = policies[item.legacy_collection]
        return (
            item.content_sha256,
            item.content_length,
            item.source_id,
            item.canonical_span_id,
            item.source_snapshot_sha256,
            item.provenance_evidence_sha256,
            item.rights_evidence_sha256,
            item.recoverable,
            item.provenance_complete,
            item.rights_verified,
            item.publishable,
            item.scope.matiere or "",
            item.scope.niveau or "",
            item.scope.voie or "",
            item.scope.statut_enseignement or "",
            collection_policy.default_disposition.value,
            "\x1f".join(collection_policy.allowed_targets),
        )

    for item in sorted(objects, key=lambda candidate: candidate.migration_id):
        identity = deduplication_identity(item)
        canonical_ids.setdefault(identity, item.migration_id)

    def duplicate_of(item: _CapturedObject) -> str | None:
        identity = deduplication_identity(item)
        canonical = canonical_ids[identity]
        return None if canonical == item.migration_id else canonical

    prepared_items = tuple(
        _prepared_item(
            item,
            collection_policy=policies[item.legacy_collection],
            duplicate_of=duplicate_of(item),
        )
        for item in sorted(objects, key=lambda candidate: candidate.migration_id)
    )
    disposition_counts = tuple(
        (
            disposition.value,
            sum(item.disposition is disposition for item in prepared_items),
        )
        for disposition in LegacyDisposition
    )

    manifest = LegacyMigrationManifest(
        producer=_producer(header, now=now or datetime.now(UTC)),
        chroma=chroma,
        catalog_sqlite=catalog_sqlite,
        drive_sync_sqlite=drive_sync_sqlite,
        pgvector=_pgvector(header),
        assets=_assets(header),
        items=prepared_items,
        empty_collections=tuple(
            EmptyLegacyCollection(
                legacy_collection=item.name,
                disposition=LegacyDisposition.IGNORE_EMPTY,
                reason_code=LegacyReasonCode.EMPTY_COLLECTION_VERIFIED,
            )
            for item in chroma.collections
            if item.object_count == 0
        ),
        source_object_count=source_object_count,
        prepared_object_count=len(prepared_items),
        duplicate_count=sum(item.duplicate_of is not None for item in prepared_items),
        disposition_counts=disposition_counts,
        input_digest_sha256=input_digest_sha256,
        manifest_sha256="",
        migration_complete=False,
    )
    canonical_payload = asdict(manifest)
    canonical_payload.pop("manifest_sha256")
    canonical_bytes = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return replace(manifest, manifest_sha256=sha256(canonical_bytes).hexdigest())


def prepare_legacy_capture(
    path: Path,
    *,
    policy: EngineConvergencePolicy,
    max_line_bytes: int = 65_536,
    max_total_bytes: int = 64 * 1024 * 1024,
    max_records: int = 1_000_000,
    now: datetime | None = None,
) -> LegacyMigrationManifest:
    """Valider une capture en supprimant toute trace interne porteuse de contenu."""

    sanitized_error: str | None = None
    try:
        return _prepare_legacy_capture(
            path,
            policy=policy,
            max_line_bytes=max_line_bytes,
            max_total_bytes=max_total_bytes,
            max_records=max_records,
            now=now,
        )
    except LegacyCaptureError as caught:
        sanitized_error = str(caught)
    if sanitized_error is None:  # pragma: no cover - garde de typage défensive
        raise LegacyCaptureError("capture validation failed")
    raise LegacyCaptureError(sanitized_error)
