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
from typing import Any

from trusted_human_review import (
    TrustedReviewDecision,
    build_expected_challenges,
    evaluate_trusted_review,
    load_config,
)


STATUS_CONTEXT = "trusted-human-review"
COMMENT_MARKER = "<!-- nexus:trusted-human-review:v1 -->"
GH_API_VERSION = "2026-03-10"
GH_API_TIMEOUT_SECONDS = 30
PAGE_SIZE = 100
MAX_REVIEW_PAGES = 20
MAX_COMMENT_PAGES = 20
DEFAULT_CONFIG_PATH = Path(__file__).with_name("trusted-reviewers.json")

_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


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


def _api_args(endpoint: str, *, method: str = "GET") -> list[str]:
    argv = [
        "gh",
        "api",
        endpoint,
        "-H",
        f"X-GitHub-Api-Version: {GH_API_VERSION}",
    ]
    if method != "GET":
        argv.extend(["--method", method, "--input", "-"])
    return argv


def _call(
    runner: Runner,
    endpoint: str,
    *,
    method: str = "GET",
    payload: Mapping[str, object] | None = None,
) -> object:
    input_data = None
    if payload is not None:
        input_data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return runner(_api_args(endpoint, method=method), input_data=input_data)


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


def _evaluate(
    *,
    repository: str,
    pull_request_number: int,
    expected_head: str,
    config_path: Path,
    runner: Runner,
    initial_pull_request: Mapping[str, object] | None = None,
) -> GitHubReviewResult:
    if type(pull_request_number) is not int or pull_request_number <= 0:
        raise ValueError("pull_request_number must be a positive integer")
    expected_head = _require_expected_head(expected_head)
    config = load_config(config_path)
    if repository != config.repository:
        raise ValueError("repository does not match trusted reviewer config")

    pull_request = initial_pull_request or _read_pull_request(
        runner, repository, pull_request_number
    )
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

    initial_head = _head_sha(pull_request)
    if initial_head != expected_head:
        decision = _failure_decision(decision, "expected_head_mismatch")

    readback = _read_pull_request(runner, repository, pull_request_number)
    if _head_sha(readback) != initial_head:
        decision = _failure_decision(
            decision, "head_changed_during_evaluation"
        )
    return GitHubReviewResult(decision=decision, challenges=challenges)


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


def _post_status(
    *,
    runner: Runner,
    repository: str,
    head_sha: str,
    state: str,
    description: str,
    target_url: str | None,
) -> None:
    payload: dict[str, object] = {
        "state": state,
        "context": STATUS_CONTEXT,
        "description": description[:140],
    }
    if target_url is not None:
        payload["target_url"] = target_url
    _call(
        runner,
        f"repos/{repository}/statuses/{head_sha}",
        method="POST",
        payload=payload,
    )


def _collect_comments(
    runner: Runner, repository: str, pull_request_number: int
) -> list[object]:
    comments: list[object] = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        endpoint = (
            f"repos/{repository}/issues/{pull_request_number}/comments"
            f"?per_page={PAGE_SIZE}&page={page}"
        )
        current = _list(_call(runner, endpoint), f"comments page {page}")
        comments.extend(current)
        if len(current) < PAGE_SIZE:
            return comments
    raise GitHubAdapterError("issue comments pagination is incomplete")


def _comment_body(result: GitHubReviewResult) -> str:
    verdict = "APPROVED" if result.decision.approved else "PENDING"
    challenges = "\n".join(
        f"- `{reviewer}` : `{challenge}`"
        for reviewer, challenge in sorted(result.challenges.items())
    )
    return (
        f"{COMMENT_MARKER}\n"
        "## Revue humaine fiable LOT41V\n\n"
        f"- Verdict : `{verdict}`\n"
        f"- Motif : `{result.decision.reason}`\n"
        f"- Head exact : `{result.decision.head_sha}`\n\n"
        "Le reviewer autorisé doit soumettre une review GitHub formelle "
        "sur ce head et placer son challenge exact sur une ligne distincte :\n\n"
        f"{challenges}\n"
    )


def _upsert_comment(
    *,
    runner: Runner,
    repository: str,
    pull_request_number: int,
    result: GitHubReviewResult,
) -> None:
    managed: list[Mapping[str, object]] = []
    for index, raw_comment in enumerate(
        _collect_comments(runner, repository, pull_request_number)
    ):
        comment = _mapping(raw_comment, f"comments[{index}]")
        body = comment.get("body")
        user = _mapping(comment.get("user"), f"comments[{index}].user")
        if (
            isinstance(body, str)
            and COMMENT_MARKER in body
            and user.get("login") == "github-actions[bot]"
        ):
            managed.append(comment)
    if len(managed) > 1:
        raise GitHubAdapterError("multiple managed review comments found")

    payload = {"body": _comment_body(result)}
    if managed:
        comment_id = managed[0].get("id")
        if type(comment_id) is not int or comment_id <= 0:
            raise GitHubAdapterError("managed comment id is malformed")
        endpoint = f"repos/{repository}/issues/comments/{comment_id}"
        _call(runner, endpoint, method="PATCH", payload=payload)
    else:
        endpoint = f"repos/{repository}/issues/{pull_request_number}/comments"
        _call(runner, endpoint, method="POST", payload=payload)


def publish_github_review(
    *,
    repository: str,
    pull_request_number: int,
    expected_head: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
    target_url: str | None,
    runner: Runner = run_gh_api,
) -> GitHubReviewResult:
    """Publie un statut explicite et le challenge, sans créer de review."""

    expected_head = _require_expected_head(expected_head)
    try:
        _post_status(
            runner=runner,
            repository=repository,
            head_sha=expected_head,
            state="pending",
            description="Revue humaine indépendante en cours",
            target_url=target_url,
        )
        initial_pull_request = _read_pull_request(
            runner, repository, pull_request_number
        )
        observed_head = _head_sha(initial_pull_request)
        result = _evaluate(
            repository=repository,
            pull_request_number=pull_request_number,
            expected_head=expected_head,
            config_path=config_path,
            runner=runner,
            initial_pull_request=initial_pull_request,
        )
        if observed_head != expected_head:
            result = GitHubReviewResult(
                decision=_failure_decision(
                    result.decision, "expected_head_mismatch"
                ),
                challenges=result.challenges,
            )
        _post_status(
            runner=runner,
            repository=repository,
            head_sha=expected_head,
            state="success" if result.decision.approved else "failure",
            description=(
                "Revue humaine indépendante vérifiée"
                if result.decision.approved
                else f"Revue refusée: {result.decision.reason}"
            ),
            target_url=target_url,
        )
        _upsert_comment(
            runner=runner,
            repository=repository,
            pull_request_number=pull_request_number,
            result=result,
        )
        return result
    except Exception:
        try:
            _post_status(
                runner=runner,
                repository=repository,
                head_sha=expected_head,
                state="failure",
                description="Évaluation de revue GitHub en échec fermé",
                target_url=target_url,
            )
        except Exception:
            pass
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Vérifie une approbation humaine GitHub liée au head exact."
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--expected-head", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--publish", action="store_true")
    parser.add_argument("--target-url")
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
    kwargs: dict[str, Any] = {
        "repository": args.repository,
        "pull_request_number": args.pull_request,
        "expected_head": args.expected_head,
        "config_path": config_path,
        "runner": runner,
    }
    try:
        if args.check:
            result = check_github_review(**kwargs)
        else:
            result = publish_github_review(
                **kwargs,
                target_url=args.target_url,
            )
    except (GitHubAdapterError, TypeError, ValueError) as exc:
        print(f"trusted human review error: {exc}", file=sys.stderr)
        return 2
    print(_json_result(result))
    if args.check and not result.decision.approved:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
