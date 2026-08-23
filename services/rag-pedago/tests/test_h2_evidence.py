"""Tests de ``NEXUS-H2-EVIDENCE-V1`` et de son résolveur.

Chaque test construit une preuve réelle et lit son comportement. Aucune
assertion ne porte sur le texte du code.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nexus_contracts.authorization_set import (
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.h2_coverage_evidence import (
    H2_COVERAGE_EVIDENCE_V2_PROTOCOL_VERSION,
    H2CoverageEvidenceV2,
)
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.release_evidence import (
    H2_EVIDENCE_V2_PROTOCOL_VERSION,
    ReleaseEvidenceError,
    parse_h2_evidence_bundle_v2,
    verify_h2_evidence_bundle_v2_freshness,
)

from rag_pedago.governance.corpus_campaign import (
    CORPUS_CAMPAIGN_V2_PROTOCOL_VERSION,
    CorpusCampaignV2,
)
from rag_pedago.governance.h2_evidence import (
    H2_EVIDENCE_PROTOCOL,
    EvidenceCandidate,
    H2EvidenceBundle,
    H2EvidenceError,
    build_evidence_index,
    build_h2_evidence_bundle_v2,
    cross_check_review_view,
    resolve_evidence_artifact,
    verify_gate_outcome,
    verify_promotion_inputs,
    verify_receipt_freshness,
)

MERGE_SHA = "a" * 40
TREE_SHA = "b" * 40
HEAD_SHA = "c" * 40
WORKFLOW = ".github/workflows/_produce-h2-evidence.yml"
NOW = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)
LEGACY_V1_FIXTURE = (
    Path(__file__).parent / "fixtures/legacy_v1/h2_evidence_bundle_v1.json"
)
LEGACY_CAMPAIGN_V1_FIXTURE = (
    Path(__file__).parent / "fixtures/legacy_v1/corpus_campaign_v1.json"
)
LEGACY_V1_FIXTURE_SHA256 = (
    "8bc7e2a903945f4f63d800fe1a4b2d68d7d518871be7eacec17c04c90f5c8cba"
)


def _v2_scope() -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_terminale",
            "collection": "rag_nexus_philo_terminale_tc",
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "philosophie",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "BOEN_special_8_2019-07-25",
        }
    )


def _authorization_set() -> AuthorizationSetV1:
    scope = _v2_scope()
    content = "0" * 64
    member = AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": "release-philo",
            "authorization_digest": "1" * 64,
            "review_binding_digest": "2" * 64,
            "scope": scope,
            "scope_digest": scope_digest(scope),
            "allowed_content_sha256": [content],
            "allowed_content_count": 1,
            "allowed_content_set_sha256": content_set_digest([content]),
            "valid_from": NOW - timedelta(days=8),
            "valid_until": NOW + timedelta(days=2),
        }
    )
    return AuthorizationSetV1.build(
        members=[member],
        corpus_manifest_sha256="5" * 64,
        profile_manifest_digest="b" * 64,
        release_scope_placement_digest="c" * 64,
        authority_required_content_sha256=[content],
    )


def _campaign_v2(authorization_set: AuthorizationSetV1) -> CorpusCampaignV2:
    return CorpusCampaignV2.model_validate(
        {
            "protocol_version": CORPUS_CAMPAIGN_V2_PROTOCOL_VERSION,
            "campaign_id": "release-2026-08",
            "source_kind": "ghcr-oci",
            "source_registry": "ghcr.io",
            "source_repository": "cyranoaladin/rag-corpus",
            "source_oci_digest": "sha256:" + "3" * 64,
            "source_archive_sha256": "4" * 64,
            "source_tree_digest": "6" * 64,
            "archive_format": "tar.zst",
            "source_root": "corpus",
            "expected_manifest_sha256": authorization_set.corpus_manifest_sha256,
            "expected_catalog_digest": "7" * 64,
            "authorization_set_digest": authorization_set.digest(),
            "authority_required_count": authorization_set.authority_required_count,
            "authority_required_set_sha256": (
                authorization_set.authority_required_set_sha256
            ),
            "profile_manifest_digest": authorization_set.profile_manifest_digest,
            "release_scope_placement_digest": (
                authorization_set.release_scope_placement_digest
            ),
            "compiler_version": "corpus-catalog-compiler/2",
            "routing_config_digest": "8" * 64,
            "rights_config_digest": "9" * 64,
            "pii_config_digest": "a" * 64,
            "golden_spec_digest": "d" * 64,
            "environment": "production",
            "retention_days": 90,
        }
    )


def _h2_coverage_v2(
    authorization_set: AuthorizationSetV1, **overrides: object
) -> H2CoverageEvidenceV2:
    input_digests = {
        "authorization_set": authorization_set.digest(),
        "authority_revocations": "e" * 64,
        "catalog": "7" * 64,
        "currentness_verification": "f" * 64,
        "golden": "d" * 64,
        "pii": "a" * 64,
        "release_scope_placement": authorization_set.release_scope_placement_digest,
        "review_binding_trust_anchor": "1" * 64,
        "rights": "9" * 64,
        "routing": "8" * 64,
        "trusted_reviewers": "2" * 64,
    }
    fields: dict[str, object] = {
        "protocol_version": H2_COVERAGE_EVIDENCE_V2_PROTOCOL_VERSION,
        "environment": "production",
        "report_id": "release-2026-08",
        "generated_at": NOW,
        "git_commit": "3" * 40,
        "producer_version": "rag-pedago/2",
        "corpus_manifest_sha256": authorization_set.corpus_manifest_sha256,
        "profile_manifest_digest": authorization_set.profile_manifest_digest,
        "authorization_set_digest": authorization_set.digest(),
        "authorization_count": authorization_set.authorization_count,
        "authorization_set_verified_at": NOW - timedelta(hours=1),
        "earliest_review_submitted_at": NOW - timedelta(days=7),
        "earliest_review_binding_verified_at": NOW - timedelta(days=6),
        "earliest_review_binding_expires_at": NOW + timedelta(days=1),
        "authorizations_effective_valid_until": (
            authorization_set.authorizations_effective_valid_until
        ),
        "release_scope_source_tree_sha": "2" * 40,
        "release_scope_placement_digest": (
            authorization_set.release_scope_placement_digest
        ),
        "release_scope_source_blob_digests": {"profiles.yml": "5" * 64},
        "input_file_digests": input_digests,
        "corpus_total_expected": 1,
        "corpus_total_actual": 1,
        "corpus_match": True,
        "sum_equals_total": True,
        "zero_overlap": True,
        "zero_gap": True,
        "coverage_complete": True,
        "rights_gate_status": "PASS",
        "pii_gate_status": "PASS",
        "golden_validation_pass": True,
        "h2_coverage_gate_pass": True,
        "authority_review_bindings_verified": True,
        "authority_revocations_checked": True,
        "authority_required_count": authorization_set.authority_required_count,
        "authority_covered_count": authorization_set.authority_required_count,
        "authority_required_set_sha256": (
            authorization_set.authority_required_set_sha256
        ),
        "authorization_overlap_count": 0,
        "authorization_gap_count": 0,
        "authorization_extra_count": 0,
        "safety_invariants": {
            "INGEST_WITHOUT_RIGHTS_CLEARANCE": 0,
            "INGEST_WITHOUT_PII_CLEARANCE": 0,
            "INGEST_WITHOUT_CURRENTNESS_CLEARANCE": 0,
            "INGEST_WITH_UNSUPPORTED_FORMAT": 0,
            "INGEST_WITHOUT_PROVENANCE": 0,
            "INGEST_WITHOUT_CONTENT_SHA": 0,
            "INGEST_WITHOUT_AUTHORITY": 0,
            "INGEST_WITH_SELF_DECLARED_AUTHORITY": 0,
            "INGEST_WITHOUT_ATTRIBUTION_METADATA": 0,
        },
    }
    fields.update(overrides)
    return H2CoverageEvidenceV2.model_validate(fields)


def _assemble_v2(**overrides: object):
    authorization_set = _authorization_set()
    campaign = _campaign_v2(authorization_set)
    coverage = _h2_coverage_v2(authorization_set)
    arguments: dict[str, object] = {
        "campaign_raw": campaign.canonical_bytes(),
        "authorization_set_raw": authorization_set.canonical_bytes(),
        "h2_coverage_evidence_raw": coverage.canonical_bytes(),
        "review_view_sha256": "a" * 64,
        "repository": "cyranoaladin/RAG",
        "pull_request_number": 127,
        "pr_head_sha": "1" * 40,
        "pr_head_tree_sha": "2" * 40,
        "merge_sha": coverage.git_commit,
        "merge_tree_sha": "2" * 40,
        "workflow_path": WORKFLOW,
        "run_id": "123",
        "run_attempt": 1,
    }
    arguments.update(overrides)
    return build_h2_evidence_bundle_v2(**arguments)


def make_bundle(**overrides) -> H2EvidenceBundle:
    base = {
        "repository": "cyranoaladin/RAG",
        "pull_request_number": 95,
        "pr_head_sha": HEAD_SHA,
        "pr_head_tree_sha": TREE_SHA,
        "merge_sha": MERGE_SHA,
        "merge_tree_sha": TREE_SHA,
        "campaign_id": "2026-08-corpus-public",
        "campaign_sha256": "1" * 64,
        "source_oci_digest": "sha256:" + "2" * 64,
        "source_archive_sha256": "3" * 64,
        "source_tree_digest": "4" * 64,
        "manifest_sha256": "5" * 64,
        "catalog_sha256": "6" * 64,
        "review_view_sha256": "7" * 64,
        "authorization_sha256": "8" * 64,
        "revocation_registry_sha256": "9" * 64,
        "trust_anchor_sha256": "a" * 64,
        "exact_head_receipt_sha256": "b" * 64,
        "exact_head_receipt_issued_at": "2026-08-08T10:00:00+00:00",
        "routing_config_sha256": "c" * 64,
        "rights_config_sha256": "d" * 64,
        "pii_config_sha256": "e" * 64,
        "golden_config_sha256": "f" * 64,
        "h2_report_sha256": "0" * 64,
        "h2_coverage_gate_pass": True,
        "authority_revocations_checked": True,
        "coverage_complete": True,
        "environment": "production",
        "workflow_path": WORKFLOW,
        "run_id": "17654321",
        "run_attempt": 1,
    }
    base.update(overrides)
    return H2EvidenceBundle(**base)


def make_candidate(**overrides) -> EvidenceCandidate:
    base = {
        "artifact_name": f"h2-evidence-{MERGE_SHA}-2026-08-corpus-public",
        "workflow_path": WORKFLOW,
        "run_id": "17654321",
        "run_attempt": 1,
        "conclusion": "success",
        "head_sha": MERGE_SHA,
        "expired": False,
    }
    base.update(overrides)
    return EvidenceCandidate(**base)


class TestDeterminism:
    def test_legacy_v1_fixture_bytes_are_immutable(self) -> None:
        raw = LEGACY_V1_FIXTURE.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == LEGACY_V1_FIXTURE_SHA256

        document = json.loads(raw.decode("utf-8"))
        assert set(document) == {"protocol", "content"}
        assert document["protocol"] == "NEXUS-H2-EVIDENCE-V1"
        parsed = H2EvidenceBundle.from_content_dict(document["content"])
        assert parsed.to_canonical_json() == raw

    def test_the_content_digest_is_reproducible_from_the_content_alone(self) -> None:
        assert make_bundle().content_sha256 == make_bundle().content_sha256

    def test_the_timestamp_lives_outside_the_digest(self) -> None:
        """Deux lectures d'horloge dans le même run donneraient sinon deux
        digests pour une seule preuve."""
        bundle = make_bundle()
        early = bundle.to_envelope(produced_at="2026-08-10T12:00:00+00:00")
        late = bundle.to_envelope(produced_at="2026-08-10T23:59:59+00:00")
        assert early["content_sha256"] == late["content_sha256"]
        assert early["produced_at"] != late["produced_at"]

    def test_the_run_id_does_belong_to_the_digest(self) -> None:
        """Contrairement à l'horodatage, le ``run_id`` *identifie* la
        preuve : deux runs sont deux preuves distinctes."""
        assert make_bundle().content_sha256 != make_bundle(run_id="99").content_sha256

    def test_the_run_attempt_belongs_to_the_digest(self) -> None:
        assert (
            make_bundle().content_sha256 != make_bundle(run_attempt=2).content_sha256
        )

    def test_the_canonical_json_carries_no_clock_reading(self) -> None:
        raw = make_bundle().to_canonical_json().decode()
        assert "produced_at" not in raw
        payload = json.loads(raw)
        assert payload["protocol"] == H2_EVIDENCE_PROTOCOL


class TestExactHeadEquality:
    def test_a_tree_mismatch_is_refused(self) -> None:
        """Le cœur de la garantie : deux SHA de commit diffèrent toujours,
        mais les arbres doivent coïncider."""
        with pytest.raises(H2EvidenceError, match="not the tree a human approved"):
            make_bundle(merge_tree_sha="d" * 40)

    def test_matching_trees_are_accepted(self) -> None:
        assert make_bundle().merge_tree_sha == make_bundle().pr_head_tree_sha


class TestStrictness:
    def test_an_unknown_field_is_refused_not_ignored(self) -> None:
        payload = make_bundle().to_content_dict()
        payload["extra_evidence"] = "surprise"
        with pytest.raises(H2EvidenceError, match="unknown field"):
            H2EvidenceBundle.from_content_dict(payload)

    def test_a_missing_field_is_refused(self) -> None:
        payload = make_bundle().to_content_dict()
        del payload["revocation_registry_sha256"]
        with pytest.raises(H2EvidenceError, match="missing required field"):
            H2EvidenceBundle.from_content_dict(payload)

    def test_a_round_trip_preserves_the_digest(self) -> None:
        original = make_bundle()
        restored = H2EvidenceBundle.from_content_dict(original.to_content_dict())
        assert restored.content_sha256 == original.content_sha256

    def test_an_envelope_that_lies_about_its_digest_is_refused(self) -> None:
        envelope = make_bundle().to_envelope(produced_at="2026-08-10T12:00:00+00:00")
        envelope["content_sha256"] = "0" * 64
        with pytest.raises(H2EvidenceError, match="does not match the recomputed"):
            H2EvidenceBundle.from_envelope(envelope)

    def test_a_foreign_protocol_is_refused(self) -> None:
        envelope = make_bundle().to_envelope(produced_at="2026-08-10T12:00:00+00:00")
        envelope["protocol"] = "NEXUS-H2-EVIDENCE-V2"
        with pytest.raises(H2EvidenceError, match="expected protocol"):
            H2EvidenceBundle.from_envelope(envelope)

    def test_a_valid_envelope_round_trips(self) -> None:
        envelope = make_bundle().to_envelope(produced_at="2026-08-10T12:00:00+00:00")
        assert H2EvidenceBundle.from_envelope(envelope).merge_sha == MERGE_SHA


class TestDigestShapes:
    def test_an_abbreviated_merge_sha_is_refused(self) -> None:
        with pytest.raises(H2EvidenceError, match="abbreviated SHA is ambiguous"):
            make_bundle(merge_sha="a" * 12)

    def test_an_uppercase_digest_is_refused(self) -> None:
        with pytest.raises(H2EvidenceError, match="manifest_sha256"):
            make_bundle(manifest_sha256="A" * 64)

    def test_a_bare_hex_oci_digest_is_refused(self) -> None:
        """Un digest OCI sans son algorithme n'est pas une référence."""
        with pytest.raises(H2EvidenceError, match="source_oci_digest"):
            make_bundle(source_oci_digest="2" * 64)

    def test_a_repository_without_an_owner_is_refused(self) -> None:
        with pytest.raises(H2EvidenceError, match="repository"):
            make_bundle(repository="RAG")

    def test_a_zero_run_attempt_is_refused(self) -> None:
        with pytest.raises(H2EvidenceError, match="run_attempt"):
            make_bundle(run_attempt=0)


class TestGateOutcome:
    def test_a_failed_gate_cannot_promote(self) -> None:
        with pytest.raises(H2EvidenceError, match="did not pass"):
            verify_gate_outcome(make_bundle(h2_coverage_gate_pass=False))

    def test_assumed_non_revocation_cannot_promote(self) -> None:
        """La différence entre « prouvé contre un registre » et « supposé
        faute de registre » est exactement ce que F2 a rendu visible."""
        with pytest.raises(H2EvidenceError, match="assumed"):
            verify_gate_outcome(make_bundle(authority_revocations_checked=False))

    def test_partial_coverage_cannot_promote(self) -> None:
        with pytest.raises(H2EvidenceError, match="green on a sample"):
            verify_gate_outcome(make_bundle(coverage_complete=False))

    def test_evidence_from_another_environment_cannot_promote(self) -> None:
        with pytest.raises(H2EvidenceError, match="protected environment"):
            verify_gate_outcome(make_bundle(environment="staging"))

    def test_a_complete_pass_is_accepted(self) -> None:
        verify_gate_outcome(make_bundle())


class TestReceiptFreshness:
    def test_a_fresh_receipt_is_accepted(self) -> None:
        verify_receipt_freshness(make_bundle(), now=NOW)

    def test_an_expired_receipt_is_refused(self) -> None:
        stale = make_bundle(exact_head_receipt_issued_at="2026-07-01T10:00:00+00:00")
        with pytest.raises(H2EvidenceError, match="blank cheque"):
            verify_receipt_freshness(stale, now=NOW)

    def test_a_receipt_from_the_future_is_refused(self) -> None:
        ahead = make_bundle(exact_head_receipt_issued_at="2026-09-01T10:00:00+00:00")
        with pytest.raises(H2EvidenceError, match="in the future"):
            verify_receipt_freshness(ahead, now=NOW)

    def test_a_naive_instant_is_refused(self) -> None:
        naive = make_bundle(exact_head_receipt_issued_at="2026-08-08T10:00:00")
        with pytest.raises(H2EvidenceError, match="explicit timezone"):
            verify_receipt_freshness(naive, now=NOW)

    def test_the_boundary_is_exercised_on_both_sides(self) -> None:
        issued = NOW - timedelta(days=7)
        just_valid = make_bundle(
            exact_head_receipt_issued_at=issued.isoformat()
        )
        verify_receipt_freshness(just_valid, now=NOW)
        too_old = make_bundle(
            exact_head_receipt_issued_at=(issued - timedelta(seconds=1)).isoformat()
        )
        with pytest.raises(H2EvidenceError):
            verify_receipt_freshness(too_old, now=NOW)


class TestCrossCheck:
    def _kwargs(self, **overrides):
        base = {
            "review_view_sha256": "7" * 64,
            "manifest_sha256": "5" * 64,
            "catalog_sha256": "6" * 64,
            "source_oci_digest": "sha256:" + "2" * 64,
        }
        base.update(overrides)
        return base

    def test_agreeing_evidence_passes(self) -> None:
        cross_check_review_view(make_bundle(), **self._kwargs())

    def test_a_reviewed_corpus_different_from_the_promoted_one_is_refused(self) -> None:
        """Chaque digest serait valide isolément ; l'ensemble ne prouve
        rien."""
        with pytest.raises(H2EvidenceError, match="not the same object"):
            cross_check_review_view(
                make_bundle(), **self._kwargs(source_oci_digest="sha256:" + "9" * 64)
            )

    def test_a_stale_review_view_is_refused(self) -> None:
        with pytest.raises(H2EvidenceError, match="review_view_sha256"):
            cross_check_review_view(
                make_bundle(), **self._kwargs(review_view_sha256="9" * 64)
            )


class TestResolver:
    def _expected(self, **overrides):
        base = {
            "expected_workflow_path": WORKFLOW,
            "expected_merge_sha": MERGE_SHA,
            "expected_campaign_id": "2026-08-corpus-public",
            "expected_run_id": "17654321",
            "expected_run_attempt": 1,
        }
        base.update(overrides)
        return base

    def test_exactly_one_admissible_candidate_resolves(self) -> None:
        found = resolve_evidence_artifact([make_candidate()], **self._expected())
        assert found.run_id == "17654321"

    def test_no_candidate_is_a_refusal_not_an_empty_result(self) -> None:
        with pytest.raises(H2EvidenceError, match="no admissible evidence"):
            resolve_evidence_artifact([], **self._expected())

    def test_two_admissible_candidates_are_a_refusal(self) -> None:
        """L'ambiguïté est un défaut de gouvernance, pas quelque chose à
        départager en prenant le plus récent."""
        with pytest.raises(H2EvidenceError, match="ambiguity is a governance defect"):
            resolve_evidence_artifact(
                [make_candidate(), make_candidate()], **self._expected()
            )

    def test_a_failed_run_is_not_admissible(self) -> None:
        with pytest.raises(H2EvidenceError, match="no admissible"):
            resolve_evidence_artifact(
                [make_candidate(conclusion="failure")], **self._expected()
            )

    def test_a_cancelled_run_is_not_admissible(self) -> None:
        with pytest.raises(H2EvidenceError, match="no admissible"):
            resolve_evidence_artifact(
                [make_candidate(conclusion="cancelled")], **self._expected()
            )

    def test_an_expired_artifact_is_not_admissible(self) -> None:
        with pytest.raises(H2EvidenceError, match="no admissible"):
            resolve_evidence_artifact(
                [make_candidate(expired=True)], **self._expected()
            )

    def test_another_workflow_cannot_supply_the_evidence(self) -> None:
        """Un workflow non autorisé pourrait fabriquer un artefact au bon
        nom."""
        with pytest.raises(H2EvidenceError, match="no admissible"):
            resolve_evidence_artifact(
                [make_candidate(workflow_path=".github/workflows/attacker.yml")],
                **self._expected(),
            )

    def test_another_run_attempt_is_not_substitutable(self) -> None:
        with pytest.raises(H2EvidenceError, match="no admissible"):
            resolve_evidence_artifact(
                [make_candidate(run_attempt=2)], **self._expected()
            )

    def test_another_merge_sha_is_not_substitutable(self) -> None:
        with pytest.raises(H2EvidenceError, match="no admissible"):
            resolve_evidence_artifact(
                [make_candidate(head_sha="e" * 40)], **self._expected()
            )

    def test_a_near_miss_artifact_name_is_not_matched(self) -> None:
        """Aucune correspondance par préfixe."""
        with pytest.raises(H2EvidenceError, match="no admissible"):
            resolve_evidence_artifact(
                [make_candidate(artifact_name=f"h2-evidence-{MERGE_SHA}")],
                **self._expected(),
            )

    def test_the_valid_candidate_is_selected_among_inadmissible_ones(self) -> None:
        good = make_candidate()
        found = resolve_evidence_artifact(
            [
                make_candidate(conclusion="failure"),
                make_candidate(expired=True),
                good,
                make_candidate(run_attempt=3),
            ],
            **self._expected(),
        )
        assert found == good


class TestPromotionInputs:
    def test_agreeing_bundle_and_artifact_pass(self) -> None:
        verify_promotion_inputs(
            make_bundle(),
            make_candidate(),
            now=NOW,
            expected_workflow_path=WORKFLOW,
        )

    def test_a_bundle_from_another_run_is_refused(self) -> None:
        with pytest.raises(H2EvidenceError, match="different execution"):
            verify_promotion_inputs(
                make_bundle(run_id="999"),
                make_candidate(),
                now=NOW,
                expected_workflow_path=WORKFLOW,
            )

    def test_a_bundle_claiming_another_workflow_is_refused(self) -> None:
        with pytest.raises(H2EvidenceError, match="promotion expects"):
            verify_promotion_inputs(
                make_bundle(workflow_path=".github/workflows/other.yml"),
                make_candidate(workflow_path=".github/workflows/other.yml"),
                now=NOW,
                expected_workflow_path=WORKFLOW,
            )

    def test_a_failed_gate_still_blocks_at_promotion(self) -> None:
        with pytest.raises(H2EvidenceError, match="did not pass"):
            verify_promotion_inputs(
                make_bundle(h2_coverage_gate_pass=False),
                make_candidate(),
                now=NOW,
                expected_workflow_path=WORKFLOW,
            )

    def test_an_expired_receipt_still_blocks_at_promotion(self) -> None:
        with pytest.raises(H2EvidenceError, match="blank cheque"):
            verify_promotion_inputs(
                make_bundle(exact_head_receipt_issued_at="2026-01-01T00:00:00+00:00"),
                make_candidate(),
                now=NOW,
                expected_workflow_path=WORKFLOW,
            )


class TestEvidenceIndex:
    def test_the_index_never_contains_its_own_digest(self) -> None:
        bundle = make_bundle()
        index = build_evidence_index([bundle])
        assert list(index) == [bundle.artifact_name]
        assert bundle.content_sha256 in index.values()
        # Aucune clé ne désigne l'index lui-même.
        assert not any("index" in key for key in index)

    def test_two_bundles_sharing_a_name_are_refused(self) -> None:
        with pytest.raises(H2EvidenceError, match="silently shadow"):
            build_evidence_index([make_bundle(), make_bundle(run_id="2")])

    def test_the_index_is_sorted_and_deterministic(self) -> None:
        one = make_bundle()
        two = make_bundle(merge_sha="d" * 40)
        assert build_evidence_index([one, two]) == build_evidence_index([two, one])


class TestArtifactName:
    def test_the_name_is_derived_never_supplied(self) -> None:
        bundle = make_bundle()
        assert bundle.artifact_name == f"h2-evidence-{MERGE_SHA}-2026-08-corpus-public"

    def test_a_bundle_cannot_be_published_under_a_foreign_name(self) -> None:
        with pytest.raises(H2EvidenceError, match="artifact name"):
            verify_promotion_inputs(
                make_bundle(),
                make_candidate(artifact_name="h2-evidence-other"),
                now=NOW,
                expected_workflow_path=WORKFLOW,
            )

    def test_replacing_the_campaign_changes_the_name(self) -> None:
        bundle = replace(make_bundle(), campaign_id="2026-09-corpus-public")
        assert bundle.artifact_name.endswith("2026-09-corpus-public")


class TestH2EvidenceBundleV2:
    def test_assembles_only_from_three_cross_bound_v2_documents(self) -> None:
        bundle = _assemble_v2()
        assert bundle.protocol_version == H2_EVIDENCE_V2_PROTOCOL_VERSION
        assert bundle.authorization_set_digest == bundle.input_file_digests[
            "authorization_set"
        ]
        assert bundle.authority_required_count == bundle.authority_covered_count == 1
        assert parse_h2_evidence_bundle_v2(bundle.canonical_bytes()) == bundle

    def test_changed_authorization_set_is_refused(self) -> None:
        changed = _authorization_set().model_copy(
            update={"corpus_manifest_sha256": "f" * 64}
        )
        with pytest.raises(ReleaseEvidenceError, match="authorization_set_digest"):
            _assemble_v2(authorization_set_raw=changed.canonical_bytes())

    def test_changed_campaign_is_refused(self) -> None:
        authorization_set = _authorization_set()
        changed = _campaign_v2(authorization_set).model_copy(
            update={"expected_catalog_digest": "f" * 64}
        )
        with pytest.raises(ReleaseEvidenceError, match="catalog"):
            _assemble_v2(campaign_raw=changed.canonical_bytes())

    def test_changed_h2_coverage_is_refused(self) -> None:
        authorization_set = _authorization_set()
        changed = _h2_coverage_v2(
            authorization_set,
            authority_required_set_sha256="f" * 64,
        )
        with pytest.raises(ReleaseEvidenceError, match="authority_required_set_sha256"):
            _assemble_v2(h2_coverage_evidence_raw=changed.canonical_bytes())

    @pytest.mark.parametrize("offset", [timedelta(seconds=-1), timedelta(seconds=1)])
    def test_h2_expiry_must_equal_the_signed_authorization_set_minimum(
        self, offset: timedelta
    ) -> None:
        authorization_set = _authorization_set()
        changed = _h2_coverage_v2(
            authorization_set,
            authorizations_effective_valid_until=(
                authorization_set.authorizations_effective_valid_until + offset
            ),
        )
        with pytest.raises(
            ReleaseEvidenceError,
            match="authorizations_effective_valid_until",
        ):
            _assemble_v2(h2_coverage_evidence_raw=changed.canonical_bytes())

    def test_placement_provenance_must_come_from_the_merge_tree(self) -> None:
        authorization_set = _authorization_set()
        changed = _h2_coverage_v2(
            authorization_set,
            release_scope_source_tree_sha="4" * 40,
        )
        with pytest.raises(
            ReleaseEvidenceError,
            match="release_scope_source_tree_sha",
        ):
            _assemble_v2(h2_coverage_evidence_raw=changed.canonical_bytes())

    def test_signed_minimum_expiry_is_a_half_open_promotion_boundary(self) -> None:
        authorization_set = _authorization_set()
        coverage = _h2_coverage_v2(
            authorization_set,
            earliest_review_submitted_at=NOW - timedelta(days=5),
            earliest_review_binding_verified_at=NOW - timedelta(days=4),
            authorization_set_verified_at=NOW - timedelta(days=3),
            earliest_review_binding_expires_at=NOW + timedelta(days=3),
        )
        bundle = _assemble_v2(h2_coverage_evidence_raw=coverage.canonical_bytes())
        with pytest.raises(ReleaseEvidenceError, match="authorizations expired"):
            verify_h2_evidence_bundle_v2_freshness(
                bundle,
                now=authorization_set.authorizations_effective_valid_until,
            )

    def test_v1_documents_never_fall_back_into_v2(self) -> None:
        with pytest.raises(ReleaseEvidenceError, match="campaign V2"):
            _assemble_v2(campaign_raw=LEGACY_CAMPAIGN_V1_FIXTURE.read_bytes())
