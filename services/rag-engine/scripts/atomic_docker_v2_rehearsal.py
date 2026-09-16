"""Rehearsal Docker V2 isolé, reproductible et fail-closed.

Le CLI complet est construit par cycles TDD. Les primitives de ce module
restent sans effet de bord afin que les invariants de noms, de photographie et
de sérialisation soient vérifiables indépendamment du daemon Docker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import atomic_docker_v2_rehearsal_fixture as fixture
import deploy_verified_release_cli as deploy
import deployment_image_inventory as image_inventory
import verify_release_image_provenance_cli as release_images


class RehearsalError(RuntimeError):
    """Le rehearsal ne peut pas établir sa preuve sans ambiguïté."""


_PROJECT_NAME = re.compile(
    r"^nexus-go-live-rehearsal-v2-[0-9a-f]{8,32}-(?:main|witness|collision)$"
)
_ABSOLUTE_PATH = re.compile(r"(?:^|[= ])/(?:[^\s]*)")
_REQUIRED_TRUE_VERDICTS = frozenset(
    {
        "BAD_DIGEST_REFUSED",
        "BAD_READINESS_REFUSED",
        "BAD_AUTHORIZATION_SET_REFUSED",
        "FOREIGN_COLLISION_REFUSED",
        "ISOLATION_PREFLIGHT_PASS",
        "ROLLBACK_REHEARSAL_PASS",
    }
)
_REQUIRED_ZERO_VERDICTS = frozenset(
    {
        "FOREIGN_SERVICES_TOUCHED",
        "PRODUCTION_PORTS_PUBLISHED",
        "PROJECT_CONTAINERS_REMAINING",
    }
)
_REQUIRED_FALSE_VERDICTS = frozenset(
    {"PRODUCTION_PROJECT_NAME_USED", "REMOVE_ORPHANS_USED"}
)
_COMPOSE_FILES = (
    "docker-compose.v2.yml",
    "docker-compose.production-workers.yml",
    "docker-compose.production-release.yml",
)

MutationRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]
RefusalOperation = Callable[[MutationRunner], None]
CleanupOperation = Callable[[], None]
InventoryOperation = Callable[[], Mapping[str, Sequence[str]]]


def require_rehearsal_project_name(name: str) -> str:
    """Accepte uniquement un nom généré dans l'espace de noms du harnais."""
    if _PROJECT_NAME.fullmatch(name) is None:
        raise RehearsalError(f"unsafe rehearsal project name {name!r}")
    return name


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    """Sérialise une preuve JSON selon une convention canonique unique."""
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def foreign_snapshot_changes(
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
    *,
    generated_projects: set[str],
) -> list[str]:
    """Retourne les changements de conteneurs étrangers, triés et explicites."""

    def foreign(snapshot: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
        return {
            container_id: fact
            for container_id, fact in snapshot.items()
            if fact.get("project") not in generated_projects
        }

    left = foreign(before)
    right = foreign(after)
    changes = [f"{item}:removed" for item in sorted(left.keys() - right.keys())]
    changes.extend(f"{item}:added" for item in sorted(right.keys() - left.keys()))
    changes.extend(
        f"{item}:changed"
        for item in sorted(left.keys() & right.keys())
        if left[item] != right[item]
    )
    return changes


def sanitize_transcript_line(line: str, *, forbidden_values: Sequence[str]) -> str:
    """Refuse plutôt que masquer une ligne susceptible de divulguer un secret."""
    if "\n" in line or "\r" in line:
        raise RehearsalError("transcript line contains a line break")
    if any(value and value in line for value in forbidden_values):
        raise RehearsalError("transcript line contains a forbidden value")
    if _ABSOLUTE_PATH.search(line):
        raise RehearsalError("transcript line contains an absolute path")
    return line


def global_rehearsal_pass(verdicts: Mapping[str, object]) -> bool:
    """Calcule le verdict global depuis tous les invariants obligatoires."""
    return (
        all(verdicts.get(name) is True for name in _REQUIRED_TRUE_VERDICTS)
        and all(
            verdicts.get(name) == 0 and verdicts.get(name) is not False
            for name in _REQUIRED_ZERO_VERDICTS
        )
        and all(verdicts.get(name) is False for name in _REQUIRED_FALSE_VERDICTS)
    )


def run_refusal_scenario(
    *,
    name: str,
    operation: RefusalOperation,
    cwd: Path,
    expected_error_substrings: Sequence[str] = (),
) -> dict[str, object]:
    """Prouve qu'un refus intervient avant la frontière de mutation."""
    calls: list[list[str]] = []

    def mutation_runner(
        args: list[str], command_cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    refused = False
    error_class: str | None = None
    error_message: str | None = None
    try:
        operation(mutation_runner)
    except Exception as exc:  # noqa: BLE001 - toute exception est un refus observé
        refused = True
        error_class = type(exc).__name__
        error_message = str(exc)
    expected_layer = error_message is not None and all(
        fragment in error_message for fragment in expected_error_substrings
    )
    return {
        "name": name,
        "refused": refused,
        "error_class": error_class,
        "error_message": error_message,
        "mutation_boundary_calls": len(calls),
        "mutation_commands": [args[-1] if args else "" for args in calls],
        "cwd_exists": cwd.is_dir(),
        "expected_refusal_layer": expected_layer,
        "passed": refused and not calls and expected_layer,
    }


def rewrite_outer_bundle_manifest(
    bundle_dir: Path, *, changed_file: str
) -> dict[str, Any]:
    """Rehache un fichier précis puis l'enveloppe extérieure du bundle."""
    if Path(changed_file).name != changed_file:
        raise RehearsalError("changed bundle file name is unsafe")
    manifest_path = bundle_dir / "bundle_manifest.json"
    try:
        document = json.loads(manifest_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise RehearsalError(f"bundle manifest cannot be rewritten: {exc}") from exc
    files = document.get("files") if isinstance(document, dict) else None
    if not isinstance(files, dict) or changed_file not in files:
        raise RehearsalError("changed file is not recorded by the bundle manifest")
    changed_path = bundle_dir / changed_file
    if changed_path.is_symlink() or not changed_path.is_file():
        raise RehearsalError("changed bundle file is missing or unsafe")
    files[changed_file] = hashlib.sha256(changed_path.read_bytes()).hexdigest()
    document.pop("bundle_digest", None)
    document["bundle_digest"] = hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(document))
    return document


def bundle_member_attestation(
    bundle_dir: Path,
    manifest_members: Mapping[str, object],
) -> list[dict[str, str]]:
    """Recalcule chaque membre avec des champs sans sémantique de secret."""
    attestation: list[dict[str, str]] = []
    for name, expected in sorted(manifest_members.items()):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name:
            raise RehearsalError(f"unsafe bundle member path {name!r}")
        member_path = bundle_dir / relative
        if member_path.is_symlink() or not member_path.is_file():
            raise RehearsalError(f"bundle member is missing or unsafe: {name}")
        actual = hashlib.sha256(member_path.read_bytes()).hexdigest()
        if actual != expected:
            raise RehearsalError(f"bundle member attestation mismatch: {name}")
        attestation.append({"path": name, "sha256": actual})
    return attestation


def rollback_command(bundle_dir: Path) -> list[str]:
    """Construit l'unique rollback Compose autorisé pour la fixture."""
    command = [
        "docker",
        "compose",
        "--env-file",
        str(bundle_dir / ".env"),
    ]
    for name in _COMPOSE_FILES:
        command.extend(("-f", str(bundle_dir / name)))
    return [*command, "down", "--timeout", "10"]


def project_inventory_count(inventory: Mapping[str, Sequence[object]]) -> int:
    """Compte tous les objets Compose générés, pas seulement les conteneurs."""
    return sum(len(inventory.get(name, ())) for name in ("containers", "networks", "volumes"))


def require_empty_project_inventories(
    inventories: Mapping[str, Mapping[str, Sequence[object]]],
) -> None:
    """Refuse avant mutation si un nom généré possède déjà une ressource."""
    dirty = sorted(
        role
        for role, inventory in inventories.items()
        if project_inventory_count(inventory) != 0
    )
    if dirty:
        raise RehearsalError(
            "pre-existing resources found for generated project roles: "
            + ", ".join(dirty)
        )


def exhaust_cleanup(
    operations: Mapping[str, CleanupOperation],
    inventory: InventoryOperation,
) -> tuple[dict[str, list[str]], list[str]]:
    """Épuise deux passes de cleanup et d'audit sans court-circuiter une cible."""
    failures: list[str] = []
    residue: dict[str, list[str]] = {
        "containers": ["inventory-not-observed"],
        "networks": [],
        "volumes": [],
    }
    inventory_observed = False
    for attempt in range(2):
        for target, operation in operations.items():
            try:
                operation()
            except Exception as exc:  # noqa: BLE001 - cleanup doit continuer
                failures.append(
                    f"{target} cleanup attempt {attempt + 1} raised "
                    f"{type(exc).__name__}"
                )
        try:
            observed = inventory()
        except Exception as exc:  # noqa: BLE001 - la seconde passe reste obligatoire
            failures.append(
                f"inventory attempt {attempt + 1} raised {type(exc).__name__}"
            )
            continue
        inventory_observed = True
        residue = {
            kind: list(observed.get(kind, ()))
            for kind in ("containers", "networks", "volumes")
        }
        if project_inventory_count(residue) == 0:
            break
    if not inventory_observed:
        failures.append("generated project inventory was never observed")
    if project_inventory_count(residue):
        failures.append("generated project cleanup left residue")
    return residue, failures


def _run(
    args: list[str], *, cwd: Path, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RehearsalError(f"command boundary failed: {type(exc).__name__}") from exc


def _require_success(
    completed: subprocess.CompletedProcess[str], *, label: str
) -> subprocess.CompletedProcess[str]:
    if completed.returncode != 0:
        raise RehearsalError(
            f"{label} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()[:500]}"
        )
    return completed


def _git_fact(repo_root: Path, expression: str) -> str:
    return _require_success(
        _run(["git", "rev-parse", expression], cwd=repo_root, timeout=30),
        label=f"git rev-parse {expression}",
    ).stdout.strip()


def _docker_versions(*, cwd: Path) -> dict[str, str]:
    engine = _require_success(
        _run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            cwd=cwd,
            timeout=30,
        ),
        label="Docker engine version",
    ).stdout.strip()
    compose = _require_success(
        _run(["docker", "compose", "version", "--short"], cwd=cwd, timeout=30),
        label="Docker Compose version",
    ).stdout.strip()
    if not engine or not compose:
        raise RehearsalError("Docker version facts are incomplete")
    return {"engine_version": engine, "compose_version": compose}


def _local_pinned_image(image_tag: str, *, cwd: Path) -> tuple[str, str]:
    completed = _require_success(
        _run(
            [
                "docker",
                "image",
                "inspect",
                image_tag,
                "--format",
                "{{json .RepoDigests}} {{.Id}}",
            ],
            cwd=cwd,
            timeout=30,
        ),
        label="local rehearsal image inspection",
    )
    raw_digests, separator, image_id = completed.stdout.strip().rpartition(" ")
    if not separator:
        raise RehearsalError("local image inspection returned no image ID")
    try:
        repo_digests = json.loads(raw_digests)
    except json.JSONDecodeError as exc:
        raise RehearsalError("local image inspection returned malformed digests") from exc
    if not isinstance(repo_digests, list) or not repo_digests:
        raise RehearsalError("local rehearsal image has no immutable RepoDigest")
    repository = image_tag.split(":", 1)[0]
    candidates = [
        item
        for item in repo_digests
        if isinstance(item, str) and item.startswith(f"{repository}@sha256:")
    ]
    if len(candidates) != 1 or not image_id.startswith("sha256:"):
        raise RehearsalError("local rehearsal image identity is ambiguous")
    return candidates[0], image_id


def _application_images(image_ref: str) -> dict[str, str]:
    return {
        name: image_ref
        for name in (
            "ingestor",
            "multilevel-worker-a-production",
            "multilevel-worker-b-production",
        )
    }


def _image_provenance_document(
    *, merge_sha: str, merge_tree_sha: str, image_ref: str
) -> dict[str, Any]:
    repository, image_digest = image_ref.rsplit("@", 1)
    services = {
        name: {
            "source_kind": "build",
            "build_context": ".",
            "dockerfile": (
                "services/rag-engine/infra/Dockerfile.ingestor-v2"
                if name == "ingestor"
                else "services/rag-engine/infra/Dockerfile.multilevel-worker-production"
            ),
            "dockerfile_sha256": "3" * 64,
            "image_repository": repository,
            "image_digest": image_digest,
        }
        for name in _application_images(image_ref)
    }
    return {
        "protocol_version": "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1",
        "repository": fixture.REPOSITORY,
        "source_commit_sha": merge_sha,
        "source_tree_sha": merge_tree_sha,
        "platform": "linux/amd64",
        "workflow_path": ".github/workflows/production-image-provenance.yml",
        "workflow_run_id": fixture.PROVENANCE_RUN_ID,
        "workflow_run_attempt": fixture.PROVENANCE_RUN_ATTEMPT,
        "workflow_ref": "refs/heads/main",
        "built_at": "2026-08-25T12:00:00Z",
        "services": services,
    }


def _resolve_compose_sources(
    *,
    sources: Mapping[str, bytes],
    compose_files: tuple[str, ...],
    work_dir: Path,
    env_file: Path,
) -> dict[str, Any]:
    scratch = work_dir / "compose-fixture"
    scratch.mkdir(parents=True, exist_ok=True)
    for name in compose_files:
        (scratch / name).write_bytes(sources[name])
    args = ["docker", "compose", "--env-file", str(env_file)]
    for name in compose_files:
        args.extend(("-f", str(scratch / name)))
    args.extend(("config", "--format", "json"))
    completed = _require_success(
        _run(args, cwd=scratch, timeout=60),
        label="fixture compose resolution",
    )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RehearsalError("fixture compose resolution returned malformed JSON") from exc
    if not isinstance(document, dict):
        raise RehearsalError("fixture compose resolution returned no object")
    return document


def _materialize_valid_bundle(
    *,
    repo_root: Path,
    private_root: Path,
    project_name: str,
    image_ref: str,
    merge_sha: str,
    merge_tree_sha: str,
    review_seed: str,
    readiness_seed: str,
) -> tuple[Path, bytes, fixture.ReleaseMaterialFixture, str]:
    sources = fixture.compose_source_bytes(image_ref=image_ref)
    material_fixture = fixture.build_release_material_fixture(
        review_binding_private_key_hex=review_seed,
        merge_sha=merge_sha,
        merge_tree_sha=merge_tree_sha,
        now=datetime.now(UTC),
    )
    material = material_fixture.material
    inputs = private_root / "inputs"
    inputs.mkdir(mode=0o700)
    authorization_path = inputs / "authorization-set.json"
    authorization_path.write_bytes(material.authorization_set_raw)
    authorization_path.chmod(0o600)
    material_root = inputs / "v2-material"
    material_root.mkdir(mode=0o700)
    env_file = inputs / ".env"
    env_file.write_text(
        "\n".join(
            (
                f"COMPOSE_PROJECT_NAME={project_name}",
                f"PRODUCTION_AUTHORIZATION_SET_HOST_FILE={authorization_path}",
                f"PRODUCTION_V2_RELEASE_MATERIAL_HOST_DIR={material_root}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    work_dir = private_root / "materialization-work"

    def resolve(
        _repo_root: Path,
        _source_commit_sha: str,
        compose_files: tuple[str, ...],
        callback_work_dir: Path,
        callback_env_file: Path,
    ) -> dict[str, Any]:
        return _resolve_compose_sources(
            sources=sources,
            compose_files=compose_files,
            work_dir=callback_work_dir,
            env_file=callback_env_file,
        )

    resolved = resolve(repo_root, merge_sha, _COMPOSE_FILES, work_dir, env_file)
    compose_digest = hashlib.sha256(
        release_images.canonical_resolved_compose_bytes(resolved)
    ).hexdigest()
    readiness = fixture.sign_readiness_fixture(
        material=material,
        readiness_private_key_hex=readiness_seed,
        compose_digest=compose_digest,
        application_image_digests=_application_images(image_ref),
        upstream_image_digests={"fixture-upstream": image_ref},
    )
    readiness_path = inputs / "readiness-v2.json"
    anchor_path = inputs / "readiness-anchor.json"
    readiness_path.write_bytes(readiness.signed_manifest_raw)
    anchor_path.write_bytes(readiness.trust_anchor_raw)
    readiness_path.chmod(0o600)
    anchor_path.chmod(0o600)
    inventory_document = _image_provenance_document(
        merge_sha=merge_sha,
        merge_tree_sha=merge_tree_sha,
        image_ref=image_ref,
    )
    run_document = {
        "path": ".github/workflows/production-image-provenance.yml",
        "repository": {"full_name": fixture.REPOSITORY},
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_sha": merge_sha,
        "run_attempt": fixture.PROVENANCE_RUN_ATTEMPT,
    }

    def github_api_get(path: str) -> dict[str, Any]:
        prefix = (
            f"repos/{fixture.REPOSITORY}/actions/runs/"
            f"{fixture.PROVENANCE_RUN_ID}"
        )
        if path in {prefix, f"{prefix}/attempts/{fixture.PROVENANCE_RUN_ATTEMPT}"}:
            return run_document
        raise image_inventory.DeploymentImageInventoryError(
            "fixture requested an unexpected GitHub API path"
        )

    def download_artifact(_run_id: int, _name: str, destination: Path) -> Path:
        path = destination / image_inventory._ARTIFACT_FILENAME  # noqa: SLF001
        path.write_bytes(canonical_json_bytes(inventory_document))
        return path

    def git_show_bytes(_root: Path, _sha: str, relative_path: str) -> bytes:
        name = relative_path.rsplit("/", 1)[-1]
        try:
            return sources[name]
        except KeyError as exc:
            raise RehearsalError("fixture requested an unexpected Git blob") from exc

    bundle = private_root / "bundle-valid"
    bundle_document = deploy.materialize_verified_bundle(
        merge_sha=merge_sha,
        merge_tree_sha=merge_tree_sha,
        provenance_run_id=fixture.PROVENANCE_RUN_ID,
        provenance_run_attempt=fixture.PROVENANCE_RUN_ATTEMPT,
        repo_root=repo_root,
        env_file=env_file,
        readiness_manifest_file=readiness_path,
        trust_anchor_file=anchor_path,
        environment="production",
        github_api_get=github_api_get,
        download_artifact=download_artifact,
        run_docker_compose_config=resolve,
        work_dir=work_dir,
        bundle_dir=bundle,
        git_show_bytes=git_show_bytes,
        readiness_protocol="NEXUS-PRODUCTION-READINESS-V2",
        v2_release_material=material,
    )
    return (
        bundle,
        readiness.trust_anchor_raw,
        material_fixture,
        str(bundle_document["bundle_digest"]),
    )


def _copy_bundle(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination


def _container_snapshot(*, cwd: Path) -> dict[str, dict[str, Any]]:
    listed = _require_success(
        _run(["docker", "ps", "-q", "--no-trunc"], cwd=cwd, timeout=30),
        label="Docker container listing",
    )
    ids = [item for item in listed.stdout.splitlines() if item]
    if not ids:
        return {}
    inspected = _require_success(
        _run(
            ["docker", "inspect", "--format", "{{json .}}", *ids],
            cwd=cwd,
            timeout=30,
        ),
        label="Docker container snapshot",
    )
    snapshot: dict[str, dict[str, Any]] = {}
    for raw in inspected.stdout.splitlines():
        document = json.loads(raw)
        labels = document.get("Config", {}).get("Labels") or {}
        container_id = str(document.get("Id", ""))
        snapshot[container_id] = {
            "id": container_id,
            "started_at": document.get("State", {}).get("StartedAt"),
            "project": labels.get("com.docker.compose.project"),
            "service": labels.get("com.docker.compose.service"),
        }
    return snapshot


def _project_inventory(project_name: str, *, cwd: Path) -> dict[str, list[str]]:
    require_rehearsal_project_name(project_name)

    def identifiers(kind: str) -> list[str]:
        completed = _require_success(
            _run(
                [
                    "docker",
                    kind,
                    "ls",
                    "-q",
                    "--filter",
                    f"label=com.docker.compose.project={project_name}",
                ],
                cwd=cwd,
                timeout=30,
            ),
            label=f"Docker {kind} inventory",
        )
        return sorted(item for item in completed.stdout.splitlines() if item)

    containers = _require_success(
        _run(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=com.docker.compose.project={project_name}",
            ],
            cwd=cwd,
            timeout=30,
        ),
        label="Docker project container inventory",
    )
    return {
        "containers": sorted(item for item in containers.stdout.splitlines() if item),
        "networks": identifiers("network"),
        "volumes": identifiers("volume"),
    }


def prepare_auxiliary_compose(
    *,
    root: Path,
    project_name: str,
    service_name: str,
    image_ref: str,
    cleanup_registry: dict[str, Path],
) -> Path:
    """Écrit et enregistre une cible de cleanup avant sa première mutation."""
    require_rehearsal_project_name(project_name)
    directory = root / project_name.rsplit("-", 1)[-1]
    directory.mkdir(mode=0o700)
    compose = directory / "compose.yml"
    compose.write_text(
        f"""services:
  {service_name}:
    image: {image_ref}
    command: ["sh", "-c", "while true; do sleep 3600; done"]
    healthcheck:
      test: ["CMD", "sh", "-c", "true"]
      interval: 1s
      timeout: 1s
      retries: 10
""",
        encoding="utf-8",
    )
    cleanup_registry[project_name] = compose
    return compose


def _start_auxiliary(
    *,
    compose: Path,
    project_name: str,
    service_name: str,
    mutation_commands: list[list[str]],
) -> None:
    require_rehearsal_project_name(project_name)
    command = [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        str(compose),
        "up",
        "-d",
        "--wait",
    ]
    mutation_commands.append(command)
    _require_success(
        _run(command, cwd=compose.parent, timeout=120),
        label=f"start isolated {service_name}",
    )


def _down_auxiliary(
    *,
    compose: Path | None,
    project_name: str,
    cwd: Path,
    mutation_commands: list[list[str]] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    require_rehearsal_project_name(project_name)
    if compose is None or not compose.is_file():
        return None
    command = [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        str(compose),
        "down",
        "--timeout",
        "10",
    ]
    if mutation_commands is not None:
        mutation_commands.append(command)
    return _run(command, cwd=cwd, timeout=120)


def _wait_project_healthy(
    project_name: str, *, expected_count: int, cwd: Path
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + 60
    last: list[str] = []
    while time.monotonic() < deadline:
        listed = _require_success(
            _run(
                [
                    "docker",
                    "ps",
                    "-q",
                    "--filter",
                    f"label=com.docker.compose.project={project_name}",
                ],
                cwd=cwd,
                timeout=30,
            ),
            label="healthy project listing",
        )
        ids = [item for item in listed.stdout.splitlines() if item]
        last = ids
        if len(ids) == expected_count:
            inspected = _require_success(
                _run(
                    ["docker", "inspect", "--format", "{{json .}}", *ids],
                    cwd=cwd,
                    timeout=30,
                ),
                label="container health inspection",
            )
            observation: dict[str, dict[str, str]] = {}
            for raw in inspected.stdout.splitlines():
                document = json.loads(raw)
                labels = document.get("Config", {}).get("Labels") or {}
                service = str(labels.get("com.docker.compose.service", ""))
                health = str(
                    (document.get("State", {}).get("Health") or {}).get(
                        "Status", "none"
                    )
                )
                container_id = str(document.get("Id", ""))
                if not service or not container_id:
                    raise RehearsalError("healthy project has incomplete service identity")
                observation[service] = {
                    "container_id": container_id,
                    "health": health,
                    "project": str(
                        labels.get("com.docker.compose.project", "")
                    ),
                }
            if (
                len(observation) == expected_count
                and all(fact["health"] == "healthy" for fact in observation.values())
            ):
                return dict(sorted(observation.items()))
        time.sleep(1)
    raise RehearsalError(
        f"rehearsal project did not become healthy (containers={len(last)})"
    )


def _project_published_ports(project_name: str, *, cwd: Path) -> list[str]:
    """Observe les bindings de ports réellement publiés par le projet."""
    inventory = _project_inventory(project_name, cwd=cwd)
    ids = inventory["containers"]
    if not ids:
        return []
    inspected = _require_success(
        _run(
            ["docker", "inspect", "--format", "{{json .}}", *ids],
            cwd=cwd,
            timeout=30,
        ),
        label="container published port inspection",
    )
    published: list[str] = []
    for raw in inspected.stdout.splitlines():
        document = json.loads(raw)
        container_id = str(document.get("Id", ""))
        ports = document.get("NetworkSettings", {}).get("Ports") or {}
        for container_port, bindings in ports.items():
            if bindings:
                published.extend(
                    f"{container_id}:{container_port}:{binding.get('HostPort', '')}"
                    for binding in bindings
                )
    return sorted(published)


def _combined_generated_inventory(
    project_names: Sequence[str], *, cwd: Path
) -> dict[str, list[str]]:
    combined: dict[str, list[str]] = {
        "containers": [],
        "networks": [],
        "volumes": [],
    }
    for project in project_names:
        inventory = _project_inventory(project, cwd=cwd)
        for kind in combined:
            combined[kind].extend(inventory[kind])
    return {kind: sorted(set(values)) for kind, values in combined.items()}


def _docker_project_events(
    project_name: str, *, since: datetime, until: datetime, cwd: Path
) -> list[dict[str, str]]:
    require_rehearsal_project_name(project_name)
    completed = _require_success(
        _run(
            [
                "docker",
                "events",
                "--since",
                since.isoformat(),
                "--until",
                until.isoformat(),
                "--filter",
                f"label=com.docker.compose.project={project_name}",
                "--format",
                "{{json .}}",
            ],
            cwd=cwd,
            timeout=30,
        ),
        label="Docker project event inventory",
    )
    events: list[dict[str, str]] = []
    for raw in completed.stdout.splitlines():
        document = json.loads(raw)
        events.append(
            {
                "action": str(document.get("Action", "")),
                "type": str(document.get("Type", "")),
            }
        )
    return events


def _refusal_with_docker_facts(
    *,
    name: str,
    operation: RefusalOperation,
    expected_error_substrings: Sequence[str],
    project_names: Sequence[str],
    target_project: str,
    cwd: Path,
) -> dict[str, object]:
    before = _combined_generated_inventory(project_names, cwd=cwd)
    since = datetime.now(UTC)
    result = run_refusal_scenario(
        name=name,
        operation=operation,
        cwd=cwd,
        expected_error_substrings=expected_error_substrings,
    )
    until = datetime.now(UTC)
    after = _combined_generated_inventory(project_names, cwd=cwd)
    result["exit_code"] = 1 if result["refused"] is True else 0
    result["docker_inventory_before"] = before
    result["docker_inventory_after"] = after
    result["docker_events"] = _docker_project_events(
        target_project,
        since=since,
        until=until,
        cwd=cwd,
    )
    result["passed"] = (
        result["passed"] is True
        and before == after
        and result["docker_events"] == []
    )
    return result


def _fixture_json_bytes(document: Any) -> bytes:
    """Canonicalité indentée des contrats de fixture, distincte des preuves."""
    return (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")


def run_rehearsal(
    *, repo_root: Path, private_root: Path, image_tag: str
) -> dict[str, Any]:
    """Exécute tous les cas V2 réels et nettoie seulement ses projets générés."""
    private_root.mkdir(parents=True, exist_ok=True)
    private_root.chmod(0o700)
    run_token = secrets.token_hex(16)
    projects = {
        role: require_rehearsal_project_name(
            f"nexus-go-live-rehearsal-v2-{run_token}-{role}"
        )
        for role in ("main", "witness", "collision")
    }
    image_ref, image_id = _local_pinned_image(image_tag, cwd=repo_root)
    docker_versions = _docker_versions(cwd=repo_root)
    merge_sha = _git_fact(repo_root, "HEAD")
    merge_tree_sha = _git_fact(repo_root, "HEAD^{tree}")
    review_seed = secrets.token_hex(32)
    readiness_seed = secrets.token_hex(32)
    bundle: Path | None = None
    cleanup_registry: dict[str, Path] = {}
    owned_projects: set[str] = set()
    mutation_commands: list[list[str]] = []
    scenarios: dict[str, dict[str, object]] = {}
    foreign_changes: list[str] = ["rehearsal-not-completed"]
    rollback_pass = False
    valid_deployment_pass = False
    bundle_digest = ""
    bundle_attestation: dict[str, Any] = {}
    health_observation: dict[str, dict[str, str]] = {}
    published_ports: list[str] = []
    rollback_facts: dict[str, Any] = {
        "exit_code": None,
        "project_inventory_after": {
            "containers": [],
            "networks": [],
            "volumes": [],
        },
    }
    preflight_inventories = {
        role: _project_inventory(project, cwd=repo_root)
        for role, project in projects.items()
    }
    require_empty_project_inventories(preflight_inventories)
    isolation_preflight_pass = True
    material_fixture: fixture.ReleaseMaterialFixture | None = None
    residue: dict[str, list[str]] = {
        "containers": [],
        "networks": [],
        "volumes": [],
    }
    try:
        bundle, readiness_anchor_raw, material_fixture, bundle_digest = (
            _materialize_valid_bundle(
                repo_root=repo_root,
                private_root=private_root,
                project_name=projects["main"],
                image_ref=image_ref,
                merge_sha=merge_sha,
                merge_tree_sha=merge_tree_sha,
                review_seed=review_seed,
                readiness_seed=readiness_seed,
            )
        )
        bundle_manifest_path = bundle / "bundle_manifest.json"
        bundle_manifest_raw = bundle_manifest_path.read_bytes()
        bundle_manifest = json.loads(bundle_manifest_raw)
        manifest_members = bundle_manifest.get("files")
        if not isinstance(manifest_members, dict):
            raise RehearsalError("bundle manifest has no member hash mapping")
        if bundle_manifest.get("bundle_digest") != bundle_digest:
            raise RehearsalError("materialized bundle digest attestation mismatch")
        actual_member_sha256 = bundle_member_attestation(bundle, manifest_members)
        authorization_set_protocol = str(
            json.loads((bundle / "authorization-set.json").read_bytes()).get(
                "protocol_version", ""
            )
        )
        readiness_protocol = deploy._signed_readiness_protocol(  # noqa: SLF001
            (bundle / deploy._READINESS_MANIFEST_BUNDLE_NAME).read_bytes()  # noqa: SLF001
        )
        bundle_attestation = {
            "bundle_manifest_sha256": hashlib.sha256(
                bundle_manifest_raw
            ).hexdigest(),
            "bundle_digest": bundle_digest,
            "member_sha256": actual_member_sha256,
        }
        bad_digest = _copy_bundle(bundle, private_root / "bundle-bad-digest")
        with (bad_digest / "docker-compose.v2.yml").open("ab") as stream:
            stream.write(b"\n# altered after materialization\n")
        scenarios["bad_digest"] = _refusal_with_docker_facts(
            name="bad_digest",
            cwd=private_root,
            expected_error_substrings=("modified since materialization",),
            project_names=tuple(projects.values()),
            target_project=projects["main"],
            operation=lambda runner: deploy.deploy_from_bundle(
                bundle_dir=bad_digest,
                merge_sha=merge_sha,
                execute=True,
                run_subprocess=runner,
                trusted_readiness_anchor_raw=readiness_anchor_raw,
                deployment_state_root=private_root / "state-bad-digest",
            ),
        )

        bad_readiness = _copy_bundle(bundle, private_root / "bundle-bad-readiness")
        wrong_readiness = fixture.sign_readiness_fixture(
            material=material_fixture.material,
            readiness_private_key_hex=readiness_seed,
            compose_digest="0" * 64,
            application_image_digests=_application_images(image_ref),
            upstream_image_digests={"fixture-upstream": image_ref},
        )
        readiness_name = deploy._READINESS_MANIFEST_BUNDLE_NAME  # noqa: SLF001
        (bad_readiness / readiness_name).write_bytes(
            wrong_readiness.signed_manifest_raw
        )
        rewrite_outer_bundle_manifest(
            bad_readiness,
            changed_file=readiness_name,
        )
        scenarios["bad_readiness"] = _refusal_with_docker_facts(
            name="bad_readiness",
            cwd=private_root,
            expected_error_substrings=("compose_digest",),
            project_names=tuple(projects.values()),
            target_project=projects["main"],
            operation=lambda runner: deploy.deploy_from_bundle(
                bundle_dir=bad_readiness,
                merge_sha=merge_sha,
                execute=True,
                run_subprocess=runner,
                trusted_readiness_anchor_raw=readiness_anchor_raw,
                deployment_state_root=private_root / "state-bad-readiness",
            ),
        )

        bad_authorization = _copy_bundle(
            bundle, private_root / "bundle-bad-authorization"
        )
        authorization_name = deploy._AUTHORIZATION_SET_BUNDLE_NAME  # noqa: SLF001
        authorization_path = bad_authorization / authorization_name
        authorization_document = json.loads(authorization_path.read_bytes())
        authorization_document["authority_required_set_sha256"] = "f" * 64
        authorization_path.write_bytes(_fixture_json_bytes(authorization_document))
        rewrite_outer_bundle_manifest(
            bad_authorization,
            changed_file=authorization_name,
        )
        scenarios["bad_authorization_set"] = _refusal_with_docker_facts(
            name="bad_authorization_set",
            cwd=private_root,
            expected_error_substrings=("authorization",),
            project_names=tuple(projects.values()),
            target_project=projects["main"],
            operation=lambda runner: deploy.deploy_from_bundle(
                bundle_dir=bad_authorization,
                merge_sha=merge_sha,
                execute=True,
                run_subprocess=runner,
                trusted_readiness_anchor_raw=readiness_anchor_raw,
                deployment_state_root=private_root / "state-bad-authorization",
            ),
        )

        witness_compose = prepare_auxiliary_compose(
            root=private_root,
            project_name=projects["witness"],
            service_name="foreign-witness",
            image_ref=image_ref,
            cleanup_registry=cleanup_registry,
        )
        owned_projects.add(projects["witness"])
        _start_auxiliary(
            compose=witness_compose,
            project_name=projects["witness"],
            service_name="foreign-witness",
            mutation_commands=mutation_commands,
        )
        foreign_before = _container_snapshot(cwd=repo_root)
        collision_compose = prepare_auxiliary_compose(
            root=private_root,
            project_name=projects["collision"],
            service_name="ingestor",
            image_ref=image_ref,
            cleanup_registry=cleanup_registry,
        )
        owned_projects.add(projects["collision"])
        _start_auxiliary(
            compose=collision_compose,
            project_name=projects["collision"],
            service_name="ingestor",
            mutation_commands=mutation_commands,
        )
        scenarios["foreign_collision"] = _refusal_with_docker_facts(
            name="foreign_collision",
            cwd=private_root,
            expected_error_substrings=("already running",),
            project_names=tuple(projects.values()),
            target_project=projects["main"],
            operation=lambda runner: deploy.deploy_from_bundle(
                bundle_dir=bundle,
                merge_sha=merge_sha,
                execute=True,
                run_subprocess=runner,
                trusted_readiness_anchor_raw=readiness_anchor_raw,
                deployment_state_root=private_root / "state-collision",
            ),
        )
        collision_down = _down_auxiliary(
            compose=collision_compose,
            project_name=projects["collision"],
            cwd=collision_compose.parent,
            mutation_commands=mutation_commands,
        )
        if collision_down is None or collision_down.returncode != 0:
            raise RehearsalError("collision project cleanup failed")
        if project_inventory_count(
            _project_inventory(projects["collision"], cwd=repo_root)
        ):
            raise RehearsalError("collision project cleanup left residue")

        actual_calls: list[list[str]] = []

        def actual_runner(
            args: list[str], cwd: Path
        ) -> subprocess.CompletedProcess[str]:
            actual_calls.append(list(args))
            mutation_commands.append(list(args))
            return _run(args, cwd=cwd, timeout=300)

        owned_projects.add(projects["main"])
        deploy.deploy_from_bundle(
            bundle_dir=bundle,
            merge_sha=merge_sha,
            execute=True,
            run_subprocess=actual_runner,
            trusted_readiness_anchor_raw=readiness_anchor_raw,
            deployment_state_root=private_root / "deployment-state",
        )
        health_observation = _wait_project_healthy(
            projects["main"], expected_count=4, cwd=repo_root
        )
        published_ports = _project_published_ports(projects["main"], cwd=repo_root)
        valid_deployment_pass = (
            sum("pull" in command for command in actual_calls) == 1
            and sum("up" in command for command in actual_calls) == 1
            and not published_ports
        )
        scenarios["valid_bundle"] = {
            "passed": valid_deployment_pass,
            "exit_code": 0 if valid_deployment_pass else 1,
            "mutation_boundary_calls": len(actual_calls),
            "pull_calls": sum("pull" in command for command in actual_calls),
            "up_calls": sum("up" in command for command in actual_calls),
            "remove_orphans_used": any(
                "--remove-orphans" in command for command in actual_calls
            ),
        }
        after_up = _container_snapshot(cwd=repo_root)
        if foreign_snapshot_changes(
            foreign_before,
            after_up,
            generated_projects={projects["main"], projects["collision"]},
        ):
            raise RehearsalError("foreign service changed during valid deployment")

        rollback_args = rollback_command(bundle)
        mutation_commands.append(rollback_args)
        rollback = _run(rollback_args, cwd=bundle, timeout=180)
        rollback_inventory = _project_inventory(projects["main"], cwd=repo_root)
        rollback_pass = (
            rollback.returncode == 0
            and project_inventory_count(rollback_inventory) == 0
        )
        rollback_facts = {
            "exit_code": rollback.returncode,
            "project_inventory_after": rollback_inventory,
        }
        after_rollback = _container_snapshot(cwd=repo_root)
        foreign_changes = foreign_snapshot_changes(
            foreign_before,
            after_rollback,
            generated_projects={projects["main"], projects["collision"]},
        )
    finally:
        cleanup_operations: dict[str, CleanupOperation] = {}
        if (
            projects["main"] in owned_projects
            and bundle is not None
            and bundle.is_dir()
        ):

            def cleanup_main_project() -> None:
                assert bundle is not None
                cleanup_command = rollback_command(bundle)
                mutation_commands.append(cleanup_command)
                cleanup = _run(cleanup_command, cwd=bundle, timeout=180)
                if cleanup.returncode != 0:
                    raise RehearsalError(
                        f"main cleanup exited {cleanup.returncode}"
                    )

            cleanup_operations["main"] = cleanup_main_project

        def auxiliary_cleanup_operation(
            project_name: str, compose: Path
        ) -> CleanupOperation:
            def operation() -> None:
                auxiliary_cleanup = _down_auxiliary(
                    compose=compose,
                    project_name=project_name,
                    cwd=compose.parent,
                    mutation_commands=mutation_commands,
                )
                if (
                    auxiliary_cleanup is None
                    or auxiliary_cleanup.returncode != 0
                ):
                    raise RehearsalError(
                        f"{project_name} cleanup failed"
                    )

            return operation

        for project_name, compose in cleanup_registry.items():
            if project_name in owned_projects:
                cleanup_operations[project_name] = auxiliary_cleanup_operation(
                    project_name, compose
                )
        residue, cleanup_failures = exhaust_cleanup(
            cleanup_operations,
            lambda: _combined_generated_inventory(
                tuple(projects.values()), cwd=repo_root
            ),
        )
        if cleanup_failures:
            raise RehearsalError("; ".join(cleanup_failures))

    remove_orphans_used = any(
        "--remove-orphans" in command for command in mutation_commands
    )
    production_project_name_used = any(
        project == "infra" for project in projects.values()
    ) or any("infra" in command for command in mutation_commands) or any(
        fact["project"] == "infra" for fact in health_observation.values()
    )
    verdicts: dict[str, object] = {
        "BAD_DIGEST_REFUSED": scenarios.get("bad_digest", {}).get("passed") is True,
        "BAD_READINESS_REFUSED": scenarios.get("bad_readiness", {}).get("passed")
        is True,
        "BAD_AUTHORIZATION_SET_REFUSED": scenarios.get(
            "bad_authorization_set", {}
        ).get("passed")
        is True,
        "FOREIGN_COLLISION_REFUSED": scenarios.get("foreign_collision", {}).get(
            "passed"
        )
        is True,
        "ISOLATION_PREFLIGHT_PASS": isolation_preflight_pass,
        "FOREIGN_SERVICES_TOUCHED": len(foreign_changes),
        "PRODUCTION_PORTS_PUBLISHED": len(published_ports),
        "PRODUCTION_PROJECT_NAME_USED": production_project_name_used,
        "REMOVE_ORPHANS_USED": remove_orphans_used,
        "ROLLBACK_REHEARSAL_PASS": rollback_pass,
        "PROJECT_CONTAINERS_REMAINING": project_inventory_count(residue),
    }
    verdicts["ATOMIC_DOCKER_V2_REHEARSAL_PASS"] = (
        valid_deployment_pass and global_rehearsal_pass(verdicts)
    )
    return {
        "protocol_version": "NEXUS-ATOMIC-DOCKER-V2-REHEARSAL-EVIDENCE-V1",
        "git_commit": merge_sha,
        "git_tree": merge_tree_sha,
        "project_names": projects,
        "image_ref": image_ref,
        "image_id": image_id,
        "bundle_digest": bundle_digest,
        "bundle_attestation": bundle_attestation,
        "authorization_set_protocol": authorization_set_protocol,
        "readiness_protocol": readiness_protocol,
        "docker": docker_versions,
        "health_observation": health_observation,
        "rollback": rollback_facts,
        "isolation_preflight": preflight_inventories,
        "published_ports": published_ports,
        "mutation_command_count": len(mutation_commands),
        "image_preexisting_before_harness": True,
        "compose_pull_invoked": any(
            "pull" in command for command in mutation_commands
        ),
        "build_invoked": any("build" in command for command in mutation_commands),
        "readiness_public_anchor_sha256": (
            hashlib.sha256(readiness_anchor_raw).hexdigest()
            if "readiness_anchor_raw" in locals()
            else None
        ),
        "review_binding_public_anchor_sha256": (
            material_fixture.review_binding_public_anchor_sha256
            if material_fixture is not None
            else None
        ),
        "scenarios": scenarios,
        "foreign_changes": foreign_changes,
        "generated_project_residue": residue,
        "verdicts": verdicts,
    }


def _sanitized_scenarios(
    scenarios: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    sanitized: dict[str, dict[str, object]] = {}
    for name, facts in scenarios.items():
        selected = {
            key: value
            for key, value in facts.items()
            if key not in {"error_message", "cwd_exists", "mutation_commands"}
        }
        if name != "valid_bundle":
            selected["refusal_reason_code"] = name.upper()
        sanitized[name] = selected
    return sanitized


def _transcript_bytes(evidence: Mapping[str, Any]) -> bytes:
    lines = [
        f"PROTOCOL={evidence['protocol_version']}",
        f"OBSERVED_AT={evidence['observed_at']}",
        f"GIT_COMMIT={evidence['git_commit']}",
        f"GIT_TREE={evidence['git_tree']}",
        f"BUNDLE_DIGEST={evidence['bundle_digest']}",
        f"IMAGE_REF={evidence['image']['reference']}",
        f"IMAGE_LOCAL_ID={evidence['image']['local_id']}",
        f"DOCKER_ENGINE={evidence['docker']['engine_version']}",
        f"DOCKER_COMPOSE={evidence['docker']['compose_version']}",
        "BUNDLE_MANIFEST_SHA256="
        f"{evidence['bundle_attestation']['bundle_manifest_sha256']}",
        "BUNDLE_MEMBER_COUNT="
        f"{len(evidence['bundle_attestation']['member_sha256'])}",
        "HEALTHY_SERVICES="
        + ",".join(
            sorted(
                service
                for service, facts in evidence["health_observation"].items()
                if facts["health"] == "healthy"
            )
        ),
        f"ROLLBACK_EXIT={evidence['rollback']['exit_code']}",
        "ROLLBACK_RESIDUE="
        f"{project_inventory_count(evidence['rollback']['project_inventory_after'])}",
    ]
    lines.extend(
        "SCENARIO_"
        f"{name.upper()}=passed:{str(facts['passed']).lower()},"
        f"exit:{facts['exit_code']},mutations:{facts['mutation_boundary_calls']}"
        for name, facts in sorted(evidence["scenarios"].items())
    )
    lines.extend(
        f"{name}={str(value).lower() if isinstance(value, bool) else value}"
        for name, value in sorted(evidence["verdicts"].items())
    )
    sanitized = [sanitize_transcript_line(line, forbidden_values=()) for line in lines]
    return ("\n".join(sanitized) + "\n").encode("utf-8")


def _write_evidence(
    *, repo_root: Path, output_dir: Path, result: Mapping[str, Any]
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "atomic_docker_v2_rehearsal_20260825.json"
    transcript_path = output_dir / "atomic_docker_v2_rehearsal_20260825.transcript.txt"
    hashes_path = output_dir / "atomic_docker_v2_rehearsal_20260825.sha256"
    for path in (evidence_path, transcript_path, hashes_path):
        if path.exists():
            raise RehearsalError(f"evidence output already exists: {path.name}")
    harness_path = Path(__file__).resolve()
    fixture_path = Path(fixture.__file__).resolve()
    observed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence: dict[str, Any] = {
        "protocol_version": result["protocol_version"],
        "evidence_class": "SYNTHETIC_V2_REPRODUCIBLE",
        "verification_status": "VERIFIED",
        "observed_at": observed_at,
        "git_commit": result["git_commit"],
        "git_tree": result["git_tree"],
        "readiness_protocol": result["readiness_protocol"],
        "authorization_set_protocol": result["authorization_set_protocol"],
        "bundle_digest": result["bundle_digest"],
        "bundle_attestation": result["bundle_attestation"],
        "harness": {
            "path": harness_path.relative_to(repo_root).as_posix(),
            "sha256": hashlib.sha256(harness_path.read_bytes()).hexdigest(),
        },
        "fixture_builder_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "image": {
            "reference": result["image_ref"],
            "local_id": result["image_id"],
            "preexisting_before_harness": result[
                "image_preexisting_before_harness"
            ],
            "compose_pull_invoked": result["compose_pull_invoked"],
            "build_invoked": result["build_invoked"],
        },
        "docker": result["docker"],
        "health_observation": result["health_observation"],
        "rollback": result["rollback"],
        "isolation_preflight": result["isolation_preflight"],
        "project_names": result["project_names"],
        "production_project_name_used": result["verdicts"][
            "PRODUCTION_PROJECT_NAME_USED"
        ],
        "production_ports_published": result["verdicts"][
            "PRODUCTION_PORTS_PUBLISHED"
        ],
        "remove_orphans_used": result["verdicts"]["REMOVE_ORPHANS_USED"],
        "mutation_command_count": result["mutation_command_count"],
        "review_binding_public_anchor_sha256": result[
            "review_binding_public_anchor_sha256"
        ],
        "readiness_public_anchor_sha256": result[
            "readiness_public_anchor_sha256"
        ],
        "scenarios": _sanitized_scenarios(result["scenarios"]),
        "foreign_changes": result["foreign_changes"],
        "generated_project_residue": result["generated_project_residue"],
        "verdicts": result["verdicts"],
    }
    transcript_raw = _transcript_bytes(evidence)
    evidence["transcript_sha256"] = hashlib.sha256(transcript_raw).hexdigest()
    transcript_path.write_bytes(transcript_raw)
    evidence_path.write_bytes(_fixture_json_bytes(evidence))
    relative_files = (
        harness_path.relative_to(repo_root),
        fixture_path.relative_to(repo_root),
        evidence_path.relative_to(repo_root),
        transcript_path.relative_to(repo_root),
    )
    hashes_path.write_text(
        "".join(
            f"{hashlib.sha256((repo_root / relative).read_bytes()).hexdigest()}  "
            f"{relative.as_posix()}\n"
            for relative in relative_files
        ),
        encoding="utf-8",
    )
    return evidence_path, transcript_path, hashes_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=(
            Path(__file__).resolve().parents[3] / "docs" / "reports" / "evidence"
        ),
    )
    parser.add_argument("--image-tag", default="alpine:3.20")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        with tempfile.TemporaryDirectory(
            prefix="nexus-go-live-rehearsal-v2-"
        ) as temporary:
            result = run_rehearsal(
                repo_root=repo_root,
                private_root=Path(temporary),
                image_tag=args.image_tag,
            )
        if result["verdicts"].get("ATOMIC_DOCKER_V2_REHEARSAL_PASS") is not True:
            raise RehearsalError("global Docker V2 rehearsal verdict is false")
        evidence, transcript, hashes = _write_evidence(
            repo_root=repo_root,
            output_dir=args.output_dir.resolve(),
            result=result,
        )
    except RehearsalError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"EVIDENCE={evidence.name}")
    print(f"TRANSCRIPT={transcript.name}")
    print(f"HASHES={hashes.name}")
    print("ATOMIC_DOCKER_V2_REHEARSAL_PASS=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
