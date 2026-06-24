from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rag_pedago.ledger.diagnostics import EXPECTED_TABLES, check_integrity
from rag_pedago.ledger.migrations import MIGRATIONS, initialize_database
from rag_pedago.ledger.models import DOCUMENT_STATES, RUN_STATUSES
from rag_pedago.ledger.repository import LedgerRepository
from schema.document import ChunkMeta, DocumentMeta, Modality, Rights, SourceType, TypeDoc
from schema.ledger import DocumentState, ErrorRecord, RunRecord, RunStatus


def make_repo(tmp_path) -> LedgerRepository:
    db_path = tmp_path / "ledger.sqlite"
    initialize_database(db_path)
    return LedgerRepository(db_path)


def make_run(run_id: str = "run-001") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        started_at=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
        status=RunStatus.running,
    )


def make_document(doc_id: str = "doc-001", sha: str = "a") -> DocumentMeta:
    return DocumentMeta.model_validate(
        {
            "doc_id": doc_id,
            "source_uri": f"file:///data/raw/{doc_id}.md",
            "source_type": SourceType.nexus,
            "sha256": sha * 64,
            "discovered_at": datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
            "rights": Rights.officiel_public,
            "visibility": "public",
            "matiere": "mathematiques",
            "type_doc": TypeDoc.cours,
        }
    )


def make_chunk(
    chunk_id: str = "chunk-001",
    doc_id: str = "doc-001",
    index: int = 0,
    text: str = "Premier contenu.",
    citation_label: str = "Doc test, p. 1",
) -> ChunkMeta:
    return ChunkMeta.model_validate(
        {
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "chunk_sha256": "b" * 64,
            "chunk_index": index,
            "chunk_type": Modality.text,
            "text": text,
            "page_start": 1,
            "page_end": 1,
            "citation_label": citation_label,
        }
    )


def test_finish_unknown_run_fails(tmp_path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(ValueError, match="run not found"):
        repo.finish_run("missing-run", RunStatus.success)


def test_get_latest_state_unknown_document_returns_none(tmp_path) -> None:
    repo = make_repo(tmp_path)

    assert repo.get_latest_state("missing-doc") is None


def test_record_error_unknown_run_fails(tmp_path) -> None:
    repo = make_repo(tmp_path)

    with pytest.raises(Exception):
        repo.record_error(
            ErrorRecord(
                error_id="err-unknown-run",
                run_id="missing-run",
                step="parse",
                message="No run",
                created_at=datetime.now(timezone.utc),
            )
        )


def test_record_error_unknown_document_fails_if_doc_id_given(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.create_run(make_run())

    with pytest.raises(Exception):
        repo.record_error(
            ErrorRecord(
                error_id="err-unknown-doc",
                run_id="run-001",
                doc_id="missing-doc",
                step="parse",
                message="No doc",
                created_at=datetime.now(timezone.utc),
            )
        )


def test_upsert_document_updates_updated_at_but_preserves_created_at(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_document(make_document(sha="a"))
    first = repo.get_document("doc-001")

    repo.upsert_document(make_document(sha="c"))
    second = repo.get_document("doc-001")

    assert first is not None
    assert second is not None
    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] != first["updated_at"]
    assert second["sha256"] == "c" * 64


def test_upsert_chunk_same_chunk_id_updates_metadata(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_document(make_document())
    repo.upsert_chunk(make_chunk(text="Version 1", citation_label="v1"))
    repo.upsert_chunk(make_chunk(text="Version 2", citation_label="v2"))

    chunk = repo.get_chunk_meta("chunk-001")

    assert chunk is not None
    assert chunk.text == "Version 2"
    assert chunk.citation_label == "v2"


def test_upsert_chunk_different_id_same_doc_index_fails(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_document(make_document())
    repo.upsert_chunk(make_chunk(chunk_id="chunk-001", index=0))

    with pytest.raises(Exception):
        repo.upsert_chunk(make_chunk(chunk_id="chunk-002", index=0))


def test_get_document_meta_revalidates_pydantic_model(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_document(make_document())

    meta = repo.get_document_meta("doc-001")

    assert isinstance(meta, DocumentMeta)
    assert meta.doc_id == "doc-001"


def test_get_chunk_meta_revalidates_pydantic_model(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_document(make_document())
    repo.upsert_chunk(make_chunk())

    chunk = repo.get_chunk_meta("chunk-001")

    assert isinstance(chunk, ChunkMeta)
    assert chunk.chunk_id == "chunk-001"


def test_corrupt_document_metadata_json_raises_clear_error(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.upsert_document(make_document())
    with repo.transaction() as conn:
        conn.execute("UPDATE documents SET metadata_json = ? WHERE doc_id = ?", ("{bad-json", "doc-001"))

    with pytest.raises(ValueError, match="invalid document metadata_json"):
        repo.get_document_meta("doc-001")


def test_diagnostic_reports_expected_tables_and_counts(tmp_path) -> None:
    repo = make_repo(tmp_path)
    repo.create_run(make_run())
    repo.upsert_document(make_document())
    repo.upsert_chunk(make_chunk())

    diagnostic = check_integrity(repo.db_path)

    assert diagnostic["integrity_check"] == "ok"
    assert diagnostic["foreign_key_check"] == []
    assert set(diagnostic["tables_present"]) >= EXPECTED_TABLES
    assert diagnostic["foreign_keys_enabled"] is True
    assert diagnostic["counts"]["runs"] == 1
    assert diagnostic["counts"]["documents"] == 1
    assert diagnostic["counts"]["chunks"] == 1
    assert diagnostic["migrations_count"] == len(MIGRATIONS)


def test_sqlite_allowed_values_match_python_enums() -> None:
    assert set(RUN_STATUSES) == {status.value for status in RunStatus}
    assert set(DOCUMENT_STATES) == {state.value for state in DocumentState}


def test_migrations_versioning_records_description_once(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"
    initialize_database(db_path)
    initialize_database(db_path)

    repo = LedgerRepository(db_path)
    with repo.transaction() as conn:
        rows = conn.execute(
            "SELECT version, description FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert [(row["version"], row["description"]) for row in rows] == [
        (migration.version, migration.description) for migration in MIGRATIONS
    ]
