from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rag_pedago.imports.pilot_manifest_template import (
    find_unfilled_placeholders,
    validate_manual_metadata_rules,
    validate_no_real_source_access,
    validate_template_item_shape,
)
from schema.document import DocumentMeta


class CompileReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    status: str
    items_count: int
    issue_count: int
    jsonl_line_count: int = 0
    issues: list[dict[str, str]] = Field(default_factory=list)


def _issue(code: str, field: str, message: str, severity: str = "error") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


def load_filled_draft(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"filled draft must contain a mapping: {path}")
    return payload


def iter_filled_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("filled draft must contain an items list")
    return [item for item in items if isinstance(item, dict)]


def validate_filled_item(item: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    issues.extend(validate_template_item_shape(item))
    issues.extend(
        _issue(
            code="placeholder_unfilled",
            field=field,
            message=f"placeholder remains in filled draft: {field}",
        )
        for field in find_unfilled_placeholders(item)
    )
    issues.extend(validate_no_real_source_access(item))
    issues.extend(validate_manual_metadata_rules(item))
    try:
        DocumentMeta.model_validate(item)
    except ValidationError as exc:
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            issues.append(
                _issue(
                    code="document_meta_validation_error",
                    field=location,
                    message=str(error.get("msg", "DocumentMeta validation failed")),
                )
            )
    return issues


def _prefixed_issues(index: int, issues: list[dict[str, str]]) -> list[dict[str, str]]:
    prefix = f"items[{index}]"
    return [
        {
            **issue,
            "field": f"{prefix}.{issue['field']}" if issue["field"] else prefix,
        }
        for issue in issues
    ]


def _validated_metas(path: Path) -> tuple[list[DocumentMeta], list[dict[str, str]], int]:
    items = iter_filled_items(load_filled_draft(path))
    metas: list[DocumentMeta] = []
    issues: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        item_issues = validate_filled_item(item)
        issues.extend(_prefixed_issues(index, item_issues))
        if not item_issues:
            metas.append(DocumentMeta.model_validate(item))
    return metas, issues, len(items)


def validate_filled_draft(path: Path) -> CompileReport:
    metas, issues, items_count = _validated_metas(path)
    return CompileReport(
        path=path,
        status="ready" if not issues else "blocked",
        items_count=items_count,
        issue_count=len(issues),
        jsonl_line_count=len(metas) if not issues else 0,
        issues=issues,
    )


def compile_filled_draft_to_jsonl_text(path: Path) -> str:
    report = validate_filled_draft(path)
    if report.status != "ready":
        raise ValueError(f"filled draft is not ready: {path}")
    metas, _, _ = _validated_metas(path)
    rows = [
        json.dumps(meta.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for meta in sorted(metas, key=lambda candidate: candidate.doc_id)
    ]
    return "\n".join(rows) + "\n"


def build_compile_report(path: Path) -> CompileReport:
    report = validate_filled_draft(path)
    if report.status == "ready":
        report.jsonl_line_count = len(compile_filled_draft_to_jsonl_text(path).splitlines())
    return report


def _print_report(report: CompileReport) -> None:
    print(f"filled draft checked: {report.path}")
    print(f"status: {report.status}")
    print(f"items: {report.items_count}")
    print(f"issues: {report.issue_count}")
    print(f"jsonl_lines: {report.jsonl_line_count}")
    for issue in report.issues[:20]:
        print(
            "- "
            f"{issue['severity']} | {issue['code']} | {issue['field']} | {issue['message']}"
        )
    if report.issue_count > 20:
        print(f"... {report.issue_count - 20} more issues")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile a filled pilot manifest draft offline.")
    parser.add_argument("draft_path", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate the draft and print a report")
    mode.add_argument("--emit-jsonl", action="store_true", help="print compiled JSONL to stdout")
    args = parser.parse_args()

    if args.emit_jsonl:
        print(compile_filled_draft_to_jsonl_text(args.draft_path), end="")
        return 0

    _print_report(build_compile_report(args.draft_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
