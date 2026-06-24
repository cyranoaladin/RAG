from __future__ import annotations

import sqlite3
from pathlib import Path

from rag_pedago.imports.coverage import CoverageStatus, build_coverage_report
from rag_pedago.imports.gate import GateStatus, build_gate_report
from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.quality import QualityPolicy
from rag_pedago.imports.readiness import ReadinessStatus, build_readiness_report
from rag_pedago.ledger.migrations import initialize_database

ROOT = Path(__file__).resolve().parents[2]
BATCH_PROBLEM = ROOT / "data/fixtures/manifests/batch_001"
BATCH_CLEAN = ROOT / "data/fixtures/manifests/batch_clean_001"
TAXONOMIES = [
    ROOT / "taxonomy/maths/terminale_specialite.yml",
    ROOT / "taxonomy/nsi/terminale.yml",
]
PRIORITY_NOTIONS = [
    "suites",
    "recurrence",
    "limites_de_suites",
    "fonction_exponentielle",
    "probabilites_conditionnelles",
    "graphes",
    "parcours_graphes",
    "sql",
    "poo",
]


def test_clean_batch_readiness_ready(tmp_path) -> None:
    report = build_readiness_report(
        BATCH_CLEAN,
        "test-clean-readiness",
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is ReadinessStatus.ready
    assert report.blocking_issue_count == 0
    assert report.warning_count == 0


def test_clean_batch_coverage_ok(tmp_path) -> None:
    report = build_coverage_report(
        BATCH_CLEAN,
        "test-clean-coverage",
        TAXONOMIES,
        priority_notions=PRIORITY_NOTIONS,
        output_dir=tmp_path / "reports",
    )

    assert report.status is CoverageStatus.ok
    assert report.notions_unknown == []
    assert report.missing_priority_notions == []
    assert set(PRIORITY_NOTIONS).issubset(set(report.notions_known))


def test_clean_batch_gate_ready_for_controlled_import(tmp_path) -> None:
    report = build_gate_report(
        BATCH_CLEAN,
        "test-clean-gate",
        TAXONOMIES,
        QualityPolicy(),
        priority_notions=PRIORITY_NOTIONS,
        output_dir=tmp_path / "reports",
    )

    assert report.status is GateStatus.ready_for_controlled_import
    assert report.readiness_status == "ready"
    assert report.coverage_status == "coverage_ok"


def test_clean_batch_can_be_imported_as_manifests_only(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    initialize_database(db_path)

    report = import_manifest_directory(
        BATCH_CLEAN,
        db_path=db_path,
        batch_id="test-clean-import",
    )

    assert report.status == "success"
    assert report.documents_valid > 0
    assert report.documents_not_retrievable == 0
    with sqlite3.connect(db_path) as conn:
        document_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        source_uris = [
            row[0] for row in conn.execute("SELECT source_uri FROM documents ORDER BY doc_id")
        ]
    assert document_count == report.documents_valid
    assert all(source_uri.startswith("fixture://clean/") for source_uri in source_uris)


def test_problem_batch_still_blocked(tmp_path) -> None:
    report = build_gate_report(
        BATCH_PROBLEM,
        "test-problem-gate",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is GateStatus.blocked
    assert report.readiness_status == "blocked"
