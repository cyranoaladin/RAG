"""Tests for the real sealed-corpus H2-B coverage report."""
import json
from pathlib import Path

import pytest

from rag_pedago.imports.h2b_coverage_report import (
    generate_coverage_report,
    render_markdown,
)

MANIFEST_SHA256 = "d" * 64


def _write_real_catalog(tmp_path: Path, *, authority_status: str = "PASS") -> Path:
    catalog = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": MANIFEST_SHA256,
        "manifest_entries": 1,
        "physical_object_count": 2,
        "content_artifact_count": 2,
        "eduscol_unique_artifacts": 1,
        "eduscol_placement_count": 2,
        "eduscol_placements_classified": 2,
        "eduscol_placements_unclassified": 0,
        "multi_placement_artifacts": 1,
        "disposition_counts": {
            "INGEST": 1,
            "REVIEW_REQUIRED": 0,
            "QUARANTINE": 0,
            "ARCHIVE_ONLY": 0,
            "EXCLUDE": 1,
            "UNSUPPORTED": 0,
        },
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "verification_errors": [],
        "physical_objects": [
            {
                "content_sha256": "a" * 64,
                "path": "01_EDUSCOL_OFFICIEL/current.pdf",
                "base_disposition": "INGEST",
                "disposition": "INGEST",
                "zone": "01_EDUSCOL_OFFICIEL/",
                "currentness": "actuel",
                "gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": authority_status,
                },
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "Eduscol",
                    "source_url": "https://eduscol.education.gouv.fr/test",
                },
            },
            {
                "content_sha256": MANIFEST_SHA256,
                "path": "00_ADMIN/SHA256SUMS.txt",
                "disposition": "EXCLUDE",
                "zone": "00_ADMIN/",
                "currentness": None,
                "gate_statuses": {},
            },
        ],
    }
    path = tmp_path / "real-catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


def test_real_catalog_proves_coverage_and_all_ingest_safety_invariants(
    tmp_path: Path,
) -> None:
    report = generate_coverage_report(
        _write_real_catalog(tmp_path),
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert report.real_corpus_catalog_source is True
    assert report.synthetic_catalog_used_for_final_gate is False
    assert report.corpus_total_actual == 2
    assert report.sum_equals_total is True
    assert report.zero_gap is True
    assert report.zero_overlap is True
    assert report.safety_invariants == {
        "INGEST_WITHOUT_RIGHTS_CLEARANCE": 0,
        "INGEST_WITHOUT_PII_CLEARANCE": 0,
        "INGEST_WITHOUT_CURRENTNESS_CLEARANCE": 0,
        "INGEST_WITH_UNSUPPORTED_FORMAT": 0,
        "INGEST_WITHOUT_PROVENANCE": 0,
        "INGEST_WITHOUT_CONTENT_SHA": 0,
        "INGEST_WITHOUT_AUTHORITY": 0,
        "INGEST_WITHOUT_ATTRIBUTION_METADATA": 0,
    }
    assert report.coverage_complete is True
    assert report.blocked_ingest_candidates == 0
    markdown = render_markdown(report)
    assert "REAL_CORPUS_CATALOG_SOURCE=true" in markdown
    assert "SYNTHETIC_CATALOG_USED_FOR_FINAL_GATE=false" in markdown


def test_missing_authority_keeps_coverage_gate_red(tmp_path: Path) -> None:
    report = generate_coverage_report(
        _write_real_catalog(tmp_path, authority_status="MISSING"),
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert report.safety_invariants["INGEST_WITHOUT_AUTHORITY"] == 1
    assert report.coverage_complete is False


def test_blocked_candidates_prevent_vacuous_zero_ingest_green(
    tmp_path: Path,
) -> None:
    path = _write_real_catalog(tmp_path)
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["physical_objects"][0]["disposition"] = "REVIEW_REQUIRED"
    catalog["physical_objects"][0]["gate_statuses"]["authority"] = (
        "BLOCKED_NOT_CLEARED"
    )
    catalog["disposition_counts"]["INGEST"] = 0
    catalog["disposition_counts"]["REVIEW_REQUIRED"] = 1
    path.write_text(json.dumps(catalog), encoding="utf-8")

    report = generate_coverage_report(
        path,
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert report.blocked_ingest_candidates == 1
    assert report.mandatory_gate_blockers == {"authority": 1}
    assert report.coverage_complete is False
    assert "BLOCKED_INGEST_CANDIDATES=1" in render_markdown(report)


def test_rejects_synthetic_catalog_for_final_gate(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.json"
    path.write_text(
        json.dumps(
            {
                "corpus_total_objects": 2584,
                "totals": {"INGEST": 64, "REVIEW_REQUIRED": 2520},
                "verification_passed": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="real sealed corpus catalog"):
        generate_coverage_report(path, expected_total=2584)


def test_rejects_catalog_bound_to_another_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="catalog manifest SHA256 mismatch"):
        generate_coverage_report(
            _write_real_catalog(tmp_path),
            expected_total=2,
            expected_manifest_sha256="0" * 64,
        )
