from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from rag_pedago.imports.controlled_import import (
    ControlledImportStatus,
    controlled_import_manifest_directory,
)
from rag_pedago.imports.controlled_import_cli import main
from rag_pedago.imports.quality import QualityPolicy

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


def ledger_counts(db_path: Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as conn:
        return {
            "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "states": conn.execute("SELECT COUNT(*) FROM document_states").fetchone()[0],
            "errors": conn.execute("SELECT COUNT(*) FROM errors").fetchone()[0],
        }


def test_controlled_import_blocks_problem_batch_before_ledger_write(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"

    report = controlled_import_manifest_directory(
        BATCH_PROBLEM,
        db_path=db_path,
        batch_id="problem",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is ControlledImportStatus.blocked_by_gate
    assert report.gate_status == "blocked"
    assert not db_path.exists()


def test_controlled_import_imports_clean_batch(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"

    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=db_path,
        batch_id="clean",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        priority_notions=PRIORITY_NOTIONS,
        output_dir=tmp_path / "reports",
    )

    assert report.status is ControlledImportStatus.imported
    assert report.gate_status == "ready_for_controlled_import"
    assert report.documents_not_retrievable == 0
    assert report.run_ids
    counts = ledger_counts(db_path)
    assert counts["documents"] == report.documents_valid
    assert counts["runs"] == len(report.run_ids)
    assert counts["states"] == report.documents_valid


def test_controlled_import_writes_markdown_and_json(tmp_path) -> None:
    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="files",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.markdown_path.is_file()
    assert report.json_path.is_file()
    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert payload["status"] == "imported"
    assert payload["paths"]["gate_markdown_path"]
    assert payload["guarantees"]["gate_evaluated_before_import"] is True


def test_controlled_import_cli_outputs_summary(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "controlled_import_cli",
            str(BATCH_CLEAN),
            "--batch-id",
            "cli-clean",
            "--db-path",
            str(tmp_path / "ledger.sqlite"),
            "--taxonomy",
            str(TAXONOMIES[0]),
            "--taxonomy",
            str(TAXONOMIES[1]),
            "--output-dir",
            str(tmp_path / "reports"),
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "controlled import report generated:" in output
    assert "batch_id: cli-clean" in output
    assert "status: imported" in output
    assert "gate_status: ready_for_controlled_import" in output


def test_controlled_import_does_not_read_source_uri(tmp_path) -> None:
    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="no-source-read",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert report.status is ControlledImportStatus.imported
    assert not Path("/tmp/should-not-be-read/secret.pdf").exists()


def test_controlled_import_no_network() -> None:
    module_text = (ROOT / "rag_pedago/imports/controlled_import.py").read_text(encoding="utf-8")

    assert "requests" not in module_text
    assert "httpx" not in module_text
    assert "urllib.request" not in module_text
    assert "urlopen" not in module_text


def test_controlled_import_rejects_existing_run_ids_cleanly(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    first = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=db_path,
        batch_id="duplicate-runs",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    second = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=db_path,
        batch_id="duplicate-runs",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    assert first.status is ControlledImportStatus.imported
    assert second.status is ControlledImportStatus.failed
    assert "run_id already exists" in " ".join(second.reasons)
    counts = ledger_counts(db_path)
    assert counts["runs"] == len(first.run_ids)


def test_controlled_import_report_contains_gate_and_import_paths(tmp_path) -> None:
    report = controlled_import_manifest_directory(
        BATCH_CLEAN,
        db_path=tmp_path / "ledger.sqlite",
        batch_id="paths",
        taxonomy_paths=TAXONOMIES,
        policy=QualityPolicy(),
        output_dir=tmp_path / "reports",
    )

    content = report.markdown_path.read_text(encoding="utf-8")
    assert str(report.gate_markdown_path) in content
    assert report.import_report_path is not None
    assert str(report.import_report_path) in content
    assert "Gate was evaluated before import." in content


def test_controlled_import_hash_is_cwd_independent(tmp_path, monkeypatch) -> None:
    from rag_pedago.imports import controlled_import

    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "sample.jsonl").write_text('{"doc_id": "a"}\n', encoding="utf-8")
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()

    hashes_before = controlled_import._manifest_hashes(batch)
    monkeypatch.chdir(other_cwd)
    hashes_after = controlled_import._manifest_hashes(batch)

    assert hashes_after == hashes_before
