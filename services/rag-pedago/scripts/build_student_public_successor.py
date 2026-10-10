#!/usr/bin/env python3
"""Projeter une release étudiante successeur à partir des dérivés #300 scellés.

Le producteur ne promeut jamais les PDF V4/V5 : ses seuls matériaux sont les
textes natifs et les reçus de dérivation privés, identifiés par SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from nexus_contracts.embedding_utils import format_passage
from nexus_contracts.ingestion import (
    CollectionProfile,
    collection_profile_fingerprint,
    profile_manifest_fingerprint,
)
from nexus_contracts.profile_manifest import strict_yaml_mapping
from nexus_release_chain.publication_chunking import chunk_verified_derivative

EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
EMBEDDING_REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
LINEAGE_KIND = "NEXUS_STUDENT_DERIVATIVE_CHUNK_LINEAGE_V1"
MANIFEST_REL = Path(
    "docs/reports/go_live/student_rights_evidence/"
    "public_derivative_candidate_manifest_20261010.json"
)
INDEX_REL = Path("docs/reports/go_live/student_rights_evidence/index.json")
CFTR_SHA = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
SOURCE_PROFILE_MANIFEST_REL = Path(
    "services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v3_livraison_315.yml"
)
SOURCE_PROFILE_DIR_REL = Path(
    "services/rag-engine/configs/ingestion_profiles/v3_livraison_315"
)


class PinnedE5TokenCounter:
    """Le même comptage `passage:` que le producteur V4/V5, au snapshot fixé."""

    model_id = EMBEDDING_MODEL
    model_revision = EMBEDDING_REVISION

    def __init__(self, snapshot: Path) -> None:
        if snapshot.name != self.model_revision or not snapshot.is_dir():
            raise ValueError("E5 tokenizer snapshot revision differs")
        from transformers import AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
        self.max_sequence_length = int(self._tokenizer.model_max_length)
        if self.max_sequence_length < 384:
            raise ValueError("E5 tokenizer sequence length is too small")

    def passage_token_count(self, text: str) -> int:
        encoded = self._tokenizer(
            format_passage(text), add_special_tokens=True, truncation=False,
        )
        count = len(encoded["input_ids"])
        if count <= 0:
            raise ValueError("E5 tokenizer returned no tokens")
        return count


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def current_checkout_sha(repository_root: Path) -> str:
    """HEAD source courant ; distinct du HEAD historique approuvé de #300."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository_root,
        capture_output=True, text=True, check=True, timeout=20,
    )
    sha = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ValueError("current checkout HEAD is not a Git SHA")
    return sha


def run_approved_source_gate(
    *, authority_root: Path, source_mirror_root: Path,
    private_candidate_root: Path, gate_runner: Callable[..., dict],
) -> tuple[str, dict]:
    """Rejouer #300 dans son checkout immuable, avant toute projection."""
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all",
         "--ignore-submodules=none"],
        cwd=authority_root, capture_output=True, text=True, check=True, timeout=30,
    )
    if status.stdout:
        raise ValueError("authority checkout is not clean")
    source_head = current_checkout_sha(authority_root)
    gate = gate_runner(
        root=authority_root, expected_head=source_head,
        source_mirror_root=source_mirror_root,
        private_candidate_root=private_candidate_root,
    )
    if gate.get("DELEGATED_RIGHTS_ADJUDICATION_PASS") is not True:
        raise ValueError(f"independent #300 gate failed: {gate.get('errors')}")
    return source_head, gate


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _set_digest(values: list[str] | list[int]) -> str:
    return _sha(json.dumps(
        sorted(values, key=lambda value: json.dumps(value, sort_keys=True)),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode())


def project_derivative_artifact(
    entry: Mapping[str, Any],
    receipt: Mapping[str, Any],
    content: bytes,
    *,
    token_counter: Any,
    target_tokens: int = 384,
    source_type_doc: str = "document_pedagogique",
) -> tuple[dict[str, Any], bytes]:
    """Recalculer les chunks exacts d'un dérivé, sans exposer leur texte en manifeste."""
    sha = entry.get("derivative_content_sha256")
    source_sha = entry.get("source_content_sha256")
    receipt_sha = entry.get("derivative_receipt_sha256")
    if not isinstance(sha, str) or _sha(content) != sha:
        raise ValueError("CAS derivative SHA mismatch")
    if sha == source_sha or receipt.get("source_content_sha256") != source_sha:
        raise ValueError("source PDF and derivative identities differ")
    if receipt.get("derivative_content_sha256") != sha:
        raise ValueError("derivative receipt identity differs")
    if not isinstance(receipt_sha, str) or len(receipt_sha) != 64:
        raise ValueError("derivative receipt SHA missing")
    if (entry.get("media_type") != "text/plain; charset=utf-8"
            or receipt.get("derivative_media_type") != "text/plain"
            or receipt.get("derivative_encoding") != "utf-8"):
        raise ValueError("derivative media type differs")
    if (getattr(token_counter, "model_id", None) != EMBEDDING_MODEL
            or getattr(token_counter, "model_revision", None) != EMBEDDING_REVISION):
        raise ValueError("token counter is not the pinned E5 model")
    attribution = receipt.get("source_attribution")
    if not isinstance(attribution, dict) or entry.get("citation") != attribution:
        raise ValueError("candidate citation differs from sealed receipt")
    if any(not isinstance(attribution.get(key), str) or not attribution[key].strip()
           for key in ("source_uri", "source_label", "source_updated_at",
                       "licensor", "licence_id", "derivative_notice")):
        raise ValueError("candidate citation incomplete")
    chunks = chunk_verified_derivative(
        content=content, receipt=receipt,
        token_counter=token_counter, target_tokens=target_tokens,
    )
    public_chunks: list[dict[str, Any]] = []
    private_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        chunk_sha = _sha(chunk.text.encode("utf-8"))
        chunk_id = _sha(f"{sha}:{index}:{chunk_sha}".encode())
        token_count = token_counter.passage_token_count(chunk.text)
        if token_count > target_tokens:
            raise ValueError("derivative publication chunk exceeds token budget")
        row = {
            "chunk_index": index, "chunk_id": chunk_id,
            "chunk_sha256": chunk_sha, "page_start": chunk.page_start,
            "page_end": chunk.page_end,
        }
        public_chunks.append(row)
        private_chunks.append({**row, "text": chunk.text, "token_count": token_count})
    groups = sum(len(page["review_groups"]) for page in receipt["pages"])
    excluded_pages = [
        page["page_number"] for page in receipt["pages"]
        if not page["review_groups"]
    ]
    covered_pages = sorted({row["page_start"] for row in public_chunks})
    if (sorted(covered_pages + excluded_pages)
            != list(range(1, receipt["source_page_count"] + 1))):
        raise ValueError("derived page partition differs from source receipt")
    private_lineage = _canonical({
        "kind": LINEAGE_KIND, "derivative_content_sha256": sha,
        "derivative_receipt_sha256": receipt_sha,
        "embedding_model_id": EMBEDDING_MODEL,
        "embedding_model_revision": EMBEDDING_REVISION,
        "target_tokens": target_tokens, "approved_native_group_count": groups,
        "chunks": private_chunks,
    })
    citation = {**attribution, "source_pdf_sha256": source_sha}
    artifact = {
        "artifact_id": sha, "content_sha256": sha,
        "source_pdf_sha256": source_sha,
        "source_path": f"{sha}.txt",
        "derivative_receipt_path": f"derivative_receipts/{receipt_sha}.json",
        "derivative_receipt_sha256": receipt_sha,
        "media_type": "text/plain; charset=utf-8",
        "source_url": attribution["source_uri"],
        "title": attribution["source_label"],
        "type_doc": source_type_doc,
        "citation": citation,
        "page_count": receipt["source_page_count"],
        "excluded_source_pages": excluded_pages,
        "chunks": public_chunks,
        "chunk_id_set_digest": _set_digest([row["chunk_id"] for row in public_chunks]),
        "chunk_sha256_set_digest": _set_digest(
            [row["chunk_sha256"] for row in public_chunks]
        ),
        "page_coverage_digest": _set_digest(covered_pages),
        "chunk_lineage": {
            "kind": LINEAGE_KIND,
            "private_relpath": f"chunk_lineage/{sha}.json",
            "sha256": _sha(private_lineage),
            "source_receipt_sha256": receipt_sha,
            "chunk_count": len(public_chunks),
            "approved_native_group_count": groups,
            "embedding_model_id": EMBEDDING_MODEL,
            "embedding_model_revision": EMBEDDING_REVISION,
            "target_tokens": target_tokens,
        },
    }
    return artifact, private_lineage


def _read_json_sha(path: Path, expected_sha: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if _sha(raw) != expected_sha:
        raise ValueError(f"SHA mismatch: {path.name}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path.name}")
    return value


def _source_placements(root: Path, index: Mapping[str, Any]) -> tuple[dict, dict, dict, dict]:
    subjects: dict[str, dict] = {}
    placements: dict[tuple[str, str], dict] = {}
    source_artifacts: dict[str, dict] = {}
    models: dict | None = None
    for population in index["source_population"]:
        registry = _read_json_sha(root / population["artifacts_path"], population["artifacts_sha256"])
        population_artifacts = {
            artifact["content_sha256"]: artifact for artifact in registry["artifacts"]
        }
        for ref in population["subjects"]:
            source_subject = _read_json_sha(root / ref["path"], ref["sha256"])
            collection = source_subject["collection"]
            if collection in subjects:
                raise ValueError("duplicate source collection")
            if models is None:
                models = source_subject["models"]
            elif models != source_subject["models"]:
                raise ValueError("source model inventories differ")
            subjects[collection] = source_subject
            for placement in source_subject["placements"]:
                key = (placement["artifact_id"], collection)
                if key in placements:
                    raise ValueError("duplicate source placement in collection")
                placements[key] = placement
                source_sha = placement["artifact_id"]
                if source_sha not in population_artifacts:
                    raise ValueError("source placement has no sealed PDF artifact")
                if source_sha in source_artifacts and source_artifacts[source_sha] != population_artifacts[source_sha]:
                    raise ValueError("source PDF artifact appears with divergent metadata")
                source_artifacts[source_sha] = population_artifacts[source_sha]
    if len(subjects) != 11 or models is None:
        raise ValueError("source population must contain eleven collections")
    return subjects, placements, models, source_artifacts


def _bound_source_audiences(root: Path, subjects: Mapping[str, dict]) -> dict[str, list[str]]:
    """Lire l'audience pédagogique dans les profils V3 liés aux sujets scellés."""
    manifest_path = root / SOURCE_PROFILE_MANIFEST_REL
    manifest = strict_yaml_mapping(manifest_path.read_bytes(), source=manifest_path.name)
    manifest_digest = profile_manifest_fingerprint(manifest)
    rows = manifest.get("profiles")
    if not isinstance(rows, list) or len(rows) != len(subjects):
        raise ValueError("source profile manifest population differs")
    by_collection = {row.get("collection"): row for row in rows if isinstance(row, dict)}
    if len(by_collection) != len(subjects) or set(by_collection) != set(subjects):
        raise ValueError("source profile manifest collections differ")
    audiences: dict[str, list[str]] = {}
    for collection, subject in subjects.items():
        path = root / SOURCE_PROFILE_DIR_REL / f"{collection}.yml"
        profile = CollectionProfile.model_validate(
            strict_yaml_mapping(path.read_bytes(), source=path.name)
        )
        fingerprint = collection_profile_fingerprint(profile)
        source_ref = subject["profile"]
        manifest_row = by_collection[collection]
        if (profile.scope.collection != collection
                or profile.scope.visibility != "internal"
                or source_ref.get("manifest_digest") != manifest_digest
                or source_ref.get("version") != profile.profile_version
                or source_ref.get("fingerprint") != fingerprint
                or manifest_row.get("profile_version") != profile.profile_version
                or manifest_row.get("fingerprint") != fingerprint):
            raise ValueError("source profile authority or scope differs")
        audiences[collection] = [value.value for value in profile.scope.audience]
    return audiences


def _require_successor_id(root: Path, release_id: str) -> None:
    if re.fullmatch(r"[a-z0-9][a-z0-9.-]{7,127}", release_id) is None:
        raise ValueError("successor release ID is invalid")
    releases = root / "services/rag-pedago/data/releases"
    for registry_path in releases.rglob("release-registry.json"):
        registry = json.loads(registry_path.read_bytes())
        if any(row.get("release_id") == release_id for row in registry.get("releases", [])):
            raise ValueError("successor release ID already exists")


def build_successor_documents(
    *,
    repository_root: Path,
    private_candidate_root: Path,
    release_root: Path,
    private_root: Path,
    release_id: str,
    token_counter: Any,
    authority_approval: Mapping[str, Any],
    rights_gate: Mapping[str, Any],
    target_tokens: int = 384,
) -> tuple[dict[Path, bytes], dict[Path, bytes]]:
    """Former les documents en mémoire ; aucun fichier n'est écrit par cette fonction.

    Le CLI doit avoir relu l'approbation GitHub et exécuté le gate #300 avant
    d'appeler cette projection. Les deux résultats, leurs digests et la
    population exacte sont contrôlés ici une nouvelle fois.
    """
    if authority_approval.get("PR300_AUTHORITY_APPROVAL_PASS") is not True:
        raise ValueError("exact-head #300 authority approval required")
    if rights_gate.get("DELEGATED_RIGHTS_ADJUDICATION_PASS") is not True:
        raise ValueError("independent #300 rights gate required")
    if (getattr(token_counter, "model_id", None) != EMBEDDING_MODEL
            or getattr(token_counter, "model_revision", None) != EMBEDDING_REVISION):
        raise ValueError("pinned E5 tokenizer required")
    _require_successor_id(repository_root, release_id)
    manifest_raw = (repository_root / MANIFEST_REL).read_bytes()
    index_raw = (repository_root / INDEX_REL).read_bytes()
    if (authority_approval.get("CANDIDATE_MANIFEST_SHA256") != _sha(manifest_raw)
            or authority_approval.get("EVIDENCE_PACK_SHA256") != _sha(index_raw)):
        raise ValueError("approved #300 pack digest mismatch")
    manifest = json.loads(manifest_raw)
    index = json.loads(index_raw)
    if (manifest.get("status") != "PRE_REVIEW_NOT_PROMOTABLE"
            or manifest.get("counts") != {
                "source_pdfs": 315, "public_derivative_artifacts": 253,
                "public_placements": 377, "public_collections": 11,
                "public_derivative_segments": 2504, "original_pdf_public_count": 0,
            }
            or index.get("public_candidate_manifest_sha256") != _sha(manifest_raw)
            or index.get("final_population", {}).get("original_pdf_public_count") != 0):
        raise ValueError("#300 candidate population or binding differs")
    entries = manifest["entries"]
    derivative_shas = [entry["derivative_content_sha256"] for entry in entries]
    if (len(entries) != 253 or len(set(derivative_shas)) != 253
            or CFTR_SHA in {entry["source_content_sha256"] for entry in entries}
            or rights_gate.get("APPROVED_DERIVATIVE_CONTENT_SHA256") != sorted(derivative_shas)):
        raise ValueError("approved derivative set differs")
    if (rights_gate.get("EVIDENCE_PACK_SHA256") != _sha(index_raw)
            or rights_gate.get("FINAL_POPULATION") != index.get("final_population")
            or rights_gate.get("FINAL_DECISIONS_COUNT") != 315
            or rights_gate.get("PENDING_COUNT") != 0
            or rights_gate.get("errors") != []):
        raise ValueError("independent rights gate evidence or population differs")
    topology = rights_gate.get("APPROVED_DERIVATIVE_PLACEMENTS")
    receipt_shas = rights_gate.get("APPROVED_DERIVATIVE_RECEIPT_SHA256")
    observed_topology = {
        entry["derivative_content_sha256"]: dict(Counter(entry["collections"]))
        for entry in entries
    }
    observed_receipts = {
        entry["derivative_content_sha256"]: entry["derivative_receipt_sha256"]
        for entry in entries
    }
    # Le vérificateur exact-HEAD de main #300 antérieur à l'extension retourne
    # le set approuvé et le digest du pack, mais pas ces deux projections. Elles
    # sont reconstruites uniquement depuis le manifeste dont le SHA est lié à
    # la review humaine et à l'index que le gate complet vient de valider.
    if topology is None and receipt_shas is None:
        topology, receipt_shas = observed_topology, observed_receipts
    if not isinstance(topology, dict) or not isinstance(receipt_shas, dict):
        raise ValueError("approved derivative topology missing")
    if topology != observed_topology or receipt_shas != observed_receipts:
        raise ValueError("approved derivative topology or receipt differs")
    source_subjects, source_placement_map, models, source_artifacts = _source_placements(
        repository_root, index,
    )
    source_audiences = _bound_source_audiences(repository_root, source_subjects)
    if (sum(sum(row.values()) for row in topology.values()) != 377
            or set(source_subjects) != {c for e in entries for c in e["collections"]}):
        raise ValueError("public collection or placement population differs")

    evidence_root = repository_root / "docs/reports/go_live/student_rights_evidence"
    artifacts: list[dict[str, Any]] = []
    private_documents: dict[Path, bytes] = {}
    placements_by_collection: dict[str, list[dict]] = defaultdict(list)
    for entry in sorted(entries, key=lambda row: row["derivative_content_sha256"]):
        sha = entry["derivative_content_sha256"]
        source_sha = entry["source_content_sha256"]
        receipt_sha = entry["derivative_receipt_sha256"]
        if entry.get("private_candidate_relpath") != f"candidates/{sha}.txt":
            raise ValueError("candidate CAS path differs")
        receipt_path = evidence_root / "derivative_receipts" / receipt_sha[:2] / f"{receipt_sha}.json"
        receipt_raw = receipt_path.read_bytes()
        if _sha(receipt_raw) != receipt_sha:
            raise ValueError("derivative receipt CAS SHA mismatch")
        receipt = json.loads(receipt_raw)
        content = (private_candidate_root / "candidates" / f"{sha}.txt").read_bytes()
        artifact, lineage = project_derivative_artifact(
            entry, receipt, content, token_counter=token_counter,
            target_tokens=target_tokens,
            source_type_doc=source_artifacts[source_sha]["type_doc"],
        )
        private_documents[private_root / f"{sha}.txt"] = content
        private_documents[private_root / artifact["derivative_receipt_path"]] = receipt_raw
        private_documents[private_root / artifact["chunk_lineage"]["private_relpath"]] = lineage
        artifacts.append(artifact)
        for collection in entry["collections"]:
            source = source_placement_map.get((source_sha, collection))
            if source is None:
                raise ValueError("candidate has no sealed source placement")
            placement = {
                **source,
                "artifact_id": sha,
                "visibility": "public",
                "review_status": "reviewed",
            }
            placement.pop("placement_id", None)
            placement["placement_id"] = _sha(_canonical(placement))
            placements_by_collection[collection].append(placement)
    if (len(artifacts) != 253
            or sum(map(len, placements_by_collection.values())) != 377
            or any(not rows for rows in placements_by_collection.values())):
        raise ValueError("public release counts differ from approved candidate")

    source_subject_sha = {
        ref["path"].split("/")[-1].removesuffix(".release.json"): ref["sha256"]
        for population in index["source_population"]
        for ref in population["subjects"]
    }
    profiles: dict[str, dict[str, Any]] = {}
    for collection, rows in sorted(placements_by_collection.items()):
        source = source_subjects[collection]
        scope_fields = (
            "tenant", "niveau", "voie", "matiere", "statut_enseignement",
            "candidat", "school_year", "programme_version",
        )
        first_scope = {key: rows[0][key] for key in scope_fields}
        if any({key: row[key] for key in scope_fields} != first_scope for row in rows):
            raise ValueError("public collection has divergent source scope metadata")
        scope = {
            **first_scope, "collection": collection, "visibility": "public",
            "audience": source_audiences[collection],
        }
        profiles[collection] = {
            "collection": collection,
            "source_subject_sha256": source_subject_sha[collection],
            "source_profile_fingerprint": source["profile"]["fingerprint"],
            "scope": scope,
            "profile_fingerprint": _sha(_canonical(scope)),
        }
    public_profiles_raw = _canonical({
        "kind": "NEXUS_STUDENT_PUBLIC_SCOPE_CANDIDATES_V1",
        "release_id": release_id, "status": "CANDIDATE_NOT_AUTHORIZED",
        "entries": list(profiles.values()),
    })
    public_rights_raw = _canonical({
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_RIGHTS_REGISTRY_V1",
        "release_id": release_id, "status": "CANDIDATE_NOT_AUTHORIZED",
        "rights_authority_sha256": manifest["rights_authority_sha256"],
        "evidence_pack_sha256": _sha(index_raw),
        "authorized_use": "student_retrieval_excerpt_only",
        "full_pdf_redistribution_allowed": False,
        "answer_generation_allowed": False,
        "entries": [{
            "content_sha256": artifact["content_sha256"],
            "source_pdf_sha256": artifact["source_pdf_sha256"],
            "derivative_receipt_sha256": artifact["derivative_receipt_sha256"],
            "citation_sha256": _sha(_canonical(artifact["citation"])),
        } for artifact in artifacts],
    })
    public_pii_raw = _canonical({
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_PII_REGISTRY_V1",
        "release_id": release_id, "status": "CANDIDATE_NOT_AUTHORIZED",
        "evidence_pack_sha256": _sha(index_raw),
        "entries": [{
            "content_sha256": artifact["content_sha256"],
            "source_pdf_sha256": artifact["source_pdf_sha256"],
            "derivative_receipt_sha256": artifact["derivative_receipt_sha256"],
            "pii_gate_status": "PASS_BY_PR300_FULL_DOCUMENT_GATE",
        } for artifact in artifacts],
    })

    authority = {
        "pr300_final_authority_receipt_sha256": _sha((repository_root /
            "docs/reports/go_live/student_rights_evidence/pr300_final_authority_approval.json").read_bytes()),
        "delegated_evidence_pack_sha256": _sha(index_raw),
        "candidate_manifest_sha256": _sha(manifest_raw),
        "rights_authority_sha256": manifest["rights_authority_sha256"],
        "text_derivative_extraction_policy_sha256": manifest[
            "text_derivative_extraction_policy_sha256"],
        "public_profile_registry_sha256": _sha(public_profiles_raw),
        "public_rights_registry_sha256": _sha(public_rights_raw),
        "public_pii_registry_sha256": _sha(public_pii_raw),
    }
    registry = {
        "release_kind": "MULTILEVEL_ARTIFACT_REGISTRY_V2",
        "release_id": release_id, "school_year": "2026-2027",
        "expected_counts": {
            "unique_artifacts": 253,
            "unique_chunks": sum(len(a["chunks"]) for a in artifacts),
        },
        "artifacts": artifacts,
    }
    registry_raw = _canonical(registry)
    documents: dict[Path, bytes] = {
        release_root / "artifacts.release.json": registry_raw,
        release_root / "public_profiles.json": public_profiles_raw,
        release_root / "public_rights_registry.json": public_rights_raw,
        release_root / "public_pii_registry.json": public_pii_raw,
    }
    subjects: list[dict[str, str]] = []
    for collection, rows in sorted(placements_by_collection.items()):
        source_subject = source_subjects[collection]
        profile = {
            "version": "student-public-v1",
            "fingerprint": profiles[collection]["profile_fingerprint"],
            "manifest_digest": _sha(public_profiles_raw),
        }
        subject = {
            "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V2",
            "release_id": f"{release_id}-{collection}",
            "school_year": "2026-2027", "collection": collection,
            "programme_version": source_subject["programme_version"],
            "authorities": authority, "profile": profile, "models": models,
            "artifact_registry": {"path": "../artifacts.release.json", "sha256": _sha(registry_raw)},
            "expected_counts": {
                "unique_artifact_references": len({row["artifact_id"] for row in rows}),
                "placements": len(rows),
            },
            "placements": sorted(rows, key=lambda row: (row["artifact_id"], row["placement_id"])),
        }
        path = release_root / "subjects" / f"{collection}.release.json"
        raw = _canonical(subject)
        documents[path] = raw
        subjects.append({"path": path.relative_to(release_root).as_posix(),
                         "sha256": _sha(raw), "collection": collection})
    aggregate = {
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
        "release_id": release_id, "school_year": "2026-2027",
        "authorities": authority, "models": models,
        "artifact_registry": {"path": "artifacts.release.json", "sha256": _sha(registry_raw)},
        "expected_counts": {
            "unique_artifacts": len(artifacts),
            "placements": sum(len(rows) for rows in placements_by_collection.values()),
            "unique_chunks": registry["expected_counts"]["unique_chunks"],
            "subjects": len(subjects),
        },
        "subjects": subjects,
        "release_mode": "candidate",
        "promotion_status": "NOT_PROMOTABLE",
        "activation_status": "NO_PRODUCTION_ACTIVATION",
        "review_status": "PRE_REVIEW",
    }
    aggregate_path = release_root / "production-profile-gate.release.json"
    aggregate_raw = _canonical(aggregate)
    documents[aggregate_path] = aggregate_raw
    documents[release_root.parent / "release-registry.json"] = _canonical({
        "registry_version": "1", "school_year": "2026-2027",
        "releases": [{
            "release_id": release_id,
            "collections": sorted(placements_by_collection),
            "manifest_path": f"{release_root.name}/production-profile-gate.release.json",
            "expected_manifest_sha256": _sha(aggregate_raw),
            "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
        }],
    })
    return documents, private_documents


def verify_successor_metadata(
    documents: Mapping[Path, bytes], release_root: Path,
) -> dict[str, int]:
    """Vérifier hors CAS les sceaux publics ; ne vaut pas une autorisation de publier."""
    def read(path: Path) -> dict[str, Any]:
        raw = documents.get(path)
        if not isinstance(raw, bytes) or raw.startswith(b"%PDF"):
            raise ValueError(f"release document missing or PDF: {path.name}")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"release document invalid: {path.name}")
        return value

    aggregate_path = release_root / "production-profile-gate.release.json"
    registry_path = release_root / "artifacts.release.json"
    aggregate = read(aggregate_path)
    registry = read(registry_path)
    authorities = aggregate.get("authorities")
    if not isinstance(authorities, dict):
        raise ValueError("successor authorities missing")
    sidecars: dict[str, dict] = {}
    for name, key in (
        ("public_profiles.json", "public_profile_registry_sha256"),
        ("public_rights_registry.json", "public_rights_registry_sha256"),
        ("public_pii_registry.json", "public_pii_registry_sha256"),
    ):
        path = release_root / name
        sidecars[name] = read(path)
        if _sha(documents[path]) != authorities.get(key):
            raise ValueError(f"successor {name} digest mismatch")
        if sidecars[name].get("status") != "CANDIDATE_NOT_AUTHORIZED":
            raise ValueError(f"successor {name} must remain unauthorized")
    if (aggregate.get("release_kind") != "MULTILEVEL_AGGREGATE_RELEASE_V2"
            or aggregate.get("release_mode") != "candidate"
            or aggregate.get("promotion_status") != "NOT_PROMOTABLE"
            or aggregate.get("activation_status") != "NO_PRODUCTION_ACTIVATION"
            or aggregate.get("review_status") != "PRE_REVIEW"
            or aggregate.get("artifact_registry") != {
                "path": "artifacts.release.json", "sha256": _sha(documents[registry_path]),
            }
            or registry.get("release_id") != aggregate.get("release_id")):
        raise ValueError("successor candidate status or registry binding invalid")
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 253:
        raise ValueError("successor artifact population differs")
    artifact_by_sha: dict[str, dict] = {}
    total_chunks = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("successor artifact row invalid")
        sha = artifact.get("content_sha256")
        source_sha = artifact.get("source_pdf_sha256")
        receipt_sha = artifact.get("derivative_receipt_sha256")
        if (not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
                or not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha)
                or not isinstance(receipt_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", receipt_sha)
                or sha == source_sha or sha in artifact_by_sha
                or artifact.get("artifact_id") != sha
                or artifact.get("source_path") != f"{sha}.txt"
                or artifact.get("derivative_receipt_path") != f"derivative_receipts/{receipt_sha}.json"
                or artifact.get("media_type") != "text/plain; charset=utf-8"):
            raise ValueError("successor text identity invalid")
        citation = artifact.get("citation")
        if (not isinstance(citation, dict)
                or citation.get("source_pdf_sha256") != source_sha
                or citation.get("source_uri") != artifact.get("source_url")
                or citation.get("source_label") != artifact.get("title")
                or any(not isinstance(citation.get(k), str) or not citation[k].strip()
                       for k in ("source_updated_at", "licensor", "licence_id", "derivative_notice"))):
            raise ValueError("successor citation incomplete")
        chunks = artifact.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("successor text chunks missing")
        for index, row in enumerate(chunks):
            if (not isinstance(row, dict) or row.get("chunk_index") != index
                    or row.get("page_start") != row.get("page_end")
                    or not isinstance(row.get("page_start"), int)
                    or row["page_start"] < 1 or row["page_start"] > artifact.get("page_count", 0)
                    or row.get("chunk_id") != _sha(
                        f"{sha}:{index}:{row.get('chunk_sha256')}".encode()
                    ) or "text" in row):
                raise ValueError("successor chunk identity invalid")
        coverage = sorted({row["page_start"] for row in chunks})
        excluded = artifact.get("excluded_source_pages")
        if (not isinstance(excluded, list)
                or sorted(coverage + excluded) != list(range(1, artifact["page_count"] + 1))
                or artifact.get("chunk_id_set_digest") != _set_digest([row["chunk_id"] for row in chunks])
                or artifact.get("chunk_sha256_set_digest") != _set_digest([row["chunk_sha256"] for row in chunks])
                or artifact.get("page_coverage_digest") != _set_digest(coverage)):
            raise ValueError("successor page partition or chunk digest invalid")
        lineage = artifact.get("chunk_lineage")
        if (not isinstance(lineage, dict) or lineage.get("kind") != LINEAGE_KIND
                or lineage.get("private_relpath") != f"chunk_lineage/{sha}.json"
                or lineage.get("source_receipt_sha256") != receipt_sha
                or lineage.get("chunk_count") != len(chunks)
                or lineage.get("embedding_model_id") != EMBEDDING_MODEL
                or lineage.get("embedding_model_revision") != EMBEDDING_REVISION
                or not isinstance(lineage.get("sha256"), str)):
            raise ValueError("successor private lineage binding invalid")
        artifact_by_sha[sha] = artifact
        total_chunks += len(chunks)
    if registry.get("expected_counts") != {
        "unique_artifacts": 253, "unique_chunks": total_chunks,
    }:
        raise ValueError("successor artifact count mismatch")
    subject_refs = aggregate.get("subjects")
    if not isinstance(subject_refs, list) or len(subject_refs) != 11:
        raise ValueError("successor subject population differs")
    profiles = {row["collection"]: row for row in sidecars["public_profiles.json"]["entries"]}
    if len(profiles) != 11:
        raise ValueError("successor public profile population differs")
    placements = []
    for ref in subject_refs:
        if not isinstance(ref, dict) or ref.get("path") != f"subjects/{ref.get('collection')}.release.json":
            raise ValueError("successor subject reference invalid")
        subject_path = release_root / ref["path"]
        subject = read(subject_path)
        if _sha(documents[subject_path]) != ref.get("sha256"):
            raise ValueError("successor subject digest mismatch")
        collection = ref["collection"]
        profile = profiles.get(collection)
        if (profile is None or subject.get("collection") != collection
                or subject.get("profile", {}).get("fingerprint") != profile["profile_fingerprint"]
                or subject.get("profile", {}).get("manifest_digest") != authorities["public_profile_registry_sha256"]
                or profile.get("scope", {}).get("visibility") != "public"
                or profile.get("scope", {}).get("audience") != ["libre", "aefe"]
                or subject.get("authorities") != authorities):
            raise ValueError("successor public scope binding invalid")
        subject_rows = subject.get("placements")
        if not isinstance(subject_rows, list) or not subject_rows:
            raise ValueError("successor collection empty")
        for placement in subject_rows:
            if (placement.get("collection") != collection
                    or placement.get("visibility") != "public"
                    or placement.get("artifact_id") not in artifact_by_sha):
                raise ValueError("successor placement is out of scope")
        placements.extend(subject_rows)
    if (len(placements) != 377
            or len({row["placement_id"] for row in placements}) != 377
            or aggregate.get("expected_counts") != {
                "unique_artifacts": 253, "placements": 377,
                "unique_chunks": total_chunks, "subjects": 11,
            }):
        raise ValueError("successor placement or aggregate count mismatch")
    for name in ("public_rights_registry.json", "public_pii_registry.json"):
        entries = sidecars[name].get("entries")
        if (not isinstance(entries, list) or len(entries) != 253
                or {row.get("content_sha256") for row in entries} != set(artifact_by_sha)
                or any(row.get("source_pdf_sha256") != artifact_by_sha[row["content_sha256"]]["source_pdf_sha256"]
                       or row.get("derivative_receipt_sha256") != artifact_by_sha[row["content_sha256"]]["derivative_receipt_sha256"]
                       for row in entries)):
            raise ValueError(f"successor {name} derivative population differs")
    release_registry_path = release_root.parent / "release-registry.json"
    release_registry = read(release_registry_path)
    if release_registry.get("releases") != [{
        "release_id": aggregate["release_id"],
        "collections": sorted(profiles),
        "manifest_path": f"{release_root.name}/production-profile-gate.release.json",
        "expected_manifest_sha256": _sha(documents[aggregate_path]),
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
    }]:
        raise ValueError("successor release registry binding invalid")
    allowed = {
        aggregate_path, registry_path, release_registry_path,
        *(release_root / name for name in sidecars),
        *(release_root / ref["path"] for ref in subject_refs),
    }
    if set(documents) != allowed or any(path.suffix == ".pdf" for path in documents):
        raise ValueError("successor release contains unexpected material")
    return {
        "collections": 11, "artifacts": 253, "placements": 377,
        "chunks": total_chunks, "public_pdf_count": 0,
    }


def write_successor_documents(
    documents: Mapping[Path, bytes],
    private_documents: Mapping[Path, bytes],
    release_root: Path,
    private_root: Path,
) -> None:
    """Installer une nouvelle candidate et son store privé, sans écraser l'existant."""
    registry_path = release_root.parent / "release-registry.json"
    if any(".." in root.parts for root in (release_root, private_root)):
        raise ValueError("output root path traversal")
    if release_root.exists() or private_root.exists() or registry_path.exists():
        raise FileExistsError("successor release output already exists")
    for path in documents:
        if path == registry_path:
            continue
        if not path.is_relative_to(release_root) or ".." in path.relative_to(release_root).parts:
            raise ValueError("release document escaped its output root")
    for path in private_documents:
        if not path.is_relative_to(private_root) or ".." in path.relative_to(private_root).parts:
            raise ValueError("private material escaped its output root")
    for root in (release_root, private_root):
        if any(parent.is_symlink() for parent in (root, *root.parents)):
            raise ValueError("output root symlink traversal")
    if registry_path not in documents:
        raise ValueError("successor release registry missing")
    release_root.parent.mkdir(parents=True, exist_ok=True)
    private_root.parent.mkdir(parents=True, exist_ok=True)
    staged_release = Path(tempfile.mkdtemp(prefix=".student-release-", dir=release_root.parent))
    staged_private = Path(tempfile.mkdtemp(prefix=".student-store-", dir=private_root.parent))
    installed_release = False
    installed_private = False
    created_registry = False
    try:
        for path, raw in documents.items():
            if path == registry_path:
                continue
            target = staged_release / path.relative_to(release_root)
            if not target.resolve().is_relative_to(staged_release.resolve()):
                raise ValueError("release document escaped staged output root")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        for path, raw in private_documents.items():
            target = staged_private / path.relative_to(private_root)
            if not target.resolve().is_relative_to(staged_private.resolve()):
                raise ValueError("private material escaped staged output root")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            target.chmod(0o600)
        if release_root.exists() or private_root.exists() or registry_path.exists():
            raise FileExistsError("successor release output appeared during staging")
        staged_private.rename(private_root)
        installed_private = True
        staged_release.rename(release_root)
        installed_release = True
        descriptor = os.open(registry_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        created_registry = True
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(documents[registry_path])
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if created_registry:
            registry_path.unlink(missing_ok=True)
        if installed_release:
            shutil.rmtree(release_root)
        if installed_private:
            shutil.rmtree(private_root)
        raise
    finally:
        if staged_release.exists():
            shutil.rmtree(staged_release)
        if staged_private.exists():
            shutil.rmtree(staged_private)


def main(argv: list[str] | None = None) -> int:
    """Rejouer les portes live avant de produire une nouvelle candidate isolée."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--authority-root", type=Path, required=True,
                        help="checkout propre au HEAD scellé de la PR #300")
    parser.add_argument("--private-candidate-root", type=Path, required=True)
    parser.add_argument("--source-mirror-root", type=Path, required=True)
    parser.add_argument("--embedding-snapshot", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = args.repository_root.resolve()
    authority_root = args.authority_root.resolve()
    authority_module_root = str(authority_root / "scripts/go_live")
    sys.path.insert(0, authority_module_root)
    from check_delegated_student_rights_gate import check_gate
    source_head, gate = run_approved_source_gate(
        authority_root=authority_root,
        gate_runner=check_gate,
        source_mirror_root=args.source_mirror_root.resolve(),
        private_candidate_root=args.private_candidate_root.resolve(),
    )
    print("SOURCE_DELEGATED_RIGHTS_ADJUDICATION_PASS=true", flush=True)
    print(f"SOURCE_FULL_DOCUMENT_SCAN_COUNT={gate['FULL_DOCUMENT_SCAN_COUNT']}", flush=True)
    print(f"SOURCE_EVIDENCE_PACK_SHA256={gate['EVIDENCE_PACK_SHA256']}", flush=True)
    sys.path.remove(authority_module_root)
    sys.path.insert(0, str(root / "scripts/go_live"))
    from pr300_authority_receipt import check_pr300_authority
    from public_rights_release_guard import require_public_release_rights

    # L'autorité documentaire est relue sur le HEAD source propre. Le
    # constructeur, lui, peut être dans le worktree de la future PR.
    authority = check_pr300_authority(root)
    token_counter = PinnedE5TokenCounter(args.embedding_snapshot.resolve())
    documents, private_documents = build_successor_documents(
        repository_root=root,
        private_candidate_root=args.private_candidate_root.resolve(),
        release_root=args.release_root.resolve(),
        private_root=args.private_output_root.resolve(),
        release_id=args.release_id, token_counter=token_counter,
        authority_approval=authority, rights_gate=gate,
    )
    lineage = {
        path: raw for path, raw in private_documents.items()
        if "chunk_lineage" in path.parts
    }
    verify_successor_metadata(documents, args.release_root.resolve())
    # `gate` provient du check_gate canonique rejoué plus haut dans ce même
    # processus. Une sortie mise en cache externe ne constitue pas une autorité.
    guard = require_public_release_rights(
        documents, repository_root=root,
        source_mirror_root=args.source_mirror_root.resolve(),
        private_candidate_root=args.private_candidate_root.resolve(),
        expected_head=source_head,
        token_counter=token_counter,
        private_lineage_documents=lineage,
        rights_gate_result=gate,
    )
    if guard.get("PUBLIC_RIGHTS_GATE_PASS") is not True:
        raise ValueError("successor public rights guard did not pass")
    aggregate_path = args.release_root.resolve() / "production-profile-gate.release.json"
    aggregate = json.loads(documents[aggregate_path])
    print("DELEGATED_RIGHTS_ADJUDICATION_PASS=true")
    print(f"FULL_DOCUMENT_SCAN_COUNT={gate['FULL_DOCUMENT_SCAN_COUNT']}")
    print(f"DUAL_REVIEW_COUNT={gate['DUAL_REVIEW_COUNT']}")
    print(f"EVIDENCE_PACK_SHA256={gate['EVIDENCE_PACK_SHA256']}")
    print(f"RELEASE_ID={args.release_id}")
    for key, value in aggregate["expected_counts"].items():
        print(f"{key.upper()}={value}")
    print(f"AGGREGATE_SHA256={_sha(documents[aggregate_path])}")
    print("PUBLIC_RIGHTS_GATE_PASS=true")
    if args.dry_run:
        print("DRY_RUN=true")
        return 0
    write_successor_documents(
        documents, private_documents,
        args.release_root.resolve(), args.private_output_root.resolve(),
    )
    print("SUCCESSOR_CANDIDATE_WRITTEN=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
