from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAKEFILE = REPO_ROOT / "Makefile"
DEFAULT_CONFIG = REPO_ROOT / "configs/make_target_safety.yml"

SAFE_CATEGORIES = {
    "SAFE_DIAGNOSTIC",
    "SAFE_METADATA_ONLY",
    "SAFE_CLEANUP_REVIEW",
    "SAFE_TESTING",
}
CATEGORIES = [
    "SAFE_DIAGNOSTIC",
    "SAFE_METADATA_ONLY",
    "SAFE_CLEANUP_REVIEW",
    "SAFE_TESTING",
    "RESTRICTED_METADATA_IMPORT",
    "RESTRICTED_RUNTIME",
    "RESTRICTED_NETWORK",
    "RESTRICTED_DESTRUCTIVE_OR_BACKUP",
    "FUTURE_NOT_READY",
    "UNKNOWN",
]
SENSITIVE_TARGETS = {
    "install",
    "init",
    "scrape-official",
    "ingest",
    "ingest-official",
    "ingest-internal",
    "verify",
    "eval-retrieval",
    "watch",
    "api",
    "backup",
    "format",
}
SENSITIVE_TARGET_PATTERNS = [
    "ingest",
    "scrape",
    "api",
    "watch",
    "backup",
    "deploy",
    "prod",
    "docker",
    "qdrant",
    "embed",
    "embedding",
    "upsert",
    "migrate",
    "sync",
    "upload",
    "download",
    "seed",
    "reset",
]
SAFE_TARGET_PATTERN_EXCEPTIONS = {
    "cleanup-dry-run",
    "cleanup-review",
    "cleanup-decision-draft",
    "make-target-safety-audit",
}


def _empty_config() -> dict[str, list[str]]:
    return {category: [] for category in CATEGORIES}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Makefile target safety classification.")
    parser.add_argument("--makefile", default=str(DEFAULT_MAKEFILE))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    return parser.parse_args(argv)


def _logical_lines(makefile_text: str) -> list[str]:
    logical_lines: list[str] = []
    current = ""
    for line in makefile_text.splitlines():
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
            continue
        logical_lines.append(current + stripped)
        current = ""
    if current:
        logical_lines.append(current.rstrip())
    return logical_lines


def extract_phony_targets(makefile_text: str) -> list[str]:
    targets: set[str] = set()
    for line in _logical_lines(makefile_text):
        stripped = line.strip()
        if stripped.startswith(".PHONY:"):
            targets.update(stripped.split(":", 1)[1].split())
    return sorted(targets)


def extract_rule_targets(makefile_text: str) -> list[str]:
    targets: set[str] = set()
    for line in _logical_lines(makefile_text):
        if line.startswith("\t"):
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        target_part, remainder = stripped.split(":", 1)
        if not target_part or target_part.startswith("."):
            continue
        if any(operator in target_part for operator in ["=", "?=", ":=", "+=", "!="]):
            continue
        if remainder.startswith("="):
            continue
        for target in target_part.split():
            if "%" in target or "$" in target:
                continue
            targets.add(target)
    return sorted(targets)


def extract_make_targets(makefile_text: str) -> list[str]:
    return sorted(set(extract_phony_targets(makefile_text)) | set(extract_rule_targets(makefile_text)))


def load_config(path: Path) -> dict[str, object]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = _empty_config()
    invalid_config_categories: list[str] = []
    malformed_config_entries: list[str] = []

    if not isinstance(raw, dict):
        malformed_config_entries.append("config root must be a mapping")
        return {
            "config": config,
            "invalid_config_categories": invalid_config_categories,
            "malformed_config_entries": malformed_config_entries,
        }

    for category in raw:
        if not isinstance(category, str):
            malformed_config_entries.append(f"{category!r}: category name must be a string")
        elif category not in CATEGORIES:
            invalid_config_categories.append(category)

    for category in CATEGORIES:
        targets = raw.get(category, [])
        if not isinstance(targets, list):
            malformed_config_entries.append(f"{category}: expected list")
            continue
        valid_targets: list[str] = []
        for target in targets:
            if isinstance(target, str):
                valid_targets.append(target)
            else:
                malformed_config_entries.append(f"{category}: non-string entry {target!r}")
        config[category] = sorted(valid_targets)
    return {
        "config": config,
        "invalid_config_categories": sorted(invalid_config_categories),
        "malformed_config_entries": sorted(malformed_config_entries),
    }


def classify(config: dict[str, list[str]]) -> dict[str, object]:
    classified: dict[str, str] = {}
    duplicate_targets: set[str] = set()
    for category, targets in config.items():
        for target in targets:
            if target in classified:
                duplicate_targets.add(target)
            classified[target] = category
    return {
        "classified": classified,
        "duplicate_classifications": sorted(duplicate_targets),
    }


def audit(makefile_path: Path, config_path: Path) -> dict[str, object]:
    makefile_text = makefile_path.read_text(encoding="utf-8")
    phony_targets = extract_phony_targets(makefile_text)
    rule_targets = extract_rule_targets(makefile_text)
    targets = sorted(set(phony_targets) | set(rule_targets))
    config_result = load_config(config_path)
    config = config_result["config"]
    invalid_config_categories = config_result["invalid_config_categories"]
    malformed_config_entries = config_result["malformed_config_entries"]
    if not isinstance(config, dict):
        raise TypeError("config must be a mapping")
    if not isinstance(invalid_config_categories, list):
        raise TypeError("invalid config categories must be a list")
    if not isinstance(malformed_config_entries, list):
        raise TypeError("malformed config entries must be a list")
    classify_result = classify(config)
    classified = classify_result["classified"]
    duplicate_classifications = classify_result["duplicate_classifications"]
    if not isinstance(classified, dict):
        raise TypeError("classified targets must be a mapping")
    if not isinstance(duplicate_classifications, list):
        raise TypeError("duplicate classifications must be a list")
    classified_targets = sorted(classified)

    unclassified = sorted(target for target in targets if target not in classified)
    unknown_targets = sorted(target for target in targets if classified.get(target) == "UNKNOWN")
    rule_targets_not_phony = sorted(set(rule_targets) - set(phony_targets))
    phony_targets_without_rule = sorted(set(phony_targets) - set(rule_targets))
    extra_config_targets = sorted(set(classified_targets) - set(targets))
    unsafe_safe = sorted(
        target
        for target in targets
        if classified.get(target) in SAFE_CATEGORIES
        and (target in SENSITIVE_TARGETS or classified.get(target) == "FUTURE_NOT_READY")
    )
    suspicious_safe = sorted(
        target
        for target in targets
        if classified.get(target) in SAFE_CATEGORIES
        and target not in SAFE_TARGET_PATTERN_EXCEPTIONS
        and any(pattern in target.lower() for pattern in SENSITIVE_TARGET_PATTERNS)
    )
    restricted = sorted(
        target
        for target in targets
        if classified.get(target, "").startswith("RESTRICTED_")
    )
    future_not_ready = sorted(
        target for target in targets if classified.get(target) == "FUTURE_NOT_READY"
    )
    safe = sorted(target for target in targets if classified.get(target) in SAFE_CATEGORIES)
    counts = {category: 0 for category in CATEGORIES}
    for target in targets:
        category = classified.get(target, "UNKNOWN")
        counts[category] += 1

    return {
        "phony_targets": phony_targets,
        "rule_targets": rule_targets,
        "targets": targets,
        "counts": counts,
        "invalid_config_categories": invalid_config_categories,
        "duplicate_classifications": duplicate_classifications,
        "malformed_config_entries": malformed_config_entries,
        "unclassified": unclassified,
        "unknown_targets": unknown_targets,
        "rule_targets_not_phony": rule_targets_not_phony,
        "phony_targets_without_rule": phony_targets_without_rule,
        "extra_config_targets": extra_config_targets,
        "unsafe_safe": unsafe_safe,
        "suspicious_safe": suspicious_safe,
        "restricted": restricted,
        "future_not_ready": future_not_ready,
        "safe": safe,
    }


def _print_list(items: list[str]) -> None:
    if not items:
        print("- none")
        return
    for item in items:
        print(f"- {item}")


def print_report(result: dict[str, object]) -> None:
    counts = result["counts"]
    if not isinstance(counts, dict):
        raise TypeError("counts must be a mapping")
    phony_targets = result["phony_targets"]
    rule_targets = result["rule_targets"]
    targets = result["targets"]
    invalid_config_categories = result["invalid_config_categories"]
    duplicate_classifications = result["duplicate_classifications"]
    malformed_config_entries = result["malformed_config_entries"]
    unclassified = result["unclassified"]
    unknown_targets = result["unknown_targets"]
    rule_targets_not_phony = result["rule_targets_not_phony"]
    phony_targets_without_rule = result["phony_targets_without_rule"]
    extra_config_targets = result["extra_config_targets"]
    unsafe_safe = result["unsafe_safe"]
    suspicious_safe = result["suspicious_safe"]
    restricted = result["restricted"]
    future_not_ready = result["future_not_ready"]
    safe = result["safe"]
    audit_lists = [
        phony_targets,
        rule_targets,
        targets,
        invalid_config_categories,
        duplicate_classifications,
        malformed_config_entries,
        unclassified,
        unknown_targets,
        rule_targets_not_phony,
        phony_targets_without_rule,
        extra_config_targets,
        unsafe_safe,
        suspicious_safe,
        restricted,
        future_not_ready,
        safe,
    ]
    if not all(isinstance(value, list) for value in audit_lists):
        raise TypeError("audit lists must be lists")

    print("# Make target safety audit")
    print()
    print("## Summary")
    print()
    all_targets_classified = len(unclassified) == 0 and len(unknown_targets) == 0
    print(f"- all_targets_classified: {str(all_targets_classified).lower()}")
    print(f"- phony_targets_count: {len(phony_targets)}")
    print(f"- rule_targets_count: {len(rule_targets)}")
    print(f"- all_make_targets_count: {len(targets)}")
    print(f"- rule_targets_not_phony_count: {len(rule_targets_not_phony)}")
    print(f"- phony_targets_without_rule_count: {len(phony_targets_without_rule)}")
    print(f"- extra_config_targets_count: {len(extra_config_targets)}")
    print(f"- invalid_config_categories_count: {len(invalid_config_categories)}")
    print(f"- duplicate_classifications_count: {len(duplicate_classifications)}")
    print(f"- malformed_config_entries_count: {len(malformed_config_entries)}")
    print(f"- unknown_targets_count: {len(unknown_targets)}")
    print(f"- unclassified_targets_count: {len(unclassified)}")
    print(f"- unsafe_safe_classifications_count: {len(unsafe_safe)}")
    print(f"- suspicious_safe_classifications_count: {len(suspicious_safe)}")
    print("- destructive_action_available: false")
    print("- targets_executed: false")
    print()
    print("## Target counts by category")
    print()
    for category in CATEGORIES:
        print(f"- {category}: {counts.get(category, 0)}")
    print()
    print("## Unclassified targets")
    print()
    _print_list(unclassified)
    print()
    print("## Rule targets not declared PHONY")
    print()
    _print_list(rule_targets_not_phony)
    print()
    print("## PHONY targets without rule")
    print()
    _print_list(phony_targets_without_rule)
    print()
    print("## Extra config targets")
    print()
    _print_list(extra_config_targets)
    print()
    print("## Invalid config categories")
    print()
    _print_list(invalid_config_categories)
    print()
    print("## Duplicate classifications")
    print()
    _print_list(duplicate_classifications)
    print()
    print("## Malformed config entries")
    print()
    _print_list(malformed_config_entries)
    print()
    print("## UNKNOWN targets")
    print()
    _print_list(unknown_targets)
    print()
    print("## Unsafe SAFE classifications")
    print()
    _print_list(unsafe_safe)
    print()
    print("## Suspicious SAFE classifications")
    print()
    _print_list(suspicious_safe)
    print()
    print("## Restricted targets")
    print()
    _print_list(restricted)
    print()
    print("## Future-not-ready targets")
    print()
    _print_list(future_not_ready)
    print()
    print("## Safe targets")
    print()
    _print_list(safe)
    print()
    print("## Explicit non-actions")
    print()
    print("- no make target executed")
    print("- no file deleted")
    print("- no file moved")
    print("- no archive created")
    print("- no network call")
    print("- no .env opened")
    print("- no data/staging created")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = audit(Path(args.makefile), Path(args.config))
    print_report(result)
    has_errors = bool(
        result["unclassified"]
        or result["unsafe_safe"]
        or result["suspicious_safe"]
        or result["rule_targets_not_phony"]
        or result["phony_targets_without_rule"]
        or result["extra_config_targets"]
        or result["unknown_targets"]
        or result["invalid_config_categories"]
        or result["duplicate_classifications"]
        or result["malformed_config_entries"]
    )
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
