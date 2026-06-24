from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

_CLEANUP_DRY_RUN_PATH = Path(__file__).resolve().with_name("cleanup_dry_run.py")
_SPEC = importlib.util.spec_from_file_location("cleanup_dry_run", _CLEANUP_DRY_RUN_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load cleanup dry-run module from {_CLEANUP_DRY_RUN_PATH}")
cleanup_dry_run = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cleanup_dry_run
_SPEC.loader.exec_module(cleanup_dry_run)


DEFAULT_CONFIG = cleanup_dry_run.DEFAULT_CONFIG
DEFAULT_SAMPLE_LIMIT = 20
MAX_SAMPLE_LIMIT = 200
ALLOWED_CURRENT_ACTION = "NONE_IN_THIS_LOT"


@dataclass(frozen=True)
class CategoryDecision:
    category: str
    default_decision: str
    rationale: str


CATEGORY_DECISIONS = [
    CategoryDecision("always_keep_matches", "KEEP_REQUIRED", "protected by cleanup policy"),
    CategoryDecision("never_delete_matches", "NEVER_DELETE", "automatic action forbidden"),
    CategoryDecision("readonly_repo_matches", "READONLY_REPOSITORY", "repository is read-only"),
    CategoryDecision("deep_scan_exclusions", "DEEP_SCAN_EXCLUDED", "excluded from deep scan"),
    CategoryDecision("summarize_only_roots", "DEEP_SCAN_EXCLUDED", "summarize-only heavy root"),
    CategoryDecision("archive_candidates", "FUTURE_ARCHIVE_CANDIDATE", "future archive review only"),
    CategoryDecision("safe_delete_candidates", "FUTURE_DELETE_CANDIDATE", "future delete review only"),
]

DECISION_STATES = [
    "KEEP_REQUIRED",
    "EXCLUDE_FROM_ACTION",
    "REVIEW_REQUIRED",
    "FUTURE_ARCHIVE_CANDIDATE",
    "FUTURE_DELETE_CANDIDATE",
    "NEVER_DELETE",
    "READONLY_REPOSITORY",
    "DEEP_SCAN_EXCLUDED",
    "UNDECIDED",
]


def _paths_for_category(
    report: cleanup_dry_run.DryRunReport,
    category: str,
) -> set[str]:
    return getattr(report, category)


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|")


def _print_decision_states() -> None:
    print("## Decision states")
    print()
    for state in DECISION_STATES:
        print(f"- {state}")
    print()


def _print_category_defaults() -> None:
    print("## Category decision defaults")
    print()
    for decision in CATEGORY_DECISIONS:
        print(f"- {decision.category} -> {decision.default_decision}")
    print()


def _print_decision_table(
    report: cleanup_dry_run.DryRunReport,
    sample_limit: int,
) -> None:
    print("## Decision table — sample only")
    print()
    print("| category | path | default_decision | allowed_current_action | rationale |")
    print("|---|---|---|---|---|")
    for decision in CATEGORY_DECISIONS:
        paths = sorted(_paths_for_category(report, decision.category))[:sample_limit]
        if not paths:
            print(
                f"| {decision.category} | none | {decision.default_decision} | "
                f"{ALLOWED_CURRENT_ACTION} | {decision.rationale} |"
            )
            continue
        for path in paths:
            print(
                f"| {decision.category} | {_escape_table_cell(path)} | "
                f"{decision.default_decision} | {ALLOWED_CURRENT_ACTION} | "
                f"{decision.rationale} |"
            )
    print()


def _print_excluded_from_automatic_action() -> None:
    print("## Excluded from automatic action")
    print()
    for state in [
        "KEEP_REQUIRED",
        "NEVER_DELETE",
        "READONLY_REPOSITORY",
        "DEEP_SCAN_EXCLUDED",
        "UNDECIDED",
    ]:
        print(f"- {state}: no automatic action")
    print()


def _print_future_only_candidates() -> None:
    print("## Future-only candidates")
    print()
    print("- FUTURE_ARCHIVE_CANDIDATE: requires a later archive-specific lot")
    print("- FUTURE_DELETE_CANDIDATE: requires a later delete-specific lot")
    print(f"- allowed_current_action: {ALLOWED_CURRENT_ACTION}")
    print()


def _print_human_validation_checklist() -> None:
    print("## Human validation checklist")
    print()
    for item in [
        "review every listed path before any later action",
        "confirm exact paths in writing",
        "separate archive and delete decisions",
        "exclude secrets, ledgers, bases, uploads, raw, infra/creds and Git history",
        "keep rag-local read-only unless a later instruction explicitly changes scope",
        "run validations again before any future action lot",
    ]:
        print(f"- [ ] {item}")


def print_decision_draft(
    policy: cleanup_dry_run.CleanupPolicy,
    report: cleanup_dry_run.DryRunReport,
    sample_limit: int,
) -> None:
    print("# Cleanup decision draft")
    print()
    print("## Summary")
    print()
    print(f"- workspace_root: {policy.workspace_root}")
    print(f"- active_repo: {policy.active_repo}")
    for repo in policy.readonly_repos:
        print(f"- readonly_repo: {repo}")
    print("- human_decision_required: true")
    print("- decision_applied: false")
    print("- destructive_action_available: false")
    print("- would_delete: 0")
    print("- would_move: 0")
    print(f"- sample_limit: {sample_limit}")
    print()
    print("Les compteurs sont observationnels.")
    print("Les chemins listés ne valent pas autorisation d’action.")
    print()
    _print_decision_states()
    _print_category_defaults()
    _print_decision_table(report, sample_limit)
    _print_excluded_from_automatic_action()
    _print_future_only_candidates()
    print("## Explicit non-actions")
    print()
    for item in [
        "no file deleted",
        "no file moved",
        "no archive created",
        "no decision applied",
        "no secret read",
        "no .env opened",
        "no ledger modified",
        "no data/staging created",
    ]:
        print(f"- {item}")
    print()
    _print_human_validation_checklist()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a non-destructive cleanup decision draft.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    args = parser.parse_args(argv)

    if args.sample_limit < 1 or args.sample_limit > MAX_SAMPLE_LIMIT:
        parser.error(f"--sample-limit must be between 1 and {MAX_SAMPLE_LIMIT}")

    policy = cleanup_dry_run.load_policy(args.config)
    report = cleanup_dry_run.build_dry_run_report(policy)
    print_decision_draft(policy, report, args.sample_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
