"""Lecture portable de A : identité du corpus public préparatoire, sans activation.

Le paquet A reste `candidate/NOT_PROMOTABLE`. L'autorité d'ingestion et celle
de publication sont des preuves extérieures distinctes, liées à son digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    ReleaseBatchPublicationReviewArtifact,
    ReleaseBatchReviewMismatch,
    parse_release_batch_publication_review_artifact,
    require_release_batch_review_matches_release,
)
from nexus_contracts.authorization_loader import load_authorization_set
from nexus_contracts.authorization_revocations import (
    AuthorizationRevocationsError,
    parse_revoked_authorization_ids,
)
from nexus_contracts.authorization_set import (
    AuthorizationSetError,
    AuthorizationSetV2,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV2,
    VerifiedAuthorizationSetV1,
    verify_authorization_binding_set_v2,
)
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.production_readiness import (
    ProductionReadinessManifestV2,
    parse_production_readiness_trust_anchor,
    verify_production_readiness_manifest_v2,
)
from nexus_contracts.staging_readiness import (
    StagingReadinessManifestV1,
    parse_staging_readiness_trust_anchor,
    verify_staging_readiness_manifest,
)
from nexus_contracts.scope import RetrievalScopeArtifactV3

from nexus_release_chain.release_readiness import (
    _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS,
    _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS,
    ReleaseReadinessError,
    load_release_expectation,
    load_release_registry_file,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ANCHOR_KIND = "NEXUS_PUBLIC_SUCCESSOR_CONTENT_ANCHOR_V1"
_TEXT_MIME = "text/plain; charset=utf-8"
_A2_ENVELOPE_KIND = "NEXUS_PUBLIC_SUCCESSOR_AUTHORITY_ENVELOPE_A2_V1"


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
    # Vérifiés par C depuis AuthorizationSetV2, bindings signés et preuves
    # scellées ; jamais reconstruits à partir des lignes de la DB servie.
    authorization_review_evidence_by_id: tuple[tuple[str, str, str, str], ...] = ()
    transfer_manifest_sha256: str | None = None
    publication_batch_review_id: str | None = None
    publication_batch_review_digest: str | None = None
    # Base/head/blob/review ID/challenge/reviewer vérifiés par la review LOT42.
    publication_batch_review_binding: tuple[str, str, str, int, str, str] | None = None


@dataclass(frozen=True)
class PublicSuccessorLiveVerificationRequest:
    """Identités relues par C que le signer doit contrôler sur GitHub/DB/cible."""

    bundle_root: Path
    content: PublicSuccessorContentVerdict
    authority_envelope_sha256: str
    authorities: Mapping[str, str]
    scope_sha256_by_id: Mapping[str, str]
    authorization_set: AuthorizationSetV2
    publication_batch_review: ReleaseBatchPublicationReviewArtifact
    target_pin_sha256: str
    a2_expires_at_utc: datetime
    pin_expires_at_utc: datetime
    now_utc: datetime


@dataclass(frozen=True)
class VerifiedPublicSuccessorLiveEvidence:
    """Résultats d'un fournisseur *de confiance* qui a rejoué le monde live.

    Les champs ne sont jamais lus depuis l'enveloppe C. Le signataire doit
    fournir un callable qui exécute les vérificateurs canoniques GitHub, DB,
    révocations, transfert et LOT42. Sans ce callable, C refuse toujours.
    """

    authority_sha256_by_field: Mapping[str, str]
    content_anchor_sha256: str
    authority_envelope_sha256: str
    target_pin_sha256: str
    release_id: str
    content_manifest_sha256: str
    counts: Mapping[str, int]
    scope_sha256_by_id: Mapping[str, str]
    verified_authorization_set: VerifiedAuthorizationSetV1
    authorization_review_evidence_by_id: tuple[tuple[str, str, str, str], ...]
    publication_batch_review_id: str
    publication_batch_review_digest: str
    publication_batch_review_binding: tuple[str, str, str, int, str, str]
    verified_at_utc: datetime
    revocations_checked_at_utc: datetime
    source_pulse_replayed_at_utc: datetime
    active_authorization_ids: tuple[str, ...]
    lot42_attestation_count: int
    revoked_authorization_ids: tuple[str, ...]
    revoked_review_ids: tuple[int, ...]
    target_pin_expires_at_utc: datetime
    expires_at_utc: datetime


PublicSuccessorLiveVerifier = Callable[
    [PublicSuccessorLiveVerificationRequest], VerifiedPublicSuccessorLiveEvidence,
]


def _post_replay_utc_now(started_at_utc: datetime) -> datetime:
    """Évaluer les constats live à la fin du rejeu, jamais avant son I/O."""
    return max(started_at_utc, datetime.now(UTC))


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


def verify_reviewed_public_scope_policy(
    registry_path: Path,
    expected_registry_sha256: str,
    content: PublicSuccessorContentVerdict,
    scopes: tuple[RetrievalScopeArtifactV3, ...],
    *,
    policy_raw: bytes,
    names_raw: bytes,
    receipt_raw: bytes,
    expected_receipt_sha256: str,
) -> dict[str, str]:
    """Comparer B à la politique et au nommage de sa revue exacte.

    Le reçu est revérifié en ligne au scellement ; ce lecteur portable contrôle
    ses liaisons et les octets de chaque V3 sans revendiquer un accès GitHub.
    """
    if (not isinstance(expected_receipt_sha256, str)
            or _SHA256.fullmatch(expected_receipt_sha256) is None
            or hashlib.sha256(receipt_raw).hexdigest() != expected_receipt_sha256):
        raise PublicSuccessorActivationError("scope review receipt digest differs")
    try:
        receipt = json.loads(receipt_raw)
        canonical = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        policy = yaml.safe_load(policy_raw)
        names = yaml.safe_load(names_raw)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as error:
        raise PublicSuccessorActivationError("reviewed scope authority invalid") from error
    if (not isinstance(receipt, dict) or receipt_raw != canonical
            or not isinstance(policy, dict) or not isinstance(names, dict)):
        raise PublicSuccessorActivationError("reviewed scope authority malformed")
    if (
        (receipt.get("kind"), receipt.get("pull_request")) not in {
            ("PR294_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1", 294),
            ("PR330_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1", 330),
        }
        or receipt.get("status") != "REVIEWED_SCOPES_NOT_PUBLICATION_AUTHORITY"
        or receipt.get("activation_allowed") is not False
        or receipt.get("repository") != "cyranoaladin/RAG"
        or receipt.get("reviewer") != "abenrhouma"
        or any(not isinstance(receipt.get(field), str)
               or re.fullmatch(r"[0-9a-f]{40}", receipt[field]) is None
               for field in ("base_sha", "head_sha", "head_tree_sha", "merge_commit_sha"))
        or not isinstance(receipt.get("review_id"), int)
        or receipt["review_id"] <= 0
        or receipt.get("trusted_status_context") != "trusted-human-review/head-pinned"
        or not isinstance(receipt.get("workflow_run_id"), int)
        or receipt["workflow_run_id"] <= 0
        or not isinstance(receipt.get("challenge"), str)
        or re.fullmatch(r"NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}", receipt["challenge"]) is None
        or receipt.get("content_anchor_sha256") != content.content_anchor_sha256
        or receipt.get("content_manifest_sha256") != content.content_manifest_sha256
        or receipt.get("public_scope_authority_sha256") != expected_registry_sha256
        or receipt.get("policy_registry_sha256") != hashlib.sha256(policy_raw).hexdigest()
        or receipt.get("successor_authority_sha256") != hashlib.sha256(names_raw).hexdigest()
        or policy.get("registry_kind") != "NEXUS_RETRIEVAL_SCOPE_POLICY_REGISTRY_V1"
        or policy.get("release_id") != content.release_id
        or policy.get("release_manifest_sha256") != content.content_manifest_sha256
        or names.get("authority_id") != "PRODUCTION_PROFILE_SCOPE_SUCCESSORS_V1"
        or names.get("release_id") != content.release_id
    ):
        raise PublicSuccessorActivationError("reviewed scope authority differs from A")
    registry = _read(registry_path.parent, registry_path.name, expected_registry_sha256)
    if (registry.get("policy_registry_sha256") != receipt["policy_registry_sha256"]
            or registry.get("successor_authority_sha256") != receipt["successor_authority_sha256"]):
        raise PublicSuccessorActivationError("scope registry differs from reviewed policy")
    registry_rows = registry.get("scopes")
    if not isinstance(registry_rows, list) or any(
        not isinstance(row, dict)
        or row.get("resource") != f"scopes/{row.get('scope_id')}.json"
        for row in registry_rows
    ):
        raise PublicSuccessorActivationError("scope registry resource differs from reviewed naming")
    rows = policy.get("collections")
    bindings = names.get("bindings")
    if not isinstance(rows, list) or not isinstance(bindings, list):
        raise PublicSuccessorActivationError("reviewed policy population absent")
    policies = {row.get("collection"): row for row in rows if isinstance(row, dict)}
    named = {row.get("collection"): row.get("scope_id") for row in bindings
             if isinstance(row, dict)}
    scope_by_id = {scope.scope_id: scope for scope in scopes}
    expected_collections = set(content.subject_sha256_by_collection)
    if (len(rows) != len(policies) or len(bindings) != len(named)
            or set(policies) != expected_collections or set(named) != expected_collections
            or len(scope_by_id) != len(scopes) or len(scopes) != len(expected_collections)):
        raise PublicSuccessorActivationError("reviewed policy population differs from A")
    observed: dict[str, str] = {}
    for collection in sorted(expected_collections):
        entry = policies[collection]
        scope_id = named[collection]
        if not isinstance(scope_id, str) or not re.fullmatch(
            r"student_public_[a-z0-9_]+_v1", scope_id
        ) or scope_id not in scope_by_id:
            raise PublicSuccessorActivationError("reviewed scope naming differs")
        if (
            entry.get("decision_status") != "GOVERNED_BY_HUMAN_DECISION"
            or entry.get("authority_source") != "NEXUS_HUMAN_DECISION_ADR_0064"
            or entry.get("policy_source_scope_id") is not None
            or entry.get("subject_manifest_sha256")
                != content.subject_sha256_by_collection[collection]
            or entry.get("audiences") != ["libre", "aefe"]
            or entry.get("rights") != ["public_allowed"]
            or entry.get("policy_visibility") != "public"
            or entry.get("evidence_visibility") != "public"
            or entry.get("target_audience") != "libre"
            or entry.get("target_candidates") != ["libre"]
        ):
            raise PublicSuccessorActivationError("reviewed policy student decision differs")
        try:
            expected = RetrievalScopeArtifactV3.model_validate({
                "artifact_version": "3", "scope_id": scope_id,
                "status": "eligible_for_promotion",
                "source_sha256": content.subject_sha256_by_collection[collection],
                "target_policy": {
                    key: entry[key] for key in (
                        "tenant", "niveau", "voie", "matiere", "statut_enseignement",
                    )
                } | {
                    "audiences": [entry["target_audience"]],
                    "candidates": entry["target_candidates"], "roles": ["student"],
                },
                "evidence_subject": {
                    key: entry[key] for key in (
                        "collection", "tenant", "niveau", "voie", "matiere",
                        "statut_enseignement", "candidat", "audiences", "rights",
                        "programme_version",
                    )
                } | {
                    "visibility": entry["evidence_visibility"],
                    "school_year": policy["school_year"],
                },
            })
        except (KeyError, TypeError, ValueError) as error:
            raise PublicSuccessorActivationError("reviewed policy V3 invalid") from error
        if expected.canonical_bytes() != scope_by_id[scope_id].canonical_bytes():
            raise PublicSuccessorActivationError("scope V3 differs from reviewed policy")
        observed[scope_id] = expected.sha256_digest()
    if receipt.get("scope_sha256_by_id") != observed:
        raise PublicSuccessorActivationError("reviewed scope digest population differs")
    return observed


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
    artifact_registry = _read(
        release_root / "profile_gate", "artifacts.release.json",
        content.artifact_registry_sha256,
    )
    artifacts = artifact_registry.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != content.expected_counts["unique_artifacts"]:
        raise PublicSuccessorActivationError("currentness A artifact population invalid")
    artifact_pairs = {
        row.get("content_sha256"): row.get("source_pdf_sha256")
        for row in artifacts if isinstance(row, dict)
    }
    if len(artifact_pairs) != len(artifacts) or any(
        not isinstance(sha, str) or _SHA256.fullmatch(sha) is None
        or not isinstance(pdf, str) or _SHA256.fullmatch(pdf) is None
        for sha, pdf in artifact_pairs.items()
    ):
        raise PublicSuccessorActivationError("currentness A artifact identity invalid")
    if not isinstance(entries, list) or len(entries) != content.expected_counts["unique_artifacts"] or any(
        not isinstance(row, dict)
        or row.get("currentness_status") != "PASS"
        or row.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
        for row in entries
    ):
        raise PublicSuccessorActivationError("currentness or source revocation differs")
    entry_pairs = {row.get("content_sha256"): row.get("source_pdf_sha256") for row in entries}
    if (
        registry.get("kind") != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CURRENTNESS_REGISTRY_V1"
        or registry.get("status") != "CANDIDATE_NOT_AUTHORIZED"
        or registry.get("release_id") != content.release_id
        or len(entry_pairs) != len(entries)
        or entry_pairs != artifact_pairs
    ):
        raise PublicSuccessorActivationError("currentness identity population differs from A")
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


def derive_public_release_scope_placement(
    release_root: Path,
    content: PublicSuccessorContentVerdict,
) -> ReleaseScopePlacementV2:
    """Dériver les 377 liaisons LOT41A des subjects et profils immuables de A.

    Le scope vient du profil scellé, audience comprise. Il n'est jamais
    reconstruit à partir de la simple liste d'IDs d'une autorisation.
    """
    gate = release_root / "profile_gate"
    registry = _read(gate, "artifacts.release.json", content.artifact_registry_sha256)
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, list):
        raise PublicSuccessorActivationError("LOT41A A artifact registry malformed")
    artifact_ids = {row.get("artifact_id") for row in artifacts if isinstance(row, dict)}
    if len(artifact_ids) != content.expected_counts["unique_artifacts"]:
        raise PublicSuccessorActivationError("LOT41A A artifact population differs")
    entries: list[ReleaseScopePlacementEntryV1] = []
    profile_digests: set[str] = set()
    scope_digests: set[str] = set()
    for collection, subject_sha in sorted(content.subject_sha256_by_collection.items()):
        subject = _read(gate, f"subjects/{collection}.release.json", subject_sha)
        profile = subject.get("profile")
        if not isinstance(profile, dict) or set(profile) != {
            "fingerprint", "manifest_digest", "version",
        }:
            raise PublicSuccessorActivationError("LOT41A A subject profile malformed")
        profile_raw = _read(
            gate, f"profiles/{collection}.yml",
            content.profile_sha256_by_collection[collection], json_required=False,
        )
        try:
            profile_document = yaml.safe_load(profile_raw)
            scope = ResourceScope.model_validate(profile_document["scope"])
        except (KeyError, TypeError, ValueError, yaml.YAMLError) as error:
            raise PublicSuccessorActivationError("LOT41A A profile scope invalid") from error
        if (
            scope.collection != collection
            or profile_document.get("profile_version") != profile["version"]
        ):
            raise PublicSuccessorActivationError("LOT41A A profile identity differs")
        profile_digests.add(profile["manifest_digest"])
        scope_digests.add(scope.model_dump_json())
        placements = subject.get("placements")
        if not isinstance(placements, list) or not placements:
            raise PublicSuccessorActivationError("LOT41A A subject placements absent")
        for placement in placements:
            if not isinstance(placement, dict) or placement.get("artifact_id") not in artifact_ids:
                raise PublicSuccessorActivationError("LOT41A A placement artifact unknown")
            if any(
                placement.get(field) != _enum_value(getattr(scope, field))
                for field in (
                    "tenant", "collection", "niveau", "voie", "matiere",
                    "candidat", "visibility", "school_year", "programme_version",
                )
            ):
                raise PublicSuccessorActivationError("LOT41A A placement scope differs")
            try:
                entries.append(ReleaseScopePlacementEntryV1.model_validate({
                    "content_sha256": placement["artifact_id"],
                    "profile_id": collection,
                    "profile_version": profile["version"],
                    "profile_fingerprint": profile["fingerprint"],
                    "scope": scope,
                }))
            except ValueError as error:
                raise PublicSuccessorActivationError("LOT41A A placement invalid") from error
    if (
        len(profile_digests) != 1
        or len(scope_digests) != len(content.subject_sha256_by_collection)
        or len(entries) != content.expected_counts["placements"]
        or {entry.content_sha256 for entry in entries} != artifact_ids
    ):
        raise PublicSuccessorActivationError("LOT41A A binding population differs")
    try:
        return ReleaseScopePlacementV2.build(
            placements=entries, profile_manifest_digest=profile_digests.pop(),
        )
    except AuthorizationSetError as error:
        raise PublicSuccessorActivationError("LOT41A A binding projection invalid") from error


def verify_public_lot41a_authorization_set(
    raw: bytes,
    release_root: Path,
    content: PublicSuccessorContentVerdict,
    now_utc: datetime,
    *, temporal_authority_raw: bytes | None = None,
) -> AuthorizationSetV2:
    """Vérifier forme, fenêtre et couverture exacte ; signatures séparées.

    Ce résultat n'atteste pas les revues signées LOT41A. Le signataire doit
    appeler le vérificateur complet du contrat avec trust anchor, fichiers de
    revue et registre de révocations avant toute autorité PUBLICATION.
    """
    projection = derive_public_release_scope_placement(release_root, content)
    try:
        authorization_set = load_authorization_set(raw).require_v2(
            because="public successor LOT41A",
        )
        verify_authorization_binding_set_v2(
            authorization_set, release_scope_placement=projection,
        )
    except (AuthorizationSetError, ValueError) as error:
        raise PublicSuccessorActivationError("LOT41A binding set invalid") from error
    if (
        authorization_set.corpus_manifest_sha256 != content.content_manifest_sha256
        or authorization_set.authorization_count != len(content.subject_sha256_by_collection)
        or authorization_set.unique_content_count != content.expected_counts["unique_artifacts"]
        or authorization_set.authorization_binding_count != content.expected_counts["placements"]
        or not (authorization_set.authorizations_effective_valid_from <= now_utc
                < authorization_set.authorizations_effective_valid_until)
    ):
        raise PublicSuccessorActivationError("LOT41A A identity, counts or validity differ")
    if temporal_authority_raw is not None:
        from .public_successor_temporal import (
            PublicSuccessorTemporalError,
            verify_temporal_authority_preissuance,
        )
        try:
            verify_temporal_authority_preissuance(
                content, temporal_authority_raw, now_utc=now_utc,
            )
            temporal = json.loads(temporal_authority_raw)
            valid_from = datetime.fromisoformat(temporal["valid_from_utc"])
            valid_until = datetime.fromisoformat(temporal["valid_until_utc"])
        except (PublicSuccessorTemporalError, KeyError, ValueError) as error:
            raise PublicSuccessorActivationError("A2 LOT41A temporal authority invalid") from error
        if any(
            member.authorization_id != (
                "lot41a-student-public-"
                + str(member.scope.collection).removeprefix("rag_nexus_").replace("_", "-")
                + "-v2"
            )
            or member.valid_from != valid_from
            or member.valid_until != valid_until
            for member in authorization_set.members
        ):
            raise PublicSuccessorActivationError("A2 LOT41A IDs or dates differ")
    return authorization_set


def verify_public_authorization_revocations(
    raw: bytes, *, authorization_ids: tuple[str, ...],
) -> frozenset[str]:
    """Relire le registre partagé existant et refuser une révocation LOT41A.

    La présence du registre ne prouve pas sa fraîcheur future ni l'état de
    `revoked_review_evidence` : le signataire et le runtime relisent la DB.
    """
    try:
        revoked = parse_revoked_authorization_ids(raw, origin="public successor C")
    except AuthorizationRevocationsError as error:
        raise PublicSuccessorActivationError(f"revocation registry invalid: {error}") from error
    if revoked.intersection(authorization_ids):
        raise PublicSuccessorActivationError("LOT41A authorization revoked")
    return revoked


def _compact_document(raw: bytes, label: str) -> dict[str, Any]:
    """Parser les octets canoniques compacts du protocole de transfert."""
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PublicSuccessorActivationError(f"{label}: duplicate JSON key")
            result[key] = value
        return result

    try:
        document = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicSuccessorActivationError(f"{label}: invalid JSON") from error
    canonical = (json.dumps(document, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")) + "\n").encode()
    if not isinstance(document, dict) or canonical != raw:
        raise PublicSuccessorActivationError(f"{label}: noncanonical JSON")
    return document


def derive_worker_transfer_manifest_sha256(plan_raw: bytes, receipt_v1_raw: bytes) -> str:
    """Rebuild Worker A's observed manifest identity from the verified V1 pair.

    This is distinct from the plan SHA carried by A2. Callers must first replay
    the full A/V1/V2/pin checks; this reconstruction also rejects a substituted
    or incomplete pair before its SHA is compared with the live DB.
    """
    plan = _compact_document(plan_raw, "worker transfer plan")
    receipt = _compact_document(receipt_v1_raw, "worker transfer V1 receipt")
    plan_sha = hashlib.sha256(plan_raw).hexdigest()
    files = plan.get("files")
    observed_files = receipt.get("files")
    if (
        plan.get("kind") != "NEXUS_STUDENT_PUBLIC_TEXT_TRANSFER_MANIFEST_V1"
        or receipt.get("kind") != "NEXUS_STUDENT_PUBLIC_TEXT_OBSERVED_TRANSFER_V1"
        or receipt.get("transfer_manifest_sha256") != plan_sha
        or receipt.get("release_id") != plan.get("release_id")
        or receipt.get("file_count") != plan.get("file_count")
        or receipt.get("derivative_receipt_count") != plan.get("derivative_receipt_count")
        or not isinstance(files, list) or not isinstance(observed_files, list)
        or len(files) != plan.get("file_count")
        or len(observed_files) != len(files)
        or any(not isinstance(row, dict) for row in files + observed_files)
    ):
        raise PublicSuccessorActivationError("worker transfer plan/V1 pair differs")
    expected = {row.get("file"): row.get("sha256_expected") for row in files}
    actual = {row.get("file"): row.get("sha256_observed") for row in observed_files}
    if (
        len(expected) != len(files) or len(actual) != len(observed_files)
        or expected != actual
        or any(not isinstance(name, str) or not isinstance(sha, str)
               or _SHA256.fullmatch(sha) is None for name, sha in expected.items())
    ):
        raise PublicSuccessorActivationError("worker transfer observed files differ")
    worker = {
        "manifest_kind": "NEXUS-STAGING-ARTIFACT-TRANSFER-V1",
        "release_id": plan["release_id"],
        "transfer_method": "octets textuels observes et re-haches sur la destination",
        "destination_target_identity": receipt.get("target_identity"),
        "destination_identity_status": "CLAIMED_UNQUALIFIED",
        "observed_host": receipt.get("observed_host"),
        "destination_realpath": receipt.get("destination_realpath"),
        "source_plan_sha256": plan_sha,
        "observed_transfer_receipt_sha256": hashlib.sha256(receipt_v1_raw).hexdigest(),
        "file_count": plan["file_count"],
        "derivative_receipt_count": plan["derivative_receipt_count"],
        "digest_missing": 0,
        "digest_mismatches": 0,
        "files": [
            {"file": row["file"], "sha256_expected": row["sha256_expected"],
             "sha256_observed": actual[row["file"]]}
            for row in files
        ],
    }
    raw = (json.dumps(worker, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


def _transfer_utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PublicSuccessorActivationError(f"transfer {label}: UTC absent")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise PublicSuccessorActivationError(f"transfer {label}: UTC invalid") from error
    if instant.tzinfo != UTC:
        raise PublicSuccessorActivationError(f"transfer {label}: UTC invalid")
    return instant


def verify_public_transfer_placement_population(
    inventory: dict[str, Any],
    release_root: Path,
    content: PublicSuccessorContentVerdict,
) -> None:
    """Confronter chaque liaison source de l'inventaire aux onze subjects A."""
    collections = inventory.get("collections")
    if not isinstance(collections, list) or len(collections) != len(content.subject_sha256_by_collection):
        raise PublicSuccessorActivationError("transfer placement collections differ from A")
    observed_collections: set[str] = set()
    total_pairs = 0
    for collection_row in collections:
        if not isinstance(collection_row, dict):
            raise PublicSuccessorActivationError("transfer placement collection malformed")
        collection = collection_row.get("collection")
        if collection not in content.subject_sha256_by_collection or collection in observed_collections:
            raise PublicSuccessorActivationError("transfer placement collection unknown or duplicate")
        observed_collections.add(collection)
        candidates = collection_row.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise PublicSuccessorActivationError("transfer placement candidates absent")
        candidate_pairs: list[tuple[str, str]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise PublicSuccessorActivationError("transfer placement candidate malformed")
            sha = candidate.get("content_sha256")
            placements = candidate.get("placements")
            if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None or not isinstance(placements, list):
                raise PublicSuccessorActivationError("transfer placement content identity invalid")
            for placement in placements:
                source_id = placement.get("source_placement_id") if isinstance(placement, dict) else None
                if not isinstance(source_id, str) or _SHA256.fullmatch(source_id) is None:
                    raise PublicSuccessorActivationError("transfer placement source identity invalid")
                candidate_pairs.append((sha, source_id))
        subject = _read(
            release_root / "profile_gate", f"subjects/{collection}.release.json",
            content.subject_sha256_by_collection[collection],
        )
        subject_rows = subject.get("placements")
        if not isinstance(subject_rows, list):
            raise PublicSuccessorActivationError("transfer placement subject absent")
        subject_pairs = [
            (row.get("artifact_id"), row.get("source_placement_id"))
            for row in subject_rows if isinstance(row, dict)
        ]
        if (
            len(candidate_pairs) != len(subject_pairs)
            or len(set(candidate_pairs)) != len(candidate_pairs)
            or len(subject_pairs) != len(subject_rows)
            or len(set(subject_pairs)) != len(subject_pairs)
            or set(candidate_pairs) != set(subject_pairs)
        ):
            raise PublicSuccessorActivationError("transfer placement pairs differ from A")
        total_pairs += len(candidate_pairs)
    if total_pairs != content.expected_counts["placements"]:
        raise PublicSuccessorActivationError("transfer placement count differs from A")


def verify_public_transfer_offline(
    plan_raw: bytes,
    receipt_v1_raw: bytes,
    target_pin_raw: bytes,
    attestation_v2_raw: bytes,
    release_root: Path,
    content: PublicSuccessorContentVerdict,
    *,
    expected_target_pin_sha256: str,
    now_utc: datetime,
) -> str:
    """Relier V2, V1, pin et population exacte de A sans prétendre sonder la cible.

    L'appelant de scellement doit *en plus* prouver le pin par une source
    gouvernée indépendante et rejouer l'hôte, la DB et les 253 fichiers live.
    """
    if now_utc.tzinfo != UTC or _SHA256.fullmatch(expected_target_pin_sha256) is None:
        raise PublicSuccessorActivationError("transfer clock or independent target pin absent")
    plan = _compact_document(plan_raw, "transfer plan")
    receipt = _compact_document(receipt_v1_raw, "transfer V1 receipt")
    pin = _compact_document(target_pin_raw, "transfer target pin")
    attestation = _compact_document(attestation_v2_raw, "transfer V2 attestation")
    plan_sha = hashlib.sha256(plan_raw).hexdigest()
    receipt_sha = hashlib.sha256(receipt_v1_raw).hexdigest()
    if hashlib.sha256(target_pin_raw).hexdigest() != expected_target_pin_sha256:
        raise PublicSuccessorActivationError("transfer target pin digest differs")
    inventory = _read(
        release_root / "profile_gate", "candidate_inventory.json",
        content.candidate_inventory_sha256,
    )
    verify_public_transfer_placement_population(inventory, release_root, content)
    allowed_candidates: dict[str, str] = {}
    collections = inventory.get("collections")
    if not isinstance(collections, list) or len(collections) != content.expected_counts["subjects"]:
        raise PublicSuccessorActivationError("transfer A collection population differs")
    placements = 0
    for collection in collections:
        if not isinstance(collection, dict) or collection.get("collection") not in content.subject_sha256_by_collection:
            raise PublicSuccessorActivationError("transfer A collection unknown")
        candidates = collection.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise PublicSuccessorActivationError("transfer A candidates absent")
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise PublicSuccessorActivationError("transfer A candidate malformed")
            sha = candidate.get("content_sha256")
            receipt_digest = candidate.get("derivative_receipt_sha256")
            rows = candidate.get("placements")
            if (
                not isinstance(sha, str) or _SHA256.fullmatch(sha) is None
                or not isinstance(receipt_digest, str) or _SHA256.fullmatch(receipt_digest) is None
                or candidate.get("physical_path") != f"{sha}.txt"
                or candidate.get("media_type") != _TEXT_MIME
                or not isinstance(rows, list) or not rows
                or (sha in allowed_candidates and allowed_candidates[sha] != receipt_digest)
            ):
                raise PublicSuccessorActivationError("transfer A candidate identity differs")
            allowed_candidates[sha] = receipt_digest
            placements += len(rows)
    if (
        len(allowed_candidates) != content.expected_counts["unique_artifacts"]
        or placements != content.expected_counts["placements"]
    ):
        raise PublicSuccessorActivationError("transfer A counts differ")
    expected_files = {(f"{sha}.txt", sha, _TEXT_MIME) for sha in allowed_candidates}
    expected_receipts = {
        (f"derivative_receipts/{sha}.json", sha) for sha in allowed_candidates.values()
    }
    files = plan.get("files")
    receipts = plan.get("derivative_receipts")
    if (
        set(plan) != {
            "kind", "status", "release_id", "inventory_sha256", "allowlist_sha256",
            "file_count", "derivative_receipt_count", "placement_count", "files",
            "derivative_receipts",
        }
        or plan["kind"] != "NEXUS_STUDENT_PUBLIC_TEXT_TRANSFER_MANIFEST_V1"
        or plan["status"] != "PLANNED_NOT_TRANSFERRED"
        or plan["release_id"] != content.release_id
        or plan["inventory_sha256"] != content.candidate_inventory_sha256
        or plan["placement_count"] != placements
        or plan["file_count"] != len(expected_files)
        or plan["derivative_receipt_count"] != len(expected_receipts)
        or not isinstance(files, list) or not isinstance(receipts, list)
        or len(files) != len(expected_files) or len(receipts) != len(expected_receipts)
        or any(not isinstance(row, dict) for row in files + receipts)
        or any(set(row) != {"file", "sha256_expected", "media_type"} for row in files)
        or any(set(row) != {"file", "sha256_expected"} for row in receipts)
        or [row["sha256_expected"] for row in files]
            != sorted({sha for _, sha, _ in expected_files})
        or [row["sha256_expected"] for row in receipts]
            != sorted({sha for _, sha in expected_receipts})
        or {(row.get("file"), row.get("sha256_expected"), row.get("media_type"))
            for row in files} != expected_files
        or {(row.get("file"), row.get("sha256_expected"))
            for row in receipts} != expected_receipts
    ):
        raise PublicSuccessorActivationError("transfer plan differs from exact A population")
    allowed = _read(
        release_root / "profile_gate", "private_transfer_allowlist.json",
        plan["allowlist_sha256"],
    )
    rows = allowed.get("expected_files")
    if (
        allowed.get("kind") != "NEXUS_STUDENT_PUBLIC_PRIVATE_TRANSFER_ALLOWLIST_V1"
        or allowed.get("release_id") != content.release_id
        or allowed.get("candidate_inventory_sha256") != content.candidate_inventory_sha256
        or allowed.get("transfer_status") != "NOT_TRANSFERRED"
        or not isinstance(rows, list) or allowed.get("allowed_file_count") != len(rows)
        or len(rows) != len(expected_files)
        or any(not isinstance(row, dict) for row in rows)
        or any(set(row) != {"file", "sha256_expected", "media_type", "source_private_relpath"}
               for row in rows)
        or {(row.get("file"), row.get("sha256_expected"), row.get("media_type"))
            for row in rows} != expected_files
        or any(row.get("source_private_relpath") != f"candidates/{row.get('file')}"
               for row in rows)
    ):
        raise PublicSuccessorActivationError("transfer allowlist differs from A")
    if (
        set(receipt) != {
            "kind", "status", "release_id", "transfer_manifest_sha256",
            "target_identity", "target_identity_status", "observed_host",
            "destination_realpath", "observed_at_utc", "file_count",
            "derivative_receipt_count", "total_bytes", "files", "derivative_receipts",
        }
        or receipt.get("kind") != "NEXUS_STUDENT_PUBLIC_TEXT_OBSERVED_TRANSFER_V1"
        or receipt.get("status") != "OBSERVED_NOT_PUBLICATION_AUTHORITY"
        or receipt.get("target_identity_status") != "CLAIMED_UNQUALIFIED"
        or receipt.get("release_id") != content.release_id
        or receipt.get("transfer_manifest_sha256") != plan_sha
        or receipt.get("file_count") != len(expected_files)
        or receipt.get("derivative_receipt_count") != len(expected_receipts)
        or not isinstance(receipt.get("files"), list)
        or not isinstance(receipt.get("derivative_receipts"), list)
        or len(receipt["files"]) != len(expected_files)
        or len(receipt["derivative_receipts"]) != len(expected_receipts)
        or any(not isinstance(row, dict) for row in receipt["files"] + receipt["derivative_receipts"])
        or any(set(row) != {"file", "sha256_observed", "size_bytes"}
               for row in receipt["files"] + receipt["derivative_receipts"])
        or any(type(row["size_bytes"]) is not int or row["size_bytes"] < 0
               for row in receipt["files"] + receipt["derivative_receipts"])
        or receipt.get("total_bytes") != sum(row["size_bytes"] for row in
                                             receipt["files"] + receipt["derivative_receipts"])
        or {(row.get("file"), row.get("sha256_observed")) for row in receipt["files"]}
            != {(file, sha) for file, sha, _ in expected_files}
        or {(row.get("file"), row.get("sha256_observed"))
            for row in receipt["derivative_receipts"]} != expected_receipts
    ):
        raise PublicSuccessorActivationError("transfer V1 receipt differs from plan")
    if (
        set(pin) != {
            "kind", "content_anchor_sha256", "release_id", "target_identity",
            "hostname", "host_machine_id_sha256", "postgres_system_identifier",
            "database_name", "destination_realpath", "destination_device",
            "destination_inode", "pinned_at_utc", "expires_at_utc",
        }
        or pin.get("kind") != "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1"
        or pin.get("content_anchor_sha256") != content.content_anchor_sha256
        or pin.get("release_id") != content.release_id
        or not isinstance(pin.get("target_identity"), str)
        or re.fullmatch(r"docker:[0-9a-f]{64}", pin["target_identity"]) is None
        or pin.get("target_identity") != receipt.get("target_identity")
        or pin.get("destination_realpath") != receipt.get("destination_realpath")
        or pin.get("hostname") != receipt.get("observed_host")
        or _SHA256.fullmatch(pin.get("host_machine_id_sha256", "")) is None
        or not str(pin.get("postgres_system_identifier", "")).isdigit()
        or not pin.get("database_name")
        or type(pin.get("destination_device")) is not int
        or pin["destination_device"] < 0
        or type(pin.get("destination_inode")) is not int
        or pin["destination_inode"] <= 0
    ):
        raise PublicSuccessorActivationError("transfer target pin facts differ")
    pinned_at = _transfer_utc(pin.get("pinned_at_utc"), "pin date")
    observed_v1 = _transfer_utc(receipt.get("observed_at_utc"), "V1 date")
    observed_v2 = _transfer_utc(attestation.get("observed_at_utc"), "V2 date")
    expires = _transfer_utc(pin.get("expires_at_utc"), "pin expiry")
    if not (pinned_at < observed_v1 <= observed_v2 <= now_utc < expires):
        raise PublicSuccessorActivationError("transfer evidence expired or out of order")
    expected_v2 = {
        "kind": "NEXUS_STUDENT_PUBLIC_QUALIFIED_TRANSFER_TARGET_ATTESTATION_V2",
        "status": "QUALIFIED_OBSERVED_NOT_PUBLICATION_AUTHORITY",
        "content_anchor_sha256": content.content_anchor_sha256,
        "release_id": content.release_id,
        "transfer_manifest_sha256": plan_sha,
        "observed_v1_receipt_sha256": receipt_sha,
        "target_pin_sha256": expected_target_pin_sha256,
        "target_identity": pin["target_identity"],
        "hostname": pin["hostname"],
        "host_machine_id_sha256": pin["host_machine_id_sha256"],
        "postgres_system_identifier": pin["postgres_system_identifier"],
        "database_name": pin["database_name"],
        "destination_realpath": pin["destination_realpath"],
        "observed_at_utc": attestation["observed_at_utc"],
        "expires_at_utc": pin["expires_at_utc"],
        "file_count": receipt["file_count"],
        "derivative_receipt_count": receipt["derivative_receipt_count"],
        "total_bytes": receipt.get("total_bytes"),
    }
    if attestation != expected_v2:
        raise PublicSuccessorActivationError("transfer V2 attestation differs")
    return plan_sha


def verify_publication_batch_review(
    raw: bytes,
    content: PublicSuccessorContentVerdict,
    release_root: Path,
    transfer_manifest_sha256: str,
    scope_authorization_ids: tuple[str, ...],
    now_utc: datetime,
) -> ReleaseBatchPublicationReviewArtifact:
    """Vérifier le document LOT42 canonique contre A et le transfert exact.

    La revue humaine et les lignes DB sont vérifiées séparément au scellement ;
    un document LOT42 valide par forme ne s'auto-approuve jamais.
    """
    try:
        review = parse_release_batch_publication_review_artifact(raw)
    except (CanonicalArtifactError, ValueError) as error:
        raise PublicSuccessorActivationError("LOT42 review artifact invalid") from error
    try:
        release = load_release_expectation(
            release_root / "profile_gate/production-profile-gate.release.json",
            content.content_manifest_sha256,
        )
    except ReleaseReadinessError as error:
        raise PublicSuccessorActivationError("LOT42 A source invalid") from error
    currentness_values = {row.payload.get("currentness") for row in release.placements}
    if len(currentness_values) != 1 or not currentness_values <= {"current", "official_snapshot"}:
        raise PublicSuccessorActivationError("LOT42 A currentness is not homogeneous")
    registry = _read(
        release_root / "profile_gate", "artifacts.release.json",
        content.artifact_registry_sha256,
    )
    artifacts = registry.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != content.expected_counts["unique_artifacts"]:
        raise PublicSuccessorActivationError("LOT42 A artifact population differs")
    urls = [row.get("source_url") for row in artifacts if isinstance(row, dict)]
    if len(urls) != len(artifacts) or any(not isinstance(url, str) or not url for url in urls):
        raise PublicSuccessorActivationError("LOT42 A provenance URLs absent")
    try:
        require_release_batch_review_matches_release(
            review,
            observed_release_id=content.release_id,
            observed_release_manifest_sha256=content.content_manifest_sha256,
            observed_artifacts_release_sha256=content.artifact_registry_sha256,
            observed_candidate_inventory_sha256=content.candidate_inventory_sha256,
            observed_transfer_manifest_sha256=transfer_manifest_sha256,
            observed_collections=content.subject_sha256_by_collection,
            observed_counts=content.expected_counts,
            observed_placement_states={field: tuple(
                row.payload[field] for row in release.placements
            ) for field in ("currentness", "placement_status", "review_status")},
            observed_source_url_count=len(set(urls)),
        )
    except ReleaseBatchReviewMismatch as error:
        raise PublicSuccessorActivationError(f"LOT42 {error}") from error
    if review.scope_authorization_ids != scope_authorization_ids:
        raise PublicSuccessorActivationError("LOT42 scope authorization IDs differ")
    if now_utc < review.valid_from or now_utc >= review.valid_until:
        raise PublicSuccessorActivationError("LOT42 review expired or not yet valid")
    return review


def _verify_a2_offline_c(
    root: Path, content: PublicSuccessorContentVerdict,
    authorities: dict[str, str], authority_raw: bytes,
    expected_target_pin_sha256: str, now_utc: datetime,
) -> datetime:
    """Rejouer les liaisons A2/C hors ligne ; ne prononce aucune activation.

    La capture privée effective, les reviews et la DB restent des gates du
    signataire. Des seuls octets du bundle ne peuvent attester ces faits live.
    """
    from .public_successor_a2_transfer_binding import (
        A2TransferBindingError,
        verify_a2_transfer_binding,
    )
    from .public_successor_temporal import (
        PublicSuccessorTemporalError,
        verify_temporal_successor,
    )

    def material(field: str, label: str) -> bytes:
        try:
            return _read(root, f"authorities/{field}.bin", authorities[field], json_required=False)
        except (KeyError, PublicSuccessorActivationError) as error:
            raise PublicSuccessorActivationError(f"{label} absent or divergent") from error

    issue_raw = material("temporal_a2_issue_attestation_sha256", "A2 issue attestation")
    pulse_raw = material("temporal_c_attestation_sha256", "A2 C pulse")
    packet_raw = material("source_inventory_packet_sha256", "A2 source inventory")
    approval_raw = material("pr300_final_authority_receipt_sha256", "A2 PR300 approval")
    plan_raw = material("artifact_transfer_manifest_sha256", "A2 transfer plan")
    pin_raw = _read(root, "authorities/target-pin.json", expected_target_pin_sha256,
                    json_required=False)
    binding_raw = material("a2_transfer_binding_sha256", "A2 transfer binding")
    try:
        expiry = verify_temporal_successor(
            content, root / "release", authority_raw, issue_raw, pulse_raw,
            source_packet_raw=packet_raw, approval_raw=approval_raw, now_utc=now_utc,
        )
        verify_a2_transfer_binding(
            binding_raw, authority_raw, pin_raw, plan_raw, now_utc=now_utc,
        )
    except (PublicSuccessorTemporalError, A2TransferBindingError) as error:
        raise PublicSuccessorActivationError(f"A2 C evidence invalid: {error}") from error
    return expiry


def _finalize_a2_live_evidence(
    *, live: VerifiedPublicSuccessorLiveEvidence,
    content: PublicSuccessorContentVerdict,
    authority_envelope_sha256: str,
    authorities: Mapping[str, str],
    scope_sha256_by_id: Mapping[str, str],
    authorization_set: AuthorizationSetV2,
    batch_review: ReleaseBatchPublicationReviewArtifact,
    expected_target_pin_sha256: str,
    a2_expires_at_utc: datetime,
    pin_expires_at_utc: datetime,
    now_utc: datetime,
) -> PublicSuccessorActivationVerdict:
    """Composer C après rejeu live, jamais à partir de drapeaux du bundle."""
    if not isinstance(live, VerifiedPublicSuccessorLiveEvidence):
        raise PublicSuccessorActivationError("trusted live C replay absent")
    expected_reviews = tuple(sorted((
        str(member.scope.collection), member.authorization_id,
        member.authorization_digest, member.review_binding_digest,
    ) for member in authorization_set.members))
    verified = live.verified_authorization_set
    if not isinstance(verified, VerifiedAuthorizationSetV1) or any((
        dict(live.authority_sha256_by_field) != dict(authorities),
        set(authorities) != _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS,
        live.content_anchor_sha256 != content.content_anchor_sha256,
        live.authority_envelope_sha256 != authority_envelope_sha256,
        live.target_pin_sha256 != expected_target_pin_sha256,
        live.release_id != content.release_id,
        live.content_manifest_sha256 != content.content_manifest_sha256,
        dict(live.counts) != content.expected_counts,
        dict(live.scope_sha256_by_id) != dict(scope_sha256_by_id),
        verified.authorization_set_digest != authorities["authorization_set_sha256"],
        hashlib.sha256(verified.authorization_set_bytes).hexdigest()
            != verified.authorization_set_digest,
        verified.authorization_ids != tuple(
            member.authorization_id for member in authorization_set.members
        ),
        live.active_authorization_ids != verified.authorization_ids,
        live.lot42_attestation_count != content.expected_counts["placements"],
        bool(live.revoked_authorization_ids),
        bool(live.revoked_review_ids),
        verified.authorizations_effective_valid_from
            != authorization_set.authorizations_effective_valid_from,
        verified.authorizations_effective_valid_until
            != authorization_set.authorizations_effective_valid_until,
        live.authorization_review_evidence_by_id != expected_reviews,
        live.publication_batch_review_id != batch_review.review_id,
        live.publication_batch_review_digest
            != authorities["publication_batch_review_receipt_sha256"],
        live.target_pin_expires_at_utc != pin_expires_at_utc,
    )):
        raise PublicSuccessorActivationError("live C evidence differs from sealed A2/LOT41A/LOT42")
    binding = live.publication_batch_review_binding
    if (not isinstance(binding, tuple) or len(binding) != 6
            or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None
                   for value in binding[:3])
            or type(binding[3]) is not int or binding[3] <= 0
            or not isinstance(binding[4], str)
            or re.fullmatch(r"NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}", binding[4]) is None
            or binding[5] != "abenrhouma"):
        raise PublicSuccessorActivationError("LOT42 exact human review binding absent")
    for label, moment in (
        ("live replay", live.verified_at_utc),
        ("revocations", live.revocations_checked_at_utc),
        ("source pulse", live.source_pulse_replayed_at_utc),
        ("authorization review", verified.verified_at),
    ):
        if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
            raise PublicSuccessorActivationError(f"{label} UTC proof absent")
        if not now_utc - timedelta(minutes=5) <= moment <= now_utc:
            raise PublicSuccessorActivationError(f"{label} proof stale or in future")
    if (live.revocations_checked_at_utc > live.verified_at_utc
            or live.source_pulse_replayed_at_utc > live.verified_at_utc):
        raise PublicSuccessorActivationError("source or revocations checked after live replay")
    expiry_candidates = (
        a2_expires_at_utc, pin_expires_at_utc,
        verified.authorizations_effective_valid_until,
        verified.earliest_review_binding_expires_at,
        batch_review.valid_until, live.expires_at_utc,
    )
    if any(
        value.tzinfo is None or value.utcoffset() != timedelta(0) or value <= now_utc
        for value in expiry_candidates
    ) or a2_expires_at_utc - now_utc < timedelta(hours=24):
        raise PublicSuccessorActivationError("live C authority expiry invalid")
    expiry = min(expiry_candidates)
    return PublicSuccessorActivationVerdict(
        release_id=content.release_id,
        content_anchor_sha256=content.content_anchor_sha256,
        content_manifest_sha256=content.content_manifest_sha256,
        authority_envelope_sha256=authority_envelope_sha256,
        artifact_registry_sha256=content.artifact_registry_sha256,
        release_registry_sha256=content.release_registry_sha256,
        scope_authority_sha256=authorities["public_scope_authority_sha256"],
        subject_sha256_by_collection=content.subject_sha256_by_collection,
        scope_sha256_by_id=dict(scope_sha256_by_id),
        counts=content.expected_counts,
        expires_at_utc=expiry,
        authorization_review_evidence_by_id=expected_reviews,
        transfer_manifest_sha256=authorities["artifact_transfer_manifest_sha256"],
        publication_batch_review_id=batch_review.review_id,
        publication_batch_review_digest=authorities["publication_batch_review_receipt_sha256"],
        publication_batch_review_binding=binding,
    )


def _finalize_a2_signed_readiness(
    *, readiness: ProductionReadinessManifestV2 | StagingReadinessManifestV1,
    content: PublicSuccessorContentVerdict,
    authority_envelope_sha256: str,
    authorities: Mapping[str, str],
    scope_sha256_by_id: Mapping[str, str],
    authorization_set: AuthorizationSetV2,
    batch_review: ReleaseBatchPublicationReviewArtifact,
    expected_target_pin_sha256: str,
    a2_expires_at_utc: datetime,
    pin_expires_at_utc: datetime,
    now_utc: datetime,
) -> PublicSuccessorActivationVerdict:
    """Relire C au runtime sous une assertion C effectivement signée.

    Seul le producteur de la signature avait accès au rejeu live complet.
    La DB et ses révocations doivent encore être revérifiées par l'appelant.
    """
    if not isinstance(readiness, ProductionReadinessManifestV2 | StagingReadinessManifestV1):
        raise PublicSuccessorActivationError("signed runtime C readiness type invalid")
    expiry = readiness.public_successor_c_expires_at_utc
    verified_at = readiness.public_successor_c_verified_at_utc
    binding = readiness.public_successor_lot42_review_binding
    if isinstance(readiness, ProductionReadinessManifestV2):
        signed_content = readiness.public_successor_content_manifest_digest
        signed_anchor = readiness.public_successor_content_anchor_digest
        signed_envelope = readiness.public_successor_authority_envelope_digest
        signed_pin = readiness.public_successor_target_pin_digest
        phase_valid = readiness.sealed_manifest_digest == content.content_manifest_sha256
        effective_expiry = expiry
    else:
        signed_content = readiness.allowed_release_manifest_sha256
        signed_anchor = readiness.public_successor_content_anchor_digest
        signed_envelope = readiness.public_successor_phase_authority_digest
        signed_pin = readiness.public_successor_target_pin_digest
        phase_valid = (
            readiness.public_successor_phase == "PUBLICATION"
            and readiness.allowed_release_id == content.release_id
            and readiness.environment == "rehearsal"
            and expiry is not None and readiness.expires_at <= expiry
        )
        effective_expiry = min(expiry, readiness.expires_at) if expiry is not None else None
    static_expiry = min(
        a2_expires_at_utc, pin_expires_at_utc,
        authorization_set.authorizations_effective_valid_until,
        batch_review.valid_until,
    )
    if (
        set(authorities) != _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS
        or signed_content != content.content_manifest_sha256
        or signed_anchor != content.content_anchor_sha256
        or signed_envelope != authority_envelope_sha256
        or signed_pin != expected_target_pin_sha256
        or not phase_valid
        or expiry is None or verified_at is None or effective_expiry is None
        or not readiness.issued_at <= verified_at <= now_utc < effective_expiry
        or expiry > static_expiry
        or readiness.issued_at < a2_expires_at_utc - timedelta(days=7)
        or binding is None
        or batch_review.digest()
            != authorities["publication_batch_review_receipt_sha256"]
    ):
        raise PublicSuccessorActivationError("signed runtime C authority differs or expired")
    expected_reviews = tuple(sorted((
        str(member.scope.collection), member.authorization_id,
        member.authorization_digest, member.review_binding_digest,
    ) for member in authorization_set.members))
    if len(expected_reviews) != content.expected_counts["subjects"]:
        raise PublicSuccessorActivationError("signed C authorization population differs")
    return PublicSuccessorActivationVerdict(
        release_id=content.release_id,
        content_anchor_sha256=content.content_anchor_sha256,
        content_manifest_sha256=content.content_manifest_sha256,
        authority_envelope_sha256=authority_envelope_sha256,
        artifact_registry_sha256=content.artifact_registry_sha256,
        release_registry_sha256=content.release_registry_sha256,
        scope_authority_sha256=authorities["public_scope_authority_sha256"],
        subject_sha256_by_collection=content.subject_sha256_by_collection,
        scope_sha256_by_id=dict(scope_sha256_by_id),
        counts=content.expected_counts,
        expires_at_utc=effective_expiry,
        authorization_review_evidence_by_id=expected_reviews,
        transfer_manifest_sha256=authorities["artifact_transfer_manifest_sha256"],
        publication_batch_review_id=batch_review.review_id,
        publication_batch_review_digest=authorities["publication_batch_review_receipt_sha256"],
        publication_batch_review_binding=binding,
    )


def verify_public_successor_activation(
    bundle_root: Path,
    *,
    expected_content_anchor_sha256: str,
    expected_authority_envelope_sha256: str,
    expected_release_id: str,
    expected_registry_sha256: str,
    expected_scope_authority_sha256: str,
    expected_target_pin_sha256: str,
    now_utc: datetime | None = None,
    live_verifier: PublicSuccessorLiveVerifier | None = None,
    signed_runtime_readiness: tuple[bytes, bytes] | None = None,
    signed_staging_readiness: tuple[bytes, bytes] | None = None,
) -> PublicSuccessorActivationVerdict:
    """Refuser C tant que chaque autorité externe n'est pas vérifiée sémantiquement.

    Les digests viennent de la readiness signée, et l'absence de readiness
    signée doit être refusée par l'appelant avant cet appel. Le bundle seul
    ne peut ni signer ses propres digests, ni se déclarer activable.
    """
    runtime_now = now_utc or datetime.now(UTC)
    if sum(value is not None for value in (
        live_verifier, signed_runtime_readiness, signed_staging_readiness,
    )) > 1:
        raise PublicSuccessorActivationError("C proof modes are mutually exclusive")
    signed_readiness: ProductionReadinessManifestV2 | None = None
    staging_readiness: StagingReadinessManifestV1 | None = None
    if signed_runtime_readiness is not None:
        try:
            signed_raw, trust_anchor_raw = signed_runtime_readiness
            signed_readiness = verify_production_readiness_manifest_v2(
                signed_raw,
                trust_anchor=parse_production_readiness_trust_anchor(trust_anchor_raw),
                environment="production",
            )
        except Exception as error:
            raise PublicSuccessorActivationError("signed runtime C proof invalid") from error
    if signed_staging_readiness is not None:
        try:
            signed_raw, trust_anchor_raw = signed_staging_readiness
            staging_readiness = verify_staging_readiness_manifest(
                signed_raw,
                trust_anchor=parse_staging_readiness_trust_anchor(trust_anchor_raw),
                now=runtime_now,
            )
        except Exception as error:
            raise PublicSuccessorActivationError("signed staging C proof invalid") from error
    signed_authority = signed_readiness or staging_readiness
    if signed_authority is not None:
        signed_now = signed_authority.public_successor_c_verified_at_utc
        if signed_now is None:
            raise PublicSuccessorActivationError("signed C replay time absent")
        now = signed_now
    else:
        now = runtime_now
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
        or not isinstance(expected_target_pin_sha256, str)
        or _SHA256.fullmatch(expected_target_pin_sha256) is None
    ):
        raise PublicSuccessorActivationError("signed release, registry or target pin differs")
    try:
        envelope = _read(root, "authority-envelope.json", expected_authority_envelope_sha256)
    except PublicSuccessorActivationError as error:
        raise PublicSuccessorActivationError("authority envelope absent or divergent") from error
    if set(envelope) != {
        "kind", "status", "activation_allowed", "semantic_verification_complete",
        "content_anchor_sha256", "content_release_id", "content_manifest_sha256",
        "expected_counts", "authorities",
    } or (
        envelope.get("kind") not in {
            "NEXUS_PUBLIC_SUCCESSOR_AUTHORITY_ENVELOPE_V1", _A2_ENVELOPE_KIND,
        }
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
    a2 = envelope["kind"] == _A2_ENVELOPE_KIND
    expected_fields = (
        _PUBLIC_SUCCESSOR_A2_AUTHORITY_FIELDS
        if a2 else _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS
    )
    if not isinstance(authorities, dict) or set(authorities) != expected_fields:
        raise PublicSuccessorActivationError("versioned authority field population differs")
    a2_expiry: datetime | None = None
    if a2:
        try:
            authority_raw = _read(
                root, "authorities/temporal_a2_authority_sha256.bin",
                authorities["temporal_a2_authority_sha256"], json_required=False,
            )
        except PublicSuccessorActivationError as error:
            raise PublicSuccessorActivationError("A2 authority absent or divergent") from error
        from .public_successor_temporal import (
            APPROVED_A2_AUTHORITY_SHA256,
        )
        if hashlib.sha256(authority_raw).hexdigest() != APPROVED_A2_AUTHORITY_SHA256:
            raise PublicSuccessorActivationError("A2 authority differs from approved digest")
        a2_expiry = _verify_a2_offline_c(
            root, content, authorities, authority_raw,
            expected_target_pin_sha256, now,
        )
    else:
        verify_content_currentness(root / "release", content, now)
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
    plan_raw = _read(
        root, "authorities/artifact_transfer_manifest_sha256.bin",
        authorities["artifact_transfer_manifest_sha256"], json_required=False,
    )
    transfer_v2_raw = _read(
        root, "authorities/observed_transfer_receipt_sha256.bin",
        authorities["observed_transfer_receipt_sha256"], json_required=False,
    )
    transfer_v2 = _compact_document(transfer_v2_raw, "transfer V2 attestation")
    receipt_sha = transfer_v2.get("observed_v1_receipt_sha256")
    if not isinstance(receipt_sha, str) or _SHA256.fullmatch(receipt_sha) is None:
        raise PublicSuccessorActivationError("transfer V1 receipt reference absent")
    receipt_v1_raw = _read(
        root, "authorities/observed-transfer-v1.json", receipt_sha, json_required=False,
    )
    target_pin_raw = _read(
        root, "authorities/target-pin.json", expected_target_pin_sha256,
        json_required=False,
    )
    observed_plan_sha = verify_public_transfer_offline(
        plan_raw, receipt_v1_raw, target_pin_raw, transfer_v2_raw,
        root / "release", content,
        expected_target_pin_sha256=expected_target_pin_sha256, now_utc=now,
    )
    if observed_plan_sha != authorities["artifact_transfer_manifest_sha256"]:
        raise PublicSuccessorActivationError("transfer plan differs from C")
    scope_registry_path = root / "authorities/public_scope_authority_sha256.bin"
    scopes = verify_public_scope_registry(
        scope_registry_path,
        authorities["public_scope_authority_sha256"], content,
        root / "release", scope_root=root,
    )
    scope_review_raw = _read(
        root, "authorities/exact_head_scope_review_receipt_sha256.bin",
        authorities["exact_head_scope_review_receipt_sha256"], json_required=False,
    )
    try:
        scope_review = json.loads(scope_review_raw)
        policy_sha = scope_review["policy_registry_sha256"]
        names_sha = scope_review["successor_authority_sha256"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise PublicSuccessorActivationError("scope review authority invalid") from error
    policy_raw = _read(root, "authorities/scope-policy.yml", policy_sha, json_required=False)
    names_raw = _read(root, "authorities/scope-names.yml", names_sha, json_required=False)
    scope_sha256_by_id = verify_reviewed_public_scope_policy(
        scope_registry_path, authorities["public_scope_authority_sha256"],
        content, scopes, policy_raw=policy_raw, names_raw=names_raw,
        receipt_raw=scope_review_raw,
        expected_receipt_sha256=authorities["exact_head_scope_review_receipt_sha256"],
    )
    authorization_raw = _read(
        root, "authorities/authorization_set_sha256.bin",
        authorities["authorization_set_sha256"], json_required=False,
    )
    authorization_set = verify_public_lot41a_authorization_set(
        authorization_raw, root / "release", content, now,
        temporal_authority_raw=authority_raw if a2 else None,
    )
    revocation_raw = _read(
        root, "authorities/revocation_evidence_sha256.bin",
        authorities["revocation_evidence_sha256"], json_required=False,
    )
    verify_public_authorization_revocations(
        revocation_raw,
        authorization_ids=tuple(member.authorization_id for member in authorization_set.members),
    )
    batch_review_raw = _read(
        root, "authorities/publication_batch_review_receipt_sha256.bin",
        authorities["publication_batch_review_receipt_sha256"], json_required=False,
    )
    worker_transfer_sha = derive_worker_transfer_manifest_sha256(
        plan_raw, receipt_v1_raw,
    )
    batch_review = verify_publication_batch_review(
        batch_review_raw, content, root / "release",
        worker_transfer_sha,
        tuple(member.authorization_id for member in authorization_set.members), now,
    )
    if not a2 or a2_expiry is None or (
        live_verifier is None and signed_authority is None
    ):
        raise PublicSuccessorActivationError(
            "public successor authority semantics incomplete: activation refused"
        )
    pin_expiry = _transfer_utc(
        _compact_document(target_pin_raw, "target pin").get("expires_at_utc"),
        "pin expiry",
    )
    if signed_authority is not None:
        return _finalize_a2_signed_readiness(
            readiness=signed_authority, content=content,
            authority_envelope_sha256=expected_authority_envelope_sha256,
            authorities=authorities, scope_sha256_by_id=scope_sha256_by_id,
            authorization_set=authorization_set, batch_review=batch_review,
            expected_target_pin_sha256=expected_target_pin_sha256,
            a2_expires_at_utc=a2_expiry, pin_expires_at_utc=pin_expiry,
            now_utc=runtime_now,
        )
    if live_verifier is None:
        raise PublicSuccessorActivationError("trusted live C verifier absent")
    request = PublicSuccessorLiveVerificationRequest(
        bundle_root=root, content=content,
        authority_envelope_sha256=expected_authority_envelope_sha256,
        authorities=dict(authorities), scope_sha256_by_id=scope_sha256_by_id,
        authorization_set=authorization_set, publication_batch_review=batch_review,
        target_pin_sha256=expected_target_pin_sha256,
        a2_expires_at_utc=a2_expiry, pin_expires_at_utc=pin_expiry,
        now_utc=now,
    )
    try:
        live = live_verifier(request)
    except Exception as error:
        raise PublicSuccessorActivationError("trusted live C replay failed") from error
    return _finalize_a2_live_evidence(
        live=live, content=content,
        authority_envelope_sha256=expected_authority_envelope_sha256,
        authorities=authorities, scope_sha256_by_id=scope_sha256_by_id,
        authorization_set=authorization_set, batch_review=batch_review,
        expected_target_pin_sha256=expected_target_pin_sha256,
        a2_expires_at_utc=a2_expiry, pin_expires_at_utc=pin_expiry,
        now_utc=_post_replay_utc_now(now),
    )
