#!/usr/bin/env python3
"""Tests de l'adaptateur GitHub de revue humaine fiable."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import re
import sys
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_DIR = REPO_ROOT / "scripts" / "github"
MODULE_PATH = MODULE_DIR / "trusted_human_review_github.py"
CONFIG_PATH = MODULE_DIR / "trusted-reviewers.json"
sys.path.insert(0, str(MODULE_DIR))

SPEC = importlib.util.spec_from_file_location(
    "trusted_human_review_github", MODULE_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Impossible de charger {MODULE_PATH}")
github_review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = github_review
SPEC.loader.exec_module(github_review)


HEAD_SHA = "b" * 40
BASE_SHA = "a" * 40


def pull_request(*, head_sha: str = HEAD_SHA) -> dict[str, object]:
    return {
        "number": 89,
        "state": "open",
        "draft": False,
        "base": {"ref": "main", "sha": BASE_SHA},
        "head": {
            "sha": head_sha,
            "repo": {"full_name": "cyranoaladin/RAG"},
        },
        "user": {"login": "cyranoaladin"},
    }


def expected_challenge() -> str:
    from trusted_human_review import build_expected_challenges, load_config

    return build_expected_challenges(
        pull_request(), load_config(CONFIG_PATH)
    )["abenrhouma"]


def review(
    *,
    review_id: int = 1001,
    state: str = "APPROVED",
    body: str | None = None,
) -> dict[str, object]:
    return {
        "id": review_id,
        "state": state,
        "body": expected_challenge() if body is None else body,
        "commit_id": HEAD_SHA,
        "submitted_at": "2026-08-04T00:00:00Z",
        "user": {"login": "abenrhouma"},
    }


class RecordingRunner:
    def __init__(
        self,
        *,
        pull_requests: list[dict[str, object]] | None = None,
        review_pages: dict[int, list[dict[str, object]]] | None = None,
        review_snapshots: list[list[dict[str, object]]] | None = None,
        permission_snapshots: list[dict[str, object]] | None = None,
    ) -> None:
        self.pull_requests = list(
            pull_requests or [pull_request(), pull_request(), pull_request()]
        )
        self.review_pages = review_pages or {1: [review()]}
        self.review_snapshots = list(review_snapshots or [])
        self.permission_snapshots = list(permission_snapshots or [])
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(
        self, argv: list[str], *, input_data: str | None = None
    ) -> object:
        self.calls.append((list(argv), input_data))
        if argv[:2] != ["gh", "api"]:
            raise AssertionError(f"Commande inattendue: {argv}")

        endpoint = next(
            item
            for item in argv[2:]
            if item.startswith("repos/")
        )

        if re.fullmatch(r"repos/cyranoaladin/RAG/pulls/89", endpoint):
            if not self.pull_requests:
                raise AssertionError("readback PR inattendu")
            return self.pull_requests.pop(0)
        if endpoint.startswith("repos/cyranoaladin/RAG/pulls/89/reviews?"):
            match = re.search(r"(?:^|&)page=(\d+)(?:&|$)", endpoint)
            if match is None:
                raise AssertionError(f"page absente: {endpoint}")
            page = int(match.group(1))
            if page == 1 and self.review_snapshots:
                return self.review_snapshots.pop(0)
            return self.review_pages.get(page, [])
        if endpoint == (
            "repos/cyranoaladin/RAG/collaborators/abenrhouma/permission"
        ):
            if self.permission_snapshots:
                return self.permission_snapshots.pop(0)
            return {
                "permission": "write",
                "role_name": "write",
                "user": {"login": "abenrhouma"},
            }
        raise AssertionError(f"Endpoint inattendu: {endpoint}")


class GitHubReadbackTests(unittest.TestCase):
    def test_read_only_check_approves_exact_head_without_mutation(self) -> None:
        runner = RecordingRunner()

        result = github_review.check_github_review(
            repository="cyranoaladin/RAG",
            pull_request_number=89,
            expected_head=HEAD_SHA,
            config_path=CONFIG_PATH,
            runner=runner,
        )

        self.assertTrue(result.decision.approved)
        self.assertEqual(
            result.challenges,
            {"abenrhouma": expected_challenge()},
        )
        self.assertTrue(
            all("--method" not in argv for argv, _ in runner.calls)
        )

    def test_reviews_are_paginated_until_a_short_page(self) -> None:
        first_page = [
            review(
                review_id=index + 1,
                state="COMMENTED",
                body="",
            )
            for index in range(100)
        ]
        second_page = [review(review_id=1001)]
        runner = RecordingRunner(review_pages={1: first_page, 2: second_page})

        result = github_review.check_github_review(
            repository="cyranoaladin/RAG",
            pull_request_number=89,
            expected_head=HEAD_SHA,
            config_path=CONFIG_PATH,
            runner=runner,
        )

        self.assertTrue(result.decision.approved)
        endpoints = [
            next(item for item in argv if item.startswith("repos/"))
            for argv, _ in runner.calls
        ]
        self.assertTrue(any("page=1" in endpoint for endpoint in endpoints))
        self.assertTrue(any("page=2" in endpoint for endpoint in endpoints))

    def test_full_last_allowed_page_fails_closed_as_incomplete(self) -> None:
        pages = {
            page: [
                review(
                    review_id=page * 1000 + index,
                    state="COMMENTED",
                    body="",
                )
                for index in range(100)
            ]
            for page in range(1, 21)
        }
        runner = RecordingRunner(review_pages=pages)

        result = github_review.check_github_review(
            repository="cyranoaladin/RAG",
            pull_request_number=89,
            expected_head=HEAD_SHA,
            config_path=CONFIG_PATH,
            runner=runner,
        )

        self.assertFalse(result.decision.approved)
        self.assertEqual(result.decision.reason, "reviews_incomplete")

    def test_head_race_never_returns_success(self) -> None:
        runner = RecordingRunner(
            pull_requests=[pull_request(), pull_request(head_sha="c" * 40)]
        )

        result = github_review.check_github_review(
            repository="cyranoaladin/RAG",
            pull_request_number=89,
            expected_head=HEAD_SHA,
            config_path=CONFIG_PATH,
            runner=runner,
        )

        self.assertFalse(result.decision.approved)
        self.assertEqual(result.decision.reason, "head_changed_during_evaluation")

    def test_final_review_snapshot_revokes_same_head_approval(self) -> None:
        runner = RecordingRunner(
            review_snapshots=[[review()], [review(body="")]],
        )

        result = github_review.check_github_review(
            repository="cyranoaladin/RAG",
            pull_request_number=89,
            expected_head=HEAD_SHA,
            config_path=CONFIG_PATH,
            runner=runner,
        )

        self.assertFalse(result.decision.approved)
        self.assertEqual(result.decision.reason, "current_head_approval_missing")

    def test_final_permission_snapshot_revokes_same_head_approval(self) -> None:
        runner = RecordingRunner(
            permission_snapshots=[
                {"permission": "write", "role_name": "write"},
                {"permission": "read", "role_name": "read"},
            ],
        )

        result = github_review.check_github_review(
            repository="cyranoaladin/RAG",
            pull_request_number=89,
            expected_head=HEAD_SHA,
            config_path=CONFIG_PATH,
            runner=runner,
        )

        self.assertFalse(result.decision.approved)
        self.assertEqual(result.decision.reason, "reviewer_permission_insufficient")


class CliTests(unittest.TestCase):
    def test_check_returns_three_until_approved_and_prints_json(self) -> None:
        runner = RecordingRunner(review_pages={1: []})
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = github_review.main(
                [
                    "--repository",
                    "cyranoaladin/RAG",
                    "--pull-request",
                    "89",
                    "--expected-head",
                    HEAD_SHA,
                    "--check",
                ],
                runner=runner,
                config_path=CONFIG_PATH,
            )

        self.assertEqual(status, 3)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["decision"]["approved"])
        self.assertEqual(payload["challenges"]["abenrhouma"], expected_challenge())

    def test_publish_mode_is_not_exposed(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            github_review._parser().parse_args(
                [
                    "--repository",
                    "cyranoaladin/RAG",
                    "--pull-request",
                    "89",
                    "--expected-head",
                    HEAD_SHA,
                    "--check",
                    "--publish",
                ]
            )

    def test_run_gh_api_rejects_timeout_and_non_gh_commands(self) -> None:
        with self.assertRaises(ValueError):
            github_review.run_gh_api(["curl", "https://example.invalid"])
        for mutation in (
            ["--method", "POST"],
            ["-X", "PATCH"],
            ["--input", "-"],
            ["-f", "state=success"],
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                github_review.run_gh_api(
                    ["gh", "api", "repos/cyranoaladin/RAG", *mutation]
                )

        with mock.patch.object(
            github_review.subprocess,
            "run",
            side_effect=github_review.subprocess.TimeoutExpired(
                cmd=["gh", "api"], timeout=30
            ),
        ):
            with self.assertRaises(github_review.GitHubAdapterError):
                github_review.run_gh_api(["gh", "api", "repos/o/r"])


if __name__ == "__main__":
    raise SystemExit(unittest.main())
