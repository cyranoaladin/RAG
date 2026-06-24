from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rag_pedago.ledger.migrations import initialize_database
from rag_pedago.ledger.repository import LedgerRepository
from schema.document import ChunkMeta, DocumentMeta, Modality, Rights, SourceType, TypeDoc
from schema.ledger import DocumentState, DocumentStateRecord, ErrorRecord, RunRecord, RunStatus


def make_repo(tmp_path) -> LedgerRepository:
    db_path = tmp_path / "ledger.sqlite"
    initialize_database(db_path)
    return LedgerRepository(db_path)


def make_run(run_id: str = "run-001") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        started_at=datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
        status=RunStatus.running,
        command="pytest",
        created_by="test",
    )


def make_document(doc_id: str = "doc-001", rights: Rights = Rights.officiel_public) -> DocumentMeta:
    return DocumentMeta.model_validate(
        {
            "doc_id": doc_id,
            "source_uri": f"file:///data/raw/{doc_id}.md",
            "source_type": SourceType.nexus,
            "sha256": "d" * 64,
            "discovered_at": datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
            "rights": rights,
            "visibility": "internal",
            "matiere": "mathematiques",
            "type_doc": TypeDoc.cours,
        }
    )


def make_chunk(chunk_id: str = "chunk-001", doc_id: str = "doc-001", index: int = 0) -> ChunkMeta:
    return ChunkMeta.model_validate(
        {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "chunk_sha256": "e" * 64,
            "chunk_index": index,
            "chunk_type": Modality.text,
            "text": "Contenu pedagogique testable.",
            "page_start": 1,
            "page_end": 1,
            "citation_label": "Document test, p. 1",
        }
    )


def test_create_and_finish_run(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.create_run(make_run())

    repo.finish_run("run-001", RunStatus.success, report_path="data/reports/run.md")

    row = repo.get_run("run-001")
    assert row is not None
    assert row["status"] == "success"
    assert row["finished_at"] is not None
    assert row["report_path"] == "data/reports/run.md"


def test_upsert_document_from_document_meta(tmp_path) -> None:
    repo = make_repo(tmp_path)
    meta = make_document()

    repo.upsert_document(meta)
    row = repo.get_document("doc-001")

    assert row is not None
    assert row["doc_id"] == "doc-001"
    assert row["rights"] == "officiel_public"
    assert row["is_retrievable"] == 1
    assert '"doc_id": "doc-001"' in row["metadata_json"]


def test_unknown_rights_document_is_stored_but_not_retrievable(tmp_path) -> None:
    repo = make_repo(tmp_path)

    repo.upsert_document(make_document(rights=Rights.unknown))
    row = repo.get_document("doc-001")

    assert row is not None
    assert row["rights"] == "unknown"
    assert row["is_retrievable"] == 0


def test_record_state_requires_existing_document_and_run(tmp_path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(Exception):
        repo.record_state(
            DocumentStateRecord(
                doc_id="missing-doc",
                state=DocumentState.discovered,
                run_id="missing-run",
                input_sha256="d" * 64,
                updated_at=datetime.now(UTC),
            )
        )


def test_record_state_and_latest_state(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.create_run(make_run())
    repo.upsert_document(make_document())

    repo.record_state(
        DocumentStateRecord(
            doc_id="doc-001",
            state=DocumentState.discovered,
            run_id="run-001",
            input_sha256="d" * 64,
            updated_at=datetime(2026, 6, 14, 10, 1, tzinfo=UTC),
        )
    )
    repo.record_state(
        DocumentStateRecord(
            doc_id="doc-001",
            state=DocumentState.parsed,
            run_id="run-001",
            input_sha256="d" * 64,
            updated_at=datetime(2026, 6, 14, 10, 2, tzinfo=UTC),
        )
    )

    assert repo.get_latest_state("doc-001") == "parsed"


def test_upsert_chunk_requires_existing_document(tmp_path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(Exception):
        repo.upsert_chunk(make_chunk(doc_id="missing-doc"))


def test_chunk_unique_doc_index(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_document(make_document())
    repo.upsert_chunk(make_chunk(chunk_id="chunk-001", index=0))

    with pytest.raises(Exception):
        repo.upsert_chunk(make_chunk(chunk_id="chunk-002", index=0))


def test_record_error_and_list_errors(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.create_run(make_run())

    repo.record_error(
        ErrorRecord(
            error_id="err-001",
            run_id="run-001",
            step="parse",
            message="Parsing impossible",
            recoverable=True,
            created_at=datetime(2026, 6, 14, 10, 3, tzinfo=UTC),
        )
    )

    errors = repo.list_errors("run-001")
    assert len(errors) == 1
    assert errors[0]["error_id"] == "err-001"
    assert errors[0]["recoverable"] == 1

