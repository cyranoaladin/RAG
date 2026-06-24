from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/controlled_readiness.yml"

REQUIRED_READINESS_VALUES = {
    "readiness_id": "controlled_readiness_metadata_gate_v1",
    "status": "metadata_only_controlled_readiness",
    "pilot_scope_ref": "math_terminale_specialite_metadata_only_v1",
    "retrieval_eval_ref": "math_terminale_specialite_metadata_retrieval_eval_v1",
    "pedago_interface_ref": "pedago_interface_metadata_contract_v1",
    "source_admission_policy_ref": "source_admission_metadata_policy_v1",
    "human_source_review_ref": "human_source_review_metadata_policy_v1",
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
REQUIRED_GATES = [
    "pilot_scope_gate",
    "retrieval_metadata_eval_gate",
    "pedago_interface_contract_gate",
    "source_admission_policy_gate",
    "human_source_review_gate",
    "make_target_safety_gate",
    "metadata_preflight_gate",
    "project_doctor_gate",
]
ALLOWED_TRANSITION_DECISIONS = {
    "continue_metadata_only",
    "require_human_signoff",
    "defer_real_corpus_lot",
    "do_not_proceed",
}
ALLOWED_GATE_STATUSES = {
    "passed",
    "blocked",
    "deferred",
}
REQUIRED_TRANSITION_FIELDS = [
    "transition_id",
    "gate_id",
    "gate_status",
    "decision",
    "decision_reason",
    "human_signoff_required",
    "real_corpus_allowed",
    "real_file_allowed",
    "external_url_allowed",
    "rollback_required",
    "next_lot_required",
]
REQUIRED_GATE_EVIDENCE_FIELDS = [
    "gate_id",
    "evidence_kind",
    "evidence_ref",
    "safe_target",
    "expected_status",
    "destructive_action_allowed",
    "real_document_allowed",
    "network_allowed",
]
ALLOWED_EVIDENCE_KINDS = {
    "codex_report_and_make_target",
    "make_target",
}
REQUIRED_DECISION_REASONS = {
    "defer_real_corpus_lot": "real_corpus_requires_separate_lot",
    "require_human_signoff": "human_signoff_missing",
}
GATE_STATUS_ALLOWED_DECISIONS = {
    "passed": {"continue_metadata_only", "require_human_signoff"},
    "blocked": {"require_human_signoff", "do_not_proceed"},
    "deferred": {"defer_real_corpus_lot", "do_not_proceed"},
}
FORBIDDEN_TRANSITION_FIELDS = {
    "file_path",
    "path",
    "url",
    "uri",
    "checksum",
    "sha256",
    "content",
}
REAL_DOCUMENT_SUFFIXES = (".pdf", ".docx", ".pptx", ".xlsx")
SENSITIVE_EVIDENCE_REF_MARKERS = {
    "file_path",
    "source_uri",
    "data/staging",
}
SENSITIVE_TARGET_TERMS = {
    "ingest",
    "ingestion",
    "api",
    "upload",
    "download",
    "sync",
    "deploy",
    "qdrant",
    "embed",
    "embedding",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a metadata-only controlled readiness gate.")
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


def _transition_label(index: int, transition_check: object) -> str:
    if isinstance(transition_check, dict) and isinstance(transition_check.get("transition_id"), str):
        transition_id = str(transition_check["transition_id"]).strip()
        if transition_id:
            return transition_id
    return f"index {index}"


def _gate_evidence_label(index: int, evidence: object) -> str:
    if isinstance(evidence, dict) and isinstance(evidence.get("gate_id"), str):
        gate_id = str(evidence["gate_id"]).strip()
        if gate_id:
            return gate_id
    return f"index {index}"


def _contains_url(value: str) -> bool:
    lowered = value.lower()
    return "://" in lowered or lowered.startswith("www.")


def _contains_real_document_suffix(value: str) -> bool:
    lowered = value.lower()
    return any(lowered.endswith(suffix) or f"{suffix}?" in lowered for suffix in REAL_DOCUMENT_SUFFIXES)


def audit_config(config: dict[str, Any]) -> dict[str, list[str]]:
    config_errors: list[str] = []
    invalid_readiness_values: list[str] = []
    dangerous_flags_enabled: list[str] = []
    missing_required_gates: list[str] = []
    missing_required_fields: list[str] = []
    malformed_transition_checks: list[str] = []
    transition_identity_errors: list[str] = []
    transition_decision_errors: list[str] = []
    transition_safety_errors: list[str] = []
    forbidden_transition_fields: list[str] = []
    gate_evidence_errors: list[str] = []
    gate_coverage_errors: list[str] = []
    sensitive_target_errors: list[str] = []
    transition_status_decision_errors: list[str] = []

    if isinstance(config.get("_config_error"), str):
        config_errors.append(str(config["_config_error"]))

    for field, expected_value in REQUIRED_READINESS_VALUES.items():
        if config.get(field) != expected_value:
            invalid_readiness_values.append(f"{field} must be {expected_value}")

    for flag in REQUIRED_FALSE_FLAGS:
        if config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    configured_gates = set(_string_list(config.get("required_gates")))
    configured_decisions = set(_string_list(config.get("allowed_transition_decisions")))
    configured_fields = set(_string_list(config.get("required_transition_fields")))
    configured_gate_evidence_fields = set(_string_list(config.get("required_gate_evidence_fields")))

    for gate in REQUIRED_GATES:
        if gate not in configured_gates:
            missing_required_gates.append(f"missing required_gates: {gate}")
    for decision in ALLOWED_TRANSITION_DECISIONS:
        if decision not in configured_decisions:
            missing_required_fields.append(f"missing allowed_transition_decisions: {decision}")
    for decision in sorted(configured_decisions.difference(ALLOWED_TRANSITION_DECISIONS)):
        transition_decision_errors.append(f"allowed_transition_decisions contains unknown decision: {decision}")
    for field in REQUIRED_TRANSITION_FIELDS:
        if field not in configured_fields:
            missing_required_fields.append(f"missing required_transition_fields: {field}")
    for field in REQUIRED_GATE_EVIDENCE_FIELDS:
        if field not in configured_gate_evidence_fields:
            gate_evidence_errors.append(f"missing required_gate_evidence_fields: {field}")

    gate_evidence = config.get("gate_evidence")
    if not isinstance(gate_evidence, list) or not gate_evidence:
        gate_evidence_errors.append("gate_evidence must be a non-empty list")
        gate_evidence = []

    seen_gate_ids: set[str] = set()
    for index, evidence in enumerate(gate_evidence):
        if not isinstance(evidence, dict):
            gate_evidence_errors.append(f"gate_evidence at index {index} must be a mapping")
            continue

        label = _gate_evidence_label(index, evidence)
        gate_id = evidence.get("gate_id")
        if not isinstance(gate_id, str) or gate_id not in configured_gates:
            gate_coverage_errors.append(f"gate_evidence {label} gate_id must be declared in required_gates")
        elif gate_id in seen_gate_ids:
            gate_coverage_errors.append(f"duplicate gate_evidence gate_id: {gate_id}")
        else:
            seen_gate_ids.add(gate_id)

        for field in REQUIRED_GATE_EVIDENCE_FIELDS:
            if field not in evidence:
                gate_evidence_errors.append(f"gate_evidence {label} missing required field {field}")

        evidence_kind = evidence.get("evidence_kind")
        if evidence_kind not in ALLOWED_EVIDENCE_KINDS:
            gate_evidence_errors.append(f"gate_evidence {label} evidence_kind must be allowed")

        evidence_ref = evidence.get("evidence_ref")
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            gate_evidence_errors.append(f"gate_evidence {label} evidence_ref must be a non-empty string")
        else:
            if _contains_url(evidence_ref):
                sensitive_target_errors.append(f"gate_evidence {label} evidence_ref must not contain a URL")
            if _contains_real_document_suffix(evidence_ref):
                sensitive_target_errors.append(f"gate_evidence {label} evidence_ref must not point to a real document")
            for marker in sorted(SENSITIVE_EVIDENCE_REF_MARKERS):
                if marker in evidence_ref:
                    sensitive_target_errors.append(f"gate_evidence {label} evidence_ref must not contain {marker}")

        safe_target = evidence.get("safe_target")
        if not isinstance(safe_target, str) or not safe_target.strip():
            gate_evidence_errors.append(f"gate_evidence {label} safe_target must be a non-empty string")
        else:
            for term in sorted(SENSITIVE_TARGET_TERMS):
                if term in safe_target:
                    sensitive_target_errors.append(f"gate_evidence {label} safe_target contains sensitive term: {term}")
                    break

        if evidence.get("expected_status") != "passed":
            gate_evidence_errors.append(f"gate_evidence {label} expected_status must be passed")
        if evidence.get("destructive_action_allowed") is not False:
            gate_evidence_errors.append(f"gate_evidence {label} destructive_action_allowed must be false")
        if evidence.get("real_document_allowed") is not False:
            gate_evidence_errors.append(f"gate_evidence {label} real_document_allowed must be false")
        if evidence.get("network_allowed") is not False:
            gate_evidence_errors.append(f"gate_evidence {label} network_allowed must be false")

    for gate in REQUIRED_GATES:
        if gate not in seen_gate_ids:
            gate_coverage_errors.append(f"missing gate_evidence for required gate: {gate}")

    transition_checks = config.get("transition_checks")
    if not isinstance(transition_checks, list):
        malformed_transition_checks.append("transition_checks must be a list")
        transition_checks = []

    seen_transition_ids: set[str] = set()
    for index, transition_check in enumerate(transition_checks):
        if not isinstance(transition_check, dict):
            malformed_transition_checks.append(f"transition check at index {index} must be a mapping")
            continue

        label = _transition_label(index, transition_check)
        transition_id = transition_check.get("transition_id")
        if not isinstance(transition_id, str) or not transition_id.strip():
            transition_identity_errors.append(f"transition index {index} transition_id must be a non-empty string")
        elif transition_id in seen_transition_ids:
            transition_identity_errors.append(f"duplicate transition_id: {transition_id}")
        else:
            seen_transition_ids.add(transition_id)

        for field in REQUIRED_TRANSITION_FIELDS:
            if field not in transition_check:
                missing_required_fields.append(f"transition {label} missing required field {field}")

        gate_id = transition_check.get("gate_id")
        if not isinstance(gate_id, str) or gate_id not in configured_gates:
            transition_decision_errors.append(f"transition {label} gate_id must be declared in required_gates")

        gate_status = transition_check.get("gate_status")
        if not isinstance(gate_status, str) or gate_status not in ALLOWED_GATE_STATUSES:
            transition_decision_errors.append(f"transition {label} gate_status must be allowed")

        decision = transition_check.get("decision")
        if not isinstance(decision, str) or decision not in configured_decisions.intersection(ALLOWED_TRANSITION_DECISIONS):
            transition_decision_errors.append(f"transition {label} decision must be allowed")

        decision_reason = transition_check.get("decision_reason")
        if not isinstance(decision_reason, str) or not decision_reason.strip():
            transition_decision_errors.append(f"transition {label} decision_reason must be a non-empty string")

        if transition_check.get("human_signoff_required") is not True:
            transition_safety_errors.append(f"transition {label} human_signoff_required must be true")
        if transition_check.get("real_corpus_allowed") is not False:
            transition_safety_errors.append(f"transition {label} real_corpus_allowed must be false")
        if transition_check.get("real_file_allowed") is not False:
            transition_safety_errors.append(f"transition {label} real_file_allowed must be false")
        if transition_check.get("external_url_allowed") is not False:
            transition_safety_errors.append(f"transition {label} external_url_allowed must be false")
        if transition_check.get("rollback_required") is not True:
            transition_safety_errors.append(f"transition {label} rollback_required must be true")
        if transition_check.get("next_lot_required") is not True:
            transition_safety_errors.append(f"transition {label} next_lot_required must be true")

        if decision in REQUIRED_DECISION_REASONS:
            expected_reason = REQUIRED_DECISION_REASONS[decision]
            if decision_reason != expected_reason:
                transition_decision_errors.append(f"{decision} requires decision_reason {expected_reason}")

        if isinstance(gate_status, str) and isinstance(decision, str):
            allowed_decisions = GATE_STATUS_ALLOWED_DECISIONS.get(gate_status, set())
            if decision not in allowed_decisions:
                transition_status_decision_errors.append(
                    f"transition {label} gate_status {gate_status} cannot use decision {decision}"
                )

        for field in sorted(FORBIDDEN_TRANSITION_FIELDS):
            if field in transition_check:
                forbidden_transition_fields.append(f"transition {label} forbidden field: {field}")

    issues = [
        *config_errors,
        *invalid_readiness_values,
        *dangerous_flags_enabled,
        *missing_required_gates,
        *missing_required_fields,
        *malformed_transition_checks,
        *transition_identity_errors,
        *transition_decision_errors,
        *transition_safety_errors,
        *forbidden_transition_fields,
        *gate_evidence_errors,
        *gate_coverage_errors,
        *sensitive_target_errors,
        *transition_status_decision_errors,
    ]
    return {
        "config_errors": config_errors,
        "invalid_readiness_values": invalid_readiness_values,
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_required_gates": missing_required_gates,
        "missing_required_fields": missing_required_fields,
        "malformed_transition_checks": malformed_transition_checks,
        "transition_identity_errors": transition_identity_errors,
        "transition_decision_errors": transition_decision_errors,
        "transition_safety_errors": transition_safety_errors,
        "forbidden_transition_fields": forbidden_transition_fields,
        "gate_evidence_errors": gate_evidence_errors,
        "gate_coverage_errors": gate_coverage_errors,
        "sensitive_target_errors": sensitive_target_errors,
        "transition_status_decision_errors": transition_status_decision_errors,
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
    transition_checks = config.get("transition_checks")
    check_list = transition_checks if isinstance(transition_checks, list) else []
    gate_evidence = config.get("gate_evidence")
    evidence_list = gate_evidence if isinstance(gate_evidence, list) else []
    passed_count = 0
    deferred_count = 0
    blocked_count = 0
    for transition_check in check_list:
        if not isinstance(transition_check, dict):
            continue
        gate_status = transition_check.get("gate_status")
        if gate_status == "passed":
            passed_count += 1
        if gate_status == "deferred":
            deferred_count += 1
        if gate_status == "blocked":
            blocked_count += 1

    print("# Controlled readiness audit")
    print()
    print("## Summary")
    print()
    print(f"- readiness_id: {config.get('readiness_id', 'missing')}")
    print(f"- status: {config.get('status', 'missing')}")
    print(f"- readiness_ready_for_review: {str(not issues).lower()}")
    print(f"- transition_checks_count: {len(check_list)}")
    print(f"- passed_gates_count: {passed_count}")
    print(f"- deferred_gates_count: {deferred_count}")
    print(f"- blocked_gates_count: {blocked_count}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_required_gates_count: {len(audit['missing_required_gates'])}")
    print(f"- missing_required_fields_count: {len(audit['missing_required_fields'])}")
    print(f"- malformed_transition_checks_count: {len(audit['malformed_transition_checks'])}")
    print(f"- transition_identity_errors_count: {len(audit['transition_identity_errors'])}")
    print(f"- transition_decision_errors_count: {len(audit['transition_decision_errors'])}")
    print(f"- transition_safety_errors_count: {len(audit['transition_safety_errors'])}")
    print(f"- forbidden_transition_fields_count: {len(audit['forbidden_transition_fields'])}")
    print(f"- gate_evidence_errors_count: {len(audit['gate_evidence_errors'])}")
    print(f"- gate_coverage_errors_count: {len(audit['gate_coverage_errors'])}")
    print(f"- sensitive_target_errors_count: {len(audit['sensitive_target_errors'])}")
    print(f"- transition_status_decision_errors_count: {len(audit['transition_status_decision_errors'])}")
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
    print("## Transition checks")
    print()
    for transition_check in check_list:
        if isinstance(transition_check, dict):
            print(f"- {transition_check.get('transition_id', 'missing')}: {transition_check.get('decision', 'missing')}")
    if not check_list:
        print("- none")
    print()
    print("## Gate evidence")
    print()
    for evidence in evidence_list:
        if isinstance(evidence, dict):
            print(f"- {evidence.get('gate_id', 'missing')}: {evidence.get('safe_target', 'missing')}")
    if not evidence_list:
        print("- none")
    print()
    print("## Gate evidence errors")
    print()
    _print_list(audit["gate_evidence_errors"])
    print()
    print("## Gate coverage errors")
    print()
    _print_list(audit["gate_coverage_errors"])
    print()
    print("## Sensitive target errors")
    print()
    _print_list(audit["sensitive_target_errors"])
    print()
    print("## Transition status decision errors")
    print()
    _print_list(audit["transition_status_decision_errors"])
    print()
    print("## Required gates")
    print()
    _print_list(_string_list(config.get("required_gates")))
    print()
    print("## Allowed transition decisions")
    print()
    _print_list(_string_list(config.get("allowed_transition_decisions")))
    print()
    print("## Required transition fields")
    print()
    _print_list(_string_list(config.get("required_transition_fields")))
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
