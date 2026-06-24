from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.quality import QualityIssue, QualityPolicy, Severity


class ReadinessStatus(str, Enum):
    ready = "ready"
    ready_with_warnings = "ready_with_warnings"
    blocked = "blocked"


class ReadinessReport(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    batch_id: str
    status: ReadinessStatus
    manifest_count: int
    documents_valid: int
    documents_invalid: int
    documents_retrievable: int
    documents_not_retrievable: int
    blocking_issue_count: int
    warning_count: int
    info_count: int
    blocking_issues: list[QualityIssue]
    warning_issues: list[QualityIssue]
    recommended_actions: list[str]
    markdown_path: Path
    json_path: Path


ACTION_BY_CODE = {
    "invalid_lines": "Corriger ou supprimer les lignes invalides du manifest.",
    "duplicate_source_uri": "Fusionner les entrées ou attribuer un doc_id unique cohérent.",
    "duplicate_doc_id_conflict": "Choisir une version canonique du document.",
    "duplicate_doc_id_exact": "Dédupliquer les entrées identiques du manifest.",
    "duplicate_sha256": "Vérifier les doublons de contenu par sha256.",
    "unknown_rights": "Clarifier les droits avant retrieval.",
    "missing_programme_version": "Renseigner programme_version.",
    "missing_niveau": "Renseigner le niveau scolaire.",
    "missing_epreuve": "Renseigner l’épreuve concernée.",
}


def recommended_actions_for_issues(issues: list[QualityIssue]) -> list[str]:
    actions: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        action = ACTION_BY_CODE.get(issue.code, "Examiner et corriger le problème signalé.")
        if action not in seen:
            actions.append(action)
            seen.add(action)
    return actions


def _status_from_quality(quality_status: str, warning_count: int) -> ReadinessStatus:
    if quality_status == "quality_blocked":
        return ReadinessStatus.blocked
    if warning_count > 0:
        return ReadinessStatus.ready_with_warnings
    return ReadinessStatus.ready


def _issue_rows(issues: list[QualityIssue]) -> str:
    if not issues:
        return "| severity | code | doc_id | field | message |\n| --- | --- | --- | --- | --- |\n| info | none |  |  | none |"
    rows = [
        "| severity | code | doc_id | field | message |",
        "| --- | --- | --- | --- | --- |",
    ]
    rows.extend(
        "| {severity} | {code} | {doc_id} | {field} | {message} |".format(
            severity=issue.severity.value,
            code=issue.code,
            doc_id=issue.doc_id or "",
            field=issue.field or "",
            message=issue.message.replace("|", "\\|"),
        )
        for issue in issues
    )
    return "\n".join(rows)


def _compatibility_issues(issues: list[QualityIssue]) -> list[QualityIssue]:
    return [issue for issue in issues if issue.compatibility_explanation is not None]


def _compatibility_rows(issues: list[QualityIssue]) -> str:
    compatibility_issues = _compatibility_issues(issues)
    if not compatibility_issues:
        return "| doc_id | ref_id | compatible | document_refs | reason |\n| --- | --- | --- | --- | --- |\n|  |  |  |  | none |"
    rows = [
        "| doc_id | ref_id | compatible | document_refs | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for issue in compatibility_issues:
        explanation = issue.compatibility_explanation
        if explanation is None:
            continue
        rows.append(
            "| {doc_id} | {ref_id} | {compatible} | {document_refs} | {reason} |".format(
                doc_id=issue.doc_id or "",
                ref_id=explanation.ref_id,
                compatible=str(explanation.compatible).lower(),
                document_refs=", ".join(explanation.document_refs),
                reason=explanation.reason.replace("|", "\\|"),
            )
        )
    return "\n".join(rows)


def _next_step(status: ReadinessStatus) -> str:
    if status is ReadinessStatus.blocked:
        return "corriger les manifests puis relancer le readiness report."
    if status is ReadinessStatus.ready_with_warnings:
        return "validation humaine avant import réel."
    return "import contrôlé possible, toujours sans parsing documentaire."


def _write_markdown_report(report: ReadinessReport) -> None:
    report.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    actions = "\n".join(f"- {action}" for action in report.recommended_actions) or "- none"
    status_label = report.status.value.upper()
    content = f"""# Readiness Report — {report.batch_id}

## Decision

Status: {status_label}

## Executive summary

Batch `{report.batch_id}` contains {report.documents_valid} valid document metadata entries across {report.manifest_count} manifest file(s). The readiness decision is `{report.status.value}`.

## Counts

- manifest_count: {report.manifest_count}
- documents_valid: {report.documents_valid}
- documents_invalid: {report.documents_invalid}
- documents_retrievable: {report.documents_retrievable}
- documents_not_retrievable: {report.documents_not_retrievable}
- blocking_issue_count: {report.blocking_issue_count}
- warning_count: {report.warning_count}
- info_count: {report.info_count}

## Blocking issues

{_issue_rows(report.blocking_issues)}

## Warnings

{_issue_rows(report.warning_issues)}

## Official reference compatibility

{_compatibility_rows(report.blocking_issues + report.warning_issues)}

## Recommended actions

{actions}

## Guarantees

- No source_uri was opened.
- No network call was made.
- No document ingestion was performed.

## Next step

{_next_step(report.status)}
"""
    report.markdown_path.write_text(content, encoding="utf-8")


def _write_json_report(report: ReadinessReport) -> None:
    report.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "batch_id": report.batch_id,
        "status": report.status.value,
        "counts": {
            "manifest_count": report.manifest_count,
            "documents_valid": report.documents_valid,
            "documents_invalid": report.documents_invalid,
            "documents_retrievable": report.documents_retrievable,
            "documents_not_retrievable": report.documents_not_retrievable,
            "blocking_issue_count": report.blocking_issue_count,
            "warning_count": report.warning_count,
            "info_count": report.info_count,
        },
        "issues": {
            "blocking": [issue.model_dump(mode="json") for issue in report.blocking_issues],
            "warnings": [issue.model_dump(mode="json") for issue in report.warning_issues],
        },
        "recommended_actions": report.recommended_actions,
        "generated_at": datetime.now(UTC).isoformat(),
        "guarantees": {
            "no_source_uri_opened": True,
            "no_network_call": True,
            "no_document_ingestion": True,
        },
    }
    report.json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_readiness_report(
    directory_path: Path,
    batch_id: str,
    policy: QualityPolicy,
    output_dir: Path = Path("data/reports"),
) -> ReadinessReport:
    directory_report = import_manifest_directory(
        directory_path=directory_path,
        db_path=Path("__readiness_dry_run_unused__/rag_pedago.sqlite"),
        batch_id=batch_id,
        dry_run=True,
        policy=policy,
    )
    quality_report = directory_report.quality_report
    status = _status_from_quality(quality_report.status, quality_report.warning_count)
    blocking_issues = [
        issue
        for issue in quality_report.issues
        if issue.severity in {Severity.error, Severity.critical}
    ]
    warning_issues = [
        issue
        for issue in quality_report.issues
        if issue.severity in {Severity.warning, Severity.info}
    ]
    all_issues = blocking_issues + warning_issues
    markdown_path = output_dir / f"readiness_{batch_id}.md"
    json_path = output_dir / f"readiness_{batch_id}.json"
    report = ReadinessReport(
        batch_id=batch_id,
        status=status,
        manifest_count=directory_report.manifest_count,
        documents_valid=directory_report.documents_valid,
        documents_invalid=directory_report.documents_invalid,
        documents_retrievable=directory_report.documents_retrievable,
        documents_not_retrievable=directory_report.documents_not_retrievable,
        blocking_issue_count=quality_report.blocking_issue_count,
        warning_count=quality_report.warning_count,
        info_count=quality_report.info_count,
        blocking_issues=blocking_issues,
        warning_issues=warning_issues,
        recommended_actions=recommended_actions_for_issues(all_issues),
        markdown_path=markdown_path,
        json_path=json_path,
    )
    _write_markdown_report(report)
    _write_json_report(report)
    return report
