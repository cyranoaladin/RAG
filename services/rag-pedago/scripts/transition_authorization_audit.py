from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/transition_authorization.yml"

REQUIRED_AUTHORIZATION_VALUES = {
    "authorization_id": "transition_authorization_metadata_policy_v1",
    "status": "metadata_only_transition_authorization",
    "controlled_readiness_ref": "controlled_readiness_metadata_gate_v1",
    "human_source_review_ref": "human_source_review_metadata_policy_v1",
    "source_admission_policy_ref": "source_admission_metadata_policy_v1",
    "pedago_interface_ref": "pedago_interface_metadata_contract_v1",
    "retrieval_eval_ref": "math_terminale_specialite_metadata_retrieval_eval_v1",
    "pilot_scope_ref": "math_terminale_specialite_metadata_only_v1",
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

# Flags authorized at true via transition_authorization.yml + ADR
AUTHORIZED_TRUE_FLAGS: dict[str, str] = {
    "network_allowed": "ADR-0004",
    "data_staging_allowed": "ADR-0004",
    "pdf_allowed": "ADR-0004",
    "parsing_allowed": "ADR-0004",
    "chunking_allowed": "ADR-0006",
    "embeddings_allowed": "ADR-0007",
}

REQUIRED_AUTHORIZATION_FIELDS = [
    "authorization_case_id",
    "readiness_gate",
    "decision",
    "decision_reason",
    "final_human_signoff_required",
    "rights_confirmation_required",
    "provenance_confirmation_required",
    "pii_absence_required",
    "rollback_plan_required",
    "checksum_plan_required",
    "separate_real_lot_required",
    "real_corpus_authorized",
    "real_file_authorized",
    "pipeline_authorized",
]
ALLOWED_AUTHORIZATION_DECISIONS = {
    "authorize_metadata_only_preparation",
    "require_final_human_signoff",
    "block_real_corpus_transition",
    "defer_to_separate_real_lot",
}
REQUIRED_DECISION_REASONS = {
    "authorize_metadata_only_preparation": "metadata_only_preparation_allowed",
    "block_real_corpus_transition": "real_corpus_requires_separate_authorization",
    "require_final_human_signoff": "final_human_signoff_missing",
    "defer_to_separate_real_lot": "separate_real_lot_required",
}
REQUIRED_AUTHORIZATION_DECISION_COVERAGE = {
    "authorize_metadata_only_preparation",
    "require_final_human_signoff",
    "block_real_corpus_transition",
    "defer_to_separate_real_lot",
}
REQUIRED_TRUE_SAFETY_FIELDS = [
    "final_human_signoff_required",
    "rights_confirmation_required",
    "provenance_confirmation_required",
    "pii_absence_required",
    "rollback_plan_required",
    "checksum_plan_required",
    "separate_real_lot_required",
]
REQUIRED_FALSE_SAFETY_FIELDS = [
    "real_corpus_authorized",
    "real_file_authorized",
    "pipeline_authorized",
]
FORBIDDEN_AUTHORIZATION_FIELDS = {
    "file_path",
    "path",
    "source_uri",
    "url",
    "uri",
    "checksum",
    "sha256",
    "content",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a metadata-only transition authorization policy.")
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


def _authorization_label(index: int, authorization_case: object) -> str:
    if isinstance(authorization_case, dict) and isinstance(authorization_case.get("authorization_case_id"), str):
        authorization_case_id = str(authorization_case["authorization_case_id"]).strip()
        if authorization_case_id:
            return authorization_case_id
    return f"index {index}"


def audit_config(config: dict[str, Any]) -> dict[str, list[str]]:
    config_errors: list[str] = []
    invalid_authorization_values: list[str] = []
    dangerous_flags_enabled: list[str] = []
    missing_required_fields: list[str] = []
    malformed_authorization_cases: list[str] = []
    authorization_identity_errors: list[str] = []
    authorization_decision_errors: list[str] = []
    authorization_decision_coverage_errors: list[str] = []
    authorization_safety_errors: list[str] = []
    forbidden_authorization_fields: list[str] = []

    if isinstance(config.get("_config_error"), str):
        config_errors.append(str(config["_config_error"]))

    for field, expected_value in REQUIRED_AUTHORIZATION_VALUES.items():
        if config.get(field) != expected_value:
            invalid_authorization_values.append(f"{field} must be {expected_value}")

    for flag in REQUIRED_FALSE_FLAGS:
        if flag in AUTHORIZED_TRUE_FLAGS:
            if config.get(flag) is not True:
                dangerous_flags_enabled.append(
                    f"{flag} must be true (authorized under {AUTHORIZED_TRUE_FLAGS[flag]})"
                )
        elif config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    configured_decisions = set(_string_list(config.get("allowed_authorization_decisions")))
    configured_fields = set(_string_list(config.get("required_authorization_fields")))

    for decision in ALLOWED_AUTHORIZATION_DECISIONS:
        if decision not in configured_decisions:
            missing_required_fields.append(f"missing allowed_authorization_decisions: {decision}")
    for decision in sorted(configured_decisions.difference(ALLOWED_AUTHORIZATION_DECISIONS)):
        authorization_decision_errors.append(f"allowed_authorization_decisions contains unknown decision: {decision}")
    for field in REQUIRED_AUTHORIZATION_FIELDS:
        if field not in configured_fields:
            missing_required_fields.append(f"missing required_authorization_fields: {field}")

    authorization_cases = config.get("authorization_cases")
    if not isinstance(authorization_cases, list) or not authorization_cases:
        malformed_authorization_cases.append("authorization_cases must be a non-empty list")
        authorization_cases = []

    seen_authorization_case_ids: set[str] = set()
    covered_decisions: set[str] = set()
    for index, authorization_case in enumerate(authorization_cases):
        if not isinstance(authorization_case, dict):
            malformed_authorization_cases.append(f"authorization case at index {index} must be a mapping")
            continue

        label = _authorization_label(index, authorization_case)
        authorization_case_id = authorization_case.get("authorization_case_id")
        if not isinstance(authorization_case_id, str) or not authorization_case_id.strip():
            authorization_identity_errors.append(
                f"authorization case index {index} authorization_case_id must be a non-empty string"
            )
        elif authorization_case_id in seen_authorization_case_ids:
            authorization_identity_errors.append(f"duplicate authorization_case_id: {authorization_case_id}")
        else:
            seen_authorization_case_ids.add(authorization_case_id)

        for field in REQUIRED_AUTHORIZATION_FIELDS:
            if field not in authorization_case:
                missing_required_fields.append(f"authorization {label} missing required field {field}")

        if authorization_case.get("readiness_gate") != "controlled_readiness_metadata_gate_v1":
            authorization_decision_errors.append(
                f"authorization {label} readiness_gate must be controlled_readiness_metadata_gate_v1"
            )

        decision = authorization_case.get("decision")
        if not isinstance(decision, str) or decision not in configured_decisions.intersection(ALLOWED_AUTHORIZATION_DECISIONS):
            authorization_decision_errors.append(f"authorization {label} decision must be allowed")
        else:
            covered_decisions.add(decision)

        decision_reason = authorization_case.get("decision_reason")
        if not isinstance(decision_reason, str) or not decision_reason.strip():
            authorization_decision_errors.append(f"authorization {label} decision_reason must be a non-empty string")

        for field in REQUIRED_TRUE_SAFETY_FIELDS:
            if authorization_case.get(field) is not True:
                authorization_safety_errors.append(f"authorization {label} {field} must be true")

        for field in REQUIRED_FALSE_SAFETY_FIELDS:
            if authorization_case.get(field) is not False:
                authorization_safety_errors.append(f"authorization {label} {field} must be false")

        if decision in REQUIRED_DECISION_REASONS:
            expected_reason = REQUIRED_DECISION_REASONS[decision]
            if decision_reason != expected_reason:
                authorization_decision_errors.append(f"{decision} requires decision_reason {expected_reason}")

        for field in sorted(FORBIDDEN_AUTHORIZATION_FIELDS):
            if field in authorization_case:
                forbidden_authorization_fields.append(f"authorization {label} forbidden field: {field}")

    for decision in sorted(REQUIRED_AUTHORIZATION_DECISION_COVERAGE):
        if decision not in covered_decisions:
            authorization_decision_coverage_errors.append(f"missing authorization case for decision: {decision}")
    for decision in sorted(configured_decisions.intersection(ALLOWED_AUTHORIZATION_DECISIONS)):
        if decision not in covered_decisions:
            authorization_decision_coverage_errors.append(f"allowed decision has no authorization case: {decision}")

    issues = [
        *config_errors,
        *invalid_authorization_values,
        *dangerous_flags_enabled,
        *missing_required_fields,
        *malformed_authorization_cases,
        *authorization_identity_errors,
        *authorization_decision_errors,
        *authorization_decision_coverage_errors,
        *authorization_safety_errors,
        *forbidden_authorization_fields,
    ]
    return {
        "config_errors": config_errors,
        "invalid_authorization_values": invalid_authorization_values,
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_required_fields": missing_required_fields,
        "malformed_authorization_cases": malformed_authorization_cases,
        "authorization_identity_errors": authorization_identity_errors,
        "authorization_decision_errors": authorization_decision_errors,
        "authorization_decision_coverage_errors": authorization_decision_coverage_errors,
        "authorization_safety_errors": authorization_safety_errors,
        "forbidden_authorization_fields": forbidden_authorization_fields,
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
    authorization_cases = config.get("authorization_cases")
    case_list = authorization_cases if isinstance(authorization_cases, list) else []
    metadata_only_authorized_count = 0
    blocked_real_corpus_count = 0
    human_signoff_required_count = 0
    deferred_real_lot_count = 0
    for authorization_case in case_list:
        if not isinstance(authorization_case, dict):
            continue
        decision = authorization_case.get("decision")
        if decision == "authorize_metadata_only_preparation":
            metadata_only_authorized_count += 1
        if decision == "block_real_corpus_transition":
            blocked_real_corpus_count += 1
        if decision == "require_final_human_signoff":
            human_signoff_required_count += 1
        if decision == "defer_to_separate_real_lot":
            deferred_real_lot_count += 1

    print("# Transition authorization audit")
    print()
    print("## Summary")
    print()
    print(f"- authorization_id: {config.get('authorization_id', 'missing')}")
    print(f"- status: {config.get('status', 'missing')}")
    print(f"- authorization_ready_for_review: {str(not issues).lower()}")
    print(f"- authorization_cases_count: {len(case_list)}")
    print(f"- metadata_only_authorized_count: {metadata_only_authorized_count}")
    print(f"- blocked_real_corpus_count: {blocked_real_corpus_count}")
    print(f"- human_signoff_required_count: {human_signoff_required_count}")
    print(f"- deferred_real_lot_count: {deferred_real_lot_count}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_required_fields_count: {len(audit['missing_required_fields'])}")
    print(f"- malformed_authorization_cases_count: {len(audit['malformed_authorization_cases'])}")
    print(f"- authorization_identity_errors_count: {len(audit['authorization_identity_errors'])}")
    print(f"- authorization_decision_errors_count: {len(audit['authorization_decision_errors'])}")
    print(f"- authorization_decision_coverage_errors_count: {len(audit['authorization_decision_coverage_errors'])}")
    print(f"- authorization_safety_errors_count: {len(audit['authorization_safety_errors'])}")
    print(f"- forbidden_authorization_fields_count: {len(audit['forbidden_authorization_fields'])}")
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
    print("## Authorization cases")
    print()
    for authorization_case in case_list:
        if isinstance(authorization_case, dict):
            print(
                f"- {authorization_case.get('authorization_case_id', 'missing')}: "
                f"{authorization_case.get('decision', 'missing')}"
            )
    if not case_list:
        print("- none")
    print()
    print("## Allowed authorization decisions")
    print()
    _print_list(_string_list(config.get("allowed_authorization_decisions")))
    print()
    print("## Required authorization fields")
    print()
    _print_list(_string_list(config.get("required_authorization_fields")))
    print()
    print("## Authorization decision coverage errors")
    print()
    _print_list(audit["authorization_decision_coverage_errors"])
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
