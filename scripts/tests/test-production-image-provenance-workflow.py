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
from datetime import datetime
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

    def test_cuda_ingestor_is_opt_in_and_uses_a_distinct_commit_tag(self) -> None:
        inputs = self.workflow[True]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["cuda_ingestor"]["type"], "boolean")
        self.assertIs(inputs["cuda_ingestor"]["default"], False)
        steps = self.workflow["jobs"]["build-and-push"]["steps"]
        cpu = next(step for step in steps if step.get("id") == "build_ingestor")
        cuda = next(step for step in steps if step.get("id") == "build_ingestor_cuda")
        self.assertEqual(cpu["if"], "inputs.cuda_ingestor != true")
        self.assertEqual(cuda["if"], "inputs.cuda_ingestor == true")
        self.assertEqual(cuda["with"]["file"], "services/rag-engine/infra/Dockerfile.ingestor-v2.cuda")
        self.assertIn(":sha-${{ steps.source.outputs.commit_sha }}-cuda", cuda["with"]["tags"])
        self.assertIs(cuda["with"]["push"], True)
        self.assertIs(cuda["with"]["provenance"], True)
        self.assertIs(cuda["with"]["sbom"], True)

    def _run_assembler(
        self, directory: str, *, public_candidate: str, cockpit_digest: str,
        cuda_ingestor: str = "false",
    ) -> subprocess.CompletedProcess[str]:
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
            "COCKPIT_DIGEST": cockpit_digest,
            "COCKPIT_DOCKERFILE_SHA256": "6" * 64,
            "IMAGE_NAMESPACE": "ghcr.io/cyranoaladin",
        }
        return subprocess.run(
            ["bash", "-e", "-c", assemble["run"]],
            cwd=directory,
            env={
                **os.environ,
                **env,
                "PUBLIC_CANDIDATE": public_candidate,
                "CUDA_INGESTOR": cuda_ingestor,
                "GITHUB_OUTPUT": str(Path(directory) / "github-output"),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    def test_assembler_emits_golden_v1_or_exact_four_service_v2(self) -> None:
        for enabled, protocol, filename in (
            (False, "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1", "nexus-deployment-image-inventory.json"),
            (True, "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V2", "nexus-public-deployment-image-inventory-v2.json"),
        ):
            with self.subTest(public_candidate=enabled):
                with TemporaryDirectory() as directory:
                    output = Path(directory) / "github-output"
                    result = self._run_assembler(
                        directory,
                        public_candidate=str(enabled).lower(),
                        cockpit_digest="sha256:" + "5" * 64 if enabled else "",
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    document = json.loads((Path(directory) / filename).read_text())
                    self.assertEqual(document["protocol_version"], protocol)
                    required_services = {
                        "ingestor", "multilevel-worker-a-production",
                        "multilevel-worker-b-production",
                    }
                    self.assertEqual(
                        set(document["services"]),
                        required_services | ({"cockpit"} if enabled else set()),
                    )
                    self.assertTrue(document["built_at"].endswith("Z"))
                    timestamp = datetime.fromisoformat(document["built_at"].replace("Z", "+00:00"))
                    self.assertEqual(timestamp.utcoffset().total_seconds(), 0)
                    without_timestamp = {key: value for key, value in document.items() if key != "built_at"}
                    expected = {
                        "protocol_version": "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1",
                        "repository": "cyranoaladin/RAG",
                        "source_commit_sha": "a" * 40,
                        "source_tree_sha": "b" * 40,
                        "platform": "linux/amd64",
                        "workflow_path": ".github/workflows/production-image-provenance.yml",
                        "workflow_run_id": 42,
                        "workflow_run_attempt": 1,
                        "workflow_ref": "refs/heads/main",
                        "services": {
                            "ingestor": {
                                "source_kind": "build", "build_context": ".",
                                "dockerfile": "services/rag-engine/infra/Dockerfile.ingestor-v2",
                                "dockerfile_sha256": "2" * 64,
                                "image_repository": "ghcr.io/cyranoaladin/rag-ingestor",
                                "image_digest": "sha256:" + "1" * 64,
                            },
                            "multilevel-worker-a-production": {
                                "source_kind": "build", "build_context": ".",
                                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                                "dockerfile_sha256": "4" * 64,
                                "image_repository": "ghcr.io/cyranoaladin/rag-multilevel-worker-production",
                                "image_digest": "sha256:" + "3" * 64,
                            },
                            "multilevel-worker-b-production": {
                                "source_kind": "build", "build_context": ".",
                                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                                "dockerfile_sha256": "4" * 64,
                                "image_repository": "ghcr.io/cyranoaladin/rag-multilevel-worker-production",
                                "image_digest": "sha256:" + "3" * 64,
                            },
                        },
                    }
                    if enabled:
                        expected["protocol_version"] = "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V2"
                        expected["services"]["cockpit"] = {
                            "source_kind": "build", "build_context": ".",
                            "dockerfile": "services/cockpit/Dockerfile",
                            "dockerfile_sha256": "6" * 64,
                            "image_repository": "ghcr.io/cyranoaladin/rag-cockpit",
                            "image_digest": "sha256:" + "5" * 64,
                        }
                    self.assertEqual(without_timestamp, expected)
                    self.assertIn("inventory_file=" + filename, output.read_text())

    def test_assembler_binds_cuda_dockerfile_to_the_public_image_digest(self) -> None:
        with TemporaryDirectory() as directory:
            result = self._run_assembler(
                directory, public_candidate="true", cuda_ingestor="true",
                cockpit_digest="sha256:" + "5" * 64,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            path = Path(directory) / "nexus-public-deployment-image-inventory-v2.json"
            image = json.loads(path.read_text())["services"]["ingestor"]
            self.assertEqual(image["dockerfile"], "services/rag-engine/infra/Dockerfile.ingestor-v2.cuda")
            self.assertEqual(image["dockerfile_sha256"], "2" * 64)
            self.assertEqual(image["image_repository"], "ghcr.io/cyranoaladin/rag-ingestor")
            self.assertEqual(image["image_digest"], "sha256:" + "1" * 64)

    def test_assembler_refuses_cuda_without_public_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            result = self._run_assembler(
                directory, public_candidate="false", cuda_ingestor="true", cockpit_digest="",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires public_candidate", result.stderr)

    def test_assembler_refuses_invalid_mode_and_missing_cockpit_digest(self) -> None:
        for mode, digest, expected_error in (
            ("not-a-boolean", "sha256:" + "5" * 64, "explicit boolean"),
            ("true", "", "produced no digest"),
        ):
            with self.subTest(mode=mode, digest=digest):
                with TemporaryDirectory() as directory:
                    result = self._run_assembler(
                        directory, public_candidate=mode, cockpit_digest=digest
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected_error, result.stderr)
                    self.assertEqual(list(Path(directory).glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
