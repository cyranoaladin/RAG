"""Frontière pure et unique de vérification du matériel de release V2.

Le signer, le déploiement et le runtime lui transmettent un snapshot d'octets
déjà gelé. Aucun de ces appelants ne réimplémente la chaîne de confiance.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nexus_contracts.authorization_set import (
    AuthorizationSetError,
    AuthorizationSetV1,
    ReleaseScopePlacementV1,
    VerifiedAuthorizationSetV1,
    VerifiedProfileFactV1,
    parse_authorization_set,
    parse_release_scope_placement,
    verify_authorization_set,
)
from nexus_contracts.h2_coverage_evidence import (
    H2CoverageEvidenceError,
    H2CoverageEvidenceV2,
    parse_h2_coverage_evidence_v2,
)
from nexus_contracts.profile_manifest import (
    ProductionProfileManifestError,
    validate_production_profile_manifest,
)
from nexus_contracts.release_evidence import (
    H2EvidenceBundleV2,
    PromotionEvidenceV2,
    ReleaseEvidenceError,
    parse_h2_evidence_bundle_v2,
    parse_promotion_evidence_v2,
    verify_h2_evidence_bundle_v2_freshness,
    verify_promotion_evidence_v2,
)
from nexus_contracts.release_scope_placement import (
    ReleaseScopePlacementProducerError,
    produce_release_scope_placement_from_blobs,
)
from nexus_contracts.review_binding import (
    ReviewBindingError,
)
from nexus_contracts.review_binding import (
    parse_trust_anchor as parse_review_binding_trust_anchor,
)

TRUSTED_REPOSITORY = "cyranoaladin/RAG"
RELEASE_SCOPE_GIT_PATH_KEYS = frozenset(
    {
        "profile_proposal_matrix_path",
        "accepted_placements_path",
        "release_registry_path",
        "expected_contents_path",
        "verified_profiles_path",
        "profile_manifest_path",
    }
)


class V2ReleaseVerificationError(RuntimeError):
    """Le snapshot V2 n'établit pas une release complète et cohérente."""


@dataclass(frozen=True)
class V2ReleaseMaterial:
    authorization_set_raw: bytes
    release_files: Mapping[str, bytes]
    review_binding_trust_anchor_raw: bytes
    trusted_reviewers_raw: bytes
    revocation_registry_raw: bytes
    release_scope_placement_raw: bytes
    release_scope_source_blobs: Mapping[str, bytes]
    verified_profiles: tuple[VerifiedProfileFactV1, ...]
    profile_manifest_raw: bytes
    authority_required_content_sha256: tuple[str, ...]
    h2_coverage_raw: bytes
    h2_evidence_bundle_raw: bytes
    promotion_evidence_raw: bytes
    evidence_files: Mapping[str, bytes]
    sealed_manifest_raw: bytes
    now: datetime
    merge_sha: str
    merge_tree_sha: str
    release_scope_git_paths: Mapping[str, str] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_signing_material(cls, material: Any) -> V2ReleaseMaterial:
        """Copie défensivement un snapshot compatible sans lui faire confiance."""
        return cls(
            authorization_set_raw=bytes(material.authorization_set_raw),
            release_files=dict(material.release_files),
            review_binding_trust_anchor_raw=bytes(
                material.review_binding_trust_anchor_raw
            ),
            trusted_reviewers_raw=bytes(material.trusted_reviewers_raw),
            revocation_registry_raw=bytes(material.revocation_registry_raw),
            release_scope_placement_raw=bytes(material.release_scope_placement_raw),
            release_scope_source_blobs=dict(material.release_scope_source_blobs),
            verified_profiles=tuple(material.verified_profiles),
            profile_manifest_raw=bytes(material.profile_manifest_raw),
            authority_required_content_sha256=tuple(
                material.authority_required_content_sha256
            ),
            h2_coverage_raw=bytes(material.h2_coverage_raw),
            h2_evidence_bundle_raw=bytes(material.h2_evidence_bundle_raw),
            promotion_evidence_raw=bytes(material.promotion_evidence_raw),
            evidence_files=dict(material.evidence_files),
            sealed_manifest_raw=bytes(material.sealed_manifest_raw),
            now=material.now,
            merge_sha=str(material.merge_sha),
            merge_tree_sha=str(material.merge_tree_sha),
            release_scope_git_paths=dict(material.release_scope_git_paths),
        )


@dataclass(frozen=True)
class VerifiedV2ReleaseMaterial:
    authorization_set: AuthorizationSetV1
    verified_authorization_set: VerifiedAuthorizationSetV1
    release_scope_placement: ReleaseScopePlacementV1
    h2_coverage: H2CoverageEvidenceV2
    h2_bundle: H2EvidenceBundleV2
    promotion: PromotionEvidenceV2


def _trusted_reviewers(raw: bytes) -> tuple[str, tuple[str, ...]]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise V2ReleaseVerificationError(
                    f"trusted reviewers repeats key {key!r}"
                )
            result[key] = value
        return result

    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V2ReleaseVerificationError(
            f"trusted reviewers is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(document, dict) or set(document) != {"repository", "reviewers"}:
        raise V2ReleaseVerificationError("trusted reviewers has an unexpected field set")
    repository = document.get("repository")
    reviewers = document.get("reviewers")
    if (
        not isinstance(repository, str)
        or not repository
        or not isinstance(reviewers, list)
        or not reviewers
        or any(not isinstance(item, str) or not item for item in reviewers)
        or len(reviewers) != len(set(reviewers))
    ):
        raise V2ReleaseVerificationError(
            "trusted reviewers must be a non-empty unique string list"
        )
    return repository, tuple(reviewers)


def _require_equal(label: str, *values: object) -> None:
    if not values or any(value != values[0] for value in values[1:]):
        raise V2ReleaseVerificationError(
            f"{label} does not match across V2 release evidence"
        )


def _produce_release_scope_from_frozen_blobs(
    material: V2ReleaseMaterial,
) -> tuple[ReleaseScopePlacementV1, tuple[VerifiedProfileFactV1, ...], dict[str, str]]:
    paths = dict(material.release_scope_git_paths)
    if set(paths) != RELEASE_SCOPE_GIT_PATH_KEYS:
        raise V2ReleaseVerificationError("release scope exact-tree path roles are incomplete")
    if len(set(paths.values())) != len(paths):
        raise V2ReleaseVerificationError("release scope exact-tree path roles are duplicated")
    try:
        produced = produce_release_scope_placement_from_blobs(
            source_blobs=material.release_scope_source_blobs,
            **paths,
        )
    except ReleaseScopePlacementProducerError as exc:
        raise V2ReleaseVerificationError(
            f"exact-tree profile verification refused: {exc}"
        ) from exc
    actual_digests = {
        path: hashlib.sha256(raw).hexdigest()
        for path, raw in sorted(material.release_scope_source_blobs.items())
    }
    if produced.input_blob_sha256 != actual_digests:
        raise V2ReleaseVerificationError(
            "exact-tree producer did not consume the complete release scope source set"
        )
    return produced.placement, produced.verified_profile_facts, actual_digests


def verify_v2_release_material(
    material: V2ReleaseMaterial,
) -> VerifiedV2ReleaseMaterial:
    """Revérifie toute la chaîne V2 par un unique appel global au set."""
    if not isinstance(material, V2ReleaseMaterial):
        raise TypeError("material must be a V2ReleaseMaterial")
    if material.now.tzinfo is None:
        raise V2ReleaseVerificationError("V2 verification time must be timezone-aware")
    try:
        authorization_set = parse_authorization_set(material.authorization_set_raw)
        placement = parse_release_scope_placement(material.release_scope_placement_raw)
        produced_placement, produced_profiles, produced_source_digests = (
            _produce_release_scope_from_frozen_blobs(material)
        )
        if produced_placement.canonical_bytes() != placement.canonical_bytes():
            raise V2ReleaseVerificationError(
                "exact-tree producer placement differs from supplied release placement"
            )
        if produced_profiles != material.verified_profiles:
            raise V2ReleaseVerificationError(
                "verified profile facts differ from exact-tree producer output"
            )
        profile_manifest_path = material.release_scope_git_paths["profile_manifest_path"]
        if material.release_scope_source_blobs.get(profile_manifest_path) != (
            material.profile_manifest_raw
        ):
            raise V2ReleaseVerificationError(
                "profile manifest differs from exact-tree source bytes"
            )
        review_anchor = parse_review_binding_trust_anchor(
            material.review_binding_trust_anchor_raw
        )
        expected_repository, accepted_reviewers = _trusted_reviewers(
            material.trusted_reviewers_raw
        )
        verified_set = verify_authorization_set(
            authorization_set,
            release_files=material.release_files,
            trust_anchor=review_anchor,
            environment="production",
            now=material.now,
            expected_repository=expected_repository,
            accepted_reviewers=accepted_reviewers,
            release_scope_placement=placement,
            verified_profiles=produced_profiles,
            revocation_registry_raw=material.revocation_registry_raw,
            authority_required_content_sha256=material.authority_required_content_sha256,
        )
    except (AuthorizationSetError, ReviewBindingError, ValueError) as exc:
        raise V2ReleaseVerificationError(
            f"authorization set verification refused: {exc}"
        ) from exc

    if expected_repository != TRUSTED_REPOSITORY:
        raise V2ReleaseVerificationError(
            f"trusted reviewers repository {expected_repository!r} is not "
            f"{TRUSTED_REPOSITORY!r}"
        )
    if verified_set.authorization_set_bytes != material.authorization_set_raw:
        raise V2ReleaseVerificationError("authorization set bytes changed during verification")
    if hashlib.sha256(material.sealed_manifest_raw).hexdigest() != (
        authorization_set.corpus_manifest_sha256
    ):
        raise V2ReleaseVerificationError(
            "corpus manifest digest does not match the authorization set"
        )

    profile_fingerprints = {
        (fact.profile_id, fact.profile_version): fact.profile_fingerprint
        for fact in material.verified_profiles
    }
    if len(profile_fingerprints) != len(material.verified_profiles):
        raise V2ReleaseVerificationError("verified profile identities are duplicated")
    try:
        profile_manifest = validate_production_profile_manifest(
            material.profile_manifest_raw,
            profile_fingerprints=profile_fingerprints,
            source="profile_manifest",
        )
    except ProductionProfileManifestError as exc:
        raise V2ReleaseVerificationError(
            f"profile manifest verification refused: {exc}"
        ) from exc
    _require_equal(
        "profile manifest digest",
        profile_manifest.manifest_fingerprint,
        authorization_set.profile_manifest_digest,
        placement.profile_manifest_digest,
    )

    exact_evidence = {
        "authorization_set": material.authorization_set_raw,
        "authority_revocations": material.revocation_registry_raw,
        "release_scope_placement": material.release_scope_placement_raw,
        "review_binding_trust_anchor": material.review_binding_trust_anchor_raw,
        "trusted_reviewers": material.trusted_reviewers_raw,
    }
    for name, raw in exact_evidence.items():
        if material.evidence_files.get(name) != raw:
            raise V2ReleaseVerificationError(f"{name} evidence bytes were substituted")

    try:
        h2_coverage = parse_h2_coverage_evidence_v2(material.h2_coverage_raw)
        h2_bundle = parse_h2_evidence_bundle_v2(material.h2_evidence_bundle_raw)
        promotion = parse_promotion_evidence_v2(material.promotion_evidence_raw)
        verify_h2_evidence_bundle_v2_freshness(h2_bundle, now=material.now)
        verify_promotion_evidence_v2(promotion, h2_bundle=h2_bundle)
    except (H2CoverageEvidenceError, ReleaseEvidenceError, ValueError) as exc:
        raise V2ReleaseVerificationError(
            f"V2 H2/promotion verification refused: {exc}"
        ) from exc

    _require_equal("input_file_digests", h2_coverage.input_file_digests, h2_bundle.input_file_digests)
    if set(material.evidence_files) != set(h2_coverage.input_file_digests):
        raise V2ReleaseVerificationError(
            "V2 H2 evidence file set differs from input_file_digests"
        )
    for name, expected_digest in h2_coverage.input_file_digests.items():
        if hashlib.sha256(material.evidence_files[name]).hexdigest() != expected_digest:
            raise V2ReleaseVerificationError(f"H2 input digest mismatch for {name!r}")

    authorization_set_digest = hashlib.sha256(material.authorization_set_raw).hexdigest()
    placement_digest = hashlib.sha256(material.release_scope_placement_raw).hexdigest()
    h2_coverage_digest = hashlib.sha256(material.h2_coverage_raw).hexdigest()
    _require_equal(
        "authorization_set_digest", authorization_set_digest,
        verified_set.authorization_set_digest, h2_coverage.authorization_set_digest,
        h2_bundle.authorization_set_digest, promotion.authorization_set_digest,
    )
    _require_equal(
        "authorization_count", authorization_set.authorization_count,
        h2_coverage.authorization_count, h2_bundle.authorization_count,
        promotion.authorization_count,
    )
    _require_equal(
        "authority_required_count", authorization_set.authority_required_count,
        h2_coverage.authority_required_count, h2_coverage.authority_covered_count,
        h2_bundle.authority_required_count, h2_bundle.authority_covered_count,
        promotion.authority_required_count,
    )
    _require_equal(
        "authority_required_set_sha256", authorization_set.authority_required_set_sha256,
        h2_coverage.authority_required_set_sha256,
        h2_bundle.authority_required_set_sha256, promotion.authority_required_set_sha256,
    )
    _require_equal(
        "release scope placement digest", placement.digest(), placement_digest,
        authorization_set.release_scope_placement_digest,
        h2_coverage.release_scope_placement_digest,
        h2_bundle.release_scope_placement_digest,
        promotion.release_scope_placement_digest,
    )
    _require_equal(
        "corpus manifest digest", authorization_set.corpus_manifest_sha256,
        h2_coverage.corpus_manifest_sha256, h2_bundle.corpus_manifest_sha256,
        promotion.corpus_manifest_sha256,
    )
    _require_equal(
        "profile manifest digest", authorization_set.profile_manifest_digest,
        h2_coverage.profile_manifest_digest, h2_bundle.profile_manifest_digest,
        promotion.profile_manifest_digest,
    )
    _require_equal(
        "H2 coverage digest", h2_coverage_digest,
        h2_bundle.h2_coverage_evidence_sha256, promotion.h2_coverage_evidence_sha256,
    )
    _require_equal(
        "catalog digest", hashlib.sha256(material.evidence_files["catalog"]).hexdigest(),
        h2_bundle.catalog_sha256, promotion.catalog_sha256,
    )
    _require_equal(
        "revocation registry digest", hashlib.sha256(material.revocation_registry_raw).hexdigest(),
        h2_bundle.revocation_registry_sha256, promotion.revocation_registry_sha256,
    )
    _require_equal(
        "review binding trust anchor digest",
        hashlib.sha256(material.review_binding_trust_anchor_raw).hexdigest(),
        h2_bundle.review_binding_trust_anchor_sha256,
        promotion.review_binding_trust_anchor_sha256,
    )
    _require_equal(
        "trusted reviewers digest", hashlib.sha256(material.trusted_reviewers_raw).hexdigest(),
        h2_bundle.trusted_reviewers_sha256, promotion.trusted_reviewers_sha256,
    )
    _require_equal(
        "effective authorization expiry", verified_set.authorizations_effective_valid_until,
        h2_coverage.authorizations_effective_valid_until,
        h2_bundle.authorizations_effective_valid_until,
    )
    _require_equal(
        "earliest review submitted_at", verified_set.earliest_review_submitted_at,
        h2_coverage.earliest_review_submitted_at, h2_bundle.earliest_review_submitted_at,
    )
    _require_equal(
        "earliest review binding verified_at",
        verified_set.earliest_review_binding_verified_at,
        h2_coverage.earliest_review_binding_verified_at,
        h2_bundle.earliest_review_binding_verified_at,
    )
    _require_equal(
        "earliest review binding expires_at", verified_set.earliest_review_binding_expires_at,
        h2_coverage.earliest_review_binding_expires_at,
        h2_bundle.earliest_review_binding_expires_at,
    )
    _require_equal(
        "merge SHA", material.merge_sha, h2_coverage.git_commit,
        h2_bundle.merge_sha, promotion.merge_sha,
    )
    _require_equal(
        "release scope source tree SHA", material.merge_tree_sha,
        h2_coverage.release_scope_source_tree_sha,
        h2_bundle.release_scope_source_tree_sha,
    )
    _require_equal(
        "release scope source blobs", h2_coverage.release_scope_source_blob_digests,
        h2_bundle.release_scope_source_blob_digests,
    )
    _require_equal(
        "exact-tree release scope source blobs", produced_source_digests,
        h2_coverage.release_scope_source_blob_digests,
    )
    if not h2_coverage.h2_coverage_gate_pass:
        raise V2ReleaseVerificationError("H2 coverage gate is not passing")
    return VerifiedV2ReleaseMaterial(
        authorization_set=authorization_set,
        verified_authorization_set=verified_set,
        release_scope_placement=placement,
        h2_coverage=h2_coverage,
        h2_bundle=h2_bundle,
        promotion=promotion,
    )


__all__ = [
    "RELEASE_SCOPE_GIT_PATH_KEYS",
    "TRUSTED_REPOSITORY",
    "V2ReleaseMaterial",
    "V2ReleaseVerificationError",
    "VerifiedV2ReleaseMaterial",
    "verify_v2_release_material",
]
