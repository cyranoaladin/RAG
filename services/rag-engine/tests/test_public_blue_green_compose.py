"""Le candidat public doit rester isolé du dépôt et de la production historique."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import public_blue_green_preflight as preflight  # noqa: E402

INFRA = Path(__file__).resolve().parents[1] / "infra"
BASE = INFRA / "docker-compose.v2.yml"
OVERLAY = INFRA / "docker-compose.public-blue-green.yml"
EXAMPLE_ENV = INFRA / ".env.example"


def _compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return (
        subprocess.run(
            ["docker", "compose", "version"], capture_output=True, check=False
        ).returncode
        == 0
    )


def _overlay_document() -> dict:
    class ComposeLoader(yaml.SafeLoader):
        pass

    ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))
    ComposeLoader.add_constructor("!reset", lambda loader, node: None)
    document = yaml.load(OVERLAY.read_text(encoding="utf-8"), Loader=ComposeLoader)
    assert isinstance(document, dict)
    return document


@pytest.mark.skipif(not _compose_available(), reason="Docker Compose indisponible")
@pytest.mark.parametrize("color", ["blue", "green"])
def test_public_blue_green_compose_declares_isolated_sources(tmp_path: Path, color: str) -> None:
    material = tmp_path / "release-material"
    secrets = tmp_path / "runtime-secrets"
    secrets.mkdir()
    (secrets / "cockpit.env").write_text(
        "RAG_ENGINE_INTERNAL_URL=http://ingestor:8001\n"
        "NEXUS_SESSION_REDIS_URL=redis://default:synthetic@session-redis:6379/0\n",
        encoding="utf-8",
    )
    names = set(
        re.findall(
            r"\$\{([A-Z][A-Z0-9_]+):\?",
            BASE.read_text(encoding="utf-8") + OVERLAY.read_text(encoding="utf-8"),
        )
    )
    env = os.environ.copy()
    env.update({name: "synthetic" for name in names})
    env.update(
        {
            name: str(material / name.lower())
            for name in names
            if name.endswith(("HOST_DIR", "HOST_FILE"))
        }
    )
    env.update(
        NEXUS_RELEASE_MATERIAL_ROOT=str(material),
        NEXUS_RUNTIME_SECRETS_ROOT=str(secrets),
        NEXUS_INGESTOR_IMAGE_SHA256="a" * 64,
        NEXUS_COCKPIT_IMAGE_SHA256="b" * 64,
        NEXUS_REDIS_IMAGE_SHA256="c" * 64,
        NEXUS_RELEASE_MATERIAL_MANIFEST_SHA256="e" * 64,
        NEXUS_SEARCH_PORT="18101" if color == "blue" else "18102",
        NEXUS_PROM_PORT="19101" if color == "blue" else "19102",
        NEXUS_COCKPIT_PORT="13101" if color == "blue" else "13102",
        PG_RAG_DSN="postgresql://rag_reader:synthetic@pgvector:5432/ragdb",
        PG_REVIEW_DSN="postgresql://rag_reviewer:synthetic@pgvector:5432/ragdb",
    )
    command = [
        "docker",
        "compose",
        "-p",
        f"nexus-rag-{color}",
        "-f",
        str(BASE),
        "-f",
        str(OVERLAY),
        "config",
        "--format",
        "json",
    ]
    completed = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    assert completed.returncode == 0, completed.stderr
    resolved = json.loads(completed.stdout)
    assert resolved["name"] == f"nexus-rag-{color}"
    assert resolved["networks"] == {
        "rag_net": {"name": f"nexus-rag-{color}_rag_net", "driver": "bridge", "ipam": {}},
        "bff_net": {"name": f"nexus-rag-{color}_bff_net", "driver": "bridge", "ipam": {}},
    }
    assert resolved["volumes"] == {
        "rag_pgvector_data": {"name": f"nexus-rag-{color}_rag_pgvector_data"},
        "rag_prometheus_data": {"name": f"nexus-rag-{color}_rag_prometheus_data"},
        "session_redis_data": {"name": f"nexus-rag-{color}_session_redis_data"},
    }
    assert resolved["services"]["ingestor"]["networks"] == {"rag_net": None, "bff_net": None}
    assert resolved["services"]["pgvector"]["networks"] == {"rag_net": None}
    assert resolved["services"]["prometheus"]["networks"] == {"rag_net": None}
    assert resolved["services"]["cockpit"]["networks"] == {"bff_net": None}
    assert resolved["services"]["session-redis"]["networks"] == {"bff_net": None}
    assert set(resolved["services"]) == {"pgvector", "ingestor", "prometheus", "cockpit", "session-redis"}
    assert resolved["services"]["ingestor"]["image"] == (
        "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "a" * 64
    )
    assert resolved["services"]["ingestor"]["labels"]["nexus.release-material.sha256"] == "e" * 64
    api_env = resolved["services"]["ingestor"]["environment"]
    assert api_env["NEXUS_PUBLIC_SUCCESSOR_BUNDLE_ROOT"] == "/app/release"
    assert api_env["NEXUS_READINESS_MANIFEST_PATH"] == "/app/release/readiness-manifest.json"
    assert api_env["RAG_RELEASE_REGISTRY_PATH"] == "/app/release/release/release-registry.json"
    assert resolved["services"]["cockpit"]["image"] == (
        "ghcr.io/cyranoaladin/rag-cockpit@sha256:" + "b" * 64
    )
    assert resolved["services"]["session-redis"]["image"] == (
        "docker.io/library/redis@sha256:" + "c" * 64
    )
    base_command = ["docker", "compose", "-f", str(BASE), "config", "--format", "json"]
    base_completed = subprocess.run(
        base_command, env=env, text=True, capture_output=True, check=False
    )
    assert base_completed.returncode == 0, base_completed.stderr
    base_resolved = json.loads(base_completed.stdout)
    for name in ("pgvector", "ingestor", "prometheus"):
        service = resolved["services"][name]
        base_targets = {mount["target"] for mount in base_resolved["services"][name]["volumes"]}
        candidate_targets = {mount["target"] for mount in service["volumes"]}
        assert candidate_targets == base_targets
    for service in resolved["services"].values():
        assert "build" not in service
        assert "@sha256:" in service["image"]
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                assert Path(mount["source"]).is_relative_to(material) or Path(
                    mount["source"]
                ).is_relative_to(secrets)
                assert mount["read_only"] is True
    for service_name, expected_binds in preflight._MATERIAL_BINDS.items():
        actual_binds = {
            mount["target"]: str(Path(mount["source"]).relative_to(material))
            for mount in resolved["services"][service_name]["volumes"]
            if mount["type"] == "bind" and Path(mount["source"]).is_relative_to(material)
        }
        assert actual_binds == expected_binds
    client_mount = next(
        mount
        for mount in resolved["services"]["ingestor"]["volumes"]
        if mount["target"] == "/app/api-clients/api-clients.json"
    )
    assert Path(client_mount["source"]).is_relative_to(secrets)
    client_spec = next(
        mount
        for mount in _overlay_document()["services"]["ingestor"]["volumes"]
        if isinstance(mount, dict) and mount.get("target") == "/app/api-clients/api-clients.json"
    )
    assert client_spec["bind"]["create_host_path"] is False
    for service in _overlay_document()["services"].values():
        for mount in service.get("volumes", []):
            if isinstance(mount, str):
                assert mount.startswith(("rag_pgvector_data:", "rag_prometheus_data:", "session_redis_data:"))
            else:
                assert mount["type"] == "bind"
                assert mount["read_only"] is True
                assert mount["bind"]["create_host_path"] is False
    ports = {
        service: [
            (port["host_ip"], port["published"], port["target"]) for port in spec.get("ports", [])
        ]
        for service, spec in resolved["services"].items()
    }
    assert ports == {
        "pgvector": [],
        "ingestor": [("127.0.0.1", "18101" if color == "blue" else "18102", 8001)],
        "prometheus": [("127.0.0.1", "19101" if color == "blue" else "19102", 9090)],
        "cockpit": [("127.0.0.1", "13101" if color == "blue" else "13102", 3000)],
        "session-redis": [],
    }
    prometheus_targets = {
        mount["target"] for mount in resolved["services"]["prometheus"]["volumes"]
    }
    assert {"/etc/prometheus/prometheus.yml", "/etc/prometheus/rules"} <= prometheus_targets
    assert {mount["target"] for mount in resolved["services"]["session-redis"]["volumes"]} == {
        "/data", "/run/secrets/session-redis.acl"
    }
    assert not resolved["services"]["cockpit"].get("volumes")
    assert resolved["services"]["cockpit"]["environment"]["RAG_ENGINE_INTERNAL_URL"] == "http://ingestor:8001"


def test_candidate_variables_are_documented_in_example_env() -> None:
    example = EXAMPLE_ENV.read_text(encoding="utf-8")
    for name in (
        "NEXUS_RELEASE_MATERIAL_ROOT",
        "NEXUS_RUNTIME_SECRETS_ROOT",
        "NEXUS_INGESTOR_IMAGE_SHA256",
        "NEXUS_COCKPIT_IMAGE_SHA256",
        "NEXUS_REDIS_IMAGE_SHA256",
        "NEXUS_RELEASE_MATERIAL_MANIFEST_SHA256",
        "NEXUS_RELEASE_SHA",
        "NEXUS_PUBLIC_SCOPE_AUTHORITY_SHA256",
        "NEXUS_SEARCH_PORT",
        "NEXUS_PROM_PORT",
        "NEXUS_COCKPIT_PORT",
    ):
        assert re.search(rf"^{name}=", example, re.MULTILINE), name
