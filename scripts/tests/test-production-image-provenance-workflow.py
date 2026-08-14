#!/usr/bin/env python3
"""Garde-fou structurel — `.github/workflows/production-image-provenance.yml`.

Ce workflow portait un `if:` de job (`github.ref == 'refs/heads/main'`) en
plus de son refus par étape -- un `if:` de job qui évalue à faux produit un
statut `skipped`, jamais `failure`. Un dispatch sur la mauvaise ref aurait
donc laissé le run entier apparaître **vert** (job "skipped"), jamais
rouge, l'étape de refus explicite n'ayant jamais l'occasion de s'exécuter.
Même défaut trouvé et corrigé dans `promote.yml` (PR #110) ; corrigé ici
à l'identique. Ce test ferme cette classe de régression.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "production-image-provenance.yml"
PINNED_ACTION = re.compile(r"actions/[a-z0-9-]+@[0-9a-f]{40}\Z")


class ProductionImageProvenanceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW_PATH.read_text(encoding="utf-8")
        document = yaml.safe_load(cls.source)
        if not isinstance(document, dict):
            raise AssertionError("workflow must be a YAML object")
        cls.workflow = document

    def test_workflow_yaml_is_valid(self) -> None:
        self.assertIn("jobs", self.workflow)

    def test_build_and_push_job_has_no_top_level_if_and_fails_closed_on_wrong_ref(self) -> None:
        job = self.workflow["jobs"]["build-and-push"]
        self.assertNotIn(
            "if", job, "build-and-push job must never gate itself with a job-level `if:`"
        )
        steps = job["steps"]
        refuse = steps[0]
        self.assertEqual(refuse.get("if"), "github.ref != 'refs/heads/main'")
        self.assertIn("exit 1", refuse["run"])

    def test_only_workflow_dispatch_is_enabled(self) -> None:
        # PyYAML parses a bare `on:` key as the boolean `True` (YAML 1.1
        # legacy quirk) -- this workflow doesn't quote it (unlike
        # promote.yml's `"on":`), so look it up under the boolean key.
        events = self.workflow.get(True)
        self.assertIsInstance(events, dict)
        assert isinstance(events, dict)
        self.assertEqual(set(events), {"workflow_dispatch"})

    def test_never_signs(self) -> None:
        # `secrets.GITHUB_TOKEN` is the standard ephemeral, run-scoped
        # token needed to push to GHCR -- not a long-lived credential and
        # not the production-readiness signing key. Any OTHER secret
        # reference would be suspicious; that one specific reference is
        # legitimate and expected.
        for m in re.finditer(r"secrets\.(\w+)", self.source):
            with self.subTest(secret=m.group(0)):
                self.assertEqual(m.group(1), "GITHUB_TOKEN")
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
