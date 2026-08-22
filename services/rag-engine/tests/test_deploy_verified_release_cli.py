"""Tests -- wrapper de déploiement atomique (Lot C, ferme la fenêtre TOCTOU
documentée dans `verify_release_image_provenance_cli.py`, PR #105).

Aucun vrai `docker`, `git`, `gh`, ni réseau dans cette suite unitaire :
toutes les frontières (`github_api_get`/`download_artifact`/
`run_docker_compose_config`/`git_show_bytes`/`run_subprocess`/
`list_running_containers`) sont des doubles injectés explicitement, comme
dans la suite sœur `test_verify_release_image_provenance_cli.py`. Une
suite séparée à la fin (`TestRealDockerRehearsal`) exerce un vrai
`docker compose` isolé de la production -- skip si Docker est absent.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
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
    PRODUCTION_READINESS_V2_PROTOCOL_VERSION,
    ProductionReadinessManifestV1,
    ProductionReadinessManifestV2,
    public_readiness_key_hex,
    sign_production_readiness_manifest,
    sign_production_readiness_manifest_v2,
)

from tests.test_verify_release_image_provenance_cli import (  # noqa: E402
    _dummy_compose_env,
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

EXPECTED_SERVICES = (
    "ingestor",
    "multilevel-worker-a-production",
    "multilevel-worker-b-production",
)


def _resolved_compose(**per_service_overrides: dict[str, Any]) -> dict[str, Any]:
    services: dict[str, Any] = {
        "ingestor": {"image": f"{INGESTOR_REPO}@{INGESTOR_DIGEST}"},
        "multilevel-worker-a-production": {"image": f"{WORKER_REPO}@{WORKER_DIGEST}"},
        "multilevel-worker-b-production": {"image": f"{WORKER_REPO}@{WORKER_DIGEST}"},
        "pgvector": {"image": "pgvector/pgvector@sha256:" + "9" * 64},
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
    **overrides: Any,
) -> dict[str, Any]:
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
        git_show_bytes=_fake_git_show,
    )
    kwargs.update(overrides)
    return dep.materialize_verified_bundle(**kwargs)


class TestMaterializeVerifiedBundleHappyPath:
    def test_bundle_contains_every_compose_file_byte_identical(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
        for name, content in COMPOSE_CONTENTS.items():
            assert (bundle_dir / name).read_bytes() == content

    def test_bundle_contains_resolved_compose_and_image_provenance_evidence(
        self, tmp_path: Path
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
        resolved = json.loads((bundle_dir / "resolved-compose.json").read_bytes())
        assert resolved == _resolved_compose()
        evidence = json.loads((bundle_dir / "image-provenance-evidence.json").read_bytes())
        assert evidence == _inventory_document()

    def test_bundle_manifest_records_sha256_of_every_file(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        document = _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
        for name in list(COMPOSE_CONTENTS) + [
            ".env",
            "resolved-compose.json",
            "image-provenance-evidence.json",
        ]:
            path = bundle_dir / name
            assert document["files"][name] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert "readiness-manifest.json" not in document["files"]

    def test_bundle_digest_is_present_and_deterministic_for_same_inputs(
        self, tmp_path: Path
    ) -> None:
        fakes1 = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        d1 = _materialize(fakes1, tmp_path, bundle_dir=tmp_path / "b1")

        fakes2 = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        d2 = _materialize(fakes2, tmp_path, bundle_dir=tmp_path / "b2")
        assert d1["bundle_digest"] == d2["bundle_digest"]

    def test_verified_images_are_the_provenance_verified_ones(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        document = _materialize(fakes, tmp_path)
        assert document["verified_images"]["ingestor"] == f"{INGESTOR_REPO}@{INGESTOR_DIGEST}"

    def test_explicit_services_come_from_the_resolved_compose_not_a_hardcoded_list(
        self, tmp_path: Path
    ) -> None:
        fakes = _Fakes(
            run=_run_document(),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(prometheus={"image": "prom/prometheus@sha256:" + "7" * 64}),
        )
        document = _materialize(fakes, tmp_path)
        assert set(document["explicit_services"]) == {*EXPECTED_SERVICES, "pgvector", "prometheus"}

    def test_readiness_manifest_not_included_when_not_supplied(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        document = _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
        assert document["readiness_manifest_included"] is False
        assert not (bundle_dir / "readiness-manifest.json").exists()


class TestMaterializeVerifiedBundleRefusals:
    def test_image_provenance_mismatch_aborts_before_any_bundle_write(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(ingestor={"image": f"{INGESTOR_REPO}@sha256:" + "9" * 64}),
        )
        bundle_dir = tmp_path / "bundle"
        with pytest.raises(vri.ReleaseVerificationError, match="do not match verified provenance"):
            _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
        assert not bundle_dir.exists()

    def test_failed_provenance_run_aborts_before_any_bundle_write(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(conclusion="failure"),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(),
        )
        bundle_dir = tmp_path / "bundle"
        with pytest.raises(vri.ReleaseVerificationError, match="successfully completed"):
            _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
        assert not bundle_dir.exists()

    def test_existing_bundle_directory_is_never_silently_overwritten(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        (bundle_dir / "sentinel").write_text("pre-existing", encoding="utf-8")
        with pytest.raises(dep.DeploymentWrapperError, match="already exists"):
            _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
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


def _manifest_v2_fields(**overrides: object) -> dict[str, object]:
    fields = _manifest_fields(**overrides)
    fields["protocol_version"] = PRODUCTION_READINESS_V2_PROTOCOL_VERSION
    del fields["review_binding_digest"]
    del fields["authorization_digest"]
    fields["authorization_set_digest"] = "22" * 32
    return fields


def _signed_manifest_v2_bytes(**overrides: object) -> bytes:
    manifest = ProductionReadinessManifestV2(**_manifest_v2_fields(**overrides))  # type: ignore[arg-type]
    return sign_production_readiness_manifest_v2(
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


#: Digest du Compose résolu par défaut de ces tests (`_resolved_compose()`)
#: -- calculé une fois avec la même primitive partagée que le wrapper
#: (`vri.canonical_resolved_compose_bytes`), jamais recopié à la main :
#: un manifeste de test signé avec ce digest est un manifeste dont la
#: liaison `compose_digest` réussit réellement contre `_resolved_compose()`.
RESOLVED_COMPOSE_DIGEST = hashlib.sha256(
    vri.canonical_resolved_compose_bytes(_resolved_compose())
).hexdigest()


class TestReadinessManifestOptionalVerification:
    def test_no_manifest_supplied_is_accepted_and_omitted_from_bundle(self) -> None:
        result = dep.verify_readiness_manifest_if_supplied(
            readiness_manifest_raw=None,
            trust_anchor_raw=None,
            environment="production",
            merge_sha=MERGE_SHA,
            resolved_compose_digest=RESOLVED_COMPOSE_DIGEST,
        )
        assert result is None

    def test_valid_manifest_bound_to_merge_sha_and_compose_digest_is_accepted(self) -> None:
        result = dep.verify_readiness_manifest_if_supplied(
            readiness_manifest_raw=_signed_manifest_bytes(compose_digest=RESOLVED_COMPOSE_DIGEST),
            trust_anchor_raw=_trust_anchor_bytes(),
            environment="production",
            merge_sha=MERGE_SHA,
            resolved_compose_digest=RESOLVED_COMPOSE_DIGEST,
        )
        assert result is not None
        assert result.merge_sha == MERGE_SHA
        assert result.compose_digest == RESOLVED_COMPOSE_DIGEST

    def test_valid_v2_manifest_bound_to_merge_sha_and_compose_digest_is_accepted(self) -> None:
        """ADR-0044 : le vérificateur accepte NEXUS-PRODUCTION-READINESS-V2
        (ensemble d'autorisations) en plus de V1 — même ancre, dispatch par
        ``protocol_version`` uniquement."""
        result = dep.verify_readiness_manifest_if_supplied(
            readiness_manifest_raw=_signed_manifest_v2_bytes(compose_digest=RESOLVED_COMPOSE_DIGEST),
            trust_anchor_raw=_trust_anchor_bytes(),
            environment="production",
            merge_sha=MERGE_SHA,
            resolved_compose_digest=RESOLVED_COMPOSE_DIGEST,
        )
        assert result is not None
        assert isinstance(result, ProductionReadinessManifestV2)
        assert result.merge_sha == MERGE_SHA
        assert result.compose_digest == RESOLVED_COMPOSE_DIGEST

    def test_manifest_with_unrecognized_protocol_version_is_refused(self) -> None:
        v1_bytes = _signed_manifest_bytes(compose_digest=RESOLVED_COMPOSE_DIGEST)
        document = json.loads(v1_bytes)
        document["manifest"]["protocol_version"] = "NEXUS-PRODUCTION-READINESS-V9"
        tampered = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with pytest.raises(dep.DeploymentWrapperError, match="protocol_version is not"):
            dep.verify_readiness_manifest_if_supplied(
                readiness_manifest_raw=tampered,
                trust_anchor_raw=_trust_anchor_bytes(),
                environment="production",
                merge_sha=MERGE_SHA,
                resolved_compose_digest=RESOLVED_COMPOSE_DIGEST,
            )

    def test_manifest_signed_for_a_different_compose_digest_is_refused(self) -> None:
        # PR #107 round 2: compose_digest=None is gone -- a manifest signed
        # for a different resolved Compose than the one this wrapper just
        # resolved is refused, never silently ignored.
        with pytest.raises(dep.DeploymentWrapperError, match="rejected"):
            dep.verify_readiness_manifest_if_supplied(
                readiness_manifest_raw=_signed_manifest_bytes(compose_digest="99" * 32),
                trust_anchor_raw=_trust_anchor_bytes(),
                environment="production",
                merge_sha=MERGE_SHA,
                resolved_compose_digest=RESOLVED_COMPOSE_DIGEST,
            )

    def test_manifest_without_trust_anchor_is_refused(self) -> None:
        with pytest.raises(dep.DeploymentWrapperError, match="trust-anchor-file"):
            dep.verify_readiness_manifest_if_supplied(
                readiness_manifest_raw=_signed_manifest_bytes(compose_digest=RESOLVED_COMPOSE_DIGEST),
                trust_anchor_raw=None,
                environment="production",
                merge_sha=MERGE_SHA,
                resolved_compose_digest=RESOLVED_COMPOSE_DIGEST,
            )

    def test_manifest_signed_for_a_different_merge_sha_is_refused(self) -> None:
        other_sha = "f" * 40
        with pytest.raises(dep.DeploymentWrapperError, match="rejected"):
            dep.verify_readiness_manifest_if_supplied(
                readiness_manifest_raw=_signed_manifest_bytes(
                    merge_sha=other_sha,
                    pr_head_tree_sha=MERGE_TREE_SHA,
                    release_tag=f"release/rag/20260814-{other_sha[:12]}",
                    compose_digest=RESOLVED_COMPOSE_DIGEST,
                ),
                trust_anchor_raw=_trust_anchor_bytes(),
                environment="production",
                merge_sha=MERGE_SHA,
                resolved_compose_digest=RESOLVED_COMPOSE_DIGEST,
            )

    def test_manifest_with_non_passing_gate_result_is_refused(self) -> None:
        # gate_result is a Literal["pass"] on the contract itself -- this
        # proves the wrapper surfaces that rejection rather than masking it.
        with pytest.raises(dep.DeploymentWrapperError, match="rejected"):
            dep.verify_readiness_manifest_if_supplied(
                readiness_manifest_raw=_signed_manifest_bytes(compose_digest=RESOLVED_COMPOSE_DIGEST)[
                    :-1
                ]
                + b"}",
                trust_anchor_raw=_trust_anchor_bytes(),
                environment="production",
                merge_sha=MERGE_SHA,
                resolved_compose_digest=RESOLVED_COMPOSE_DIGEST,
            )

    def test_materialize_includes_readiness_manifest_bytes_in_bundle(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        manifest_path = tmp_path / "readiness-manifest.json"
        manifest_path.write_bytes(_signed_manifest_bytes(compose_digest=RESOLVED_COMPOSE_DIGEST))
        anchor_path = tmp_path / "trust-anchor.json"
        anchor_path.write_bytes(_trust_anchor_bytes())
        bundle_dir = tmp_path / "bundle"
        document = _materialize(
            fakes,
            tmp_path,
            bundle_dir=bundle_dir,
            readiness_manifest_file=manifest_path,
            trust_anchor_file=anchor_path,
        )
        assert document["readiness_manifest_included"] is True
        assert (bundle_dir / "readiness-manifest.json").read_bytes() == manifest_path.read_bytes()

    def test_materialize_refuses_manifest_for_wrong_merge_sha_before_writing_bundle(
        self, tmp_path: Path
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
                compose_digest=RESOLVED_COMPOSE_DIGEST,
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
                readiness_manifest_file=manifest_path,
                trust_anchor_file=anchor_path,
            )
        assert not bundle_dir.exists()

    def test_materialize_refuses_manifest_for_wrong_compose_digest_before_writing_bundle(
        self, tmp_path: Path
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        manifest_path = tmp_path / "readiness-manifest.json"
        manifest_path.write_bytes(_signed_manifest_bytes(compose_digest="99" * 32))
        anchor_path = tmp_path / "trust-anchor.json"
        anchor_path.write_bytes(_trust_anchor_bytes())
        bundle_dir = tmp_path / "bundle"
        with pytest.raises(dep.DeploymentWrapperError, match="rejected"):
            _materialize(
                fakes,
                tmp_path,
                bundle_dir=bundle_dir,
                readiness_manifest_file=manifest_path,
                trust_anchor_file=anchor_path,
            )
        assert not bundle_dir.exists()


class TestDeployFromBundle:
    def _bundle(self, tmp_path: Path) -> Path:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
        return bundle_dir

    def test_dry_run_returns_a_plan_and_runs_no_subprocess(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        calls: list[list[str]] = []

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            raise AssertionError("dry run must never invoke a subprocess")

        plan = dep.deploy_from_bundle(
            bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False, run_subprocess=_run_subprocess
        )
        assert calls == []
        assert any("pull" in step for step in plan)
        assert any("up" in step for step in plan)
        assert all(str(bundle_dir) in step for step in plan)
        for name in EXPECTED_SERVICES:
            assert any(name in step for step in plan)

    def test_execute_runs_pull_then_up_with_explicit_services_against_bundle_paths_only(
        self, tmp_path: Path
    ) -> None:
        bundle_dir = self._bundle(tmp_path)
        calls: list[list[str]] = []

        class _Result:
            returncode = 0
            stderr = ""

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            assert cwd == bundle_dir
            return _Result()

        dep.deploy_from_bundle(
            bundle_dir=bundle_dir,
            merge_sha=MERGE_SHA,
            execute=True,
            run_subprocess=_run_subprocess,
            list_running_containers=lambda: [],
        )
        assert len(calls) == 2
        expected_services = sorted({*EXPECTED_SERVICES, "pgvector"})
        assert calls[0][calls[0].index("pull") + 1 :] == expected_services
        assert calls[1][calls[1].index("up") + 1 :] == ["-d", *expected_services]
        for call in calls:
            joined = " ".join(call)
            assert str(tmp_path / "services" / "rag-engine" / "infra") not in joined
            assert str(bundle_dir) in joined
            assert "--remove-orphans" not in call

    def test_pull_failure_aborts_before_up_is_ever_invoked(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        calls: list[list[str]] = []

        class _Failed:
            returncode = 1
            stderr = "pull failed (simulated)"

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            return _Failed()

        with pytest.raises(dep.DeploymentWrapperError, match="pull failed"):
            dep.deploy_from_bundle(
                bundle_dir=bundle_dir,
                merge_sha=MERGE_SHA,
                execute=True,
                run_subprocess=_run_subprocess,
                list_running_containers=lambda: [],
            )
        assert len(calls) == 1

    def test_tampered_bundle_file_is_refused_before_any_subprocess_runs(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        (bundle_dir / "docker-compose.v2.yml").write_bytes(b"services:\n  tampered: {}\n")
        calls: list[list[str]] = []

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            raise AssertionError("must never run a subprocess against a tampered bundle")

        with pytest.raises(dep.DeploymentWrapperError, match="modified since materialization"):
            dep.deploy_from_bundle(
                bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=True, run_subprocess=_run_subprocess
            )
        assert calls == []

    def test_tampered_env_file_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        (bundle_dir / ".env").write_bytes(b"TAMPERED=true\n")
        with pytest.raises(dep.DeploymentWrapperError, match="modified since materialization"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False)

    def test_tampered_resolved_compose_json_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        (bundle_dir / "resolved-compose.json").write_bytes(b'{"services": {}}')
        with pytest.raises(dep.DeploymentWrapperError, match="modified since materialization"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False)

    def test_tampered_image_provenance_evidence_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        (bundle_dir / "image-provenance-evidence.json").write_bytes(b"{}")
        with pytest.raises(dep.DeploymentWrapperError, match="modified since materialization"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False)

    def test_unexpected_extra_file_in_bundle_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        (bundle_dir / "unexpected-extra-file").write_text("sneaky", encoding="utf-8")
        with pytest.raises(dep.DeploymentWrapperError, match="unexpected file"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False)

    def test_bundle_for_a_different_merge_sha_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        with pytest.raises(dep.DeploymentWrapperError, match="not the commit currently being deployed"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha="f" * 40, execute=False)

    def test_bundle_manifest_wrong_protocol_version_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        manifest_path = bundle_dir / "bundle_manifest.json"
        document = json.loads(manifest_path.read_bytes())
        document["protocol_version"] = "SOMETHING-ELSE-V1"
        manifest_path.write_bytes(json.dumps(document).encode("utf-8"))
        with pytest.raises(dep.DeploymentWrapperError, match="protocol_version"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False)

    def test_bundle_manifest_wrong_repository_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        manifest_path = bundle_dir / "bundle_manifest.json"
        document = json.loads(manifest_path.read_bytes())
        document["repository"] = "someone-else/fork"
        manifest_path.write_bytes(json.dumps(document).encode("utf-8"))
        with pytest.raises(dep.DeploymentWrapperError, match="repository"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False)

    def test_malformed_bundle_manifest_json_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)
        (bundle_dir / "bundle_manifest.json").write_bytes(b"not json{{{")
        with pytest.raises(dep.DeploymentWrapperError, match="not valid JSON"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False)

    def test_missing_bundle_manifest_is_refused(self, tmp_path: Path) -> None:
        bundle_dir = tmp_path / "not-a-bundle"
        bundle_dir.mkdir()
        with pytest.raises(dep.DeploymentWrapperError, match="is missing"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=MERGE_SHA, execute=False)


class TestLabelSafetyBeforeMutation:
    def _bundle(self, tmp_path: Path) -> Path:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        bundle_dir = tmp_path / "bundle"
        _materialize(fakes, tmp_path, bundle_dir=bundle_dir)
        return bundle_dir

    def test_foreign_container_with_colliding_service_name_refuses_before_any_mutation(
        self, tmp_path: Path
    ) -> None:
        bundle_dir = self._bundle(tmp_path)
        calls: list[list[str]] = []

        def _run_subprocess(args: list[str], cwd: Path) -> Any:
            calls.append(args)
            raise AssertionError("must never mutate when a foreign container collides")

        foreign = dep.RunningContainerInfo(
            container_id="deadbeef",
            service="ingestor",
            project="infra",
            config_files="/some/other/stack/docker-compose.yml",
            working_dir="/some/other/stack",
        )
        with pytest.raises(dep.DeploymentWrapperError, match="does not recognizably belong"):
            dep.deploy_from_bundle(
                bundle_dir=bundle_dir,
                merge_sha=MERGE_SHA,
                execute=True,
                run_subprocess=_run_subprocess,
                list_running_containers=lambda: [foreign],
            )
        assert calls == []

    def test_container_already_running_from_the_same_bundle_working_dir_is_not_a_collision(
        self, tmp_path: Path
    ) -> None:
        bundle_dir = self._bundle(tmp_path)

        class _Result:
            returncode = 0
            stderr = ""

        own = dep.RunningContainerInfo(
            container_id="cafef00d",
            service="ingestor",
            project="infra",
            config_files=str(bundle_dir / "docker-compose.v2.yml"),
            working_dir=str(bundle_dir),
        )
        dep.deploy_from_bundle(
            bundle_dir=bundle_dir,
            merge_sha=MERGE_SHA,
            execute=True,
            run_subprocess=lambda args, cwd: _Result(),
            list_running_containers=lambda: [own],
        )  # must not raise

    def test_unrelated_service_name_running_elsewhere_is_not_a_collision(self, tmp_path: Path) -> None:
        bundle_dir = self._bundle(tmp_path)

        class _Result:
            returncode = 0
            stderr = ""

        unrelated = dep.RunningContainerInfo(
            container_id="0ff1ce",
            service="some-other-non-rag-service",
            project="infra",
            config_files="/some/other/stack/docker-compose.yml",
            working_dir="/some/other/stack",
        )
        dep.deploy_from_bundle(
            bundle_dir=bundle_dir,
            merge_sha=MERGE_SHA,
            execute=True,
            run_subprocess=lambda args, cwd: _Result(),
            list_running_containers=lambda: [unrelated],
        )  # must not raise


class TestNoRemoveOrphansAnywhereInTheModule:
    def test_remove_orphans_string_never_appears_in_the_module_source(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "scripts" / "deploy_verified_release_cli.py"
        ).read_text()
        assert "--remove-orphans" not in source
        assert "remove_orphans" not in source
        assert "remove-orphans" not in source


class TestMainRequiresReadinessManifestForExecute:
    def test_execute_without_readiness_manifest_is_refused_before_any_work(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = dep.main(
            [
                "--merge-sha", MERGE_SHA,
                "--merge-tree-sha", MERGE_TREE_SHA,
                "--provenance-run-id", str(RUN_ID),
                "--provenance-run-attempt", str(RUN_ATTEMPT),
                "--repo-root", str(tmp_path),
                "--bundle-dir", str(tmp_path / "bundle"),
                "--execute",
            ]
        )
        assert code == 1
        # Message spécifique au refus précoce, jamais confondu avec un
        # refus tardif générique (les deux impriment "REFUSED:" -- une
        # assertion sur ce seul préfixe passerait même si le refus précoce
        # était contourné et qu'une erreur réseau/git en aval échouait
        # pour une tout autre raison ; trouvé par mutation-testing).
        assert "requires both --readiness-manifest-file and --trust-anchor-file" in (
            capsys.readouterr().err
        )
        assert not (tmp_path / "bundle").exists()

    def test_execute_with_manifest_but_without_trust_anchor_is_refused_before_any_work(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest_path = tmp_path / "readiness-manifest.json"
        manifest_path.write_bytes(_signed_manifest_bytes(compose_digest=RESOLVED_COMPOSE_DIGEST))
        code = dep.main(
            [
                "--merge-sha", MERGE_SHA,
                "--merge-tree-sha", MERGE_TREE_SHA,
                "--provenance-run-id", str(RUN_ID),
                "--provenance-run-attempt", str(RUN_ATTEMPT),
                "--repo-root", str(tmp_path),
                "--bundle-dir", str(tmp_path / "bundle"),
                "--readiness-manifest-file", str(manifest_path),
                "--execute",
            ]
        )
        assert code == 1
        assert "requires both --readiness-manifest-file and --trust-anchor-file" in (
            capsys.readouterr().err
        )
        assert not (tmp_path / "bundle").exists()

    def test_dry_run_without_readiness_manifest_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        (tmp_path / "services" / "rag-engine" / "infra").mkdir(parents=True)
        (tmp_path / "services" / "rag-engine" / "infra" / ".env").write_bytes(ENV_FILE_CONTENT)
        monkeypatch.setattr(dep.dii, "gh_api_get", fakes.github_api_get)
        monkeypatch.setattr(
            dep.dii, "make_download_artifact_via_gh", lambda *, repository: fakes.download_artifact
        )
        monkeypatch.setattr(dep.vri, "run_docker_compose_config_via_subprocess", fakes.run_docker_compose_config)
        monkeypatch.setattr(dep.vri, "_git_show_bytes", _fake_git_show)
        code = dep.main(
            [
                "--merge-sha", MERGE_SHA,
                "--merge-tree-sha", MERGE_TREE_SHA,
                "--provenance-run-id", str(RUN_ID),
                "--provenance-run-attempt", str(RUN_ATTEMPT),
                "--repo-root", str(tmp_path),
                "--bundle-dir", str(tmp_path / "bundle"),
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "DEPLOYED=false" in out
        assert "SIGNED_COMPOSE_DIGEST_MATCH" not in out


class TestRealDockerRehearsal:
    """Rehearsal isolé, contre un vrai `docker compose`/`git show` -- jamais
    la production réelle : project name/bundle dir dédiés au test, images
    placeholder jamais construites/poussées, `--execute` jamais exercé
    contre un vrai `docker compose up` (seul le côté vérification/
    matérialisation/refus est prouvé avec de vrais binaires ; `pull`/`up`
    restent des doubles même ici, pour ne jamais risquer de contacter un
    registre réel depuis cette suite)."""

    requires_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not available")
    requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")

    @requires_docker
    @requires_git
    def test_real_compose_resolution_and_bundle_materialization_round_trip(
        self, tmp_path: Path
    ) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        env_file = tmp_path / "real.env"
        # Réutilise le même dérivateur que la suite sœur
        # (test_verify_release_image_provenance_cli._dummy_compose_env) :
        # valeurs factices non vides pour TOUTES les variables requises,
        # dérivées dynamiquement des vrais fichiers Compose -- jamais une
        # liste partielle recopiée à la main qui pourrait diverger sans
        # que ce test ne le remarque, jamais un `.env` de production réel.
        env_values = dict(_dummy_compose_env())
        env_values["COMPOSE_PROJECT_NAME"] = "nexus-lotc-rehearsal"
        env_file.write_text(
            "\n".join(f"{name}={value}" for name, value in env_values.items()) + "\n",
            encoding="utf-8",
        )
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout.strip()

        fakes = _Fakes(
            run=_run_document(head_sha=head_sha),
            inventory=_inventory_document(source_commit_sha=head_sha),
            resolved_compose={},  # unused: real resolution below replaces this fake path
        )
        bundle_dir = tmp_path / "bundle"
        try:
            document = dep.materialize_verified_bundle(
                merge_sha=head_sha,
                merge_tree_sha=MERGE_TREE_SHA,
                provenance_run_id=RUN_ID,
                provenance_run_attempt=RUN_ATTEMPT,
                repo_root=repo_root,
                env_file=env_file,
                readiness_manifest_file=None,
                trust_anchor_file=None,
                environment="production",
                github_api_get=fakes.github_api_get,
                download_artifact=fakes.download_artifact,
                run_docker_compose_config=vri.run_docker_compose_config_via_subprocess,
                work_dir=tmp_path / "work",
                bundle_dir=bundle_dir,
            )
        except (dep.DeploymentWrapperError, vri.ReleaseVerificationError) as exc:
            pytest.fail(
                f"real docker compose config / git show resolution failed: {exc} -- "
                "the real committed Compose files no longer resolve with these "
                "empirically-derived dummy env values, or docker/git themselves "
                "are misbehaving in this environment"
            )
        # Bytes matérialisés = octets réellement vérifiés (fix TOCTOU
        # résiduel, item 4/9) : aucune seconde résolution.
        assert (bundle_dir / "docker-compose.v2.yml").is_file()
        assert (bundle_dir / ".env").read_bytes() == env_file.read_bytes()
        resolved_on_disk = json.loads((bundle_dir / "resolved-compose.json").read_bytes())
        assert set(resolved_on_disk["services"]) == set(document["explicit_services"])

        # Round-trip : deploy_from_bundle en dry-run ne lance aucun
        # sous-processus mutant, et le plan référence bien tous les
        # services explicites, jamais --remove-orphans.
        plan = dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=head_sha, execute=False)
        assert all("--remove-orphans" not in step for step in plan)
        for name in document["explicit_services"]:
            assert any(name in step for step in plan)

        # Un digest de bundle tamponné est refusé même côté réel.
        (bundle_dir / "docker-compose.v2.yml").write_bytes(b"services:\n  tampered: {}\n")
        with pytest.raises(dep.DeploymentWrapperError, match="modified since materialization"):
            dep.deploy_from_bundle(bundle_dir=bundle_dir, merge_sha=head_sha, execute=False)
