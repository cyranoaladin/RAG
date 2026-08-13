"""Contrat `NEXUS-H2-COVERAGE-EVIDENCE-V1` — représentation, pas calcul.

Chaque test prouve que ce contrat refuse une preuve H2 malformée ou
non canonique, sans jamais recalculer lui-même un verdict de gate.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from nexus_contracts.h2_coverage_evidence import (
    H2_COVERAGE_EVIDENCE_PROTOCOL_VERSION,
    H2CoverageEvidenceError,
    H2CoverageEvidenceV1,
    parse_h2_coverage_evidence,
)
from pydantic import ValidationError

GIT_COMMIT = "a" * 40
MANIFEST_SHA256 = "b" * 64
GENERATED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "protocol_version": H2_COVERAGE_EVIDENCE_PROTOCOL_VERSION,
        "environment": "production",
        "report_id": "h2b-coverage-20260813",
        "generated_at": GENERATED_AT,
        "git_commit": GIT_COMMIT,
        "producer_version": "h2b_coverage_report/1",
        "manifest_sha256": MANIFEST_SHA256,
        "input_file_digests": {
            "catalog": "c" * 64,
            "routing": "d" * 64,
            "rights": "e" * 64,
            "pii": "f" * 64,
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
    }
    fields.update(overrides)
    return fields


def _valid_bytes(**overrides: Any) -> bytes:
    return H2CoverageEvidenceV1.model_validate(_fields(**overrides)).canonical_bytes()


class TestCanonicalization:
    def test_canonical_bytes_are_deterministic(self) -> None:
        a = H2CoverageEvidenceV1.model_validate(_fields())
        b = H2CoverageEvidenceV1.model_validate(_fields())
        assert a.canonical_bytes() == b.canonical_bytes()

    def test_field_order_of_input_never_changes_the_digest(self) -> None:
        forward = _fields()
        backward = dict(reversed(list(forward.items())))
        a = H2CoverageEvidenceV1.model_validate(forward)
        b = H2CoverageEvidenceV1.model_validate(backward)
        assert a.canonical_bytes() == b.canonical_bytes()

    def test_roundtrip_through_parse_succeeds_on_canonical_bytes(self) -> None:
        raw = _valid_bytes()
        parsed = parse_h2_coverage_evidence(raw)
        assert parsed.h2_coverage_gate_pass is True
        assert parsed.canonical_bytes() == raw


class TestStrictValidation:
    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(_fields(unexpected_field="surprise"))

    def test_missing_field_is_rejected(self) -> None:
        fields = _fields()
        del fields["h2_coverage_gate_pass"]
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(fields)

    def test_wrong_protocol_version_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(_fields(protocol_version="OTHER-V1"))

    def test_non_production_environment_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(_fields(environment="rehearsal"))

    def test_malformed_git_commit_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(_fields(git_commit="not-a-sha"))

    def test_malformed_manifest_sha256_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(_fields(manifest_sha256="not-a-digest"))

    def test_empty_input_file_digests_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(_fields(input_file_digests={}))

    def test_invalid_gate_status_literal_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(_fields(rights_gate_status="MAYBE"))

    def test_negative_corpus_total_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            H2CoverageEvidenceV1.model_validate(_fields(corpus_total_actual=-1))


class TestCrossFieldConsistency:
    """Deux invariants structurels ajoutés après revue Codex (P1, PR #104) :
    un document ne peut jamais revendiquer un succès global tout en
    omettant l'une des quatre preuves d'entrée, ni tout en enregistrant
    lui-même un échec de couverture ou de gouvernance."""

    def test_input_file_digests_missing_a_required_key_is_rejected(self) -> None:
        digests = {**_fields()["input_file_digests"]}
        del digests["rights"]
        with pytest.raises(ValidationError, match="missing required key"):
            H2CoverageEvidenceV1.model_validate(_fields(input_file_digests=digests))

    def test_input_file_digests_with_only_an_arbitrary_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="missing required key"):
            H2CoverageEvidenceV1.model_validate(
                _fields(input_file_digests={"placeholder": "c" * 64})
            )

    def test_input_file_digests_with_all_four_required_keys_is_accepted(self) -> None:
        H2CoverageEvidenceV1.model_validate(_fields())  # no raise

    @pytest.mark.parametrize(
        "override",
        [
            {"coverage_complete": False},
            {"golden_validation_pass": False},
            {"rights_gate_status": "BLOCKED_INGEST_WITHOUT_CLEARANCE"},
            {"pii_gate_status": "BLOCKED_INGEST_WITHOUT_CLEARANCE"},
            {"authority_review_binding_verified": False},
            {"authority_revocations_checked": False},
        ],
    )
    def test_gate_pass_true_with_a_false_prerequisite_is_rejected(
        self, override: dict[str, Any]
    ) -> None:
        with pytest.raises(ValidationError, match="inconsistent with its own prerequisites"):
            H2CoverageEvidenceV1.model_validate(
                _fields(h2_coverage_gate_pass=True, **override)
            )

    def test_gate_pass_false_with_a_false_prerequisite_is_accepted(self) -> None:
        H2CoverageEvidenceV1.model_validate(
            _fields(h2_coverage_gate_pass=False, coverage_complete=False)
        )  # no raise

    def test_gate_pass_true_with_all_prerequisites_true_is_accepted(self) -> None:
        H2CoverageEvidenceV1.model_validate(_fields(h2_coverage_gate_pass=True))  # no raise


class TestParseHardensAgainstNonCanonicalOrMalformedInput:
    def test_malformed_json_is_refused(self) -> None:
        with pytest.raises(H2CoverageEvidenceError, match="not valid JSON"):
            parse_h2_coverage_evidence(b"not json")

    def test_non_utf8_is_refused(self) -> None:
        with pytest.raises(H2CoverageEvidenceError, match="not valid UTF-8"):
            parse_h2_coverage_evidence(b"\xff\xfe")

    def test_non_object_json_is_refused(self) -> None:
        with pytest.raises(H2CoverageEvidenceError, match="must be a JSON object"):
            parse_h2_coverage_evidence(b"[]")

    def test_schema_violation_is_refused(self) -> None:
        import json

        raw = json.dumps({"protocol_version": H2_COVERAGE_EVIDENCE_PROTOCOL_VERSION}).encode(
            "utf-8"
        )
        with pytest.raises(H2CoverageEvidenceError, match="failed strict validation"):
            parse_h2_coverage_evidence(raw)

    def test_non_canonical_bytes_are_refused(self) -> None:
        # Valid JSON, valid schema, but not the canonical byte form
        # (extra whitespace) -- the reviewed bytes must be exactly what
        # gets re-derived, never "close enough".
        canonical = _valid_bytes()
        non_canonical = canonical.replace(b'"protocol_version"', b'"protocol_version" ')
        assert non_canonical != canonical
        with pytest.raises(H2CoverageEvidenceError, match="not in canonical form"):
            parse_h2_coverage_evidence(non_canonical)

    def test_malformed_digest_inside_input_file_digests_is_refused(self) -> None:
        digests = {**_fields()["input_file_digests"], "catalog": "not-a-hex-digest"}
        raw = H2CoverageEvidenceV1.model_validate(
            _fields(input_file_digests=digests)
        ).canonical_bytes()
        with pytest.raises(H2CoverageEvidenceError, match="malformed sha256 digest"):
            parse_h2_coverage_evidence(raw)


class TestMutationCanaries:
    """Un verdict de gate qui bascule doit changer le digest — sinon le
    contrat ne lie pas réellement ce qu'il prétend lier."""

    def test_flipping_gate_pass_changes_the_digest(self) -> None:
        passing = _valid_bytes(h2_coverage_gate_pass=True)
        failing = _valid_bytes(h2_coverage_gate_pass=False)
        assert passing != failing

    def test_changing_manifest_sha256_changes_the_digest(self) -> None:
        a = _valid_bytes(manifest_sha256="b" * 64)
        b = _valid_bytes(manifest_sha256="c" * 64)
        assert a != b
