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

1. **Vérifier** — réutilise `verify_release_image_provenance_cli.
   verify_release_images` (donc, transitivement, `deployment_image_
   inventory.py`, PR #102) sans le redéfinir : preuve que le Compose
   résolu pour `--merge-sha` pin, pour chaque service applicatif, EXACTEMENT
   le digest produit par un run GitHub Actions de provenance réel et
   vérifié. Si `--readiness-manifest-file` est fourni, le manifeste signé
   est en plus vérifié (signature, ancre, environnement, verdict) via
   `nexus_contracts.production_readiness.verify_production_readiness_
   manifest`, et lié à `--merge-sha` via `require_manifest_matches_
   release` — réutilisés tels quels, jamais réimplémentés.
2. **Matérialiser une fois, dans un bundle immuable** — les trois
   fichiers Compose (déjà lus depuis l'objet git `merge_sha`, jamais
   depuis le disque non vérifié), le JSON résolu, l'évidence de
   provenance des images applicatives, le fichier `.env` hôte utilisé
   pour la résolution, et (si fourni) le manifeste de readiness signé
   sont copiés dans un répertoire bundle dédié. Un manifeste de bundle
   (`bundle_manifest.json`) enregistre le SHA-256 de chaque fichier, et
   le SHA-256 de ce manifeste lui-même sert d'identité du bundle.
3. **Déployer depuis le bundle uniquement** — `docker compose pull` puis
   `docker compose up -d` sont invoqués avec `-f <bundle>/<fichier>...
   --env-file <bundle>/.env`, donc contre les copies vérifiées, jamais
   contre `services/rag-engine/infra/*` de nouveau. Rien ne peut diverger
   silencieusement entre la vérification et le déploiement, puisque le
   déploiement ne relit jamais la source mutable.

**Ce que ce wrapper ne fait jamais.** Il ne construit ni ne pousse aucune
image. Il ne mute jamais rien sans `--execute` explicite (par défaut,
verdict + bundle matérialisé + plan imprimé, aucune commande Docker
mutante lancée — `LIVE_MUTATIONS_ALLOWED=false` par défaut). Il ne
recalcule aucun verdict de gouvernance pédagogique (ADR-0001).

**Limite acceptée, documentée plutôt que devinée.** `--readiness-
manifest-file` est optionnel. Quand il est fourni, ce wrapper vérifie sa
signature/ancre/environnement/verdict et sa liaison à `--merge-sha` (via
`require_manifest_matches_release(..., release_sha=merge_sha)`), mais
**ne recalcule pas** et ne confronte pas le `compose_digest` signé dans
le manifeste au Compose réellement résolu ici (`compose_digest=None`
passé à `require_manifest_matches_release`) : la sémantique exacte de ce
champ pour un Compose multi-fichiers résolu est en cours de définition
dans un lot parallèle (PR #100, Section 11 du signer) au moment où ce
lot a été écrit, et ce wrapper ne doit pas figer une interprétation
concurrente à la sienne. Fermer cet écart est un travail de suivi
explicite, pas une omission silencieuse. Quand aucun manifeste n'est
fourni, ce wrapper ne prouve QUE la provenance des images et le pinning
Compose — jamais un feu vert de gouvernance production complet."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
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

RunDockerComposeConfig = vri.RunDockerComposeConfig
RunSubprocess = Callable[[list[str], Path], "subprocess.CompletedProcess[str]"]


class DeploymentWrapperError(RuntimeError):
    """Le bundle ne peut pas être matérialisé, ou le déploiement ne peut
    pas procéder — fail-closed. Une seule exception : vérification
    échouée, fichier manquant, sous-processus en échec. Un appelant n'a
    jamais à distinguer ces cas pour décider de ne pas déployer."""


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
) -> ProductionReadinessManifestV1 | None:
    """Vérifie le manifeste de readiness signé s'il est fourni — jamais
    un manifeste non vérifié consommé silencieusement, jamais un
    manifeste requis quand l'opérateur choisit de n'en fournir aucun
    (voir la limite documentée dans le docstring du module)."""
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
        require_manifest_matches_release(manifest, release_sha=merge_sha, compose_digest=None)
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
) -> dict[str, Any]:
    """Phase 1 (vérifier) + phase 2 (matérialiser) — jamais l'inverse.

    Rien n'est écrit dans ``bundle_dir`` avant que la vérification de la
    provenance des images (et, si fourni, du manifeste de readiness)
    n'ait réussi : un bundle partiellement matérialisé pour une release
    refusée n'existe jamais."""
    work_dir.mkdir(parents=True, exist_ok=True)
    verified_images = vri.verify_release_images(
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
    )

    readiness_manifest_raw = (
        readiness_manifest_file.read_bytes() if readiness_manifest_file is not None else None
    )
    trust_anchor_raw = trust_anchor_file.read_bytes() if trust_anchor_file is not None else None
    verify_readiness_manifest_if_supplied(
        readiness_manifest_raw=readiness_manifest_raw,
        trust_anchor_raw=trust_anchor_raw,
        environment=environment,
        merge_sha=merge_sha,
    )

    # Ré-exécute la résolution Compose une seconde fois n'est pas
    # nécessaire : `verify_release_images` a déjà matérialisé les trois
    # fichiers dans son propre `work_dir` scratch (via
    # `run_docker_compose_config`) — mais ce scratch est éphémère et
    # privé à cet appel. On le refait ici, dans un sous-répertoire de
    # `work_dir` que CE wrapper contrôle, pour obtenir des octets stables
    # à copier dans le bundle plutôt que de dépendre d'un détail
    # d'implémentation interne du vérificateur.
    compose_scratch = work_dir / "bundle-compose-source"
    compose_scratch.mkdir(parents=True, exist_ok=True)
    resolved_config = run_docker_compose_config(
        repo_root, merge_sha, _CANONICAL_COMPOSE_FILES, compose_scratch, env_file
    )

    if bundle_dir.exists():
        raise DeploymentWrapperError(
            f"bundle directory {bundle_dir} already exists — a bundle is never "
            "overwritten silently (rename or remove it first)"
        )
    bundle_dir.mkdir(parents=True)

    file_digests: dict[str, str] = {}
    for name in _CANONICAL_COMPOSE_FILES:
        content = vri._git_show_bytes(repo_root, merge_sha, f"{vri._INFRA_RELATIVE_PATH}/{name}")
        (bundle_dir / name).write_bytes(content)
        file_digests[name] = _sha256_bytes(content)

    env_bytes = env_file.read_bytes()
    (bundle_dir / ".env").write_bytes(env_bytes)
    file_digests[".env"] = _sha256_bytes(env_bytes)

    resolved_bytes = _canonical_json_bytes(resolved_config)
    (bundle_dir / "resolved-compose.json").write_bytes(resolved_bytes)
    file_digests["resolved-compose.json"] = _sha256_bytes(resolved_bytes)

    if readiness_manifest_raw is not None:
        (bundle_dir / "readiness-manifest.json").write_bytes(readiness_manifest_raw)
        file_digests["readiness-manifest.json"] = _sha256_bytes(readiness_manifest_raw)

    bundle_document = {
        "protocol_version": _BUNDLE_PROTOCOL_VERSION,
        "repository": _CANONICAL_REPOSITORY,
        "merge_sha": merge_sha,
        "merge_tree_sha": merge_tree_sha,
        "provenance_run_id": provenance_run_id,
        "provenance_run_attempt": provenance_run_attempt,
        "verified_images": dict(sorted(verified_images.items())),
        "files": dict(sorted(file_digests.items())),
        "readiness_manifest_included": readiness_manifest_raw is not None,
    }
    bundle_bytes = _canonical_json_bytes(bundle_document)
    bundle_document["bundle_digest"] = _sha256_bytes(bundle_bytes)
    (bundle_dir / "bundle_manifest.json").write_bytes(_canonical_json_bytes(bundle_document))
    return bundle_document


def _default_run_subprocess(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=600, check=False)


def deploy_from_bundle(
    *,
    bundle_dir: Path,
    execute: bool,
    run_subprocess: RunSubprocess = _default_run_subprocess,
) -> list[str]:
    """Phase 3 (déployer) — toujours et uniquement depuis ``bundle_dir``.

    Sans ``--execute``, aucune commande Docker mutante n'est lancée :
    seul le plan (la liste des commandes qui SERAIENT exécutées) est
    retourné. Avec ``--execute``, chaque étape doit réussir avant que la
    suivante ne soit lancée — un `pull` en échec n'est jamais suivi d'un
    `up`."""
    bundle_manifest_path = bundle_dir / "bundle_manifest.json"
    if not bundle_manifest_path.is_file():
        raise DeploymentWrapperError(
            f"{bundle_manifest_path} is missing — this is not a bundle produced by "
            "materialize_verified_bundle, or it was tampered with"
        )
    bundle_document = json.loads(bundle_manifest_path.read_bytes())
    for name in _CANONICAL_COMPOSE_FILES:
        expected_digest = bundle_document.get("files", {}).get(name)
        path = bundle_dir / name
        if not path.is_file():
            raise DeploymentWrapperError(f"bundle is missing compose file {name!r}")
        actual_digest = _sha256_bytes(path.read_bytes())
        if actual_digest != expected_digest:
            raise DeploymentWrapperError(
                f"bundle file {name!r} has been modified since materialization "
                f"(sha256 {actual_digest} != recorded {expected_digest}) — a "
                "bundle is deployed byte-identical to what was verified, or not at all"
            )

    compose_args = ["docker", "compose", "--env-file", str(bundle_dir / ".env")]
    for name in _CANONICAL_COMPOSE_FILES:
        compose_args += ["-f", str(bundle_dir / name)]

    plan = [
        " ".join(compose_args + ["pull"]),
        " ".join(compose_args + ["up", "-d", "--remove-orphans"]),
    ]
    if not execute:
        return plan

    pull = run_subprocess(compose_args + ["pull"], bundle_dir)
    if pull.returncode != 0:
        raise DeploymentWrapperError(
            f"docker compose pull failed (exit {pull.returncode}): {pull.stderr.strip()[:1000]}"
        )
    up = run_subprocess(compose_args + ["up", "-d", "--remove-orphans"], bundle_dir)
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
        "par défaut).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
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
            )
        plan = deploy_from_bundle(bundle_dir=args.bundle_dir, execute=args.execute)
    except (DeploymentWrapperError, vri.ReleaseVerificationError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    print(f"BUNDLE_DIGEST={bundle_document['bundle_digest']}")
    for name, ref in sorted(bundle_document["verified_images"].items()):
        print(f"VERIFIED {name}={ref}")
    if args.execute:
        print("DEPLOYED=true")
    else:
        print("DEPLOYED=false (dry run — pass --execute to run the plan below)")
        for step in plan:
            print(f"PLAN: {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
