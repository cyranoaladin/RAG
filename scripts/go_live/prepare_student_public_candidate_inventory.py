#!/usr/bin/env python3
"""Préparer l'inventaire textuel #312 et une allowlist, sans attester un transfert.

Les PDF V4/V5 restent des preuves de provenance internes. Seuls les SHA des
dérivés textuels et leurs identifiants de placement source entrent au candidat.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DATA = Path("services/rag-pedago/data/releases/prerentree_2026_2027")
SUCCESSOR = DATA / "profile_gate_student_public_v1/release-eb39f6cd0423e184"
SOURCES = {
    "v4": DATA / "profile_gate_v4/release-024f8625ebfeb7ce/profile_gate",
    "v5": DATA / "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate",
}
DERIVATIVES = Path(
    "docs/reports/go_live/student_rights_evidence/"
    "public_derivative_candidate_manifest_20261010.json"
)
DEFAULT_OUTPUT = Path("docs/reports/go_live/student_public_inventory_preparation_20261010")
SHA = re.compile(r"[0-9a-f]{64}\Z")
TEXT_MIME = "text/plain; charset=utf-8"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(document: object) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _read(path: Path, expected: str | None = None) -> tuple[str, dict[str, Any]]:
    raw = path.read_bytes()
    observed = digest(raw)
    if expected is not None and observed != expected:
        raise ValueError(f"sealed digest differs: {path.name}")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise TypeError(f"sealed document malformed: {path.name}")
    return observed, document


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise ValueError(f"{label} is not a SHA-256")
    return value


def load_sealed_inputs(root: Path) -> dict[str, Any]:
    """Relire les digests nommés par les manifests, sans accès au CAS privé."""
    root = root.resolve()
    registry_path = root / SUCCESSOR / "release-registry.json"
    _, release_registry = _read(registry_path)
    releases = release_registry.get("releases")
    if not isinstance(releases, list) or len(releases) != 1:
        raise ValueError("successor release registry population differs")
    release_ref = releases[0]
    if not isinstance(release_ref, dict) or release_ref.get("manifest_path") != (
        "profile_gate/production-profile-gate.release.json"
    ):
        raise ValueError("successor release registry reference differs")
    release_sha, release = _read(
        root / SUCCESSOR / release_ref["manifest_path"],
        _sha(release_ref.get("expected_manifest_sha256"), "release manifest digest"),
    )
    if (release_ref.get("release_id") != release.get("release_id")
            or release.get("release_mode") != "candidate"
            or release.get("promotion_status") != "NOT_PROMOTABLE"
            or release.get("activation_status") != "NO_PRODUCTION_ACTIVATION"
            or release.get("review_status") != "PRE_REVIEW"):
        raise ValueError("successor candidate authority differs")
    artifact_ref = release.get("artifact_registry")
    if not isinstance(artifact_ref, dict) or artifact_ref.get("path") != "artifacts.release.json":
        raise ValueError("successor artifact reference differs")
    artifact_sha, artifacts = _read(
        root / SUCCESSOR / "profile_gate" / artifact_ref["path"],
        _sha(artifact_ref.get("sha256"), "artifact registry digest"),
    )
    subjects: list[dict[str, Any]] = []
    refs = release.get("subjects")
    if not isinstance(refs, list) or len(refs) != 11:
        raise ValueError("successor subject population differs")
    for ref in refs:
        if not isinstance(ref, dict) or ref.get("path") != (
            f"subjects/{ref.get('collection')}.release.json"
        ):
            raise ValueError("successor subject reference differs")
        _, subject = _read(
            root / SUCCESSOR / "profile_gate" / ref["path"],
            _sha(ref.get("sha256"), "subject digest"),
        )
        if subject.get("collection") != ref["collection"]:
            raise ValueError("successor subject collection differs")
        subjects.append(subject)
    authorities = release.get("authorities")
    if not isinstance(authorities, dict):
        raise TypeError("successor authorities absent")
    derivative_sha, candidate_manifest = _read(
        root / DERIVATIVES,
        _sha(authorities.get("candidate_manifest_sha256"), "candidate manifest digest"),
    )
    source_inventories: dict[str, dict[str, Any]] = {}
    source_shas: dict[str, str] = {}
    for version, source_root in SOURCES.items():
        _, source_registry = _read(root / source_root.parent / "release-registry.json")
        source_refs = source_registry.get("releases")
        if (not isinstance(source_refs, list) or len(source_refs) != 1
                or source_refs[0].get("manifest_path")
                    != "profile_gate/production-profile-gate.release.json"):
            raise ValueError(f"source {version} release registry differs")
        source_manifest_sha, source_release = _read(
            root / source_root / "production-profile-gate.release.json"
        )
        if source_manifest_sha != _sha(
            source_refs[0].get("expected_manifest_sha256"),
            f"source {version} release manifest digest",
        ):
            raise ValueError(f"source {version} release manifest digest differs")
        source_authorities = source_release.get("authorities")
        if not isinstance(source_authorities, dict):
            raise TypeError(f"source {version} authorities absent")
        source_shas[version], source_inventories[version] = _read(
            root / source_root / "candidate_inventory.json",
            _sha(source_authorities.get("candidate_inventory_sha256"),
                 f"source {version} inventory digest"),
        )
    return {
        "release": release,
        "release_sha256": release_sha,
        "artifacts": artifacts,
        "artifact_registry_sha256": artifact_sha,
        "subjects": subjects,
        "candidate_manifest": candidate_manifest,
        "candidate_manifest_sha256": derivative_sha,
        "source_inventories": source_inventories,
        "source_inventory_sha256": source_shas,
    }


def build_bundle(inputs: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Faire la jointure exacte (collection, source_placement_id, PDF source)."""
    release = inputs["release"]
    artifacts_raw = inputs["artifacts"].get("artifacts")
    entries = inputs["candidate_manifest"].get("entries")
    subjects = inputs["subjects"]
    if (not isinstance(artifacts_raw, list) or len(artifacts_raw) != 253
            or not isinstance(entries, list) or len(entries) != 253
            or not isinstance(subjects, list) or len(subjects) != 11):
        raise ValueError("candidate manifest or derivative population differs")
    artifacts: dict[str, dict[str, Any]] = {}
    for raw in artifacts_raw:
        if not isinstance(raw, dict):
            raise TypeError("derivative artifact malformed")
        sha = _sha(raw.get("content_sha256"), "derivative SHA")
        source_sha = _sha(raw.get("source_pdf_sha256"), "source PDF SHA")
        if (sha in artifacts or sha == source_sha or raw.get("artifact_id") != sha
                or raw.get("media_type") != TEXT_MIME
                or raw.get("source_path") != f"{sha}.txt"
                or raw.get("derivative_receipt_path") != (
                    f"derivative_receipts/{raw.get('derivative_receipt_sha256')}.json"
                )):
            raise ValueError("derivative text identity differs")
        artifacts[sha] = raw
    derivative_entries: dict[str, dict[str, Any]] = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise TypeError("candidate manifest derivative malformed")
        sha = _sha(raw.get("derivative_content_sha256"), "candidate derivative SHA")
        if sha in derivative_entries:
            raise ValueError("candidate manifest derivative duplicate")
        derivative_entries[sha] = raw
    if set(derivative_entries) != set(artifacts):
        raise ValueError("candidate manifest derivative set differs")
    for sha, artifact in artifacts.items():
        entry = derivative_entries[sha]
        citation = artifact.get("citation")
        if (entry.get("source_content_sha256") != artifact["source_pdf_sha256"]
                or entry.get("derivative_receipt_sha256") != artifact.get("derivative_receipt_sha256")
                or entry.get("private_candidate_relpath") != f"candidates/{sha}.txt"
                or entry.get("media_type") != TEXT_MIME
                or entry.get("derivative_disposition") != "APPROVE_PUBLIC"
                or entry.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
                or not isinstance(citation, dict)
                or {k: v for k, v in citation.items() if k != "source_pdf_sha256"}
                    != entry.get("citation")):
            raise ValueError("candidate manifest derivative provenance differs")

    source_index: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for version, source_inventory in inputs["source_inventories"].items():
        if source_inventory.get("inventory_kind") != "MULTILEVEL_CANDIDATE_INVENTORY_V1":
            raise ValueError("source inventory kind differs")
        for collection in source_inventory["collections"]:
            collection_id = collection["collection"]
            if ("hggsp" in collection_id) != (version == "v5"):
                continue
            for candidate in collection["candidates"]:
                for placement in candidate["placements"]:
                    key = (collection_id, placement["source_placement_id"])
                    if key in source_index:
                        raise ValueError("source placement duplicate")
                    source_index[key] = (candidate, placement)

    used_artifacts: set[str] = set()
    collections_by_sha: dict[str, set[str]] = defaultdict(set)
    placement_ids: set[str] = set()
    collection_rows: list[dict[str, Any]] = []
    for subject in sorted(subjects, key=lambda row: row["collection"]):
        collection_id = subject["collection"]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        rows = subject.get("placements")
        if not isinstance(rows, list) or not rows:
            raise ValueError("successor collection empty")
        for placement in rows:
            sha = placement.get("artifact_id")
            source_id = placement.get("source_placement_id")
            placement_id = placement.get("placement_id")
            if sha not in artifacts or not isinstance(source_id, str):
                raise ValueError("successor artifact or source placement absent")
            if placement_id in placement_ids:
                raise ValueError("successor placement duplicate")
            placement_ids.add(placement_id)
            key = (collection_id, source_id)
            if key not in source_index:
                raise ValueError("source placement absent from sealed V4/V5 inventory")
            original, source = source_index[key]
            artifact = artifacts[sha]
            if original.get("content_sha256") != artifact["source_pdf_sha256"]:
                raise ValueError("source PDF SHA differs from sealed placement")
            if (source.get("title") != artifact.get("title")
                    or source.get("external_scope") != placement.get("source_scope")
                    or source.get("external_level") != placement.get("niveau")
                    or source.get("external_subject") != placement.get("matiere")
                    or not isinstance(source.get("source_url"), str)
                    or not source["source_url"].startswith("https://eduscol.education.gouv.fr/")):
                raise ValueError("source placement provenance differs")
            grouped[sha].append({
                "source_placement_id": source_id,
                "source_url": source["source_url"],
                "title": source["title"],
                "external_level": source["external_level"],
                "external_subject": source["external_subject"],
                "external_scope": source["external_scope"],
                "external_document_type": source["external_document_type"],
                "year": source["year"],
                "placement_origin": source["placement_origin"],
                "placement_reason_code": source["placement_reason_code"],
            })
            used_artifacts.add(sha)
            collections_by_sha[sha].add(collection_id)
        collection_rows.append({
            "collection": collection_id,
            "candidates": [
                {
                    "content_sha256": sha,
                    "source_pdf_sha256": artifacts[sha]["source_pdf_sha256"],
                    "physical_path": f"{sha}.txt",
                    "media_type": TEXT_MIME,
                    "derivative_receipt_sha256": artifacts[sha]["derivative_receipt_sha256"],
                    "placements": sorted(grouped[sha], key=lambda row: row["source_placement_id"]),
                }
                for sha in sorted(grouped)
            ],
        })
    if (len(used_artifacts) != 253 or len(placement_ids) != 377
            or set(used_artifacts) != set(artifacts)
            or release.get("expected_counts") != {
                "subjects": 11, "unique_artifacts": 253,
                "placements": 377, "unique_chunks": 3975,
            }):
        raise ValueError("successor derivative or placement population differs")
    if any(
        sorted(collections_by_sha[sha]) != derivative_entries[sha].get("collections")
        for sha in artifacts
    ):
        raise ValueError("derivative collection scope differs from approved candidate")
    inventory = {
        "inventory_kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_INVENTORY_V1",
        "release_id": release["release_id"],
        "release_manifest_sha256": inputs["release_sha256"],
        "artifact_registry_sha256": inputs["artifact_registry_sha256"],
        "candidate_manifest_sha256": inputs["candidate_manifest_sha256"],
        "source_candidate_inventory_sha256": inputs["source_inventory_sha256"],
        "counts": {"collections": 11, "unique_artifacts": 253, "placements": 377},
        "collections": collection_rows,
    }
    allowlist = {
        "kind": "NEXUS_STUDENT_PUBLIC_PRIVATE_TRANSFER_ALLOWLIST_V1",
        "release_id": release["release_id"],
        "candidate_inventory_sha256": digest(canonical(inventory)),
        "transfer_status": "NOT_TRANSFERRED",
        "allowed_file_count": 253,
        "expected_files": [
            {
                "file": f"{sha}.txt",
                "sha256_expected": sha,
                "source_private_relpath": derivative_entries[sha]["private_candidate_relpath"],
                "media_type": TEXT_MIME,
            }
            for sha in sorted(artifacts)
        ],
    }
    return inventory, allowlist


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    inputs = load_sealed_inputs(root)
    inventory, allowlist = build_bundle(inputs)
    output.mkdir(parents=True, exist_ok=True)
    for name, document in (("candidate_inventory.json", inventory),
                           ("private_transfer_allowlist.json", allowlist)):
        path = output / name
        payload = canonical(document)
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError(f"existing {name} differs")
        else:
            path.write_bytes(payload)
    print(f"CANDIDATE_INVENTORY_SHA256={digest(canonical(inventory))}")
    print("PRIVATE_TRANSFER_STATUS=NOT_TRANSFERRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
