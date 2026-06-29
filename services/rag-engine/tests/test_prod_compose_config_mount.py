from __future__ import annotations

import re
from pathlib import Path

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
COMPOSE_PATH = ENGINE_ROOT / "infra" / "docker-compose.prod.yml"
CONFIGS_DIR = ENGINE_ROOT / "configs"
DEPLOYMENT_PLAN = REPO_ROOT / "docs" / "reports" / "lot_19_prod_deployment_plan.md"


def _load_compose() -> dict:
    data = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _parse_short_volume(volume: str) -> tuple[str, str, str]:
    parts = volume.rsplit(":", 2)
    assert len(parts) == 3
    return parts[0], parts[1], parts[2]


def _resolve_source(source: str) -> Path:
    match = re.fullmatch(r"\$\{RAG_CONFIGS_HOST_DIR:-([^}]+)\}", source)
    if match:
        source = match.group(1)
    return (COMPOSE_PATH.parent / source).resolve()


def test_versioned_prod_compose_mounts_configs_structurally() -> None:
    compose = _load_compose()
    service = compose["services"]["ingestor"]
    volumes = service["volumes"]

    config_mounts = []
    for volume in volumes:
        if not isinstance(volume, str):
            continue
        if ":/app/configs:" not in volume:
            continue
        source, target, mode = _parse_short_volume(volume)
        if target == "/app/configs":
            config_mounts.append((source, target, mode))

    assert config_mounts == [("${RAG_CONFIGS_HOST_DIR:-../configs}", "/app/configs", "ro")]
    source, target, mode = config_mounts[0]
    resolved_source = _resolve_source(source)

    assert target == "/app/configs"
    assert mode == "ro"
    assert resolved_source == CONFIGS_DIR.resolve()
    assert resolved_source.is_dir()
    assert (resolved_source / "rag_collections.yml").is_file()
    assert (resolved_source / "legacy_collection_mapping.yml").is_file()


def test_prod_deployment_plan_does_not_persist_rendered_compose_secrets() -> None:
    plan = DEPLOYMENT_PLAN.read_text(encoding="utf-8")

    assert "/tmp/rag-ui-compose.rendered" not in plan
    assert "docker compose config --format json >" not in plan
    assert '["docker", "compose", "config", "--format", "json"]' in plan
    assert "stdout=subprocess.PIPE" in plan
