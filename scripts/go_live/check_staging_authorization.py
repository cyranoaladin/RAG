#!/usr/bin/env python3
"""Dit si une connexion SSH de staging est AUTORISÉE, et dans quel périmètre. Fail-closed.

L'autorisation n'est pas une phrase dans une conversation : c'est un fichier versionné,
fusionné sur `main` par une PR à revue humaine épinglée, et lié par empreinte au plan
d'exécution qu'il autorise. Avant toute commande `ssh`, l'opérateur automatisé lance ce
contrôle ; un seul écart et il n'y a pas de connexion.

    python3 scripts/go_live/check_staging_authorization.py          # code 0 = autorisé
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

AUTORISATION = "docs/reports/go_live/authorizations/staging_ssh_authorization.json"
KIND = "NEXUS-STAGING-SSH-AUTHORIZATION-V1"
HOTE = "nexus-prod"
APPROBATEUR = "abenrhouma"
#: Ce que l'autorisation INTERDIT, quoi qu'il arrive. Absente d'une autorisation, une
#: interdiction la rend invalide : on ne peut pas autoriser « un peu plus » par omission.
INTERDITS_REQUIS = frozenset({
    "current_switch", "production_db_write", "production_db_read", "production_ingestion",
    "public_exposure", "nginx_modification", "dns_modification", "certificate_modification",
    "production_service_restart", "production_secret_read", "docker_prune", "remove_orphans",
    "volume_removal_outside_project", "oauth_revocation", "rclone_reconfiguration",
})
PERIMETRE_REQUIS = {
    "host": HOTE,
    "compose_project": "nexus-staging",
    "bind_address": "127.0.0.1",
    "access": "ssh_tunnel_only",
    "pgvector_container_required": "nexus-staging-pgvector-1",
    "ingestor_image": "pinned_by_digest_no_rebuild",
    #: Le digest exact construit au lot A et consigné sur l'hôte. Une image
    #: différente en service est un refus : le digest n'est pas décoratif.
    "ingestor_image_digest": (
        "sha256:d0134f494a2af2895ebdeb91e55b047cd4774ca607c55e33d4dba1d6c47af8d1"
    ),
}
#: CH3 — la source de l'index de staging cesse d'être une PHRASE pour devenir
#: un périmètre CHIFFRÉ, vérifiable. L'ancienne rédaction libre
#: (« 11 PDF officiels, 353 chunks ») ne décrivait plus le terrain : ni la base
#: de staging, ni la release que le runtime exige. Une chaîne de texte n'est
#: donc plus acceptée ici — seul un objet portant ces clés l'est.
INDEX_SOURCE_REQUIS = {
    "release_id": "production-profile-gate-2026-2027-v2",
    "target_pgvector_container": "nexus-staging-pgvector-1",
    "contracts_version": "0.18.0",
    "contracts_scopes_available": 52,
    "production_database": "forbidden",
}
#: Les quatre comptes que la release scellée DÉCLARE elle-même dans
#: `expected_counts`. Ils ne sont pas estimés ici : ils y sont lus.
INDEX_COUNTS_REQUIS = {
    "subjects": 11,
    "unique_artifacts": 315,
    "placements": 479,
    "unique_chunks": 8268,
}
#: CH6 — l'image epinglee du perimetre (``ingestor_image_digest``) est l'API
#: de retrieval : elle ne porte ni ``httpx`` ni ``ingestion_agents``, et ne
#: peut donc pas executer le point d'entree d'ingestion. CH6 autorise une
#: SECONDE image, construite hors nexus-prod, epinglee par digest, et
#: autorisee pour ce seul point d'entree. Elle ne remplace pas la premiere :
#: les deux coexistent, chacune pour ce qu'elle sait faire, et chacune
#: declare la version de contrats qui est reellement la sienne.
IMAGE_WORKER_REQUISE = {
    "pinning": "pinned_by_digest_no_rebuild",
    "tag_alone_accepted": False,
    "built_off_host": True,
    "build_on_nexus_prod": "forbidden",
    "build_workflow": ".github/workflows/production-image-provenance.yml",
    "image_repository": "ghcr.io/cyranoaladin/rag-multilevel-worker-production",
    "image_digest": (
        "sha256:2ce7533d00e171f47d42a579ad6afe1d8b5d51e91c63f14cf6ae051592109029"
    ),
    "source_commit_sha": "24b28d417d1f99ebe8f37363d75b73a83ffe87ff",
    "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
    "contracts_version": "0.19.0",
    "allowed_entrypoint_module": (
        "ingestor.ingestion_worker.sealed_release_ingestion_cli"
    ),
    "durable_service": False,
    "compose_file_on_host": "forbidden",
    "network": "loopback_only",
    "product_database_access": "forbidden",
}
#: Les deux workers restent hors de portee de cette autorisation. Worker B
#: publierait ; Worker A creerait des jobs par URL, ce que la release scellee
#: ne permet pas (ADR-0056). L'image sait les lancer : l'autorisation, non.
MODULES_WORKER_INTERDITS = (
    "ingestor.ingestion_worker.multilevel_cli",
    "ingestor.ingestion_worker.multilevel_publication_resume_cli",
)

PORTS_LOOPBACK_REQUIS = {
    "ingestor": 18003,
    "pgvector": 15435,
    "prometheus": 19191,
}


def _git(racine: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=racine, capture_output=True, text=True, check=False)


def _ecarts_image_worker(image: object) -> list[str]:
    """Ecarts de l'image worker de staging (CH6). Absente, elle n'autorise rien.

    Une image nommee par tag n'est jamais acceptee : un tag designe une cible
    mouvante, et c'est precisement ce qu'un digest remplace."""
    if image is None:
        return ["image worker de staging absente : aucune image n'est autorisee"]
    if not isinstance(image, dict):
        return ["image worker de staging : objet attendu, pas une phrase"]

    ecarts: list[str] = []
    for cle, attendu in IMAGE_WORKER_REQUISE.items():
        if image.get(cle) != attendu:
            ecarts.append(
                f"image worker : {cle} = {image.get(cle)!r}, attendu {attendu!r}"
            )

    reference = image.get("reference")
    attendue = f"{IMAGE_WORKER_REQUISE['image_repository']}@{IMAGE_WORKER_REQUISE['image_digest']}"
    if reference != attendue:
        ecarts.append(
            f"image worker : reference = {reference!r}, attendu {attendue!r}"
        )
    if isinstance(reference, str) and "@sha256:" not in reference:
        ecarts.append(
            "image worker : reference sans digest — un tag seul n'est jamais "
            "une unite d'execution"
        )

    interdits = image.get("forbidden_entrypoint_modules") or []
    manquants = sorted(set(MODULES_WORKER_INTERDITS) - set(interdits))
    if manquants:
        ecarts.append(f"image worker : modules interdits manquants : {manquants}")

    preuve = image.get("evidence")
    if not isinstance(preuve, dict) or not preuve.get("path") or not preuve.get("sha256"):
        ecarts.append("image worker : preuve de provenance absente ou incomplete")
    return ecarts


def evaluer(document: dict, *, plan_sha256: str) -> list[str]:
    """Écarts d'une autorisation. Liste vide = forme et périmètre valides."""
    ecarts: list[str] = []
    if document.get("kind") != KIND:
        ecarts.append("type d'autorisation inconnu")
    if document.get("granted_by_pull_request_approval_of") != APPROBATEUR:
        ecarts.append("approbateur attendu absent ou différent")
    perimetre = document.get("scope") or {}
    for cle, attendu in PERIMETRE_REQUIS.items():
        if perimetre.get(cle) != attendu:
            ecarts.append(f"périmètre : {cle} = {perimetre.get(cle)!r}, attendu {attendu!r}")
    ports = perimetre.get("loopback_ports") or {}
    if not ports or not all(isinstance(p, int) and 1024 < p < 65536 for p in ports.values()):
        ecarts.append("ports loopback absents ou invalides")
    elif ports != PORTS_LOOPBACK_REQUIS:
        ecarts.append(f"ports loopback non conformes : {ports}, attendu {PORTS_LOOPBACK_REQUIS}")
    source = perimetre.get("staging_index_source")
    if not isinstance(source, dict):
        # L'ancienne rédaction libre passait ici sans rien prouver.
        ecarts.append(
            "staging_index_source doit être un périmètre chiffré, pas une phrase"
        )
    else:
        for cle, attendu in INDEX_SOURCE_REQUIS.items():
            if source.get(cle) != attendu:
                ecarts.append(
                    f"source d'index : {cle} = {source.get(cle)!r}, attendu {attendu!r}"
                )
        comptes = source.get("expected_counts")
        if comptes != INDEX_COUNTS_REQUIS:
            ecarts.append(
                f"source d'index : expected_counts = {comptes!r}, "
                f"attendu {INDEX_COUNTS_REQUIS!r}"
            )
    ecarts.extend(_ecarts_image_worker(perimetre.get("staging_worker_image")))
    manquants = sorted(INTERDITS_REQUIS - set(document.get("forbidden") or []))
    if manquants:
        ecarts.append(f"interdits manquants : {manquants}")
    plan = document.get("execution_plan") or {}
    if plan.get("sha256") != plan_sha256:
        ecarts.append("le plan d'exécution a changé depuis l'autorisation : elle ne le couvre plus")
    if not document.get("stop_conditions") or not document.get("expected_proof"):
        ecarts.append("conditions d'arrêt ou preuve attendue absentes")
    if document.get("expires_after_use") is not True:
        ecarts.append("l'autorisation doit être à usage unique (expires_after_use)")
    return ecarts


def verifier(racine: Path) -> list[str]:
    chemin = racine / AUTORISATION
    if not chemin.is_file():
        return [f"aucune autorisation : {AUTORISATION} absent"]
    try:
        document = json.loads(chemin.read_text(encoding="utf-8"))
    except ValueError as erreur:
        return [f"autorisation illisible : {erreur}"]
    plan_path = racine / str((document.get("execution_plan") or {}).get("path", ""))
    if not plan_path.is_file():
        return ["plan d'exécution cité introuvable"]
    ecarts = evaluer(document, plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest())

    # L'autorisation ne vaut que FUSIONNÉE sur main : une branche locale n'autorise rien.
    if _git(racine, "fetch", "-q", "origin", "main").returncode != 0:
        ecarts.append("origin/main injoignable : impossible de prouver que l'autorisation est fusionnée")
    else:
        sur_main = _git(racine, "show", f"origin/main:{AUTORISATION}")
        if sur_main.returncode != 0 or sur_main.stdout != chemin.read_text(encoding="utf-8"):
            ecarts.append("l'autorisation n'est pas (ou pas à l'identique) sur origin/main")
    if document.get("consumed") is True:
        ecarts.append("autorisation déjà consommée : une nouvelle PR est nécessaire")
    return ecarts


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    ecarts = verifier(Path(__file__).resolve().parents[2])
    print(json.dumps({"ssh_staging_authorized": not ecarts, "ecarts": ecarts}, ensure_ascii=False, indent=2))
    return 1 if ecarts else 0


if __name__ == "__main__":
    raise SystemExit(main())
