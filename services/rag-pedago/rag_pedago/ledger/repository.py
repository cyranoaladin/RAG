from __future__ import annotations

import json
import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from rag_pedago.ledger.db import connect, transaction
from schema.document import ChunkMeta, DocumentMeta
from schema.ledger import DocumentStateRecord, ErrorRecord, RunRecord, RunStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump_model(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


def _sha256_model(model: Any) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _load_metadata_json(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {label} metadata_json") from exc


class LedgerRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with transaction(self.db_path) as conn:
            yield conn

    def create_run(self, run: RunRecord) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, started_at, finished_at, status, command, git_commit,
                    report_path, created_by, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                    run.status.value,
                    run.command,
                    run.git_commit,
                    run.report_path,
                    run.created_by,
                    run.notes,
                ),
            )

    def finish_run(self, run_id: str, status: RunStatus, report_path: str | None = None) -> None:
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, report_path = COALESCE(?, report_path)
                WHERE run_id = ?
                """,
                (status.value, _now_iso(), report_path, run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"run not found: {run_id}")

    def upsert_document(self, meta: DocumentMeta) -> None:
        now = _now_iso()
        metadata_json = _json_dump_model(meta)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    doc_id, source_uri, source_type, sha256, rights, visibility,
                    niveau, voie, matiere, statut_enseignement, type_doc, epreuve,
                    candidat, is_retrievable, created_at, updated_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    source_uri = excluded.source_uri,
                    source_type = excluded.source_type,
                    sha256 = excluded.sha256,
                    rights = excluded.rights,
                    visibility = excluded.visibility,
                    niveau = excluded.niveau,
                    voie = excluded.voie,
                    matiere = excluded.matiere,
                    statut_enseignement = excluded.statut_enseignement,
                    type_doc = excluded.type_doc,
                    epreuve = excluded.epreuve,
                    candidat = excluded.candidat,
                    is_retrievable = excluded.is_retrievable,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    meta.doc_id,
                    meta.source_uri,
                    meta.source_type.value,
                    meta.sha256,
                    meta.rights.value,
                    meta.visibility,
                    meta.niveau.value if meta.niveau else None,
                    meta.voie.value,
                    meta.matiere,
                    meta.statut_enseignement.value,
                    meta.type_doc.value,
                    meta.epreuve.value,
                    meta.candidat.value,
                    1 if meta.is_retrievable else 0,
                    now,
                    now,
                    metadata_json,
                ),
            )

    def record_state(self, record: DocumentStateRecord) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO document_states (doc_id, state, run_id, input_sha256, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.doc_id,
                    record.state.value,
                    record.run_id,
                    record.input_sha256,
                    record.updated_at.isoformat(),
                ),
            )

    def upsert_chunk(self, chunk: ChunkMeta) -> None:
        metadata_json = _json_dump_model(chunk)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO chunks (
                    chunk_id, doc_id, chunk_index, chunk_sha256, page_start, page_end,
                    char_count, chunk_type, citation_label, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    chunk_sha256 = excluded.chunk_sha256,
                    page_start = excluded.page_start,
                    page_end = excluded.page_end,
                    char_count = excluded.char_count,
                    chunk_type = excluded.chunk_type,
                    citation_label = excluded.citation_label,
                    metadata_json = excluded.metadata_json
                """,
                (
                    chunk.chunk_id,
                    chunk.doc_id,
                    chunk.chunk_index,
                    chunk.chunk_sha256,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.char_count,
                    chunk.chunk_type.value,
                    chunk.citation_label,
                    metadata_json,
                    _now_iso(),
                ),
            )

    def record_error(self, error: ErrorRecord) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO errors (
                    error_id, run_id, doc_id, step, message, recoverable, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    error.error_id,
                    error.run_id,
                    error.doc_id,
                    error.step,
                    error.message,
                    1 if error.recoverable else 0,
                    error.created_at.isoformat(),
                ),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_dict(row)

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return _row_to_dict(row)

    def get_document_meta(self, doc_id: str) -> DocumentMeta | None:
        row = self.get_document(doc_id)
        if row is None:
            return None
        payload = _load_metadata_json(row["metadata_json"], "document")
        try:
            return DocumentMeta.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"invalid document metadata_json for {doc_id}") from exc

    def get_chunk_meta(self, chunk_id: str) -> ChunkMeta | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT metadata_json FROM chunks WHERE chunk_id = ?",
                (chunk_id,),
            ).fetchone()
        if row is None:
            return None
        payload = _load_metadata_json(row["metadata_json"], "chunk")
        try:
            return ChunkMeta.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(f"invalid chunk metadata_json for {chunk_id}") from exc

    def get_latest_state(self, doc_id: str) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT state
                FROM document_states
                WHERE doc_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (doc_id,),
            ).fetchone()
        return None if row is None else str(row["state"])

    def list_errors(self, run_id: str) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM errors WHERE run_id = ? ORDER BY created_at, error_id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_review_package(self, package: Any) -> None:
        metadata_json = _json_dump_model(package)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO review_packages (
                    package_id, batch_id, status, gate_status, readiness_status,
                    coverage_status, review_package_sha256, gate_json_sha256,
                    readiness_json_sha256, coverage_json_sha256,
                    official_reference_sha256, manifests_sha256_json,
                    taxonomy_sha256_json, package_json_path, package_markdown_path,
                    created_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(package_id) DO UPDATE SET
                    status = excluded.status,
                    gate_status = excluded.gate_status,
                    readiness_status = excluded.readiness_status,
                    coverage_status = excluded.coverage_status,
                    review_package_sha256 = excluded.review_package_sha256,
                    gate_json_sha256 = excluded.gate_json_sha256,
                    readiness_json_sha256 = excluded.readiness_json_sha256,
                    coverage_json_sha256 = excluded.coverage_json_sha256,
                    official_reference_sha256 = excluded.official_reference_sha256,
                    manifests_sha256_json = excluded.manifests_sha256_json,
                    taxonomy_sha256_json = excluded.taxonomy_sha256_json,
                    package_json_path = excluded.package_json_path,
                    package_markdown_path = excluded.package_markdown_path,
                    metadata_json = excluded.metadata_json
                """,
                (
                    package.batch_id,
                    package.batch_id,
                    package.status.value,
                    package.gate_status,
                    package.readiness_status,
                    package.coverage_status,
                    _sha256_model(package),
                    package.gate_json_sha256,
                    package.readiness_json_sha256,
                    package.coverage_json_sha256,
                    package.official_reference_sha256,
                    json.dumps(package.manifests_sha256, ensure_ascii=False, sort_keys=True),
                    json.dumps(package.taxonomy_sha256, ensure_ascii=False, sort_keys=True),
                    str(package.json_path),
                    str(package.markdown_path),
                    package.generated_at.isoformat(),
                    metadata_json,
                ),
            )

    def record_review_decision(
        self,
        decision: Any,
        package_id: str,
        decision_json_path: str | None = None,
    ) -> None:
        metadata_json = _json_dump_model(decision)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO review_decisions (
                    review_id, package_id, batch_id, decision, reviewer, reviewed_at,
                    review_package_sha256, gate_json_sha256, notes,
                    decision_json_path, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    decision = excluded.decision,
                    reviewer = excluded.reviewer,
                    reviewed_at = excluded.reviewed_at,
                    review_package_sha256 = excluded.review_package_sha256,
                    gate_json_sha256 = excluded.gate_json_sha256,
                    notes = excluded.notes,
                    decision_json_path = excluded.decision_json_path,
                    metadata_json = excluded.metadata_json
                """,
                (
                    decision.review_id,
                    package_id,
                    decision.batch_id,
                    decision.decision,
                    decision.reviewer,
                    decision.reviewed_at.isoformat(),
                    decision.review_package_sha256,
                    decision.gate_json_sha256,
                    decision.notes,
                    decision_json_path,
                    metadata_json,
                ),
            )

    def record_controlled_import_attempt(self, report: Any) -> None:
        metadata_json = _json_dump_model(report)
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO controlled_import_attempts (
                    attempt_id, batch_id, status, gate_status, review_required,
                    review_id, package_id, documents_valid, documents_invalid,
                    documents_not_retrievable, run_ids_json, reasons_json,
                    report_markdown_path, report_json_path, created_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO UPDATE SET
                    status = excluded.status,
                    gate_status = excluded.gate_status,
                    review_required = excluded.review_required,
                    review_id = excluded.review_id,
                    package_id = excluded.package_id,
                    documents_valid = excluded.documents_valid,
                    documents_invalid = excluded.documents_invalid,
                    documents_not_retrievable = excluded.documents_not_retrievable,
                    run_ids_json = excluded.run_ids_json,
                    reasons_json = excluded.reasons_json,
                    report_markdown_path = excluded.report_markdown_path,
                    report_json_path = excluded.report_json_path,
                    metadata_json = excluded.metadata_json
                """,
                (
                    report.attempt_id,
                    report.batch_id,
                    report.status.value,
                    report.gate_status,
                    1 if report.review_required else 0,
                    report.review_id,
                    report.package_id,
                    report.documents_valid,
                    report.documents_invalid,
                    report.documents_not_retrievable,
                    json.dumps(report.run_ids, ensure_ascii=False),
                    json.dumps(report.reasons, ensure_ascii=False),
                    str(report.markdown_path),
                    str(report.json_path),
                    _now_iso(),
                    metadata_json,
                ),
            )

    def record_controlled_import_verification(
        self,
        attempt_id: str,
        check_name: str,
        passed: bool,
        message: str | None = None,
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO controlled_import_verifications (
                    attempt_id, check_name, passed, message, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (attempt_id, check_name, 1 if passed else 0, message, _now_iso()),
            )

    def get_review_package(self, package_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM review_packages WHERE package_id = ?",
                (package_id,),
            ).fetchone()
        return _row_to_dict(row)

    def get_review_decision(self, review_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM review_decisions WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return _row_to_dict(row)

    def get_controlled_import_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM controlled_import_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        return _row_to_dict(row)

    def list_controlled_import_attempts(self, batch_id: str | None = None) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            if batch_id is None:
                rows = conn.execute(
                    "SELECT * FROM controlled_import_attempts ORDER BY created_at, attempt_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM controlled_import_attempts
                    WHERE batch_id = ?
                    ORDER BY created_at, attempt_id
                    """,
                    (batch_id,),
                ).fetchall()
        return [dict(row) for row in rows]
