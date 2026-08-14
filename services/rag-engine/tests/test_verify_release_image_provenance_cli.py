"""Tests -- vérificateur hôte pré-déploiement (ADR-0036 phase B, Lot B).

Deux frontières réseau/processus (``github_api_get``/``download_artifact``,
hérités de ``deployment_image_inventory``) et une troisième propre à ce
module (``run_docker_compose_config``) sont des doubles injectés
explicitement -- jamais un vrai ``gh`` ni un vrai ``docker`` dans ces
tests unitaires. Une suite séparée, plus bas, exerce le vrai binaire
``docker compose`` et le vrai ``git show`` contre les fichiers réellement
commités (skip si Docker est absent -- jamais un vert non démontré).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deployment_image_inventory as dii  # noqa: E402
import verify_release_image_provenance_cli as vri  # noqa: E402

REPOSITORY = vri._CANONICAL_REPOSITORY
RUN_ID = 777
RUN_ATTEMPT = 1
SOURCE_COMMIT_SHA = "a" * 40
SOURCE_TREE_SHA = "b" * 40
WORKFLOW_PATH = ".github/workflows/production-image-provenance.yml"

INGESTOR_DIGEST = "sha256:" + "1" * 64
WORKER_DIGEST = "sha256:" + "2" * 64
DOCKERFILE_SHA = "3" * 64

INGESTOR_REPO = "ghcr.io/cyranoaladin/rag-ingestor"
WORKER_REPO = "ghcr.io/cyranoaladin/rag-multilevel-worker-production"

EXPECTED_SERVICES = (
    "ingestor",
    "multilevel-worker-a-production",
    "multilevel-worker-b-production",
)


def _provenance_images(**overrides: str) -> dict[str, str]:
    images = {
        "ingestor": f"{INGESTOR_REPO}@{INGESTOR_DIGEST}",
        "multilevel-worker-a-production": f"{WORKER_REPO}@{WORKER_DIGEST}",
        "multilevel-worker-b-production": f"{WORKER_REPO}@{WORKER_DIGEST}",
    }
    images.update(overrides)
    return images


def _pinned_images(**overrides: str) -> dict[str, str]:
    return _provenance_images(**overrides)


class TestCanonicalRepositoryIsNeverOperatorControlled:
    def test_no_repository_cli_flag_exists(self) -> None:
        # Codex P1 (PR #105): a --repository flag would let a routine
        # operator anchor provenance verification on a repository they
        # control. Proven both statically (no such flag) and by the
        # module constant being the sole source of truth (used below).
        help_text = vri._build_arg_parser().format_help()
        assert "--repository" not in help_text

    def test_canonical_repository_constant_is_the_real_repo(self) -> None:
        assert vri._CANONICAL_REPOSITORY == "cyranoaladin/RAG"


class TestRequirePinnedImagesMatchVerifiedProvenance:
    def test_matching_digests_are_accepted(self) -> None:
        result = vri.require_pinned_images_match_verified_provenance(
            pinned_images=_pinned_images(), provenance_images=_provenance_images()
        )
        assert result == _provenance_images()

    def test_mismatched_digest_for_one_service_is_refused(self) -> None:
        pinned = _pinned_images(ingestor=f"{INGESTOR_REPO}@sha256:" + "9" * 64)
        with pytest.raises(vri.ReleaseVerificationError, match="do not match verified provenance"):
            vri.require_pinned_images_match_verified_provenance(
                pinned_images=pinned, provenance_images=_provenance_images()
            )

    def test_different_service_sets_are_refused(self) -> None:
        pinned = _pinned_images()
        del pinned["multilevel-worker-b-production"]
        with pytest.raises(vri.ReleaseVerificationError, match="do not name the same services"):
            vri.require_pinned_images_match_verified_provenance(
                pinned_images=pinned, provenance_images=_provenance_images()
            )

    def test_a_correctly_formed_but_unrelated_digest_is_refused(self) -> None:
        # A digest that is validly formed and genuinely digest-pinned, but
        # was never produced by the canonical provenance workflow for this
        # exact commit -- require_resolved_compose_images_are_pinned alone
        # would accept it; this function is the guard that does not.
        pinned = _pinned_images(
            **{"multilevel-worker-a-production": f"{WORKER_REPO}@sha256:" + "7" * 64}
        )
        with pytest.raises(vri.ReleaseVerificationError, match="multilevel-worker-a-production"):
            vri.require_pinned_images_match_verified_provenance(
                pinned_images=pinned, provenance_images=_provenance_images()
            )


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
        "head_sha": SOURCE_COMMIT_SHA,
        "run_attempt": RUN_ATTEMPT,
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
        attempt_exists: bool = True,
    ) -> None:
        self.run = run
        self.inventory = inventory
        self.resolved_compose = resolved_compose
        self.attempt_exists = attempt_exists
        self.compose_calls: list[tuple[Path, str, tuple[str, ...], Path]] = []

    def github_api_get(self, path: str) -> dict[str, Any]:
        run_path = f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"
        attempt_path = f"{run_path}/attempts/{RUN_ATTEMPT}"
        if path == run_path:
            return self.run
        if path == attempt_path:
            if not self.attempt_exists:
                raise dii.DeploymentImageInventoryError(f"attempt not found (simulated): {path!r}")
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


def _verify(fakes: _Fakes, tmp_path: Path, **overrides: Any) -> dict[str, str]:
    kwargs: dict[str, Any] = dict(
        source_commit_sha=SOURCE_COMMIT_SHA,
        source_tree_sha=SOURCE_TREE_SHA,
        provenance_run_id=RUN_ID,
        provenance_run_attempt=RUN_ATTEMPT,
        repo_root=tmp_path,
        compose_files=vri._CANONICAL_COMPOSE_FILES,
        env_file=tmp_path / "dummy.env",
        github_api_get=fakes.github_api_get,
        download_artifact=fakes.download_artifact,
        run_docker_compose_config=fakes.run_docker_compose_config,
        work_dir=tmp_path,
    )
    kwargs.update(overrides)
    return vri.verify_release_images(**kwargs)


class TestVerifyReleaseImagesEndToEnd:
    def test_matching_compose_and_provenance_is_accepted(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        result = _verify(fakes, tmp_path)
        assert set(result) == set(EXPECTED_SERVICES)
        assert result["ingestor"] == f"{INGESTOR_REPO}@{INGESTOR_DIGEST}"

    def test_calls_docker_compose_config_with_the_canonical_files_and_commit(
        self, tmp_path: Path
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        _verify(fakes, tmp_path)
        assert fakes.compose_calls == [
            (tmp_path, SOURCE_COMMIT_SHA, vri._CANONICAL_COMPOSE_FILES, tmp_path, tmp_path / "dummy.env")
        ]

    def test_provenance_is_always_anchored_on_the_canonical_repository(self, tmp_path: Path) -> None:
        # Codex P1 (PR #105): the caller can no longer supply an arbitrary
        # --repository -- verify_release_images always anchors on the
        # module constant, proven here by a run/inventory keyed on it.
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        result = _verify(fakes, tmp_path)
        assert result  # would have raised via github_api_get's path check otherwise

    def test_mutable_tag_in_resolved_compose_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(ingestor={"image": f"{INGESTOR_REPO}:latest"}),
        )
        with pytest.raises(vri.ReleaseVerificationError, match="not pinned by digest"):
            _verify(fakes, tmp_path)

    def test_residual_build_key_in_resolved_compose_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(
                ingestor={"image": f"{INGESTOR_REPO}@{INGESTOR_DIGEST}", "build": {}}
            ),
        )
        with pytest.raises(vri.ReleaseVerificationError, match="still resolves with a 'build'"):
            _verify(fakes, tmp_path)

    def test_failed_provenance_run_is_refused(self, tmp_path: Path) -> None:
        fakes = _Fakes(
            run=_run_document(conclusion="failure"),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(),
        )
        with pytest.raises(vri.ReleaseVerificationError, match="successfully completed"):
            _verify(fakes, tmp_path)

    def test_compose_pinned_but_not_matching_provenance_is_refused(self, tmp_path: Path) -> None:
        # Each half individually passes its own primitive (pinned by
        # digest; genuine provenance) -- only the cross-check catches an
        # operator who wired a real, unrelated, digest-pinned image.
        fakes = _Fakes(
            run=_run_document(),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(
                ingestor={"image": f"{INGESTOR_REPO}@sha256:" + "9" * 64}
            ),
        )
        with pytest.raises(vri.ReleaseVerificationError, match="do not match verified provenance"):
            _verify(fakes, tmp_path)


class TestMain:
    def test_successful_run_prints_verified_digests_and_returns_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fakes = _Fakes(
            run=_run_document(), inventory=_inventory_document(), resolved_compose=_resolved_compose()
        )
        monkeypatch.setattr(vri.dii, "gh_api_get", fakes.github_api_get)
        monkeypatch.setattr(vri.dii, "make_download_artifact_via_gh", lambda *, repository: fakes.download_artifact)
        monkeypatch.setattr(vri, "run_docker_compose_config_via_subprocess", fakes.run_docker_compose_config)
        code = vri.main(
            [
                "--source-commit-sha", SOURCE_COMMIT_SHA,
                "--source-tree-sha", SOURCE_TREE_SHA,
                "--provenance-run-id", str(RUN_ID),
                "--provenance-run-attempt", str(RUN_ATTEMPT),
                "--repo-root", str(tmp_path),
            ]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "RELEASE_IMAGE_PROVENANCE_VERIFIED=true" in out
        assert "VERIFIED ingestor=" in out
        assert "docker compose up" in out

    def test_refused_run_returns_1_and_never_prints_verified_true(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fakes = _Fakes(
            run=_run_document(conclusion="failure"),
            inventory=_inventory_document(),
            resolved_compose=_resolved_compose(),
        )
        monkeypatch.setattr(vri.dii, "gh_api_get", fakes.github_api_get)
        monkeypatch.setattr(vri.dii, "make_download_artifact_via_gh", lambda *, repository: fakes.download_artifact)
        monkeypatch.setattr(vri, "run_docker_compose_config_via_subprocess", fakes.run_docker_compose_config)
        code = vri.main(
            [
                "--source-commit-sha", SOURCE_COMMIT_SHA,
                "--source-tree-sha", SOURCE_TREE_SHA,
                "--provenance-run-id", str(RUN_ID),
                "--provenance-run-attempt", str(RUN_ATTEMPT),
                "--repo-root", str(tmp_path),
            ]
        )
        captured = capsys.readouterr()
        assert code == 1
        assert "RELEASE_IMAGE_PROVENANCE_VERIFIED" not in captured.out
        assert "REFUSED:" in captured.err

    def test_main_never_invokes_docker_compose_up(self, tmp_path: Path) -> None:
        # Static guarantee, not just behavioral: grep the module source for
        # any occurrence of "up" as a compose subcommand argument.
        source = (Path(__file__).resolve().parents[1] / "scripts" / "verify_release_image_provenance_cli.py").read_text()
        assert '"up"' not in source
        assert "'up'" not in source


class TestRunDockerComposeConfigViaSubprocess:
    """La frontière process réelle -- injectée par défaut dans ``main()``,
    jamais exercée réseau/registre : ``docker compose config`` ne
    contacte ni un registre ni un daemon distant, il ne fait que
    résoudre/interpoler le YAML localement. ``git show`` ne contacte
    jamais non plus de remote (objet déjà local)."""

    requires_docker = pytest.mark.skipif(
        shutil.which("docker") is None, reason="Docker not available"
    )
    requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")

    @requires_docker
    @requires_git
    def test_missing_env_file_is_refused_before_shelling_out_to_anything(self, tmp_path: Path) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        with pytest.raises(vri.ReleaseVerificationError, match="env file not found"):
            vri.run_docker_compose_config_via_subprocess(
                repo_root, "0" * 40, vri._CANONICAL_COMPOSE_FILES, tmp_path, tmp_path / "missing.env"
            )

    @requires_docker
    @requires_git
    def test_missing_git_object_is_refused_before_shelling_out_to_docker(self, tmp_path: Path) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        env_file = tmp_path / "dummy.env"
        env_file.write_text("", encoding="utf-8")
        with pytest.raises(vri.ReleaseVerificationError, match="git show failed"):
            vri.run_docker_compose_config_via_subprocess(
                repo_root, "0" * 40, vri._CANONICAL_COMPOSE_FILES, tmp_path, env_file
            )

    @requires_docker
    @requires_git
    def test_real_committed_compose_files_resolve_with_no_build_and_pinned_images(
        self, tmp_path: Path
    ) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout.strip()

        # Shell-exported values take priority over --env-file in Docker
        # Compose's own precedence rules -- an existing but otherwise
        # empty env file, combined with real env vars, exercises the
        # --env-file wiring itself (file must exist) without needing a
        # real production .env in this sandbox.
        env_file = tmp_path / "dummy.env"
        env_file.write_text("", encoding="utf-8")

        env_overrides = _dummy_compose_env()
        old_environ = dict(os.environ)
        try:
            os.environ.update(env_overrides)
            resolved = vri.run_docker_compose_config_via_subprocess(
                repo_root, head_sha, vri._CANONICAL_COMPOSE_FILES, tmp_path, env_file
            )
        finally:
            os.environ.clear()
            os.environ.update(old_environ)

        pinned = dii.require_resolved_compose_images_are_pinned(resolved)
        assert set(pinned) == set(EXPECTED_SERVICES)
        assert pinned["ingestor"] == f"{INGESTOR_REPO}@{INGESTOR_DIGEST}"

    @requires_docker
    @requires_git
    def test_real_env_file_values_are_actually_loaded(self, tmp_path: Path) -> None:
        # Distinct from the previous test: proves --env-file itself
        # supplies values (not just that shell-exported vars mask its
        # absence) by putting every required value in the file and
        # exporting nothing.
        repo_root = Path(__file__).resolve().parents[3]
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout.strip()

        env_file = tmp_path / "dummy.env"
        env_file.write_text(
            "\n".join(f"{name}={value}" for name, value in _dummy_compose_env().items()) + "\n",
            encoding="utf-8",
        )

        resolved = vri.run_docker_compose_config_via_subprocess(
            repo_root, head_sha, vri._CANONICAL_COMPOSE_FILES, tmp_path, env_file
        )

        pinned = dii.require_resolved_compose_images_are_pinned(resolved)
        assert set(pinned) == set(EXPECTED_SERVICES)

    @requires_docker
    @requires_git
    def test_a_relative_env_file_path_resolves_against_the_callers_cwd_not_scratch(
        self, tmp_path: Path
    ) -> None:
        # Codex P2 (PR #105): the production runbook itself invokes
        # `--env-file .env` relative to services/rag-engine/infra
        # (docs/runbooks/go_live.md). Docker Compose runs with
        # cwd=<scratch>, so an unresolved relative path would silently
        # look in the wrong place and fail -- proven here by actually
        # chdir'ing away before calling.
        repo_root = Path(__file__).resolve().parents[3]
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, check=True
        ).stdout.strip()

        work_dir = tmp_path / "work"
        work_dir.mkdir()
        env_dir = tmp_path / "operator-cwd"
        env_dir.mkdir()
        (env_dir / "dummy.env").write_text(
            "\n".join(f"{name}={value}" for name, value in _dummy_compose_env().items()) + "\n",
            encoding="utf-8",
        )

        old_cwd = Path.cwd()
        try:
            os.chdir(env_dir)
            resolved = vri.run_docker_compose_config_via_subprocess(
                repo_root, head_sha, vri._CANONICAL_COMPOSE_FILES, work_dir, Path("dummy.env")
            )
        finally:
            os.chdir(old_cwd)

        pinned = dii.require_resolved_compose_images_are_pinned(resolved)
        assert set(pinned) == set(EXPECTED_SERVICES)


class TestMakeDownloadArtifactViaGh:
    """Codex P2 (PR #105) : le téléchargement doit être lié au dépôt
    vérifié, jamais dépendant du CWD du process."""

    def test_returned_callable_passes_dash_r_repository(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            (tmp_path / dii._ARTIFACT_FILENAME).write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(dii.subprocess, "run", fake_run)
        download = dii.make_download_artifact_via_gh(repository="cyranoaladin/RAG")
        download(123, "some-artifact", tmp_path)
        assert calls == [
            ["gh", "run", "download", "123", "-n", "some-artifact", "-D", str(tmp_path), "-R", "cyranoaladin/RAG"]
        ]

    def test_plain_download_artifact_via_gh_never_passes_dash_r(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            (tmp_path / dii._ARTIFACT_FILENAME).write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(dii.subprocess, "run", fake_run)
        dii.download_artifact_via_gh(123, "some-artifact", tmp_path)
        assert calls == [["gh", "run", "download", "123", "-n", "some-artifact", "-D", str(tmp_path)]]


def _dummy_compose_env() -> dict[str, str]:
    """Valeurs factices non vides pour toutes les variables requises par
    docker-compose.v2.yml + docker-compose.production-workers.yml +
    docker-compose.production-release.yml -- dérivées dynamiquement des
    fichiers réels (jamais une liste figée qui pourrait diverger sans que
    ce test ne le remarque)."""
    infra_dir = Path(__file__).resolve().parents[1] / "infra"
    completed = subprocess.run(
        ["bash", "-c", r"""
        grep -ohE '\$\{[A-Z0-9_]+' """
        + " ".join(str(infra_dir / f) for f in vri._CANONICAL_COMPOSE_FILES)
        + r""" | sed 's/\${//' | sort -u
        """],
        capture_output=True,
        text=True,
        check=True,
    )
    names = [line for line in completed.stdout.splitlines() if line]
    env: dict[str, str] = {}
    for name in names:
        if name == "NEXUS_INGESTOR_IMAGE_DIGEST":
            env[name] = f"{INGESTOR_REPO}@{INGESTOR_DIGEST}"
        elif name == "NEXUS_MULTILEVEL_WORKER_IMAGE_DIGEST":
            env[name] = f"{WORKER_REPO}@{WORKER_DIGEST}"
        elif name.endswith("_HOST_DIR"):
            env[name] = "/tmp/dummy-dir"
        elif name.endswith("_HOST_FILE"):
            env[name] = "/tmp/dummy-file"
        elif name.endswith(("_PORT", "_TIMEOUT_S", "_TIMEOUT_MS", "_INTERVAL_S", "_SIZE", "_TTL")):
            env[name] = "1"
        else:
            env[name] = "dummy"
    return env
