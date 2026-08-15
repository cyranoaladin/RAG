#!/usr/bin/env python3
"""Garde-fou structurel — `.github/workflows/trusted-human-review.yml`.

Déclenché par `issue_comment` (la commande `/nexus-trusted-review`), ce
workflow n'a pas de `head_sha` naturel côté GitHub (contrairement à
`pull_request_target`) : le check-run IMPLICITE que GitHub Actions crée
pour ce job s'attache par défaut au tip de `main` au moment du
déclenchement, jamais au head réel de la PR commentée -- confirmé
empiriquement deux fois cette session (PR #104, PR #106) via
`gh api repos/.../check-runs/<id>` montrant `head_sha` = le tip de main
à ce moment, pas le head de la PR. Ce test ferme cette classe de
régression : il ne déclenche jamais le workflow réellement, il parse son
YAML et confronte sa structure au correctif (un check-run explicite,
publié via l'API Checks, épinglé au vrai head résolu en sortie de step).
"""
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

    def test_workflow_yaml_is_valid(self) -> None:
        self.assertIn("jobs", self.workflow)

    def test_checks_write_permission_is_granted(self) -> None:
        # Required to call `POST /repos/.../check-runs` explicitly --
        # without this, the fix below cannot publish anything.
        self.assertEqual(self.workflow.get("permissions", {}).get("checks"), "write")

    def test_scope_resolution_step_exposes_expected_head_as_output(self) -> None:
        scope_step = next(s for s in self.steps if s.get("id") == "scope")
        self.assertIn("expected_head=$EXPECTED_HEAD", scope_step["run"])
        self.assertIn("in_scope=true", scope_step["run"])

    def test_evaluate_step_continues_on_error_so_the_check_run_step_still_runs(self) -> None:
        evaluate_step = next(s for s in self.steps if s.get("id") == "evaluate")
        self.assertTrue(evaluate_step.get("continue-on-error"))

    def test_check_run_is_published_explicitly_pinned_to_the_resolved_head(self) -> None:
        publish_step = next(
            s for s in self.steps if s.get("name") == "Publish head-pinned check-run"
        )
        self.assertEqual(publish_step.get("if"), "always() && steps.scope.outputs.in_scope == 'true'")
        run = publish_step["run"]
        self.assertIn("check-runs", run)
        self.assertIn('head_sha="$EXPECTED_HEAD"', run)
        self.assertEqual(
            publish_step["env"]["EXPECTED_HEAD"],
            "${{ steps.scope.outputs.expected_head }}",
        )

    def test_check_run_conclusion_reflects_the_evaluate_step_outcome(self) -> None:
        publish_step = next(
            s for s in self.steps if s.get("name") == "Publish head-pinned check-run"
        )
        self.assertEqual(publish_step["env"]["OUTCOME"], "${{ steps.evaluate.outcome }}")
        run = publish_step["run"]
        self.assertIn('"$OUTCOME" == "success"', run)
        self.assertIn("conclusion=success", run)
        self.assertIn("conclusion=failure", run)

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

    def test_no_private_key_material_referenced(self) -> None:
        forbidden = ("private-key", "private_key", "PRIVATE_KEY", "sign_production_readiness_manifest")
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.source)

    def test_all_actions_are_pinned_by_commit_sha(self) -> None:
        for m in re.finditer(r"uses:\s*(actions/[a-z0-9-]+@[^\s]+)", self.source):
            with self.subTest(action=m.group(1)):
                self.assertRegex(m.group(1), PINNED_ACTION)


if __name__ == "__main__":
    unittest.main()
