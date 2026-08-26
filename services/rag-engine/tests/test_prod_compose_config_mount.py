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
CONFIGS_DIR = ENGINE_ROOT / "configs"
TAXONOMY_DIR = REPO_ROOT / "services" / "rag-pedago" / "taxonomy"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"
DEPLOYMENT_PLAN = REPO_ROOT / "docs" / "reports" / "lot_19_prod_deployment_plan.md"
PROVISION_PROD_SCRIPT = ENGINE_ROOT / "infra" / "scripts" / "provision-prod.sh"
LEGACY_INGESTOR_ENV_KEYS = {
    "LEGACY_ADMIN_API_TOKEN",
    "RAG_ADMIN_TOKEN",
    "RAG_REVIEWER_TOKEN",
    "REVIEWER_API_TOKEN",
    "RAG_TEACHER_TOKEN",
    "RAG_INGEST_AGENT_TOKEN",
    "INGESTOR_API_TOKEN",
    "INGEST_AUTH_TOKEN",
    "RAG_STUDENT_TOKEN",
    "RAG_BFF_SERVICE_TOKEN",
    "NEXUS_INTERNAL_TOKEN_SECRET",
    "NEXUS_INTERNAL_TOKEN_ISSUER",
    "NEXUS_INTERNAL_TOKEN_AUDIENCE",
    "NEXUS_SSO_ISSUER",
    "NEXUS_SSO_AUDIENCE",
    "PG_RAG_DSN",
    "PG_REVIEW_DSN",
    "INGESTOR_IP_ALLOWLIST",
    "INGESTOR_TRUSTED_PROXY_CIDRS",
}
V2_RUNTIME_ENV_KEYS = {
    "PG_RAG_DSN",
    "PG_REVIEW_DSN",
    "RAG_BFF_SERVICE_TOKEN",
    "NEXUS_INTERNAL_TOKEN_SECRET",
    "NEXUS_INTERNAL_TOKEN_ISSUER",
    "NEXUS_INTERNAL_TOKEN_AUDIENCE",
    "NEXUS_SSO_ISSUER",
    "NEXUS_SSO_AUDIENCE",
}
V2_FORBIDDEN_ENV_KEYS = LEGACY_INGESTOR_ENV_KEYS - V2_RUNTIME_ENV_KEYS


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


def _assert_legacy_ingestor_has_v2_env(compose_path: Path) -> None:
    compose = _load_compose(compose_path)
    service = compose["services"]["ingestor"]
    configured = _environment_variables(service["environment"])

    assert LEGACY_INGESTOR_ENV_KEYS <= set(configured)
    for key in LEGACY_INGESTOR_ENV_KEYS:
        assert _compose_env_ref_is_valid(configured[key], key)


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
    _assert_legacy_ingestor_has_v2_env(COMPOSE_PATH)


def test_default_compose_passes_v2_role_tokens_to_ingestor() -> None:
    _assert_legacy_ingestor_has_v2_env(DEFAULT_COMPOSE_PATH)


def test_v2_compose_requires_only_internal_runtime_authorities() -> None:
    compose = _load_compose(V2_COMPOSE_PATH)
    configured = _environment_variables(
        compose["services"]["ingestor"]["environment"]
    )

    assert V2_RUNTIME_ENV_KEYS <= set(configured)
    assert not (V2_FORBIDDEN_ENV_KEYS & set(configured))
    for key in V2_RUNTIME_ENV_KEYS:
        assert _compose_env_ref_is_valid(configured[key], key)
        assert f"${{{key}:?" in configured[key]


def test_v2_compose_mounts_exact_release_registry_authority_read_only() -> None:
    compose = _load_compose(V2_COMPOSE_PATH)
    service = compose["services"]["ingestor"]
    configured = _environment_variables(service["environment"])

    assert (
        configured["RAG_RELEASE_REGISTRY_PATH"]
        == "/app/release/release-registry.json"
    )
    assert _compose_env_ref_is_valid(
        configured["RAG_RELEASE_REGISTRY_SHA256"],
        "RAG_RELEASE_REGISTRY_SHA256",
    )
    assert "${RAG_RELEASE_REGISTRY_SHA256:?" in configured[
        "RAG_RELEASE_REGISTRY_SHA256"
    ]

    release_mounts = [
        volume
        for volume in service["volumes"]
        if isinstance(volume, str) and ":/app/release:" in volume
    ]
    assert release_mounts == [
        "${RAG_RELEASE_REGISTRY_HOST_DIR:-../../rag-pedago/data/releases/"
        "prerentree_2026_2027}:/app/release:ro"
    ]

    source = release_mounts[0].rsplit(":", 2)[0]
    match = re.fullmatch(r"\$\{RAG_RELEASE_REGISTRY_HOST_DIR:-([^}]+)\}", source)
    assert match is not None
    resolved = (V2_COMPOSE_PATH.parent / match.group(1)).resolve()
    assert (resolved / "release-registry.json").is_file()
    assert (resolved / "wave0" / "wave0.release.json").is_file()
    assert (resolved / "multilevel" / "multilevel.release.json").is_file()


def test_v2_compose_contains_only_the_read_review_stack() -> None:
    """La topologie canonique reste lecture/revue, plus sa seule supervision.

    P0-L6A ajoute `alertmanager` : une règle qui se déclenche n'allait nulle
    part. Comme Prometheus, il n'apporte aucune capacité métier — ni writer, ni
    parseur, ni client de source distante, ni interface — et n'est joignable
    que sur la boucle locale. L'invariant protégé par ce test n'est pas le
    nombre de services : c'est qu'aucune capacité du moteur A ne réapparaisse
    ici.
    """
    compose = _load_compose(V2_COMPOSE_PATH)

    assert set(compose["services"]) == {
        "pgvector",
        "ingestor",
        "prometheus",
        "alertmanager",
    }
    assert set(compose["volumes"]) == {
        "rag_pgvector_data",
        "rag_prometheus_data",
        "rag_alertmanager_data",
    }

    forbidden = {"chroma", "ollama", "ui", "redis", "worker", "celery", "nginx"}
    assert not forbidden & set(compose["services"])

    for name in ("prometheus", "alertmanager"):
        published = compose["services"][name].get("ports", [])
        assert published, f"{name} must publish on loopback only, never nothing"
        assert all(
            str(port).startswith("127.0.0.1:") for port in published
        ), (name, published)


def test_v2_compose_ingestion_control_lives_in_a_separate_opt_in_file() -> None:
    """LOT44f (ADR-0031), remédiation revue PR#90 : le plan de contrôle
    d'ingestion gouvernée n'est jamais chargé par la commande normale du
    runtime v2 — `docker-compose.v2.yml` est revenu à l'état exact
    d'origin/main (assertion stricte ci-dessus). Il vit dans un fichier
    Compose séparé, strictement additif, chargé uniquement par un second
    `-f` explicite."""
    ingestion_compose_path = V2_COMPOSE_PATH.parent / "docker-compose.ingestion.yml"
    assert ingestion_compose_path.is_file()

    compose = _load_compose(ingestion_compose_path)
    services = compose["services"]

    # Remédiation GATE H1 (item K) : deux autorités d'opérateur ponctuelles
    # s'ajoutent aux deux services d'origine. Elles restent hors du `up`
    # normal grâce à `profiles: [operator]` — vérifié explicitement ci-dessous
    # plutôt que par leur simple absence de cette liste.
    assert set(services) == {
        "migrator-ingestion-control",
        "ingestion-worker",
        "publication-resume-worker",
        "scope-authority-operator",
        "publication-attestor-operator",
    }
    assert set(compose["volumes"]) == {"rag_ingestion_artifacts_data"}

    for operator in ("scope-authority-operator", "publication-attestor-operator"):
        assert services[operator]["profiles"] == ["operator"], (
            f"{operator} must never start with a plain `up`"
        )
        assert "ports" not in services[operator]

    assert "ports" not in services["ingestion-worker"]
    assert "ports" not in services["publication-resume-worker"]
    assert services["migrator-ingestion-control"]["restart"] == "no"


def test_v2_compose_alone_never_requires_ingestion_env_vars() -> None:
    """Le rendu de `docker-compose.v2.yml` seul ne doit jamais échouer sur
    une variable d'environnement d'ingestion — sinon la commande normale du
    runtime v2 serait cassée par une fonctionnalité opt-in non activée
    (régression exacte signalée en revue PR#90)."""
    content = V2_COMPOSE_PATH.read_text(encoding="utf-8")
    assert "INGESTION_CONTROL" not in content
    assert "PG_INGESTION_CONTROL_DSN" not in content
    assert "ingestion-worker" not in content
    assert "migrator-ingestion-control" not in content


def test_v2_ingestor_has_no_writer_mount_or_dependency() -> None:
    compose = _load_compose(V2_COMPOSE_PATH)
    ingestor = compose["services"]["ingestor"]
    volumes = "\n".join(str(item) for item in ingestor["volumes"])

    assert set(ingestor["depends_on"]) == {"pgvector"}
    assert "/data/uploads" not in volumes
    assert "/creds" not in volumes


def test_v2_up_uses_wired_v2_compose() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert "COMPOSE_V2=docker compose -f infra/docker-compose.v2.yml" in makefile
    recipe = _make_target_recipe(makefile, "v2-up")
    assert "up -d --build --wait" in recipe
    assert "sleep" not in recipe
    assert "||" not in recipe
    for obsolete_target in (
        "v2-migrate-chroma:",
        "v2-migrate-qdrant:",
        "v2-eval:",
        "v2-stats:",
        "v2-cleanup:",
    ):
        assert obsolete_target not in makefile


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
    assert "requirements.runtime-v2.txt" in content, (
        "Dockerfile.ingestor-v2 must install the minimal v2 runtime manifest"
    )
    assert (
        "COPY services/rag-engine/src/ingestor/retrieval_contract_adapter.py "
        "/app/retrieval_contract_adapter.py"
    ) in content, "the flattened v2 image must include every imported contract adapter"


def test_ingestion_worker_image_preserves_the_ingestor_package_boundary() -> None:
    dockerfile = (
        ENGINE_ROOT / "infra" / "Dockerfile.ingestion-worker"
    ).read_text(encoding="utf-8")
    compose = _load_compose(ENGINE_ROOT / "infra" / "docker-compose.ingestion.yml")

    assert (
        "COPY services/rag-engine/src/ingestor/__init__.py "
        "/app/ingestor/__init__.py"
    ) in dockerfile
    assert "/app/ingestor/ingestion_agents/" in dockerfile
    assert "/app/ingestor/ingestion_control/" in dockerfile
    assert 'CMD ["python", "-m", "ingestor.ingestion_worker.cli"]' in dockerfile

    assert compose["services"]["ingestion-worker"]["command"][:3] == [
        "python",
        "-m",
        "ingestor.ingestion_worker.cli",
    ]
    assert compose["services"]["publication-resume-worker"]["command"][:3] == [
        "python",
        "-m",
        "ingestor.ingestion_worker.publication_resume_cli",
    ]


def test_v2_image_packages_the_authoritative_taxonomy() -> None:
    """Le catalogue runtime doit pouvoir vérifier chaque taxonomie déclarée."""
    dockerfile = (ENGINE_ROOT / "infra" / "Dockerfile.ingestor-v2").read_text(
        encoding="utf-8"
    )
    dockerignore = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
    catalogue = yaml.safe_load((CONFIGS_DIR / "rag_collections.yml").read_text())

    assert "COPY services/rag-pedago/taxonomy/ /app/taxonomy/" in dockerfile
    assert "!services/rag-pedago/taxonomy/" in dockerignore
    assert "!services/rag-pedago/taxonomy/**" in dockerignore
    assert TAXONOMY_DIR.is_dir()

    missing = sorted(
        str(taxonomy_file)
        for definition in catalogue["collections"].values()
        if (taxonomy_file := definition.get("taxonomy_file"))
        and not (TAXONOMY_DIR / str(taxonomy_file)).is_file()
    )
    assert missing == []


def test_v2_compose_has_no_writer_worker() -> None:
    compose = _load_compose(V2_COMPOSE_PATH)
    assert "worker" not in compose["services"]


def test_v2_pydantic_pin_aligned_with_contracts() -> None:
    """Pydantic pin in the runtime manifest must match contracts."""
    contracts_toml = REPO_ROOT / "packages" / "contracts" / "pyproject.toml"
    v2_reqs = ENGINE_ROOT / "src" / "ingestor" / "requirements.runtime-v2.txt"

    assert contracts_toml.is_file()
    assert v2_reqs.is_file()

    # Extract pydantic pin from contracts
    import re
    contracts_text = contracts_toml.read_text(encoding="utf-8")
    m = re.search(r'"pydantic==([^"]+)"', contracts_text)
    assert m, "contracts pyproject.toml must pin pydantic"
    contracts_pydantic = m.group(1)

    # Extract pydantic pin from the v2 runtime manifest
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
    _assert_legacy_ingestor_has_v2_env(DEFAULT_COMPOSE_PATH)


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
    """LOT41 disables the unscoped search warmup in every environment."""
    source = (ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py").read_text(
        encoding="utf-8"
    )
    assert "CACHE_ENABLED = False" in source
    assert 'os.environ.get("RERANK_CACHE"' not in source


def test_prod_deployment_plan_does_not_persist_rendered_compose_secrets() -> None:
    plan = DEPLOYMENT_PLAN.read_text(encoding="utf-8")

    assert "/tmp/rag-ui-compose.rendered" not in plan
    assert "docker compose config --format json >" not in plan
    assert '["docker", "compose", "config", "--format", "json"]' in plan
    assert "stdout=subprocess.PIPE" in plan
