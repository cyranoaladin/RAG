"""Inspection externe en lecture seule du successeur public (ADR-0070).

Ce contrôleur lie les 21 déclarations et le paquet préparatoire. Il ne délivre
aucun verdict de promotion : plusieurs pièces n'ont pas encore de format ni de
vérificateur sémantique. Un fichier au bon SHA ne remplace pas cette preuve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from nexus_release_chain.release_readiness import (
    ReleaseReadinessError,
    load_release_expectation,
)
from public_text_transfer import TransferRefused, verify_observed_destination

AUTHORITY_FIELDS = frozenset({
    "source_candidate_release_manifest_sha256",
    "source_preparation_release_manifest_sha256",
    "source_preparation_index_sha256",
    "candidate_inventory_sha256",
    "inclusion_attestation_sha256",
    "derivative_pii_evidence_sha256",
    "derivative_currentness_evidence_sha256",
    "public_profile_manifest_sha256",
    "public_rights_registry_sha256",
    "public_pii_registry_sha256",
    "rights_authority_sha256",
    "delegated_evidence_pack_sha256",
    "pr300_final_authority_receipt_sha256",
    "public_scope_authority_sha256",
    "exact_head_scope_review_receipt_sha256",
    "authorization_set_sha256",
    "exact_head_authorization_review_receipt_sha256",
    "publication_batch_review_receipt_sha256",
    "artifact_transfer_manifest_sha256",
    "observed_transfer_receipt_sha256",
    "revocation_evidence_sha256",
})

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHAPE_REJECTION = "public successor external evidence verification unavailable"
_LOCAL_FILES = {
    "source_preparation_release_manifest_sha256": "source_preparation/production-profile-gate.release.json",
    "source_preparation_index_sha256": "source_preparation/preparation-index.json",
    "candidate_inventory_sha256": "candidate_inventory.json",
}


class ExternalGateError(ValueError):
    """Une liaison locale ou un digest déclaré est invalide."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _read(root: Path, relative: str, expected: str, field: str) -> dict[str, Any]:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ExternalGateError(f"{field}: evidence path missing or escapes release root")
    raw = path.read_bytes()
    if _sha(raw) != expected:
        raise ExternalGateError(f"{field}: evidence SHA-256 differs")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalGateError(f"{field}: evidence JSON invalid") from exc
    if not isinstance(value, dict):
        raise ExternalGateError(f"{field}: evidence must be an object")
    return value


def _inventory_population(inventory: Mapping[str, Any]) -> dict[str, tuple[Mapping[str, Any], ...]]:
    collections = inventory.get("collections")
    if not isinstance(collections, list) or not collections:
        raise ExternalGateError("candidate_inventory_sha256: collections missing")
    result: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for row in collections:
        if not isinstance(row, dict) or not isinstance(row.get("collection"), str):
            raise ExternalGateError("candidate_inventory_sha256: collection invalid")
        collection = row["collection"]
        candidates = row.get("candidates")
        if collection in result or not isinstance(candidates, list) or not candidates:
            raise ExternalGateError("candidate_inventory_sha256: empty or duplicate collection")
        if not all(isinstance(item, dict) for item in candidates):
            raise ExternalGateError("candidate_inventory_sha256: candidate invalid")
        identities = [item.get("content_sha256") for item in candidates]
        if any(not isinstance(sha, str) or _SHA256.fullmatch(sha) is None for sha in identities):
            raise ExternalGateError("candidate_inventory_sha256: derivative SHA invalid")
        if len(set(identities)) != len(identities):
            raise ExternalGateError("candidate_inventory_sha256: duplicate derivative")
        result[collection] = tuple(candidates)
    return result


def _candidate_placement_pairs(
    candidates: tuple[Mapping[str, Any], ...], collection: str,
) -> set[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for candidate in candidates:
        placements = candidate.get("placements")
        if not isinstance(placements, list) or not placements:
            raise ExternalGateError(f"{collection}: candidate placements absent")
        for placement in placements:
            source_id = placement.get("source_placement_id") if isinstance(placement, dict) else None
            if not isinstance(source_id, str) or _SHA256.fullmatch(source_id) is None:
                raise ExternalGateError(f"{collection}: source placement identity invalid")
            pairs.append((candidate["content_sha256"], source_id))
    if len(set(pairs)) != len(pairs):
        raise ExternalGateError(f"{collection}: duplicate candidate placement")
    return set(pairs)


def _verify_preparation_chain(
    release_root: Path, manifest: Mapping[str, Any], authorities: Mapping[str, str]
) -> tuple[dict[str, list[str]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    preparation = _read(
        release_root, _LOCAL_FILES["source_preparation_release_manifest_sha256"],
        authorities["source_preparation_release_manifest_sha256"],
        "source_preparation_release_manifest_sha256",
    )
    index = _read(
        release_root, _LOCAL_FILES["source_preparation_index_sha256"],
        authorities["source_preparation_index_sha256"],
        "source_preparation_index_sha256",
    )
    source_inventory_sha = index.get("candidate_inventory_sha256")
    if not isinstance(source_inventory_sha, str) or _SHA256.fullmatch(source_inventory_sha) is None:
        raise ExternalGateError("source_preparation_index_sha256: source inventory SHA missing")
    source_inventory = _read(
        release_root, "source_preparation/candidate_inventory.json", source_inventory_sha,
        "source_preparation_index_sha256",
    )
    final_inventory = _read(
        release_root, _LOCAL_FILES["candidate_inventory_sha256"],
        authorities["candidate_inventory_sha256"], "candidate_inventory_sha256",
    )
    source_registry = preparation.get("artifact_registry")
    source_authorities = preparation.get("authorities")
    if not isinstance(source_registry, dict) or not isinstance(source_authorities, dict):
        raise ExternalGateError("source_preparation_release_manifest_sha256: source authorities absent")
    if not (
        index.get("kind") == "NEXUS_STUDENT_PUBLIC_SUCCESSOR_PREPARATION_V2"
        and index.get("status") == "PREPARATION_ONLY_NOT_ACTIVABLE"
        and index.get("transfer_status") == "NOT_TRANSFERRED"
        and preparation.get("release_mode") == "candidate"
        and preparation.get("promotion_status") == "NOT_PROMOTABLE"
        and preparation.get("review_status") == "PRE_REVIEW"
        and preparation.get("activation_status") == "NO_PRODUCTION_ACTIVATION"
        and index.get("release_id") == preparation.get("release_id")
        and index.get("release_manifest_sha256")
            == authorities["source_preparation_release_manifest_sha256"]
        and index.get("artifact_registry_sha256") == source_registry.get("sha256")
        and index.get("source_candidate_manifest_sha256")
            == authorities["source_candidate_release_manifest_sha256"]
        and source_inventory.get("candidate_manifest_sha256")
            == source_authorities.get("candidate_manifest_sha256")
        and source_inventory.get("release_id") == preparation.get("release_id")
        and source_inventory.get("release_manifest_sha256")
            == authorities["source_preparation_release_manifest_sha256"]
        and source_inventory.get("artifact_registry_sha256") == source_registry.get("sha256")
        and final_inventory.get("release_id") == manifest.get("release_id")
        and final_inventory.get("release_manifest_sha256")
            == authorities["source_preparation_release_manifest_sha256"]
        and final_inventory.get("artifact_registry_sha256")
            == manifest.get("artifact_registry", {}).get("sha256")
        and final_inventory.get("candidate_manifest_sha256")
            == source_inventory.get("candidate_manifest_sha256")
        and final_inventory.get("source_candidate_inventory_sha256")
            == source_inventory.get("source_candidate_inventory_sha256")
    ):
        raise ExternalGateError("source preparation → final authority chain differs")

    source_population = _inventory_population(source_inventory)
    final_population = _inventory_population(final_inventory)
    subject_refs = manifest.get("subjects")
    if not isinstance(subject_refs, list):
        raise ExternalGateError("canonical subjects absent")
    subjects = {
        row.get("collection"): row for row in subject_refs if isinstance(row, dict)
    }
    if (
        len(subjects) != len(subject_refs)
        or set(final_population) != set(source_population)
        or set(final_population) != set(subjects)
    ):
        raise ExternalGateError("inventory collections differ from canonical subjects")
    unreconciled_exclusions: dict[str, list[str]] = {}
    for collection, candidates in final_population.items():
        source_by_sha = {
            item.get("content_sha256"): item for item in source_population[collection]
        }
        if len(source_by_sha) != len(source_population[collection]):
            raise ExternalGateError("source preparation inventory has duplicate derivative")
        if any(source_by_sha.get(item.get("content_sha256")) != item for item in candidates):
            raise ExternalGateError("candidate_inventory_sha256: derivative identity differs")
        removed = sorted(set(source_by_sha) - {
            item["content_sha256"] for item in candidates
        })
        if removed:
            # Un retrait est possible (ADR-0070 : « 253 ou moins »), mais il
            # demande une preuve d'exclusion gouvernée encore indisponible.
            unreconciled_exclusions[collection] = removed
        subject_ref = subjects[collection]
        subject = _read(
            release_root, subject_ref["path"], subject_ref["sha256"],
            f"canonical subjects.{collection}",
        )
        subject_placements = subject.get("placements")
        if not isinstance(subject_placements, list):
            raise ExternalGateError(f"canonical subjects.{collection}: placements absent")
        subject_pairs = [
            (item.get("artifact_id"), item.get("source_placement_id"))
            for item in subject_placements if isinstance(item, dict)
        ]
        if len(subject_pairs) != len(subject_placements) or len(set(subject_pairs)) != len(subject_pairs):
            raise ExternalGateError(f"canonical subjects.{collection}: duplicate placement")
        if _candidate_placement_pairs(candidates, collection) != set(subject_pairs):
            raise ExternalGateError(f"{collection}: inventory placement population differs")

    registry_ref = manifest.get("artifact_registry")
    if not isinstance(registry_ref, dict) or not isinstance(registry_ref.get("path"), str):
        raise ExternalGateError("final artifact registry reference absent")
    registry = _read(
        release_root, registry_ref["path"], registry_ref["sha256"],
        "final artifact registry",
    )
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, list):
        raise ExternalGateError("final artifact registry entries absent")
    inventory_by_sha: dict[str, Mapping[str, Any]] = {}
    for candidates in final_population.values():
        for candidate in candidates:
            sha = candidate.get("content_sha256")
            if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
                raise ExternalGateError("final inventory derivative identity invalid")
            previous = inventory_by_sha.setdefault(sha, candidate)
            if any(
                previous.get(name) != candidate.get(name)
                for name in ("source_pdf_sha256", "derivative_receipt_sha256", "media_type")
            ):
                raise ExternalGateError("final inventory shared derivative differs")
    registry_by_sha = {
        item.get("content_sha256"): item for item in artifacts if isinstance(item, dict)
    }
    if len(registry_by_sha) != len(artifacts) or set(registry_by_sha) != set(inventory_by_sha):
        raise ExternalGateError("final inventory differs from artifact registry population")
    for sha, candidate in inventory_by_sha.items():
        artifact = registry_by_sha[sha]
        if (
            artifact.get("artifact_id") != sha
            or artifact.get("source_pdf_sha256") != candidate.get("source_pdf_sha256")
            or artifact.get("derivative_receipt_sha256")
                != candidate.get("derivative_receipt_sha256")
            or artifact.get("media_type") != "text/plain; charset=utf-8"
        ):
            raise ExternalGateError("final inventory differs from artifact registry identity")
    return unreconciled_exclusions, index, source_inventory, final_inventory


def _verify_inclusion_population(
    attestation: Mapping[str, Any], index: Mapping[str, Any],
    source_inventory: Mapping[str, Any], final_inventory: Mapping[str, Any],
) -> None:
    """Relire les décisions #313, sans leur attribuer les droits ou la fraîcheur."""
    required = {
        "kind", "source_candidate_manifest_sha256", "source_candidate_inventory_sha256",
        "rights_authority_sha256", "pii_adjudication_report_sha256",
        "source_currentness_attestation_sha256", "fresh_source_index_file_sha256",
        "fresh_source_index_logical_sha256", "private_cas_manifest_sha256",
        "source_currentness_valid_until_utc", "decision_count", "evidence_pack_sha256",
        "decisions",
    }
    verified = index.get("verified_authorities")
    if not isinstance(verified, dict) or set(attestation) != required or (
        attestation.get("kind") != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_INCLUSIONS_V2"
    ):
        raise ExternalGateError("inclusion authority structure differs")
    bindings = {
        "source_candidate_manifest_sha256": verified.get("candidate_manifest_sha256"),
        "source_candidate_inventory_sha256": index.get("source_candidate_inventory_sha256"),
        "rights_authority_sha256": verified.get("rights_authority_sha256"),
        "pii_adjudication_report_sha256": verified.get("pii_adjudication_report_sha256"),
        "source_currentness_attestation_sha256": verified.get(
            "source_currentness_attestation_sha256"
        ),
        "fresh_source_index_file_sha256": verified.get("fresh_source_index_file_sha256"),
        "fresh_source_index_logical_sha256": index.get("fresh_source_index_logical_sha256"),
        "private_cas_manifest_sha256": verified.get("private_cas_manifest_sha256"),
        "source_currentness_valid_until_utc": index.get("source_currentness_valid_until_utc"),
    }
    sha_bindings = {
        field: expected for field, expected in bindings.items()
        if field != "source_currentness_valid_until_utc"
    }
    if any(
        not isinstance(expected, str) or _SHA256.fullmatch(expected) is None
        or attestation.get(field) != expected
        for field, expected in sha_bindings.items()
    ):
        raise ExternalGateError("inclusion preparation authority differs")
    valid_until = bindings["source_currentness_valid_until_utc"]
    if (not isinstance(valid_until, str) or not valid_until.endswith("Z")
            or attestation.get("source_currentness_valid_until_utc") != valid_until):
        raise ExternalGateError("inclusion preparation authority differs")
    try:
        parsed_until = datetime.fromisoformat(valid_until)
    except ValueError as exc:
        raise ExternalGateError("inclusion preparation authority differs") from exc
    if parsed_until.utcoffset() != UTC.utcoffset(parsed_until):
        raise ExternalGateError("inclusion preparation authority differs")
    decisions = attestation.get("decisions")
    source_by_sha: dict[str, str] = {}
    for candidates in _inventory_population(source_inventory).values():
        for candidate in candidates:
            sha = candidate["content_sha256"]
            source_pdf = candidate.get("source_pdf_sha256")
            if (not isinstance(source_pdf, str) or _SHA256.fullmatch(source_pdf) is None
                    or sha in source_by_sha and source_by_sha[sha] != source_pdf):
                raise ExternalGateError("inclusion source inventory identity differs")
            source_by_sha[sha] = source_pdf
    if (not isinstance(decisions, list)
            or attestation.get("decision_count") != len(source_by_sha)
            or len(decisions) != len(source_by_sha)
            or attestation.get("evidence_pack_sha256") != _sha(_canonical(decisions))):
        raise ExternalGateError("inclusion exact population or pack digest differs")
    included: set[str] = set()
    seen: set[str] = set()
    for row in decisions:
        if not isinstance(row, dict) or set(row) != {
            "content_sha256", "source_pdf_sha256", "disposition", "evidence_sha256",
            "pii_evidence_sha256", "currentness_evidence_sha256",
            "fresh_source_checkpoint_file_sha256",
        }:
            raise ExternalGateError("inclusion decision structure differs")
        sha = row["content_sha256"]
        if sha not in source_by_sha or sha in seen:
            raise ExternalGateError("inclusion derivative identity differs")
        seen.add(sha)
        if row["source_pdf_sha256"] != source_by_sha[sha]:
            raise ExternalGateError("inclusion source PDF differs")
        proof = {field: row[field] for field in (
            "pii_evidence_sha256", "currentness_evidence_sha256",
            "fresh_source_checkpoint_file_sha256",
        )}
        if (any(not isinstance(value, str) or _SHA256.fullmatch(value) is None
                for value in proof.values())
                or row["evidence_sha256"] != _sha(_canonical(proof))):
            raise ExternalGateError("inclusion evidence digest differs")
        if row["disposition"] == "INCLUDE":
            included.add(sha)
        elif row["disposition"] != "EXCLUDE":
            raise ExternalGateError("inclusion disposition is not final")
    if seen != set(source_by_sha):
        raise ExternalGateError("inclusion source population differs")
    final = {
        candidate["content_sha256"]
        for candidates in _inventory_population(final_inventory).values()
        for candidate in candidates
    }
    if not included or included != final:
        raise ExternalGateError("included derivative population differs")


def _verify_private_replay_bindings(
    source: Mapping[str, Any], replay: Mapping[str, Any],
    attestation: Mapping[str, Any], pr300: Mapping[str, Any],
    pr312: Mapping[str, Any], manifest: Mapping[str, Any], index: Mapping[str, Any],
) -> None:
    """Lier le rejeu privé aux reviews #300/#312 et à la release examinée."""
    inputs = source.get("inputs")
    authorities = manifest.get("authorities")
    if not isinstance(inputs, dict) or not isinstance(authorities, dict):
        raise ExternalGateError("private candidate authority differs")
    if (pr300.get("PR300_AUTHORITY_APPROVAL_PASS") is not True
            or pr312.get("PR312_AUTHORITY_APPROVAL_PASS") is not True
            or inputs.get("release_sha256")
                != authorities.get("source_candidate_release_manifest_sha256")
            or pr312.get("AGGREGATE_SHA256") != inputs.get("release_sha256")
            or pr312.get("ARTIFACTS_SHA256") != inputs.get("artifact_registry_sha256")
            or pr312.get("EXPECTED_COUNTS")
                != inputs.get("release", {}).get("expected_counts")
            or pr300.get("CANDIDATE_MANIFEST_SHA256")
                != inputs.get("candidate_manifest_sha256")
            or index.get("source_candidate_manifest_sha256")
                != inputs.get("release_sha256")
            or index.get("verified_authorities", {}).get("candidate_manifest_sha256")
                != inputs.get("candidate_manifest_sha256")):
        raise ExternalGateError("private candidate authority differs")
    if (replay != attestation
            or _sha(_canonical(replay)) != authorities.get("inclusion_attestation_sha256")
            or replay.get("private_cas_manifest_sha256")
                != index.get("private_cas_manifest_sha256")):
        raise ExternalGateError("private inclusion replay differs")


def _verify_preparation_semantics(
    source: Mapping[str, Any], replay: Mapping[str, Any],
    index: Mapping[str, Any], prepared_gate_root: Path,
) -> None:
    """Confronter les registres aux décisions rejouées et profils complets.

    Ces registres sont des candidats : leur validité ne délivre aucune autorité
    de scope, de droits ou d'actualité à la release finale.
    """
    inputs = source.get("inputs")
    sidecars = source.get("sidecars")
    verified = index.get("verified_authorities")
    if not all(isinstance(value, dict) for value in (inputs, sidecars, verified)):
        raise ExternalGateError("preparation registry sources missing")
    candidate_authorities = inputs.get("release", {}).get("authorities")
    if not isinstance(candidate_authorities, dict):
        raise ExternalGateError("preparation registry candidate authority missing")
    for name, authority in (
        ("public_profiles.json", "public_profile_registry_sha256"),
        ("public_rights_registry.json", "public_rights_registry_sha256"),
        ("public_pii_registry.json", "public_pii_registry_sha256"),
    ):
        value = sidecars.get(name)
        if not isinstance(value, dict) or _sha(_canonical(value)) != candidate_authorities.get(authority):
            raise ExternalGateError("preparation registry candidate digest differs")

    release_id = index.get("release_id")
    expected_manifest_sha = index.get("release_manifest_sha256")
    if (not isinstance(release_id, str)
            or re.fullmatch(r"student-public-successor-[0-9]{8}-[0-9a-f]{16}", release_id) is None
            or not isinstance(expected_manifest_sha, str)):
        raise ExternalGateError("preparation registry release identity differs")
    prepared_manifest = _read(
        prepared_gate_root, "production-profile-gate.release.json",
        expected_manifest_sha, "preparation registry manifest",
    )
    prepared_authorities = prepared_manifest.get("authorities")
    if (prepared_manifest.get("release_id") != release_id
            or not isinstance(prepared_authorities, dict)):
        raise ExternalGateError("preparation registry manifest authority differs")

    # Les deux paquets immuables ont des identités distinctes. Le mode v2 est
    # déterminé par les entrées rejouées, jamais par le champ profile d'un sujet.
    from build_student_public_successor_release import build_documents

    binding_modes = []
    for legacy in (True, False):
        documents = build_documents(dict(source), inclusion=dict(replay),
                                    legacy_profile_binding=legacy)
        generated_index = next(json.loads(raw) for path, raw in documents.items()
                               if path.name == "preparation-index.json")
        if generated_index["release_id"] == release_id:
            binding_modes.append(legacy)
    if len(binding_modes) != 1:
        raise ExternalGateError("preparation profile binding differs")
    complete_profile_binding = not binding_modes[0]

    expected = {
        row["content_sha256"]: row for row in replay.get("decisions", [])
        if isinstance(row, dict) and row.get("disposition") == "INCLUDE"
    }
    artifacts = inputs.get("artifacts", {}).get("artifacts")
    if (not isinstance(artifacts, list) or len(expected) != len(artifacts)
            or len(expected) != replay.get("decision_count")
            or any(not isinstance(row, dict) for row in artifacts)):
        raise ExternalGateError("preparation registry replay population differs")
    artifact_by_sha = {row.get("content_sha256"): row for row in artifacts}
    if len(artifact_by_sha) != len(artifacts) or set(artifact_by_sha) != set(expected):
        raise ExternalGateError("preparation registry artifact population differs")

    registry_specs = {
        "public_rights_registry.json": (
            "public_rights_registry_sha256", "NEXUS_STUDENT_PUBLIC_DERIVATIVE_RIGHTS_REGISTRY_V2",
            {"content_sha256", "source_pdf_sha256", "derivative_receipt_sha256",
             "citation_sha256", "currentness_evidence_sha256", "rights_basis"},
        ),
        "public_pii_registry.json": (
            "public_pii_registry_sha256", "NEXUS_STUDENT_PUBLIC_DERIVATIVE_PII_REGISTRY_V2",
            {"content_sha256", "source_pdf_sha256", "derivative_receipt_sha256",
             "pii_evidence_sha256", "pii_gate_status"},
        ),
        "public_currentness_registry.json": (
            "public_currentness_registry_sha256",
            "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CURRENTNESS_REGISTRY_V1",
            {"content_sha256", "source_pdf_sha256", "currentness_evidence_sha256",
             "fresh_source_checkpoint_file_sha256", "currentness_status", "revocation_status"},
        ),
    }
    for name, (authority, kind, fields) in registry_specs.items():
        sha = verified.get(authority)
        if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
            raise ExternalGateError("preparation registry authority differs")
        # La fraîcheur est scellée dans l'index #313, hors de l'agrégat #312.
        if (name != "public_currentness_registry.json"
                and prepared_authorities.get(authority) != sha):
            raise ExternalGateError("preparation registry authority differs")
        registry = _read(prepared_gate_root, name, sha, "preparation registry")
        if (registry.get("kind") != kind or registry.get("status") != "CANDIDATE_NOT_AUTHORIZED"
                or registry.get("release_id") != release_id):
            raise ExternalGateError("preparation registry status differs")
        entries = registry.get("entries")
        if (not isinstance(entries, list) or len(entries) != len(expected)
                or any(not isinstance(row, dict) or set(row) != fields for row in entries)):
            raise ExternalGateError("preparation registry row structure differs")
        rows = {row["content_sha256"]: row for row in entries}
        if len(rows) != len(entries) or set(rows) != set(expected):
            raise ExternalGateError("preparation registry exact population differs")
        if name == "public_rights_registry.json" and (
            registry.get("authorized_use") != "student_retrieval_excerpt_only"
            or registry.get("full_pdf_redistribution_allowed") is not False
            or registry.get("answer_generation_allowed") is not False
            or registry.get("rights_authority_sha256") != replay.get("rights_authority_sha256")
            or registry.get("source_currentness_attestation_sha256")
                != replay.get("source_currentness_attestation_sha256")
            or registry.get("inclusion_attestation_sha256")
                != index.get("inclusion_attestation_sha256")
            or registry.get("evidence_pack_sha256")
                != candidate_authorities.get("delegated_evidence_pack_sha256")
        ):
            raise ExternalGateError("preparation registry rights policy differs")
        if name == "public_pii_registry.json" and (
            registry.get("adjudication_report_sha256") != replay.get("pii_adjudication_report_sha256")
            or registry.get("evidence_pack_sha256")
                != candidate_authorities.get("delegated_evidence_pack_sha256")
        ):
            raise ExternalGateError("preparation registry PII authority differs")
        if name == "public_currentness_registry.json" and (
            registry.get("source_currentness_attestation_sha256")
                != replay.get("source_currentness_attestation_sha256")
            or registry.get("fresh_source_index_file_sha256")
                != replay.get("fresh_source_index_file_sha256")
            or registry.get("private_cas_manifest_sha256")
                != replay.get("private_cas_manifest_sha256")
            or registry.get("valid_until_utc")
                != replay.get("source_currentness_valid_until_utc")
        ):
            raise ExternalGateError("preparation registry currentness authority differs")
        for content_sha, row in rows.items():
            decision = expected[content_sha]
            artifact = artifact_by_sha[content_sha]
            if (row["source_pdf_sha256"] != decision["source_pdf_sha256"]
                    or row["source_pdf_sha256"] != artifact.get("source_pdf_sha256")):
                raise ExternalGateError("preparation registry source PDF differs")
            if name != "public_currentness_registry.json" and (
                row["derivative_receipt_sha256"] != artifact.get("derivative_receipt_sha256")
            ):
                raise ExternalGateError("preparation registry receipt differs")
            if name == "public_rights_registry.json" and (
                row["rights_basis"] != "EDUSCOL_ETALAB_2_0_SITEWIDE"
                or row["citation_sha256"] != _sha(_canonical(artifact.get("citation")))
                or row["currentness_evidence_sha256"]
                    != decision["currentness_evidence_sha256"]
            ):
                raise ExternalGateError("preparation registry rights evidence differs")
            if name == "public_pii_registry.json" and (
                row["pii_gate_status"] != "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"
                or row["pii_evidence_sha256"] != decision["pii_evidence_sha256"]
            ):
                raise ExternalGateError("preparation registry PII evidence differs")
            if name == "public_currentness_registry.json" and (
                row["currentness_status"] != "PASS"
                or row["revocation_status"] != "PASS_CURRENT_OFFICIAL_PUBLICATION"
                or row["currentness_evidence_sha256"]
                    != decision["currentness_evidence_sha256"]
                or row["fresh_source_checkpoint_file_sha256"]
                    != decision["fresh_source_checkpoint_file_sha256"]
            ):
                raise ExternalGateError("preparation registry currentness evidence differs")

    profiles_sha = prepared_authorities.get("public_profile_registry_sha256")
    if not isinstance(profiles_sha, str):
        raise ExternalGateError("preparation profile authority missing")
    profiles_registry = _read(prepared_gate_root, "public_profiles.json", profiles_sha,
                              "preparation profile registry")
    profiles = profiles_registry.get("entries")
    source_profiles = sidecars["public_profiles.json"].get("entries")
    source_refs = source.get("profile_refs")
    source_bytes = source.get("profiles")
    index_refs = index.get("complete_profiles")
    if (profiles_registry.get("kind") != "NEXUS_STUDENT_PUBLIC_SCOPE_CANDIDATES_V1"
            or profiles_registry.get("status") != "CANDIDATE_NOT_AUTHORIZED"
            or profiles_registry.get("release_id") != release_id
            or index.get("complete_profile_count") != 11
            or index.get("complete_profile_proposal_sha256")
                != source.get("profile_proposal_sha256")
            or not isinstance(profiles, list) or len(profiles) != 11
            or not isinstance(source_profiles, list) or not isinstance(source_refs, dict)
            or not isinstance(source_bytes, dict) or not isinstance(index_refs, list)
            or len(index_refs) != 11):
        raise ExternalGateError("preparation profile population differs")
    by_collection = {row.get("collection"): row for row in profiles if isinstance(row, dict)}
    source_by_collection = {
        row.get("collection"): row for row in source_profiles if isinstance(row, dict)
    }
    refs = {row.get("collection"): row for row in index_refs if isinstance(row, dict)}
    if (len(by_collection) != 11 or len(source_by_collection) != 11 or len(refs) != 11
            or set(by_collection) != set(source_by_collection)
            or set(by_collection) != set(source_refs)
            or set(by_collection) != set(source_bytes) or set(by_collection) != set(refs)):
        raise ExternalGateError("preparation profile exact population differs")
    for collection, row in by_collection.items():
        source_row = source_by_collection[collection]
        ref = refs[collection]
        source_ref = source_refs[collection]
        raw = source_bytes[collection]
        scope = row.get("scope")
        try:
            yaml_profile = yaml.safe_load(raw)
        except (TypeError, yaml.YAMLError) as exc:
            raise ExternalGateError("preparation profile YAML invalid") from exc
        yaml_scope = yaml_profile.get("scope") if isinstance(yaml_profile, dict) else None
        if (row != source_row or not isinstance(scope, dict)
                or scope.get("collection") != collection or scope.get("visibility") != "public"
                or row.get("profile_fingerprint") != _sha(_canonical(scope))
                or not isinstance(yaml_scope, dict)
                or any(scope.get(key) != value for key, value in yaml_scope.items())
                or ref != {**source_ref, "path": f"profile_gate/profiles/{collection}.yml"}
                or not isinstance(raw, bytes) or _sha(raw) != ref.get("sha256")
                or (prepared_gate_root / "profiles" / f"{collection}.yml").read_bytes() != raw):
            raise ExternalGateError("preparation profile binding differs")
    if complete_profile_binding:
        subject_refs = prepared_manifest.get("subjects")
        if not isinstance(subject_refs, list) or len(subject_refs) != len(refs):
            raise ExternalGateError("preparation profile binding differs")
        by_subject = {item.get("collection"): item for item in subject_refs
                      if isinstance(item, dict)}
        if set(by_subject) != set(refs) or len(by_subject) != len(subject_refs):
            raise ExternalGateError("preparation profile binding differs")
        for collection, ref in refs.items():
            subject_ref = by_subject[collection]
            subject = _read(prepared_gate_root, subject_ref.get("path", ""),
                            subject_ref.get("sha256", ""), "preparation profile binding")
            if subject.get("profile") != {
                "version": ref["profile_version"],
                "fingerprint": ref["fingerprint"],
                "manifest_digest": profiles_sha,
            }:
                raise ExternalGateError("preparation profile binding differs")


def _verify_private_cas_replay(
    private_cas_root: Path, repository_root: Path, attestation: Mapping[str, Any],
    manifest: Mapping[str, Any], index: Mapping[str, Any],
) -> None:
    """Réutiliser les vérificateurs existants ; toute panne laisse le gate rouge."""
    if not private_cas_root.is_dir() or not repository_root.is_dir():
        raise ExternalGateError("private CAS or repository root missing")
    try:
        from build_student_public_successor_release import load_sources
        from check_student_public_derivative_inclusions import (
            verify_private_cas_evidence,
        )
        from pr300_authority_receipt import check_pr300_authority
        from pr312_authority_receipt import check_pr312_authority

        pr300 = check_pr300_authority(repository_root)
        pr312 = check_pr312_authority(repository_root)
        source = load_sources(repository_root)
        replay = verify_private_cas_evidence(source, private_cas_root)
    except Exception as exc:
        raise ExternalGateError("private CAS replay or authority verification failed") from exc
    _verify_private_replay_bindings(source, replay, attestation, pr300, pr312,
                                    manifest, index)
    from build_student_public_successor_release import RELEASE_ROOT

    release_id = index.get("release_id")
    if (not isinstance(release_id, str)
            or re.fullmatch(r"student-public-successor-[0-9]{8}-([0-9a-f]{16})", release_id) is None):
        raise ExternalGateError("preparation registry release identity differs")
    suffix = release_id.rsplit("-", 1)[-1]
    prepared_gate_root = repository_root / RELEASE_ROOT / f"release-{suffix}" / "profile_gate"
    _verify_preparation_semantics(source, replay, index, prepared_gate_root)


def inspect_release(
    release_manifest_path: Path,
    expected_manifest_sha256: str,
    evidence_paths: Mapping[str, Path],
    *,
    private_cas_root: Path | None = None,
    repository_root: Path | None = None,
    transfer_destination_root: Path | None = None,
    transfer_target_identity: str | None = None,
) -> dict[str, Any]:
    """Inspecter une release finale, sans l'autoriser ni la publier."""
    if _SHA256.fullmatch(expected_manifest_sha256) is None:
        raise ExternalGateError("expected release manifest SHA-256 invalid")
    if set(evidence_paths) - AUTHORITY_FIELDS:
        raise ExternalGateError("unknown authority in evidence mapping")
    transfer_fields = {
        "artifact_transfer_manifest_sha256",
        "observed_transfer_receipt_sha256",
    }
    if transfer_fields & set(evidence_paths) and not transfer_fields <= set(evidence_paths):
        raise ExternalGateError("transfer evidence must be paired")
    if transfer_fields <= set(evidence_paths) and (
        transfer_destination_root is None or not transfer_target_identity
    ):
        raise ExternalGateError("observed transfer requires destination and target identity")
    root = release_manifest_path.resolve().parent
    manifest = _read(root, release_manifest_path.name, expected_manifest_sha256,
                     "release manifest")
    if manifest.get("release_mode") != "public_successor":
        raise ExternalGateError("release_mode must be public_successor")
    authorities = manifest.get("authorities")
    if not isinstance(authorities, dict) or set(authorities) != AUTHORITY_FIELDS:
        raise ExternalGateError("public_successor requires exactly 21 authorities")
    for name, value in authorities.items():
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise ExternalGateError(f"{name}: invalid declared SHA-256")

    # Le parseur canonique valide agrégat, sujets, artefacts et cardinalités.
    # Son refus terminal est la seule issue actuellement autorisée.
    try:
        load_release_expectation(release_manifest_path, expected_manifest_sha256)
    except ReleaseReadinessError as exc:
        if str(exc) != _SHAPE_REJECTION:
            raise ExternalGateError(f"release-chain structure refused: {exc}") from exc
    else:
        raise ExternalGateError("release-chain unexpectedly accepted public successor")

    unreconciled_exclusions, index, source_inventory, final_inventory = (
        _verify_preparation_chain(root, manifest, authorities)
    )
    verified_bytes = set(_LOCAL_FILES)
    evidence_bytes: dict[str, bytes] = {}
    inclusion_population_verified = False
    inclusion_attestation: dict[str, Any] | None = None
    for name, path in evidence_paths.items():
        resolved = path.resolve()
        if not resolved.is_file():
            raise ExternalGateError(f"{name}: evidence SHA-256 differs or file absent")
        raw = resolved.read_bytes()
        if _sha(raw) != authorities[name]:
            raise ExternalGateError(f"{name}: evidence SHA-256 differs or file absent")
        evidence_bytes[name] = raw
        if name == "inclusion_attestation_sha256":
            index_verified = index.get("verified_authorities")
            if (authorities[name] != index.get("inclusion_attestation_sha256")
                    or not isinstance(index_verified, dict)
                    or authorities[name] != index_verified.get(name)):
                raise ExternalGateError("inclusion preparation index digest differs")
            try:
                attestation = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ExternalGateError("inclusion evidence JSON invalid") from exc
            if not isinstance(attestation, dict):
                raise ExternalGateError("inclusion evidence must be an object")
            _verify_inclusion_population(attestation, index, source_inventory, final_inventory)
            inclusion_population_verified = True
            inclusion_attestation = attestation
        verified_bytes.add(name)

    transfer_bytes_replayed = False
    if transfer_fields <= set(evidence_paths):
        try:
            transfer_plan = json.loads(evidence_bytes["artifact_transfer_manifest_sha256"])
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExternalGateError("transfer plan JSON invalid") from exc
        if (
            not isinstance(transfer_plan, dict)
            or transfer_plan.get("inventory_sha256")
            != authorities["candidate_inventory_sha256"]
        ):
            raise ExternalGateError("transfer inventory differs from final release")
        final_candidates = {
            item["content_sha256"]: item
            for candidates in _inventory_population(final_inventory).values()
            for item in candidates
        }
        expected_files = {
            (f"{sha}.txt", sha) for sha in final_candidates
        }
        expected_receipts = {
            (f"derivative_receipts/{item['derivative_receipt_sha256']}.json",
             item["derivative_receipt_sha256"])
            for item in final_candidates.values()
        }
        plan_files = transfer_plan.get("files")
        plan_receipts = transfer_plan.get("derivative_receipts")
        if (
            transfer_plan.get("release_id") != manifest["release_id"]
            or transfer_plan.get("file_count") != len(expected_files)
            or transfer_plan.get("placement_count")
                != manifest["expected_counts"]["placements"]
            or transfer_plan.get("derivative_receipt_count") != len(expected_receipts)
            or not isinstance(plan_files, list)
            or not isinstance(plan_receipts, list)
            or len(plan_files) != len(expected_files)
            or len(plan_receipts) != len(expected_receipts)
            or any(not isinstance(row, dict) for row in plan_files + plan_receipts)
            or {(row.get("file"), row.get("sha256_expected")) for row in plan_files}
                != expected_files
            or {(row.get("file"), row.get("sha256_expected")) for row in plan_receipts}
                != expected_receipts
        ):
            raise ExternalGateError("transfer population differs from final release")
        assert transfer_destination_root is not None
        assert transfer_target_identity is not None
        try:
            verify_observed_destination(
                evidence_bytes["artifact_transfer_manifest_sha256"],
                evidence_bytes["observed_transfer_receipt_sha256"],
                transfer_destination_root,
                transfer_target_identity,
            )
        except TransferRefused as exc:
            raise ExternalGateError(f"observed transfer differs: {exc}") from exc
        transfer_bytes_replayed = True

    if (private_cas_root is None) != (repository_root is None):
        raise ExternalGateError("private replay requires repository and CAS roots")
    private_replay_verified = False
    if private_cas_root is not None and repository_root is not None:
        if inclusion_attestation is None:
            raise ExternalGateError("private replay requires inclusion evidence")
        _verify_private_cas_replay(
            private_cas_root, repository_root, inclusion_attestation, manifest, index,
        )
        private_replay_verified = True

    # Le transfert est re-haché si plan, reçu et destination sont fournis,
    # mais l'identité de cible reste CLAIMED_UNQUALIFIED. Les revues GitHub,
    # LOT41A/LOT42 et autres autorités finales ne sont pas vérifiées ici.
    return {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_EXTERNAL_GATE_DIAGNOSTIC_V1",
        "release_manifest_sha256": expected_manifest_sha256,
        "release_id": manifest["release_id"],
        "release_counts": manifest["expected_counts"],
        "authority_count": len(authorities),
        "preparation_subset_lineage_verified": True,
        "preparation_chain_verified": not bool(unreconciled_exclusions),
        "preparation_inclusion_population_verified": inclusion_population_verified,
        "preparation_private_cas_replay_verified": private_replay_verified,
        "preparation_registries_verified": private_replay_verified,
        "preparation_profiles_verified": private_replay_verified,
        "transfer_bytes_replayed": transfer_bytes_replayed,
        "unreconciled_preparation_exclusions": unreconciled_exclusions,
        "bytes_verified_authorities": sorted(verified_bytes),
        "unverified_authorities": sorted(AUTHORITY_FIELDS - verified_bytes),
        "semantic_unverified_authorities": sorted(AUTHORITY_FIELDS),
        "semantic_verification_complete": False,
        "PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS": False,
        "PROMOTION_ALLOWED": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--evidence-map", type=Path, help="JSON field → path (inclusion opened)")
    parser.add_argument("--private-cas-root", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--transfer-destination-root", type=Path)
    parser.add_argument("--transfer-target-identity")
    parser.add_argument("--assert-ready", action="store_true")
    args = parser.parse_args()
    try:
        evidence_map = json.loads(args.evidence_map.read_text()) if args.evidence_map else {}
        if not isinstance(evidence_map, dict) or not all(
            isinstance(name, str) and isinstance(path, str)
            for name, path in evidence_map.items()
        ):
            raise ExternalGateError("evidence map must be a JSON object of paths")
        result = inspect_release(
            args.release_manifest, args.expected_manifest_sha256,
            {name: Path(path) for name, path in evidence_map.items()},
            private_cas_root=args.private_cas_root,
            repository_root=args.repository_root,
            transfer_destination_root=args.transfer_destination_root,
            transfer_target_identity=args.transfer_target_identity,
        )
    except (ExternalGateError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"PUBLIC_SUCCESSOR_EXTERNAL_GATE_PASS": False, "error": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # Le mode diagnostic et --assert-ready restent tous deux rouges : un code
    # zéro serait trop facile à interpréter comme une autorisation de promotion.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
