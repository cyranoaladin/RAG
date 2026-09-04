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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WAVE0_AGGREGATE_KIND = "WAVE0_AGGREGATE_RELEASE_V1"
_WAVE0_SUBJECT_KIND = "WAVE0_SUBJECT_RELEASE_V1"
_MULTILEVEL_AGGREGATE_KIND = "MULTILEVEL_AGGREGATE_RELEASE_V1"
_MULTILEVEL_SUBJECT_KIND = "MULTILEVEL_SUBJECT_RELEASE_V1"
_MULTILEVEL_ARTIFACT_REGISTRY_KIND_V2 = "MULTILEVEL_ARTIFACT_REGISTRY_V2"
_MULTILEVEL_AGGREGATE_KIND_V2 = "MULTILEVEL_AGGREGATE_RELEASE_V2"
_MULTILEVEL_SUBJECT_KIND_V2 = "MULTILEVEL_SUBJECT_RELEASE_V2"
MAX_RELEASE_MANIFESTS = 32
_REGISTRY_SUPPORTED_VERSIONS = frozenset({"1"})
_REGISTRY_ENTRY_FIELDS = frozenset(
    {
        "release_id",
        "collections",
        "manifest_path",
        "expected_manifest_sha256",
        "release_kind",
    }
)
_REGISTRY_SUPPORTED_RELEASE_KINDS = frozenset(
    {
        _WAVE0_AGGREGATE_KIND,
        _MULTILEVEL_AGGREGATE_KIND,
        _MULTILEVEL_AGGREGATE_KIND_V2,
    }
)
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
#: Chaîne d'autorité de la revue humaine PII (ADR-0047), en extension de
#: l'ensemble fermé ci-dessus. OPTIONNELLE — une release sans contenu détecté
#: n'a pas de décisions à joindre — mais INDIVISIBLE : un ensemble de décisions
#: sans son reçu ne prouve rien, un reçu sans son ancre ne se vérifie pas, et
#: la moitié d'une chaîne d'autorité est une chaîne rompue.
_PII_REVIEW_AUTHORITY_FIELDS = frozenset(
    {
        "pii_decision_set_sha256",
        "pii_review_receipt_sha256",
        "pii_review_trust_anchor_sha256",
        "pii_review_index_sha256",
    }
)
_MULTILEVEL_V2_ARTIFACT_FIELDS = frozenset(
    {
        "artifact_id",
        "content_sha256",
        "source_path",
        "source_url",
        "title",
        "type_doc",
        "page_count",
        "ignored_empty_pages",
        "chunk_id_set_digest",
        "chunk_sha256_set_digest",
        "page_coverage_digest",
        "chunks",
    }
)
_MULTILEVEL_V2_CHUNK_FIELDS = frozenset(
    {"chunk_id", "chunk_index", "chunk_sha256", "page_start", "page_end"}
)
_MULTILEVEL_V2_PLACEMENT_FIELDS = frozenset(
    {
        "placement_id",
        "artifact_id",
        "source_placement_id",
        "source_scope",
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
    collection: str | None
    embedding_model: str
    embedding_dimension: int
    chunks: tuple[Mapping[str, Any], ...]
    placements: tuple[Mapping[str, Any], ...] = ()
    legacy_chunk_collection: str | None = None


@dataclass(frozen=True)
class ExpectedPlacement:
    artifact_id: str
    collection: str
    programme_version: str
    profile_version: str
    profile_fingerprint: str
    profile_manifest_digest: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ReleaseExpectation:
    release_kind: str
    release_id: str
    school_year: str
    collections: tuple[str, ...]
    artifacts: tuple[ExpectedArtifact, ...]
    placements: tuple[ExpectedPlacement, ...]
    embedding_model_id: str
    embedding_inventory_sha256: str
    embedding_dimension: int
    reranker_model_id: str
    reranker_inventory_sha256: str
    subject_manifest_sha256_by_collection: tuple[tuple[str, str], ...]
    release_mode: str | None = None
    promotion_status: str | None = None
    activation_status: str | None = None
    review_status: str | None = None
    #: Chaîne d'autorité de la revue humaine PII, telle que le MANIFESTE la
    #: déclare. Elle était vérifiée syntaxiquement puis jetée : le worker
    #: chargeait la sienne depuis ses propres arguments, et rien ne confrontait
    #: les deux. Une release pouvait donc annoncer une chaîne pendant que le
    #: worker en vérifiait une autre, chacune valide de son côté.
    pii_decision_set_sha256: str | None = None
    pii_review_receipt_sha256: str | None = None
    pii_review_trust_anchor_sha256: str | None = None
    pii_review_index_sha256: str | None = None


@dataclass(frozen=True)
class ReleaseManifestBinding:
    """Manifest explicitement nommé et lié à son empreinte externe."""

    path: Path
    expected_sha256: str
    expectation: ReleaseExpectation


@dataclass(frozen=True)
class ReleaseRegistryExpectation:
    """Union bornée de manifests sans découverte implicite du filesystem."""

    manifests: tuple[ReleaseManifestBinding, ...]
    collections: tuple[str, ...]

    @property
    def model_contract(self) -> tuple[str, str, int, str, str]:
        expectation = self.manifests[0].expectation
        return (
            expectation.embedding_model_id,
            expectation.embedding_inventory_sha256,
            expectation.embedding_dimension,
            expectation.reranker_model_id,
            expectation.reranker_inventory_sha256,
        )

    def manifest_for_collection(self, collection: str) -> ReleaseManifestBinding | None:
        for manifest in self.manifests:
            if collection in manifest.expectation.collections:
                return manifest
        return None


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


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ReleaseReadinessError(f"duplicate JSON object key: {key!r}")
        document[key] = value
    return document


def _read_json_with_digest(path: Path, expected_sha256: str, label: str) -> Mapping[str, Any]:
    _require_sha256(expected_sha256, f"{label}.sha256")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReleaseReadinessError(f"{label} unavailable") from exc
    if _sha256_bytes(data) != expected_sha256:
        raise ReleaseReadinessError(f"{label} digest mismatch")
    try:
        payload = json.loads(data, object_pairs_hook=_reject_duplicate_object_pairs)
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


def _validate_artifact_digests(
    artifact: Mapping[str, Any],
    field: str,
    *,
    include_placements: bool,
) -> None:
    placements = (
        _require_list(artifact.get("placements"), f"{field}.placements")
        if include_placements
        else []
    )
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
        **(
            {
                "placement_id_set_digest": _compact_set_digest(
                    [
                        _require_sha256(
                            _require_mapping(item, f"{field}.placements").get("placement_id"),
                            f"{field}.placement_id",
                        )
                        for item in placements
                    ]
                )
            }
            if include_placements
            else {}
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


def _validate_v2_page_partition(
    artifact: Mapping[str, Any],
    field: str,
    *,
    page_count: int,
    chunks: Sequence[Mapping[str, Any]],
) -> None:
    ignored_empty_pages = _require_list(
        artifact.get("ignored_empty_pages"),
        f"{field}.ignored_empty_pages",
    )
    for index, page in enumerate(ignored_empty_pages):
        if (
            not isinstance(page, int)
            or isinstance(page, bool)
            or page < 1
            or page > page_count
        ):
            raise ReleaseReadinessError(
                f"{field}.ignored_empty_pages[{index}] is invalid"
            )
    if any(
        current <= previous
        for previous, current in zip(
            ignored_empty_pages,
            ignored_empty_pages[1:],
            strict=False,
        )
    ):
        raise ReleaseReadinessError(
            f"{field}.ignored_empty_pages must be strictly increasing"
        )

    covered_pages = {
        page
        for chunk in chunks
        for page in range(int(chunk["page_start"]), int(chunk["page_end"]) + 1)
    }
    ignored_pages = set(ignored_empty_pages)
    if covered_pages & ignored_pages:
        raise ReleaseReadinessError(f"{field} page partition overlaps")
    if covered_pages | ignored_pages != set(range(1, page_count + 1)):
        raise ReleaseReadinessError(f"{field} page partition is incomplete")


def _require_authority_chain(
    authorities: Mapping[str, Any],
    authority_fields: frozenset[str],
    field: str,
    *,
    review_chain_allowed: bool,
) -> None:
    """Vérifie une chaîne d'autorité, agrégat comme sujet.

    L'ensemble fermé peut s'étendre des quatre empreintes de la revue humaine
    PII, et d'elles seules. Elles sont optionnelles — une release sans contenu
    détecté n'a pas de décisions à joindre — mais indivisibles : la moitié
    d'une chaîne d'autorité est une chaîne rompue.

    **L'ouverture dépend du SCHÉMA, pas de la présence des champs.** Soustraire
    ces quatre noms de toute chaîne déclarée les rendait acceptables partout, y
    compris dans les schémas Wave 0 et multi-niveaux V1 qui ne les définissent
    pas : un format ancien s'élargissait alors de lui-même, du seul fait qu'un
    manifeste les mentionne. `review_chain_allowed` est donc décidé par
    l'appelant depuis le genre de release, jamais deviné du contenu.

    Écrit une fois, appelé aux trois endroits : les laisser diverger ferait
    accepter dans l'agrégat ce que le sujet refuse."""
    declared = set(authorities)
    review_declared = (
        declared & _PII_REVIEW_AUTHORITY_FIELDS if review_chain_allowed else set()
    )
    if declared - review_declared != authority_fields:
        raise ReleaseReadinessError(f"{field} fields mismatch")
    if review_declared and review_declared != _PII_REVIEW_AUTHORITY_FIELDS:
        missing = sorted(_PII_REVIEW_AUTHORITY_FIELDS - review_declared)
        raise ReleaseReadinessError(
            f"{field}: incomplete PII review authority chain, {missing} missing — a "
            "decision set without its receipt, or a receipt without its anchor, "
            "proves nothing"
        )
    for name in sorted(authority_fields | review_declared):
        _require_sha256(authorities.get(name), f"{field}.{name}")


def _parse_subject_v1(
    payload: Mapping[str, Any],
    field: str,
    *,
    expected_kind: str,
    authority_fields: frozenset[str],
) -> tuple[str, list[ExpectedArtifact], list[ExpectedPlacement]]:
    if payload.get("release_kind") != expected_kind:
        raise ReleaseReadinessError(f"{field}.release_kind is unsupported")
    collection = _require_nonblank(payload.get("collection"), f"{field}.collection")
    school_year = _require_nonblank(payload.get("school_year"), f"{field}.school_year")
    programme_version = _require_nonblank(
        payload.get("programme_version"), f"{field}.programme_version"
    )
    authorities = _require_mapping(payload.get("authorities"), f"{field}.authorities")
    _require_authority_chain(
        authorities, authority_fields, f"{field}.authorities", review_chain_allowed=False
    )
    profile = _require_mapping(payload.get("profile"), f"{field}.profile")
    if set(profile) != {"version", "fingerprint", "manifest_digest"}:
        raise ReleaseReadinessError(f"{field}.profile fields mismatch")
    profile_version = _require_nonblank(profile.get("version"), f"{field}.profile.version")
    profile_fingerprint = _require_sha256(
        profile.get("fingerprint"), f"{field}.profile.fingerprint"
    )
    profile_manifest_digest = _require_sha256(
        profile.get("manifest_digest"), f"{field}.profile.manifest_digest"
    )
    if "profile_manifest_sha256" in authority_fields and profile_manifest_digest != authorities.get(
        "profile_manifest_sha256"
    ):
        raise ReleaseReadinessError(f"{field}.profile manifest digest differs from authority")
    models = _require_mapping(payload.get("models"), f"{field}.models")
    if set(models) != {"embedding", "reranker"}:
        raise ReleaseReadinessError(f"{field}.models fields mismatch")
    embedding = _require_mapping(models.get("embedding"), f"{field}.models.embedding")
    if set(embedding) != {"model_id", "inventory_sha256", "dimension"}:
        raise ReleaseReadinessError(f"{field}.models.embedding fields mismatch")
    model_id = _require_nonblank(embedding.get("model_id"), f"{field}.models.embedding.model_id")
    _require_sha256(embedding.get("inventory_sha256"), f"{field}.models.embedding.inventory_sha256")
    dimension = embedding.get("dimension")
    if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
        raise ReleaseReadinessError(f"{field}.models.embedding.dimension is invalid")
    reranker = _require_mapping(models.get("reranker"), f"{field}.models.reranker")
    if set(reranker) != {"model_id", "inventory_sha256"}:
        raise ReleaseReadinessError(f"{field}.models.reranker fields mismatch")
    _require_nonblank(reranker.get("model_id"), f"{field}.models.reranker.model_id")
    _require_sha256(reranker.get("inventory_sha256"), f"{field}.models.reranker.inventory_sha256")
    artifacts_raw = _require_list(payload.get("artifacts"), f"{field}.artifacts")
    artifacts: list[ExpectedArtifact] = []
    expected_placements: list[ExpectedPlacement] = []
    seen_artifacts: set[str] = set()
    seen_placements: set[str] = set()
    seen_chunks: set[str] = set()
    for index, artifact_raw in enumerate(artifacts_raw):
        artifact_field = f"{field}.artifacts[{index}]"
        artifact = _require_mapping(artifact_raw, artifact_field)
        _validate_artifact_digests(
            artifact,
            artifact_field,
            include_placements=True,
        )
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
            expected_placements.append(
                ExpectedPlacement(
                    artifact_id=sha,
                    collection=collection,
                    programme_version=programme_version,
                    profile_version=profile_version,
                    profile_fingerprint=profile_fingerprint,
                    profile_manifest_digest=profile_manifest_digest,
                    payload=placement,
                )
            )
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
                type_doc=_require_nonblank(artifact.get("type_doc"), f"{artifact_field}.type_doc"),
                page_count=page_count,
                collection=collection,
                embedding_model=model_id,
                embedding_dimension=dimension,
                chunks=chunks,
                placements=placements,
                legacy_chunk_collection=collection,
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
    return collection, artifacts, expected_placements


def _validate_exact_counts(
    value: object,
    expected: Mapping[str, int],
    field: str,
) -> None:
    counts = _require_mapping(value, field)
    if set(counts) != set(expected):
        raise ReleaseReadinessError(f"{field} fields mismatch")
    for name, expected_value in expected.items():
        observed = counts.get(name)
        if (
            not isinstance(observed, int)
            or isinstance(observed, bool)
            or observed != expected_value
        ):
            raise ReleaseReadinessError(f"{field} mismatch")


def _parse_v2_artifact_registry(
    payload: Mapping[str, Any],
    field: str,
    *,
    release_id: str,
    school_year: str,
    embedding_model: str,
    embedding_dimension: int,
) -> list[ExpectedArtifact]:
    expected_fields = {
        "release_kind",
        "release_id",
        "school_year",
        "expected_counts",
        "artifacts",
    }
    if set(payload) != expected_fields:
        raise ReleaseReadinessError(f"{field} fields mismatch")
    if payload.get("release_kind") != _MULTILEVEL_ARTIFACT_REGISTRY_KIND_V2:
        raise ReleaseReadinessError(f"{field}.release_kind is unsupported")
    if payload.get("release_id") != release_id:
        raise ReleaseReadinessError(f"{field}.release_id mismatch")
    if payload.get("school_year") != school_year:
        raise ReleaseReadinessError(f"{field}.school_year mismatch")

    artifacts_raw = _require_list(payload.get("artifacts"), f"{field}.artifacts")
    if not artifacts_raw:
        raise ReleaseReadinessError(f"{field}.artifacts must not be empty")
    artifacts: list[ExpectedArtifact] = []
    seen_artifacts: set[str] = set()
    seen_chunk_ids: set[str] = set()
    seen_artifact_chunk_indices: set[tuple[str, int]] = set()
    for index, artifact_raw in enumerate(artifacts_raw):
        artifact_field = f"{field}.artifacts[{index}]"
        artifact = _require_mapping(artifact_raw, artifact_field)
        if set(artifact) != _MULTILEVEL_V2_ARTIFACT_FIELDS:
            raise ReleaseReadinessError(f"{artifact_field} fields mismatch")
        artifact_id = _require_sha256(artifact.get("artifact_id"), f"{artifact_field}.artifact_id")
        content_sha256 = _require_sha256(
            artifact.get("content_sha256"), f"{artifact_field}.content_sha256"
        )
        if artifact_id != content_sha256:
            raise ReleaseReadinessError(f"{artifact_field}.artifact_id differs from content_sha256")
        if artifact_id in seen_artifacts:
            raise ReleaseReadinessError(f"{field} contains duplicate artifact definitions")
        seen_artifacts.add(artifact_id)
        page_count = artifact.get("page_count")
        if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count <= 0:
            raise ReleaseReadinessError(f"{artifact_field}.page_count is invalid")
        chunks = tuple(
            _require_mapping(item, f"{artifact_field}.chunks")
            for item in _require_list(artifact.get("chunks"), f"{artifact_field}.chunks")
        )
        if not chunks:
            raise ReleaseReadinessError(f"{artifact_field}.chunks must not be empty")
        chunk_indices: list[int] = []
        for chunk_index_in_manifest, chunk in enumerate(chunks):
            if set(chunk) != _MULTILEVEL_V2_CHUNK_FIELDS:
                raise ReleaseReadinessError(
                    f"{artifact_field}.chunks[{chunk_index_in_manifest}] fields mismatch"
                )
            chunk_id = _require_sha256(chunk.get("chunk_id"), f"{artifact_field}.chunk_id")
            _require_sha256(chunk.get("chunk_sha256"), f"{artifact_field}.chunk_sha256")
            chunk_index = chunk.get("chunk_index")
            if not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 0:
                raise ReleaseReadinessError(f"{artifact_field}.chunk_index is invalid")
            artifact_chunk_index = (artifact_id, chunk_index)
            if chunk_id in seen_chunk_ids or artifact_chunk_index in seen_artifact_chunk_indices:
                raise ReleaseReadinessError(f"{field} contains duplicate chunk definitions")
            seen_chunk_ids.add(chunk_id)
            seen_artifact_chunk_indices.add(artifact_chunk_index)
            chunk_indices.append(chunk_index)
        if chunk_indices != list(range(len(chunks))):
            raise ReleaseReadinessError(f"{artifact_field} chunk indices are not contiguous")
        _validate_artifact_digests(
            artifact,
            artifact_field,
            include_placements=False,
        )
        _validate_v2_page_partition(
            artifact,
            artifact_field,
            page_count=page_count,
            chunks=chunks,
        )
        artifacts.append(
            ExpectedArtifact(
                content_sha256=content_sha256,
                source_path=_require_nonblank(
                    artifact.get("source_path"), f"{artifact_field}.source_path"
                ),
                source_url=_require_nonblank(
                    artifact.get("source_url"), f"{artifact_field}.source_url"
                ),
                title=_require_nonblank(artifact.get("title"), f"{artifact_field}.title"),
                type_doc=_require_nonblank(artifact.get("type_doc"), f"{artifact_field}.type_doc"),
                page_count=page_count,
                collection=None,
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
                chunks=chunks,
            )
        )
    _validate_exact_counts(
        payload.get("expected_counts"),
        {
            "unique_artifacts": len(artifacts),
            "unique_chunks": len(seen_chunk_ids),
        },
        f"{field}.expected_counts",
    )
    return artifacts


def _parse_subject_v2(
    payload: Mapping[str, Any],
    field: str,
    *,
    root: Path,
    subject_path: Path,
    registry_path: Path,
    registry_sha256: str,
    aggregate: Mapping[str, Any],
    school_year: str,
) -> tuple[str, list[ExpectedPlacement]]:
    expected_fields = {
        "release_kind",
        "release_id",
        "school_year",
        "collection",
        "programme_version",
        "authorities",
        "profile",
        "models",
        "artifact_registry",
        "expected_counts",
        "placements",
    }
    if set(payload) != expected_fields:
        if {"artifacts", "chunks"}.intersection(payload):
            raise ReleaseReadinessError(
                f"{field} must not define artifacts or chunks; fields mismatch"
            )
        raise ReleaseReadinessError(f"{field} fields mismatch")
    if payload.get("release_kind") != _MULTILEVEL_SUBJECT_KIND_V2:
        raise ReleaseReadinessError(f"{field}.release_kind is unsupported")
    _require_nonblank(payload.get("release_id"), f"{field}.release_id")
    if payload.get("school_year") != school_year:
        raise ReleaseReadinessError(f"{field}.school_year mismatch")
    collection = _require_nonblank(payload.get("collection"), f"{field}.collection")
    # Un sujet V2 n'a pas d'identite libre : son release_id est DERIVE de celui
    # de l'agregat et de sa collection, comme les sujets V1 reels et le producteur
    # l'ecrivent. Un nom seul n'identifie rien (le meme release_id a deja designe
    # des contenus differents) ; l'identite reste la chaine de digests. Ce lien
    # empeche seulement qu'un sujet rescelle se reclame d'une autre release ou
    # d'une autre collection tout en gardant des parents coherents.
    aggregate_release_id = _require_nonblank(aggregate.get("release_id"), "release_id")
    expected_release_id = f"{aggregate_release_id}-{collection}"
    if payload.get("release_id") != expected_release_id:
        raise ReleaseReadinessError(
            f"{field}.release_id must derive from the aggregate release_id and the "
            f"collection ({expected_release_id!r})"
        )
    programme_version = _require_nonblank(
        payload.get("programme_version"), f"{field}.programme_version"
    )
    authorities = _require_mapping(payload.get("authorities"), f"{field}.authorities")
    _require_authority_chain(
        authorities,
        _MULTILEVEL_AUTHORITY_FIELDS,
        f"{field}.authorities",
        review_chain_allowed=True,
    )
    if authorities != aggregate.get("authorities"):
        raise ReleaseReadinessError(f"{field}.authorities mismatch")
    profile = _require_mapping(payload.get("profile"), f"{field}.profile")
    if set(profile) != {"version", "fingerprint", "manifest_digest"}:
        raise ReleaseReadinessError(f"{field}.profile fields mismatch")
    profile_version = _require_nonblank(profile.get("version"), f"{field}.profile.version")
    profile_fingerprint = _require_sha256(
        profile.get("fingerprint"), f"{field}.profile.fingerprint"
    )
    profile_manifest_digest = _require_sha256(
        profile.get("manifest_digest"), f"{field}.profile.manifest_digest"
    )
    if profile_manifest_digest != authorities.get("profile_manifest_sha256"):
        raise ReleaseReadinessError(f"{field}.profile manifest digest differs from authority")
    if payload.get("models") != aggregate.get("models"):
        raise ReleaseReadinessError(f"{field}.models mismatch")

    registry_reference = _require_mapping(
        payload.get("artifact_registry"), f"{field}.artifact_registry"
    )
    if set(registry_reference) != {"path", "sha256"}:
        raise ReleaseReadinessError(f"{field}.artifact_registry fields mismatch")
    relative_registry_path = Path(
        _require_nonblank(registry_reference.get("path"), f"{field}.artifact_registry.path")
    )
    if relative_registry_path.is_absolute():
        raise ReleaseReadinessError(f"{field}.artifact_registry path must be relative")
    resolved_registry_path = (subject_path.parent / relative_registry_path).resolve()
    if not resolved_registry_path.is_relative_to(root) or resolved_registry_path != registry_path:
        raise ReleaseReadinessError(f"{field}.artifact_registry path mismatch or escape")
    if (
        _require_sha256(registry_reference.get("sha256"), f"{field}.artifact_registry.sha256")
        != registry_sha256
    ):
        raise ReleaseReadinessError(f"{field}.artifact_registry digest mismatch")

    placements_raw = _require_list(payload.get("placements"), f"{field}.placements")
    if not placements_raw:
        raise ReleaseReadinessError(f"{field}.placements must not be empty")
    placements: list[ExpectedPlacement] = []
    seen_placement_ids: set[str] = set()
    seen_artifact_references: set[str] = set()
    for index, placement_raw in enumerate(placements_raw):
        placement_field = f"{field}.placements[{index}]"
        placement = _require_mapping(placement_raw, placement_field)
        if set(placement) != _MULTILEVEL_V2_PLACEMENT_FIELDS:
            raise ReleaseReadinessError(f"{placement_field} fields mismatch")
        placement_id = _require_sha256(
            placement.get("placement_id"), f"{placement_field}.placement_id"
        )
        artifact_id = _require_sha256(
            placement.get("artifact_id"), f"{placement_field}.artifact_id"
        )
        if placement_id in seen_placement_ids:
            raise ReleaseReadinessError(f"{field} contains duplicate placements")
        if artifact_id in seen_artifact_references:
            raise ReleaseReadinessError(f"{field} contains duplicate artifact references")
        seen_placement_ids.add(placement_id)
        seen_artifact_references.add(artifact_id)
        if placement.get("collection") != collection:
            raise ReleaseReadinessError(f"{placement_field} collection mismatch")
        if placement.get("school_year") != school_year:
            raise ReleaseReadinessError(f"{placement_field} school year mismatch")
        if placement.get("programme_version") != programme_version:
            raise ReleaseReadinessError(f"{placement_field} programme version mismatch")
        placements.append(
            ExpectedPlacement(
                artifact_id=artifact_id,
                collection=collection,
                programme_version=programme_version,
                profile_version=profile_version,
                profile_fingerprint=profile_fingerprint,
                profile_manifest_digest=profile_manifest_digest,
                payload=placement,
            )
        )
    _validate_exact_counts(
        payload.get("expected_counts"),
        {
            "unique_artifact_references": len(seen_artifact_references),
            "placements": len(placements),
        },
        f"{field}.expected_counts",
    )
    return collection, placements


def load_release_expectation(path: Path, expected_sha256: str) -> ReleaseExpectation:
    """Charger l'agrégat et chaque manifest matière sous digest exact."""
    aggregate = _read_json_with_digest(Path(path), expected_sha256, "release manifest")
    aggregate_kind = aggregate.get("release_kind")
    if aggregate_kind == _WAVE0_AGGREGATE_KIND:
        subject_kind = _WAVE0_SUBJECT_KIND
        authority_fields = _WAVE0_AUTHORITY_FIELDS
        is_v2 = False
    elif aggregate_kind == _MULTILEVEL_AGGREGATE_KIND:
        subject_kind = _MULTILEVEL_SUBJECT_KIND
        authority_fields = _MULTILEVEL_AUTHORITY_FIELDS
        is_v2 = False
    elif aggregate_kind == _MULTILEVEL_AGGREGATE_KIND_V2:
        subject_kind = _MULTILEVEL_SUBJECT_KIND_V2
        authority_fields = _MULTILEVEL_AUTHORITY_FIELDS
        is_v2 = True
    else:
        raise ReleaseReadinessError("release manifest kind is unsupported")
    valid_v2_keys = {
        "release_kind",
        "release_id",
        "school_year",
        "authorities",
        "models",
        "artifact_registry",
        "expected_counts",
        "subjects",
    }
    optional_v2_keys = {
        "release_mode",
        "promotion_status",
        "activation_status",
        "review_status",
    }
    if is_v2:
        aggregate_keys = set(aggregate)
        if not (aggregate_keys >= valid_v2_keys and aggregate_keys <= (valid_v2_keys | optional_v2_keys)):
            raise ReleaseReadinessError("release manifest fields mismatch")
        release_mode = aggregate.get("release_mode")
        if release_mode is not None and release_mode not in {"production", "rehearsal"}:
            raise ReleaseReadinessError("release manifest release_mode is unsupported")
        promotion_status = aggregate.get("promotion_status")
        if promotion_status is not None and promotion_status not in {"PROMOTABLE", "NOT_PROMOTABLE"}:
            raise ReleaseReadinessError("release manifest promotion_status is unsupported")
        activation_status = aggregate.get("activation_status")
        if activation_status is not None and activation_status not in {
            "PRODUCTION_ACTIVATION_ALLOWED",
            "NO_PRODUCTION_ACTIVATION",
        }:
            raise ReleaseReadinessError("release manifest activation_status is unsupported")
        review_status = aggregate.get("review_status")
        if review_status is not None and review_status not in {"REVIEWED", "PRE_REVIEW"}:
            raise ReleaseReadinessError("release manifest review_status is unsupported")
    else:
        release_mode = None
        promotion_status = None
        activation_status = None
        review_status = None

    release_id = _require_nonblank(aggregate.get("release_id"), "release_id")
    school_year = _require_nonblank(aggregate.get("school_year"), "school_year")
    aggregate_authorities = _require_mapping(aggregate.get("authorities"), "authorities")
    _require_authority_chain(
        aggregate_authorities, authority_fields, "authorities", review_chain_allowed=is_v2
    )
    aggregate_models = _require_mapping(aggregate.get("models"), "models")
    if set(aggregate_models) != {"embedding", "reranker"}:
        raise ReleaseReadinessError("models fields mismatch")
    aggregate_embedding = _require_mapping(aggregate_models.get("embedding"), "models.embedding")
    aggregate_reranker = _require_mapping(aggregate_models.get("reranker"), "models.reranker")
    if set(aggregate_embedding) != {"model_id", "inventory_sha256", "dimension"}:
        raise ReleaseReadinessError("models.embedding fields mismatch")
    if set(aggregate_reranker) != {"model_id", "inventory_sha256"}:
        raise ReleaseReadinessError("models.reranker fields mismatch")
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
    placements: list[ExpectedPlacement] = []
    subject_manifest_sha256_by_collection: list[tuple[str, str]] = []
    seen_subject_paths: set[Path] = set()
    artifact_registry_path: Path | None = None
    artifact_registry_sha256: str | None = None
    if is_v2:
        artifact_registry_reference = _require_mapping(
            aggregate.get("artifact_registry"), "artifact_registry"
        )
        if set(artifact_registry_reference) != {"path", "sha256"}:
            raise ReleaseReadinessError("artifact_registry fields mismatch")
        artifact_registry_relative = Path(
            _require_nonblank(artifact_registry_reference.get("path"), "artifact_registry.path")
        )
        if artifact_registry_relative.is_absolute():
            raise ReleaseReadinessError("artifact registry path must be relative")
        artifact_registry_path = (root / artifact_registry_relative).resolve()
        if not artifact_registry_path.is_relative_to(root):
            raise ReleaseReadinessError("artifact registry path escapes release root")
        artifact_registry_sha256 = _require_sha256(
            artifact_registry_reference.get("sha256"), "artifact_registry.sha256"
        )
        artifact_registry = _read_json_with_digest(
            artifact_registry_path,
            artifact_registry_sha256,
            "artifact registry",
        )
        artifacts.extend(
            _parse_v2_artifact_registry(
                artifact_registry,
                "artifact registry",
                release_id=release_id,
                school_year=school_year,
                embedding_model=embedding_model_id,
                embedding_dimension=embedding_dimension,
            )
        )
    for index, subject_raw in enumerate(subjects):
        subject = _require_mapping(subject_raw, f"subjects[{index}]")
        if is_v2 and set(subject) != {"path", "sha256", "collection"}:
            raise ReleaseReadinessError(f"subjects[{index}] fields mismatch")
        relative = Path(_require_nonblank(subject.get("path"), f"subjects[{index}].path"))
        if is_v2 and relative.is_absolute():
            raise ReleaseReadinessError(f"subjects[{index}].path must be relative")
        subject_path = (root / relative).resolve()
        if not subject_path.is_relative_to(root) or subject_path in seen_subject_paths:
            raise ReleaseReadinessError("subject path escapes or is duplicated")
        seen_subject_paths.add(subject_path)
        subject_sha256 = _require_sha256(subject.get("sha256"), f"subjects[{index}].sha256")
        subject_payload = _read_json_with_digest(
            subject_path,
            subject_sha256,
            "subject release manifest",
        )
        if is_v2:
            if artifact_registry_path is None or artifact_registry_sha256 is None:
                raise ReleaseReadinessError("artifact registry is unavailable")
            collection, subject_placements = _parse_subject_v2(
                subject_payload,
                f"subjects[{index}]",
                root=root,
                subject_path=subject_path,
                registry_path=artifact_registry_path,
                registry_sha256=artifact_registry_sha256,
                aggregate=aggregate,
                school_year=school_year,
            )
            subject_artifacts: list[ExpectedArtifact] = []
        else:
            collection, subject_artifacts, subject_placements = _parse_subject_v1(
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
        subject_manifest_sha256_by_collection.append((collection, subject_sha256))
        artifacts.extend(subject_artifacts)
        placements.extend(subject_placements)
    if not is_v2 and len({item.content_sha256 for item in artifacts}) != len(artifacts):
        raise ReleaseReadinessError("artifact is duplicated across subjects")
    placement_ids = [str(placement.payload["placement_id"]) for placement in placements]
    if len(set(placement_ids)) != len(placement_ids):
        raise ReleaseReadinessError("placement is duplicated across subjects")
    chunk_ids = [str(chunk["chunk_id"]) for artifact in artifacts for chunk in artifact.chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ReleaseReadinessError("chunk is duplicated across subjects")
    if is_v2:
        artifact_ids = {item.content_sha256 for item in artifacts}
        referenced_artifact_ids = {item.artifact_id for item in placements}
        unknown_artifact_ids = referenced_artifact_ids - artifact_ids
        if unknown_artifact_ids:
            raise ReleaseReadinessError("placement references an unknown artifact")
        orphan_artifact_ids = artifact_ids - referenced_artifact_ids
        if orphan_artifact_ids:
            raise ReleaseReadinessError("artifact registry contains an orphan artifact")
        _validate_exact_counts(
            aggregate.get("expected_counts"),
            {
                "unique_artifacts": len(artifacts),
                "placements": len(placements),
                "unique_chunks": len(chunk_ids),
                "subjects": len(collections),
            },
            "expected_counts",
        )
    else:
        counts = _require_mapping(aggregate.get("expected_counts"), "expected_counts")
        aggregate_counts = {
            "artifacts": len(artifacts),
            "placements": len(placements),
            "chunks": len(chunk_ids),
        }
        if any(counts.get(name) != value for name, value in aggregate_counts.items()):
            raise ReleaseReadinessError("expected_counts mismatch")
    return ReleaseExpectation(
        release_kind=str(aggregate_kind),
        release_id=release_id,
        school_year=school_year,
        collections=tuple(collections),
        artifacts=tuple(artifacts),
        placements=tuple(placements),
        embedding_model_id=embedding_model_id,
        embedding_inventory_sha256=embedding_inventory_sha256,
        embedding_dimension=embedding_dimension,
        reranker_model_id=reranker_model_id,
        reranker_inventory_sha256=reranker_inventory_sha256,
        subject_manifest_sha256_by_collection=tuple(subject_manifest_sha256_by_collection),
        release_mode=release_mode,
        promotion_status=promotion_status,
        activation_status=activation_status,
        review_status=review_status,
        # La chaîne de revue déclarée par le manifeste voyage jusqu'au
        # consommateur, au lieu d'être vérifiée puis oubliée : c'est elle que le
        # worker doit confronter à celle qu'il charge de son côté.
        pii_decision_set_sha256=aggregate_authorities.get("pii_decision_set_sha256"),
        pii_review_receipt_sha256=aggregate_authorities.get("pii_review_receipt_sha256"),
        pii_review_trust_anchor_sha256=aggregate_authorities.get(
            "pii_review_trust_anchor_sha256"
        ),
        pii_review_index_sha256=aggregate_authorities.get("pii_review_index_sha256"),
    )



def _expectation_model_contract(
    expectation: ReleaseExpectation,
) -> tuple[str, str, int, str, str]:
    return (
        expectation.embedding_model_id,
        expectation.embedding_inventory_sha256,
        expectation.embedding_dimension,
        expectation.reranker_model_id,
        expectation.reranker_inventory_sha256,
    )


def load_release_registry(
    configurations: Sequence[tuple[Path, str]],
) -> ReleaseRegistryExpectation:
    """Charger 1..N manifests explicitement pinnés, sans glob ni collision."""
    if not configurations:
        raise ReleaseReadinessError("release manifest registry must not be empty")
    if len(configurations) > MAX_RELEASE_MANIFESTS:
        raise ReleaseReadinessError("release manifest registry is too large")

    manifests: list[ReleaseManifestBinding] = []
    collections: list[str] = []
    seen_paths: set[Path] = set()
    seen_artifacts: set[str] = set()
    expected_model_contract: tuple[str, str, int, str, str] | None = None
    expected_school_year: str | None = None
    for path_raw, expected_sha256 in configurations:
        if any(character in str(path_raw) for character in "*?["):
            raise ReleaseReadinessError("release manifest path must be explicit")
        path = Path(path_raw).resolve()
        if path in seen_paths:
            raise ReleaseReadinessError("release manifest path collision")
        seen_paths.add(path)
        expectation = load_release_expectation(path, expected_sha256)
        model_contract = _expectation_model_contract(expectation)
        if expected_model_contract is None:
            expected_model_contract = model_contract
            expected_school_year = expectation.school_year
        elif model_contract != expected_model_contract:
            raise ReleaseReadinessError("release registry model contract mismatch")
        elif expectation.school_year != expected_school_year:
            raise ReleaseReadinessError("release registry school year mismatch")

        duplicate_collections = set(expectation.collections).intersection(collections)
        if duplicate_collections:
            raise ReleaseReadinessError("release registry collection collision")
        artifact_ids = {artifact.content_sha256 for artifact in expectation.artifacts}
        if artifact_ids.intersection(seen_artifacts):
            raise ReleaseReadinessError("release registry artifact collision")
        collections.extend(expectation.collections)
        seen_artifacts.update(artifact_ids)
        manifests.append(
            ReleaseManifestBinding(
                path=path,
                expected_sha256=expected_sha256,
                expectation=expectation,
            )
        )
    return ReleaseRegistryExpectation(
        manifests=tuple(manifests),
        collections=tuple(collections),
    )


def load_release_registry_file(path: Path, expected_sha256: str) -> ReleaseRegistryExpectation:
    """Charger le registre canonique borné des releases actives.

    Le registre est un fichier versionné, vérifié par sa propre empreinte
    externe, qui énumère explicitement chaque release active (2 releases
    Troisième + 10 releases multi-niveaux au démarrage courant). Il ne fait
    que borner *quels* manifests agrégés sont chargés — toute la validation
    de contenu (digest par manifest, collisions de collection/artefact,
    contrat modèle unique) reste celle de :func:`load_release_registry`,
    jamais dupliquée ici.
    """
    payload = _read_json_with_digest(Path(path), expected_sha256, "release registry")
    if payload.get("registry_version") not in _REGISTRY_SUPPORTED_VERSIONS:
        raise ReleaseReadinessError("release registry version is unsupported")
    school_year = _require_nonblank(payload.get("school_year"), "release registry.school_year")
    releases_raw = _require_list(payload.get("releases"), "release registry.releases")
    if not releases_raw:
        raise ReleaseReadinessError("release registry must declare at least one release")
    if len(releases_raw) > MAX_RELEASE_MANIFESTS:
        raise ReleaseReadinessError("release registry declares too many releases")

    root = Path(path).resolve().parent
    configurations: list[tuple[Path, str]] = []
    declared_collections_by_index: list[tuple[str, ...]] = []
    declared_kind_by_index: list[str] = []
    declared_release_id_by_index: list[str] = []
    seen_release_ids: set[str] = set()
    seen_manifest_paths: set[Path] = set()
    seen_declared_collections: set[str] = set()
    for index, entry_raw in enumerate(releases_raw):
        field = f"release registry.releases[{index}]"
        entry = _require_mapping(entry_raw, field)
        if set(entry) != _REGISTRY_ENTRY_FIELDS:
            raise ReleaseReadinessError(f"{field} fields mismatch")

        release_id = _require_nonblank(entry.get("release_id"), f"{field}.release_id")
        if release_id in seen_release_ids:
            raise ReleaseReadinessError(f"{field} declares a duplicate release_id")
        seen_release_ids.add(release_id)

        release_kind = entry.get("release_kind")
        if release_kind not in _REGISTRY_SUPPORTED_RELEASE_KINDS:
            raise ReleaseReadinessError(f"{field}.release_kind is unsupported")

        collections_raw = _require_list(entry.get("collections"), f"{field}.collections")
        if not collections_raw:
            raise ReleaseReadinessError(f"{field}.collections must not be empty")
        collections = tuple(
            _require_nonblank(item, f"{field}.collections") for item in collections_raw
        )
        if len(set(collections)) != len(collections):
            raise ReleaseReadinessError(f"{field}.collections contains duplicates")
        if seen_declared_collections.intersection(collections):
            raise ReleaseReadinessError("release registry collection collision")
        seen_declared_collections.update(collections)

        manifest_path_raw = _require_nonblank(entry.get("manifest_path"), f"{field}.manifest_path")
        if any(character in manifest_path_raw for character in "*?["):
            raise ReleaseReadinessError(f"{field}.manifest_path must be explicit")
        if Path(manifest_path_raw).is_absolute():
            raise ReleaseReadinessError(f"{field}.manifest_path must be relative")
        manifest_path = (root / manifest_path_raw).resolve()
        if not manifest_path.is_relative_to(root):
            raise ReleaseReadinessError(f"{field}.manifest_path escapes the release root")
        if manifest_path in seen_manifest_paths:
            raise ReleaseReadinessError("release registry manifest path collision")
        seen_manifest_paths.add(manifest_path)

        expected_manifest_sha256 = _require_sha256(
            entry.get("expected_manifest_sha256"), f"{field}.expected_manifest_sha256"
        )
        configurations.append((manifest_path, expected_manifest_sha256))
        declared_collections_by_index.append(collections)
        declared_kind_by_index.append(release_kind)
        declared_release_id_by_index.append(release_id)

    registry = load_release_registry(tuple(configurations))

    for binding, declared_collections, declared_kind, declared_release_id in zip(
        registry.manifests,
        declared_collections_by_index,
        declared_kind_by_index,
        declared_release_id_by_index,
        strict=True,
    ):
        if binding.expectation.release_id != declared_release_id:
            raise ReleaseReadinessError(
                "release registry release_id does not match the manifest it names"
            )
        if binding.expectation.release_kind != declared_kind:
            raise ReleaseReadinessError(
                "release registry release_kind does not match the manifest it names"
            )
        if set(binding.expectation.collections) != set(declared_collections):
            raise ReleaseReadinessError(
                "release registry declared collections do not match the manifest"
            )
        if binding.expectation.school_year != school_year:
            raise ReleaseReadinessError("release registry school_year does not match the manifest")

    return registry


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
        str(placement.payload["placement_id"]): placement for placement in expectation.placements
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
        expected_placement = expected_placements[placement_id]
        artifact = expected_artifacts[expected_placement.artifact_id]
        exp_placement = expected_placement.payload
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
            or (
                artifact.legacy_chunk_collection is not None
                and actual.get("collection") != artifact.legacy_chunk_collection
            )
            or actual.get("chunk_index") != exp_chunk.get("chunk_index")
        ):
            wrong_chunk_metadata += 1
        if actual.get("chunk_sha256") != exp_chunk.get("chunk_sha256"):
            wrong_chunk_sha += 1
        if actual.get("page_start") != exp_chunk.get("page_start") or actual.get(
            "page_end"
        ) != exp_chunk.get("page_end"):
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
    *,
    expected_artifact_ids: tuple[str, ...] | None = None,
    release_kind: str | None = None,
) -> ReleaseDatabaseSnapshot:
    """Lire un snapshot borné aux collections déclarées par le manifest."""
    if release_kind == _MULTILEVEL_AGGREGATE_KIND_V2:
        if not expected_artifact_ids:
            raise ReleaseReadinessError(
                "V2 release snapshot requires explicit expected artifact identities"
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
        scoped_artifact_ids = tuple(
            sorted(
                set(expected_artifact_ids)
                | {str(placement["artifact_id"]) for placement in placements}
            )
        )
        artifacts = _fetch_rows(
            connection,
            """
            SELECT DISTINCT a.artifact_id, a.content_sha256, a.source_label,
                   a.source_uri, a.rights, a.official, a.source_kind, a.type_doc
            FROM public.rag_artifacts AS a
            WHERE a.artifact_id = ANY(%s)
               OR NOT EXISTS (
                    SELECT 1 FROM public.rag_artifact_placements AS placement
                    WHERE placement.artifact_id = a.artifact_id
               )
            ORDER BY a.artifact_id
            """,
            scoped_artifact_ids,
            _ARTIFACT_COLUMNS,
        )
        chunk_artifact_ids = tuple(
            sorted(
                set(scoped_artifact_ids)
                | {str(artifact["artifact_id"]) for artifact in artifacts}
            )
        )
        chunks = _fetch_rows(
            connection,
            """
            SELECT chunk_id, artifact_id, collection, chunk_index, chunk_sha256,
                   page_start, page_end, review_status, model,
                   vector IS NOT NULL, CASE WHEN vector IS NULL THEN NULL ELSE vector_dims(vector) END
            FROM public.rag_chunks
            WHERE artifact_id = ANY(%s)
            ORDER BY chunk_id
            """,
            chunk_artifact_ids,
            _CHUNK_COLUMNS,
        )
        return ReleaseDatabaseSnapshot(
            artifacts=artifacts,
            placements=placements,
            chunks=chunks,
        )
    if release_kind not in {
        None,
        _WAVE0_AGGREGATE_KIND,
        _MULTILEVEL_AGGREGATE_KIND,
    }:
        raise ReleaseReadinessError("release snapshot kind is unsupported")
    if expected_artifact_ids is not None:
        raise ReleaseReadinessError(
            "expected artifact identities are reserved for V2 release snapshots"
        )
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


def validate_release_registry_readiness(
    registry: ReleaseRegistryExpectation,
    connection: Any,
) -> dict[str, ReleaseReadinessReport]:
    """Réconcilier séparément chaque collection déclarée par le registre."""
    return {
        collection: validate_release_collection_readiness(
            registry,
            collection,
            connection,
        )
        for collection in registry.collections
    }


def validate_release_collection_readiness(
    registry: ReleaseRegistryExpectation,
    collection: str,
    connection: Any,
) -> ReleaseReadinessReport:
    """Réconcilier une collection avec l'unique manifest qui la possède."""
    manifest = registry.manifest_for_collection(collection)
    if manifest is None:
        return ReleaseReadinessReport(
            ready=False,
            collections=(collection,),
            blockers=("release collection is not configured",),
        )
    placements = tuple(
        placement
        for placement in manifest.expectation.placements
        if placement.collection == collection
    )
    referenced_artifact_ids = {placement.artifact_id for placement in placements}
    artifacts = tuple(
        artifact
        for artifact in manifest.expectation.artifacts
        if artifact.content_sha256 in referenced_artifact_ids
    )
    expectation = replace(
        manifest.expectation,
        collections=(collection,),
        artifacts=artifacts,
        placements=placements,
    )
    try:
        if expectation.release_kind == _MULTILEVEL_AGGREGATE_KIND_V2:
            snapshot = collect_release_snapshot(
                connection,
                (collection,),
                expected_artifact_ids=tuple(
                    artifact.content_sha256 for artifact in expectation.artifacts
                ),
                release_kind=expectation.release_kind,
            )
        else:
            snapshot = collect_release_snapshot(connection, (collection,))
        return evaluate_release_snapshot(expectation, snapshot)
    except Exception:
        return ReleaseReadinessReport(
            ready=False,
            collections=(collection,),
            blockers=("release database reconciliation unavailable",),
        )


def validate_release_readiness(
    manifest_path: Path,
    expected_sha256: str,
    connection: Any,
) -> ReleaseReadinessReport:
    """Retourner un rapport fail-closed sans divulguer le contenu documentaire."""
    try:
        expectation = load_release_expectation(Path(manifest_path), expected_sha256)
        if expectation.release_kind == _MULTILEVEL_AGGREGATE_KIND_V2:
            snapshot = collect_release_snapshot(
                connection,
                expectation.collections,
                expected_artifact_ids=tuple(
                    artifact.content_sha256 for artifact in expectation.artifacts
                ),
                release_kind=expectation.release_kind,
            )
        else:
            snapshot = collect_release_snapshot(connection, expectation.collections)
        return evaluate_release_snapshot(expectation, snapshot)
    except ReleaseReadinessError as exc:
        return ReleaseReadinessReport(ready=False, blockers=(str(exc),))
    except Exception:
        return ReleaseReadinessReport(
            ready=False,
            blockers=("release database reconciliation unavailable",),
        )
