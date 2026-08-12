"""Réconciliation exacte d'un release manifest avec PostgreSQL/pgvector.

Le manifest est une cible scellée, pas une indication de volume. Une collection
Wave 0 n'est prête que si les ensembles complets d'artefacts, placements et
chunks correspondent et si chaque ligne conserve les statuts et modèles
gouvernés attendus.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WAVE0_AGGREGATE_KIND = "WAVE0_AGGREGATE_RELEASE_V1"
_WAVE0_SUBJECT_KIND = "WAVE0_SUBJECT_RELEASE_V1"
_MULTILEVEL_AGGREGATE_KIND = "MULTILEVEL_AGGREGATE_RELEASE_V1"
_MULTILEVEL_SUBJECT_KIND = "MULTILEVEL_SUBJECT_RELEASE_V1"
_WAVE0_AUTHORITY_FIELDS = frozenset(
    {
        "corpus_manifest_sha256",
        "sealed_catalog_sha256",
        "placement_catalog_sha256",
        "candidate_inventory_sha256",
        "currentness_evidence_sha256",
        "pii_evidence_sha256",
        "pii_policy_sha256",
        "rights_registry_sha256",
    }
)
_MULTILEVEL_AUTHORITY_FIELDS = frozenset(
    {
        "corpus_manifest_sha256",
        "parent_sealed_catalog_sha256",
        "placement_catalog_sha256",
        "catalog_delta_sha256",
        "effective_catalog_authority_sha256",
        "candidate_inventory_sha256",
        "currentness_evidence_sha256",
        "pii_evidence_sha256",
        "pii_policy_sha256",
        "pii_scanner_sha256",
        "rights_registry_sha256",
        "preflight_evidence_sha256",
        "programme_registry_sha256",
        "profile_manifest_sha256",
        "level_mapping_sha256",
        "subject_mapping_sha256",
        "document_type_mapping_sha256",
        "embedding_inventory_sha256",
        "reranker_inventory_sha256",
    }
)


class ReleaseReadinessError(ValueError):
    """Le manifest release ne peut pas constituer une autorité exacte."""


@dataclass(frozen=True)
class ExpectedArtifact:
    content_sha256: str
    source_path: str
    source_url: str
    title: str
    type_doc: str
    page_count: int
    collection: str
    embedding_model: str
    embedding_dimension: int
    programme_version: str
    profile_version: str
    profile_fingerprint: str
    profile_manifest_digest: str
    placements: tuple[Mapping[str, Any], ...]
    chunks: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ReleaseExpectation:
    release_id: str
    school_year: str
    collections: tuple[str, ...]
    artifacts: tuple[ExpectedArtifact, ...]
    embedding_model_id: str
    embedding_inventory_sha256: str
    embedding_dimension: int
    reranker_model_id: str
    reranker_inventory_sha256: str


@dataclass(frozen=True)
class ReleaseDatabaseSnapshot:
    artifacts: tuple[Mapping[str, Any], ...]
    placements: tuple[Mapping[str, Any], ...]
    chunks: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ReleaseReadinessReport:
    ready: bool
    collections: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    missing_artifacts: int = 0
    unexpected_artifacts: int = 0
    missing_placements: int = 0
    unexpected_placements: int = 0
    missing_chunks: int = 0
    unexpected_chunks: int = 0
    wrong_artifact_metadata: int = 0
    wrong_placement_metadata: int = 0
    wrong_chunk_metadata: int = 0
    wrong_chunk_sha: int = 0
    wrong_page_metadata: int = 0
    wrong_model_rows: int = 0
    null_vectors: int = 0
    wrong_vector_dimensions: int = 0
    wrong_review_status: int = 0
    wrong_currentness: int = 0


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReleaseReadinessError(f"{field} must be a lowercase SHA-256")
    return value


def _require_nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseReadinessError(f"{field} must be nonblank")
    return value


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseReadinessError(f"{field} must be an object")
    return value


def _require_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReleaseReadinessError(f"{field} must be an array")
    return value


def _read_json_with_digest(path: Path, expected_sha256: str, label: str) -> Mapping[str, Any]:
    _require_sha256(expected_sha256, f"{label}.sha256")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReleaseReadinessError(f"{label} unavailable") from exc
    if _sha256_bytes(data) != expected_sha256:
        raise ReleaseReadinessError(f"{label} digest mismatch")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseReadinessError(f"{label} is not valid JSON") from exc
    return _require_mapping(payload, label)


def _compact_set_digest(values: Sequence[object]) -> str:
    encoded = json.dumps(
        sorted(values, key=lambda item: json.dumps(item, sort_keys=True)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _validate_artifact_digests(artifact: Mapping[str, Any], field: str) -> None:
    placements = _require_list(artifact.get("placements"), f"{field}.placements")
    chunks = _require_list(artifact.get("chunks"), f"{field}.chunks")
    pages: set[int] = set()
    for index, chunk_raw in enumerate(chunks):
        chunk = _require_mapping(chunk_raw, f"{field}.chunks[{index}]")
        page_start = chunk.get("page_start")
        page_end = chunk.get("page_end")
        if (
            not isinstance(page_start, int)
            or isinstance(page_start, bool)
            or not isinstance(page_end, int)
            or isinstance(page_end, bool)
            or page_start < 1
            or page_end < page_start
        ):
            raise ReleaseReadinessError(f"{field}.chunks[{index}] has invalid pages")
        pages.update(range(page_start, page_end + 1))
    expected = {
        "placement_id_set_digest": _compact_set_digest(
            [
                _require_sha256(
                    _require_mapping(item, f"{field}.placements").get("placement_id"),
                    f"{field}.placement_id",
                )
                for item in placements
            ]
        ),
        "chunk_id_set_digest": _compact_set_digest(
            [
                _require_sha256(
                    _require_mapping(item, f"{field}.chunks").get("chunk_id"),
                    f"{field}.chunk_id",
                )
                for item in chunks
            ]
        ),
        "chunk_sha256_set_digest": _compact_set_digest(
            [
                _require_sha256(
                    _require_mapping(item, f"{field}.chunks").get("chunk_sha256"),
                    f"{field}.chunk_sha256",
                )
                for item in chunks
            ]
        ),
        "page_coverage_digest": _compact_set_digest(list(pages)),
    }
    for name, digest in expected.items():
        if artifact.get(name) != digest:
            raise ReleaseReadinessError(f"{field}.{name} mismatch")


def _parse_subject(
    payload: Mapping[str, Any],
    field: str,
    *,
    expected_kind: str,
    authority_fields: frozenset[str],
) -> tuple[str, list[ExpectedArtifact]]:
    if payload.get("release_kind") != expected_kind:
        raise ReleaseReadinessError(f"{field}.release_kind is unsupported")
    collection = _require_nonblank(payload.get("collection"), f"{field}.collection")
    school_year = _require_nonblank(payload.get("school_year"), f"{field}.school_year")
    programme_version = _require_nonblank(
        payload.get("programme_version"), f"{field}.programme_version"
    )
    authorities = _require_mapping(payload.get("authorities"), f"{field}.authorities")
    if set(authorities) != authority_fields:
        raise ReleaseReadinessError(f"{field}.authorities fields mismatch")
    for name in authority_fields:
        _require_sha256(authorities.get(name), f"{field}.authorities.{name}")
    profile = _require_mapping(payload.get("profile"), f"{field}.profile")
    if set(profile) != {"version", "fingerprint", "manifest_digest"}:
        raise ReleaseReadinessError(f"{field}.profile fields mismatch")
    profile_version = _require_nonblank(
        profile.get("version"), f"{field}.profile.version"
    )
    profile_fingerprint = _require_sha256(
        profile.get("fingerprint"), f"{field}.profile.fingerprint"
    )
    profile_manifest_digest = _require_sha256(
        profile.get("manifest_digest"), f"{field}.profile.manifest_digest"
    )
    models = _require_mapping(payload.get("models"), f"{field}.models")
    if set(models) != {"embedding", "reranker"}:
        raise ReleaseReadinessError(f"{field}.models fields mismatch")
    embedding = _require_mapping(models.get("embedding"), f"{field}.models.embedding")
    if set(embedding) != {"model_id", "inventory_sha256", "dimension"}:
        raise ReleaseReadinessError(f"{field}.models.embedding fields mismatch")
    model_id = _require_nonblank(
        embedding.get("model_id"), f"{field}.models.embedding.model_id"
    )
    _require_sha256(
        embedding.get("inventory_sha256"), f"{field}.models.embedding.inventory_sha256"
    )
    dimension = embedding.get("dimension")
    if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
        raise ReleaseReadinessError(f"{field}.models.embedding.dimension is invalid")
    reranker = _require_mapping(models.get("reranker"), f"{field}.models.reranker")
    if set(reranker) != {"model_id", "inventory_sha256"}:
        raise ReleaseReadinessError(f"{field}.models.reranker fields mismatch")
    _require_nonblank(reranker.get("model_id"), f"{field}.models.reranker.model_id")
    _require_sha256(
        reranker.get("inventory_sha256"), f"{field}.models.reranker.inventory_sha256"
    )
    artifacts_raw = _require_list(payload.get("artifacts"), f"{field}.artifacts")
    artifacts: list[ExpectedArtifact] = []
    seen_artifacts: set[str] = set()
    seen_placements: set[str] = set()
    seen_chunks: set[str] = set()
    for index, artifact_raw in enumerate(artifacts_raw):
        artifact_field = f"{field}.artifacts[{index}]"
        artifact = _require_mapping(artifact_raw, artifact_field)
        _validate_artifact_digests(artifact, artifact_field)
        sha = _require_sha256(artifact.get("content_sha256"), f"{artifact_field}.content_sha256")
        if sha in seen_artifacts:
            raise ReleaseReadinessError(f"{field} contains duplicate artifacts")
        seen_artifacts.add(sha)
        page_count = artifact.get("page_count")
        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count <= 0:
            raise ReleaseReadinessError(f"{artifact_field}.page_count is invalid")
        placements = tuple(
            _require_mapping(item, f"{artifact_field}.placements")
            for item in _require_list(artifact.get("placements"), f"{artifact_field}.placements")
        )
        chunks = tuple(
            _require_mapping(item, f"{artifact_field}.chunks")
            for item in _require_list(artifact.get("chunks"), f"{artifact_field}.chunks")
        )
        if not placements or not chunks:
            raise ReleaseReadinessError(f"{artifact_field} must contain placements and chunks")
        chunk_indices = [chunk.get("chunk_index") for chunk in chunks]
        if chunk_indices != list(range(len(chunks))):
            raise ReleaseReadinessError(f"{artifact_field} chunk indices are not contiguous")
        covered_pages = {
            page
            for chunk in chunks
            for page in range(int(chunk["page_start"]), int(chunk["page_end"]) + 1)
        }
        if covered_pages != set(range(1, page_count + 1)):
            raise ReleaseReadinessError(f"{artifact_field} page coverage is incomplete")
        for placement in placements:
            placement_id = _require_sha256(
                placement.get("placement_id"), f"{artifact_field}.placement_id"
            )
            if placement_id in seen_placements:
                raise ReleaseReadinessError(f"{field} contains duplicate placements")
            seen_placements.add(placement_id)
            if placement.get("collection") != collection:
                raise ReleaseReadinessError(f"{artifact_field} placement collection mismatch")
            if placement.get("school_year") != school_year:
                raise ReleaseReadinessError(f"{artifact_field} placement school year mismatch")
            if placement.get("programme_version") != programme_version:
                raise ReleaseReadinessError(f"{artifact_field} programme version mismatch")
        for chunk in chunks:
            chunk_id = _require_sha256(chunk.get("chunk_id"), f"{artifact_field}.chunk_id")
            _require_sha256(chunk.get("chunk_sha256"), f"{artifact_field}.chunk_sha256")
            if chunk_id in seen_chunks:
                raise ReleaseReadinessError(f"{field} contains duplicate chunks")
            seen_chunks.add(chunk_id)
        artifacts.append(
            ExpectedArtifact(
                content_sha256=sha,
                source_path=_require_nonblank(
                    artifact.get("source_path"), f"{artifact_field}.source_path"
                ),
                source_url=_require_nonblank(
                    artifact.get("source_url"), f"{artifact_field}.source_url"
                ),
                title=_require_nonblank(artifact.get("title"), f"{artifact_field}.title"),
                type_doc=_require_nonblank(
                    artifact.get("type_doc"), f"{artifact_field}.type_doc"
                ),
                page_count=page_count,
                collection=collection,
                embedding_model=model_id,
                embedding_dimension=dimension,
                programme_version=programme_version,
                profile_version=profile_version,
                profile_fingerprint=profile_fingerprint,
                profile_manifest_digest=profile_manifest_digest,
                placements=placements,
                chunks=chunks,
            )
        )
    counts = _require_mapping(payload.get("expected_counts"), f"{field}.expected_counts")
    observed_counts = {
        "artifacts": len(artifacts),
        "placements": len(seen_placements),
        "chunks": len(seen_chunks),
    }
    if any(counts.get(name) != value for name, value in observed_counts.items()):
        raise ReleaseReadinessError(f"{field}.expected_counts mismatch")
    return collection, artifacts


def load_release_expectation(path: Path, expected_sha256: str) -> ReleaseExpectation:
    """Charger l'agrégat et chaque manifest matière sous digest exact."""
    aggregate = _read_json_with_digest(Path(path), expected_sha256, "release manifest")
    aggregate_kind = aggregate.get("release_kind")
    if aggregate_kind == _WAVE0_AGGREGATE_KIND:
        subject_kind = _WAVE0_SUBJECT_KIND
        authority_fields = _WAVE0_AUTHORITY_FIELDS
    elif aggregate_kind == _MULTILEVEL_AGGREGATE_KIND:
        subject_kind = _MULTILEVEL_SUBJECT_KIND
        authority_fields = _MULTILEVEL_AUTHORITY_FIELDS
    else:
        raise ReleaseReadinessError("release manifest kind is unsupported")
    release_id = _require_nonblank(aggregate.get("release_id"), "release_id")
    school_year = _require_nonblank(aggregate.get("school_year"), "school_year")
    aggregate_authorities = _require_mapping(aggregate.get("authorities"), "authorities")
    if set(aggregate_authorities) != authority_fields:
        raise ReleaseReadinessError("authorities fields mismatch")
    for name in authority_fields:
        _require_sha256(aggregate_authorities.get(name), f"authorities.{name}")
    aggregate_models = _require_mapping(aggregate.get("models"), "models")
    if set(aggregate_models) != {"embedding", "reranker"}:
        raise ReleaseReadinessError("models fields mismatch")
    aggregate_embedding = _require_mapping(
        aggregate_models.get("embedding"), "models.embedding"
    )
    aggregate_reranker = _require_mapping(
        aggregate_models.get("reranker"), "models.reranker"
    )
    embedding_model_id = _require_nonblank(
        aggregate_embedding.get("model_id"), "models.embedding.model_id"
    )
    embedding_inventory_sha256 = _require_sha256(
        aggregate_embedding.get("inventory_sha256"),
        "models.embedding.inventory_sha256",
    )
    embedding_dimension = aggregate_embedding.get("dimension")
    if (
        not isinstance(embedding_dimension, int)
        or isinstance(embedding_dimension, bool)
        or embedding_dimension <= 0
    ):
        raise ReleaseReadinessError("models.embedding.dimension is invalid")
    reranker_model_id = _require_nonblank(
        aggregate_reranker.get("model_id"), "models.reranker.model_id"
    )
    reranker_inventory_sha256 = _require_sha256(
        aggregate_reranker.get("inventory_sha256"),
        "models.reranker.inventory_sha256",
    )
    subjects = _require_list(aggregate.get("subjects"), "subjects")
    if not subjects:
        raise ReleaseReadinessError("subjects must not be empty")
    root = Path(path).resolve().parent
    collections: list[str] = []
    artifacts: list[ExpectedArtifact] = []
    seen_subject_paths: set[Path] = set()
    for index, subject_raw in enumerate(subjects):
        subject = _require_mapping(subject_raw, f"subjects[{index}]")
        relative = Path(_require_nonblank(subject.get("path"), f"subjects[{index}].path"))
        subject_path = (root / relative).resolve()
        if not subject_path.is_relative_to(root) or subject_path in seen_subject_paths:
            raise ReleaseReadinessError("subject path escapes or is duplicated")
        seen_subject_paths.add(subject_path)
        subject_payload = _read_json_with_digest(
            subject_path,
            _require_sha256(subject.get("sha256"), f"subjects[{index}].sha256"),
            "subject release manifest",
        )
        collection, subject_artifacts = _parse_subject(
            subject_payload,
            f"subjects[{index}]",
            expected_kind=subject_kind,
            authority_fields=authority_fields,
        )
        if collection != subject.get("collection") or collection in collections:
            raise ReleaseReadinessError("subject collection mismatch or duplicate")
        if subject_payload.get("school_year") != school_year:
            raise ReleaseReadinessError("subject school year mismatch")
        if subject_payload.get("authorities") != aggregate.get("authorities"):
            raise ReleaseReadinessError("subject authorities mismatch")
        if subject_payload.get("models") != aggregate.get("models"):
            raise ReleaseReadinessError("subject models mismatch")
        collections.append(collection)
        artifacts.extend(subject_artifacts)
    if len({item.content_sha256 for item in artifacts}) != len(artifacts):
        raise ReleaseReadinessError("artifact is duplicated across subjects")
    counts = _require_mapping(aggregate.get("expected_counts"), "expected_counts")
    aggregate_counts = {
        "artifacts": len(artifacts),
        "placements": sum(len(item.placements) for item in artifacts),
        "chunks": sum(len(item.chunks) for item in artifacts),
    }
    if any(counts.get(name) != value for name, value in aggregate_counts.items()):
        raise ReleaseReadinessError("expected_counts mismatch")
    return ReleaseExpectation(
        release_id=release_id,
        school_year=school_year,
        collections=tuple(collections),
        artifacts=tuple(artifacts),
        embedding_model_id=embedding_model_id,
        embedding_inventory_sha256=embedding_inventory_sha256,
        embedding_dimension=embedding_dimension,
        reranker_model_id=reranker_model_id,
        reranker_inventory_sha256=reranker_inventory_sha256,
    )


def _mapping_by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        identity = row.get(key)
        if isinstance(identity, str) and identity not in result:
            result[identity] = row
    return result


def evaluate_release_snapshot(
    expectation: ReleaseExpectation,
    snapshot: ReleaseDatabaseSnapshot,
) -> ReleaseReadinessReport:
    """Comparer les sets complets et tous les champs gouvernés attendus."""
    expected_artifacts = {item.content_sha256: item for item in expectation.artifacts}
    expected_placements = {
        str(placement["placement_id"]): (artifact, placement)
        for artifact in expectation.artifacts
        for placement in artifact.placements
    }
    expected_chunks = {
        str(chunk["chunk_id"]): (artifact, chunk)
        for artifact in expectation.artifacts
        for chunk in artifact.chunks
    }
    actual_artifacts = _mapping_by(snapshot.artifacts, "artifact_id")
    actual_placements = _mapping_by(snapshot.placements, "placement_id")
    actual_chunks = _mapping_by(snapshot.chunks, "chunk_id")

    missing_artifacts = len(expected_artifacts.keys() - actual_artifacts.keys())
    unexpected_artifacts = len(actual_artifacts.keys() - expected_artifacts.keys())
    missing_placements = len(expected_placements.keys() - actual_placements.keys())
    unexpected_placements = len(actual_placements.keys() - expected_placements.keys())
    missing_chunks = len(expected_chunks.keys() - actual_chunks.keys())
    unexpected_chunks = len(actual_chunks.keys() - expected_chunks.keys())

    wrong_artifact_metadata = 0
    for artifact_id in expected_artifacts.keys() & actual_artifacts.keys():
        exp_artifact = expected_artifacts[artifact_id]
        actual = actual_artifacts[artifact_id]
        expected_source_kind = urlparse(exp_artifact.source_url).hostname
        if (
            actual.get("content_sha256") != exp_artifact.content_sha256
            or actual.get("source_label") != expected_source_kind
            or actual.get("source_uri") != exp_artifact.source_url
            or actual.get("type_doc") != exp_artifact.type_doc
            or actual.get("rights") != "officiel_public"
            or actual.get("official") is not True
            or actual.get("source_kind") != expected_source_kind
        ):
            wrong_artifact_metadata += 1

    wrong_placement_metadata = 0
    wrong_review_status = 0
    wrong_currentness = 0
    placement_fields = (
        "placement_id",
        "collection",
        "tenant",
        "niveau",
        "voie",
        "matiere",
        "statut_enseignement",
        "candidat",
        "visibility",
        "school_year",
        "programme_version",
        "source_scope",
        "source_placement_id",
    )
    for placement_id in expected_placements.keys() & actual_placements.keys():
        artifact, exp_placement = expected_placements[placement_id]
        actual = actual_placements[placement_id]
        if (
            any(actual.get(field) != exp_placement.get(field) for field in placement_fields)
            or actual.get("artifact_id") != artifact.content_sha256
            or actual.get("source_path") != artifact.source_path
            or actual.get("source_uri") != artifact.source_url
            or not actual.get("authorization_id")
            or not actual.get("publication_attestation_id")
            or actual.get("placement_status") != "active"
        ):
            wrong_placement_metadata += 1
        if actual.get("review_status") != "reviewed":
            wrong_review_status += 1
        if actual.get("currentness") != "current":
            wrong_currentness += 1

    wrong_chunk_metadata = 0
    wrong_chunk_sha = 0
    wrong_page_metadata = 0
    wrong_model_rows = 0
    null_vectors = 0
    wrong_vector_dimensions = 0
    for chunk_id in expected_chunks.keys() & actual_chunks.keys():
        artifact, exp_chunk = expected_chunks[chunk_id]
        actual = actual_chunks[chunk_id]
        if (
            actual.get("artifact_id") != artifact.content_sha256
            or actual.get("collection") != artifact.collection
            or actual.get("chunk_index") != exp_chunk.get("chunk_index")
        ):
            wrong_chunk_metadata += 1
        if actual.get("chunk_sha256") != exp_chunk.get("chunk_sha256"):
            wrong_chunk_sha += 1
        if (
            actual.get("page_start") != exp_chunk.get("page_start")
            or actual.get("page_end") != exp_chunk.get("page_end")
        ):
            wrong_page_metadata += 1
        if actual.get("model") != artifact.embedding_model:
            wrong_model_rows += 1
        if actual.get("review_status") != "reviewed":
            wrong_review_status += 1
        if actual.get("vector_present") is not True:
            null_vectors += 1
        elif actual.get("vector_dimension") != artifact.embedding_dimension:
            wrong_vector_dimensions += 1

    counters = {
        "missing_artifacts": missing_artifacts,
        "unexpected_artifacts": unexpected_artifacts,
        "missing_placements": missing_placements,
        "unexpected_placements": unexpected_placements,
        "missing_chunks": missing_chunks,
        "unexpected_chunks": unexpected_chunks,
        "wrong_artifact_metadata": wrong_artifact_metadata,
        "wrong_placement_metadata": wrong_placement_metadata,
        "wrong_chunk_metadata": wrong_chunk_metadata,
        "wrong_chunk_sha": wrong_chunk_sha,
        "wrong_page_metadata": wrong_page_metadata,
        "wrong_model_rows": wrong_model_rows,
        "null_vectors": null_vectors,
        "wrong_vector_dimensions": wrong_vector_dimensions,
        "wrong_review_status": wrong_review_status,
        "wrong_currentness": wrong_currentness,
    }
    blockers = tuple(f"{name}={value}" for name, value in counters.items() if value)
    return ReleaseReadinessReport(
        ready=not blockers,
        collections=expectation.collections,
        blockers=blockers,
        **counters,
    )


_ARTIFACT_COLUMNS = (
    "artifact_id",
    "content_sha256",
    "source_label",
    "source_uri",
    "rights",
    "official",
    "source_kind",
    "type_doc",
)
_PLACEMENT_COLUMNS = (
    "placement_id",
    "artifact_id",
    "collection",
    "tenant",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "candidat",
    "visibility",
    "school_year",
    "programme_version",
    "currentness",
    "placement_status",
    "review_status",
    "source_scope",
    "source_placement_id",
    "source_path",
    "source_uri",
    "authorization_id",
    "publication_attestation_id",
)
_CHUNK_COLUMNS = (
    "chunk_id",
    "artifact_id",
    "collection",
    "chunk_index",
    "chunk_sha256",
    "page_start",
    "page_end",
    "review_status",
    "model",
    "vector_present",
    "vector_dimension",
)


def _fetch_rows(
    connection: Any,
    sql: str,
    collections: tuple[str, ...],
    columns: tuple[str, ...],
    *,
    collection_parameters: int = 1,
) -> tuple[Mapping[str, Any], ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            tuple(list(collections) for _ in range(collection_parameters)),
        )
        return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())


def collect_release_snapshot(
    connection: Any,
    collections: tuple[str, ...],
) -> ReleaseDatabaseSnapshot:
    """Lire un snapshot borné aux collections déclarées par le manifest."""
    artifacts = _fetch_rows(
        connection,
        """
        SELECT DISTINCT a.artifact_id, a.content_sha256, a.source_label,
               a.source_uri, a.rights, a.official, a.source_kind, a.type_doc
        FROM public.rag_artifacts AS a
        JOIN (
            SELECT artifact_id
            FROM public.rag_artifact_placements
            WHERE collection = ANY(%s)
            UNION
            SELECT artifact_id
            FROM public.rag_chunks
            WHERE collection = ANY(%s) AND artifact_id IS NOT NULL
            UNION
            SELECT orphan.artifact_id
            FROM public.rag_artifacts AS orphan
            WHERE NOT EXISTS (
                SELECT 1 FROM public.rag_artifact_placements AS placement
                WHERE placement.artifact_id = orphan.artifact_id
            ) AND NOT EXISTS (
                SELECT 1 FROM public.rag_chunks AS chunk
                WHERE chunk.artifact_id = orphan.artifact_id
            )
        ) AS scoped ON scoped.artifact_id = a.artifact_id
        ORDER BY a.artifact_id
        """,
        collections,
        _ARTIFACT_COLUMNS,
        collection_parameters=2,
    )
    placements = _fetch_rows(
        connection,
        """
        SELECT placement_id, artifact_id, collection, tenant, niveau, voie,
               matiere, statut_enseignement, candidat, visibility, school_year,
               programme_version, currentness, placement_status, review_status,
               source_scope, source_placement_id, source_path, source_uri, authorization_id,
               publication_attestation_id::text
        FROM public.rag_artifact_placements
        WHERE collection = ANY(%s)
        ORDER BY placement_id
        """,
        collections,
        _PLACEMENT_COLUMNS,
    )
    chunks = _fetch_rows(
        connection,
        """
        SELECT chunk_id, artifact_id, collection, chunk_index, chunk_sha256,
               page_start, page_end, review_status, model,
               vector IS NOT NULL, CASE WHEN vector IS NULL THEN NULL ELSE vector_dims(vector) END
        FROM public.rag_chunks
        WHERE collection = ANY(%s)
        ORDER BY chunk_id
        """,
        collections,
        _CHUNK_COLUMNS,
    )
    return ReleaseDatabaseSnapshot(
        artifacts=artifacts,
        placements=placements,
        chunks=chunks,
    )


def validate_release_readiness(
    manifest_path: Path,
    expected_sha256: str,
    connection: Any,
) -> ReleaseReadinessReport:
    """Retourner un rapport fail-closed sans divulguer le contenu documentaire."""
    try:
        expectation = load_release_expectation(Path(manifest_path), expected_sha256)
        snapshot = collect_release_snapshot(connection, expectation.collections)
        return evaluate_release_snapshot(expectation, snapshot)
    except ReleaseReadinessError as exc:
        return ReleaseReadinessReport(ready=False, blockers=(str(exc),))
    except Exception:
        return ReleaseReadinessReport(
            ready=False,
            blockers=("release database reconciliation unavailable",),
        )
