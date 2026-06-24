from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/metadata_review_handoff.yml"
GOVERNANCE_CONFIG = REPO_ROOT / "configs/metadata_governance_chain.yml"
GOVERNANCE_REPORT = REPO_ROOT / "data/reports/codex_lot_17J_metadata_governance_chain.md"
GOVERNANCE_READY_MARKER = "READY_FOR_METADATA_GOVERNANCE_CHAIN_REVIEW"

REQUIRED_HANDOFF_VALUES = {
    "handoff_id": "metadata_review_handoff_17C_17J_v1",
    "status": "metadata_only_review_handoff",
    "governance_chain_ref": "metadata_governance_chain_17C_17I_v1",
    "latest_lot_ref": "17J",
    "latest_commit_ref": "d78b5dbae68d493266e89257781a3ec7df47e44b",
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
REQUIRED_REVIEW_ROLES = {
    "reviewer_pedagogique",
    "reviewer_droits",
    "reviewer_technique",
    "responsable_validation",
}
REQUIRED_HANDOFF_FIELDS = [
    "handoff_case_id",
    "reviewed_chain_ref",
    "decision",
    "decision_reason",
    "reviewer_role",
    "human_review_required",
    "real_action_allowed",
    "real_file_allowed",
    "pipeline_allowed",
    "followup_lot_required",
    "rollback_later_required",
    "checksum_later_required",
]
ALLOWED_HANDOFF_DECISIONS = {
    "ready_for_human_metadata_review",
    "require_more_metadata_hardening",
    "block_any_real_action",
    "defer_until_named_followup_lot",
}
REQUIRED_DECISION_REASONS = {
    "ready_for_human_metadata_review": "governance_chain_complete_metadata_only",
    "require_more_metadata_hardening": "metadata_hardening_required_before_handoff",
    "block_any_real_action": "real_action_not_authorized_by_handoff",
    "defer_until_named_followup_lot": "followup_lot_must_be_named_and_scoped",
}
REQUIRED_DECISION_COVERAGE = {
    "ready_for_human_metadata_review",
    "require_more_metadata_hardening",
    "block_any_real_action",
    "defer_until_named_followup_lot",
}
TRUE_CASE_FIELDS = [
    "human_review_required",
    "followup_lot_required",
    "rollback_later_required",
    "checksum_later_required",
]
FALSE_CASE_FIELDS = ["real_action_allowed", "real_file_allowed", "pipeline_allowed"]
FORBIDDEN_HANDOFF_FIELDS = {"file_path", "path", "url", "uri", "source_uri", "checksum", "sha256", "content"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the metadata-only review handoff.")
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


def _case_label(index: int, case: object) -> str:
    if isinstance(case, dict) and isinstance(case.get("handoff_case_id"), str) and str(case["handoff_case_id"]).strip():
        return str(case["handoff_case_id"]).strip()
    return f"index {index}"


def _validate_references() -> list[str]:
    errors: list[str] = []
    if not GOVERNANCE_CONFIG.is_file():
        errors.append("missing 17J governance config")
    if not GOVERNANCE_REPORT.is_file():
        errors.append("missing 17J governance report")
        return errors
    report = GOVERNANCE_REPORT.read_text(encoding="utf-8")
    if GOVERNANCE_READY_MARKER not in report:
        errors.append("17J governance report must contain READY_FOR_METADATA_GOVERNANCE_CHAIN_REVIEW")
    return errors


def audit_config(config: dict[str, Any]) -> dict[str, list[str]]:
    config_errors: list[str] = []
    invalid_handoff_values: list[str] = []
    dangerous_flags_enabled: list[str] = []
    missing_required_roles: list[str] = []
    missing_required_fields: list[str] = []
    malformed_handoff_cases: list[str] = []
    handoff_identity_errors: list[str] = []
    handoff_decision_errors: list[str] = []
    handoff_decision_coverage_errors: list[str] = []
    handoff_safety_errors: list[str] = []
    forbidden_handoff_fields: list[str] = []
    reference_errors: list[str] = []

    if isinstance(config.get("_config_error"), str):
        config_errors.append(str(config["_config_error"]))

    for field, expected_value in REQUIRED_HANDOFF_VALUES.items():
        if config.get(field) != expected_value:
            invalid_handoff_values.append(f"{field} must be {expected_value}")

    for flag in REQUIRED_FALSE_FLAGS:
        if config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    declared_roles = set(_string_list(config.get("required_review_roles")))
    for role in sorted(REQUIRED_REVIEW_ROLES):
        if role not in declared_roles:
            missing_required_roles.append(f"missing required review role: {role}")

    allowed_decisions = set(_string_list(config.get("allowed_handoff_decisions")))
    for decision in sorted(allowed_decisions - ALLOWED_HANDOFF_DECISIONS):
        handoff_decision_errors.append(f"unknown allowed handoff decision: {decision}")
    for decision in sorted(ALLOWED_HANDOFF_DECISIONS - allowed_decisions):
        handoff_decision_errors.append(f"missing allowed handoff decision: {decision}")

    declared_fields = set(_string_list(config.get("required_handoff_fields")))
    for field in REQUIRED_HANDOFF_FIELDS:
        if field not in declared_fields:
            missing_required_fields.append(f"missing required handoff field declaration: {field}")

    cases = config.get("handoff_cases")
    if not isinstance(cases, list) or not cases:
        malformed_handoff_cases.append("handoff_cases must be a non-empty list")
        cases = []

    seen_ids: set[str] = set()
    covered_decisions: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            malformed_handoff_cases.append(f"handoff case at index {index} must be a mapping")
            continue

        label = _case_label(index, case)
        case_id = case.get("handoff_case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            handoff_identity_errors.append(f"handoff case at index {index} missing non-empty handoff_case_id")
        elif case_id in seen_ids:
            handoff_identity_errors.append(f"duplicate handoff_case_id: {case_id}")
        else:
            seen_ids.add(case_id)

        for field in REQUIRED_HANDOFF_FIELDS:
            if field not in case:
                missing_required_fields.append(f"handoff {label} missing required field: {field}")

        forbidden = sorted(field for field in FORBIDDEN_HANDOFF_FIELDS if field in case)
        for field in forbidden:
            forbidden_handoff_fields.append(f"handoff {label} forbidden field: {field}")

        if case.get("reviewed_chain_ref") != REQUIRED_HANDOFF_VALUES["governance_chain_ref"]:
            handoff_decision_errors.append(
                f"handoff {label} reviewed_chain_ref must be {REQUIRED_HANDOFF_VALUES['governance_chain_ref']}"
            )

        role = case.get("reviewer_role")
        if role not in REQUIRED_REVIEW_ROLES:
            handoff_decision_errors.append(f"handoff {label} unknown reviewer_role: {role}")

        decision = case.get("decision")
        if decision not in ALLOWED_HANDOFF_DECISIONS:
            handoff_decision_errors.append(f"handoff {label} unknown decision: {decision}")
        elif isinstance(decision, str):
            covered_decisions.add(decision)

        reason = case.get("decision_reason")
        if not isinstance(reason, str) or not reason.strip():
            handoff_decision_errors.append(f"handoff {label} decision_reason must be non-empty")
        if isinstance(decision, str) and decision in REQUIRED_DECISION_REASONS:
            expected_reason = REQUIRED_DECISION_REASONS[decision]
            if reason != expected_reason:
                handoff_decision_errors.append(f"handoff {label} decision_reason mismatch for {decision}")

        for field in TRUE_CASE_FIELDS:
            if case.get(field) is not True:
                handoff_safety_errors.append(f"handoff {label} {field} must be true")
        for field in FALSE_CASE_FIELDS:
            if case.get(field) is not False:
                handoff_safety_errors.append(f"handoff {label} {field} must be false")

    for decision in sorted(REQUIRED_DECISION_COVERAGE - covered_decisions):
        handoff_decision_coverage_errors.append(f"missing critical handoff decision coverage: {decision}")

    reference_errors.extend(_validate_references())

    return {
        "config_errors": config_errors,
        "invalid_handoff_values": invalid_handoff_values,
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_required_roles": missing_required_roles,
        "missing_required_fields": missing_required_fields,
        "malformed_handoff_cases": malformed_handoff_cases,
        "handoff_identity_errors": handoff_identity_errors,
        "handoff_decision_errors": handoff_decision_errors,
        "handoff_decision_coverage_errors": handoff_decision_coverage_errors,
        "handoff_safety_errors": handoff_safety_errors,
        "forbidden_handoff_fields": forbidden_handoff_fields,
        "reference_errors": reference_errors,
    }


def _count_cases(config: dict[str, Any], decision: str) -> int:
    cases = config.get("handoff_cases")
    if not isinstance(cases, list):
        return 0
    return sum(1 for case in cases if isinstance(case, dict) and case.get("decision") == decision)


def _issues(audit: dict[str, list[str]]) -> list[str]:
    issues: list[str] = []
    for values in audit.values():
        issues.extend(values)
    return issues


def _print_list(title: str, values: list[str]) -> None:
    print(f"\n## {title}\n")
    if values:
        for value in values:
            print(f"- {value}")
    else:
        print("- none")


def render_markdown(config: dict[str, Any], audit: dict[str, list[str]]) -> None:
    issues = _issues(audit)
    cases = config.get("handoff_cases")
    case_count = len(cases) if isinstance(cases, list) else 0

    print("# Metadata review handoff audit\n")
    print("## Summary\n")
    print(f"- handoff_id: {config.get('handoff_id')}")
    print(f"- status: {config.get('status')}")
    print(f"- handoff_ready_for_review: {str(not issues).lower()}")
    print(f"- handoff_cases_count: {case_count}")
    print(f"- ready_for_human_review_count: {_count_cases(config, 'ready_for_human_metadata_review')}")
    print(f"- hardening_required_count: {_count_cases(config, 'require_more_metadata_hardening')}")
    print(f"- blocked_real_action_count: {_count_cases(config, 'block_any_real_action')}")
    print(f"- deferred_followup_count: {_count_cases(config, 'defer_until_named_followup_lot')}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_required_roles_count: {len(audit['missing_required_roles'])}")
    print(f"- missing_required_fields_count: {len(audit['missing_required_fields'])}")
    print(f"- malformed_handoff_cases_count: {len(audit['malformed_handoff_cases'])}")
    print(f"- handoff_identity_errors_count: {len(audit['handoff_identity_errors'])}")
    print(f"- handoff_decision_errors_count: {len(audit['handoff_decision_errors'])}")
    print(f"- handoff_decision_coverage_errors_count: {len(audit['handoff_decision_coverage_errors'])}")
    print(f"- handoff_safety_errors_count: {len(audit['handoff_safety_errors'])}")
    print(f"- forbidden_handoff_fields_count: {len(audit['forbidden_handoff_fields'])}")
    print(f"- reference_errors_count: {len(audit['reference_errors'])}")
    print(f"- real_documents_allowed: {str(config.get('real_documents_allowed')).lower()}")
    print(f"- ingestion_allowed: {str(config.get('ingestion_allowed')).lower()}")
    print(f"- embeddings_allowed: {str(config.get('embeddings_allowed')).lower()}")
    print(f"- qdrant_allowed: {str(config.get('qdrant_allowed')).lower()}")
    print(f"- network_allowed: {str(config.get('network_allowed')).lower()}")
    print(f"- data_staging_allowed: {str(config.get('data_staging_allowed')).lower()}")
    print("- destructive_action_available: false")

    print("\n## Handoff cases\n")
    if isinstance(cases, list) and cases:
        for case in cases:
            if isinstance(case, dict):
                print(f"- {case.get('handoff_case_id')}: {case.get('decision')}")
            else:
                print(f"- malformed: {case}")
    else:
        print("- none")

    print("\n## Required review roles\n")
    for role in _string_list(config.get("required_review_roles")):
        print(f"- {role}")

    print("\n## Allowed handoff decisions\n")
    for decision in _string_list(config.get("allowed_handoff_decisions")):
        print(f"- {decision}")

    print("\n## Required handoff fields\n")
    for field in _string_list(config.get("required_handoff_fields")):
        print(f"- {field}")

    _print_list("Reference errors", audit["reference_errors"])
    _print_list("Handoff decision coverage errors", audit["handoff_decision_coverage_errors"])
    _print_list("Blocking issues", issues)

    print("\n## Explicit non-actions\n")
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
    render_markdown(config, audit)
    return 1 if _issues(audit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
