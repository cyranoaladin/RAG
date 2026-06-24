from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/pilot_corpus_scope.yml"

REQUIRED_SCOPE_VALUES = {
    "pilot_id": "math_terminale_specialite_metadata_only_v1",
    "status": "metadata_only_scope",
    "subject": "mathematiques",
    "level": "terminale",
    "track": "generale",
    "teaching": "specialite_mathematiques",
    "teaching_status": "specialite",
    "context": "aefe_tunisie",
    "candidate_status": "candidat_scolarise",
    "candidate_ref": "scolarise",
    "usage": "preparation_pedagogique_encadree_nexus_reussite",
}
REQUIRED_FALSE_FLAGS = [
    "real_documents_allowed",
    "pdf_allowed",
    "docx_allowed",
    "pptx_allowed",
    "xlsx_allowed",
    "ingestion_allowed",
    "parsing_allowed",
    "chunking_allowed",
    "embeddings_allowed",
    "qdrant_allowed",
    "network_allowed",
    "data_staging_allowed",
]
REQUIRED_METADATA_FIELDS = [
    "doc_id",
    "source_type",
    "source_uri",
    "sha256",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "type_doc",
    "epreuve",
    "candidat",
    "rights",
    "visibility",
    "official_refs",
    "official_level_ref",
    "official_subject_ref",
    "official_exam_ref",
    "candidate_status_ref",
    "establishment_context_ref",
    "notions",
    "competences",
    "objectifs",
    "difficulty",
    "school_year",
    "session",
]
REQUIRED_ALLOWED_RESOURCE_KINDS = [
    "synthetic_metadata",
    "versioned_fixture",
    "official_reference_metadata",
    "taxonomy_reference",
    "codex_report",
]
REQUIRED_EXCLUDED_RESOURCE_KINDS = [
    "real_document",
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "private_student_data",
    "unknown_rights",
    "qdrant_required",
    "embeddings_required",
]
REQUIRED_ACCEPTANCE_CHECKS = [
    "no_real_document",
    "rights_explicit",
    "visibility_explicit",
    "taxonomy_linked",
    "official_refs_checked",
    "metadata_only",
]
SAFE_RESOURCE_KINDS = {
    "synthetic_metadata",
    "versioned_fixture",
    "official_reference_metadata",
    "taxonomy_reference",
    "codex_report",
}


def _missing_ordered(required: list[str], observed: set[str]) -> list[str]:
    return [value for value in required if value not in observed]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a metadata-only pilot corpus scope.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args(argv)


def load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"_config_error": "config must be a YAML mapping"}
    return data


def _list_values(config: dict[str, Any], key: str) -> list[str]:
    value = config.get(key, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def audit_scope(config: dict[str, Any]) -> dict[str, list[str]]:
    invalid_scope_values: list[str] = []
    dangerous_flags_enabled: list[str] = []

    if isinstance(config.get("_config_error"), str):
        invalid_scope_values.append(str(config["_config_error"]))

    for key, expected in REQUIRED_SCOPE_VALUES.items():
        if config.get(key) != expected:
            invalid_scope_values.append(f"{key} must be {expected}")

    for flag in REQUIRED_FALSE_FLAGS:
        if config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    resource_kinds = set(_list_values(config, "allowed_resource_kinds"))
    unsafe_kinds = sorted(resource_kinds - SAFE_RESOURCE_KINDS)
    missing_allowed_resource_kinds = _missing_ordered(REQUIRED_ALLOWED_RESOURCE_KINDS, resource_kinds)

    excluded_resource_kinds = set(_list_values(config, "excluded_resource_kinds"))
    missing_excluded_resource_kinds = _missing_ordered(REQUIRED_EXCLUDED_RESOURCE_KINDS, excluded_resource_kinds)

    fields = set(_list_values(config, "required_metadata_fields"))
    missing_fields = _missing_ordered(REQUIRED_METADATA_FIELDS, fields)

    checks = set(_list_values(config, "acceptance_checks"))
    missing_checks = _missing_ordered(REQUIRED_ACCEPTANCE_CHECKS, checks)

    issues = [
        *invalid_scope_values,
        *dangerous_flags_enabled,
    ]
    if missing_fields:
        issues.append("missing required_metadata_fields: " + ", ".join(missing_fields))
    if unsafe_kinds:
        issues.append("unsafe allowed_resource_kinds: " + ", ".join(unsafe_kinds))
    if missing_allowed_resource_kinds:
        issues.append("missing allowed_resource_kinds: " + ", ".join(missing_allowed_resource_kinds))
    if missing_excluded_resource_kinds:
        issues.append("missing excluded_resource_kinds: " + ", ".join(missing_excluded_resource_kinds))
    if missing_checks:
        issues.append("missing acceptance_checks: " + ", ".join(missing_checks))

    return {
        "invalid_scope_values": invalid_scope_values,
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_required_metadata_fields": missing_fields,
        "unsafe_allowed_resource_kinds": unsafe_kinds,
        "missing_allowed_resource_kinds": missing_allowed_resource_kinds,
        "missing_excluded_resource_kinds": missing_excluded_resource_kinds,
        "missing_acceptance_checks": missing_checks,
        "issues": issues,
    }


def _print_list(values: list[str]) -> None:
    if not values:
        print("- none")
        return
    for value in values:
        print(f"- {value}")


def print_report(config: dict[str, Any], audit: dict[str, list[str]]) -> None:
    issues = audit["issues"]
    print("# Pilot corpus scope audit")
    print()
    print("## Summary")
    print()
    print(f"- pilot_id: {config.get('pilot_id', 'missing')}")
    print(f"- status: {config.get('status', 'missing')}")
    print(f"- scope_ready_for_review: {str(not issues).lower()}")
    print(f"- invalid_scope_values_count: {len(audit['invalid_scope_values'])}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_required_metadata_fields_count: {len(audit['missing_required_metadata_fields'])}")
    print(f"- unsafe_allowed_resource_kinds_count: {len(audit['unsafe_allowed_resource_kinds'])}")
    print(f"- missing_allowed_resource_kinds_count: {len(audit['missing_allowed_resource_kinds'])}")
    print(f"- missing_excluded_resource_kinds_count: {len(audit['missing_excluded_resource_kinds'])}")
    print(f"- missing_acceptance_checks_count: {len(audit['missing_acceptance_checks'])}")
    for flag in [
        "real_documents_allowed",
        "ingestion_allowed",
        "embeddings_allowed",
        "qdrant_allowed",
        "network_allowed",
        "data_staging_allowed",
    ]:
        print(f"- {flag}: {str(config.get(flag, 'missing')).lower()}")
    print("- destructive_action_available: false")
    print()
    print("## Invalid scope values")
    print()
    _print_list(audit["invalid_scope_values"])
    print()
    print("## Scope")
    print()
    for key in ["subject", "level", "track", "teaching", "context", "candidate_status", "usage"]:
        print(f"- {key}: {config.get(key, 'missing')}")
    print()
    print("## Allowed resource kinds")
    print()
    _print_list(_list_values(config, "allowed_resource_kinds"))
    print()
    print("## Excluded resource kinds")
    print()
    _print_list(_list_values(config, "excluded_resource_kinds"))
    print()
    print("## Required metadata fields")
    print()
    _print_list(_list_values(config, "required_metadata_fields"))
    print()
    print("## Acceptance checks")
    print()
    _print_list(_list_values(config, "acceptance_checks"))
    print()
    print("## Blocking issues")
    print()
    _print_list(issues)
    print()
    print("## Explicit non-actions")
    print()
    print("- no real document copied")
    print("- no PDF copied")
    print("- no ingestion launched")
    print("- no parsing launched")
    print("- no chunking launched")
    print("- no embedding created")
    print("- no Qdrant touched")
    print("- no network call")
    print("- no .env opened")
    print("- no data/staging created")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    audit = audit_scope(config)
    print_report(config, audit)
    return 1 if audit["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
