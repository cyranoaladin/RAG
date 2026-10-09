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

import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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

    def test_public_candidate_is_an_explicit_opt_in(self) -> None:
        event = self.workflow[True]["workflow_dispatch"]
        self.assertEqual(event["inputs"]["public_candidate"]["type"], "boolean")
        self.assertIs(event["inputs"]["public_candidate"]["default"], False)
        steps = self.workflow["jobs"]["build-and-push"]["steps"]
        cockpit = next(step for step in steps if step["name"] == "Build and push cockpit")
        self.assertEqual(cockpit["if"], "inputs.public_candidate == true")
        self.assertEqual(cockpit["with"]["build-args"], "SOURCE_COMMIT_SHA=${{ steps.source.outputs.commit_sha }}")
        self.assertEqual(cockpit["with"]["file"], "services/cockpit/Dockerfile")
        self.assertIs(cockpit["with"]["push"], True)

    def test_assembler_emits_unchanged_v1_or_exact_four_service_v2(self) -> None:
        steps = self.workflow["jobs"]["build-and-push"]["steps"]
        assemble = next(step for step in steps if step.get("id") == "inventory")
        env = {
            "REPOSITORY": "cyranoaladin/RAG",
            "SOURCE_COMMIT_SHA": "a" * 40,
            "SOURCE_TREE_SHA": "b" * 40,
            "WORKFLOW_RUN_ID": "42",
            "WORKFLOW_RUN_ATTEMPT": "1",
            "INGESTOR_DIGEST": "sha256:" + "1" * 64,
            "INGESTOR_DOCKERFILE_SHA256": "2" * 64,
            "WORKER_DIGEST": "sha256:" + "3" * 64,
            "WORKER_DOCKERFILE_SHA256": "4" * 64,
            "COCKPIT_DIGEST": "sha256:" + "5" * 64,
            "COCKPIT_DOCKERFILE_SHA256": "6" * 64,
            "IMAGE_NAMESPACE": "ghcr.io/cyranoaladin",
        }
        for enabled, protocol, names, filename in (
            (False, "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1", 3, "nexus-deployment-image-inventory.json"),
            (True, "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V2", 4, "nexus-public-deployment-image-inventory-v2.json"),
        ):
            with self.subTest(public_candidate=enabled):
                with TemporaryDirectory() as directory:
                    output = Path(directory) / "github-output"
                    result = subprocess.run(
                        ["bash", "-e", "-c", assemble["run"]],
                        cwd=directory,
                        env={
                            **os.environ,
                            **env,
                            "PUBLIC_CANDIDATE": str(enabled).lower(),
                            "COCKPIT_DIGEST": env["COCKPIT_DIGEST"] if enabled else "",
                            "COCKPIT_DOCKERFILE_SHA256": env["COCKPIT_DOCKERFILE_SHA256"] if enabled else "",
                            "GITHUB_OUTPUT": str(output),
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    document = json.loads((Path(directory) / filename).read_text())
                    self.assertEqual(document["protocol_version"], protocol)
                    self.assertEqual(len(document["services"]), names)
                    self.assertEqual("cockpit" in document["services"], enabled)
                    if enabled:
                        self.assertEqual(document["services"]["cockpit"]["dockerfile"], "services/cockpit/Dockerfile")
                    self.assertIn("inventory_file=" + filename, output.read_text())


if __name__ == "__main__":
    unittest.main()
