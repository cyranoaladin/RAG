from __future__ import annotations

import argparse
import json
from pathlib import Path

from rag_pedago.imports.human_unlock_guard import (
    APPROVED_STATUS,
    build_human_unlock_report,
    load_human_unlock,
)
from rag_pedago.imports.real_draft_guard import build_real_draft_guard_report

APPROVED_GATE_STATUS = "approved_for_real_metadata_draft_preparation"
DRAFT_READY_STATUS = "ready_for_human_locked_metadata_validation"


def _issue(code: str, field: str, message: str, severity: str = "error") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


def load_unlock(path: Path) -> dict:
    return load_human_unlock(path)


def load_draft_items(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _item_value(item: dict, field: str) -> object:
    if field == "extra.zone":
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        return extra.get("zone")
    if field == "extra.manual_human_review_required":
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        return extra.get("manual_human_review_required")
    return item.get(field)


def validate_unlock_and_draft(unlock: dict, items: list[dict]) -> list[dict]:
    issues: list[dict] = []
    max_items = unlock.get("max_items")
    if isinstance(max_items, int) and len(items) > max_items:
        issues.append(
            _issue(
                code="item_count_exceeds_unlock",
                field="items",
                message=f"draft item count {len(items)} exceeds max_items {max_items}",
            )
        )

    comparisons = (
        ("matiere", "allowed_subject", "item_subject_out_of_scope"),
        ("niveau", "allowed_level", "item_level_out_of_scope"),
        ("voie", "allowed_track", "item_track_out_of_scope"),
        ("statut_enseignement", "allowed_teaching", "item_teaching_out_of_scope"),
        ("extra.zone", "allowed_zone", "item_zone_out_of_scope"),
        ("candidat", "allowed_candidate_status", "item_candidate_status_out_of_scope"),
    )
    for index, item in enumerate(items, start=1):
        prefix = f"items[{index}]"
        for item_field, unlock_field, code in comparisons:
            expected = unlock.get(unlock_field)
            actual = _item_value(item, item_field)
            if actual != expected:
                issues.append(
                    _issue(
                        code=code,
                        field=f"{prefix}.{item_field}",
                        message=f"{item_field}={actual!r} does not match {unlock_field}={expected!r}",
                    )
                )
        if _item_value(item, "extra.manual_human_review_required") is not True:
            issues.append(
                _issue(
                    code="missing_human_review_unlock",
                    field=f"{prefix}.extra.manual_human_review_required",
                    message="extra.manual_human_review_required=true is required",
                )
            )
        if "batch_id" in item and item.get("batch_id") != unlock.get("batch_id"):
            issues.append(
                _issue(
                    code="batch_id_mismatch",
                    field=f"{prefix}.batch_id",
                    message="item batch_id must match unlock batch_id when present",
                )
            )
    return issues


def build_unlock_gate_report(unlock_path: Path, draft_path: Path) -> dict:
    unlock = load_unlock(unlock_path)
    items = load_draft_items(draft_path)
    unlock_report = build_human_unlock_report(unlock_path)
    draft_report = build_real_draft_guard_report(items)
    issues: list[dict] = []

    if unlock_report["status"] != APPROVED_STATUS:
        issues.append(
            _issue(
                code="human_unlock_blocked",
                field="unlock",
                message="human unlock guard did not approve the authorization",
            )
        )
        issues.extend(unlock_report.get("issues", []))
    if draft_report["status"] != DRAFT_READY_STATUS:
        issues.append(
            _issue(
                code="draft_guard_blocked",
                field="draft",
                message="real draft guard did not approve the metadata candidate",
            )
        )
        issues.extend(draft_report.get("issues", []))

    issues.extend(validate_unlock_and_draft(unlock, items))

    return {
        "status": APPROVED_GATE_STATUS if not issues else "blocked",
        "issue_count": len(issues),
        "item_count": len(items),
        "unlock_status": unlock_report["status"],
        "draft_status": draft_report["status"],
        "max_items": unlock.get("max_items"),
        "issues": issues,
    }


def _print_report(report: dict) -> None:
    print("real draft unlock gate report:")
    print(f"status: {report['status']}")
    print(f"unlock_status: {report['unlock_status']}")
    print(f"draft_status: {report['draft_status']}")
    print(f"items: {report['item_count']}")
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
    parser = argparse.ArgumentParser(description="Validate combined human unlock and real draft metadata gate.")
    parser.add_argument("unlock_path", type=Path)
    parser.add_argument("draft_path", type=Path)
    args = parser.parse_args(argv)

    report = build_unlock_gate_report(args.unlock_path, args.draft_path)
    _print_report(report)
    return 0 if report["status"] == APPROVED_GATE_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())

