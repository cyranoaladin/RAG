"""Fabrique contractuelle de fixture pour le rehearsal Docker V2.

Ce module ne contient aucune clé. Les deux graines Ed25519 sont des arguments
obligatoires des frontières qui les utilisent et ne sont jamais retournées.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import sign_production_readiness_manifest_cli as signer
from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.authorization_set import (
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV1,
    VerifiedProfileFactV1,
    canonical_review_binding_path,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.h2_coverage_evidence import H2CoverageEvidenceV2
from nexus_contracts.ingestion import CollectionProfile, collection_profile_fingerprint
from nexus_contracts.production_readiness import (
    ProductionReadinessTrustAnchor,
    ProductionReadinessTrustAnchorKey,
    public_readiness_key_hex,
)
from nexus_contracts.profile_manifest import validate_production_profile_manifest
from nexus_contracts.release_evidence import H2EvidenceBundleV2, PromotionEvidenceV2
from nexus_contracts.review_binding import (
    ScopeAuthorizationReviewBindingV1,
    expected_challenge_digest,
    sign_review_binding,
)
from nexus_contracts.review_binding import (
    TrustAnchor as ReviewBindingTrustAnchor,
)
from nexus_contracts.review_binding import (
    public_key_hex as review_binding_public_key_hex,
)

REPOSITORY = "cyranoaladin/RAG"
PR_NUMBER = 9001
REVIEWER = "abenrhouma"
AUTHOR = "cyranoaladin"
AUTHORIZATION_ID = "atomic-docker-v2-rehearsal-authz-v1"
REVIEW_KEY_ID = "atomic-docker-v2-rehearsal-review-ephemeral"
READINESS_KEY_ID = "atomic-docker-v2-rehearsal-readiness-ephemeral"
WORKFLOW_REF = "refs/heads/main"
PROMOTION_WORKFLOW_PATH = ".github/workflows/promote.yml"
PROVENANCE_RUN_ID = 7001
PROVENANCE_RUN_ATTEMPT = 1
PROMOTION_RUN_ID = 7002
PROMOTION_RUN_ATTEMPT = 1
CONTENT_SHA256 = "e" * 64


@dataclass(frozen=True)
class ReleaseMaterialFixture:
    material: signer.V2ReleaseMaterial
    review_binding_public_anchor_sha256: str


@dataclass(frozen=True)
class SignedReadinessFixture:
    signed_manifest_raw: bytes
    trust_anchor_raw: bytes
    public_anchor_sha256: str


def _canonical_json(document: Any) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _authorization_bytes(
    *, profile_manifest_digest: str, profile_fingerprint: str, now: datetime
) -> bytes:
    return ScopeAuthorizationArtifactV2.model_validate(
        {
            "protocol_version": "LOT41A-V2",
            "authorization_id": AUTHORIZATION_ID,
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": {
                "tenant": "libre_terminale",
                "collection": "rag_nexus_nsi_terminale_specialite",
                "niveau": "terminale",
                "voie": "generale",
                "matiere": "nsi",
                "candidat": "libre",
                "audience": ["libre", "tous"],
                "visibility": "internal",
                "school_year": "2026-2027",
                "programme_version": "BOEN_special_8_2019-07-25",
            },
            "manifest_digest": profile_manifest_digest,
            "profile_id": "rag_nexus_nsi_terminale_specialite",
            "profile_version": "v1",
            "profile_fingerprint": profile_fingerprint,
            "allowed_domains": ["eduscol.education.fr"],
            "rights_categories": ["officiel_public"],
            "exclusions": [],
            "allowed_content_sha256": [CONTENT_SHA256],
            "pii_absence_attested": True,
            "pii_absence_evidence": "Fixture officielle sans donnee personnelle.",
            "valid_from": now - timedelta(days=1),
            "valid_until": now + timedelta(days=14),
        }
    ).canonical_bytes()


def _review_binding_bytes(
    *,
    authorization_raw: bytes,
    private_key_hex: str,
    merge_sha: str,
    now: datetime,
) -> bytes:
    authorization = signer.parse_scope_authorization_artifact(authorization_raw)
    binding = ScopeAuthorizationReviewBindingV1.model_validate(
        {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1",
            "repository": REPOSITORY,
            "pull_request": PR_NUMBER,
            "base_ref": "main",
            "base_sha": "d" * 40,
            "head_sha": merge_sha,
            "authorization_artifact_path": canonical_authorization_path(
                AUTHORIZATION_ID
            ),
            "authorization_artifact_sha256": hashlib.sha256(
                authorization_raw
            ).hexdigest(),
            "authorization_artifact_git_blob_sha1": git_blob_sha1(
                authorization_raw
            ),
            "authorization_id": AUTHORIZATION_ID,
            "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
            "review_id": 9002,
            "reviewer_login": REVIEWER,
            "reviewer_permission": "admin",
            "author_login": AUTHOR,
            "submitted_at": now - timedelta(hours=4),
            "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
            "challenge_digest": expected_challenge_digest(
                repository=REPOSITORY,
                pull_request=PR_NUMBER,
                base_ref="main",
                base_sha="d" * 40,
                head_sha=merge_sha,
                author=AUTHOR,
                reviewer=REVIEWER,
            ),
            "verified_at": now - timedelta(hours=3),
            "verifier_version": "nexus-review-binding/1",
            "expires_at": now + timedelta(days=7),
        }
    )
    assert binding.authorization_id == authorization.authorization_id
    return sign_review_binding(
        binding,
        private_key_hex=private_key_hex,
        key_id=REVIEW_KEY_ID,
    ).canonical_bytes()


def _review_trust_anchor(private_key_hex: str) -> bytes:
    anchor = ReviewBindingTrustAnchor.model_validate(
        {
            "protocol_version": "NEXUS-REVIEW-BINDING-V1",
            "keys": [
                {
                    "key_id": REVIEW_KEY_ID,
                    "algorithm": "ed25519",
                    "public_key": review_binding_public_key_hex(private_key_hex),
                    "environment": "production",
                }
            ],
        }
    )
    return _canonical_json(anchor.model_dump(mode="json"))


def _profile_material() -> tuple[dict[str, Any], str, bytes, str]:
    source = {
        "profile_version": "v1",
        "enabled": True,
        "scope": {
            "tenant": "libre_terminale",
            "collection": "rag_nexus_nsi_terminale_specialite",
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "nsi",
            "candidat": "libre",
            "audience": ["libre", "tous"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "BOEN_special_8_2019-07-25",
        },
        "title": "Profil fixture NSI terminale",
        "owner": "atomic-docker-v2-rehearsal",
        "expected_topics": ["notion"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 1,
        "max_documents_per_run": 1,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.7,
    }
    fingerprint = collection_profile_fingerprint(CollectionProfile.model_validate(source))
    manifest_raw = f'''manifest_version: "1"
provenance: "atomic-docker-v2-rehearsal"
generated_at: "2026-08-25T12:00:00+00:00"
profiles:
  - collection: rag_nexus_nsi_terminale_specialite
    profile_version: v1
    fingerprint: {fingerprint}
    approved_by: abenrhouma
    approved_at: "2026-08-25T12:00:00+00:00"
'''.encode()
    digest = validate_production_profile_manifest(
        manifest_raw,
        profile_fingerprints={
            ("rag_nexus_nsi_terminale_specialite", "v1"): fingerprint
        },
        source="profiles-manifest.yml",
    ).manifest_fingerprint
    return source, fingerprint, manifest_raw, digest


def build_release_material_fixture(
    *,
    review_binding_private_key_hex: str,
    merge_sha: str,
    merge_tree_sha: str,
    now: datetime,
) -> ReleaseMaterialFixture:
    """Construit le matériau V2 exact avec une clé de revue fournie en mémoire."""
    profile_source, profile_fingerprint, profile_manifest_raw, profile_digest = (
        _profile_material()
    )
    authorization_raw = _authorization_bytes(
        profile_manifest_digest=profile_digest,
        profile_fingerprint=profile_fingerprint,
        now=now,
    )
    authorization = signer.parse_scope_authorization_artifact(authorization_raw)
    binding_raw = _review_binding_bytes(
        authorization_raw=authorization_raw,
        private_key_hex=review_binding_private_key_hex,
        merge_sha=merge_sha,
        now=now,
    )
    member = AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": authorization.authorization_id,
            "authorization_digest": hashlib.sha256(authorization_raw).hexdigest(),
            "review_binding_digest": hashlib.sha256(binding_raw).hexdigest(),
            "scope": authorization.scope,
            "scope_digest": scope_digest(authorization.scope),
            "allowed_content_sha256": authorization.allowed_content_sha256,
            "allowed_content_count": 1,
            "allowed_content_set_sha256": content_set_digest(
                authorization.allowed_content_sha256
            ),
            "valid_from": authorization.valid_from,
            "valid_until": authorization.valid_until,
        }
    )
    profile = VerifiedProfileFactV1(
        profile_id=authorization.profile_id,
        profile_version=authorization.profile_version,
        profile_fingerprint=authorization.profile_fingerprint,
        scope=authorization.scope,
    )
    placement = ReleaseScopePlacementV1.build(
        placements=(
            ReleaseScopePlacementEntryV1(
                content_sha256=CONTENT_SHA256,
                profile_id=authorization.profile_id,
                profile_version=authorization.profile_version,
                profile_fingerprint=authorization.profile_fingerprint,
                scope=authorization.scope,
            ),
        ),
        profile_manifest_digest=profile_digest,
    )
    sealed_manifest_raw = b"atomic-docker-v2-rehearsal-sealed-manifest\n"
    authorization_set = AuthorizationSetV1.build(
        members=(member,),
        corpus_manifest_sha256=hashlib.sha256(sealed_manifest_raw).hexdigest(),
        profile_manifest_digest=profile_digest,
        release_scope_placement_digest=placement.digest(),
        authority_required_content_sha256=(CONTENT_SHA256,),
    )
    review_anchor_raw = _review_trust_anchor(review_binding_private_key_hex)
    revocations_raw = _canonical_json(
        {
            "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
            "revoked_authorization_ids": [],
        }
    )
    trusted_reviewers_raw = _canonical_json(
        {"repository": REPOSITORY, "reviewers": [REVIEWER]}
    )
    catalog_raw = b"atomic-docker-v2-rehearsal-catalog\n"
    evidence_files = {
        "catalog": catalog_raw,
        "routing": b"routing-v2\n",
        "rights": b"rights-v2\n",
        "pii": b"pii-v2\n",
        "golden": b"golden-v2\n",
        "currentness_verification": b"currentness-v2\n",
        "authorization_set": authorization_set.canonical_bytes(),
        "authority_revocations": revocations_raw,
        "review_binding_trust_anchor": review_anchor_raw,
        "release_scope_placement": placement.canonical_bytes(),
        "trusted_reviewers": trusted_reviewers_raw,
    }
    input_digests = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in evidence_files.items()
    }
    release_scope_git_paths = {
        "profile_proposal_matrix_path": "governance/profile-matrix.json",
        "accepted_placements_path": "governance/placements.json",
        "release_registry_path": "governance/release-registry.json",
        "expected_contents_path": "governance/expected-contents.txt",
        "verified_profiles_path": "governance/verified-profiles.json",
        "profile_manifest_path": "governance/profile-manifest.yml",
    }
    profile_source_path = "profiles/nsi.yml"
    scope_document = authorization.scope.model_dump(mode="json")
    release_scope_source_blobs = {
        release_scope_git_paths["profile_proposal_matrix_path"]: _canonical_json(
            [
                {
                    "partition_id": "P01",
                    "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
                    "content_count": 1,
                    "content_sha256": [CONTENT_SHA256],
                    "profile_decision_required": False,
                    "evidence_sources": [profile_source_path],
                    "dimensions": {
                        name: {
                            "value": value,
                            "grounded": True,
                            "source_of_truth": profile_source_path,
                        }
                        for name, value in scope_document.items()
                    },
                }
            ]
        ),
        release_scope_git_paths["accepted_placements_path"]: _canonical_json(
            [
                {
                    "content_sha256": CONTENT_SHA256,
                    "release_id": "atomic-docker-v2-rehearsal",
                    "collection": authorization.profile_id,
                    "profile_version": authorization.profile_version,
                }
            ]
        ),
        release_scope_git_paths["release_registry_path"]: _canonical_json(
            {
                "registry_version": "1",
                "school_year": authorization.scope.school_year,
                "releases": [
                    {
                        "release_id": "atomic-docker-v2-rehearsal",
                        "collections": [authorization.profile_id],
                    }
                ],
            }
        ),
        release_scope_git_paths["expected_contents_path"]: (
            CONTENT_SHA256 + "\n"
        ).encode(),
        release_scope_git_paths["verified_profiles_path"]: _canonical_json(
            {
                "profile_manifest_digest": profile_digest,
                "profiles": [
                    {**profile.model_dump(mode="json"), "source_path": profile_source_path}
                ],
            }
        ),
        release_scope_git_paths["profile_manifest_path"]: profile_manifest_raw,
        profile_source_path: _canonical_json(profile_source),
    }
    source_digests = {
        path: hashlib.sha256(raw).hexdigest()
        for path, raw in release_scope_source_blobs.items()
    }
    safety = {
        "INGEST_WITHOUT_RIGHTS_CLEARANCE": 0,
        "INGEST_WITHOUT_PII_CLEARANCE": 0,
        "INGEST_WITHOUT_CURRENTNESS_CLEARANCE": 0,
        "INGEST_WITH_UNSUPPORTED_FORMAT": 0,
        "INGEST_WITHOUT_PROVENANCE": 0,
        "INGEST_WITHOUT_CONTENT_SHA": 0,
        "INGEST_WITHOUT_AUTHORITY": 0,
        "INGEST_WITH_SELF_DECLARED_AUTHORITY": 0,
        "INGEST_WITHOUT_ATTRIBUTION_METADATA": 0,
    }
    coverage = H2CoverageEvidenceV2(
        protocol_version="NEXUS-H2-COVERAGE-EVIDENCE-V2",
        environment="production",
        report_id="atomic-docker-v2-rehearsal",
        generated_at=now - timedelta(hours=1),
        git_commit=merge_sha,
        producer_version="atomic-docker-v2-rehearsal/1",
        corpus_manifest_sha256=authorization_set.corpus_manifest_sha256,
        profile_manifest_digest=profile_digest,
        authorization_set_digest=authorization_set.digest(),
        authorization_count=1,
        authorization_set_verified_at=now - timedelta(hours=2),
        earliest_review_submitted_at=now - timedelta(hours=4),
        earliest_review_binding_verified_at=now - timedelta(hours=3),
        earliest_review_binding_expires_at=now + timedelta(days=7),
        authorizations_effective_valid_until=(
            authorization_set.authorizations_effective_valid_until
        ),
        release_scope_source_tree_sha=merge_tree_sha,
        release_scope_placement_digest=placement.digest(),
        release_scope_source_blob_digests=source_digests,
        input_file_digests=input_digests,
        corpus_total_expected=1,
        corpus_total_actual=1,
        corpus_match=True,
        sum_equals_total=True,
        zero_overlap=True,
        zero_gap=True,
        coverage_complete=True,
        rights_gate_status="PASS",
        pii_gate_status="PASS",
        golden_validation_pass=True,
        h2_coverage_gate_pass=True,
        authority_review_bindings_verified=True,
        authority_revocations_checked=True,
        authority_required_count=1,
        authority_covered_count=1,
        authority_required_set_sha256=(
            authorization_set.authority_required_set_sha256
        ),
        authorization_overlap_count=0,
        authorization_gap_count=0,
        authorization_extra_count=0,
        safety_invariants=safety,
    )
    h2_bundle = H2EvidenceBundleV2(
        protocol_version="NEXUS-H2-EVIDENCE-V2",
        repository=REPOSITORY,
        pull_request_number=PR_NUMBER,
        pr_head_sha=merge_sha,
        pr_head_tree_sha=merge_tree_sha,
        merge_sha=merge_sha,
        merge_tree_sha=merge_tree_sha,
        campaign_id="atomic-docker-v2-rehearsal",
        campaign_digest="1" * 64,
        source_oci_digest="sha256:" + "2" * 64,
        source_archive_sha256="3" * 64,
        source_tree_digest="4" * 64,
        corpus_manifest_sha256=authorization_set.corpus_manifest_sha256,
        catalog_sha256=hashlib.sha256(catalog_raw).hexdigest(),
        review_view_sha256="5" * 64,
        profile_manifest_digest=profile_digest,
        authorization_set_digest=authorization_set.digest(),
        authorization_count=1,
        authority_required_count=1,
        authority_required_set_sha256=(
            authorization_set.authority_required_set_sha256
        ),
        release_scope_source_tree_sha=merge_tree_sha,
        release_scope_placement_digest=placement.digest(),
        release_scope_source_blob_digests=source_digests,
        revocation_registry_sha256=hashlib.sha256(revocations_raw).hexdigest(),
        review_binding_trust_anchor_sha256=hashlib.sha256(
            review_anchor_raw
        ).hexdigest(),
        trusted_reviewers_sha256=hashlib.sha256(
            trusted_reviewers_raw
        ).hexdigest(),
        input_file_digests=input_digests,
        authorization_set_verified_at=coverage.authorization_set_verified_at,
        earliest_review_submitted_at=coverage.earliest_review_submitted_at,
        earliest_review_binding_verified_at=(
            coverage.earliest_review_binding_verified_at
        ),
        earliest_review_binding_expires_at=coverage.earliest_review_binding_expires_at,
        authorizations_effective_valid_from=(
            authorization_set.authorizations_effective_valid_from
        ),
        authorizations_effective_valid_until=(
            authorization_set.authorizations_effective_valid_until
        ),
        h2_coverage_generated_at=coverage.generated_at,
        h2_coverage_evidence_sha256=hashlib.sha256(
            coverage.canonical_bytes()
        ).hexdigest(),
        h2_coverage_gate_pass=True,
        authority_revocations_checked=True,
        authority_review_bindings_verified=True,
        coverage_complete=True,
        authority_covered_count=1,
        authorization_overlap_count=0,
        authorization_gap_count=0,
        authorization_extra_count=0,
        environment="production",
        workflow_path=".github/workflows/_produce-h2-evidence.yml",
        run_id="7000",
        run_attempt=1,
    )
    promotion = PromotionEvidenceV2.model_validate(
        PromotionEvidenceV2.fields_from_h2_bundle(
            h2_bundle,
            image_provenance_run_id=PROVENANCE_RUN_ID,
            image_provenance_run_attempt=PROVENANCE_RUN_ATTEMPT,
            promotion_workflow_path=PROMOTION_WORKFLOW_PATH,
            promotion_run_id=PROMOTION_RUN_ID,
            promotion_run_attempt=PROMOTION_RUN_ATTEMPT,
            promotion_workflow_ref=WORKFLOW_REF,
        )
    )
    material = signer.V2ReleaseMaterial(
        authorization_set_raw=authorization_set.canonical_bytes(),
        release_files={
            authorization.canonical_path(): authorization_raw,
            canonical_review_binding_path(authorization.authorization_id): binding_raw,
        },
        review_binding_trust_anchor_raw=review_anchor_raw,
        trusted_reviewers_raw=trusted_reviewers_raw,
        revocation_registry_raw=revocations_raw,
        release_scope_placement_raw=placement.canonical_bytes(),
        release_scope_source_blobs=release_scope_source_blobs,
        verified_profiles=(profile,),
        profile_manifest_raw=profile_manifest_raw,
        authority_required_content_sha256=(CONTENT_SHA256,),
        h2_coverage_raw=coverage.canonical_bytes(),
        h2_evidence_bundle_raw=h2_bundle.canonical_bytes(),
        promotion_evidence_raw=promotion.canonical_bytes(),
        evidence_files=evidence_files,
        sealed_manifest_raw=sealed_manifest_raw,
        now=now,
        merge_sha=merge_sha,
        merge_tree_sha=merge_tree_sha,
        release_scope_git_paths=release_scope_git_paths,
    )
    signer.verify_v2_release_material(material)
    return ReleaseMaterialFixture(
        material=material,
        review_binding_public_anchor_sha256=hashlib.sha256(
            review_anchor_raw
        ).hexdigest(),
    )


def sign_readiness_fixture(
    *,
    material: signer.V2ReleaseMaterial,
    readiness_private_key_hex: str,
    compose_digest: str,
    application_image_digests: Mapping[str, str],
    upstream_image_digests: Mapping[str, str],
) -> SignedReadinessFixture:
    verified = signer.verify_v2_release_material(material)
    promotion = verified.promotion
    manifest = signer.assemble_and_sign_v2(
        material,
        repository=REPOSITORY,
        pr_number=promotion.pull_request_number,
        pr_head_sha=promotion.pr_head_sha,
        pr_head_tree_sha=promotion.pr_head_tree_sha,
        application_image_digests=application_image_digests,
        upstream_image_digests=upstream_image_digests,
        compose_digest=compose_digest,
        key_id=READINESS_KEY_ID,
        workflow_ref=promotion.promotion_workflow_ref,
    )
    signed = signer.sign_production_readiness_manifest_v2(
        manifest,
        private_key_hex=readiness_private_key_hex,
        key_id=READINESS_KEY_ID,
    ).canonical_bytes()
    anchor = ProductionReadinessTrustAnchor(
        protocol_version="NEXUS-PRODUCTION-READINESS-V1",
        keys=(
            ProductionReadinessTrustAnchorKey(
                key_id=READINESS_KEY_ID,
                algorithm="ed25519",
                public_key=public_readiness_key_hex(readiness_private_key_hex),
                environment="production",
            ),
        ),
    )
    anchor_raw = _canonical_json(anchor.model_dump(mode="json"))
    return SignedReadinessFixture(
        signed_manifest_raw=signed,
        trust_anchor_raw=anchor_raw,
        public_anchor_sha256=hashlib.sha256(anchor_raw).hexdigest(),
    )


def compose_source_bytes(*, image_ref: str) -> dict[str, bytes]:
    """Trois fichiers Compose minimaux, sans port, pour le vrai daemon local."""
    base = f"""services:
  ingestor:
    image: {image_ref}
    command: [\"sh\", \"-c\", \"while true; do sleep 3600; done\"]
    healthcheck:
      test: [\"CMD\", \"sh\", \"-c\", \"true\"]
      interval: 1s
      timeout: 1s
      retries: 10
  fixture-upstream:
    image: {image_ref}
    command: [\"sh\", \"-c\", \"while true; do sleep 3600; done\"]
    healthcheck:
      test: [\"CMD\", \"sh\", \"-c\", \"true\"]
      interval: 1s
      timeout: 1s
      retries: 10
""".encode()
    worker = f"""services:
  multilevel-worker-a-production:
    image: {image_ref}
    command: [\"sh\", \"-c\", \"while true; do sleep 3600; done\"]
    volumes:
      - ${{PRODUCTION_AUTHORIZATION_SET_HOST_FILE:?required}}:/app/production/authorization-set.json:ro
      - ${{PRODUCTION_V2_RELEASE_MATERIAL_HOST_DIR:?required}}:/app/production/v2-material:ro
    healthcheck:
      test: [\"CMD-SHELL\", \"test -r /app/production/authorization-set.json && test -d /app/production/v2-material\"]
      interval: 1s
      timeout: 1s
      retries: 10
  multilevel-worker-b-production:
    image: {image_ref}
    command: [\"sh\", \"-c\", \"while true; do sleep 3600; done\"]
    volumes:
      - ${{PRODUCTION_AUTHORIZATION_SET_HOST_FILE:?required}}:/app/production/authorization-set.json:ro
      - ${{PRODUCTION_V2_RELEASE_MATERIAL_HOST_DIR:?required}}:/app/production/v2-material:ro
    healthcheck:
      test: [\"CMD-SHELL\", \"test -r /app/production/authorization-set.json && test -d /app/production/v2-material\"]
      interval: 1s
      timeout: 1s
      retries: 10
""".encode()
    return {
        "docker-compose.v2.yml": base,
        "docker-compose.production-workers.yml": worker,
        "docker-compose.production-release.yml": b"services: {}\n",
    }
