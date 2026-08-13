"""Focused unit tests for exhaustive H2 golden controls."""

from __future__ import annotations

from rag_pedago.imports.golden_corpus_validator import (
    _validate_boundary_control,
    _validate_negative_control,
    _validate_positive_control,
)


def _positive_control() -> dict[str, object]:
    return {
        "control_id": "pos_01",
        "sha256_prefix": "a" * 12,
        "expected_base_disposition": "INGEST",
        "expected_final_disposition": "REVIEW_REQUIRED",
        "expected_currentness": "actuel",
        "expected_gate_statuses": {
            "rights": "PASS",
            "pii": "PASS",
            "authority": "BLOCKED_NOT_CLEARED",
        },
    }


def _positive_object() -> dict[str, object]:
    return {
        "content_sha256": "a" * 64,
        "path": "01_EDUSCOL/10_ACTUEL_CONFIRME/a.pdf",
        "base_disposition": "INGEST",
        "disposition": "REVIEW_REQUIRED",
        "currentness": "actuel",
        "gate_statuses": {
            "rights": "PASS",
            "pii": "PASS",
            "authority": "BLOCKED_NOT_CLEARED",
        },
    }


def test_positive_control_checks_base_final_currentness_and_gates() -> None:
    result = _validate_positive_control(
        _positive_control(),
        [_positive_object()],
    )

    assert result.passed is True
    assert result.actual_base_disposition == "INGEST"
    assert result.actual_disposition == "REVIEW_REQUIRED"


def test_positive_control_does_not_infer_ingest_from_currentness() -> None:
    item = _positive_object()
    item["base_disposition"] = "REVIEW_REQUIRED"

    result = _validate_positive_control(_positive_control(), [item])

    assert result.passed is False
    assert "base expected INGEST" in str(result.failure_reason)


def test_positive_control_fails_when_prefix_has_no_match() -> None:
    result = _validate_positive_control(
        _positive_control(),
        [{**_positive_object(), "content_sha256": "b" * 64}],
    )

    assert result.passed is False
    assert result.actual_count == 0


def test_boundary_control_validates_all_objects() -> None:
    control = {
        "control_id": "bnd_01",
        "zone": "01_EDUSCOL/80_A_VERIFIER/",
        "expected_count_in_zone": 2,
        "expected_disposition": "REVIEW_REQUIRED",
        "expected_currentness": "a_verifier",
    }
    objects = [
        {
            "content_sha256": "a" * 64,
            "path": "01_EDUSCOL/80_A_VERIFIER/a.pdf",
            "disposition": "REVIEW_REQUIRED",
            "currentness": "a_verifier",
        },
        {
            "content_sha256": "b" * 64,
            "path": "01_EDUSCOL/80_A_VERIFIER/b.pdf",
            "disposition": "REVIEW_REQUIRED",
            "currentness": "a_verifier",
        },
    ]

    assert _validate_boundary_control(control, objects).passed is True
    objects[1]["disposition"] = "INGEST"
    result = _validate_boundary_control(control, objects)
    assert result.passed is False
    assert result.mismatching_count == 1


def test_boundary_control_requires_exact_count() -> None:
    result = _validate_boundary_control(
        {
            "control_id": "bnd_01",
            "zone": "01_EDUSCOL/80_A_VERIFIER/",
            "expected_count_in_zone": 2,
            "expected_disposition": "REVIEW_REQUIRED",
        },
        [
            {
                "content_sha256": "a" * 64,
                "path": "01_EDUSCOL/80_A_VERIFIER/a.pdf",
                "disposition": "REVIEW_REQUIRED",
            }
        ],
    )

    assert result.passed is False
    assert result.actual_count == 1


def test_negative_control_is_exact_and_absence_is_failure() -> None:
    control = {
        "control_id": "neg_manifest",
        "path": "00_ADMIN/SHA256SUMS.txt",
        "expected_count": 1,
        "expected_disposition": "EXCLUDE",
    }
    item = {
        "content_sha256": "a" * 64,
        "path": "00_ADMIN/SHA256SUMS.txt",
        "disposition": "EXCLUDE",
    }

    assert _validate_negative_control(control, [item]).passed is True
    absent = _validate_negative_control(control, [])
    assert absent.passed is False
    assert absent.actual_count == 0


def test_negative_zone_control_checks_every_match() -> None:
    control = {
        "control_id": "neg_geogebra",
        "zone": "03_RESSOURCES_INTERACTIVES/",
        "expected_count_in_zone": 2,
        "expected_disposition": "UNSUPPORTED",
    }
    objects = [
        {
            "content_sha256": "a" * 64,
            "path": "03_RESSOURCES_INTERACTIVES/a.ggb",
            "disposition": "UNSUPPORTED",
        },
        {
            "content_sha256": "b" * 64,
            "path": "03_RESSOURCES_INTERACTIVES/b.ggb",
            "disposition": "INGEST",
        },
    ]

    result = _validate_negative_control(control, objects)

    assert result.passed is False
    assert result.mismatching_count == 1
