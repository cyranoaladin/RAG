#!/usr/bin/env python3
"""Préparer les profils du successeur public, sans activer le candidat #312."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from build_student_public_successor import (
    SOURCE_PROFILE_DIR_REL,
    _bound_source_audiences,
    _canonical,
    _source_placements,
)
from nexus_contracts.ingestion import CollectionProfile, collection_profile_fingerprint
from nexus_contracts.profile_manifest import strict_yaml_mapping

EVIDENCE_INDEX_REL = Path("docs/reports/go_live/student_rights_evidence/index.json")
PROFILE_VERSION = "student-public-derivative-v1"


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON document: {path.name}")
    return value


def project_public_profiles(
    repository_root: Path,
    candidate_root: Path,
) -> dict[str, CollectionProfile]:
    """Projeter onze profils complets depuis les sujets et profils sources liés.

    Cette projection ne confère aucune autorisation de publication : elle
    produit seulement des valeurs que le manifeste/review successeur devra
    approuver à son propre HEAD exact.
    """
    aggregate = _read_json(candidate_root / "production-profile-gate.release.json")
    if (aggregate.get("release_mode") != "candidate"
            or aggregate.get("promotion_status") != "NOT_PROMOTABLE"):
        raise ValueError("source release is not the sealed candidate")
    authority = aggregate.get("authorities")
    if not isinstance(authority, dict):
        raise ValueError("candidate authority missing")
    proposal_raw = (candidate_root / "public_profiles.json").read_bytes()
    if hashlib.sha256(proposal_raw).hexdigest() != authority.get("public_profile_registry_sha256"):
        raise ValueError("candidate profile proposal digest mismatch")
    proposal = json.loads(proposal_raw)
    rows = proposal.get("entries")
    if (proposal.get("kind") != "NEXUS_STUDENT_PUBLIC_SCOPE_CANDIDATES_V1"
            or proposal.get("status") != "CANDIDATE_NOT_AUTHORIZED"
            or proposal.get("release_id") != aggregate.get("release_id")
            or not isinstance(rows, list) or len(rows) != 11):
        raise ValueError("candidate profile proposal invalid")
    proposed = {row.get("collection"): row for row in rows if isinstance(row, dict)}
    if len(proposed) != 11:
        raise ValueError("candidate profile proposal duplicates")

    index = _read_json(repository_root / EVIDENCE_INDEX_REL)
    source_subjects, _, _, _ = _source_placements(repository_root, index)
    audiences = _bound_source_audiences(repository_root, source_subjects)
    if set(proposed) != set(source_subjects):
        raise ValueError("candidate profile proposal population mismatch")

    candidate_subjects = {}
    for ref in aggregate.get("subjects", []):
        relative = Path(ref["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "subjects":
            raise ValueError("candidate subject path invalid")
        raw = (candidate_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref.get("sha256"):
            raise ValueError("candidate subject digest mismatch")
        subject = json.loads(raw)
        collection = subject.get("collection")
        if collection != ref.get("collection") or collection in candidate_subjects:
            raise ValueError("candidate subject collection mismatch")
        candidate_subjects[collection] = subject
    if set(candidate_subjects) != set(proposed):
        raise ValueError("candidate subject population mismatch")

    projected = {}
    for collection in sorted(proposed):
        row = proposed[collection]
        subject = candidate_subjects[collection]
        source = source_subjects[collection]
        source_path = repository_root / SOURCE_PROFILE_DIR_REL / f"{collection}.yml"
        source_profile = CollectionProfile.model_validate(
            strict_yaml_mapping(source_path.read_bytes(), source=source_path.name)
        )
        scope = source_profile.scope.model_dump(mode="json")
        scope["visibility"] = "public"
        proposed_scope = row.get("scope")
        if not isinstance(proposed_scope, dict):
            raise ValueError("candidate profile proposal scope missing")
        expected_scope = {**scope, "statut_enseignement": subject["placements"][0]["statut_enseignement"]}
        if (proposed_scope != expected_scope
                or row.get("source_profile_fingerprint") != source["profile"]["fingerprint"]
                or row.get("source_subject_sha256") not in {
                    ref["sha256"] for population in index["source_population"]
                    for ref in population["subjects"]
                    if ref["path"].endswith(f"/{collection}.release.json")
                }
                or row.get("profile_fingerprint") != hashlib.sha256(
                    _canonical(proposed_scope)).hexdigest()
                or subject.get("profile", {}).get("fingerprint") != row["profile_fingerprint"]
                or subject.get("profile", {}).get("manifest_digest")
                != authority["public_profile_registry_sha256"]
                or audiences[collection] != scope["audience"]):
            raise ValueError(f"candidate profile proposal or scope mismatch: {collection}")
        for placement in subject["placements"]:
            if any(placement.get(key) != value for key, value in expected_scope.items()
                   if key not in {"audience", "statut_enseignement"}):
                raise ValueError(f"candidate placement scope mismatch: {collection}")
        profile_data = source_profile.model_dump(mode="json")
        profile_data["profile_version"] = PROFILE_VERSION
        profile_data["scope"] = scope
        projected[collection] = CollectionProfile.model_validate(profile_data)
    return projected


def build_public_profile_proposal_documents(
    repository_root: Path,
    candidate_root: Path,
    output_dir: Path,
) -> dict[Path, bytes]:
    """Rendre des YAML complets et une proposition, jamais un manifeste approuvé."""
    profiles = project_public_profiles(repository_root, candidate_root)
    candidate_manifest = (candidate_root / "production-profile-gate.release.json").read_bytes()
    candidate_profiles = (candidate_root / "public_profiles.json").read_bytes()
    documents: dict[Path, bytes] = {}
    rows = []
    for collection, profile in sorted(profiles.items()):
        relative = Path(f"{collection}.yml")
        raw = yaml.safe_dump(
            profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True,
        ).encode("utf-8")
        documents[output_dir / relative] = raw
        rows.append({
            "collection": collection,
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "profile_version": profile.profile_version,
            "fingerprint": collection_profile_fingerprint(profile),
        })
    proposal = {
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_PROFILE_PROPOSAL_V1",
        "status": "PENDING_EXACT_HEAD_AUTHORITY_REVIEW",
        "candidate_release_id": _read_json(
            candidate_root / "production-profile-gate.release.json")["release_id"],
        "candidate_manifest_sha256": hashlib.sha256(candidate_manifest).hexdigest(),
        "candidate_profile_registry_sha256": hashlib.sha256(candidate_profiles).hexdigest(),
        "profile_count": len(rows),
        "entries": rows,
    }
    documents[output_dir / "public_profile_proposal.json"] = _canonical(proposal)
    return documents
