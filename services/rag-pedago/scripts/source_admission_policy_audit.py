from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/source_admission_policy.yml"

REQUIRED_POLICY_VALUES = {
    "policy_id": "source_admission_metadata_policy_v1",
    "status": "metadata_only_source_admission_policy",
    "pilot_scope_ref": "math_terminale_specialite_metadata_only_v1",
    "retrieval_eval_ref": "math_terminale_specialite_metadata_retrieval_eval_v1",
    "pedago_interface_ref": "pedago_interface_metadata_contract_v1",
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
    "server_start_allowed",
    "runtime_api_allowed",
    "data_staging_allowed",
]
REQUIRED_ALLOWED_SOURCE_KINDS = [
    "official_reference_metadata",
    "synthetic_learning_resource",
    "teacher_authored_metadata",
    "taxonomy_reference",
    "codex_report",
    "internal_protocol",
]
REQUIRED_FORBIDDEN_SOURCE_KINDS = [
    "real_document_file",
    "pdf_file",
    "docx_file",
    "pptx_file",
    "xlsx_file",
    "unknown_rights",
    "private_student_data",
    "external_url_unreviewed",
    "parsing_required",
    "embeddings_required",
    "qdrant_required",
]
REQUIRED_SOURCE_FIELDS = [
    "source_id",
    "title",
    "source_kind",
    "subject",
    "level",
    "track",
    "teaching_status",
    "provenance",
    "rights_status",
    "license_status",
    "visibility",
    "pii_status",
    "real_file_attached",
    "external_url_required",
    "human_review_required",
    "admission_decision",
    "refusal_reason",
]
ALLOWED_ADMISSION_DECISIONS = {
    "admit_metadata_only",
    "refuse_real_document",
    "refuse_unknown_rights",
    "refuse_private_data",
    "require_human_review",
}
SAFE_RIGHTS_STATUSES = {
    "allowed_for_metadata_reference",
    "owned_or_synthetic",
}
SAFE_LICENSE_STATUSES = {
    "metadata_reference_only",
    "internal_metadata_only",
}
REQUIRED_REFUSAL_REASONS = {
    "admit_metadata_only": "none",
    "refuse_real_document": "real_document",
    "refuse_unknown_rights": "rights_unknown",
    "refuse_private_data": "private_student_data",
    "require_human_review": "human_review_required",
}
DOCUMENT_FILE_SOURCE_KINDS = {
    "real_document_file",
    "pdf_file",
    "docx_file",
    "pptx_file",
    "xlsx_file",
}
KNOWN_PROVENANCE_STATUSES = {
    "official_reference_metadata",
    "synthetic_metadata",
    "teacher_authored_metadata",
    "taxonomy_reference",
    "codex_report",
    "internal_protocol",
    "unknown",
}
ALLOWED_VISIBILITIES = {
    "internal_review_only",
    "blocked",
}
FORBIDDEN_SOURCE_FIELDS = {
    "file_path",
    "path",
    "url",
    "uri",
    "checksum",
    "sha256",
    "content",
}
SCOPE_VALUES = {
    "subject": "mathematiques",
    "level": "terminale",
    "track": "generale",
    "teaching_status": "specialite",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a metadata-only source admission policy.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args(argv)


def load_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"_config_error": "config must be a YAML mapping"}
    return data


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _source_label(index: int, source: object) -> str:
    if isinstance(source, dict) and isinstance(source.get("source_id"), str):
        source_id = str(source["source_id"]).strip()
        if source_id:
            return source_id
    return f"index {index}"


def audit_config(config: dict[str, Any]) -> dict[str, list[str]]:
    config_errors: list[str] = []
    invalid_policy_values: list[str] = []
    dangerous_flags_enabled: list[str] = []
    missing_required_fields: list[str] = []
    malformed_sources: list[str] = []
    invalid_source_kinds: list[str] = []
    forbidden_source_fields: list[str] = []
    admission_decision_errors: list[str] = []
    rights_policy_errors: list[str] = []
    license_policy_errors: list[str] = []
    refusal_reason_errors: list[str] = []
    source_identity_errors: list[str] = []
    human_review_errors: list[str] = []
    source_kind_policy_errors: list[str] = []

    if isinstance(config.get("_config_error"), str):
        config_errors.append(str(config["_config_error"]))

    for field, expected_value in REQUIRED_POLICY_VALUES.items():
        if config.get(field) != expected_value:
            invalid_policy_values.append(f"{field} must be {expected_value}")

    for flag in REQUIRED_FALSE_FLAGS:
        if config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    allowed_source_kinds = set(_string_list(config.get("allowed_source_kinds")))
    forbidden_source_kinds = set(_string_list(config.get("forbidden_source_kinds")))
    configured_required_fields = set(_string_list(config.get("required_source_fields")))
    configured_decisions = set(_string_list(config.get("allowed_admission_decisions")))

    for kind in REQUIRED_ALLOWED_SOURCE_KINDS:
        if kind not in allowed_source_kinds:
            missing_required_fields.append(f"missing allowed_source_kinds: {kind}")
    for kind in REQUIRED_FORBIDDEN_SOURCE_KINDS:
        if kind not in forbidden_source_kinds:
            missing_required_fields.append(f"missing forbidden_source_kinds: {kind}")
    for field in REQUIRED_SOURCE_FIELDS:
        if field not in configured_required_fields:
            missing_required_fields.append(f"missing required_source_fields: {field}")
    for decision in ALLOWED_ADMISSION_DECISIONS:
        if decision not in configured_decisions:
            missing_required_fields.append(f"missing allowed_admission_decisions: {decision}")
    for kind in sorted(allowed_source_kinds.intersection(REQUIRED_FORBIDDEN_SOURCE_KINDS)):
        source_kind_policy_errors.append(f"allowed_source_kinds must not contain forbidden kind: {kind}")
    for kind in sorted(forbidden_source_kinds.intersection(REQUIRED_ALLOWED_SOURCE_KINDS)):
        source_kind_policy_errors.append(f"forbidden_source_kinds must not contain allowed kind: {kind}")
    for decision in sorted(configured_decisions.difference(ALLOWED_ADMISSION_DECISIONS)):
        source_kind_policy_errors.append(f"allowed_admission_decisions contains unknown decision: {decision}")

    candidate_sources = config.get("candidate_sources")
    if not isinstance(candidate_sources, list):
        malformed_sources.append("candidate_sources must be a list")
        candidate_sources = []

    known_source_kinds = allowed_source_kinds | forbidden_source_kinds
    allowed_decisions = configured_decisions.intersection(ALLOWED_ADMISSION_DECISIONS)
    seen_source_ids: set[str] = set()

    for index, source in enumerate(candidate_sources):
        if not isinstance(source, dict):
            malformed_sources.append(f"source at index {index} must be a mapping")
            continue

        label = _source_label(index, source)
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            source_identity_errors.append(f"source index {index} source_id must be a non-empty string")
        elif source_id in seen_source_ids:
            source_identity_errors.append(f"duplicate source_id: {source_id}")
        else:
            seen_source_ids.add(source_id)

        title = source.get("title")
        if not isinstance(title, str) or not title.strip():
            source_identity_errors.append(f"source {label} title must be a non-empty string")

        for field in REQUIRED_SOURCE_FIELDS:
            if field not in source:
                missing_required_fields.append(f"source {label} missing required field {field}")

        if source.get("human_review_required") is not True:
            human_review_errors.append(f"source {label} human_review_required must be true")

        for field, expected_value in SCOPE_VALUES.items():
            if source.get(field) != expected_value:
                malformed_sources.append(f"source {label} {field} must be {expected_value}")

        if source.get("real_file_attached") is not False:
            forbidden_source_fields.append(f"source {label} real_file_attached must be false")
        if source.get("external_url_required") is not False:
            forbidden_source_fields.append(f"source {label} external_url_required must be false")
        for field in sorted(FORBIDDEN_SOURCE_FIELDS):
            if field in source:
                forbidden_source_fields.append(f"source {label} forbidden field: {field}")

        source_kind = source.get("source_kind")
        decision = source.get("admission_decision")
        if not isinstance(source_kind, str) or source_kind not in known_source_kinds:
            invalid_source_kinds.append(f"source {label} source_kind must be declared")
        if source_kind in DOCUMENT_FILE_SOURCE_KINDS and decision != "refuse_real_document":
            admission_decision_errors.append(f"source {label} document file source_kind requires refuse_real_document")

        if not isinstance(decision, str) or decision not in allowed_decisions:
            admission_decision_errors.append(f"source {label} admission_decision must be allowed")

        rights_status = source.get("rights_status")
        license_status = source.get("license_status")
        provenance = source.get("provenance")
        visibility = source.get("visibility")
        pii_status = source.get("pii_status")
        refusal_reason = source.get("refusal_reason")
        if provenance not in KNOWN_PROVENANCE_STATUSES:
            rights_policy_errors.append(f"source {label} provenance must be declared")
        if visibility not in ALLOWED_VISIBILITIES:
            rights_policy_errors.append(f"source {label} visibility must be internal_review_only or blocked")
        if decision == "admit_metadata_only" and rights_status not in SAFE_RIGHTS_STATUSES:
            rights_policy_errors.append(f"source {label} admit_metadata_only requires safe rights_status")
        if decision == "admit_metadata_only" and license_status not in SAFE_LICENSE_STATUSES:
            license_policy_errors.append(f"source {label} admit_metadata_only requires safe license_status")
        if decision == "admit_metadata_only" and pii_status != "no_personal_data":
            rights_policy_errors.append(f"source {label} admit_metadata_only requires no_personal_data")
        if source_kind == "unknown_rights" and decision != "refuse_unknown_rights":
            rights_policy_errors.append(f"source {label} unknown_rights requires refuse_unknown_rights")
        if (
            rights_status == "unknown"
            and source_kind not in DOCUMENT_FILE_SOURCE_KINDS
            and decision != "refuse_unknown_rights"
        ):
            rights_policy_errors.append(f"source {label} unknown_rights requires refuse_unknown_rights")
        if (source_kind == "private_student_data" or pii_status == "private_student_data") and decision != "refuse_private_data":
            rights_policy_errors.append(f"source {label} private_student_data requires refuse_private_data")
        if decision in REQUIRED_REFUSAL_REASONS:
            expected_reason = REQUIRED_REFUSAL_REASONS[decision]
            if refusal_reason != expected_reason:
                refusal_reason_errors.append(f"source {label} refusal_reason must be {expected_reason}")

    issues = [
        *config_errors,
        *invalid_policy_values,
        *dangerous_flags_enabled,
        *missing_required_fields,
        *malformed_sources,
        *invalid_source_kinds,
        *forbidden_source_fields,
        *admission_decision_errors,
        *rights_policy_errors,
        *license_policy_errors,
        *refusal_reason_errors,
        *source_identity_errors,
        *human_review_errors,
        *source_kind_policy_errors,
    ]
    return {
        "config_errors": config_errors,
        "invalid_policy_values": invalid_policy_values,
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_required_fields": missing_required_fields,
        "malformed_sources": malformed_sources,
        "invalid_source_kinds": invalid_source_kinds,
        "forbidden_source_fields": forbidden_source_fields,
        "admission_decision_errors": admission_decision_errors,
        "rights_policy_errors": rights_policy_errors,
        "license_policy_errors": license_policy_errors,
        "refusal_reason_errors": refusal_reason_errors,
        "source_identity_errors": source_identity_errors,
        "human_review_errors": human_review_errors,
        "source_kind_policy_errors": source_kind_policy_errors,
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
    candidate_sources = config.get("candidate_sources")
    source_list = candidate_sources if isinstance(candidate_sources, list) else []
    admitted_count = 0
    refused_count = 0
    for source in source_list:
        if not isinstance(source, dict):
            continue
        if source.get("admission_decision") == "admit_metadata_only":
            admitted_count += 1
        if isinstance(source.get("admission_decision"), str) and str(source["admission_decision"]).startswith("refuse_"):
            refused_count += 1

    print("# Source admission policy audit")
    print()
    print("## Summary")
    print()
    print(f"- policy_id: {config.get('policy_id', 'missing')}")
    print(f"- status: {config.get('status', 'missing')}")
    print(f"- policy_ready_for_review: {str(not issues).lower()}")
    print(f"- candidate_sources_count: {len(source_list)}")
    print(f"- admitted_metadata_only_count: {admitted_count}")
    print(f"- refused_sources_count: {refused_count}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_required_fields_count: {len(audit['missing_required_fields'])}")
    print(f"- malformed_sources_count: {len(audit['malformed_sources'])}")
    print(f"- invalid_source_kinds_count: {len(audit['invalid_source_kinds'])}")
    print(f"- forbidden_source_fields_count: {len(audit['forbidden_source_fields'])}")
    print(f"- admission_decision_errors_count: {len(audit['admission_decision_errors'])}")
    print(f"- rights_policy_errors_count: {len(audit['rights_policy_errors'])}")
    print(f"- license_policy_errors_count: {len(audit['license_policy_errors'])}")
    print(f"- refusal_reason_errors_count: {len(audit['refusal_reason_errors'])}")
    print(f"- source_identity_errors_count: {len(audit['source_identity_errors'])}")
    print(f"- human_review_errors_count: {len(audit['human_review_errors'])}")
    print(f"- source_kind_policy_errors_count: {len(audit['source_kind_policy_errors'])}")
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
    print("## Candidate sources")
    print()
    for source in source_list:
        if isinstance(source, dict):
            print(f"- {source.get('source_id', 'missing')}: {source.get('admission_decision', 'missing')}")
    if not source_list:
        print("- none")
    print()
    print("## Allowed source kinds")
    print()
    _print_list(_string_list(config.get("allowed_source_kinds")))
    print()
    print("## Forbidden source kinds")
    print()
    _print_list(_string_list(config.get("forbidden_source_kinds")))
    print()
    print("## Required source fields")
    print()
    _print_list(_string_list(config.get("required_source_fields")))
    print()
    print("## License policy errors")
    print()
    _print_list(audit["license_policy_errors"])
    print()
    print("## Refusal reason errors")
    print()
    _print_list(audit["refusal_reason_errors"])
    print()
    print("## Source identity errors")
    print()
    _print_list(audit["source_identity_errors"])
    print()
    print("## Human review errors")
    print()
    _print_list(audit["human_review_errors"])
    print()
    print("## Source kind policy errors")
    print()
    _print_list(audit["source_kind_policy_errors"])
    print()
    print("## Blocking issues")
    print()
    _print_list(issues)
    print()
    print("## Explicit non-actions")
    print()
    print("- no real document read")
    print("- no PDF copied")
    print("- no DOCX copied")
    print("- no PPTX copied")
    print("- no XLSX copied")
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
    audit = audit_config(config)
    print_report(config, audit)
    return 1 if audit["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
