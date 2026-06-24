from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from rag_pedago.paths import PRODUCTION_RAG_UI_ROOT, RAG_LOCAL_ROOT


FORBIDDEN_SOURCE_ROOTS = (
    str(PRODUCTION_RAG_UI_ROOT),
    str(RAG_LOCAL_ROOT),
)
SENSITIVE_SOURCE_MARKERS = (
    ".env",
    ".pem",
    ".key",
    "gdrive",
    "credential",
    "secret",
)
INTERNAL_RIGHTS = {"nexus_proprietaire", "usage_interne", "restricted"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _issue(code: str, field: str, message: str, severity: str = "error") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


def validate_candidate_source_uri(source_uri: str) -> list[dict]:
    issues: list[dict] = []
    lowered = source_uri.lower()
    for forbidden_root in FORBIDDEN_SOURCE_ROOTS:
        if forbidden_root in source_uri:
            issues.append(
                _issue(
                    code="forbidden_source_uri_path",
                    field="source_uri",
                    message=f"source_uri points to forbidden root: {forbidden_root}",
                )
            )
    for marker in SENSITIVE_SOURCE_MARKERS:
        if marker in lowered:
            issues.append(
                _issue(
                    code="sensitive_source_uri",
                    field="source_uri",
                    message=f"source_uri contains forbidden marker: {marker}",
                )
            )
    return issues


def _official_refs(item: dict) -> list[str]:
    refs: list[str] = []
    for field in ("official_source_refs", "official_claim_refs"):
        value = item.get(field)
        if isinstance(value, str):
            refs.append(value)
        elif isinstance(value, list):
            refs.extend(str(candidate) for candidate in value)
    return refs


def _prefixed(index: int, issues: list[dict]) -> list[dict]:
    prefix = f"items[{index}]"
    return [
        {
            **issue,
            "field": f"{prefix}.{issue['field']}" if issue.get("field") else prefix,
        }
        for issue in issues
    ]


def validate_real_draft_metadata(item: dict) -> list[dict]:
    issues: list[dict] = []
    issues.extend(validate_candidate_source_uri(str(item.get("source_uri", ""))))

    rights = item.get("rights")
    visibility = item.get("visibility")
    if rights == "unknown":
        issues.append(
            _issue(
                code="unknown_rights",
                field="rights",
                message="rights=unknown must be resolved before any real metadata draft proceeds",
            )
        )
    if visibility == "public" and rights in INTERNAL_RIGHTS:
        issues.append(
            _issue(
                code="public_internal_rights",
                field="visibility",
                message="internal or restricted rights cannot use visibility=public",
            )
        )

    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    if extra.get("zone") == "aefe_tunisie" and item.get("establishment_context_ref") != "aefe":
        issues.append(
            _issue(
                code="aefe_context_mismatch",
                field="establishment_context_ref",
                message="extra.zone=aefe_tunisie requires establishment_context_ref=aefe",
            )
        )
    if item.get("candidat") == "scolarise" and item.get("candidate_status_ref") != "scolarise":
        issues.append(
            _issue(
                code="candidate_status_mismatch",
                field="candidate_status_ref",
                message="candidat=scolarise requires candidate_status_ref=scolarise",
            )
        )

    refs = _official_refs(item)
    if refs and all(ref == "pending" for ref in refs):
        issues.append(
            _issue(
                code="pending_official_source_only",
                field="official_source_refs",
                message="a pending official source cannot be the only regulatory support",
            )
        )

    sha256 = item.get("sha256")
    if not sha256:
        issues.append(
            _issue(
                code="missing_sha256",
                field="sha256",
                message="sha256 must be provided from a manual out-of-pipeline calculation",
            )
        )
    elif not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
        issues.append(
            _issue(
                code="invalid_sha256",
                field="sha256",
                message="sha256 must be exactly 64 hexadecimal characters",
            )
        )

    if extra.get("manual_human_review_required") is not True:
        issues.append(
            _issue(
                code="missing_human_review_unlock",
                field="extra.manual_human_review_required",
                message="extra.manual_human_review_required=true is required",
            )
        )
    return issues


def validate_human_unlock_file(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return [
            _issue(
                code="invalid_unlock_file",
                field="unlock_file",
                message="unlock file must contain a JSON object",
            )
        ]
    if payload.get("human_review_locked") is not True:
        return [
            _issue(
                code="missing_human_lock",
                field="human_review_locked",
                message="human_review_locked=true is required",
            )
        ]
    return []


def build_real_draft_guard_report(
    items: list[dict],
    unlock_file: Path | None = None,
) -> dict:
    issues: list[dict] = []
    for index, item in enumerate(items, start=1):
        issues.extend(_prefixed(index, validate_real_draft_metadata(item)))
    if unlock_file is not None:
        issues.extend(validate_human_unlock_file(unlock_file))
    return {
        "status": "ready_for_human_locked_metadata_validation" if not issues else "blocked",
        "item_count": len(items),
        "issue_count": len(issues),
        "issues": issues,
    }


def _load_items(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, dict)]
    raise ValueError("candidate metadata must be a JSON list, JSON object with items, or JSONL")


def _print_report(report: dict) -> None:
    print("real draft guard report:")
    print(f"status: {report['status']}")
    print(f"items: {report['item_count']}")
    print(f"issues: {report['issue_count']}")
    for issue in report["issues"][:20]:
        print(
            "- "
            f"{issue['severity']} | {issue['code']} | {issue['field']} | {issue['message']}"
        )
    if report["issue_count"] > 20:
        print(f"... {report['issue_count'] - 20} more issues")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate real draft metadata guardrails offline.")
    parser.add_argument("candidate_path", type=Path)
    parser.add_argument("--unlock-file", type=Path, default=None)
    args = parser.parse_args(argv)

    report = build_real_draft_guard_report(
        _load_items(args.candidate_path),
        unlock_file=args.unlock_file,
    )
    _print_report(report)
    return 0 if report["status"] == "ready_for_human_locked_metadata_validation" else 1


if __name__ == "__main__":
    raise SystemExit(main())
