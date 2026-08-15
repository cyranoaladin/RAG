"""Vérification de NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1 (ADR-0036, phase B).

Produit par `.github/workflows/production-image-provenance.yml` : la
preuve que les images applicatives de production (`ingestor`,
`multilevel-worker-a/b-production`) ont été construites depuis *ce* commit
exact et poussées vers un registre réel, jamais une affirmation opérateur.

Ce module ne construit ni ne pousse rien — il vérifie hors ligne un run
GitHub Actions déjà terminé et l'artefact qu'il a publié. Toute frontière
réseau (`gh api`, `gh run download`) est injectée par l'appelant : jamais
exercée contre le réseau réel dans les tests de ce module.

Réutilisé par `sign_production_readiness_manifest_cli.py` pour dériver
`application_image_digests` sans jamais accepter de saisie opérateur libre
pour ces images (Codex, instruction humaine PR #100 §12).
"""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

_PROTOCOL_VERSION = "NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1"
_CANONICAL_WORKFLOW_PATH = ".github/workflows/production-image-provenance.yml"
_ARTIFACT_NAME = "nexus-deployment-image-inventory"
_ARTIFACT_FILENAME = "nexus-deployment-image-inventory.json"
_SUPPORTED_PLATFORM = "linux/amd64"

#: Le set exact des services applicatifs de production, dérivé de
#: docker-compose.v2.yml + docker-compose.production-workers.yml (les
#: seuls services `build:` réels de ce dépôt aujourd'hui — voir
#: docs/reports/lot_h2b_production_image_provenance.md §4). Un inventaire
#: qui omet ou invente un service est refusé, jamais silencieusement
#: accepté avec une carte de digests partielle (Codex P1, PR #102).
_EXPECTED_APPLICATION_SERVICES = frozenset(
    {"ingestor", "multilevel-worker-a-production", "multilevel-worker-b-production"}
)

#: Toujours main : cet outil ne vérifie jamais une provenance construite
#: depuis autre chose que la branche protégée (le workflow lui-même refuse
#: de tourner ailleurs — voir `if: github.ref == 'refs/heads/main'`).
_EXPECTED_WORKFLOW_REF = "refs/heads/main"

#: Ensemble de clés exact du document top-level et de chaque entrée de
#: service — un champ inconnu (ajouté par erreur, ou par une version
#: divergente du workflow) est refusé plutôt que silencieusement ignoré
#: (instruction humaine PR #102 §6).
_EXPECTED_TOP_LEVEL_KEYS = frozenset(
    {
        "protocol_version",
        "repository",
        "source_commit_sha",
        "source_tree_sha",
        "platform",
        "workflow_path",
        "workflow_run_id",
        "workflow_run_attempt",
        "workflow_ref",
        "built_at",
        "services",
    }
)
_EXPECTED_SERVICE_KEYS = frozenset(
    {
        "source_kind",
        "build_context",
        "dockerfile",
        "dockerfile_sha256",
        "image_repository",
        "image_digest",
    }
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_REPOSITORY = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

GitHubApiGet = Callable[[str], dict[str, Any]]
DownloadArtifact = Callable[[int, str, Path], Path]


class DeploymentImageInventoryError(RuntimeError):
    """La provenance d'image ne prouve rien — fail-closed.

    Une seule exception pour tout refus : run manquant/faux workflow/faux
    commit, artefact absent/expiré, document malformé, digest absent. Un
    appelant n'a jamais à distinguer ces cas pour décider : tous refusent
    de dériver des digests applicatifs."""


def gh_api_get(path: str) -> dict[str, Any]:
    """Frontière GitHub par défaut — ``gh api``, même transport que
    ``sign_production_readiness_manifest_cli._github_api_get`` (pas
    dupliqué : ce module est appelé par ce script, qui peut passer sa
    propre fonction ou celle-ci)."""
    try:
        completed = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentImageInventoryError(f"GitHub API call to {path!r} failed: {exc}") from exc
    if completed.returncode != 0:
        raise DeploymentImageInventoryError(
            f"GitHub API call to {path!r} failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:500]}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DeploymentImageInventoryError(
            f"GitHub API call to {path!r} returned non-JSON output: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise DeploymentImageInventoryError(f"GitHub API call to {path!r} did not return a JSON object")
    return document


def _download_artifact_via_gh(
    run_id: int, artifact_name: str, dest_dir: Path, *, repository: str | None = None
) -> Path:
    command = ["gh", "run", "download", str(run_id), "-n", artifact_name, "-D", str(dest_dir)]
    if repository is not None:
        command += ["-R", repository]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentImageInventoryError(f"gh run download failed: {exc}") from exc
    if completed.returncode != 0:
        raise DeploymentImageInventoryError(
            f"gh run download failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:500]}"
        )
    candidate = dest_dir / _ARTIFACT_FILENAME
    if not candidate.is_file():
        raise DeploymentImageInventoryError(
            f"downloaded artifact {artifact_name!r} does not contain {_ARTIFACT_FILENAME}"
        )
    return candidate


def download_artifact_via_gh(run_id: int, artifact_name: str, dest_dir: Path) -> Path:
    """Frontière de téléchargement par défaut — ``gh run download``, le
    sous-commande dédiée (pas un appel manuel à l'API zip/archive).

    Résout le dépôt depuis le répertoire courant de ce process (``gh``
    sans ``-R``) — n'est correct que si ce process tourne depuis un
    checkout du bon dépôt. Un appelant qui a déjà un dépôt vérifié
    devrait utiliser ``make_download_artifact_via_gh`` à la place (Codex
    P2, PR #105)."""
    return _download_artifact_via_gh(run_id, artifact_name, dest_dir)


def make_download_artifact_via_gh(*, repository: str) -> DownloadArtifact:
    """Lie ``gh run download`` à un dépôt précis (``-R``), indépendamment
    du répertoire courant du process — pour un appelant qui a déjà un
    dépôt de confiance vérifié et ne veut jamais dépendre du CWD (Codex
    P2, PR #105 : sans ceci, un lancement hors du bon checkout, ou depuis
    un checkout dont le remote nomme un autre dépôt, résout silencieusement
    vers le mauvais dépôt)."""

    def _download(run_id: int, artifact_name: str, dest_dir: Path) -> Path:
        return _download_artifact_via_gh(run_id, artifact_name, dest_dir, repository=repository)

    return _download


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DeploymentImageInventoryError(message)


def _parse_inventory_document(raw: bytes) -> dict[str, Any]:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentImageInventoryError(f"image inventory is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise DeploymentImageInventoryError("image inventory must be a JSON object")
    return document


def _verify_service_entry(name: str, service: Any) -> tuple[str, str]:
    _require(isinstance(service, dict), f"service {name!r}: entry must be a JSON object")
    _require(
        set(service) == _EXPECTED_SERVICE_KEYS,
        f"service {name!r}: unexpected key set (got={sorted(service)}, "
        f"expected={sorted(_EXPECTED_SERVICE_KEYS)})",
    )
    _require(
        service.get("source_kind") == "build",
        f"service {name!r}: source_kind must be 'build' (this module only verifies "
        "build-based application images, never upstream)",
    )
    repository = service.get("image_repository")
    digest = service.get("image_digest")
    _require(
        isinstance(repository, str) and _IMAGE_REPOSITORY.fullmatch(repository) is not None,
        f"service {name!r}: image_repository {repository!r} is not a valid repository name",
    )
    _require(
        isinstance(digest, str) and _OCI_DIGEST.fullmatch(digest) is not None,
        f"service {name!r}: image_digest {digest!r} is not a valid sha256:<64hex> digest — "
        "a missing or mutable-tag digest is never accepted",
    )
    dockerfile_sha256 = service.get("dockerfile_sha256")
    _require(
        isinstance(dockerfile_sha256, str) and _HEX64.fullmatch(dockerfile_sha256) is not None,
        f"service {name!r}: dockerfile_sha256 is missing or malformed",
    )
    return name, f"{repository}@{digest}"


def fetch_and_verify_image_provenance_document(
    *,
    repository: str,
    source_commit_sha: str,
    source_tree_sha: str,
    provenance_run_id: int,
    provenance_run_attempt: int,
    expected_workflow_path: str = _CANONICAL_WORKFLOW_PATH,
    github_api_get: GitHubApiGet,
    download_artifact: DownloadArtifact,
    work_dir: Path,
) -> dict[str, Any]:
    """Récupère et vérifie structurellement le document d'inventaire brut
    publié par le run de provenance — jamais seulement les digests qui en
    sont dérivés.

    Extrait de ``verify_application_image_provenance`` (qui reste le seul
    point d'entrée pour les appelants qui ne veulent que les digests, et
    dont le comportement/signature ne changent pas) pour que d'autres
    appelants (``deploy_verified_release_cli.py``, Lot C) puissent
    matérialiser ce document complet, déjà vérifié, comme preuve
    auditable hors ligne — sans jamais re-télécharger/re-vérifier
    l'artefact une seconde fois pour l'obtenir (même discipline
    « vérifier une fois » que la résolution Compose)."""
    _require(_HEX40.fullmatch(source_commit_sha) is not None, "source_commit_sha is malformed")
    _require(_HEX40.fullmatch(source_tree_sha) is not None, "source_tree_sha is malformed")
    _require(provenance_run_id > 0, "provenance_run_id must be a positive integer")
    _require(provenance_run_attempt > 0, "provenance_run_attempt must be a positive integer")

    run = github_api_get(f"repos/{repository}/actions/runs/{provenance_run_id}")
    _require(
        run.get("path") == expected_workflow_path,
        f"run {provenance_run_id} has workflow path {run.get('path')!r}, expected "
        f"{expected_workflow_path!r} — only the canonical production image provenance "
        "workflow may back an application image digest",
    )
    _require(
        (run.get("repository") or {}).get("full_name") == repository,
        f"run {provenance_run_id} belongs to "
        f"{(run.get('repository') or {}).get('full_name')!r}, not {repository!r}",
    )
    _require(
        run.get("event") == "workflow_dispatch",
        f"run {provenance_run_id} was triggered by {run.get('event')!r}, not "
        "'workflow_dispatch' — the canonical trigger for a production image build",
    )
    _require(
        run.get("status") == "completed" and run.get("conclusion") == "success",
        f"run {provenance_run_id} is not a successfully completed run "
        f"(status={run.get('status')!r}, conclusion={run.get('conclusion')!r})",
    )
    _require(
        run.get("head_sha") == source_commit_sha,
        f"run {provenance_run_id} built head_sha {run.get('head_sha')!r}, not the "
        f"commit being signed ({source_commit_sha!r})",
    )
    # ``run_attempt`` sur l'endpoint général reflète l'attempt COURANTE
    # (la plus récente) de ce run_id — si le workflow a été rejoué depuis
    # que cet artefact a été publié, cette valeur a changé et ce refus se
    # déclenche : jamais une tentative périmée acceptée silencieusement.
    _require(
        run.get("run_attempt") == provenance_run_attempt,
        f"run {provenance_run_id}'s current attempt is {run.get('run_attempt')!r}, not "
        f"the attempt being attested ({provenance_run_attempt!r}) — the run was "
        "re-run since this attempt, or the wrong attempt was named",
    )
    # Confirme aussi, via l'endpoint dédié, que cette tentative précise
    # existe réellement pour ce run — même mécanisme que le signer
    # (sign_production_readiness_manifest_cli._verify_git_and_workflow_facts).
    github_api_get(f"repos/{repository}/actions/runs/{provenance_run_id}/attempts/{provenance_run_attempt}")

    artifact_path = download_artifact(provenance_run_id, _ARTIFACT_NAME, work_dir)
    document = _parse_inventory_document(artifact_path.read_bytes())

    _require(
        set(document) == _EXPECTED_TOP_LEVEL_KEYS,
        f"image inventory has an unexpected key set (got={sorted(document)}, "
        f"expected={sorted(_EXPECTED_TOP_LEVEL_KEYS)}) — an unknown or missing "
        "top-level field is never silently accepted",
    )
    _require(
        document.get("protocol_version") == _PROTOCOL_VERSION,
        f"image inventory declares protocol_version {document.get('protocol_version')!r}, "
        f"expected {_PROTOCOL_VERSION!r}",
    )
    _require(
        document.get("repository") == repository,
        f"image inventory repository {document.get('repository')!r} != {repository!r}",
    )
    _require(
        document.get("source_commit_sha") == source_commit_sha,
        f"image inventory source_commit_sha {document.get('source_commit_sha')!r} != "
        f"{source_commit_sha!r}",
    )
    _require(
        document.get("source_tree_sha") == source_tree_sha,
        f"image inventory source_tree_sha {document.get('source_tree_sha')!r} != "
        f"{source_tree_sha!r}",
    )
    _require(
        document.get("workflow_run_id") == provenance_run_id,
        f"image inventory workflow_run_id {document.get('workflow_run_id')!r} != "
        f"{provenance_run_id!r}",
    )
    _require(
        document.get("workflow_run_attempt") == provenance_run_attempt,
        f"image inventory workflow_run_attempt {document.get('workflow_run_attempt')!r} != "
        f"{provenance_run_attempt!r}",
    )
    _require(
        document.get("workflow_path") == expected_workflow_path,
        f"image inventory workflow_path {document.get('workflow_path')!r} != "
        f"{expected_workflow_path!r}",
    )
    _require(
        document.get("platform") == _SUPPORTED_PLATFORM,
        f"image inventory platform {document.get('platform')!r} != {_SUPPORTED_PLATFORM!r} "
        "— this module only verifies single-platform (linux/amd64) provenance",
    )
    _require(
        document.get("workflow_ref") == _EXPECTED_WORKFLOW_REF,
        f"image inventory workflow_ref {document.get('workflow_ref')!r} != "
        f"{_EXPECTED_WORKFLOW_REF!r}",
    )
    built_at = document.get("built_at")
    if not isinstance(built_at, str):
        raise DeploymentImageInventoryError("image inventory built_at is missing or not a string")
    try:
        datetime.fromisoformat(built_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeploymentImageInventoryError(
            f"image inventory built_at {built_at!r} is not a valid ISO-8601 timestamp: {exc}"
        ) from exc

    services = document.get("services")
    if not isinstance(services, dict) or not services:
        raise DeploymentImageInventoryError("image inventory declares no services")
    if set(services) != _EXPECTED_APPLICATION_SERVICES:
        raise DeploymentImageInventoryError(
            "image inventory does not name exactly the production application "
            f"services (declared={sorted(services)}, "
            f"expected={sorted(_EXPECTED_APPLICATION_SERVICES)}) — an omitted or "
            "invented service is never silently accepted"
        )

    for name, service in services.items():
        _verify_service_entry(name, service)
    return document


def verify_application_image_provenance(
    *,
    repository: str,
    source_commit_sha: str,
    source_tree_sha: str,
    provenance_run_id: int,
    provenance_run_attempt: int,
    expected_workflow_path: str = _CANONICAL_WORKFLOW_PATH,
    github_api_get: GitHubApiGet,
    download_artifact: DownloadArtifact,
    work_dir: Path,
) -> dict[str, str]:
    """Dérive ``{service_name: "repo@sha256:..."}`` depuis un run GitHub
    Actions réel et vérifié — jamais depuis une saisie opérateur.

    Chaque fait est confronté à sa source d'autorité : le run (chemin de
    workflow canonique, succès, déclenchement manuel, même commit que ce
    qui est signé) puis l'artefact qu'il a publié (même protocole, même
    commit, même run, mêmes arbres, chaque image réellement digest-pinnée).

    Enveloppe fine autour de ``fetch_and_verify_image_provenance_document``
    (comportement/signature inchangés pour les appelants existants) — ne
    revérifie rien, se contente de projeter le document déjà vérifié sur
    la carte de digests."""
    document = fetch_and_verify_image_provenance_document(
        repository=repository,
        source_commit_sha=source_commit_sha,
        source_tree_sha=source_tree_sha,
        provenance_run_id=provenance_run_id,
        provenance_run_attempt=provenance_run_attempt,
        expected_workflow_path=expected_workflow_path,
        github_api_get=github_api_get,
        download_artifact=download_artifact,
        work_dir=work_dir,
    )
    digests: dict[str, str] = {}
    for name, service in document["services"].items():
        _, image_ref = _verify_service_entry(name, service)
        digests[name] = image_ref
    return digests


#: ``name@sha256:<64hex>`` — un Compose déjà résolu ne porte plus de tag
#: (contrairement au fichier source, cf. `sign_production_readiness_
#: manifest_cli._COMPOSE_IMAGE_REF`) : `docker compose config` normalise
#: `name:tag@sha256:...` en gardant le digest, jamais le tag, pour les
#: références déjà digest-pinnées côté source.
_PINNED_IMAGE_REF = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")


def require_resolved_compose_images_are_pinned(
    resolved_config: dict[str, Any],
    *,
    expected_services: frozenset[str] = _EXPECTED_APPLICATION_SERVICES,
) -> dict[str, str]:
    """Confronte un Compose **déjà résolu** (sortie de ``docker compose
    -f ... config --format json``, jamais le YAML source non interpolé) :
    chaque service applicatif attendu doit exister, ne porter aucun
    ``build`` résiduel, et son ``image`` doit être épinglée par digest —
    jamais un tag mutable (Codex P2, PR #102).

    ``docker-compose.production-release.yml``'s ``${VAR:?requis}`` only
    proves the variable is *non-empty* — an operator or a broken wrapper
    could still set it to a mutable tag and Compose would accept it
    silently. This function is the primitive a future host deployment
    wrapper must call before any ``docker compose up`` — it does not call
    itself: that wrapper does not exist yet in this repository (see
    docs/reports/lot_h2b_production_image_provenance.md §9)."""
    services = resolved_config.get("services")
    if not isinstance(services, dict):
        raise DeploymentImageInventoryError("resolved compose config has no 'services' mapping")
    missing = expected_services - set(services)
    if missing:
        raise DeploymentImageInventoryError(
            f"resolved compose config is missing expected service(s): {sorted(missing)}"
        )
    pinned: dict[str, str] = {}
    for name in expected_services:
        service = services[name]
        if not isinstance(service, dict):
            raise DeploymentImageInventoryError(f"service {name!r} is not a mapping")
        if "build" in service:
            raise DeploymentImageInventoryError(
                f"service {name!r} still resolves with a 'build' key — the release "
                "overlay's `!reset null` did not take effect, or the wrong compose "
                "files were combined"
            )
        image = service.get("image")
        if not isinstance(image, str) or _PINNED_IMAGE_REF.fullmatch(image) is None:
            raise DeploymentImageInventoryError(
                f"service {name!r} resolves to image {image!r}, which is not pinned "
                "by digest (name@sha256:<64hex>) — a mutable tag is never accepted "
                "for a production release"
            )
        pinned[name] = image
    return pinned
