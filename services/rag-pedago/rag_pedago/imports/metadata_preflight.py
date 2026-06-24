from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from rag_pedago.imports.human_unlock_guard import build_human_unlock_report
from rag_pedago.imports.pilot_manifest_compiler import build_compile_report
from rag_pedago.imports.pilot_manifest_template import build_template_validation_report
from rag_pedago.imports.pilot_metadata_rehearsal import run_metadata_rehearsal
from rag_pedago.imports.real_draft_guard import build_real_draft_guard_report
from rag_pedago.imports.real_draft_unlock_gate import build_unlock_gate_report
from rag_pedago.paths import REPO_ROOT

TEMPLATE_PATH = REPO_ROOT / "docs/templates/pilot_math_terminale/pilot_manifest.template.yml"
FILLED_DRAFT_PATH = (
    REPO_ROOT
    / "data/fixtures/pilot_math_terminale/filled_drafts/pilot_manifest.filled.valid.yml"
)
REAL_DRAFT_GUARD_PATH = (
    REPO_ROOT
    / "data/fixtures/pilot_math_terminale/real_draft_guard/metadata_candidate.valid.jsonl"
)
HUMAN_UNLOCK_PATH = (
    REPO_ROOT
    / "data/fixtures/pilot_math_terminale/human_unlock/human_unlock.valid.json"
)
UNLOCK_GATE_UNLOCK_PATH = (
    REPO_ROOT
    / "data/fixtures/pilot_math_terminale/real_draft_unlock_gate/unlock.valid.json"
)
UNLOCK_GATE_DRAFT_PATH = (
    REPO_ROOT
    / "data/fixtures/pilot_math_terminale/real_draft_unlock_gate/draft.valid.jsonl"
)
PERMANENT_LEDGER_PATH = REPO_ROOT / "data/ledger/rag_pedago.sqlite"
REAL_DOCUMENT_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx"}
EXPECTED_REHEARSAL_STATUSES = {
    "compile_status": "ready",
    "dry_run_status": "dry_run_success",
    "readiness_status": "ready",
    "coverage_status": "coverage_ok",
    "gate_status": "ready_for_controlled_import",
    "review_status": "ready_for_review",
    "decision_status": "approved",
    "controlled_import_status": "imported",
    "ledger_audit_status": "recorded",
}


def _issue(code: str, field: str, message: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": "error",
        "field": field,
        "message": message,
    }


def _check(name: str, status: str, expected_status: str, details: dict | None = None) -> dict:
    ok = status == expected_status
    return {
        "name": name,
        "status": status,
        "expected_status": expected_status,
        "ok": ok,
        "issues": [] if ok else [_issue("unexpected_status", name, f"{status} != {expected_status}")],
        "details": details or {},
    }


def _jsonl_items(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _ledger_marker() -> tuple[bool, int | None]:
    try:
        return True, PERMANENT_LEDGER_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return False, None


def _ledger_unchanged(marker: tuple[bool, int | None]) -> bool:
    existed, mtime = marker
    try:
        current_mtime = PERMANENT_LEDGER_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return not existed
    return existed and current_mtime == mtime


def _real_documents_absent() -> bool:
    roots = (
        REPO_ROOT / "data/fixtures/pilot_math_terminale",
        REPO_ROOT / "docs/templates",
    )
    for root in roots:
        for candidate in root.rglob("*"):
            if candidate.is_file() and candidate.suffix.lower() in REAL_DOCUMENT_SUFFIXES:
                return False
    return True


def _prefixed_issues(check: dict) -> list[dict]:
    return [
        {
            **issue,
            "field": f"{check['name']}.{issue.get('field', '')}".rstrip("."),
        }
        for issue in check.get("issues", [])
    ]


def run_template_check() -> dict:
    report = build_template_validation_report(TEMPLATE_PATH)
    return _check(
        "template",
        report.status,
        "needs_completion",
        {"items_count": report.items_count, "issue_count": report.issue_count},
    )


def run_compile_check() -> dict:
    report = build_compile_report(FILLED_DRAFT_PATH)
    return _check(
        "compile",
        report.status,
        "ready",
        {
            "items_count": report.items_count,
            "issue_count": report.issue_count,
            "jsonl_line_count": report.jsonl_line_count,
        },
    )


def run_rehearsal_check(base_dir: Path | None = None) -> dict:
    if base_dir is None:
        with tempfile.TemporaryDirectory(prefix="rag-pedago-metadata-preflight-") as temp_dir:
            return run_rehearsal_check(Path(temp_dir))

    summary = run_metadata_rehearsal(
        FILLED_DRAFT_PATH,
        base_dir,
        batch_id="metadata-preflight-rehearsal",
    )
    details = {
        key: getattr(summary, key)
        for key in EXPECTED_REHEARSAL_STATUSES
    }
    issues = [
        _issue("unexpected_rehearsal_status", key, f"{details[key]} != {expected}")
        for key, expected in EXPECTED_REHEARSAL_STATUSES.items()
        if details[key] != expected
    ]
    status = "rehearsal_ok" if not issues else "blocked"
    return {
        "name": "rehearsal",
        "status": status,
        "expected_status": "rehearsal_ok",
        "ok": not issues,
        "issues": issues,
        "details": details,
    }


def run_real_draft_guard_check() -> dict:
    report = build_real_draft_guard_report(_jsonl_items(REAL_DRAFT_GUARD_PATH))
    return _check(
        "real_draft_guard",
        report["status"],
        "ready_for_human_locked_metadata_validation",
        {"item_count": report["item_count"], "issue_count": report["issue_count"]},
    )


def run_human_unlock_check() -> dict:
    report = build_human_unlock_report(HUMAN_UNLOCK_PATH)
    return _check(
        "human_unlock",
        report["status"],
        "approved_for_metadata_only_next_step",
        {
            "issue_count": report["issue_count"],
            "decision": report["decision"],
            "scope": report["scope"],
            "max_items": report["max_items"],
        },
    )


def run_unlock_gate_check() -> dict:
    report = build_unlock_gate_report(UNLOCK_GATE_UNLOCK_PATH, UNLOCK_GATE_DRAFT_PATH)
    return _check(
        "unlock_gate",
        report["status"],
        "approved_for_real_metadata_draft_preparation",
        {
            "issue_count": report["issue_count"],
            "item_count": report["item_count"],
            "max_items": report["max_items"],
            "unlock_status": report["unlock_status"],
            "draft_status": report["draft_status"],
        },
    )


def build_metadata_preflight_report(base_dir: Path | None = None) -> dict:
    ledger_marker = _ledger_marker()
    checks = [
        run_template_check(),
        run_compile_check(),
        run_rehearsal_check(base_dir=base_dir),
        run_real_draft_guard_check(),
        run_human_unlock_check(),
        run_unlock_gate_check(),
    ]
    data_staging_absent = not (REPO_ROOT / "data/staging").is_dir()
    permanent_ledger_unchanged = _ledger_unchanged(ledger_marker)
    real_documents_absent = _real_documents_absent()

    issues: list[dict] = []
    for check in checks:
        if not check.get("ok"):
            issues.extend(_prefixed_issues(check))
    if not data_staging_absent:
        issues.append(_issue("data_staging_present", "data/staging", "data/staging must be absent"))
    if not permanent_ledger_unchanged:
        issues.append(
            _issue(
                "permanent_ledger_changed",
                "data/ledger/rag_pedago.sqlite",
                "permanent ledger marker changed during preflight",
            )
        )
    if not real_documents_absent:
        issues.append(
            _issue(
                "real_document_present",
                "fixtures_or_templates",
                "real document suffix detected in checked metadata-only directories",
            )
        )

    status = "metadata_preflight_ready" if not issues else "blocked"
    status_by_name = {check["name"]: check["status"] for check in checks}
    return {
        "status": status,
        "issue_count": len(issues),
        "issues": issues,
        "checks": checks,
        "template_status": status_by_name["template"],
        "compile_status": status_by_name["compile"],
        "rehearsal_status": status_by_name["rehearsal"],
        "real_draft_guard_status": status_by_name["real_draft_guard"],
        "human_unlock_status": status_by_name["human_unlock"],
        "unlock_gate_status": status_by_name["unlock_gate"],
        "data_staging_absent": data_staging_absent,
        "permanent_ledger_unchanged": permanent_ledger_unchanged,
        "real_documents_absent": real_documents_absent,
        "limitations": {
            "pedagogical_content_validated": False,
            "ingestion_authorized": False,
            "real_draft_created": False,
            "ready_manifest_created": False,
        },
    }


def _print_report(report: dict) -> None:
    print("metadata preflight report:")
    print(f"status: {report['status']}")
    print(f"issues: {report['issue_count']}")
    for key in (
        "template_status",
        "compile_status",
        "rehearsal_status",
        "real_draft_guard_status",
        "human_unlock_status",
        "unlock_gate_status",
        "data_staging_absent",
        "permanent_ledger_unchanged",
        "real_documents_absent",
    ):
        if key in report:
            print(f"{key}: {report[key]}")
    for issue in report["issues"][:20]:
        print(
            "- "
            f"{issue['severity']} | {issue['code']} | {issue['field']} | {issue['message']}"
        )
    if report["issue_count"] > 20:
        print(f"... {report['issue_count'] - 20} more issues")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run global metadata-only preflight.")
    parser.parse_args(argv)
    report = build_metadata_preflight_report()
    _print_report(report)
    return 0 if report["status"] == "metadata_preflight_ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
