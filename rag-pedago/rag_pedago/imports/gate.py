from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from rag_pedago.imports.coverage import CoverageStatus, build_coverage_report
from rag_pedago.imports.quality import QualityIssue, QualityPolicy
from rag_pedago.imports.readiness import ReadinessStatus, build_readiness_report


class GateStatus(str, Enum):
    ready_for_controlled_import = "ready_for_controlled_import"
    review_required = "review_required"
    blocked = "blocked"


class GateReport(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    batch_id: str
    status: GateStatus
    readiness_status: str
    coverage_status: str
    documents_valid: int
    blocking_issue_count: int
    warning_count: int
    notions_unknown: list[str]
    missing_priority_notions: list[str]
    reasons: list[str]
    recommended_actions: list[str]
    markdown_path: Path
    json_path: Path
    blocking_issues: list[QualityIssue] = Field(default_factory=list)
    warning_issues: list[QualityIssue] = Field(default_factory=list)
    manifests_sha256: dict[str, str] = Field(default_factory=dict)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_hashes(directory_path: Path) -> dict[str, str]:
    return {
        str(path): _sha256_file(path)
        for path in sorted(directory_path.iterdir())
        if path.suffix == ".jsonl"
    }


def _gate_status(readiness_status: str, coverage_status: str) -> GateStatus:
    if readiness_status == ReadinessStatus.blocked.value:
        return GateStatus.blocked
    if coverage_status == CoverageStatus.insufficient.value:
        return GateStatus.blocked
    if readiness_status == ReadinessStatus.ready_with_warnings.value:
        return GateStatus.review_required
    if coverage_status == CoverageStatus.partial.value:
        return GateStatus.review_required
    return GateStatus.ready_for_controlled_import


def _reasons(
    *,
    status: GateStatus,
    readiness_status: str,
    coverage_status: str,
    notions_unknown: list[str],
    missing_priority_notions: list[str],
    warning_count: int,
) -> list[str]:
    reasons: list[str] = []
    if readiness_status == ReadinessStatus.blocked.value:
        reasons.append("Readiness is blocked by manifest quality issues.")
    if coverage_status == CoverageStatus.insufficient.value:
        reasons.append("Coverage is insufficient: no valid notions declared.")
    if coverage_status == CoverageStatus.partial.value and notions_unknown:
        reasons.append("Coverage is partial: unknown notions are present.")
    if coverage_status == CoverageStatus.partial.value and missing_priority_notions:
        reasons.append("Coverage is partial: priority notions are missing.")
    if readiness_status == ReadinessStatus.ready_with_warnings.value or (
        status is GateStatus.review_required and warning_count > 0
    ):
        reasons.append("Human review required because warnings remain.")
    if status is GateStatus.ready_for_controlled_import:
        reasons.append("Ready for controlled manifest import")
        reasons.append("Ready for controlled manifest import; document parsing still forbidden.")
    return _dedupe(reasons)


def _gate_actions(status: GateStatus) -> list[str]:
    if status is GateStatus.blocked:
        return ["Corriger les manifests puis relancer readiness, coverage et gate."]
    if status is GateStatus.review_required:
        return ["Faire valider humainement les warnings et les écarts de couverture."]
    return ["Lancer uniquement un import contrôlé de manifests; le parsing documentaire reste interdit."]


def _next_step(status: GateStatus) -> str:
    if status is GateStatus.blocked:
        return "fix manifests and rerun readiness + coverage + gate."
    if status is GateStatus.review_required:
        return "human validation required before controlled import."
    return "controlled manifest import may be run; document parsing remains forbidden."


def _issue_rows(title: str, values: list[str]) -> str:
    lines = [f"## {title}", ""]
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- none")
    return "\n".join(lines)


def _compatibility_issues(report: GateReport) -> list[QualityIssue]:
    return [
        issue
        for issue in report.blocking_issues + report.warning_issues
        if issue.compatibility_explanation is not None
    ]


def _compatibility_rows(report: GateReport) -> str:
    issues = _compatibility_issues(report)
    if not issues:
        return "| doc_id | ref_id | compatible | document_refs | reason |\n| --- | --- | --- | --- | --- |\n|  |  |  |  | none |"
    rows = [
        "| doc_id | ref_id | compatible | document_refs | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for issue in issues:
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


def _write_markdown_report(report: GateReport) -> None:
    report.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    reasons = "\n".join(f"- {reason}" for reason in report.reasons) or "- none"
    actions = "\n".join(f"- {action}" for action in report.recommended_actions) or "- none"
    content = f"""# Pre-Ingestion Gate Report — {report.batch_id}

## Final decision

Status: {report.status.value}

## Why this decision

{reasons}

## Readiness summary

- readiness_status: {report.readiness_status}
- blocking_issue_count: {report.blocking_issue_count}
- warning_count: {report.warning_count}

## Coverage summary

- coverage_status: {report.coverage_status}
- documents_valid: {report.documents_valid}
- notions_unknown: {len(report.notions_unknown)}
- missing_priority_notions: {len(report.missing_priority_notions)}

## Blocking issues

- blocking_issue_count: {report.blocking_issue_count}

## Warnings

- warning_count: {report.warning_count}

{_issue_rows("Coverage gaps", report.notions_unknown + report.missing_priority_notions)}

## Official reference compatibility

{_compatibility_rows(report)}

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


def _write_json_report(report: GateReport) -> None:
    report.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "batch_id": report.batch_id,
        "status": report.status.value,
        "readiness_status": report.readiness_status,
        "coverage_status": report.coverage_status,
        "counts": {
            "documents_valid": report.documents_valid,
            "blocking_issue_count": report.blocking_issue_count,
            "warning_count": report.warning_count,
            "notions_unknown": len(report.notions_unknown),
            "missing_priority_notions": len(report.missing_priority_notions),
        },
        "notions_unknown": report.notions_unknown,
        "missing_priority_notions": report.missing_priority_notions,
        "reasons": report.reasons,
        "issues": {
            "blocking": [issue.model_dump(mode="json") for issue in report.blocking_issues],
            "warnings": [issue.model_dump(mode="json") for issue in report.warning_issues],
        },
        "official_reference_compatibility": [
            issue.compatibility_explanation.model_dump(mode="json")
            for issue in _compatibility_issues(report)
            if issue.compatibility_explanation is not None
        ],
        "recommended_actions": report.recommended_actions,
        "manifests_sha256": report.manifests_sha256,
        "guarantees": {
            "no_source_uri_opened": True,
            "no_network_call": True,
            "no_document_ingestion": True,
        },
    }
    report.json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_gate_report(
    directory_path: Path,
    batch_id: str,
    taxonomy_paths: list[Path],
    policy: QualityPolicy,
    priority_notions: list[str] | None = None,
    output_dir: Path = Path("data/reports"),
) -> GateReport:
    readiness_report = build_readiness_report(
        directory_path=directory_path,
        batch_id=batch_id,
        policy=policy,
        output_dir=output_dir,
    )
    coverage_report = build_coverage_report(
        directory_path=directory_path,
        batch_id=batch_id,
        taxonomy_paths=taxonomy_paths,
        priority_notions=priority_notions,
        output_dir=output_dir,
    )
    status = _gate_status(readiness_report.status.value, coverage_report.status.value)
    reasons = _reasons(
        status=status,
        readiness_status=readiness_report.status.value,
        coverage_status=coverage_report.status.value,
        notions_unknown=coverage_report.notions_unknown,
        missing_priority_notions=coverage_report.missing_priority_notions,
        warning_count=readiness_report.warning_count,
    )
    actions = _dedupe(
        readiness_report.recommended_actions
        + coverage_report.recommended_actions
        + _gate_actions(status)
    )
    report = GateReport(
        batch_id=batch_id,
        status=status,
        readiness_status=readiness_report.status.value,
        coverage_status=coverage_report.status.value,
        documents_valid=coverage_report.documents_valid,
        blocking_issue_count=readiness_report.blocking_issue_count,
        warning_count=readiness_report.warning_count,
        notions_unknown=coverage_report.notions_unknown,
        missing_priority_notions=coverage_report.missing_priority_notions,
        reasons=reasons,
        recommended_actions=actions,
        markdown_path=output_dir / f"gate_{batch_id}.md",
        json_path=output_dir / f"gate_{batch_id}.json",
        blocking_issues=readiness_report.blocking_issues,
        warning_issues=readiness_report.warning_issues,
        manifests_sha256=_manifest_hashes(directory_path),
    )
    _write_markdown_report(report)
    _write_json_report(report)
    return report
