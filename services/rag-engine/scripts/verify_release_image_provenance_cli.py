"""Vérificateur hôte pré-déploiement — provenance + pinning (ADR-0036, phase B).

**Ce que fait ce script.** Avant tout `docker compose up` d'une release
de production, il refuse fail-closed de laisser passer une release dont
les images ne sont pas (a) réellement épinglées par digest dans le
Compose résolu (`docker-compose.v2.yml` + `docker-compose.production-
workers.yml` + `docker-compose.production-release.yml`, jamais le YAML
source non interpolé) et (b) ce digest précis n'est pas issu d'un run
GitHub Actions vérifié (`.github/workflows/production-image-provenance.
yml`) pour EXACTEMENT le commit source déclaré.

**Ce qu'il ne fait jamais.** Il ne lance jamais lui-même `docker compose
up` (ni aucune autre commande de mutation) — un verdict positif
n'autorise que l'étape de déploiement suivante, séparée, de l'opérateur.
Il ne construit ni ne pousse aucune image. Il ne recalcule aucun verdict
de gouvernance pédagogique (ADR-0001).

Réutilise les deux primitives déjà vérifiées et testées de
`deployment_image_inventory.py` (PR #102) — ne les redéfinit pas — et
n'ajoute qu'un seul fait nouveau : que le digest réellement câblé côté
Compose et le digest issu de la provenance vérifiée sont, pour chaque
service, EXACTEMENT le même (un digest correctement formé mais sans
lien avec la provenance de ce commit — substitué, ou laissé d'un essai
précédent — passerait sinon les deux primitives existantes séparément
sans jamais être confronté à l'autre).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deployment_image_inventory as dii  # noqa: E402

#: Ordre et noms exacts documentés dans docker-compose.production-
#: release.yml — jamais un YAML source seul, toujours cette combinaison.
_CANONICAL_COMPOSE_FILES: tuple[str, ...] = (
    "docker-compose.v2.yml",
    "docker-compose.production-workers.yml",
    "docker-compose.production-release.yml",
)

RunDockerComposeConfig = Callable[[Path, tuple[str, ...]], dict[str, Any]]


class ReleaseVerificationError(RuntimeError):
    """La release ne prouve pas ses images — fail-closed.

    Une seule exception pour tout refus : Compose non résolvable, image
    non épinglée par digest, provenance invalide/absente/périmée, digest
    câblé qui ne correspond pas à la provenance vérifiée. Un appelant
    n'a jamais à distinguer ces cas pour décider : tous interdisent le
    déploiement."""


def run_docker_compose_config_via_subprocess(
    infra_dir: Path, compose_files: tuple[str, ...]
) -> dict[str, Any]:
    """Frontière process par défaut — ``docker compose ... config
    --format json``. Ne contacte ni registre ni daemon distant : cette
    sous-commande ne fait que résoudre/interpoler le YAML localement."""
    for name in compose_files:
        candidate = infra_dir / name
        if not candidate.is_file():
            raise ReleaseVerificationError(f"compose file not found: {candidate}")
    args = ["docker", "compose"]
    for name in compose_files:
        args += ["-f", name]
    args += ["config", "--format", "json"]
    try:
        completed = subprocess.run(
            args, cwd=infra_dir, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseVerificationError(f"docker compose config failed: {exc}") from exc
    if completed.returncode != 0:
        raise ReleaseVerificationError(
            "docker compose config failed (exit "
            f"{completed.returncode}): {completed.stderr.strip()[:1000]}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseVerificationError(f"docker compose config produced non-JSON output: {exc}") from exc
    if not isinstance(document, dict):
        raise ReleaseVerificationError("docker compose config did not produce a JSON object")
    return document


def require_pinned_images_match_verified_provenance(
    *, pinned_images: dict[str, str], provenance_images: dict[str, str]
) -> dict[str, str]:
    """Le digest câblé côté Compose doit être EXACTEMENT celui qu'un run
    de provenance vérifié a produit pour ce commit — jamais seulement
    « un digest valide et épinglé, dont on présume qu'il est le bon »."""
    if set(pinned_images) != set(provenance_images):
        raise ReleaseVerificationError(
            "resolved compose images and verified provenance do not name the same "
            f"services (compose={sorted(pinned_images)}, provenance={sorted(provenance_images)})"
        )
    mismatched = {
        name: (pinned_images[name], provenance_images[name])
        for name in pinned_images
        if pinned_images[name] != provenance_images[name]
    }
    if mismatched:
        details = "; ".join(
            f"{name}: compose={compose!r} != provenance={prov!r}"
            for name, (compose, prov) in sorted(mismatched.items())
        )
        raise ReleaseVerificationError(
            "resolved compose image(s) do not match verified provenance digest(s): "
            f"{details} — a digest-pinned reference not produced by the canonical "
            "provenance workflow for this exact commit is never accepted"
        )
    return dict(pinned_images)


def verify_release_images(
    *,
    repository: str,
    source_commit_sha: str,
    source_tree_sha: str,
    provenance_run_id: int,
    provenance_run_attempt: int,
    infra_dir: Path,
    compose_files: tuple[str, ...],
    github_api_get: dii.GitHubApiGet,
    download_artifact: dii.DownloadArtifact,
    run_docker_compose_config: RunDockerComposeConfig,
    work_dir: Path,
) -> dict[str, str]:
    resolved_config = run_docker_compose_config(infra_dir, compose_files)
    try:
        pinned_images = dii.require_resolved_compose_images_are_pinned(resolved_config)
    except dii.DeploymentImageInventoryError as exc:
        raise ReleaseVerificationError(str(exc)) from exc
    try:
        provenance_images = dii.verify_application_image_provenance(
            repository=repository,
            source_commit_sha=source_commit_sha,
            source_tree_sha=source_tree_sha,
            provenance_run_id=provenance_run_id,
            provenance_run_attempt=provenance_run_attempt,
            github_api_get=github_api_get,
            download_artifact=download_artifact,
            work_dir=work_dir,
        )
    except dii.DeploymentImageInventoryError as exc:
        raise ReleaseVerificationError(str(exc)) from exc
    return require_pinned_images_match_verified_provenance(
        pinned_images=pinned_images, provenance_images=provenance_images
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repository", required=True)
    p.add_argument("--source-commit-sha", required=True)
    p.add_argument("--source-tree-sha", required=True)
    p.add_argument("--provenance-run-id", type=int, required=True)
    p.add_argument("--provenance-run-attempt", type=int, required=True)
    p.add_argument(
        "--infra-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "infra",
        help="Répertoire contenant les trois fichiers Compose canoniques "
        f"({', '.join(_CANONICAL_COMPOSE_FILES)}).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            verified = verify_release_images(
                repository=args.repository,
                source_commit_sha=args.source_commit_sha,
                source_tree_sha=args.source_tree_sha,
                provenance_run_id=args.provenance_run_id,
                provenance_run_attempt=args.provenance_run_attempt,
                infra_dir=args.infra_dir,
                compose_files=_CANONICAL_COMPOSE_FILES,
                github_api_get=dii.gh_api_get,
                download_artifact=dii.download_artifact_via_gh,
                run_docker_compose_config=run_docker_compose_config_via_subprocess,
                work_dir=Path(tmp),
            )
    except ReleaseVerificationError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    for name, ref in sorted(verified.items()):
        print(f"VERIFIED {name}={ref}")
    print("RELEASE_IMAGE_PROVENANCE_VERIFIED=true")
    print(
        "NOTE: this tool never runs docker compose up — a passing verdict only "
        "authorizes the operator's own subsequent, separate deployment step."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
