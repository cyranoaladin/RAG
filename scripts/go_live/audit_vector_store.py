#!/usr/bin/env python3
"""Mesure les vecteurs LÀ OÙ ILS SONT : dans la base dédiée.

L'écart de recherche mesurait jusqu'ici `staging_vectors_present` sur la base
de REVUE. C'était juste tant qu'aucun vecteur n'existait nulle part ; ça
devient faux dès que la vectorisation écrit dans une base dédiée. Le compteur
serait resté à zéro après une vectorisation réussie, et le lot suivant en
aurait conclu qu'elle n'avait rien produit.

Cet audit sépare donc deux faits sur deux bases différentes :
  - la base DÉDIÉE porte les vecteurs, et c'est elle qu'on mesure ;
  - la base de REVUE est mesurée pour une seule chose : prouver qu'elle reste
    intacte, sans extension vectorielle et sans vecteur.

Aucun identifiant de connexion n'entre dans le rapport : les DSN viennent de
l'environnement, seuls l'hôte, le port et le nom de base sont consignés.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

KIND = "NEXUS-VECTOR-STORE-AUDIT-V1"

SORTIE_JSON = "docs/reports/go_live/vector_store_audit.json"
SORTIE_MD = "docs/reports/go_live/VECTOR_STORE_AUDIT.md"

VAR_DEDIEE = "DEDICATED_VECTOR_DB_URL"
VAR_REVUE = "REVIEW_DB_READONLY_URL"

SCHEMA = "drive_staging"
TABLE_VECTEURS = "chunk_embeddings"
TABLE_PASSAGES = "publication_chunks"
TABLE_LISTE_BLANCHE = "authorized_content"

DIMENSION = 1024


class EntreeManquante(RuntimeError):
    """Une mesure nécessaire est absente. Jamais un zéro."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _source(dsn: str) -> dict:
    analyse = urlparse(dsn)
    return {
        "host": analyse.hostname,
        "port": analyse.port,
        "dbname": (analyse.path or "/").lstrip("/"),
    }


def mesurer_dediee(dsn: str) -> dict:  # pragma: no cover - dépend du serveur
    import psycopg  # noqa: PLC0415

    with psycopg.connect(dsn) as cx, cx.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_extension WHERE extname='vector'")
        extension = cur.fetchone()[0] > 0
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_VECTEURS}")
        vecteurs = cur.fetchone()[0]
        cur.execute(
            f"SELECT count(DISTINCT content_sha256) FROM {SCHEMA}.{TABLE_VECTEURS}"
        )
        contenus = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_PASSAGES}")
        passages = cur.fetchone()[0]
        cur.execute(
            f"SELECT count(DISTINCT content_sha256) FROM {SCHEMA}.{TABLE_PASSAGES}"
        )
        contenus_passages = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_LISTE_BLANCHE}")
        liste_blanche = cur.fetchone()[0]
        cur.execute(
            f"SELECT count(*) FROM {SCHEMA}.{TABLE_VECTEURS} "
            "WHERE vector_dims(embedding) <> %s",
            (DIMENSION,),
        )
        dimensions_fausses = cur.fetchone()[0]
        cur.execute(
            f"SELECT count(*) FROM {SCHEMA}.{TABLE_VECTEURS} v WHERE NOT EXISTS "
            f"(SELECT 1 FROM {SCHEMA}.{TABLE_LISTE_BLANCHE} a "
            "WHERE a.content_sha256 = v.content_sha256)"
        )
        hors_liste = cur.fetchone()[0]
    return {
        "source": _source(dsn),
        "vector_extension": extension,
        "vector_rows": vecteurs,
        "vectorized_contents": contenus,
        "passages": passages,
        "passage_contents": contenus_passages,
        "allowlist_rows": liste_blanche,
        "dimension_mismatch": dimensions_fausses,
        "unauthorized_rows": hors_liste,
    }


def mesurer_revue(dsn: str) -> dict:  # pragma: no cover - dépend du serveur
    """Lecture seule, et pour une seule question : est-elle restée intacte ?"""
    import psycopg  # noqa: PLC0415

    with psycopg.connect(
        dsn, options="-c default_transaction_read_only=on"
    ) as cx, cx.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_extension WHERE extname='vector'")
        extension = cur.fetchone()[0] > 0
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE udt_name = 'vector'"
        )
        colonnes = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM drive_staging.artifacts")
        artefacts = cur.fetchone()[0]
    return {
        "source": _source(dsn),
        "vector_extension": extension,
        "vector_columns": colonnes,
        "artifacts": artefacts,
    }


def construire(dediee: dict, revue: dict) -> dict:
    coherent = (
        dediee["vector_rows"] > 0
        and dediee["dimension_mismatch"] == 0
        and dediee["vector_extension"]
    )
    return {
        "kind": KIND,
        "measured_on": "DEDICATED_VECTOR_DB",
        "why_not_the_review_db": (
            "les vecteurs sont écrits dans la base dédiée ; mesurer la base de "
            "revue rendrait zéro après une vectorisation réussie et ferait "
            "conclure qu'elle n'a rien produit"
        ),
        "dedicated": dediee,
        "review": revue,
        "staging_vectors_present": dediee["vector_rows"],
        "vector_dimensions_consistent": coherent,
        "review_db_written": False,
        "review_db_intact": (
            not revue["vector_extension"] and revue["vector_columns"] == 0
        ),
        "pgvector_installed_in_review_db": revue["vector_extension"],
        "what_this_does_not_prove": [
            "ne prouve pas que le retrieval fonctionne",
            "ne prouve pas que les citations sont disponibles",
            "ne rend pas target_scope_searchable vrai",
        ],
    }


def rendre_markdown(etat: dict) -> str:
    d, r = etat["dedicated"], etat["review"]
    return "\n".join(
        [
            "# Audit du magasin de vecteurs",
            "",
            f"- kind : `{etat['kind']}`",
            f"- mesuré sur : **{etat['measured_on']}**",
            "",
            f"> {etat['why_not_the_review_db']}",
            "",
            "## Base dédiée",
            "",
            "| Mesure | Valeur |",
            "|---|---:|",
            f"| base | `{d['source']['dbname']}` |",
            f"| hôte/port | `{d['source']['host']}:{d['source']['port']}` |",
            f"| extension vectorielle | `{d['vector_extension']}` |",
            f"| **vecteurs** | **{d['vector_rows']}** |",
            f"| contenus vectorisés | {d['vectorized_contents']} |",
            f"| passages re-découpés | {d['passages']} |",
            f"| contenus porteurs de passages | {d['passage_contents']} |",
            f"| liste blanche | {d['allowlist_rows']} |",
            f"| dimensions fausses | {d['dimension_mismatch']} |",
            f"| lignes hors liste blanche | {d['unauthorized_rows']} |",
            "",
            "## Base de revue — mesurée pour prouver qu'elle est intacte",
            "",
            f"- base : `{r['source']['dbname']}` "
            f"(`{r['source']['host']}:{r['source']['port']}`)",
            f"- extension vectorielle : `{r['vector_extension']}`",
            f"- colonnes vectorielles : {r['vector_columns']}",
            f"- artefacts : {r['artifacts']}",
            f"- `review_db_intact` : `{etat['review_db_intact']}`",
            f"- `review_db_written` : `{etat['review_db_written']}`",
            "",
            "## Ce que ceci ne prouve pas",
            "",
            *[f"- {ligne}" for ligne in etat["what_this_does_not_prove"]],
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    racine = racine_depot()
    try:
        for nom in (VAR_DEDIEE, VAR_REVUE):
            if not os.environ.get(nom, "").strip():
                raise EntreeManquante(f"{nom} n'est pas défini")
        etat = construire(
            mesurer_dediee(os.environ[VAR_DEDIEE]),
            mesurer_revue(os.environ[VAR_REVUE]),
        )
    except EntreeManquante as erreur:
        print(f"REFUS : {erreur}", file=sys.stderr)
        return 2

    (racine / SORTIE_JSON).write_text(
        json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (racine / SORTIE_MD).write_text(rendre_markdown(etat), encoding="utf-8")
    print(f"écrit : {racine / SORTIE_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
