#!/usr/bin/env python3
"""Sceller un nouveau paquet successeur préparatoire, jamais une activation."""

from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from check_student_public_candidate_inventory import verify_bundle
from nexus_contracts.ingestion import CollectionProfile, collection_profile_fingerprint
from prepare_student_public_candidate_inventory import (
    DEFAULT_OUTPUT,
    SUCCESSOR,
    TEXT_MIME,
    canonical,
    digest,
    load_sealed_inputs,
)

PROFILE_DIR = Path("services/rag-engine/configs/ingestion_profiles/student_public_derivative_v1")
RELEASE_ROOT = Path(
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1"
)
BLOCKERS = [
    "EXACT_HEAD_SUCCESSOR_SCOPE_REVIEW",
    "FRESH_SOURCE_CURRENTNESS_AT_PROMOTION",
    "PRIVATE_BYTES_TRANSFER_RECEIPT",
    "SUCCESSOR_AUTHORIZATION_AND_BATCH_REVIEW",
]
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SIDECARS = {
    "public_profiles.json": "public_profile_registry_sha256",
    "public_rights_registry.json": "public_rights_registry_sha256",
    "public_pii_registry.json": "public_pii_registry_sha256",
}


def _json(raw: bytes, label: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict) or raw != canonical(value):
        raise ValueError(f"{label} canonical JSON differs")
    return value


def load_sources(root: Path) -> dict[str, Any]:
    """Vérifier le candidat #312, son inventaire et les onze profils proposés."""
    root = root.resolve()
    inputs = load_sealed_inputs(root)
    paths = [root / DEFAULT_OUTPUT / name for name in (
        "candidate_inventory.json", "private_transfer_allowlist.json",
    )]
    inventory, allowlist = (_json(path.read_bytes(), path.name) for path in paths)
    verify_bundle(root, inventory, allowlist)
    candidate = inputs["release"]
    candidate_root = root / SUCCESSOR / "profile_gate"
    sidecars = {}
    for name, authority in SIDECARS.items():
        raw = (candidate_root / name).read_bytes()
        if digest(raw) != candidate["authorities"].get(authority):
            raise ValueError(f"candidate {name} authority differs")
        document = _json(raw, name)
        if (document.get("release_id") != candidate.get("release_id")
                or document.get("status") != "CANDIDATE_NOT_AUTHORIZED"):
            raise ValueError(f"candidate {name} status differs")
        if (name == "public_rights_registry.json"
                and document.get("rights_authority_sha256")
                != candidate["authorities"]["rights_authority_sha256"]):
            raise ValueError("candidate global rights authority differs")
        sidecars[name] = document
    proposal_raw = (root / PROFILE_DIR / "public_profile_proposal.json").read_bytes()
    proposal = _json(proposal_raw, "profile proposal")
    if (proposal.get("status") != "PENDING_EXACT_HEAD_AUTHORITY_REVIEW"
            or proposal.get("candidate_release_id") != candidate.get("release_id")
            or proposal.get("candidate_manifest_sha256") != inputs["release_sha256"]
            or proposal.get("candidate_profile_registry_sha256")
            != candidate["authorities"]["public_profile_registry_sha256"]):
        raise ValueError("complete profile proposal authority differs")
    rows = proposal.get("entries")
    if not isinstance(rows, list) or len(rows) != 11:
        raise ValueError("complete profile population differs")
    profiles: dict[str, bytes] = {}
    profile_refs: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("complete profile row differs")
        collection = row.get("collection")
        if (not isinstance(collection, str) or collection in profiles
                or row.get("path") != f"{collection}.yml"):
            raise ValueError("complete profile population differs")
        raw = (root / PROFILE_DIR / row["path"]).read_bytes()
        if digest(raw) != row.get("sha256"):
            raise ValueError("complete profile digest differs")
        profile = CollectionProfile.model_validate(yaml.safe_load(raw))
        if (profile.scope.collection != collection
                or profile.scope.visibility != "public"
                or profile.profile_version != row.get("profile_version")
                or collection_profile_fingerprint(profile) != row.get("fingerprint")):
            raise ValueError("complete profile content differs")
        profiles[collection] = raw
        profile_refs[collection] = row
    if (set(profiles) != {subject["collection"] for subject in inputs["subjects"]}
            or set(profiles) != {row["collection"] for row in sidecars["public_profiles.json"]["entries"]}):
        raise ValueError("complete profile population differs")
    return {
        "inputs": inputs,
        "inventory": inventory,
        "allowlist": allowlist,
        "sidecars": sidecars,
        "profiles": profiles,
        "profile_refs": profile_refs,
        "profile_proposal_raw": proposal_raw,
        "profile_proposal_sha256": digest(proposal_raw),
    }


def validate_inclusions(source: dict[str, Any], inclusion: object) -> frozenset[str]:
    """Exiger une décision probante par SHA, sans assimiler ceci à une review de scope."""
    if inclusion is None:
        raise ValueError("inclusion attestation required")
    if not isinstance(inclusion, dict):
        raise TypeError("inclusion attestation malformed")
    inputs = source["inputs"]
    if (set(inclusion) != {
            "kind", "source_candidate_manifest_sha256", "source_candidate_inventory_sha256",
            "rights_authority_sha256",
            "pii_adjudication_report_sha256", "source_currentness_attestation_sha256",
            "fresh_source_index_file_sha256", "fresh_source_index_logical_sha256",
            "private_cas_manifest_sha256", "source_currentness_valid_until_utc",
            "decision_count", "evidence_pack_sha256", "decisions",
        } or inclusion["kind"] != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_INCLUSIONS_V2"
            or inclusion["source_candidate_manifest_sha256"]
            != inputs["candidate_manifest_sha256"]
            or inclusion["source_candidate_inventory_sha256"]
            != digest(canonical(source["inventory"]))
            or inclusion["rights_authority_sha256"]
            != inputs["release"]["authorities"]["rights_authority_sha256"]
            or any(not isinstance(inclusion[field], str)
                   or SHA256.fullmatch(inclusion[field]) is None
                   for field in (
                       "pii_adjudication_report_sha256",
                       "source_currentness_attestation_sha256",
                       "fresh_source_index_file_sha256",
                       "fresh_source_index_logical_sha256",
                       "private_cas_manifest_sha256",
                       "evidence_pack_sha256",
                   ))):
        raise ValueError("verified inclusion authority differs")
    try:
        valid_until = datetime.fromisoformat(
            inclusion["source_currentness_valid_until_utc"].replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        raise ValueError("verified inclusion freshness invalid") from None
    if valid_until.tzinfo is None or valid_until <= datetime.now(timezone.utc):
        raise ValueError("verified inclusion freshness expired")
    decisions = inclusion["decisions"]
    expected = sorted(item["content_sha256"] for item in inputs["artifacts"]["artifacts"])
    if (not isinstance(decisions, list) or len(decisions) != len(expected)
            or inclusion["decision_count"] != len(expected)
            or inclusion["evidence_pack_sha256"] != digest(canonical(decisions))
            or any(not isinstance(row, dict) or set(row) != {
                "content_sha256", "source_pdf_sha256", "disposition", "evidence_sha256",
                "pii_evidence_sha256", "currentness_evidence_sha256",
                "fresh_source_checkpoint_file_sha256",
            } for row in decisions)
            or [row["content_sha256"] for row in decisions] != expected):
        raise ValueError("inclusion population differs")
    included: set[str] = set()
    source_by_sha = {item["content_sha256"]: item["source_pdf_sha256"]
                     for item in inputs["artifacts"]["artifacts"]}
    for row in decisions:
        if row["source_pdf_sha256"] != source_by_sha[row["content_sha256"]]:
            raise ValueError("inclusion PDF source differs")
        if row["disposition"] not in {"INCLUDE", "EXCLUDE"}:
            raise ValueError("inclusion disposition is not final")
        evidence = row["evidence_sha256"]
        proof = {field: row[field] for field in (
            "pii_evidence_sha256", "currentness_evidence_sha256",
            "fresh_source_checkpoint_file_sha256",
        )}
        if (any(not isinstance(value, str) or SHA256.fullmatch(value) is None
                for value in proof.values())
                or evidence != digest(canonical(proof))):
            raise ValueError("inclusion evidence SHA differs")
        if row["disposition"] == "INCLUDE":
            included.add(row["content_sha256"])
    if not included:
        raise ValueError("inclusion set is empty")
    return frozenset(included)


def build_documents(
    source: dict[str, Any], *, inclusion: dict[str, Any] | None = None,
    legacy_profile_binding: bool = False,
) -> dict[Path, bytes]:
    """Réidentifier le candidat sous un nouvel ID ; conserver tous les verrous."""
    inputs = source["inputs"]
    old = inputs["release"]
    if (old.get("release_mode"), old.get("promotion_status"),
            old.get("review_status"), old.get("activation_status")) != (
                "candidate", "NOT_PROMOTABLE", "PRE_REVIEW", "NO_PRODUCTION_ACTIVATION",
            ):
        raise ValueError("source candidate status differs")
    artifacts = inputs["artifacts"].get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 253 or any(
        not isinstance(item, dict) or item.get("media_type") != TEXT_MIME
        or item.get("source_path") != f"{item.get('content_sha256')}.txt"
        or item.get("source_pdf_sha256") == item.get("content_sha256")
        for item in artifacts
    ):
        raise ValueError("successor text artifact population differs")
    profiles = source["profiles"]
    if len(profiles) != 11 or set(profiles) != {s["collection"] for s in inputs["subjects"]}:
        raise ValueError("complete profile population differs")
    if source["allowlist"].get("transfer_status") != "NOT_TRANSFERRED":
        raise ValueError("source transfer status differs")
    included = validate_inclusions(source, inclusion)
    selection_sha = digest(canonical(inclusion))
    # L'identité dépend des preuves d'entrée, jamais d'une horloge ou d'un HEAD mobile.
    seed = canonical({
        "kind": ("NEXUS_STUDENT_PUBLIC_SUCCESSOR_PREPARATION_V1"
                 if legacy_profile_binding else
                 "NEXUS_STUDENT_PUBLIC_SUCCESSOR_PREPARATION_V2"),
        "candidate_manifest_sha256": inputs["release_sha256"],
        "candidate_inventory_sha256": digest(canonical(source["inventory"])),
        "complete_profile_proposal_sha256": source["profile_proposal_sha256"],
        "inclusion_attestation_sha256": selection_sha,
    })
    suffix = digest(seed)[:16]
    release_id = f"student-public-successor-20261010-{suffix}"
    base = RELEASE_ROOT / f"release-{suffix}"
    gate = Path("profile_gate")
    documents: dict[Path, bytes] = {}

    artifact_registry = copy.deepcopy(inputs["artifacts"])
    artifact_registry["release_id"] = release_id
    artifact_registry["artifacts"] = [item for item in artifact_registry["artifacts"]
                                      if item["content_sha256"] in included]
    artifact_registry["expected_counts"] = {
        "unique_artifacts": len(artifact_registry["artifacts"]),
        "unique_chunks": sum(len(item["chunks"]) for item in artifact_registry["artifacts"]),
    }
    artifact_raw = canonical(artifact_registry)
    artifact_sha = digest(artifact_raw)
    documents[base / gate / "artifacts.release.json"] = artifact_raw

    authorities = copy.deepcopy(old["authorities"])
    decisions_by_sha = {row["content_sha256"]: row for row in inclusion["decisions"]}
    for name, authority in SIDECARS.items():
        sidecar = copy.deepcopy(source["sidecars"][name])
        sidecar["release_id"] = release_id
        if name != "public_profiles.json":
            sidecar["entries"] = [item for item in sidecar["entries"]
                                  if item["content_sha256"] in included]
        if name == "public_pii_registry.json":
            sidecar["kind"] = "NEXUS_STUDENT_PUBLIC_DERIVATIVE_PII_REGISTRY_V2"
            sidecar["adjudication_report_sha256"] = inclusion[
                "pii_adjudication_report_sha256"]
            for entry in sidecar["entries"]:
                entry["pii_gate_status"] = "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"
                entry["pii_evidence_sha256"] = decisions_by_sha[
                    entry["content_sha256"]]["pii_evidence_sha256"]
        if name == "public_rights_registry.json":
            sidecar["kind"] = "NEXUS_STUDENT_PUBLIC_DERIVATIVE_RIGHTS_REGISTRY_V2"
            sidecar["inclusion_attestation_sha256"] = selection_sha
            sidecar["source_currentness_attestation_sha256"] = inclusion[
                "source_currentness_attestation_sha256"]
            for entry in sidecar["entries"]:
                decision = decisions_by_sha[entry["content_sha256"]]
                if entry["source_pdf_sha256"] != decision["source_pdf_sha256"]:
                    raise ValueError("derivative rights source PDF differs")
                entry["rights_basis"] = "EDUSCOL_ETALAB_2_0_SITEWIDE"
                entry["currentness_evidence_sha256"] = decision[
                    "currentness_evidence_sha256"]
        raw = canonical(sidecar)
        authorities[authority] = digest(raw)
        documents[base / gate / name] = raw

    currentness_registry = {
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CURRENTNESS_REGISTRY_V1",
        "status": "CANDIDATE_NOT_AUTHORIZED",
        "release_id": release_id,
        "source_currentness_attestation_sha256": inclusion[
            "source_currentness_attestation_sha256"],
        "fresh_source_index_file_sha256": inclusion["fresh_source_index_file_sha256"],
        "private_cas_manifest_sha256": inclusion["private_cas_manifest_sha256"],
        "valid_until_utc": inclusion["source_currentness_valid_until_utc"],
        "entries": [
            {
                "content_sha256": row["content_sha256"],
                "source_pdf_sha256": row["source_pdf_sha256"],
                "currentness_evidence_sha256": row["currentness_evidence_sha256"],
                "fresh_source_checkpoint_file_sha256": row[
                    "fresh_source_checkpoint_file_sha256"],
                "currentness_status": "PASS",
                "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
            }
            for row in inclusion["decisions"] if row["disposition"] == "INCLUDE"
        ],
    }
    currentness_raw = canonical(currentness_registry)
    currentness_sha = digest(currentness_raw)
    documents[base / gate / "public_currentness_registry.json"] = currentness_raw

    subjects = []
    total_placements = 0
    for original in sorted(inputs["subjects"], key=lambda row: row["collection"]):
        subject = copy.deepcopy(original)
        collection = subject["collection"]
        subject["release_id"] = f"{release_id}-{collection}"
        subject["artifact_registry"]["sha256"] = artifact_sha
        subject["authorities"] = copy.deepcopy(authorities)
        subject["profile"]["manifest_digest"] = authorities["public_profile_registry_sha256"]
        if not legacy_profile_binding:
            profile_ref = source["profile_refs"][collection]
            subject["profile"]["version"] = profile_ref["profile_version"]
            subject["profile"]["fingerprint"] = profile_ref["fingerprint"]
        placements = subject.get("placements")
        if (not isinstance(placements, list) or not placements
                or any(row.get("visibility") != "public" for row in placements)):
            raise ValueError("successor public placement population differs")
        subject["placements"] = [row for row in placements if row["artifact_id"] in included]
        if not subject["placements"]:
            raise ValueError(f"successor collection empty: {collection}")
        subject["expected_counts"] = {
            "placements": len(subject["placements"]),
            "unique_artifact_references": len({row["artifact_id"] for row in subject["placements"]}),
        }
        total_placements += len(subject["placements"])
        raw = canonical(subject)
        path = Path("subjects") / f"{collection}.release.json"
        documents[base / gate / path] = raw
        subjects.append({"collection": collection, "path": path.as_posix(), "sha256": digest(raw)})
        documents[base / gate / "profiles" / f"{collection}.yml"] = profiles[collection]
    unique_chunks = artifact_registry["expected_counts"]["unique_chunks"]
    counts = {
        "subjects": len(subjects), "unique_artifacts": len(artifact_registry["artifacts"]),
        "placements": total_placements, "unique_chunks": unique_chunks,
    }
    if counts["subjects"] != 11 or counts["placements"] < 11:
        raise ValueError("successor real counts differ")
    aggregate = copy.deepcopy(old)
    aggregate["release_id"] = release_id
    aggregate["artifact_registry"]["sha256"] = artifact_sha
    aggregate["authorities"] = authorities
    aggregate["subjects"] = subjects
    aggregate["expected_counts"] = counts
    aggregate_raw = canonical(aggregate)
    aggregate_sha = digest(aggregate_raw)
    documents[base / gate / "production-profile-gate.release.json"] = aggregate_raw
    registry = {
        "registry_version": "1", "school_year": aggregate["school_year"],
        "releases": [{
            "release_id": release_id, "release_kind": aggregate["release_kind"],
            "collections": [row["collection"] for row in subjects],
            "manifest_path": "profile_gate/production-profile-gate.release.json",
            "expected_manifest_sha256": aggregate_sha,
        }],
    }
    documents[base / "release-registry.json"] = canonical(registry)

    inventory = copy.deepcopy(source["inventory"])
    inventory["release_id"] = release_id
    inventory["release_manifest_sha256"] = aggregate_sha
    inventory["artifact_registry_sha256"] = artifact_sha
    for collection in inventory["collections"]:
        collection["candidates"] = [item for item in collection["candidates"]
                                    if item["content_sha256"] in included]
        if not collection["candidates"]:
            raise ValueError(f"successor inventory collection empty: {collection['collection']}")
    inventory["counts"] = {
        "collections": len(inventory["collections"]),
        "unique_artifacts": len(included),
        "placements": sum(len(item["placements"]) for collection in inventory["collections"]
                          for item in collection["candidates"]),
    }
    if inventory["counts"]["placements"] != total_placements:
        raise ValueError("successor inventory placements differ")
    inventory_raw = canonical(inventory)
    inventory_sha = digest(inventory_raw)
    documents[base / gate / "candidate_inventory.json"] = inventory_raw
    allowlist = copy.deepcopy(source["allowlist"])
    allowlist["release_id"] = release_id
    allowlist["candidate_inventory_sha256"] = inventory_sha
    allowlist["expected_files"] = [row for row in allowlist["expected_files"]
                                   if row["sha256_expected"] in included]
    allowlist["allowed_file_count"] = len(allowlist["expected_files"])
    documents[base / gate / "private_transfer_allowlist.json"] = canonical(allowlist)
    documents[base / gate / "inclusion_attestation.json"] = canonical(inclusion)
    documents[base / gate / "profiles" / "public_profile_proposal.json"] = (
        source["profile_proposal_raw"]
    )
    profile_index = [
        {**source["profile_refs"][row["collection"]],
         "path": f"profile_gate/profiles/{row['collection']}.yml"}
        for row in subjects
    ]
    proposed_scopes = [
        {
            "collection": row["collection"],
            "final_subject_sha256": row["sha256"],
            "proposed_scope_id": (
                f"student_public_{row['collection'].removeprefix('rag_nexus_')}_v1"
            ),
            "status": "NOT_ISSUED",
        }
        for row in subjects
    ]
    index = {
        "kind": "NEXUS_STUDENT_PUBLIC_SUCCESSOR_PREPARATION_V2",
        "status": "PREPARATION_ONLY_NOT_ACTIVABLE",
        "release_id": release_id,
        "source_candidate_release_id": old["release_id"],
        "source_candidate_manifest_sha256": inputs["release_sha256"],
        "source_candidate_inventory_sha256": digest(canonical(source["inventory"])),
        "complete_profile_proposal_sha256": source["profile_proposal_sha256"],
        "inclusion_attestation_sha256": selection_sha,
        "pii_adjudication_report_sha256": inclusion["pii_adjudication_report_sha256"],
        "source_currentness_attestation_sha256": inclusion[
            "source_currentness_attestation_sha256"],
        "fresh_source_index_file_sha256": inclusion["fresh_source_index_file_sha256"],
        "fresh_source_index_logical_sha256": inclusion["fresh_source_index_logical_sha256"],
        "private_cas_manifest_sha256": inclusion["private_cas_manifest_sha256"],
        "source_currentness_valid_until_utc": inclusion[
            "source_currentness_valid_until_utc"],
        "evidence_pack_sha256": inclusion["evidence_pack_sha256"],
        "verified_authorities": {
            "candidate_manifest_sha256": inputs["candidate_manifest_sha256"],
            "rights_authority_sha256": inclusion["rights_authority_sha256"],
            "inclusion_attestation_sha256": selection_sha,
            "pii_adjudication_report_sha256": inclusion[
                "pii_adjudication_report_sha256"],
            "source_currentness_attestation_sha256": inclusion[
                "source_currentness_attestation_sha256"],
            "fresh_source_index_file_sha256": inclusion[
                "fresh_source_index_file_sha256"],
            "private_cas_manifest_sha256": inclusion["private_cas_manifest_sha256"],
            "public_pii_registry_sha256": authorities["public_pii_registry_sha256"],
            "public_rights_registry_sha256": authorities["public_rights_registry_sha256"],
            "public_currentness_registry_sha256": currentness_sha,
        },
        "excluded_derivative_count": len(artifacts) - len(included),
        "complete_profile_count": len(profiles),
        "complete_profiles": profile_index,
        "proposed_scopes": proposed_scopes,
        "release_manifest_sha256": aggregate_sha,
        "artifact_registry_sha256": artifact_sha,
        "candidate_inventory_sha256": inventory_sha,
        "expected_counts": counts,
        "blocking_evidence": BLOCKERS,
        "transfer_status": "NOT_TRANSFERRED",
    }
    documents[base / "preparation-index.json"] = canonical(index)
    return documents


def write_immutable(root: Path, documents: dict[Path, bytes]) -> None:
    """Écrire uniquement si chaque chemin absent ou strictement identique."""
    for relative, raw in documents.items():
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("immutable output path invalid")
        path = root / relative
        if path.exists() and path.read_bytes() != raw:
            raise ValueError(f"immutable output differs: {relative}")
    for relative, raw in documents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--inclusion-attestation", type=Path, required=True)
    parser.add_argument("--inclusion-attestation-sha256", required=True)
    parser.add_argument("--private-cas-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.repository_root.resolve()
    inclusion_path = args.inclusion_attestation.resolve()
    raw = inclusion_path.read_bytes()
    if (SHA256.fullmatch(args.inclusion_attestation_sha256) is None
            or digest(raw) != args.inclusion_attestation_sha256):
        raise ValueError("inclusion attestation sealed digest differs")
    source = load_sources(root)
    from check_student_public_derivative_inclusions import verify_private_cas_evidence

    verified = verify_private_cas_evidence(source, args.private_cas_root)
    if canonical(verified) != raw:
        raise ValueError("inclusion attestation differs from private CAS replay")
    documents = build_documents(source, inclusion=verified)
    write_immutable(root, documents)
    index = next(json.loads(raw) for path, raw in documents.items()
                 if path.name == "preparation-index.json")
    print(f"SUCCESSOR_PREPARATION_RELEASE_ID={index['release_id']}")
    print(f"SUCCESSOR_MANIFEST_SHA256={index['release_manifest_sha256']}")
    print("SUCCESSOR_ACTIVABLE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
