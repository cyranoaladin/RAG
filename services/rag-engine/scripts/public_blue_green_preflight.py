"""Préflight local du candidat public blue-green, sans mutation Docker.

Le digest du manifeste de matériaux est une étiquette du Compose résolu.
Une signature de readiness sur le digest de ce Compose lie donc ces octets
au manifeste exhaustif, puis aux fichiers qu'il référence. Ce module ne
vérifie pas lui-même la signature et n'autorise jamais ``compose up``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deployment_image_inventory as dii  # noqa: E402
import verify_release_image_provenance_cli as vri  # noqa: E402

_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}\Z")
_API_REPO = "ghcr.io/cyranoaladin/rag-ingestor"
_MANIFEST_NAME = "release-material-manifest.json"
_MANIFEST_PROTOCOL = "NEXUS-PUBLIC-MATERIAL-V1"
_MATERIAL_LABEL = "nexus.release-material.sha256"
_SERVICES = {"pgvector", "ingestor", "prometheus"}
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
    project = f"nexus-rag-{color}"
    _require(resolved_compose.get("name") == project, "isolated Compose project differs")
    _require(
        resolved_compose.get("networks")
        == {"rag_net": {"name": f"{project}_rag_net", "driver": "bridge", "ipam": {}}},
        "candidate network must be project-scoped and non-external",
    )
    _require(
        resolved_compose.get("volumes")
        == {
            "rag_pgvector_data": {"name": f"{project}_rag_pgvector_data"},
            "rag_prometheus_data": {"name": f"{project}_rag_prometheus_data"},
        },
        "candidate volumes must be project-scoped local volumes without driver options",
    )
    services = resolved_compose.get("services")
    _require(isinstance(services, dict) and set(services) == _SERVICES,
             "public candidate must have exactly three read-only services")
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
    labels = ingestor.get("labels")
    _require(isinstance(labels, dict) and labels.get(_MATERIAL_LABEL) == manifest_digest,
             "material manifest digest is not bound to resolved Compose")
    for name, service in services.items():
        _require(isinstance(service, dict) and "build" not in service, f"build refused: {name}")
        _require(service.get("networks") == {"rag_net": None} and
                 "network_mode" not in service,
                 f"candidate service network differs: {name}")
        ref = service.get("image")
        _require(isinstance(ref, str) and _IMAGE.fullmatch(ref) is not None,
                 f"unpinned image: {name}")
        ports = service.get("ports", [])
        _require(isinstance(ports, list), f"invalid ports: {name}")
        if name == "pgvector":
            _require(not ports, "database port must not be published")
        else:
            _require(len(ports) == 1 and isinstance(ports[0], dict) and
                     ports[0].get("host_ip") == "127.0.0.1",
                     f"only one loopback port allowed: {name}")
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
                }.get(name)
                _require(volume.get("type") == "volume" and expected_named is not None and
                         volume.get("target") == expected_named[0] and
                         volume.get("source") == f"{project}_{expected_named[1]}" and
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
            else:
                expected = _MATERIAL_BINDS[name].get(target)
                _require(expected is not None and actual == root / expected,
                         f"unexpected or misplaced material bind: {name}/{target}")
        expected_targets = set(_MATERIAL_BINDS[name])
        if name == "ingestor":
            expected_targets.add(_SECRET_BIND)
        _require(found_targets == expected_targets,
                 f"missing or extra bind targets: {name}")
        _require(found_named == ({name} if name in {"pgvector", "prometheus"} else set()),
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
    try:
        verified = dii.verify_application_image_provenance(
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
