"""Préflight local du candidat public blue-green, sans mutation Docker.

Le digest du manifeste de matériaux est une étiquette du Compose résolu.
Une signature de readiness sur le digest de ce Compose lie donc ces octets
au manifeste exhaustif, puis aux fichiers qu'il référence. Ce module ne
vérifie pas lui-même la signature et n'autorise jamais ``compose up``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deployment_image_inventory as dii  # noqa: E402
import verify_release_image_provenance_cli as vri  # noqa: E402

_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]*(?::[a-zA-Z0-9._-]+)?@sha256:[0-9a-f]{64}\Z")
_API_REPO = "ghcr.io/cyranoaladin/rag-ingestor"
_COCKPIT_REPO = "ghcr.io/cyranoaladin/rag-cockpit"
_REDIS_REPO = "docker.io/library/redis"
_MANIFEST_NAME = "release-material-manifest.json"
_MANIFEST_PROTOCOL = "NEXUS-PUBLIC-MATERIAL-V1"
_MATERIAL_LABEL = "nexus.release-material.sha256"
_LEGACY_PLAN_SERVICES = {"pgvector", "ingestor", "prometheus"}
_SERVICES = _LEGACY_PLAN_SERVICES | {"cockpit", "session-redis"}
_COCKPIT_ENV_KEYS = {
    "RAG_ENGINE_INTERNAL_URL", "RAG_ENGINE_INTERNAL_TOKEN", "RAG_ENGINE_API_KEY",
    "NEXUS_INTERNAL_TOKEN_SECRET", "NEXUS_INTERNAL_TOKEN_ISSUER",
    "NEXUS_INTERNAL_TOKEN_AUDIENCE", "NEXUS_SSO_ISSUER", "NEXUS_SSO_AUDIENCE",
    "NEXUS_RELEASE_SCHOOL_YEAR", "NEXTAUTH_SECRET", "NEXTAUTH_URL",
    "NEXUS_COCKPIT_PUBLIC_ORIGIN", "NEXUS_SESSION_REDIS_URL",
}
_REDIS_COMMAND = [
    "redis-server", "--appendonly", "yes", "--appendfsync", "always",
    "--aclfile", "/run/secrets/session-redis.acl",
]
_MATERIAL_BINDS = {
    "pgvector": {
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
    },
    "ingestor": {
        "/app/configs": "configs",
        "/app/release": "release",
        "/app/servable-corpus": "servable-corpus",
        "/models/e5-large": "models/e5-large",
        "/models/reranker": "models/reranker",
    },
    "prometheus": {
        "/etc/prometheus/prometheus.yml": "prometheus/prometheus.v2.yml",
        "/etc/prometheus/rules": "prometheus/rules",
    },
}
_SECRET_BIND = "/app/api-clients/api-clients.json"


class PublicCandidateError(RuntimeError):
    """Le candidat n'est pas admissible."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicCandidateError(message)


def _no_symlink_components(path: Path) -> Path:
    _require(path.is_absolute(), f"absolute path required: {path}")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        try:
            info = cursor.lstat()
        except OSError as exc:
            raise PublicCandidateError(f"missing material path {cursor}: {exc}") from exc
        _require(not stat.S_ISLNK(info.st_mode), f"symlink refused: {cursor}")
    return path.resolve(strict=True)


def _require_outside_git_checkout(path: Path) -> None:
    for ancestor in (path, *path.parents):
        try:
            (ancestor / ".git").lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PublicCandidateError(f"cannot inspect Git boundary: {ancestor}: {exc}") from exc
        raise PublicCandidateError(f"release bind root is inside a Git checkout: {ancestor}")


def _sha256_file(path: Path) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            _require(stat.S_ISREG(before.st_mode), f"non-regular file: {path}")
            _require(before.st_nlink == 1, f"hardlinked file refused: {path}")
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
            after = os.fstat(stream.fileno())
            _require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
                     f"file changed during hashing: {path}")
            return digest.hexdigest()
    except OSError as exc:
        raise PublicCandidateError(f"cannot hash {path}: {exc}") from exc


def _read_secret_file(path: Path, *, private: bool) -> str:
    _no_symlink_components(path)
    info = path.stat()
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
             "runtime secret must be a regular non-hardlinked file")
    _require(info.st_mode & 0o022 == 0, "runtime secret must not be writable by others")
    if private:
        _require(info.st_mode & 0o077 == 0, "cockpit environment must be private")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PublicCandidateError("runtime secret cannot be read") from exc


def _cockpit_environment(secret_root: Path, api_env: dict[str, Any]) -> dict[str, str]:
    raw = _read_secret_file(secret_root / "cockpit.env", private=True)
    values: dict[str, str] = {}
    for line in raw.splitlines():
        _require(bool(line) and not line.startswith("#") and "=" in line,
                 "cockpit environment format differs")
        key, value = line.split("=", 1)
        _require(key not in values and re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None
                 and bool(value) and not value.startswith(("'", '"')),
                 "cockpit environment entry differs")
        values[key] = value
    _require(set(values) in ({*_COCKPIT_ENV_KEYS, "NEXUS_SSO_JWKS_URL"},
                            {*_COCKPIT_ENV_KEYS, "NEXUS_SSO_SHARED_SECRET"}),
             "cockpit environment keys differ")
    _require(values["RAG_ENGINE_INTERNAL_URL"] == "http://ingestor:8001",
             "Cockpit must call the project API over bff_net")
    _require(values["NEXTAUTH_URL"] == values["NEXUS_COCKPIT_PUBLIC_ORIGIN"] and
             values["NEXTAUTH_URL"].startswith("https://") and
             urlsplit(values["NEXTAUTH_URL"]).path in ("", "/") and
             not urlsplit(values["NEXTAUTH_URL"]).query and
             not urlsplit(values["NEXTAUTH_URL"]).fragment,
             "Cockpit public origin differs")
    _require(re.fullmatch(r"20[0-9]{2}-20[0-9]{2}", values["NEXUS_RELEASE_SCHOOL_YEAR"]) is not None,
             "Cockpit school year differs")
    if "NEXUS_SSO_JWKS_URL" in values:
        _require(values["NEXUS_SSO_JWKS_URL"].startswith("https://"),
                 "Cockpit JWKS URL must use HTTPS")
    for cockpit_key, api_key in (
        ("RAG_ENGINE_INTERNAL_TOKEN", "RAG_BFF_SERVICE_TOKEN"),
        ("NEXUS_INTERNAL_TOKEN_SECRET", "NEXUS_INTERNAL_TOKEN_SECRET"),
        ("NEXUS_INTERNAL_TOKEN_ISSUER", "NEXUS_INTERNAL_TOKEN_ISSUER"),
        ("NEXUS_INTERNAL_TOKEN_AUDIENCE", "NEXUS_INTERNAL_TOKEN_AUDIENCE"),
        ("NEXUS_SSO_ISSUER", "NEXUS_SSO_ISSUER"),
        ("NEXUS_SSO_AUDIENCE", "NEXUS_SSO_AUDIENCE"),
    ):
        _require(isinstance(api_env.get(api_key), str) and
                 hmac.compare_digest(values[cockpit_key], api_env[api_key]),
                 f"Cockpit/API identity binding differs: {cockpit_key}")
    return values


def _validate_redis_secret(secret_root: Path, redis_url: str) -> None:
    try:
        parsed = urlsplit(redis_url)
        valid = (parsed.scheme == "redis" and parsed.hostname == "session-redis" and
                 parsed.port == 6379 and parsed.path == "/0" and
                 parsed.username == "default" and bool(parsed.password) and
                 not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    _require(valid, "Cockpit Redis URL must target its private session service")
    password = unquote(parsed.password or "")
    _require(len(password) >= 24, "Cockpit Redis credential is too short")
    acl = _read_secret_file(secret_root / "session-redis.acl", private=False).strip()
    expected = (
        "user default on #" + hashlib.sha256(password.encode()).hexdigest()
        + " ~nexus:session:v1:* +@connection +get +set"
    )
    _require(hmac.compare_digest(acl, expected), "Redis ACL differs from Cockpit credential")


def _material_inventory(root: Path, source_sha: str) -> tuple[str, int]:
    manifest_path = root / _MANIFEST_NAME
    _no_symlink_components(manifest_path)
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise PublicCandidateError(f"invalid material manifest: {exc}") from exc
    _require(isinstance(manifest, dict) and set(manifest) == {"protocol", "source_sha", "files"},
             "material manifest schema differs")
    _require(manifest["protocol"] == _MANIFEST_PROTOCOL and manifest["source_sha"] == source_sha,
             "material manifest identity differs")
    files = manifest["files"]
    _require(isinstance(files, dict) and bool(files), "material manifest has no files")
    listed: dict[str, str] = {}
    for relative, expected in files.items():
        _require(isinstance(relative, str) and isinstance(expected, str), "invalid file entry")
        parts = Path(relative).parts
        _require(bool(parts) and not Path(relative).is_absolute() and
                 all(part not in (".", "..", ".git") for part in parts) and
                 relative != _MANIFEST_NAME and _HEX64.fullmatch(expected) is not None,
                 f"invalid material file entry: {relative}")
        listed[relative] = expected
    seen: set[str] = set()
    def fail_walk(exc: OSError) -> None:
        raise PublicCandidateError(f"cannot inventory material tree: {exc}") from exc

    for directory, directories, filenames in os.walk(
        root, followlinks=False, onerror=fail_walk
    ):
        for name in directories + filenames:
            path = Path(directory) / name
            _no_symlink_components(path)
            info = path.lstat()
            _require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode),
                     f"special material path refused: {path}")
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == _MANIFEST_NAME:
                continue
            _require(relative in listed, f"unlisted material file: {relative}")
            _require(_sha256_file(path) == listed[relative], f"material digest differs: {relative}")
            seen.add(relative)
    _require(seen == set(listed), f"missing material files: {sorted(set(listed) - seen)}")
    return digest, len(seen)


def require_public_candidate(
    *,
    resolved_compose: dict[str, Any],
    source_sha: str,
    color: str,
    material_root: Path,
    secrets_root: Path,
    repo_root: Path,
    verified_application_images: dict[str, str],
) -> dict[str, object]:
    """Refuse un candidat qui diverge des matériaux ou de l'image vérifiés.

    ``verified_application_images`` doit provenir du vérificateur canonique
    de provenance GitHub pour ``source_sha``. L'appelant ne peut utiliser ce
    verdict pour déployer qu'après vérification indépendante de la signature
    de readiness sur le ``compose_digest`` retourné.
    """
    _require(_HEX40.fullmatch(source_sha) is not None, "malformed source SHA")
    _require(color in {"blue", "green"}, "unknown candidate color")
    has_cockpit_provenance = "cockpit" in verified_application_images
    project = f"nexus-rag-{color}"
    _require(resolved_compose.get("name") == project, "isolated Compose project differs")
    _require(
        resolved_compose.get("networks")
        == {
            "rag_net": {"name": f"{project}_rag_net", "driver": "bridge", "ipam": {}},
            "bff_net": {"name": f"{project}_bff_net", "driver": "bridge", "ipam": {}},
        },
        "candidate network must be project-scoped and non-external",
    )
    expected_volumes = {
        "rag_pgvector_data": {"name": f"{project}_rag_pgvector_data"},
        "rag_prometheus_data": {"name": f"{project}_rag_prometheus_data"},
    }
    if has_cockpit_provenance:
        expected_volumes["session_redis_data"] = {"name": f"{project}_session_redis_data"}
    _require(
        resolved_compose.get("volumes") == expected_volumes,
        "candidate volumes must be project-scoped local volumes without driver options",
    )
    services = resolved_compose.get("services")
    expected_services = _SERVICES if has_cockpit_provenance else _LEGACY_PLAN_SERVICES
    _require(isinstance(services, dict) and set(services) == expected_services,
             "public candidate service inventory differs from its provenance mode")
    root = _no_symlink_components(material_root)
    secret_root = _no_symlink_components(secrets_root)
    checkout = _no_symlink_components(repo_root)
    _require_outside_git_checkout(root)
    _require_outside_git_checkout(secret_root)
    _require(root != checkout and not root.is_relative_to(checkout),
             "release material is inside a checkout")
    _require(secret_root != checkout and not secret_root.is_relative_to(checkout),
             "runtime secrets are inside a checkout")
    _require(secret_root != root and not secret_root.is_relative_to(root),
             "runtime secrets are inside release material")
    manifest_digest, file_count = _material_inventory(root, source_sha)
    ingestor = services["ingestor"]
    _require(isinstance(ingestor, dict), "invalid API service")
    database_env = services["pgvector"].get("environment")
    api_env = ingestor.get("environment")
    _require(isinstance(database_env, dict) and isinstance(api_env, dict),
             "candidate database environment is missing")
    database_name = database_env.get("POSTGRES_DB")
    _require(isinstance(database_name, str) and bool(database_name),
             "candidate database name is missing")
    _require(
        all(
            isinstance(key, str)
            and "PUBLISHER" not in key.upper()
            and "WRITER" not in key.upper()
            and not key.upper().startswith(("PGVECTOR_", "POSTGRES_"))
            for key in api_env
        ),
        "API must not receive publisher or writer credentials",
    )
    for variable, username in (("PG_RAG_DSN", "rag_reader"), ("PG_REVIEW_DSN", "rag_reviewer")):
        value = api_env.get(variable)
        _require(isinstance(value, str), f"candidate {variable} is missing")
        try:
            dsn = urlsplit(value)
            correct = (
                dsn.scheme == "postgresql"
                and dsn.hostname == "pgvector"
                and dsn.port == 5432
                and dsn.path == f"/{database_name}"
                and dsn.username == username
                and not dsn.query
                and not dsn.fragment
            )
        except ValueError:
            correct = False
        _require(correct, f"candidate {variable} must target its own pgvector service")
    image = ingestor.get("image")
    _require(image == verified_application_images.get("ingestor") and
             isinstance(image, str) and image.startswith(_API_REPO + "@sha256:") and
             _IMAGE.fullmatch(image) is not None,
             "API image differs from canonical provenance")
    cockpit_image: str | None = None
    redis_image: str | None = None
    if has_cockpit_provenance:
        cockpit = services["cockpit"]
        redis = services["session-redis"]
        _require(isinstance(cockpit, dict) and isinstance(redis, dict),
                 "Cockpit or session Redis service missing")
        cockpit_image = cockpit.get("image")
        _require(cockpit_image == verified_application_images.get("cockpit") and
                 isinstance(cockpit_image, str) and
                 cockpit_image.startswith(_COCKPIT_REPO + "@sha256:") and
                 _IMAGE.fullmatch(cockpit_image) is not None,
                 "Cockpit image differs from canonical provenance")
        redis_image = redis.get("image")
        _require(isinstance(redis_image, str) and
                 redis_image.startswith(_REDIS_REPO + "@sha256:") and
                 _IMAGE.fullmatch(redis_image) is not None,
                 "Redis upstream image must be pinned by digest")
        _require(redis.get("command") == _REDIS_COMMAND and
                 not redis.get("environment") and "build" not in redis,
                 "session Redis configuration differs")
        _require(cockpit.get("read_only") is True, "Cockpit filesystem must be read-only")
        cockpit_env = cockpit.get("environment")
        _require(isinstance(cockpit_env, dict), "Cockpit environment missing")
        required_env = _cockpit_environment(secret_root, api_env)
        _require(cockpit_env == {"NODE_ENV": "production", **required_env},
                 "Cockpit environment differs from private secret file")
        _validate_redis_secret(secret_root, required_env["NEXUS_SESSION_REDIS_URL"])
    labels = ingestor.get("labels")
    _require(isinstance(labels, dict) and labels.get(_MATERIAL_LABEL) == manifest_digest,
             "material manifest digest is not bound to resolved Compose")
    published_ports: set[int] = set()
    for name, service in services.items():
        _require(isinstance(service, dict) and "build" not in service, f"build refused: {name}")
        _require(not any(key in service for key in (
            "extra_hosts", "links", "external_links", "volumes_from", "devices",
            "cap_add", "pid", "ipc", "userns_mode",
        )) and not service.get("privileged"),
                 f"host access or privilege override refused: {name}")
        if name in {"cockpit", "session-redis"}:
            _require(service.get("entrypoint") is None and
                     (name != "cockpit" or service.get("command") is None),
                     f"application entrypoint override refused: {name}")
        expected_networks = (
            {"rag_net": None, "bff_net": None} if name == "ingestor"
            else {"bff_net": None} if name in {"cockpit", "session-redis"}
            else {"rag_net": None}
        )
        _require(service.get("networks") == expected_networks and
                 "network_mode" not in service,
                 f"candidate service network differs: {name}")
        ref = service.get("image")
        _require(isinstance(ref, str) and _IMAGE.fullmatch(ref) is not None,
                 f"unpinned image: {name}")
        ports = service.get("ports", [])
        _require(isinstance(ports, list), f"invalid ports: {name}")
        if name in {"pgvector", "session-redis"}:
            _require(not ports, f"{name} port must not be published")
        else:
            _require(len(ports) == 1 and isinstance(ports[0], dict) and
                     ports[0].get("host_ip") == "127.0.0.1" and
                     ports[0].get("target") == {
                         "ingestor": 8001, "prometheus": 9090, "cockpit": 3000
                     }[name] and
                     str(ports[0].get("published", "")).isdigit(),
                     f"only one loopback port allowed: {name}")
            published = int(ports[0]["published"])
            _require(1 <= published <= 65535 and published not in published_ports,
                     f"duplicate or invalid loopback port: {name}")
            published_ports.add(published)
        volumes = service.get("volumes", [])
        _require(isinstance(volumes, list), f"invalid volumes: {name}")
        found_targets: set[str] = set()
        found_named: set[str] = set()
        for volume in volumes:
            _require(isinstance(volume, dict), f"invalid volume: {name}")
            if volume.get("type") != "bind":
                expected_named = {
                    "pgvector": ("/var/lib/postgresql/data", "rag_pgvector_data"),
                    "prometheus": ("/prometheus", "rag_prometheus_data"),
                    "session-redis": ("/data", "session_redis_data"),
                }.get(name)
                _require(volume.get("type") == "volume" and expected_named is not None and
                         volume.get("target") == expected_named[0] and
                         volume.get("source") == expected_named[1] and
                         name not in found_named,
                         f"foreign or duplicate named volume: {name}")
                found_named.add(name)
                continue
            _require(volume.get("read_only") is True, f"writable bind refused: {name}")
            source = volume.get("source")
            _require(isinstance(source, str), f"bind source missing: {name}")
            actual = _no_symlink_components(Path(source))
            target = volume.get("target")
            _require(isinstance(target, str) and target not in found_targets,
                     f"invalid or duplicate bind target: {name}")
            found_targets.add(target)
            if target == _SECRET_BIND and name == "ingestor":
                _require(actual == secret_root / "api-clients.json", "API registry secret path differs")
                _require(actual.is_file(), "API registry secret missing")
            elif target == "/run/secrets/session-redis.acl" and name == "session-redis":
                _require(actual == secret_root / "session-redis.acl",
                         "Redis ACL secret path differs")
            else:
                expected = _MATERIAL_BINDS.get(name, {}).get(target)
                _require(expected is not None and actual == root / expected,
                         f"unexpected or misplaced material bind: {name}/{target}")
        expected_targets = set(_MATERIAL_BINDS.get(name, {}))
        if name == "ingestor":
            expected_targets.add(_SECRET_BIND)
        if name == "session-redis":
            expected_targets.add("/run/secrets/session-redis.acl")
        _require(found_targets == expected_targets,
                 f"missing or extra bind targets: {name}")
        _require(found_named == ({name} if name in {"pgvector", "prometheus", "session-redis"} else set()),
                 f"isolated named volume missing: {name}")
    return {
        "project": project,
        "source_sha": source_sha,
        "compose_digest": hashlib.sha256(
            vri.canonical_resolved_compose_bytes(resolved_compose)
        ).hexdigest(),
        "material_manifest_digest": manifest_digest,
        "material_files": file_count,
        "api_image": image,
        **({"cockpit_image": cockpit_image, "redis_image": redis_image}
           if has_cockpit_provenance else {}),
        "mutation_allowed": False,
    }


def require_candidate_with_live_provenance(
    *,
    resolved_compose: dict[str, Any],
    source_sha: str,
    source_tree_sha: str,
    color: str,
    material_root: Path,
    secrets_root: Path,
    repo_root: Path,
    provenance_run_id: int,
    provenance_run_attempt: int,
    github_api_get: Callable[[str], dict[str, Any]],
    download_artifact: Callable[[int, str, Path], Path],
    work_dir: Path,
) -> dict[str, object]:
    """Obtient les digests depuis le workflow canonique, puis qualifie le candidat."""
    services = resolved_compose.get("services")
    _require(isinstance(services, dict), "candidate service inventory missing")
    if set(services) == _SERVICES:
        verifier = dii.verify_public_candidate_image_provenance
    elif set(services) == _LEGACY_PLAN_SERVICES:
        verifier = dii.verify_application_image_provenance
    else:
        raise PublicCandidateError("candidate service inventory differs")
    try:
        verified = verifier(
            repository=vri._CANONICAL_REPOSITORY,  # noqa: SLF001 - autorité fixe
            source_commit_sha=source_sha,
            source_tree_sha=source_tree_sha,
            provenance_run_id=provenance_run_id,
            provenance_run_attempt=provenance_run_attempt,
            github_api_get=github_api_get,
            download_artifact=download_artifact,
            work_dir=work_dir,
        )
    except dii.DeploymentImageInventoryError as exc:
        raise PublicCandidateError(f"canonical image provenance rejected: {exc}") from exc
    return require_public_candidate(
        resolved_compose=resolved_compose,
        source_sha=source_sha,
        color=color,
        material_root=material_root,
        secrets_root=secrets_root,
        repo_root=repo_root,
        verified_application_images=verified,
    )
