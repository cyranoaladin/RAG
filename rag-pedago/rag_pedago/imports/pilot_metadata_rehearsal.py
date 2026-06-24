from __future__ import annotations

import argparse
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, ConfigDict

from rag_pedago.imports.controlled_import import (
    ControlledImportReport,
    controlled_import_manifest_directory,
)
from rag_pedago.imports.coverage import CoverageReport, build_coverage_report
from rag_pedago.imports.gate import GateReport, build_gate_report
from rag_pedago.imports.manifest import DirectoryImportReport, import_manifest_directory
from rag_pedago.imports.pilot_manifest_compiler import (
    compile_filled_draft_to_jsonl_text,
    validate_filled_draft,
)
from rag_pedago.imports.quality import QualityPolicy
from rag_pedago.imports.readiness import ReadinessReport, build_readiness_report
from rag_pedago.imports.review import (
    ReviewDecision,
    ReviewPackage,
    approve_review_package,
    build_review_package,
)
from rag_pedago.paths import PRODUCTION_RAG_UI_ROOT, RAG_LOCAL_ROOT, REPO_ROOT

FORBIDDEN_OUTPUT_ROOTS = (
    PRODUCTION_RAG_UI_ROOT,
    RAG_LOCAL_ROOT,
)
SENSITIVE_OUTPUT_MARKERS = (
    ".env",
    ".pem",
    ".key",
    "secret",
    "credential",
    "credentials",
    "creds",
    "gdrive",
)
DEFAULT_TAXONOMY_PATHS = (
    REPO_ROOT / "taxonomy/maths/terminale_specialite.yml",
    REPO_ROOT / "taxonomy/nsi/terminale.yml",
)
DEFAULT_PRIORITY_NOTIONS = (
    "suites",
    "recurrence",
    "limites_de_suites",
    "probabilites_conditionnelles",
    "loi_binomiale",
    "algorithmique_python",
)
BATCH_ID = "pilot-metadata-rehearsal"


class RehearsalReports(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    dry_run: DirectoryImportReport
    readiness: ReadinessReport
    coverage: CoverageReport
    gate: GateReport
    review_package: ReviewPackage


class RehearsalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    batch_id: str
    workspace: Path
    manifest_dir: Path
    output_dir: Path
    ledger_db_path: Path
    compile_status: str
    dry_run_status: str
    readiness_status: str
    coverage_status: str
    gate_status: str
    review_status: str
    decision_status: str
    controlled_import_status: str
    ledger_audit_status: str
    review_decision_path: Path | None
    review_notes: str
    controlled_import_report_path: Path


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _validate_runtime_path(path: Path) -> None:
    resolved = _resolve(path)
    for forbidden_root in FORBIDDEN_OUTPUT_ROOTS:
        if resolved == forbidden_root or resolved.is_relative_to(forbidden_root):
            raise ValueError(f"forbidden output_dir: {path}")
    lowered = str(resolved).lower()
    if any(marker in lowered for marker in SENSITIVE_OUTPUT_MARKERS):
        raise ValueError(f"sensitive output_dir: {path}")


def _safe_link(link_path: Path, target_path: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        link_path.symlink_to(target_path, target_is_directory=True)
    except FileExistsError:
        return


def build_rehearsal_workspace(base_dir: Path) -> Path:
    _validate_runtime_path(base_dir)
    workspace = _resolve(base_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "manifests").mkdir(parents=True, exist_ok=True)
    (workspace / "reports").mkdir(parents=True, exist_ok=True)
    (workspace / "reviews").mkdir(parents=True, exist_ok=True)
    (workspace / "ledger").mkdir(parents=True, exist_ok=True)
    _safe_link(workspace / "data/reference", REPO_ROOT / "data/reference")
    _safe_link(workspace / "taxonomy", REPO_ROOT / "taxonomy")
    return workspace


def compile_draft_to_workspace_manifest(draft_path: Path, workspace: Path) -> Path:
    _validate_runtime_path(workspace)
    workspace = build_rehearsal_workspace(workspace)
    report = validate_filled_draft(draft_path)
    if report.status != "ready":
        raise ValueError(f"filled draft is not ready: {draft_path}")
    manifest_path = workspace / "manifests" / "pilot_metadata_rehearsal.jsonl"
    manifest_path.write_text(compile_filled_draft_to_jsonl_text(draft_path), encoding="utf-8")
    return manifest_path


@contextmanager
def _chdir(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def run_rehearsal_reports(
    manifest_dir: Path,
    output_dir: Path,
    batch_id: str = BATCH_ID,
    taxonomy_paths: list[Path] | None = None,
    priority_notions: list[str] | None = None,
    ledger_db_path: Path | None = None,
) -> RehearsalReports:
    _validate_runtime_path(output_dir)
    taxonomy_paths = taxonomy_paths or list(DEFAULT_TAXONOMY_PATHS)
    priority_notions = priority_notions or list(DEFAULT_PRIORITY_NOTIONS)
    workspace = output_dir.parent
    policy = QualityPolicy()
    with _chdir(workspace):
        dry_run = import_manifest_directory(
            directory_path=manifest_dir,
            db_path=workspace / "ledger" / "dry_run_unused.sqlite",
            batch_id=f"{batch_id}-dry-run",
            dry_run=True,
            policy=policy,
        )
        readiness = build_readiness_report(
            directory_path=manifest_dir,
            batch_id=batch_id,
            policy=policy,
            output_dir=output_dir,
        )
        coverage = build_coverage_report(
            directory_path=manifest_dir,
            batch_id=batch_id,
            taxonomy_paths=taxonomy_paths,
            priority_notions=priority_notions,
            output_dir=output_dir,
        )
        gate = build_gate_report(
            directory_path=manifest_dir,
            batch_id=batch_id,
            taxonomy_paths=taxonomy_paths,
            policy=policy,
            priority_notions=priority_notions,
            output_dir=output_dir,
        )
        review_package = build_review_package(
            directory_path=manifest_dir,
            batch_id=batch_id,
            taxonomy_paths=taxonomy_paths,
            policy=policy,
            priority_notions=priority_notions,
            output_dir=output_dir,
            ledger_db_path=ledger_db_path,
        )
    return RehearsalReports(
        dry_run=dry_run,
        readiness=readiness,
        coverage=coverage,
        gate=gate,
        review_package=review_package,
    )


def build_synthetic_review_decision(
    review_package_path: Path,
    output_dir: Path,
    ledger_db_path: Path | None = None,
) -> ReviewDecision:
    _validate_runtime_path(output_dir)
    notes = (
        "synthetic=true; reviewer=synthetic-reviewer; "
        "scope=metadata-only rehearsal; no_real_documents=true; "
        "no_source_uri_opened=true"
    )
    return approve_review_package(
        review_package_json=review_package_path,
        reviewer="synthetic-reviewer",
        decision="approved",
        notes=notes,
        output_dir=output_dir,
        ledger_db_path=ledger_db_path,
    )


def _review_decision_path(decision: ReviewDecision, output_dir: Path) -> Path:
    return output_dir / f"review_{decision.review_id}.json"


def run_controlled_metadata_import_rehearsal(
    manifest_dir: Path,
    output_dir: Path,
    ledger_db_path: Path,
    review_package_path: Path,
    review_decision_path: Path,
    batch_id: str = BATCH_ID,
    taxonomy_paths: list[Path] | None = None,
    priority_notions: list[str] | None = None,
) -> ControlledImportReport:
    _validate_runtime_path(output_dir)
    _validate_runtime_path(ledger_db_path.parent)
    taxonomy_paths = taxonomy_paths or list(DEFAULT_TAXONOMY_PATHS)
    priority_notions = priority_notions or list(DEFAULT_PRIORITY_NOTIONS)
    with _chdir(output_dir.parent):
        return controlled_import_manifest_directory(
            directory_path=manifest_dir,
            db_path=ledger_db_path,
            batch_id=batch_id,
            taxonomy_paths=taxonomy_paths,
            policy=QualityPolicy(),
            priority_notions=priority_notions,
            output_dir=output_dir,
            review_decision_path=review_decision_path,
            review_package_path=review_package_path,
            require_review=True,
            audit_ledger_db_path=ledger_db_path,
        )


def build_rehearsal_summary(
    *,
    workspace: Path,
    manifest_dir: Path,
    reports: RehearsalReports,
    decision: ReviewDecision,
    decision_path: Path,
    controlled_import_report: ControlledImportReport,
    ledger_db_path: Path,
    compile_status: str,
    batch_id: str,
) -> RehearsalSummary:
    ledger_audit_status = "recorded" if controlled_import_report.attempt_id else "missing"
    return RehearsalSummary(
        batch_id=batch_id,
        workspace=workspace,
        manifest_dir=manifest_dir,
        output_dir=reports.review_package.json_path.parent,
        ledger_db_path=ledger_db_path,
        compile_status=compile_status,
        dry_run_status=reports.dry_run.status,
        readiness_status=reports.readiness.status.value,
        coverage_status=reports.coverage.status.value,
        gate_status=reports.gate.status.value,
        review_status=reports.review_package.status.value,
        decision_status=decision.decision,
        controlled_import_status=controlled_import_report.status.value,
        ledger_audit_status=ledger_audit_status,
        review_decision_path=decision_path,
        review_notes=decision.notes or "",
        controlled_import_report_path=controlled_import_report.json_path,
    )


def run_metadata_rehearsal(
    draft_path: Path,
    base_dir: Path,
    batch_id: str = BATCH_ID,
    taxonomy_paths: list[Path] | None = None,
    priority_notions: list[str] | None = None,
) -> RehearsalSummary:
    workspace = build_rehearsal_workspace(base_dir)
    manifest_path = compile_draft_to_workspace_manifest(draft_path, workspace)
    manifest_dir = manifest_path.parent
    compile_status = validate_filled_draft(draft_path).status
    output_dir = workspace / "reports"
    ledger_db_path = workspace / "ledger" / "pilot_metadata_rehearsal.sqlite"
    reports = run_rehearsal_reports(
        manifest_dir=manifest_dir,
        output_dir=output_dir,
        batch_id=batch_id,
        taxonomy_paths=taxonomy_paths,
        priority_notions=priority_notions,
        ledger_db_path=ledger_db_path,
    )
    decision = build_synthetic_review_decision(
        reports.review_package.json_path,
        workspace / "reviews",
        ledger_db_path=ledger_db_path,
    )
    decision_path = _review_decision_path(decision, workspace / "reviews")
    controlled_import_report = run_controlled_metadata_import_rehearsal(
        manifest_dir=manifest_dir,
        output_dir=output_dir,
        ledger_db_path=ledger_db_path,
        review_package_path=reports.review_package.json_path,
        review_decision_path=decision_path,
        batch_id=batch_id,
        taxonomy_paths=taxonomy_paths,
        priority_notions=priority_notions,
    )
    return build_rehearsal_summary(
        workspace=workspace,
        manifest_dir=manifest_dir,
        reports=reports,
        decision=decision,
        decision_path=decision_path,
        controlled_import_report=controlled_import_report,
        ledger_db_path=ledger_db_path,
        compile_status=compile_status,
        batch_id=batch_id,
    )


def _print_summary(summary: RehearsalSummary) -> None:
    print("rehearsal summary:")
    for key in (
        "compile_status",
        "dry_run_status",
        "readiness_status",
        "coverage_status",
        "gate_status",
        "review_status",
        "decision_status",
        "controlled_import_status",
        "ledger_audit_status",
    ):
        print(f"{key}: {getattr(summary, key)}")
    print(f"workspace: {summary.workspace}")
    print(f"ledger: {summary.ledger_db_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run metadata-only pilot rehearsal in tmp space.")
    parser.add_argument("draft_path", type=Path)
    parser.add_argument("--batch-id", default=BATCH_ID)
    parser.add_argument("--tmp", action="store_true", help="run in a temporary directory")
    parser.add_argument("--workspace", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.tmp and args.workspace is None:
        raise SystemExit("--tmp or --workspace is required")
    if args.tmp:
        with tempfile.TemporaryDirectory(prefix="rag-pedago-pilot-rehearsal-") as temp_dir:
            summary = run_metadata_rehearsal(
                args.draft_path,
                Path(temp_dir),
                batch_id=args.batch_id,
            )
            _print_summary(summary)
            return 0
    summary = run_metadata_rehearsal(
        args.draft_path,
        args.workspace,
        batch_id=args.batch_id,
    )
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
