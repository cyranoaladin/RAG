from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/pedago_interface_contract.yml"

REQUIRED_CONTRACT_VALUES = {
    "contract_id": "pedago_interface_metadata_contract_v1",
    "status": "metadata_only_interface_contract",
    "pilot_scope_ref": "math_terminale_specialite_metadata_only_v1",
    "retrieval_eval_ref": "math_terminale_specialite_metadata_retrieval_eval_v1",
}
REQUIRED_FALSE_FLAGS = [
    "runtime_api_allowed",
    "server_start_allowed",
    "ui_runtime_allowed",
    "real_documents_allowed",
    "pdf_allowed",
    "ingestion_allowed",
    "parsing_allowed",
    "chunking_allowed",
    "embeddings_allowed",
    "qdrant_allowed",
    # network_allowed: lifted under ADR-0004 (scoped fetch, lot 4.2)
    "answer_generation_allowed",
    "data_staging_allowed",
]
REQUIRED_PERSONAS = [
    "eleve",
    "enseignant",
    "administrateur_pedagogique",
]
REQUIRED_INTERACTION_FIELDS = [
    "interaction_id",
    "persona",
    "intent",
    "input_kind",
    "expected_behavior",
    "citation_policy",
    "refusal_policy",
    "metadata_filters_required",
    "human_review_required",
]
ALLOWED_EXPECTED_BEHAVIORS = {
    "metadata_filter_preview",
    "human_review_required",
    "controlled_refusal",
    "no_source_refusal",
    "rights_refusal",
}
REFUSAL_BEHAVIORS = {
    "controlled_refusal",
    "no_source_refusal",
    "rights_refusal",
}
ALLOWED_INPUT_KINDS = {
    "synthetic_query",
    "synthetic_review_case",
    "synthetic_refusal_case",
}
REQUIRED_METADATA_FILTERS_FOR_NON_REFUSAL = {
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "rights",
    "visibility",
}
REQUIRED_GLOBAL_REFUSAL_RULES = [
    "refusal_required_when_no_source",
    "refusal_required_for_real_document_request",
    "refusal_required_for_unknown_rights",
    "no_answer_generation_on_refusal",
]
EXPLICIT_REFUSAL_RULES = [
    "refusal_required_when_no_source",
    "refusal_required_for_real_document_request",
    "refusal_required_for_unknown_rights",
]
FORBIDDEN_RUNTIME_FIELDS = {
    "endpoint",
    "route",
    "url",
    "http_method",
    "server",
    "component_runtime",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a metadata-only pedagogical interface contract.")
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


def _interaction_label(index: int, interaction: object) -> str:
    if isinstance(interaction, dict) and isinstance(interaction.get("interaction_id"), str):
        interaction_id = str(interaction["interaction_id"]).strip()
        if interaction_id:
            return interaction_id
    return f"index {index}"


def _validate_citation_policy(label: str, policy: object, *, require_source_trace: bool) -> list[str]:
    if not isinstance(policy, dict):
        return [f"citation_policy for {label} must be a mapping"]
    errors: list[str] = []
    if policy.get("citations_required") is not True:
        errors.append(f"{label} citations_required must be true")
    if policy.get("answer_without_source_allowed") is not False:
        errors.append(f"{label} answer_without_source_allowed must be false")
    if require_source_trace and policy.get("source_trace_required") is not True:
        errors.append(f"{label} source_trace_required must be true")
    if not require_source_trace and policy.get("source_trace_required") is False:
        errors.append(f"{label} source_trace_required must not be false")
    return errors


def _validate_refusal_policy(label: str, policy: object, *, behavior: object | None = None) -> list[str]:
    if not isinstance(policy, dict):
        return [f"refusal_policy for {label} must be a mapping"]
    errors: list[str] = []
    if behavior is None:
        for rule in REQUIRED_GLOBAL_REFUSAL_RULES:
            if policy.get(rule) is not True:
                errors.append(f"{label} {rule} must be true")
        return errors

    if policy.get("no_answer_generation_on_refusal") is not True:
        errors.append(f"{label} no_answer_generation_on_refusal must be true")
    if behavior == "controlled_refusal" and not any(policy.get(rule) is True for rule in EXPLICIT_REFUSAL_RULES):
        errors.append(f"controlled_refusal {label} must include an explicit refusal rule")
    if behavior == "no_source_refusal" and policy.get("refusal_required_when_no_source") is not True:
        errors.append(f"{label} refusal_required_when_no_source must be true")
    if behavior == "rights_refusal" and policy.get("refusal_required_for_unknown_rights") is not True:
        errors.append(f"{label} refusal_required_for_unknown_rights must be true")
    return errors


def audit_config(config: dict[str, Any]) -> dict[str, list[str]]:
    config_errors: list[str] = []
    invalid_contract_values: list[str] = []
    dangerous_flags_enabled: list[str] = []
    missing_required_personas: list[str] = []
    malformed_interactions: list[str] = []
    invalid_personas: list[str] = []
    invalid_expected_behaviors: list[str] = []
    citation_policy_errors: list[str] = []
    refusal_policy_errors: list[str] = []
    interaction_contract_errors: list[str] = []
    forbidden_runtime_fields: list[str] = []

    if isinstance(config.get("_config_error"), str):
        config_errors.append(str(config["_config_error"]))
    for field, expected_value in REQUIRED_CONTRACT_VALUES.items():
        if config.get(field) != expected_value:
            invalid_contract_values.append(f"{field} must be {expected_value}")

    for flag in REQUIRED_FALSE_FLAGS:
        if config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    allowed_personas = set(_string_list(config.get("allowed_personas")))
    for persona in REQUIRED_PERSONAS:
        if persona not in allowed_personas:
            missing_required_personas.append(f"missing required persona: {persona}")

    citation_policy_errors.extend(
        _validate_citation_policy("global citation_policy", config.get("citation_policy"), require_source_trace=True)
    )
    refusal_policy_errors.extend(_validate_refusal_policy("global refusal_policy", config.get("refusal_policy")))

    interactions = config.get("interactions")
    if not isinstance(interactions, list):
        malformed_interactions.append("interactions must be a list")
        interactions = []

    for index, interaction in enumerate(interactions):
        if not isinstance(interaction, dict):
            malformed_interactions.append(f"interaction at index {index} must be a mapping")
            continue
        label = _interaction_label(index, interaction)
        for field in REQUIRED_INTERACTION_FIELDS:
            if field not in interaction:
                malformed_interactions.append(f"interaction {label} missing required field {field}")

        interaction_id = interaction.get("interaction_id")
        if not isinstance(interaction_id, str) or not interaction_id.strip():
            interaction_contract_errors.append(f"interaction_id at index {index} must be a non-empty string")

        intent = interaction.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            interaction_contract_errors.append(f"interaction {label} intent must be a non-empty string")

        input_kind = interaction.get("input_kind")
        if not isinstance(input_kind, str) or input_kind not in ALLOWED_INPUT_KINDS:
            interaction_contract_errors.append(f"interaction {label} input_kind must be allowed")

        if not isinstance(interaction.get("human_review_required"), bool):
            interaction_contract_errors.append(f"interaction {label} human_review_required must be boolean")

        persona = interaction.get("persona")
        if not isinstance(persona, str) or persona not in allowed_personas:
            invalid_personas.append(f"interaction {label} persona must be allowed")

        behavior = interaction.get("expected_behavior")
        if not isinstance(behavior, str) or behavior not in ALLOWED_EXPECTED_BEHAVIORS:
            invalid_expected_behaviors.append(f"invalid expected_behavior for {label}: {behavior}")

        citation_policy_errors.extend(
            _validate_citation_policy(
                f"interaction {label}",
                interaction.get("citation_policy"),
                require_source_trace=False,
            )
        )
        refusal_policy_errors.extend(
            _validate_refusal_policy(
                f"interaction {label}",
                interaction.get("refusal_policy"),
                behavior=behavior,
            )
        )

        raw_metadata_filters = interaction.get("metadata_filters_required")
        metadata_filters = _string_list(interaction.get("metadata_filters_required"))
        if not isinstance(raw_metadata_filters, list) or len(metadata_filters) != len(raw_metadata_filters):
            interaction_contract_errors.append(f"interaction {label} metadata_filters_required must be a list of strings")
        if isinstance(behavior, str) and behavior not in REFUSAL_BEHAVIORS and not metadata_filters:
            malformed_interactions.append(f"interaction {label} metadata_filters_required must be non-empty")
        if isinstance(behavior, str) and behavior not in REFUSAL_BEHAVIORS:
            missing_filters = sorted(REQUIRED_METADATA_FILTERS_FOR_NON_REFUSAL.difference(metadata_filters))
            if missing_filters:
                interaction_contract_errors.append(
                    f"interaction {label} missing metadata_filters_required: {', '.join(missing_filters)}"
                )
        if isinstance(behavior, str) and behavior in REFUSAL_BEHAVIORS and metadata_filters:
            interaction_contract_errors.append(f"refusal interaction {label} metadata_filters_required must be empty")
        if interaction.get("answer_generation_expected") is True:
            malformed_interactions.append(f"interaction {label} must not request answer generation")
        if interaction.get("output_kind") == "final_answer":
            interaction_contract_errors.append(f"interaction {label} output_kind final_answer is forbidden")
        for field in sorted(FORBIDDEN_RUNTIME_FIELDS):
            if field in interaction:
                forbidden_runtime_fields.append(f"interaction {label} forbidden runtime field: {field}")

    issues = [
        *config_errors,
        *invalid_contract_values,
        *dangerous_flags_enabled,
        *missing_required_personas,
        *malformed_interactions,
        *invalid_personas,
        *invalid_expected_behaviors,
        *citation_policy_errors,
        *refusal_policy_errors,
        *interaction_contract_errors,
        *forbidden_runtime_fields,
    ]
    return {
        "config_errors": config_errors,
        "invalid_contract_values": invalid_contract_values,
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_required_personas": missing_required_personas,
        "malformed_interactions": malformed_interactions,
        "invalid_personas": invalid_personas,
        "invalid_expected_behaviors": invalid_expected_behaviors,
        "citation_policy_errors": citation_policy_errors,
        "refusal_policy_errors": refusal_policy_errors,
        "interaction_contract_errors": interaction_contract_errors,
        "forbidden_runtime_fields": forbidden_runtime_fields,
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
    interactions = config.get("interactions")
    interaction_list = interactions if isinstance(interactions, list) else []

    print("# Pedagogical interface contract audit")
    print()
    print("## Summary")
    print()
    print(f"- contract_id: {config.get('contract_id', 'missing')}")
    print(f"- status: {config.get('status', 'missing')}")
    print(f"- interface_ready_for_review: {str(not issues).lower()}")
    print(f"- interactions_count: {len(interaction_list)}")
    print(f"- personas_count: {len(_string_list(config.get('allowed_personas')))}")
    print(f"- invalid_contract_values_count: {len(audit['invalid_contract_values'])}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_required_personas_count: {len(audit['missing_required_personas'])}")
    print(f"- malformed_interactions_count: {len(audit['malformed_interactions'])}")
    print(f"- invalid_personas_count: {len(audit['invalid_personas'])}")
    print(f"- invalid_expected_behaviors_count: {len(audit['invalid_expected_behaviors'])}")
    print(f"- citation_policy_errors_count: {len(audit['citation_policy_errors'])}")
    print(f"- refusal_policy_errors_count: {len(audit['refusal_policy_errors'])}")
    print(f"- interaction_contract_errors_count: {len(audit['interaction_contract_errors'])}")
    print(f"- forbidden_runtime_fields_count: {len(audit['forbidden_runtime_fields'])}")
    for flag in [
        "answer_generation_allowed",
        "runtime_api_allowed",
        "server_start_allowed",
        "ui_runtime_allowed",
        "embeddings_allowed",
        "qdrant_allowed",
        "real_documents_allowed",
    ]:
        print(f"- {flag}: {str(config.get(flag, 'missing')).lower()}")
    print("- destructive_action_available: false")
    print()
    print("## Invalid contract values")
    print()
    _print_list(audit["invalid_contract_values"])
    print()
    print("## Personas")
    print()
    _print_list(_string_list(config.get("allowed_personas")))
    print()
    print("## Interactions")
    print()
    for interaction in interaction_list:
        if isinstance(interaction, dict):
            print(f"- {interaction.get('interaction_id', 'missing')}: {interaction.get('expected_behavior', 'missing')}")
    if not interaction_list:
        print("- none")
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
    print("## Refusal policy")
    print()
    refusal_policy = config.get("refusal_policy")
    if isinstance(refusal_policy, dict):
        for key in [
            "refusal_required_when_no_source",
            "refusal_required_for_real_document_request",
            "refusal_required_for_unknown_rights",
            "no_answer_generation_on_refusal",
        ]:
            print(f"- {key}: {str(refusal_policy.get(key, 'missing')).lower()}")
    else:
        print("- missing")
    print()
    print("## Interaction contract errors")
    print()
    _print_list(audit["interaction_contract_errors"])
    print()
    print("## Forbidden runtime fields")
    print()
    _print_list(audit["forbidden_runtime_fields"])
    print()
    print("## Blocking issues")
    print()
    _print_list(issues)
    print()
    print("## Explicit non-actions")
    print()
    print("- no API server started")
    print("- no UI runtime started")
    print("- no real document read")
    print("- no PDF copied")
    print("- no ingestion launched")
    print("- no retrieval executed")
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
