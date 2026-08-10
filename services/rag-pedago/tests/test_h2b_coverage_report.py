"""Tests for the real sealed-corpus H2-B coverage report."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from rag_pedago.imports.h2b_coverage_report import (
    generate_coverage_report,
    render_markdown,
)

MANIFEST_SHA256 = "d" * 64


def _write_external_evidence(tmp_path: Path) -> tuple[Path, Path, Path]:
    routing = {
        "config_id": "coverage-routing-v1",
        "manifest_sha256": MANIFEST_SHA256,
        "rights_evidence_perimeter": [
            "00_ADMIN/",
            "01_EDUSCOL_OFFICIEL/",
        ],
        "zone_rules": [
            {
                "zone_prefix": "00_ADMIN/",
                "disposition": "EXCLUDE",
                "reason": "admin",
            },
            {
                "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                "disposition": "INGEST",
                "currentness": "actuel",
            },
        ],
    }
    rights = {
        "registry_id": "coverage-rights-v1",
        "human_rights_decisions": {
            "eduscol": {
                "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                "decision_maker": "Nexus Réussite",
                "decision_date": "2026-08-08",
                "scope_manifest_sha256": MANIFEST_SHA256,
                "scope_zone": "01_EDUSCOL_OFFICIEL/",
                "approved_for_production_rag": True,
                "generic_rights_blocker": False,
            }
        },
        "source_evidence": {
            "admin": {
                "zone": "00_ADMIN/",
                "rights_status": "REVIEW_REQUIRED",
                "disposition_override": "EXCLUDE",
            },
            "eduscol": {
                "zone": "01_EDUSCOL_OFFICIEL/",
                "rights_status": "CLEARED_BY_HUMAN_DECISION",
                "rights_decision_ref": "eduscol",
            },
        },
        "summary": {"total_zones": 2},
    }
    required_path = "01_EDUSCOL_OFFICIEL/current.pdf"
    pii = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "scanner_version": "coverage-scanner-v1",
        "scanner_sha256": "1" * 64,
        "policy_version": "coverage-policy-v1",
        "policy_sha256": "2" * 64,
        "corpus_manifest_sha256": MANIFEST_SHA256,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "required_pdf_path_count": 1,
        "required_pdf_path_set_digest": hashlib.sha256(
            f"{required_path}\n".encode()
        ).hexdigest(),
        "summary": {
            "sha256_mismatches": 0,
            "pii_scan_scope": "ALL_CORPUS_PDFS",
            "pii_scan_required": 1,
            "pii_scan_exempt": 0,
        },
        "results": [
            {
                "content_sha256": "a" * 64,
                "physical_object_count": 1,
                "status": "CLEARED",
                "error_code": None,
            }
        ],
    }
    routing_path = tmp_path / "routing.yml"
    rights_path = tmp_path / "rights.yml"
    pii_path = tmp_path / "pii.json"
    routing_path.write_text(yaml.safe_dump(routing), encoding="utf-8")
    rights_path.write_text(yaml.safe_dump(rights), encoding="utf-8")
    pii_path.write_text(json.dumps(pii), encoding="utf-8")
    return routing_path, rights_path, pii_path


def _generate(
    tmp_path: Path,
    catalog_path: Path,
    golden_path: Path,
    **kwargs: object,
):
    routing_path, rights_path, pii_path = _write_external_evidence(tmp_path)
    return generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        **kwargs,
    )


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
                "base_disposition": "EXCLUDE",
                "disposition": "EXCLUDE",
                "zone": "00_ADMIN/",
                "currentness": None,
                "gate_statuses": {},
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "NEXUS_CORPUS_GOVERNANCE",
                    "source_reference": "00_ADMIN/SHA256SUMS.txt",
                },
            },
        ],
    }
    path = tmp_path / "real-catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    return path


def _write_golden_spec(
    tmp_path: Path,
    *,
    expected_final: str = "INGEST",
    expected_authority: str = "PASS",
) -> Path:
    spec = {
        "spec_id": "coverage_fixture_v2",
        "catalog_kind_required": "REAL_SEALED_CORPUS",
        "positive_controls": [
            {
                "control_id": "pos_01",
                "sha256_prefix": "a" * 12,
                "expected_base_disposition": "INGEST",
                "expected_final_disposition": expected_final,
                "expected_currentness": "actuel",
                "expected_gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": expected_authority,
                },
            }
        ],
        "boundary_controls": [],
        "negative_controls": [
            {
                "control_id": "neg_manifest",
                "path": "00_ADMIN/SHA256SUMS.txt",
                "expected_count": 1,
                "expected_disposition": "EXCLUDE",
            }
        ],
        "descriptive_assertions": {
            "authoritative": False,
            "items": [],
        },
        "coverage_summary": {
            "total_controls": 2,
            "positive_controls": 1,
            "boundary_controls": 0,
            "negative_controls": 1,
        },
    }
    path = tmp_path / "golden.yml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def test_real_catalog_proves_coverage_and_all_ingest_safety_invariants(
    tmp_path: Path,
) -> None:
    report = _generate(
        tmp_path,
        _write_real_catalog(tmp_path),
        _write_golden_spec(tmp_path),
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
    report = _generate(
        tmp_path,
        _write_real_catalog(tmp_path, authority_status="MISSING"),
        _write_golden_spec(tmp_path),
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert report.safety_invariants["INGEST_WITHOUT_AUTHORITY"] == 1
    assert report.coverage_complete is False


def test_expected_authority_blocked_candidate_can_pass_inert_h2_gate(
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

    report = _generate(
        tmp_path,
        path,
        _write_golden_spec(
            tmp_path,
            expected_final="REVIEW_REQUIRED",
            expected_authority="BLOCKED_NOT_CLEARED",
        ),
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert report.blocked_ingest_candidates == 1
    assert report.mandatory_gate_blockers == {"authority": 1}
    assert report.coverage_complete is True
    assert "BLOCKED_INGEST_CANDIDATES=1" in render_markdown(report)


def test_rejects_catalog_rights_pass_not_derived_from_registry(
    tmp_path: Path,
) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path = _write_external_evidence(tmp_path)
    rights = yaml.safe_load(rights_path.read_text(encoding="utf-8"))
    rights["source_evidence"]["eduscol"]["rights_status"] = "REVIEW_REQUIRED"
    rights["source_evidence"]["eduscol"]["disposition_override"] = (
        "REVIEW_REQUIRED"
    )
    rights_path.write_text(yaml.safe_dump(rights), encoding="utf-8")

    with pytest.raises(ValueError, match="catalog rights gate evidence mismatch"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_rejects_catalog_pii_pass_not_derived_from_sealed_scan(
    tmp_path: Path,
) -> None:
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path = _write_external_evidence(tmp_path)
    pii = json.loads(pii_path.read_text(encoding="utf-8"))
    pii["results"][0]["status"] = "REVIEW_REQUIRED_EXTRACTION_FAILED"
    pii_path.write_text(json.dumps(pii), encoding="utf-8")

    with pytest.raises(ValueError, match="catalog PII gate evidence mismatch"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_final_gate_requires_rights_pii_and_routing_evidence(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="rights evidence is required"):
        generate_coverage_report(
            _write_real_catalog(tmp_path),
            golden_path=_write_golden_spec(tmp_path),
            expected_total=2,
        )


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
