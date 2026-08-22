"""Contrat `NEXUS-H2-COVERAGE-EVIDENCE-V2` (ADR-0044) — liaison d'autorité
multi-scope, jamais un recalcul du gate.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from nexus_contracts.h2_coverage_evidence import (
    H2CoverageEvidenceError,
    H2CoverageEvidenceV1,
    H2CoverageEvidenceV2,
    parse_h2_coverage_evidence,
    parse_h2_coverage_evidence_v2,
)
from pydantic import ValidationError

GIT_COMMIT = "a" * 40
MANIFEST_SHA256 = "b" * 64
GENERATED_AT = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

ZERO_SAFETY_INVARIANTS: dict[str, int] = {
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


def _fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "protocol_version": "NEXUS-H2-COVERAGE-EVIDENCE-V2",
        "environment": "production",
        "report_id": "h2b-coverage-20260822",
        "generated_at": GENERATED_AT,
        "git_commit": GIT_COMMIT,
        "producer_version": "h2b_coverage_report/2",
        "manifest_sha256": MANIFEST_SHA256,
        "input_file_digests": {
            "catalog": "c" * 64,
            "routing": "d" * 64,
            "rights": "e" * 64,
            "pii": "f" * 64,
            "golden": "0" * 64,
        },
        "corpus_total_expected": 2584,
        "corpus_total_actual": 2584,
        "corpus_match": True,
        "sum_equals_total": True,
        "zero_overlap": True,
        "zero_gap": True,
        "coverage_complete": True,
        "rights_gate_status": "PASS",
        "pii_gate_status": "PASS",
        "golden_validation_pass": True,
        "h2_coverage_gate_pass": True,
        "authority_review_binding_verified": True,
        "authority_revocations_checked": True,
        "authorization_set_digest": "1" * 64,
        "authorization_count": 23,
        "authority_required_count": 72,
        "authority_covered_count": 72,
        "authority_required_set_sha256": "2" * 64,
        "safety_invariants": dict(ZERO_SAFETY_INVARIANTS),
    }
    fields.update(overrides)
    return fields


def _valid_bytes(**overrides: Any) -> bytes:
    return H2CoverageEvidenceV2.model_validate(_fields(**overrides)).canonical_bytes()


class TestRequiredInputFiles:
    def test_five_keys_are_required_not_six(self) -> None:
        H2CoverageEvidenceV2.model_validate(_fields())

    def test_missing_a_required_key_is_refused(self) -> None:
        digests = _fields()["input_file_digests"]
        del digests["golden"]
        with pytest.raises(ValidationError, match="golden"):
            H2CoverageEvidenceV2.model_validate(_fields(input_file_digests=digests))

    def test_authority_key_is_never_required_in_v2(self) -> None:
        """V2 délibérément n'exige plus 'authority' dans
        input_file_digests — la liaison d'autorité passe désormais par
        authorization_set_digest, un champ de premier niveau."""
        digests = {k: v for k, v in _fields()["input_file_digests"].items()}
        assert "authority" not in digests
        H2CoverageEvidenceV2.model_validate(_fields(input_file_digests=digests))


class TestSafetyInvariants:
    def test_exact_key_set_still_enforced(self) -> None:
        invariants = dict(ZERO_SAFETY_INVARIANTS)
        del invariants["INGEST_WITHOUT_PROVENANCE"]
        with pytest.raises(ValidationError, match="safety_invariants"):
            H2CoverageEvidenceV2.model_validate(_fields(safety_invariants=invariants))

    def test_unknown_key_is_refused(self) -> None:
        invariants = dict(ZERO_SAFETY_INVARIANTS)
        invariants["INGEST_WITH_MADE_UP_VIOLATION"] = 0
        with pytest.raises(ValidationError, match="safety_invariants"):
            H2CoverageEvidenceV2.model_validate(_fields(safety_invariants=invariants))


class TestAuthorityCounts:
    def test_covered_cannot_exceed_required(self) -> None:
        with pytest.raises(ValidationError, match="exceeds"):
            H2CoverageEvidenceV2.model_validate(
                _fields(authority_required_count=10, authority_covered_count=11)
            )

    def test_gate_pass_requires_covered_equals_required(self) -> None:
        with pytest.raises(ValidationError, match="prerequisites"):
            H2CoverageEvidenceV2.model_validate(
                _fields(
                    h2_coverage_gate_pass=True,
                    authority_required_count=72,
                    authority_covered_count=71,
                )
            )

    def test_gate_fail_permits_partial_coverage(self) -> None:
        H2CoverageEvidenceV2.model_validate(
            _fields(
                h2_coverage_gate_pass=False,
                coverage_complete=False,
                authority_required_count=72,
                authority_covered_count=71,
            )
        )


class TestGatePassPrerequisites:
    def test_gate_pass_with_all_prerequisites_is_accepted(self) -> None:
        H2CoverageEvidenceV2.model_validate(_fields())

    def test_gate_pass_with_a_failed_safety_invariant_is_refused(self) -> None:
        invariants = dict(ZERO_SAFETY_INVARIANTS)
        invariants["INGEST_WITHOUT_RIGHTS_CLEARANCE"] = 1
        with pytest.raises(ValidationError, match="prerequisites"):
            H2CoverageEvidenceV2.model_validate(_fields(safety_invariants=invariants))

    def test_gate_pass_with_corpus_mismatch_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="prerequisites"):
            H2CoverageEvidenceV2.model_validate(_fields(corpus_match=False))


class TestCanonicalizationAndParsing:
    def test_canonical_bytes_are_deterministic(self) -> None:
        a = H2CoverageEvidenceV2.model_validate(_fields())
        b = H2CoverageEvidenceV2.model_validate(_fields())
        assert a.canonical_bytes() == b.canonical_bytes()

    def test_round_trip_parses_canonical_bytes(self) -> None:
        raw = _valid_bytes()
        parsed = parse_h2_coverage_evidence_v2(raw)
        assert parsed.authorization_set_digest == "1" * 64

    def test_refuses_non_canonical_bytes(self) -> None:
        canonical = _valid_bytes()
        non_canonical = canonical.replace(b'"protocol_version"', b'"protocol_version" ')
        assert non_canonical != canonical
        with pytest.raises(H2CoverageEvidenceError, match="not in canonical form"):
            parse_h2_coverage_evidence_v2(non_canonical)


class TestV1AndV2AreNeverInterchangeable:
    def test_v2_document_is_never_parseable_as_v1(self) -> None:
        raw = _valid_bytes()
        with pytest.raises(H2CoverageEvidenceError):
            parse_h2_coverage_evidence(raw)

    def test_v1_authorization_id_field_does_not_exist_on_v2(self) -> None:
        fields = _fields()
        fields["authorization_id"] = "some-id"
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV2.model_validate(fields)

    def test_v2_authorization_set_digest_field_does_not_exist_on_v1(self) -> None:
        v1_fields: dict[str, Any] = {
            "protocol_version": "NEXUS-H2-COVERAGE-EVIDENCE-V1",
            "environment": "production",
            "report_id": "r1",
            "generated_at": GENERATED_AT,
            "git_commit": GIT_COMMIT,
            "producer_version": "p/1",
            "manifest_sha256": MANIFEST_SHA256,
            "input_file_digests": {
                "catalog": "c" * 64,
                "routing": "d" * 64,
                "rights": "e" * 64,
                "pii": "f" * 64,
                "golden": "0" * 64,
                "authority": "1" * 64,
            },
            "corpus_total_expected": 2583,
            "corpus_total_actual": 2583,
            "corpus_match": True,
            "sum_equals_total": True,
            "zero_overlap": True,
            "zero_gap": True,
            "coverage_complete": True,
            "rights_gate_status": "PASS",
            "pii_gate_status": "PASS",
            "golden_validation_pass": True,
            "h2_coverage_gate_pass": True,
            "authority_review_binding_verified": True,
            "authority_revocations_checked": True,
            "authorization_id": "some-id",
            "authorization_set_digest": "1" * 64,
            "safety_invariants": dict(ZERO_SAFETY_INVARIANTS),
        }
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(v1_fields)
