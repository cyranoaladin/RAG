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


# ── DB : la publication V4 sur le staging cloisonné ─────────────────────
#
# L'autorisation de base ouvre l'accès et interdit Worker B, la base produit,
# les migrations et toute écriture d'autorité. Elle reste telle quelle. Une
# autorisation gouvernée DISTINCTE, liée à la base et à son plan par
# empreinte, ouvre ces opérations — chacune sur sa cible exacte : hôte,
# projet, conteneur, base, schéma, rôle, image et release. Ce qui n'y est pas
# nommé reste refusé. Chemin DIRECT seulement, sur une base DÉDIÉE à V4
# (lot DC) : ``ragdb`` porte l'acquisition V2 (479 lignes) et 26 placements
# pilotes ; elle reste intacte, hors du chemin V4, mesurée avant et revérifiée
# après chaque écriture. La base dédiée est créée, additivement, dans le même
# cluster ; tout contenu inattendu qu'elle porterait reste un refus.

AUTORISATION_V4 = "docs/reports/go_live/authorizations/staging_v4_publication_authorization.json"
KIND_V4 = "NEXUS-STAGING-V4-PUBLICATION-AUTHORIZATION-V1"
PLAN_V4 = "docs/runbooks/staging_v4_publication_EXECUTION_PLAN.md"
DEPOT_IMAGE = "ghcr.io/cyranoaladin/rag-multilevel-worker-production"
DEPOT_INGESTOR = "ghcr.io/cyranoaladin/rag-ingestor"
BASE_V4 = "ragdb_profile_gate_v4"
BASE_HISTORIQUE = "ragdb"
REPERTOIRE_ROLES = "/srv/nexus-staging/secrets/v4-roles"
#: L'autorisation que DC remplace, par ses octets : non consommée, jamais
#: exécutée au-delà du pré-vol (arrêté sur une base non vierge).
REMPLACE_V4 = {
    "amends": "DC",
    "sha256": "c2b410006516985da819608305462accbbf06e671135048a3f3f3388de0f4fdf",
    "reason": (
        "chaînon manquant : aucune opération ne mettait en file les jobs de publication "
        "que Worker B consomme ; exécution DC arrêtée proprement avant toute publication"
    ),
}
JETON_GITHUB = {
    "path": "/srv/nexus-staging/secrets/github-read-token/token",
    "file_mode": "0600",
    "dir_mode": "0700",
    "repository_selection": ["cyranoaladin/RAG"],
    "permissions": {"contents": "read", "metadata": "read"},
    "created_by": "propriétaire, après approbation de cette autorisation ; jamais par l'agent",
    "consumers": ["scope_authorization_registration_r4", "batch_review_record", "worker_b_publication"],
}

RELEASE_V4 = {
    "release_id": "production-profile-gate-2026-2027-v4",
    "release_dir": (
        "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/"
        "release-024f8625ebfeb7ce/profile_gate"
    ),
    "release_manifest_sha256": (
        "bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be"
    ),
    "profiles_dir": "services/rag-engine/configs/ingestion_profiles/v3_livraison_315",
    "expected_counts": {"subjects": 11, "unique_artifacts": 315, "placements": 479, "unique_chunks": 8268},
    "served_currentness": "official_snapshot",
    "served_visibility": "internal",
}
PREDECESSEURS = {
    "publication": "forbidden",
    "releases": [
        {
            "release_id": "production-profile-gate-2026-2027-v2",
            "release_manifest_sha256": "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864",
        },
        {
            "release_id": "production-profile-gate-2026-2027-v3",
            "release_manifest_sha256": "c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16",
        },
    ],
    "adoption": "non autorisée : placement_id et programme changent (ADR-0061), décision distincte requise",
}
#: Les onze r4, versées par la PR #252 : enregistrées à son HEAD approuvé,
#: pendant qu'elle est ouverte (ordre enregistrer-puis-fusionner).
AUTORISATIONS_R4 = {
    "repository": "cyranoaladin/RAG",
    "pull_request": 252,
    "expected_head": "2590a1722fb6ec9f079d3de5aab0ee22ad5fad93",
    "prefix": "lot41a-staging-v4-",
    "count": 11,
    "protocol_version": "LOT41A-V2",
}
CIBLES_V4 = {
    "host": HOTE,
    "compose_project": "nexus-staging",
    "container": "nexus-staging-pgvector-1",
    "database": BASE_V4,
    "database_creation": "additive : nouvelle base du cluster existant, jamais une réutilisation",
    "legacy_database": {
        "name": BASE_HISTORIQUE,
        "mode": "untouched",
        "holds": "acquisition V2 (479 ressources, 479 artefacts) et 26 placements pilotes",
        "guard": "têtes et comptes mesurés au pré-vol, revérifiés après chaque écriture",
    },
    "product_schema": "public",
    "control_schema": "ingestion_control",
    "roles": {
        "migrator": "superutilisateur du conteneur staging, via les seuls runners canoniques",
        "control_migrator": "ingestion_control_migrator",
        "authority": "ingestion_control_authority",
        "worker": "ingestion_control_app",
        "attestor": "ingestion_control_attestor",
        "product_writer": "rag_publisher",
        "product_reader": "rag_reader",
        "product_reviewer": "rag_reviewer (droits posés par le runner produit, non utilisé par ce plan)",
    },
    "role_env_dir": REPERTOIRE_ROLES,
    "worker_never_receives": [
        "identifiants du migrateur",
        "DSN ingestion_control_authority",
        "DSN ingestion_control_attestor",
        "staging.env",
        "ingestion_control.env",
    ],
}

_COMMUNE = {
    "host": HOTE,
    "compose_project": "nexus-staging",
    "container": "nexus-staging-pgvector-1",
    "database": BASE_V4,
}
_V4 = RELEASE_V4["release_id"]
OPERATIONS_V4: dict[str, dict] = {
    "preflight_measurement": {
        "cible": {**_COMMUNE, "mode": "read_only", "legacy_database": BASE_HISTORIQUE},
        "limite": (
            "mesures en lecture : ragdb (têtes, comptes : référence d'intangibilité), base "
            "dédiée (absente, ou vierge), identités des rôles, fichiers sources ; arrêt si la "
            "base dédiée porte un contenu"
        ),
    },
    "backup_before_migration": {
        "cible": {**_COMMUNE, "database": BASE_HISTORIQUE, "mode": "read_only", "command": "pg_dump", "destination": "/srv/nexus-staging/backups"},
        "limite": "sauvegarde de ragdb, en lecture, avant tout changement du cluster ; jamais supprimée par ce plan",
    },
    "database_creation": {
        "cible": {
            **_COMMUNE, "mode": "additive", "command": "createdb", "template": "template0",
            "encoding": "UTF8", "locale": "C", "refuse_if_exists": True,
        },
        "limite": "crée la base dédiée ; une base de ce nom déjà présente est un refus, hors reprise de cette étape",
    },
    "product_migrations": {
        "cible": {
            **_COMMUNE, "schema": "public",
            "runner": "services/rag-engine/infra/scripts/apply_pgvector_migrations.sh",
            "from_head": "000", "target_head": "005",
            "provisions_roles": ["rag_reader", "rag_reviewer", "rag_publisher"],
        },
        "limite": "001 à 005 dans l'ordre par le runner canonique ; rôles existants, aucun mot de passe changé ; ragdb revérifiée",
    },
    "control_migrations": {
        "cible": {
            **_COMMUNE, "schema": "ingestion_control",
            "runner": "services/rag-engine/infra/scripts/provision_and_bootstrap_ingestion_control.sh",
            "from_head": "000", "target_head": "019",
        },
        "limite": (
            "001 à 019 dans l'ordre, puis rôles provisionnés, par le runner canonique ; "
            "chaque mot de passe source doit d'abord authentifier son rôle (ALTER ROLE sans effet)"
        ),
    },
    "role_env_derivation": {
        "cible": {
            "host": HOTE, "compose_project": "nexus-staging", "database": BASE_V4,
            "script": "scripts/go_live/staging_v4_role_env.py",
            "destination": REPERTOIRE_ROLES, "dir_mode": "0700", "file_mode": "0600",
            "sources": ["staging.env", "ingestion_control.env"], "new_secrets": False,
        },
        "limite": "un fichier par rôle, dérivé des secrets existants, atomique, jamais écrasé ; aucune valeur affichée",
    },
    "model_artifact_install": {
        "cible": {
            "host": HOTE, "compose_project": "nexus-staging",
            "destination": "/srv/nexus-staging/models/e5-large-prerentree-2026-2027-20260828-materialise",
            "inventory_sha256": "58ad18dbb0a154c5a10320de9efdf81944f8b1ee1a01cc7f077e8b86b364dbc6",
        },
        "limite": "seulement si l'artefact E5 de l'hôte ne porte pas l'inventaire que V4 déclare ; copie vérifiée, rien d'écrasé",
    },
    "readiness_manifest_install": {
        "cible": {
            "host": HOTE, "compose_project": "nexus-staging",
            "destination": "/srv/nexus-staging/readiness",
            "manifests": ["staging-readiness-v4.json"],
        },
        "limite": "dépôt du manifeste signé localement par le détenteur de la clé ; vérifié contre l'ancre avant usage",
    },
    "transfer_manifest_v4": {
        "cible": {**_COMMUNE, "mode": "read_only", "artifact_store": "/srv/nexus-staging/artifact-store", "release_id": _V4},
        "limite": "rehachage en lecture des 315 objets du magasin sous l'identité V4",
    },
    "scope_authorization_registration_r4": {
        "cible": {
            **_COMMUNE, "schema": "ingestion_control",
            "entrypoint": "ingestor.ingestion_worker.authorize_scope_cli record-authorization",
            "control_role": "ingestion_control_authority", "release_id": _V4,
            "pull_request": AUTORISATIONS_R4["pull_request"],
            "expected_head": AUTORISATIONS_R4["expected_head"],
        },
        "limite": "les onze r4 de la PR nommée, à son HEAD approuvé, avant sa fusion ; aucune autre autorisation",
    },
    "sealed_ingestion_v4": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "entrypoint": "ingestor.ingestion_worker.sealed_release_ingestion_cli", "control_role": "ingestion_control_app", "release_id": _V4},
        "limite": "sous les onze r4 seulement ; base sans placement acquis",
    },
    "batch_review_proposal": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "entrypoint": "ingestor.ingestion_worker.attest_publication_cli propose-release-batch-review", "control_role": "ingestion_control_attestor", "release_id": _V4},
        "limite": "projection et artefact de revue ; n'approuve rien",
    },
    "batch_review_record": {
        "cible": {**_COMMUNE, "schema": "ingestion_control", "entrypoint": "ingestor.ingestion_worker.attest_publication_cli record-release-batch-attestation", "control_role": "ingestion_control_attestor", "release_id": _V4},
        "limite": "après approbation humaine réelle de la revue batch, au head exact, dans sa fenêtre",
    },
    "publication_job_enqueue": {
        "cible": {
            **_COMMUNE, "schema": "ingestion_control",
            "script": "scripts/go_live/staging_v4_enqueue_publication.py",
            "control_role": "ingestion_control_app", "release_id": _V4,
            "job_type": "publication_resume", "expected_jobs": 479,
        },
        "limite": (
            "un job par attestation batch active de V4, sur ressource NEEDS_REVIEW ; "
            "idempotent ; compte exact exigé ; aucun droit nouveau"
        ),
    },
    "worker_b_publication": {
        "cible": {**_COMMUNE, "schema": "public", "entrypoint": "ingestor.ingestion_worker.multilevel_publication_resume_cli", "control_role": "ingestion_control_app", "product_role": "rag_publisher", "release_id": _V4, "authority_mode": "RELEASE_BOUND_STAGING_QUALIFICATION"},
        "limite": "seuls les placements couverts par l'attestation batch enregistrée ; qualification tirée de la readiness de staging vérifiée",
    },
    "independent_verification": {
        "cible": {**_COMMUNE, "mode": "read_only", "product_role": "rag_reader", "release_id": _V4, "probe": "scripts/go_live/staging_retrieval_probe.py"},
        "limite": "réconciliation des deux schémas et retrieval servi sous les onze scopes V4, image ingestor épinglée, conteneur ponctuel",
    },
}
ORDRE_V4 = tuple(OPERATIONS_V4)

MENTIONS_V4 = (
    "staging cloisonne uniquement",
    "Worker B uniquement dans le staging cloisonne",
    "base dediee ragdb_profile_gate_v4",
    "ni modification de ragdb",
    "ni suppression des donnees V2",
    "ni reutilisation des placements pilotes",
    "ni bascule du service API",
    "ni publication de V2 ou de V3",
    "ni adoption",
    "ni build sur nexus-prod",
    "ni tag non epingle",
    "ni ecriture DB production",
    "ni current switch",
    "ni exposition publique",
)

GABARIT_V4: dict = {
    "kind": KIND_V4,
    "amends": "DG",
    "supersedes": REMPLACE_V4,
    "granted_by_pull_request_approval_of": APPROBATEUR,
    "effective_when": (
        "ce fichier est fusionné sur main par une PR à revue humaine épinglée "
        "(trusted-human-review/head-pinned)"
    ),
    "consumed": False,
    "expires_after_use": True,
    "release": RELEASE_V4,
    "predecessors": PREDECESSEURS,
    "scope_authorizations": AUTORISATIONS_R4,
    "github_read_token": JETON_GITHUB,
    "targets": CIBLES_V4,
    "runtime_image": {
        "image_repository": DEPOT_IMAGE,
        "pinning": "pinned_by_digest_no_rebuild",
        "tag_alone_accepted": False,
        "built_off_host": True,
        "build_on_nexus_prod": "forbidden",
        "build_workflow": ".github/workflows/production-image-provenance.yml",
        "dockerfile": "services/rag-engine/infra/Dockerfile.multilevel-worker-production",
        "contracts_version": "0.21.0",
        "runtime_image_binding_guard": "NEXUS_ACTUAL_WORKER_IMAGE",
        "network": "no_inbound_exposure",
        "durable_service": False,
    },
    "probe_image": {
        "image_repository": DEPOT_INGESTOR,
        "pinning": "pinned_by_digest_no_rebuild",
        "tag_alone_accepted": False,
        "built_off_host": True,
        "build_on_nexus_prod": "forbidden",
        "build_workflow": ".github/workflows/production-image-provenance.yml",
        "dockerfile": "services/rag-engine/infra/Dockerfile.ingestor-v2",
        "contracts_version": "0.21.0",
        "use": "sonde de retrieval ponctuelle en lecture (rag_reader) ; aucun service démarré",
        "network": "no_inbound_exposure",
        "durable_service": False,
    },
    "operations": list(ORDRE_V4),
    "forbidden": sorted(INTERDITS_REQUIS | {
        "v2_publication", "v3_publication", "predecessor_adoption",
        "production_image_rebuild_on_host", "legacy_database_modification",
        "legacy_v2_data_deletion", "pilot_placements_reuse", "api_service_switch",
    }),
    "authorization_statement": (
        "L'approbation de cette PR par abenrhouma vaut autorisation, pour le staging "
        "cloisonne uniquement, de publier production-profile-gate-2026-2027-v4 selon "
        "les operations nommees et sur leurs cibles exactes : Worker B uniquement dans "
        "le staging cloisonne, ecritures limitees a une base dediee "
        "ragdb_profile_gate_v4 creee dans le conteneur nexus-staging-pgvector-1. Elle "
        "n'autorise ni modification de ragdb, ni suppression des donnees V2, ni "
        "reutilisation des placements pilotes, ni publication de V2 ou de V3, ni "
        "adoption, ni build sur nexus-prod, ni tag non epingle, ni ecriture DB "
        "production, ni current switch, ni bascule du service API, ni exposition "
        "publique."
    ),
    "stop_conditions": (
        "toute precondition non satisfaite, tout ecart mesure, toute signature ou "
        "approbation manquante, tout contenu trouve dans la base dediee, toute "
        "variation de ragdb ; arret de securite sans suppression de volume, de base "
        "ni de preuve"
    ),
    "expected_proof": [
        "ragdb inchangée : têtes (produit 4, contrôle 15) et comptes (479, 479, 26) identiques avant et après",
        "base dédiée créée, puis têtes mesurées (produit 005, contrôle 019)",
        "cinq fichiers par rôle en 0600 sous un répertoire 0700, chacun authentifiant son rôle sur la base dédiée",
        "onze r4 enregistrées au HEAD approuvé de leur PR",
        "rapport d'ingestion scellée sous les r4, rejeu idempotent",
        "attestation batch enregistrée au head exact de la revue approuvée",
        "479 jobs publication_resume mis en file par l'outil canonique, rôle ingestion_control_app, rejeu sans effet",
        "comptes et identités servis : 11 collections, 315 artefacts, 479 placements, 8268 chunks",
        "retrieval servi sous les onze scopes V4 : aucun candidat hors du jeu publié",
    ],
    "rollback": {
        "service": "arrêt des processus lancés par ce plan ; aucune suppression de volume",
        "database": "la base dédiée peut être abandonnée, sur décision humaine ; ragdb n'est jamais touchée",
        "governance_evidence": "jamais supprimée : les preuves et attestations restent",
    },
}

#: Les digests que DB écarte : l'image de CY précédait ADR-0060/0061 et la
#: publication exacte des chunks scellés.
DIGESTS_ECARTES_V4 = (
    *DIGESTS_ECARTES,
    IMAGE_WORKER_REQUISE["image_digest"],
    "sha256:f931f59cb75aecacfb88959aa7b0d85302fd7b40e60851bdb8b1c6860dd35002",
)


def _ecarts_image(image: object, *, gabarit: dict, depot: str, nom: str) -> list[str]:
    if not isinstance(image, dict):
        return [f"{nom} : objet attendu"]
    ecarts = [
        f"{nom} : {cle} = {image.get(cle)!r}, attendu {attendu!r}"
        for cle, attendu in gabarit.items()
        if image.get(cle) != attendu
    ]
    digest = image.get("image_digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:") or len(digest) != 71:
        ecarts.append(f"{nom} : digest sha256 absent ou mal formé")
    elif digest in DIGESTS_ECARTES_V4:
        ecarts.append(f"{nom} : digest écarté (antérieur à ADR-0060/0061)")
    if image.get("reference") != f"{depot}@{digest}":
        ecarts.append(f"{nom} : la référence doit être dépôt@digest, jamais un tag")
    commit = image.get("source_commit_sha")
    if not isinstance(commit, str) or len(commit) != 40:
        ecarts.append(f"{nom} : commit de build absent")
    if not isinstance(image.get("build_workflow_run_id"), int):
        ecarts.append(f"{nom} : run de build absent")
    preuve = image.get("evidence")
    if not isinstance(preuve, dict) or not preuve.get("path") or not preuve.get("sha256"):
        ecarts.append(f"{nom} : preuve de provenance absente")
    return ecarts


def evaluer_v4(document: dict, *, base_sha256: str, plan_sha256: str) -> list[str]:
    """Écarts de l'autorisation de publication V4. Liste vide = conforme."""
    ecarts: list[str] = []
    for cle in (
        "kind", "amends", "supersedes", "granted_by_pull_request_approval_of", "release",
        "predecessors", "scope_authorizations", "github_read_token", "targets", "operations",
        "stop_conditions", "expected_proof", "rollback",
    ):
        if document.get(cle) != GABARIT_V4[cle]:
            ecarts.append(f"V4 : {cle} ne correspond pas au périmètre gouverné")
    if document.get("consumed") is not False:
        ecarts.append("V4 : autorisation déjà consommée")
    if document.get("expires_after_use") is not True:
        ecarts.append("V4 : l'autorisation doit être à usage unique")
    base = document.get("extends") or {}
    if base.get("path") != AUTORISATION or base.get("sha256") != base_sha256:
        ecarts.append("V4 : non liée à l'autorisation de base courante (empreinte)")
    plan = document.get("execution_plan") or {}
    if plan.get("path") != PLAN_V4 or plan.get("sha256") != plan_sha256:
        ecarts.append("V4 : le plan d'exécution a changé depuis l'autorisation")
    manquants = sorted(set(GABARIT_V4["forbidden"]) - set(document.get("forbidden") or []))
    if manquants:
        ecarts.append(f"V4 : interdits manquants : {manquants}")
    declaration = document.get("authorization_statement") or ""
    ecarts.extend(
        f"V4 : déclaration, mention manquante {m!r}" for m in MENTIONS_V4 if m not in declaration
    )
    ecarts.extend(_ecarts_image(
        document.get("runtime_image"), gabarit=GABARIT_V4["runtime_image"],
        depot=DEPOT_IMAGE, nom="image worker V4",
    ))
    ecarts.extend(_ecarts_image(
        document.get("probe_image"), gabarit=GABARIT_V4["probe_image"],
        depot=DEPOT_INGESTOR, nom="image de sonde V4",
    ))
    worker, sonde = document.get("runtime_image") or {}, document.get("probe_image") or {}
    if worker.get("source_commit_sha") != sonde.get("source_commit_sha"):
        ecarts.append("V4 : les deux images doivent venir du même commit")
    return ecarts


def evaluer_operation(
    operation: str,
    cible: dict,
    *,
    document_v4: dict | None,
    base_sha256: str,
    plan_v4_sha256: str,
) -> list[str]:
    """Une opération est-elle autorisée, sur CETTE cible ? Liste vide = oui."""
    if operation not in OPERATIONS_V4:
        return [f"opération inconnue : {operation!r} — rien ne l'autorise"]
    if document_v4 is None:
        return [
            f"l'autorisation de base ne couvre pas {operation!r} : ni Worker B, ni base "
            "produit, ni migration, ni autorité sans autorisation V4 fusionnée"
        ]
    ecarts = evaluer_v4(document_v4, base_sha256=base_sha256, plan_sha256=plan_v4_sha256)
    if operation not in (document_v4.get("operations") or []):
        ecarts.append(f"{operation!r} n'est pas nommée par l'autorisation V4")
    attendue = OPERATIONS_V4[operation]["cible"]
    for cle in sorted(set(attendue) | set(cible)):
        if cible.get(cle) != attendue.get(cle):
            ecarts.append(
                f"{operation} : {cle} = {cible.get(cle)!r}, autorisé {attendue.get(cle)!r}"
            )
    return ecarts


def empreinte_base(racine: Path) -> str:
    return hashlib.sha256((racine / AUTORISATION).read_bytes()).hexdigest()


def verifier_operation(racine: Path, operation: str, cible: dict) -> list[str]:
    """Contrôle complet avant une opération : base valide ET V4 fusionnée et conforme."""
    ecarts = verifier(racine)
    chemin = racine / AUTORISATION_V4
    document_v4 = json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else None
    plan = racine / PLAN_V4
    plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest() if plan.is_file() else ""
    ecarts += evaluer_operation(
        operation, cible, document_v4=document_v4,
        base_sha256=empreinte_base(racine), plan_v4_sha256=plan_sha,
    )
    if document_v4 is not None:
        sur_main = _git(racine, "show", f"origin/main:{AUTORISATION_V4}")
        if sur_main.returncode != 0 or sur_main.stdout != chemin.read_text(encoding="utf-8"):
            ecarts.append("l'autorisation V4 n'est pas (ou pas à l'identique) sur origin/main")
    return ecarts


# ── DH : récupérer la publication V4 après la fermeture de la revue #257 ──
#
# L'autorisation V4 (DG) a été exercée jusqu'à Worker B, qui a refusé les 479
# attestations : la PR de revue #257 a été fusionnée avant leur usage. Elle
# n'est ni rejouée ni élargie. Une autorisation DISTINCTE, liée par empreinte
# à la V4, à l'identité de la revue périmée et au plan DH, nomme les seules
# opérations de reprise. Mêmes rôles, même image épinglée, même base dédiée ;
# rien n'est supprimé, rien n'est réaffecté.
#
# Ce dépôt n'en porte qu'une PROPOSITION (``PROPOSITION_DH``) : l'autorisation
# n'existe qu'une fois copiée à ``AUTORISATION_DH`` par une PR distincte,
# approuvée par le relecteur gouverné et fusionnée.

AUTORISATION_DH = "docs/reports/go_live/authorizations/staging_v4_publication_recovery_authorization.json"
PROPOSITION_DH = "docs/reports/go_live/authorizations/proposed/staging_v4_publication_recovery_authorization.json"
KIND_DH = "NEXUS-STAGING-V4-PUBLICATION-RECOVERY-AUTHORIZATION-V1"
PLAN_DH = "docs/runbooks/staging_v4_publication_recovery_DH_EXECUTION_PLAN.md"
IDENTITE_PERIMEE_DH = "docs/reports/go_live/recovery/dh_stale_review_257.json"
OUTIL_DH = "scripts/go_live/staging_v4_publication_recovery.py"
REVUE_PERIMEE_DH = {
    "repository": "cyranoaladin/RAG",
    "pull_request": 257,
    "head_sha": "85f9000115df34cab3060a52de6594bebe24c73c",
    "review_id": "lot42-release-batch-v4-staging-20260924",
    "review_artifact_sha256": "19ba49a2b56b3075b0f26ac75998cadcc696dab44864e6940d4f004c862279b9",
    "reuse": "forbidden : une revue fermée ne fonde jamais une reprise",
}
CYCLE_DE_REVUE_DH = {
    "r4_scope_authorizations": (
        "preuve scellée (ADR-0058) : enregistrées pendant que #252 était ouverte, elles ne "
        "dépendent plus de l'état de #252"
    ),
    "batch_review": (
        "revue GitHub vérifiée EN DIRECT à chaque usage (ADR-0033 § 5) : la PR doit rester "
        "ouverte, approuvée au head exact et inchangée tant qu'un job peut être repris"
    ),
    "preconditions": ["review-precondition --stage enqueue", "review-precondition --stage worker-b"],
    "per_publication_checks": "inchangées : Worker B revérifie chaque attestation avant chaque publication",
    "closure_condition": (
        "closure-check : toutes les ressources RETRIEVAL_ELIGIBLE, un pin de commit par "
        "attestation active à son head, aucun job publication_resume en file ou en cours ; "
        "vérification indépendante faite"
    ),
    "merge_or_close": "décision humaine après closure-check ; jamais automatique",
}
JETON_GITHUB_DH = {
    **JETON_GITHUB,
    "created_by": "propriétaire, après approbation de l'autorisation DH ; jamais par l'agent",
    "consumers": [
        "stale_attestation_invalidation", "recovery_review_record",
        "recovery_job_enqueue", "recovery_worker_b_publication",
    ],
}
_V4_OUTIL = {**_COMMUNE, "schema": "ingestion_control", "script": OUTIL_DH, "release_id": _V4,
             "stale_review_identity": IDENTITE_PERIMEE_DH}
OPERATIONS_DH: dict[str, dict] = {
    "recovery_preflight": {
        "cible": {**_V4_OUTIL, "mode": "read_only", "control_role": "ingestion_control_app",
                  "command": "preview", "legacy_database": BASE_HISTORIQUE},
        "limite": (
            "mesures en lecture : ragdb (référence), base dédiée (produit vide), conteneur Worker B "
            "arrêté, manifeste de transfert V4 ; aperçu exact de l'ensemble périmé ; arrêt humain "
            "avant toute écriture"
        ),
    },
    "stale_job_cancellation": {
        "cible": {**_V4_OUTIL, "control_role": "ingestion_control_app", "command": "cancel-stale-jobs",
                  "job_type": "publication_resume", "expected_jobs": 479},
        "limite": (
            "jobs nommant une attestation de #257, en file ou à bail EXPIRÉ, seulement ; bail actif = "
            "refus ; empreintes de l'aperçu exigées ; rien de supprimé ni de réaffecté"
        ),
    },
    "stale_attestation_invalidation": {
        "cible": {**_V4_OUTIL, "control_role": "ingestion_control_attestor",
                  "command": "invalidate-stale-attestations", "expected_attestations": 479},
        "limite": (
            "attestations de #257 seulement, après constat EN DIRECT que #257 n'autorise plus rien ; "
            "colonnes invalidated_at/invalidated_reason seulement"
        ),
    },
    "recovery_review_proposal": {
        "cible": {**_COMMUNE, "schema": "ingestion_control",
                  "entrypoint": "ingestor.ingestion_worker.attest_publication_cli propose-release-batch-review",
                  "control_role": "ingestion_control_attestor", "release_id": _V4},
        "limite": "nouvel artefact de revue sur les faits existants (projection réutilisée) ; n'approuve rien",
    },
    "recovery_review_record": {
        "cible": {**_COMMUNE, "schema": "ingestion_control",
                  "entrypoint": "ingestor.ingestion_worker.attest_publication_cli record-release-batch-attestation",
                  "control_role": "ingestion_control_attestor", "release_id": _V4,
                  "forbidden_pull_request": 257},
        "limite": "après approbation humaine réelle d'une NOUVELLE PR, au head exact, PR ouverte",
    },
    "recovery_job_enqueue": {
        "cible": {**_COMMUNE, "schema": "ingestion_control",
                  "script": "scripts/go_live/staging_v4_enqueue_publication.py",
                  "precondition": "review-precondition --stage enqueue",
                  "control_role": "ingestion_control_app", "release_id": _V4,
                  "job_type": "publication_resume", "expected_jobs": 479},
        "limite": "nouveaux jobs nommant les nouvelles attestations et les artefacts existants ; précondition de revue",
    },
    "recovery_worker_b_publication": {
        "cible": {**_COMMUNE, "schema": "public",
                  "entrypoint": "ingestor.ingestion_worker.multilevel_publication_resume_cli",
                  "precondition": "review-precondition --stage worker-b",
                  "container_name": "nexus-v4-worker-b-dh",
                  "control_role": "ingestion_control_app", "product_role": "rag_publisher", "release_id": _V4,
                  "authority_mode": "RELEASE_BOUND_STAGING_QUALIFICATION"},
        "limite": "Worker B inchangé, sans privilège nouveau ; précondition de revue avant lancement",
    },
    "recovery_independent_verification": {
        "cible": {**_COMMUNE, "mode": "read_only", "product_role": "rag_reader", "release_id": _V4,
                  "probe": "scripts/go_live/staging_retrieval_probe.py"},
        "limite": "réconciliation des deux schémas et retrieval servi sous les onze scopes V4",
    },
    "recovery_review_closure_check": {
        "cible": {**_V4_OUTIL, "mode": "read_only", "control_role": "ingestion_control_app",
                  "command": "closure-check"},
        "limite": "constat en lecture ; la fusion ou la fermeture de la PR de revue reste humaine",
    },
}
ORDRE_DH = tuple(OPERATIONS_DH)
MENTIONS_DH = (
    "staging cloisonne uniquement",
    "base dediee ragdb_profile_gate_v4",
    "ni nouvelle base",
    "ni reingestion",
    "ni nouvelle release",
    "ni suppression de ligne",
    "ni reaffectation d'ancien job",
    "ni reutilisation de la revue 257",
    "ni fusion automatique de la revue",
    "ni modification de ragdb",
    "ni privilege nouveau",
    "ni build sur nexus-prod",
    "ni ecriture DB production",
    "ni current switch",
    "ni exposition publique",
)
GABARIT_DH: dict = {
    "kind": KIND_DH,
    "amends": "DH",
    "granted_by_pull_request_approval_of": APPROBATEUR,
    "effective_when": (
        f"ce document est copié (git mv) de {PROPOSITION_DH} vers {AUTORISATION_DH} par une PR "
        "distincte, approuvée au head exact par le relecteur gouverné, puis fusionnée sur main"
    ),
    "consumed": False,
    "expires_after_use": True,
    "release": RELEASE_V4,
    "stale_review": REVUE_PERIMEE_DH,
    "review_lifecycle": CYCLE_DE_REVUE_DH,
    "github_read_token": JETON_GITHUB_DH,
    "targets": CIBLES_V4,
    "operations": list(ORDRE_DH),
    "forbidden": sorted(INTERDITS_REQUIS | {
        "v2_publication", "v3_publication", "predecessor_adoption",
        "production_image_rebuild_on_host", "legacy_database_modification",
        "legacy_v2_data_deletion", "pilot_placements_reuse", "api_service_switch",
        "new_database", "reingestion", "new_release", "row_deletion", "job_reassignment",
        "stale_review_reuse", "automatic_review_merge", "worker_b_privilege_escalation",
        "role_grant_change", "permission_file_modification", "applied_migration_change",
        "sealed_artifact_change",
    }),
    "authorization_statement": (
        "L'approbation de la PR d'activation par abenrhouma vaut autorisation, pour le staging "
        "cloisonne uniquement, de reprendre la publication de production-profile-gate-2026-2027-v4 "
        "sur la base dediee ragdb_profile_gate_v4 selon les operations nommees : apercu, annulation "
        "des jobs perimes par ingestion_control_app, invalidation des attestations de la revue 257 "
        "par ingestion_control_attestor, nouvelle revue humaine, nouvelles attestations, nouveaux "
        "jobs, Worker B, verification. Elle n'autorise ni nouvelle base, ni reingestion, ni nouvelle "
        "release, ni suppression de ligne, ni reaffectation d'ancien job, ni reutilisation de la "
        "revue 257, ni fusion automatique de la revue, ni modification de ragdb, ni privilege "
        "nouveau, ni build sur nexus-prod, ni ecriture DB production, ni current switch, ni "
        "exposition publique."
    ),
    "stop_conditions": (
        "tout ecart de l'apercu, toute ligne etrangere, tout bail actif, tout pin ou placement "
        "produit deja present, toute revue non approuvee en direct, toute variation de ragdb ; "
        "arret sans suppression de ligne, de base ni de preuve"
    ),
    "expected_proof": [
        "ragdb inchangée avant et après chaque écriture",
        "aperçu : 479 attestations, 479 ressources, 315 contenus, 11 collections, 479 jobs, empreintes",
        "jobs périmés annulés (en file ou bail expiré), dernier motif de Worker B conservé, rejeu sans effet",
        "attestations de #257 invalidées par le rôle attestor, motif DH, rejeu sans effet",
        "nouvelle revue approuvée au head exact, 479 nouvelles attestations",
        "préconditions de revue avant mise en file et avant Worker B",
        "479 nouveaux jobs ; publication : 11 collections, 315 artefacts, 479 placements, 8268 chunks",
        "retrieval servi sous les onze scopes V4 ; closure-check avant toute fermeture de la revue",
    ],
    "rollback": {
        "service": "arrêt des processus lancés ; aucune suppression de volume",
        "database": "aucune ligne supprimée : anciennes attestations et anciens jobs restent comme historique",
        "governance_evidence": "jamais supprimée",
    },
}


def evaluer_dh(
    document: dict, *, base_sha256: str, v4_sha256: str, plan_sha256: str, identite_sha256: str,
    document_v4: dict | None,
) -> list[str]:
    """Écarts de l'autorisation de reprise DH. Liste vide = conforme."""
    ecarts = [
        f"DH : {cle} ne correspond pas au périmètre gouverné"
        for cle in (
            "kind", "amends", "granted_by_pull_request_approval_of", "effective_when", "release",
            "stale_review", "review_lifecycle", "github_read_token", "targets", "operations",
            "stop_conditions", "expected_proof", "rollback",
        )
        if document.get(cle) != GABARIT_DH[cle]
    ]
    if document.get("consumed") is not False:
        ecarts.append("DH : autorisation déjà consommée")
    if document.get("expires_after_use") is not True:
        ecarts.append("DH : l'autorisation doit être à usage unique")
    for cle, chemin, attendu in (
        ("extends", AUTORISATION, base_sha256),
        ("extends_v4", AUTORISATION_V4, v4_sha256),
        ("execution_plan", PLAN_DH, plan_sha256),
        ("stale_review_identity", IDENTITE_PERIMEE_DH, identite_sha256),
    ):
        lien = document.get(cle) or {}
        if lien.get("path") != chemin or lien.get("sha256") != attendu:
            ecarts.append(f"DH : {cle} non lié à {chemin} (empreinte)")
    manquants = sorted(set(GABARIT_DH["forbidden"]) - set(document.get("forbidden") or []))
    if manquants:
        ecarts.append(f"DH : interdits manquants : {manquants}")
    declaration = document.get("authorization_statement") or ""
    ecarts.extend(f"DH : déclaration, mention manquante {m!r}" for m in MENTIONS_DH if m not in declaration)
    # Aucune reconstruction : les images sont EXACTEMENT celles de la V4.
    if document_v4 is None:
        ecarts.append("DH : autorisation V4 absente, images non vérifiables")
    else:
        for cle in ("runtime_image", "probe_image"):
            if document.get(cle) != document_v4.get(cle):
                ecarts.append(f"DH : {cle} diffère de celle de la V4 — aucune reconstruction n'est autorisée")
    return ecarts


def verifier_operation_dh(racine: Path, operation: str, cible: dict) -> list[str]:
    """Contrôle avant une opération DH : base valide, V4 et DH fusionnées et conformes."""
    if operation not in OPERATIONS_DH:
        return [f"opération DH inconnue : {operation!r} — rien ne l'autorise"]
    ecarts = verifier(racine)
    chemin_v4, chemin_dh = racine / AUTORISATION_V4, racine / AUTORISATION_DH
    if not chemin_dh.is_file():
        return [*ecarts, f"aucune autorisation DH : {AUTORISATION_DH} absent (la proposition n'autorise rien)"]
    document = json.loads(chemin_dh.read_text(encoding="utf-8"))
    document_v4 = json.loads(chemin_v4.read_text(encoding="utf-8")) if chemin_v4.is_file() else None

    def empreinte(relatif: str) -> str:
        chemin = racine / relatif
        return hashlib.sha256(chemin.read_bytes()).hexdigest() if chemin.is_file() else ""

    ecarts += evaluer_dh(
        document, base_sha256=empreinte(AUTORISATION), v4_sha256=empreinte(AUTORISATION_V4),
        plan_sha256=empreinte(PLAN_DH), identite_sha256=empreinte(IDENTITE_PERIMEE_DH),
        document_v4=document_v4,
    )
    if operation not in (document.get("operations") or []):
        ecarts.append(f"{operation!r} n'est pas nommée par l'autorisation DH")
    attendue = OPERATIONS_DH[operation]["cible"]
    for cle in sorted(set(attendue) | set(cible)):
        if cible.get(cle) != attendue.get(cle):
            ecarts.append(f"{operation} : {cle} = {cible.get(cle)!r}, autorisé {attendue.get(cle)!r}")
    for relatif in (AUTORISATION_DH, IDENTITE_PERIMEE_DH, PLAN_DH):
        sur_main = _git(racine, "show", f"origin/main:{relatif}")
        if sur_main.returncode != 0 or sur_main.stdout != (racine / relatif).read_text(encoding="utf-8"):
            ecarts.append(f"{relatif} n'est pas (ou pas à l'identique) sur origin/main")
    return ecarts



# ── DI : reprise PARTIELLE de la publication V4 sous la revue #262 ──────────
#
# Worker B (DH) a publié 76 des 479 placements attestés sous #262, puis s'est
# heurté à deux causes distinctes : une limitation GitHub pendant les
# revérifications live (390 échecs), et 74 placements HGGSP qu'aucun Worker B
# ne peut publier sous V4 — le mapping de sujets que V4 scelle ne gouverne pas
# ``hggsp``. L'autorisation DH n'autorise ni une sélection de collections, ni
# une autre image : DI est une autorisation DISTINCTE, liée par empreinte à
# DH, à V4, à l'identité de la reprise partielle et à son plan.
#
# Elle ne nomme que les 405 placements des neuf collections gouvernées. Les 74
# HGGSP ne sont ni réclamés, ni annulés, ni retentés : ils attendent la
# décision sur la release successeur. La revue #262 reste ouverte.
#
# Le correctif (limitation nommée, report sans tentative, sélection de
# collections, contrôle de démarrage) n'est PAS dans l'image de V4/DH. L'image
# DI n'existe qu'après fusion, construite par le workflow canonique depuis
# main : la proposition le déclare ``PENDING_BUILD_FROM_MAIN`` et reste
# inopérante tant qu'une PR d'activation ne l'a pas épinglée par digest.

AUTORISATION_DI = "docs/reports/go_live/authorizations/staging_v4_partial_recovery_authorization.json"
PROPOSITION_DI = "docs/reports/go_live/authorizations/proposed/staging_v4_partial_recovery_authorization.json"
KIND_DI = "NEXUS-STAGING-V4-PARTIAL-RECOVERY-AUTHORIZATION-V1"
PLAN_DI = "docs/runbooks/staging_v4_partial_recovery_DI_EXECUTION_PLAN.md"
IDENTITE_DI = "docs/reports/go_live/recovery/di_partial_v4_262.json"
OUTIL_DI = "scripts/go_live/staging_v4_partial_recovery.py"
SIGNATURE_DI = "scripts/go_live/sign_staging_v4_di_readiness_manifest.sh"
IMAGE_EN_ATTENTE = "PENDING_BUILD_FROM_MAIN"
REVUE_ACTIVE_DI = {
    "repository": "cyranoaladin/RAG",
    "pull_request": 262,
    "head_sha": "079461659b60f8a8ce9458145a199599ad822bbc",
    "state_required": "ouverte, approuvée au head exact, inchangée, jamais fusionnée ni fermée par ce lot",
}
COLLECTIONS_REPRISES_DI = (
    "rag_nexus_dgemc_terminale_option",
    "rag_nexus_hlp_premiere_specialite",
    "rag_nexus_hlp_terminale_specialite",
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
    "rag_nexus_ses_premiere_specialite",
    "rag_nexus_ses_terminale_specialite",
    "rag_nexus_svt_premiere_specialite",
    "rag_nexus_svt_terminale_specialite",
)
PERIMETRE_DI = {
    "claimed_collections": list(COLLECTIONS_REPRISES_DI),
    "excluded_collections": {
        "rag_nexus_hggsp_premiere_specialite": "external subject 'hggsp' is not governed",
        "rag_nexus_hggsp_terminale_specialite": "external subject 'hggsp' is not governed",
    },
    "exclusion_rule": (
        "dérivée des mappings SCELLÉS de V4 (ungoverned_release_collections), jamais choisie à la "
        "main ; Worker B refuse de démarrer sur une collection exclue"
    ),
    "excluded_jobs": "ni réclamés, ni annulés, ni retentés, ni reportés : empreinte exacte avant/après",
    "expected_product_after": {"collections": 9, "artifacts": 263, "placements": 405, "chunks": 5678},
}
#: Mesuré sur le banc DI : 63 GET GitHub par publication (neuf vérifications
#: live d'ADR-0033 § 7bis, aucune supprimée ; 56 pour un job déjà épinglé).
#: 76 publications en consomment ~4 800 : le quota primaire de 5 000/h par
#: utilisateur. 60 s par job = au plus ~3 780 requêtes/heure.
CADENCE_DI = {
    "min_job_interval_s": 60,
    "rate_limit_max_wait_s": 900,
    "max_consecutive_rate_limits": 3,
    "max_idle_polls": 5,
    "on_rate_limit": "job différé SANS tentative consommée ; toute réclamation suspendue ; arrêt 75 au-delà",
    "live_verification": "inchangée : aucune décision de revue mise en cache (ADR-0033 § 5)",
}
MARQUEURS_CORRECTIF_DI = {
    "services/rag-engine/src/ingestor/ingestion_control/github_authority.py": "class GitHubRateLimitedError",
    "services/rag-engine/src/ingestor/ingestion_control/jobs.py": "def defer_job_for_external_throttle",
    "services/rag-engine/src/ingestor/ingestion_worker/multilevel_publication_resume_cli.py": (
        "resolver.require_collections_governed(claim_collections)"
    ),
}
JETON_GITHUB_DI = {
    **JETON_GITHUB,
    "created_by": "propriétaire ; le jeton DH existant est réutilisé tel quel, jamais élargi",
    "consumers": ["partial_preflight", "partial_worker_b_publication"],
}
_V4_OUTIL_DI = {**_COMMUNE, "schema": "ingestion_control", "script": OUTIL_DI, "release_id": _V4,
                "partial_identity": IDENTITE_DI, "control_role": "ingestion_control_app", "mode": "read_only"}
OPERATIONS_DI: dict[str, dict] = {
    "partial_readiness_resign": {
        "cible": {"mode": "local_operator_signing", "script": SIGNATURE_DI, "release_id": _V4,
                  "worker_image": "runtime_image.reference de l'autorisation DI active"},
        "limite": "poste du détenteur de la clé ; jamais sur l'hôte ; un seul manifeste, V4, image DI",
    },
    "partial_readiness_install": {
        "cible": {"host": HOTE, "compose_project": "nexus-staging", "mode": "file_deposit",
                  "file": "staging-readiness-v4-di.json", "file_mode": "0600",
                  "destination": "répertoire readiness de l'exécution V4, à côté du manifeste V4 conservé"},
        "limite": "dépôt du seul manifeste DI signé ; le manifeste V4 n'est ni remplacé ni supprimé",
    },
    "partial_preflight": {
        "cible": {**_V4_OUTIL_DI, "command": "partial-precondition",
                  "review_precondition": "review-precondition --pull-request 262 --stage worker-b"},
        "limite": (
            "lecture seule : périmètre, exclusions dérivées de l'autorité scellée, empreinte des jobs "
            "exclus, revue #262 approuvée EN DIRECT au head exact ; aucun Worker B en cours"
        ),
    },
    "partial_worker_b_publication": {
        "cible": {**_COMMUNE, "schema": "public",
                  "entrypoint": "ingestor.ingestion_worker.multilevel_publication_resume_cli",
                  "precondition": "partial_preflight",
                  "container_name": "nexus-v4-worker-b-di",
                  "control_role": "ingestion_control_app", "product_role": "rag_publisher", "release_id": _V4,
                  "authority_mode": "RELEASE_BOUND_STAGING_QUALIFICATION",
                  "claimed_collections": list(COLLECTIONS_REPRISES_DI),
                  "min_job_interval_s": CADENCE_DI["min_job_interval_s"],
                  "rate_limit_max_wait_s": CADENCE_DI["rate_limit_max_wait_s"],
                  "max_consecutive_rate_limits": CADENCE_DI["max_consecutive_rate_limits"],
                  "max_idle_polls": CADENCE_DI["max_idle_polls"]},
        "limite": (
            "Worker B de l'image DI, liste d'autorisation des neuf collections ; aucun privilège "
            "nouveau ; arrêt 75 sur limitation persistante, sans rien réécrire"
        ),
    },
    "partial_independent_verification": {
        "cible": {**_COMMUNE, "mode": "read_only", "product_role": "rag_reader", "release_id": _V4,
                  "probe": "scripts/go_live/staging_retrieval_probe.py",
                  "expected_product": PERIMETRE_DI["expected_product_after"]},
        "limite": "9 collections, 263 artefacts, 405 placements, 5678 chunks ; retrieval sous les neuf scopes",
    },
    "partial_closure_check": {
        "cible": {**_V4_OUTIL_DI, "command": "partial-closure-check"},
        "limite": "constat en lecture ; n'annonce jamais la fermeture de #262 tant que HGGSP attend",
    },
}
ORDRE_DI = tuple(OPERATIONS_DI)
MENTIONS_DI = (
    "staging cloisonne uniquement",
    "base dediee ragdb_profile_gate_v4",
    "neuf collections gouvernees",
    "405 placements",
    "ni reclamation d'un job hggsp",
    "ni annulation d'un job hggsp",
    "ni modification sql manuelle d'un job",
    "ni modification du mapping scelle de v4",
    "ni nouvelle release",
    "ni fusion ni fermeture de la revue 262",
    "ni suppression de ligne",
    "ni privilege nouveau",
    "ni elargissement du jeton github",
    "ni mise en cache d'une revue",
    "ni build sur nexus-prod",
    "ni current switch",
    "ni exposition publique",
)
GABARIT_DI: dict = {
    "kind": KIND_DI,
    "amends": "DH",
    "granted_by_pull_request_approval_of": APPROBATEUR,
    "effective_when": (
        f"ce document, image DI épinglée par digest, est placé à {AUTORISATION_DI} par une PR "
        "distincte, approuvée au head exact par le relecteur gouverné, puis fusionnée sur main"
    ),
    "consumed": False,
    "expires_after_use": True,
    "release": RELEASE_V4,
    "active_review": REVUE_ACTIVE_DI,
    "partial_scope": PERIMETRE_DI,
    "worker_b_pacing": CADENCE_DI,
    "github_read_token": JETON_GITHUB_DI,
    "targets": CIBLES_V4,
    "operations": list(ORDRE_DI),
    "forbidden": sorted(INTERDITS_REQUIS | {
        "new_database", "reingestion", "new_release", "successor_release_publication",
        "row_deletion", "job_reassignment", "hggsp_job_claim", "hggsp_job_cancellation",
        "excluded_job_modification", "manual_job_sql", "attempt_count_reset", "dead_letter_revival",
        "v4_subject_mapping_change", "sealed_artifact_change", "applied_migration_change",
        "review_262_merge_or_close", "automatic_review_merge", "review_verification_caching",
        "github_permission_widening", "worker_b_privilege_escalation", "role_grant_change",
        "permission_file_modification", "production_image_rebuild_on_host",
        "legacy_database_modification", "api_service_switch",
    }),
    "authorization_statement": (
        "L'approbation de la PR d'activation par abenrhouma vaut autorisation, pour le staging "
        "cloisonne uniquement, de reprendre sur la base dediee ragdb_profile_gate_v4 la publication "
        "des neuf collections gouvernees de production-profile-gate-2026-2027-v4, soit 405 placements "
        "attestes sous la revue 262, avec l'image DI epinglee : readiness resignee, preconditions, "
        "Worker B restreint a ces neuf collections et cadence, verification, controle partiel. Elle "
        "n'autorise ni reclamation d'un job hggsp, ni annulation d'un job hggsp, ni modification sql "
        "manuelle d'un job, ni modification du mapping scelle de v4, ni nouvelle release, ni fusion "
        "ni fermeture de la revue 262, ni suppression de ligne, ni privilege nouveau, ni "
        "elargissement du jeton github, ni mise en cache d'une revue, ni build sur nexus-prod, ni "
        "current switch, ni exposition publique."
    ),
    "stop_conditions": (
        "tout ecart de la precondition partielle, toute exclusion non derivee de l'autorite scellee, "
        "tout job exclu modifie, toute revue 262 non approuvee en direct, tout arret 75 de Worker B "
        "(limitation persistante), toute variation de ragdb ; arret sans suppression ni reecriture"
    ),
    "expected_proof": [
        "image DI construite depuis main par le workflow canonique, digest et preuve de provenance",
        "readiness V4 resignee pour l'image DI, verifiee contre l'ancre, deposee a cote de celle de V4",
        "precondition partielle : 479 attestations actives de #262, 405 reprises, 74 exclues, empreinte",
        "review-precondition --stage worker-b : #262 approuvee en direct au head exact",
        "Worker B : publications succeeded pour les 329 restants, aucun job HGGSP reclame",
        "produit : 9 collections, 263 artefacts, 405 placements, 5678 chunks ; retrieval sous 9 scopes",
        "controle partiel : empreinte des jobs exclus inchangee, review_closure=NOT_SAFE",
        "closure-check (DH) refuse tant que HGGSP attend : #262 reste ouverte",
    ],
    "rollback": {
        "service": "arret du conteneur Worker B DI ; aucune suppression de volume",
        "database": "aucune ligne supprimee ni reecrite a la main ; les jobs restent l'historique",
        "governance_evidence": "jamais supprimee",
    },
}


def _ecarts_image_di(racine: Path, image: object, *, image_dh: object) -> list[str]:
    """L'image DI : construite depuis main APRÈS le correctif, jamais celle de DH."""
    if isinstance(image, dict) and image.get("status") == IMAGE_EN_ATTENTE:
        return ["DI : runtime_image en attente de construction depuis main — l'autorisation reste inactive"]
    ecarts = _ecarts_image(image, gabarit=GABARIT_V4["runtime_image"], depot=DEPOT_IMAGE, nom="image worker DI")
    if not isinstance(image, dict):
        return ecarts
    if isinstance(image_dh, dict) and image.get("image_digest") == image_dh.get("image_digest"):
        ecarts.append("DI : l'image de DH ne contient pas le correctif — une image DI distincte est exigée")
    commit = image.get("source_commit_sha")
    if isinstance(commit, str) and len(commit) == 40:
        for chemin, marqueur in MARQUEURS_CORRECTIF_DI.items():
            source = _git(racine, "show", f"{commit}:{chemin}")
            if source.returncode != 0:
                ecarts.append(f"DI : commit de build {commit} introuvable ou sans {chemin}")
                break
            if marqueur not in source.stdout:
                ecarts.append(f"DI : le commit de build ne porte pas le correctif ({chemin})")
        if _git(racine, "merge-base", "--is-ancestor", commit, "origin/main").returncode != 0:
            ecarts.append("DI : le commit de build n'est pas sur origin/main")
    return ecarts


def evaluer_di(
    racine: Path, document: dict, *, liens: dict[str, str], document_dh: dict | None
) -> list[str]:
    """Écarts de l'autorisation de reprise partielle DI. Liste vide = conforme."""
    ecarts = [
        f"DI : {cle} ne correspond pas au périmètre gouverné"
        for cle in (
            "kind", "amends", "granted_by_pull_request_approval_of", "effective_when", "release",
            "active_review", "partial_scope", "worker_b_pacing", "github_read_token", "targets",
            "operations", "stop_conditions", "expected_proof", "rollback",
        )
        if document.get(cle) != GABARIT_DI[cle]
    ]
    if document.get("consumed") is not False:
        ecarts.append("DI : autorisation déjà consommée")
    if document.get("expires_after_use") is not True:
        ecarts.append("DI : l'autorisation doit être à usage unique")
    for cle, chemin in (
        ("extends_dh", AUTORISATION_DH), ("extends_v4", AUTORISATION_V4),
        ("execution_plan", PLAN_DI), ("partial_identity", IDENTITE_DI),
    ):
        lien = document.get(cle) or {}
        if lien.get("path") != chemin or lien.get("sha256") != liens.get(chemin) or not liens.get(chemin):
            ecarts.append(f"DI : {cle} non lié à {chemin} (empreinte)")
    manquants = sorted(set(GABARIT_DI["forbidden"]) - set(document.get("forbidden") or []))
    if manquants:
        ecarts.append(f"DI : interdits manquants : {manquants}")
    declaration = document.get("authorization_statement") or ""
    ecarts.extend(f"DI : déclaration, mention manquante {m!r}" for m in MENTIONS_DI if m not in declaration)
    if document_dh is None:
        ecarts.append("DI : autorisation DH absente — DI ne l'amende que si elle existe")
    else:
        if document.get("probe_image") != document_dh.get("probe_image"):
            ecarts.append("DI : probe_image diffère de celle de DH — aucune reconstruction de la sonde")
        ecarts.extend(_ecarts_image_di(racine, document.get("runtime_image"),
                                       image_dh=document_dh.get("runtime_image")))
    return ecarts


def verifier_operation_di(racine: Path, operation: str, cible: dict) -> list[str]:
    """Contrôle avant une opération DI : base valide, DI fusionnée, conforme, image construite."""
    if operation not in OPERATIONS_DI:
        return [f"opération DI inconnue : {operation!r} — rien ne l'autorise"]
    ecarts = verifier(racine)
    chemin_di, chemin_dh = racine / AUTORISATION_DI, racine / AUTORISATION_DH
    if not chemin_di.is_file():
        return [*ecarts, f"aucune autorisation DI : {AUTORISATION_DI} absent (la proposition n'autorise rien)"]
    document = json.loads(chemin_di.read_text(encoding="utf-8"))
    document_dh = json.loads(chemin_dh.read_text(encoding="utf-8")) if chemin_dh.is_file() else None
    liens = {
        relatif: hashlib.sha256((racine / relatif).read_bytes()).hexdigest()
        for relatif in (AUTORISATION_DH, AUTORISATION_V4, PLAN_DI, IDENTITE_DI)
        if (racine / relatif).is_file()
    }
    ecarts += evaluer_di(racine, document, liens=liens, document_dh=document_dh)
    if operation not in (document.get("operations") or []):
        ecarts.append(f"{operation!r} n'est pas nommée par l'autorisation DI")
    attendue = OPERATIONS_DI[operation]["cible"]
    for cle in sorted(set(attendue) | set(cible)):
        if cible.get(cle) != attendue.get(cle):
            ecarts.append(f"{operation} : {cle} = {cible.get(cle)!r}, autorisé {attendue.get(cle)!r}")
    for relatif in (AUTORISATION_DI, IDENTITE_DI, PLAN_DI):
        sur_main = _git(racine, "show", f"origin/main:{relatif}")
        if sur_main.returncode != 0 or sur_main.stdout != (racine / relatif).read_text(encoding="utf-8"):
            ecarts.append(f"{relatif} n'est pas (ou pas à l'identique) sur origin/main")
    return ecarts

def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", default=None, help="opération de publication V4 à contrôler")
    parser.add_argument("--cible", default="{}", help="cible exacte, en JSON")
    args = parser.parse_args(argv)
    racine = Path(__file__).resolve().parents[2]
    if args.operation is None:
        ecarts = verifier(racine)
        print(json.dumps({"ssh_staging_authorized": not ecarts, "ecarts": ecarts}, ensure_ascii=False, indent=2))
        return 1 if ecarts else 0
    if args.operation in OPERATIONS_DI:
        ecarts = verifier_operation_di(racine, args.operation, json.loads(args.cible))
    elif args.operation in OPERATIONS_DH:
        ecarts = verifier_operation_dh(racine, args.operation, json.loads(args.cible))
    else:
        ecarts = verifier_operation(racine, args.operation, json.loads(args.cible))
    print(json.dumps({"operation": args.operation, "authorized": not ecarts, "ecarts": ecarts}, ensure_ascii=False, indent=2))
    return 1 if ecarts else 0


if __name__ == "__main__":
    raise SystemExit(main())
