from __future__ import annotations

import argparse
import importlib.util
import sys
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


def _print_count(name: str, paths: set[str]) -> None:
    print(f"- {name}: {len(paths)}")


def _print_sample(title: str, paths: set[str], sample_limit: int) -> None:
    print(f"## {title}")
    print()
    if not paths:
        print("- none")
        print()
        return
    for path in sorted(paths)[:sample_limit]:
        print(f"- {path}")
    remaining = len(paths) - sample_limit
    if remaining > 0:
        print(f"- ... {remaining} more")
    print()


def _print_decision_items() -> None:
    for item in [
        "conserver",
        "ignorer",
        "archiver dans un futur lot dédié",
        "supprimer dans un futur lot dédié",
        "examiner manuellement",
        "exclure explicitement du périmètre",
    ]:
        print(f"- [ ] {item}")


def print_review_package(
    policy: cleanup_dry_run.CleanupPolicy,
    report: cleanup_dry_run.DryRunReport,
    sample_limit: int,
) -> None:
    print("# Cleanup review package")
    print()
    print("## Summary")
    print()
    print(f"- workspace_root: {policy.workspace_root}")
    print(f"- active_repo: {policy.active_repo}")
    for repo in policy.readonly_repos:
        print(f"- readonly_repo: {repo}")
    print("- would_delete: 0")
    print("- would_move: 0")
    print("- human_review_required: true")
    print("- destructive_action_available: false")
    print(f"- sample_limit: {sample_limit}")
    print()
    print("Les compteurs sont observationnels.")
    print("Ils peuvent varier selon l’état courant du workspace.")
    print("Les chemins listés ne valent pas autorisation d’action.")
    print()
    print("## Counts")
    print()
    _print_count("safe_delete_candidates", report.safe_delete_candidates)
    _print_count("archive_candidates", report.archive_candidates)
    _print_count("never_delete_matches", report.never_delete_matches)
    _print_count("always_keep_matches", report.always_keep_matches)
    _print_count("readonly_repo_matches", report.readonly_repo_matches)
    _print_count("deep_scan_exclusions", report.deep_scan_exclusions)
    _print_count("summarize_only_roots", report.summarize_only_roots)
    print()
    _print_sample("Safe delete candidates — sample only", report.safe_delete_candidates, sample_limit)
    _print_sample("Archive candidates — sample only", report.archive_candidates, sample_limit)
    _print_sample("Never delete matches — sample only", report.never_delete_matches, sample_limit)
    _print_sample("Always keep matches — sample only", report.always_keep_matches, sample_limit)
    _print_sample("Read-only repository matches — summary", report.readonly_repo_matches, sample_limit)
    _print_sample("Deep scan exclusions", report.deep_scan_exclusions, sample_limit)
    _print_sample("Summarize-only roots", report.summarize_only_roots, sample_limit)
    print("## Human decision checklist")
    print()
    _print_decision_items()
    print()
    print("Aucune décision ne doit être appliquée par ce paquet de revue.")
    print()
    print("## Explicit non-actions")
    print()
    for item in [
        "no file deleted",
        "no file moved",
        "no archive created",
        "no secret read",
        "no .env opened",
        "no ledger modified",
        "no data/staging created",
    ]:
        print(f"- {item}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a non-destructive cleanup review package.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    args = parser.parse_args(argv)

    if args.sample_limit < 1 or args.sample_limit > MAX_SAMPLE_LIMIT:
        parser.error(f"--sample-limit must be between 1 and {MAX_SAMPLE_LIMIT}")

    policy = cleanup_dry_run.load_policy(args.config)
    report = cleanup_dry_run.build_dry_run_report(policy)
    print_review_package(policy, report, args.sample_limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
