#!/usr/bin/env python3
"""Résout le gate de profils de production depuis des preuves versionnées."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from nexus_contracts.ingestion import CollectionProfile, collection_profile_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
DECISIONS_PATH = SERVICE_ROOT / "configs/production_profile_decisions_20260825.json"
PROPOSED_MATRIX_PATH = REPO_ROOT / "docs/reports/proposed_production_profile_matrix_20260823.json"
DRIVE_MAPPING_PATH = (
    REPO_ROOT
    / "docs/reports/evidence-index/drive-snapshot/drive_snapshot_mapping_20260815.json"
)
PRIMARY_EVIDENCE_PATH = (
    REPO_ROOT / "docs/reports/production_profile_primary_evidence_20260825.json"
)
DEFAULT_RESOLUTION_PATH = (
    REPO_ROOT / "docs/reports/production_profile_resolution_records_20260825.json"
)
DEFAULT_MATRIX_PATH = (
    REPO_ROOT / "docs/reports/final_production_profile_matrix_20260825.json"
)
PROFILE_SOURCE_PREFIX = "services/rag-engine/configs/ingestion_profiles/"
STAGING_MULTILEVEL_PREFIX = f"{PROFILE_SOURCE_PREFIX}staging/multilevel/"
PRIMARY_EVIDENCE_REPO_PATH = (
    "docs/reports/production_profile_primary_evidence_20260825.json"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
P11_P23_RE = re.compile(r"P(?:1[1-9]|2[0-3])")


class ProfileGateError(ValueError):
    """Une entrée du gate est incohérente ou incomplète."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileGateError(f"Impossible de lire {path}: {exc}") from exc


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ProfileGateError(f"{label} n'est pas un SHA-256 canonique")
    return value


def _rewrite_promoted_profile_path(value: str) -> str:
    if value.startswith(STAGING_MULTILEVEL_PREFIX):
        return PROFILE_SOURCE_PREFIX + value.removeprefix(STAGING_MULTILEVEL_PREFIX)
    return value


def _promote_matrix_partition(partition: dict[str, Any]) -> dict[str, Any]:
    promoted = copy.deepcopy(partition)
    promoted["evidence_sources"] = [
        _rewrite_promoted_profile_path(source) for source in promoted["evidence_sources"]
    ]
    for dimension in promoted["dimensions"].values():
        source = dimension.get("source_of_truth")
        if isinstance(source, str):
            dimension["source_of_truth"] = _rewrite_promoted_profile_path(source)
    return promoted


def _profile_index(
    decisions: dict[str, Any],
) -> tuple[dict[str, tuple[str, dict[str, Any], str]], dict[str, dict[str, Any]]]:
    by_content: dict[str, tuple[str, dict[str, Any], str]] = {}
    profiles: dict[str, dict[str, Any]] = {}
    for profile_id, decision in decisions["profiles"].items():
        profile = CollectionProfile.model_validate(decision["profile"])
        if profile.scope.collection != profile_id:
            raise ProfileGateError(f"Le profil {profile_id} déclare une autre collection")
        source = decision["profile_source"]
        if not isinstance(source, str) or not source.startswith(PROFILE_SOURCE_PREFIX):
            raise ProfileGateError(f"Source de profil non canonique pour {profile_id}")
        fingerprint = collection_profile_fingerprint(profile)
        profile_document = profile.model_dump(mode="json")
        profiles[profile_id] = {
            "profile": profile_document,
            "profile_source": source,
            "profile_fingerprint": fingerprint,
        }
        for raw_sha in decision["content_sha256"]:
            sha = _require_sha256(raw_sha, label=f"contenu de {profile_id}")
            if sha in by_content:
                raise ProfileGateError(f"Le contenu {sha} appartient à plusieurs profils")
            by_content[sha] = (profile_id, profile_document, source)
    return by_content, profiles


def build_outputs() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    decisions = _load_json(DECISIONS_PATH)
    matrix = _load_json(PROPOSED_MATRIX_PATH)
    drive_mapping = _load_json(DRIVE_MAPPING_PATH)
    evidence_raw = PRIMARY_EVIDENCE_PATH.read_bytes()
    evidence = json.loads(evidence_raw)

    expected_evidence_digest = _require_sha256(
        decisions["primary_evidence_sha256"], label="primary_evidence_sha256"
    )
    actual_evidence_digest = hashlib.sha256(evidence_raw).hexdigest()
    if actual_evidence_digest != expected_evidence_digest:
        raise ProfileGateError("Le digest de la preuve primaire a dérivé")

    partitions_by_content: dict[str, str] = {}
    for partition in matrix:
        partition_id = partition["partition_id"]
        if P11_P23_RE.fullmatch(partition_id):
            for sha in partition["content_sha256"]:
                if sha in partitions_by_content:
                    raise ProfileGateError(f"Contenu répété dans la matrice: {sha}")
                partitions_by_content[sha] = partition_id
    mapping_by_content = {row["content_sha256"]: row for row in drive_mapping}
    evidence_by_content = {row["content_sha256"]: row for row in evidence["records"]}
    if set(partitions_by_content) != set(evidence_by_content):
        raise ProfileGateError("La preuve primaire ne couvre pas exactement P11-P23")

    profile_by_content, profiles = _profile_index(decisions)
    evidence_grounded = {
        sha
        for sha, row in evidence_by_content.items()
        if row["evidence_disposition"] == "EXACT_SCOPE_GROUNDED"
    }
    if set(profile_by_content) != evidence_grounded:
        raise ProfileGateError("Les décisions de profils divergent des preuves exactement groundées")

    product_defaults = decisions["product_defaults"]
    resolution_records: list[dict[str, Any]] = []
    for sha in sorted(partitions_by_content):
        partition_id = partitions_by_content[sha]
        mapping = mapping_by_content.get(sha)
        primary = evidence_by_content[sha]
        if mapping is None or mapping["canonical_path"] != primary["canonical_path"]:
            raise ProfileGateError(f"Chemin canonique incohérent pour {sha}")
        evidence_ref = f"{PRIMARY_EVIDENCE_REPO_PATH}#content_sha256={sha}"
        selected = profile_by_content.get(sha)
        if selected is None:
            residual = decisions["partition_residuals"].get(partition_id)
            if residual is None:
                raise ProfileGateError(f"Disposition résiduelle absente pour {partition_id}")
            resolution_records.append(
                {
                    "audience": None,
                    "candidat": None,
                    "canonical_path": mapping["canonical_path"],
                    "collection": None,
                    "content_sha256": sha,
                    "matiere": None,
                    "matiere_evidence": [evidence_ref],
                    "niveau": None,
                    "niveau_evidence": [evidence_ref],
                    "partition_id": partition_id,
                    "profile_fingerprint": None,
                    "profile_id": None,
                    "profile_version": None,
                    "programme_version": None,
                    "programme_version_evidence": [evidence_ref],
                    "reason_code": residual["reason_code"],
                    "resolution_status": residual["resolution_status"],
                    "school_year": None,
                    "tenant": None,
                    "visibility": None,
                    "voie": None,
                    "voie_evidence": [evidence_ref],
                }
            )
            continue

        profile_id, profile_document, _ = selected
        profile_fact = profiles[profile_id]
        scope = profile_document["scope"]
        product_evidence = (
            "services/rag-pedago/configs/production_profile_decisions_20260825.json"
            "#product_defaults"
        )
        resolution_records.append(
            {
                "audience": scope["audience"],
                "candidat": scope["candidat"],
                "canonical_path": mapping["canonical_path"],
                "collection": scope["collection"],
                "content_sha256": sha,
                "matiere": scope["matiere"],
                "matiere_evidence": [evidence_ref],
                "niveau": scope["niveau"],
                "niveau_evidence": [evidence_ref],
                "partition_id": partition_id,
                "profile_fingerprint": profile_fact["profile_fingerprint"],
                "profile_id": profile_id,
                "profile_version": profile_document["profile_version"],
                "programme_version": scope["programme_version"],
                "programme_version_evidence": [
                    evidence_ref,
                    *primary["primary_identifiers"],
                ],
                "reason_code": "PRIMARY_SCOPE_PROVEN",
                "resolution_status": "EXACTLY_GROUNDED",
                "school_year": product_defaults["school_year"],
                "tenant": scope["tenant"],
                "visibility": product_defaults["visibility"],
                "voie": scope["voie"],
                "voie_evidence": [evidence_ref],
                "product_policy_evidence": [product_evidence],
            }
        )

    grounded_count = sum(
        row["resolution_status"] == "EXACTLY_GROUNDED" for row in resolution_records
    )
    resolution = {
        "schema_version": "PRODUCTION_PROFILE_RESOLUTION_V1",
        "source_tree_commit": decisions["source_tree_commit"],
        "primary_evidence_path": PRIMARY_EVIDENCE_REPO_PATH,
        "primary_evidence_sha256": actual_evidence_digest,
        "input_content_count": len(resolution_records),
        "exactly_grounded_count": grounded_count,
        "review_required_count": len(resolution_records) - grounded_count,
        "residual_policy": product_defaults["residual_policy"],
        "records": resolution_records,
    }

    final_matrix: list[dict[str, Any]] = []
    for partition in matrix:
        partition_id = partition["partition_id"]
        if re.fullmatch(r"P(?:0[1-9]|10)", partition_id):
            final_matrix.append(_promote_matrix_partition(partition))
        elif partition_id == "P24":
            final_matrix.append(copy.deepcopy(partition))

    contents_by_profile: dict[str, list[str]] = defaultdict(list)
    partition_by_profile: dict[str, set[str]] = defaultdict(set)
    for sha, (profile_id, _, _) in profile_by_content.items():
        contents_by_profile[profile_id].append(sha)
        partition_by_profile[profile_id].add(partitions_by_content[sha])
    for profile_id in sorted(contents_by_profile):
        profile_fact = profiles[profile_id]
        profile_document = profile_fact["profile"]
        source = profile_fact["profile_source"]
        source_partitions = "-".join(sorted(partition_by_profile[profile_id]))
        suffix = profile_id.removeprefix("rag_nexus_").replace("_", "-").upper()
        scope = profile_document["scope"]
        final_matrix.append(
            {
                "content_count": len(contents_by_profile[profile_id]),
                "content_sha256": sorted(contents_by_profile[profile_id]),
                "dimensions": {
                    name: {"grounded": True, "source_of_truth": source, "value": value}
                    for name, value in scope.items()
                },
                "evidence_sources": [PRIMARY_EVIDENCE_REPO_PATH, source],
                "observed_matiere_evidence": [scope["matiere"]],
                "observed_niveau_evidence": [scope["niveau"]],
                "partition_id": f"{source_partitions}-{suffix}",
                "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
                "profile_decision_required": False,
            }
        )
    final_matrix.sort(key=lambda row: row["partition_id"])
    return resolution, final_matrix


def _write_or_check(path: Path, content: bytes, *, check: bool) -> None:
    if check:
        if not path.is_file() or path.read_bytes() != content:
            raise ProfileGateError(f"Artefact absent ou non reproductible: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolution-output", type=Path, default=DEFAULT_RESOLUTION_PATH)
    parser.add_argument("--matrix-output", type=Path, default=DEFAULT_MATRIX_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    resolution, matrix = build_outputs()
    _write_or_check(args.resolution_output, _canonical_bytes(resolution), check=args.check)
    _write_or_check(args.matrix_output, _canonical_bytes(matrix), check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
