#!/usr/bin/env python3
"""Adaptateur GitHub fail-closed pour la revue humaine fiable LOT41V."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import re
import subprocess
import sys

from trusted_human_review import (
    TrustedReviewDecision,
    TrustedReviewerConfig,
    build_expected_challenges,
    evaluate_trusted_review,
    load_config,
)


GH_API_VERSION = "2026-03-10"
GH_API_TIMEOUT_SECONDS = 30
PAGE_SIZE = 100
MAX_REVIEW_PAGES = 20
DEFAULT_CONFIG_PATH = Path(__file__).with_name("trusted-reviewers.json")

_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_MUTATING_GH_FLAGS = (
    "--method",
    "-X",
    "--input",
    "--field",
    "-F",
    "--raw-field",
    "-f",
)


class GitHubAdapterError(RuntimeError):
    """Erreur de transport ou de forme à la frontière GitHub."""


Runner = Callable[..., object]


@dataclass(frozen=True)
class GitHubReviewResult:
    """Résultat public de la collecte et de la décision GitHub."""

    decision: TrustedReviewDecision
    challenges: dict[str, str]


def run_gh_api(
    argv: list[str], *, input_data: str | None = None
) -> object:
    """Exécute uniquement ``gh api`` sans shell et décode sa réponse JSON."""

    if argv[:2] != ["gh", "api"]:
        raise ValueError("only gh api commands are allowed")
    if any(
        argument == flag
        or argument.startswith(f"{flag}=")
        or (flag in {"-X", "-F", "-f"} and argument.startswith(flag))
        for argument in argv[2:]
        for flag in _MUTATING_GH_FLAGS
    ):
        raise ValueError("mutating gh api flags are forbidden")
    try:
        completed = subprocess.run(
            argv,
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
            timeout=GH_API_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubAdapterError(f"gh api execution failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "unknown gh api error"
        raise GitHubAdapterError(
            f"gh api returned {completed.returncode}: {detail}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubAdapterError("gh api returned malformed JSON") from exc


def _api_args(endpoint: str) -> list[str]:
    return [
        "gh",
        "api",
        endpoint,
        "-H",
        f"X-GitHub-Api-Version: {GH_API_VERSION}",
    ]


def _call(
    runner: Runner,
    endpoint: str,
) -> object:
    return runner(_api_args(endpoint), input_data=None)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise GitHubAdapterError(f"{label} is not a JSON object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise GitHubAdapterError(f"{label} is not a JSON list")
    return value


def _require_expected_head(value: object) -> str:
    if not isinstance(value, str) or _SHA_PATTERN.fullmatch(value) is None:
        raise ValueError("expected_head must be a lowercase 40-character SHA")
    return value


def _read_pull_request(
    runner: Runner, repository: str, pull_request_number: int
) -> Mapping[str, object]:
    return _mapping(
        _call(runner, f"repos/{repository}/pulls/{pull_request_number}"),
        "pull request response",
    )


def _head_sha(pull_request: Mapping[str, object]) -> str:
    head = _mapping(pull_request.get("head"), "pull request.head")
    value = head.get("sha")
    if not isinstance(value, str) or _SHA_PATTERN.fullmatch(value) is None:
        raise GitHubAdapterError("pull request.head.sha is malformed")
    return value


def _pull_request_revision(
    pull_request: Mapping[str, object],
) -> tuple[str, str, str]:
    base = _mapping(pull_request.get("base"), "pull request.base")
    base_ref = base.get("ref")
    base_sha = base.get("sha")
    if not isinstance(base_ref, str) or not base_ref:
        raise GitHubAdapterError("pull request.base.ref is malformed")
    if not isinstance(base_sha, str) or _SHA_PATTERN.fullmatch(base_sha) is None:
        raise GitHubAdapterError("pull request.base.sha is malformed")
    return (_head_sha(pull_request), base_ref, base_sha)


def _collect_reviews(
    runner: Runner, repository: str, pull_request_number: int
) -> tuple[list[object], bool]:
    reviews: list[object] = []
    for page in range(1, MAX_REVIEW_PAGES + 1):
        endpoint = (
            f"repos/{repository}/pulls/{pull_request_number}/reviews"
            f"?per_page={PAGE_SIZE}&page={page}"
        )
        current = _list(_call(runner, endpoint), f"reviews page {page}")
        reviews.extend(current)
        if len(current) < PAGE_SIZE:
            return reviews, True
    return reviews, False


def _collect_permissions(
    runner: Runner, repository: str, reviewers: Sequence[str]
) -> dict[str, object]:
    return {
        reviewer: _mapping(
            _call(
                runner,
                f"repos/{repository}/collaborators/{reviewer}/permission",
            ),
            f"permission for {reviewer}",
        )
        for reviewer in reviewers
    }


def _failure_decision(
    decision: TrustedReviewDecision, reason: str
) -> TrustedReviewDecision:
    return replace(
        decision,
        approved=False,
        reason=reason,
        reviewer=None,
        review_id=None,
        submitted_at=None,
        challenge=None,
    )


def _validated_scope(
    *,
    repository: str,
    pull_request_number: int,
    expected_head: str,
    config_path: Path,
) -> tuple[str, TrustedReviewerConfig]:
    if type(pull_request_number) is not int or pull_request_number <= 0:
        raise ValueError("pull_request_number must be a positive integer")
    normalized_head = _require_expected_head(expected_head)
    config = load_config(config_path)
    if repository != config.repository:
        raise ValueError("repository does not match trusted reviewer config")
    return normalized_head, config


def _evaluate_snapshot(
    *,
    pull_request: Mapping[str, object],
    repository: str,
    pull_request_number: int,
    config: TrustedReviewerConfig,
    runner: Runner,
) -> GitHubReviewResult:
    challenges = build_expected_challenges(pull_request, config)
    reviews, reviews_complete = _collect_reviews(
        runner, repository, pull_request_number
    )
    permissions = _collect_permissions(runner, repository, config.reviewers)
    decision = evaluate_trusted_review(
        pull_request=pull_request,
        reviews=reviews,
        permissions=permissions,
        config=config,
        reviews_complete=reviews_complete,
    )
    return GitHubReviewResult(decision=decision, challenges=challenges)


def _evaluate(
    *,
    repository: str,
    pull_request_number: int,
    expected_head: str,
    config_path: Path,
    runner: Runner,
    initial_pull_request: Mapping[str, object] | None = None,
) -> GitHubReviewResult:
    expected_head, config = _validated_scope(
        repository=repository,
        pull_request_number=pull_request_number,
        expected_head=expected_head,
        config_path=config_path,
    )

    pull_request = initial_pull_request or _read_pull_request(
        runner, repository, pull_request_number
    )
    initial_result = _evaluate_snapshot(
        pull_request=pull_request,
        repository=repository,
        pull_request_number=pull_request_number,
        config=config,
        runner=runner,
    )

    initial_revision = _pull_request_revision(pull_request)
    if initial_revision[0] != expected_head:
        return GitHubReviewResult(
            decision=_failure_decision(
                initial_result.decision, "expected_head_mismatch"
            ),
            challenges=initial_result.challenges,
        )

    readback = _read_pull_request(runner, repository, pull_request_number)
    readback_revision = _pull_request_revision(readback)
    if readback_revision != initial_revision:
        return GitHubReviewResult(
            decision=_failure_decision(
                initial_result.decision,
                (
                    "head_changed_during_evaluation"
                    if readback_revision[0] != initial_revision[0]
                    else "base_changed_during_evaluation"
                ),
            ),
            challenges=initial_result.challenges,
        )

    final_result = _evaluate_snapshot(
        pull_request=readback,
        repository=repository,
        pull_request_number=pull_request_number,
        config=config,
        runner=runner,
    )
    final_readback = _read_pull_request(
        runner, repository, pull_request_number
    )
    final_revision = _pull_request_revision(final_readback)
    if final_revision != readback_revision:
        return GitHubReviewResult(
            decision=_failure_decision(
                final_result.decision,
                (
                    "head_changed_during_evaluation"
                    if final_revision[0] != readback_revision[0]
                    else "base_changed_during_evaluation"
                ),
            ),
            challenges=final_result.challenges,
        )
    return final_result


def check_github_review(
    *,
    repository: str,
    pull_request_number: int,
    expected_head: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
    runner: Runner = run_gh_api,
) -> GitHubReviewResult:
    """Lit GitHub sans mutation et rend un verdict lié au head attendu."""

    return _evaluate(
        repository=repository,
        pull_request_number=pull_request_number,
        expected_head=expected_head,
        config_path=config_path,
        runner=runner,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Vérifie une approbation humaine GitHub liée au head exact."
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--check", action="store_true", required=True)
    return parser


def _json_result(result: GitHubReviewResult) -> str:
    return json.dumps(
        {
            "decision": asdict(result.decision),
            "challenges": result.challenges,
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = run_gh_api,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> int:
    """Point d'entrée CLI ; ``--check`` reste non nul tant que pending."""

    args = _parser().parse_args(argv)
    try:
        result = check_github_review(
            repository=args.repository,
            pull_request_number=args.pull_request,
            expected_head=args.expected_head,
            config_path=config_path,
            runner=runner,
        )
    except (GitHubAdapterError, TypeError, ValueError) as exc:
        print(f"trusted human review error: {exc}", file=sys.stderr)
        return 2
    print(_json_result(result))
    if not result.decision.approved:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
