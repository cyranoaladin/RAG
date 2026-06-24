from __future__ import annotations

import builtins
import json
import sys
from datetime import datetime, timezone

import pytest

from rag_pedago.imports.import_manifest_dir import main
from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.ledger.repository import LedgerRepository
from schema.document import Rights, SourceType, TypeDoc


@pytest.fixture(autouse=True)
def chdir_tmp_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)


def payload(
    doc_id: str,
    *,
    source_uri: str | None = None,
    sha: str = "a",
    rights: str = "officiel_public",
) -> dict[str, object]:
    return {
        "doc_id": doc_id,
        "source_uri": source_uri or f"file:///tmp/should-not-be-read/{doc_id}.pdf",
        "source_type": SourceType.upload.value,
        "sha256": sha * 64,
        "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
        "rights": rights,
        "visibility": "restricted" if rights == Rights.unknown.value else "public",
        "matiere": "mathematiques",
        "type_doc": TypeDoc.cours.value,
        "niveau": "terminale",
        "programme_version": "fixture-programme",
    }


def write_jsonl(path, lines: list[dict[str, object] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def test_import_directory_success_with_multiple_manifests(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("doc-a")])
    write_jsonl(directory / "b.jsonl", [payload("doc-b", sha="b")])

    report = import_manifest_directory(directory, db_path, batch_id="batch-ok")
    repo = LedgerRepository(db_path)

    assert report.status == "success"
    assert report.manifest_count == 2
    assert report.documents_valid == 2
    assert repo.get_document("doc-a") is not None
    assert repo.get_document("doc-b") is not None
    assert repo.get_run("batch-batch-ok-001")["status"] == "success"
    assert repo.get_run("batch-batch-ok-002")["status"] == "success"


def test_import_directory_partial_with_invalid_lines(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("doc-a"), {"doc_id": "invalid"}])

    report = import_manifest_directory(directory, db_path, batch_id="batch-partial")

    assert report.status == "quality_blocked"
    assert report.quality_report.status == "quality_blocked"
    assert report.documents_valid == 1
    assert report.documents_invalid == 1


def test_import_directory_detects_duplicate_doc_id(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("dup-doc", sha="a")])
    write_jsonl(directory / "b.jsonl", [payload("dup-doc", sha="b")])

    report = import_manifest_directory(directory, db_path, batch_id="batch-dup-doc")

    assert "dup-doc" in report.duplicate_doc_ids


def test_import_directory_detects_duplicate_source_uri(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    source_uri = "fixture://same-source"
    write_jsonl(directory / "a.jsonl", [payload("doc-a", source_uri=source_uri, sha="a")])
    write_jsonl(directory / "b.jsonl", [payload("doc-b", source_uri=source_uri, sha="b")])

    report = import_manifest_directory(directory, db_path, batch_id="batch-dup-source")

    assert source_uri in report.duplicate_source_uris


def test_import_directory_detects_duplicate_sha256(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("doc-a", sha="c")])
    write_jsonl(directory / "b.jsonl", [payload("doc-b", sha="c")])

    report = import_manifest_directory(directory, db_path, batch_id="batch-dup-sha")

    assert "c" * 64 in report.duplicate_sha256


def test_dry_run_does_not_write_ledger(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("doc-a"), {"doc_id": "invalid"}])

    report = import_manifest_directory(directory, db_path, batch_id="batch-dry", dry_run=True)

    assert report.status == "dry_run_blocked"
    assert report.quality_report.status == "quality_blocked"
    assert report.report_path.is_file()
    assert not db_path.exists()


def test_import_directory_does_not_read_source_uri(tmp_path, monkeypatch) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    guarded_uri = "file:///tmp/should-not-be-read/secret.pdf"
    write_jsonl(directory / "a.jsonl", [payload("doc-guard", source_uri=guarded_uri)])
    real_open = builtins.open

    def guarded_open(file, *args, **kwargs):
        if str(file) == "/tmp/should-not-be-read/secret.pdf":
            raise AssertionError("source_uri was opened")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    report = import_manifest_directory(directory, db_path, batch_id="batch-no-source")

    assert report.status == "success"


def test_empty_directory_fails_clearly(tmp_path) -> None:
    directory = tmp_path / "empty"
    directory.mkdir()

    with pytest.raises(ValueError, match="no JSONL manifests found"):
        import_manifest_directory(directory, tmp_path / "ledger.sqlite", batch_id="batch-empty")


def test_directory_report_written(tmp_path) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("dup-doc", sha="a")])
    write_jsonl(directory / "b.jsonl", [payload("dup-doc", sha="b")])

    report = import_manifest_directory(directory, db_path, batch_id="batch-report")
    content = report.report_path.read_text(encoding="utf-8")

    assert "batch-report" in content
    assert "manifest_count: 2" in content
    assert "## Duplicate doc_ids" in content
    assert "dup-doc" in content


def test_manifest_dir_cli_outputs_summary(tmp_path, monkeypatch, capsys) -> None:
    directory = tmp_path / "manifests"
    db_path = tmp_path / "ledger.sqlite"
    write_jsonl(directory / "a.jsonl", [payload("doc-cli", rights=Rights.unknown.value)])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_manifest_dir",
            str(directory),
            "--db-path",
            str(db_path),
            "--batch-id",
            "batch-cli",
            "--dry-run",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "manifest directory imported:" in output
    assert "batch_id: batch-cli" in output
    assert "dry_run: True" in output
    assert "documents_not_retrievable: 1" in output
