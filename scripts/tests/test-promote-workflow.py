#!/usr/bin/env python3
"""Contrat statique du workflow canonique de promotion (ADR-0036).

Chaque chemin littéral référencé dans le workflow doit exister sur disque
-- un workflow qui pointe vers un fichier absent échouerait silencieusement
au premier run réel, bien après la revue humaine. Ce test le prouve avant
tout run."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "promote.yml"
PINNED_ACTION = re.compile(r"actions/[a-z0-9-]+@[0-9a-f]{40}\Z")


class PromoteWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW_PATH.read_text(encoding="utf-8")
        document = yaml.safe_load(cls.source)
        if not isinstance(document, dict):
            raise AssertionError("workflow must be a YAML object")
        cls.workflow = document
        # Only the executable `run:` bodies -- never the header docstring,
        # which legitimately explains in prose why compose/.env/signing
        # are deliberately out of scope for this workflow.
        cls.run_bodies = "\n".join(
            step["run"]
            for job in document["jobs"].values()
            for step in job.get("steps", [])
            if isinstance(step, dict) and "run" in step
        )

    def test_only_workflow_dispatch_is_enabled(self) -> None:
        events = self.workflow.get("on")
        self.assertIsInstance(events, dict)
        assert isinstance(events, dict)
        self.assertEqual(set(events), {"workflow_dispatch"})
        inputs = events["workflow_dispatch"]["inputs"]
        self.assertEqual(
            set(inputs),
            {
                "pr_number",
                "campaign_id",
                "image_provenance_run_id",
                "image_provenance_run_attempt",
            },
        )
        for name, spec in inputs.items():
            with self.subTest(name=name):
                self.assertTrue(spec.get("required"))

    def test_permissions_are_minimal_and_read_only(self) -> None:
        top_level = self.workflow.get("permissions")
        self.assertEqual(
            top_level,
            {"contents": "read", "actions": "read", "pull-requests": "read"},
        )
        for job_name, job in self.workflow["jobs"].items():
            if "permissions" not in job:
                continue
            with self.subTest(job=job_name):
                for scope, level in job["permissions"].items():
                    self.assertEqual(
                        level, "read", f"{job_name}.permissions.{scope} must be read-only"
                    )

    def test_expected_jobs_exist_with_correct_shape(self) -> None:
        jobs = self.workflow.get("jobs")
        self.assertEqual(set(jobs), {"identity", "h2-evidence", "image-provenance", "assemble"})

        self.assertEqual(jobs["identity"].get("if"), "github.ref == 'refs/heads/main'")

        # Reusable-workflow call: must reference the real, existing local
        # workflow by relative path, never a fork/tag/branch reference.
        h2_job = jobs["h2-evidence"]
        self.assertEqual(h2_job.get("uses"), "./.github/workflows/_produce-h2-evidence.yml")
        self.assertEqual(h2_job.get("needs"), "identity")
        self.assertEqual(
            h2_job.get("with"),
            {
                "pull_request_number": "${{ inputs.pr_number }}",
                "campaign_id": "${{ inputs.campaign_id }}",
            },
        )

        self.assertEqual(jobs["image-provenance"].get("needs"), "identity")
        self.assertEqual(
            set(jobs["assemble"].get("needs")),
            {"identity", "h2-evidence", "image-provenance"},
        )

    def test_never_signs_and_never_touches_a_private_key(self) -> None:
        # "secrets." is checked against the full source (never legitimate
        # anywhere in this workflow, comment or code); the rest are
        # checked only against executable run: bodies, since the header
        # docstring legitimately discusses signing in prose.
        self.assertNotIn("secrets.", self.source)
        forbidden = (
            "private-key",
            "private_key",
            "PRIVATE_KEY",
            "sign_production_readiness_manifest",
            "NEXUS_PRODUCTION_READINESS_SIGNING_KEY",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.run_bodies)

    def test_never_resolves_compose_or_touches_env_secrets(self) -> None:
        forbidden = ("docker compose", "--env-file", ".env")
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.run_bodies)

    def test_never_deploys(self) -> None:
        forbidden = ("docker compose up", "docker compose pull", "deploy_verified_release")
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.run_bodies)

    def test_assemble_job_is_environment_gated(self) -> None:
        self.assertEqual(self.workflow["jobs"]["assemble"].get("environment"), "production")

    def test_image_provenance_job_verifies_status_headsha_and_attempt(self) -> None:
        job = self.workflow["jobs"]["image-provenance"]
        steps = job["steps"]
        verify = next(s for s in steps if s.get("id") == "verify")
        run = verify["run"]
        for fragment in (
            '"$status" != "completed"',
            '"$conclusion" != "success"',
            '"$head_sha" != "$MERGE_SHA"',
            '"$current_attempt" != "$RUN_ATTEMPT"',
            "attempts/${RUN_ATTEMPT}",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, run)

    def test_identity_job_requires_tree_equality_and_ancestry(self) -> None:
        job = self.workflow["jobs"]["identity"]
        steps = job["steps"]
        identity = next(s for s in steps if s.get("id") == "identity")
        run = identity["run"]
        for fragment in (
            "merge-base --is-ancestor",
            '"$head_tree" != "$merge_tree"',
            '"$merged" != "true"',
            '"$base_ref" != "main"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, run)

    def test_all_actions_are_pinned_by_commit_sha(self) -> None:
        for m in re.finditer(r"uses:\s*(actions/[a-z0-9-]+@[^\s]+)", self.source):
            with self.subTest(action=m.group(1)):
                self.assertRegex(m.group(1), PINNED_ACTION)

    def test_referenced_local_workflow_paths_exist_on_disk(self) -> None:
        referenced = {
            ".github/workflows/_produce-h2-evidence.yml",
            ".github/workflows/production-image-provenance.yml",
            ".github/workflows/promote.yml",
        }
        for rel in referenced:
            with self.subTest(path=rel):
                self.assertTrue((REPO_ROOT / rel).is_file(), f"{rel} does not exist on disk")

    def test_promotion_workflow_ref_uses_github_ref_not_workflow_ref_context(self) -> None:
        # sign_production_readiness_manifest_cli.py compares --workflow-ref
        # against f"refs/heads/{run.head_branch}" -- github.workflow_ref
        # is a different, longer format and would never match.
        assemble = self.workflow["jobs"]["assemble"]["steps"][0]
        self.assertEqual(assemble["env"]["PROMOTION_WORKFLOW_REF"], "${{ github.ref }}")
        for job in self.workflow["jobs"].values():
            for step in job.get("steps", []):
                if isinstance(step, dict):
                    for value in step.get("env", {}).values():
                        self.assertNotIn("github.workflow_ref", str(value))

    def test_concurrency_is_bound_to_the_pull_request(self) -> None:
        self.assertEqual(
            self.workflow.get("concurrency"),
            {"group": "promote-${{ inputs.pr_number }}", "cancel-in-progress": False},
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())
