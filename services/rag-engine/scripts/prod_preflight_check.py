#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

COMPOSE_CANDIDATES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)
ADMIN_TOKEN_KEY = "LEGACY_ADMIN_API_TOKEN"
INGESTOR_TOKEN_KEY = "INGESTOR_API_TOKEN"
TOKEN_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class PreflightError(RuntimeError):
    """Raised for a production preflight invariant failure."""


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate rag-ui production compose layout without exposing secrets."
    )
    parser.add_argument("--compose-dir", required=True, type=Path)
    parser.add_argument("--expected-config-source", required=True, type=Path)
    parser.add_argument("--expected-config-target", default="/app/configs")
    return parser.parse_args(argv)


def _find_compose_file(compose_dir: Path) -> Path:
    for filename in COMPOSE_CANDIDATES:
        candidate = compose_dir / filename
        if candidate.is_file():
            return candidate
    raise PreflightError("compose file missing")


def _read_env_keys(env_path: Path) -> dict[str, str]:
    if not env_path.is_file():
        raise PreflightError(".env file missing")
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _require_env(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise PreflightError(f"required env key missing: {key}")
    return value


_V2_ROLE_GROUPS: dict[str, tuple[str, ...]] = {
    "admin": ("RAG_ADMIN_TOKEN",),
    "reviewer": ("RAG_REVIEWER_TOKEN", "REVIEWER_API_TOKEN"),
    "teacher": ("RAG_TEACHER_TOKEN",),
    "ingest_agent": ("RAG_INGEST_AGENT_TOKEN", "INGESTOR_API_TOKEN", "INGEST_AUTH_TOKEN"),
    "student": ("RAG_STUDENT_TOKEN",),
}


def _validate_v2_role_token_uniqueness(env: dict[str, str]) -> None:
    """Reject any token value shared across distinct v2 roles."""
    token_to_role: dict[str, str] = {}
    for role, var_names in _V2_ROLE_GROUPS.items():
        for var_name in var_names:
            value = env.get(var_name, "").strip()
            if not value:
                continue
            if not TOKEN_PATTERN.fullmatch(value):
                raise PreflightError(
                    f"{var_name} must be a 64-character hex token"
                )
            existing_role = token_to_role.get(value)
            if existing_role is not None and existing_role != role:
                raise PreflightError(
                    "v2 role tokens must be distinct across roles"
                )
            token_to_role[value] = role


def _validate_env(env: dict[str, str], expected_target: str) -> None:
    if _require_env(env, "RAG_ENV") != "production":
        raise PreflightError("RAG_ENV must be production")
    if _require_env(env, "RAG_ENGINE_CONFIG_DIR") != expected_target:
        raise PreflightError("RAG_ENGINE_CONFIG_DIR must match expected config target")
    _require_env(env, "RAG_CONFIGS_HOST_DIR")
    if _require_env(env, "ALLOW_UNAUTHENTICATED_ADMIN_DEV") != "false":
        raise PreflightError("ALLOW_UNAUTHENTICATED_ADMIN_DEV must be false")
    admin_token = _require_env(env, ADMIN_TOKEN_KEY)
    if not TOKEN_PATTERN.fullmatch(admin_token):
        raise PreflightError("LEGACY_ADMIN_API_TOKEN must be a 64-character hex token")
    ingestor_token = _require_env(env, INGESTOR_TOKEN_KEY)
    if not TOKEN_PATTERN.fullmatch(ingestor_token):
        raise PreflightError("INGESTOR_API_TOKEN must be a 64-character hex token")
    v2_admin_token = _require_env(env, "RAG_ADMIN_TOKEN")
    if not TOKEN_PATTERN.fullmatch(v2_admin_token):
        raise PreflightError("RAG_ADMIN_TOKEN must be a 64-character hex token")
    ingest_auth_token = env.get("INGEST_AUTH_TOKEN", "").strip()
    if admin_token in {v2_admin_token, ingestor_token, ingest_auth_token}:
        raise PreflightError(
            "legacy admin, v2 admin, and ingestion tokens must be distinct"
        )
    _validate_v2_role_token_uniqueness(env)


def _validate_config_files(config_dir: Path) -> None:
    collections_path = config_dir / "rag_collections.yml"
    mapping_path = config_dir / "legacy_collection_mapping.yml"
    if not collections_path.is_file():
        raise PreflightError("configs/rag_collections.yml missing")
    if not mapping_path.is_file():
        raise PreflightError("configs/legacy_collection_mapping.yml missing")

    collections = yaml.safe_load(collections_path.read_text(encoding="utf-8"))
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(collections, dict):
        raise PreflightError("rag_collections.yml must be a mapping")
    if not isinstance(mapping, dict):
        raise PreflightError("legacy_collection_mapping.yml must be a mapping")
    domains = collections.get("domains")
    if not isinstance(domains, dict):
        raise PreflightError("rag_collections.yml domains missing")
    quarantine = domains.get("quarantine")
    if not isinstance(quarantine, dict) or quarantine.get("retrievable") is not False:
        raise PreflightError("rag_nexus_quarantine must be non retrievable")
    if mapping.get("rag_divers") != "rag_nexus_quarantine":
        raise PreflightError("rag_divers must map to rag_nexus_quarantine")


def _validate_gdrive_credentials_marker(compose_file: Path, compose_dir: Path, env: dict[str, str]) -> None:
    compose_text = compose_file.read_text(encoding="utf-8")
    if "GOOGLE_APPLICATION_CREDENTIALS" not in compose_text and "GOOGLE_APPLICATION_CREDENTIALS" not in env:
        return
    expected = compose_dir / "creds" / "gdrive-sa.json"
    if not expected.is_file():
        raise PreflightError("Google Drive credentials file missing")


def _render_compose_json(compose_dir: Path, compose_file: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(  # noqa: UP022 - keep stdout in memory, never on disk.
            ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
            cwd=compose_dir,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as exc:
        raise PreflightError("docker compose command unavailable") from exc
    if result.returncode != 0:
        raise PreflightError("docker compose config failed")
    try:
        rendered = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PreflightError("docker compose config did not return JSON") from exc
    if not isinstance(rendered, dict):
        raise PreflightError("docker compose config JSON must be an object")
    return rendered


def _same_path(left: Any, right: Path) -> bool:
    if not isinstance(left, str):
        return False
    return Path(left).expanduser().resolve() == right.expanduser().resolve()


def _validate_ingestor_config_mount(
    rendered: dict[str, Any],
    *,
    expected_source: Path,
    expected_target: str,
) -> None:
    services = rendered.get("services")
    if not isinstance(services, dict):
        raise PreflightError("compose services missing")
    ingestor = services.get("ingestor")
    if not isinstance(ingestor, dict):
        raise PreflightError("ingestor service missing")
    volumes = ingestor.get("volumes", [])
    if not isinstance(volumes, list):
        raise PreflightError("ingestor volumes must be a list")

    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        if (
            volume.get("type") == "bind"
            and _same_path(volume.get("source"), expected_source)
            and volume.get("target") == expected_target
            and volume.get("read_only") is True
        ):
            return
    raise PreflightError(
        "missing read-only ingestor configs bind mount with expected source and target /app/configs"
    )


def _port_host_ip(port: Any) -> str | None:
    if not isinstance(port, dict):
        return None
    for key in ("host_ip", "hostIp", "hostIP", "HostIp", "HostIP"):
        value = port.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _string_port_is_loopback(port: str) -> bool:
    return (
        port.startswith("127.0.0.1:")
        or port.startswith("localhost:")
        or port.startswith("[::1]:")
        or port.startswith("::1:")
    )


def _validate_no_public_host_port_bindings(rendered: dict[str, Any]) -> None:
    services = rendered.get("services")
    if not isinstance(services, dict):
        raise PreflightError("compose services missing")

    for service_name, service in services.items():
        if not isinstance(service, dict):
            raise PreflightError(f"{service_name} service must be a mapping")
        ports = service.get("ports", [])
        if ports is None:
            continue
        if not isinstance(ports, list):
            raise PreflightError(f"{service_name} ports must be a list")
        for port in ports:
            if isinstance(port, str):
                if _string_port_is_loopback(port):
                    continue
                raise PreflightError(f"{service_name} host port binding must be loopback-only")
            host_ip = _port_host_ip(port)
            if host_ip not in LOOPBACK_HOSTS:
                raise PreflightError(f"{service_name} host port binding must be loopback-only")


def run_preflight(
    *,
    compose_dir: Path,
    expected_config_source: Path,
    expected_config_target: str,
) -> None:
    if not compose_dir.is_dir():
        raise PreflightError("compose directory missing")
    compose_file = _find_compose_file(compose_dir)
    env = _read_env_keys(compose_dir / ".env")
    _validate_env(env, expected_config_target)
    _validate_config_files(compose_dir / "configs")
    _validate_gdrive_credentials_marker(compose_file, compose_dir, env)
    rendered = _render_compose_json(compose_dir, compose_file)
    _validate_ingestor_config_mount(
        rendered,
        expected_source=expected_config_source,
        expected_target=expected_config_target,
    )
    _validate_no_public_host_port_bindings(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        run_preflight(
            compose_dir=args.compose_dir.expanduser(),
            expected_config_source=args.expected_config_source.expanduser(),
            expected_config_target=args.expected_config_target,
        )
    except PreflightError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("OK: production preflight checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
