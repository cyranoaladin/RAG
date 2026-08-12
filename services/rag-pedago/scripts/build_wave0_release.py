#!/usr/bin/env python3
"""Construire l'autorité release Wave 0 exacte avant toute écriture produit.

Le module garde les décisions métier dans les artefacts versionnés. Les octets
PDF, caches de modèles et preuves de scan restent fournis explicitement par
l'appelant et ne sont jamais copiés dans Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

INVENTORY_KIND = "WAVE0_EXACT_GRADE_CANDIDATE_INVENTORY_V1"
SUBJECT_RELEASE_KIND = "WAVE0_SUBJECT_RELEASE_V1"
AGGREGATE_RELEASE_KIND = "WAVE0_AGGREGATE_RELEASE_V1"
SCHOOL_YEAR = "2026-2027"
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
EMBEDDING_INVENTORY_SHA256 = (
    "e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a"
)
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_INVENTORY_SHA256 = (
    "bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1"
)
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_EXACT_SCOPES = {
    "francais": "college/cycle-4/francais",
    "mathematiques": "college/cycle-4/mathematiques",
}
_COLLECTIONS = {
    "francais": "rag_nexus_francais_troisieme_tc",
    "mathematiques": "rag_nexus_maths_troisieme_tc",
}
_TYPE_DOC = {"reperes-attendus": "ressource_officielle"}


def canonical_json_bytes(value: object) -> bytes:
    """Sérialisation fichier reproductible, UTF-8, triée, terminée par LF."""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def set_digest(values: Sequence[object]) -> str:
    if len(values) != len({compact_json_bytes(value) for value in values}):
        raise ValueError("canonical set contains duplicates")
    ordered = sorted(values, key=compact_json_bytes)
    return sha256_bytes(compact_json_bytes(ordered))


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 64-hex SHA-256")
    return value


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _require_nonblank(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonblank")
    return value


def build_candidate_inventory(
    catalog: dict[str, Any],
    *,
    sealed_catalog_sha256: str,
    school_year: str,
) -> dict[str, Any]:
    """Filtrer exhaustivement les placements PDF Éduscol de niveau exact 3e."""
    _require_sha(sealed_catalog_sha256, "sealed catalog SHA")
    if school_year != SCHOOL_YEAR:
        raise ValueError(f"school_year must be {SCHOOL_YEAR}")
    if catalog.get("catalog_kind") != "REAL_SEALED_CORPUS":
        raise ValueError("sealed catalog kind is invalid")
    if catalog.get("verification_passed") is not True:
        raise ValueError("sealed catalog is not verified")
    corpus_manifest_sha = _require_sha(
        catalog.get("manifest_sha256"), "corpus manifest SHA"
    )
    placement_catalog_sha = _require_sha(
        catalog.get("placement_catalog_sha256"), "placement catalog SHA"
    )
    artifacts = _require_mapping(catalog.get("artifacts"), "catalog artifacts")

    candidates: list[dict[str, Any]] = []
    physical_by_sha: dict[str, str] = {}
    placement_keys: set[tuple[str, str]] = set()
    for content_sha256, raw_artifact in artifacts.items():
        sha = _require_sha(content_sha256, "artifact key")
        artifact = _require_mapping(raw_artifact, f"artifact {sha}")
        placements = artifact.get("pedagogical_placements")
        if not isinstance(placements, list):
            raise ValueError(f"artifact {sha} placements must be a list")
        selected: list[Mapping[str, Any]] = []
        for raw_placement in placements:
            placement = _require_mapping(raw_placement, f"artifact {sha} placement")
            subject = placement.get("subject")
            if (
                placement.get("level") == "3e"
                and isinstance(subject, str)
                and subject in _EXACT_SCOPES
                and placement.get("scope") == _EXACT_SCOPES[subject]
            ):
                selected.append(placement)
        if not selected:
            continue

        physical_objects = artifact.get("physical_objects")
        if not isinstance(physical_objects, list) or len(physical_objects) != 1:
            raise ValueError(f"artifact {sha} must have exactly one physical object")
        physical = _require_mapping(physical_objects[0], f"artifact {sha} physical object")
        if physical.get("content_sha256") != sha:
            raise ValueError(f"artifact {sha} physical object SHA differs")
        physical_path = _require_nonblank(physical.get("path"), "physical path")
        if not physical_path.startswith("01_EDUSCOL_OFFICIEL/") or not physical_path.endswith(
            ".pdf"
        ):
            raise ValueError(f"artifact {sha} is not an official Eduscol PDF")
        physical_by_sha[sha] = physical_path

        for placement in selected:
            if placement.get("content_sha256") != sha:
                raise ValueError(f"artifact {sha} placement SHA differs")
            source_placement_id = _require_nonblank(
                placement.get("scope_path"), "source placement id"
            )
            placement_key = (sha, source_placement_id)
            if placement_key in placement_keys:
                raise ValueError(f"artifact {sha} has a duplicate pedagogical placement")
            placement_keys.add(placement_key)
            candidates.append(
                {
                    "content_sha256": sha,
                    "physical_path": physical_path,
                    "source_url": _require_nonblank(
                        placement.get("source_url"), "source URL"
                    ),
                    "title": _require_nonblank(placement.get("title"), "title"),
                    "external_scope": str(placement["scope"]),
                    "external_level": "3e",
                    "external_subject": str(placement["subject"]),
                    "external_document_type": _require_nonblank(
                        placement.get("document_type"), "document type"
                    ),
                    "pedagogical_status": _require_nonblank(
                        placement.get("status"), "pedagogical status"
                    ),
                    "physical_currentness_candidate": str(
                        physical.get("currentness", "")
                    ),
                    "physical_disposition_candidate": str(
                        physical.get("disposition", "")
                    ),
                    "source_placement_id": source_placement_id,
                }
            )

    candidates.sort(key=lambda row: (row["content_sha256"], row["source_placement_id"]))
    if not candidates:
        raise ValueError("exact-grade Wave 0 inventory is empty")
    unique_shas = {row["content_sha256"] for row in candidates}
    counts_by_subject: dict[str, dict[str, int]] = {}
    for subject in sorted(_EXACT_SCOPES):
        subject_rows = [row for row in candidates if row["external_subject"] == subject]
        counts_by_subject[subject] = {
            "unique_artifacts": len({row["content_sha256"] for row in subject_rows}),
            "placements": len(subject_rows),
        }
    return {
        "inventory_kind": INVENTORY_KIND,
        "school_year": school_year,
        "corpus_manifest_sha256": corpus_manifest_sha,
        "sealed_catalog_sha256": sealed_catalog_sha256,
        "placement_catalog_sha256": placement_catalog_sha,
        "selection": {
            "external_level": "3e",
            "external_subjects": ["francais", "mathematiques", "maths"],
            "source_zone": "01_EDUSCOL_OFFICIEL/",
            "media_type": "application/pdf",
        },
        "counts": {
            "unique_artifacts": len(unique_shas),
            "placements": len(candidates),
            "physical_objects": len(physical_by_sha),
            "multi_placement_artifacts": sum(
                1
                for sha in unique_shas
                if sum(row["content_sha256"] == sha for row in candidates) > 1
            ),
            "by_subject": counts_by_subject,
        },
        "candidates": candidates,
    }


def build_full_pii_evidence(
    source_scan: dict[str, Any],
    *,
    source_scan_sha256: str,
    candidate_inventory_sha256: str,
    candidate_content_sha256: set[str],
) -> dict[str, Any]:
    """Lier un scan exact déjà immuable à l'inventaire full Wave 0."""
    _require_sha(source_scan_sha256, "source scan evidence SHA")
    _require_sha(candidate_inventory_sha256, "candidate inventory SHA")
    if source_scan.get("evidence_kind") != "REAL_CORPUS_PII_SCAN":
        raise ValueError("source PII evidence kind is invalid")
    for field in ("corpus_manifest_sha256", "policy_sha256", "scanner_sha256"):
        _require_sha(source_scan.get(field), field)
    if source_scan.get("remote_access_mode") != "READ_ONLY":
        raise ValueError("PII scan was not read-only")
    if source_scan.get("remote_write_operations") != 0:
        raise ValueError("PII scan reports remote writes")
    if source_scan.get("raw_pii_in_output") is not False or source_scan.get(
        "raw_pii_in_logs"
    ) is not False:
        raise ValueError("PII scan may expose raw PII")
    results = source_scan.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("PII scan carries no results")
    ordered = sorted(results, key=lambda row: str(row.get("content_sha256", "")))
    seen: set[str] = set()
    for row in ordered:
        if not isinstance(row, Mapping):
            raise ValueError("PII result is malformed")
        sha = _require_sha(row.get("content_sha256"), "PII result SHA")
        if sha in seen:
            raise ValueError("PII scan contains a duplicate SHA")
        seen.add(sha)
    if seen != candidate_content_sha256:
        raise ValueError("PII scan content differs from the exact candidate set")
    summary = _require_mapping(source_scan.get("summary"), "PII scan summary")
    if (
        summary.get("pii_scan_required") != len(ordered)
        or summary.get("pii_scanned") != len(ordered)
        or summary.get("pii_not_scanned") != 0
        or summary.get("sha256_mismatches") != 0
        or float(summary.get("pii_scan_coverage", 0.0)) != 1.0
    ):
        raise ValueError("PII source scan does not have exact full coverage")
    document = dict(source_scan)
    document["candidate_inventory_sha256"] = candidate_inventory_sha256
    document["source_scan_evidence_sha256"] = source_scan_sha256
    document["scan_scope"] = "WAVE0_EXACT_GRADE_3E_UNIQUE_ARTIFACTS"
    document["results"] = [dict(row) for row in ordered]
    document["required_pdf_path_count"] = len(ordered)
    document["summary"] = {
        **dict(summary),
        "pdf_total": len(ordered),
        "pii_scan_scope": "WAVE0_EXACT_GRADE_3E_UNIQUE_ARTIFACTS",
        "pii_scan_required": len(ordered),
        "pii_scan_exempt": 0,
        "pii_scanned": len(ordered),
        "unique_content_attempted": len(ordered),
        "unique_pdf_content": len(ordered),
    }
    return document


def evaluate_release_candidates(
    inventory: dict[str, Any],
    *,
    currentness_by_sha: dict[str, dict[str, Any]],
    pii_by_sha: dict[str, dict[str, Any]],
    rights_by_sha: dict[str, str],
    preflight_by_sha: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Évaluer tous les SHA; tout échec devient un reason code, jamais un arrêt batch."""
    candidates = inventory.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidate inventory is empty")
    shas = sorted({str(row["content_sha256"]) for row in candidates})
    by_content: dict[str, dict[str, Any]] = {}
    for sha in shas:
        rows = [row for row in candidates if row["content_sha256"] == sha]
        reasons: list[str] = []
        currentness = currentness_by_sha.get(sha)
        if not currentness or currentness.get("effective_currentness") != "actuel":
            reasons.append("CURRENTNESS_NOT_CURRENT")
        elif (
            currentness.get("current_for_school_year") != inventory.get("school_year")
            or currentness.get("exact_path") != rows[0]["physical_path"]
        ):
            reasons.append("CURRENTNESS_SCOPE_MISMATCH")
        pii = pii_by_sha.get(sha)
        if not pii or pii.get("status") != "CLEARED" or pii.get("pii_detected") is not False:
            reasons.append("PII_NOT_CLEARED")
        if rights_by_sha.get(sha) != "officiel_public":
            reasons.append("RIGHTS_NOT_CLEARED")
        preflight = preflight_by_sha.get(sha)
        if not preflight:
            reasons.append("PREFLIGHT_NOT_EVALUATED")
        else:
            if (
                preflight.get("extraction_complete") is not True
                or int(preflight.get("page_count", 0)) <= 0
                or preflight.get("empty_extracted_pages") != 0
            ):
                reasons.append("EXTRACTION_INCOMPLETE")
            if preflight.get("placement_clear") is not True:
                reasons.append("PLACEMENT_AMBIGUOUS")
            if preflight.get("programme_conformity") is not True:
                reasons.append("PROGRAMME_NOT_CONFORM")
            if preflight.get("profile_conformity") is not True:
                reasons.append("PROFILE_NOT_CONFORM")
            if (
                preflight.get("chunking_complete") is not True
                or float(preflight.get("page_coverage", 0.0)) != 1.0
                or preflight.get("empty_chunks") != 0
                or preflight.get("oversized_model_chunks") != 0
                or preflight.get("null_page_metadata") != 0
            ):
                reasons.append("CHUNKING_INCOMPLETE")
        by_content[sha] = {
            "release_eligible": not reasons,
            "reason_codes": reasons,
            "placement_count": len(rows),
        }
    eligible = sum(row["release_eligible"] for row in by_content.values())
    return {
        "counts": {
            "candidates": len(shas),
            "release_eligible": eligible,
            "review_required": len(shas) - eligible,
        },
        "by_content": by_content,
    }


def _manifest_artifact(
    candidate_rows: list[dict[str, Any]],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    sha = candidate_rows[0]["content_sha256"]
    placements = preflight.get("placements")
    chunks = preflight.get("chunks")
    if not isinstance(placements, list) or not placements:
        raise ValueError(f"artifact {sha} has no expected placement")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError(f"artifact {sha} has no expected chunks")
    placements = sorted((dict(row) for row in placements), key=lambda row: row["placement_id"])
    chunks = sorted((dict(row) for row in chunks), key=lambda row: row["chunk_index"])
    if [row["chunk_index"] for row in chunks] != list(range(len(chunks))):
        raise ValueError(f"artifact {sha} chunk indexes are not contiguous")
    placement_ids = [_require_sha(row.get("placement_id"), "placement ID") for row in placements]
    chunk_ids = [_require_sha(row.get("chunk_id"), "chunk ID") for row in chunks]
    chunk_shas = [_require_sha(row.get("chunk_sha256"), "chunk SHA") for row in chunks]
    pages: set[int] = set()
    for row in chunks:
        start, end = row.get("page_start"), row.get("page_end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            raise ValueError(f"artifact {sha} chunk page metadata is invalid")
        pages.update(range(start, end + 1))
    page_count = int(preflight.get("page_count", 0))
    if pages != set(range(1, page_count + 1)):
        raise ValueError(f"artifact {sha} page coverage is incomplete")
    first = candidate_rows[0]
    if any(
        row["physical_path"] != first["physical_path"]
        or row["source_url"] != first["source_url"]
        or row["title"] != first["title"]
        for row in candidate_rows
    ):
        raise ValueError(f"artifact {sha} physical metadata differs between placements")
    external_type = str(first["external_document_type"])
    try:
        type_doc = _TYPE_DOC[external_type]
    except KeyError as exc:
        raise ValueError(f"unknown external document type {external_type!r}") from exc
    return {
        "content_sha256": sha,
        "source_path": first["physical_path"],
        "source_url": first["source_url"],
        "title": first["title"],
        "type_doc": type_doc,
        "page_count": page_count,
        "placements": placements,
        "chunks": chunks,
        "placement_id_set_digest": set_digest(placement_ids),
        "chunk_id_set_digest": set_digest(chunk_ids),
        "chunk_sha256_set_digest": set_digest(chunk_shas),
        "page_coverage_digest": set_digest(sorted(pages)),
    }


def build_subject_release_manifest(
    *,
    subject: str,
    inventory: dict[str, Any],
    eligibility: dict[str, Any],
    artifact_preflights: dict[str, dict[str, Any]],
    authorities: dict[str, str],
    profile: dict[str, str],
    models: dict[str, Any],
) -> dict[str, Any]:
    if subject not in _COLLECTIONS:
        raise ValueError(f"unsupported Wave 0 subject {subject!r}")
    required_authorities = {
        "corpus_manifest_sha256",
        "sealed_catalog_sha256",
        "placement_catalog_sha256",
        "candidate_inventory_sha256",
        "currentness_evidence_sha256",
        "pii_evidence_sha256",
        "pii_policy_sha256",
        "rights_registry_sha256",
    }
    if set(authorities) != required_authorities:
        raise ValueError("release authority set is incomplete or unexpected")
    for field, digest in authorities.items():
        _require_sha(digest, field)
    if models.get("embedding") != {
        "model_id": EMBEDDING_MODEL,
        "inventory_sha256": EMBEDDING_INVENTORY_SHA256,
        "dimension": 1024,
    }:
        raise ValueError("embedding model authority differs from canonical E5")
    if models.get("reranker") != {
        "model_id": RERANKER_MODEL,
        "inventory_sha256": RERANKER_INVENTORY_SHA256,
    }:
        raise ValueError("reranker model authority differs from canonical model")
    for field in ("fingerprint", "manifest_digest"):
        _require_sha(profile.get(field), f"profile {field}")
    candidates = inventory.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("inventory candidates are absent")
    subject_rows = [row for row in candidates if row["external_subject"] == subject]
    by_sha: dict[str, list[dict[str, Any]]] = {}
    for row in subject_rows:
        if eligibility["by_content"].get(row["content_sha256"], {}).get(
            "release_eligible"
        ):
            by_sha.setdefault(row["content_sha256"], []).append(row)
    artifacts = [
        _manifest_artifact(rows, artifact_preflights[sha])
        for sha, rows in sorted(by_sha.items())
    ]
    if not artifacts:
        raise ValueError(f"subject {subject} has no release-eligible artifact")
    placement_count = sum(len(row["placements"]) for row in artifacts)
    chunk_count = sum(len(row["chunks"]) for row in artifacts)
    collection = _COLLECTIONS[subject]
    if any(
        placement["collection"] != collection
        for artifact in artifacts
        for placement in artifact["placements"]
    ):
        raise ValueError("expected placement collection differs from release subject")
    return {
        "release_kind": SUBJECT_RELEASE_KIND,
        "release_id": f"wave0-{subject}-troisieme-2026-2027-v1",
        "school_year": SCHOOL_YEAR,
        "collection": collection,
        "programme_version": "BOEN_special_11_2018-07-26_aj_2020",
        "authorities": dict(sorted(authorities.items())),
        "profile": {
            "version": _require_nonblank(profile.get("version"), "profile version"),
            "fingerprint": profile["fingerprint"],
            "manifest_digest": profile["manifest_digest"],
        },
        "models": models,
        "expected_counts": {
            "artifacts": len(artifacts),
            "placements": placement_count,
            "chunks": chunk_count,
        },
        "artifacts": artifacts,
    }


def build_aggregate_release_manifest(
    *,
    subjects: Sequence[tuple[str, str, dict[str, Any]]],
    authorities: dict[str, str],
    models: dict[str, Any],
) -> dict[str, Any]:
    if len(subjects) != 2:
        raise ValueError("Wave 0 aggregate requires exactly two subject releases")
    references: list[dict[str, str]] = []
    counts = {"artifacts": 0, "placements": 0, "chunks": 0}
    collections: set[str] = set()
    for path, sha, manifest in sorted(subjects, key=lambda item: item[2]["collection"]):
        _require_sha(sha, "subject release SHA")
        if manifest.get("release_kind") != SUBJECT_RELEASE_KIND:
            raise ValueError("aggregate subject release kind is invalid")
        collection = str(manifest["collection"])
        if collection in collections:
            raise ValueError("aggregate collection is duplicated")
        collections.add(collection)
        references.append({"path": path, "sha256": sha, "collection": collection})
        for field in counts:
            counts[field] += int(manifest["expected_counts"][field])
    return {
        "release_kind": AGGREGATE_RELEASE_KIND,
        "release_id": "wave0-exact-grade-troisieme-2026-2027-v1",
        "school_year": SCHOOL_YEAR,
        "authorities": dict(sorted(authorities.items())),
        "models": models,
        "expected_counts": counts,
        "subjects": references,
    }


def write_canonical_json(path: Path, document: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(document)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def _inventory_cli(args: argparse.Namespace) -> int:
    catalog_path = Path(args.catalog)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    inventory = build_candidate_inventory(
        catalog,
        sealed_catalog_sha256=_require_sha(args.catalog_sha256, "catalog SHA"),
        school_year=args.school_year,
    )
    digest = write_canonical_json(Path(args.output), inventory)
    print(f"CANDIDATE_INVENTORY_SHA256={digest}")
    print(f"WAVE0_UNIQUE_ARTIFACTS={inventory['counts']['unique_artifacts']}")
    print(f"WAVE0_PLACEMENTS={inventory['counts']['placements']}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--catalog", required=True)
    inventory.add_argument("--catalog-sha256", required=True)
    inventory.add_argument("--school-year", default=SCHOOL_YEAR)
    inventory.add_argument("--output", required=True)
    inventory.set_defaults(handler=_inventory_cli)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
