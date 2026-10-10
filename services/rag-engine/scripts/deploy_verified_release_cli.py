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
de gouvernance pédagogique (ADR-0001). La voie historique n'arrête aucun
conteneur ; la voie publique peut retirer uniquement la couleur candidate
après un échec de démarrage ou sur rollback explicite."""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import hashlib
import json
import os
import secrets
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deployment_image_inventory as dii  # noqa: E402
import public_blue_green_preflight as public_preflight  # noqa: E402
import sign_production_readiness_manifest_cli as signer  # noqa: E402
import verify_release_image_provenance_cli as vri  # noqa: E402
from nexus_contracts.authorization_loader import (  # noqa: E402
    load_authorization_set,
)
from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    ProductionReadinessManifestV2,
    parse_production_readiness_trust_anchor,
    require_manifest_matches_release,
    require_public_candidate_inventory_matches_readiness,
    verify_production_readiness_manifest,
    verify_production_readiness_manifest_v2,
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
_READINESS_TRUST_ANCHOR_BUNDLE_NAME = "readiness-trust-anchor.json"
_AUTHORIZATION_SET_BUNDLE_NAME = "authorization-set.json"
_REVOCATIONS_BUNDLE_NAME = "authorization-revocations.json"
_PLACEMENT_BUNDLE_NAME = "release-scope-placement.jsonl"
_VERIFIED_PROFILES_BUNDLE_NAME = "verified-profiles.json"
_PROFILE_MANIFEST_BUNDLE_NAME = "profile-manifest.yml"
_AUTHORITY_REQUIRED_BUNDLE_NAME = "authority-required.txt"
_H2_COVERAGE_BUNDLE_NAME = "h2-coverage.json"
_H2_EVIDENCE_BUNDLE_NAME = "h2-evidence.json"
_PROMOTION_BUNDLE_NAME = "promotion-evidence.json"
_SEALED_MANIFEST_BUNDLE_NAME = "sealed-manifest.txt"
_BUNDLE_MANIFEST_NAME = "bundle_manifest.json"

RunDockerComposeConfig = Callable[[Path, str, tuple[str, ...], Path, Path], dict[str, Any]]
GitShowBytes = Callable[[Path, str, str], bytes]
RunSubprocess = Callable[[list[str], Path], "subprocess.CompletedProcess[str]"]
RunBundleComposeConfig = Callable[[Path, Path, tuple[str, ...]], dict[str, Any]]


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
ProjectInventory = Callable[[str], dict[str, list[str]]]
ReadinessAssert = Callable[[], bool]
ProjectContainers = Callable[[str], list[dict[str, Any]]]
PrometheusProbe = Callable[[int], bool]
HostLocalGuard = Callable[[], bool]


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


def _run_bundle_compose_config(
    bundle_dir: Path, env_file: Path, compose_files: tuple[str, ...]
) -> dict[str, Any]:
    """Résout les octets exacts que la commande de mutation consommera."""
    args = ["docker", "compose", "--env-file", str(env_file)]
    for name in compose_files:
        args += ["-f", str(bundle_dir / name)]
    args += ["config", "--format", "json"]
    try:
        completed = subprocess.run(
            args, cwd=bundle_dir, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentWrapperError(f"docker compose config failed: {exc}") from exc
    if completed.returncode != 0:
        raise DeploymentWrapperError(
            f"docker compose config failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:1000]}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DeploymentWrapperError(
            f"docker compose config produced non-JSON output: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise DeploymentWrapperError("docker compose config did not produce a JSON object")
    return document


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


def require_public_candidate_inventory_binding(
    manifest: ProductionReadinessManifestV2, document: dict[str, Any]
) -> None:
    """Relie l'inventaire V2 vérifié au manifeste signé, sans réseau nouveau."""
    if manifest.public_candidate_inventory_digest is None:
        return
    services = document.get("services")
    if (
        document.get("protocol_version") != dii._PUBLIC_PROTOCOL_VERSION
        or document.get("repository") != manifest.repository
        or document.get("source_commit_sha") != manifest.merge_sha
        or document.get("source_tree_sha") != manifest.merge_tree_sha
        or not isinstance(services, dict)
    ):
        raise DeploymentWrapperError("public candidate inventory identity differs from signed readiness")
    try:
        images = {
            name: f"{service['image_repository']}@{service['image_digest']}"
            for name, service in services.items()
        }
        require_public_candidate_inventory_matches_readiness(
            manifest,
            inventory_digest=dii.public_candidate_inventory_digest(document),
            provenance_run_id=document["workflow_run_id"],
            provenance_run_attempt=document["workflow_run_attempt"],
            application_image_digests=images,
        )
    except (KeyError, TypeError, ProductionReadinessError) as exc:
        raise DeploymentWrapperError(
            f"public candidate inventory differs from signed readiness: {exc}"
        ) from exc


def _runtime_application_services(
    manifest: ProductionReadinessManifestV1 | ProductionReadinessManifestV2,
) -> frozenset[str]:
    if isinstance(manifest, ProductionReadinessManifestV2) and (
        manifest.public_candidate_inventory_digest is not None
    ):
        return dii._PUBLIC_RUNTIME_APPLICATION_SERVICES
    return dii._EXPECTED_APPLICATION_SERVICES


def require_runtime_images_match_readiness(
    manifest: ProductionReadinessManifestV1 | ProductionReadinessManifestV2,
    pinned_images: dict[str, str],
) -> None:
    """Deux images exécutées pour le public ; quatre restent signées."""
    if isinstance(manifest, ProductionReadinessManifestV2) and (
        manifest.public_candidate_inventory_digest is not None
    ):
        expected = {
            name: manifest.application_image_digests[name]
            for name in dii._PUBLIC_RUNTIME_APPLICATION_SERVICES
        }
    else:
        expected = manifest.application_image_digests
    if pinned_images != expected:
        raise DeploymentWrapperError("runtime images differ from signed readiness")


def _verify_readiness_manifest_v2_with_material_details(
    *,
    readiness_manifest_raw: bytes,
    trust_anchor_raw: bytes,
    material: signer.V2ReleaseMaterial,
    environment: str,
    merge_sha: str,
    resolved_compose_digest: str,
) -> tuple[ProductionReadinessManifestV2, signer.VerifiedV2ReleaseMaterial]:
    """Chemin V2 explicite : signature puis toutes les preuves exactes.

    Aucun fallback V1 et aucun digest seul : le même snapshot de release est
    revérifié par le boundary global avant qu'un bundle puisse être écrit.
    """
    try:
        trust_anchor = parse_production_readiness_trust_anchor(trust_anchor_raw)
        manifest = verify_production_readiness_manifest_v2(
            readiness_manifest_raw,
            trust_anchor=trust_anchor,
            environment=environment,
        )
        verified = signer.verify_v2_release_material(material)
    except (ProductionReadinessError, signer.SigningToolError) as exc:
        raise DeploymentWrapperError(f"readiness V2 rejected: {exc}") from exc

    comparisons = {
        "repository": (
            manifest.repository,
            _CANONICAL_REPOSITORY,
            verified.promotion.repository,
        ),
        "pr_number": (manifest.pr_number, verified.promotion.pull_request_number),
        "pr_head_sha": (manifest.pr_head_sha, verified.promotion.pr_head_sha),
        "pr_head_tree_sha": (
            manifest.pr_head_tree_sha,
            verified.promotion.pr_head_tree_sha,
        ),
        "merge_sha": (manifest.merge_sha, merge_sha, material.merge_sha),
        "merge_tree_sha": (manifest.merge_tree_sha, material.merge_tree_sha),
        "compose_digest": (manifest.compose_digest, resolved_compose_digest),
        "authorization_set_digest": (
            manifest.authorization_set_digest,
            verified.authorization_set.digest(),
        ),
        "trust_anchor_digest": (
            manifest.trust_anchor_digest,
            _sha256_bytes(material.review_binding_trust_anchor_raw),
        ),
        "revocation_registry_digest": (
            manifest.revocation_registry_digest,
            _sha256_bytes(material.revocation_registry_raw),
        ),
        "catalog_digest": (
            manifest.catalog_digest,
            _sha256_bytes(material.evidence_files["catalog"]),
        ),
        "sealed_manifest_digest": (
            manifest.sealed_manifest_digest,
            _sha256_bytes(material.sealed_manifest_raw),
        ),
        "h2b_report_digest": (
            manifest.h2b_report_digest,
            _sha256_bytes(material.promotion_evidence_raw),
        ),
        "promotion_run_id": (manifest.run_id, verified.promotion.promotion_run_id),
        "promotion_run_attempt": (
            manifest.run_attempt,
            verified.promotion.promotion_run_attempt,
        ),
        "promotion_workflow_path": (
            manifest.workflow_path,
            verified.promotion.promotion_workflow_path,
        ),
        "promotion_workflow_ref": (
            manifest.workflow_ref,
            verified.promotion.promotion_workflow_ref,
        ),
    }
    mismatches = [
        name for name, values in comparisons.items() if any(v != values[0] for v in values[1:])
    ]
    if mismatches:
        raise DeploymentWrapperError(
            f"readiness V2 material mismatch: {sorted(mismatches)!r}"
        )
    if not (
        verified.verified_authorization_set.authorizations_effective_valid_from
        <= material.now
        < verified.verified_authorization_set.authorizations_effective_valid_until
    ):
        raise DeploymentWrapperError("readiness V2 authorization window is not active")
    return manifest, verified


def verify_readiness_manifest_v2_with_material(
    *,
    readiness_manifest_raw: bytes,
    trust_anchor_raw: bytes,
    material: signer.V2ReleaseMaterial,
    environment: str,
    merge_sha: str,
    resolved_compose_digest: str,
) -> ProductionReadinessManifestV2:
    """Conserve le contrat public du vérificateur V2 existant."""
    manifest, _ = _verify_readiness_manifest_v2_with_material_details(
        readiness_manifest_raw=readiness_manifest_raw,
        trust_anchor_raw=trust_anchor_raw,
        material=material,
        environment=environment,
        merge_sha=merge_sha,
        resolved_compose_digest=resolved_compose_digest,
    )
    return manifest


def plan_signed_public_candidate(
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
    github_api_get: dii.GitHubApiGet,
    download_artifact: dii.DownloadArtifact,
    work_dir: Path,
    readiness_manifest_raw: bytes,
    trust_anchor_raw: bytes,
    release_material: signer.V2ReleaseMaterial,
) -> dict[str, Any]:
    """Relie le préflight public à la readiness V2, sans chemin de mutation.

    La source Compose n'est pas encore matérialisée depuis l'objet Git dans
    un bundle public durable. Ce verdict est donc uniquement un plan : même
    une signature et un préflight valides n'autorisent pas ``compose up``.
    """
    if not readiness_manifest_raw or not trust_anchor_raw:
        raise DeploymentWrapperError("public candidate requires signed V2 readiness and trust anchor")
    compose_digest = _sha256_bytes(vri.canonical_resolved_compose_bytes(resolved_compose))
    manifest, verified = _verify_readiness_manifest_v2_with_material_details(
        readiness_manifest_raw=readiness_manifest_raw,
        trust_anchor_raw=trust_anchor_raw,
        material=release_material,
        environment="production",
        merge_sha=source_sha,
        resolved_compose_digest=compose_digest,
    )
    if manifest.merge_tree_sha != source_tree_sha:
        raise DeploymentWrapperError("public candidate source tree differs from signed readiness")
    if manifest.public_candidate_inventory_digest is None:
        raise DeploymentWrapperError("public candidate inventory is absent from signed readiness")
    promotion = verified.promotion
    if (
        promotion.image_provenance_run_id != provenance_run_id
        or promotion.image_provenance_run_attempt != provenance_run_attempt
    ):
        raise DeploymentWrapperError("public candidate provenance run differs from signed promotion")
    try:
        inventory = dii.fetch_and_verify_public_candidate_image_provenance_document(
            repository=_CANONICAL_REPOSITORY,
            source_commit_sha=source_sha,
            source_tree_sha=source_tree_sha,
            provenance_run_id=provenance_run_id,
            provenance_run_attempt=provenance_run_attempt,
            github_api_get=github_api_get,
            download_artifact=download_artifact,
            work_dir=work_dir,
        )
        require_public_candidate_inventory_binding(manifest, inventory)
        verified_images = {
            name: f"{item['image_repository']}@{item['image_digest']}"
            for name, item in inventory["services"].items()
        }
        evidence = public_preflight.require_public_candidate(
            resolved_compose=resolved_compose,
            source_sha=source_sha,
            color=color,
            material_root=material_root,
            secrets_root=secrets_root,
            repo_root=repo_root,
            verified_application_images=verified_images,
        )
        upstream = signer._upstream_services_from_resolved_compose(  # noqa: SLF001
            resolved_compose, application_services=dii._PUBLIC_RUNTIME_APPLICATION_SERVICES
        )
    except (
        public_preflight.PublicCandidateError,
        signer.SigningToolError,
        dii.DeploymentImageInventoryError,
    ) as exc:
        raise DeploymentWrapperError(f"public candidate preflight rejected: {exc}") from exc
    if manifest.application_image_digests["ingestor"] != evidence["api_image"]:
        raise DeploymentWrapperError("public candidate API image differs from signed readiness")
    if manifest.upstream_image_digests != upstream:
        raise DeploymentWrapperError("public candidate upstream images differ from signed readiness")
    return {
        **evidence,
        "signed_readiness_valid": True,
        "production_ready": False,
        "go_live_ready": False,
        "mutation_allowed": False,
        "missing_cutover_preconditions": [
            "compose_source_snapshot_unverified",
            "durable_material_snapshot_unverified",
            "cockpit_bff_digest_and_e2e_unverified",
            "public_edge_ingest_denial_unverified",
            "candidate_rollback_unverified",
            "final_cutover_go_missing",
        ],
    }


def _create_private_bundle_dir(bundle_dir: Path) -> None:
    """Crée le bundle à 0700 sous un parent sans lien ni écriture étrangère."""
    if bundle_dir.exists() or bundle_dir.is_symlink():
        raise DeploymentWrapperError(
            f"bundle directory {bundle_dir} already exists — a bundle is never overwritten"
        )
    try:
        parent_fd, _identities = _open_directory_chain_no_follow(bundle_dir.parent)
    except OSError as exc:
        raise DeploymentWrapperError(f"bundle directory parent cannot be opened safely: {exc}") from exc
    try:
        try:
            os.mkdir(bundle_dir.name, 0o700, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise DeploymentWrapperError("bundle directory already exists") from exc
        except OSError as exc:
            raise DeploymentWrapperError(f"bundle directory cannot be created safely: {exc}") from exc
        try:
            bundle_fd = os.open(
                bundle_dir.name,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise DeploymentWrapperError(f"bundle directory cannot be opened safely: {exc}") from exc
        try:
            os.fchmod(bundle_fd, 0o700)
        finally:
            os.close(bundle_fd)
    finally:
        os.close(parent_fd)


def _write_private_bundle_file(bundle_dir: Path, name: str, raw: bytes) -> None:
    """Écrit atomiquement à 0600 sous des sous-répertoires privés."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise DeploymentWrapperError(f"unsafe bundle file path {name!r}")
    parent = bundle_dir
    for part in relative.parts[:-1]:
        parent /= part
        try:
            parent.mkdir(mode=0o700)
        except FileExistsError:
            metadata = parent.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or metadata.st_uid != os.geteuid()
            ):
                raise DeploymentWrapperError("bundle subdirectory is not private") from None
    path = bundle_dir / name
    if path.exists() or path.is_symlink():
        raise DeploymentWrapperError(f"bundle file {name!r} already exists")
    try:
        signer._atomic_private_write(path, raw)  # noqa: SLF001 - même écriture 0600 atomique
    except signer.SigningToolError as exc:
        raise DeploymentWrapperError(f"bundle file {name!r} cannot be written privately: {exc}") from exc
    metadata = path.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise DeploymentWrapperError(f"bundle file {name!r} is not a private regular file")


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
    readiness_protocol: str = "NEXUS-PRODUCTION-READINESS-V1",
    v2_release_material: signer.V2ReleaseMaterial | None = None,
    frozen_trust_anchor_raw: bytes | None = None,
    public_candidate: bool = False,
) -> dict[str, Any]:
    """Phase 1 (vérifier, une seule fois) + phase 2 (matérialiser) —
    jamais l'inverse, et jamais une seconde résolution/lecture d'une
    entrée mutable entre les deux.

    Rien n'est écrit dans ``bundle_dir`` avant que la vérification de la
    provenance des images (et, si fourni, du manifeste de readiness)
    n'ait réussi : un bundle partiellement matérialisé pour une release
    refusée n'existe jamais."""
    if public_candidate and readiness_protocol != "NEXUS-PRODUCTION-READINESS-V2":
        raise DeploymentWrapperError("public candidate requires signed readiness V2")
    compose_files = (
        vri._PUBLIC_CANDIDATE_COMPOSE_FILES if public_candidate else _CANONICAL_COMPOSE_FILES
    )
    try:
        work_dir = vri.require_private_work_dir(work_dir)
    except vri.ReleaseVerificationError as exc:
        raise DeploymentWrapperError(str(exc)) from exc
    materialization = vri.verify_release_images(
        source_commit_sha=merge_sha,
        source_tree_sha=merge_tree_sha,
        provenance_run_id=provenance_run_id,
        provenance_run_attempt=provenance_run_attempt,
        repo_root=repo_root,
        compose_files=compose_files,
        env_file=env_file,
        github_api_get=github_api_get,
        download_artifact=download_artifact,
        run_docker_compose_config=run_docker_compose_config,
        work_dir=work_dir,
        git_show_bytes=git_show_bytes,
        public_candidate=public_candidate,
    )

    resolved_compose_bytes = vri.canonical_resolved_compose_bytes(materialization.resolved_compose)
    resolved_compose_digest = _sha256_bytes(resolved_compose_bytes)

    if readiness_protocol == "NEXUS-PRODUCTION-READINESS-V2":
        readiness_manifest_raw = (
            signer._read_bytes_no_follow(  # noqa: SLF001 - shared service boundary
                readiness_manifest_file, label="readiness_manifest"
            )
            if readiness_manifest_file is not None
            else None
        )
        trust_anchor_raw = frozen_trust_anchor_raw if frozen_trust_anchor_raw is not None else (
            signer._read_bytes_no_follow(  # noqa: SLF001 - shared service boundary
                trust_anchor_file, label="readiness_trust_anchor"
            )
            if trust_anchor_file is not None
            else None
        )
    else:
        readiness_manifest_raw = (
            signer._read_bytes_no_follow(  # noqa: SLF001 - même gel V1/V2
                readiness_manifest_file, label="readiness_manifest"
            )
            if readiness_manifest_file is not None
            else None
        )
        trust_anchor_raw = frozen_trust_anchor_raw if frozen_trust_anchor_raw is not None else (
            signer._read_bytes_no_follow(  # noqa: SLF001 - même gel V1/V2
                trust_anchor_file, label="readiness_trust_anchor"
            )
            if trust_anchor_file is not None
            else None
        )
    readiness_v2: ProductionReadinessManifestV2 | None = None
    if readiness_protocol == "NEXUS-PRODUCTION-READINESS-V1":
        if v2_release_material is not None:
            raise DeploymentWrapperError("V1 deployment never accepts V2 release material")
        verify_readiness_manifest_if_supplied(
            readiness_manifest_raw=readiness_manifest_raw,
            trust_anchor_raw=trust_anchor_raw,
            environment=environment,
            merge_sha=merge_sha,
            resolved_compose_digest=resolved_compose_digest,
        )
    elif readiness_protocol == "NEXUS-PRODUCTION-READINESS-V2":
        if readiness_manifest_raw is None or trust_anchor_raw is None or v2_release_material is None:
            raise DeploymentWrapperError(
                "readiness V2 requires the signed manifest, trust anchor and exact release material"
            )
        readiness_v2 = verify_readiness_manifest_v2_with_material(
            readiness_manifest_raw=readiness_manifest_raw,
            trust_anchor_raw=trust_anchor_raw,
            material=v2_release_material,
            environment=environment,
            merge_sha=merge_sha,
            resolved_compose_digest=resolved_compose_digest,
        )
        if public_candidate and readiness_v2.public_candidate_inventory_digest is None:
            raise DeploymentWrapperError("public candidate inventory is absent from signed readiness")
        if not public_candidate and readiness_v2.public_candidate_inventory_digest is not None:
            raise DeploymentWrapperError("public readiness requires the public candidate Compose protocol")
        require_runtime_images_match_readiness(readiness_v2, materialization.pinned_images)
        if readiness_v2.upstream_image_digests != signer._upstream_services_from_resolved_compose(  # noqa: SLF001
            materialization.resolved_compose,
            application_services=_runtime_application_services(readiness_v2),
        ):
            raise DeploymentWrapperError(
                "readiness V2 image inventory differs from verified provenance/Compose"
            )
        require_public_candidate_inventory_binding(
            readiness_v2, materialization.image_provenance_document
        )
    else:
        raise DeploymentWrapperError(f"unsupported readiness protocol {readiness_protocol!r}")

    _create_private_bundle_dir(bundle_dir)

    file_digests: dict[str, str] = {}

    def write_bundle_file(name: str, raw: bytes) -> None:
        _write_private_bundle_file(bundle_dir, name, raw)
        file_digests[name] = _sha256_bytes(raw)

    for name in compose_files:
        content = materialization.compose_source_bytes[name]
        write_bundle_file(name, content)

    write_bundle_file(_ENV_BUNDLE_NAME, materialization.env_bytes)

    write_bundle_file(_RESOLVED_COMPOSE_BUNDLE_NAME, resolved_compose_bytes)

    image_provenance_bytes = (
        dii.public_candidate_inventory_bytes(materialization.image_provenance_document)
        if public_candidate else _canonical_json_bytes(materialization.image_provenance_document)
    )
    write_bundle_file(_IMAGE_PROVENANCE_BUNDLE_NAME, image_provenance_bytes)

    if readiness_manifest_raw is not None:
        write_bundle_file(_READINESS_MANIFEST_BUNDLE_NAME, readiness_manifest_raw)
        assert trust_anchor_raw is not None
        write_bundle_file(_READINESS_TRUST_ANCHOR_BUNDLE_NAME, trust_anchor_raw)

    v2_release_files: dict[str, str] = {}
    v2_evidence_files: dict[str, str] = {}
    v2_source_blobs: dict[str, str] = {}
    if readiness_v2 is not None and v2_release_material is not None:
        assert trust_anchor_raw is not None  # vérifié dans la branche V2
        fixed = {
            _AUTHORIZATION_SET_BUNDLE_NAME: v2_release_material.authorization_set_raw,
            _REVOCATIONS_BUNDLE_NAME: v2_release_material.revocation_registry_raw,
            _PLACEMENT_BUNDLE_NAME: v2_release_material.release_scope_placement_raw,
            _PROFILE_MANIFEST_BUNDLE_NAME: v2_release_material.profile_manifest_raw,
            _AUTHORITY_REQUIRED_BUNDLE_NAME: "".join(
                f"{value}\n" for value in v2_release_material.authority_required_content_sha256
            ).encode(),
            _H2_COVERAGE_BUNDLE_NAME: v2_release_material.h2_coverage_raw,
            _H2_EVIDENCE_BUNDLE_NAME: v2_release_material.h2_evidence_bundle_raw,
            _PROMOTION_BUNDLE_NAME: v2_release_material.promotion_evidence_raw,
            _SEALED_MANIFEST_BUNDLE_NAME: v2_release_material.sealed_manifest_raw,
            _VERIFIED_PROFILES_BUNDLE_NAME: (
                json.dumps(
                    {
                        # Chargeur canonique. `profile_manifest_digest` est
                        # commun aux deux protocoles : ce site accepte donc un
                        # document V2 sans changer ce qu il publie.
                        "profile_manifest_digest": load_authorization_set(
                            v2_release_material.authorization_set_raw
                        ).authorization_set.profile_manifest_digest,
                        "profiles": [
                            fact.model_dump(mode="json")
                            for fact in v2_release_material.verified_profiles
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode(),
        }
        for name, raw in fixed.items():
            write_bundle_file(name, raw)
        for relative, raw in sorted(v2_release_material.release_files.items()):
            bundle_name = f"release-material/{relative}"
            write_bundle_file(bundle_name, raw)
            v2_release_files[relative] = bundle_name
        for evidence_name, raw in sorted(v2_release_material.evidence_files.items()):
            bundle_name = f"evidence/{evidence_name}.bin"
            write_bundle_file(bundle_name, raw)
            v2_evidence_files[evidence_name] = bundle_name
        for source_path, raw in sorted(v2_release_material.release_scope_source_blobs.items()):
            bundle_name = f"release-scope-sources/{source_path}"
            write_bundle_file(bundle_name, raw)
            v2_source_blobs[source_path] = bundle_name

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
        "readiness_protocol": readiness_protocol,
        "v2_release_files": v2_release_files,
        "v2_evidence_files": v2_evidence_files,
        "v2_source_blobs": v2_source_blobs,
        "v2_release_scope_git_paths": (
            dict(sorted(v2_release_material.release_scope_git_paths.items()))
            if v2_release_material is not None
            else {}
        ),
    }
    if public_candidate:
        bundle_document["public_candidate"] = True
        bundle_document["compose_files"] = list(compose_files)
    bundle_bytes = _canonical_json_bytes(bundle_document)
    bundle_document["bundle_digest"] = _sha256_bytes(bundle_bytes)
    _write_private_bundle_file(bundle_dir, _BUNDLE_MANIFEST_NAME, _canonical_json_bytes(bundle_document))
    return bundle_document


def _default_run_subprocess(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=600, check=False)


def _default_project_inventory(project: str) -> dict[str, list[str]]:
    """Inventorie aussi les conteneurs arrêtés et volumes d'une couleur."""
    commands = {
        "containers": [
            "docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"
        ],
        "networks": ["docker", "network", "ls", "--format", "{{.Name}}"],
        "volumes": ["docker", "volume", "ls", "--format", "{{.Name}}"],
    }
    inventory: dict[str, list[str]] = {}
    for kind, command in commands.items():
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeploymentWrapperError(f"Docker {kind} inventory failed") from exc
        if completed.returncode != 0:
            raise DeploymentWrapperError(f"Docker {kind} inventory failed")
        names = completed.stdout.splitlines()
        inventory[kind] = (
            names if kind == "containers" else
            [name for name in names if name.startswith(project + "_")]
        )
    return inventory


def _default_project_containers(project: str) -> list[dict[str, Any]]:
    """Inspecte les labels complets, aussi pour les conteneurs arrêtés."""
    inventory = _default_project_inventory(project)
    ids = inventory["containers"]
    if not ids:
        return []
    try:
        inspected = subprocess.run(
            ["docker", "inspect", *ids], capture_output=True, text=True,
            timeout=30, check=False,
        )
        rows = json.loads(inspected.stdout) if inspected.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise DeploymentWrapperError("Docker project identity inspection failed") from exc
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise DeploymentWrapperError("Docker project identity inspection failed")
    return [
        {"Id": row.get("Id"), "Labels": row.get("Config", {}).get("Labels")}
        if isinstance(row, dict) and isinstance(row.get("Config"), dict) else {}
        for row in rows
    ]


def _assert_go_live_ready(repo_root: Path, merge_sha: str) -> bool:
    """Relit le garde canonique sur le checkout exact, jamais son snapshot."""
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if head.returncode != 0 or head.stdout.strip() != merge_sha:
        return False
    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if status.returncode != 0 or status.stdout.strip():
        return False
    checker = subprocess.run(
        [sys.executable, str(repo_root / "scripts/go_live/check_go_live_readiness.py"),
         "--assert-ready"],
        cwd=repo_root, capture_output=True, text=True, timeout=300, check=False,
        env={**os.environ, "NEXUS_REPO_ROOT": str(repo_root)},
    )
    return checker.returncode == 0 and "GO_LIVE_READY=true" in checker.stdout.splitlines()


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
        if not isinstance(name, str):
            raise DeploymentWrapperError("bundle file name is not a string")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not name:
            raise DeploymentWrapperError(f"bundle file path is unsafe: {name!r}")
        path = bundle_dir / name
        if path.is_symlink():
            raise DeploymentWrapperError(f"bundle file {name!r} is a symlink")
        if not path.is_file():
            raise DeploymentWrapperError(f"bundle is missing file {name!r} recorded in its own manifest")
        actual_digest = _sha256_bytes(path.read_bytes())
        if actual_digest != expected_digest:
            raise DeploymentWrapperError(
                f"bundle file {name!r} has been modified since materialization "
                f"(sha256 {actual_digest} != recorded {expected_digest}) — a "
                "bundle is deployed byte-identical to what was verified, or not at all"
            )
    on_disk = {
        p.relative_to(bundle_dir).as_posix()
        for p in bundle_dir.rglob("*")
        if p.is_file() and p.name != _BUNDLE_MANIFEST_NAME
    }
    unexpected = on_disk - set(files)
    if unexpected:
        raise DeploymentWrapperError(
            f"bundle directory contains unexpected file(s) not recorded in its own "
            f"manifest: {sorted(unexpected)} — an extra critical file is never "
            "silently deployed alongside a verified bundle"
        )


def _load_and_verify_bundle_manifest(bundle_dir: Path, *, merge_sha: str) -> dict[str, Any]:
    bundle_manifest_path = bundle_dir / _BUNDLE_MANIFEST_NAME
    if bundle_manifest_path.is_symlink():
        raise DeploymentWrapperError("bundle_manifest.json is a symlink")
    if not bundle_manifest_path.is_file():
        raise DeploymentWrapperError(
            f"{bundle_manifest_path} is missing — this is not a bundle produced by "
            "materialize_verified_bundle, or it was tampered with"
        )
    raw = signer._read_bytes_no_follow(  # noqa: SLF001 - même frontière no-follow
        bundle_manifest_path, label="bundle_manifest"
    )
    try:
        bundle_document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeploymentWrapperError(f"bundle_manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(bundle_document, dict):
        raise DeploymentWrapperError("bundle_manifest.json must be a JSON object")
    if _canonical_json_bytes(bundle_document) != raw:
        raise DeploymentWrapperError("bundle_manifest.json is not canonical JSON")
    claimed_digest = bundle_document.get("bundle_digest")
    unsigned_document = dict(bundle_document)
    unsigned_document.pop("bundle_digest", None)
    actual_digest = _sha256_bytes(_canonical_json_bytes(unsigned_document))
    if claimed_digest != actual_digest:
        raise DeploymentWrapperError(
            f"bundle_manifest.json bundle_digest mismatch ({claimed_digest!r} != {actual_digest!r})"
        )
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
    if bundle_document.get("public_candidate") is True:
        if bundle_document.get("compose_files") != list(vri._PUBLIC_CANDIDATE_COMPOSE_FILES):
            raise DeploymentWrapperError("public candidate bundle Compose files differ")
        if bundle_document.get("readiness_protocol") != "NEXUS-PRODUCTION-READINESS-V2":
            raise DeploymentWrapperError("public candidate bundle requires readiness V2")
    elif "public_candidate" in bundle_document or "compose_files" in bundle_document:
        raise DeploymentWrapperError("bundle Compose mode is ambiguous")
    _require_bundle_files_match_manifest(bundle_dir, bundle_document)
    return bundle_document


def _signed_readiness_protocol(raw: bytes) -> str:
    """Inspecte le discriminant signé; chaque branche reparse ensuite strictement."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentWrapperError(f"readiness manifest is not valid JSON: {exc}") from exc
    manifest = document.get("manifest") if isinstance(document, dict) else None
    protocol = manifest.get("protocol_version") if isinstance(manifest, dict) else None
    if not isinstance(protocol, str) or protocol not in {
        "NEXUS-PRODUCTION-READINESS-V1",
        "NEXUS-PRODUCTION-READINESS-V2",
    }:
        raise DeploymentWrapperError(f"unsupported signed readiness protocol {protocol!r}")
    return protocol


@dataclass(frozen=True)
class _VerifiedDeployInputs:
    bundle_document: dict[str, Any]
    explicit_services: list[str]
    effective_compose_bytes: bytes
    authorization_set_bind_source: Path | None = None
    authorization_set_digest: str | None = None


@dataclass(frozen=True)
class _PinnedGenerationFile:
    relative_path: str
    digest: str
    device: int
    inode: int


@dataclass(frozen=True)
class _DurableAuthorizationSetGeneration:
    """Source privée adressée par contenu et identité d'inodes épinglée."""

    path: Path
    generation_directory: Path
    file_device: int
    file_inode: int
    directory_device: int
    directory_inode: int
    directory_chain: tuple[tuple[int, int], ...]
    material_root: Path | None = None
    material_root_device: int | None = None
    material_root_inode: int | None = None
    material_files: tuple[_PinnedGenerationFile, ...] = ()


def _require_trusted_ancestor(metadata: os.stat_result, *, label: str) -> None:
    deploy_uid = os.geteuid()
    if metadata.st_uid not in {0, deploy_uid}:
        raise DeploymentWrapperError(f"{label} has an untrusted owner")
    writable_by_others = metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    sticky_trusted = metadata.st_mode & stat.S_ISVTX and metadata.st_uid in {
        0,
        deploy_uid,
    }
    if writable_by_others and not sticky_trusted:
        raise DeploymentWrapperError(f"{label} is a group/world-writable ancestor")


def _open_directory_chain_no_follow(
    path: Path,
) -> tuple[int, tuple[tuple[int, int], ...]]:
    """Ouvre et épingle chaque composant sans suivre de lien."""
    absolute = Path(os.path.abspath(path))
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(absolute.anchor, flags)
    identities: list[tuple[int, int]] = []
    walked = Path(absolute.anchor)
    try:
        metadata = os.fstat(descriptor)
        _require_trusted_ancestor(metadata, label=f"deployment ancestor {walked}")
        identities.append((metadata.st_dev, metadata.st_ino))
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            walked /= part
            metadata = os.fstat(descriptor)
            _require_trusted_ancestor(metadata, label=f"deployment ancestor {walked}")
            identities.append((metadata.st_dev, metadata.st_ino))
        return descriptor, tuple(identities)
    except Exception:
        os.close(descriptor)
        raise


def _open_directory_no_follow(path: Path) -> int:
    descriptor, _identities = _open_directory_chain_no_follow(path)
    return descriptor


def _require_private_directory(descriptor: int, *, label: str) -> os.stat_result:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise DeploymentWrapperError(f"{label} is not a directory")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise DeploymentWrapperError(f"{label} must have mode 0700")
    if metadata.st_uid != os.geteuid():
        raise DeploymentWrapperError(f"{label} owner must be the effective deploy UID")
    return metadata


def _open_or_create_private_child(parent: int, name: str, *, label: str) -> tuple[int, bool]:
    created = False
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
        created = True
        os.fsync(parent)
    except FileExistsError:
        pass
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
    except OSError as exc:
        raise DeploymentWrapperError(f"{label} cannot be opened safely: {exc}") from exc
    try:
        _require_private_directory(descriptor, label=label)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor, created


def _materialize_authorization_set_generation(
    *,
    state_root: Path,
    bundle_digest: str,
    authorization_set_digest: str,
    raw: bytes,
) -> _DurableAuthorizationSetGeneration:
    """Crée sans écrasement le bind durable 0600 d'une release vérifiée."""
    for value, label in (
        (bundle_digest, "bundle digest"),
        (authorization_set_digest, "authorization set digest"),
    ):
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise DeploymentWrapperError(f"{label} is not canonical lowercase SHA-256")
    if _sha256_bytes(raw) != authorization_set_digest:
        raise DeploymentWrapperError("authorization set bytes differ from their signed digest")

    absolute_root = Path(os.path.abspath(state_root))
    if absolute_root == Path(absolute_root.anchor):
        raise DeploymentWrapperError("deployment state root cannot be a filesystem root")
    try:
        parent = _open_directory_no_follow(absolute_root.parent)
    except OSError as exc:
        raise DeploymentWrapperError(
            f"deployment state parent cannot be opened safely: {exc}"
        ) from exc
    root = generations = generation = -1
    filename = "authorization-set.json"
    generation_name = f"{bundle_digest}-{authorization_set_digest}"
    try:
        root, _ = _open_or_create_private_child(
            parent, absolute_root.name, label="deployment state root"
        )
        generations, _ = _open_or_create_private_child(
            root, "generations", label="deployment generations directory"
        )
        generation, _ = _open_or_create_private_child(
            generations,
            generation_name,
            label="deployment release generation",
        )
        generation_metadata = os.fstat(generation)
        create_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        temporary_name = f".authorization-set.{secrets.token_hex(16)}"
        file_descriptor = os.open(
            temporary_name, create_flags, 0o600, dir_fd=generation
        )
        try:
            try:
                os.fchmod(file_descriptor, 0o600)
                remaining = memoryview(raw)
                while remaining:
                    written = os.write(file_descriptor, remaining)
                    if written == 0:
                        raise DeploymentWrapperError(
                            "deployment authorization set write made no progress"
                        )
                    remaining = remaining[written:]
                os.fsync(file_descriptor)
            finally:
                os.close(file_descriptor)
        except Exception:
            os.unlink(temporary_name, dir_fd=generation)
            os.fsync(generation)
            raise
        try:
            try:
                os.link(
                    temporary_name,
                    filename,
                    src_dir_fd=generation,
                    dst_dir_fd=generation,
                    follow_symlinks=False,
                )
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary_name, dir_fd=generation)
            os.fsync(generation)

        read_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        file_descriptor = os.open(filename, read_flags, dir_fd=generation)
        try:
            file_metadata = os.fstat(file_descriptor)
            chunks: list[bytes] = []
            while chunk := os.read(file_descriptor, 1024 * 1024):
                chunks.append(chunk)
        finally:
            os.close(file_descriptor)
        if b"".join(chunks) != raw:
            raise DeploymentWrapperError(
                "existing deployment generation differs from signed authorization set"
            )
        if not stat.S_ISREG(file_metadata.st_mode):
            raise DeploymentWrapperError("deployment authorization set is not a regular file")
        if stat.S_IMODE(file_metadata.st_mode) != 0o600:
            raise DeploymentWrapperError("deployment authorization set must have mode 0600")
        if file_metadata.st_uid != os.geteuid():
            raise DeploymentWrapperError(
                "deployment authorization set owner must be the effective deploy UID"
            )
        if file_metadata.st_nlink != 1:
            raise DeploymentWrapperError(
                "deployment authorization set has a non-unique hardlink count"
            )
        generation_directory = absolute_root / "generations" / generation_name
        pinned_generation, directory_chain = _open_directory_chain_no_follow(
            generation_directory
        )
        try:
            pinned_metadata = _require_private_directory(
                pinned_generation, label="deployment release generation"
            )
        finally:
            os.close(pinned_generation)
        if (pinned_metadata.st_dev, pinned_metadata.st_ino) != (
            generation_metadata.st_dev,
            generation_metadata.st_ino,
        ):
            raise DeploymentWrapperError(
                "deployment release generation was substituted while materializing"
            )
        return _DurableAuthorizationSetGeneration(
            path=generation_directory / filename,
            generation_directory=generation_directory,
            file_device=file_metadata.st_dev,
            file_inode=file_metadata.st_ino,
            directory_device=generation_metadata.st_dev,
            directory_inode=generation_metadata.st_ino,
            directory_chain=directory_chain,
        )
    finally:
        for descriptor in (generation, generations, root, parent):
            if descriptor >= 0:
                os.close(descriptor)


def _v2_runtime_material_bundle_paths(bundle_document: dict[str, Any]) -> tuple[str, ...]:
    """Retourne l'arbre minimal exact relu par le readiness gate runtime V2."""
    fixed = {
        _BUNDLE_MANIFEST_NAME,
        "evidence/review_binding_trust_anchor.bin",
        "evidence/trusted_reviewers.bin",
        _REVOCATIONS_BUNDLE_NAME,
        _PLACEMENT_BUNDLE_NAME,
        _VERIFIED_PROFILES_BUNDLE_NAME,
        _PROFILE_MANIFEST_BUNDLE_NAME,
        _AUTHORITY_REQUIRED_BUNDLE_NAME,
        _H2_COVERAGE_BUNDLE_NAME,
        _H2_EVIDENCE_BUNDLE_NAME,
        _PROMOTION_BUNDLE_NAME,
        _SEALED_MANIFEST_BUNDLE_NAME,
    }
    for field in ("v2_release_files", "v2_evidence_files", "v2_source_blobs"):
        mapping = bundle_document.get(field)
        if not isinstance(mapping, dict) or not mapping:
            raise DeploymentWrapperError(f"V2 bundle has no exact {field!r} mapping")
        for value in mapping.values():
            if not isinstance(value, str):
                raise DeploymentWrapperError(f"V2 bundle {field!r} path is not a string")
            fixed.add(value)
    for name in fixed:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or not name:
            raise DeploymentWrapperError(f"V2 runtime material path is unsafe: {name!r}")
    return tuple(sorted(fixed))


def _publish_private_generation_file(
    *, directory: int, staging_directory: int, filename: str, raw: bytes, label: str
) -> os.stat_result:
    """Publie une cible complète sans écrasement, puis relit les octets publiés."""
    create_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    temporary_name = f".{filename}.{secrets.token_hex(16)}"
    descriptor = os.open(temporary_name, create_flags, 0o600, dir_fd=staging_directory)
    try:
        try:
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(raw)
            while remaining:
                written = os.write(descriptor, remaining)
                if written == 0:
                    raise DeploymentWrapperError(f"{label} write made no progress")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        os.unlink(temporary_name, dir_fd=staging_directory)
        os.fsync(staging_directory)
        raise
    try:
        try:
            os.link(
                temporary_name,
                filename,
                src_dir_fd=staging_directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary_name, dir_fd=staging_directory)
        os.fsync(staging_directory)
        os.fsync(directory)

    read_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(filename, read_flags, dir_fd=directory)
    try:
        metadata = os.fstat(descriptor)
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    if b"".join(chunks) != raw:
        raise DeploymentWrapperError(f"existing {label} differs from verified bundle bytes")
    if not stat.S_ISREG(metadata.st_mode):
        raise DeploymentWrapperError(f"{label} is not a regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise DeploymentWrapperError(f"{label} must have mode 0600")
    if metadata.st_uid != os.geteuid():
        raise DeploymentWrapperError(f"{label} owner must be the effective deploy UID")
    if metadata.st_nlink != 1:
        raise DeploymentWrapperError(f"{label} has a non-unique hardlink count")
    return metadata


def _materialize_v2_release_generation(
    *,
    state_root: Path,
    bundle_dir: Path,
    bundle_document: dict[str, Any],
    authorization_set_digest: str,
    authorization_set_raw: bytes,
) -> _DurableAuthorizationSetGeneration:
    """Fige le set et tout l'arbre runtime V2 dans une même génération privée."""
    _dotenv_path_value(Path(os.path.abspath(state_root)), label="deployment state root")
    generation = _materialize_authorization_set_generation(
        state_root=state_root,
        bundle_digest=str(bundle_document["bundle_digest"]),
        authorization_set_digest=authorization_set_digest,
        raw=authorization_set_raw,
    )
    runtime_paths = _v2_runtime_material_bundle_paths(bundle_document)
    raw_files: dict[str, bytes] = {}
    file_digests = bundle_document.get("files")
    assert isinstance(file_digests, dict)
    for name in runtime_paths:
        raw = signer._read_bytes_no_follow(bundle_dir / name, label=f"bundle:{name}")  # noqa: SLF001
        if name == _BUNDLE_MANIFEST_NAME:
            expected = _sha256_bytes(_canonical_json_bytes(bundle_document))
        else:
            claimed = file_digests.get(name)
            if not isinstance(claimed, str):
                raise DeploymentWrapperError(
                    f"V2 release material {name!r} has no recorded bundle digest"
                )
            expected = claimed
        if _sha256_bytes(raw) != expected:
            raise DeploymentWrapperError(
                f"V2 release material {name!r} changed before durable publication"
            )
        raw_files[name] = raw

    generation_fd, chain = _open_directory_chain_no_follow(generation.generation_directory)
    material_fd = -1
    try:
        generation_metadata = _require_private_directory(
            generation_fd, label="deployment release generation"
        )
        if chain != generation.directory_chain or (
            generation_metadata.st_dev,
            generation_metadata.st_ino,
        ) != (generation.directory_device, generation.directory_inode):
            raise DeploymentWrapperError("deployment generation path was substituted")
        material_fd, _ = _open_or_create_private_child(
            generation_fd, "v2-material", label="deployment V2 release material root"
        )
        material_metadata = _require_private_directory(
            material_fd, label="deployment V2 release material root"
        )
        pinned: list[_PinnedGenerationFile] = []
        for name, raw in sorted(raw_files.items()):
            relative = PurePosixPath(name)
            parent_fd = os.dup(material_fd)
            try:
                for part in relative.parts[:-1]:
                    child_fd, _ = _open_or_create_private_child(
                        parent_fd,
                        part,
                        label=f"deployment V2 material directory {part!r}",
                    )
                    os.close(parent_fd)
                    parent_fd = child_fd
                metadata = _publish_private_generation_file(
                    directory=parent_fd,
                    staging_directory=generation_fd,
                    filename=relative.name,
                    raw=raw,
                    label=f"deployment V2 release material {name!r}",
                )
            finally:
                os.close(parent_fd)
            pinned.append(
                _PinnedGenerationFile(
                    relative_path=name,
                    digest=_sha256_bytes(raw),
                    device=metadata.st_dev,
                    inode=metadata.st_ino,
                )
            )
    finally:
        if material_fd >= 0:
            os.close(material_fd)
        os.close(generation_fd)
    return dataclasses.replace(
        generation,
        material_root=generation.generation_directory / "v2-material",
        material_root_device=material_metadata.st_dev,
        material_root_inode=material_metadata.st_ino,
        material_files=tuple(pinned),
    )


def _require_generation_identity(generation: _DurableAuthorizationSetGeneration) -> None:
    """Revalide la chaîne et les inodes épinglés avant chaque mutation Docker."""
    try:
        directory, current_chain = _open_directory_chain_no_follow(
            generation.generation_directory
        )
        metadata = _require_private_directory(
            directory, label="deployment release generation"
        )
        if current_chain != generation.directory_chain or (
            metadata.st_dev,
            metadata.st_ino,
        ) != (generation.directory_device, generation.directory_inode):
            raise DeploymentWrapperError("deployment generation path was substituted")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(generation.path.name, flags, dir_fd=directory)
        try:
            file_metadata = os.fstat(file_descriptor)
        finally:
            os.close(file_descriptor)
    except OSError as exc:
        raise DeploymentWrapperError(
            f"deployment generation identity cannot be reverified: {exc}"
        ) from exc
    finally:
        if "directory" in locals():
            os.close(directory)
    if not stat.S_ISREG(file_metadata.st_mode):
        raise DeploymentWrapperError("deployment authorization set is not a regular file")
    if stat.S_IMODE(file_metadata.st_mode) != 0o600:
        raise DeploymentWrapperError("deployment authorization set must have mode 0600")
    if file_metadata.st_uid != os.geteuid():
        raise DeploymentWrapperError(
            "deployment authorization set owner must be the effective deploy UID"
        )
    if file_metadata.st_nlink != 1:
        raise DeploymentWrapperError(
            "deployment authorization set has a non-unique hardlink count"
        )
    if (file_metadata.st_dev, file_metadata.st_ino) != (
        generation.file_device,
        generation.file_inode,
    ):
        raise DeploymentWrapperError("deployment authorization set path was substituted")
    if generation.material_root is None:
        return
    try:
        material_root_fd, _material_chain = _open_directory_chain_no_follow(
            generation.material_root
        )
        material_metadata = _require_private_directory(
            material_root_fd, label="deployment V2 release material root"
        )
        if (material_metadata.st_dev, material_metadata.st_ino) != (
            generation.material_root_device,
            generation.material_root_inode,
        ):
            raise DeploymentWrapperError("deployment V2 release material root was substituted")
        expected_inventory = {item.relative_path for item in generation.material_files}
        expected_directories = {
            PurePosixPath(*PurePosixPath(path).parts[:index]).as_posix()
            for path in expected_inventory
            for index in range(1, len(PurePosixPath(path).parts))
        }
        actual_inventory: set[str] = set()
        actual_directories: set[str] = set()

        def walk(directory_fd: int, prefix: PurePosixPath) -> None:
            with os.scandir(directory_fd) as entries:
                for entry in entries:
                    relative = prefix / entry.name
                    if entry.is_symlink():
                        raise DeploymentWrapperError(
                            f"deployment V2 release material {relative.as_posix()!r} changed"
                        )
                    if entry.is_dir(follow_symlinks=False):
                        actual_directories.add(relative.as_posix())
                        flags = (
                            os.O_RDONLY
                            | getattr(os, "O_CLOEXEC", 0)
                            | getattr(os, "O_DIRECTORY", 0)
                            | getattr(os, "O_NOFOLLOW", 0)
                        )
                        child = os.open(entry.name, flags, dir_fd=directory_fd)
                        try:
                            _require_private_directory(
                                child,
                                label=(
                                    "deployment V2 material directory "
                                    f"{relative.as_posix()!r}"
                                ),
                            )
                            walk(child, relative)
                        finally:
                            os.close(child)
                    elif entry.is_file(follow_symlinks=False):
                        actual_inventory.add(relative.as_posix())
                    else:
                        raise DeploymentWrapperError(
                            f"deployment V2 release material {relative.as_posix()!r} changed"
                        )

        walk(material_root_fd, PurePosixPath())
        if actual_inventory != expected_inventory:
            raise DeploymentWrapperError(
                "deployment V2 release material inventory changed "
                f"(missing={sorted(expected_inventory - actual_inventory)!r}, "
                f"extra={sorted(actual_inventory - expected_inventory)!r})"
            )
        if actual_directories != expected_directories:
            raise DeploymentWrapperError(
                "deployment V2 release material directory inventory changed "
                f"(missing={sorted(expected_directories - actual_directories)!r}, "
                f"extra={sorted(actual_directories - expected_directories)!r})"
            )
        for pinned in generation.material_files:
            relative = PurePosixPath(pinned.relative_path)
            parent_fd = os.dup(material_root_fd)
            try:
                for part in relative.parts[:-1]:
                    flags = (
                        os.O_RDONLY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0)
                    )
                    child_fd = os.open(part, flags, dir_fd=parent_fd)
                    os.close(parent_fd)
                    parent_fd = child_fd
                    _require_private_directory(
                        parent_fd,
                        label=f"deployment V2 material directory {part!r}",
                    )
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                descriptor = os.open(relative.name, flags, dir_fd=parent_fd)
                try:
                    metadata = os.fstat(descriptor)
                    chunks: list[bytes] = []
                    while chunk := os.read(descriptor, 1024 * 1024):
                        chunks.append(chunk)
                finally:
                    os.close(descriptor)
            finally:
                os.close(parent_fd)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()
                or metadata.st_nlink != 1
                or (metadata.st_dev, metadata.st_ino) != (pinned.device, pinned.inode)
                or _sha256_bytes(b"".join(chunks)) != pinned.digest
            ):
                raise DeploymentWrapperError(
                    f"deployment V2 release material {pinned.relative_path!r} changed"
                )
    except OSError as exc:
        raise DeploymentWrapperError(
            f"deployment V2 release material changed or cannot be reverified: {exc}"
        ) from exc
    finally:
        if "material_root_fd" in locals():
            os.close(material_root_fd)


def _dotenv_path_value(path: Path, *, label: str) -> bytes:
    raw = str(path).encode("utf-8")
    if any(marker in raw for marker in (b"\x00", b"\r", b"\n")):
        raise DeploymentWrapperError(f"{label} cannot contain NUL, CR or LF")
    return raw


def require_effective_authorization_set_bind(
    *, effective_compose: dict[str, Any], expected_digest: str
) -> Path:
    """Vérifie le bind réellement résolu, pas seulement le bundle.

    Les deux workers doivent partager un unique fichier régulier, absolu,
    monté en lecture seule au chemin runtime canonique. Chaque composant du
    chemin est refusé s'il est un symlink, puis les octets sont ouverts avec
    ``O_NOFOLLOW`` par la primitive du signer et rehashés.
    """
    services = effective_compose.get("services")
    if not isinstance(services, dict):
        raise DeploymentWrapperError("effective compose has no services")
    sources: list[Path] = []
    for service_name in (
        "multilevel-worker-a-production",
        "multilevel-worker-b-production",
    ):
        service = services.get(service_name)
        if not isinstance(service, dict):
            raise DeploymentWrapperError(
                f"effective compose is missing production service {service_name!r}"
            )
        volumes = service.get("volumes")
        if not isinstance(volumes, list):
            raise DeploymentWrapperError(
                f"{service_name} has no resolved authorization set bind"
            )
        matches = [
            volume
            for volume in volumes
            if isinstance(volume, dict)
            and volume.get("target") == "/app/production/authorization-set.json"
        ]
        if len(matches) != 1:
            raise DeploymentWrapperError(
                f"{service_name} must have exactly one authorization set bind"
            )
        volume = matches[0]
        if volume.get("type") != "bind" or volume.get("read_only") is not True:
            raise DeploymentWrapperError(
                f"{service_name} authorization set bind must be a read-only bind"
            )
        source_raw = volume.get("source")
        if not isinstance(source_raw, str) or not source_raw:
            raise DeploymentWrapperError(
                f"{service_name} authorization set bind source is missing"
            )
        source = Path(source_raw)
        if not source.is_absolute():
            raise DeploymentWrapperError(
                "effective authorization set bind source must be absolute"
            )
        walked = Path(source.anchor)
        for part in source.parts[1:]:
            walked /= part
            if walked.is_symlink():
                raise DeploymentWrapperError(
                    f"effective authorization set bind source {walked} is a symlink"
                )
        sources.append(source)
    if sources[0] != sources[1]:
        raise DeploymentWrapperError(
            "production workers resolve different authorization set bind sources"
        )
    source = sources[0]
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise DeploymentWrapperError(
                    "effective authorization set bind source is not a regular file"
                )
            if before.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise DeploymentWrapperError(
                    "effective authorization set bind source is group/world-writable"
                )
            if before.st_nlink != 1:
                raise DeploymentWrapperError(
                    "effective authorization set bind source has a non-unique hardlink count"
                )
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        path_after = os.stat(source, follow_symlinks=False)
    except OSError as exc:
        raise DeploymentWrapperError(
            f"effective authorization set bind cannot be frozen safely: {exc}"
        ) from exc
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise DeploymentWrapperError(
            "effective authorization set bind mutated while it was read"
        )
    if (before.st_dev, before.st_ino) != (path_after.st_dev, path_after.st_ino):
        raise DeploymentWrapperError(
            "effective authorization set bind path was substituted while it was read"
        )
    raw = b"".join(chunks)
    actual = _sha256_bytes(raw)
    if actual != expected_digest:
        raise DeploymentWrapperError(
            "effective authorization set bind digest differs from signed readiness "
            f"({actual} != {expected_digest})"
        )
    return source.resolve(strict=True)


def require_effective_v2_material_bind(*, effective_compose: dict[str, Any]) -> Path:
    """Exige le répertoire runtime V2 unique, absolu et monté en lecture seule."""
    services = effective_compose.get("services")
    if not isinstance(services, dict):
        raise DeploymentWrapperError("effective compose has no services")
    sources: list[Path] = []
    for service_name in (
        "multilevel-worker-a-production",
        "multilevel-worker-b-production",
    ):
        service = services.get(service_name)
        volumes = service.get("volumes") if isinstance(service, dict) else None
        if not isinstance(volumes, list):
            raise DeploymentWrapperError(f"{service_name} has no resolved V2 material bind")
        matches = [
            volume
            for volume in volumes
            if isinstance(volume, dict)
            and volume.get("target") == "/app/production/v2-material"
        ]
        if len(matches) != 1:
            raise DeploymentWrapperError(
                f"{service_name} must have exactly one V2 release material bind"
            )
        nested_targets = [
            volume.get("target")
            for volume in volumes
            if isinstance(volume, dict)
            and isinstance(volume.get("target"), str)
            and volume.get("target").startswith("/app/production/v2-material/")
        ]
        if nested_targets:
            raise DeploymentWrapperError(
                f"{service_name} has a bind masking V2 release material: "
                f"{sorted(nested_targets)!r}"
            )
        volume = matches[0]
        if volume.get("type") != "bind" or volume.get("read_only") is not True:
            raise DeploymentWrapperError(
                f"{service_name} V2 release material bind must be a read-only bind"
            )
        source_raw = volume.get("source")
        if not isinstance(source_raw, str) or not source_raw:
            raise DeploymentWrapperError(
                f"{service_name} V2 release material bind source is missing"
            )
        source = Path(source_raw)
        if not source.is_absolute():
            raise DeploymentWrapperError("effective V2 release material bind source must be absolute")
        try:
            descriptor, _chain = _open_directory_chain_no_follow(source)
            try:
                _require_private_directory(
                    descriptor, label="effective V2 release material bind source"
                )
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise DeploymentWrapperError(
                f"effective V2 release material bind cannot be frozen safely: {exc}"
            ) from exc
        sources.append(source)
    if sources[0] != sources[1]:
        raise DeploymentWrapperError(
            "production workers resolve different V2 release material bind sources"
        )
    return sources[0].resolve(strict=True)


def _load_v2_release_material_from_bundle(
    bundle_dir: Path, bundle_document: dict[str, Any]
) -> signer.V2ReleaseMaterial:
    release_map = bundle_document.get("v2_release_files")
    evidence_map = bundle_document.get("v2_evidence_files")
    source_blob_map = bundle_document.get("v2_source_blobs")
    release_scope_git_paths = bundle_document.get("v2_release_scope_git_paths")
    if not isinstance(release_map, dict) or not release_map:
        raise DeploymentWrapperError("V2 bundle has no exact release member mapping")
    if not isinstance(evidence_map, dict) or not evidence_map:
        raise DeploymentWrapperError("V2 bundle has no exact evidence mapping")
    if not isinstance(source_blob_map, dict) or not source_blob_map:
        raise DeploymentWrapperError("V2 bundle has no exact-tree source blob mapping")
    if (
        not isinstance(release_scope_git_paths, dict)
        or set(release_scope_git_paths) != signer._RELEASE_SCOPE_GIT_PATH_KEYS  # noqa: SLF001
        or any(not isinstance(value, str) for value in release_scope_git_paths.values())
    ):
        raise DeploymentWrapperError("V2 bundle has no exact release scope path roles")

    def read(name: str) -> bytes:
        path = bundle_dir / name
        if not path.is_file():
            raise DeploymentWrapperError(f"V2 bundle is missing {name!r}")
        return signer._read_bytes_no_follow(path, label=f"bundle:{name}")  # noqa: SLF001

    authorization_set_raw = read(_AUTHORIZATION_SET_BUNDLE_NAME)
    h2_coverage_raw = read(_H2_COVERAGE_BUNDLE_NAME)
    try:
        authorization_set = load_authorization_set(
            authorization_set_raw
        ).authorization_set
        h2_coverage = signer.parse_h2_coverage_evidence_v2(h2_coverage_raw)
    except (signer.AuthorizationSetError, signer.H2CoverageEvidenceError) as exc:
        raise DeploymentWrapperError(f"V2 bundle mappings cannot be derived: {exc}") from exc
    expected_release_paths = {
        relative
        for member in authorization_set.members
        for relative in (member.authorization_path, member.review_binding_path)
    }
    expected_release_map = {
        relative: f"release-material/{relative}" for relative in expected_release_paths
    }
    expected_evidence_map = {
        name: f"evidence/{name}.bin" for name in h2_coverage.input_file_digests
    }
    expected_source_blob_map = {
        path: f"release-scope-sources/{path}"
        for path in h2_coverage.release_scope_source_blob_digests
    }
    if release_map != expected_release_map:
        raise DeploymentWrapperError("V2 release member mapping is not derived from authorization set")
    if evidence_map != expected_evidence_map:
        raise DeploymentWrapperError("V2 evidence mapping is not derived from H2 coverage")
    if source_blob_map != expected_source_blob_map:
        raise DeploymentWrapperError("V2 source mapping is not derived from H2 coverage")

    try:
        profiles = signer._parse_verified_profiles(  # noqa: SLF001 - même boundary CLI
            read(_VERIFIED_PROFILES_BUNDLE_NAME)
        )
        required = signer._parse_authority_required(  # noqa: SLF001 - même boundary CLI
            read(_AUTHORITY_REQUIRED_BUNDLE_NAME)
        )
    except signer.SigningToolError as exc:
        raise DeploymentWrapperError(f"V2 bundle facts rejected: {exc}") from exc
    return signer.V2ReleaseMaterial(
        authorization_set_raw=authorization_set_raw,
        release_files={str(key): read(str(value)) for key, value in release_map.items()},
        review_binding_trust_anchor_raw=read("evidence/review_binding_trust_anchor.bin"),
        trusted_reviewers_raw=read("evidence/trusted_reviewers.bin"),
        revocation_registry_raw=read(_REVOCATIONS_BUNDLE_NAME),
        release_scope_placement_raw=read(_PLACEMENT_BUNDLE_NAME),
        release_scope_source_blobs={
            str(key): read(str(value)) for key, value in source_blob_map.items()
        },
        verified_profiles=profiles,
        profile_manifest_raw=read(_PROFILE_MANIFEST_BUNDLE_NAME),
        authority_required_content_sha256=required,
        h2_coverage_raw=h2_coverage_raw,
        h2_evidence_bundle_raw=read(_H2_EVIDENCE_BUNDLE_NAME),
        promotion_evidence_raw=read(_PROMOTION_BUNDLE_NAME),
        evidence_files={str(key): read(str(value)) for key, value in evidence_map.items()},
        sealed_manifest_raw=read(_SEALED_MANIFEST_BUNDLE_NAME),
        now=datetime.now(UTC),
        merge_sha=str(bundle_document["merge_sha"]),
        merge_tree_sha=str(bundle_document["merge_tree_sha"]),
        release_scope_git_paths={
            str(key): str(value) for key, value in release_scope_git_paths.items()
        },
    )


def _verify_deploy_inputs(
    *,
    bundle_dir: Path,
    merge_sha: str,
    execute: bool,
    trusted_readiness_anchor_raw: bytes | None,
    run_bundle_compose_config: RunBundleComposeConfig,
) -> _VerifiedDeployInputs:
    bundle_document = _load_and_verify_bundle_manifest(bundle_dir, merge_sha=merge_sha)
    public_candidate = bundle_document.get("public_candidate") is True
    compose_files = (
        vri._PUBLIC_CANDIDATE_COMPOSE_FILES if public_candidate else _CANONICAL_COMPOSE_FILES
    )
    readiness_path = bundle_dir / _READINESS_MANIFEST_BUNDLE_NAME
    readiness_raw = (
        signer._read_bytes_no_follow(readiness_path, label="readiness_manifest")  # noqa: SLF001
        if readiness_path.is_file()
        else None
    )
    if readiness_raw is None:
        if public_candidate:
            raise DeploymentWrapperError("public candidate requires signed readiness V2")
        if execute:
            raise DeploymentWrapperError("a signed readiness manifest is required before mutation")
        explicit = bundle_document.get("explicit_services")
        if not isinstance(explicit, list) or not explicit:
            raise DeploymentWrapperError("bundle manifest has no explicit_services")
        stored = signer._read_bytes_no_follow(  # noqa: SLF001
            bundle_dir / _RESOLVED_COMPOSE_BUNDLE_NAME, label="resolved_compose"
        )
        return _VerifiedDeployInputs(bundle_document, explicit, stored)
    if trusted_readiness_anchor_raw is None:
        raise DeploymentWrapperError("trusted readiness anchor bytes are required")

    actual_protocol = _signed_readiness_protocol(readiness_raw)
    if bundle_document.get("readiness_protocol") != actual_protocol:
        raise DeploymentWrapperError(
            "bundle readiness protocol does not match the signed readiness protocol"
        )

    effective = run_bundle_compose_config(
        bundle_dir, bundle_dir / _ENV_BUNDLE_NAME, compose_files
    )
    effective_bytes = vri.canonical_resolved_compose_bytes(effective)
    stored_bytes = signer._read_bytes_no_follow(  # noqa: SLF001
        bundle_dir / _RESOLVED_COMPOSE_BUNDLE_NAME, label="resolved_compose"
    )
    if effective_bytes != stored_bytes:
        raise DeploymentWrapperError(
            "effective compose differs from the signed/materialized resolved compose"
        )
    compose_digest = _sha256_bytes(effective_bytes)
    manifest: ProductionReadinessManifestV1 | ProductionReadinessManifestV2
    if actual_protocol == "NEXUS-PRODUCTION-READINESS-V1":
        if public_candidate:
            raise DeploymentWrapperError("public candidate requires signed readiness V2")
        manifest_v1 = verify_readiness_manifest_if_supplied(
            readiness_manifest_raw=readiness_raw,
            trust_anchor_raw=trusted_readiness_anchor_raw,
            environment="production",
            merge_sha=merge_sha,
            resolved_compose_digest=compose_digest,
        )
        if manifest_v1 is None:
            raise DeploymentWrapperError("signed V1 readiness is missing")
        manifest = manifest_v1
    elif actual_protocol == "NEXUS-PRODUCTION-READINESS-V2":
        manifest_v2 = verify_readiness_manifest_v2_with_material(
            readiness_manifest_raw=readiness_raw,
            trust_anchor_raw=trusted_readiness_anchor_raw,
            material=_load_v2_release_material_from_bundle(bundle_dir, bundle_document),
            environment="production",
            merge_sha=merge_sha,
            resolved_compose_digest=compose_digest,
        )
        manifest = manifest_v2
        if public_candidate != (manifest_v2.public_candidate_inventory_digest is not None):
            raise DeploymentWrapperError("public candidate bundle and signed inventory mode differ")
        if manifest_v2.public_candidate_inventory_digest is not None:
            try:
                inventory_raw = signer._read_bytes_no_follow(  # noqa: SLF001 - octets du bundle gelé
                    bundle_dir / _IMAGE_PROVENANCE_BUNDLE_NAME,
                    label="bundle:image_provenance",
                )
                inventory_document = json.loads(inventory_raw)
            except (UnicodeDecodeError, json.JSONDecodeError, signer.SigningToolError) as exc:
                raise DeploymentWrapperError(
                    f"public candidate inventory bundle cannot be read: {exc}"
                ) from exc
            if not isinstance(inventory_document, dict):
                raise DeploymentWrapperError("public candidate inventory bundle is not an object")
            if inventory_raw != dii.public_candidate_inventory_bytes(inventory_document):
                raise DeploymentWrapperError("public candidate inventory bundle is not canonical")
            require_public_candidate_inventory_binding(manifest_v2, inventory_document)
    else:  # pragma: no cover - exhaustivité imposée par _signed_readiness_protocol
        raise DeploymentWrapperError(f"unsupported signed readiness protocol {actual_protocol!r}")

    if bundle_document.get("readiness_manifest_included") is not True:
        raise DeploymentWrapperError("bundle readiness presence flag contradicts signed bytes")
    if bundle_document.get("merge_tree_sha") != manifest.merge_tree_sha:
        raise DeploymentWrapperError("bundle merge_tree_sha differs from signed readiness")

    services = effective.get("services")
    if not isinstance(services, dict) or not services:
        raise DeploymentWrapperError("effective compose has no services")
    explicit_services = sorted(services)
    if public_candidate and set(explicit_services) != vri._PUBLIC_CANDIDATE_SERVICES:
        raise DeploymentWrapperError("public candidate effective Compose services differ")
    if bundle_document.get("explicit_services") != explicit_services:
        raise DeploymentWrapperError("bundle explicit_services differ from effective compose")
    verified_images = bundle_document.get("verified_images")
    if not isinstance(verified_images, dict):
        raise DeploymentWrapperError("bundle verified_images is not a mapping")
    require_runtime_images_match_readiness(manifest, verified_images)
    if signer._upstream_services_from_resolved_compose(  # noqa: SLF001
        effective, application_services=_runtime_application_services(manifest)
    ) != (
        manifest.upstream_image_digests
    ):
        raise DeploymentWrapperError("effective upstream images differ from signed readiness")
    authorization_source = None
    authorization_digest = None
    if isinstance(manifest, ProductionReadinessManifestV2) and not public_candidate:
        authorization_digest = manifest.authorization_set_digest
        authorization_source = require_effective_authorization_set_bind(
            effective_compose=effective,
            expected_digest=authorization_digest,
        )
    return _VerifiedDeployInputs(
        bundle_document,
        explicit_services,
        effective_bytes,
        authorization_source,
        authorization_digest,
    )


def _public_compose_args(bundle_dir: Path, project: str) -> list[str]:
    command = [
        "docker", "compose", "--project-name", project,
        "--project-directory", str(bundle_dir),
        "--env-file", str(bundle_dir / _ENV_BUNDLE_NAME),
    ]
    for name in vri._PUBLIC_CANDIDATE_COMPOSE_FILES:
        command.extend(("-f", str(bundle_dir / name)))
    return command


def _require_empty_public_project(project: str, inventory: ProjectInventory) -> None:
    observed = inventory(project)
    if set(observed) != {"containers", "networks", "volumes"} or any(
        not isinstance(observed[kind], list) for kind in observed
    ):
        raise DeploymentWrapperError("public candidate project inventory is incomplete")
    if any(observed.values()):
        raise DeploymentWrapperError("pre-existing resources in candidate project")


def _require_host_local_docker_daemon() -> bool:
    """Refuse un proxy/daemon distant ou un namespace distinct du daemon local."""
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        return False
    try:
        context = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        endpoint = json.loads(context.stdout) if context.returncode == 0 else None
        if endpoint not in {"unix:///var/run/docker.sock", "unix:///run/docker.sock"}:
            return False
        socket_path = endpoint.removeprefix("unix://")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer_socket:
            peer_socket.settimeout(2)
            peer_socket.connect(socket_path)
            peer_pid, _uid, _gid = struct.unpack(
                "3i", peer_socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
        peer_comm = (Path("/proc") / str(peer_pid) / "comm").read_text(
            encoding="ascii"
        ).strip()
        daemon_pid = peer_pid
        if peer_comm == "systemd" and peer_pid == 1:
            unit = subprocess.run(
                ["systemctl", "show", "docker.socket", "-p", "ActiveState",
                 "-p", "Listen", "-p", "Triggers", "--no-pager"],
                capture_output=True, text=True, timeout=30, check=False,
            )
            fields = dict(line.split("=", 1) for line in unit.stdout.splitlines() if "=" in line)
            if (unit.returncode != 0 or fields.get("ActiveState") != "active"
                    or fields.get("Triggers") != "docker.service"
                    or str(Path(socket_path).resolve()) not in fields.get("Listen", "")):
                return False
            service = subprocess.run(
                ["systemctl", "show", "docker.service", "-p", "MainPID",
                 "-p", "ActiveState", "--no-pager"],
                capture_output=True, text=True, timeout=30, check=False,
            )
            fields = dict(line.split("=", 1) for line in service.stdout.splitlines() if "=" in line)
            if (service.returncode != 0 or fields.get("ActiveState") != "active"
                    or not fields.get("MainPID", "").isdecimal()):
                return False
            daemon_pid = int(fields["MainPID"])
        elif peer_comm != "dockerd":
            return False
        if daemon_pid < 2 or (Path("/proc") / str(daemon_pid) / "comm").read_text(
            encoding="ascii"
        ).strip() != "dockerd":
            return False
        own_net = os.stat("/proc/self/net/dev")
        daemon_net = os.stat(f"/proc/{daemon_pid}/net/dev")
        return (own_net.st_dev, own_net.st_ino) == (daemon_net.st_dev, daemon_net.st_ino)
    except (OSError, UnicodeError, subprocess.SubprocessError, json.JSONDecodeError,
            ValueError, struct.error):
        return False


@contextlib.contextmanager
def _public_color_lock(
    state_root: Path | None, color: str, host_local_guard: HostLocalGuard,
) -> Iterator[int]:
    """Verrou canonique de couleur dans le namespace réseau du daemon local."""
    if state_root is None or color not in {"blue", "green"}:
        raise DeploymentWrapperError("public candidate requires a stable deployment state root")
    if host_local_guard() is not True:
        raise DeploymentWrapperError("public candidate requires host-local Docker namespace")
    absolute = Path(os.path.abspath(state_root))
    if absolute == Path(absolute.anchor):
        raise DeploymentWrapperError("deployment state root cannot be filesystem root")
    global_lock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        global_lock.bind(f"\0nexus-rag-public-{color}-deployment-v1")
    except OSError as exc:
        global_lock.close()
        raise DeploymentWrapperError("public candidate color lock is busy or unavailable") from exc
    try:
        parent = _open_directory_no_follow(absolute.parent)
    except OSError as exc:
        global_lock.close()
        raise DeploymentWrapperError("deployment state parent cannot be opened safely") from exc
    root = lock = -1
    try:
        root, _ = _open_or_create_private_child(
            parent, absolute.name, label="deployment state root"
        )
        lock = os.open(
            f"public-{color}.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600, dir_fd=root,
        )
        metadata = os.fstat(lock)
        if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid() or metadata.st_nlink != 1):
            raise DeploymentWrapperError("public candidate lock identity is unsafe")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeploymentWrapperError("public candidate color lock is busy") from exc
        yield root
    finally:
        if lock >= 0:
            os.close(lock)
        if root >= 0:
            os.close(root)
        os.close(parent)
        global_lock.close()


def _public_state_name(color: str) -> str:
    return f"public-{color}.json"


def _read_public_state(root: int, color: str) -> dict[str, Any] | None:
    try:
        fd = os.open(
            _public_state_name(color),
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=root,
        )
    except FileNotFoundError:
        return None
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid() or metadata.st_nlink != 1
                or metadata.st_size > 16384):
            raise DeploymentWrapperError("public generation state identity is unsafe")
        raw = os.read(fd, 16385)
        document = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentWrapperError("public generation state cannot be read") from exc
    finally:
        os.close(fd)
    if not isinstance(document, dict):
        raise DeploymentWrapperError("public generation state is invalid")
    return document


def _write_public_state(root: int, color: str, document: dict[str, Any]) -> None:
    if _read_public_state(root, color) is not None:
        raise DeploymentWrapperError("public generation state already exists")
    raw = _canonical_json_bytes(document)
    temp = f".public-{color}.{secrets.token_hex(16)}"
    fd = os.open(
        temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        0o600, dir_fd=root,
    )
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(fd, remaining)
            if written == 0:
                raise DeploymentWrapperError("public generation state write made no progress")
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(temp, _public_state_name(color), src_dir_fd=root, dst_dir_fd=root,
                follow_symlinks=False)
        os.fsync(root)
    finally:
        os.unlink(temp, dir_fd=root)


def _owned_public_container_ids(
    *, project: str, bundle_dir: Path, containers: ProjectContainers,
    require_all_services: bool,
) -> list[str]:
    rows = containers(project)
    if not isinstance(rows, list) or not rows:
        raise DeploymentWrapperError("public candidate container ownership is ambiguous")
    expected_files = {
        str(bundle_dir / name) for name in vri._PUBLIC_CANDIDATE_COMPOSE_FILES
    }
    ids: list[str] = []
    services: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("Labels"), dict):
            raise DeploymentWrapperError("public candidate container identity is ambiguous")
        labels = row["Labels"]
        service = labels.get("com.docker.compose.service")
        container_id = row.get("Id")
        files = labels.get("com.docker.compose.project.config_files")
        if (not isinstance(container_id, str) or not container_id
                or labels.get("com.docker.compose.project") != project
                or service not in vri._PUBLIC_CANDIDATE_SERVICES
                or service in services
                or labels.get("com.docker.compose.project.working_dir") != str(bundle_dir)
                or not isinstance(files, str)
                or set(files.split(",")) != expected_files):
            raise DeploymentWrapperError("public candidate container ownership is ambiguous")
        ids.append(container_id)
        services.add(service)
    if require_all_services and services != vri._PUBLIC_CANDIDATE_SERVICES:
        raise DeploymentWrapperError("public candidate five-service identity is incomplete")
    return sorted(ids)


def _prometheus_port(verified: _VerifiedDeployInputs) -> int:
    try:
        effective = json.loads(verified.effective_compose_bytes)
        port = int(effective["services"]["prometheus"]["ports"][0]["published"])
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise DeploymentWrapperError("public Prometheus port is unavailable") from exc
    if not 1 <= port <= 65535:
        raise DeploymentWrapperError("public Prometheus port is invalid")
    return port


def _default_public_prometheus_probe(port: int) -> bool:
    """Exige readiness, alertes chargées et collecte effective de l'API."""
    base = f"http://127.0.0.1:{port}"
    # Trois intervalles de collecte de 30 s : un premier scrape peut arriver
    # juste après le délai de 30 s sans signaler de panne de l'API.
    deadline = time.monotonic() + 90
    expected = {
        "RAGRetrievalMetricsScrapeFailed", "RAGRetrievalUnavailable",
        "RAGRetrievalTieOverflow", "RAGRetrievalP95High",
    }
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/-/ready", timeout=2) as response:
                if response.status != 200:
                    raise ValueError("Prometheus is not ready")
            with urllib.request.urlopen(base + "/api/v1/rules", timeout=2) as response:
                rules = json.load(response)
            names = {
                rule.get("name")
                for group in rules.get("data", {}).get("groups", [])
                if group.get("name") == "retrieval-v2"
                for rule in group.get("rules", [])
                if rule.get("type") == "alerting"
            }
            if rules.get("status") == "success" and expected <= names:
                query = urlencode({"query": 'up{job="rag-engine-v2"}'})
                with urllib.request.urlopen(base + "/api/v1/query?" + query, timeout=2) as response:
                    scrape = json.load(response)
                data = scrape.get("data", {})
                targets = data.get("result") if isinstance(data, dict) else None
                if (scrape.get("status") == "success" and data.get("resultType") == "vector"
                        and isinstance(targets, list) and len(targets) == 1
                        and isinstance(targets[0], dict)
                        and targets[0].get("metric", {}).get("job") == "rag-engine-v2"
                        and isinstance(targets[0].get("value"), list)
                        and len(targets[0]["value"]) == 2
                        and targets[0]["value"][1] == "1"):
                    return True
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        time.sleep(1)
    return False


def _public_preflight_from_bundle(
    *,
    verified: _VerifiedDeployInputs,
    merge_sha: str,
    color: str | None,
    material_root: Path | None,
    secrets_root: Path | None,
    repo_root: Path | None,
) -> str:
    if color not in {"blue", "green"} or any(
        value is None for value in (material_root, secrets_root, repo_root)
    ):
        raise DeploymentWrapperError("public candidate color and material roots are required")
    assert color is not None and material_root is not None
    assert secrets_root is not None and repo_root is not None
    try:
        effective = json.loads(verified.effective_compose_bytes)
        evidence = public_preflight.require_public_candidate(
            resolved_compose=effective,
            source_sha=merge_sha,
            color=color,
            material_root=material_root,
            secrets_root=secrets_root,
            repo_root=repo_root,
            verified_application_images=verified.bundle_document["verified_images"],
        )
    except (json.JSONDecodeError, public_preflight.PublicCandidateError) as exc:
        raise DeploymentWrapperError(f"public candidate preflight refused: {exc}") from exc
    project = evidence.get("project")
    if not isinstance(project, str) or project != f"nexus-rag-{color}":
        raise DeploymentWrapperError("public candidate project differs from selected color")
    return project


def rollback_public_candidate_from_bundle(
    *,
    bundle_dir: Path,
    merge_sha: str,
    public_color: str,
    run_bundle_compose_config: RunBundleComposeConfig = _run_bundle_compose_config,
    run_subprocess: RunSubprocess = _default_run_subprocess,
    deployment_state_root: Path | None = None,
    project_containers: ProjectContainers = _default_project_containers,
    host_local_guard: HostLocalGuard = _require_host_local_docker_daemon,
) -> None:
    """Arrête seulement la couleur candidate, sans supprimer ses volumes."""
    document = _load_and_verify_bundle_manifest(bundle_dir, merge_sha=merge_sha)
    if document.get("public_candidate") is not True or public_color not in {"blue", "green"}:
        raise DeploymentWrapperError("rollback requires a public candidate bundle and color")
    effective = run_bundle_compose_config(
        bundle_dir, bundle_dir / _ENV_BUNDLE_NAME, vri._PUBLIC_CANDIDATE_COMPOSE_FILES
    )
    if vri.canonical_resolved_compose_bytes(effective) != signer._read_bytes_no_follow(  # noqa: SLF001
        bundle_dir / _RESOLVED_COMPOSE_BUNDLE_NAME, label="resolved_compose"
    ):
        raise DeploymentWrapperError("rollback effective Compose differs from candidate bundle")
    project = f"nexus-rag-{public_color}"
    if effective.get("name") != project or set(effective.get("services", {})) != (
        vri._PUBLIC_CANDIDATE_SERVICES
    ):
        raise DeploymentWrapperError("rollback project or services differ from candidate bundle")
    with _public_color_lock(deployment_state_root, public_color, host_local_guard) as state_root:
        if _load_and_verify_bundle_manifest(bundle_dir, merge_sha=merge_sha) != document:
            raise DeploymentWrapperError("public rollback bundle changed before mutation")
        current_effective = run_bundle_compose_config(
            bundle_dir, bundle_dir / _ENV_BUNDLE_NAME, vri._PUBLIC_CANDIDATE_COMPOSE_FILES
        )
        if vri.canonical_resolved_compose_bytes(current_effective) != (
            vri.canonical_resolved_compose_bytes(effective)
        ):
            raise DeploymentWrapperError("public rollback Compose changed before mutation")
        state = _read_public_state(state_root, public_color)
        if (state is None or state.get("bundle_digest") != document["bundle_digest"]
                or state.get("bundle_dir") != str(bundle_dir)
                or state.get("merge_sha") != merge_sha):
            raise DeploymentWrapperError("public rollback bundle is not the active generation")
        ids = _owned_public_container_ids(
            project=project, bundle_dir=bundle_dir,
            containers=project_containers, require_all_services=True,
        )
        if ids != state.get("container_ids"):
            raise DeploymentWrapperError("public rollback generation container identity changed")
        command = _public_compose_args(bundle_dir, project) + ["down", "--timeout", "10"]
        try:
            result = run_subprocess(command, bundle_dir)
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeploymentWrapperError("public candidate rollback failed") from exc
        if result.returncode != 0:
            raise DeploymentWrapperError("public candidate rollback failed")
        try:
            os.unlink(_public_state_name(public_color), dir_fd=state_root)
            os.fsync(state_root)
        except OSError as exc:
            raise DeploymentWrapperError("public rollback state cleanup failed") from exc


def _deploy_public_candidate_from_bundle(
    *,
    bundle_dir: Path,
    merge_sha: str,
    verified: _VerifiedDeployInputs,
    trusted_readiness_anchor_raw: bytes | None,
    run_bundle_compose_config: RunBundleComposeConfig,
    run_subprocess: RunSubprocess,
    public_color: str | None,
    public_material_root: Path | None,
    public_secrets_root: Path | None,
    public_repo_root: Path | None,
    public_final_cutover_go: bool,
    assert_readiness: ReadinessAssert | None,
    project_inventory: ProjectInventory,
    deployment_state_root: Path | None,
    project_containers: ProjectContainers,
    prometheus_probe: PrometheusProbe | None,
    host_local_guard: HostLocalGuard,
) -> list[str]:
    if public_final_cutover_go is not True:
        raise DeploymentWrapperError("public candidate remains plan-only until final cutover GO")
    if public_repo_root is None:
        raise DeploymentWrapperError("public candidate requires final repository checkout")
    ready = assert_readiness or (lambda: _assert_go_live_ready(public_repo_root, merge_sha))
    try:
        if ready() is not True:
            raise DeploymentWrapperError("canonical --assert-ready did not pass")
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeploymentWrapperError("canonical --assert-ready could not run") from exc
    project = _public_preflight_from_bundle(
        verified=verified, merge_sha=merge_sha, color=public_color,
        material_root=public_material_root, secrets_root=public_secrets_root,
        repo_root=public_repo_root,
    )
    assert public_color is not None
    with _public_color_lock(deployment_state_root, public_color, host_local_guard) as state_root:
        if _read_public_state(state_root, public_color) is not None:
            raise DeploymentWrapperError("public candidate color has an active generation")
        _require_empty_public_project(project, project_inventory)
        command = _public_compose_args(bundle_dir, project)
        services = verified.explicit_services
        try:
            pull = run_subprocess(command + ["pull", *services], bundle_dir)
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeploymentWrapperError("public candidate pull failed") from exc
        if pull.returncode != 0:
            raise DeploymentWrapperError("public candidate pull failed")
        reverified = _verify_deploy_inputs(
            bundle_dir=bundle_dir, merge_sha=merge_sha, execute=True,
            trusted_readiness_anchor_raw=trusted_readiness_anchor_raw,
            run_bundle_compose_config=run_bundle_compose_config,
        )
        if reverified != verified:
            raise DeploymentWrapperError("public candidate bundle changed after pull")
        _public_preflight_from_bundle(
            verified=reverified, merge_sha=merge_sha, color=public_color,
            material_root=public_material_root, secrets_root=public_secrets_root,
            repo_root=public_repo_root,
        )
        try:
            if ready() is not True:
                raise DeploymentWrapperError("canonical --assert-ready changed after pull")
        except (OSError, subprocess.SubprocessError) as exc:
            raise DeploymentWrapperError("canonical --assert-ready could not run after pull") from exc
        _require_empty_public_project(project, project_inventory)
        try:
            up = run_subprocess(
                command + ["up", "-d", "--no-build", "--pull", "never", "--wait",
                           "--wait-timeout", "300", *services], bundle_dir,
            )
            up_failed = up.returncode != 0
        except (OSError, subprocess.SubprocessError):
            up_failed = True
        failure = "public candidate up failed" if up_failed else ""
        if not up_failed:
            try:
                ids = _owned_public_container_ids(
                    project=project, bundle_dir=bundle_dir,
                    containers=project_containers, require_all_services=True,
                )
                probe = prometheus_probe or _default_public_prometheus_probe
                if probe(_prometheus_port(verified)) is not True:
                    failure = "public Prometheus rules readiness failed"
                else:
                    _write_public_state(state_root, public_color, {
                        "bundle_digest": verified.bundle_document["bundle_digest"],
                        "bundle_dir": str(bundle_dir),
                        "merge_sha": merge_sha,
                        "container_ids": ids,
                    })
                    return ["PUBLIC_CANDIDATE_DEPLOYED=true", "EDGE_SWITCHED=false"]
            except (DeploymentWrapperError, OSError) as exc:
                failure = f"public candidate identity/readiness failed: {exc}"
        # La même serrure couvre la vérification des labels puis `down`.
        try:
            rollback_ids = _owned_public_container_ids(
                project=project, bundle_dir=bundle_dir,
                containers=project_containers, require_all_services=False,
            )
        except DeploymentWrapperError as exc:
            raise DeploymentWrapperError(
                f"{failure}; rollback refused: container ownership ambiguous"
            ) from exc
        try:
            rollback = run_subprocess(command + ["down", "--timeout", "10"], bundle_dir)
            rollback_passed = rollback.returncode == 0
        except (OSError, subprocess.SubprocessError):
            rollback_passed = False
        if not rollback_passed:
            raise DeploymentWrapperError(f"{failure}; rollback failed")
        state = _read_public_state(state_root, public_color)
        if state is not None:
            if state != {
                "bundle_digest": verified.bundle_document["bundle_digest"],
                "bundle_dir": str(bundle_dir),
                "merge_sha": merge_sha,
                "container_ids": rollback_ids,
            }:
                raise DeploymentWrapperError(
                    f"{failure}; rollback passed but generation state is ambiguous"
                )
            try:
                os.unlink(_public_state_name(public_color), dir_fd=state_root)
                os.fsync(state_root)
            except OSError as exc:
                raise DeploymentWrapperError(
                    f"{failure}; rollback passed but state cleanup failed"
                ) from exc
        raise DeploymentWrapperError(f"{failure}; rollback passed")


def deploy_from_bundle(
    *,
    bundle_dir: Path,
    merge_sha: str,
    execute: bool,
    run_subprocess: RunSubprocess = _default_run_subprocess,
    list_running_containers: ListRunningContainers = _default_list_running_containers,
    trusted_readiness_anchor_raw: bytes | None = None,
    run_bundle_compose_config: RunBundleComposeConfig = _run_bundle_compose_config,
    deployment_state_root: Path | None = None,
    public_color: str | None = None,
    public_material_root: Path | None = None,
    public_secrets_root: Path | None = None,
    public_repo_root: Path | None = None,
    public_final_cutover_go: bool = False,
    assert_readiness: ReadinessAssert | None = None,
    project_inventory: ProjectInventory = _default_project_inventory,
    project_containers: ProjectContainers = _default_project_containers,
    prometheus_probe: PrometheusProbe | None = None,
    host_local_guard: HostLocalGuard = _require_host_local_docker_daemon,
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
    sur l'hôte cible. La voie publique V2 est distincte : elle exige le GO
    explicite, le garde canonique frais, un projet/couleur vide, puis attend
    la santé de ses cinq services ; elle ne change pas le routage public.

    En V2, la source de bind de l'AuthorizationSet et l'allowlist exacte des
    fichiers relus par le readiness gate vivent dans une génération durable
    adressée par les digests du bundle et du set, et non dans le scratch
    Compose ni dans un répertoire opérateur résiduel. Toute génération
    complètement matérialisée est conservée, même si le déploiement échoue
    avant ``compose up`` : un autre processus a pu la réutiliser entre-temps.
    Le garbage collection est donc une opération séparée, hors de cette
    frontière concurrente; les générations antérieures restent utilisables
    pour rollback.
    """
    verified = _verify_deploy_inputs(
        bundle_dir=bundle_dir,
        merge_sha=merge_sha,
        execute=execute,
        trusted_readiness_anchor_raw=trusted_readiness_anchor_raw,
        run_bundle_compose_config=run_bundle_compose_config,
    )
    explicit_services = verified.explicit_services
    public_candidate = verified.bundle_document.get("public_candidate") is True
    if public_candidate:
        if execute:
            return _deploy_public_candidate_from_bundle(
                bundle_dir=bundle_dir, merge_sha=merge_sha, verified=verified,
                trusted_readiness_anchor_raw=trusted_readiness_anchor_raw,
                run_bundle_compose_config=run_bundle_compose_config,
                run_subprocess=run_subprocess,
                public_color=public_color,
                public_material_root=public_material_root,
                public_secrets_root=public_secrets_root,
                public_repo_root=public_repo_root,
                public_final_cutover_go=public_final_cutover_go,
                assert_readiness=assert_readiness,
                project_inventory=project_inventory,
                deployment_state_root=deployment_state_root,
                project_containers=project_containers,
                prometheus_probe=prometheus_probe,
                host_local_guard=host_local_guard,
            )
        return [
            "PUBLIC_CANDIDATE_VERIFIED=true",
            "MUTATION_ALLOWED=false",
            "CUTOVER_GATE_REQUIRED=true",
        ]
    compose_files = (
        vri._PUBLIC_CANDIDATE_COMPOSE_FILES if public_candidate else _CANONICAL_COMPOSE_FILES
    )

    compose_args = ["docker", "compose", "--env-file", str(bundle_dir / _ENV_BUNDLE_NAME)]
    for name in compose_files:
        compose_args += ["-f", str(bundle_dir / name)]

    plan = [
        " ".join(compose_args + ["pull", *explicit_services]),
        " ".join(compose_args + ["up", "-d", *explicit_services]),
    ]
    if not execute:
        return plan

    authorization_generation: _DurableAuthorizationSetGeneration | None = None
    with tempfile.TemporaryDirectory(prefix="nexus-verified-compose-") as temporary:
        snapshot = Path(temporary)
        for name in _CANONICAL_COMPOSE_FILES:
            raw = signer._read_bytes_no_follow(bundle_dir / name, label=name)  # noqa: SLF001
            expected = verified.bundle_document["files"].get(name)
            if _sha256_bytes(raw) != expected:
                raise DeploymentWrapperError(f"bundle file {name!r} changed before snapshot")
            signer._atomic_private_write(snapshot / name, raw)  # noqa: SLF001

        env_raw = signer._read_bytes_no_follow(  # noqa: SLF001
            bundle_dir / _ENV_BUNDLE_NAME, label=_ENV_BUNDLE_NAME
        )
        if _sha256_bytes(env_raw) != verified.bundle_document["files"].get(
            _ENV_BUNDLE_NAME
        ):
            raise DeploymentWrapperError("bundle .env changed before snapshot")
        snapshot_authorization_set: Path | None = None
        if verified.authorization_set_digest is not None:
            authorization_raw = signer._read_bytes_no_follow(  # noqa: SLF001
                bundle_dir / _AUTHORIZATION_SET_BUNDLE_NAME,
                label=_AUTHORIZATION_SET_BUNDLE_NAME,
            )
            if _sha256_bytes(authorization_raw) != verified.authorization_set_digest:
                raise DeploymentWrapperError(
                    "bundled authorization set differs from signed readiness"
                )
            authorization_generation = _materialize_v2_release_generation(
                state_root=(
                    deployment_state_root
                    if deployment_state_root is not None
                    else bundle_dir.parent / ".nexus-deployment-state"
                ),
                bundle_dir=bundle_dir,
                bundle_document=verified.bundle_document,
                authorization_set_digest=verified.authorization_set_digest,
                authorization_set_raw=authorization_raw,
            )
            snapshot_authorization_set = authorization_generation.path
            assert authorization_generation.material_root is not None
            env_raw = env_raw.rstrip(b"\n") + (
                b"\nPRODUCTION_AUTHORIZATION_SET_HOST_FILE="
                + _dotenv_path_value(
                    snapshot_authorization_set, label="authorization set snapshot path"
                )
                + b"\nPRODUCTION_V2_RELEASE_MATERIAL_HOST_DIR="
                + _dotenv_path_value(
                    authorization_generation.material_root,
                    label="V2 release material snapshot path",
                )
                + b"\n"
            )
        signer._atomic_private_write(snapshot / _ENV_BUNDLE_NAME, env_raw)  # noqa: SLF001

        snapshot_args = [
            "docker",
            "compose",
            "--project-directory",
            str(bundle_dir),
            "--env-file",
            str(snapshot / _ENV_BUNDLE_NAME),
        ]
        for name in _CANONICAL_COMPOSE_FILES:
            snapshot_args += ["-f", str(snapshot / name)]

        require_no_foreign_container_collision(
            target_services=explicit_services,
            expected_working_dir=str(bundle_dir),
            running_containers=list_running_containers(),
        )

        reverified = _verify_deploy_inputs(
            bundle_dir=bundle_dir,
            merge_sha=merge_sha,
            execute=True,
            trusted_readiness_anchor_raw=trusted_readiness_anchor_raw,
            run_bundle_compose_config=run_bundle_compose_config,
        )
        if (
            reverified.effective_compose_bytes != verified.effective_compose_bytes
            or reverified.explicit_services != explicit_services
        ):
            raise DeploymentWrapperError("effective compose changed immediately before mutation")

        if (
            reverified.authorization_set_bind_source
            != verified.authorization_set_bind_source
            or reverified.authorization_set_digest != verified.authorization_set_digest
        ):
            raise DeploymentWrapperError(
                "effective authorization set bind changed immediately before mutation"
            )
        if verified.authorization_set_bind_source is not None:
            assert verified.authorization_set_digest is not None
            assert authorization_generation is not None
            _require_generation_identity(authorization_generation)
            snapshot_effective = run_bundle_compose_config(
                    snapshot,
                    snapshot / _ENV_BUNDLE_NAME,
                    _CANONICAL_COMPOSE_FILES,
                )
            effective_snapshot_source = require_effective_authorization_set_bind(
                effective_compose=snapshot_effective,
                expected_digest=verified.authorization_set_digest,
            )
            if effective_snapshot_source != snapshot_authorization_set:
                raise DeploymentWrapperError(
                    "effective Compose does not use the private authorization set snapshot"
                )
            effective_material_root = require_effective_v2_material_bind(
                effective_compose=snapshot_effective
            )
            if effective_material_root != authorization_generation.material_root:
                raise DeploymentWrapperError(
                    "effective Compose does not use the private V2 release material snapshot"
                )
            _require_generation_identity(authorization_generation)

        pull = run_subprocess(snapshot_args + ["pull", *explicit_services], bundle_dir)
        if pull.returncode != 0:
            raise DeploymentWrapperError(
                f"docker compose pull failed (exit {pull.returncode}): {pull.stderr.strip()[:1000]}"
            )
        if verified.authorization_set_bind_source is not None:
            assert verified.authorization_set_digest is not None
            assert authorization_generation is not None
            _require_generation_identity(authorization_generation)
            require_effective_authorization_set_bind(
                effective_compose=run_bundle_compose_config(
                    snapshot,
                    snapshot / _ENV_BUNDLE_NAME,
                    _CANONICAL_COMPOSE_FILES,
                ),
                expected_digest=verified.authorization_set_digest,
            )
            effective_material_root = require_effective_v2_material_bind(
                effective_compose=run_bundle_compose_config(
                    snapshot,
                    snapshot / _ENV_BUNDLE_NAME,
                    _CANONICAL_COMPOSE_FILES,
                )
            )
            if effective_material_root != authorization_generation.material_root:
                raise DeploymentWrapperError(
                    "effective Compose changed its private V2 release material snapshot"
                )
            _require_generation_identity(authorization_generation)
        up = run_subprocess(snapshot_args + ["up", "-d", *explicit_services], bundle_dir)
        if up.returncode != 0:
            raise DeploymentWrapperError(
                f"docker compose up failed (exit {up.returncode}): {up.stderr.strip()[:1000]}"
            )
        if authorization_generation is not None:
            _require_generation_identity(authorization_generation)
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
    p.add_argument(
        "--readiness-protocol",
        choices=[
            "NEXUS-PRODUCTION-READINESS-V1",
            "NEXUS-PRODUCTION-READINESS-V2",
        ],
        default="NEXUS-PRODUCTION-READINESS-V1",
    )
    for flag in (
        "authorization-set-file",
        "governed-root",
        "review-binding-trust-anchor-file",
        "trusted-reviewers-file",
        "revocation-registry-file",
        "release-scope-placement-file",
        "verified-profiles-file",
        "profile-manifest-file",
        "authority-required-file",
        "h2b-report-file",
        "h2-evidence-bundle-file",
        "promotion-evidence-file",
        "catalog-file",
        "sealed-manifest-file",
        "routing-file",
        "rights-file",
        "pii-file",
        "golden-file",
        "currentness-file",
    ):
        p.add_argument(f"--{flag}", type=Path, default=None)
    for flag in (
        "profile-proposal-matrix-path",
        "accepted-placements-path",
        "release-registry-path",
        "expected-contents-path",
        "verified-profiles-path",
        "profile-manifest-path",
    ):
        p.add_argument(f"--{flag}", default=None)
    p.add_argument("--environment", default="production")
    p.add_argument(
        "--bundle-dir", type=Path, required=True,
        help="Destination neuve sous un parent existant, de confiance et sans symlink ; "
        "le bundle est créé à 0700 et ses fichiers à 0600.",
    )
    p.add_argument(
        "--public-candidate", action="store_true", default=False,
        help="Matérialise le candidat public V2 avec ses deux fichiers Compose.",
    )
    p.add_argument("--public-color", choices=("blue", "green"), default=None)
    p.add_argument("--public-material-root", type=Path, default=None)
    p.add_argument("--public-secrets-root", type=Path, default=None)
    p.add_argument(
        "--final-cutover-go", action="store_true", default=False,
        help="Autorisation humaine explicite du cutover final ; l'exécution exige aussi "
        "le garde canonique --assert-ready frais et le bundle public signé.",
    )
    p.add_argument(
        "--rollback-public-candidate", action="store_true", default=False,
        help="Arrête uniquement la couleur candidate issue du bundle existant ; "
        "conserve ses volumes et ne rematérialise rien.",
    )
    p.add_argument(
        "--deployment-state-root",
        type=Path,
        default=None,
        help="Répertoire privé durable des générations V2 ; obligatoire pour "
        "déployer ou annuler une couleur publique, identique entre opérations.",
    )
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
    p.add_argument("--json-output", action="store_true", default=False)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    final_cutover_go = getattr(args, "final_cutover_go", False)
    if getattr(args, "rollback_public_candidate", False):
        if not args.public_candidate or args.execute or final_cutover_go or getattr(
            args, "public_color", None
        ) not in {"blue", "green"}:
            print("REFUSED: public candidate rollback requires a color and forbids execute/GO", file=sys.stderr)
            return 1
        if args.deployment_state_root is None:
            print("REFUSED: public rollback requires --deployment-state-root", file=sys.stderr)
            return 1
        try:
            rollback_public_candidate_from_bundle(
                bundle_dir=args.bundle_dir,
                merge_sha=args.merge_sha,
                public_color=args.public_color,
                deployment_state_root=args.deployment_state_root,
            )
        except DeploymentWrapperError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        if args.json_output:
            print('{"edge_switched":false,"rolled_back":true}')
        else:
            print("PUBLIC_CANDIDATE_ROLLBACK_PASS=true")
            print("EDGE_SWITCHED=false")
        return 0
    if args.public_candidate and args.readiness_protocol != "NEXUS-PRODUCTION-READINESS-V2":
        print("REFUSED: --public-candidate requires signed readiness V2", file=sys.stderr)
        return 1
    if args.public_candidate and args.execute and not final_cutover_go:
        print("REFUSED: public candidate execution requires final cutover GO", file=sys.stderr)
        return 1
    if final_cutover_go and not (args.public_candidate and args.execute):
        print("REFUSED: final cutover GO requires public candidate execution", file=sys.stderr)
        return 1
    if args.public_candidate and args.execute and args.deployment_state_root is None:
        print("REFUSED: public execution requires --deployment-state-root", file=sys.stderr)
        return 1
    if args.public_candidate and args.execute:
        for value, flag in (
            (getattr(args, "public_color", None), "--public-color"),
            (getattr(args, "public_material_root", None), "--public-material-root"),
            (getattr(args, "public_secrets_root", None), "--public-secrets-root"),
        ):
            if value is None:
                print(f"REFUSED: public execution requires {flag}", file=sys.stderr)
                return 1
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
        trusted_anchor_raw = (
            signer._read_bytes_no_follow(  # noqa: SLF001 - gel externe unique
                args.trust_anchor_file, label="readiness_trust_anchor"
            )
            if args.trust_anchor_file is not None
            else None
        )
        v2_material: signer.V2ReleaseMaterial | None = None
        if args.readiness_protocol == "NEXUS-PRODUCTION-READINESS-V2":
            required_v2 = (
                "authorization_set_file",
                "governed_root",
                "review_binding_trust_anchor_file",
                "trusted_reviewers_file",
                "revocation_registry_file",
                "release_scope_placement_file",
                "verified_profiles_file",
                "profile_manifest_file",
                "authority_required_file",
                "h2b_report_file",
                "h2_evidence_bundle_file",
                "promotion_evidence_file",
                "catalog_file",
                "sealed_manifest_file",
                "routing_file",
                "rights_file",
                "pii_file",
                "golden_file",
                "currentness_file",
                "profile_proposal_matrix_path",
                "accepted_placements_path",
                "release_registry_path",
                "expected_contents_path",
                "verified_profiles_path",
                "profile_manifest_path",
            )
            missing = [name for name in required_v2 if getattr(args, name) is None]
            if missing or not args.json_output:
                detail = f"missing {missing!r}" if missing else "--json-output is required"
                raise DeploymentWrapperError(f"readiness V2 arguments incomplete: {detail}")
            v2_material = dataclasses.replace(
                signer._load_v2_release_material(  # noqa: SLF001 - même bundle de service
                    args,
                    now=datetime.now(UTC),
                    merge_tree_sha=args.merge_tree_sha,
                ),
                merge_sha=args.merge_sha,
                merge_tree_sha=args.merge_tree_sha,
            )
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
                download_artifact=(
                    dii.make_public_candidate_download_artifact_via_gh(repository=_CANONICAL_REPOSITORY)
                    if args.public_candidate else
                    dii.make_download_artifact_via_gh(repository=_CANONICAL_REPOSITORY)
                ),
                run_docker_compose_config=vri.run_docker_compose_config_via_subprocess,
                work_dir=Path(tmp),
                bundle_dir=args.bundle_dir,
                git_show_bytes=vri._git_show_bytes,
                readiness_protocol=args.readiness_protocol,
                v2_release_material=v2_material,
                frozen_trust_anchor_raw=trusted_anchor_raw,
                public_candidate=args.public_candidate,
            )
        plan = deploy_from_bundle(
            bundle_dir=args.bundle_dir,
            merge_sha=args.merge_sha,
            execute=args.execute,
            trusted_readiness_anchor_raw=trusted_anchor_raw,
            deployment_state_root=args.deployment_state_root,
            public_color=getattr(args, "public_color", None),
            public_material_root=getattr(args, "public_material_root", None),
            public_secrets_root=getattr(args, "public_secrets_root", None),
            public_repo_root=args.repo_root,
            public_final_cutover_go=final_cutover_go,
        )
    except (DeploymentWrapperError, vri.ReleaseVerificationError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    if args.json_output:
        output = {
            "bundle_digest": bundle_document["bundle_digest"],
            "deployed": args.execute,
            "readiness_protocol": bundle_document["readiness_protocol"],
            "verified_images": bundle_document["verified_images"],
        }
        if args.public_candidate:
            output["mutation_allowed"] = bool(args.execute)
            output["cutover_gate_required"] = not args.execute
            output["edge_switched"] = False
        print(
            json.dumps(
                output,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    print(f"BUNDLE_DIGEST={bundle_document['bundle_digest']}")
    for name, ref in sorted(bundle_document["verified_images"].items()):
        print(f"VERIFIED {name}={ref}")
    if bundle_document["readiness_manifest_included"]:
        print("SIGNED_COMPOSE_DIGEST_MATCH=true")
    if args.execute:
        print("DEPLOYED=true")
    elif args.public_candidate:
        print("DEPLOYED=false")
        print("MUTATION_ALLOWED=false")
        print("CUTOVER_GATE_REQUIRED=true")
    else:
        print("DEPLOYED=false (dry run — pass --execute to run the plan below)")
        for step in plan:
            print(f"PLAN: {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
