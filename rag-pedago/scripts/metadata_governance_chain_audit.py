from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / "configs/metadata_governance_chain.yml"

REQUIRED_CHAIN_VALUES = {
    "chain_id": "metadata_governance_chain_17C_17I_v1",
    "status": "metadata_only_governance_chain",
    "latest_committed_lot": "17I",
    "latest_commit_ref": "cbc4655e51c9e09e396cff957620359c9005b2e9",
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
REQUIRED_LOTS = ["17C", "17D", "17E", "17F", "17G", "17H", "17I"]
REQUIRED_LOT_FIELDS = [
    "lot_id",
    "config_ref",
    "protocol_ref",
    "script_ref",
    "test_ref",
    "report_ref",
    "make_target",
    "expected_status",
    "expected_ready_marker",
]
PATH_REF_FIELDS = ["config_ref", "protocol_ref", "script_ref", "test_ref", "report_ref"]
ALLOWED_CHAIN_DECISIONS = {
    "chain_ready_for_metadata_review",
    "chain_requires_human_review",
    "chain_blocked_for_real_corpus",
    "chain_requires_followup_metadata_lot",
}
EXPECTED_CHAIN_DECISION = "chain_ready_for_metadata_review"
EXPECTED_CHAIN_DECISION_REASON = "metadata_governance_chain_complete"
CHAIN_DECISION_TRUE_FIELDS = ["human_review_required", "followup_lot_required"]
CHAIN_DECISION_FALSE_FIELDS = ["real_corpus_allowed", "real_file_allowed", "pipeline_allowed"]
REAL_DOCUMENT_SUFFIXES = (".pdf", ".docx", ".pptx", ".xlsx")
UNSAFE_PATH_MARKERS = ("data/staging", ".env")
SENSITIVE_MAKE_TARGET_TERMS = {
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
    "scrape",
    "backup",
    "watch",
}
SCRIPT_FORBIDDEN_TOKENS = [
    "sub" + "process",
    "req" + "uests",
    "htt" + "px",
    "url" + "lib",
    "sock" + "et",
    "un" + "link(",
    "rem" + "ove(",
    "rm" + "dir(",
    "shutil." + "rmtree",
    "shutil." + "move",
    "git " + "clean",
    "find " + "-delete",
    "rm " + "-rf",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the metadata-only governance chain.")
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


def _contains_url(value: str) -> bool:
    lowered = value.lower()
    return "://" in lowered or lowered.startswith("www.")


def _contains_real_document_suffix(value: str) -> bool:
    lowered = value.lower()
    return any(lowered.endswith(suffix) or f"{suffix}?" in lowered for suffix in REAL_DOCUMENT_SUFFIXES)


def _is_unsafe_path(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    path = Path(value)
    lowered = value.lower()
    if path.is_absolute():
        return True
    if _contains_url(value) or _contains_real_document_suffix(value):
        return True
    return any(marker in lowered for marker in UNSAFE_PATH_MARKERS)


def _resolve_repo_path(value: str) -> Path:
    return REPO_ROOT / value


def _load_yaml_mapping(path: Path) -> dict[str, Any] | None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def _load_safe_targets() -> set[str]:
    data = yaml.safe_load((REPO_ROOT / "configs/make_target_safety.yml").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return set()
    return set(_string_list(data.get("SAFE_METADATA_ONLY")))


def _lot_label(index: int, lot: object) -> str:
    if isinstance(lot, dict) and isinstance(lot.get("lot_id"), str) and str(lot["lot_id"]).strip():
        return str(lot["lot_id"]).strip()
    return f"index {index}"


def audit_config(config: dict[str, Any]) -> dict[str, list[str]]:
    config_errors: list[str] = []
    invalid_chain_values: list[str] = []
    dangerous_flags_enabled: list[str] = []
    missing_chain_lots: list[str] = []
    duplicate_chain_lots: list[str] = []
    missing_required_fields: list[str] = []
    missing_referenced_files: list[str] = []
    unsafe_paths: list[str] = []
    unsafe_make_targets: list[str] = []
    missing_safe_classifications: list[str] = []
    config_status_errors: list[str] = []
    script_safety_errors: list[str] = []
    report_marker_errors: list[str] = []
    chain_decision_errors: list[str] = []

    if isinstance(config.get("_config_error"), str):
        config_errors.append(str(config["_config_error"]))

    for field, expected_value in REQUIRED_CHAIN_VALUES.items():
        if config.get(field) != expected_value:
            invalid_chain_values.append(f"{field} must be {expected_value}")

    for flag in REQUIRED_FALSE_FLAGS:
        if config.get(flag) is not False:
            dangerous_flags_enabled.append(f"{flag} must be false")

    safe_targets = _load_safe_targets()
    chain_lots = config.get("required_chain_lots")
    if not isinstance(chain_lots, list) or not chain_lots:
        missing_required_fields.append("required_chain_lots must be a non-empty list")
        chain_lots = []

    seen_lots: set[str] = set()
    lot_entries: list[dict[str, Any]] = []
    for index, lot in enumerate(chain_lots):
        if not isinstance(lot, dict):
            missing_required_fields.append(f"chain lot at index {index} must be a mapping")
            continue
        lot_entries.append(lot)
        label = _lot_label(index, lot)
        lot_id = lot.get("lot_id")
        if not isinstance(lot_id, str) or not lot_id.strip():
            missing_required_fields.append(f"chain lot at index {index} missing required field lot_id")
        elif lot_id in seen_lots:
            duplicate_chain_lots.append(f"duplicate chain lot: {lot_id}")
        else:
            seen_lots.add(lot_id)

        for field in REQUIRED_LOT_FIELDS:
            if field not in lot:
                missing_required_fields.append(f"lot {label} missing required field {field}")

        for field in PATH_REF_FIELDS:
            if field not in lot:
                continue
            value = lot[field]
            if _is_unsafe_path(value):
                unsafe_paths.append(f"unsafe path for {label} {field}: {value}")
                continue
            ref_path = _resolve_repo_path(str(value))
            if not ref_path.is_file():
                missing_referenced_files.append(f"missing referenced file for {label} {field}: {value}")

        make_target = lot.get("make_target")
        if isinstance(make_target, str) and make_target.strip():
            for term in sorted(SENSITIVE_MAKE_TARGET_TERMS):
                if term in make_target:
                    unsafe_make_targets.append(f"unsafe make target for {label}: {make_target}")
                    break
            if make_target not in safe_targets:
                missing_safe_classifications.append(
                    f"make_target {make_target} must be classified SAFE_METADATA_ONLY"
                )
        elif "make_target" in lot:
            unsafe_make_targets.append(f"unsafe make target for {label}: {make_target}")

        config_ref = lot.get("config_ref")
        expected_status = lot.get("expected_status")
        if (
            isinstance(config_ref, str)
            and isinstance(expected_status, str)
            and not _is_unsafe_path(config_ref)
            and _resolve_repo_path(config_ref).is_file()
        ):
            referenced_config = _load_yaml_mapping(_resolve_repo_path(config_ref))
            if referenced_config is None:
                config_status_errors.append(f"config for {label} must be a YAML mapping")
            elif referenced_config.get("status") != expected_status:
                config_status_errors.append(f"config for {label} missing expected_status {expected_status}")

        script_ref = lot.get("script_ref")
        if isinstance(script_ref, str) and not _is_unsafe_path(script_ref) and _resolve_repo_path(script_ref).is_file():
            script_text = _resolve_repo_path(script_ref).read_text(encoding="utf-8")
            for token in SCRIPT_FORBIDDEN_TOKENS:
                if token in script_text:
                    script_safety_errors.append(f"script for {label} contains forbidden token: {token}")
                    break

        report_ref = lot.get("report_ref")
        expected_ready_marker = lot.get("expected_ready_marker")
        if (
            isinstance(report_ref, str)
            and isinstance(expected_ready_marker, str)
            and not _is_unsafe_path(report_ref)
            and _resolve_repo_path(report_ref).is_file()
        ):
            report_text = _resolve_repo_path(report_ref).read_text(encoding="utf-8")
            if expected_ready_marker not in report_text:
                report_marker_errors.append(f"report for {label} missing expected_ready_marker")

    for required_lot in REQUIRED_LOTS:
        if required_lot not in seen_lots:
            missing_chain_lots.append(f"missing required chain lot: {required_lot}")
    for lot_id in sorted(seen_lots.difference(REQUIRED_LOTS)):
        missing_chain_lots.append(f"unknown chain lot: {lot_id}")

    configured_decisions = set(_string_list(config.get("allowed_chain_decisions")))
    for decision in ALLOWED_CHAIN_DECISIONS:
        if decision not in configured_decisions:
            chain_decision_errors.append(f"missing allowed_chain_decisions: {decision}")
    for decision in sorted(configured_decisions.difference(ALLOWED_CHAIN_DECISIONS)):
        chain_decision_errors.append(f"allowed_chain_decisions contains unknown decision: {decision}")

    chain_decision = config.get("chain_decision")
    if not isinstance(chain_decision, dict):
        chain_decision_errors.append("chain_decision must be a mapping")
    else:
        decision = chain_decision.get("decision")
        if not isinstance(decision, str) or decision not in configured_decisions.intersection(ALLOWED_CHAIN_DECISIONS):
            chain_decision_errors.append("chain_decision.decision must be allowed")
        elif decision != EXPECTED_CHAIN_DECISION:
            chain_decision_errors.append(f"chain_decision.decision must be {EXPECTED_CHAIN_DECISION}")
        decision_reason = chain_decision.get("decision_reason")
        if not isinstance(decision_reason, str) or not decision_reason.strip():
            chain_decision_errors.append("chain_decision.decision_reason must be a non-empty string")
        elif decision_reason != EXPECTED_CHAIN_DECISION_REASON:
            chain_decision_errors.append(
                f"chain_decision.decision_reason must be {EXPECTED_CHAIN_DECISION_REASON}"
            )
        for field in CHAIN_DECISION_FALSE_FIELDS:
            if chain_decision.get(field) is not False:
                chain_decision_errors.append(f"chain_decision.{field} must be false")
        for field in CHAIN_DECISION_TRUE_FIELDS:
            if chain_decision.get(field) is not True:
                chain_decision_errors.append(f"chain_decision.{field} must be true")

    issues = [
        *config_errors,
        *invalid_chain_values,
        *dangerous_flags_enabled,
        *missing_chain_lots,
        *duplicate_chain_lots,
        *missing_required_fields,
        *missing_referenced_files,
        *unsafe_paths,
        *unsafe_make_targets,
        *missing_safe_classifications,
        *config_status_errors,
        *script_safety_errors,
        *report_marker_errors,
        *chain_decision_errors,
    ]
    return {
        "config_errors": config_errors,
        "invalid_chain_values": invalid_chain_values,
        "dangerous_flags_enabled": dangerous_flags_enabled,
        "missing_chain_lots": missing_chain_lots,
        "duplicate_chain_lots": duplicate_chain_lots,
        "missing_required_fields": missing_required_fields,
        "missing_referenced_files": missing_referenced_files,
        "unsafe_paths": unsafe_paths,
        "unsafe_make_targets": unsafe_make_targets,
        "missing_safe_classifications": missing_safe_classifications,
        "config_status_errors": config_status_errors,
        "script_safety_errors": script_safety_errors,
        "report_marker_errors": report_marker_errors,
        "chain_decision_errors": chain_decision_errors,
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
    chain_lots = config.get("required_chain_lots")
    lot_list = chain_lots if isinstance(chain_lots, list) else []

    print("# Metadata governance chain audit")
    print()
    print("## Summary")
    print()
    print(f"- chain_id: {config.get('chain_id', 'missing')}")
    print(f"- status: {config.get('status', 'missing')}")
    print(f"- chain_ready_for_review: {str(not issues).lower()}")
    print(f"- chain_lots_count: {len(lot_list)}")
    print(f"- dangerous_flags_enabled_count: {len(audit['dangerous_flags_enabled'])}")
    print(f"- missing_chain_lots_count: {len(audit['missing_chain_lots'])}")
    print(f"- duplicate_chain_lots_count: {len(audit['duplicate_chain_lots'])}")
    print(f"- missing_required_fields_count: {len(audit['missing_required_fields'])}")
    print(f"- missing_referenced_files_count: {len(audit['missing_referenced_files'])}")
    print(f"- unsafe_paths_count: {len(audit['unsafe_paths'])}")
    print(f"- unsafe_make_targets_count: {len(audit['unsafe_make_targets'])}")
    print(f"- missing_safe_classifications_count: {len(audit['missing_safe_classifications'])}")
    print(f"- config_status_errors_count: {len(audit['config_status_errors'])}")
    print(f"- script_safety_errors_count: {len(audit['script_safety_errors'])}")
    print(f"- report_marker_errors_count: {len(audit['report_marker_errors'])}")
    print(f"- chain_decision_errors_count: {len(audit['chain_decision_errors'])}")
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
    print("## Chain lots")
    print()
    for lot in lot_list:
        if isinstance(lot, dict):
            print(f"- {lot.get('lot_id', 'missing')}: {lot.get('make_target', 'missing')}")
        else:
            print("- malformed lot entry")
    if not lot_list:
        print("- none")
    print()
    print("## Missing chain lots")
    print()
    _print_list(audit["missing_chain_lots"])
    print()
    print("## Duplicate chain lots")
    print()
    _print_list(audit["duplicate_chain_lots"])
    print()
    print("## Missing referenced files")
    print()
    _print_list(audit["missing_referenced_files"])
    print()
    print("## Unsafe paths")
    print()
    _print_list(audit["unsafe_paths"])
    print()
    print("## Unsafe make targets")
    print()
    _print_list(audit["unsafe_make_targets"])
    print()
    print("## Missing safe classifications")
    print()
    _print_list(audit["missing_safe_classifications"])
    print()
    print("## Config status errors")
    print()
    _print_list(audit["config_status_errors"])
    print()
    print("## Script safety errors")
    print()
    _print_list(audit["script_safety_errors"])
    print()
    print("## Report marker errors")
    print()
    _print_list(audit["report_marker_errors"])
    print()
    print("## Chain decision errors")
    print()
    _print_list(audit["chain_decision_errors"])
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
