"""Autorités versionnées du release exact-grade Wave 0.

Ce module ne classe aucun document par heuristique. Il charge des artefacts
bornés par digest, vérifie leurs ensembles et expose les faits minimaux dont
le resolver a besoin. Les SHA métier appartiennent aux données versionnées,
jamais au code runtime.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from nexus_contracts.document import Niveau, TypeDoc, Voie

CANDIDATE_INVENTORY_KIND = "WAVE0_EXACT_GRADE_CANDIDATE_INVENTORY_V1"
PEDAGOGICAL_MAPPING_KIND = "EDUSCOL_WAVE0_PEDAGOGICAL_MAPPING_V1"
SUBJECT_RELEASE_KIND = "WAVE0_SUBJECT_RELEASE_V1"
AGGREGATE_RELEASE_KIND = "WAVE0_AGGREGATE_RELEASE_V1"

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_SCHOOL_YEAR = re.compile(r"\A[0-9]{4}-[0-9]{4}\Z")
_EDUSCOL_ZONE = "01_EDUSCOL_OFFICIEL/"
_EXACT_LEVEL = "3e"
_SUBJECTS = frozenset({"francais", "mathematiques", "maths"})


class ReleaseAuthorityError(RuntimeError):
    """Un artefact d'autorité release est absent, ambigu ou a dérivé."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReleaseAuthorityError(f"{label} must be a lowercase 64-hex SHA")
    return value


def require_file_digest(path: Path, expected_sha256: str, *, label: str) -> str:
    expected = require_sha256(expected_sha256, label=f"expected {label} SHA")
    try:
        actual = file_sha256(path)
    except OSError as exc:
        raise ReleaseAuthorityError(f"{label} cannot be read") from exc
    if actual != expected:
        raise ReleaseAuthorityError(
            f"{label} hashes to {actual}, not expected digest {expected}"
        )
    return actual


def _load_json(path: Path, *, label: str) -> Mapping[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseAuthorityError(f"{label} cannot be read") from exc
    if not isinstance(document, Mapping):
        raise ReleaseAuthorityError(f"{label} must be a mapping")
    return document


def _require_nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseAuthorityError(f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True)
class CandidatePlacement:
    content_sha256: str
    physical_path: str
    source_url: str
    title: str
    source_placement_id: str
    external_scope: str
    external_level: str
    external_subject: str
    external_document_type: str
    pedagogical_status: str
    physical_currentness_candidate: str
    physical_disposition_candidate: str


@dataclass(frozen=True)
class CandidateInventory:
    sha256: str
    school_year: str
    corpus_manifest_sha256: str
    sealed_catalog_sha256: str
    placement_catalog_sha256: str
    candidates: tuple[CandidatePlacement, ...]

    @property
    def unique_content_sha256(self) -> frozenset[str]:
        return frozenset(candidate.content_sha256 for candidate in self.candidates)

    @property
    def placement_identities(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (candidate.content_sha256, candidate.source_placement_id)
            for candidate in self.candidates
        )

    def candidates_for(self, content_sha256: str) -> tuple[CandidatePlacement, ...]:
        return tuple(
            candidate
            for candidate in self.candidates
            if candidate.content_sha256 == content_sha256
        )


def load_candidate_inventory(
    path: Path, *, expected_sha256: str
) -> CandidateInventory:
    inventory_sha = require_file_digest(
        path, expected_sha256, label="Wave 0 candidate inventory"
    )
    document = _load_json(path, label="Wave 0 candidate inventory")
    if document.get("inventory_kind") != CANDIDATE_INVENTORY_KIND:
        raise ReleaseAuthorityError("candidate inventory kind is invalid")
    school_year = document.get("school_year")
    if not isinstance(school_year, str) or _SCHOOL_YEAR.fullmatch(school_year) is None:
        raise ReleaseAuthorityError("candidate inventory school year is invalid")
    manifest_sha = require_sha256(
        document.get("corpus_manifest_sha256"), label="candidate inventory corpus manifest"
    )
    catalog_sha = require_sha256(
        document.get("sealed_catalog_sha256"), label="candidate inventory sealed catalog"
    )
    placement_catalog_sha = require_sha256(
        document.get("placement_catalog_sha256"),
        label="candidate inventory placement catalog",
    )

    selection = document.get("selection")
    if not isinstance(selection, Mapping):
        raise ReleaseAuthorityError("candidate inventory selection is absent")
    if (
        selection.get("external_level") != _EXACT_LEVEL
        or selection.get("source_zone") != _EDUSCOL_ZONE
        or selection.get("media_type") != "application/pdf"
    ):
        raise ReleaseAuthorityError("candidate inventory selection is not exact-grade PDF")
    raw_subjects = selection.get("external_subjects")
    if (
        not isinstance(raw_subjects, list)
        or any(not isinstance(subject, str) for subject in raw_subjects)
        or frozenset(raw_subjects) != _SUBJECTS
    ):
        raise ReleaseAuthorityError("candidate inventory subject selection is invalid")

    raw_candidates = document.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ReleaseAuthorityError("candidate inventory candidates are absent")
    candidates: list[CandidatePlacement] = []
    identities: set[tuple[str, str]] = set()
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            raise ReleaseAuthorityError("candidate inventory entry is malformed")
        sha = require_sha256(raw.get("content_sha256"), label="candidate content")
        source_placement_id = _require_nonempty_string(
            raw.get("source_placement_id"), label="candidate source placement identity"
        )
        identity = (sha, source_placement_id)
        if identity in identities:
            raise ReleaseAuthorityError("candidate placement identity is duplicated")
        identities.add(identity)
        physical_path = _require_nonempty_string(
            raw.get("physical_path"), label="candidate physical path"
        )
        if not physical_path.startswith(_EDUSCOL_ZONE) or not physical_path.lower().endswith(
            ".pdf"
        ):
            raise ReleaseAuthorityError("candidate physical path is outside Eduscol PDF scope")
        external_level = _require_nonempty_string(
            raw.get("external_level"), label="candidate external level"
        )
        if external_level != _EXACT_LEVEL:
            raise ReleaseAuthorityError("candidate is outside the exact-grade 3e scope")
        external_subject = _require_nonempty_string(
            raw.get("external_subject"), label="candidate external subject"
        )
        if external_subject not in _SUBJECTS:
            raise ReleaseAuthorityError("candidate subject is outside the Wave 0 scope")
        external_scope = _require_nonempty_string(
            raw.get("external_scope"), label="candidate external scope"
        )
        expected_scope_subject = (
            "mathematiques" if external_subject == "maths" else external_subject
        )
        if external_scope != f"college/cycle-4/{expected_scope_subject}":
            raise ReleaseAuthorityError("candidate external scope differs from its subject")
        candidates.append(
            CandidatePlacement(
                content_sha256=sha,
                physical_path=physical_path,
                source_url=_require_nonempty_string(
                    raw.get("source_url"), label="candidate source URL"
                ),
                title=_require_nonempty_string(raw.get("title"), label="candidate title"),
                source_placement_id=source_placement_id,
                external_scope=external_scope,
                external_level=external_level,
                external_subject=external_subject,
                external_document_type=_require_nonempty_string(
                    raw.get("external_document_type"),
                    label="candidate external document type",
                ),
                pedagogical_status=_require_nonempty_string(
                    raw.get("pedagogical_status"), label="candidate pedagogical status"
                ),
                physical_currentness_candidate=_require_nonempty_string(
                    raw.get("physical_currentness_candidate"),
                    label="candidate physical currentness",
                ),
                physical_disposition_candidate=_require_nonempty_string(
                    raw.get("physical_disposition_candidate"),
                    label="candidate physical disposition",
                ),
            )
        )

    counts = document.get("counts")
    unique_artifacts = {candidate.content_sha256 for candidate in candidates}
    physical_objects = {
        (candidate.content_sha256, candidate.physical_path) for candidate in candidates
    }
    placements_by_artifact: dict[str, int] = {}
    for candidate in candidates:
        placements_by_artifact[candidate.content_sha256] = (
            placements_by_artifact.get(candidate.content_sha256, 0) + 1
        )
    expected_counts = {
        "unique_artifacts": len(unique_artifacts),
        "placements": len(candidates),
        "physical_objects": len(physical_objects),
        "multi_placement_artifacts": sum(
            count > 1 for count in placements_by_artifact.values()
        ),
    }
    if not isinstance(counts, Mapping) or any(
        counts.get(name) != expected for name, expected in expected_counts.items()
    ):
        raise ReleaseAuthorityError("candidate inventory counts differ from its sets")
    return CandidateInventory(
        sha256=inventory_sha,
        school_year=school_year,
        corpus_manifest_sha256=manifest_sha,
        sealed_catalog_sha256=catalog_sha,
        placement_catalog_sha256=placement_catalog_sha,
        candidates=tuple(candidates),
    )


@dataclass(frozen=True)
class PedagogicalMapping:
    external_level: str
    external_scope: str
    external_subject: str
    nexus_collection: str
    nexus_niveau: Niveau
    nexus_voie: Voie
    nexus_matiere: str
    nexus_statut_enseignement: str


@dataclass(frozen=True)
class ClosedPedagogicalMapping:
    sha256: str
    pedagogical_mappings: tuple[PedagogicalMapping, ...]
    document_types: Mapping[str, TypeDoc]

    def resolve_type_doc(self, external_document_type: str) -> TypeDoc:
        try:
            return self.document_types[external_document_type]
        except KeyError as exc:
            raise ReleaseAuthorityError(
                f"external document type {external_document_type!r} is not governed"
            ) from exc

    def resolve_placement(
        self,
        candidate: CandidatePlacement,
        *,
        collection: str,
    ) -> PedagogicalMapping:
        matches = [
            mapping
            for mapping in self.pedagogical_mappings
            if mapping.external_level == candidate.external_level
            and mapping.external_scope == candidate.external_scope
            and mapping.external_subject == candidate.external_subject
            and mapping.nexus_collection == collection
        ]
        if len(matches) != 1:
            raise ReleaseAuthorityError(
                "candidate has no unique governed external-to-Nexus mapping"
            )
        return matches[0]


def load_pedagogical_mapping(
    path: Path, *, expected_sha256: str
) -> ClosedPedagogicalMapping:
    mapping_sha = require_file_digest(
        path, expected_sha256, label="Wave 0 pedagogical mapping"
    )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ReleaseAuthorityError("Wave 0 pedagogical mapping cannot be read") from exc
    if not isinstance(document, Mapping):
        raise ReleaseAuthorityError("Wave 0 pedagogical mapping must be a mapping")
    if document.get("mapping_kind") != PEDAGOGICAL_MAPPING_KIND:
        raise ReleaseAuthorityError("pedagogical mapping kind is invalid")

    raw_document_types = document.get("document_types")
    if not isinstance(raw_document_types, Mapping) or not raw_document_types:
        raise ReleaseAuthorityError("pedagogical document type mapping is absent")
    document_types: dict[str, TypeDoc] = {}
    for external_type, nexus_type in raw_document_types.items():
        if not isinstance(external_type, str) or not external_type:
            raise ReleaseAuthorityError("external document type is invalid")
        if external_type in document_types:
            raise ReleaseAuthorityError("external document type is duplicated")
        try:
            document_types[external_type] = TypeDoc(str(nexus_type))
        except ValueError as exc:
            raise ReleaseAuthorityError("Nexus document type mapping is invalid") from exc

    raw_mappings = document.get("pedagogical_mappings")
    if not isinstance(raw_mappings, list) or not raw_mappings:
        raise ReleaseAuthorityError("pedagogical mappings are absent")
    mappings: list[PedagogicalMapping] = []
    external_identities: set[tuple[str, str, str, str]] = set()
    for raw in raw_mappings:
        if not isinstance(raw, Mapping):
            raise ReleaseAuthorityError("pedagogical mapping entry is malformed")
        level = _require_nonempty_string(raw.get("external_level"), label="mapping level")
        scope = _require_nonempty_string(raw.get("external_scope"), label="mapping scope")
        subject = _require_nonempty_string(
            raw.get("external_subject"), label="mapping subject"
        )
        collection = _require_nonempty_string(
            raw.get("nexus_collection"), label="mapping collection"
        )
        identity = (level, scope, subject, collection)
        if identity in external_identities:
            raise ReleaseAuthorityError("pedagogical mapping entry is duplicated")
        external_identities.add(identity)
        try:
            niveau = Niveau(str(raw.get("nexus_niveau")))
            voie = Voie(str(raw.get("nexus_voie")))
        except ValueError as exc:
            raise ReleaseAuthorityError("Nexus level or track mapping is invalid") from exc
        mappings.append(
            PedagogicalMapping(
                external_level=level,
                external_scope=scope,
                external_subject=subject,
                nexus_collection=collection,
                nexus_niveau=niveau,
                nexus_voie=voie,
                nexus_matiere=_require_nonempty_string(
                    raw.get("nexus_matiere"), label="mapping Nexus subject"
                ),
                nexus_statut_enseignement=_require_nonempty_string(
                    raw.get("nexus_statut_enseignement"),
                    label="mapping teaching status",
                ),
            )
        )
    return ClosedPedagogicalMapping(
        sha256=mapping_sha,
        pedagogical_mappings=tuple(mappings),
        document_types=document_types,
    )


@dataclass(frozen=True)
class ReleaseArtifactAuthority:
    collection: str
    content_sha256: str
    source_path: str
    expected_placement_ids: frozenset[str]
    programme_version: str
    profile_version: str
    profile_fingerprint: str
    profile_manifest_digest: str


@dataclass(frozen=True)
class Wave0ReleaseAuthority:
    sha256: str
    release_id: str
    school_year: str
    corpus_manifest_sha256: str
    sealed_catalog_sha256: str
    placement_catalog_sha256: str
    candidate_inventory_sha256: str
    currentness_evidence_sha256: str
    authorities: Mapping[str, str]
    models: Mapping[str, object]
    expected_counts: Mapping[str, int]
    artifacts: Mapping[tuple[str, str], ReleaseArtifactAuthority]

    def artifact_for(
        self, *, collection: str, content_sha256: str
    ) -> ReleaseArtifactAuthority | None:
        return self.artifacts.get((collection, content_sha256))

    def is_allowed(
        self,
        *,
        collection: str,
        content_sha256: str,
        source_placement_id: str,
    ) -> bool:
        artifact = self.artifact_for(
            collection=collection, content_sha256=content_sha256
        )
        return artifact is not None and source_placement_id in artifact.expected_placement_ids


def load_subject_release(
    path: Path,
    *,
    expected_sha256: str,
    candidate_inventory: CandidateInventory,
    expected_currentness_evidence_sha256: str,
) -> Wave0ReleaseAuthority:
    release_sha = require_file_digest(path, expected_sha256, label="Wave 0 release manifest")
    document = _load_json(path, label="Wave 0 release manifest")
    if document.get("release_kind") != SUBJECT_RELEASE_KIND:
        raise ReleaseAuthorityError("release manifest kind is invalid")
    if set(document) != {
        "release_kind",
        "release_id",
        "school_year",
        "collection",
        "programme_version",
        "authorities",
        "profile",
        "models",
        "expected_counts",
        "artifacts",
    }:
        raise ReleaseAuthorityError("release manifest fields are not exact")
    release_id = _require_nonempty_string(
        document.get("release_id"), label="release identity"
    )
    if document.get("school_year") != candidate_inventory.school_year:
        raise ReleaseAuthorityError("release school year differs from candidate inventory")
    authorities = document.get("authorities")
    if not isinstance(authorities, Mapping):
        raise ReleaseAuthorityError("release authorities are absent")
    bindings = (
        ("corpus_manifest_sha256", candidate_inventory.corpus_manifest_sha256),
        ("sealed_catalog_sha256", candidate_inventory.sealed_catalog_sha256),
        ("placement_catalog_sha256", candidate_inventory.placement_catalog_sha256),
        ("candidate_inventory_sha256", candidate_inventory.sha256),
        ("currentness_evidence_sha256", expected_currentness_evidence_sha256),
    )
    for field, expected in bindings:
        if authorities.get(field) != expected:
            raise ReleaseAuthorityError(f"release {field} differs from its authority")
    authority_names = {
        "corpus_manifest_sha256",
        "sealed_catalog_sha256",
        "placement_catalog_sha256",
        "candidate_inventory_sha256",
        "currentness_evidence_sha256",
        "pii_evidence_sha256",
        "pii_policy_sha256",
        "rights_registry_sha256",
    }
    if set(authorities) != authority_names:
        raise ReleaseAuthorityError("release authorities fields are not exact")
    normalized_authorities = {
        name: require_sha256(authorities.get(name), label=f"release authority {name}")
        for name in sorted(authority_names)
    }
    models = _validate_models(document.get("models"), label="release models")

    collection = _require_nonempty_string(
        document.get("collection"), label="release collection"
    )
    programme_version = _require_nonempty_string(
        document.get("programme_version"), label="release programme version"
    )
    raw_profile = document.get("profile")
    if not isinstance(raw_profile, Mapping) or set(raw_profile) != {
        "version",
        "fingerprint",
        "manifest_digest",
    }:
        raise ReleaseAuthorityError("release profile fields are not exact")
    profile_version = _require_nonempty_string(
        raw_profile.get("version"), label="release profile version"
    )
    profile_fingerprint = require_sha256(
        raw_profile.get("fingerprint"), label="release profile fingerprint"
    )
    profile_manifest_digest = require_sha256(
        raw_profile.get("manifest_digest"), label="release profile manifest digest"
    )
    raw_artifacts = document.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise ReleaseAuthorityError("release expected artifacts are absent")
    inventory_by_identity = {
        (candidate.content_sha256, candidate.source_placement_id): candidate
        for candidate in candidate_inventory.candidates
    }
    artifacts: dict[tuple[str, str], ReleaseArtifactAuthority] = {}
    consumed_placements: set[tuple[str, str]] = set()
    chunk_ids: set[str] = set()
    actual_chunk_count = 0
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, Mapping):
            raise ReleaseAuthorityError("release artifact is malformed")
        sha = require_sha256(raw_artifact.get("content_sha256"), label="release content")
        source_path = _require_nonempty_string(
            raw_artifact.get("source_path"), label="release source path"
        )
        raw_placements = raw_artifact.get("placements")
        if not isinstance(raw_placements, list) or not raw_placements:
            raise ReleaseAuthorityError("release placement set is invalid")
        raw_placement_ids: list[str] = []
        for raw_placement in raw_placements:
            if not isinstance(raw_placement, Mapping):
                raise ReleaseAuthorityError("release placement is malformed")
            if raw_placement.get("collection") != collection:
                raise ReleaseAuthorityError("release placement collection differs")
            raw_placement_ids.append(
                _require_nonempty_string(
                    raw_placement.get("source_placement_id"),
                    label="release source placement identity",
                )
            )
        placement_ids = frozenset(raw_placement_ids)
        if len(placement_ids) != len(raw_placement_ids):
            raise ReleaseAuthorityError("release placement identity is duplicated")
        key = (collection, sha)
        if key in artifacts:
            raise ReleaseAuthorityError("release artifact is duplicated")
        for placement_id in placement_ids:
            inventory_candidate = inventory_by_identity.get((sha, placement_id))
            if inventory_candidate is None:
                raise ReleaseAuthorityError(
                    "release placement is absent from the candidate inventory"
                )
            if inventory_candidate.physical_path != source_path:
                raise ReleaseAuthorityError(
                    "release source path differs from the candidate inventory"
                )
            identity = (sha, placement_id)
            if identity in consumed_placements:
                raise ReleaseAuthorityError(
                    "candidate placement is assigned more than once"
                )
            consumed_placements.add(identity)
        artifacts[key] = ReleaseArtifactAuthority(
            collection=collection,
            content_sha256=sha,
            source_path=source_path,
            expected_placement_ids=placement_ids,
            programme_version=programme_version,
            profile_version=profile_version,
            profile_fingerprint=profile_fingerprint,
            profile_manifest_digest=profile_manifest_digest,
        )
        raw_chunks = raw_artifact.get("chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            raise ReleaseAuthorityError("release chunk set is invalid")
        for raw_chunk in raw_chunks:
            if not isinstance(raw_chunk, Mapping):
                raise ReleaseAuthorityError("release chunk is malformed")
            chunk_id = require_sha256(
                raw_chunk.get("chunk_id"), label="release chunk identity"
            )
            if chunk_id in chunk_ids:
                raise ReleaseAuthorityError("release chunk identity is duplicated")
            chunk_ids.add(chunk_id)
        actual_chunk_count += len(raw_chunks)
    expected_counts = _validate_expected_counts(
        document.get("expected_counts"),
        actual={
            "artifacts": len(artifacts),
            "placements": len(consumed_placements),
            "chunks": actual_chunk_count,
        },
        label="release expected counts",
    )
    return Wave0ReleaseAuthority(
        sha256=release_sha,
        release_id=release_id,
        school_year=candidate_inventory.school_year,
        corpus_manifest_sha256=candidate_inventory.corpus_manifest_sha256,
        sealed_catalog_sha256=candidate_inventory.sealed_catalog_sha256,
        placement_catalog_sha256=candidate_inventory.placement_catalog_sha256,
        candidate_inventory_sha256=candidate_inventory.sha256,
        currentness_evidence_sha256=expected_currentness_evidence_sha256,
        authorities=normalized_authorities,
        models=models,
        expected_counts=expected_counts,
        artifacts=artifacts,
    )


# Nom historique interne conservé comme alias de migration. Les deux noms
# chargent le même manifest matière strict, jamais l'agrégat.
load_release_authority = load_subject_release


def _validate_models(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != {"embedding", "reranker"}:
        raise ReleaseAuthorityError(f"{label} fields are not exact")
    embedding = value.get("embedding")
    reranker = value.get("reranker")
    if not isinstance(embedding, Mapping) or set(embedding) != {
        "model_id",
        "inventory_sha256",
        "dimension",
    }:
        raise ReleaseAuthorityError(f"{label} embedding fields are not exact")
    if not isinstance(reranker, Mapping) or set(reranker) != {
        "model_id",
        "inventory_sha256",
    }:
        raise ReleaseAuthorityError(f"{label} reranker fields are not exact")
    _require_nonempty_string(embedding.get("model_id"), label=f"{label} embedding model")
    require_sha256(
        embedding.get("inventory_sha256"), label=f"{label} embedding inventory"
    )
    dimension = embedding.get("dimension")
    if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
        raise ReleaseAuthorityError(f"{label} embedding dimension is invalid")
    _require_nonempty_string(reranker.get("model_id"), label=f"{label} reranker model")
    require_sha256(
        reranker.get("inventory_sha256"), label=f"{label} reranker inventory"
    )
    return {
        "embedding": dict(embedding),
        "reranker": dict(reranker),
    }


def _validate_expected_counts(
    value: object, *, actual: Mapping[str, int], label: str
) -> Mapping[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(actual):
        raise ReleaseAuthorityError(f"{label} fields are not exact")
    for name, expected in actual.items():
        if value.get(name) != expected:
            raise ReleaseAuthorityError(f"{label} differ from release sets")
    return dict(actual)


def load_aggregate_release(
    path: Path,
    *,
    expected_sha256: str,
    candidate_inventory: CandidateInventory,
    expected_currentness_evidence_sha256: str,
) -> Wave0ReleaseAuthority:
    """Charge l'agrégat et fusionne ses manifests matière scellés."""
    aggregate_sha = require_file_digest(
        path, expected_sha256, label="Wave 0 aggregate release manifest"
    )
    document = _load_json(path, label="Wave 0 aggregate release manifest")
    if document.get("release_kind") != AGGREGATE_RELEASE_KIND:
        raise ReleaseAuthorityError("aggregate release manifest kind is invalid")
    if set(document) != {
        "release_kind",
        "release_id",
        "school_year",
        "authorities",
        "models",
        "expected_counts",
        "subjects",
    }:
        raise ReleaseAuthorityError("aggregate release manifest fields are not exact")
    release_id = _require_nonempty_string(
        document.get("release_id"), label="aggregate release identity"
    )
    if document.get("school_year") != candidate_inventory.school_year:
        raise ReleaseAuthorityError(
            "aggregate release school year differs from candidate inventory"
        )
    authorities = document.get("authorities")
    if not isinstance(authorities, Mapping):
        raise ReleaseAuthorityError("aggregate release authorities are absent")
    models = _validate_models(document.get("models"), label="aggregate release models")
    raw_subjects = document.get("subjects")
    if not isinstance(raw_subjects, list) or not raw_subjects:
        raise ReleaseAuthorityError("aggregate release subjects are absent")

    aggregate_parent = path.resolve().parent
    merged_artifacts: dict[tuple[str, str], ReleaseArtifactAuthority] = {}
    seen_collections: set[str] = set()
    seen_content: set[str] = set()
    seen_placements: set[str] = set()
    total_chunks = 0
    normalized_authorities: Mapping[str, str] | None = None
    for raw_subject in raw_subjects:
        if not isinstance(raw_subject, Mapping) or set(raw_subject) != {
            "collection",
            "path",
            "sha256",
        }:
            raise ReleaseAuthorityError("aggregate release subject is malformed")
        collection = _require_nonempty_string(
            raw_subject.get("collection"), label="aggregate subject collection"
        )
        if collection in seen_collections:
            raise ReleaseAuthorityError("aggregate release collection is duplicated")
        seen_collections.add(collection)
        relative_path = Path(
            _require_nonempty_string(
                raw_subject.get("path"), label="aggregate subject path"
            )
        )
        if relative_path.is_absolute():
            raise ReleaseAuthorityError("aggregate subject path must be relative")
        subject_path = (aggregate_parent / relative_path).resolve()
        if not subject_path.is_relative_to(aggregate_parent):
            raise ReleaseAuthorityError("aggregate subject path escapes its release directory")
        subject = load_subject_release(
            subject_path,
            expected_sha256=require_sha256(
                raw_subject.get("sha256"), label="aggregate subject manifest"
            ),
            candidate_inventory=candidate_inventory,
            expected_currentness_evidence_sha256=expected_currentness_evidence_sha256,
        )
        subject_collections = {subject_collection for subject_collection, _ in subject.artifacts}
        if subject_collections != {collection}:
            raise ReleaseAuthorityError(
                "aggregate subject collection differs from its subject manifest"
            )
        if normalized_authorities is None:
            normalized_authorities = subject.authorities
        if dict(subject.authorities) != dict(authorities):
            raise ReleaseAuthorityError(
                "aggregate authorities differ from a subject manifest"
            )
        if dict(subject.models) != dict(models):
            raise ReleaseAuthorityError("aggregate models differ from a subject manifest")
        for key, artifact in subject.artifacts.items():
            if key in merged_artifacts or artifact.content_sha256 in seen_content:
                raise ReleaseAuthorityError("aggregate release artifact is duplicated")
            seen_content.add(artifact.content_sha256)
            overlapping = seen_placements & set(artifact.expected_placement_ids)
            if overlapping:
                raise ReleaseAuthorityError("aggregate release placement is duplicated")
            seen_placements.update(artifact.expected_placement_ids)
            merged_artifacts[key] = artifact
        total_chunks += subject.expected_counts["chunks"]
    if normalized_authorities is None:
        raise ReleaseAuthorityError("aggregate release has no subject authority")
    aggregate_counts = _validate_expected_counts(
        document.get("expected_counts"),
        actual={
            "artifacts": len(merged_artifacts),
            "placements": len(seen_placements),
            "chunks": total_chunks,
        },
        label="aggregate expected counts",
    )
    return Wave0ReleaseAuthority(
        sha256=aggregate_sha,
        release_id=release_id,
        school_year=candidate_inventory.school_year,
        corpus_manifest_sha256=candidate_inventory.corpus_manifest_sha256,
        sealed_catalog_sha256=candidate_inventory.sealed_catalog_sha256,
        placement_catalog_sha256=candidate_inventory.placement_catalog_sha256,
        candidate_inventory_sha256=candidate_inventory.sha256,
        currentness_evidence_sha256=expected_currentness_evidence_sha256,
        authorities=normalized_authorities,
        models=models,
        expected_counts=aggregate_counts,
        artifacts=merged_artifacts,
    )


__all__ = [
    "CANDIDATE_INVENTORY_KIND",
    "AGGREGATE_RELEASE_KIND",
    "PEDAGOGICAL_MAPPING_KIND",
    "SUBJECT_RELEASE_KIND",
    "CandidateInventory",
    "CandidatePlacement",
    "ClosedPedagogicalMapping",
    "PedagogicalMapping",
    "ReleaseArtifactAuthority",
    "ReleaseAuthorityError",
    "Wave0ReleaseAuthority",
    "file_sha256",
    "load_candidate_inventory",
    "load_aggregate_release",
    "load_pedagogical_mapping",
    "load_release_authority",
    "load_subject_release",
    "require_file_digest",
    "require_sha256",
]
