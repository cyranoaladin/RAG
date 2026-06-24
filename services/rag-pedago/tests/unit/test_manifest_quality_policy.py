from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import pytest

from rag_pedago.imports.import_manifest_dir import main
from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.quality import QualityPolicy, Severity, evaluate_manifest_directory_quality
from schema.document import Rights, SourceType


@pytest.fixture(autouse=True)
def chdir_tmp_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)


def payload(
    doc_id: str,
    *,
    source_uri: str | None = None,
    sha: str = "a",
    rights: str = "officiel_public",
    programme_version: str | None = "fixture-programme",
    niveau: str | None = "terminale",
    type_doc: str = "cours",
    epreuve: str | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "doc_id": doc_id,
        "source_uri": source_uri or f"fixture://{doc_id}",
        "source_type": SourceType.upload.value,
        "sha256": sha * 64,
        "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=UTC).isoformat(),
        "rights": rights,
        "visibility": "restricted" if rights == Rights.unknown.value else "public",
        "matiere": "mathematiques",
        "type_doc": type_doc,
    }
    if programme_version is not None:
        data["programme_version"] = programme_version
    if niveau is not None:
        data["niveau"] = niveau
    if epreuve is not None:
        data["epreuve"] = epreuve
    return data


def write_jsonl(path, lines: list[dict[str, object] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def test_duplicate_doc_id_exact_is_warning(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("same", sha="a")])
    write_jsonl(directory / "b.jsonl", [payload("same", sha="a")])
    directory_report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)

    quality = evaluate_manifest_directory_quality(directory_report, QualityPolicy())

    assert "same" in directory_report.duplicate_doc_id_exact
    assert any(issue.code == "duplicate_doc_id_exact" and issue.severity is Severity.warning for issue in quality.issues)
    assert quality.status == "quality_warn"


def test_duplicate_doc_id_conflict_blocks(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("same", sha="a")])
    write_jsonl(directory / "b.jsonl", [payload("same", sha="b")])
    directory_report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)

    quality = evaluate_manifest_directory_quality(directory_report, QualityPolicy())

    assert "same" in directory_report.duplicate_doc_id_conflicts
    assert quality.status == "quality_blocked"
    assert any(issue.code == "duplicate_doc_id_conflict" for issue in quality.issues)


def test_duplicate_source_uri_blocks_in_strict_policy(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("a", source_uri="fixture://same", sha="a")])
    write_jsonl(directory / "b.jsonl", [payload("b", source_uri="fixture://same", sha="b")])
    directory_report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)

    quality = evaluate_manifest_directory_quality(directory_report, QualityPolicy())

    assert quality.status == "quality_blocked"
    assert any(issue.code == "duplicate_source_uri" for issue in quality.issues)


def test_duplicate_sha256_warns_by_default(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("a", sha="c")])
    write_jsonl(directory / "b.jsonl", [payload("b", sha="c")])
    directory_report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)

    quality = evaluate_manifest_directory_quality(directory_report, QualityPolicy())

    assert quality.status == "quality_warn"
    assert any(issue.code == "duplicate_sha256" and issue.severity is Severity.warning for issue in quality.issues)


def test_unknown_rights_warns_by_default(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("unknown", rights=Rights.unknown.value)])
    directory_report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)

    quality = evaluate_manifest_directory_quality(directory_report, QualityPolicy())

    assert quality.status == "quality_warn"
    assert any(issue.code == "unknown_rights" and issue.severity is Severity.warning for issue in quality.issues)


def test_unknown_rights_blocks_when_policy_requires(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("unknown", rights=Rights.unknown.value)])
    directory_report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)

    quality = evaluate_manifest_directory_quality(
        directory_report,
        QualityPolicy(block_on_unknown_rights=True),
    )

    assert quality.status == "quality_blocked"
    assert any(issue.code == "unknown_rights" and issue.severity is Severity.error for issue in quality.issues)


def test_invalid_lines_block_by_default(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [{"doc_id": "invalid"}])
    directory_report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", dry_run=True)

    quality = evaluate_manifest_directory_quality(directory_report, QualityPolicy())

    assert quality.status == "quality_blocked"
    assert any(issue.code == "invalid_lines" for issue in quality.issues)


def test_dry_run_blocked_does_not_write_ledger(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [{"doc_id": "invalid"}])

    report = import_manifest_directory(directory, db_path, batch_id="blocked-dry", dry_run=True)

    assert report.status == "dry_run_blocked"
    assert report.quality_report.status == "quality_blocked"
    assert not db_path.exists()


def test_real_import_blocked_creates_no_runs(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [{"doc_id": "invalid"}])

    report = import_manifest_directory(directory, db_path, batch_id="blocked-real")

    assert report.status == "quality_blocked"
    assert report.quality_report.status == "quality_blocked"
    assert not db_path.exists()


def test_report_contains_quality_section(tmp_path) -> None:
    directory = tmp_path / "manifests"
    write_jsonl(directory / "a.jsonl", [payload("unknown", rights=Rights.unknown.value)])

    report = import_manifest_directory(directory, tmp_path / "ledger.sqlite", batch_id="quality-report", dry_run=True)
    content = report.report_path.read_text(encoding="utf-8")

    assert "## Quality policy" in content
    assert "## Quality issues" in content
    assert "| warning | unknown_rights | unknown | rights |" in content
    assert "Import decision:" in content


def test_cli_strict_outputs_quality_status(tmp_path, monkeypatch, capsys) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("unknown", rights=Rights.unknown.value)])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_manifest_dir",
            str(directory),
            "--db-path",
            str(db_path),
            "--batch-id",
            "strict-cli",
            "--strict",
            "--dry-run",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "quality_status: quality_blocked" in output
    assert "blocking_issue_count: 1" in output


def test_cli_allow_unknown_rights_downgrades_unknown_rights(tmp_path, monkeypatch, capsys) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("unknown", rights=Rights.unknown.value)])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_manifest_dir",
            str(directory),
            "--db-path",
            str(db_path),
            "--batch-id",
            "allow-cli",
            "--strict",
            "--allow-unknown-rights",
            "--dry-run",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "quality_status: quality_warn" in output
    assert "blocking_issue_count: 0" in output
