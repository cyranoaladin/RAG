from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import pytest

from rag_pedago.imports.manifest import import_manifest
from rag_pedago.ledger.repository import LedgerRepository
from schema.document import Candidat, Niveau, Rights, SourceType, StatutEnseignement, TypeDoc, Voie


@pytest.fixture(autouse=True)
def chdir_tmp_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)


def document_payload(doc_id: str, rights: str = "officiel_public", source_uri: str | None = None) -> dict[str, object]:
    return {
        "doc_id": doc_id,
        "source_uri": source_uri or f"file:///does/not/exist/{doc_id}.pdf",
        "source_type": SourceType.eduscol.value,
        "sha256": "a" * 64,
        "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc).isoformat(),
        "rights": rights,
        "visibility": "public" if rights == "officiel_public" else "internal",
        "niveau": Niveau.terminale.value,
        "voie": Voie.generale.value,
        "matiere": "mathematiques",
        "statut_enseignement": StatutEnseignement.specialite.value,
        "type_doc": TypeDoc.cours.value,
        "candidat": Candidat.scolarise.value,
        "programme_version": "terminale-specialite-2020",
        "notions": ["suites"],
        "competences": ["raisonner"],
    }


def write_manifest(path, lines: list[dict[str, object] | str]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            if isinstance(line, str):
                handle.write(line + "\n")
            else:
                handle.write(json.dumps(line) + "\n")


def test_import_manifest_success_with_valid_lines(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [document_payload("doc-1"), document_payload("doc-2")])

    report = import_manifest(manifest, db_path, run_id="run-success")
    repo = LedgerRepository(db_path)

    assert report.status == "success"
    assert report.documents_valid == 2
    assert repo.get_run("run-success")["status"] == "success"
    assert repo.get_document("doc-1") is not None
    assert repo.get_latest_state("doc-1") == "discovered"
    assert repo.get_latest_state("doc-2") == "discovered"


def test_import_manifest_partial_with_invalid_line(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    invalid = {"doc_id": "invalid-without-rights"}
    write_manifest(manifest, [document_payload("doc-valid"), invalid])

    report = import_manifest(manifest, db_path, run_id="run-partial")
    repo = LedgerRepository(db_path)

    assert report.status == "partial"
    assert report.documents_valid == 1
    assert report.documents_invalid == 1
    assert repo.get_document("doc-valid") is not None
    assert len(repo.list_errors("run-partial")) == 1


def test_import_manifest_failed_if_no_valid_documents(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [{"doc_id": "invalid"}])

    report = import_manifest(manifest, db_path, run_id="run-failed")
    repo = LedgerRepository(db_path)

    assert report.status == "failed"
    assert report.documents_valid == 0
    assert report.documents_invalid == 1
    assert repo.get_run("run-failed")["status"] == "failed"
    assert len(repo.list_errors("run-failed")) == 1


def test_import_manifest_rights_unknown_stored_not_retrievable(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [document_payload("doc-unknown", rights=Rights.unknown.value)])

    report = import_manifest(manifest, db_path, run_id="run-unknown")
    row = LedgerRepository(db_path).get_document("doc-unknown")

    assert report.documents_not_retrievable == 1
    assert row["is_retrievable"] == 0


def test_import_manifest_idempotent_documents(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [document_payload("doc-idempotent")])

    import_manifest(manifest, db_path, run_id="run-1")
    import_manifest(manifest, db_path, run_id="run-2")

    repo = LedgerRepository(db_path)
    with repo.transaction() as conn:
        documents_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        runs_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        states_count = conn.execute("SELECT COUNT(*) FROM document_states").fetchone()[0]

    assert documents_count == 1
    assert runs_count == 2
    assert states_count == 2


def test_import_manifest_does_not_access_source_uri(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    missing_path = tmp_path / "missing-source.pdf"
    write_manifest(
        manifest,
        [document_payload("doc-missing-source", source_uri=f"file://{missing_path}")],
    )

    report = import_manifest(manifest, db_path, run_id="run-no-source-read")

    assert report.status == "success"
    assert LedgerRepository(db_path).get_document("doc-missing-source") is not None


def test_import_manifest_report_written(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [document_payload("doc-report"), {"doc_id": "invalid"}])

    report = import_manifest(manifest, db_path, run_id="run-report")
    content = report.report_path.read_text(encoding="utf-8")

    assert report.report_path.is_file()
    assert "run-report" in content
    assert "documents_valid: 1" in content
    assert "documents_invalid: 1" in content


def test_import_manifest_no_network_modules_loaded(tmp_path) -> None:
    manifest = tmp_path / "manifest.jsonl"
    db_path = tmp_path / "ledger.sqlite"
    write_manifest(manifest, [document_payload("doc-no-network")])

    import_manifest(manifest, db_path, run_id="run-no-network")

    assert "requests" not in sys.modules
    assert "httpx" not in sys.modules
    assert "urllib.request" not in sys.modules
