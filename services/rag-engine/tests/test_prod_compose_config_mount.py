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


def test_v2_ingestor_uses_dedicated_dockerfile_with_contracts() -> None:
    compose = _load_compose(V2_COMPOSE_PATH)
    ingestor = compose["services"]["ingestor"]
    build = ingestor["build"]

    assert "Dockerfile.ingestor-v2" in str(build.get("dockerfile", "")), (
        "v2 ingestor must use Dockerfile.ingestor-v2"
    )

    dockerfile_path = ENGINE_ROOT / "infra" / "Dockerfile.ingestor-v2"
    assert dockerfile_path.is_file(), "Dockerfile.ingestor-v2 must exist"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "packages/contracts" in content, (
        "Dockerfile.ingestor-v2 must install packages/contracts"
    )
    assert "requirements.v2.txt" in content, (
        "Dockerfile.ingestor-v2 must install requirements.v2.txt"
    )


def test_v2_worker_uses_same_dockerfile_as_ingestor() -> None:
    compose = _load_compose(V2_COMPOSE_PATH)
    ingestor_build = compose["services"]["ingestor"]["build"]
    worker_build = compose["services"]["worker"]["build"]

    assert ingestor_build.get("dockerfile") == worker_build.get("dockerfile"), (
        "worker must use the same Dockerfile as ingestor"
    )


def test_v2_pydantic_pin_aligned_with_contracts() -> None:
    """Pydantic pin in requirements.v2.txt must match contracts pyproject.toml."""
    contracts_toml = REPO_ROOT / "packages" / "contracts" / "pyproject.toml"
    v2_reqs = ENGINE_ROOT / "src" / "ingestor" / "requirements.v2.txt"

    assert contracts_toml.is_file()
    assert v2_reqs.is_file()

    # Extract pydantic pin from contracts
    import re
    contracts_text = contracts_toml.read_text(encoding="utf-8")
    m = re.search(r'"pydantic==([^"]+)"', contracts_text)
    assert m, "contracts pyproject.toml must pin pydantic"
    contracts_pydantic = m.group(1)

    # Extract pydantic pin from requirements.v2.txt
    v2_text = v2_reqs.read_text(encoding="utf-8")
    m2 = re.search(r"^pydantic==(.+)$", v2_text, re.MULTILINE)
    assert m2, "requirements.v2.txt must pin pydantic"
    v2_pydantic = m2.group(1).strip()

    assert v2_pydantic == contracts_pydantic, (
        f"pydantic pin mismatch: requirements.v2.txt={v2_pydantic} "
        f"vs contracts={contracts_pydantic}"
    )


def test_init_sql_has_v2_schema_columns() -> None:
    init_sql = ENGINE_ROOT / "infra" / "postgres" / "init.sql"
    assert init_sql.is_file()
    content = init_sql.read_text(encoding="utf-8")

    for column in ("chunk_id", "doc_id", "chunk_sha256", "review_status",
                    "collection", "source_label", "source_uri", "rights", "type_doc"):
        assert column in content, f"init.sql must define column {column}"

    assert "vector(1024)" in content, "init.sql must use vector(1024) for e5-large"
    assert "vector(768)" not in content, "init.sql must NOT use vector(768) (v1 schema)"


def test_v2_dockerfile_runs_pip_check() -> None:
    dockerfile = ENGINE_ROOT / "infra" / "Dockerfile.ingestor-v2"
    assert dockerfile.is_file()
    content = dockerfile.read_text(encoding="utf-8")
    assert "pip check" in content, (
        "Dockerfile.ingestor-v2 must run pip check to verify dependency integrity"
    )


def test_repo_root_dockerignore_blocks_sensitive_paths() -> None:
    dockerignore = REPO_ROOT / ".dockerignore"
    assert dockerignore.is_file(), ".dockerignore must exist at repo root"

    content = dockerignore.read_text(encoding="utf-8")

    # Must deny-all by default
    assert content.strip().startswith("# Deny all by default.\n**") or "**" in content.splitlines()[:3], (
        ".dockerignore must deny all by default"
    )

    # Must block sensitive patterns
    for pattern in (".git", ".env", "*secret*", "*credential*", "node_modules", "__pycache__", ".venv"):
        assert pattern in content, f".dockerignore must block {pattern}"

    # Must allow required paths
    for required in ("packages/contracts", "services/rag-engine/src/ingestor", "Dockerfile.ingestor-v2"):
        assert required in content, f".dockerignore must allow {required}"


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

    assert 'TRUSTED_PROXY_CIDRS=$(prompt_value "CIDR des reverse proxies de confiance' in script
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
    assert "docker0" not in trusted_proxy_block, (
        "TRUSTED_PROXY_CIDRS must not rely on docker0 (Compose uses its own bridge)"
    )
    assert "addr show docker0" not in script, (
        "provision-prod.sh must not detect docker0 for trusted proxy"
    )


def test_provision_prod_allowlist_default_has_no_broad_private_ranges() -> None:
    script = PROVISION_PROD_SCRIPT.read_text(encoding="utf-8")

    allowlist_lines = [
        line for line in script.splitlines() if "ALLOWLIST_DEFAULT" in line
    ]
    assert allowlist_lines, "ALLOWLIST_DEFAULT must appear in script"
    allowlist_block = "\n".join(allowlist_lines)
    assert "127.0.0.1/32" in allowlist_block
    for broad_range in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        assert broad_range not in allowlist_block, (
            f"ALLOWLIST_DEFAULT must not include broad range {broad_range}"
        )


def test_search_cache_disabled_in_production() -> None:
    """In RAG_ENV=production, search cache must default to disabled."""
    source = (ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py").read_text(
        encoding="utf-8"
    )
    # Static check: when RAG_ENV==production, RERANK_CACHE default must be "0"
    assert 'CACHE_ENABLED = os.environ.get("RERANK_CACHE", "0") == "1"' in source, (
        "Production cache must default to disabled (RERANK_CACHE default '0')"
    )


def test_prod_deployment_plan_does_not_persist_rendered_compose_secrets() -> None:
    plan = DEPLOYMENT_PLAN.read_text(encoding="utf-8")

    assert "/tmp/rag-ui-compose.rendered" not in plan
    assert "docker compose config --format json >" not in plan
    assert '["docker", "compose", "config", "--format", "json"]' in plan
    assert "stdout=subprocess.PIPE" in plan
