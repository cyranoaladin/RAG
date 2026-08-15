#!/usr/bin/env python3
"""Contrat statique du workflow privilégié de revue humaine LOT41V.

Étend la couverture d'origine avec la correction du ciblage SHA du
required check (voir `docs/reports/lot_fix_trusted_review_check_sha.md`
puis `docs/reports/trusted_review_head_drift_incident_20260815.md`) :
déclenché par `issue_comment` (la commande `/nexus-trusted-review`), ce
workflow n'a pas de `head_sha` naturel côté GitHub (contrairement à
`pull_request_target`) : le check-run IMPLICITE que GitHub Actions crée
pour ce job s'attache par défaut au tip de `main` au moment du
déclenchement, jamais au head réel de la PR commentée -- confirmé
empiriquement deux fois cette session (PR #104, PR #106) via
`gh api repos/.../check-runs/<id>` montrant `head_sha` = le tip de main
à ce moment, pas le head de la PR.

Une première correction (PR#114) a publié un check-run explicite,
épinglé au vrai head, via l'API Checks. Ce check-run s'est révélé peu
fiable comme required status check (PR#116) : un check-run ajouté par un
déclenchement `issue_comment` ultérieur rejoint le check_suite déjà
`completed` de la toute première évaluation pour ce head_sha, dont le
rollup ne se rafraîchit jamais ; la branch-protection GitHub, qui
s'appuie sur ce rollup, continue de rapporter le required check comme
"expected" même quand le check-run individuel est bien `success` --
prouvé par rehearsal isolé, voir
`docs/reports/trusted_review_branch_protection_rehearsal_20260815.md`.
Remplacé ici par un Commit Status explicite (API Statuses), sans notion
de suite/rollup -- chaque POST est un enregistrement plat, immédiatement
pris en compte.

Ce fichier ne déclenche jamais le workflow réellement : il parse son
YAML et confronte sa structure au correctif."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

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
        cls.steps = document["jobs"]["evaluate"]["steps"]

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
        # `statuses: write` (not `checks: write`): required to publish
        # the head-pinned Commit Status explicitly (see module
        # docstring) -- still nothing beyond the minimum this job
        # actually needs.
        self.assertEqual(
            self.workflow.get("permissions"),
            {
                "contents": "read",
                "pull-requests": "read",
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
        # `continue-on-error` now legitimately appears on the `evaluate`
        # step (see test_evaluate_step_continues_on_error_so_the_check_run_step_still_runs)
        # -- deliberate, so the head-pinned check-run can still be
        # published even when the review evaluation itself fails. The
        # dedicated test below (`test_job_still_fails_for_real_when_review_is_not_approved`)
        # proves this never silently turns a real failure green.

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

    def test_scope_step_resolves_numeric_pr_and_exact_event_head_via_env(self) -> None:
        scope = next(s for s in self.steps if s.get("id") == "scope")
        self.assertEqual(scope["env"]["GH_TOKEN"], "${{ github.token }}")
        self.assertEqual(
            scope["env"]["PR_NUMBER"],
            "${{ github.event.pull_request.number || "
            "github.event.issue.number }}",
        )
        self.assertEqual(
            scope["env"]["EXPECTED_HEAD"],
            "${{ github.event.pull_request.head.sha }}",
        )
        run = scope["run"]
        self.assertIn('[[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]', run)
        self.assertIn('if [[ -z "$EXPECTED_HEAD" ]]', run)
        self.assertIn("pulls/$PR_NUMBER", run)
        self.assertIn("[.base.ref, .head.sha] | @tsv", run)
        self.assertIn('[[ "$OBSERVED_BASE_REF" == "main" ]]', run)
        self.assertIn("PR hors main ignorée", run)
        self.assertIn('[[ "$EXPECTED_HEAD" =~ ^[0-9a-f]{40}$ ]]', run)
        self.assertIn("expected_head=$EXPECTED_HEAD", run)
        self.assertIn("in_scope=true", run)

    def test_evaluate_step_invokes_the_unchanged_adapter_script(self) -> None:
        evaluate = next(s for s in self.steps if s.get("id") == "evaluate")
        run = evaluate["run"]
        self.assertIn("trusted_human_review_github.py", run)
        self.assertIn("--check", run)
        self.assertNotIn("--publish", run)
        self.assertNotIn("--target-url", run)
        self.assertIn("${{ steps.scope.outputs.pr_number }}", run)
        self.assertIn("${{ steps.scope.outputs.expected_head }}", run)

    def test_evaluate_step_continues_on_error_so_the_check_run_step_still_runs(self) -> None:
        evaluate_step = next(s for s in self.steps if s.get("id") == "evaluate")
        self.assertTrue(evaluate_step.get("continue-on-error"))

    def test_status_is_published_explicitly_pinned_to_the_resolved_head(self) -> None:
        publish_step = next(
            s for s in self.steps if s.get("name") == "Publish head-pinned trusted-review status"
        )
        self.assertEqual(publish_step.get("if"), "always() && steps.scope.outputs.in_scope == 'true'")
        run = publish_step["run"]
        self.assertIn("statuses/$EXPECTED_HEAD", run)
        self.assertIn('context="trusted-human-review/head-pinned"', run)
        self.assertEqual(
            publish_step["env"]["EXPECTED_HEAD"],
            "${{ steps.scope.outputs.expected_head }}",
        )

    def test_status_uses_the_statuses_api_not_checks_api(self) -> None:
        # The Checks API (check-runs, grouped into check_suites) was
        # abandoned after PR#116 proved its required-check recognition
        # unreliable (stale suite rollup). The Statuses API has no such
        # grouping layer.
        publish_step = next(
            s for s in self.steps if s.get("name") == "Publish head-pinned trusted-review status"
        )
        run = publish_step["run"]
        self.assertIn("repos/$GITHUB_REPOSITORY/statuses/", run)
        self.assertNotIn("check-runs", run)

    def test_status_state_reflects_the_evaluate_step_outcome(self) -> None:
        publish_step = next(
            s for s in self.steps if s.get("name") == "Publish head-pinned trusted-review status"
        )
        self.assertEqual(publish_step["env"]["OUTCOME"], "${{ steps.evaluate.outcome }}")
        run = publish_step["run"]
        self.assertIn('"$OUTCOME" == "success"', run)
        self.assertIn("state=success", run)
        self.assertIn("state=failure", run)
        self.assertIn('-f state="$state"', run)

    def test_job_still_fails_for_real_when_review_is_not_approved(self) -> None:
        # continue-on-error on the `evaluate` step would otherwise leave
        # the whole job green even when the review was refused -- a
        # dedicated final step must still fail it for real.
        fail_step = next(
            s for s in self.steps if s.get("name") == "Fail the job if the review was not approved"
        )
        self.assertEqual(
            fail_step.get("if"),
            "steps.scope.outputs.in_scope == 'true' && steps.evaluate.outcome != 'success'",
        )
        self.assertIn("exit 1", fail_step["run"])

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
