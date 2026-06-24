from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/retrieval_metadata_eval.yml"

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
    "answer_generation_allowed",
    "data_staging_allowed",
]
REQUIRED_FILTER_FIELDS = [
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
    "notions",
    "competences",
]
REQUIRED_STUDENT_PROFILE_VALUES = {
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "mathematiques",
    "statut_enseignement": "specialite",
    "candidat": "scolarise",
}
REQUIRED_CASE_FIELDS = [
    "case_id",
    "query",
    "student_profile",
    "expected_filters",
    "expected_citation_policy",
    "expected_behavior",
    "pedagogical_relevance_criteria",
]
ALLOWED_EXPECTED_BEHAVIORS = {
    "metadata_filter_only",
    "refuse_no_real_document_access",
    "refuse_missing_sources",
    "refuse_rights_unknown",
}
REFUSAL_BEHAVIORS = {
    "refuse_no_real_document_access",
    "refuse_missing_sources",
    "refuse_rights_unknown",
}
REQUIRED_REFUSAL_CRITERIA = {
    "refuse_no_real_document_access": "must_refuse_real_document_access",
    "refuse_rights_unknown": "must_refuse_unknown_rights",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a metadata-only retrieval evaluation config.")
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


def _case_label(index: int, case: object) -> str:
    if isinstance(case, dict) and isinstance(case.get("case_id"), str):
        return str(case["case_id"])
    return f"index {index}"


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _validate_student_profile(label: str, case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    student_profile = case.get("student_profile")
    if not isinstance(student_profile, dict):
        return [f"student_profile for {label} must be a mapping"]
    for key, expected in REQUIRED_STUDENT_PROFILE_VALUES.items():
        if key not in student_profile:
            errors.append(f"student_profile for {label} missing {key}")
        elif student_profile.get(key) != expected:
            errors.append(f"student_profile for {label} {key} must be {expected}")
    return errors


def _validate_metadata_filters(label: str, filters: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(filters, dict) or not filters:
        return [f"metadata_filter_only case {label} must define expected_filters"]

    for field in REQUIRED_FILTER_FIELDS:
        if field not in filters:
            errors.append(f"missing expected_filters for {label}: {field}")

    for key, expected in REQUIRED_STUDENT_PROFILE_VALUES.items():
        if key in filters and filters.get(key) != expected:
            errors.append(f"expected_filters for {label} {key} must be {expected}")
    if "rights" in filters and filters.get("rights") != "allowed_for_retrieval":
        errors.append(f"expected_filters for {label} rights must be allowed_for_retrieval")
    if "visibility" in filters and filters.get("visibility") != "student_visible":
        errors.append(f"expected_filters for {label} visibility must be student_visible")
    for key in ["notions", "competences"]:
        if key in filters and not _string_list(filters.get(key)):
            errors.append(f"expected_filters for {label} {key} must be a non-empty list")
    return errors


def _validate_case_citation_policy(label: str, citation_policy: object) -> list[str]:
    if not isinstance(citation_policy, dict):
        return [f"expected_citation_policy for {label} must be a mapping"]
    errors: list[str] = []
    if citation_policy.get("citations_required") is not True:
        errors.append(f"case {label} citations_required must be true")
    if citation_policy.get("answer_without_source_allowed") is not False:
        errors.append(f"case {label} answer_without_source_allowed must be false")
    return errors


def _validate_pedagogical_criteria(label: str, behavior: object, criteria: object) -> list[str]:
    criteria_values = _string_list(criteria)
    if not criteria_values:
        return [f"pedagogical_relevance_criteria for {label} must be a non-empty list"]

    errors: list[str] = []
    if behavior == "metadata_filter_only" and "citation_required" not in criteria_values:
        errors.append(f"metadata_filter_only case {label} must include citation_required criterion")
    if isinstance(behavior, str) and behavior in REFUSAL_BEHAVIORS:
        has_refusal_criterion = any(value.startswith("must_refuse_") for value in criteria_values)
        if "no_answer_generation" not in criteria_values and not has_refusal_criterion:
            errors.append(f"refusal case {label} must include no_answer_generation or must_refuse_* criterion")
        required_criterion = REQUIRED_REFUSAL_CRITERIA.get(behavior)
        if required_criterion and required_criterion not in criteria_values:
            errors.append(f"{behavior} case {label} must include {required_criterion}")
    return errors


def _validate_refusal_case(label: str, case: dict[str, Any], behavior: object) -> list[str]:
    errors: list[str] = []
    if not (isinstance(behavior, str) and behavior.startswith("refuse_")):
        errors.append(f"refusal case {label} behavior must start with refuse_")
    expected_filters = case.get("expected_filters")
    if expected_filters != {}:
        errors.append(f"refusal case {label} expected_filters must be empty")
    if case.get("answer_generation_expected") is True:
        errors.append(f"refusal case {label} must not request answer generation")
    return errors


def audit_config(config: dict[str, Any]) -> dict[str, list[str]]:
    dangerous_flags_enabled: list[str] = []
    malformed_cases: list[str] = []
    invalid_expected_behaviors: list[str] = []
    citation_policy_errors: list[str] = []
    student_profile_errors: list[str] = []
    expected_filter_errors: list[str] = []
    case_citation_policy_errors: list[str] = []
    pedagogical_criteria_errors: list[str] = []
    refusal_case_errors: list[str] = []
    missing_required_filter_fields: list[str] = []
    config_errors: list[str] = []

    if isinstance(config.get("_config_error"), str):
        config_errors.append(str(config["_config_error"]))
    if config.get("status") != "metadata_only_eval":
        config_errors.append("status must be metadata_only_eval")

    for flag in REQUIRED_FALSE_FLAGS:
        if config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    filter_fields = set(_list_values(config, "required_filter_fields"))
    missing_required_filter_fields = [field for field in REQUIRED_FILTER_FIELDS if field not in filter_fields]

    citation_policy = config.get("citation_policy")
    if not isinstance(citation_policy, dict):
        citation_policy_errors.append("citation_policy must be a mapping")
        citation_policy = {}
    if citation_policy.get("citations_required") is not True:
        citation_policy_errors.append("citations_required must be true")
    if citation_policy.get("answer_without_source_allowed") is not False:
        citation_policy_errors.append("answer_without_source_allowed must be false")
    if citation_policy.get("source_trace_required") is not True:
        citation_policy_errors.append("source_trace_required must be true")

    cases = config.get("cases")
    if not isinstance(cases, list):
        malformed_cases.append("cases must be a list")
        cases = []

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            malformed_cases.append(f"case at index {index} must be a mapping")
            continue
        label = _case_label(index, case)
        for field in REQUIRED_CASE_FIELDS:
            if field not in case:
                if field == "case_id":
                    malformed_cases.append(f"case at index {index} missing required field case_id")
                else:
                    malformed_cases.append(f"case {label} missing required field {field}")
        behavior = case.get("expected_behavior")
        if isinstance(behavior, str) and behavior not in ALLOWED_EXPECTED_BEHAVIORS:
            invalid_expected_behaviors.append(f"invalid expected_behavior for {label}: {behavior}")
        student_profile_errors.extend(_validate_student_profile(label, case))
        if behavior == "metadata_filter_only":
            expected_filter_errors.extend(_validate_metadata_filters(label, case.get("expected_filters")))
        if isinstance(behavior, str) and behavior in REFUSAL_BEHAVIORS:
            refusal_case_errors.extend(_validate_refusal_case(label, case, behavior))
        if case.get("answer_generation_expected") is True:
            malformed_cases.append(f"case {label} must not request answer generation")
        case_citation_policy_errors.extend(_validate_case_citation_policy(label, case.get("expected_citation_policy")))
        pedagogical_criteria_errors.extend(
            _validate_pedagogical_criteria(label, behavior, case.get("pedagogical_relevance_criteria"))
        )

    issues = [
        *config_errors,
        *dangerous_flags_enabled,
        *missing_required_filter_fields,
        *malformed_cases,
        *invalid_expected_behaviors,
        *citation_policy_errors,
        *student_profile_errors,
        *expected_filter_errors,
        *case_citation_policy_errors,
        *pedagogical_criteria_errors,
        *refusal_case_errors,
    ]
    return {
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_required_filter_fields": missing_required_filter_fields,
        "malformed_cases": malformed_cases,
        "invalid_expected_behaviors": invalid_expected_behaviors,
        "citation_policy_errors": citation_policy_errors,
        "student_profile_errors": student_profile_errors,
        "expected_filter_errors": expected_filter_errors,
        "case_citation_policy_errors": case_citation_policy_errors,
        "pedagogical_criteria_errors": pedagogical_criteria_errors,
        "refusal_case_errors": refusal_case_errors,
        "config_errors": config_errors,
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
    cases = config.get("cases")
    case_list = cases if isinstance(cases, list) else []
    metadata_cases = [
        case for case in case_list if isinstance(case, dict) and case.get("expected_behavior") == "metadata_filter_only"
    ]
    refusal_cases = [
        case for case in case_list if isinstance(case, dict) and str(case.get("expected_behavior", "")).startswith("refuse_")
    ]

    print("# Retrieval metadata eval audit")
    print()
    print("## Summary")
    print()
    print(f"- eval_id: {config.get('eval_id', 'missing')}")
    print(f"- status: {config.get('status', 'missing')}")
    print(f"- eval_ready_for_review: {str(not issues).lower()}")
    print(f"- cases_count: {len(case_list)}")
    print(f"- metadata_filter_cases_count: {len(metadata_cases)}")
    print(f"- refusal_cases_count: {len(refusal_cases)}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_required_filter_fields_count: {len(audit['missing_required_filter_fields'])}")
    print(f"- malformed_cases_count: {len(audit['malformed_cases'])}")
    print(f"- invalid_expected_behaviors_count: {len(audit['invalid_expected_behaviors'])}")
    print(f"- citation_policy_errors_count: {len(audit['citation_policy_errors'])}")
    print(f"- student_profile_errors_count: {len(audit['student_profile_errors'])}")
    print(f"- expected_filter_errors_count: {len(audit['expected_filter_errors'])}")
    print(f"- case_citation_policy_errors_count: {len(audit['case_citation_policy_errors'])}")
    print(f"- pedagogical_criteria_errors_count: {len(audit['pedagogical_criteria_errors'])}")
    print(f"- refusal_case_errors_count: {len(audit['refusal_case_errors'])}")
    for flag in ["answer_generation_allowed", "embeddings_allowed", "qdrant_allowed", "real_documents_allowed"]:
        print(f"- {flag}: {str(config.get(flag, 'missing')).lower()}")
    print("- destructive_action_available: false")
    print()
    print("## Cases")
    print()
    for case in case_list:
        if isinstance(case, dict):
            print(f"- {case.get('case_id', 'missing')}: {case.get('expected_behavior', 'missing')}")
    if not case_list:
        print("- none")
    print()
    print("## Required filter fields")
    print()
    _print_list(_list_values(config, "required_filter_fields"))
    print()
    print("## Citation policy")
    print()
    citation_policy = config.get("citation_policy")
    if isinstance(citation_policy, dict):
        for key in ["citations_required", "answer_without_source_allowed", "source_trace_required"]:
            print(f"- {key}: {str(citation_policy.get(key, 'missing')).lower()}")
    else:
        print("- missing")
    print()
    print("## Student profile errors")
    print()
    _print_list(audit["student_profile_errors"])
    print()
    print("## Expected filter errors")
    print()
    _print_list(audit["expected_filter_errors"])
    print()
    print("## Case citation policy errors")
    print()
    _print_list(audit["case_citation_policy_errors"])
    print()
    print("## Pedagogical criteria errors")
    print()
    _print_list(audit["pedagogical_criteria_errors"])
    print()
    print("## Refusal case errors")
    print()
    _print_list(audit["refusal_case_errors"])
    print()
    print("## Blocking issues")
    print()
    _print_list(issues)
    print()
    print("## Explicit non-actions")
    print()
    print("- no real document read")
    print("- no PDF copied")
    print("- no ingestion launched")
    print("- no parsing launched")
    print("- no chunking launched")
    print("- no embedding created")
    print("- no Qdrant touched")
    print("- no answer generated")
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
