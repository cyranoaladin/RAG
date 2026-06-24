from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rag_pedago.ledger.migrations import initialize_database
from rag_pedago.ledger.repository import LedgerRepository
from schema.document import DocumentMeta, Rights, SourceType, TypeDoc
from schema.ledger import DocumentState, DocumentStateRecord, ErrorRecord, RunRecord, RunStatus


def make_repo(tmp_path) -> LedgerRepository:
    db_path = tmp_path / "ledger.sqlite"
    initialize_database(db_path)
    return LedgerRepository(db_path)


def make_run(run_id: str) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        started_at=datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
        status=RunStatus.running,
    )


def make_document() -> DocumentMeta:
    return DocumentMeta.model_validate(
        {
            "doc_id": "doc-recovery",
            "source_uri": "file:///data/raw/recovery.md",
            "source_type": SourceType.nexus,
            "sha256": "f" * 64,
            "discovered_at": datetime(2026, 6, 14, 10, 0, tzinfo=UTC),
            "rights": Rights.usage_interne,
            "visibility": "internal",
            "matiere": "nsi",
            "type_doc": TypeDoc.cours,
        }
    )


def state(run_id: str, value: DocumentState, minute: int) -> DocumentStateRecord:
    return DocumentStateRecord(
        doc_id="doc-recovery",
        state=value,
        run_id=run_id,
        input_sha256="f" * 64,
        updated_at=datetime(2026, 6, 14, 10, minute, tzinfo=UTC),
    )


def test_recovery_after_failed_run(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.create_run(make_run("run-1"))
    repo.upsert_document(make_document())
    repo.record_state(state("run-1", DocumentState.discovered, 1))
    repo.record_error(
        ErrorRecord(
            error_id="err-recovery",
            run_id="run-1",
            doc_id="doc-recovery",
            step="parse",
            message="Temporary parser failure",
            recoverable=True,
            created_at=datetime(2026, 6, 14, 10, 2, tzinfo=UTC),
        )
    )
    repo.finish_run("run-1", RunStatus.failed)

    repo.create_run(make_run("run-2"))
    repo.record_state(state("run-2", DocumentState.parsed, 3))

    assert repo.get_latest_state("doc-recovery") == "parsed"
    assert repo.get_run("run-1")["status"] == "failed"


def test_transactions_prevent_partial_state(tmp_path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(Exception):
        with repo.transaction() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, started_at, status) VALUES (?, ?, ?)",
                ("partial-run", "2026-06-14T10:00:00+00:00", "running"),
            )
            conn.execute(
                "INSERT INTO document_states (doc_id, state, run_id, updated_at) "
                "VALUES (?, ?, ?, ?)",
                ("missing-doc", "discovered", "partial-run", "2026-06-14T10:01:00+00:00"),
            )

    assert repo.get_run("partial-run") is None

