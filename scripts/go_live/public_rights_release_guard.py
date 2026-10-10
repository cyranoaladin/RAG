"""Porte du producteur de release publique étudiante successeur.

Le droit historique ``officiel_public`` ne participe jamais à cette décision.
Avant toute écriture, la topologie V2 produite en mémoire doit correspondre
exactement aux SHA APPROVE_PUBLIC du pack délégué vérifié sur les PDF du miroir.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from nexus_contracts.ingestion import (
    CollectionProfile,
    collection_profile_fingerprint,
    profile_manifest_fingerprint,
)
from nexus_contracts.profile_manifest import strict_yaml_mapping

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


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _canonical_pack(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def _candidate_registries(
    documents: Mapping[Path, bytes], aggregate: dict, subjects: list[dict],
    artifact_rows: list[dict], evidence_sha: str,
) -> None:
    """Les registres sont une proposition non activable liée aux SHA du candidat."""
    root = next(p for p in documents if p.name == "production-profile-gate.release.json").parent
    authority = aggregate.get("authorities")
    if not isinstance(authority, dict) or authority.get("delegated_evidence_pack_sha256") != evidence_sha:
        raise PublicRightsReleaseError("PUBLIC_AUTHORITY_BINDING_INVALID")
    labels = {
        "public_profiles.json": ("public_profile_registry_sha256", "NEXUS_STUDENT_PUBLIC_SCOPE_CANDIDATES_V1",
                                 {"kind", "release_id", "status", "entries"}),
        "public_rights_registry.json": ("public_rights_registry_sha256", "NEXUS_STUDENT_PUBLIC_DERIVATIVE_RIGHTS_REGISTRY_V1",
                                        {"kind", "release_id", "status", "rights_authority_sha256",
                                         "evidence_pack_sha256", "authorized_use", "full_pdf_redistribution_allowed",
                                         "answer_generation_allowed", "entries"}),
        "public_pii_registry.json": ("public_pii_registry_sha256", "NEXUS_STUDENT_PUBLIC_DERIVATIVE_PII_REGISTRY_V1",
                                     {"kind", "release_id", "status", "evidence_pack_sha256", "entries"}),
    }
    registries = {}
    for name, (digest_key, kind, exact_keys) in labels.items():
        path = root / name
        value = _document(documents, path)
        raw = documents[path]
        if (set(value) != exact_keys or raw != _canonical(value)
                or authority.get(digest_key) != _sha(raw)
                or value.get("kind") != kind
                or value.get("release_id") != aggregate.get("release_id")
                or value.get("status") != "CANDIDATE_NOT_AUTHORIZED"):
            raise PublicRightsReleaseError("PUBLIC_CANDIDATE_REGISTRY_BINDING_INVALID")
        registries[name] = value
    if any(subject.get("authorities") != authority for subject in subjects):
        raise PublicRightsReleaseError("PUBLIC_SUBJECT_AUTHORITY_BINDING_INVALID")
    profiles = registries["public_profiles.json"]["entries"]
    if (not isinstance(profiles, list) or len(profiles) != 11
            or len({row.get("collection") for row in profiles if isinstance(row, dict)}) != 11):
        raise PublicRightsReleaseError("PUBLIC_PROFILE_REGISTRY_INVALID")
    profile_by_collection = {row["collection"]: row for row in profiles}
    for subject in subjects:
        collection = subject["collection"]
        row = profile_by_collection.get(collection)
        if not isinstance(row, dict):
            raise PublicRightsReleaseError("PUBLIC_PROFILE_REGISTRY_INVALID")
        scope = row.get("scope")
        profile = subject.get("profile")
        if (set(row) != {"collection", "scope", "profile_fingerprint",
                         "source_subject_sha256", "source_profile_fingerprint"}
                or not isinstance(scope, dict) or scope.get("collection") != collection
                or scope.get("visibility") != "public"
                or scope.get("audience") != ["libre", "aefe"]
                or not isinstance(profile, dict)
                or row.get("profile_fingerprint") != _sha(_canonical(scope))
                or profile.get("fingerprint") != row["profile_fingerprint"]
                or profile.get("manifest_digest") != authority["public_profile_registry_sha256"]
                or not isinstance(row.get("source_subject_sha256"), str)
                or SHA_RE.fullmatch(row["source_subject_sha256"]) is None
                or not isinstance(row.get("source_profile_fingerprint"), str)
                or SHA_RE.fullmatch(row["source_profile_fingerprint"]) is None):
            raise PublicRightsReleaseError("PUBLIC_PROFILE_REGISTRY_INVALID")
        for placement in subject["placements"]:
            if any(placement.get(key) != scope.get(key) for key in (
                "tenant", "niveau", "voie", "matiere", "statut_enseignement",
                "candidat", "school_year", "programme_version", "collection", "visibility",
            )):
                raise PublicRightsReleaseError("PUBLIC_PROFILE_SCOPE_MISMATCH")
    artifacts_by_sha = {row["content_sha256"]: row for row in artifact_rows}
    rights = registries["public_rights_registry.json"]
    if (rights.get("evidence_pack_sha256") != evidence_sha
            or rights.get("rights_authority_sha256") != authority.get("rights_authority_sha256")
            or rights.get("authorized_use") != "student_retrieval_excerpt_only"
            or rights.get("full_pdf_redistribution_allowed") is not False
            or rights.get("answer_generation_allowed") is not False):
        raise PublicRightsReleaseError("PUBLIC_RIGHTS_REGISTRY_INVALID")
    pii = registries["public_pii_registry.json"]
    if pii.get("evidence_pack_sha256") != evidence_sha:
        raise PublicRightsReleaseError("PUBLIC_PII_REGISTRY_INVALID")
    entry_fields = {
        "RIGHTS": {"content_sha256", "source_pdf_sha256",
                   "derivative_receipt_sha256", "citation_sha256"},
        "PII": {"content_sha256", "source_pdf_sha256",
                "derivative_receipt_sha256", "pii_gate_status"},
    }
    for name, entries in (("RIGHTS", rights.get("entries")), ("PII", pii.get("entries"))):
        if (not isinstance(entries, list) or len(entries) != 253
                or not all(isinstance(row, dict) and set(row) == entry_fields[name]
                           for row in entries)):
            raise PublicRightsReleaseError(f"PUBLIC_{name}_REGISTRY_INVALID")
        by_sha = {row.get("content_sha256"): row for row in entries}
        if len(by_sha) != 253 or set(by_sha) != set(artifacts_by_sha):
            raise PublicRightsReleaseError(f"PUBLIC_{name}_REGISTRY_INVALID")
        for sha, artifact in artifacts_by_sha.items():
            row = by_sha[sha]
            if (row.get("source_pdf_sha256") != artifact.get("source_pdf_sha256")
                    or row.get("derivative_receipt_sha256")
                    != artifact.get("derivative_receipt_sha256")):
                raise PublicRightsReleaseError(f"PUBLIC_{name}_REGISTRY_INVALID")
            if name == "RIGHTS" and row.get("citation_sha256") != _sha(_canonical(artifact.get("citation"))):
                raise PublicRightsReleaseError("PUBLIC_RIGHTS_REGISTRY_INVALID")
            if name == "PII" and row.get("pii_gate_status") != "PASS_BY_PR300_FULL_DOCUMENT_GATE":
                raise PublicRightsReleaseError("PUBLIC_PII_REGISTRY_INVALID")


def _source_scope_bindings(
    documents: Mapping[Path, bytes], subjects: list[dict],
    manifest_by_sha: dict[str, dict], index: dict, repository_root: Path,
) -> None:
    """Lie chaque scope public aux placements scellés V4/V5 de #300."""
    root = next(p for p in documents if p.name == "production-profile-gate.release.json").parent
    profiles = _document(documents, root / "public_profiles.json")["entries"]
    profile_by_collection = {row["collection"]: row for row in profiles}
    approved_sources = {
        (sha, collection): entry["source_content_sha256"]
        for sha, entry in manifest_by_sha.items()
        for collection in entry["collections"]
    }
    source_subjects: dict[str, tuple[dict, str]] = {}
    for population in index.get("source_population", []):
        for ref in population.get("subjects", []):
            relative = Path(ref.get("path", ""))
            path = (repository_root / relative).resolve()
            if (relative.is_absolute() or ".." in relative.parts
                    or not path.is_relative_to(repository_root.resolve())):
                raise PublicRightsReleaseError("PUBLIC_SOURCE_SUBJECT_PATH_INVALID")
            try:
                raw = path.read_bytes()
                source = json.loads(raw)
            except (OSError, ValueError) as error:
                raise PublicRightsReleaseError("PUBLIC_SOURCE_SUBJECT_MISSING") from error
            if _sha(raw) != ref.get("sha256") or not isinstance(source, dict):
                raise PublicRightsReleaseError("PUBLIC_SOURCE_SUBJECT_DIGEST_MISMATCH")
            collection = source.get("collection")
            if collection in source_subjects:
                raise PublicRightsReleaseError("PUBLIC_SOURCE_SUBJECT_DUPLICATE")
            source_subjects[collection] = (source, ref["sha256"])
    if set(source_subjects) != {subject["collection"] for subject in subjects}:
        raise PublicRightsReleaseError("PUBLIC_SOURCE_SUBJECT_SET_MISMATCH")
    profile_root = repository_root / "services/rag-engine/configs/ingestion_profiles"
    profile_manifest_path = profile_root / "ingestion_manifest_v3_livraison_315.yml"
    try:
        profile_manifest = strict_yaml_mapping(
            profile_manifest_path.read_bytes(), source=profile_manifest_path.name,
        )
        profile_manifest_sha = profile_manifest_fingerprint(profile_manifest)
        manifest_rows = profile_manifest["profiles"]
        manifest_by_collection = {
            row["collection"]: row for row in manifest_rows
        }
        if (len(manifest_rows) != 11 or len(manifest_by_collection) != 11
                or set(manifest_by_collection) != set(source_subjects)):
            raise ValueError("source profile manifest population differs")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PublicRightsReleaseError("PUBLIC_SOURCE_PROFILE_MANIFEST_INVALID") from error
    scope_keys = (
        "tenant", "niveau", "voie", "matiere", "statut_enseignement",
        "candidat", "school_year", "programme_version",
    )
    for subject in subjects:
        collection = subject["collection"]
        source, source_sha = source_subjects[collection]
        profile = profile_by_collection[collection]
        profile_path = profile_root / "v3_livraison_315" / f"{collection}.yml"
        try:
            source_profile = CollectionProfile.model_validate(strict_yaml_mapping(
                profile_path.read_bytes(), source=profile_path.name,
            ))
        except (OSError, ValueError) as error:
            raise PublicRightsReleaseError("PUBLIC_SOURCE_PROFILE_INVALID") from error
        source_profile_sha = collection_profile_fingerprint(source_profile)
        source_profile_ref = source.get("profile", {})
        manifest_row = manifest_by_collection[collection]
        if (source_profile.scope.collection != collection
                or source_profile.scope.visibility != "internal"
                or source_profile_ref.get("manifest_digest") != profile_manifest_sha
                or source_profile_ref.get("version") != source_profile.profile_version
                or source_profile_ref.get("fingerprint") != source_profile_sha
                or manifest_row.get("profile_version") != source_profile.profile_version
                or manifest_row.get("fingerprint") != source_profile_sha):
            raise PublicRightsReleaseError("PUBLIC_SOURCE_PROFILE_AUTHORITY_MISMATCH")
        expected_audience = [value.value for value in source_profile.scope.audience]
        if (profile.get("source_subject_sha256") != source_sha
                or profile.get("source_profile_fingerprint")
                != source.get("profile", {}).get("fingerprint")):
            raise PublicRightsReleaseError("PUBLIC_SOURCE_PROFILE_MISMATCH")
        source_by_pdf = {row["artifact_id"]: row for row in source["placements"]}
        for placement in subject["placements"]:
            derivative_sha = placement["artifact_id"]
            source_pdf = approved_sources.get((derivative_sha, collection))
            source_placement = source_by_pdf.get(source_pdf)
            if source_placement is None:
                raise PublicRightsReleaseError("PUBLIC_SOURCE_PLACEMENT_MISSING")
            expected = {**source_placement, "artifact_id": derivative_sha,
                        "visibility": "public", "review_status": "reviewed"}
            expected.pop("placement_id", None)
            expected["placement_id"] = _sha(_canonical(expected))
            if placement != expected:
                raise PublicRightsReleaseError("PUBLIC_SOURCE_SCOPE_MISMATCH")
            expected_scope = {key: source_placement[key] for key in scope_keys}
            expected_scope.update({"collection": collection, "visibility": "public",
                                   "audience": expected_audience})
            if profile.get("scope") != expected_scope:
                raise PublicRightsReleaseError("PUBLIC_SOURCE_PROFILE_SCOPE_MISMATCH")


def _private_lineage_bytes(documents: Mapping[Path, bytes], relative: Path) -> bytes:
    matches = [raw for path, raw in documents.items()
               if tuple(path.parts[-len(relative.parts):]) == relative.parts]
    if len(matches) != 1 or not isinstance(matches[0], bytes):
        raise PublicRightsReleaseError("PRIVATE_CHUNK_LINEAGE_MISSING")
    return matches[0]


def _verify_derivative_chunk_lineage(
    artifact: dict, *, repository_root: Path, private_candidate_root: Path,
    private_lineage_documents: Mapping[Path, bytes], token_counter: Any,
    approved_receipt_sha: str,
) -> int:
    """Rejoue le parseur natif et le chunker exacts depuis le CAS approuvé."""
    from nexus_release_chain.publication_chunking import chunk_verified_derivative

    sha = artifact["content_sha256"]
    source_sha = artifact.get("source_pdf_sha256")
    receipt_sha = artifact.get("derivative_receipt_sha256")
    if (artifact.get("artifact_id") != sha or artifact.get("source_path") != f"{sha}.txt"
            or artifact.get("media_type") != "text/plain; charset=utf-8"
            or not isinstance(source_sha, str) or SHA_RE.fullmatch(source_sha) is None
            or source_sha == sha or source_sha == CFTR_SHA256
            or receipt_sha != approved_receipt_sha
            or artifact.get("derivative_receipt_path") != f"derivative_receipts/{receipt_sha}.json"):
        raise PublicRightsReleaseError("PUBLIC_DERIVATIVE_IDENTITY_INVALID")
    candidate = private_candidate_root / "candidates" / f"{sha}.txt"
    if candidate.is_symlink() or not candidate.is_file() or not candidate.resolve().is_relative_to(
        private_candidate_root.resolve()
    ):
        raise PublicRightsReleaseError("PRIVATE_CANDIDATE_MISSING")
    content = candidate.read_bytes()
    if _sha(content) != sha:
        raise PublicRightsReleaseError("PRIVATE_CANDIDATE_SHA_MISMATCH")
    receipt_path = (repository_root / "docs/reports/go_live/student_rights_evidence"
                    / "derivative_receipts" / receipt_sha[:2] / f"{receipt_sha}.json")
    try:
        receipt_raw = receipt_path.read_bytes()
        receipt = json.loads(receipt_raw)
    except (OSError, ValueError) as error:
        raise PublicRightsReleaseError("PUBLIC_DERIVATIVE_RECEIPT_MISSING") from error
    if (_sha(receipt_raw) != receipt_sha or not isinstance(receipt, dict)
            or receipt.get("source_content_sha256") != source_sha
            or receipt.get("derivative_content_sha256") != sha
            or receipt.get("publication_authorized") is not False
            or receipt.get("candidate_relpath") != f"candidates/{sha}.txt"
            or artifact.get("page_count") != receipt.get("source_page_count")
            or artifact.get("citation") != {
                **receipt.get("source_attribution", {}), "source_pdf_sha256": source_sha,
            }):
        raise PublicRightsReleaseError("PUBLIC_DERIVATIVE_RECEIPT_MISMATCH")
    lineage_ref = artifact.get("chunk_lineage")
    if not isinstance(lineage_ref, dict):
        raise PublicRightsReleaseError("PRIVATE_CHUNK_LINEAGE_MISSING")
    relative = Path("chunk_lineage") / f"{sha}.json"
    if (lineage_ref.get("private_relpath") != relative.as_posix()
            or lineage_ref.get("source_receipt_sha256") != receipt_sha
            or lineage_ref.get("kind") != "NEXUS_STUDENT_DERIVATIVE_CHUNK_LINEAGE_V1"
            or lineage_ref.get("embedding_model_id") != "intfloat/multilingual-e5-large"
            or lineage_ref.get("embedding_model_revision") != "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
            or lineage_ref.get("target_tokens") != 384):
        raise PublicRightsReleaseError("PRIVATE_CHUNK_LINEAGE_REF_INVALID")
    raw = _private_lineage_bytes(private_lineage_documents, relative)
    try:
        lineage = json.loads(raw)
    except ValueError as error:
        raise PublicRightsReleaseError("PRIVATE_CHUNK_LINEAGE_INVALID") from error
    if (not isinstance(lineage, dict) or raw != _canonical(lineage)
            or _sha(raw) != lineage_ref.get("sha256")):
        raise PublicRightsReleaseError("PRIVATE_CHUNK_LINEAGE_DIGEST_MISMATCH")
    try:
        parsed = chunk_verified_derivative(
            content=content, receipt=receipt, token_counter=token_counter,
            target_tokens=384,
        )
    except ValueError as error:
        raise PublicRightsReleaseError("PUBLIC_DERIVATIVE_CHUNK_REPLAY_FAILED") from error
    public_chunks: list[dict] = []
    private_chunks: list[dict] = []
    for index, chunk in enumerate(parsed):
        chunk_sha = _sha(chunk.text.encode("utf-8"))
        token_count = token_counter.passage_token_count(chunk.text)
        if token_count > 384:
            raise PublicRightsReleaseError("PUBLIC_DERIVATIVE_CHUNK_TOKEN_OVERFLOW")
        row = {
            "chunk_index": index,
            "chunk_id": _sha(f"{sha}:{index}:{chunk_sha}".encode()),
            "chunk_sha256": chunk_sha, "page_start": chunk.page_start,
            "page_end": chunk.page_end,
        }
        public_chunks.append(row)
        private_chunks.append({**row, "text": chunk.text, "token_count": token_count})
    groups = sum(len(page["review_groups"]) for page in receipt["pages"])
    expected_lineage = {
        "kind": "NEXUS_STUDENT_DERIVATIVE_CHUNK_LINEAGE_V1",
        "derivative_content_sha256": sha,
        "derivative_receipt_sha256": receipt_sha,
        "embedding_model_id": "intfloat/multilingual-e5-large",
        "embedding_model_revision": "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3",
        "target_tokens": 384, "approved_native_group_count": groups,
        "chunks": private_chunks,
    }
    if (artifact.get("chunks") != public_chunks
            or lineage != expected_lineage
            or lineage_ref.get("chunk_count") != len(public_chunks)
            or lineage_ref.get("approved_native_group_count") != groups):
        raise PublicRightsReleaseError("PUBLIC_DERIVATIVE_CHUNK_LINEAGE_MISMATCH")
    return groups


def require_public_release_rights(
    documents: Mapping[Path, bytes], *, repository_root: Path,
    source_mirror_root: Path | None, expected_head: str | None,
    private_candidate_root: Path | None = None,
    private_lineage_documents: Mapping[Path, bytes] | None = None,
    token_counter: Any = None,
    gate_runner: Callable[..., dict] | None = None,
    authority_runner: Callable[[Path], dict] | None = None,
    rights_gate_result: dict | None = None,
) -> dict[str, Any]:
    """Bloque avant écriture tout candidat public divergeant du pack #300."""
    aggregate, registry, subjects = _release_documents(documents)
    placements = [p for subject in subjects for p in subject.get("placements", [])]
    if not placements or not all(isinstance(p, dict) for p in placements):
        raise PublicRightsReleaseError("RELEASE_PLACEMENTS_INVALID")
    public = [p for p in placements if p.get("visibility") == "public"]
    if not public:
        return {"PUBLIC_RIGHTS_GATE_APPLICABLE": False}
    if len(public) != len(placements):
        raise PublicRightsReleaseError("MIXED_PUBLIC_INTERNAL_RELEASE")
    if (private_candidate_root is None or not private_candidate_root.is_dir()):
        raise PublicRightsReleaseError("PRIVATE_CANDIDATE_ROOT_REQUIRED")
    if private_lineage_documents is None or token_counter is None:
        raise PublicRightsReleaseError("PRIVATE_CHUNK_LINEAGE_AND_TOKEN_COUNTER_REQUIRED")
    if (getattr(token_counter, "model_id", None) != "intfloat/multilingual-e5-large"
            or getattr(token_counter, "model_revision", None)
            != "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
            or getattr(token_counter, "max_sequence_length", 0) < 384):
        raise PublicRightsReleaseError("PINNED_E5_TOKEN_COUNTER_REQUIRED")
    if (aggregate.get("release_mode") != "candidate"
            or aggregate.get("promotion_status") != "NOT_PROMOTABLE"
            or aggregate.get("activation_status") != "NO_PRODUCTION_ACTIVATION"
            or aggregate.get("review_status") != "PRE_REVIEW"):
        raise PublicRightsReleaseError("FINAL_SUCCESSOR_APPROVAL_REQUIRED")
    if aggregate.get("release_id") in HISTORICAL_IDS:
        raise PublicRightsReleaseError("HISTORICAL_RELEASE_ID_FORBIDDEN")
    _validate_public_document_bindings(documents, aggregate, subjects)
    if (source_mirror_root is None or not source_mirror_root.is_dir()
            or not isinstance(expected_head, str) or GIT_SHA_RE.fullmatch(expected_head) is None):
        raise PublicRightsReleaseError("SOURCE_MIRROR_AND_HEAD_REQUIRED")
    if authority_runner is None:
        from pr300_authority_receipt import check_pr300_authority
        authority_runner = check_pr300_authority
    authority = authority_runner(repository_root)
    # Le HEAD approuvé de #300 précède son merge ; le gate documentaire est
    # rejoué sur le HEAD courant du successeur, vérifié séparément.
    if (not isinstance(authority, dict)
            or authority.get("PR300_AUTHORITY_APPROVAL_PASS") is not True
            or not isinstance(authority.get("HEAD_SHA"), str)
            or GIT_SHA_RE.fullmatch(authority["HEAD_SHA"]) is None):
        raise PublicRightsReleaseError("PR300_AUTHORITY_APPROVAL_REQUIRED")
    if rights_gate_result is None:
        if gate_runner is None:
            from check_delegated_student_rights_gate import check_gate
            gate_runner = check_gate
        gate = gate_runner(root=repository_root, source_mirror_root=source_mirror_root,
                           private_candidate_root=private_candidate_root,
                           expected_head=expected_head)
    else:
        gate = rights_gate_result
    # Le protocole #300 V2 vérifie les revues A/B ciblées dans son gate canonique.
    # Son ancien compteur de revue intégrale par page vaut zéro pour ce pack :
    # le réclamer à 315 reviendrait à rejeter une adjudication déjà approuvée.
    if (not isinstance(gate, dict)
            or gate.get("DELEGATED_RIGHTS_ADJUDICATION_PASS") is not True
            or gate.get("INVENTORY_COUNT") != 315
            or gate.get("FINAL_DECISIONS_COUNT") != 315
            or gate.get("FULL_DOCUMENT_SCAN_COUNT") != 315
            or gate.get("CFTR_DISPOSITION") != "EXCLUDE"
            or gate.get("POLICY_FAIL_CLOSED") is not True
            or gate.get("MANUAL_PER_FILE_REVIEW_REQUIRED") is not False
            or gate.get("PENDING_COUNT") != 0
            or gate.get("errors") != []):
        raise PublicRightsReleaseError("DELEGATED_GATE_NOT_PASS")
    evidence_sha = gate.get("EVIDENCE_PACK_SHA256")
    if (not isinstance(evidence_sha, str) or SHA_RE.fullmatch(evidence_sha) is None
            or authority.get("EVIDENCE_PACK_SHA256") != evidence_sha):
        raise PublicRightsReleaseError("PUBLIC_EVIDENCE_AUTHORITY_MISMATCH")
    artifact_rows = registry.get("artifacts")
    if (not isinstance(artifact_rows, list) or len(artifact_rows) != 253
            or not all(isinstance(row, dict) for row in artifact_rows)):
        raise PublicRightsReleaseError("PUBLIC_RELEASE_CONTENT_SET_INVALID")
    manifest_path = (repository_root / "docs/reports/go_live/student_rights_evidence"
                     / "public_derivative_candidate_manifest_20261010.json")
    try:
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw)
    except (OSError, ValueError) as error:
        raise PublicRightsReleaseError("PUBLIC_APPROVED_MANIFEST_MISSING") from error
    manifest_sha = _sha(manifest_raw)
    index_path = repository_root / "docs/reports/go_live/student_rights_evidence/index.json"
    try:
        index_raw = index_path.read_bytes()
        index = json.loads(index_raw)
    except (OSError, ValueError) as error:
        raise PublicRightsReleaseError("PUBLIC_EVIDENCE_INDEX_MISSING") from error
    if _sha(index_raw) != evidence_sha or not isinstance(index, dict):
        raise PublicRightsReleaseError("PUBLIC_EVIDENCE_INDEX_MISMATCH")
    if (not isinstance(manifest, dict) or manifest_raw != _canonical_pack(manifest)
            or manifest.get("status") != "PRE_REVIEW_NOT_PROMOTABLE"
            or manifest_sha != authority.get("CANDIDATE_MANIFEST_SHA256")
            or manifest_sha != aggregate.get("authorities", {}).get("candidate_manifest_sha256")):
        raise PublicRightsReleaseError("PUBLIC_APPROVED_MANIFEST_MISMATCH")
    entries = manifest.get("entries")
    if (not isinstance(entries, list) or len(entries) != 253
            or not all(isinstance(entry, dict) for entry in entries)):
        raise PublicRightsReleaseError("PUBLIC_APPROVED_MANIFEST_POPULATION_INVALID")
    manifest_by_sha = {entry.get("derivative_content_sha256"): entry for entry in entries}
    if len(manifest_by_sha) != 253:
        raise PublicRightsReleaseError("PUBLIC_APPROVED_MANIFEST_POPULATION_INVALID")
    approved = gate.get("APPROVED_DERIVATIVE_CONTENT_SHA256",
                        gate.get("APPROVED_CONTENT_SHA256"))
    artifact_shas = [row.get("content_sha256") for row in artifact_rows]
    if (not isinstance(approved, list) or len(approved) != 253
            or len(set(approved)) != 253 or not all(
                isinstance(sha, str) and SHA_RE.fullmatch(sha) for sha in approved
            ) or sorted(artifact_shas) != sorted(approved)
            or set(artifact_shas) != set(manifest_by_sha)
            or len(set(artifact_shas)) != 253):
        raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_CONTENT_SET_INVALID")
    receipt_bindings = {sha: entry.get("derivative_receipt_sha256")
                        for sha, entry in manifest_by_sha.items()}
    projected_receipts = gate.get("APPROVED_DERIVATIVE_RECEIPT_SHA256")
    if projected_receipts is not None and projected_receipts != receipt_bindings:
        raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_RECEIPT_MISMATCH")
    if (not isinstance(receipt_bindings, dict) or set(receipt_bindings) != set(approved)
            or any(not isinstance(value, str) or SHA_RE.fullmatch(value) is None
                   for value in receipt_bindings.values())):
        raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_RECEIPTS_INVALID")
    if any(row.get("derivative_receipt_sha256") != receipt_bindings[row["content_sha256"]]
           for row in artifact_rows):
        raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_RECEIPT_MISMATCH")
    _candidate_registries(documents, aggregate, subjects, artifact_rows, evidence_sha)
    _source_scope_bindings(documents, subjects, manifest_by_sha, index, repository_root)
    root = next(path for path in documents if path.name == "production-profile-gate.release.json").parent
    allowed_documents = {
        root / "production-profile-gate.release.json", root / "artifacts.release.json",
        root / "public_profiles.json", root / "public_rights_registry.json",
        root / "public_pii_registry.json", root.parent / "release-registry.json",
        *(root / ref["path"] for ref in aggregate["subjects"]),
    }
    if (set(documents) != allowed_documents
            or any(raw.startswith(b"%PDF") for raw in documents.values())):
        raise PublicRightsReleaseError("PUBLIC_RELEASE_UNEXPECTED_MATERIAL")
    expected_topology = {sha: dict(Counter(entry.get("collections", [])))
                         for sha, entry in manifest_by_sha.items()}
    projected_topology = gate.get("APPROVED_DERIVATIVE_PLACEMENTS")
    if projected_topology is not None and projected_topology != expected_topology:
        raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_TOPOLOGY_MISMATCH")
    if (not isinstance(expected_topology, dict) or set(expected_topology) != set(approved)):
        raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_TOPOLOGY_MISSING")
    observed: Counter[tuple[str, str]] = Counter()
    for subject in subjects:
        collection = subject.get("collection")
        if (not isinstance(collection, str) or not collection
                or not subject.get("placements")):
            raise PublicRightsReleaseError("PUBLIC_EMPTY_OR_INVALID_COLLECTION")
        for placement in subject["placements"]:
            if (placement.get("collection") != collection
                    or placement.get("artifact_id") not in approved):
                raise PublicRightsReleaseError("PUBLIC_RELEASE_COLLECTION_SCOPE_INVALID")
            observed[(placement["artifact_id"], collection)] += 1
    expected: Counter[tuple[str, str]] = Counter()
    for sha, collections in expected_topology.items():
        if not isinstance(collections, dict) or not collections:
            raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_TOPOLOGY_MISSING")
        for collection, count in collections.items():
            if not isinstance(collection, str) or type(count) is not int or count < 1:
                raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_TOPOLOGY_MISSING")
            expected[(sha, collection)] = count
    if observed != expected:
        raise PublicRightsReleaseError("PUBLIC_APPROVED_DERIVATIVE_TOPOLOGY_MISMATCH")
    total_groups = sum(_verify_derivative_chunk_lineage(
        row, repository_root=repository_root,
        private_candidate_root=private_candidate_root,
        private_lineage_documents=private_lineage_documents,
        token_counter=token_counter,
        approved_receipt_sha=receipt_bindings[row["content_sha256"]],
    ) for row in artifact_rows)
    chunks = sum(len(row["chunks"]) for row in artifact_rows)
    observed_counts = {"collections": len(subjects), "artifacts": len(artifact_rows),
                       "placements": len(placements), "chunks": chunks}
    declared = aggregate.get("expected_counts")
    registry_counts = registry.get("expected_counts")
    population = gate.get("FINAL_POPULATION")
    if (not isinstance(declared, dict) or not isinstance(registry_counts, dict)
            or not isinstance(population, dict)
            or declared != {"subjects": 11, "unique_artifacts": 253,
                            "placements": 377, "unique_chunks": chunks}
            or registry_counts != {"unique_artifacts": 253, "unique_chunks": chunks}
            or observed_counts["collections"] != 11
            or observed_counts["placements"] != 377
            or population.get("artifacts") != 253
            or population.get("collections") != 11
            or population.get("placements") != 377
            or population.get("derivative_segments") != total_groups
            or population.get("original_pdf_public_count") != 0):
        raise PublicRightsReleaseError("PUBLIC_RELEASE_COUNTS_MISMATCH")
    return {
        "PUBLIC_RIGHTS_GATE_APPLICABLE": True,
        "PUBLIC_RIGHTS_GATE_PASS": True,
        "PUBLIC_CANDIDATE_PROMOTABLE": False,
        "EVIDENCE_PACK_SHA256": evidence_sha,
        "APPROVED_DERIVATIVE_CONTENT_SHA256": sorted(approved),
        "FINAL_POPULATION": observed_counts,
    }
