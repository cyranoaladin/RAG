from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from rag_pedago.imports.controlled_import import (
    ControlledImportStatus,
    controlled_import_manifest_directory,
)
from rag_pedago.imports.quality import QualityPolicy
from rag_pedago.imports.review import approve_review_package, build_review_package
from rag_pedago.imports.review_package_cli import main as review_package_main
from rag_pedago.ledger.migrations import initialize_database
from rag_pedago.ledger.repository import LedgerRepository

ROOT = Path(__file__).resolve().parents[2]
BATCH_CLEAN = ROOT / "data/fixtures/manifests/batch_official_profiles_clean"
BATCH_MISMATCH = ROOT / "data/fixtures/manifests/batch_official_mismatch"
TAXONOMIES = [
    ROOT / "taxonomy/maths/terminale_specialite.yml",
    ROOT / "taxonomy/nsi/terminale.yml",
]


def table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def make_review(tmp_path: Path, batch_id: str = "audit-clean", *, ledger_db_path: Path | None = None):
    package = build_review_package(
        BATCH_CLEAN,
        batch_id,
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
        ledger_db_path=ledger_db_path,
    )
    decision = approve_review_package(
        package.json_path,
        reviewer="Nexus Direction",
        decision="approved",
        output_dir=tmp_path / "reviews",
        ledger_db_path=ledger_db_path,
    )
    return package, tmp_path / "reviews" / f"review_{decision.review_id}.json", decision


def test_migration_v2_adds_review_tables(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"

    initialize_database(db_path)

    assert {
        "review_packages",
        "review_decisions",
        "controlled_import_attempts",
        "controlled_import_verifications",
    }.issubset(table_names(db_path))


def test_record_review_package_in_ledger(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    initialize_database(db_path)
    package = build_review_package(
        BATCH_CLEAN,
        "audit-package",
        TAXONOMIES,
        QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    repo = LedgerRepository(db_path)
    repo.record_review_package(package)
    row = repo.get_review_package("audit-package")

    assert row is not None
    assert row["batch_id"] == "audit-package"
    assert json.loads(row["metadata_json"])["gate_status"] == "ready_for_controlled_import"


def test_record_review_decision_in_ledger(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    initialize_database(db_path)
    package, _, decision = make_review(tmp_path)
    repo = LedgerRepository(db_path)
    repo.record_review_package(package)

    repo.record_review_decision(decision, package_id=package.batch_id)
    row = repo.get_review_decision(decision.review_id)

    assert row is not None
    assert row["package_id"] == package.batch_id
    assert row["decision"] == "approved"


def test_controlled_import_attempt_recorded_when_blocked_by_gate(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    report = controlled_import_manifest_directory(
        BATCH_MISMATCH,
        db_path=tmp_path / "documents.sqlite",
        batch_id="audit-blocked",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
        audit_ledger_db_path=db_path,
    )

    assert report.status is ControlledImportStatus.blocked_by_gate
    attempts = LedgerRepository(db_path).list_controlled_import_attempts("audit-blocked")
    assert len(attempts) == 1
    assert attempts[0]["status"] == "blocked_by_gate"


def test_controlled_import_attempt_recorded_when_imported(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    package, decision_path, decision = make_review(tmp_path, "audit-imported", ledger_db_path=db_path)

    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "documents.sqlite",
        batch_id="audit-imported",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
        require_review=True,
        review_package_path=package.json_path,
        review_decision_path=decision_path,
        audit_ledger_db_path=db_path,
    )

    assert report.status is ControlledImportStatus.imported
    attempts = LedgerRepository(db_path).list_controlled_import_attempts("audit-imported")
    assert attempts[0]["review_id"] == decision.review_id
    assert attempts[0]["package_id"] == package.batch_id


def test_controlled_import_verifications_recorded(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    package, decision_path, _ = make_review(tmp_path, "audit-verifications", ledger_db_path=db_path)

    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "documents.sqlite",
        batch_id="audit-verifications",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
        require_review=True,
        review_package_path=package.json_path,
        review_decision_path=decision_path,
        audit_ledger_db_path=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT check_name, passed FROM controlled_import_verifications WHERE attempt_id = ?",
            (report.attempt_id,),
        ).fetchall()
    checks = {row[0]: row[1] for row in rows}
    assert checks["gate_evaluated"] == 1
    assert checks["review_package_hash_verified"] == 1
    assert checks["ledger_write_performed"] == 1


def test_blocked_attempt_has_no_document_runs(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    report = controlled_import_manifest_directory(
        BATCH_MISMATCH,
        db_path=tmp_path / "documents.sqlite",
        batch_id="audit-blocked-runs",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
        audit_ledger_db_path=db_path,
    )

    assert report.run_ids == []
    row = LedgerRepository(db_path).get_controlled_import_attempt(report.attempt_id)
    assert row is not None
    assert json.loads(row["run_ids_json"]) == []


def test_imported_attempt_links_review_decision_and_package(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    package, decision_path, decision = make_review(tmp_path, "audit-links", ledger_db_path=db_path)

    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "documents.sqlite",
        batch_id="audit-links",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
        require_review=True,
        review_package_path=package.json_path,
        review_decision_path=decision_path,
        audit_ledger_db_path=db_path,
    )

    row = LedgerRepository(db_path).get_controlled_import_attempt(report.attempt_id)
    assert row is not None
    assert row["review_id"] == decision.review_id
    assert row["package_id"] == package.batch_id


def test_review_decision_requires_existing_package(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    initialize_database(db_path)
    package, _, decision = make_review(tmp_path)

    with pytest.raises(sqlite3.IntegrityError):
        LedgerRepository(db_path).record_review_decision(decision, package_id=package.batch_id)


def test_review_audit_metadata_json_revalidates_or_is_parseable(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    package, decision_path, _ = make_review(tmp_path, "audit-json", ledger_db_path=db_path)
    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "documents.sqlite",
        batch_id="audit-json",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
        require_review=True,
        review_package_path=package.json_path,
        review_decision_path=decision_path,
        audit_ledger_db_path=db_path,
    )

    repo = LedgerRepository(db_path)
    assert json.loads(repo.get_review_package(package.batch_id)["metadata_json"])["batch_id"] == "audit-json"
    assert json.loads(repo.get_controlled_import_attempt(report.attempt_id)["metadata_json"])["batch_id"] == "audit-json"


def test_audit_ledger_cli_option_records_package_and_import(tmp_path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "ledger.sqlite"
    monkeypatch.setattr(
        "sys.argv",
        [
            "review_package_cli",
            str(BATCH_CLEAN),
            "--batch-id",
            "audit-cli",
            "--taxonomy",
            str(TAXONOMIES[0]),
            "--taxonomy",
            str(TAXONOMIES[1]),
            "--output-dir",
            str(tmp_path / "reports"),
            "--audit-ledger",
            str(db_path),
        ],
    )
    assert review_package_main() == 0
    assert LedgerRepository(db_path).get_review_package("audit-cli") is not None
