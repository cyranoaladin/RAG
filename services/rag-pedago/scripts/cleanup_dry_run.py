from __future__ import annotations

import argparse
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from rag_pedago.paths import WORKSPACE_ROOT

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "configs/cleanup_policy.yml"
SAMPLE_LIMIT = 20


@dataclass
class CleanupPolicy:
    workspace_root: Path
    active_repo: str
    readonly_repos: list[str]
    deep_scan_exclusions: list[str]
    summarize_only_roots: list[str]
    safe_delete_candidates: list[str]
    archive_candidates: list[str]
    never_delete: list[str]
    always_keep: list[str]


@dataclass
class DryRunReport:
    safe_delete_candidates: set[str] = field(default_factory=set)
    archive_candidates: set[str] = field(default_factory=set)
    never_delete_matches: set[str] = field(default_factory=set)
    always_keep_matches: set[str] = field(default_factory=set)
    readonly_repo_matches: set[str] = field(default_factory=set)
    deep_scan_exclusions: set[str] = field(default_factory=set)
    summarize_only_roots: set[str] = field(default_factory=set)


def load_policy(config_path: Path) -> CleanupPolicy:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"cleanup policy must be a mapping: {config_path}")
    return CleanupPolicy(
        workspace_root=Path(str(payload["workspace_root"])) if payload.get("workspace_root") else WORKSPACE_ROOT,
        active_repo=str(payload["active_repo"]),
        readonly_repos=[str(item) for item in payload.get("readonly_repos", [])],
        deep_scan_exclusions=[str(item) for item in payload.get("deep_scan_exclusions", [])],
        summarize_only_roots=[str(item) for item in payload.get("summarize_only_roots", [])],
        safe_delete_candidates=[str(item) for item in payload.get("safe_delete_candidates", [])],
        archive_candidates=[str(item) for item in payload.get("archive_candidates", [])],
        never_delete=[str(item) for item in payload.get("never_delete", [])],
        always_keep=[str(item) for item in payload.get("always_keep", [])],
    )


def _matches(path_text: str, patterns: list[str]) -> bool:
    candidate = PurePosixPath(path_text)
    for pattern in patterns:
        normalized = pattern.rstrip("/")
        if candidate.match(normalized):
            return True
    return False


def _is_deep_scan_excluded(path_text: str, patterns: list[str]) -> bool:
    if _matches(path_text, patterns):
        return True
    root_patterns = [
        pattern.removesuffix("/**").rstrip("/")
        for pattern in patterns
        if pattern.endswith("/**")
    ]
    return _matches(path_text, root_patterns)


def _is_summarize_only_root(path_text: str, roots: list[str]) -> bool:
    normalized_roots = {root.rstrip("/") for root in roots}
    return path_text.rstrip("/") in normalized_roots


def _iter_workspace_paths(policy: CleanupPolicy) -> Iterable[tuple[Path, str, bool, bool]]:
    workspace_root = policy.workspace_root
    for current_root, dirs, files in os.walk(workspace_root, topdown=True, followlinks=False):
        current = Path(current_root)
        retained_dirs: list[str] = []
        for dirname in dirs:
            path = current / dirname
            if path.is_symlink():
                continue
            path_text = path.relative_to(workspace_root).as_posix()
            is_summarize_only_root = _is_summarize_only_root(
                path_text,
                policy.summarize_only_roots,
            )
            is_deep_scan_excluded = is_summarize_only_root or _is_deep_scan_excluded(
                path_text,
                policy.deep_scan_exclusions,
            )
            yield path, path_text, is_deep_scan_excluded, is_summarize_only_root
            if not is_deep_scan_excluded:
                retained_dirs.append(dirname)
        dirs[:] = retained_dirs
        for filename in files:
            path = current / filename
            if path.is_symlink():
                continue
            yield path, path.relative_to(workspace_root).as_posix(), False, False


def _is_readonly_repo_path(path_text: str, readonly_repos: list[str]) -> bool:
    return any(path_text == repo or path_text.startswith(f"{repo}/") for repo in readonly_repos)


def build_dry_run_report(policy: CleanupPolicy) -> DryRunReport:
    report = DryRunReport()
    for _path, path_text, is_deep_scan_excluded, is_summarize_only_root in _iter_workspace_paths(policy):
        if is_deep_scan_excluded:
            report.deep_scan_exclusions.add(path_text)
        if is_summarize_only_root:
            report.summarize_only_roots.add(path_text)
        if _is_readonly_repo_path(path_text, policy.readonly_repos):
            report.readonly_repo_matches.add(path_text)
        if _matches(path_text, policy.never_delete):
            report.never_delete_matches.add(path_text)
        if _matches(path_text, policy.always_keep):
            report.always_keep_matches.add(path_text)
        if _matches(path_text, policy.safe_delete_candidates):
            report.safe_delete_candidates.add(path_text)
        if _matches(path_text, policy.archive_candidates):
            report.archive_candidates.add(path_text)
    return report


def _print_samples(title: str, paths: set[str]) -> None:
    print(f"{title}:")
    for path in sorted(paths)[:SAMPLE_LIMIT]:
        print(f"  - {path}")
    if len(paths) > SAMPLE_LIMIT:
        print(f"  ... {len(paths) - SAMPLE_LIMIT} more")


def print_report(policy: CleanupPolicy, report: DryRunReport) -> None:
    print("cleanup dry-run report")
    print(f"workspace_root: {policy.workspace_root}")
    print(f"active_repo: {policy.active_repo}")
    for repo in policy.readonly_repos:
        print(f"readonly_repo: {repo}")
    print(f"safe_delete_candidates_count: {len(report.safe_delete_candidates)}")
    print(f"archive_candidates_count: {len(report.archive_candidates)}")
    print(f"never_delete_matches_count: {len(report.never_delete_matches)}")
    print(f"always_keep_matches_count: {len(report.always_keep_matches)}")
    print(f"readonly_repo_matches_count: {len(report.readonly_repo_matches)}")
    print(f"deep_scan_exclusions_count: {len(report.deep_scan_exclusions)}")
    print(f"summarize_only_roots_count: {len(report.summarize_only_roots)}")
    print("would_delete: 0")
    print("would_move: 0")
    _print_samples("safe_delete_candidates_sample", report.safe_delete_candidates)
    _print_samples("archive_candidates_sample", report.archive_candidates)
    _print_samples("never_delete_matches_sample", report.never_delete_matches)
    _print_samples("always_keep_matches_sample", report.always_keep_matches)
    _print_samples("deep_scan_exclusions_sample", report.deep_scan_exclusions)
    _print_samples("summarize_only_roots_sample", report.summarize_only_roots)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify cleanup candidates without changing files.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    policy = load_policy(args.config)
    report = build_dry_run_report(policy)
    print_report(policy, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
