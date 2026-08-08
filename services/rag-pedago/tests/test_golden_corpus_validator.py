"""Tests for golden corpus validator — H2-B."""
from pathlib import Path

import pytest

from rag_pedago.imports.golden_corpus_validator import (
    _validate_boundary_control,
    _validate_negative_control,
    _validate_positive_control,
    validate_golden_corpus,
)


class TestPositiveControlValidation:
    """Test positive control validation."""

    def test_positive_control_passes_when_disposition_matches(self) -> None:
        """Positive control passes when disposition matches expected."""
        control = {
            "control_id": "pos_01",
            "sha256_prefix": "abc123",
            "expected_disposition": "INGEST",
        }
        objects = [
            {"sha256": "abc123def456", "disposition": "INGEST", "currentness": "actuel"},
        ]

        result = _validate_positive_control(control, objects)
        assert result.passed
        assert result.actual_disposition == "INGEST"

    def test_positive_control_passes_when_currentness_actuel(self) -> None:
        """Positive control passes when currentness is actuel (INGEST eligible)."""
        control = {
            "control_id": "pos_01",
            "sha256_prefix": "abc123",
            "expected_disposition": "INGEST",
        }
        objects = [
            {"sha256": "abc123def456", "disposition": "INGEST", "currentness": "actuel"},
        ]

        result = _validate_positive_control(control, objects)
        assert result.passed
        assert result.control_type == "positive"

    def test_positive_control_fails_when_not_found(self) -> None:
        """Positive control fails when object not found."""
        control = {
            "control_id": "pos_01",
            "sha256_prefix": "abc123",
            "expected_disposition": "INGEST",
        }
        objects = [
            {"sha256": "xyz789", "disposition": "INGEST"},
        ]

        result = _validate_positive_control(control, objects)
        assert not result.passed
        assert "not found" in result.failure_reason.lower()


class TestBoundaryControlValidation:
    """Test boundary control validation."""

    def test_boundary_control_passes_when_review_required(self) -> None:
        """Boundary control passes when disposition is REVIEW_REQUIRED."""
        control = {
            "control_id": "bnd_01",
            "zone": "80_A_VERIFIER",
            "expected_disposition": "REVIEW_REQUIRED",
        }
        objects = [
            {"sha256": "abc123", "path": "01_EDUSCOL/.../80_A_VERIFIER/doc.pdf", "disposition": "REVIEW_REQUIRED"},
        ]

        result = _validate_boundary_control(control, objects)
        assert result.passed

    def test_boundary_control_fails_when_wrong_disposition(self) -> None:
        """Boundary control fails when disposition doesn't match."""
        control = {
            "control_id": "bnd_01",
            "zone": "80_A_VERIFIER",
            "expected_disposition": "REVIEW_REQUIRED",
        }
        objects = [
            {"sha256": "abc123", "path": "01_EDUSCOL/.../80_A_VERIFIER/doc.pdf", "disposition": "INGEST"},
        ]

        result = _validate_boundary_control(control, objects)
        assert not result.passed


class TestNegativeControlValidation:
    """Test negative control validation."""

    def test_negative_control_passes_when_excluded(self) -> None:
        """Negative control passes when disposition is EXCLUDE."""
        control = {
            "control_id": "neg_01",
            "zone": "00_ADMIN/",
            "expected_disposition": "EXCLUDE",
        }
        objects = [
            {"sha256": "abc123", "path": "00_ADMIN/SHA256SUMS.txt", "disposition": "EXCLUDE"},
        ]

        result = _validate_negative_control(control, objects)
        assert result.passed

    def test_negative_control_passes_when_not_in_catalog(self) -> None:
        """Negative control passes when object not in catalog (properly excluded)."""
        control = {
            "control_id": "neg_01",
            "filename_pattern": "excluded_file.pdf",
            "expected_disposition": "EXCLUDE",
        }
        objects = []  # Object not in catalog

        result = _validate_negative_control(control, objects)
        assert result.passed  # Not in catalog = properly excluded

    def test_negative_control_passes_when_unsupported(self) -> None:
        """Negative control passes when disposition is UNSUPPORTED."""
        control = {
            "control_id": "neg_04",
            "zone": "03_RESSOURCES_INTERACTIVES/",
            "expected_disposition": "UNSUPPORTED",
        }
        objects = [
            {"sha256": "abc123", "path": "03_RESSOURCES_INTERACTIVES/geo.ggb", "disposition": "UNSUPPORTED"},
        ]

        result = _validate_negative_control(control, objects)
        assert result.passed


class TestGoldenCorpusValidation:
    """Test full golden corpus validation."""

    @pytest.fixture
    def spec(self) -> dict:
        return {
            "spec_id": "test_spec",
            "positive_controls": [
                {
                    "control_id": "pos_01",
                    "sha256_prefix": "aaa",
                    "expected_disposition": "INGEST",
                },
            ],
            "boundary_controls": [
                {
                    "control_id": "bnd_01",
                    "zone": "80_A_VERIFIER",
                    "expected_disposition": "REVIEW_REQUIRED",
                },
            ],
            "negative_controls": [
                {
                    "control_id": "neg_01",
                    "zone": "00_ADMIN/",
                    "expected_disposition": "EXCLUDE",
                },
            ],
        }

    @pytest.fixture
    def catalog(self) -> dict:
        return {
            "objects": [
                {"sha256": "aaa111", "path": "01_EDUSCOL/.../10_ACTUEL_CONFIRME/prog.pdf", "disposition": "INGEST", "currentness": "actuel"},
                {"sha256": "bbb222", "path": "01_EDUSCOL/.../80_A_VERIFIER/doc.pdf", "disposition": "REVIEW_REQUIRED"},
                {"sha256": "ccc333", "path": "00_ADMIN/SHA256SUMS.txt", "disposition": "EXCLUDE"},
            ],
        }

    def test_validation_passes_when_all_controls_pass(
        self, spec: dict, catalog: dict
    ) -> None:
        """Validation passes when all controls pass."""
        report = validate_golden_corpus(
            spec, catalog,
            Path("test_spec.yml"), Path("test_catalog.json"),
        )

        assert report.validation_passed
        assert report.failed_controls == 0
        assert report.passed_controls == 3

    def test_validation_counts_by_control_type(
        self, spec: dict, catalog: dict
    ) -> None:
        """Validation summary includes counts by control type."""
        report = validate_golden_corpus(
            spec, catalog,
            Path("test_spec.yml"), Path("test_catalog.json"),
        )

        assert report.summary["positive_passed"] == 1
        assert report.summary["boundary_passed"] == 1
        assert report.summary["negative_passed"] == 1
