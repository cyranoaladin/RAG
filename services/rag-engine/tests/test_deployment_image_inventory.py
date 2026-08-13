"""Tests — vérification de NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1 (ADR-0036).

Aucun appel réseau : ``github_api_get``/``download_artifact`` sont des
doubles fournis explicitement à chaque appel, jamais un vrai ``gh``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deployment_image_inventory as dii  # noqa: E402

REPOSITORY = "cyranoaladin/RAG"
RUN_ID = 555
SOURCE_COMMIT_SHA = "a" * 40
SOURCE_TREE_SHA = "b" * 40
WORKFLOW_PATH = ".github/workflows/production-image-provenance.yml"

INGESTOR_DIGEST = "sha256:" + "1" * 64
WORKER_DIGEST = "sha256:" + "2" * 64
DOCKERFILE_SHA = "3" * 64


def _run_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "path": WORKFLOW_PATH,
        "repository": {"full_name": REPOSITORY},
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_sha": SOURCE_COMMIT_SHA,
    }
    document.update(overrides)
    return document


def _inventory_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "protocol_version": "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1",
        "repository": REPOSITORY,
        "source_commit_sha": SOURCE_COMMIT_SHA,
        "source_tree_sha": SOURCE_TREE_SHA,
        "platform": "linux/amd64",
        "workflow_path": WORKFLOW_PATH,
        "workflow_run_id": RUN_ID,
        "workflow_run_attempt": 1,
        "workflow_ref": "refs/heads/main",
        "built_at": "2026-08-13T12:00:00Z",
        "services": {
            "ingestor": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.ingestor-v2",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": "ghcr.io/cyranoaladin/rag-ingestor",
                "image_digest": INGESTOR_DIGEST,
            },
            "multilevel-worker-a-production": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": "ghcr.io/cyranoaladin/rag-multilevel-worker-production",
                "image_digest": WORKER_DIGEST,
            },
            "multilevel-worker-b-production": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": "ghcr.io/cyranoaladin/rag-multilevel-worker-production",
                "image_digest": WORKER_DIGEST,
            },
        },
    }
    document.update(overrides)
    return document


class _Fakes:
    def __init__(self, *, run: dict[str, Any], inventory: dict[str, Any] | None) -> None:
        self.run = run
        self.inventory = inventory
        self.download_calls: list[tuple[int, str, Path]] = []

    def github_api_get(self, path: str) -> dict[str, Any]:
        expected = f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"
        if path != expected:
            raise dii.DeploymentImageInventoryError(f"unexpected path in test: {path!r}")
        return self.run

    def download_artifact(self, run_id: int, artifact_name: str, dest_dir: Path) -> Path:
        self.download_calls.append((run_id, artifact_name, dest_dir))
        if self.inventory is None:
            raise dii.DeploymentImageInventoryError("artifact not found (simulated)")
        path = dest_dir / dii._ARTIFACT_FILENAME
        path.write_text(json.dumps(self.inventory), encoding="utf-8")
        return path


def _verify(fakes: _Fakes, tmp_path: Path, **overrides: Any) -> dict[str, str]:
    kwargs: dict[str, Any] = dict(
        repository=REPOSITORY,
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_tree_sha=SOURCE_TREE_SHA,
        provenance_run_id=RUN_ID,
        github_api_get=fakes.github_api_get,
        download_artifact=fakes.download_artifact,
        work_dir=tmp_path,
    )
    kwargs.update(overrides)
    return dii.verify_application_image_provenance(**kwargs)


class TestValidProvenanceIsAccepted:
    def test_matching_run_and_inventory_yields_expected_digest_map(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(), inventory=_inventory_document())
        digests = _verify(fakes, tmp_path)
        assert digests == {
            "ingestor": f"ghcr.io/cyranoaladin/rag-ingestor@{INGESTOR_DIGEST}",
            "multilevel-worker-a-production": (
                f"ghcr.io/cyranoaladin/rag-multilevel-worker-production@{WORKER_DIGEST}"
            ),
            "multilevel-worker-b-production": (
                f"ghcr.io/cyranoaladin/rag-multilevel-worker-production@{WORKER_DIGEST}"
            ),
        }

    def test_downloads_the_canonical_artifact_name_for_the_right_run(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(), inventory=_inventory_document())
        _verify(fakes, tmp_path)
        assert fakes.download_calls == [(RUN_ID, "nexus-deployment-image-inventory", tmp_path)]


class TestRunLevelRefusals:
    def test_wrong_workflow_path_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(path=".github/workflows/ci.yml"), inventory=_inventory_document())
        with pytest.raises(dii.DeploymentImageInventoryError, match="workflow path"):
            _verify(fakes, tmp_path)

    def test_wrong_repository_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(repository={"full_name": "someone-else/RAG"}),
            inventory=_inventory_document(),
        )
        with pytest.raises(dii.DeploymentImageInventoryError, match="belongs to"):
            _verify(fakes, tmp_path)

    def test_non_workflow_dispatch_trigger_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(event="push"), inventory=_inventory_document())
        with pytest.raises(dii.DeploymentImageInventoryError, match="workflow_dispatch"):
            _verify(fakes, tmp_path)

    def test_failed_run_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(conclusion="failure"), inventory=_inventory_document())
        with pytest.raises(dii.DeploymentImageInventoryError, match="successfully completed"):
            _verify(fakes, tmp_path)

    def test_in_progress_run_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(status="in_progress", conclusion=None), inventory=_inventory_document()
        )
        with pytest.raises(dii.DeploymentImageInventoryError, match="successfully completed"):
            _verify(fakes, tmp_path)

    def test_wrong_source_commit_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(head_sha="f" * 40), inventory=_inventory_document())
        with pytest.raises(dii.DeploymentImageInventoryError, match="not the commit being signed"):
            _verify(fakes, tmp_path)


class TestArtifactLevelRefusals:
    def test_missing_artifact_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(), inventory=None)
        with pytest.raises(dii.DeploymentImageInventoryError, match="artifact not found"):
            _verify(fakes, tmp_path)

    def test_wrong_protocol_version_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(), inventory=_inventory_document(protocol_version="OTHER-V1"))
        with pytest.raises(dii.DeploymentImageInventoryError, match="protocol_version"):
            _verify(fakes, tmp_path)

    def test_inventory_repository_mismatch_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(repository="someone-else/RAG")
        )
        with pytest.raises(dii.DeploymentImageInventoryError, match="repository"):
            _verify(fakes, tmp_path)

    def test_inventory_source_commit_mismatch_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(source_commit_sha="f" * 40)
        )
        with pytest.raises(dii.DeploymentImageInventoryError, match="source_commit_sha"):
            _verify(fakes, tmp_path)

    def test_inventory_source_tree_mismatch_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(), inventory=_inventory_document(source_tree_sha="f" * 40))
        with pytest.raises(dii.DeploymentImageInventoryError, match="source_tree_sha"):
            _verify(fakes, tmp_path)

    def test_inventory_workflow_run_id_mismatch_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(), inventory=_inventory_document(workflow_run_id=999))
        with pytest.raises(dii.DeploymentImageInventoryError, match="workflow_run_id"):
            _verify(fakes, tmp_path)

    def test_wrong_platform_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(), inventory=_inventory_document(platform="linux/arm64"))
        with pytest.raises(dii.DeploymentImageInventoryError, match="platform"):
            _verify(fakes, tmp_path)

    def test_malformed_json_is_refused(self, tmp_path: Path) -> None:
        class BrokenFakes(_Fakes):
            def download_artifact(self, run_id: int, artifact_name: str, dest_dir: Path) -> Path:
                self.download_calls.append((run_id, artifact_name, dest_dir))
                path = dest_dir / dii._ARTIFACT_FILENAME
                path.write_bytes(b"not json")
                return path

        fakes = BrokenFakes(run=_run_document(), inventory=_inventory_document())
        with pytest.raises(dii.DeploymentImageInventoryError, match="not valid UTF-8 JSON"):
            _verify(fakes, tmp_path)

    def test_no_services_declared_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(run=_run_document(), inventory=_inventory_document(services={}))
        with pytest.raises(dii.DeploymentImageInventoryError, match="no services"):
            _verify(fakes, tmp_path)


class TestPerServiceRefusals:
    def test_upstream_source_kind_is_refused(self, tmp_path: Path) -> None:
        inventory = _inventory_document()
        inventory["services"]["ingestor"]["source_kind"] = "upstream"
        fakes = _Fakes(run=_run_document(), inventory=inventory)
        with pytest.raises(dii.DeploymentImageInventoryError, match="source_kind must be 'build'"):
            _verify(fakes, tmp_path)

    def test_mutable_tag_instead_of_digest_is_refused(self, tmp_path: Path) -> None:
        inventory = _inventory_document()
        inventory["services"]["ingestor"]["image_digest"] = "latest"
        fakes = _Fakes(run=_run_document(), inventory=inventory)
        with pytest.raises(dii.DeploymentImageInventoryError, match="not a valid sha256"):
            _verify(fakes, tmp_path)

    def test_missing_digest_is_refused(self, tmp_path: Path) -> None:
        inventory = _inventory_document()
        del inventory["services"]["ingestor"]["image_digest"]
        fakes = _Fakes(run=_run_document(), inventory=inventory)
        with pytest.raises(dii.DeploymentImageInventoryError, match="not a valid sha256"):
            _verify(fakes, tmp_path)

    def test_missing_dockerfile_sha256_is_refused(self, tmp_path: Path) -> None:
        inventory = _inventory_document()
        del inventory["services"]["ingestor"]["dockerfile_sha256"]
        fakes = _Fakes(run=_run_document(), inventory=inventory)
        with pytest.raises(dii.DeploymentImageInventoryError, match="dockerfile_sha256"):
            _verify(fakes, tmp_path)

    def test_invalid_image_repository_is_refused(self, tmp_path: Path) -> None:
        inventory = _inventory_document()
        inventory["services"]["ingestor"]["image_repository"] = "GHCR.IO/Not-Valid!"
        fakes = _Fakes(run=_run_document(), inventory=inventory)
        with pytest.raises(dii.DeploymentImageInventoryError, match="image_repository"):
            _verify(fakes, tmp_path)

    def test_an_omitted_service_is_refused_not_silently_dropped(self, tmp_path: Path) -> None:
        """Codex P1 (PR #102): both worker services must appear as distinct,
        explicit entries (even though they share one underlying build) --
        an inventory missing one of the three production services must be
        refused outright, never silently accepted with a partial digest
        map. The original version of this test asserted the opposite
        (partial acceptance) and was itself the evidence of the bug."""
        inventory = _inventory_document()
        del inventory["services"]["multilevel-worker-b-production"]
        fakes = _Fakes(run=_run_document(), inventory=inventory)
        with pytest.raises(dii.DeploymentImageInventoryError, match="exactly the production"):
            _verify(fakes, tmp_path)

    def test_an_invented_extra_service_is_refused(self, tmp_path: Path) -> None:
        inventory = _inventory_document()
        inventory["services"]["invented-service"] = dict(
            inventory["services"]["ingestor"], image_repository="ghcr.io/x/invented"
        )
        fakes = _Fakes(run=_run_document(), inventory=inventory)
        with pytest.raises(dii.DeploymentImageInventoryError, match="exactly the production"):
            _verify(fakes, tmp_path)


EXPECTED_SERVICES = (
    "ingestor",
    "multilevel-worker-a-production",
    "multilevel-worker-b-production",
)


def _resolved_compose(**per_service_overrides: dict[str, Any]) -> dict[str, Any]:
    services: dict[str, Any] = {
        name: {"image": f"ghcr.io/cyranoaladin/rag-x@sha256:{str(i + 1) * 64}"}
        for i, name in enumerate(EXPECTED_SERVICES)
    }
    for name, override in per_service_overrides.items():
        services[name] = override
    return {"services": services}


class TestResolvedComposeImagesArePinned:
    """Codex P2 (PR #102): ``${VAR:?requis}`` only proves non-empty, never
    digest-pinned. This is the primitive a future deployment wrapper must
    call before ``docker compose up`` -- proven here directly against
    ``docker compose ... config`` shaped output."""

    def test_all_three_services_pinned_by_digest_is_accepted(self) -> None:
        resolved = _resolved_compose()
        pinned = dii.require_resolved_compose_images_are_pinned(resolved)
        assert set(pinned) == set(EXPECTED_SERVICES)
        for image in pinned.values():
            assert dii._PINNED_IMAGE_REF.fullmatch(image)

    def test_mutable_tag_is_refused(self) -> None:
        resolved = _resolved_compose(ingestor={"image": "ghcr.io/cyranoaladin/rag-ingestor:latest"})
        with pytest.raises(dii.DeploymentImageInventoryError, match="not pinned by digest"):
            dii.require_resolved_compose_images_are_pinned(resolved)

    def test_tag_alongside_digest_is_refused(self) -> None:
        # Real docker compose config does NOT strip a tag that coexists
        # with a digest (verified empirically against Docker Compose
        # v5.4.0) -- so this must be refused, not silently accepted.
        resolved = _resolved_compose(
            ingestor={"image": "ghcr.io/cyranoaladin/rag-ingestor:sha-abc@sha256:" + "1" * 64}
        )
        with pytest.raises(dii.DeploymentImageInventoryError, match="not pinned by digest"):
            dii.require_resolved_compose_images_are_pinned(resolved)

    def test_residual_build_key_is_refused(self) -> None:
        resolved = _resolved_compose(
            ingestor={"image": "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "1" * 64, "build": {}}
        )
        with pytest.raises(dii.DeploymentImageInventoryError, match="still resolves with a 'build'"):
            dii.require_resolved_compose_images_are_pinned(resolved)

    def test_missing_service_is_refused(self) -> None:
        resolved = _resolved_compose()
        del resolved["services"]["multilevel-worker-b-production"]
        with pytest.raises(dii.DeploymentImageInventoryError, match="missing expected service"):
            dii.require_resolved_compose_images_are_pinned(resolved)

    def test_missing_image_field_is_refused(self) -> None:
        resolved = _resolved_compose(ingestor={})
        with pytest.raises(dii.DeploymentImageInventoryError, match="not pinned by digest"):
            dii.require_resolved_compose_images_are_pinned(resolved)

    def test_no_services_mapping_is_refused(self) -> None:
        with pytest.raises(dii.DeploymentImageInventoryError, match="no 'services' mapping"):
            dii.require_resolved_compose_images_are_pinned({})
