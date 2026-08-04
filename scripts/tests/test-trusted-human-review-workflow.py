#!/usr/bin/env python3
"""Contrat statique du workflow privilégié de revue humaine LOT41V."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "trusted-human-review.yml"
PINNED_ACTION = re.compile(r"actions/[a-z0-9-]+@[0-9a-f]{40}\Z")


class TrustedHumanReviewWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW_PATH.read_text(encoding="utf-8")
        document = yaml.safe_load(cls.source)
        if not isinstance(document, dict):
            raise AssertionError("workflow must be a YAML object")
        cls.workflow = document

    def test_only_trusted_events_are_enabled(self) -> None:
        events = self.workflow.get("on")
        self.assertIsInstance(events, dict)
        assert isinstance(events, dict)
        self.assertEqual(
            set(events),
            {
                "pull_request_target",
                "issue_comment",
            },
        )
        self.assertEqual(
            events["pull_request_target"]["types"],
            ["opened", "reopened", "synchronize", "ready_for_review", "edited"],
        )
        self.assertEqual(events["pull_request_target"]["branches"], ["main"])
        self.assertEqual(events["issue_comment"]["types"], ["created"])

    def test_permissions_are_minimal_and_explicit(self) -> None:
        self.assertEqual(
            self.workflow.get("permissions"),
            {
                "contents": "read",
                "pull-requests": "read",
                "issues": "write",
                "statuses": "write",
            },
        )

    def test_job_checks_out_only_main_without_credentials(self) -> None:
        jobs = self.workflow.get("jobs")
        self.assertIsInstance(jobs, dict)
        assert isinstance(jobs, dict)
        self.assertEqual(set(jobs), {"evaluate"})
        job = jobs["evaluate"]
        self.assertNotEqual(job.get("name"), "trusted-human-review")
        self.assertEqual(job.get("timeout-minutes"), 5)
        self.assertEqual(
            job.get("if"),
            "${{ github.event_name != 'issue_comment' || ("
            "github.event.issue.pull_request != null && "
            "github.event.comment.body == '/nexus-trusted-review') }}",
        )
        self.assertNotIn("continue-on-error", json.dumps(job))

        steps = job.get("steps")
        self.assertIsInstance(steps, list)
        checkout_steps = [
            step
            for step in steps
            if isinstance(step, dict)
            and isinstance(step.get("uses"), str)
            and step["uses"].startswith("actions/checkout@")
        ]
        self.assertEqual(len(checkout_steps), 1)
        checkout = checkout_steps[0]
        self.assertEqual(checkout.get("with", {}).get("ref"), "refs/heads/main")
        self.assertIs(checkout.get("with", {}).get("persist-credentials"), False)

        for step in steps:
            if isinstance(step, dict) and "uses" in step:
                self.assertRegex(step["uses"], PINNED_ACTION)

    def test_workflow_never_interprets_untrusted_pr_text_or_secrets(self) -> None:
        forbidden = (
            "secrets.",
            "github.event.pull_request.head.ref",
            "github.event.pull_request.title",
            "github.event.pull_request.body",
            "github.event.pull_request.user",
            "github.head_ref",
            "refs/pull/",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.source)

        for run in re.findall(r"(?m)^\s+run:\s*(.*)$", self.source):
            self.assertNotIn("${{ github.event", run)
            self.assertNotIn("${{ inputs", run)

    def test_adapter_receives_numeric_pr_and_exact_event_head_via_env(self) -> None:
        job = self.workflow["jobs"]["evaluate"]
        steps = job["steps"]
        publish = next(
            step
            for step in steps
            if isinstance(step, dict)
            and "trusted_human_review_github.py" in str(step.get("run", ""))
        )
        self.assertEqual(publish["env"]["GH_TOKEN"], "${{ github.token }}")
        self.assertEqual(
            publish["env"]["PR_NUMBER"],
            "${{ github.event.pull_request.number || "
            "github.event.issue.number }}",
        )
        self.assertEqual(
            publish["env"]["EXPECTED_HEAD"],
            "${{ github.event.pull_request.head.sha }}",
        )
        run = publish["run"]
        self.assertIn('[[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]', run)
        self.assertIn('if [[ -z "$EXPECTED_HEAD" ]]', run)
        self.assertIn('pulls/$PR_NUMBER', run)
        self.assertIn("[.base.ref, .head.sha] | @tsv", run)
        self.assertIn('[[ "$OBSERVED_BASE_REF" == "main" ]]', run)
        self.assertIn("PR hors main ignorée", run)
        self.assertIn('[[ "$EXPECTED_HEAD" =~ ^[0-9a-f]{40}$ ]]', run)
        self.assertIn("--publish", run)
        self.assertIn('"$PR_NUMBER"', run)
        self.assertIn('"$EXPECTED_HEAD"', run)

    def test_concurrency_is_bound_to_the_pull_request(self) -> None:
        concurrency = self.workflow.get("concurrency")
        self.assertEqual(
            concurrency,
            {
                "group": (
                    "trusted-human-review-${{ "
                    "github.event.pull_request.number || "
                    "github.event.issue.number }}"
                ),
                "cancel-in-progress": True,
            },
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())
