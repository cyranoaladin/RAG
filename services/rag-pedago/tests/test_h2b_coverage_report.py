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


CONTENT_SHA256 = "a" * 64  # SHA256 of the PDF content


def _write_external_evidence(
    tmp_path: Path,
    *,
    include_authority: bool = True,
) -> tuple[Path, Path, Path, Path | None]:
    """Write external evidence files for testing.

    Returns (routing_path, rights_path, pii_path, authority_path).
    If include_authority is False, authority_path will be None.
    """
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
                "content_sha256": CONTENT_SHA256,
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

    # H2-F Défaut 5: LOT41A-V2 authority evidence with content allowlist
    authority_path: Path | None = None
    if include_authority:
        authority = {
            "protocol_version": "LOT41A-V2",
            "authorization_id": "h2b_test_authority_v1",
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "manifest_digest": MANIFEST_SHA256,
            "profile_id": "h2b_test_profile",
            "profile_version": "1.0.0",
            "profile_fingerprint": "f" * 64,
            "allowed_domains": ["eduscol.education.fr"],
            "rights_categories": ["officiel_public"],
            "exclusions": [],
            "pii_absence_attested": True,
            "pii_absence_evidence": "Manual review: no PII found",
            "valid_from": "2026-01-01T00:00:00.000000Z",
            "valid_until": "2026-12-31T23:59:59.999999Z",
            "allowed_content_sha256": [CONTENT_SHA256],
            "scope": {
                "audience": ["libre"],
                "candidat": "libre",
                "collection": "test_collection",
                "matiere": "maths",
                "niveau": "terminale",
                "programme_version": "v1",
                "school_year": "2026-2027",
                "tenant": "libre_terminale",
                "visibility": "public",
                "voie": "generale",
            },
        }
        authority_path = tmp_path / "authority.json"
        authority_path.write_text(json.dumps(authority), encoding="utf-8")

    return routing_path, rights_path, pii_path, authority_path


def _generate(
    tmp_path: Path,
    catalog_path: Path,
    golden_path: Path,
    *,
    include_authority: bool = True,
    **kwargs: object,
):
    """Generate coverage report with external evidence.

    If include_authority=True (default), LOT41A-V2 authority evidence is included.
    """
    routing_path, rights_path, pii_path, authority_path = _write_external_evidence(
        tmp_path, include_authority=include_authority
    )
    return generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        authority_path=authority_path,
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
                "content_sha256": CONTENT_SHA256,
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
                "sha256_prefix": CONTENT_SHA256[:12],
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
    """Nominal test: with proper LOT41A-V2 authority evidence, coverage is complete."""
    report = _generate(
        tmp_path,
        _write_real_catalog(tmp_path),
        _write_golden_spec(tmp_path),
        include_authority=True,  # Include LOT41A-V2 authority evidence
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    assert report.real_corpus_catalog_source is True
    assert report.synthetic_catalog_used_for_final_gate is False
    assert report.corpus_total_actual == 2
    assert report.sum_equals_total is True
    assert report.zero_gap is True
    assert report.zero_overlap is True
    # With proper LOT41A-V2 authority evidence, all invariants should be 0
    assert report.safety_invariants == {
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
    # With proper authority evidence, coverage is complete
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
    routing_path, rights_path, pii_path, _ = _write_external_evidence(tmp_path)
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
    routing_path, rights_path, pii_path, _ = _write_external_evidence(tmp_path)
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


def test_h2f_defaut1_manifest_sha256_mismatch_is_detected(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 1: Any manifest content mismatch must be detected.

    When --manifest is provided, the coverage report MUST verify that:
    1. The manifest file's actual SHA256 matches the catalog's declared manifest_sha256
    2. The manifest entries exactly match the catalog's physical_objects

    If either check fails, the report must reject with a clear error.
    """
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _ = _write_external_evidence(tmp_path)

    # Create a manifest with different content (will have different SHA256)
    manifest_path = tmp_path / "SHA256SUMS.txt"
    manifest_path.write_text(
        "c" * 64 + "  completely_different_file.pdf\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="H2-F Défaut 1"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_h2f_defaut1_missing_manifest_file_is_rejected(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 1: Non-existent manifest file must be rejected."""
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _ = _write_external_evidence(tmp_path)

    # Point to non-existent manifest
    manifest_path = tmp_path / "nonexistent_SHA256SUMS.txt"

    with pytest.raises(ValueError, match="H2-F Défaut 1.*does not exist"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            manifest_path=manifest_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_h2f_defaut5_authority_pass_autodeclare_is_not_sufficient(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 5: authority=PASS auto-déclaré ne suffit pas sans preuve LOT41A/42.

    Le catalogue peut contenir authority=PASS mais le coverage report doit
    comptabiliser cela comme INGEST_WITH_SELF_DECLARED_AUTHORITY car aucune
    preuve LOT41A/42 externe n'est fournie et liée au manifest exact.

    Note: Le compilateur candidat ne peut jamais produire authority=PASS
    (il est toujours BLOCKED_NOT_CLEARED). Ce test vérifie qu'un catalogue
    manuellement modifié avec authority=PASS est tout de même détecté.
    """
    catalog_path = _write_real_catalog(tmp_path)
    # Simulate a manually injected authority=PASS without LOT41A/42 evidence
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["physical_objects"][0]["gate_statuses"]["authority"] = "PASS"
    catalog["physical_objects"][0]["disposition"] = "INGEST"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    # The spec expects authority=PASS but the system must still count it
    # as a violation if there's no external LOT41A/42 proof
    golden_path = _write_golden_spec(tmp_path, expected_authority="PASS")

    # Key: include_authority=False - no external LOT41A evidence
    report = _generate(
        tmp_path,
        catalog_path,
        golden_path,
        include_authority=False,  # No authority evidence provided
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    # H2-F Défaut 5: Self-declared authority=PASS MUST be flagged
    assert report.safety_invariants.get("INGEST_WITH_SELF_DECLARED_AUTHORITY", 0) == 1, \
        "Self-declared authority=PASS should be counted as a violation"
    assert report.coverage_complete is False, \
        "Coverage cannot be complete with self-declared authority"


def test_h2f_defaut5_authority_bound_to_wrong_manifest_is_rejected(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 5: Authority evidence bound to a different manifest must fail closed."""
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _ = _write_external_evidence(
        tmp_path, include_authority=False
    )

    # Create authority evidence bound to a DIFFERENT manifest
    wrong_manifest_sha256 = "b" * 64  # Different from MANIFEST_SHA256
    authority = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": "wrong_manifest_authority",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": wrong_manifest_sha256,  # Wrong manifest!
        "profile_id": "test_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "allowed_content_sha256": [CONTENT_SHA256],
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "test",
            "matiere": "maths",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }
    authority_path = tmp_path / "wrong_authority.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")

    with pytest.raises(ValueError, match="H2-F Défaut 5.*wrong manifest"):
        generate_coverage_report(
            catalog_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
            golden_path=golden_path,
            authority_path=authority_path,
            expected_total=2,
            expected_manifest_sha256=MANIFEST_SHA256,
        )


def test_h2f_defaut5_content_not_in_authority_allowlist_fails(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 5: Content not in authority allowlist must be flagged."""
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _ = _write_external_evidence(
        tmp_path, include_authority=False
    )

    # Create authority evidence that does NOT include the catalog's content SHA256
    different_content_sha256 = "c" * 64  # Different from CONTENT_SHA256
    authority = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": "narrow_authority",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": MANIFEST_SHA256,
        "profile_id": "test_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "allowed_content_sha256": [different_content_sha256],  # Wrong content!
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "test",
            "matiere": "maths",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }
    authority_path = tmp_path / "narrow_authority.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")

    report = generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        authority_path=authority_path,
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    # Content not in allowlist = INGEST_WITHOUT_AUTHORITY (authority claim invalid)
    assert report.safety_invariants["INGEST_WITHOUT_AUTHORITY"] == 1, \
        "Content not in authority allowlist should be flagged as without authority"
    assert report.coverage_complete is False


def test_h2f_defaut5_lot41a_v1_has_no_content_verification(
    tmp_path: Path,
) -> None:
    """H2-F Défaut 5: LOT41A-V1 (no content allowlist) cannot verify content authority."""
    catalog_path = _write_real_catalog(tmp_path)
    golden_path = _write_golden_spec(tmp_path)
    routing_path, rights_path, pii_path, _ = _write_external_evidence(
        tmp_path, include_authority=False
    )

    # Create V1 authority (no allowed_content_sha256)
    authority = {
        "protocol_version": "LOT41A-V1",  # V1, no content list
        "authorization_id": "v1_authority",
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "manifest_digest": MANIFEST_SHA256,
        "profile_id": "test_profile",
        "profile_version": "1.0.0",
        "profile_fingerprint": "f" * 64,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Manual review",
        "valid_from": "2026-01-01T00:00:00.000000Z",
        "valid_until": "2026-12-31T23:59:59.999999Z",
        "scope": {
            "audience": ["libre"],
            "candidat": "libre",
            "collection": "test",
            "matiere": "maths",
            "niveau": "terminale",
            "programme_version": "v1",
            "school_year": "2026-2027",
            "tenant": "libre_terminale",
            "visibility": "public",
            "voie": "generale",
        },
    }
    authority_path = tmp_path / "v1_authority.json"
    authority_path.write_text(json.dumps(authority), encoding="utf-8")

    report = generate_coverage_report(
        catalog_path,
        rights_path=rights_path,
        pii_path=pii_path,
        routing_path=routing_path,
        golden_path=golden_path,
        authority_path=authority_path,
        expected_total=2,
        expected_manifest_sha256=MANIFEST_SHA256,
    )

    # V1 cannot verify individual content = self-declared
    assert report.safety_invariants["INGEST_WITH_SELF_DECLARED_AUTHORITY"] == 1, \
        "V1 authority without content allowlist should be flagged as self-declared"
    assert report.coverage_complete is False
