from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
COMPOSE_PATH = ENGINE_ROOT / "infra" / "docker-compose.prod.yml"
DEFAULT_COMPOSE_PATH = ENGINE_ROOT / "infra" / "docker-compose.yml"
V2_COMPOSE_PATH = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
MAKEFILE_PATH = ENGINE_ROOT / "Makefile"
V2_EFFECTIVE_API_TOKEN_REF = "${INGESTOR_API_TOKEN:-${API_SECRET_KEY}}"
CONFIGS_DIR = ENGINE_ROOT / "configs"
DEPLOYMENT_PLAN = REPO_ROOT / "docs" / "reports" / "lot_19_prod_deployment_plan.md"
PROVISION_PROD_SCRIPT = ENGINE_ROOT / "infra" / "scripts" / "provision-prod.sh"
V2_INGESTOR_ENV_KEYS = {
    "LEGACY_ADMIN_API_TOKEN",
    "RAG_ADMIN_TOKEN",
    "RAG_REVIEWER_TOKEN",
    "REVIEWER_API_TOKEN",
    "RAG_TEACHER_TOKEN",
    "RAG_INGEST_AGENT_TOKEN",
    "INGESTOR_API_TOKEN",
    "INGEST_AUTH_TOKEN",
    "RAG_STUDENT_TOKEN",
    "INGESTOR_IP_ALLOWLIST",
    "INGESTOR_TRUSTED_PROXY_CIDRS",
}


def _load_compose(path: Path = COMPOSE_PATH) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _environment_variables(environment: object) -> dict[str, str]:
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    if isinstance(environment, list):
        return dict(
            entry.split("=", 1)
            for entry in environment
            if isinstance(entry, str) and "=" in entry
        )
    raise AssertionError(f"unsupported environment format: {type(environment)!r}")


def _compose_env_ref_is_valid(value: str, key: str) -> bool:
    marker = f"${{{key}"
    start = value.find(marker)
    if start < 0:
        return False

    position = start + len(marker)
    if position >= len(value):
        return False
    if value[position] == "}":
        return True
    if not (value.startswith(":-", position) or value.startswith(":?", position)):
        return False

    depth = 1
    position += 2
    while position < len(value):
        if value.startswith("${", position):
            depth += 1
            position += 2
            continue
        if value[position] == "}":
            depth -= 1
            if depth == 0:
                return True
        position += 1
    return False


def _assert_ingestor_has_v2_env(compose_path: Path) -> None:
    compose = _load_compose(compose_path)
    service = compose["services"]["ingestor"]
    configured = _environment_variables(service["environment"])

    assert V2_INGESTOR_ENV_KEYS <= set(configured)
    for key in V2_INGESTOR_ENV_KEYS:
        assert _compose_env_ref_is_valid(configured[key], key)


def _v2_api_token_refs() -> tuple[str, str]:
    compose = _load_compose(V2_COMPOSE_PATH)
    ingestor_env = _environment_variables(compose["services"]["ingestor"]["environment"])
    ui_env = _environment_variables(compose["services"]["ui"]["environment"])
    return ingestor_env["INGESTOR_API_TOKEN"], ui_env["RAG_API_TOKEN"]


def _resolve_nested_default(expression: str, environment: dict[str, str]) -> str:
    match = re.fullmatch(r"\$\{([A-Z0-9_]+):-\$\{([A-Z0-9_]+)\}\}", expression)
    assert match is not None, f"unsupported compose token expression: {expression}"
    primary, fallback = match.groups()
    return environment.get(primary) or environment.get(fallback, "")


def _make_target_recipe(makefile: str, target: str) -> str:
    lines = makefile.splitlines()
    start = lines.index(f"{target}:") + 1
    recipe: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith(("\t", " ")):
            break
        recipe.append(line)
    return "\n".join(recipe)


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("${RAG_ADMIN_TOKEN}", "RAG_ADMIN_TOKEN"),
        ("${RAG_ADMIN_TOKEN:-}", "RAG_ADMIN_TOKEN"),
        ("${RAG_ADMIN_TOKEN:-fallback}", "RAG_ADMIN_TOKEN"),
        ("${RAG_ADMIN_TOKEN:?required}", "RAG_ADMIN_TOKEN"),
        (
            "${INGESTOR_API_TOKEN:-${API_SECRET_KEY}}",
            "INGESTOR_API_TOKEN",
        ),
    ],
)
def test_compose_env_ref_accepts_complete_syntax(value: str, key: str) -> None:
    assert _compose_env_ref_is_valid(value, key)


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("${RAG_ADMIN_TOKEN", "RAG_ADMIN_TOKEN"),
        ("${RAG_ADMIN_TOKEN-invalid}", "RAG_ADMIN_TOKEN"),
        ("${RAG_REVIEWER_TOKEN:-}", "RAG_ADMIN_TOKEN"),
    ],
)
def test_compose_env_ref_rejects_incomplete_or_wrong_syntax(
    value: str,
    key: str,
) -> None:
    assert not _compose_env_ref_is_valid(value, key)


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


def test_prod_compose_passes_v2_role_tokens_to_ingestor() -> None:
    _assert_ingestor_has_v2_env(COMPOSE_PATH)


def test_default_compose_passes_v2_role_tokens_to_ingestor() -> None:
    _assert_ingestor_has_v2_env(DEFAULT_COMPOSE_PATH)


def test_v2_compose_passes_v2_role_tokens_to_ingestor() -> None:
    _assert_ingestor_has_v2_env(V2_COMPOSE_PATH)


def test_v2_ui_uses_same_effective_token_reference_as_ingestor() -> None:
    ingestor_token_ref, ui_token_ref = _v2_api_token_refs()

    assert ingestor_token_ref == V2_EFFECTIVE_API_TOKEN_REF
    assert ui_token_ref == V2_EFFECTIVE_API_TOKEN_REF


def test_v2_token_render_prefers_ingestor_api_token() -> None:
    ingestor_token_ref, ui_token_ref = _v2_api_token_refs()
    environment = {
        "API_SECRET_KEY": "api-secret-dummy",
        "INGESTOR_API_TOKEN": "ingestor-dummy",
    }

    assert _resolve_nested_default(ingestor_token_ref, environment) == "ingestor-dummy"
    assert _resolve_nested_default(ui_token_ref, environment) == "ingestor-dummy"


def test_v2_token_render_preserves_api_secret_fallback() -> None:
    ingestor_token_ref, ui_token_ref = _v2_api_token_refs()
    environment = {"API_SECRET_KEY": "api-secret-dummy"}

    assert _resolve_nested_default(ingestor_token_ref, environment) == "api-secret-dummy"
    assert _resolve_nested_default(ui_token_ref, environment) == "api-secret-dummy"


def test_v2_makefile_clients_use_effective_ingestor_token() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    for target in ("v2-eval", "v2-stats"):
        recipe = _make_target_recipe(makefile, target)
        assert "$${INGESTOR_API_TOKEN:-$${API_SECRET_KEY}}" in recipe
        assert "Bearer $${TOKEN}" in recipe
        assert "Bearer $${API_SECRET_KEY}" not in recipe


def test_v2_up_uses_wired_v2_compose() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert "COMPOSE_V2=docker compose -f infra/docker-compose.v2.yml" in makefile
    _assert_ingestor_has_v2_env(V2_COMPOSE_PATH)


def test_provision_prod_uses_wired_default_compose() -> None:
    script = PROVISION_PROD_SCRIPT.read_text(encoding="utf-8")

    assert "docker compose -f docker-compose.yml" in script
    _assert_ingestor_has_v2_env(DEFAULT_COMPOSE_PATH)


def test_provision_prod_generates_distinct_legacy_admin_token() -> None:
    script = PROVISION_PROD_SCRIPT.read_text(encoding="utf-8")

    assert "LEGACY_ADMIN_API_TOKEN=$(generate_hex 32)" in script
    assert '"LEGACY_ADMIN_API_TOKEN=$(printf \'%q\' "${LEGACY_ADMIN_API_TOKEN}")"' in script
    assert 'LEGACY_ADMIN_API_TOKEN="${INGESTOR_API_TOKEN}"' not in script
    assert 'LEGACY_ADMIN_API_TOKEN="${INGEST_AUTH_TOKEN}"' not in script


def test_provision_prod_configures_nonempty_trusted_proxy_cidrs() -> None:
    script = PROVISION_PROD_SCRIPT.read_text(encoding="utf-8")

    assert 'TRUSTED_PROXY_CIDRS=$(prompt_value "CIDR des reverse proxies de confiance"' in script
    assert '"INGESTOR_TRUSTED_PROXY_CIDRS=$(printf \'%q\' "${TRUSTED_PROXY_CIDRS}")"' in script
    assert '"INGESTOR_TRUSTED_PROXY_CIDRS="' not in script
    assert "127.0.0.1/32" in script
    trusted_proxy_lines = [
        line for line in script.splitlines() if "TRUSTED_PROXY_CIDRS_DEFAULT" in line
    ]
    assert trusted_proxy_lines, "TRUSTED_PROXY_CIDRS_DEFAULT must appear in script"
    trusted_proxy_block = "\n".join(trusted_proxy_lines)
    for broad_range in ("172.16.0.0/12", "10.0.0.0/8", "192.168.0.0/16"):
        assert broad_range not in trusted_proxy_block, (
            f"TRUSTED_PROXY_CIDRS_DEFAULT must not include broad range {broad_range}"
        )


def test_prod_deployment_plan_does_not_persist_rendered_compose_secrets() -> None:
    plan = DEPLOYMENT_PLAN.read_text(encoding="utf-8")

    assert "/tmp/rag-ui-compose.rendered" not in plan
    assert "docker compose config --format json >" not in plan
    assert '["docker", "compose", "config", "--format", "json"]' in plan
    assert "stdout=subprocess.PIPE" in plan
