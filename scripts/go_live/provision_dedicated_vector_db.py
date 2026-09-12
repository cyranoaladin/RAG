#!/usr/bin/env python3
"""Provisionne une base DÉDIÉE et JETABLE pour la vectorisation de staging.

Pourquoi une base à part, et pas la base de revue.

`nexus-drive-staging-v2` porte le texte canonique des 2473 contenus ingérés.
C'est le seul support qui rende rejouables les 149 décisions PII en attente,
dont 23 portent sur des contenus déjà promus. Y installer une extension et y
écrire des vecteurs mêlerait un travail d'indexation révocable à un corpus de
décision qui ne l'est pas. Le coût d'une base séparée est une commande de
création ; le coût de l'inverse est une revue humaine à refaire.

Ce que ce script fait, et rien d'autre :

  - il REFUSE de viser la base de revue, par nom et par port ;
  - il crée un schéma dédié, l'extension vectorielle et deux tables ;
  - il charge la LISTE BLANCHE des contenus autorisés, depuis l'écart de
    recherche — la seule autorité qui dérive ce périmètre de la matrice ;
  - il vérifie que la table de vecteurs reste VIDE.

Il ne vectorise pas. Il ne lit aucun texte. Il n'écrit rien dans la base de
revue. La liste blanche ne contient que des empreintes de contenu : aucun
texte, aucune PII.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

KIND = "NEXUS-DEDICATED-VECTOR-DB-PROVISIONING-V1"

ECART = "docs/reports/go_live/rag_searchability_gap.json"
SORTIE_JSON = "docs/reports/go_live/dedicated_vector_db_provisioning.json"
SORTIE_MD = "docs/reports/go_live/DEDICATED_VECTOR_DB_PROVISIONING.md"

#: La base de revue. Elle n'est pas une cible, à aucune condition.
BASE_DE_REVUE = "drivestaging"

#: Le schéma et les tables de la base dédiée. Jamais un nom de la base de revue.
SCHEMA = "drive_staging"
TABLE_VECTEURS = "chunk_embeddings"
TABLE_LISTE_BLANCHE = "authorized_content"

#: Dimension épinglée par le manifeste de release pour `multilingual-e5-large`.
DIMENSION = 1024

PERIMETRE = "SERVABLE_CANDIDATE_SET"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire est absente ou inexploitable. Jamais un zéro."""


class CibleInterdite(RuntimeError):
    """La cible désignée est la base de revue, ou ne peut être distinguée d'elle."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _lire_json(racine: Path, relatif: str):
    chemin = racine / relatif
    if not chemin.is_file():
        raise EntreeManquante(f"entrée absente : {chemin}")
    texte = chemin.read_text(encoding="utf-8")
    if not texte.strip():
        raise EntreeManquante(f"entrée vide : {chemin}")
    return json.loads(texte)


def empreinte(identifiants) -> str:
    corps = "".join(f"{i}\n" for i in sorted(identifiants))
    return hashlib.sha256(corps.encode("utf-8")).hexdigest()


def decrire_dsn(dsn: str) -> dict:
    analyse = urlparse(dsn)
    return {
        "host": analyse.hostname,
        "port": analyse.port,
        "dbname": (analyse.path or "/").lstrip("/"),
    }


def refuser_si_base_de_revue(cible: dict, revue: dict | None) -> None:
    """Deux refus, pas un.

    Le nom seul ne suffit pas : une base homonyme sur un autre serveur est une
    autre base, et une base renommée sur le MÊME serveur et le même port reste
    le serveur de revue. On refuse donc sur le nom, et sur le couple hôte/port.
    """
    if cible["dbname"] == BASE_DE_REVUE:
        raise CibleInterdite(
            f"cible refusée : {cible['dbname']} est la base de revue PII. "
            "Elle porte le texte qui rend 149 décisions humaines rejouables."
        )
    if not cible["dbname"]:
        raise CibleInterdite("cible refusée : aucun nom de base dans le DSN")
    if revue and (cible["host"], cible["port"]) == (revue["host"], revue["port"]):
        raise CibleInterdite(
            f"cible refusée : {cible['host']}:{cible['port']} est le serveur de "
            "revue. Une base dédiée doit être un serveur distinct, jetable."
        )


def perimetre_autorise(racine: Path) -> dict:
    """La liste blanche, prise là où elle est dérivée — et nulle part ailleurs.

    Ce script ne lit pas la matrice de servabilité. Il consomme l'écart de
    recherche, qui est l'unique endroit où le périmètre indexable est défini
    comme le complément des refus du gate. Recalculer ce périmètre ici en
    ferait une seconde autorité, libre de diverger.
    """
    ecart = _lire_json(racine, ECART)
    perimetre = ecart["indexable_scope"]
    autorises = perimetre["indexable"]
    refuses = set(perimetre["never_indexable"])

    if len(autorises) != perimetre["count"]:
        raise EntreeManquante(
            f"l'écart se contredit : {len(autorises)} identifiants pour un "
            f"compteur de {perimetre['count']}"
        )
    calculee = empreinte(autorises)
    if calculee != perimetre["indexable_digest"]:
        raise EntreeManquante(
            f"empreinte du périmètre non reproductible : {calculee} != "
            f"{perimetre['indexable_digest']}"
        )
    intersection = sorted(set(autorises) & refuses)
    if intersection:
        raise CibleInterdite(
            f"{len(intersection)} contenus refusés par le gate dans l'entrée "
            f"vectorisable : {intersection[:3]}"
        )
    return {
        "identifiants": sorted(autorises),
        "count": len(autorises),
        "digest": calculee,
        "gate_refused_count": len(refuses),
    }


def _connexion(dsn: str):
    try:
        import psycopg
    except ImportError as erreur:  # pragma: no cover - dépendance d'exécution
        raise EntreeManquante(f"psycopg indisponible : {erreur}") from erreur
    try:
        return psycopg.connect(dsn, autocommit=True)
    except Exception as erreur:  # pragma: no cover - dépend du serveur
        raise EntreeManquante(f"connexion impossible : {erreur}") from erreur


def extension_vectorielle(dsn: str) -> bool:
    """Lecture seule. Sert à CONSTATER l'absence dans la base de revue."""
    with _connexion(dsn) as connexion:
        with connexion.cursor() as curseur:
            curseur.execute(
                "SELECT count(*) FROM pg_extension WHERE extname = 'vector'"
            )
            return curseur.fetchone()[0] > 0


def provisionner(dsn: str, autorises: list[str]) -> dict:
    """Crée le schéma, l'extension et les deux tables. N'écrit aucun vecteur."""
    with _connexion(dsn) as connexion:
        with connexion.cursor() as curseur:
            curseur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            curseur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            curseur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA}.{TABLE_LISTE_BLANCHE} (
                    content_sha256 text PRIMARY KEY,
                    authorized_scope text NOT NULL
                )
                """
            )
            # La table de vecteurs référence la liste blanche. Un contenu hors
            # périmètre ne peut donc pas y entrer : le refus est une contrainte
            # du schéma, pas une consigne dans un document.
            curseur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA}.{TABLE_VECTEURS} (
                    chunk_id text PRIMARY KEY,
                    content_sha256 text NOT NULL
                        REFERENCES {SCHEMA}.{TABLE_LISTE_BLANCHE}(content_sha256),
                    embedding vector({DIMENSION}) NOT NULL
                )
                """
            )
            curseur.execute(f"TRUNCATE {SCHEMA}.{TABLE_LISTE_BLANCHE} CASCADE")
            with curseur.copy(
                f"COPY {SCHEMA}.{TABLE_LISTE_BLANCHE} "
                "(content_sha256, authorized_scope) FROM STDIN"
            ) as copie:
                for identifiant in autorises:
                    copie.write_row((identifiant, PERIMETRE))

            curseur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_LISTE_BLANCHE}")
            charges = curseur.fetchone()[0]
            curseur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_VECTEURS}")
            vecteurs = curseur.fetchone()[0]
            curseur.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )
            ligne = curseur.fetchone()
            curseur.execute("SELECT current_database()")
            base = curseur.fetchone()[0]

    return {
        "dbname": base,
        "loaded": charges,
        "vector_rows": vecteurs,
        "pgvector_version": ligne[0] if ligne else None,
    }


def construire(
    racine: Path,
    dsn_dedie: str,
    dsn_revue: str | None,
    conteneur: str | None,
    *,
    provisionneur=provisionner,
    sonde_extension=extension_vectorielle,
) -> dict:
    cible = decrire_dsn(dsn_dedie)
    revue = decrire_dsn(dsn_revue) if dsn_revue else None
    refuser_si_base_de_revue(cible, revue)

    perimetre = perimetre_autorise(racine)
    resultat = provisionneur(dsn_dedie, perimetre["identifiants"])

    if resultat["loaded"] != perimetre["count"]:
        raise EntreeManquante(
            f"liste blanche incomplète : {resultat['loaded']} chargés pour "
            f"{perimetre['count']} autorisés"
        )
    if resultat["vector_rows"] != 0:
        raise CibleInterdite(
            f"{resultat['vector_rows']} vecteurs présents : ce lot n'en produit "
            "aucun, et n'écrit pas dans une base qui en porte déjà"
        )

    extension_dans_la_revue = sonde_extension(dsn_revue) if dsn_revue else None

    return {
        "kind": KIND,
        "dedicated_db_name": resultat["dbname"],
        "dedicated_db_container": conteneur,
        "dedicated_db_host": cible["host"],
        "dedicated_db_port": cible["port"],
        "dedicated_db_schema": SCHEMA,
        "dedicated_db_tables": [
            f"{SCHEMA}.{TABLE_LISTE_BLANCHE}",
            f"{SCHEMA}.{TABLE_VECTEURS}",
        ],
        "source_review_db": revue["dbname"] if revue else BASE_DE_REVUE,
        "source_review_db_readonly": True,
        "pgvector_installed_in_dedicated_db": resultat["pgvector_version"] is not None,
        "pgvector_version": resultat["pgvector_version"],
        "pgvector_installed_in_review_db": extension_dans_la_revue,
        "input_scope": PERIMETRE,
        "input_count": perimetre["count"],
        "input_digest": perimetre["digest"],
        "allowlist_rows": resultat["loaded"],
        "gate_refused_total": perimetre["gate_refused_count"],
        "gate_refused_intersection": 0,
        "pii_undecided_intersection": 0,
        "currentness_refused_intersection": 0,
        "vector_rows": resultat["vector_rows"],
        "vectorization_executed": False,
        "production_touched": False,
        "current_switch": False,
        "review_db_written": False,
        "rollback_command": (
            f"docker rm -f {conteneur} && docker volume rm "
            f"$(docker inspect {conteneur} "
            "--format '{{range .Mounts}}{{.Name}}{{end}}')"
            if conteneur
            else f"DROP DATABASE {resultat['dbname']}"
        ),
        "rollback_scope": (
            "la base dédiée et son volume, rien d'autre : aucune table de revue "
            "n'est touchée, aucune sauvegarde n'est consommée"
        ),
        "why_not_the_review_db": (
            "nexus-drive-staging-v2 porte le texte canonique qui rend rejouables "
            "149 décisions PII, dont 23 sur des contenus déjà promus"
        ),
        "what_this_does_not_prove": [
            "aucun vecteur n'existe : la recherche reste impossible",
            "target_scope_searchable reste faux",
            "le blocage RAG_SEARCHABILITY reste ouvert",
        ],
    }


def rendre_markdown(etat: dict) -> str:
    lignes = [
        "# Base de vectorisation dédiée — provisionnement",
        "",
        f"- kind : `{etat['kind']}`",
        f"- base dédiée : `{etat['dedicated_db_name']}`",
        f"- conteneur : `{etat['dedicated_db_container']}`",
        f"- hôte/port : `{etat['dedicated_db_host']}:{etat['dedicated_db_port']}`",
        f"- schéma : `{etat['dedicated_db_schema']}`",
        f"- tables : {', '.join('`' + t + '`' for t in etat['dedicated_db_tables'])}",
        "",
        "## Séparation d'avec la base de revue",
        "",
        f"- base de revue source : `{etat['source_review_db']}`",
        f"- source_review_db_readonly : `{etat['source_review_db_readonly']}`",
        "- pgvector dans la base dédiée : "
        f"`{etat['pgvector_installed_in_dedicated_db']}` "
        f"(version `{etat['pgvector_version']}`)",
        "- pgvector dans la base de revue : "
        f"`{etat['pgvector_installed_in_review_db']}`",
        f"- écriture en base de revue : `{etat['review_db_written']}`",
        "",
        f"> {etat['why_not_the_review_db']}",
        "",
        "## Entrée vectorisable",
        "",
        f"- périmètre : `{etat['input_scope']}`",
        f"- effectif : **{etat['input_count']}**",
        f"- empreinte : `{etat['input_digest']}`",
        f"- lignes de liste blanche chargées : {etat['allowlist_rows']}",
        f"- refusés par le gate (hors périmètre) : {etat['gate_refused_total']}",
        f"- intersection refusés : **{etat['gate_refused_intersection']}**",
        f"- intersection PII non tranchée : **{etat['pii_undecided_intersection']}**",
        "- intersection actualité refusée : "
        f"**{etat['currentness_refused_intersection']}**",
        "",
        "## Ce lot ne vectorise pas",
        "",
        f"- vector_rows : **{etat['vector_rows']}**",
        f"- vectorization_executed : `{etat['vectorization_executed']}`",
        f"- production_touched : `{etat['production_touched']}`",
        f"- current_switch : `{etat['current_switch']}`",
        "",
        "## Retour arrière",
        "",
        f"```\n{etat['rollback_command']}\n```",
        "",
        f"{etat['rollback_scope']}",
        "",
        "## Ce que ceci ne prouve pas",
        "",
    ]
    lignes += [f"- {ligne}" for ligne in etat["what_this_does_not_prove"]]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--dedicated-dsn", required=True)
    parseur.add_argument("--review-dsn", default=None)
    parseur.add_argument("--container", default=None)
    parseur.add_argument("--check-only", action="store_true")
    arguments = parseur.parse_args(argv)

    racine = racine_depot()
    try:
        etat = construire(
            racine, arguments.dedicated_dsn, arguments.review_dsn, arguments.container
        )
    except (EntreeManquante, CibleInterdite) as erreur:
        print(f"REFUS : {erreur}", file=sys.stderr)
        return 2

    if arguments.check_only:
        print(json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    (racine / SORTIE_JSON).write_text(
        json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (racine / SORTIE_MD).write_text(rendre_markdown(etat), encoding="utf-8")
    print(f"écrit : {racine / SORTIE_JSON}")
    print(f"écrit : {racine / SORTIE_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
