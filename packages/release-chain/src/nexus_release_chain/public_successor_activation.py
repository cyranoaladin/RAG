"""Lecture portable de A : identité du corpus public préparatoire, sans activation.

Le paquet A reste `candidate/NOT_PROMOTABLE`. L'autorité d'ingestion et celle
de publication sont des preuves extérieures distinctes, liées à son digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from nexus_contracts.scope import RetrievalScopeArtifactV3

from nexus_release_chain.release_readiness import (
    _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS,
    ReleaseReadinessError,
    load_release_expectation,
    load_release_registry_file,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ANCHOR_KIND = "NEXUS_PUBLIC_SUCCESSOR_CONTENT_ANCHOR_V1"
_TEXT_MIME = "text/plain; charset=utf-8"


class PublicSuccessorActivationError(ValueError):
    """Une identité ou une autorité publique manque ou diverge."""


@dataclass(frozen=True)
class PublicSuccessorContentVerdict:
    release_id: str
    content_anchor_sha256: str
    content_manifest_sha256: str
    preparation_index_sha256: str
    candidate_inventory_sha256: str
    currentness_registry_sha256: str
    artifact_registry_sha256: str
    release_registry_sha256: str
    subject_sha256_by_collection: dict[str, str]
    profile_sha256_by_collection: dict[str, str]
    expected_counts: dict[str, int]
    activation_allowed: bool = False


@dataclass(frozen=True)
class PublicSuccessorActivationVerdict:
    release_id: str
    content_anchor_sha256: str
    content_manifest_sha256: str
    authority_envelope_sha256: str
    artifact_registry_sha256: str
    release_registry_sha256: str
    scope_authority_sha256: str
    subject_sha256_by_collection: dict[str, str]
    scope_sha256_by_id: dict[str, str]
    counts: dict[str, int]
    expires_at_utc: datetime


def _read(root: Path, relative: str, expected: str, *, json_required: bool = True) -> Any:
    if _SHA256.fullmatch(expected) is None:
        raise PublicSuccessorActivationError(f"{relative}: invalid expected digest")
    root = root.resolve()
    unresolved = root / relative
    walked = root
    for part in Path(relative).parts:
        walked /= part
        if walked.is_symlink():
            raise PublicSuccessorActivationError(f"{relative}: symlink content refused")
    candidate = unresolved.resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise PublicSuccessorActivationError(f"{relative}: absent or outside content root")
    raw = candidate.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise PublicSuccessorActivationError(f"{relative}: digest differs")
    if not json_required:
        return raw
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicSuccessorActivationError(f"{relative}: invalid JSON") from error
    canonical = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if not isinstance(document, dict) or raw != canonical:
        raise PublicSuccessorActivationError(f"{relative}: noncanonical JSON")
    return document


def verify_content_anchor(
    anchor_path: Path, expected_anchor_sha256: str, release_root: Path,
) -> PublicSuccessorContentVerdict:
    """Relire les octets de A dans un bundle ou un checkout, jamais les statuts seuls."""
    anchor = _read(anchor_path.parent, anchor_path.name, expected_anchor_sha256)
    if set(anchor) != {
        "activation_allowed", "artifact_registry_sha256", "candidate_inventory_sha256",
        "content_manifest_sha256", "content_release_id", "expected_counts", "kind",
        "preparation_index_sha256", "preparation_sidecars", "status", "subjects",
    } or (
        anchor.get("kind") != _ANCHOR_KIND
        or anchor.get("status") != "CONTENT_ONLY_NOT_ACTIVABLE"
        or anchor.get("activation_allowed") is not False
    ):
        raise PublicSuccessorActivationError("content anchor is not immutable preparation")
    root = release_root.resolve()
    gate = root / "profile_gate"
    manifest = _read(gate, "production-profile-gate.release.json", anchor["content_manifest_sha256"])
    index = _read(root, "preparation-index.json", anchor["preparation_index_sha256"])
    if not (
        manifest.get("release_mode") == "candidate"
        and manifest.get("promotion_status") == "NOT_PROMOTABLE"
        and manifest.get("review_status") == "PRE_REVIEW"
        and manifest.get("activation_status") == "NO_PRODUCTION_ACTIVATION"
        and manifest.get("release_id") == anchor["content_release_id"]
        and manifest.get("expected_counts") == anchor["expected_counts"]
        and index.get("kind") == "NEXUS_STUDENT_PUBLIC_SUCCESSOR_PREPARATION_V2"
        and index.get("status") == "PREPARATION_ONLY_NOT_ACTIVABLE"
        and index.get("transfer_status") == "NOT_TRANSFERRED"
        and index.get("release_id") == anchor["content_release_id"]
        and index.get("release_manifest_sha256") == anchor["content_manifest_sha256"]
        and index.get("candidate_inventory_sha256") == anchor["candidate_inventory_sha256"]
    ):
        raise PublicSuccessorActivationError("content manifest or index differs from A")
    registry_ref = manifest.get("artifact_registry")
    if not isinstance(registry_ref, dict) or registry_ref != {
        "path": "artifacts.release.json", "sha256": anchor["artifact_registry_sha256"],
    }:
        raise PublicSuccessorActivationError("artifact registry is not bound to A")
    registry = _read(gate, "artifacts.release.json", anchor["artifact_registry_sha256"])
    inventory = _read(gate, "candidate_inventory.json", anchor["candidate_inventory_sha256"])
    if (
        index.get("artifact_registry_sha256") != anchor["artifact_registry_sha256"]
        or inventory.get("artifact_registry_sha256") != anchor["artifact_registry_sha256"]
        or inventory.get("release_manifest_sha256") != anchor["content_manifest_sha256"]
        or inventory.get("release_id") != anchor["content_release_id"]
        or any(
            item.get("media_type") != _TEXT_MIME
            or item.get("content_sha256") == item.get("source_pdf_sha256")
            for item in registry.get("artifacts", [])
        )
    ):
        raise PublicSuccessorActivationError("public derivative inventory differs")
    expected_sidecars = {
        "public_profiles.json": ("public_profile_registry_sha256", manifest.get("authorities")),
        "public_rights_registry.json": ("public_rights_registry_sha256", manifest.get("authorities")),
        "public_pii_registry.json": ("public_pii_registry_sha256", manifest.get("authorities")),
        "public_currentness_registry.json": (
            "public_currentness_registry_sha256", index.get("verified_authorities"),
        ),
        "inclusion_attestation.json": ("inclusion_attestation_sha256", index),
    }
    if not isinstance(anchor.get("preparation_sidecars"), dict) or set(
        anchor["preparation_sidecars"]
    ) != set(expected_sidecars):
        raise PublicSuccessorActivationError("A sidecar population differs")
    for name, (field, authority) in expected_sidecars.items():
        if not isinstance(authority, dict) or (
            authority.get(field) != anchor["preparation_sidecars"][name]
        ):
            raise PublicSuccessorActivationError(f"{name}: sidecar authority differs")
        _read(gate, name, anchor["preparation_sidecars"][name])
    refs = manifest.get("subjects")
    subjects = anchor.get("subjects")
    if not isinstance(refs, list) or not isinstance(subjects, list) or len(refs) != 11 or len(subjects) != 11:
        raise PublicSuccessorActivationError("eleven subject references required")
    by_collection = {row.get("collection"): row for row in refs if isinstance(row, dict)}
    observed: dict[str, str] = {}
    profiles: dict[str, str] = {}
    for row in subjects:
        if not isinstance(row, dict) or set(row) != {
            "collection", "path", "subject_sha256", "profile_sha256",
        }:
            raise PublicSuccessorActivationError("A subject binding malformed")
        collection = row["collection"]
        expected_path = f"subjects/{collection}.release.json"
        if collection in observed or row["path"] != expected_path or by_collection.get(collection) != {
            "collection": collection, "path": expected_path, "sha256": row["subject_sha256"],
        }:
            raise PublicSuccessorActivationError("A subject binding differs")
        subject = _read(gate, expected_path, row["subject_sha256"])
        _read(gate, f"profiles/{collection}.yml", row["profile_sha256"], json_required=False)
        if subject.get("collection") != collection:
            raise PublicSuccessorActivationError("A subject collection differs")
        observed[collection] = row["subject_sha256"]
        profiles[collection] = row["profile_sha256"]
    if len(by_collection) != 11 or set(by_collection) != set(observed):
        raise PublicSuccessorActivationError("A subject population differs")
    try:
        parsed = load_release_expectation(gate / "production-profile-gate.release.json",
                                          anchor["content_manifest_sha256"])
    except ReleaseReadinessError as error:
        raise PublicSuccessorActivationError("release-chain refused A content") from error
    if parsed.release_id != anchor["content_release_id"] or any(
        row.payload.get("visibility") != "public" for row in parsed.placements
    ):
        raise PublicSuccessorActivationError("A release identity or visibility differs")
    registry_path = root / "release-registry.json"
    try:
        release_registry_sha = hashlib.sha256(registry_path.read_bytes()).hexdigest()
        release_registry = load_release_registry_file(registry_path, release_registry_sha)
    except (OSError, ReleaseReadinessError) as error:
        raise PublicSuccessorActivationError("A release registry invalid") from error
    if (
        len(release_registry.manifests) != 1
        or release_registry.manifests[0].expected_sha256 != anchor["content_manifest_sha256"]
        or release_registry.manifests[0].expectation.release_id != anchor["content_release_id"]
        or set(release_registry.collections) != set(observed)
    ):
        raise PublicSuccessorActivationError("A release registry differs from manifest")
    return PublicSuccessorContentVerdict(
        release_id=anchor["content_release_id"],
        content_anchor_sha256=expected_anchor_sha256,
        content_manifest_sha256=anchor["content_manifest_sha256"],
        preparation_index_sha256=anchor["preparation_index_sha256"],
        candidate_inventory_sha256=anchor["candidate_inventory_sha256"],
        currentness_registry_sha256=anchor["preparation_sidecars"][
            "public_currentness_registry.json"
        ],
        artifact_registry_sha256=anchor["artifact_registry_sha256"],
        release_registry_sha256=release_registry_sha,
        subject_sha256_by_collection=observed,
        profile_sha256_by_collection=profiles,
        expected_counts=anchor["expected_counts"],
    )


def verify_public_scope_registry(
    registry_path: Path,
    expected_registry_sha256: str,
    content: PublicSuccessorContentVerdict,
    release_root: Path,
    *,
    scope_root: Path | None = None,
) -> tuple[RetrievalScopeArtifactV3, ...]:
    """Relire les scopes V3 émis sur les onze subjects de A, sans les autoriser."""
    registry = _read(registry_path.parent, registry_path.name, expected_registry_sha256)
    if set(registry) != {
        "kind", "status", "activation_allowed", "content_anchor_sha256",
        "content_manifest_sha256", "policy_registry_sha256",
        "successor_authority_sha256", "scopes",
    } or (
        registry.get("kind") != "NEXUS_STUDENT_PUBLIC_SCOPE_REGISTRY_V1"
        or registry.get("status") != "SCOPES_ISSUED_NOT_PUBLICATION_AUTHORITY"
        or registry.get("activation_allowed") is not False
        or registry.get("content_anchor_sha256") != content.content_anchor_sha256
        or registry.get("content_manifest_sha256") != content.content_manifest_sha256
        or any(_SHA256.fullmatch(registry.get(name, "")) is None for name in (
            "policy_registry_sha256", "successor_authority_sha256",
        ))
    ):
        raise PublicSuccessorActivationError("scope registry policy or A binding differs")
    rows = registry.get("scopes")
    if not isinstance(rows, list) or len(rows) != len(content.subject_sha256_by_collection):
        raise PublicSuccessorActivationError("scope registry collection population differs")
    root = scope_root or registry_path.parent
    observed: dict[str, RetrievalScopeArtifactV3] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "collection", "scope_id", "resource", "sha256", "source_sha256",
            "artifact_version",
        }:
            raise PublicSuccessorActivationError("scope registry entry malformed")
        collection = row["collection"]
        if (
            collection not in content.subject_sha256_by_collection
            or collection in observed
            or row["source_sha256"] != content.subject_sha256_by_collection[collection]
            or row["artifact_version"] != "3"
            or not isinstance(row["resource"], str)
            or not row["resource"].startswith("scopes/")
            or not row["resource"].endswith(".json")
        ):
            raise PublicSuccessorActivationError("scope registry subject identity differs")
        raw = _read(root, row["resource"], row["sha256"], json_required=False)
        try:
            scope = RetrievalScopeArtifactV3.model_validate_json(raw)
        except ValueError as error:
            raise PublicSuccessorActivationError("scope V3 invalid") from error
        if scope.canonical_bytes() != raw or scope.sha256_digest() != row["sha256"]:
            raise PublicSuccessorActivationError("scope V3 canonical digest differs")
        policy = scope.target_policy
        evidence = scope.evidence_subject
        if (
            scope.scope_id != row["scope_id"]
            or scope.source_sha256 != row["source_sha256"]
            or evidence.collection != collection
            or policy.roles != ["student"]
            or evidence.visibility != "public"
            or [value.value for value in evidence.rights] != ["public_allowed"]
            or policy.tenant != evidence.tenant
            or policy.niveau != evidence.niveau
            or policy.voie != evidence.voie
            or policy.matiere != evidence.matiere
            or policy.statut_enseignement != evidence.statut_enseignement
            or evidence.candidat not in policy.candidates
            or not set(policy.audiences) <= set(evidence.audiences)
        ):
            raise PublicSuccessorActivationError("scope V3 student/public semantics differ")
        subject = _read(
            release_root / "profile_gate", f"subjects/{collection}.release.json",
            row["source_sha256"],
        )
        placements = subject.get("placements")
        if not isinstance(placements, list) or not placements or any(
            not isinstance(placement, dict) or any(
                placement.get(field) != _enum_value(getattr(evidence, field))
                for field in (
                    "collection", "tenant", "niveau", "voie", "matiere",
                    "statut_enseignement", "candidat", "visibility", "school_year",
                    "programme_version",
                )
            ) for placement in placements
        ):
            raise PublicSuccessorActivationError("scope V3 differs from A placements")
        profile_raw = _read(
            release_root / "profile_gate", f"profiles/{collection}.yml",
            content.profile_sha256_by_collection[collection],
            json_required=False,
        )
        profile = yaml.safe_load(profile_raw)
        configured_audiences = profile.get("scope", {}).get("audience") if isinstance(profile, dict) else None
        if not isinstance(configured_audiences, list) or not set(
            policy.audiences
        ) <= set(configured_audiences):
            raise PublicSuccessorActivationError("scope V3 audience outside A profile")
        observed[collection] = scope
    if set(observed) != set(content.subject_sha256_by_collection):
        raise PublicSuccessorActivationError("scope V3 population incomplete")
    return tuple(observed[name] for name in sorted(observed))


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def verify_content_currentness(
    release_root: Path, content: PublicSuccessorContentVerdict, now_utc: datetime,
) -> datetime:
    """La fraîcheur scellée ne peut jamais être prolongée par l'horloge locale."""
    if now_utc.tzinfo is None or now_utc.utcoffset() != UTC.utcoffset(now_utc):
        raise PublicSuccessorActivationError("currentness clock must be UTC")
    index = _read(release_root, "preparation-index.json", content.preparation_index_sha256)
    registry = _read(
        release_root / "profile_gate", "public_currentness_registry.json",
        content.currentness_registry_sha256,
    )
    expiry_raw = index.get("source_currentness_valid_until_utc")
    if not isinstance(expiry_raw, str) or registry.get("valid_until_utc") != expiry_raw:
        raise PublicSuccessorActivationError("currentness registry differs from A")
    try:
        expiry = datetime.fromisoformat(expiry_raw)
    except ValueError as error:
        raise PublicSuccessorActivationError("currentness expiry invalid") from error
    if expiry.utcoffset() != UTC.utcoffset(expiry) or now_utc >= expiry:
        raise PublicSuccessorActivationError("currentness expired")
    entries = registry.get("entries")
    if not isinstance(entries, list) or len(entries) != content.expected_counts["unique_artifacts"] or any(
        not isinstance(row, dict)
        or row.get("currentness_status") != "PASS"
        or row.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
        for row in entries
    ):
        raise PublicSuccessorActivationError("currentness or source revocation differs")
    return expiry


def verify_content_authority_bindings(
    release_root: Path,
    content: PublicSuccessorContentVerdict,
    authorities: dict[str, str],
) -> None:
    """Lier les treize preuves de préparation C aux digests déjà scellés dans A.

    Ce contrôle ne valide pas, à lui seul, les droits ou les revues externes.
    """
    index = _read(release_root, "preparation-index.json", content.preparation_index_sha256)
    manifest = _read(
        release_root / "profile_gate", "production-profile-gate.release.json",
        content.content_manifest_sha256,
    )
    prepared = manifest.get("authorities")
    if not isinstance(prepared, dict):
        raise PublicSuccessorActivationError("A prepared authorities absent")
    expected = {
        "source_candidate_release_manifest_sha256": index.get("source_candidate_manifest_sha256"),
        "source_preparation_release_manifest_sha256": content.content_manifest_sha256,
        "source_preparation_index_sha256": content.preparation_index_sha256,
        "candidate_inventory_sha256": content.candidate_inventory_sha256,
        "inclusion_attestation_sha256": index.get("inclusion_attestation_sha256"),
        "derivative_pii_evidence_sha256": index.get("pii_adjudication_report_sha256"),
        "derivative_currentness_evidence_sha256": index.get("source_currentness_attestation_sha256"),
        "public_profile_manifest_sha256": prepared.get("public_profile_registry_sha256"),
        "public_rights_registry_sha256": prepared.get("public_rights_registry_sha256"),
        "public_pii_registry_sha256": prepared.get("public_pii_registry_sha256"),
        "rights_authority_sha256": prepared.get("rights_authority_sha256"),
        "delegated_evidence_pack_sha256": prepared.get("delegated_evidence_pack_sha256"),
        "pr300_final_authority_receipt_sha256": prepared.get(
            "pr300_final_authority_receipt_sha256"
        ),
    }
    for field, digest in expected.items():
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None or authorities.get(field) != digest:
            raise PublicSuccessorActivationError(f"{field}: C differs from immutable A")


def verify_public_successor_activation(
    bundle_root: Path,
    *,
    expected_content_anchor_sha256: str,
    expected_authority_envelope_sha256: str,
    expected_release_id: str,
    expected_registry_sha256: str,
    expected_scope_authority_sha256: str,
    now_utc: datetime | None = None,
) -> PublicSuccessorActivationVerdict:
    """Refuser C tant que chaque autorité externe n'est pas vérifiée sémantiquement.

    Les digests viennent de la readiness signée, et l'absence de readiness
    signée doit être refusée par l'appelant avant cet appel. Le bundle seul
    ne peut ni signer ses propres digests, ni se déclarer activable.
    """
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise PublicSuccessorActivationError("activation clock must be UTC")
    root = bundle_root.resolve()
    try:
        content = verify_content_anchor(
            root / "content-anchor.json", expected_content_anchor_sha256,
            root / "release",
        )
    except (OSError, KeyError, TypeError) as error:
        raise PublicSuccessorActivationError("content anchor or release absent") from error
    if (
        content.release_id != expected_release_id
        or content.release_registry_sha256 != expected_registry_sha256
    ):
        raise PublicSuccessorActivationError("signed release or registry binding differs")
    verify_content_currentness(root / "release", content, now)
    try:
        envelope = _read(root, "authority-envelope.json", expected_authority_envelope_sha256)
    except PublicSuccessorActivationError as error:
        raise PublicSuccessorActivationError("authority envelope absent or divergent") from error
    if set(envelope) != {
        "kind", "status", "activation_allowed", "semantic_verification_complete",
        "content_anchor_sha256", "content_release_id", "content_manifest_sha256",
        "expected_counts", "authorities",
    } or (
        envelope.get("kind") != "NEXUS_PUBLIC_SUCCESSOR_AUTHORITY_ENVELOPE_V1"
        or envelope.get("status") != "EVIDENCE_BYTES_ONLY_NOT_ACTIVABLE"
        or envelope.get("activation_allowed") is not False
        or envelope.get("semantic_verification_complete") is not False
        or envelope.get("content_anchor_sha256") != expected_content_anchor_sha256
        or envelope.get("content_release_id") != content.release_id
        or envelope.get("content_manifest_sha256") != content.content_manifest_sha256
        or envelope.get("expected_counts") != content.expected_counts
    ):
        raise PublicSuccessorActivationError("authority envelope does not bind A")
    authorities = envelope["authorities"]
    if not isinstance(authorities, dict) or set(authorities) != (
        _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS
    ):
        raise PublicSuccessorActivationError("all 21 authority fields are required")
    for field, digest in authorities.items():
        _read(root, f"authorities/{field}.bin", digest, json_required=False)
    if (
        authorities["source_preparation_release_manifest_sha256"]
            != content.content_manifest_sha256
        or authorities["candidate_inventory_sha256"]
            != _read(root, "content-anchor.json", expected_content_anchor_sha256)[
                "candidate_inventory_sha256"
            ]
        or authorities["public_scope_authority_sha256"]
            != expected_scope_authority_sha256
    ):
        raise PublicSuccessorActivationError("authority bytes differ from signed A or scopes")
    verify_content_authority_bindings(root / "release", content, authorities)
    verify_public_scope_registry(
        root / "authorities/public_scope_authority_sha256.bin",
        authorities["public_scope_authority_sha256"], content,
        root / "release", scope_root=root,
    )
    # Chaque pièce doit être comprise et confrontée à A, à la cible et à
    # l'heure, notamment LOT42 et les révocations. Ces vérificateurs sont
    # ajoutés avant toute levée du refus historique public_successor.
    raise PublicSuccessorActivationError(
        "public successor authority semantics incomplete: activation refused"
    )
