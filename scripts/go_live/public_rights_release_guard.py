"""Porte du producteur de release publique étudiante successeur.

Le droit historique ``officiel_public`` ne participe jamais à cette décision.
Avant toute écriture, la topologie V2 produite en mémoire doit correspondre
exactement aux SHA APPROVE_PUBLIC du pack délégué vérifié sur les PDF du miroir.
"""

from __future__ import annotations

import json
import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

CFTR_SHA256 = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HISTORICAL_IDS = frozenset({
    "production-profile-gate-2026-2027-v4",
    "production-profile-gate-2026-2027-v5-hggsp",
})


class PublicRightsReleaseError(ValueError):
    """La candidate ne peut pas devenir une release publique gouvernée."""


def _document(documents: Mapping[Path, bytes], path: Path) -> dict:
    raw = documents.get(path)
    if not isinstance(raw, bytes):
        raise PublicRightsReleaseError(f"RELEASE_DOCUMENT_MISSING:{path.name}")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise PublicRightsReleaseError(f"RELEASE_DOCUMENT_INVALID:{path.name}") from error
    if not isinstance(value, dict):
        raise PublicRightsReleaseError(f"RELEASE_DOCUMENT_INVALID:{path.name}")
    return value


def _release_documents(documents: Mapping[Path, bytes]) -> tuple[dict, dict, list[dict]]:
    aggregates = [path for path in documents if path.name == "production-profile-gate.release.json"]
    if len(aggregates) != 1:
        raise PublicRightsReleaseError("RELEASE_AGGREGATE_AMBIGUOUS")
    aggregate_path = aggregates[0]
    aggregate = _document(documents, aggregate_path)
    root = aggregate_path.parent
    registry_ref = aggregate.get("artifact_registry")
    if not isinstance(registry_ref, dict) or registry_ref.get("path") != "artifacts.release.json":
        raise PublicRightsReleaseError("RELEASE_REGISTRY_REF_INVALID")
    registry = _document(documents, root / "artifacts.release.json")
    subject_refs = aggregate.get("subjects")
    if not isinstance(subject_refs, list) or not subject_refs:
        raise PublicRightsReleaseError("RELEASE_SUBJECTS_MISSING")
    subjects = []
    for ref in subject_refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise PublicRightsReleaseError("RELEASE_SUBJECT_REF_INVALID")
        relative = Path(ref["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "subjects":
            raise PublicRightsReleaseError("RELEASE_SUBJECT_REF_INVALID")
        subject = _document(documents, root / relative)
        if subject.get("collection") != ref.get("collection") and "collection" in ref:
            raise PublicRightsReleaseError("RELEASE_SUBJECT_COLLECTION_MISMATCH")
        subjects.append(subject)
    return aggregate, registry, subjects


def _validate_public_document_bindings(documents: Mapping[Path, bytes], aggregate: dict,
                                       subjects: list[dict]) -> None:
    aggregate_path = next(path for path in documents
                          if path.name == "production-profile-gate.release.json")
    root = aggregate_path.parent
    registry_raw = documents[root / "artifacts.release.json"]
    registry_sha = hashlib.sha256(registry_raw).hexdigest()
    registry_ref = aggregate["artifact_registry"]
    if registry_ref.get("sha256") != registry_sha:
        raise PublicRightsReleaseError("RELEASE_REGISTRY_DIGEST_MISMATCH")
    for ref, subject in zip(aggregate["subjects"], subjects, strict=True):
        raw = documents[root / ref["path"]]
        if ref.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise PublicRightsReleaseError("RELEASE_SUBJECT_DIGEST_MISMATCH")
        subject_registry = subject.get("artifact_registry")
        if (not isinstance(subject_registry, dict)
                or subject_registry.get("path") != "../artifacts.release.json"
                or subject_registry.get("sha256") != registry_sha):
            raise PublicRightsReleaseError("RELEASE_SUBJECT_REGISTRY_MISMATCH")
    release_registry = _document(documents, root.parent / "release-registry.json")
    releases = release_registry.get("releases")
    if (not isinstance(releases, list) or len(releases) != 1
            or not isinstance(releases[0], dict)
            or releases[0].get("release_id") != aggregate.get("release_id")
            or releases[0].get("manifest_path") != (
                Path(root.name) / aggregate_path.name).as_posix()
            or releases[0].get("expected_manifest_sha256") != hashlib.sha256(
                documents[aggregate_path]).hexdigest()
            or releases[0].get("release_kind") != "MULTILEVEL_AGGREGATE_RELEASE_V2"
            or releases[0].get("collections") != sorted(s["collection"] for s in subjects)):
        raise PublicRightsReleaseError("RELEASE_REGISTRY_BINDING_MISMATCH")


def require_public_release_rights(
    documents: Mapping[Path, bytes], *, repository_root: Path,
    source_mirror_root: Path | None, expected_head: str | None,
    gate_runner: Callable[..., dict] | None = None,
) -> dict[str, Any]:
    """Bloque tout contenu public absent du pack scellé avant écriture disque."""
    aggregate, registry, subjects = _release_documents(documents)
    placements = [p for subject in subjects for p in subject.get("placements", [])]
    if not placements or not all(isinstance(p, dict) for p in placements):
        raise PublicRightsReleaseError("RELEASE_PLACEMENTS_INVALID")
    public = [p for p in placements if p.get("visibility") == "public"]
    if not public:
        return {"PUBLIC_RIGHTS_GATE_APPLICABLE": False}
    if len(public) != len(placements):
        raise PublicRightsReleaseError("MIXED_PUBLIC_INTERNAL_RELEASE")
    # Le pack machine prépare un candidat. Tant que l'approbation d'autorité
    # exacte #300 n'est pas attestée par un reçu externe, il ne peut jamais
    # sortir de ce producteur sous statut publiable, même si tous les SHA sont
    # positifs. Les trois statuts explicites évitent un défaut permissif.
    if (aggregate.get("promotion_status") != "NOT_PROMOTABLE"
            or aggregate.get("activation_status") != "NO_PRODUCTION_ACTIVATION"
            or aggregate.get("review_status") != "PRE_REVIEW"):
        raise PublicRightsReleaseError("FINAL_AUTHORITY_APPROVAL_REQUIRED")
    _validate_public_document_bindings(documents, aggregate, subjects)
    if aggregate.get("release_id") in HISTORICAL_IDS:
        raise PublicRightsReleaseError("HISTORICAL_RELEASE_ID_FORBIDDEN")
    if (source_mirror_root is None or not source_mirror_root.is_dir()
            or not isinstance(expected_head, str) or GIT_SHA_RE.fullmatch(expected_head) is None):
        raise PublicRightsReleaseError("SOURCE_MIRROR_AND_HEAD_REQUIRED")
    placement_shas = {p.get("artifact_id") for p in placements}
    artifact_rows = registry.get("artifacts")
    if not isinstance(artifact_rows, list) or not artifact_rows:
        raise PublicRightsReleaseError("RELEASE_ARTIFACTS_INVALID")
    artifact_shas = {a.get("content_sha256") for a in artifact_rows if isinstance(a, dict)}
    if (len(artifact_shas) != len(artifact_rows) or not all(
        isinstance(sha, str) and SHA_RE.fullmatch(sha) for sha in artifact_shas
    ) or any(not isinstance(artifact, dict)
             or artifact.get("artifact_id") != artifact.get("content_sha256")
             for artifact in artifact_rows)
            or placement_shas != artifact_shas):
        raise PublicRightsReleaseError("PUBLIC_RELEASE_CONTENT_SET_INVALID")
    if CFTR_SHA256 in placement_shas:
        raise PublicRightsReleaseError("PUBLIC_SHA_NOT_APPROVED:CFTR")
    if gate_runner is None:
        from check_delegated_student_rights_gate import check_gate

        gate_runner = check_gate
    gate = gate_runner(root=repository_root, source_mirror_root=source_mirror_root,
                       expected_head=expected_head)
    if not isinstance(gate, dict) or gate.get("DELEGATED_RIGHTS_ADJUDICATION_PASS") is not True:
        raise PublicRightsReleaseError("DELEGATED_GATE_NOT_PASS")
    evidence_pack_sha = gate.get("EVIDENCE_PACK_SHA256")
    if not isinstance(evidence_pack_sha, str) or SHA_RE.fullmatch(evidence_pack_sha) is None:
        raise PublicRightsReleaseError("EVIDENCE_PACK_DIGEST_MISSING")
    approved_rows = gate.get("APPROVED_CONTENT_SHA256")
    if not isinstance(approved_rows, list) or not all(
        isinstance(sha, str) and SHA_RE.fullmatch(sha) for sha in approved_rows
    ) or len(approved_rows) != len(set(approved_rows)):
        raise PublicRightsReleaseError("APPROVED_SET_INVALID")
    approved = set(approved_rows)
    if placement_shas - approved:
        raise PublicRightsReleaseError("PUBLIC_SHA_NOT_APPROVED")
    if approved - placement_shas:
        raise PublicRightsReleaseError("APPROVED_SHA_NOT_IN_RELEASE")
    source_placements = gate.get("APPROVED_SOURCE_PLACEMENTS")
    if not isinstance(source_placements, dict) or set(source_placements) != approved:
        raise PublicRightsReleaseError("PUBLIC_RELEASE_SOURCE_TOPOLOGY_MISSING")
    actual_placements: Counter[tuple[str, str]] = Counter()
    for subject in subjects:
        collection = subject.get("collection")
        if not isinstance(collection, str) or not collection:
            raise PublicRightsReleaseError("PUBLIC_RELEASE_COLLECTION_SCOPE_INVALID")
        for placement in subject["placements"]:
            if placement.get("collection") != collection:
                raise PublicRightsReleaseError("PUBLIC_RELEASE_COLLECTION_SCOPE_INVALID")
            actual_placements[(placement["artifact_id"], collection)] += 1
    expected_placements: Counter[tuple[str, str]] = Counter()
    for sha, collections in source_placements.items():
        if not isinstance(collections, dict) or not collections:
            raise PublicRightsReleaseError("PUBLIC_RELEASE_SOURCE_TOPOLOGY_MISSING")
        for collection, count in collections.items():
            if not isinstance(collection, str) or type(count) is not int or count < 1:
                raise PublicRightsReleaseError("PUBLIC_RELEASE_SOURCE_TOPOLOGY_MISSING")
            expected_placements[(sha, collection)] = count
    if actual_placements != expected_placements:
        raise PublicRightsReleaseError("PUBLIC_RELEASE_SOURCE_TOPOLOGY_MISMATCH")
    source_chunks = gate.get("APPROVED_SOURCE_CHUNKS_SHA256")
    if not isinstance(source_chunks, dict) or set(source_chunks) != approved:
        raise PublicRightsReleaseError("PUBLIC_RELEASE_SOURCE_CHUNKS_MISSING")
    for artifact in artifact_rows:
        sha = artifact["content_sha256"]
        chunks = artifact.get("chunks")
        if not isinstance(chunks, list) or not chunks or not isinstance(
            source_chunks.get(sha), str
        ) or SHA_RE.fullmatch(source_chunks[sha]) is None:
            raise PublicRightsReleaseError("PUBLIC_RELEASE_SOURCE_CHUNKS_MISSING")
        raw = (json.dumps(chunks, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False) + "\n").encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != source_chunks[sha]:
            raise PublicRightsReleaseError("PUBLIC_RELEASE_SOURCE_CHUNKS_MISMATCH")
    chunks = [chunk for artifact in artifact_rows for chunk in artifact.get("chunks", [])]
    observed = {
        "collections": len(subjects), "artifacts": len(artifact_shas),
        "placements": len(placements), "chunks": len(chunks),
    }
    declared = aggregate.get("expected_counts")
    if not isinstance(declared, dict) or any(declared.get(key) != observed[value] for key, value in (
        ("subjects", "collections"), ("unique_artifacts", "artifacts"),
        ("placements", "placements"), ("unique_chunks", "chunks"),
    )):
        raise PublicRightsReleaseError("PUBLIC_RELEASE_COUNTS_MISMATCH")
    population = gate.get("FINAL_POPULATION")
    if not isinstance(population, dict) or any(population.get(key) != value
                                               for key, value in observed.items()):
        raise PublicRightsReleaseError("PUBLIC_RELEASE_COUNTS_MISMATCH")
    return {
        "PUBLIC_RIGHTS_GATE_APPLICABLE": True,
        "PUBLIC_RIGHTS_GATE_PASS": True,
        "EVIDENCE_PACK_SHA256": evidence_pack_sha,
        "APPROVED_CONTENT_SHA256": sorted(approved),
        "FINAL_POPULATION": observed,
    }
