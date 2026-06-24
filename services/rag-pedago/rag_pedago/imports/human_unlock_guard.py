from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rag_pedago.paths import PRODUCTION_RAG_UI_ROOT, RAG_LOCAL_ROOT

APPROVED_STATUS = "approved_for_metadata_only_next_step"
EXPECTED_VALUES = {
    "decision": "approved",
    "scope": "real_minimal_metadata_only_draft",
    "allowed_zone": "aefe_tunisie",
    "allowed_candidate_status": "scolarise",
    "allowed_subject": "mathematiques",
    "allowed_level": "terminale",
    "allowed_track": "generale",
    "allowed_teaching": "specialite",
}
REQUIRED_TRUE_FLAGS = (
    "rights_checked",
    "sha256_checked_outside_pipeline",
    "no_personal_data",
    "no_real_document_copied",
    "no_source_uri_opening_allowed",
    "no_parsing_allowed",
    "no_embedding_allowed",
    "no_" + "qd" + "rant" + "_allowed",
    "no_scraping_allowed",
    "no_data_staging_allowed",
    "no_permanent_ledger_write_allowed",
)
FORBIDDEN_MARKERS = (
    str(PRODUCTION_RAG_UI_ROOT),
    str(RAG_LOCAL_ROOT),
    ".env",
    ".pem",
    ".key",
    "gdrive",
    "credential",
    "secret",
    "".join(("OPENAI", "_API_KEY")),
    "".join(("QDRANT", "_URL")),
    "".join(("POSTGRES", "_URL")),
    "BEGIN PRIVATE KEY",
)
PLACEHOLDER_PREFIXES = ("A_REMPLIR", "A_CONFIRMER")


def _issue(code: str, field: str, message: str, severity: str = "error") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


def load_human_unlock(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"human unlock JSON must contain an object: {path}")
    return data


def _walk_values(value: Any, field_path: str) -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(field_path, value)]
    if isinstance(value, dict):
        values: list[tuple[str, str]] = []
        for key, nested in value.items():
            nested_path = f"{field_path}.{key}" if field_path else str(key)
            values.extend(_walk_values(nested, nested_path))
        return values
    if isinstance(value, list):
        values = []
        for index, nested in enumerate(value):
            values.extend(_walk_values(nested, f"{field_path}[{index}]"))
        return values
    return []


def find_unlock_placeholders(data: dict) -> list[dict]:
    issues: list[dict] = []
    for field, value in _walk_values(data, ""):
        if value.startswith(PLACEHOLDER_PREFIXES):
            issues.append(
                _issue(
                    code="placeholder_unfilled",
                    field=field,
                    message=f"placeholder must be filled by a human: {field}",
                )
            )
    return issues


def _forbidden_marker_issues(data: dict) -> list[dict]:
    issues: list[dict] = []
    for field, value in _walk_values(data, ""):
        lowered = value.lower()
        for marker in FORBIDDEN_MARKERS:
            if marker.lower() in lowered:
                issues.append(
                    _issue(
                        code="forbidden_marker",
                        field=field,
                        message=f"forbidden marker is present: {marker}",
                    )
                )
    return issues


def validate_human_unlock(data: dict) -> list[dict]:
    issues: list[dict] = []
    issues.extend(find_unlock_placeholders(data))
    issues.extend(_forbidden_marker_issues(data))

    if data.get("decision") != EXPECTED_VALUES["decision"]:
        issues.append(
            _issue(
                code="decision_not_approved",
                field="decision",
                message="decision must be approved",
            )
        )
    if data.get("scope") != EXPECTED_VALUES["scope"]:
        issues.append(
            _issue(
                code="invalid_scope",
                field="scope",
                message="scope must be real_minimal_metadata_only_draft",
            )
        )
    if data.get("max_items", 0) > 2:
        issues.append(
            _issue(
                code="too_many_items",
                field="max_items",
                message="max_items must be 2 or less",
            )
        )
    for field in REQUIRED_TRUE_FLAGS:
        if data.get(field) is not True:
            issues.append(
                _issue(
                    code="unsafe_permission_enabled",
                    field=field,
                    message=f"{field} must be true",
                )
            )
    for field in (
        "allowed_zone",
        "allowed_candidate_status",
        "allowed_subject",
        "allowed_level",
        "allowed_track",
        "allowed_teaching",
    ):
        if data.get(field) != EXPECTED_VALUES[field]:
            issues.append(
                _issue(
                    code="wrong_allowed_context",
                    field=field,
                    message=f"{field} must be {EXPECTED_VALUES[field]}",
                )
            )
    return issues


def build_human_unlock_report(path: Path) -> dict:
    data = load_human_unlock(path)
    issues = validate_human_unlock(data)
    return {
        "status": APPROVED_STATUS if not issues else "blocked",
        "issue_count": len(issues),
        "issues": issues,
        "decision": data.get("decision"),
        "scope": data.get("scope"),
        "max_items": data.get("max_items"),
        "reviewer_present": bool(data.get("reviewer_name") and data.get("reviewer_role")),
        "reviewed_at_present": bool(data.get("reviewed_at")),
    }


def _print_report(report: dict) -> None:
    print("human unlock guard report:")
    print(f"status: {report['status']}")
    print(f"decision: {report['decision']}")
    print(f"scope: {report['scope']}")
    print(f"max_items: {report['max_items']}")
    print(f"issues: {report['issue_count']}")
    for issue in report["issues"][:20]:
        print(
            "- "
            f"{issue['severity']} | {issue['code']} | {issue['field']} | {issue['message']}"
        )
    if report["issue_count"] > 20:
        print(f"... {report['issue_count'] - 20} more issues")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a human unlock JSON file offline.")
    parser.add_argument("unlock_path", type=Path)
    args = parser.parse_args(argv)

    report = build_human_unlock_report(args.unlock_path)
    _print_report(report)
    return 0 if report["status"] == APPROVED_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
