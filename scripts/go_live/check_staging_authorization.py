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
    #: CS — le digest change une seconde fois, et pour la meme raison de
    #: fond : une image epinglee conserve exactement son contenu, donc
    #: fusionner du code sur main ne la met pas a jour. L'image de CH7B
    #: precedait ADR-0058 ; elle porte l'ancien modele de revue vivante et
    #: refuserait toute autorisation scellee.
    "image_digest": (
        "sha256:431264a02e2e2a5484cef7d5ac620a3aa7fa16f66be1497fde886dfb7f83ccd8"
    ),
    "source_commit_sha": "39f1314ec3576eb72a5ad0650938eb64252be3a7",
    #: L'image doit porter ADR-0058 : c'est ce qui la distingue de celle
    #: qu'elle remplace, et c'est verifiable dans ses octets.
    "carries_adr_0058": True,
    "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
    "contracts_version": "0.19.0",
    "allowed_entrypoint_module": (
        "ingestor.ingestion_worker.sealed_release_ingestion_cli"
    ),
    "durable_service": False,
    "compose_file_on_host": "forbidden",
    #: CT — clarification, pas elargissement. « loopback_only » decrivait
    #: l'EXPOSITION (aucun port publie, aucune ecoute au-dela de 127.0.0.1)
    #: et n'a jamais decrit la SORTIE. Le worker emet deja un HTTPS sortant
    #: vers l'API GitHub pour relire l'artefact approuve ; l'ancienne
    #: formulation laissait croire le contraire, et l'ambiguite d'une garde
    #: est un defaut.
    "network": "no_inbound_exposure",
    "product_database_access": "forbidden",
    #: La garde ajoutee par CH7A : l'image REELLEMENT en cours doit etre
    #: celle que le manifeste signe nomme. L'autorisation la declare pour
    #: qu'un futur amendement ne puisse pas la faire disparaitre en silence.
    "runtime_image_binding_guard": "NEXUS_ACTUAL_WORKER_IMAGE",
}

#: Le digest que CH7B remplace. Le nommer ici n'est pas decoratif : une
#: autorisation qui redeviendrait celle de CH6 serait refusee par la garde
#: ci-dessous, au lieu de passer inapercue.
IMAGE_WORKER_REMPLACEE = (
    "sha256:1fb70485f94a539c83142a372b24fa657daea398524173c5cdb5a3d2a9c38efb"
)

#: Les digests definitivement ecartes. Y revenir n'est jamais un retour en
#: arriere neutre : chacun precede une garde que le suivant apporte.
DIGESTS_ECARTES = (
    # CH6 : construite avant CQ/CR/CH7A — ni readiness de repetition, ni
    # garde d'identite d'image.
    "sha256:2ce7533d00e171f47d42a579ad6afe1d8b5d51e91c63f14cf6ae051592109029",
    # CH7B : construite avant ADR-0058 — ancien modele de revue vivante.
    "sha256:1fb70485f94a539c83142a372b24fa657daea398524173c5cdb5a3d2a9c38efb",
)
#: CT — le jeton GitHub ephemere. Chaque cle est exigee a l'identique :
#: une permission en plus, une duree en plus, ou une valeur passee par
#: l'environnement plutot que par un fichier, et l'autorisation est refusee.
JETON_EPHEMERE_REQUIS = {
    "environment": "staging cloisonne uniquement",
    "token_kind": "fine_grained_personal_access_token",
    "token_permissions": {"contents": "read", "metadata": "read"},
    "token_repository_selection": ["cyranoaladin/RAG"],
    "max_lifetime_days": 1,
    "api_base_override_forbidden": True,
    "tls_verification_disabled_forbidden": True,
}

#: L'injection : par fichier, jamais par l'environnement ni par un argument.
INJECTION_REQUISE = {
    "mechanism": "fichier monte en lecture seule",
    "env_var": "NEXUS_GITHUB_TOKEN_FILE",
    "value_in_environment": False,
    "value_in_command_arguments": False,
    "file_mode": "0600",
    "directory_mode": "0700",
}

#: Les quatre gestes de fin d'operation. En omettre un laisserait un acces
#: ouvert apres la fin de ce qui le justifiait.
FIN_OPERATION_REQUISE = (
    "arret des processus concernes",
    "retrait du montage",
    "suppression de la copie temporaire",
    "revocation du jeton dedie par son detenteur",
)


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


def _ecarts_jeton_ephemere(jeton: object) -> list[str]:
    """Ecarts du jeton GitHub ephemere (CT). Absent, il n'autorise rien.

    Un jeton de lecture dont une seule dimension deborde — une permission de
    plus, un depot de plus, une duree plus longue, une valeur passee par
    l'environnement — n'est plus le jeton qui a ete autorise."""
    if jeton is None:
        return []  # l'amendement CT n'est pas en vigueur : rien a verifier
    if not isinstance(jeton, dict):
        return ["jeton ephemere : objet attendu, pas une phrase"]

    ecarts: list[str] = []
    for cle, attendu in JETON_EPHEMERE_REQUIS.items():
        if jeton.get(cle) != attendu:
            ecarts.append(
                f"jeton ephemere : {cle} = {jeton.get(cle)!r}, attendu {attendu!r}"
            )

    injection = jeton.get("injection")
    if not isinstance(injection, dict):
        ecarts.append("jeton ephemere : injection absente")
    else:
        for cle, attendu in INJECTION_REQUISE.items():
            if injection.get(cle) != attendu:
                ecarts.append(
                    f"jeton ephemere : injection.{cle} = {injection.get(cle)!r}, "
                    f"attendu {attendu!r}"
                )

    base = jeton.get("database")
    if not isinstance(base, dict) or base.get("role") != "ingestion_control_app":
        ecarts.append(
            "jeton ephemere : le worker doit tourner sous ingestion_control_app"
        )
    elif base.get("authority_dsn_in_worker") is not False:
        ecarts.append(
            "jeton ephemere : le DSN d'autorite n'a rien a faire dans le worker"
        )

    fin = jeton.get("end_of_operation") or []
    manquants = sorted(set(FIN_OPERATION_REQUISE) - set(fin))
    if manquants:
        ecarts.append(f"jeton ephemere : fin d'operation incomplete : {manquants}")

    interdits = jeton.get("token_must_not_carry") or []
    if not interdits:
        ecarts.append(
            "jeton ephemere : l'autorisation doit nommer ce que le jeton ne "
            "porte pas — un perimetre qui ne dit que ce qu'il permet se lit mal"
        )
    return ecarts


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

    if image.get("image_digest") in DIGESTS_ECARTES:
        ecarts.append(
            f"image worker : le digest {image.get('image_digest')} a ete ecarte "
            "et ne peut plus etre autorise — chacun precede une garde que son "
            "successeur apporte"
        )
    if image.get("supersedes_image_digest") != IMAGE_WORKER_REMPLACEE:
        ecarts.append(
            "image worker : l'amendement doit nommer le digest qu'il remplace"
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
    ecarts.extend(_ecarts_jeton_ephemere(perimetre.get("ephemeral_github_read_token")))
    manquants = sorted(INTERDITS_REQUIS - set(document.get("forbidden") or []))
    if manquants:
        ecarts.append(f"interdits manquants : {manquants}")
    plan = document.get("execution_plan") or {}
    if plan.get("sha256") != plan_sha256:
        ecarts.append("le plan d'exécution a changé depuis l'autorisation : elle ne le couvre plus")
    if not document.get("stop_conditions") or not document.get("expected_proof"):
        ecarts.append("conditions d'arrêt ou preuve attendue absentes")
    declaration = document.get("authorization_statement") or ""
    for exigence in (
        "staging cloisonne uniquement",
        # La declaration doit nommer le commit de BUILD de l'image autorisee,
        # pas celui de l'amendement qui l'autorise : sans quoi chaque commit
        # documentaire imposerait une reconstruction.
        "39f1314ec3576eb72a5ad0650938eb64252be3a7",
        "ni build sur nexus-prod",
        "ni tag non epingle",
        "ni Worker B",
        "ni ecriture DB production",
        "ni current switch",
        "ni exposition publique",
    ):
        if exigence not in declaration:
            ecarts.append(
                f"declaration d'autorisation : mention manquante {exigence!r}"
            )
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


# ── CY : la publication V3 sur le staging cloisonné ─────────────────────
#
# L'autorisation de base ouvre l'accès et interdit Worker B, la base produit,
# les migrations et l'adoption. Elle reste telle quelle. Une autorisation
# gouvernée DISTINCTE, liée à la base et à son plan par empreinte, ouvre ces
# opérations — chacune sur sa cible exacte : hôte, projet, conteneur, base,
# schéma, rôle et release. Ce qui n'y est pas nommé reste refusé.

AUTORISATION_V3 = "docs/reports/go_live/authorizations/staging_v3_publication_authorization.json"
KIND_V3 = "NEXUS-STAGING-V3-PUBLICATION-AUTHORIZATION-V1"
PLAN_V3 = "docs/runbooks/staging_v3_publication_EXECUTION_PLAN.md"
DEPOT_IMAGE = "ghcr.io/cyranoaladin/rag-multilevel-worker-production"

RELEASE_V3 = {
    "release_id": "production-profile-gate-2026-2027-v3",
    "release_dir": (
        "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v3/"
        "release-f8fb983d04f4b7c1/profile_gate"
    ),
    "release_manifest_sha256": (
        "c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16"
    ),
    "expected_counts": {"subjects": 11, "unique_artifacts": 315, "placements": 479, "unique_chunks": 8268},
    "served_currentness": "official_snapshot",
}
PREDECESSEUR_V2 = {
    "release_id": "production-profile-gate-2026-2027-v2",
    "release_manifest_sha256": (
        "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
    ),
    "use": "attribution_backfill_and_adoption_only",
    "publication": "forbidden",
}
CIBLES_V3 = {
    "host": HOTE,
    "compose_project": "nexus-staging",
    "container": "nexus-staging-pgvector-1",
    "database": "ragdb",
    "product_schema": "public",
    "control_schema": "ingestion_control",
    "roles": {
        "migrator": "superutilisateur du conteneur staging, via les seuls runners canoniques",
        "worker": "ingestion_control_app",
        "attestor": "ingestion_control_attestor",
        "product_writer": "rag_publisher",
        "product_reader": "rag_reader",
    },
    "worker_never_receives": [
        "identifiants du migrateur",
        "DSN ingestion_control_authority",
        "DSN ingestion_control_attestor",
    ],
}

_COMMUNE = {
    "host": HOTE,
    "compose_project": "nexus-staging",
    "container": "nexus-staging-pgvector-1",
    "database": "ragdb",
}
_V3 = RELEASE_V3["release_id"]
OPERATIONS_V3: dict[str, dict] = {
    "preflight_measurement": {
        "cible": {**_COMMUNE, "mode": "read_only"},
        "limite": "mesures en lecture : têtes de migration réelles, comptes, disque",
    },
    "backup_before_migration": {
        "cible": {**_COMMUNE, "command": "pg_dump", "destination": "/srv/nexus-staging/backups"},
        "limite": "sauvegarde de ragdb avant toute migration ; jamais supprimée par ce plan",
    },
    "product_migrations": {
        "cible": {**_COMMUNE, "schema": "public", "runner": "services/rag-engine/infra/scripts/apply_pgvector_migrations.sh", "target_head": "005"},
        "limite": "migrations manquantes appliquées dans l'ordre par le runner canonique",
    },
    "control_migrations": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "runner": "services/rag-engine/infra/scripts/bootstrap_ingestion_control_schema.sh", "target_head": "018"},
        "limite": "migrations manquantes appliquées dans l'ordre par le runner canonique",
    },
    "model_artifact_install": {
        "cible": {
            "host": HOTE, "compose_project": "nexus-staging",
            "destination": "/srv/nexus-staging/models/e5-large-prerentree-2026-2027-20260828-materialise",
            "inventory_sha256": "58ad18dbb0a154c5a10320de9efdf81944f8b1ee1a01cc7f077e8b86b364dbc6",
        },
        "limite": "seulement si l'artefact E5 de l'hôte ne porte pas l'inventaire que V3 déclare ; copie vérifiée, rien d'écrasé",
    },
    "readiness_manifest_install": {
        "cible": {
            "host": HOTE, "compose_project": "nexus-staging",
            "destination": "/srv/nexus-staging/readiness",
            "manifests": ["staging-readiness-v3.json", "staging-readiness-v2-backfill.json"],
        },
        "limite": "dépôt des manifestes signés localement par le détenteur de la clé ; vérifiés contre l'ancre avant usage",
    },
    "transfer_manifest_v3": {
        "cible": {**_COMMUNE, "mode": "read_only", "artifact_store": "/srv/nexus-staging/artifact-store", "release_id": _V3},
        "limite": "rehachage en lecture des 315 objets du magasin sous l'identité V3",
    },
    "sealed_ingestion_v3": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "entrypoint": "ingestor.ingestion_worker.sealed_release_ingestion_cli", "control_role": "ingestion_control_app", "release_id": _V3},
        "limite": "seulement si aucune ligne V2 n'est acquise ; sinon rattrapage puis adoption",
    },
    "attribution_backfill_v2": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "entrypoint": "ingestor.ingestion_worker.sealed_release_ingestion_cli --only-attributions", "control_role": "ingestion_control_app", "release_id": PREDECESSEUR_V2["release_id"]},
        "limite": "placements V2 déjà acquis ; ni réingestion, ni réécriture de leurs faits",
    },
    "adoption_v3": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "entrypoint": "ingestor.ingestion_worker.attest_publication_cli adopt-predecessor-release", "control_role": "ingestion_control_attestor", "release_id": _V3},
        "limite": "reprise par V3 des placements V2 acquis, bijection et égalité exacte (ADR-0059 § 5)",
    },
    "batch_review_proposal": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "entrypoint": "ingestor.ingestion_worker.attest_publication_cli propose-release-batch-review", "control_role": "ingestion_control_attestor", "release_id": _V3},
        "limite": "projection et artefact de revue ; n'approuve rien",
    },
    "batch_review_record": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "entrypoint": "ingestor.ingestion_worker.attest_publication_cli record-release-batch-attestation", "control_role": "ingestion_control_attestor", "release_id": _V3},
        "limite": "après approbation humaine réelle de la revue batch, au head exact, dans sa fenêtre",
    },
    "worker_b_publication": {
        "cible": {**_COMMUNE, "schema": "public", "entrypoint": "ingestor.ingestion_worker.multilevel_publication_resume_cli", "control_role": "ingestion_control_app", "product_role": "rag_publisher", "release_id": _V3},
        "limite": "seuls les placements couverts par l'attestation batch enregistrée",
    },
    "independent_verification": {
        "cible": {**_COMMUNE, "mode": "read_only", "product_role": "rag_reader", "release_id": _V3},
        "limite": "réconciliation des deux schémas et retrieval par le tunnel existant",
    },
}
ORDRE_V3 = tuple(OPERATIONS_V3)

MENTIONS_V3 = (
    "staging cloisonne uniquement",
    "Worker B uniquement dans le staging cloisonne",
    "ni publication de V2",
    "ni build sur nexus-prod",
    "ni tag non epingle",
    "ni ecriture DB production",
    "ni current switch",
    "ni exposition publique",
)

GABARIT_V3: dict = {
    "kind": KIND_V3,
    "amends": "CY",
    "granted_by_pull_request_approval_of": APPROBATEUR,
    "effective_when": (
        "ce fichier est fusionné sur main par une PR à revue humaine épinglée "
        "(trusted-human-review/head-pinned)"
    ),
    "consumed": False,
    "expires_after_use": True,
    "release": RELEASE_V3,
    "predecessor": PREDECESSEUR_V2,
    "targets": CIBLES_V3,
    "runtime_image": {
        "image_repository": DEPOT_IMAGE,
        "pinning": "pinned_by_digest_no_rebuild",
        "tag_alone_accepted": False,
        "built_off_host": True,
        "build_on_nexus_prod": "forbidden",
        "build_workflow": ".github/workflows/production-image-provenance.yml",
        "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
        "contracts_version": "0.20.0",
        "runtime_image_binding_guard": "NEXUS_ACTUAL_WORKER_IMAGE",
        "network": "no_inbound_exposure",
        "durable_service": False,
    },
    "operations": list(ORDRE_V3),
    "forbidden": sorted(INTERDITS_REQUIS | {"v2_publication", "production_image_rebuild_on_host"}),
    "authorization_statement": (
        "L'approbation de cette PR par abenrhouma vaut autorisation, pour le staging "
        "cloisonne uniquement, de publier production-profile-gate-2026-2027-v3 selon "
        "les operations nommees et sur leurs cibles exactes : Worker B uniquement dans "
        "le staging cloisonne, ecritures limitees a la base ragdb du conteneur "
        "nexus-staging-pgvector-1. Elle n'autorise ni publication de V2, ni build sur "
        "nexus-prod, ni tag non epingle, ni ecriture DB production, ni current switch, "
        "ni exposition publique."
    ),
    "stop_conditions": (
        "toute precondition non satisfaite, tout ecart mesure, toute signature ou "
        "approbation manquante ; arret de securite sans suppression de volume ni de preuve"
    ),
    "expected_proof": [
        "têtes de migration avant et après, mesurées",
        "rapport d'attribution et d'adoption (ou d'ingestion scellée), rejeu idempotent",
        "attestation batch enregistrée au head exact de la revue approuvée",
        "comptes et identités servis : 11 collections, 315 artefacts, 479 placements, 8268 chunks",
        "retrieval exercé ; actualité servie official_snapshot",
    ],
    "rollback": {
        "service": "arrêt des processus lancés par ce plan ; aucune suppression de volume",
        "database": "restauration de la sauvegarde pg_dump préalable, sur décision humaine",
        "governance_evidence": "jamais supprimée : les preuves et attestations restent",
    },
}


def _ecarts_image_v3(image: object) -> list[str]:
    if not isinstance(image, dict):
        return ["image V3 : objet attendu"]
    ecarts = [
        f"image V3 : {cle} = {image.get(cle)!r}, attendu {attendu!r}"
        for cle, attendu in GABARIT_V3["runtime_image"].items()
        if image.get(cle) != attendu
    ]
    digest = image.get("image_digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
        ecarts.append("image V3 : digest sha256 absent ou mal formé")
    elif digest in DIGESTS_ECARTES or digest == IMAGE_WORKER_REQUISE["image_digest"]:
        ecarts.append("image V3 : digest écarté ou antérieur aux contrats 0.20.0")
    if image.get("reference") != f"{DEPOT_IMAGE}@{digest}":
        ecarts.append("image V3 : la référence doit être dépôt@digest, jamais un tag")
    commit = image.get("source_commit_sha")
    if not isinstance(commit, str) or len(commit) != 40:
        ecarts.append("image V3 : commit de build absent")
    if not isinstance(image.get("build_workflow_run_id"), int):
        ecarts.append("image V3 : run de build absent")
    preuve = image.get("evidence")
    if not isinstance(preuve, dict) or not preuve.get("path") or not preuve.get("sha256"):
        ecarts.append("image V3 : preuve de provenance absente")
    return ecarts


def evaluer_v3(document: dict, *, base_sha256: str, plan_sha256: str) -> list[str]:
    """Écarts de l'autorisation de publication V3. Liste vide = conforme."""
    ecarts: list[str] = []
    for cle in (
        "kind", "granted_by_pull_request_approval_of", "release", "predecessor",
        "targets", "operations", "stop_conditions", "expected_proof", "rollback",
    ):
        if document.get(cle) != GABARIT_V3[cle]:
            ecarts.append(f"V3 : {cle} ne correspond pas au périmètre gouverné")
    if document.get("consumed") is not False:
        ecarts.append("V3 : autorisation déjà consommée")
    if document.get("expires_after_use") is not True:
        ecarts.append("V3 : l'autorisation doit être à usage unique")
    base = document.get("extends") or {}
    if base.get("path") != AUTORISATION or base.get("sha256") != base_sha256:
        ecarts.append("V3 : non liée à l'autorisation de base courante (empreinte)")
    plan = document.get("execution_plan") or {}
    if plan.get("path") != PLAN_V3 or plan.get("sha256") != plan_sha256:
        ecarts.append("V3 : le plan d'exécution a changé depuis l'autorisation")
    manquants = sorted(set(GABARIT_V3["forbidden"]) - set(document.get("forbidden") or []))
    if manquants:
        ecarts.append(f"V3 : interdits manquants : {manquants}")
    declaration = document.get("authorization_statement") or ""
    ecarts.extend(
        f"V3 : déclaration, mention manquante {m!r}" for m in MENTIONS_V3 if m not in declaration
    )
    ecarts.extend(_ecarts_image_v3(document.get("runtime_image")))
    return ecarts


def evaluer_operation(
    operation: str,
    cible: dict,
    *,
    document_v3: dict | None,
    base_sha256: str,
    plan_v3_sha256: str,
) -> list[str]:
    """Une opération est-elle autorisée, sur CETTE cible ? Liste vide = oui."""
    if operation not in OPERATIONS_V3:
        return [f"opération inconnue : {operation!r} — rien ne l'autorise"]
    if document_v3 is None:
        return [
            f"l'autorisation de base ne couvre pas {operation!r} : ni Worker B, ni base "
            "produit, ni migration, ni adoption sans autorisation V3 fusionnée"
        ]
    ecarts = evaluer_v3(document_v3, base_sha256=base_sha256, plan_sha256=plan_v3_sha256)
    if operation not in (document_v3.get("operations") or []):
        ecarts.append(f"{operation!r} n'est pas nommée par l'autorisation V3")
    attendue = OPERATIONS_V3[operation]["cible"]
    for cle in sorted(set(attendue) | set(cible)):
        if cible.get(cle) != attendue.get(cle):
            ecarts.append(
                f"{operation} : {cle} = {cible.get(cle)!r}, autorisé {attendue.get(cle)!r}"
            )
    return ecarts


def empreinte_base(racine: Path) -> str:
    return hashlib.sha256((racine / AUTORISATION).read_bytes()).hexdigest()


def verifier_operation(racine: Path, operation: str, cible: dict) -> list[str]:
    """Contrôle complet avant une opération : base valide ET V3 fusionnée et conforme."""
    ecarts = verifier(racine)
    chemin = racine / AUTORISATION_V3
    document_v3 = json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else None
    plan = racine / PLAN_V3
    plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest() if plan.is_file() else ""
    ecarts += evaluer_operation(
        operation, cible, document_v3=document_v3,
        base_sha256=empreinte_base(racine), plan_v3_sha256=plan_sha,
    )
    if document_v3 is not None:
        sur_main = _git(racine, "show", f"origin/main:{AUTORISATION_V3}")
        if sur_main.returncode != 0 or sur_main.stdout != chemin.read_text(encoding="utf-8"):
            ecarts.append("l'autorisation V3 n'est pas (ou pas à l'identique) sur origin/main")
    return ecarts


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", default=None, help="opération de publication V3 à contrôler")
    parser.add_argument("--cible", default="{}", help="cible exacte, en JSON")
    args = parser.parse_args(argv)
    racine = Path(__file__).resolve().parents[2]
    if args.operation is None:
        ecarts = verifier(racine)
        print(json.dumps({"ssh_staging_authorized": not ecarts, "ecarts": ecarts}, ensure_ascii=False, indent=2))
        return 1 if ecarts else 0
    ecarts = verifier_operation(racine, args.operation, json.loads(args.cible))
    print(json.dumps({"operation": args.operation, "authorized": not ecarts, "ecarts": ecarts}, ensure_ascii=False, indent=2))
    return 1 if ecarts else 0


if __name__ == "__main__":
    raise SystemExit(main())
