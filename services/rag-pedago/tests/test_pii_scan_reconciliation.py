"""Réconciliation par union stricte de deux scans PII réels — jamais
'latest wins', jamais une couverture partielle présentée comme complète."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_pedago.imports.pii_scan_reconciliation import (
    PiiScanReconciliationError,
    build_all_corpus_pdfs_pii_evidence,
    load_campaign_scan_results,
    load_exhaustive_scan_results,
    reconcile_pii_scan_evidence,
    union_pii_scan_results,
)

MANIFEST_SHA256 = "d" * 64
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    return path


def _write_campaign(path: Path, results: list[dict], **overrides: object) -> Path:
    document = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "corpus_manifest_sha256": MANIFEST_SHA256,
        "results": results,
    }
    document.update(overrides)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class TestLoadExhaustiveScanResults:
    def test_real_shaped_lines_are_parsed(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path / "scan.jsonl",
            [
                {"content_sha256": SHA_A, "status": "CLEARED"},
                {"content_sha256": SHA_B, "status": "QUARANTINED_PII"},
                {"content_sha256": SHA_C, "status": "REVIEW_REQUIRED_EXTRACTION_FAILED"},
            ],
        )
        results = load_exhaustive_scan_results(path)
        assert results == {
            SHA_A: "CLEARED",
            SHA_B: "QUARANTINED_PII",
            SHA_C: "REVIEW_REQUIRED_EXTRACTION_FAILED",
        }

    def test_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PiiScanReconciliationError, match="does not exist"):
            load_exhaustive_scan_results(tmp_path / "missing.jsonl")

    def test_unknown_status_is_refused(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path / "scan.jsonl", [{"content_sha256": SHA_A, "status": "MAYBE_FINE"}]
        )
        with pytest.raises(PiiScanReconciliationError, match="unknown PII status"):
            load_exhaustive_scan_results(path)

    def test_duplicate_content_sha256_within_the_same_file_is_refused(
        self, tmp_path: Path
    ) -> None:
        path = _write_jsonl(
            tmp_path / "scan.jsonl",
            [
                {"content_sha256": SHA_A, "status": "CLEARED"},
                {"content_sha256": SHA_A, "status": "QUARANTINED_PII"},
            ],
        )
        with pytest.raises(PiiScanReconciliationError, match="duplicate"):
            load_exhaustive_scan_results(path)

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "scan.jsonl"
        path.write_text(
            json.dumps({"content_sha256": SHA_A, "status": "CLEARED"}) + "\n\n\n",
            encoding="utf-8",
        )
        assert load_exhaustive_scan_results(path) == {SHA_A: "CLEARED"}


class TestLoadCampaignScanResults:
    def test_real_shaped_campaign_is_parsed(self, tmp_path: Path) -> None:
        path = _write_campaign(
            tmp_path / "campaign.json",
            [{"content_sha256": SHA_A, "status": "CLEARED"}],
        )
        results = load_campaign_scan_results(
            path, expected_manifest_sha256=MANIFEST_SHA256
        )
        assert results == {SHA_A: "CLEARED"}

    def test_wrong_evidence_kind_is_refused(self, tmp_path: Path) -> None:
        path = _write_campaign(
            tmp_path / "campaign.json", [], evidence_kind="SOMETHING_ELSE"
        )
        with pytest.raises(PiiScanReconciliationError, match="REAL_CORPUS_PII_SCAN"):
            load_campaign_scan_results(path, expected_manifest_sha256=MANIFEST_SHA256)

    def test_manifest_mismatch_is_refused(self, tmp_path: Path) -> None:
        path = _write_campaign(
            tmp_path / "campaign.json", [], corpus_manifest_sha256="0" * 64
        )
        with pytest.raises(PiiScanReconciliationError, match="another manifest"):
            load_campaign_scan_results(path, expected_manifest_sha256=MANIFEST_SHA256)


class TestUnionPiiScanResults:
    def test_disjoint_sources_are_unioned(self) -> None:
        union = union_pii_scan_results({SHA_A: "CLEARED"}, {SHA_B: "QUARANTINED_PII"})
        assert union == {SHA_A: "CLEARED", SHA_B: "QUARANTINED_PII"}

    def test_agreeing_overlap_is_fine(self) -> None:
        union = union_pii_scan_results({SHA_A: "CLEARED"}, {SHA_A: "CLEARED"})
        assert union == {SHA_A: "CLEARED"}

    def test_disagreeing_overlap_is_an_evidence_conflict(self) -> None:
        with pytest.raises(PiiScanReconciliationError, match="EVIDENCE_CONFLICT"):
            union_pii_scan_results({SHA_A: "CLEARED"}, {SHA_A: "QUARANTINED_PII"})


class TestBuildAllCorpusPdfsPiiEvidence:
    def _entries(self) -> list[tuple[str, str]]:
        return [
            (SHA_A, "01_EDUSCOL_OFFICIEL/a.pdf"),
            (SHA_B, "01_EDUSCOL_OFFICIEL/b.pdf"),
            (SHA_C, "00_ADMIN/not-a-pdf.tsv"),
        ]

    def test_complete_coverage_builds_a_valid_document(self) -> None:
        document = build_all_corpus_pdfs_pii_evidence(
            union_results={SHA_A: "CLEARED", SHA_B: "QUARANTINED_PII"},
            manifest_entries=self._entries(),
            manifest_sha256=MANIFEST_SHA256,
            policy_version="test-policy-v1",
            scanner_version="test-scanner-v1",
        )
        assert document["evidence_kind"] == "REAL_CORPUS_PII_SCAN"
        assert document["corpus_manifest_sha256"] == MANIFEST_SHA256
        assert document["summary"]["pii_scan_scope"] == "ALL_CORPUS_PDFS"
        assert document["summary"]["pii_scan_required"] == 2  # only the 2 PDFs
        assert document["summary"]["pii_scan_exempt"] == 0
        assert document["required_pdf_path_count"] == 2
        results_by_sha = {r["content_sha256"]: r for r in document["results"]}
        assert results_by_sha[SHA_A]["status"] == "CLEARED"
        assert results_by_sha[SHA_A]["physical_object_count"] == 1
        assert results_by_sha[SHA_B]["status"] == "QUARANTINED_PII"
        # SHA_C (non-PDF) never appears -- only real PDFs are in scope.
        assert SHA_C not in results_by_sha

    def test_missing_coverage_for_a_real_pdf_is_refused(self) -> None:
        with pytest.raises(PiiScanReconciliationError, match="covered by neither"):
            build_all_corpus_pdfs_pii_evidence(
                union_results={SHA_A: "CLEARED"},  # SHA_B missing
                manifest_entries=self._entries(),
                manifest_sha256=MANIFEST_SHA256,
                policy_version="test-policy-v1",
                scanner_version="test-scanner-v1",
            )

    def test_multiple_placements_of_the_same_content_are_counted(self) -> None:
        entries = [
            (SHA_A, "01_EDUSCOL_OFFICIEL/a.pdf"),
            (SHA_A, "02_NEXUS_DIAGNOSTICS/a-copy.pdf"),
        ]
        document = build_all_corpus_pdfs_pii_evidence(
            union_results={SHA_A: "CLEARED"},
            manifest_entries=entries,
            manifest_sha256=MANIFEST_SHA256,
            policy_version="test-policy-v1",
            scanner_version="test-scanner-v1",
        )
        (result,) = document["results"]
        assert result["physical_object_count"] == 2

    def test_scanner_and_policy_sha256_are_well_formed_hex64(self) -> None:
        document = build_all_corpus_pdfs_pii_evidence(
            union_results={},
            manifest_entries=[],
            manifest_sha256=MANIFEST_SHA256,
            policy_version="test-policy-v1",
            scanner_version="test-scanner-v1",
        )
        import re

        assert re.fullmatch(r"[0-9a-f]{64}", document["scanner_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", document["policy_sha256"])


class TestReconcilePiiScanEvidenceEndToEnd:
    def test_real_shaped_two_source_reconciliation(self, tmp_path: Path) -> None:
        exhaustive_path = _write_jsonl(
            tmp_path / "exhaustive.jsonl",
            [{"content_sha256": SHA_A, "status": "CLEARED"}],
        )
        campaign_path = _write_campaign(
            tmp_path / "campaign.json",
            [{"content_sha256": SHA_B, "status": "QUARANTINED_PII"}],
        )
        document = reconcile_pii_scan_evidence(
            exhaustive_scan_path=exhaustive_path,
            campaign_scan_path=campaign_path,
            manifest_entries=[
                (SHA_A, "01_EDUSCOL_OFFICIEL/a.pdf"),
                (SHA_B, "01_EDUSCOL_OFFICIEL/b.pdf"),
            ],
            manifest_sha256=MANIFEST_SHA256,
            policy_version="test-policy-v1",
            scanner_version="test-scanner-v1",
        )
        results_by_sha = {r["content_sha256"]: r["status"] for r in document["results"]}
        assert results_by_sha == {SHA_A: "CLEARED", SHA_B: "QUARANTINED_PII"}

    def test_conflicting_sources_refuse_before_building_anything(
        self, tmp_path: Path
    ) -> None:
        exhaustive_path = _write_jsonl(
            tmp_path / "exhaustive.jsonl",
            [{"content_sha256": SHA_A, "status": "CLEARED"}],
        )
        campaign_path = _write_campaign(
            tmp_path / "campaign.json",
            [{"content_sha256": SHA_A, "status": "QUARANTINED_PII"}],
        )
        with pytest.raises(PiiScanReconciliationError, match="EVIDENCE_CONFLICT"):
            reconcile_pii_scan_evidence(
                exhaustive_scan_path=exhaustive_path,
                campaign_scan_path=campaign_path,
                manifest_entries=[(SHA_A, "01_EDUSCOL_OFFICIEL/a.pdf")],
                manifest_sha256=MANIFEST_SHA256,
                policy_version="test-policy-v1",
                scanner_version="test-scanner-v1",
            )
