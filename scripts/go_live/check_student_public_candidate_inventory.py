#!/usr/bin/env python3
"""Contrôle indépendant de l'inventaire texte et de son allowlist non transférée."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from prepare_student_public_candidate_inventory import (
    DEFAULT_OUTPUT,
    TEXT_MIME,
    canonical,
    digest,
    load_sealed_inputs,
)

SHA = re.compile(r"[0-9a-f]{64}\Z")
INVENTORY_FIELDS = {
    "inventory_kind", "release_id", "release_manifest_sha256",
    "artifact_registry_sha256", "candidate_manifest_sha256",
    "source_candidate_inventory_sha256", "counts", "collections",
}
SOURCE_FIELDS = {
    "source_placement_id", "source_url", "title", "external_level",
    "external_subject", "external_scope", "external_document_type",
    "year", "placement_origin", "placement_reason_code",
}


def _exact(row: object, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(row, dict) or set(row) != fields:
        raise ValueError(f"{label} fields differ")
    return row


def verify_bundle(
    root: Path, inventory: Mapping[str, Any], allowlist: Mapping[str, Any]
) -> dict[str, int]:
    inputs = load_sealed_inputs(root)
    inv = _exact(inventory, INVENTORY_FIELDS, "candidate inventory")
    release = inputs["release"]
    if (
        inv["inventory_kind"] != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_INVENTORY_V1"
        or inv["release_id"] != release["release_id"]
        or inv["release_manifest_sha256"] != inputs["release_sha256"]
        or inv["artifact_registry_sha256"] != inputs["artifact_registry_sha256"]
        or inv["candidate_manifest_sha256"] != inputs["candidate_manifest_sha256"]
        or inv["source_candidate_inventory_sha256"] != inputs["source_inventory_sha256"]
    ):
        raise ValueError("candidate inventory sealed authorities differ")
    artifact_rows = inputs["artifacts"]["artifacts"]
    artifact_by_sha = {row["content_sha256"]: row for row in artifact_rows}
    manifest_rows = inputs["candidate_manifest"]["entries"]
    manifest_by_sha = {row["derivative_content_sha256"]: row for row in manifest_rows}
    if (len(artifact_by_sha) != 253 or len(manifest_by_sha) != 253
            or set(artifact_by_sha) != set(manifest_by_sha)):
        raise ValueError("derivative source population differs")
    source_by_key: dict[tuple[str, str], tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for version, source in inputs["source_inventories"].items():
        for collection in source["collections"]:
            collection_id = collection["collection"]
            if ("hggsp" in collection_id) != (version == "v5"):
                continue
            for candidate in collection["candidates"]:
                for placement in candidate["placements"]:
                    key = collection_id, placement["source_placement_id"]
                    if key in source_by_key:
                        raise ValueError("source placement duplicate")
                    source_by_key[key] = candidate, placement
    expected_subjects = {row["collection"]: row for row in inputs["subjects"]}
    collections = inv["collections"]
    if (not isinstance(collections, list) or len(collections) != 11
            or [row.get("collection") for row in collections] != sorted(expected_subjects)):
        raise ValueError("candidate inventory collection population differs")
    seen_shas: set[str] = set()
    collections_by_sha: dict[str, set[str]] = {}
    seen_placements: set[tuple[str, str]] = set()
    for collection in collections:
        row = _exact(collection, {"collection", "candidates"}, "collection")
        collection_id = row["collection"]
        subject = expected_subjects[collection_id]
        expected_pairs = {
            (placement["artifact_id"], placement["source_placement_id"])
            for placement in subject["placements"]
        }
        candidates = row["candidates"]
        if (not isinstance(candidates, list) or not candidates
                or [item.get("content_sha256") for item in candidates]
                    != sorted(item.get("content_sha256") for item in candidates)):
            raise ValueError("candidate order or population differs")
        observed_pairs: set[tuple[str, str]] = set()
        for candidate in candidates:
            item = _exact(candidate, {
                "content_sha256", "source_pdf_sha256", "physical_path",
                "media_type", "derivative_receipt_sha256", "placements",
            }, "candidate")
            sha = item["content_sha256"]
            if (not isinstance(sha, str) or SHA.fullmatch(sha) is None
                    or sha not in artifact_by_sha):
                raise ValueError("candidate derivative SHA absent")
            artifact = artifact_by_sha[sha]
            manifest = manifest_by_sha[sha]
            if (item["source_pdf_sha256"] != artifact["source_pdf_sha256"]
                    or sha == item["source_pdf_sha256"]
                    or item["physical_path"] != f"{sha}.txt"
                    or item["media_type"] != TEXT_MIME
                    or artifact.get("media_type") != TEXT_MIME
                    or item["derivative_receipt_sha256"] != artifact["derivative_receipt_sha256"]
                    or manifest.get("source_content_sha256") != artifact["source_pdf_sha256"]
                    or manifest.get("private_candidate_relpath") != f"candidates/{sha}.txt"):
                raise ValueError("candidate text path or derivative provenance differs")
            placements = item["placements"]
            if (not isinstance(placements, list) or not placements
                    or [p.get("source_placement_id") for p in placements]
                        != sorted(p.get("source_placement_id") for p in placements)):
                raise ValueError("candidate placement order or population differs")
            for placement in placements:
                source_row = _exact(placement, SOURCE_FIELDS, "source placement")
                source_id = source_row["source_placement_id"]
                pair = sha, source_id
                source_key = collection_id, source_id
                if pair in observed_pairs or source_key not in source_by_key:
                    raise ValueError("source placement absent or duplicate")
                source_artifact, original = source_by_key[source_key]
                if source_artifact["content_sha256"] != artifact["source_pdf_sha256"]:
                    raise ValueError("source PDF SHA differs")
                if any(source_row[name] != original[name] for name in SOURCE_FIELDS):
                    raise ValueError("source URL or provenance differs")
                if (not source_row["source_url"].startswith(
                        "https://eduscol.education.gouv.fr/")
                        or source_row["title"] != artifact["title"]):
                    raise ValueError("source URL or title differs")
                observed_pairs.add(pair)
                if (collection_id, source_id) in seen_placements:
                    raise ValueError("source placement duplicate across candidates")
                seen_placements.add((collection_id, source_id))
            seen_shas.add(sha)
            collections_by_sha.setdefault(sha, set()).add(collection_id)
        if observed_pairs != expected_pairs:
            raise ValueError("source placement set differs from sealed subject")
    if (seen_shas != set(artifact_by_sha) or len(seen_placements) != 377
            or inv["counts"] != {
                "collections": 11, "unique_artifacts": 253, "placements": 377,
            }):
        raise ValueError("candidate inventory exact population differs")
    if any(
        sorted(collections_by_sha[sha]) != manifest_by_sha[sha].get("collections")
        for sha in artifact_by_sha
    ):
        raise ValueError("derivative collection scope differs")

    allowed = _exact(allowlist, {
        "kind", "release_id", "candidate_inventory_sha256", "transfer_status",
        "allowed_file_count", "expected_files",
    }, "private transfer allowlist")
    if (allowed["kind"] != "NEXUS_STUDENT_PUBLIC_PRIVATE_TRANSFER_ALLOWLIST_V1"
            or allowed["release_id"] != release["release_id"]
            or allowed["candidate_inventory_sha256"] != digest(canonical(inventory))
            or allowed["transfer_status"] != "NOT_TRANSFERRED"
            or allowed["allowed_file_count"] != 253):
        raise ValueError("private transfer status or authority differs")
    expected_files = [
        {
            "file": f"{sha}.txt", "sha256_expected": sha,
            "source_private_relpath": f"candidates/{sha}.txt",
            "media_type": TEXT_MIME,
        }
        for sha in sorted(artifact_by_sha)
    ]
    if allowed["expected_files"] != expected_files:
        raise ValueError("private transfer allowlist includes observed or unexpected files")
    return {"collections": 11, "artifacts": 253, "placements": 377}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    directory = args.bundle_dir if args.bundle_dir.is_absolute() else root / args.bundle_dir
    paths = [directory / "candidate_inventory.json",
             directory / "private_transfer_allowlist.json"]
    parsed = []
    for path in paths:
        raw = path.read_bytes()
        document = json.loads(raw)
        if raw != canonical(document):
            raise ValueError(f"{path.name} was edited after generation")
        parsed.append(document)
    counts = verify_bundle(root, parsed[0], parsed[1])
    print("STUDENT_PUBLIC_CANDIDATE_INVENTORY_PASS=true")
    print(f"CANDIDATE_INVENTORY_SHA256={digest(paths[0].read_bytes())}")
    print(f"PRIVATE_TRANSFER_ALLOWLIST_SHA256={digest(paths[1].read_bytes())}")
    print("PRIVATE_TRANSFER_STATUS=NOT_TRANSFERRED")
    print(f"DERIVATIVE_ARTIFACTS={counts['artifacts']}")
    print(f"SOURCE_PLACEMENTS={counts['placements']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
