from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rag_pedago.imports.quality import (
    QualityPolicy,
    QualityReport,
    evaluate_manifest_directory_quality,
)
from rag_pedago.ledger.migrations import DEFAULT_LEDGER_PATH, initialize_database
from rag_pedago.ledger.repository import LedgerRepository
from schema.document import DocumentMeta
from schema.ledger import DocumentState, DocumentStateRecord, ErrorRecord, RunRecord, RunStatus


class ImportLineError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: int
    message: str
    error_type: str
    doc_id: str | None = None
    raw_excerpt: str | None = None


class ImportedDocumentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    rights: str
    is_retrievable: bool
    source_type: str
    niveau: str | None = None
    matiere: str
    type_doc: str
    non_retrievable_reason: str | None = None


class ImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    run_id: str
    manifest_path: Path
    manifest_sha256: str
    lines_read: int = 0
    documents_valid: int = 0
    documents_invalid: int = 0
    documents_retrievable: int = 0
    documents_not_retrievable: int = 0
    valid_doc_ids: list[str] = Field(default_factory=list)
    not_retrievable_doc_ids: list[str] = Field(default_factory=list)
    valid_documents: list[ImportedDocumentSummary] = Field(default_factory=list)
    errors: list[ImportLineError] = Field(default_factory=list)
    report_path: Path
    status: str


class DirectoryImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    batch_id: str
    directory_path: Path
    manifest_count: int
    manifest_paths: list[Path]
    lines_read: int
    documents_valid: int
    documents_invalid: int
    documents_retrievable: int
    documents_not_retrievable: int
    duplicate_doc_ids: list[str] = Field(default_factory=list)
    duplicate_doc_id_exact: list[str] = Field(default_factory=list)
    duplicate_doc_id_conflicts: list[str] = Field(default_factory=list)
    duplicate_source_uris: list[str] = Field(default_factory=list)
    duplicate_sha256: list[str] = Field(default_factory=list)
    valid_metas: list[DocumentMeta] = Field(default_factory=list)
    invalid_lines: list[ImportLineError] = Field(default_factory=list)
    quality_report: QualityReport
    run_ids: list[str] = Field(default_factory=list)
    dry_run: bool
    status: str
    report_path: Path


def _new_run_id() -> str:
    return f"manifest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"


def _report_path_for(run_id: str) -> Path:
    return Path("data/reports") / f"manifest_import_{run_id}.md"


def _new_batch_id() -> str:
    return f"batch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"


def _directory_report_path(batch_id: str) -> Path:
    return Path("data/reports") / f"manifest_directory_import_{batch_id}.md"


def _manifest_sha256(manifest_path: Path) -> str:
    digest = hashlib.sha256()
    with manifest_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _document_summary(meta: DocumentMeta) -> ImportedDocumentSummary:
    reason = None if meta.is_retrievable else f"rights={meta.rights.value}"
    return ImportedDocumentSummary(
        doc_id=meta.doc_id,
        rights=meta.rights.value,
        is_retrievable=meta.is_retrievable,
        source_type=meta.source_type.value,
        niveau=meta.niveau.value if meta.niveau else None,
        matiere=meta.matiere,
        type_doc=meta.type_doc.value,
        non_retrievable_reason=reason,
    )


def _write_markdown_report(report: ImportReport) -> None:
    report.report_path.parent.mkdir(parents=True, exist_ok=True)
    valid_lines = "\n".join(
        "- {doc_id} | {rights} | {is_retrievable} | {source_type} | {niveau} | {matiere} | {type_doc}".format(
            **summary.model_dump()
        )
        for summary in report.valid_documents
    )
    if not valid_lines:
        valid_lines = "- none"

    non_retrievable_lines = "\n".join(
        f"- {summary.doc_id} | {summary.rights} | {summary.non_retrievable_reason}"
        for summary in report.valid_documents
        if not summary.is_retrievable
    )
    if not non_retrievable_lines:
        non_retrievable_lines = "- none"

    invalid_lines = "\n".join(
        f"- {error.line_number} | {error.error_type} | {error.doc_id or ''} | {error.message}"
        for error in report.errors
    )
    if not invalid_lines:
        invalid_lines = "- none"

    content = f"""# Manifest Import Report

## Summary

run_id: {report.run_id}
manifest_path: {report.manifest_path}
manifest_sha256: {report.manifest_sha256}
status: {report.status}
lines_read: {report.lines_read}
documents_valid: {report.documents_valid}
documents_invalid: {report.documents_invalid}
documents_retrievable: {report.documents_retrievable}
documents_not_retrievable: {report.documents_not_retrievable}

## Valid documents

{valid_lines}

## Non retrievable documents

{non_retrievable_lines}

## Invalid lines

{invalid_lines}

## Notes

- No source_uri was opened.
- No network call was made.
- This report is generated from manifest metadata only.
"""
    report.report_path.write_text(content, encoding="utf-8")


def _raw_excerpt(raw_line: str, max_length: int = 160) -> str:
    return raw_line[:max_length]


def _extract_doc_id(payload: object) -> str | None:
    if isinstance(payload, dict) and isinstance(payload.get("doc_id"), str):
        return payload["doc_id"]
    return None


def _parse_document_line(raw_line: str) -> DocumentMeta:
    payload = json.loads(raw_line)
    return DocumentMeta.model_validate(payload)


def _line_error(raw_line: str, line_number: int, exc: Exception) -> ImportLineError:
    doc_id = None
    error_type = "validation_error"
    message = str(exc)

    if isinstance(exc, json.JSONDecodeError):
        error_type = "json_decode"
        message = exc.msg
    else:
        try:
            payload = json.loads(raw_line)
            doc_id = _extract_doc_id(payload)
        except json.JSONDecodeError:
            error_type = "json_decode"
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if errors:
            message = str(errors[0]["msg"])

    return ImportLineError(
        line_number=line_number,
        message=message,
        error_type=error_type,
        doc_id=doc_id,
        raw_excerpt=_raw_excerpt(raw_line),
    )


def _iter_manifest_lines(manifest_path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            raw_line = raw_line.strip()
            if raw_line:
                lines.append((line_number, raw_line))
    return lines


def _analyze_manifest_directory(manifest_paths: list[Path]) -> tuple[
    int,
    int,
    int,
    int,
    int,
    list[ImportLineError],
    list[DocumentMeta],
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
]:
    lines_read = 0
    documents_valid = 0
    documents_invalid = 0
    documents_retrievable = 0
    documents_not_retrievable = 0
    errors: list[ImportLineError] = []
    metas: list[DocumentMeta] = []
    by_doc_id: dict[str, list[tuple[str, str]]] = {}
    by_source_uri: dict[str, set[str]] = {}
    by_sha256: dict[str, set[str]] = {}

    for manifest_path in manifest_paths:
        for line_number, raw_line in _iter_manifest_lines(manifest_path):
            lines_read += 1
            try:
                meta = _parse_document_line(raw_line)
                metas.append(meta)
                documents_valid += 1
                if meta.is_retrievable:
                    documents_retrievable += 1
                else:
                    documents_not_retrievable += 1
                canonical_payload = json.dumps(
                    meta.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                by_doc_id.setdefault(meta.doc_id, []).append((meta.sha256, canonical_payload))
                by_source_uri.setdefault(meta.source_uri, set()).add(meta.doc_id)
                by_sha256.setdefault(meta.sha256, set()).add(meta.doc_id)
            except Exception as exc:
                documents_invalid += 1
                errors.append(_line_error(raw_line, line_number, exc))

    duplicate_doc_ids = sorted(doc_id for doc_id, rows in by_doc_id.items() if len(rows) > 1)
    duplicate_doc_id_exact = sorted(
        doc_id
        for doc_id, rows in by_doc_id.items()
        if len(rows) > 1 and len({payload for _sha, payload in rows}) == 1
    )
    duplicate_doc_id_conflicts = sorted(
        doc_id
        for doc_id, rows in by_doc_id.items()
        if len(rows) > 1 and len({payload for _sha, payload in rows}) > 1
    )
    duplicate_source_uris = sorted(
        source_uri for source_uri, doc_ids in by_source_uri.items() if len(doc_ids) > 1
    )
    duplicate_sha256 = sorted(sha for sha, doc_ids in by_sha256.items() if len(doc_ids) > 1)

    return (
        lines_read,
        documents_valid,
        documents_invalid,
        documents_retrievable,
        documents_not_retrievable,
        errors,
        metas,
        duplicate_doc_ids,
        duplicate_doc_id_exact,
        duplicate_doc_id_conflicts,
        duplicate_source_uris,
        duplicate_sha256,
    )


def _directory_status(
    *,
    dry_run: bool,
    documents_valid: int,
    documents_invalid: int,
    duplicate_source_uris: list[str],
    duplicate_doc_ids: list[str],
) -> str:
    has_quality_error = bool(duplicate_source_uris or duplicate_doc_ids)
    if documents_valid == 0:
        base = "failed"
    elif documents_invalid or has_quality_error:
        base = "partial"
    else:
        base = "success"
    return f"dry_run_{base}" if dry_run else base


def _status_with_quality(
    *,
    dry_run: bool,
    base_status: str,
    quality_report: QualityReport,
) -> str:
    if quality_report.status == "quality_blocked":
        return "dry_run_blocked" if dry_run else "quality_blocked"
    if dry_run and quality_report.status == "quality_warn":
        return "dry_run_warning"
    return base_status


def _write_directory_report(report: DirectoryImportReport) -> None:
    report.report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_lines = "\n".join(f"- {path}" for path in report.manifest_paths) or "- none"
    duplicate_doc_lines = "\n".join(f"- {value}" for value in report.duplicate_doc_ids) or "- none"
    duplicate_doc_exact_lines = (
        "\n".join(f"- {value}" for value in report.duplicate_doc_id_exact) or "- none"
    )
    duplicate_doc_conflict_lines = (
        "\n".join(f"- {value}" for value in report.duplicate_doc_id_conflicts) or "- none"
    )
    duplicate_source_lines = "\n".join(f"- {value}" for value in report.duplicate_source_uris) or "- none"
    duplicate_sha_lines = "\n".join(f"- {value}" for value in report.duplicate_sha256) or "- none"
    run_lines = "\n".join(f"- {value}" for value in report.run_ids) or "- none"
    quality_lines = "\n".join(
        "| {severity} | {code} | {doc_id} | {field} | {message} |".format(
            severity=issue.severity.value,
            code=issue.code,
            doc_id=issue.doc_id or "",
            field=issue.field or "",
            message=issue.message,
        )
        for issue in report.quality_report.issues
    )
    if not quality_lines:
        quality_lines = "| info | none |  |  | no quality issue |"
    decision = "blocked" if report.quality_report.status == "quality_blocked" else "allowed"
    if report.dry_run:
        decision = "dry-run only" if report.quality_report.status != "quality_blocked" else "blocked"
    content = f"""# Manifest Directory Import Report

## Summary

batch_id: {report.batch_id}
directory_path: {report.directory_path}
status: {report.status}
dry_run: {report.dry_run}
manifest_count: {report.manifest_count}
lines_read: {report.lines_read}
documents_valid: {report.documents_valid}
documents_invalid: {report.documents_invalid}
documents_retrievable: {report.documents_retrievable}
documents_not_retrievable: {report.documents_not_retrievable}

## Manifests

{manifest_lines}

## Duplicate doc_ids

{duplicate_doc_lines}

## Duplicate doc_id exact

{duplicate_doc_exact_lines}

## Duplicate doc_id conflicts

{duplicate_doc_conflict_lines}

## Duplicate source_uris

{duplicate_source_lines}

## Duplicate sha256

{duplicate_sha_lines}

## Runs

{run_lines}

## Quality policy

quality_status: {report.quality_report.status}
blocking_issue_count: {report.quality_report.blocking_issue_count}
warning_count: {report.quality_report.warning_count}
info_count: {report.quality_report.info_count}

## Quality issues

| severity | code | doc_id | field | message |
| --- | --- | --- | --- | --- |
{quality_lines}

Import decision: {decision}

## Notes

- No source_uri was opened.
- No network call was made.
- Directory import is non-recursive.
"""
    report.report_path.write_text(content, encoding="utf-8")


def import_manifest(
    manifest_path: Path,
    db_path: Path = DEFAULT_LEDGER_PATH,
    run_id: str | None = None,
) -> ImportReport:
    run_id = run_id or _new_run_id()
    report_path = _report_path_for(run_id)
    manifest_sha256 = _manifest_sha256(manifest_path)

    initialize_database(db_path)
    repo = LedgerRepository(db_path)
    if repo.get_run(run_id) is not None:
        raise ValueError(f"run_id already exists: {run_id}")
    repo.create_run(
        RunRecord(
            run_id=run_id,
            started_at=datetime.now(timezone.utc),
            status=RunStatus.running,
            command=f"import_manifest {manifest_path}",
        )
    )

    lines_read = 0
    documents_valid = 0
    documents_invalid = 0
    documents_retrievable = 0
    documents_not_retrievable = 0
    valid_documents: list[ImportedDocumentSummary] = []
    errors: list[ImportLineError] = []

    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            lines_read += 1
            try:
                meta = _parse_document_line(raw_line)
                repo.upsert_document(meta)
                repo.record_state(
                    DocumentStateRecord(
                        doc_id=meta.doc_id,
                        state=DocumentState.discovered,
                        run_id=run_id,
                        input_sha256=meta.sha256,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                documents_valid += 1
                summary = _document_summary(meta)
                valid_documents.append(summary)
                if meta.is_retrievable:
                    documents_retrievable += 1
                else:
                    documents_not_retrievable += 1
            except Exception as exc:
                documents_invalid += 1
                error = _line_error(raw_line, line_number, exc)
                errors.append(error)
                repo.record_error(
                    ErrorRecord(
                        error_id=f"{run_id}-line-{line_number}",
                        run_id=run_id,
                        step="manifest_import",
                        message=f"{error.error_type}: {error.message}",
                        recoverable=True,
                        created_at=datetime.now(timezone.utc),
                    )
                )

    if documents_invalid == 0:
        status = RunStatus.success
    elif documents_valid > 0:
        status = RunStatus.partial
    else:
        status = RunStatus.failed

    report = ImportReport(
        run_id=run_id,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        lines_read=lines_read,
        documents_valid=documents_valid,
        documents_invalid=documents_invalid,
        documents_retrievable=documents_retrievable,
        documents_not_retrievable=documents_not_retrievable,
        valid_doc_ids=[summary.doc_id for summary in valid_documents],
        not_retrievable_doc_ids=[
            summary.doc_id for summary in valid_documents if not summary.is_retrievable
        ],
        valid_documents=valid_documents,
        errors=errors,
        report_path=report_path,
        status=status.value,
    )
    _write_markdown_report(report)
    repo.finish_run(run_id, status, report_path=str(report_path))
    return report


def import_manifest_directory(
    directory_path: Path,
    db_path: Path = DEFAULT_LEDGER_PATH,
    batch_id: str | None = None,
    dry_run: bool = False,
    policy: QualityPolicy | None = None,
) -> DirectoryImportReport:
    batch_id = batch_id or _new_batch_id()
    manifest_paths = sorted(path for path in directory_path.iterdir() if path.suffix == ".jsonl")
    if not manifest_paths:
        raise ValueError(f"no JSONL manifests found: {directory_path}")

    (
        lines_read,
        documents_valid,
        documents_invalid,
        documents_retrievable,
        documents_not_retrievable,
        _errors,
        metas,
        duplicate_doc_ids,
        duplicate_doc_id_exact,
        duplicate_doc_id_conflicts,
        duplicate_source_uris,
        duplicate_sha256,
    ) = _analyze_manifest_directory(manifest_paths)

    run_ids = [f"batch-{batch_id}-{index:03d}" for index, _ in enumerate(manifest_paths, start=1)]
    base_status = _directory_status(
        dry_run=dry_run,
        documents_valid=documents_valid,
        documents_invalid=documents_invalid,
        duplicate_source_uris=duplicate_source_uris,
        duplicate_doc_ids=duplicate_doc_ids,
    )

    provisional_report = DirectoryImportReport(
        batch_id=batch_id,
        directory_path=directory_path,
        manifest_count=len(manifest_paths),
        manifest_paths=manifest_paths,
        lines_read=lines_read,
        documents_valid=documents_valid,
        documents_invalid=documents_invalid,
        documents_retrievable=documents_retrievable,
        documents_not_retrievable=documents_not_retrievable,
        duplicate_doc_ids=duplicate_doc_ids,
        duplicate_doc_id_exact=duplicate_doc_id_exact,
        duplicate_doc_id_conflicts=duplicate_doc_id_conflicts,
        duplicate_source_uris=duplicate_source_uris,
        duplicate_sha256=duplicate_sha256,
        valid_metas=metas,
        invalid_lines=_errors,
        quality_report=QualityReport(
            status="quality_pass",
            issues=[],
            blocking_issue_count=0,
            warning_count=0,
            info_count=0,
        ),
        run_ids=[] if dry_run else run_ids,
        dry_run=dry_run,
        status=base_status,
        report_path=_directory_report_path(batch_id),
    )
    quality_report = evaluate_manifest_directory_quality(
        provisional_report,
        policy or QualityPolicy(),
    )
    status = _status_with_quality(
        dry_run=dry_run,
        base_status=base_status,
        quality_report=quality_report,
    )

    if not dry_run and quality_report.status != "quality_blocked":
        initialize_database(db_path)
        repo = LedgerRepository(db_path)
        for run_id in run_ids:
            if repo.get_run(run_id) is not None:
                raise ValueError(f"run_id already exists: {run_id}")
        for manifest_path, run_id in zip(manifest_paths, run_ids, strict=True):
            import_manifest(manifest_path, db_path, run_id=run_id)

    report = DirectoryImportReport(
        batch_id=batch_id,
        directory_path=directory_path,
        manifest_count=len(manifest_paths),
        manifest_paths=manifest_paths,
        lines_read=lines_read,
        documents_valid=documents_valid,
        documents_invalid=documents_invalid,
        documents_retrievable=documents_retrievable,
        documents_not_retrievable=documents_not_retrievable,
        duplicate_doc_ids=duplicate_doc_ids,
        duplicate_doc_id_exact=duplicate_doc_id_exact,
        duplicate_doc_id_conflicts=duplicate_doc_id_conflicts,
        duplicate_source_uris=duplicate_source_uris,
        duplicate_sha256=duplicate_sha256,
        valid_metas=metas,
        invalid_lines=_errors,
        quality_report=quality_report,
        run_ids=[] if dry_run else run_ids,
        dry_run=dry_run,
        status=status,
        report_path=_directory_report_path(batch_id),
    )
    _write_directory_report(report)
    return report
