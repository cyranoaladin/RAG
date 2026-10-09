"""Le candidat public doit rester isolé du dépôt et de la production historique."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parents[1] / "infra"
BASE = INFRA / "docker-compose.v2.yml"
OVERLAY = INFRA / "docker-compose.public-blue-green.yml"


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose indisponible")
def test_public_blue_green_compose_declares_isolated_sources(tmp_path: Path) -> None:
    material = tmp_path / "release-material"
    secrets = tmp_path / "runtime-secrets"
    names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]+):\?", BASE.read_text() + OVERLAY.read_text()))
    env = os.environ.copy()
    env.update({name: "synthetic" for name in names})
    env.update(
        NEXUS_RELEASE_MATERIAL_ROOT=str(material),
        NEXUS_RUNTIME_SECRETS_ROOT=str(secrets),
        NEXUS_INGESTOR_IMAGE_DIGEST="example.invalid/rag@sha256:" + "a" * 64,
        NEXUS_SEARCH_PORT="18101",
        NEXUS_PROM_PORT="19101",
        PG_RAG_DSN="postgresql://rag_reader:synthetic@pgvector:5432/ragdb",
        PG_REVIEW_DSN="postgresql://rag_reviewer:synthetic@pgvector:5432/ragdb",
    )
    command = [
        "docker",
        "compose",
        "-p",
        "nexus-rag-blue",
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
    assert set(resolved["services"]) == {"pgvector", "ingestor", "prometheus"}
    for service in resolved["services"].values():
        assert "build" not in service
        assert "@sha256:" in service["image"]
        for mount in service.get("volumes", []):
            if mount["type"] == "bind":
                assert Path(mount["source"]).is_relative_to(material) or Path(
                    mount["source"]
                ).is_relative_to(secrets)
                assert mount["read_only"] is True
    client_mount = next(
        mount
        for mount in resolved["services"]["ingestor"]["volumes"]
        if mount["target"] == "/app/api-clients/api-clients.json"
    )
    assert Path(client_mount["source"]).is_relative_to(secrets)
    ports = {
        service: [(port["host_ip"], port["published"]) for port in spec.get("ports", [])]
        for service, spec in resolved["services"].items()
    }
    assert ports == {
        "pgvector": [],
        "ingestor": [("127.0.0.1", "18101")],
        "prometheus": [("127.0.0.1", "19101")],
    }
    prometheus_targets = {
        mount["target"] for mount in resolved["services"]["prometheus"]["volumes"]
    }
    assert {"/etc/prometheus/prometheus.yml", "/etc/prometheus/rules"} <= prometheus_targets
