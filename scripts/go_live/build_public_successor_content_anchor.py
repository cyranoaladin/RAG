"""Sceller l'identité de contenu du successeur avant ses autorités externes.

Ce fichier n'émet ni scope, ni attestation, ni autorisation de publication.
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

from nexus_release_chain.release_readiness import (
    _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS,
    ReleaseReadinessError,
    load_release_expectation,
)

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
TEXT_MIME = "text/plain; charset=utf-8"


class ContentAnchorError(ValueError):
    """Le contenu préparatoire ne possède pas l'identité déclarée."""


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path, expected: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        raise ContentAnchorError(f"missing content file: {path.name}")
    raw = path.read_bytes()
    if expected is not None and _sha(raw) != expected:
        raise ContentAnchorError(f"content SHA mismatch: {path.name}")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContentAnchorError(f"invalid JSON: {path.name}") from error
    if not isinstance(document, dict) or canonical_bytes(document) != raw:
        raise ContentAnchorError(f"noncanonical JSON: {path.name}")
    return document


def build_content_anchor(manifest_path: Path, expected_sha256: str) -> dict[str, Any]:
    """Relire les 34 documents #323 et nommer leur contenu immuable.

    La sortie ne constitue jamais un verdict de promotion. Les autorités de
    droits, scopes, LOT41A/LOT42, transfert et révocation restent externes.
    """
    if SHA256.fullmatch(expected_sha256) is None:
        raise ContentAnchorError("expected content manifest SHA invalid")
    manifest_path = manifest_path.resolve()
    gate = manifest_path.parent
    release = gate.parent
    manifest = _read(manifest_path, expected_sha256)
    index_path = release / "preparation-index.json"
    index = _read(index_path)
    try:
        parsed = load_release_expectation(manifest_path, expected_sha256)
    except ReleaseReadinessError as error:
        raise ContentAnchorError(f"release-chain refused content: {error}") from error
    if (
        manifest.get("release_mode") != "candidate"
        or manifest.get("promotion_status") != "NOT_PROMOTABLE"
        or manifest.get("review_status") != "PRE_REVIEW"
        or manifest.get("activation_status") != "NO_PRODUCTION_ACTIVATION"
        or not str(manifest.get("release_id", "")).startswith("student-public-successor-")
        or index.get("kind") != "NEXUS_STUDENT_PUBLIC_SUCCESSOR_PREPARATION_V2"
        or index.get("status") != "PREPARATION_ONLY_NOT_ACTIVABLE"
        or index.get("transfer_status") != "NOT_TRANSFERRED"
        or index.get("release_id") != manifest.get("release_id")
        or index.get("release_manifest_sha256") != expected_sha256
        or index.get("expected_counts") != manifest.get("expected_counts")
        or parsed.release_id != manifest.get("release_id")
    ):
        raise ContentAnchorError("preparation identity or nonactivation status differs")
    registry_ref = manifest.get("artifact_registry")
    if not isinstance(registry_ref, dict) or registry_ref.get("path") != "artifacts.release.json":
        raise ContentAnchorError("artifact registry path differs")
    registry_sha = registry_ref.get("sha256")
    inventory_sha = index.get("candidate_inventory_sha256")
    if not isinstance(registry_sha, str) or not isinstance(inventory_sha, str):
        raise ContentAnchorError("content digests missing")
    registry = _read(gate / "artifacts.release.json", registry_sha)
    inventory = _read(gate / "candidate_inventory.json", inventory_sha)
    manifest_authorities = manifest.get("authorities")
    verified_authorities = index.get("verified_authorities")
    if not isinstance(manifest_authorities, dict) or not isinstance(verified_authorities, dict):
        raise ContentAnchorError("preparation sidecar authorities absent")
    sidecar_bindings = {
        "public_profiles.json": ("public_profile_registry_sha256", manifest_authorities),
        "public_rights_registry.json": ("public_rights_registry_sha256", manifest_authorities),
        "public_pii_registry.json": ("public_pii_registry_sha256", manifest_authorities),
        "public_currentness_registry.json": (
            "public_currentness_registry_sha256", verified_authorities,
        ),
        "inclusion_attestation.json": ("inclusion_attestation_sha256", index),
    }
    sidecars: dict[str, str] = {}
    for name, (field, authority) in sidecar_bindings.items():
        sha = authority.get(field)
        if not isinstance(sha, str) or SHA256.fullmatch(sha) is None:
            raise ContentAnchorError(f"preparation sidecar authority invalid: {name}")
        try:
            _read(gate / name, sha)
        except ContentAnchorError as error:
            raise ContentAnchorError(f"preparation sidecar refused: {name}") from error
        if (field in verified_authorities and verified_authorities[field] != sha):
            raise ContentAnchorError(f"preparation sidecar authority differs: {name}")
        sidecars[name] = sha
    if (
        index.get("artifact_registry_sha256") != registry_sha
        or inventory.get("artifact_registry_sha256") != registry_sha
        or inventory.get("release_manifest_sha256") != expected_sha256
        or inventory.get("release_id") != manifest["release_id"]
        or inventory.get("counts") != {
            "collections": manifest["expected_counts"]["subjects"],
            "unique_artifacts": manifest["expected_counts"]["unique_artifacts"],
            "placements": manifest["expected_counts"]["placements"],
        }
        or any(item.get("media_type") != TEXT_MIME
               or item.get("source_pdf_sha256") == item.get("content_sha256")
               for item in registry.get("artifacts", []))
        or any(item.payload.get("visibility") != "public" for item in parsed.placements)
    ):
        raise ContentAnchorError("public text inventory or placement differs")
    refs = manifest.get("subjects")
    scopes = index.get("proposed_scopes")
    profiles = index.get("complete_profiles")
    if (
        not isinstance(refs, list) or len(refs) != 11
        or not isinstance(scopes, list) or len(scopes) != len(refs)
        or not isinstance(profiles, list) or len(profiles) != len(refs)
    ):
        raise ContentAnchorError("eleven content subjects, scopes and profiles required")
    by_collection = {row.get("collection"): row for row in refs if isinstance(row, dict)}
    scope_by_collection = {row.get("collection"): row for row in scopes if isinstance(row, dict)}
    profile_by_collection = {row.get("collection"): row for row in profiles if isinstance(row, dict)}
    if any(len(mapping) != 11 for mapping in (by_collection, scope_by_collection,
                                             profile_by_collection)) or not (
        set(by_collection) == set(scope_by_collection) == set(profile_by_collection)
    ):
        raise ContentAnchorError("content collection population differs")
    subjects: list[dict[str, str]] = []
    for collection, ref in sorted(by_collection.items()):
        expected_path = f"subjects/{collection}.release.json"
        scope = scope_by_collection[collection]
        profile = profile_by_collection[collection]
        if (
            ref.get("path") != expected_path
            or scope.get("status") != "NOT_ISSUED"
            or scope.get("final_subject_sha256") != ref.get("sha256")
            or profile.get("path") != f"profile_gate/profiles/{collection}.yml"
        ):
            raise ContentAnchorError("scope or profile changed prepared subject")
        subject = _read(gate / expected_path, ref["sha256"])
        profile_path = release / profile["path"]
        if _sha(profile_path.read_bytes()) != profile.get("sha256"):
            raise ContentAnchorError("complete profile SHA differs")
        if subject.get("collection") != collection:
            raise ContentAnchorError("subject collection differs")
        subjects.append({"collection": collection, "path": expected_path,
                         "subject_sha256": ref["sha256"],
                         "profile_sha256": profile["sha256"]})
    return {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_CONTENT_ANCHOR_V1",
        "status": "CONTENT_ONLY_NOT_ACTIVABLE",
        "activation_allowed": False,
        "content_release_id": manifest["release_id"],
        "content_manifest_sha256": expected_sha256,
        "preparation_index_sha256": _sha(index_path.read_bytes()),
        "artifact_registry_sha256": registry_sha,
        "candidate_inventory_sha256": inventory_sha,
        "preparation_sidecars": sidecars,
        "expected_counts": manifest["expected_counts"],
        "subjects": subjects,
    }


def write_content_anchor(path: Path, anchor: dict[str, Any]) -> None:
    raw = canonical_bytes(anchor)
    if path.exists():
        if path.read_bytes() != raw:
            raise ContentAnchorError("refusing to replace divergent content anchor")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def build_authority_envelope(
    anchor_path: Path,
    expected_anchor_sha256: str,
    evidence_paths: dict[str, Path],
) -> dict[str, Any]:
    """Sceller des octets externes, sans en déduire leur valeur juridique.

    L'enveloppe C référence le contenu A ; A ne contient jamais le SHA de C.
    Les revues et LOT42 peuvent donc lier A sans cercle cryptographique. Un
    vérificateur sémantique et les contrôles Worker/runtime restent nécessaires.
    """
    if SHA256.fullmatch(expected_anchor_sha256) is None:
        raise ContentAnchorError("expected content anchor SHA invalid")
    anchor = _read(anchor_path, expected_anchor_sha256)
    if set(evidence_paths) != _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS:
        raise ContentAnchorError("authority envelope requires exactly 21 evidence files")
    content_path = evidence_paths["source_preparation_release_manifest_sha256"]
    if build_content_anchor(content_path, anchor.get("content_manifest_sha256", "")) != anchor:
        raise ContentAnchorError("content anchor does not match immutable preparation")
    authorities: dict[str, str] = {}
    for field, path in sorted(evidence_paths.items()):
        if not path.is_file():
            raise ContentAnchorError(f"authority evidence missing: {field}")
        raw = path.read_bytes()
        if not raw:
            raise ContentAnchorError(f"authority evidence empty: {field}")
        authorities[field] = _sha(raw)
    if (
        authorities["source_preparation_release_manifest_sha256"]
        != anchor["content_manifest_sha256"]
        or authorities["source_preparation_index_sha256"]
        != anchor["preparation_index_sha256"]
        or authorities["candidate_inventory_sha256"]
        != anchor["candidate_inventory_sha256"]
    ):
        raise ContentAnchorError("authority evidence differs from content anchor")
    return {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_AUTHORITY_ENVELOPE_V1",
        "status": "EVIDENCE_BYTES_ONLY_NOT_ACTIVABLE",
        "activation_allowed": False,
        "semantic_verification_complete": False,
        "content_anchor_sha256": expected_anchor_sha256,
        "content_release_id": anchor["content_release_id"],
        "content_manifest_sha256": anchor["content_manifest_sha256"],
        "expected_counts": anchor["expected_counts"],
        "authorities": authorities,
    }


def inspect_content_preparation(
    manifest_path: Path,
    expected_manifest_sha256: str,
    *,
    private_cas_root: Path | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Rejouer la population #313 réelle directement depuis A, sans C."""
    anchor = build_content_anchor(manifest_path, expected_manifest_sha256)
    if (private_cas_root is None) != (repository_root is None):
        raise ContentAnchorError("private replay needs repository and CAS together")
    gate = manifest_path.resolve().parent
    index = _read(gate.parent / "preparation-index.json")
    inventory = _read(gate / "candidate_inventory.json",
                      anchor["candidate_inventory_sha256"])
    if index.get("excluded_derivative_count") != 0:
        raise ContentAnchorError(
            "source inventory distinct from final requires a new replay path"
        )
    inclusion_path = gate / "inclusion_attestation.json"
    inclusion = _read(inclusion_path, index.get("inclusion_attestation_sha256"))
    from check_public_successor_external_gate import (
        ExternalGateError,
        _verify_inclusion_population,
        _verify_private_cas_replay,
    )

    try:
        _verify_inclusion_population(inclusion, index, inventory, inventory)
        if private_cas_root is not None and repository_root is not None:
            _verify_private_cas_replay(
                private_cas_root, repository_root, inclusion,
                {"authorities": {
                    "source_candidate_release_manifest_sha256": index[
                        "source_candidate_manifest_sha256"
                    ],
                    "inclusion_attestation_sha256": _sha(inclusion_path.read_bytes()),
                }}, index,
            )
    except ExternalGateError as error:
        raise ContentAnchorError(f"preparation replay refused: {error}") from error
    valid_until = index.get("source_currentness_valid_until_utc")
    try:
        currentness_open = (
            isinstance(valid_until, str)
            and datetime.fromisoformat(valid_until) > datetime.now(UTC)
        )
    except ValueError:
        currentness_open = False
    return {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_PREPARATION_REPLAY_V1",
        "content_manifest_sha256": expected_manifest_sha256,
        "inclusion_population_verified": True,
        "private_cas_replay_verified": private_cas_root is not None,
        "source_currentness_window_open": currentness_open,
        "semantic_verification_complete": False,
        "activation_allowed": False,
    }


def inspect_envelope_preparation(
    anchor_path: Path,
    envelope: Mapping[str, Any],
    evidence_paths: dict[str, Path],
    *,
    private_cas_root: Path | None = None,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Rejouer les preuves A/#313 possibles sans octroyer l'activation C."""
    if not isinstance(envelope, dict) or envelope.get("kind") != (
        "NEXUS_PUBLIC_SUCCESSOR_AUTHORITY_ENVELOPE_V1"
    ):
        raise ContentAnchorError("authority envelope kind differs")
    expected_anchor_sha = envelope.get("content_anchor_sha256")
    if not isinstance(expected_anchor_sha, str):
        raise ContentAnchorError("authority envelope anchor missing")
    rebuilt = build_authority_envelope(anchor_path, expected_anchor_sha, evidence_paths)
    if rebuilt != envelope:
        raise ContentAnchorError("authority envelope differs from evidence bytes")
    anchor = _read(anchor_path, expected_anchor_sha)
    index = _read(evidence_paths["source_preparation_index_sha256"])
    inclusion_path = evidence_paths["inclusion_attestation_sha256"]
    if (
        _sha(inclusion_path.read_bytes()) != index.get("inclusion_attestation_sha256")
        or index.get("candidate_inventory_sha256") != anchor["candidate_inventory_sha256"]
        or index.get("release_manifest_sha256") != anchor["content_manifest_sha256"]
    ):
        raise ContentAnchorError("inclusion preparation authority differs")
    replayed = inspect_content_preparation(
        evidence_paths["source_preparation_release_manifest_sha256"],
        anchor["content_manifest_sha256"],
        private_cas_root=private_cas_root, repository_root=repository_root,
    )
    verified = {
        "source_preparation_release_manifest_sha256",
        "source_preparation_index_sha256",
        "candidate_inventory_sha256",
        "inclusion_attestation_sha256",
    }
    private_replayed = replayed["private_cas_replay_verified"]
    if private_replayed:
        verified.add("source_candidate_release_manifest_sha256")
    return {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_PREPARATION_REPLAY_V1",
        "content_anchor_sha256": expected_anchor_sha,
        "inclusion_population_verified": replayed["inclusion_population_verified"],
        "private_cas_replay_verified": private_replayed,
        "source_currentness_window_open": replayed["source_currentness_window_open"],
        "verified_preparation_authorities": sorted(verified),
        "unverified_authorities": sorted(
            _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS - verified
        ),
        "semantic_verification_complete": False,
        "activation_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        anchor = build_content_anchor(args.manifest, args.expected_sha256)
        write_content_anchor(args.output, anchor)
    except (ContentAnchorError, OSError) as error:
        parser.exit(2, f"content anchor refused: {error}\n")
    print(json.dumps({"content_anchor_sha256": _sha(canonical_bytes(anchor)),
                      "activation_allowed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
