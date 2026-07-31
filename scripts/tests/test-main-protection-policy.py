#!/usr/bin/env python3
"""Tests du contrat de protection de la branche ``main``."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "github" / "main_protection.py"
POLICY_PATH = REPO_ROOT / "scripts" / "github" / "main-protection-policy.json"

SPEC = importlib.util.spec_from_file_location("main_protection", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Impossible de charger {MODULE_PATH}")
main_protection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(main_protection)


CONTEXTS = [
    "packages/contracts",
    "services/rag-pedago",
    "services/rag-engine",
    "services/cockpit",
    "governance locks guard",
    "repository controls",
]
_ABSENT = object()


def expected_policy() -> dict[str, object]:
    return {
        "required_status_checks": {"strict": True, "contexts": list(CONTEXTS)},
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": False,
            "require_code_owner_reviews": False,
            "required_approving_review_count": 0,
            "require_last_push_approval": False,
        },
        "restrictions": None,
        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "block_creations": False,
        "required_conversation_resolution": True,
        "lock_branch": False,
        "allow_fork_syncing": False,
    }


def remote_policy(
    *,
    contexts: list[str] | None = None,
    bypass: object = _ABSENT,
) -> dict[str, object]:
    policy = expected_policy()
    checks = policy["required_status_checks"]
    assert isinstance(checks, dict)
    reviews = policy["required_pull_request_reviews"]
    assert isinstance(reviews, dict)
    remote_reviews = {
        **reviews,
        "url": "https://api.github.invalid/protection/reviews",
    }
    if bypass is not _ABSENT:
        remote_reviews["bypass_pull_request_allowances"] = bypass
    return {
        "required_status_checks": {
            "strict": checks["strict"],
            "contexts": list(contexts if contexts is not None else CONTEXTS),
            "checks": [],
            "url": "https://api.github.invalid/protection/required_status_checks",
        },
        "enforce_admins": {"enabled": policy["enforce_admins"]},
        "required_pull_request_reviews": remote_reviews,
        "restrictions": None,
        "required_linear_history": {
            "enabled": policy["required_linear_history"]
        },
        "allow_force_pushes": {"enabled": policy["allow_force_pushes"]},
        "allow_deletions": {"enabled": policy["allow_deletions"]},
        "block_creations": {"enabled": policy["block_creations"]},
        "required_conversation_resolution": {
            "enabled": policy["required_conversation_resolution"]
        },
        "lock_branch": {"enabled": policy["lock_branch"]},
        "allow_fork_syncing": {"enabled": policy["allow_fork_syncing"]},
        "url": "https://api.github.invalid/protection",
    }


class RecordingRunner:
    def __init__(
        self,
        *,
        sha: str = "a" * 40,
        remote: dict[str, object] | None = None,
        malformed_ref: dict[str, object] | None = None,
    ) -> None:
        self.sha = sha
        self.remote = remote if remote is not None else remote_policy()
        self.malformed_ref = malformed_ref
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(
        self, argv: list[str], *, input_data: str | None = None
    ) -> dict[str, object] | str:
        self.calls.append((list(argv), input_data))
        if argv[:2] != ["gh", "api"]:
            raise AssertionError(f"Commande inattendue: {argv}")
        if "--method" in argv:
            expected_endpoint = "repos/owner/repo/branches/main/protection"
            if argv[2:5] != ["--method", "PUT", expected_endpoint]:
                raise AssertionError(f"Mutation inattendue: {argv}")
            return {"url": "https://api.github.invalid/protection"}
        endpoint = argv[2]
        if endpoint.endswith("/git/ref/heads/main"):
            if self.malformed_ref is not None:
                return self.malformed_ref
            return {"object": {"sha": self.sha}}
        if endpoint.endswith("/branches/main/protection"):
            return self.remote
        raise AssertionError(f"Endpoint inattendu: {endpoint}")


class PolicyContractTests(unittest.TestCase):
    def test_load_policy_returns_the_exact_unique_contexts(self) -> None:
        policy = main_protection.load_policy(POLICY_PATH)
        self.assertEqual(policy, expected_policy())
        checks = policy["required_status_checks"]
        self.assertIsInstance(checks, dict)
        assert isinstance(checks, dict)
        self.assertEqual(checks["contexts"], CONTEXTS)
        self.assertEqual(len(checks["contexts"]), len(set(checks["contexts"])))

    def test_policy_enables_all_required_guards(self) -> None:
        policy = main_protection.load_policy(POLICY_PATH)
        checks = policy["required_status_checks"]
        assert isinstance(checks, dict)
        self.assertIs(checks["strict"], True)
        for key in (
            "enforce_admins",
            "required_linear_history",
            "required_conversation_resolution",
        ):
            self.assertIs(policy[key], True)

    def test_policy_disables_destructive_branch_operations(self) -> None:
        policy = main_protection.load_policy(POLICY_PATH)
        for key in ("allow_force_pushes", "allow_deletions", "lock_branch"):
            self.assertIs(policy[key], False)

    def test_policy_requires_prs_without_blocking_solo_approvals(self) -> None:
        policy = main_protection.load_policy(POLICY_PATH)
        reviews = policy["required_pull_request_reviews"]
        self.assertEqual(
            reviews,
            {
                "dismiss_stale_reviews": False,
                "require_code_owner_reviews": False,
                "required_approving_review_count": 0,
                "require_last_push_approval": False,
            },
        )

    def test_load_policy_refuses_unknown_keys_and_duplicate_contexts(self) -> None:
        cases = []
        unknown = expected_policy()
        unknown["unknown"] = False
        cases.append(unknown)
        unknown_nested = expected_policy()
        checks = unknown_nested["required_status_checks"]
        assert isinstance(checks, dict)
        checks["unknown"] = False
        cases.append(unknown_nested)
        duplicate = expected_policy()
        duplicate_checks = duplicate["required_status_checks"]
        assert isinstance(duplicate_checks, dict)
        duplicate_checks["contexts"] = CONTEXTS + [CONTEXTS[0]]
        cases.append(duplicate)

        for document in cases:
            with self.subTest(document=document):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "policy.json"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        main_protection.load_policy(path)

    def test_load_policy_refuses_invalid_governed_shapes(self) -> None:
        invalid_documents: list[object] = [[], {"enforce_admins": 1}]
        invalid_checks = expected_policy()
        invalid_checks["required_status_checks"] = {
            "strict": True,
            "contexts": "packages/contracts",
        }
        invalid_documents.append(invalid_checks)

        for document in invalid_documents:
            with self.subTest(document=document):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "policy.json"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises((TypeError, ValueError)):
                        main_protection.load_policy(path)

    def test_normalize_remote_unwraps_enabled_values_and_sorts_contexts(self) -> None:
        reordered = list(reversed(CONTEXTS))
        normalized = main_protection.normalize_remote(remote_policy(contexts=reordered))
        expected = main_protection.normalize_policy(expected_policy())
        self.assertEqual(normalized, expected)
        checks = normalized["required_status_checks"]
        assert isinstance(checks, dict)
        self.assertEqual(checks["contexts"], sorted(CONTEXTS))

    def test_normalize_remote_accepts_absent_or_empty_bypass_allowances(self) -> None:
        expected = main_protection.normalize_policy(expected_policy())
        self.assertEqual(main_protection.normalize_remote(remote_policy()), expected)
        self.assertEqual(
            main_protection.normalize_remote(remote_policy(bypass=None)),
            expected,
        )
        actor_keys = ("users", "teams", "apps")
        for mask in range(1 << len(actor_keys)):
            empty_bypass: dict[str, list[object]] = {
                key: []
                for index, key in enumerate(actor_keys)
                if mask & (1 << index)
            }
            with self.subTest(keys=sorted(empty_bypass)):
                self.assertEqual(
                    main_protection.normalize_remote(
                        remote_policy(bypass=empty_bypass)
                    ),
                    expected,
                )

    def test_verify_policy_rejects_each_non_empty_bypass_allowance(self) -> None:
        bypass_cases = {
            "user": (
                {
                    "users": [{"login": "alice"}],
                },
                "alice",
            ),
            "team": (
                {
                    "teams": [{"slug": "release-team"}],
                },
                "release-team",
            ),
            "app": (
                {
                    "apps": [{"slug": "release-app"}],
                },
                "release-app",
            ),
        }
        for label, (bypass, identity) in bypass_cases.items():
            with self.subTest(label=label):
                with self.assertRaises(main_protection.PolicyDrift) as caught:
                    main_protection.verify_policy(
                        expected_policy(), remote_policy(bypass=bypass)
                    )
                self.assertIn(identity, str(caught.exception))

    def test_normalize_remote_rejects_malformed_bypass_allowances(self) -> None:
        malformed = [
            [],
            {"users": [], "teams": [], "apps": [], "unknown": []},
            {"users": "alice", "teams": [], "apps": []},
            {"users": [{}], "teams": [], "apps": []},
        ]
        for bypass in malformed:
            with self.subTest(bypass=bypass):
                with self.assertRaises((TypeError, ValueError)):
                    main_protection.normalize_remote(remote_policy(bypass=bypass))

    def test_normalize_remote_refuses_malformed_or_missing_governed_fields(self) -> None:
        malformed = remote_policy()
        malformed["enforce_admins"] = {"enabled": "true"}
        missing = remote_policy()
        del missing["allow_force_pushes"]
        for document in (malformed, missing, "not a mapping"):
            with self.subTest(document=document):
                with self.assertRaises((TypeError, ValueError)):
                    main_protection.normalize_remote(document)

    def test_missing_remote_restrictions_is_semantically_null(self) -> None:
        remote = remote_policy()
        del remote["restrictions"]
        self.assertEqual(
            main_protection.normalize_remote(remote),
            main_protection.normalize_policy(expected_policy()),
        )
        main_protection.verify_policy(expected_policy(), remote)

    def test_non_null_remote_restrictions_remains_policy_drift(self) -> None:
        remote = remote_policy()
        remote["restrictions"] = {"users": [], "teams": [], "apps": []}
        with self.assertRaises(main_protection.PolicyDrift) as caught:
            main_protection.verify_policy(expected_policy(), remote)
        self.assertIn('"restrictions": null', str(caught.exception))
        self.assertIn('"restrictions": {', str(caught.exception))

    def test_verify_policy_accepts_semantically_equal_reordered_json(self) -> None:
        reordered = expected_policy()
        checks = reordered["required_status_checks"]
        assert isinstance(checks, dict)
        checks["contexts"] = list(reversed(CONTEXTS))
        main_protection.verify_policy(reordered, remote_policy())

    def test_verify_policy_reports_deterministic_context_drift(self) -> None:
        remote = remote_policy(contexts=CONTEXTS[:-1])
        with self.assertRaises(main_protection.PolicyDrift) as first:
            main_protection.verify_policy(expected_policy(), remote)
        with self.assertRaises(main_protection.PolicyDrift) as second:
            main_protection.verify_policy(expected_policy(), remote)
        self.assertEqual(str(first.exception), str(second.exception))
        self.assertIn('"repository controls"', str(first.exception))
        self.assertIn("--- expected", str(first.exception))
        self.assertIn("+++ remote", str(first.exception))

    def test_verify_policy_reports_active_force_push_drift(self) -> None:
        remote = remote_policy()
        remote["allow_force_pushes"] = {"enabled": True}
        with self.assertRaises(main_protection.PolicyDrift) as caught:
            main_protection.verify_policy(expected_policy(), remote)
        self.assertIn('"allow_force_pushes": false', str(caught.exception))
        self.assertIn('"allow_force_pushes": true', str(caught.exception))


class ApplyPolicyTests(unittest.TestCase):
    def test_apply_does_not_mutate_when_remote_sha_differs(self) -> None:
        runner = RecordingRunner(sha="b" * 40)
        with self.assertRaises(main_protection.PolicyDrift):
            main_protection.apply_policy(
                "owner/repo",
                "a" * 40,
                "owner/repo@" + "a" * 40,
                POLICY_PATH,
                runner,
            )
        self.assertEqual(len(runner.calls), 1)
        self.assertNotIn("--method", runner.calls[0][0])

    def test_apply_refuses_malformed_ref_without_mutation(self) -> None:
        runner = RecordingRunner(malformed_ref={"object": {"sha": 42}})
        with self.assertRaises((TypeError, ValueError)):
            main_protection.apply_policy(
                "owner/repo",
                "a" * 40,
                "owner/repo@" + "a" * 40,
                POLICY_PATH,
                runner,
            )
        self.assertEqual(len(runner.calls), 1)
        self.assertNotIn("--method", runner.calls[0][0])

    def test_apply_refuses_absent_or_false_confirmation_without_put(self) -> None:
        for confirmation in (None, "", "owner/repo@" + "b" * 40):
            runner = RecordingRunner()
            with self.subTest(confirmation=confirmation):
                with self.assertRaises(PermissionError):
                    main_protection.apply_policy(
                        "owner/repo",
                        "a" * 40,
                        confirmation,
                        POLICY_PATH,
                        runner,
                    )
                self.assertEqual(len(runner.calls), 1)
                self.assertNotIn("--method", runner.calls[0][0])

    def test_apply_with_sha_and_confirmation_puts_once_then_verifies(self) -> None:
        runner = RecordingRunner()
        main_protection.apply_policy(
            "owner/repo",
            "a" * 40,
            "owner/repo@" + "a" * 40,
            POLICY_PATH,
            runner,
        )
        header = "X-GitHub-Api-Version: 2026-03-10"
        expected_calls = [
            (
                [
                    "gh",
                    "api",
                    "repos/owner/repo/git/ref/heads/main",
                    "-H",
                    header,
                ],
                None,
            ),
            (
                [
                    "gh",
                    "api",
                    "--method",
                    "PUT",
                    "repos/owner/repo/branches/main/protection",
                    "-H",
                    header,
                    "--input",
                    "-",
                ],
                json.dumps(expected_policy(), ensure_ascii=False),
            ),
            (
                [
                    "gh",
                    "api",
                    "repos/owner/repo/branches/main/protection",
                    "-H",
                    header,
                ],
                None,
            ),
        ]
        self.assertEqual(runner.calls, expected_calls)
        put_calls = [call for call in runner.calls if "--method" in call[0]]
        self.assertEqual(len(put_calls), 1)
        put_argv, put_input = put_calls[0]
        self.assertEqual(put_argv[put_argv.index("--method") + 1], "PUT")
        self.assertEqual(put_argv[put_argv.index("--input") + 1], "-")
        self.assertEqual(json.loads(put_input or ""), expected_policy())
        self.assertTrue(
            runner.calls[-1][0][2].endswith("/branches/main/protection")
        )

    def test_every_api_call_uses_the_pinned_github_header(self) -> None:
        runner = RecordingRunner()
        main_protection.apply_policy(
            "owner/repo",
            "a" * 40,
            "owner/repo@" + "a" * 40,
            POLICY_PATH,
            runner,
        )
        expected_header = "X-GitHub-Api-Version: 2026-03-10"
        for argv, _ in runner.calls:
            self.assertIn("-H", argv)
            self.assertEqual(argv[argv.index("-H") + 1], expected_header)


class CliTests(unittest.TestCase):
    def test_check_only_reads_protection_and_verifies(self) -> None:
        runner = RecordingRunner()
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main_protection.main(
                ["--repository", "owner/repo", "--check"], runner=runner
            )
        self.assertEqual(status, 0)
        self.assertIn("OK: main protection matches policy", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(len(runner.calls), 1)
        self.assertTrue(
            runner.calls[0][0][2].endswith("/branches/main/protection")
        )
        self.assertNotIn("--method", runner.calls[0][0])

    def test_check_accepts_github_response_without_restrictions(self) -> None:
        remote = remote_policy()
        del remote["restrictions"]
        runner = RecordingRunner(remote=remote)
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main_protection.main(
                ["--repository", "owner/repo", "--check"], runner=runner
            )
        self.assertEqual(status, 0)
        self.assertIn("OK: main protection matches policy", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(len(runner.calls), 1)
        self.assertNotIn("--method", runner.calls[0][0])

    def test_check_fails_closed_when_main_is_not_protected(self) -> None:
        def missing_protection(
            argv: list[str], *, input_data: str | None = None
        ) -> dict[str, object] | str:
            del argv, input_data
            raise main_protection.GitHubAPIError(
                "gh api failed (1): Branch not protected (HTTP 404)",
                returncode=1,
            )

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main_protection.main(
                ["--repository", "owner/repo", "--check"],
                runner=missing_protection,
            )
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("main is not protected", stderr.getvalue())

    def test_check_does_not_misclassify_repository_not_found(self) -> None:
        def repository_not_found(
            argv: list[str], *, input_data: str | None = None
        ) -> dict[str, object] | str:
            del argv, input_data
            raise main_protection.GitHubAPIError(
                "gh api failed (1): Not Found (HTTP 404)", returncode=1
            )

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main_protection.main(
                ["--repository", "owner/missing", "--check"],
                runner=repository_not_found,
            )
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("main is not protected", stderr.getvalue())
        self.assertIn("Not Found (HTTP 404)", stderr.getvalue())

    def test_check_does_not_misclassify_access_error(self) -> None:
        def access_error(
            argv: list[str], *, input_data: str | None = None
        ) -> dict[str, object] | str:
            del argv, input_data
            raise main_protection.GitHubAPIError(
                "gh api failed (1): Resource not accessible by integration",
                returncode=1,
            )

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main_protection.main(
                ["--repository", "owner/repo", "--check"],
                runner=access_error,
            )
        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("main is not protected", stderr.getvalue())
        self.assertIn("Resource not accessible", stderr.getvalue())

    def test_cli_refuses_invalid_modes_and_missing_apply_sha(self) -> None:
        invalid_argv = [
            ["--repository", "owner/repo"],
            ["--repository", "owner/repo", "--check", "--apply"],
            ["--repository", "owner/repo", "--apply"],
            [
                "--repository",
                "owner/repo",
                "--check",
                "--expected-main-sha",
                "a" * 40,
            ],
        ]
        for argv in invalid_argv:
            stdout = StringIO()
            stderr = StringIO()
            with self.subTest(argv=argv), redirect_stdout(stdout), redirect_stderr(
                stderr
            ), self.assertRaises(SystemExit):
                main_protection.main(argv, runner=RecordingRunner())
            self.assertEqual(stdout.getvalue(), "")
            self.assertNotEqual(stderr.getvalue(), "")

    def test_cli_refuses_invalid_repository_and_sha(self) -> None:
        invalid_argv = [
            ["--repository", "owner/repo/extra", "--check"],
            [
                "--repository",
                "owner/repo",
                "--apply",
                "--expected-main-sha",
                "not-a-sha",
            ],
        ]
        for argv in invalid_argv:
            stdout = StringIO()
            stderr = StringIO()
            with self.subTest(argv=argv), redirect_stdout(stdout), redirect_stderr(
                stderr
            ), self.assertRaises(SystemExit):
                main_protection.main(argv, runner=RecordingRunner())
            self.assertEqual(stdout.getvalue(), "")
            self.assertNotEqual(stderr.getvalue(), "")


class GitHubAdapterTests(unittest.TestCase):
    def test_run_gh_api_passes_the_bounded_timeout(self) -> None:
        completed = subprocess_completed(stdout='{"ok": true}')
        argv = ["gh", "api", "repos/owner/repo"]
        with mock.patch.object(
            main_protection.subprocess, "run", return_value=completed
        ) as run:
            self.assertEqual(main_protection.run_gh_api(argv), {"ok": True})
        run.assert_called_once_with(
            argv,
            input=None,
            text=True,
            capture_output=True,
            check=False,
            timeout=main_protection.GH_API_TIMEOUT_SECONDS,
        )

    def test_run_gh_api_fails_without_retry_on_timeout(self) -> None:
        argv = [
            "gh",
            "api",
            "--method",
            "PUT",
            "repos/owner/repo/branches/main/protection",
        ]
        timeout = main_protection.subprocess.TimeoutExpired(argv, 30)
        with mock.patch.object(
            main_protection.subprocess, "run", side_effect=timeout
        ) as run, self.assertRaises(main_protection.GitHubAPIError) as caught:
            main_protection.run_gh_api(argv, input_data="{}")
        self.assertEqual(run.call_count, 1)
        self.assertIn("timed out", str(caught.exception))
        self.assertIn("--check", str(caught.exception))
        self.assertIn("before any new attempt", str(caught.exception))

    def test_run_gh_api_rejects_nonzero_and_malformed_json(self) -> None:
        cases = [
            (
                subprocess_completed(returncode=1, stderr="forbidden"),
                "gh api failed (1): forbidden",
            ),
            (subprocess_completed(stdout="not-json"), "malformed JSON"),
        ]
        for completed, message in cases:
            with self.subTest(message=message), mock.patch.object(
                main_protection.subprocess, "run", return_value=completed
            ):
                with self.assertRaises(main_protection.GitHubAPIError) as caught:
                    main_protection.run_gh_api(
                        ["gh", "api", "repos/owner/repo"]
                    )
                self.assertIn(message, str(caught.exception))


def subprocess_completed(
    *, returncode: int = 0, stdout: str = "{}", stderr: str = ""
) -> object:
    return main_protection.subprocess.CompletedProcess(
        ["gh", "api"], returncode, stdout=stdout, stderr=stderr
    )


if __name__ == "__main__":
    unittest.main()
