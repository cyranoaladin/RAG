from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/human_source_review.yml"

REQUIRED_POLICY_VALUES = {
    "review_policy_id": "human_source_review_metadata_policy_v1",
    "status": "metadata_only_human_source_review",
    "source_admission_policy_ref": "source_admission_metadata_policy_v1",
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
REQUIRED_REVIEW_ROLES = [
    "reviewer_pedagogique",
    "reviewer_droits",
    "reviewer_technique",
    "responsable_validation",
]
ALLOWED_REVIEW_DECISIONS = {
    "approve_metadata_only",
    "reject_real_document",
    "reject_unknown_rights",
    "reject_private_data",
    "request_more_information",
    "defer_until_real_source_lot",
}
REQUIRED_REVIEW_FIELDS = [
    "review_id",
    "source_id",
    "reviewer_role",
    "decision",
    "decision_reason",
    "rights_checked",
    "provenance_checked",
    "pii_checked",
    "visibility_checked",
    "no_real_file_confirmed",
    "no_external_url_confirmed",
    "human_validation_required",
]
REQUIRED_DECISION_REASONS = {
    "reject_unknown_rights": "rights_unknown",
    "reject_private_data": "private_student_data",
    "reject_real_document": "real_document",
    "defer_until_real_source_lot": "real_source_requires_separate_lot",
}
APPROVAL_CHECK_FIELDS = [
    "rights_checked",
    "provenance_checked",
    "pii_checked",
    "visibility_checked",
]
FORBIDDEN_REVIEW_FIELDS = {
    "file_path",
    "path",
    "url",
    "uri",
    "checksum",
    "sha256",
    "content",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a metadata-only human source review policy.")
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


def _review_label(index: int, review_case: object) -> str:
    if isinstance(review_case, dict) and isinstance(review_case.get("review_id"), str):
        review_id = str(review_case["review_id"]).strip()
        if review_id:
            return review_id
    return f"index {index}"


def audit_config(config: dict[str, Any]) -> dict[str, list[str]]:
    config_errors: list[str] = []
    invalid_policy_values: list[str] = []
    dangerous_flags_enabled: list[str] = []
    missing_required_roles: list[str] = []
    missing_required_fields: list[str] = []
    malformed_review_cases: list[str] = []
    review_identity_errors: list[str] = []
    review_decision_errors: list[str] = []
    review_check_errors: list[str] = []
    forbidden_review_fields: list[str] = []
    known_source_errors: list[str] = []
    role_coverage_errors: list[str] = []
    source_decision_conflicts: list[str] = []

    if isinstance(config.get("_config_error"), str):
        config_errors.append(str(config["_config_error"]))

    for field, expected_value in REQUIRED_POLICY_VALUES.items():
        if config.get(field) != expected_value:
            invalid_policy_values.append(f"{field} must be {expected_value}")

    for flag in REQUIRED_FALSE_FLAGS:
        if config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    configured_roles = set(_string_list(config.get("required_review_roles")))
    configured_decisions = set(_string_list(config.get("allowed_review_decisions")))
    configured_fields = set(_string_list(config.get("required_review_fields")))
    raw_known_source_ids = config.get("known_source_ids")
    configured_known_source_ids = _string_list(raw_known_source_ids)

    for role in REQUIRED_REVIEW_ROLES:
        if role not in configured_roles:
            missing_required_roles.append(f"missing required_review_roles: {role}")
    for decision in ALLOWED_REVIEW_DECISIONS:
        if decision not in configured_decisions:
            missing_required_fields.append(f"missing allowed_review_decisions: {decision}")
    for decision in sorted(configured_decisions.difference(ALLOWED_REVIEW_DECISIONS)):
        review_decision_errors.append(f"allowed_review_decisions contains unknown decision: {decision}")
    for field in REQUIRED_REVIEW_FIELDS:
        if field not in configured_fields:
            missing_required_fields.append(f"missing required_review_fields: {field}")

    review_cases = config.get("review_cases")
    if not isinstance(review_cases, list):
        malformed_review_cases.append("review_cases must be a list")
        review_cases = []

    allowed_roles = configured_roles.intersection(REQUIRED_REVIEW_ROLES)
    allowed_decisions = configured_decisions.intersection(ALLOWED_REVIEW_DECISIONS)
    seen_review_ids: set[str] = set()
    seen_known_source_ids: set[str] = set()
    used_roles: set[str] = set()
    decisions_by_source_id: dict[str, set[str]] = {}

    if (
        not isinstance(raw_known_source_ids, list)
        or not configured_known_source_ids
        or len(configured_known_source_ids) != len(raw_known_source_ids)
    ):
        known_source_errors.append("known_source_ids must be a non-empty list of strings")
    for source_id in configured_known_source_ids:
        if source_id in seen_known_source_ids:
            known_source_errors.append(f"duplicate known_source_ids: {source_id}")
        seen_known_source_ids.add(source_id)

    for index, review_case in enumerate(review_cases):
        if not isinstance(review_case, dict):
            malformed_review_cases.append(f"review case at index {index} must be a mapping")
            continue

        label = _review_label(index, review_case)
        review_id = review_case.get("review_id")
        if not isinstance(review_id, str) or not review_id.strip():
            review_identity_errors.append(f"review index {index} review_id must be a non-empty string")
        elif review_id in seen_review_ids:
            review_identity_errors.append(f"duplicate review_id: {review_id}")
        else:
            seen_review_ids.add(review_id)

        source_id = review_case.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            review_identity_errors.append(f"review {label} source_id must be a non-empty string")
        elif source_id not in seen_known_source_ids:
            known_source_errors.append(f"review {label} source_id must be listed in known_source_ids")

        for field in REQUIRED_REVIEW_FIELDS:
            if field not in review_case:
                missing_required_fields.append(f"review {label} missing required field {field}")

        reviewer_role = review_case.get("reviewer_role")
        if not isinstance(reviewer_role, str) or reviewer_role not in allowed_roles:
            review_decision_errors.append(f"review {label} reviewer_role must be allowed")
        else:
            used_roles.add(reviewer_role)

        decision = review_case.get("decision")
        if not isinstance(decision, str) or decision not in allowed_decisions:
            review_decision_errors.append(f"review {label} decision must be allowed")
        elif isinstance(source_id, str) and source_id.strip():
            decisions_by_source_id.setdefault(source_id, set()).add(decision)

        decision_reason = review_case.get("decision_reason")
        if not isinstance(decision_reason, str) or not decision_reason.strip():
            review_decision_errors.append(f"review {label} decision_reason must be a non-empty string")

        if review_case.get("human_validation_required") is not True:
            review_check_errors.append(f"review {label} human_validation_required must be true")
        if review_case.get("no_real_file_confirmed") is not True:
            review_check_errors.append(f"review {label} no_real_file_confirmed must be true")
        if review_case.get("no_external_url_confirmed") is not True:
            review_check_errors.append(f"review {label} no_external_url_confirmed must be true")

        if decision == "approve_metadata_only":
            if reviewer_role != "responsable_validation":
                review_decision_errors.append("approve_metadata_only must be reviewed by responsable_validation")
            for check_field in APPROVAL_CHECK_FIELDS:
                if review_case.get(check_field) is not True:
                    review_check_errors.append(f"review {label} approve_metadata_only requires {check_field} true")

        if decision == "defer_until_real_source_lot" and reviewer_role != "responsable_validation":
            review_decision_errors.append("defer_until_real_source_lot must be reviewed by responsable_validation")

        if decision in REQUIRED_DECISION_REASONS:
            expected_reason = REQUIRED_DECISION_REASONS[decision]
            if decision_reason != expected_reason:
                review_decision_errors.append(f"{decision} requires decision_reason {expected_reason}")

        for field in sorted(FORBIDDEN_REVIEW_FIELDS):
            if field in review_case:
                forbidden_review_fields.append(f"review {label} forbidden field: {field}")

    for role in sorted(configured_roles):
        if role not in used_roles:
            role_coverage_errors.append(f"required role {role} must appear in review_cases")

    for source_id, decisions in sorted(decisions_by_source_id.items()):
        if "approve_metadata_only" in decisions and any(decision.startswith("reject_") for decision in decisions):
            source_decision_conflicts.append(f"source {source_id} cannot be both approved and rejected")
        if "approve_metadata_only" in decisions and "defer_until_real_source_lot" in decisions:
            source_decision_conflicts.append(f"source {source_id} cannot be both approved and deferred")

    issues = [
        *config_errors,
        *invalid_policy_values,
        *dangerous_flags_enabled,
        *missing_required_roles,
        *missing_required_fields,
        *malformed_review_cases,
        *review_identity_errors,
        *review_decision_errors,
        *review_check_errors,
        *forbidden_review_fields,
        *known_source_errors,
        *role_coverage_errors,
        *source_decision_conflicts,
    ]
    return {
        "config_errors": config_errors,
        "invalid_policy_values": invalid_policy_values,
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_required_roles": missing_required_roles,
        "missing_required_fields": missing_required_fields,
        "malformed_review_cases": malformed_review_cases,
        "review_identity_errors": review_identity_errors,
        "review_decision_errors": review_decision_errors,
        "review_check_errors": review_check_errors,
        "forbidden_review_fields": forbidden_review_fields,
        "known_source_errors": known_source_errors,
        "role_coverage_errors": role_coverage_errors,
        "source_decision_conflicts": source_decision_conflicts,
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
    review_cases = config.get("review_cases")
    case_list = review_cases if isinstance(review_cases, list) else []
    approved_count = 0
    rejected_count = 0
    deferred_count = 0
    for review_case in case_list:
        if not isinstance(review_case, dict):
            continue
        decision = review_case.get("decision")
        if decision == "approve_metadata_only":
            approved_count += 1
        if isinstance(decision, str) and decision.startswith("reject_"):
            rejected_count += 1
        if decision == "defer_until_real_source_lot":
            deferred_count += 1

    print("# Human source review audit")
    print()
    print("## Summary")
    print()
    print(f"- review_policy_id: {config.get('review_policy_id', 'missing')}")
    print(f"- status: {config.get('status', 'missing')}")
    print(f"- review_ready_for_review: {str(not issues).lower()}")
    print(f"- review_cases_count: {len(case_list)}")
    print(f"- approved_metadata_only_count: {approved_count}")
    print(f"- rejected_cases_count: {rejected_count}")
    print(f"- deferred_cases_count: {deferred_count}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_required_roles_count: {len(audit['missing_required_roles'])}")
    print(f"- missing_required_fields_count: {len(audit['missing_required_fields'])}")
    print(f"- malformed_review_cases_count: {len(audit['malformed_review_cases'])}")
    print(f"- review_identity_errors_count: {len(audit['review_identity_errors'])}")
    print(f"- review_decision_errors_count: {len(audit['review_decision_errors'])}")
    print(f"- review_check_errors_count: {len(audit['review_check_errors'])}")
    print(f"- forbidden_review_fields_count: {len(audit['forbidden_review_fields'])}")
    print(f"- known_source_errors_count: {len(audit['known_source_errors'])}")
    print(f"- role_coverage_errors_count: {len(audit['role_coverage_errors'])}")
    print(f"- source_decision_conflicts_count: {len(audit['source_decision_conflicts'])}")
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
    print("## Review cases")
    print()
    for review_case in case_list:
        if isinstance(review_case, dict):
            print(f"- {review_case.get('review_id', 'missing')}: {review_case.get('decision', 'missing')}")
    if not case_list:
        print("- none")
    print()
    print("## Required review roles")
    print()
    _print_list(_string_list(config.get("required_review_roles")))
    print()
    print("## Allowed review decisions")
    print()
    _print_list(_string_list(config.get("allowed_review_decisions")))
    print()
    print("## Required review fields")
    print()
    _print_list(_string_list(config.get("required_review_fields")))
    print()
    print("## Known source errors")
    print()
    _print_list(audit["known_source_errors"])
    print()
    print("## Role coverage errors")
    print()
    _print_list(audit["role_coverage_errors"])
    print()
    print("## Source decision conflicts")
    print()
    _print_list(audit["source_decision_conflicts"])
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
