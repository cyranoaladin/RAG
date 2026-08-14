#!/usr/bin/env python3
"""Assemble et signe un ``ProductionReadinessManifestV1`` (ADR non encore
numéroté — chantier signing tool, mission H2-B go-live).

**Ce que cet outil refuse structurellement.** Chaque fait exigé par le
contrat est un argument CLI **typé et validé** — jamais un booléen libre
(``--ready true``). Les digests d'evidence locale ne sont jamais fournis "à
l'œil" : pour chaque fichier, l'outil relit le fichier et **recalcule** son
SHA-256 lui-même. Les faits Git (``pr_head_sha``/``merge_sha``/leurs tree
SHA) et de provenance workflow (``run_id``/``run_attempt``/``workflow_path``/
``workflow_ref``) sont **vérifiés en direct** contre l'API GitHub réelle
(``gh api``) — jamais seulement un format hexadécimal plausible. Les images
applicatives (``ingestor``, workers) ne sont plus une saisie opérateur
(ancien ``--application-image``) : elles sont **dérivées** d'un run
GitHub Actions de provenance réel et vérifié
(``.github/workflows/production-image-provenance.yml``, PR #102, via
``--provenance-run-id``/``--provenance-run-attempt``). Les images upstream
(``--upstream-image``, non construites par ce dépôt) restent une entrée
opérateur, mais confrontées au fichier Compose réellement haché dans ce
même manifeste (``--compose-file``) : aucun service omis, aucun service
inventé, digest byte-identique à ce que Compose pin réellement. Le rapport
de couverture H2-B (``--h2b-report-file``, ADR-0042) n'est plus un fichier
opaque simplement haché : il est **parsé et sémantiquement vérifié**
(``h2_coverage_gate_pass`` doit être vrai), et ses six
``input_file_digests`` (``catalog``/``routing``/``rights``/``pii``/
``golden``/``authority``) sont chacun confrontés à un fichier réel
(``--routing-file``/``--rights-file``/``--pii-file``/``--golden-file``,
en plus de ``--catalog-file``/``--authorization-file`` déjà présents) —
plus aucun des six ne peut porter un digest arbitraire sans jamais être
détecté. Lié aussi par digest/commit à l'autorisation, au manifeste
scellé et au commit signés dans ce même manifeste. Le registre de
révocation
(``--revocation-registry-file``) est analysé par le parseur strict partagé
(``nexus_contracts.authorization_revocations``, ADR-0042) — plus de parseur
minimal local. Le run GitHub Actions déclaré (``--run-id``/``--run-
attempt``) doit être un run **réellement terminé avec succès**, bâti sur
le commit signé, et sa tentative courante doit correspondre exactement
(même défaut, même correctif, que la provenance d'image PR #102).

**Clé privée.** Lue depuis un fichier local (``--private-key-file``),
jamais depuis un argument en clair, jamais depuis une variable
d'environnement qui apparaîtrait dans ``/proc/<pid>/environ``. Jamais
journalisée, jamais incluse dans la sortie. Après signature, le manifeste
signé est **immédiatement revérifié** contre l'ancre de confiance publique
avant d'être écrit sur disque — un manifeste dont la propre vérification
échoue n'est jamais produit.

Usage minimal (voir --help pour la liste complète des faits requis) :

    python sign_production_readiness_manifest_cli.py \\
        --pr-number 98 \\
        --pr-head-sha <40hex> --merge-sha <40hex> \\
        --environment production \\
        --private-key-file /path/held/by/operator \\
        --trust-anchor-file governance/trust-anchors/production-readiness-v1.json \\
        --key-id prod-readiness-v1-2026-08-13 \\
        ... (voir --help) \\
        --output readiness-manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "contracts" / "src"))

import deployment_image_inventory as dii  # noqa: E402
from nexus_contracts.authority_artifacts import (  # noqa: E402
    CanonicalArtifactError,
    git_blob_sha1,
    parse_scope_authorization_artifact,
)
from nexus_contracts.authorization_revocations import (  # noqa: E402
    AuthorizationRevocationsError,
    parse_revoked_authorization_ids,
)
from nexus_contracts.h2_coverage_evidence import (  # noqa: E402
    H2CoverageEvidenceError,
    parse_h2_coverage_evidence,
)
from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    parse_production_readiness_trust_anchor,
    sign_production_readiness_manifest,
    verify_production_readiness_manifest,
)
from nexus_contracts.review_binding import (  # noqa: E402
    ReviewBindingError,
    require_challenge_is_bound,
    require_matches_authorization,
    verify_review_binding,
)
from nexus_contracts.review_binding import (  # noqa: E402
    parse_trust_anchor as parse_review_binding_trust_anchor,
)

#: Jamais une entrée opérateur (ancien ``--repository``, Codex, même
#: classe de défaut déjà corrigée dans PR #105) : un opérateur ne peut
#: pas fournir un autre dépôt puis faire vérifier PR/run/workflow/
#: provenance d'image contre ce dépôt alternatif.
_TRUSTED_REPOSITORY = "cyranoaladin/RAG"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OCI = re.compile(r"^sha256:[0-9a-f]{64}$")
#: Identique à ``nexus_contracts.production_readiness._IMAGE_REF`` (jamais
#: de tag ici — c'est le contrat partagé, versionné, qui l'exige ; le
#: changer serait un changement de contrat silencieux, interdit sans ADR).
#: Le fichier Compose réel, lui, pin souvent ``name:tag@sha256:...`` — voir
#: ``_COMPOSE_IMAGE_REF`` plus bas, qui normalise cette forme avant
#: comparaison plutôt que d'assouplir ce que le manifeste accepte.
_IMAGE_REF = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")

#: Forme que peut prendre ``image:`` dans un fichier Compose réel de ce
#: dépôt — tag optionnel avant le digest (``docker-compose.v2.yml`` pin
#: ``pgvector/pgvector:pg16@sha256:...``). Jamais utilisée pour construire
#: un fait du manifeste : seule sert à reconnaître puis retirer le tag
#: avant de comparer au format tagless qu'exige le contrat.
_COMPOSE_IMAGE_REF = re.compile(
    r"^(?P<name>[a-z0-9][a-z0-9._/-]*)(:(?P<tag>[a-zA-Z0-9_][a-zA-Z0-9._-]*))?"
    r"@sha256:(?P<digest>[0-9a-f]{64})$"
)


class SigningToolError(RuntimeError):
    """L'assemblage ou la signature a été refusé — jamais un manifeste
    partiel écrit sur disque."""


def _hex(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise SigningToolError(f"{label} does not match the required format")
    return value


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SigningToolError(f"{label}: cannot read {path}: {exc}") from exc


def _digest_of_file(path: Path, *, label: str) -> str:
    """Ne fait jamais confiance à un digest fourni pour un fichier local :
    le relit et le recalcule toujours lui-même."""
    return hashlib.sha256(_read_bytes(path, label=label)).hexdigest()


def _image_digest_pairs(raw_pairs: list[str], *, label: str) -> dict[str, str]:
    """``--upstream-image name=ref@sha256:...`` répété, jamais un tag.

    Les images applicatives (``ingestor``, workers) ne passent plus par ce
    chemin opérateur libre : elles sont dérivées d'une provenance GitHub
    Actions vérifiée (``deployment_image_inventory.verify_application_
    image_provenance``, PR #102) — voir ``_derive_application_image_
    digests``. Seules les images upstream (non construites par ce dépôt,
    ex. ``pgvector``) restent une entrée opérateur, confrontée au fichier
    Compose réellement haché juste après."""
    result: dict[str, str] = {}
    for pair in raw_pairs:
        if "=" not in pair:
            raise SigningToolError(f"{label} entry {pair!r} must be name=image@sha256:<64hex>")
        name, ref = pair.split("=", 1)
        if _IMAGE_REF.fullmatch(ref) is None:
            raise SigningToolError(
                f"{label} entry {pair!r}: image reference must be pinned as "
                "name@sha256:<64 hex> — a mutable tag is never accepted"
            )
        if name in result:
            raise SigningToolError(f"{label} declares service {name!r} twice")
        result[name] = ref
    if not result:
        raise SigningToolError(f"{label} must declare at least one image")
    return result


def _compose_services(compose_raw: bytes) -> dict[str, dict[str, Any]]:
    """Analyse minimale, strictement locale au fichier fourni.

    N'invoque jamais ``docker compose config`` : la résolution complète
    (overlays, substitution de variables, profiles) exigerait de fournir
    toutes les variables d'environnement de production — y compris celles
    qui n'ont rien à voir avec les images — juste pour extraire des
    références d'image. Correct ici uniquement parce que, vérifié sur
    chaque fichier Compose réellement commité dans ce dépôt, aucune valeur
    ``image:`` n'utilise de substitution ``${...}`` : voir le refus
    ci-dessous, qui fait échouer explicitement l'hypothèse plutôt que de la
    supposer silencieusement vraie."""
    try:
        document = yaml.safe_load(compose_raw)
    except yaml.YAMLError as exc:
        raise SigningToolError(f"compose file is not valid YAML: {exc}") from exc
    services = document.get("services") if isinstance(document, dict) else None
    if not isinstance(services, dict):
        raise SigningToolError("compose file does not declare a top-level 'services' mapping")
    return services


def _verify_image_bindings(
    compose_raw: bytes,
    *,
    application_image_digests: dict[str, str],
    upstream_image_digests: dict[str, str],
) -> None:
    """Confronte les images déclarées par l'opérateur au fichier Compose
    réellement haché dans ce manifeste — jamais deux sources indépendantes
    qui pourraient diverger sans qu'aucun refus ne se produise (Codex P1,
    PR #100)."""
    services = _compose_services(compose_raw)

    upstream_services: dict[str, str] = {}
    application_services: set[str] = set()
    for name, service in services.items():
        if not isinstance(service, dict):
            raise SigningToolError(f"compose service {name!r} is not a mapping")
        if "image" in service:
            image = service["image"]
            if not isinstance(image, str) or "$" in image:
                raise SigningToolError(
                    f"compose service {name!r} declares a templated or "
                    "non-literal 'image' value — this tool only cross-checks "
                    "an already-resolved, literal image reference"
                )
            match = _COMPOSE_IMAGE_REF.fullmatch(image)
            if match is None:
                raise SigningToolError(
                    f"compose service {name!r} declares image {image!r}, which is "
                    "not pinned by digest (name[:tag]@sha256:<64hex>) — an "
                    "unpinned upstream image can never back a production manifest"
                )
            # Le tag (s'il existe) est une commodité de lecture pour un
            # humain qui lit le fichier Compose ; le contrat partagé
            # (ProductionReadinessManifestV1, jamais modifié ici sans ADR)
            # n'accepte que la forme sans tag. On normalise donc le côté
            # Compose avant de comparer, plutôt que d'assouplir ce que le
            # manifeste signe.
            upstream_services[name] = f"{match.group('name')}@sha256:{match.group('digest')}"
        elif "build" in service:
            application_services.add(name)
        # Un service sans `image:` ni `build:` (rare, ex. profil désactivé
        # dans un futur fichier) n'engage aucune image et n'entre dans
        # aucun des deux ensembles.

    declared_upstream = set(upstream_image_digests)
    if declared_upstream != set(upstream_services):
        raise SigningToolError(
            "--upstream-image does not name exactly the compose file's "
            f"image-pinned services (declared={sorted(declared_upstream)}, "
            f"compose={sorted(upstream_services)})"
        )
    for name, declared_ref in upstream_image_digests.items():
        if declared_ref != upstream_services[name]:
            raise SigningToolError(
                f"--upstream-image {name}={declared_ref!r} does not match the "
                f"compose file's pinned image for the same service "
                f"(normalized to {upstream_services[name]!r}, tag ignored)"
            )

    declared_application = set(application_image_digests)
    if declared_application != application_services:
        raise SigningToolError(
            "--application-image does not name exactly the compose file's "
            f"build-based services (declared={sorted(declared_application)}, "
            f"compose={sorted(application_services)})"
        )


def _github_api_get(path: str) -> dict[str, Any]:
    """Seule frontière réseau de cet outil — isolée pour être substituée
    par un double dans les tests, jamais exercée contre le réseau réel en
    suite de tests.

    ``gh api`` (même transport que ``scripts/github/`` et l'ensemble de
    cette mission), pas ``httpx`` : cet outil tourne en contexte
    opérateur/CI où ``gh`` est disponible et déjà authentifié —
    contrairement à ``ingestor.ingestion_control.github_authority``,
    construit spécifiquement pour l'image Docker minimale du worker, qui
    ne l'a pas. Réutilise le transport existant plutôt que d'en inventer un
    second (AGENTS.md)."""
    try:
        completed = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SigningToolError(f"GitHub API call to {path!r} failed: {exc}") from exc
    if completed.returncode != 0:
        raise SigningToolError(
            f"GitHub API call to {path!r} failed (exit {completed.returncode}): "
            f"{completed.stderr.strip()[:500]}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SigningToolError(
            f"GitHub API call to {path!r} returned non-JSON output: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise SigningToolError(f"GitHub API call to {path!r} did not return a JSON object")
    return document


def _verify_git_and_workflow_facts(args: argparse.Namespace) -> tuple[str, str]:
    """Preuve en direct, jamais une simple validation de format (Codex,
    PR #100 §9-11).

    Un SHA 40-hex bien formé n'est pas un fait : il peut être inventé. Ici,
    ``pr_head_sha``/``merge_sha`` sont confrontés à l'état réel de la PR
    sur GitHub (mergée, même commit de merge, même repository des deux
    côtés) ; les tree SHA ne sont plus des arguments CLI acceptés — ils
    sont **dérivés** de la réponse de l'API, jamais affirmés par
    l'opérateur ; ``run_id``/``run_attempt``/``workflow_path`` sont
    confrontés à un run GitHub Actions réel de ce dépôt."""
    pr = _github_api_get(f"repos/{_TRUSTED_REPOSITORY}/pulls/{args.pr_number}")
    if pr.get("merged") is not True:
        raise SigningToolError(
            f"PR #{args.pr_number} is not merged according to the live GitHub "
            "API — a production manifest is never signed for an unmerged change"
        )
    if pr.get("merge_commit_sha") != args.merge_sha:
        raise SigningToolError(
            f"--merge-sha {args.merge_sha!r} does not match the live "
            f"merge_commit_sha {pr.get('merge_commit_sha')!r} of PR #{args.pr_number}"
        )
    head = pr.get("head") or {}
    if head.get("sha") != args.pr_head_sha:
        raise SigningToolError(
            f"--pr-head-sha {args.pr_head_sha!r} does not match the live "
            f"head.sha {head.get('sha')!r} of PR #{args.pr_number}"
        )
    for side, doc in (("base", pr.get("base") or {}), ("head", head)):
        repo_full_name = (doc.get("repo") or {}).get("full_name")
        if repo_full_name != _TRUSTED_REPOSITORY:
            raise SigningToolError(
                f"PR #{args.pr_number} {side} repository is {repo_full_name!r}, "
                f"not {_TRUSTED_REPOSITORY!r} — a fork or cross-repository PR is "
                "never accepted by this tool"
            )

    pr_head_commit = _github_api_get(f"repos/{_TRUSTED_REPOSITORY}/git/commits/{args.pr_head_sha}")
    merge_commit = _github_api_get(f"repos/{_TRUSTED_REPOSITORY}/git/commits/{args.merge_sha}")
    pr_head_tree_sha = (pr_head_commit.get("tree") or {}).get("sha")
    merge_tree_sha = (merge_commit.get("tree") or {}).get("sha")
    if not isinstance(pr_head_tree_sha, str) or _HEX40.fullmatch(pr_head_tree_sha) is None:
        raise SigningToolError(
            f"GitHub did not return a valid tree sha for commit {args.pr_head_sha!r}"
        )
    if not isinstance(merge_tree_sha, str) or _HEX40.fullmatch(merge_tree_sha) is None:
        raise SigningToolError(
            f"GitHub did not return a valid tree sha for commit {args.merge_sha!r}"
        )

    run = _github_api_get(f"repos/{_TRUSTED_REPOSITORY}/actions/runs/{args.run_id}")
    if run.get("path") != args.workflow_path:
        raise SigningToolError(
            f"--workflow-path {args.workflow_path!r} does not match the live "
            f"workflow path {run.get('path')!r} of run {args.run_id}"
        )
    run_repo_full_name = (run.get("repository") or {}).get("full_name")
    if run_repo_full_name != _TRUSTED_REPOSITORY:
        raise SigningToolError(
            f"run {args.run_id} belongs to {run_repo_full_name!r}, not "
            f"{_TRUSTED_REPOSITORY!r}"
        )
    head_branch = run.get("head_branch")
    expected_ref = f"refs/heads/{head_branch}" if head_branch else None
    if expected_ref != args.workflow_ref:
        raise SigningToolError(
            f"--workflow-ref {args.workflow_ref!r} does not match the live run's "
            f"head_branch (expected {expected_ref!r})"
        )
    # Codex, PR #100 §8 : un run bien identifié par chemin/branche n'est
    # pas pour autant un run *réussi*, ni un run bâti sur le commit
    # promu. Même défaut déjà corrigé dans `deployment_image_inventory.
    # verify_application_image_provenance` (PR #102) : reproduit ici à
    # l'identique.
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise SigningToolError(
            f"run {args.run_id} is not a successfully completed run "
            f"(status={run.get('status')!r}, conclusion={run.get('conclusion')!r})"
        )
    if run.get("head_sha") != args.merge_sha:
        raise SigningToolError(
            f"run {args.run_id} built head_sha {run.get('head_sha')!r}, not the "
            f"commit being signed ({args.merge_sha!r})"
        )
    # `run_attempt` sur l'endpoint général reflète l'attempt COURANTE (la
    # plus récente) de ce run_id — si le workflow a été rejoué depuis,
    # cette valeur a changé et ce refus se déclenche : jamais une
    # tentative périmée acceptée silencieusement (même bug que celui
    # trouvé et corrigé dans PR #102, reproduit ici à l'identique — cet
    # outil appelait déjà l'endpoint `/attempts/<n>` mais n'exploitait
    # jamais sa réponse ni ne croisait `run_attempt` du run général).
    if run.get("run_attempt") != args.run_attempt:
        raise SigningToolError(
            f"run {args.run_id}'s current attempt is {run.get('run_attempt')!r}, not "
            f"the attempt being attested ({args.run_attempt!r}) — the run was "
            "re-run since this attempt, or the wrong attempt was named"
        )
    # Confirme aussi, via l'endpoint dédié, que cette tentative précise
    # existe réellement pour ce run.
    _github_api_get(
        f"repos/{_TRUSTED_REPOSITORY}/actions/runs/{args.run_id}/attempts/{args.run_attempt}"
    )

    return pr_head_tree_sha, merge_tree_sha


def _derive_application_image_digests(
    args: argparse.Namespace, *, merge_sha: str, merge_tree_sha: str
) -> dict[str, str]:
    """Dérive les digests d'images applicatives depuis un run GitHub Actions
    de provenance réel et vérifié (PR #102) — jamais depuis une saisie
    opérateur libre (ancien ``--application-image``, Codex, instruction
    humaine PR #100 §12).

    Ancrée sur ``merge_sha``/``merge_tree_sha`` : c'est le commit qui
    atterrit réellement sur ``main`` que le workflow de provenance doit
    avoir construit, pas le head de PR avant merge."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            return dii.verify_application_image_provenance(
                repository=_TRUSTED_REPOSITORY,
                source_commit_sha=merge_sha,
                source_tree_sha=merge_tree_sha,
                provenance_run_id=args.provenance_run_id,
                provenance_run_attempt=args.provenance_run_attempt,
                github_api_get=_github_api_get,
                download_artifact=dii.make_download_artifact_via_gh(repository=_TRUSTED_REPOSITORY),
                work_dir=Path(tmp),
            )
        except dii.DeploymentImageInventoryError as exc:
            raise SigningToolError(f"application image provenance refused: {exc}") from exc


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    # Identité du dépôt et de la revue.
    p.add_argument("--pr-number", type=int, required=True)
    p.add_argument("--pr-head-sha", required=True,
                    help="Verified live against GitHub (repos/<repo>/pulls/<pr-number>) "
                         "before use — an operator-asserted value that mismatches the "
                         "PR's real head is refused.")
    p.add_argument("--merge-sha", required=True,
                    help="Verified live against GitHub's merge_commit_sha for this PR "
                         "before use.")
    p.add_argument("--environment", choices=["production"], default="production")

    # Digests des preuves de gouvernance : chemins vers des fichiers réels,
    # jamais des valeurs affirmées. Chacun est relu et rehashé ici.
    p.add_argument("--review-binding-file", type=Path, required=True)
    p.add_argument("--review-binding-trust-anchor-file", type=Path, required=True,
                    help="Ancre publique NEXUS-REVIEW-BINDING-V1 (ADR-0035) utilisée "
                         "pour vérifier la signature du reçu de revue avant de le "
                         "faire entrer dans ce manifeste — distincte de l'ancre "
                         "production-readiness.")
    p.add_argument("--authorization-file", type=Path, required=True)
    p.add_argument("--trust-anchor-file", type=Path, required=True,
                    help="L'ancre PRODUCTION dont le digest entre dans le manifeste "
                         "(distincte de celle utilisée pour vérifier LA signature de ce manifeste).")
    p.add_argument("--revocation-registry-file", type=Path, required=True)
    p.add_argument("--catalog-file", type=Path, required=True)
    p.add_argument("--sealed-manifest-file", type=Path, required=True)
    p.add_argument("--h2b-report-file", type=Path, required=True,
                    help="NEXUS-H2-COVERAGE-EVIDENCE-V1 (ADR-0042) — parsé et "
                         "sémantiquement vérifié (h2_coverage_gate_pass doit être "
                         "vrai), jamais seulement haché comme un fichier opaque.")
    p.add_argument("--routing-file", type=Path, required=True,
                    help="Fichier réel correspondant à h2b_report.input_file_"
                         "digests['routing'] — relu et rehaché, jamais un digest "
                         "arbitraire pris au mot.")
    p.add_argument("--rights-file", type=Path, required=True,
                    help="Fichier réel correspondant à h2b_report.input_file_"
                         "digests['rights'].")
    p.add_argument("--pii-file", type=Path, required=True,
                    help="Fichier réel correspondant à h2b_report.input_file_"
                         "digests['pii'].")
    p.add_argument("--golden-file", type=Path, required=True,
                    help="Fichier réel correspondant à h2b_report.input_file_"
                         "digests['golden'].")

    # Unité de déploiement.
    p.add_argument("--upstream-image", action="append", default=[], metavar="name=ref@sha256:...")
    p.add_argument("--compose-file", type=Path, required=True)
    p.add_argument("--provenance-run-id", type=int, required=True,
                    help="Run GitHub Actions de "
                         ".github/workflows/production-image-provenance.yml (PR #102) "
                         "dont les digests d'images applicatives (ingestor, workers) "
                         "sont dérivés — jamais une saisie opérateur libre.")
    p.add_argument("--provenance-run-attempt", type=int, required=True)

    # Provenance de l'émission.
    p.add_argument("--workflow-path", required=True)
    p.add_argument("--workflow-ref", required=True)
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--run-attempt", type=int, required=True)

    # Signature.
    p.add_argument("--key-id", required=True)
    p.add_argument("--private-key-file", type=Path, required=True,
                    help="Fichier local contenant la graine Ed25519 (64 hex). "
                         "Jamais un argument en clair, jamais une variable d'environnement.")
    p.add_argument("--verification-trust-anchor-file", type=Path, required=True,
                    help="Ancre publique utilisée pour REVÉRIFIER immédiatement la "
                         "signature produite (normalement le même fichier que "
                         "governance/trust-anchors/production-readiness-v1.json).")

    p.add_argument("--output", type=Path, required=True)
    return p


def assemble_and_sign(args: argparse.Namespace) -> ProductionReadinessManifestV1:
    pr_head_sha = _hex(args.pr_head_sha, _HEX40, "pr_head_sha")
    merge_sha = _hex(args.merge_sha, _HEX40, "merge_sha")
    pr_head_tree_sha, merge_tree_sha = _verify_git_and_workflow_facts(args)

    review_binding_raw = _read_bytes(args.review_binding_file, label="review_binding")
    authorization_raw = _read_bytes(args.authorization_file, label="authorization")
    review_binding_digest = hashlib.sha256(review_binding_raw).hexdigest()
    authorization_digest = hashlib.sha256(authorization_raw).hexdigest()
    trust_anchor_digest = _digest_of_file(args.trust_anchor_file, label="trust_anchor")
    revocation_registry_raw = _read_bytes(args.revocation_registry_file, label="revocation_registry")
    revocation_registry_digest = hashlib.sha256(revocation_registry_raw).hexdigest()
    catalog_digest = _digest_of_file(args.catalog_file, label="catalog")
    sealed_manifest_digest = _digest_of_file(args.sealed_manifest_file, label="sealed_manifest")
    h2b_report_raw = _read_bytes(args.h2b_report_file, label="h2b_report")
    h2b_report_digest = hashlib.sha256(h2b_report_raw).hexdigest()
    compose_raw = _read_bytes(args.compose_file, label="compose")
    compose_digest = hashlib.sha256(compose_raw).hexdigest()

    # Un digest prouve que le fichier n'a pas changé depuis qu'il a été lu
    # ici — pas qu'il décrit une revue humaine réelle, non expirée, non
    # révoquée, portant sur *cette* autorisation précise. Sans ce bloc,
    # n'importe quels octets acceptés par le hachage seul deviendraient un
    # fait "review_binding_digest" dans un manifeste signé production.
    try:
        review_binding_anchor = parse_review_binding_trust_anchor(
            _read_bytes(args.review_binding_trust_anchor_file, label="review_binding_trust_anchor")
        )
        binding = verify_review_binding(
            review_binding_raw,
            trust_anchor=review_binding_anchor,
            environment="production",
            now=datetime.now(UTC),
        )
        authorization = parse_scope_authorization_artifact(authorization_raw)
        require_matches_authorization(
            binding,
            authorization_id=authorization.authorization_id,
            authorization_bytes=authorization_raw,
            authorization_git_blob_sha1=git_blob_sha1(authorization_raw),
            expected_repository=_TRUSTED_REPOSITORY,
        )
        require_challenge_is_bound(binding)
    except (ReviewBindingError, CanonicalArtifactError) as exc:
        raise SigningToolError(f"review binding does not authorize this authorization: {exc}") from exc

    now = datetime.now(UTC)
    if not (authorization.valid_from <= now <= authorization.valid_until):
        raise SigningToolError(
            f"authorization {authorization.authorization_id!r} is outside its "
            f"validity window ({authorization.valid_from} .. {authorization.valid_until}, "
            f"now={now}) — a manifest is never signed for an authorization that "
            "is not currently valid"
        )
    try:
        revoked = parse_revoked_authorization_ids(
            revocation_registry_raw, origin="revocation_registry"
        )
    except AuthorizationRevocationsError as exc:
        raise SigningToolError(f"revocation_registry failed strict validation: {exc}") from exc
    if authorization.authorization_id in revoked:
        raise SigningToolError(
            f"authorization {authorization.authorization_id!r} appears in the "
            "revocation registry — a revoked authorization is never signed "
            "into a production readiness manifest"
        )

    # ADR-0042 : le rapport de couverture H2-B n'est plus un fichier opaque
    # simplement haché — il est analysé et son verdict est exigé passant.
    # Sans ce bloc, un `h2b_report_digest` prouverait seulement qu'un
    # fichier n'a pas changé, jamais qu'il décrit une campagne de
    # gouvernance H2-B réellement réussie.
    try:
        h2_evidence = parse_h2_coverage_evidence(h2b_report_raw)
    except H2CoverageEvidenceError as exc:
        raise SigningToolError(f"h2b_report failed semantic verification: {exc}") from exc
    if not h2_evidence.h2_coverage_gate_pass:
        raise SigningToolError(
            "h2b_report's own h2_coverage_gate_pass is false — a production "
            "manifest is never signed for a non-passing H2-B coverage gate"
        )
    # Lie la preuve H2 à *cette même* autorisation, *ce même* fichier
    # d'autorité et *ce même* catalogue/manifeste scellé — sans ces
    # croisements, un rapport H2 authentique mais décrivant une toute
    # autre campagne (autre autorisation, autre catalogue) passerait
    # inaperçu : chaque digest, pris isolément, prouve seulement qu'un
    # fichier n'a pas changé depuis sa lecture, jamais qu'il appartient à
    # la même campagne que les autres (Codex, précédent établi PR #100).
    if h2_evidence.authorization_id != authorization.authorization_id:
        raise SigningToolError(
            f"h2b_report authorization_id {h2_evidence.authorization_id!r} does not "
            f"match --authorization-file's authorization_id "
            f"{authorization.authorization_id!r}"
        )
    if h2_evidence.input_file_digests.get("authority") != authorization_digest:
        raise SigningToolError(
            "h2b_report's authority digest does not match the sha256 of "
            "--authorization-file — the H2 evidence does not vouch for this "
            "exact authorization artifact"
        )
    if h2_evidence.input_file_digests.get("catalog") != catalog_digest:
        raise SigningToolError(
            "h2b_report's catalog digest does not match the sha256 of "
            "--catalog-file — the H2 evidence does not vouch for this exact catalog"
        )
    # Codex, PR #100 §10 : le contrat ADR-0042 exige six clés dans
    # `input_file_digests` (catalog/routing/rights/pii/golden/authority)
    # — seules catalog et authority étaient confrontées à un fichier réel
    # ici ; les quatre autres pouvaient porter un digest arbitraire sans
    # jamais être détectées. Fermé en exigeant les quatre fichiers réels
    # correspondants, relus et rehachés (jamais un digest pris au mot).
    for evidence_key, path_arg, cli_flag in (
        ("routing", args.routing_file, "--routing-file"),
        ("rights", args.rights_file, "--rights-file"),
        ("pii", args.pii_file, "--pii-file"),
        ("golden", args.golden_file, "--golden-file"),
    ):
        real_digest = _digest_of_file(path_arg, label=evidence_key)
        if h2_evidence.input_file_digests.get(evidence_key) != real_digest:
            raise SigningToolError(
                f"h2b_report's {evidence_key} digest does not match the sha256 of "
                f"{cli_flag} — the H2 evidence does not vouch for this exact "
                f"{evidence_key} file"
            )
    if h2_evidence.manifest_sha256 != sealed_manifest_digest:
        raise SigningToolError(
            "h2b_report's manifest_sha256 does not match the sha256 of "
            "--sealed-manifest-file — the H2 evidence does not vouch for this "
            "exact sealed manifest"
        )
    if h2_evidence.git_commit != merge_sha:
        raise SigningToolError(
            f"h2b_report git_commit {h2_evidence.git_commit!r} does not match "
            f"--merge-sha {merge_sha!r} — an H2 pass produced for a different "
            "commit is never used to sign this release"
        )

    application_image_digests = _derive_application_image_digests(
        args, merge_sha=merge_sha, merge_tree_sha=merge_tree_sha
    )
    upstream_image_digests = _image_digest_pairs(args.upstream_image, label="--upstream-image")
    _verify_image_bindings(
        compose_raw,
        application_image_digests=application_image_digests,
        upstream_image_digests=upstream_image_digests,
    )

    release_tag = f"release/rag/{datetime.now(UTC):%Y%m%d}-{merge_sha[:12]}"

    try:
        manifest = ProductionReadinessManifestV1(
            protocol_version="NEXUS-PRODUCTION-READINESS-V1",
            repository=_TRUSTED_REPOSITORY,
            pr_number=args.pr_number,
            pr_head_sha=pr_head_sha,
            pr_head_tree_sha=pr_head_tree_sha,
            merge_sha=merge_sha,
            merge_tree_sha=merge_tree_sha,
            release_tag=release_tag,
            environment=args.environment,
            review_binding_digest=review_binding_digest,
            authorization_digest=authorization_digest,
            trust_anchor_digest=trust_anchor_digest,
            revocation_registry_digest=revocation_registry_digest,
            catalog_digest=catalog_digest,
            sealed_manifest_digest=sealed_manifest_digest,
            h2b_report_digest=h2b_report_digest,
            gate_result="pass",
            application_image_digests=application_image_digests,
            upstream_image_digests=upstream_image_digests,
            compose_digest=compose_digest,
            workflow_path=args.workflow_path,
            workflow_ref=args.workflow_ref,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            issued_at=datetime.now(UTC),
            key_id=args.key_id,
        )
    except Exception as exc:  # noqa: BLE001 - frontière CLI, jamais silencieuse
        raise SigningToolError(f"manifest assembly refused: {exc}") from exc
    return manifest


_INPUT_PATH_ARGS = (
    "trust_anchor_file",
    "review_binding_file",
    "review_binding_trust_anchor_file",
    "authorization_file",
    "revocation_registry_file",
    "catalog_file",
    "sealed_manifest_file",
    "h2b_report_file",
    "routing_file",
    "rights_file",
    "pii_file",
    "golden_file",
    "compose_file",
    "private_key_file",
    "verification_trust_anchor_file",
)


def _reject_output_aliasing_an_input(args: argparse.Namespace) -> None:
    """``--output`` ne peut jamais résoudre vers un fichier d'entrée.

    Sans ce contrôle, une erreur de sélection de chemin ferait écrire le
    manifeste JSON par-dessus la graine de signature locale (ou toute
    autre preuve d'entrée), détruisant un secret de production pour une
    invocation par ailleurs réussie.

    Deux contrôles distincts, aucun ne subsume l'autre :
    ``Path.resolve()`` (chemin identique, lien symbolique) compare des
    chaînes de chemin canoniques — mais un lien physique (``ln``, pas
    ``ln -s``) est une seconde entrée de répertoire vers le **même
    inode**, sans jamais être un « lien » que ``resolve()`` puisse
    suivre : ses deux chemins se résolvent chacun vers eux-mêmes,
    identiques en apparence. Codex, PR #100 : le commentaire précédent
    affirmait détecter ce cas sans jamais le faire réellement. Corrigé
    par une comparaison d'inode (``os.path.samefile``, st_dev/st_ino)
    quand les deux fichiers existent déjà — la seule situation où un
    lien physique peut exister."""
    output_resolved = args.output.resolve(strict=False)
    output_exists = args.output.exists()
    for name in _INPUT_PATH_ARGS:
        candidate: Path = getattr(args, name)
        if output_resolved == candidate.resolve(strict=False):
            raise SigningToolError(
                f"--output resolves to the same file as --{name.replace('_', '-')} "
                f"({candidate}) — refusing to overwrite a signing input"
            )
        if output_exists and candidate.exists() and os.path.samefile(args.output, candidate):
            raise SigningToolError(
                f"--output is a hard link to the same file as --{name.replace('_', '-')} "
                f"({candidate}) — refusing to overwrite a signing input"
            )


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        _reject_output_aliasing_an_input(args)
        manifest = assemble_and_sign(args)

        # Pas d'effacement mémoire déterministe ici, et ce commentaire ne
        # le prétend plus (Codex, PR #100) : `sign_production_readiness_
        # manifest` (contrat partagé, packages/contracts) exige un `str`,
        # immuable en Python — réaffecter le nom local à une chaîne de
        # zéros crée un NOUVEL objet et ne touche jamais la mémoire de
        # l'original, qui reste présente jusqu'au ramasse-miettes (et
        # au-delà, la page mémoire sous-jacente n'étant elle-même pas
        # garantie effacée). Une vraie garantie exigerait soit de changer
        # la signature du contrat partagé pour accepter un tampon
        # mutable (hors périmètre de ce lot, cf. Escalade AGENTS.md — ce
        # contrat a d'autres appelants), soit un verrouillage mémoire
        # spécifique à l'OS, disproportionné pour un CLI opérateur. La
        # frontière de sécurité réelle est la durée de vie du process et
        # les protections mémoire du système, pas ce code.
        private_key_hex = args.private_key_file.read_text(encoding="utf-8").strip()
        signed = sign_production_readiness_manifest(
            manifest, private_key_hex=private_key_hex, key_id=args.key_id
        )

        verification_anchor = parse_production_readiness_trust_anchor(
            args.verification_trust_anchor_file.read_bytes()
        )
        verify_production_readiness_manifest(
            signed.canonical_bytes(),
            trust_anchor=verification_anchor,
            environment=args.environment,
        )
    except (SigningToolError, ProductionReadinessError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    args.output.write_bytes(signed.canonical_bytes())
    args.output.chmod(0o600)
    print(f"MANIFEST_DIGEST={signed.manifest_digest}")
    print(f"KEY_ID={signed.key_id}")
    print(f"OUTPUT={args.output}")
    print("SIGNED_MANIFEST_VERIFY_ROUNDTRIP=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
