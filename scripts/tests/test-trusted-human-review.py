#!/usr/bin/env python3
"""Tests du challenge et de la décision de revue humaine fiable."""

from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "github" / "trusted_human_review.py"
CONFIG_PATH = REPO_ROOT / "scripts" / "github" / "trusted-reviewers.json"

SPEC = importlib.util.spec_from_file_location("trusted_human_review", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Impossible de charger {MODULE_PATH}")
trusted_review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = trusted_review
SPEC.loader.exec_module(trusted_review)


def expected_config() -> dict[str, object]:
    return {
        "protocol": "NEXUS-TRUSTED-REVIEW-V1",
        "repository": "cyranoaladin/RAG",
        "base_ref": "main",
        "reviewers": ["abenrhouma"],
    }


def valid_payload() -> dict[str, object]:
    return {
        "repository": "cyranoaladin/RAG",
        "pull_request": 89,
        "base_ref": "main",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "author": "cyranoaladin",
        "reviewer": "abenrhouma",
        "protocol": "NEXUS-TRUSTED-REVIEW-V1",
    }


def valid_pull_request() -> dict[str, object]:
    return {
        "number": 89,
        "state": "open",
        "draft": False,
        "base": {"ref": "main", "sha": "a" * 40},
        "head": {
            "sha": "b" * 40,
            "repo": {"full_name": "cyranoaladin/RAG"},
        },
        "user": {"login": "cyranoaladin"},
    }


def approved_review(
    *,
    body: str | None = None,
    commit_id: str | None = None,
    state: str = "APPROVED",
    review_id: int = 1001,
    submitted_at: str = "2026-08-04T00:00:00Z",
    reviewer: str = "abenrhouma",
) -> dict[str, object]:
    challenge = trusted_review.build_challenge(valid_payload())
    return {
        "id": review_id,
        "state": state,
        "body": challenge if body is None else body,
        "commit_id": "b" * 40 if commit_id is None else commit_id,
        "submitted_at": submitted_at,
        "user": {"login": reviewer},
    }


def valid_permissions() -> dict[str, object]:
    return {
        "abenrhouma": {"permission": "write", "role_name": "write"},
    }


class TrustedReviewerConfigTests(unittest.TestCase):
    def test_versioned_config_is_exact(self) -> None:
        config = trusted_review.load_config(CONFIG_PATH)

        self.assertEqual(config.protocol, "NEXUS-TRUSTED-REVIEW-V1")
        self.assertEqual(config.repository, "cyranoaladin/RAG")
        self.assertEqual(config.base_ref, "main")
        self.assertEqual(config.reviewers, ("abenrhouma",))

    def test_config_refuses_unknown_keys_and_invalid_values(self) -> None:
        cases: list[object] = []

        unknown = expected_config()
        unknown["unknown"] = True
        cases.append(unknown)

        duplicate = expected_config()
        duplicate["reviewers"] = ["abenrhouma", "abenrhouma"]
        cases.append(duplicate)

        empty_reviewer = expected_config()
        empty_reviewer["reviewers"] = [""]
        cases.append(empty_reviewer)

        wrong_repository = expected_config()
        wrong_repository["repository"] = "someone/else"
        cases.append(wrong_repository)

        wrong_protocol = expected_config()
        wrong_protocol["protocol"] = "NEXUS-TRUSTED-REVIEW-V2"
        cases.append(wrong_protocol)

        wrong_base = expected_config()
        wrong_base["base_ref"] = "develop"
        cases.append(wrong_base)

        cases.extend(([], {"protocol": 1}))

        for document in cases:
            with self.subTest(document=document):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "reviewers.json"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises((TypeError, ValueError)):
                        trusted_review.load_config(path)


class CanonicalChallengeTests(unittest.TestCase):
    def test_challenge_uses_canonical_json_and_sha256(self) -> None:
        payload = valid_payload()
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected = "NEXUS-TRUSTED-REVIEW-V1:" + sha256(encoded).hexdigest()

        self.assertEqual(trusted_review.build_challenge(payload), expected)

    def test_challenge_is_independent_of_input_key_order(self) -> None:
        payload = valid_payload()
        reversed_payload = dict(reversed(tuple(payload.items())))

        self.assertEqual(
            trusted_review.build_challenge(payload),
            trusted_review.build_challenge(reversed_payload),
        )

    def test_expected_challenges_are_derived_from_validated_pr_dimensions(self) -> None:
        config = trusted_review.load_config(CONFIG_PATH)

        self.assertEqual(
            trusted_review.build_expected_challenges(
                valid_pull_request(), config
            ),
            {"abenrhouma": trusted_review.build_challenge(valid_payload())},
        )

    def test_challenge_refuses_unknown_missing_or_malformed_fields(self) -> None:
        cases: list[dict[str, object]] = []

        unknown = valid_payload()
        unknown["unknown"] = "value"
        cases.append(unknown)

        missing = valid_payload()
        del missing["head_sha"]
        cases.append(missing)

        uppercase_sha = valid_payload()
        uppercase_sha["head_sha"] = "B" * 40
        cases.append(uppercase_sha)

        short_sha = valid_payload()
        short_sha["base_sha"] = "a" * 39
        cases.append(short_sha)

        zero_pr = valid_payload()
        zero_pr["pull_request"] = 0
        cases.append(zero_pr)

        bool_pr = valid_payload()
        bool_pr["pull_request"] = True
        cases.append(bool_pr)

        empty_author = valid_payload()
        empty_author["author"] = ""
        cases.append(empty_author)

        wrong_repository = valid_payload()
        wrong_repository["repository"] = "someone/else"
        cases.append(wrong_repository)

        wrong_base = valid_payload()
        wrong_base["base_ref"] = "develop"
        cases.append(wrong_base)

        wrong_protocol = valid_payload()
        wrong_protocol["protocol"] = "NEXUS-TRUSTED-REVIEW-V2"
        cases.append(wrong_protocol)

        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises((TypeError, ValueError)):
                    trusted_review.build_challenge(payload)


class TrustedReviewDecisionTests(unittest.TestCase):
    def evaluate(
        self,
        *,
        pull_request: object | None = None,
        reviews: object | None = None,
        permissions: object | None = None,
        reviews_complete: bool = True,
    ) -> object:
        return trusted_review.evaluate_trusted_review(
            pull_request=(
                valid_pull_request() if pull_request is None else pull_request
            ),
            reviews=[approved_review()] if reviews is None else reviews,
            permissions=(
                valid_permissions() if permissions is None else permissions
            ),
            config=trusted_review.load_config(CONFIG_PATH),
            reviews_complete=reviews_complete,
        )

    def test_exact_approval_on_current_head_is_authoritative(self) -> None:
        decision = self.evaluate()

        self.assertTrue(decision.approved)
        self.assertEqual(decision.reason, "approved")
        self.assertEqual(decision.repository, "cyranoaladin/RAG")
        self.assertEqual(decision.pull_request, 89)
        self.assertEqual(decision.base_sha, "a" * 40)
        self.assertEqual(decision.head_sha, "b" * 40)
        self.assertEqual(decision.reviewer, "abenrhouma")
        self.assertEqual(decision.review_id, 1001)
        self.assertEqual(decision.submitted_at, "2026-08-04T00:00:00Z")
        self.assertEqual(
            decision.challenge,
            trusted_review.build_challenge(valid_payload()),
        )

    def test_closed_draft_wrong_base_and_fork_are_rejected(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []

        closed = valid_pull_request()
        closed["state"] = "closed"
        cases.append(("pull_request_not_open", closed))

        draft = valid_pull_request()
        draft["draft"] = True
        cases.append(("pull_request_is_draft", draft))

        wrong_base = valid_pull_request()
        wrong_base["base"] = {"ref": "develop", "sha": "a" * 40}
        cases.append(("base_ref_mismatch", wrong_base))

        fork = valid_pull_request()
        fork["head"] = {
            "sha": "b" * 40,
            "repo": {"full_name": "someone/RAG"},
        }
        cases.append(("head_repository_mismatch", fork))

        for reason, pull_request in cases:
            with self.subTest(reason=reason):
                decision = self.evaluate(pull_request=pull_request)
                self.assertFalse(decision.approved)
                self.assertEqual(decision.reason, reason)

    def test_self_review_and_read_only_reviewer_are_rejected(self) -> None:
        self_authored = valid_pull_request()
        self_authored["user"] = {"login": "abenrhouma"}

        decision = self.evaluate(pull_request=self_authored)
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "reviewer_is_author")

        decision = self.evaluate(
            permissions={
                "abenrhouma": {"permission": "read", "role_name": "read"}
            }
        )
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "reviewer_permission_insufficient")

    def test_stale_head_and_wrong_challenge_are_rejected(self) -> None:
        stale = self.evaluate(reviews=[approved_review(commit_id="c" * 40)])
        self.assertFalse(stale.approved)
        self.assertEqual(stale.reason, "current_head_approval_missing")

        wrong_challenge = self.evaluate(
            reviews=[approved_review(body="NEXUS-TRUSTED-REVIEW-V1:" + "0" * 64)]
        )
        self.assertFalse(wrong_challenge.approved)
        self.assertEqual(wrong_challenge.reason, "current_head_approval_missing")

        embedded = self.evaluate(
            reviews=[
                approved_review(
                    body=(
                        "prefix "
                        + trusted_review.build_challenge(valid_payload())
                        + " suffix"
                    )
                )
            ]
        )
        self.assertFalse(embedded.approved)
        self.assertEqual(embedded.reason, "current_head_approval_missing")

    def test_later_changes_requested_or_dismissal_revokes_approval(self) -> None:
        for state in ("CHANGES_REQUESTED", "DISMISSED"):
            with self.subTest(state=state):
                decision = self.evaluate(
                    reviews=[
                        approved_review(),
                        approved_review(
                            state=state,
                            body="",
                            review_id=1002,
                            submitted_at="2026-08-04T00:01:00Z",
                        ),
                    ]
                )
                self.assertFalse(decision.approved)
                self.assertEqual(decision.reason, "approval_revoked")

    def test_duplicate_ids_and_incomplete_pages_fail_closed(self) -> None:
        duplicate = self.evaluate(
            reviews=[approved_review(), approved_review()]
        )
        self.assertFalse(duplicate.approved)
        self.assertEqual(duplicate.reason, "duplicate_review_id")

        incomplete = self.evaluate(reviews_complete=False)
        self.assertFalse(incomplete.approved)
        self.assertEqual(incomplete.reason, "reviews_incomplete")

    def test_malformed_inputs_are_rejected_without_approval(self) -> None:
        cases = (
            {"number": 89},
            [],
            {**valid_pull_request(), "number": True},
        )
        for pull_request in cases:
            with self.subTest(pull_request=pull_request):
                with self.assertRaises((TypeError, ValueError)):
                    self.evaluate(pull_request=pull_request)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
