#!/usr/bin/env python3
"""Mesure l'ingestion réelle dans une base, et refuse de la confondre avec le service.

Le plan de clôture déclarait trois niveaux « non mesurables depuis le dépôt » :
ingéré, exploitable par recherche, servi en production. C'était exact — depuis
le dépôt seul. Ce n'est pas une raison pour les laisser indéfiniment
indéterminés : ils sont mesurables dès qu'une base est nommée.

Ce script prend une base et la mesure. Il ne suppose rien de son rôle.

Le piège qu'il refuse : conclure d'une ingestion complète que le corpus est
servi. Ingérer un document, c'est en stocker le texte. Le rendre exploitable
par recherche vectorielle, c'est en stocker les vecteurs. Les servir en
production, c'est encore autre chose, et aucune base de préparation ne peut en
témoigner. Un rapport qui écrirait « 100 % ingéré » sans dire lequel de ces
trois niveaux il mesure fabriquerait une assurance fausse.

Le niveau « servi en production » n'est jamais prononcé ici. Une base dont on
n'a pas prouvé qu'elle est celle de la production ne prouve rien sur la
production, et ce script n'a aucun moyen de le prouver.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

KIND = "NEXUS-INGESTION-AUDIT-V1"

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"

#: Le seul niveau que ce script ne prononce jamais.
NIVEAU_JAMAIS_PRONONCE = "contenu réellement servi en production"


def identifier_source(dsn: str) -> dict:
    """Nomme la base auditée sans recopier d'identifiants.

    Un rapport qui ne dit pas quelle base il a mesurée n'est pas opposable.
    Un rapport qui recopie le DSN publie un secret. On garde l'hôte, le port
    et le nom de la base ; jamais l'utilisateur ni le mot de passe.
    """
    from urllib.parse import urlparse

    analyse = urlparse(dsn)
    return {
        "host": analyse.hostname or "",
        "port": analyse.port or "",
        "dbname": (analyse.path or "").lstrip("/"),
    }


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au calcul est absente ou inexploitable."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _lire_json(chemin: Path):
    if not chemin.is_file():
        raise EntreeManquante(f"entrée absente : {chemin}")
    return json.loads(chemin.read_text(encoding="utf-8"))


def interroger(dsn: str, schema: str) -> dict:
    """Lecture seule. Aucune écriture n'est émise par ce script."""
    try:
        import psycopg
    except ModuleNotFoundError as erreur:  # pragma: no cover - dépend de l'env
        raise EntreeManquante(f"psycopg indisponible : {erreur}") from erreur

    try:
        connexion = psycopg.connect(dsn)
    except psycopg.OperationalError as erreur:
        # Un refus de connexion est une entrée manquante, pas une mesure nulle.
        # Le message de la base peut porter le DSN : on ne le recopie pas.
        raise EntreeManquante(
            f"connexion refusée par la base ({type(erreur).__name__})"
        ) from None

    with connexion:
        with connexion.cursor() as curseur:
            curseur.execute(
                "select count(*) from pg_namespace where nspname = %s", (schema,)
            )
            if not curseur.fetchone()[0]:
                raise EntreeManquante(f"schéma « {schema} » absent de la base")

            curseur.execute(
                "select c.relname from pg_class c join pg_namespace n"
                " on n.oid = c.relnamespace where n.nspname = %s and c.relkind = 'r'",
                (schema,),
            )
            tables = {ligne[0] for ligne in curseur.fetchall()}
            if "artifacts" not in tables:
                raise EntreeManquante(
                    f"table « artifacts » absente du schéma {schema} ;"
                    f" tables vues : {sorted(tables)}"
                )

            curseur.execute(f'select content_sha256 from "{schema}".artifacts')  # noqa: S608
            contenus = {ligne[0] for ligne in curseur.fetchall() if ligne[0]}

            curseur.execute(
                f'select count(*) from "{schema}".artifacts'  # noqa: S608
                " where canonical_text_sha256 is not null"
            )
            avec_texte = curseur.fetchone()[0]

            # L'exploitabilité par recherche vectorielle se lit à la présence de
            # vecteurs, pas à celle de texte.
            curseur.execute(
                "select count(*) from information_schema.columns"
                " where table_schema = %s and udt_name = 'vector'",
                (schema,),
            )
            colonnes_vecteur = curseur.fetchone()[0]

            curseur.execute("select count(*) from pg_extension where extname = 'vector'")
            extension_vecteur = bool(curseur.fetchone()[0])

    return {
        "contenus": contenus,
        "avec_texte_canonique": avec_texte,
        "colonnes_vecteur": colonnes_vecteur,
        "extension_vecteur": extension_vecteur,
        "tables": sorted(tables),
    }


def auditer(racine: Path, dsn: str, schema: str, *, interrogateur=interroger) -> dict:
    mesure = interrogateur(dsn, schema)
    lignes = _lire_json(racine / MATRICE).get("rows")
    if not lignes:
        raise EntreeManquante(f"matrice sans lignes : {racine / MATRICE}")
    matrice = {ligne["content_sha256"] for ligne in lignes}

    ingeres = mesure["contenus"]
    recherchable = bool(mesure["colonnes_vecteur"]) and mesure["extension_vecteur"]

    return {
        "kind": KIND,
        "source": identifier_source(dsn),
        "schema": schema,
        "tables": mesure["tables"],
        "ingested": {
            "contenus": len(ingeres),
            "avec_texte_canonique": mesure["avec_texte_canonique"],
            "inconnus_de_la_matrice": sorted(ingeres - matrice),
        },
        "searchable": {
            "vector_columns": mesure["colonnes_vecteur"],
            "vector_extension": mesure["extension_vecteur"],
            "searchable_contents": len(ingeres) if recherchable else 0,
            "why": (
                "des vecteurs sont présents"
                if recherchable
                else "aucun vecteur : le texte est stocké, pas indexé pour la recherche"
            ),
        },
        "served_in_production": {
            "measured": False,
            "why": (
                "cette base n'est pas prouvée être celle de la production ; "
                "aucune mesure prise ici ne peut en témoigner"
            ),
        },
        "never_asserted_here": [NIVEAU_JAMAIS_PRONONCE],
    }


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--dsn", required=True)
    analyseur.add_argument("--schema", default="drive_staging")
    analyseur.add_argument(
        "--output", default="docs/reports/go_live/ingestion_audit.json"
    )
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    try:
        rapport = auditer(racine, arguments.dsn, arguments.schema)
    except EntreeManquante as erreur:
        print(f"ENTREE_MANQUANTE: {erreur}", file=sys.stderr)
        return 2

    chemin = racine / arguments.output
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(rapport, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"écrit : {chemin}")
    print(
        json.dumps(
            {
                "ingested": rapport["ingested"]["contenus"],
                "searchable": rapport["searchable"]["searchable_contents"],
                "served_in_production_measured": rapport["served_in_production"][
                    "measured"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
