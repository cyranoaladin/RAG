"""Tests -- wrapper de déploiement atomique (Lot C, ferme la fenêtre TOCTOU
documentée dans `verify_release_image_provenance_cli.py`, PR #105).

Aucun vrai `docker`, `git`, `gh`, ni réseau : toutes les frontières
(`github_api_get`/`download_artifact`/`run_docker_compose_config`/
`run_subprocess`) sont des doubles injectés explicitement, comme dans la
suite sœur `test_verify_release_image_provenance_cli.py`.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deploy_verified_release_cli as dep  # noqa: E402
import deployment_image_inventory as dii  # noqa: E402
import verify_release_image_provenance_cli as vri  # noqa: E402
from nexus_contracts.production_readiness import (  # noqa: E402
    PRODUCTION_READINESS_PROTOCOL_VERSION,
    ProductionReadinessManifestV1,
    public_readiness_key_hex,
    sign_production_readiness_manifest,
)

REPOSITORY = dep._CANONICAL_REPOSITORY
RUN_ID = 777
RUN_ATTEMPT = 1
MERGE_SHA = "a" * 40
MERGE_TREE_SHA = "b" * 40
WORKFLOW_PATH = ".github/workflows/production-image-provenance.yml"

INGESTOR_DIGEST = "sha256:" + "1" * 64
WORKER_DIGEST = "sha256:" + "2" * 64
DOCKERFILE_SHA = "3" * 64
INGESTOR_REPO = "ghcr.io/cyranoaladin/rag-ingestor"
WORKER_REPO = "ghcr.io/cyranoaladin/rag-multilevel-worker-production"

READINESS_SEED = "11" * 32
KEY_ID = "nexus-readiness-test-1"

COMPOSE_CONTENTS = {
    "docker-compose.v2.yml": b"services:\n  ingestor:\n    image: placeholder\n",
    "docker-compose.production-workers.yml": b"services: {}\n",
    "docker-compose.production-release.yml": b"services: {}\n",
}
ENV_FILE_CONTENT = b"FOO=bar\n"


def _resolved_compose(**per_service_overrides: dict[str, Any]) -> dict[str, Any]:
    services: dict[str, Any] = {
        "ingestor": {"image": f"{INGESTOR_REPO}@{INGESTOR_DIGEST}"},
        "multilevel-worker-a-production": {"image": f"{WORKER_REPO}@{WORKER_DIGEST}"},
        "multilevel-worker-b-production": {"image": f"{WORKER_REPO}@{WORKER_DIGEST}"},
    }
    for name, override in per_service_overrides.items():
        services[name] = override
    return {"services": services}


def _run_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "path": WORKFLOW_PATH,
        "repository": {"full_name": REPOSITORY},
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_sha": MERGE_SHA,
        "run_attempt": RUN_ATTEMPT,
    }
    document.update(overrides)
    return document


def _inventory_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "protocol_version": "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1",
        "repository": REPOSITORY,
        "source_commit_sha": MERGE_SHA,
        "source_tree_sha": MERGE_TREE_SHA,
        "platform": "linux/amd64",
        "workflow_path": WORKFLOW_PATH,
        "workflow_run_id": RUN_ID,
        "workflow_run_attempt": RUN_ATTEMPT,
        "workflow_ref": "refs/heads/main",
        "built_at": "2026-08-13T12:00:00Z",
        "services": {
            "ingestor": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.ingestor-v2",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": INGESTOR_REPO,
                "image_digest": INGESTOR_DIGEST,
            },
            "multilevel-worker-a-production": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": WORKER_REPO,
                "image_digest": WORKER_DIGEST,
            },
            "multilevel-worker-b-production": {
                "source_kind": "build",
                "build_context": ".",
                "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
                "dockerfile_sha256": DOCKERFILE_SHA,
                "image_repository": WORKER_REPO,
                "image_digest": WORKER_DIGEST,
            },
        },
    }
    document.update(overrides)
    return document


class _Fakes:
    def __init__(
        self,
        *,
        run: dict[str, Any],
        inventory: dict[str, Any] | None,
        resolved_compose: dict[str, Any],
    ) -> None:
        self.run = run
        self.inventory = inventory
        self.resolved_compose = resolved_compose
        self.compose_calls: list[tuple[Path, str, tuple[str, ...], Path, Path]] = []

    def github_api_get(self, path: str) -> dict[str, Any]:
        run_path = f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"
        attempt_path = f"{run_path}/attempts/{RUN_ATTEMPT}"
        if path == run_path:
            return self.run
        if path == attempt_path:
            return self.run
        raise dii.DeploymentImageInventoryError(f"unexpected path in test: {path!r}")

    def download_artifact(self, run_id: int, artifact_name: str, dest_dir: Path) -> Path:
        if self.inventory is None:
            raise dii.DeploymentImageInventoryError("artifact not found (simulated)")
        path = dest_dir / dii._ARTIFACT_FILENAME
        path.write_text(json.dumps(self.inventory), encoding="utf-8")
        return path

    def run_docker_compose_config(
        self,
        repo_root: Path,
        source_commit_sha: str,
        compose_files: tuple[str, ...],
        work_dir: Path,
        env_file: Path,
    ) -> dict[str, Any]:
        self.compose_calls.append((repo_root, source_commit_sha, compose_files, work_dir, env_file))
        return self.resolved_compose


def _fake_git_show(repo_root: Path, commit_sha: str, relative_path: str) -> bytes:
    name = relative_path.rsplit("/", 1)[-1]
    if name in COMPOSE_CONTENTS:
        return COMPOSE_CONTENTS[name]
    raise AssertionError(f"unexpected git show path in test: {relative_path!r}")


def _env_file(tmp_path: Path) -> Path:
    path = tmp_path / "dummy.env"
    path.write_bytes(ENV_FILE_CONTENT)
    return path


def _materialize(
    fakes: _Fakes,
    tmp_path: Path,
    *,
    bundle_dir: Path | None = None,
    monkeypatch: pytest.MonkeyPatch,
    **overrides: Any,
) -> dict[str, Any]:
    monkeypatch.setattr(vri, "_git_show_bytes", _fake_git_show)
    kwargs: dict[str, Any] = dict(
        merge_sha=MERGE_SHA,
        merge_tree_sha=MERGE_TREE_SHA,
        provenance_run_id=RUN_ID,
        provenance_run_attempt=RUN_ATTEMPT,
        repo_root=tmp_path,
        env_file=_env_file(tmp_path),
        readiness_manifest_file=None,
        trust_anchor_file=None,
        environment="production",
        github_api_get=fakes.github_api_get,
        download_artifact=fakes.download_artifact,
        run_docker_compose_config=fakes.run_docker_compose_config,
        work_dir=tmp_path / "work",
        bundle_dir=bundle_dir or (tmp_path / "bundle"),
    )
    kwargs.update(overrides)
    return dep.materialize_verified_bundle(**kwargs)


class TestMaterializeVerifiedBundleHappyPath:
    def test_bundle_contains_every_compose_file_byte_identical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        _materialize(fakes, tmp_path, bundle_dir=bundle_dir, monkeypatch=monkeypatch)
        for name, content in COMPOSE_CONTENTS.items():
            assert (bundle_dir / name).read_bytes() == content

    def test_bundle_manifest_records_sha256_of_every_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hashlib

        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        document = _materialize(fakes, tmp_path, bundle_dir=bundle_dir, monkeypatch=monkeypatch)
        for name, content in COMPOSE_CONTENTS.items():
            assert document["files"][name] == hashlib.sha256(content).hexdigest()
        assert document["files"][".env"] == hashlib.sha256(ENV_FILE_CONTENT).hexdigest()

    def test_bundle_digest_is_present_and_deterministic_for_same_inputs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes1 = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        d1 = _materialize(fakes1, tmp_path, bundle_dir=tmp_path / "b1", monkeypatch=monkeypatch)

        fakes2 = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        d2 = _materialize(fakes2, tmp_path, bundle_dir=tmp_path / "b2", monkeypatch=monkeypatch)
        assert d1["bundle_digest"] == d2["bundle_digest"]

    def test_verified_images_are_the_provenance_verified_ones(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        document = _materialize(fakes, tmp_path, monkeypatch=monkeypatch)
        assert document["verified_images"]["ingestor"] == f"{INGESTOR_REPO}@{INGESTOR_DIGEST}"

    def test_readiness_manifest_not_included_when_not_supplied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        document = _materialize(fakes, tmp_path, bundle_dir=bundle_dir, monkeypatch=monkeypatch)
        assert document["readiness_manifest_included"] is False
        assert not (bundle_dir / "readiness-manifest.json").exists()


class TestMaterializeVerifiedBundleRefusals:
    def test_image_provenance_mismatch_aborts_before_any_bundle_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes = _Fakes(
            run=_run_document(),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(ingestor={"image": f"{INGESTOR_REPO}@sha256:" + "9" * 64}),
        )
        bundle_dir = tmp_path / "bundle"
        with pytest.raises(vri.ReleaseVerificationError, match="do not match verified provenance"):
            _materialize(fakes, tmp_path, bundle_dir=bundle_dir, monkeypatch=monkeypatch)
        assert not bundle_dir.exists()

    def test_failed_provenance_run_aborts_before_any_bundle_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes = _Fakes(
            run=_run_document(conclusion="failure"),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(),
        )
        bundle_dir = tmp_path / "bundle"
        with pytest.raises(vri.ReleaseVerificationError, match="successfully completed"):
            _materialize(fakes, tmp_path, bundle_dir=bundle_dir, monkeypatch=monkeypatch)
        assert not bundle_dir.exists()

    def test_existing_bundle_directory_is_never_silently_overwritten(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "sentinel").write_text("pre-existing", encoding="utf-8")
        with pytest.raises(dep.DeploymentWrapperError, match="already exists"):
            _materialize(fakes, tmp_path, bundle_dir=bundle_dir, monkeypatch=monkeypatch)
        assert (bundle_dir / "sentinel").read_text(encoding="utf-8") == "pre-existing"


def _manifest_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
        "repository": "cyranoaladin/RAG",
        "pr_number": 95,
        "pr_head_sha": "c" * 40,
        "pr_head_tree_sha": MERGE_TREE_SHA,
        "merge_sha": MERGE_SHA,
        "merge_tree_sha": MERGE_TREE_SHA,
        "release_tag": f"release/rag/20260814-{MERGE_SHA[:12]}",
        "environment": "production",
        "review_binding_digest": "11" * 32,
        "authorization_digest": "22" * 32,
        "trust_anchor_digest": "33" * 32,
        "revocation_registry_digest": "44" * 32,
        "catalog_digest": "55" * 32,
        "sealed_manifest_digest": "66" * 32,
        "h2b_report_digest": "77" * 32,
        "gate_result": "pass",
        "application_image_digests": {
            "ingestor": f"{INGESTOR_REPO}@{INGESTOR_DIGEST}",
        },
        "upstream_image_digests": {
            "pgvector": "pgvector/pgvector@sha256:" + "3" * 64,
        },
        "compose_digest": "88" * 32,
        "workflow_path": ".github/workflows/promote-rag-production.yml",
        "workflow_ref": "refs/heads/main",
        "run_id": 4242,
        "run_attempt": 1,
        "issued_at": datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        "key_id": KEY_ID,
    }
    fields.update(overrides)
    return fields


def _signed_manifest_bytes(**overrides: object) -> bytes:
    manifest = ProductionReadinessManifestV1(**_manifest_fields(**overrides))  # type: ignore[arg-type]
    return sign_production_readiness_manifest(
        manifest, private_key_hex=READINESS_SEED, key_id=KEY_ID
    ).canonical_bytes()


def _trust_anchor_bytes(*, key_id: str = KEY_ID, environment: str = "production") -> bytes:
    return json.dumps(
        {
            "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
            "keys": [
                {
                    "key_id": key_id,
                    "algorithm": "ed25519",
                    "public_key": public_readiness_key_hex(READINESS_SEED),
                    "environment": environment,
                }
            ],
        }
    ).encode("utf-8")


class TestReadinessManifestOptionalVerification:
    def test_no_manifest_supplied_is_accepted_and_omitted_from_bundle(self) -> None:
        result = dep.verify_readiness_manifest_if_supplied(
            readiness_manifest_raw=None,
            trust_anchor_raw=None,
            environment="production",
            merge_sha=MERGE_SHA,
        )
        assert result is None

    def test_valid_manifest_bound_to_merge_sha_is_accepted(self) -> None:
        result = dep.verify_readiness_manifest_if_supplied(
            readiness_manifest_raw=_signed_manifest_bytes(),
            trust_anchor_raw=_trust_anchor_bytes(),
            environment="production",
            merge_sha=MERGE_SHA,
        )
        assert result is not None
        assert result.merge_sha == MERGE_SHA

    def test_manifest_without_trust_anchor_is_refused(self) -> None:
        with pytest.raises(dep.DeploymentWrapperError, match="trust-anchor-file"):
            dep.verify_readiness_manifest_if_supplied(
                readiness_manifest_raw=_signed_manifest_bytes(),
                trust_anchor_raw=None,
                environment="production",
                merge_sha=MERGE_SHA,
            )

    def test_manifest_signed_for_a_different_merge_sha_is_refused(self) -> None:
        other_sha = "f" * 40
        with pytest.raises(dep.DeploymentWrapperError, match="rejected"):
            dep.verify_readiness_manifest_if_supplied(
                readiness_manifest_raw=_signed_manifest_bytes(
                    merge_sha=other_sha,
                    pr_head_tree_sha=MERGE_TREE_SHA,
                    release_tag=f"release/rag/20260814-{other_sha[:12]}",
                ),
                trust_anchor_raw=_trust_anchor_bytes(),
                environment="production",
                merge_sha=MERGE_SHA,
            )

    def test_manifest_with_non_passing_gate_result_is_refused(self) -> None:
        # gate_result is a Literal["pass"] on the contract itself -- this
        # proves the wrapper surfaces that rejection rather than masking it.
        with pytest.raises(dep.DeploymentWrapperError, match="rejected"):
            dep.verify_readiness_manifest_if_supplied(
                readiness_manifest_raw=_signed_manifest_bytes()[:-1] + b"}",
                trust_anchor_raw=_trust_anchor_bytes(),
                environment="production",
                merge_sha=MERGE_SHA,
            )

    def test_materialize_includes_readiness_manifest_bytes_in_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        manifest_path = tmp_path / "readiness-manifest.json"
        manifest_path.write_bytes(_signed_manifest_bytes())
        anchor_path = tmp_path / "trust-anchor.json"
        anchor_path.write_bytes(_trust_anchor_bytes())
        bundle_dir = tmp_path / "bundle"
        document = _materialize(
            fakes,
            tmp_path,
            bundle_dir=bundle_dir,
            monkeypatch=monkeypatch,
            readiness_manifest_file=manifest_path,
            trust_anchor_file=anchor_path,
        )
        assert document["readiness_manifest_included"] is True
        assert (bundle_dir / "readiness-manifest.json").read_bytes() == manifest_path.read_bytes()

    def test_materialize_refuses_manifest_for_wrong_merge_sha_before_writing_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        manifest_path = tmp_path / "readiness-manifest.json"
        manifest_path.write_bytes(
            _signed_manifest_bytes(
                merge_sha="f" * 40,
                pr_head_tree_sha=MERGE_TREE_SHA,
                release_tag=f"release/rag/20260814-{'f' * 12}",
            )
        )
        anchor_path = tmp_path / "trust-anchor.json"
        anchor_path.write_bytes(_trust_anchor_bytes())
        bundle_dir = tmp_path / "bundle"
        with pytest.raises(dep.DeploymentWrapperError, match="rejected"):
            _materialize(
                fakes,
                tmp_path,
                bundle_dir=bundle_dir,
                monkeypatch=monkeypatch,
                readiness_manifest_file=manifest_path,
                trust_anchor_file=anchor_path,
            )
        assert not bundle_dir.exists()


class TestDeployFromBundle:
    def _bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        _materialize(fakes, tmp_path, bundle_dir=bundle_dir, monkeypatch=monkeypatch)
        return bundle_dir

    def test_dry_run_returns_a_plan_and_runs_no_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle_dir = self._bundle(tmp_path, monkeypatch)
        calls: list[list[str]] = []

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            raise AssertionError("dry run must never invoke a subprocess")

        plan = dep.deploy_from_bundle(bundle_dir=bundle_dir, execute=False, run_subprocess=_run_subprocess)
        assert calls == []
        assert any("pull" in step for step in plan)
        assert any("up" in step for step in plan)
        assert all(str(bundle_dir) in step for step in plan)

    def test_execute_runs_pull_then_up_against_bundle_paths_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle_dir = self._bundle(tmp_path, monkeypatch)
        calls: list[list[str]] = []

        class _Result:
            returncode = 0
            stderr = ""

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            assert cwd == bundle_dir
            return _Result()

        dep.deploy_from_bundle(bundle_dir=bundle_dir, execute=True, run_subprocess=_run_subprocess)
        assert len(calls) == 2
        assert calls[0][-1] == "pull"
        assert calls[1][-2:] == ["up", "-d"] or "up" in calls[1]
        for call in calls:
            assert str(tmp_path / "services" / "rag-engine" / "infra") not in " ".join(call)
            assert str(bundle_dir) in " ".join(call)

    def test_pull_failure_aborts_before_up_is_ever_invoked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle_dir = self._bundle(tmp_path, monkeypatch)
        calls: list[list[str]] = []

        class _Failed:
            returncode = 1
            stderr = "pull failed (simulated)"

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            return _Failed()

        with pytest.raises(dep.DeploymentWrapperError, match="pull failed"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, execute=True, run_subprocess=_run_subprocess)
        assert len(calls) == 1

    def test_tampered_bundle_file_is_refused_before_any_subprocess_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bundle_dir = self._bundle(tmp_path, monkeypatch)
        (bundle_dir / "docker-compose.v2.yml").write_bytes(b"services:\n  tampered: {}\n")
        calls: list[list[str]] = []

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            raise AssertionError("must never run a subprocess against a tampered bundle")

        with pytest.raises(dep.DeploymentWrapperError, match="modified since materialization"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, execute=True, run_subprocess=_run_subprocess)
        assert calls == []

    def test_missing_bundle_manifest_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "not-a-bundle"
        bundle_dir.mkdir()
        with pytest.raises(dep.DeploymentWrapperError, match="is missing"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, execute=False)
