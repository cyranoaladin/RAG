"""Wrapper de déploiement atomique — ferme la fenêtre TOCTOU (Lot C).

**Le problème que ce lot ferme.** `verify_release_image_provenance_cli.py`
(PR #105) documente explicitement, dans son propre docstring (section
« Limite connue et acceptée »), une fenêtre de temps-de-vérification-au-
temps-d'utilisation (TOCTOU) : il matérialise les trois fichiers Compose
canoniques dans un répertoire scratch **éphémère**, rend un verdict, puis
se termine — l'étape de déploiement réelle (`docker compose up`, lancée
séparément et manuellement par l'opérateur) relit ensuite les fichiers
réels sur l'hôte, jamais ce scratch. Rien n'empêchait ces fichiers de
diverger entre les deux étapes.

**Ce que ce wrapper fait pour fermer cette fenêtre.** Un seul processus,
trois phases strictement séquentielles :

1. **Vérifier une seule fois** — `verify_release_image_provenance_cli.
   verify_release_images` (PR #105, désormais enrichie pour retourner un
   `VerifiedReleaseMaterialization` : Compose résolu, images épinglées,
   octets source Compose, octets `.env`, document de provenance d'image
   déjà vérifié — tout ce qui a été lu/prouvé, sans qu'aucun appelant en
   aval n'ait besoin de relire quoi que ce soit). Si
   `--readiness-manifest-file` est fourni, le manifeste signé est en plus
   vérifié (signature, ancre, environnement, verdict) via
   `nexus_contracts.production_readiness.verify_production_readiness_
   manifest`, et lié à `--merge-sha` ET au `compose_digest` réellement
   résolu (calculé avec `verify_release_image_provenance_cli.canonical_
   resolved_compose_bytes` — la même convention de canonicalisation que
   le signer, PR #100 Section 11) via `require_manifest_matches_release`.
2. **Matérialiser une fois, dans un bundle immuable** — EXCLUSIVEMENT
   depuis les champs de `VerifiedReleaseMaterialization` : aucune seconde
   résolution Compose, aucune seconde lecture de `.env`, aucun second
   téléchargement de la preuve de provenance. Les trois fichiers Compose,
   le JSON résolu, le `.env`, le document de provenance d'image vérifié
   (`image-provenance-evidence.json` — auditable hors ligne, pas
   seulement les digests qui en sont dérivés), et (si fourni) le
   manifeste de readiness signé sont copiés dans un répertoire bundle
   dédié. Un manifeste de bundle (`bundle_manifest.json`) enregistre le
   protocole, le dépôt, `merge_sha`, le SHA-256 de chaque fichier, et le
   SHA-256 de ce manifeste lui-même sert d'identité du bundle.
3. **Déployer depuis le bundle uniquement** — `docker compose pull` puis
   `docker compose up -d` (jamais d'option de nettoyage des conteneurs
   « orphelins » : le projet Compose de production est partagé avec une
   stack non-RAG sur l'hôte cible, ce nettoyage y détruirait des
   conteneurs que ce wrapper n'a aucune raison de toucher) sont invoqués
   avec `-f <bundle>/<fichier>
   ... --env-file <bundle>/.env`, contre une liste **explicite** de
   services dérivée du Compose résolu vérifié — jamais un `docker compose
   up` sans arguments, qui engagerait implicitement tout le projet.
   Immédiatement avant toute mutation réelle, une vérification de labels
   (`com.docker.compose.project`/`.config_files`/`.working_dir`/
   `.service`) sur les conteneurs déjà en cours d'exécution refuse si un
   service ciblé est déjà géré par un déploiement étranger — jamais un
   `docker stop`/`docker rm` lancé par ce wrapper lui-même.

**Ce que ce wrapper ne fait jamais.** Il ne construit ni ne pousse aucune
image. Il ne mute jamais rien sans `--execute` explicite, et `--execute`
refuse sans un manifeste de readiness signé ET son ancre de confiance —
la seule preuve de provenance d'image ne suffit jamais à autoriser une
mutation réelle (par défaut : verdict + bundle matérialisé + plan
imprimé, aucune commande Docker mutante lancée —
`LIVE_MUTATIONS_ALLOWED=false` par défaut). Il ne recalcule aucun verdict
de gouvernance pédagogique (ADR-0001). Il n'arrête ni ne supprime jamais
aucun conteneur lui-même."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deployment_image_inventory as dii  # noqa: E402
import verify_release_image_provenance_cli as vri  # noqa: E402
from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    parse_production_readiness_trust_anchor,
    require_manifest_matches_release,
    verify_production_readiness_manifest,
)

#: Jamais une entrée opérateur — même constante que le vérificateur
#: réutilisé (PR #105).
_CANONICAL_REPOSITORY = vri._CANONICAL_REPOSITORY
_CANONICAL_COMPOSE_FILES = vri._CANONICAL_COMPOSE_FILES

#: Protocole du manifeste de bundle produit par ce wrapper — distinct du
#: protocole de l'inventaire d'image (PR #102) et de celui du manifeste
#: de readiness (PR #100) : une identité propre, jamais confondue.
_BUNDLE_PROTOCOL_VERSION = "NEXUS-DEPLOYMENT-BUNDLE-V1"

#: Nom de fichier bundle pour chaque artefact matérialisé — utilisé à la
#: fois pour écrire (phase 2) et pour revérifier avant mutation (phase 3),
#: jamais deux littéraux qui pourraient diverger.
_ENV_BUNDLE_NAME = ".env"
_RESOLVED_COMPOSE_BUNDLE_NAME = "resolved-compose.json"
_IMAGE_PROVENANCE_BUNDLE_NAME = "image-provenance-evidence.json"
_READINESS_MANIFEST_BUNDLE_NAME = "readiness-manifest.json"
_BUNDLE_MANIFEST_NAME = "bundle_manifest.json"

RunDockerComposeConfig = vri.RunDockerComposeConfig
GitShowBytes = vri.GitShowBytes
RunSubprocess = Callable[[list[str], Path], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class RunningContainerInfo:
    """Labels Compose d'un conteneur déjà en cours d'exécution sur l'hôte
    — jamais dérivés du nom de projet seul (partagé avec une stack
    étrangère sur l'hôte cible), toujours confrontés aussi à
    ``config_files``/``working_dir`` avant toute mutation (§8)."""

    container_id: str
    service: str | None
    project: str | None
    config_files: str | None
    working_dir: str | None


ListRunningContainers = Callable[[], list[RunningContainerInfo]]


class DeploymentWrapperError(RuntimeError):
    """Le bundle ne peut pas être matérialisé, ou le déploiement ne peut
    pas procéder — fail-closed. Une seule exception : vérification
    échouée, fichier manquant, collision de label, sous-processus en
    échec. Un appelant n'a jamais à distinguer ces cas pour décider de ne
    pas déployer."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def verify_readiness_manifest_if_supplied(
    *,
    readiness_manifest_raw: bytes | None,
    trust_anchor_raw: bytes | None,
    environment: str,
    merge_sha: str,
    resolved_compose_digest: str,
) -> ProductionReadinessManifestV1 | None:
    """Vérifie le manifeste de readiness signé s'il est fourni — jamais
    un manifeste non vérifié consommé silencieusement, jamais un
    manifeste requis quand l'opérateur choisit de n'en fournir aucun en
    mode plan-only (voir ``--execute`` dans ``main`` pour la contrainte
    inverse : aucune mutation réelle sans ce manifeste).

    Lie désormais le manifeste au ``compose_digest`` RÉELLEMENT résolu
    par ce wrapper (PR #107 round 2) — plus de ``compose_digest=None`` :
    un manifeste signé pour un Compose résolu différent de celui que ce
    wrapper s'apprête à déployer est refusé, jamais silencieusement
    ignoré."""
    if readiness_manifest_raw is None:
        return None
    if trust_anchor_raw is None:
        raise DeploymentWrapperError(
            "--readiness-manifest-file was supplied without --trust-anchor-file — "
            "a readiness manifest can never be trusted without its trust anchor"
        )
    try:
        trust_anchor = parse_production_readiness_trust_anchor(trust_anchor_raw)
        manifest = verify_production_readiness_manifest(
            readiness_manifest_raw, trust_anchor=trust_anchor, environment=environment
        )
        require_manifest_matches_release(
            manifest, release_sha=merge_sha, compose_digest=resolved_compose_digest
        )
    except ProductionReadinessError as exc:
        raise DeploymentWrapperError(f"readiness manifest rejected: {exc}") from exc
    return manifest


def materialize_verified_bundle(
    *,
    merge_sha: str,
    merge_tree_sha: str,
    provenance_run_id: int,
    provenance_run_attempt: int,
    repo_root: Path,
    env_file: Path,
    readiness_manifest_file: Path | None,
    trust_anchor_file: Path | None,
    environment: str,
    github_api_get: dii.GitHubApiGet,
    download_artifact: dii.DownloadArtifact,
    run_docker_compose_config: RunDockerComposeConfig,
    work_dir: Path,
    bundle_dir: Path,
    git_show_bytes: GitShowBytes = vri._git_show_bytes,
) -> dict[str, Any]:
    """Phase 1 (vérifier, une seule fois) + phase 2 (matérialiser) —
    jamais l'inverse, et jamais une seconde résolution/lecture d'une
    entrée mutable entre les deux.

    Rien n'est écrit dans ``bundle_dir`` avant que la vérification de la
    provenance des images (et, si fourni, du manifeste de readiness)
    n'ait réussi : un bundle partiellement matérialisé pour une release
    refusée n'existe jamais."""
    work_dir.mkdir(parents=True, exist_ok=True)
    materialization = vri.verify_release_images(
        source_commit_sha=merge_sha,
        source_tree_sha=merge_tree_sha,
        provenance_run_id=provenance_run_id,
        provenance_run_attempt=provenance_run_attempt,
        repo_root=repo_root,
        compose_files=_CANONICAL_COMPOSE_FILES,
        env_file=env_file,
        github_api_get=github_api_get,
        download_artifact=download_artifact,
        run_docker_compose_config=run_docker_compose_config,
        work_dir=work_dir,
        git_show_bytes=git_show_bytes,
    )

    resolved_compose_bytes = vri.canonical_resolved_compose_bytes(materialization.resolved_compose)
    resolved_compose_digest = _sha256_bytes(resolved_compose_bytes)

    readiness_manifest_raw = (
        readiness_manifest_file.read_bytes() if readiness_manifest_file is not None else None
    )
    trust_anchor_raw = trust_anchor_file.read_bytes() if trust_anchor_file is not None else None
    verify_readiness_manifest_if_supplied(
        readiness_manifest_raw=readiness_manifest_raw,
        trust_anchor_raw=trust_anchor_raw,
        environment=environment,
        merge_sha=merge_sha,
        resolved_compose_digest=resolved_compose_digest,
    )

    if bundle_dir.exists():
        raise DeploymentWrapperError(
            f"bundle directory {bundle_dir} already exists — a bundle is never "
            "overwritten silently (rename or remove it first)"
        )
    bundle_dir.mkdir(parents=True)

    file_digests: dict[str, str] = {}
    for name in _CANONICAL_COMPOSE_FILES:
        content = materialization.compose_source_bytes[name]
        (bundle_dir / name).write_bytes(content)
        file_digests[name] = _sha256_bytes(content)

    (bundle_dir / _ENV_BUNDLE_NAME).write_bytes(materialization.env_bytes)
    file_digests[_ENV_BUNDLE_NAME] = _sha256_bytes(materialization.env_bytes)

    (bundle_dir / _RESOLVED_COMPOSE_BUNDLE_NAME).write_bytes(resolved_compose_bytes)
    file_digests[_RESOLVED_COMPOSE_BUNDLE_NAME] = resolved_compose_digest

    image_provenance_bytes = _canonical_json_bytes(materialization.image_provenance_document)
    (bundle_dir / _IMAGE_PROVENANCE_BUNDLE_NAME).write_bytes(image_provenance_bytes)
    file_digests[_IMAGE_PROVENANCE_BUNDLE_NAME] = _sha256_bytes(image_provenance_bytes)

    if readiness_manifest_raw is not None:
        (bundle_dir / _READINESS_MANIFEST_BUNDLE_NAME).write_bytes(readiness_manifest_raw)
        file_digests[_READINESS_MANIFEST_BUNDLE_NAME] = _sha256_bytes(readiness_manifest_raw)

    explicit_services = sorted(materialization.resolved_compose.get("services", {}))
    bundle_document = {
        "protocol_version": _BUNDLE_PROTOCOL_VERSION,
        "repository": _CANONICAL_REPOSITORY,
        "merge_sha": merge_sha,
        "merge_tree_sha": merge_tree_sha,
        "provenance_run_id": provenance_run_id,
        "provenance_run_attempt": provenance_run_attempt,
        "verified_images": dict(sorted(materialization.pinned_images.items())),
        "explicit_services": explicit_services,
        "files": dict(sorted(file_digests.items())),
        "readiness_manifest_included": readiness_manifest_raw is not None,
    }
    bundle_bytes = _canonical_json_bytes(bundle_document)
    bundle_document["bundle_digest"] = _sha256_bytes(bundle_bytes)
    (bundle_dir / _BUNDLE_MANIFEST_NAME).write_bytes(_canonical_json_bytes(bundle_document))
    return bundle_document


def _default_run_subprocess(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=600, check=False)


def _default_list_running_containers() -> list[RunningContainerInfo]:
    """Frontière process par défaut — jamais exercée en test unitaire
    (injectée, même convention que ``run_subprocess``). Analyse les
    labels Compose de CHAQUE conteneur actuellement en cours d'exécution
    sur l'hôte, pas seulement ceux du projet attendu : c'est précisément
    ce qui permet de détecter une collision avec une stack étrangère
    portant le même nom de service ou de projet."""
    completed = subprocess.run(
        ["docker", "ps", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise DeploymentWrapperError(
            f"docker ps failed (exit {completed.returncode}): {completed.stderr.strip()[:500]}"
        )
    containers: list[RunningContainerInfo] = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        labels: dict[str, str] = {}
        for pair in (row.get("Labels") or "").split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                labels[key] = value
        containers.append(
            RunningContainerInfo(
                container_id=row.get("ID", ""),
                service=labels.get("com.docker.compose.service"),
                project=labels.get("com.docker.compose.project"),
                config_files=labels.get("com.docker.compose.project.config_files"),
                working_dir=labels.get("com.docker.compose.project.working_dir"),
            )
        )
    return containers


def require_no_foreign_container_collision(
    *,
    target_services: list[str],
    expected_working_dir: str,
    running_containers: list[RunningContainerInfo],
) -> None:
    """Refuse si un service ciblé par ce déploiement est déjà géré par un
    conteneur dont le ``working_dir`` Compose ne correspond pas à ce
    bundle — jamais un nom de projet seul, partagé sur l'hôte cible avec
    une stack non-RAG (§8). Ne supprime ni n'arrête jamais rien : refuse
    seulement, avant toute mutation."""
    for container in running_containers:
        if container.service in target_services and container.working_dir != expected_working_dir:
            raise DeploymentWrapperError(
                f"service {container.service!r} is already running (container "
                f"{container.container_id!r}) under compose working_dir "
                f"{container.working_dir!r}, not this bundle's {expected_working_dir!r} "
                "— refusing to mutate a container that does not recognizably belong "
                "to this same deployment (never stopped or removed automatically)"
            )


def _require_bundle_files_match_manifest(bundle_dir: Path, bundle_document: dict[str, Any]) -> None:
    files = bundle_document.get("files")
    if not isinstance(files, dict) or not files:
        raise DeploymentWrapperError("bundle_manifest.json has no (or an empty) 'files' entry")
    for name, expected_digest in files.items():
        path = bundle_dir / name
        if not path.is_file():
            raise DeploymentWrapperError(f"bundle is missing file {name!r} recorded in its own manifest")
        actual_digest = _sha256_bytes(path.read_bytes())
        if actual_digest != expected_digest:
            raise DeploymentWrapperError(
                f"bundle file {name!r} has been modified since materialization "
                f"(sha256 {actual_digest} != recorded {expected_digest}) — a "
                "bundle is deployed byte-identical to what was verified, or not at all"
            )
    on_disk = {p.name for p in bundle_dir.iterdir() if p.is_file() and p.name != _BUNDLE_MANIFEST_NAME}
    unexpected = on_disk - set(files)
    if unexpected:
        raise DeploymentWrapperError(
            f"bundle directory contains unexpected file(s) not recorded in its own "
            f"manifest: {sorted(unexpected)} — an extra critical file is never "
            "silently deployed alongside a verified bundle"
        )


def _load_and_verify_bundle_manifest(bundle_dir: Path, *, merge_sha: str) -> dict[str, Any]:
    bundle_manifest_path = bundle_dir / _BUNDLE_MANIFEST_NAME
    if not bundle_manifest_path.is_file():
        raise DeploymentWrapperError(
            f"{bundle_manifest_path} is missing — this is not a bundle produced by "
            "materialize_verified_bundle, or it was tampered with"
        )
    try:
        bundle_document = json.loads(bundle_manifest_path.read_bytes())
    except json.JSONDecodeError as exc:
        raise DeploymentWrapperError(f"bundle_manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(bundle_document, dict):
        raise DeploymentWrapperError("bundle_manifest.json must be a JSON object")
    if bundle_document.get("protocol_version") != _BUNDLE_PROTOCOL_VERSION:
        raise DeploymentWrapperError(
            f"bundle_manifest.json protocol_version {bundle_document.get('protocol_version')!r} "
            f"!= {_BUNDLE_PROTOCOL_VERSION!r}"
        )
    if bundle_document.get("repository") != _CANONICAL_REPOSITORY:
        raise DeploymentWrapperError(
            f"bundle_manifest.json repository {bundle_document.get('repository')!r} "
            f"!= {_CANONICAL_REPOSITORY!r}"
        )
    if bundle_document.get("merge_sha") != merge_sha:
        raise DeploymentWrapperError(
            f"bundle was materialized for merge_sha {bundle_document.get('merge_sha')!r}, "
            f"not the commit currently being deployed ({merge_sha!r})"
        )
    _require_bundle_files_match_manifest(bundle_dir, bundle_document)
    return bundle_document


def deploy_from_bundle(
    *,
    bundle_dir: Path,
    merge_sha: str,
    execute: bool,
    run_subprocess: RunSubprocess = _default_run_subprocess,
    list_running_containers: ListRunningContainers = _default_list_running_containers,
) -> list[str]:
    """Phase 3 (déployer) — toujours et uniquement depuis ``bundle_dir``,
    contre une liste explicite de services.

    Sans ``--execute``, aucune commande Docker mutante n'est lancée :
    seul le plan (la liste des commandes qui SERAIENT exécutées) est
    retourné. Avec ``--execute``, la vérification de labels (§8) tourne
    juste avant toute mutation, puis chaque étape doit réussir avant que
    la suivante ne soit lancée — un `pull` en échec n'est jamais suivi
    d'un `up`. Jamais d'option de nettoyage des conteneurs orphelins :
    le projet Compose de production est partagé avec une stack non-RAG
    sur l'hôte cible."""
    bundle_document = _load_and_verify_bundle_manifest(bundle_dir, merge_sha=merge_sha)
    explicit_services = bundle_document.get("explicit_services")
    if not isinstance(explicit_services, list) or not explicit_services:
        raise DeploymentWrapperError("bundle_manifest.json has no (or an empty) 'explicit_services' list")

    compose_args = ["docker", "compose", "--env-file", str(bundle_dir / _ENV_BUNDLE_NAME)]
    for name in _CANONICAL_COMPOSE_FILES:
        compose_args += ["-f", str(bundle_dir / name)]

    plan = [
        " ".join(compose_args + ["pull", *explicit_services]),
        " ".join(compose_args + ["up", "-d", *explicit_services]),
    ]
    if not execute:
        return plan

    require_no_foreign_container_collision(
        target_services=explicit_services,
        expected_working_dir=str(bundle_dir),
        running_containers=list_running_containers(),
    )

    pull = run_subprocess(compose_args + ["pull", *explicit_services], bundle_dir)
    if pull.returncode != 0:
        raise DeploymentWrapperError(
            f"docker compose pull failed (exit {pull.returncode}): {pull.stderr.strip()[:1000]}"
        )
    up = run_subprocess(compose_args + ["up", "-d", *explicit_services], bundle_dir)
    if up.returncode != 0:
        raise DeploymentWrapperError(
            f"docker compose up failed (exit {up.returncode}): {up.stderr.strip()[:1000]}"
        )
    return plan


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--merge-sha", required=True)
    p.add_argument("--merge-tree-sha", required=True)
    p.add_argument("--provenance-run-id", type=int, required=True)
    p.add_argument("--provenance-run-attempt", type=int, required=True)
    p.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    p.add_argument("--env-file", type=Path, default=None)
    p.add_argument("--readiness-manifest-file", type=Path, default=None)
    p.add_argument("--trust-anchor-file", type=Path, default=None)
    p.add_argument("--environment", default="production")
    p.add_argument("--bundle-dir", type=Path, required=True)
    p.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Sans ce drapeau : matérialise le bundle et imprime le plan de "
        "déploiement, ne lance aucune commande mutante (LIVE_MUTATIONS_ALLOWED=false "
        "par défaut). Avec ce drapeau : REFUSE si --readiness-manifest-file ou "
        "--trust-anchor-file est absent — la seule preuve de provenance d'image ne "
        "suffit jamais à autoriser une mutation réelle.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.execute and (args.readiness_manifest_file is None or args.trust_anchor_file is None):
        print(
            "REFUSED: --execute requires both --readiness-manifest-file and "
            "--trust-anchor-file — image provenance proof alone never authorizes a "
            "real deployment mutation",
            file=sys.stderr,
        )
        return 1
    env_file = args.env_file or (args.repo_root / vri._ENV_FILE_RELATIVE_PATH)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_document = materialize_verified_bundle(
                merge_sha=args.merge_sha,
                merge_tree_sha=args.merge_tree_sha,
                provenance_run_id=args.provenance_run_id,
                provenance_run_attempt=args.provenance_run_attempt,
                repo_root=args.repo_root,
                env_file=env_file,
                readiness_manifest_file=args.readiness_manifest_file,
                trust_anchor_file=args.trust_anchor_file,
                environment=args.environment,
                github_api_get=dii.gh_api_get,
                download_artifact=dii.make_download_artifact_via_gh(repository=_CANONICAL_REPOSITORY),
                run_docker_compose_config=vri.run_docker_compose_config_via_subprocess,
                work_dir=Path(tmp),
                bundle_dir=args.bundle_dir,
                git_show_bytes=vri._git_show_bytes,
            )
        plan = deploy_from_bundle(
            bundle_dir=args.bundle_dir, merge_sha=args.merge_sha, execute=args.execute
        )
    except (DeploymentWrapperError, vri.ReleaseVerificationError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    print(f"BUNDLE_DIGEST={bundle_document['bundle_digest']}")
    for name, ref in sorted(bundle_document["verified_images"].items()):
        print(f"VERIFIED {name}={ref}")
    if bundle_document["readiness_manifest_included"]:
        print("SIGNED_COMPOSE_DIGEST_MATCH=true")
    if args.execute:
        print("DEPLOYED=true")
    else:
        print("DEPLOYED=false (dry run — pass --execute to run the plan below)")
        for step in plan:
            print(f"PLAN: {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
