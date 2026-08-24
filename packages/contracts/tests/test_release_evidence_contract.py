from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from nexus_contracts import H2EvidenceBundleV2 as ExportedH2EvidenceBundleV2
from nexus_contracts import PromotionEvidenceV2 as ExportedPromotionEvidenceV2

from nexus_contracts.release_evidence import (
    EXACT_HEAD_RECEIPT_MAX_AGE,
    H2_EVIDENCE_V2_PROTOCOL_VERSION,
    PROMOTION_EVIDENCE_V2_PROTOCOL_VERSION,
    H2EvidenceBundleV2,
    PromotionEvidenceV2,
    ReleaseEvidenceError,
    parse_h2_evidence_bundle_v2,
    parse_promotion_evidence_v2,
    verify_h2_evidence_bundle_v2_freshness,
    verify_promotion_evidence_v2,
)


NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)


def test_v2_release_evidence_is_exported_by_the_shared_contract() -> None:
    assert ExportedH2EvidenceBundleV2 is H2EvidenceBundleV2
    assert ExportedPromotionEvidenceV2 is PromotionEvidenceV2


def _bundle(**overrides: object) -> H2EvidenceBundleV2:
    fields: dict[str, object] = {
        "protocol_version": H2_EVIDENCE_V2_PROTOCOL_VERSION,
        "repository": "cyranoaladin/RAG",
        "pull_request_number": 127,
        "pr_head_sha": "1" * 40,
        "pr_head_tree_sha": "2" * 40,
        "merge_sha": "3" * 40,
        "merge_tree_sha": "2" * 40,
        "campaign_id": "release-2026-08",
        "campaign_digest": "4" * 64,
        "source_oci_digest": "sha256:" + "5" * 64,
        "source_archive_sha256": "6" * 64,
        "source_tree_digest": "7" * 64,
        "corpus_manifest_sha256": "8" * 64,
        "catalog_sha256": "9" * 64,
        "review_view_sha256": "a" * 64,
        "profile_manifest_digest": "b" * 64,
        "authorization_set_digest": "c" * 64,
        "authorization_count": 2,
        "authority_required_count": 2,
        "authority_required_set_sha256": "d" * 64,
        "release_scope_source_tree_sha": "2" * 40,
        "release_scope_placement_digest": "f" * 64,
        "release_scope_source_blob_digests": {"profiles.yml": "0" * 64},
        "revocation_registry_sha256": "1" * 64,
        "review_binding_trust_anchor_sha256": "2" * 64,
        "trusted_reviewers_sha256": "3" * 64,
        "input_file_digests": {
            "authorization_set": "c" * 64,
            "authority_revocations": "1" * 64,
            "catalog": "9" * 64,
            "currentness_verification": "4" * 64,
            "golden": "5" * 64,
            "pii": "6" * 64,
            "release_scope_placement": "f" * 64,
            "review_binding_trust_anchor": "2" * 64,
            "rights": "7" * 64,
            "routing": "8" * 64,
            "trusted_reviewers": "3" * 64,
        },
        "authorization_set_verified_at": NOW - timedelta(hours=1),
        "earliest_review_submitted_at": NOW - timedelta(days=7),
        "earliest_review_binding_verified_at": NOW - timedelta(days=6),
        "earliest_review_binding_expires_at": NOW + timedelta(days=1),
        "authorizations_effective_valid_from": NOW - timedelta(days=8),
        "authorizations_effective_valid_until": NOW + timedelta(days=2),
        "h2_coverage_generated_at": NOW - timedelta(minutes=30),
        "h2_coverage_evidence_sha256": "a" * 64,
        "h2_coverage_gate_pass": True,
        "authority_revocations_checked": True,
        "authority_review_bindings_verified": True,
        "coverage_complete": True,
        "authority_covered_count": 2,
        "authorization_overlap_count": 0,
        "authorization_gap_count": 0,
        "authorization_extra_count": 0,
        "environment": "production",
        "workflow_path": ".github/workflows/_produce-h2-evidence.yml",
        "run_id": "123",
        "run_attempt": 1,
    }
    fields.update(overrides)
    return H2EvidenceBundleV2.model_validate(fields)


def _promotion(bundle: H2EvidenceBundleV2 | None = None, **overrides: object) -> PromotionEvidenceV2:
    bundle = bundle or _bundle()
    fields = PromotionEvidenceV2.fields_from_h2_bundle(
        bundle,
        image_provenance_run_id=456,
        image_provenance_run_attempt=2,
        promotion_workflow_path=".github/workflows/promote.yml",
        promotion_run_id=789,
        promotion_run_attempt=1,
        promotion_workflow_ref="refs/heads/main",
    )
    fields.update(overrides)
    return PromotionEvidenceV2.model_validate(fields)


def test_h2_v2_round_trip_is_canonical_and_strict() -> None:
    bundle = _bundle()
    assert parse_h2_evidence_bundle_v2(bundle.canonical_bytes()) == bundle
    document = json.loads(bundle.canonical_bytes())
    document["protocol_version"] = "NEXUS-H2-EVIDENCE-V1"
    with pytest.raises(ReleaseEvidenceError, match="protocol_version"):
        parse_h2_evidence_bundle_v2(
            (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
        )
    with pytest.raises(ReleaseEvidenceError, match="canonical"):
        parse_h2_evidence_bundle_v2(json.dumps(bundle.canonical_document()).encode())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authorization_count", 0),
        ("authority_covered_count", 1),
        ("authorization_overlap_count", 1),
        ("authorization_gap_count", 1),
        ("authorization_extra_count", 1),
        ("h2_coverage_gate_pass", False),
        ("authority_revocations_checked", False),
        ("authority_review_bindings_verified", False),
        ("coverage_complete", False),
    ],
)
def test_h2_v2_refuses_incomplete_or_nonpassing_release(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _bundle(**{field: value})


def test_h2_v2_input_digests_are_exact_and_cross_bound() -> None:
    missing = dict(_bundle().input_file_digests)
    del missing["authorization_set"]
    with pytest.raises(ValidationError, match="unexpected key set"):
        _bundle(input_file_digests=missing)
    extra = dict(_bundle().input_file_digests, authority="f" * 64)
    with pytest.raises(ValidationError, match="unexpected key set"):
        _bundle(input_file_digests=extra)
    wrong = dict(_bundle().input_file_digests, authorization_set="e" * 64)
    with pytest.raises(ValidationError, match="authorization_set"):
        _bundle(input_file_digests=wrong)


def test_h2_v2_refuses_placement_provenance_from_a_foreign_tree() -> None:
    with pytest.raises(ValidationError, match="release_scope_source_tree_sha"):
        _bundle(release_scope_source_tree_sha="e" * 40)


@pytest.mark.parametrize(
    ("field", "mapping_key"),
    [
        ("input_file_digests", "currentness_verification"),
        ("release_scope_source_blob_digests", "profiles.yml"),
    ],
)
def test_h2_v2_refuses_non_sha256_mapping_values(
    field: str, mapping_key: str
) -> None:
    mapping = dict(getattr(_bundle(), field))
    mapping[mapping_key] = "not-a-sha256"
    with pytest.raises(ValidationError, match=field):
        _bundle(**{field: mapping})


@pytest.mark.parametrize(
    ("field", "mapping_key"),
    [
        ("input_file_digests", "currentness_verification"),
        ("release_scope_source_blob_digests", "profiles.yml"),
    ],
)
def test_h2_v2_parser_refuses_non_sha256_mapping_values(
    field: str, mapping_key: str
) -> None:
    document = _bundle().canonical_document()
    document[field][mapping_key] = "not-a-sha256"
    raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(ReleaseEvidenceError, match=field):
        parse_h2_evidence_bundle_v2(raw)


def test_human_review_freshness_checks_both_dates_at_exact_boundary() -> None:
    boundary = NOW - EXACT_HEAD_RECEIPT_MAX_AGE
    verify_h2_evidence_bundle_v2_freshness(
        _bundle(
            earliest_review_submitted_at=boundary,
            earliest_review_binding_verified_at=boundary,
        ),
        now=NOW,
    )
    for field in (
        "earliest_review_submitted_at",
        "earliest_review_binding_verified_at",
    ):
        stale = boundary - timedelta(microseconds=1)
        overrides = {
            "earliest_review_submitted_at": stale,
            "earliest_review_binding_verified_at": (
                stale
                if field == "earliest_review_binding_verified_at"
                else boundary
            ),
        }
        with pytest.raises(ReleaseEvidenceError, match=field):
            verify_h2_evidence_bundle_v2_freshness(
                _bundle(**overrides),
                now=NOW,
            )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {
                "earliest_review_submitted_at": NOW + timedelta(seconds=1),
                "earliest_review_binding_verified_at": NOW + timedelta(seconds=1),
                "authorization_set_verified_at": NOW + timedelta(seconds=1),
                "h2_coverage_generated_at": NOW + timedelta(seconds=1),
                "earliest_review_binding_expires_at": NOW + timedelta(days=1),
            },
            "future",
        ),
        (
            {
                "earliest_review_binding_verified_at": NOW + timedelta(seconds=1),
                "authorization_set_verified_at": NOW + timedelta(seconds=1),
                "h2_coverage_generated_at": NOW + timedelta(seconds=1),
            },
            "future",
        ),
        ({"earliest_review_binding_expires_at": NOW}, "expired"),
        ({"authorizations_effective_valid_from": NOW + timedelta(seconds=1)}, "not yet valid"),
        ({"authorizations_effective_valid_until": NOW}, "expired"),
        (
            {
                "authorization_set_verified_at": NOW + timedelta(seconds=1),
                "h2_coverage_generated_at": NOW + timedelta(seconds=1),
            },
            "authorization_set_verified_at.*future",
        ),
        (
            {"h2_coverage_generated_at": NOW + timedelta(seconds=1)},
            "h2_coverage_generated_at.*future",
        ),
    ],
)
def test_h2_v2_freshness_is_half_open(
    overrides: dict[str, datetime], message: str
) -> None:
    bundle = _bundle(**overrides)
    with pytest.raises(ReleaseEvidenceError, match=message):
        verify_h2_evidence_bundle_v2_freshness(bundle, now=NOW)


def test_reverification_does_not_refresh_stale_human_review() -> None:
    stale = NOW - timedelta(days=8)
    bundle = _bundle(
        authorization_set_verified_at=NOW,
        h2_coverage_generated_at=NOW,
        earliest_review_submitted_at=stale,
        earliest_review_binding_verified_at=stale,
    )
    with pytest.raises(ReleaseEvidenceError, match="older than 7 days"):
        verify_h2_evidence_bundle_v2_freshness(bundle, now=NOW)


def test_promotion_v2_binds_the_exact_h2_bundle_and_release() -> None:
    bundle = _bundle()
    promotion = _promotion(bundle)
    verify_promotion_evidence_v2(promotion, h2_bundle=bundle)
    assert parse_promotion_evidence_v2(promotion.canonical_bytes()) == promotion
    assert promotion.protocol_version == PROMOTION_EVIDENCE_V2_PROTOCOL_VERSION


@pytest.mark.parametrize(
    "field",
    [
        "authorization_set_digest",
        "campaign_digest",
        "h2_evidence_bundle_digest",
        "h2_coverage_evidence_sha256",
        "authority_required_set_sha256",
        "corpus_manifest_sha256",
        "release_scope_placement_digest",
    ],
)
def test_promotion_v2_refuses_substitution(field: str) -> None:
    bundle = _bundle()
    promotion = _promotion(bundle, **{field: "e" * 64})
    with pytest.raises(ReleaseEvidenceError, match=field):
        verify_promotion_evidence_v2(promotion, h2_bundle=bundle)


def test_v2_promotion_parser_never_accepts_v1() -> None:
    document = _promotion().canonical_document()
    document["protocol_version"] = "NEXUS-PROMOTION-EVIDENCE-V1"
    raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(ReleaseEvidenceError, match="protocol_version"):
        parse_promotion_evidence_v2(raw)
