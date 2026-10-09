"""Qualification locale et sans mutation des matériaux du candidat public."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import public_blue_green_preflight as preflight  # noqa: E402

SHA = "a" * 40
IMAGE = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "b" * 64
COCKPIT_IMAGE = "ghcr.io/cyranoaladin/rag-cockpit@sha256:" + "e" * 64
REDIS_IMAGE = "docker.io/library/redis@sha256:" + "f" * 64
REDIS_PASSWORD = "redis-secret-for-test-0123456789"
TARGETS = {
    "/docker-entrypoint-initdb.d/00_init.sql": "postgres/init.sql",
    "/docker-entrypoint-initdb.d/01_003_profile_filtering.sql": "postgres/migrations/003_profile_filtering.sql",
    "/docker-entrypoint-initdb.d/02_004_artifact_placements.sql": "postgres/migrations/004_artifact_placements.sql",
    "/docker-entrypoint-initdb.d/03_005_official_snapshot_currentness.sql": "postgres/migrations/005_official_snapshot_currentness.sql",
    "/docker-entrypoint-initdb.d/04_register_bootstrap_migrations.sh": "postgres/register_bootstrap_migrations.sh",
    "/docker-entrypoint-initdb.d/05_provision_runtime_roles.sh": "postgres/provision_runtime_roles.sh",
    "/docker-entrypoint-migrations": "postgres/migrations",
    "/docker-entrypoint-healthcheck.sh": "postgres/healthcheck.sh",
    "/pgvector-migration-state.sh": "scripts/lib/pgvector_migration_state.sh",
    "/schema-head-005-fingerprints.env": "postgres/schema_head_005_fingerprints.env",
    "/schema-head-005-columns.tsv": "postgres/schema_head_005_columns.tsv",
    "/app/configs": "configs",
    "/app/release": "release",
    "/app/servable-corpus": "servable-corpus",
    "/models/e5-large": "models/e5-large",
    "/models/reranker": "models/reranker",
    "/etc/prometheus/prometheus.yml": "prometheus/prometheus.v2.yml",
    "/etc/prometheus/rules": "prometheus/rules",
}


def _cockpit_fixture(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    repo = tmp_path / "checkout"
    repo.mkdir()
    root = tmp_path / "release-x"
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    secret_root.chmod(0o700)
    secret = secret_root / "api-clients.json"
    secret.write_text(json.dumps([{
        "client_id": "cockpit-search",
        "token_sha256": hashlib.sha256(b"cockpit-search-key").hexdigest(),
        "scopes": ["rag:search"],
    }]), encoding="utf-8")
    secret.chmod(0o600)
    cockpit_env = {
        "RAG_ENGINE_INTERNAL_URL": "http://ingestor:8001",
        "RAG_ENGINE_INTERNAL_TOKEN": "bff-service-secret",
        "RAG_ENGINE_API_KEY": "cockpit-search-key",
        "NEXUS_INTERNAL_TOKEN_SECRET": "internal-signature-secret-long-enough",
        "NEXUS_INTERNAL_TOKEN_ISSUER": "nexus-cockpit",
        "NEXUS_INTERNAL_TOKEN_AUDIENCE": "nexus-rag-engine",
        "NEXUS_SSO_ISSUER": "https://sso.example.test",
        "NEXUS_SSO_AUDIENCE": "nexus-cockpit",
        "NEXUS_SSO_JWKS_URL": "https://sso.example.test/.well-known/jwks.json",
        "NEXUS_RELEASE_SCHOOL_YEAR": "2026-2027",
        "NEXTAUTH_SECRET": "nextauth-secret-long-enough-for-test",
        "NEXTAUTH_URL": "https://cockpit.example.test",
        "NEXUS_COCKPIT_PUBLIC_ORIGIN": "https://cockpit.example.test",
        "NEXUS_SESSION_REDIS_URL": f"redis://default:{quote(REDIS_PASSWORD)}@session-redis:6379/0",
    }
    (secret_root / "cockpit.env").write_text(
        "".join(f"{key}={value}\n" for key, value in cockpit_env.items()), encoding="utf-8"
    )
    (secret_root / "cockpit.env").chmod(0o600)
    (secret_root / "session-redis.acl").write_text(
        "user default on #" + hashlib.sha256(REDIS_PASSWORD.encode()).hexdigest()
        + " ~nexus:session:v1:* +@connection +get +set\n",
        encoding="utf-8",
    )
    (secret_root / "session-redis.acl").chmod(0o644)
    files: dict[str, str] = {}
    for relative in set(TARGETS.values()):
        path = root / relative
        if Path(relative).suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            path.mkdir(parents=True, exist_ok=True)
            child = path / "payload.bin"
            child.write_text(relative, encoding="utf-8")
            files[str(child.relative_to(root))] = hashlib.sha256(child.read_bytes()).hexdigest()
    manifest = {"protocol": "NEXUS-PUBLIC-MATERIAL-V1", "source_sha": SHA, "files": files}
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (root / "release-material-manifest.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    def bind(source: Path, target: str) -> dict:
        return {"type": "bind", "source": str(source), "target": target, "read_only": True}

    volumes = {
        "pgvector": [
            bind(root / relative, target)
            for target, relative in TARGETS.items()
            if target.startswith(("/docker-entrypoint-", "/pgvector-", "/schema-head-"))
        ],
        "ingestor": [
            *(
                bind(root / relative, target)
                for target, relative in TARGETS.items()
                if target.startswith(("/app/", "/models/"))
            ),
            bind(secret, "/app/api-clients/api-clients.json"),
        ],
        "prometheus": [
            bind(root / relative, target)
            for target, relative in TARGETS.items()
            if target.startswith("/etc/prometheus/")
        ],
    }
    config = {
        "name": "nexus-rag-blue",
        "networks": {
            "rag_net": {"name": "nexus-rag-blue_rag_net", "driver": "bridge", "ipam": {}},
            "bff_net": {"name": "nexus-rag-blue_bff_net", "driver": "bridge", "ipam": {}},
        },
        "volumes": {
            "rag_pgvector_data": {"name": "nexus-rag-blue_rag_pgvector_data"},
            "rag_prometheus_data": {"name": "nexus-rag-blue_rag_prometheus_data"},
            "session_redis_data": {"name": "nexus-rag-blue_session_redis_data"},
        },
        "services": {
            "pgvector": {
                "image": "pgvector/pgvector@sha256:" + "c" * 64,
                "security_opt": ["no-new-privileges:true"],
                "environment": {"POSTGRES_DB": "ragdb"},
                "networks": {"rag_net": None},
                "volumes": [*volumes["pgvector"], {"type": "volume", "source": "rag_pgvector_data", "target": "/var/lib/postgresql/data"}],
                "ports": [],
            },
            "ingestor": {
                "image": IMAGE,
                "security_opt": ["no-new-privileges:true"],
                "environment": {
                    "PG_RAG_DSN": "postgresql://rag_reader:dummy@pgvector:5432/ragdb",
                    "PG_REVIEW_DSN": "postgresql://rag_reviewer:dummy@pgvector:5432/ragdb",
                    "RAG_BFF_SERVICE_TOKEN": "bff-service-secret",
                    "RAG_API_CLIENTS_FILE": "/app/api-clients/api-clients.json",
                    "NEXUS_INTERNAL_TOKEN_SECRET": "internal-signature-secret-long-enough",
                    "NEXUS_INTERNAL_TOKEN_ISSUER": "nexus-cockpit",
                    "NEXUS_INTERNAL_TOKEN_AUDIENCE": "nexus-rag-engine",
                    "NEXUS_SSO_ISSUER": "https://sso.example.test",
                    "NEXUS_SSO_AUDIENCE": "nexus-cockpit",
                },
                "networks": {"rag_net": None, "bff_net": None},
                "volumes": volumes["ingestor"],
                "ports": [{"host_ip": "127.0.0.1", "published": "18101", "target": 8001}],
                "labels": {"nexus.release-material.sha256": digest},
            },
            "prometheus": {
                "image": "prom/prometheus@sha256:" + "d" * 64,
                "security_opt": ["no-new-privileges:true"],
                "networks": {"rag_net": None},
                "volumes": [*volumes["prometheus"], {"type": "volume", "source": "rag_prometheus_data", "target": "/prometheus"}],
                "ports": [{"host_ip": "127.0.0.1", "published": "19101", "target": 9090}],
            },
            "cockpit": {
                "image": COCKPIT_IMAGE,
                "security_opt": ["no-new-privileges:true"],
                "environment": {"NODE_ENV": "production", **cockpit_env},
                "networks": {"bff_net": None},
                "volumes": [],
                "ports": [{"host_ip": "127.0.0.1", "published": "13101", "target": 3000}],
                "read_only": True,
            },
            "session-redis": {
                "image": REDIS_IMAGE,
                "security_opt": ["no-new-privileges:true"],
                "networks": {"bff_net": None},
                "volumes": [
                    {"type": "volume", "source": "session_redis_data", "target": "/data"},
                    bind(secret_root / "session-redis.acl", "/run/secrets/session-redis.acl"),
                ],
                "ports": [],
                "command": ["redis-server", "--appendonly", "yes", "--appendfsync", "always", "--aclfile", "/run/secrets/session-redis.acl"],
            },
        },
    }
    return config, root, secret_root, repo


def _fixture(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    """Fixture du plan signé historique à trois services, encore plan-only."""
    config, root, secrets, repo = _cockpit_fixture(tmp_path)
    config["services"].pop("cockpit")
    config["services"].pop("session-redis")
    config["volumes"].pop("session_redis_data")
    return config, root, secrets, repo


def _check(config: dict, root: Path, secrets: Path, repo: Path) -> dict:
    return preflight.require_public_candidate(
        resolved_compose=config,
        source_sha=SHA,
        color="blue",
        material_root=root,
        secrets_root=secrets,
        repo_root=repo,
        verified_application_images={"ingestor": IMAGE, "cockpit": COCKPIT_IMAGE},
    )


def _compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(
            ["docker", "compose", "version"], capture_output=True, check=False, timeout=5
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def test_accepts_exact_public_candidate_material(tmp_path: Path) -> None:
    config, root, secrets, repo = _cockpit_fixture(tmp_path)
    evidence = _check(config, root, secrets, repo)
    assert evidence["project"] == "nexus-rag-blue"
    assert evidence["material_files"] == 18
    assert evidence["api_image"] == IMAGE
    assert evidence["cockpit_image"] == COCKPIT_IMAGE
    assert evidence["redis_image"] == REDIS_IMAGE
    assert evidence["mutation_allowed"] is False
    assert evidence["material_manifest_digest"] == config["services"]["ingestor"]["labels"]["nexus.release-material.sha256"]


def test_legacy_three_service_plan_stays_plan_only(tmp_path: Path) -> None:
    config, root, secrets, repo = _fixture(tmp_path)
    evidence = preflight.require_public_candidate(
        resolved_compose=config,
        source_sha=SHA,
        color="blue",
        material_root=root,
        secrets_root=secrets,
        repo_root=repo,
        verified_application_images={"ingestor": IMAGE},
    )
    assert set(config["services"]) == {"pgvector", "ingestor", "prometheus"}
    assert evidence["api_image"] == IMAGE
    assert "cockpit_image" not in evidence
    assert evidence["mutation_allowed"] is False


@pytest.mark.skipif(not _compose_available(), reason="Docker Compose indisponible")
def test_accepts_actual_resolved_five_service_compose(tmp_path: Path) -> None:
    expected, root, secrets, repo = _cockpit_fixture(tmp_path)
    infra = Path(__file__).resolve().parents[1] / "infra"
    base = infra / "docker-compose.v2.yml"
    overlay = infra / "docker-compose.public-blue-green.yml"
    names = set(re.findall(r"\$\{([A-Z][A-Z0-9_]+):\?",
                           base.read_text() + overlay.read_text()))
    env = {**os.environ, **{name: "synthetic" for name in names}}
    env.update({name: str(root / name.lower()) for name in names
                if name.endswith(("HOST_DIR", "HOST_FILE"))})
    env.update(
        NEXUS_RELEASE_MATERIAL_ROOT=str(root),
        NEXUS_RUNTIME_SECRETS_ROOT=str(secrets),
        NEXUS_INGESTOR_IMAGE_SHA256="b" * 64,
        NEXUS_COCKPIT_IMAGE_SHA256="e" * 64,
        NEXUS_REDIS_IMAGE_SHA256="f" * 64,
        NEXUS_RELEASE_MATERIAL_MANIFEST_SHA256=expected["services"]["ingestor"]["labels"]["nexus.release-material.sha256"],
        NEXUS_SEARCH_PORT="18101", NEXUS_PROM_PORT="19101", NEXUS_COCKPIT_PORT="13101",
        PG_RAG_DSN="postgresql://rag_reader:dummy@pgvector:5432/ragdb",
        PG_REVIEW_DSN="postgresql://rag_reviewer:dummy@pgvector:5432/ragdb",
        RAG_BFF_SERVICE_TOKEN="bff-service-secret",
        NEXUS_INTERNAL_TOKEN_SECRET="internal-signature-secret-long-enough",
        NEXUS_INTERNAL_TOKEN_ISSUER="nexus-cockpit",
        NEXUS_INTERNAL_TOKEN_AUDIENCE="nexus-rag-engine",
        NEXUS_SSO_ISSUER="https://sso.example.test",
        NEXUS_SSO_AUDIENCE="nexus-cockpit",
    )
    completed = subprocess.run(
        ["docker", "compose", "-p", "nexus-rag-blue", "-f", str(base), "-f", str(overlay),
         "config", "--format", "json"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    resolved = json.loads(completed.stdout)
    evidence = _check(resolved, root, secrets, repo)
    assert evidence["mutation_allowed"] is False
    assert evidence["cockpit_image"] == COCKPIT_IMAGE


@pytest.mark.parametrize("mutation", [
    "missing_cockpit", "extra_writer", "cockpit_tag", "cockpit_wrong_digest",
    "cockpit_on_rag_net", "cockpit_public_port", "cockpit_wrong_port",
    "cockpit_db_dsn", "cockpit_internal_url", "cockpit_memory_store",
    "cockpit_extra_hosts", "cockpit_privileged", "cockpit_entrypoint",
    "cockpit_secret_override", "cockpit_env_missing", "cockpit_env_symlink",
    "cockpit_env_readable", "redis_on_rag_net", "redis_public_port",
    "redis_extra_hosts", "duplicate_loopback_port",
    "redis_tag", "redis_foreign_volume", "redis_acl_missing", "redis_acl_symlink",
    "redis_acl_writable", "redis_acl_mismatch", "redis_no_appendonly",
    "api_registry_unknown_key", "api_registry_ingest_scope", "api_registry_admin_scope",
    "api_registry_read_source_scope", "api_registry_inline_override",
    "redis_acl_unreadable_by_image_user", "secret_root_not_private",
    "school_year_gap", "public_origin_missing_host", "public_origin_userinfo",
    "cockpit_unconfined_seccomp", "redis_unconfined_seccomp",
])
def test_refuses_unsafe_cockpit_or_redis(tmp_path: Path, mutation: str) -> None:
    config, root, secrets, repo = _cockpit_fixture(tmp_path)
    cockpit = config["services"]["cockpit"]
    redis = config["services"]["session-redis"]
    if mutation == "missing_cockpit":
        config["services"].pop("cockpit")
    elif mutation == "extra_writer":
        config["services"]["writer"] = dict(cockpit)
    elif mutation == "cockpit_tag":
        cockpit["image"] = "ghcr.io/cyranoaladin/rag-cockpit:latest"
    elif mutation == "cockpit_wrong_digest":
        cockpit["image"] = "ghcr.io/cyranoaladin/rag-cockpit@sha256:" + "0" * 64
    elif mutation == "cockpit_on_rag_net":
        cockpit["networks"]["rag_net"] = None
    elif mutation == "cockpit_public_port":
        cockpit["ports"][0]["host_ip"] = "0.0.0.0"
    elif mutation == "cockpit_wrong_port":
        cockpit["ports"][0]["target"] = 8001
    elif mutation == "cockpit_db_dsn":
        cockpit["environment"]["PG_RAG_DSN"] = "postgresql://pgvector:5432/ragdb"
    elif mutation == "cockpit_internal_url":
        cockpit["environment"]["RAG_ENGINE_INTERNAL_URL"] = "http://localhost:8001"
    elif mutation == "cockpit_memory_store":
        cockpit["environment"]["NEXUS_SESSION_STORE_MODE"] = "memory"
    elif mutation == "cockpit_extra_hosts":
        cockpit["extra_hosts"] = ["pgvector=host-gateway"]
    elif mutation == "cockpit_privileged":
        cockpit["privileged"] = True
    elif mutation == "cockpit_entrypoint":
        cockpit["entrypoint"] = ["sh", "-c", "cat /proc/self/environ"]
    elif mutation == "cockpit_secret_override":
        cockpit["environment"]["RAG_ENGINE_API_KEY"] = "other"
    elif mutation == "cockpit_env_missing":
        (secrets / "cockpit.env").unlink()
    elif mutation == "cockpit_env_symlink":
        (secrets / "cockpit.env").unlink()
        (secrets / "cockpit.env").symlink_to(secrets / "api-clients.json")
    elif mutation == "cockpit_env_readable":
        (secrets / "cockpit.env").chmod(0o644)
    elif mutation == "redis_on_rag_net":
        redis["networks"]["rag_net"] = None
    elif mutation == "redis_public_port":
        redis["ports"] = [{"host_ip": "0.0.0.0", "published": "6379", "target": 6379}]
    elif mutation == "redis_extra_hosts":
        redis["extra_hosts"] = ["pgvector=host-gateway"]
    elif mutation == "duplicate_loopback_port":
        cockpit["ports"][0]["published"] = "18101"
    elif mutation == "redis_tag":
        redis["image"] = "redis:latest"
    elif mutation == "redis_foreign_volume":
        redis["volumes"][0]["source"] = "infra_session_redis_data"
    elif mutation == "redis_acl_missing":
        (secrets / "session-redis.acl").unlink()
    elif mutation == "redis_acl_symlink":
        (secrets / "session-redis.acl").unlink()
        (secrets / "session-redis.acl").symlink_to(secrets / "api-clients.json")
    elif mutation == "redis_acl_writable":
        (secrets / "session-redis.acl").chmod(0o666)
    elif mutation == "redis_acl_mismatch":
        (secrets / "session-redis.acl").write_text(
            "user default on #" + "0" * 64
            + " ~nexus:session:v1:* +@connection +get +set\n", encoding="utf-8"
        )
    elif mutation == "redis_no_appendonly":
        redis["command"] = ["redis-server", "--aclfile", "/run/secrets/session-redis.acl"]
    elif mutation == "api_registry_unknown_key":
        registry = json.loads((secrets / "api-clients.json").read_text())
        registry[0]["token_sha256"] = hashlib.sha256(b"another-key").hexdigest()
        (secrets / "api-clients.json").write_text(json.dumps(registry))
    elif mutation in {"api_registry_ingest_scope", "api_registry_admin_scope", "api_registry_read_source_scope"}:
        registry = json.loads((secrets / "api-clients.json").read_text())
        registry[0]["scopes"].append({
            "api_registry_ingest_scope": "rag:ingest",
            "api_registry_admin_scope": "rag:admin",
            "api_registry_read_source_scope": "rag:read-source",
        }[mutation])
        (secrets / "api-clients.json").write_text(json.dumps(registry))
    elif mutation == "api_registry_inline_override":
        config["services"]["ingestor"]["environment"]["RAG_API_CLIENTS"] = "[]"
    elif mutation == "redis_acl_unreadable_by_image_user":
        (secrets / "session-redis.acl").chmod(0o600)
    elif mutation == "secret_root_not_private":
        secrets.chmod(0o755)
    elif mutation == "cockpit_unconfined_seccomp":
        cockpit["security_opt"].append("seccomp:unconfined")
    elif mutation == "redis_unconfined_seccomp":
        redis["security_opt"].append("seccomp:unconfined")
    elif mutation in {"school_year_gap", "public_origin_missing_host", "public_origin_userinfo"}:
        replacement = {
            "school_year_gap": ("NEXUS_RELEASE_SCHOOL_YEAR", "2026-2028"),
            "public_origin_missing_host": ("NEXTAUTH_URL", "https://"),
            "public_origin_userinfo": ("NEXTAUTH_URL", "https://user:pass@cockpit.example.test"),
        }[mutation]
        key, value = replacement
        if key == "NEXTAUTH_URL":
            cockpit["environment"]["NEXUS_COCKPIT_PUBLIC_ORIGIN"] = value
        cockpit["environment"][key] = value
        path = secrets / "cockpit.env"
        lines = path.read_text().splitlines()
        keys = {key, "NEXUS_COCKPIT_PUBLIC_ORIGIN"} if key == "NEXTAUTH_URL" else {key}
        path.write_text("\n".join(f"{line.split('=', 1)[0]}={value}" if line.split('=', 1)[0] in keys else line for line in lines) + "\n")
    with pytest.raises(preflight.PublicCandidateError):
        _check(config, root, secrets, repo)


def test_live_provenance_is_checked_for_exact_source_and_api_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, root, secrets, repo = _cockpit_fixture(tmp_path)
    calls: list[dict] = []

    def verify(**kwargs: object) -> dict[str, str]:
        calls.append(kwargs)
        return {"ingestor": IMAGE, "cockpit": COCKPIT_IMAGE}

    monkeypatch.setattr(preflight.dii, "verify_public_candidate_image_provenance", verify)
    monkeypatch.setattr(
        preflight.dii, "verify_application_image_provenance",
        lambda **_kwargs: pytest.fail("legacy image verifier used for five-service candidate"),
    )
    evidence = preflight.require_candidate_with_live_provenance(
        resolved_compose=config,
        source_sha=SHA,
        source_tree_sha="f" * 40,
        color="blue",
        material_root=root,
        secrets_root=secrets,
        repo_root=repo,
        provenance_run_id=42,
        provenance_run_attempt=1,
        github_api_get=lambda path: {},
        download_artifact=lambda run, name, where: where,
        work_dir=tmp_path / "work",
    )
    assert evidence["api_image"] == IMAGE
    assert calls[0]["repository"] == "cyranoaladin/RAG"
    assert calls[0]["source_commit_sha"] == SHA
    assert calls[0]["source_tree_sha"] == "f" * 40
    config["services"]["ingestor"]["image"] = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "0" * 64
    with pytest.raises(preflight.PublicCandidateError):
        preflight.require_candidate_with_live_provenance(
            resolved_compose=config,
            source_sha=SHA,
            source_tree_sha="f" * 40,
            color="blue",
            material_root=root,
            secrets_root=secrets,
            repo_root=repo,
            provenance_run_id=42,
            provenance_run_attempt=1,
            github_api_get=lambda path: {},
            download_artifact=lambda run, name, where: where,
            work_dir=tmp_path / "work",
        )


def test_refuses_mutable_root_alias_and_hardlinked_material(tmp_path: Path) -> None:
    config, root, secrets, repo = _cockpit_fixture(tmp_path)
    alias = tmp_path / "current"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(preflight.PublicCandidateError, match="symlink"):
        _check(config, alias, secrets, repo)

    linked = tmp_path / "outside-copy"
    linked.hardlink_to(root / "postgres/init.sql")
    with pytest.raises(preflight.PublicCandidateError, match="hardlinked"):
        _check(config, root, secrets, repo)


def test_refuses_release_material_under_a_different_git_worktree(tmp_path: Path) -> None:
    config, root, secrets, repo = _cockpit_fixture(tmp_path)
    sibling = tmp_path / "other-worktree"
    sibling.mkdir()
    (sibling / ".git").write_text("gitdir: ../.git/worktrees/other\n", encoding="utf-8")
    moved = sibling / root.name
    root.rename(moved)
    for service in config["services"].values():
        for volume in service["volumes"]:
            source = volume.get("source", "")
            if source.startswith(str(root) + "/"):
                volume["source"] = str(moved / Path(source).relative_to(root))
    with pytest.raises(preflight.PublicCandidateError, match="checkout"):
        _check(config, moved, secrets, repo)


def test_refuses_unreadable_material_subdirectory(tmp_path: Path) -> None:
    config, root, secrets, repo = _cockpit_fixture(tmp_path)
    hidden = root / "configs" / "unreadable"
    hidden.mkdir()
    (hidden / "unlisted.txt").write_text("secret", encoding="utf-8")
    hidden.chmod(0)
    try:
        with pytest.raises(preflight.PublicCandidateError, match="inventory"):
            _check(config, root, secrets, repo)
    finally:
        hidden.chmod(0o700)


@pytest.mark.parametrize("mutation", ["wrong_project", "wrong_image", "writer", "publisher_dsn", "publisher_secret", "public_db", "external_db", "query_override", "external_network", "external_bff_network", "db_on_bff", "prom_on_bff", "api_without_db_network", "api_without_bff_network", "foreign_volume_definition", "checkout_bind", "writable_bind", "wrong_label", "missing_label", "changed_file", "extra_file", "symlink", "missing_bind", "unlisted_target", "foreign_volume", "missing_volume"])
def test_refuses_unsealed_or_unsafe_candidate(tmp_path: Path, mutation: str) -> None:
    config, root, secrets, repo = _cockpit_fixture(tmp_path)
    services = config["services"]
    if mutation == "wrong_project":
        config["name"] = "infra"
    elif mutation == "wrong_image":
        services["ingestor"]["image"] = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "e" * 64
    elif mutation == "writer":
        services["worker"] = {"image": IMAGE}
    elif mutation == "publisher_dsn":
        services["ingestor"]["environment"]["PG_PUBLISHER_DSN"] = "postgresql://rag_publisher:dummy@pgvector:5432/ragdb"
    elif mutation == "publisher_secret":
        services["ingestor"]["environment"]["PGVECTOR_PUBLISHER_PASSWORD"] = "dummy"
    elif mutation == "public_db":
        services["pgvector"]["ports"] = [{"host_ip": "0.0.0.0", "published": "5436", "target": 5432}]
    elif mutation == "external_db":
        services["ingestor"]["environment"]["PG_RAG_DSN"] = "postgresql://rag_reader:dummy@historic-db:5432/ragdb"
    elif mutation == "query_override":
        services["ingestor"]["environment"]["PG_RAG_DSN"] += "?host=historic-db"
    elif mutation == "external_network":
        config["networks"]["rag_net"]["external"] = True
    elif mutation == "external_bff_network":
        config["networks"]["bff_net"]["external"] = True
    elif mutation == "db_on_bff":
        services["pgvector"]["networks"]["bff_net"] = None
    elif mutation == "prom_on_bff":
        services["prometheus"]["networks"]["bff_net"] = None
    elif mutation == "api_without_db_network":
        services["ingestor"]["networks"].pop("rag_net")
    elif mutation == "api_without_bff_network":
        services["ingestor"]["networks"].pop("bff_net")
    elif mutation == "foreign_volume_definition":
        config["volumes"]["rag_pgvector_data"]["driver_opts"] = {"device": "/srv/historic/pgdata"}
    elif mutation == "checkout_bind":
        services["ingestor"]["volumes"][0]["source"] = str(repo)
    elif mutation == "writable_bind":
        services["ingestor"]["volumes"][0]["read_only"] = False
    elif mutation == "wrong_label":
        services["ingestor"]["labels"]["nexus.release-material.sha256"] = "0" * 64
    elif mutation == "missing_label":
        services["ingestor"].pop("labels")
    elif mutation == "changed_file":
        (root / "postgres/init.sql").write_text("tampered", encoding="utf-8")
    elif mutation == "extra_file":
        (root / "configs/extra").write_text("extra", encoding="utf-8")
    elif mutation == "missing_bind":
        services["ingestor"]["volumes"].pop(0)
    elif mutation == "unlisted_target":
        services["ingestor"]["volumes"].append({"type": "bind", "source": str(root / "configs"), "target": "/app/rogue", "read_only": True})
    elif mutation == "foreign_volume":
        services["pgvector"]["volumes"][-1]["source"] = "infra_rag_pgvector_data"
    elif mutation == "missing_volume":
        services["pgvector"]["volumes"].pop()
    else:
        target = root / "postgres/init.sql"
        target.unlink()
        target.symlink_to(repo)
    with pytest.raises(preflight.PublicCandidateError):
        _check(config, root, secrets, repo)
