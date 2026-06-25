from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from rag_pedago.paths import PRODUCTION_RAG_UI_ROOT, RAG_LOCAL_ROOT

PLACEHOLDER_PREFIXES = ("A_REMPLIR", "A_CONFIRMER")
FORBIDDEN_SOURCE_PATHS = (
    str(PRODUCTION_RAG_UI_ROOT),
    str(RAG_LOCAL_ROOT),
)
SECRET_LIKE_MARKERS = (
    "secret",
    "credential",
    "creds",
    "gdrive",
    ".env",
    ".pem",
    ".key",
)
REQUIRED_FIELDS = (
    "doc_id",
    "source_uri",
    "source_type",
    "sha256",
    "discovered_at",
    "rights",
    "visibility",
    "matiere",
    "type_doc",
)


class TemplateValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    status: str
    items_count: int
    issue_count: int
    issues: list[dict[str, str]] = Field(default_factory=list)


def _issue(code: str, field: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "field": field,
        "message": message,
    }


def load_pilot_manifest_template(path: Path) -> dict[str, Any]:
    if path.suffix in {".yml", ".yaml"}:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"template YAML must contain a mapping: {path}")
        return payload
    if path.suffix == ".jsonl":
        items = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {"items": items}
    raise ValueError(f"unsupported template format: {path}")


def iter_template_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("template must contain an items list")
    return [item for item in items if isinstance(item, dict)]


def _walk_placeholders(value: Any, path: str) -> list[str]:
    if isinstance(value, str) and value.startswith(PLACEHOLDER_PREFIXES):
        return [path]
    if isinstance(value, dict):
        fields: list[str] = []
        for key, nested in value.items():
            nested_path = f"{path}.{key}" if path else str(key)
            fields.extend(_walk_placeholders(nested, nested_path))
        return fields
    if isinstance(value, list):
        fields = []
        for index, nested in enumerate(value):
            nested_path = f"{path}[{index}]"
            fields.extend(_walk_placeholders(nested, nested_path))
        return fields
    return []


def find_unfilled_placeholders(item: dict[str, Any]) -> list[str]:
    return sorted(_walk_placeholders(item, ""))


def validate_template_item_shape(item: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for field in REQUIRED_FIELDS:
        if field not in item:
            issues.append(
                _issue(
                    code="missing_required_field",
                    field=field,
                    message=f"required field is missing: {field}",
                    severity="error",
                )
            )
    return issues


def validate_no_real_source_access(item: dict[str, Any]) -> list[dict[str, str]]:
    source_uri = str(item.get("source_uri", ""))
    issues: list[dict[str, str]] = []
    for forbidden in FORBIDDEN_SOURCE_PATHS:
        if forbidden in source_uri:
            issues.append(
                _issue(
                    code="forbidden_source_uri_path",
                    field="source_uri",
                    message=f"source_uri points to forbidden path: {forbidden}",
                    severity="error",
                )
            )
    lowered = source_uri.lower()
    if any(marker in lowered for marker in SECRET_LIKE_MARKERS):
        issues.append(
            _issue(
                code="secret_like_source_uri",
                field="source_uri",
                message="source_uri contains a secret-like path marker",
                severity="error",
            )
        )
    return issues


def validate_manual_metadata_rules(item: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if item.get("rights") == "unknown":
        issues.append(
            _issue(
                code="unknown_rights",
                field="rights",
                message="rights=unknown must be qualified before retrieval",
                severity="error",
            )
        )

    candidat = item.get("candidat")
    candidate_status_ref = item.get("candidate_status_ref")
    if candidat == "scolarise" and candidate_status_ref not in {None, "A_REMPLIR", "scolarise"}:
        issues.append(
            _issue(
                code="candidate_status_mismatch",
                field="candidate_status_ref",
                message="candidat=scolarise requires candidate_status_ref=scolarise",
                severity="error",
            )
        )

    extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
    zone = extra.get("zone")  # type: ignore[union-attr]
    establishment_context_ref = item.get("establishment_context_ref")
    if zone == "aefe_tunisie" and establishment_context_ref != "aefe":
        issues.append(
            _issue(
                code="aefe_context_missing",
                field="establishment_context_ref",
                message="AEFE Tunisie metadata requires establishment_context_ref=aefe",
                severity="error",
            )
        )
    if establishment_context_ref == "aefe" and zone != "aefe_tunisie":
        issues.append(
            _issue(
                code="aefe_zone_missing",
                field="extra.zone",
                message="establishment_context_ref=aefe requires extra.zone=aefe_tunisie",
                severity="error",
            )
        )
    return issues


def build_template_validation_report(path: Path) -> TemplateValidationReport:
    data = load_pilot_manifest_template(path)
    items = iter_template_items(data)
    issues: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        prefix = f"items[{index}]"
        issues.extend(
            {
                **issue,
                "field": f"{prefix}.{issue['field']}" if issue["field"] else prefix,
            }
            for issue in validate_template_item_shape(item)
        )
        issues.extend(
            _issue(
                code="placeholder_unfilled",
                field=f"{prefix}.{field}",
                message=f"placeholder must be filled manually: {field}",
                severity="info",
            )
            for field in find_unfilled_placeholders(item)
        )
        issues.extend(
            {
                **issue,
                "field": f"{prefix}.{issue['field']}" if issue["field"] else prefix,
            }
            for issue in validate_no_real_source_access(item)
        )
        issues.extend(
            {
                **issue,
                "field": f"{prefix}.{issue['field']}" if issue["field"] else prefix,
            }
            for issue in validate_manual_metadata_rules(item)
        )

    status = "ready" if not issues else "needs_completion"
    return TemplateValidationReport(
        path=path,
        status=status,
        items_count=len(items),
        issue_count=len(issues),
        issues=issues,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a pilot manifest template offline.")
    parser.add_argument("template_path", type=Path)
    args = parser.parse_args()

    report = build_template_validation_report(args.template_path)
    print(f"pilot manifest template checked: {report.path}")
    print(f"status: {report.status}")
    print(f"items: {report.items_count}")
    print(f"issues: {report.issue_count}")
    for issue in report.issues[:20]:
        print(
            "- "
            f"{issue['severity']} | {issue['code']} | {issue['field']} | {issue['message']}"
        )
    if report.issue_count > 20:
        print(f"... {report.issue_count - 20} more issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
