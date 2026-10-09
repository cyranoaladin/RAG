"""Témoin Docker synthétique du chemin pull/up/rollback public, sans RAG réel.

La signature et les matériaux sont vérifiés par les suites dédiées. Ce témoin
remplace ces deux seules frontières afin d'exercer le vrai daemon sur cinq
services Alpine sans port, secret, base ni image de production.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deploy_verified_release_cli as dep  # noqa: E402


def _docker(*args: str, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker absent")
def test_public_atomic_docker_candidate_refusals_rollback_and_foreign_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if _docker("info", "--format", "{{.ServerVersion}}").returncode:
        pytest.skip("Docker daemon inaccessible")
    project = "nexus-rag-blue"
    if any(dep._default_project_inventory(project).values()):
        pytest.skip("La couleur candidate locale possède déjà des ressources")
    image = "alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc"
    if _docker("image", "inspect", image).returncode:
        pytest.skip("Image Alpine de répétition absente")

    bundle = tmp_path / "bundle"
    bundle.mkdir(mode=0o700)
    (bundle / ".env").write_text(f"COMPOSE_PROJECT_NAME={project}\n", encoding="utf-8")
    services = sorted(dep.vri._PUBLIC_CANDIDATE_SERVICES)
    source = "services:\n" + "".join(
        f"  {name}:\n    image: {image}\n    command: [sleep, '300']\n"
        for name in services
    )
    (bundle / dep.vri._PUBLIC_CANDIDATE_COMPOSE_FILES[0]).write_text(source, encoding="utf-8")
    (bundle / dep.vri._PUBLIC_CANDIDATE_COMPOSE_FILES[1]).write_text(
        "services: {}\n", encoding="utf-8"
    )
    verified = dep._VerifiedDeployInputs(
        bundle_document={"public_candidate": True, "verified_images": {},
                         "bundle_digest": "b" * 64},
        explicit_services=services,
        effective_compose_bytes=json.dumps({"name": project, "services": {
            "prometheus": {"ports": [{"published": "19090"}]}
        }}).encode(),
    )
    monkeypatch.setattr(dep, "_verify_deploy_inputs", lambda **_kw: verified)
    monkeypatch.setattr(dep, "_public_preflight_from_bundle", lambda **_kw: project)
    foreign_name = "nexus-foreign-witness-" + uuid.uuid4().hex[:12]
    foreign = _docker("run", "-d", "--name", foreign_name, image, "sleep", "300")
    assert foreign.returncode == 0, foreign.stderr
    foreign_id = foreign.stdout.strip()
    foreign_before = _docker(
        "inspect", foreign_id,
        "--format", "{{.Id}} {{.State.StartedAt}} {{.RestartCount}} {{.State.Running}}",
    ).stdout.strip()
    commands: list[list[str]] = []

    def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        assert cwd == bundle
        commands.append(command)
        return subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=600, check=False
        )

    common = {
        "bundle_dir": bundle,
        "merge_sha": "a" * 40,
        "verified": verified,
        "trusted_readiness_anchor_raw": b"synthetic",
        "run_bundle_compose_config": lambda *_: {},
        "run_subprocess": run,
        "public_color": "blue",
        "public_material_root": tmp_path,
        "public_secrets_root": tmp_path,
        "public_repo_root": tmp_path,
        "public_final_cutover_go": True,
        "project_inventory": dep._default_project_inventory,
        "project_containers": dep._default_project_containers,
        "deployment_state_root": tmp_path / "state",
        "prometheus_probe": lambda _port: True,
        "host_local_guard": dep._require_host_local_docker_daemon,
    }
    try:
        with pytest.raises(dep.DeploymentWrapperError, match="assert-ready"):
            dep._deploy_public_candidate_from_bundle(**common, assert_readiness=lambda: False)
        assert commands == []
        with monkeypatch.context() as bad:
            bad.setattr(
                dep, "_public_preflight_from_bundle",
                lambda **_kw: (_ for _ in ()).throw(
                    dep.DeploymentWrapperError("bad digest refused")
                ),
            )
            with pytest.raises(dep.DeploymentWrapperError, match="bad digest"):
                dep._deploy_public_candidate_from_bundle(**common, assert_readiness=lambda: True)
        assert commands == []
        assert dep._deploy_public_candidate_from_bundle(
            **common, assert_readiness=lambda: True
        ) == ["PUBLIC_CANDIDATE_DEPLOYED=true", "EDGE_SWITCHED=false"]
        assert ["pull", "up"] == [
            next(word for word in command if word in {"pull", "up"})
            for command in commands
        ]
        assert all("--remove-orphans" not in command for command in commands)
        assert all("--project-name" in command and project in command for command in commands)
        foreign_after = _docker(
            "inspect", foreign_id,
            "--format", "{{.Id}} {{.State.StartedAt}} {{.RestartCount}} {{.State.Running}}",
        ).stdout.strip()
        assert foreign_before == foreign_after
        assert foreign_after.endswith(" true")
    finally:
        rollback = run(dep._public_compose_args(bundle, project) + ["down", "--timeout", "10"], bundle)
        assert rollback.returncode == 0, rollback.stderr
        assert _docker("rm", "-f", foreign_id).returncode == 0
    assert dep._default_project_inventory(project) == {
        "containers": [], "networks": [], "volumes": []
    }
