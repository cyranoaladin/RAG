from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from rag_pedago.imports.gate import GateStatus, build_gate_report
from rag_pedago.imports.manifest import import_manifest_directory
from rag_pedago.imports.quality import QualityIssue, QualityPolicy
from rag_pedago.imports.review import (
    ReviewDecision,
    ReviewPackage,
    ReviewStatus,
    sha256_canonical_json,
    sha256_directory_yaml,
    sha256_file,
)


class ControlledImportStatus(str, Enum):
    imported = "imported"
    blocked_by_gate = "blocked_by_gate"
    failed = "failed"


class ControlledImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    batch_id: str
    status: ControlledImportStatus
    gate_status: str
    import_status: str | None
    documents_valid: int
    documents_invalid: int
    documents_not_retrievable: int
    run_ids: list[str]
    gate_markdown_path: Path
    gate_json_path: Path
    import_report_path: Path | None
    markdown_path: Path
    json_path: Path
    reasons: list[str]
    recommended_actions: list[str]
    attempt_id: str
    review_id: str | None = None
    package_id: str | None = None
    gate_blocking_issues: list[QualityIssue] = Field(default_factory=list)
    gate_warning_issues: list[QualityIssue] = Field(default_factory=list)
    review_required: bool = False
    review_decision: str | None = None
    review_hash_verified: bool = False
    review_decision_path: Path | None = None
    review_package_path: Path | None = None
    review_package_hash_verified: bool = False
    official_reference_hash_verified: bool = False
    taxonomy_hash_verified: bool = False
    manifest_hashes_verified: bool = False


def _controlled_report_paths(batch_id: str, output_dir: Path) -> tuple[Path, Path]:
    return (
        output_dir / f"controlled_import_{batch_id}.md",
        output_dir / f"controlled_import_{batch_id}.json",
    )


def _write_markdown_report(report: ControlledImportReport) -> None:
    report.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    run_lines = "\n".join(f"- {run_id}" for run_id in report.run_ids) or "- none"
    reason_lines = "\n".join(f"- {reason}" for reason in report.reasons) or "- none"
    action_lines = "\n".join(f"- {action}" for action in report.recommended_actions) or "- none"
    import_report_path = str(report.import_report_path) if report.import_report_path else "none"
    compatibility_rows = _compatibility_rows(report)
    content = f"""# Controlled Import Report — {report.batch_id}

## Decision

Status: {report.status.value}

## Gate summary

- gate_status: {report.gate_status}
- gate_markdown_path: {report.gate_markdown_path}
- gate_json_path: {report.gate_json_path}
- Review required: {str(report.review_required).lower()}
- Review decision: {report.review_decision or "none"}
- Review hash verified: {str(report.review_hash_verified).lower()}
- Review decision path: {report.review_decision_path or "none"}
- Review package path: {report.review_package_path or "none"}
- Review package hash verified: {str(report.review_package_hash_verified).lower()}
- Official reference hash verified: {str(report.official_reference_hash_verified).lower()}
- Taxonomy hash verified: {str(report.taxonomy_hash_verified).lower()}
- Manifest hashes verified: {str(report.manifest_hashes_verified).lower()}

## Import summary

- import_status: {report.import_status or "none"}
- documents_valid: {report.documents_valid}
- documents_invalid: {report.documents_invalid}
- documents_not_retrievable: {report.documents_not_retrievable}
- import_report_path: {import_report_path}

## Run IDs

{run_lines}

## Reasons

{reason_lines}

## Recommended actions

{action_lines}

## Official reference compatibility

{compatibility_rows}

## Guarantees

- Gate was evaluated before import.
- No source_uri was opened.
- No network call was made.
- No document parsing was performed.
"""
    report.markdown_path.write_text(content, encoding="utf-8")


def _compatibility_issues(report: ControlledImportReport) -> list[QualityIssue]:
    return [
        issue
        for issue in report.gate_blocking_issues + report.gate_warning_issues
        if issue.compatibility_explanation is not None
    ]


def _compatibility_rows(report: ControlledImportReport) -> str:
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


def _write_json_report(report: ControlledImportReport) -> None:
    report.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "batch_id": report.batch_id,
        "attempt_id": report.attempt_id,
        "status": report.status.value,
        "gate_status": report.gate_status,
        "import_status": report.import_status,
        "counts": {
            "documents_valid": report.documents_valid,
            "documents_invalid": report.documents_invalid,
            "documents_not_retrievable": report.documents_not_retrievable,
        },
        "run_ids": report.run_ids,
        "paths": {
            "gate_markdown_path": str(report.gate_markdown_path),
            "gate_json_path": str(report.gate_json_path),
            "import_report_path": str(report.import_report_path)
            if report.import_report_path
            else None,
            "markdown_path": str(report.markdown_path),
            "json_path": str(report.json_path),
        },
        "reasons": report.reasons,
        "recommended_actions": report.recommended_actions,
        "review": {
            "required": report.review_required,
            "decision": report.review_decision,
            "hash_verified": report.review_hash_verified,
            "decision_path": str(report.review_decision_path) if report.review_decision_path else None,
            "package_path": str(report.review_package_path) if report.review_package_path else None,
            "package_hash_verified": report.review_package_hash_verified,
            "official_reference_hash_verified": report.official_reference_hash_verified,
            "taxonomy_hash_verified": report.taxonomy_hash_verified,
            "manifest_hashes_verified": report.manifest_hashes_verified,
        },
        "issues": {
            "blocking": [issue.model_dump(mode="json") for issue in report.gate_blocking_issues],
            "warnings": [issue.model_dump(mode="json") for issue in report.gate_warning_issues],
        },
        "official_reference_compatibility": [
            issue.compatibility_explanation.model_dump(mode="json")
            for issue in _compatibility_issues(report)
            if issue.compatibility_explanation is not None
        ],
        "generated_at": datetime.now(UTC).isoformat(),
        "guarantees": {
            "gate_evaluated_before_import": True,
            "no_source_uri_opened": True,
            "no_network_call": True,
            "no_document_parsing": True,
        },
    }
    report.json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _finish(report: ControlledImportReport) -> ControlledImportReport:
    _write_markdown_report(report)
    _write_json_report(report)
    return report


def _new_attempt_id(batch_id: str) -> str:
    return f"{batch_id}-{uuid4().hex[:12]}"


def _verification_map(report: ControlledImportReport) -> dict[str, bool]:
    return {
        "gate_evaluated": True,
        "review_required": report.review_required,
        "review_decision_present": report.review_decision is not None,
        "review_package_present": report.review_package_path is not None,
        "review_package_hash_verified": report.review_package_hash_verified,
        "manifest_hashes_verified": report.manifest_hashes_verified,
        "taxonomy_hash_verified": report.taxonomy_hash_verified,
        "official_reference_hash_verified": report.official_reference_hash_verified,
        "gate_hash_verified": report.review_hash_verified,
        "ledger_write_performed": report.status is ControlledImportStatus.imported,
    }


def _record_audit_attempt(report: ControlledImportReport, audit_ledger_db_path: Path | None) -> None:
    if audit_ledger_db_path is None:
        return
    from rag_pedago.ledger.migrations import initialize_database
    from rag_pedago.ledger.repository import LedgerRepository

    initialize_database(audit_ledger_db_path)
    repo = LedgerRepository(audit_ledger_db_path)
    repo.record_controlled_import_attempt(report)
    for check_name, passed in _verification_map(report).items():
        repo.record_controlled_import_verification(
            report.attempt_id,
            check_name,
            passed,
            None if passed else "check not satisfied",
        )


def _load_review_decision(path: Path) -> ReviewDecision:
    try:
        return ReviewDecision.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid review decision JSON: {path}") from exc


def _load_review_package(path: Path) -> ReviewPackage:
    try:
        return ReviewPackage.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid review package JSON: {path}") from exc


def _manifest_hashes(directory_path: Path) -> dict[str, str]:
    return {
        str(path): sha256_file(path)
        for path in sorted(directory_path.iterdir())
        if path.suffix == ".jsonl"
    }


def _taxonomy_hashes(taxonomy_paths: list[Path]) -> dict[str, str]:
    return {str(path): sha256_file(path) for path in taxonomy_paths}


def _verify_review_decision(
    *,
    review_package_path: Path | None,
    review_decision_path: Path | None,
    batch_id: str,
) -> tuple[ReviewPackage, ReviewDecision]:
    if review_package_path is None:
        raise ValueError("review_package_path is required when require_review=True")
    if review_decision_path is None:
        raise ValueError("review_decision_path is required when require_review=True")
    package = _load_review_package(review_package_path)
    decision = _load_review_decision(review_decision_path)
    if package.status is not ReviewStatus.ready_for_review:
        raise ValueError("review package status must be ready_for_review")
    if decision.decision != "approved":
        raise ValueError("review decision must be approved")
    if decision.batch_id != batch_id:
        raise ValueError("batch_id mismatch between review decision and import")
    if package.batch_id != batch_id:
        raise ValueError("batch_id mismatch between review package and import")
    if sha256_canonical_json(package) != decision.review_package_sha256:
        raise ValueError("review_package_sha256 mismatch between review decision and package")
    return package, decision


def _verify_review_hashes(
    *,
    package: ReviewPackage,
    directory_path: Path,
    taxonomy_paths: list[Path],
) -> None:
    if _manifest_hashes(directory_path) != package.manifests_sha256:
        raise ValueError("manifest hashes mismatch between review package and current manifests")
    if _taxonomy_hashes(taxonomy_paths) != package.taxonomy_sha256:
        raise ValueError("taxonomy hashes mismatch between review package and current taxonomies")
    if sha256_directory_yaml(Path("data/reference")) != package.official_reference_sha256:
        raise ValueError("official_reference_sha256 mismatch between review package and current reference")


def _verify_gate_hash(*, decision: ReviewDecision, gate_json_path: Path) -> None:
    current_gate_hash = sha256_file(gate_json_path)
    if current_gate_hash != decision.gate_json_sha256:
        raise ValueError("gate_json_sha256 mismatch between review decision and current gate")


def controlled_import_manifest_directory(
    directory_path: Path,
    db_path: Path,
    batch_id: str,
    taxonomy_paths: list[Path],
    policy: QualityPolicy,
    priority_notions: list[str] | None = None,
    output_dir: Path = Path("data/reports"),
    review_decision_path: Path | None = None,
    review_package_path: Path | None = None,
    require_review: bool = False,
    audit_ledger_db_path: Path | None = None,
) -> ControlledImportReport:
    markdown_path, json_path = _controlled_report_paths(batch_id, output_dir)
    attempt_id = _new_attempt_id(batch_id)
    gate_report = build_gate_report(
        directory_path=directory_path,
        batch_id=batch_id,
        taxonomy_paths=taxonomy_paths,
        policy=policy,
        priority_notions=priority_notions,
        output_dir=output_dir,
    )
    review_package: ReviewPackage | None = None
    review_decision: ReviewDecision | None = None
    if require_review:
        review_package, review_decision = _verify_review_decision(
            review_package_path=review_package_path,
            review_decision_path=review_decision_path,
            batch_id=batch_id,
        )
        _verify_review_hashes(
            package=review_package,
            directory_path=directory_path,
            taxonomy_paths=taxonomy_paths,
        )
        _verify_gate_hash(decision=review_decision, gate_json_path=gate_report.json_path)

    if gate_report.status is not GateStatus.ready_for_controlled_import:
        report = _finish(
            ControlledImportReport(
                attempt_id=attempt_id,
                batch_id=batch_id,
                status=ControlledImportStatus.blocked_by_gate,
                gate_status=gate_report.status.value,
                import_status=None,
                documents_valid=gate_report.documents_valid,
                documents_invalid=0,
                documents_not_retrievable=0,
                run_ids=[],
                gate_markdown_path=gate_report.markdown_path,
                gate_json_path=gate_report.json_path,
                import_report_path=None,
                markdown_path=markdown_path,
                json_path=json_path,
                reasons=gate_report.reasons,
                recommended_actions=gate_report.recommended_actions,
                review_id=review_decision.review_id if review_decision else None,
                package_id=review_package.batch_id if review_package else None,
                gate_blocking_issues=gate_report.blocking_issues,
                gate_warning_issues=gate_report.warning_issues,
                review_required=require_review,
                review_decision=review_decision.decision if review_decision else None,
                review_hash_verified=review_decision is not None,
                review_decision_path=review_decision_path,
                review_package_path=review_package_path,
                review_package_hash_verified=review_package is not None,
                official_reference_hash_verified=review_package is not None,
                taxonomy_hash_verified=review_package is not None,
                manifest_hashes_verified=review_package is not None,
            )
        )
        _record_audit_attempt(report, audit_ledger_db_path)
        return report

    try:
        import_report = import_manifest_directory(
            directory_path=directory_path,
            db_path=db_path,
            batch_id=batch_id,
            dry_run=False,
            policy=policy,
        )
    except Exception as exc:
        report = _finish(
            ControlledImportReport(
                attempt_id=attempt_id,
                batch_id=batch_id,
                status=ControlledImportStatus.failed,
                gate_status=gate_report.status.value,
                import_status=None,
                documents_valid=gate_report.documents_valid,
                documents_invalid=0,
                documents_not_retrievable=0,
                run_ids=[],
                gate_markdown_path=gate_report.markdown_path,
                gate_json_path=gate_report.json_path,
                import_report_path=None,
                markdown_path=markdown_path,
                json_path=json_path,
                reasons=[str(exc)],
                recommended_actions=[
                    "Résoudre l'erreur d'import contrôlé puis relancer avec un nouveau batch_id."
                ],
                review_id=review_decision.review_id if review_decision else None,
                package_id=review_package.batch_id if review_package else None,
                gate_blocking_issues=gate_report.blocking_issues,
                gate_warning_issues=gate_report.warning_issues,
                review_required=require_review,
                review_decision=review_decision.decision if review_decision else None,
                review_hash_verified=review_decision is not None,
                review_decision_path=review_decision_path,
                review_package_path=review_package_path,
                review_package_hash_verified=review_package is not None,
                official_reference_hash_verified=review_package is not None,
                taxonomy_hash_verified=review_package is not None,
                manifest_hashes_verified=review_package is not None,
            )
        )
        _record_audit_attempt(report, audit_ledger_db_path)
        return report

    report = _finish(
        ControlledImportReport(
            attempt_id=attempt_id,
            batch_id=batch_id,
            status=ControlledImportStatus.imported,
            gate_status=gate_report.status.value,
            import_status=import_report.status,
            documents_valid=import_report.documents_valid,
            documents_invalid=import_report.documents_invalid,
            documents_not_retrievable=import_report.documents_not_retrievable,
            run_ids=import_report.run_ids,
            gate_markdown_path=gate_report.markdown_path,
            gate_json_path=gate_report.json_path,
            import_report_path=import_report.report_path,
            markdown_path=markdown_path,
            json_path=json_path,
            reasons=gate_report.reasons,
            recommended_actions=gate_report.recommended_actions,
            review_id=review_decision.review_id if review_decision else None,
            package_id=review_package.batch_id if review_package else None,
            gate_blocking_issues=gate_report.blocking_issues,
            gate_warning_issues=gate_report.warning_issues,
            review_required=require_review,
            review_decision=review_decision.decision if review_decision else None,
            review_hash_verified=review_decision is not None,
            review_decision_path=review_decision_path,
            review_package_path=review_package_path,
            review_package_hash_verified=review_package is not None,
            official_reference_hash_verified=review_package is not None,
            taxonomy_hash_verified=review_package is not None,
            manifest_hashes_verified=review_package is not None,
        )
    )
    _record_audit_attempt(report, audit_ledger_db_path)
    return report
