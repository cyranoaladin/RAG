from __future__ import annotations

import builtins
import json
import re
import sys
from datetime import datetime, timezone

import pytest

from rag_pedago.imports.import_manifest import main
from rag_pedago.imports.manifest import import_manifest
from rag_pedago.ledger.repository import LedgerRepository
from schema.document import Rights, SourceType, TypeDoc


@pytest.fixture(autouse=True)
def chdir_tmp_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)


def payload(doc_id: str, rights: str = "officiel_public", source_uri: str | None = None) -> dict[str, object]:
    return {
        "doc_id": doc_id,
        "source_uri": source_uri or f"file:///tmp/should-not-be-read/{doc_id}.pdf",
        "source_type": SourceType.upload.value,
        "sha256": "1" * 64,
        "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
        "rights": rights,
        "visibility": "restricted" if rights == Rights.unknown.value else "public",
        "matiere": "mathematiques",
        "type_doc": TypeDoc.cours.value,
    }


def write_manifest(path, lines: list[dict[str, object] | str]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def test_manifest_sha256_is_stable(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [payload("doc-hash")])

    first = import_manifest(manifest, db_path, run_id="run-hash-1")
    second = import_manifest(manifest, db_path, run_id="run-hash-2")

    assert re.fullmatch(r"[a-f0-9]{64}", first.manifest_sha256)
    assert first.manifest_sha256 == second.manifest_sha256


def test_existing_run_id_fails_without_partial_writes(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [payload("doc-fixed")])
    import_manifest(manifest, db_path, run_id="fixed")

    with pytest.raises(ValueError, match="run_id already exists: fixed"):
        import_manifest(manifest, db_path, run_id="fixed")

    repo = LedgerRepository(db_path)
    with repo.transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM document_states").fetchone()[0] == 1


def test_auditable_report_sections_and_documents(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(
        manifest,
        [
            payload("doc-valid"),
            payload("doc-unknown", rights=Rights.unknown.value),
            {"doc_id": "invalid-doc"},
        ],
    )

    report = import_manifest(manifest, db_path, run_id="run-audit")
    content = report.report_path.read_text(encoding="utf-8")

    assert "## Summary" in content
    assert "manifest_sha256:" in content
    assert "## Valid documents" in content
    assert "doc-valid | officiel_public | True | upload | None | mathematiques | cours" in content
    assert "## Non retrievable documents" in content
    assert "doc-unknown | unknown | rights=unknown" in content
    assert "## Invalid lines" in content
    assert "3 | validation_error | invalid-doc |" in content
    assert "No source_uri was opened." in content


def test_source_uri_file_is_never_opened(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    guarded_uri = "file:///tmp/should-not-be-read/secret.pdf"
    write_manifest(manifest, [payload("doc-guard", source_uri=guarded_uri)])
    real_open = builtins.open

    def guarded_open(file, *args, **kwargs):
        if str(file) == "/tmp/should-not-be-read/secret.pdf":
            raise AssertionError("source_uri was opened")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)

    report = import_manifest(manifest, db_path, run_id="run-source-uri")

    assert report.status == "success"


def test_manifest_module_static_no_network_imports() -> None:
    import rag_pedago.imports.manifest as manifest_module

    source = manifest_module.Path(manifest_module.__file__).read_text(encoding="utf-8")

    assert "requests" not in source
    assert "httpx" not in source
    assert "urllib.request" not in source
    assert "urlopen" not in source


def test_normalized_errors_for_json_and_validation(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, ['{"doc_id": "bad-json"', {"doc_id": "bad-meta"}])

    report = import_manifest(manifest, db_path, run_id="run-errors")

    assert report.errors[0].error_type == "json_decode"
    assert report.errors[0].doc_id is None
    assert report.errors[0].raw_excerpt == '{"doc_id": "bad-json"'
    assert report.errors[1].error_type == "validation_error"
    assert report.errors[1].doc_id == "bad-meta"


def test_counters_are_coherent_and_empty_lines_ignored(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    manifest.write_text(
        "\n"
        + json.dumps(payload("doc-valid"))
        + "\n\n"
        + json.dumps(payload("doc-unknown", rights=Rights.unknown.value))
        + "\n"
        + json.dumps({"doc_id": "invalid"})
        + "\n",
        encoding="utf-8",
    )

    report = import_manifest(manifest, db_path, run_id="run-counters")

    assert report.lines_read == report.documents_valid + report.documents_invalid
    assert report.lines_read == 3
    assert report.documents_valid == 2
    assert report.documents_not_retrievable == 1
    assert report.documents_retrievable + report.documents_not_retrievable == report.documents_valid


def test_cli_outputs_manifest_sha256_and_not_retrievable(tmp_path, monkeypatch, capsys) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [payload("doc-cli", rights=Rights.unknown.value)])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_manifest",
            str(manifest),
            "--db-path",
            str(db_path),
            "--run-id",
            "run-cli",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "manifest_sha256:" in output
    assert "documents_not_retrievable: 1" in output

