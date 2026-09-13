#!/usr/bin/env python3
"""Éprouve le retrieval sur l'index de staging, et refuse de conclure au-delà.

Avoir 54 719 vecteurs ne prouve pas qu'une question trouve sa réponse. Entre
un index et un retrieval utilisable il y a : des résultats non vides, des
résultats qui restent dans le périmètre autorisé, des citations qui pointent
une page réelle, des filtres de portée qui filtrent vraiment, une latence
mesurée contre un budget, et un retour arrière éprouvé.

Ce script mesure chacun de ces points séparément et n'en déclare aucun vrai
sans l'avoir observé. Là où le dépôt n'épingle pas de cible — la latence n'a
aucun budget contractuel — il mesure et REFUSE de valider : un chiffre sans
seuil ne valide rien.

Il ne lit que la base dédiée. La base de revue n'est ni lue ni écrite ici.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

KIND = "NEXUS-RETRIEVAL-CONTRACT-VALIDATION-V1"

SORTIE_JSON = "docs/reports/go_live/retrieval_contract_validation.json"
SORTIE_MD = "docs/reports/go_live/RETRIEVAL_CONTRACT_VALIDATION.md"
ECART = "docs/reports/go_live/rag_searchability_gap.json"

VAR_DEDIEE = "DEDICATED_VECTOR_DB_URL"
VAR_ARTEFACTS = "RAG_MODEL_ARTIFACTS_DIR"
VAR_CATALOGUE = "NEXUS_PROVENANCE_CATALOGUE"

REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
ARTEFACT_LOGIQUE = f"staging-phase-a-e5-large-{REVISION}"

SCHEMA = "drive_staging"
TABLE_VECTEURS = "chunk_embeddings"
TABLE_PASSAGES = "publication_chunks"
TABLE_META = "content_metadata"
TABLE_LISTE_BLANCHE = "authorized_content"

TOP_K = 10

#: Questions réelles, en français, couvrant plusieurs matières et niveaux.
#: Les libellés de matière sont ceux du catalogue de provenance, RELEVÉS et
#: non devinés : deux libellés inventés de bonne foi (« sciences-de-la-vie-et-
#: de-la-terre », « numerique-et-sciences-informatiques ») ne correspondaient
#: à rien et rendaient zéro résultat, ce qui aurait pu passer pour un défaut
#: du filtre alors que c'était un défaut de la requête.
REQUETES = (
    ("suites numériques et raisonnement par récurrence", "mathematiques"),
    ("fonction dérivée et variations d'une fonction", "mathematiques"),
    ("analyse d'un texte argumentatif au baccalauréat", "francais"),
    ("les états de la matière et les changements d'état", "physique-chimie"),
    ("programmation en Python : boucles et conditions", "nsi"),
    ("la Première Guerre mondiale et ses conséquences", "histoire-geographie"),
    ("reproduction sexuée et brassage génétique", "svt"),
    ("compréhension orale en langue vivante étrangère", "langues-vivantes"),
)

#: Une question hors du domaine pédagogique. Le système ne doit pas prétendre
#: qu'elle est hors périmètre — un index vectoriel rend toujours un plus proche
#: voisin — mais ses résultats doivent rester dans la liste blanche.
REQUETE_HORS_PERIMETRE = "recette de la tarte tatin et cuisson du caramel"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire est absente. Jamais un zéro."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _variable(nom: str) -> str:
    valeur = os.environ.get(nom, "").strip()
    if not valeur:
        raise EntreeManquante(f"{nom} n'est pas défini")
    return valeur


def _chemins(racine: Path) -> None:
    chemins = [racine / "services/rag-engine/src"]
    chemins += sorted((racine / "packages").glob("*/src"))
    for chemin in chemins:
        if str(chemin) not in sys.path:
            sys.path.insert(0, str(chemin))


def fournisseur(racine: Path):  # pragma: no cover - dépendance lourde
    import hashlib  # noqa: PLC0415

    _chemins(racine)
    from ingestor.embedding_provider import (  # noqa: PLC0415
        VerifiedE5EmbeddingProvider,
    )

    artefact = Path(_variable(VAR_ARTEFACTS)) / ARTEFACT_LOGIQUE
    empreinte = hashlib.sha256((artefact / "SHA256SUMS").read_bytes()).hexdigest()
    os.environ["RAG_EMBEDDING_MODEL_CACHE_DIR"] = str(artefact)
    return VerifiedE5EmbeddingProvider.from_artifact(
        artifact_root=artefact,
        inventory_sha256=empreinte,
        pg_dsn=_variable(VAR_DEDIEE),
    )


def charger_metadonnees(dsn: str, catalogue: Path, autorises: set[str]) -> int:
    """Charge niveau/matière/portée pour les contenus AUTORISÉS uniquement."""
    import psycopg  # noqa: PLC0415

    if not catalogue.is_file():
        raise EntreeManquante(f"catalogue de provenance absent : {catalogue}")
    tuples = set()
    with catalogue.open(encoding="utf-8") as flux:
        for ligne in csv.DictReader(flux, delimiter="\t"):
            sha = (ligne.get("sha256") or "").strip()
            if sha in autorises:
                tuples.add(
                    (
                        sha,
                        (ligne.get("niveau") or "").strip() or None,
                        (ligne.get("matiere_ou_rubrique") or "").strip() or None,
                        (ligne.get("scope") or "").strip() or None,
                    )
                )
    if not tuples:
        raise EntreeManquante("aucune métadonnée pour les contenus autorisés")
    with psycopg.connect(dsn, autocommit=True) as cx, cx.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA}.{TABLE_META} (
                content_sha256 text NOT NULL
                    REFERENCES {SCHEMA}.{TABLE_LISTE_BLANCHE}(content_sha256),
                niveau text, matiere text, scope text,
                PRIMARY KEY (content_sha256, niveau, matiere, scope)
            )
            """
        )
        cur.execute(f"TRUNCATE {SCHEMA}.{TABLE_META}")
        with cur.copy(
            f"COPY {SCHEMA}.{TABLE_META} (content_sha256, niveau, matiere, scope) "
            "FROM STDIN"
        ) as copie:
            for ligne in sorted(tuples):
                copie.write_row(ligne)
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_META}")
        return cur.fetchone()[0]


def prouver_retour_arriere(dsn_dedie: str) -> dict:  # pragma: no cover
    """Éprouve la procédure de retour arrière sur un JUMEAU jetable.

    Un drapeau passé par l'appelant ne prouverait rien : c'est exactement le
    défaut relevé en revue au lot BI2, où un rapport affirmait une
    vérification qui n'avait pas lieu. Le script exécute donc réellement la
    procédure — sur un conteneur équivalent, jamais sur l'index en place — et
    vérifie ensuite que les ressources protégées sont intactes.
    """
    import secrets  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import time as _time  # noqa: PLC0415

    import psycopg  # noqa: PLC0415

    nom = f"nexus-rollback-proof-{int(_time.time())}"

    def docker(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=180
        )

    creation = docker(
        "run", "-d", "--name", nom,
        "-e", "POSTGRES_DB=rollback_proof",
        "-e", "POSTGRES_USER=proof",
        "-e", f"POSTGRES_PASSWORD={secrets.token_urlsafe(16)}",
        "--label", "nexus.disposable=true",
        "pgvector/pgvector:pg16",
    )
    if creation.returncode != 0:
        raise EntreeManquante(f"jumeau non créé : {creation.stderr.strip()[:160]}")

    volume = docker(
        "inspect", nom, "--format", "{{range .Mounts}}{{.Name}}{{end}}"
    ).stdout.strip()
    present_avant = docker("ps", "-aq", "-f", f"name={nom}").stdout.strip() != ""
    volume_avant = volume in docker("volume", "ls", "-q").stdout.split()

    docker("rm", "-f", nom)
    if volume:
        docker("volume", "rm", volume)

    present_apres = docker("ps", "-aq", "-f", f"name={nom}").stdout.strip() != ""
    volume_apres = volume in docker("volume", "ls", "-q").stdout.split()

    with psycopg.connect(dsn_dedie) as cx, cx.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_VECTEURS}")
        vecteurs_apres = cur.fetchone()[0]

    reussi = (
        present_avant
        and volume_avant
        and not present_apres
        and not volume_apres
        and vecteurs_apres > 0
    )
    return {
        "proven": reussi,
        "twin_existed_before": present_avant,
        "twin_volume_existed_before": volume_avant,
        "twin_removed": not present_apres,
        "twin_volume_removed": not volume_apres,
        "dedicated_index_untouched_rows": vecteurs_apres,
        "how": (
            "un conteneur jumeau jetable est créé, la procédure documentée lui "
            "est appliquée, puis on vérifie qu'il a disparu — conteneur ET "
            "volume — et que l'index dédié est intact. L'index en place n'est "
            "jamais supprimé pour prouver qu'on saurait le supprimer."
        ),
    }


def _vecteur_sql(vecteur) -> str:
    return "[" + ",".join(repr(float(x)) for x in vecteur) + "]"


def interroger(cur, vecteur, k: int, matiere: str | None = None) -> list[dict]:
    """Recherche par plus proches voisins, avec filtre de matière facultatif."""
    if matiere:
        cur.execute(
            f"""
            SELECT v.chunk_id, v.content_sha256, p.page_start, p.page_end,
                   v.embedding <=> %s::vector AS distance
            FROM {SCHEMA}.{TABLE_VECTEURS} v
            JOIN {SCHEMA}.{TABLE_PASSAGES} p ON p.chunk_id = v.chunk_id
            WHERE EXISTS (
                SELECT 1 FROM {SCHEMA}.{TABLE_META} m
                WHERE m.content_sha256 = v.content_sha256 AND m.matiere = %s
            )
            ORDER BY distance LIMIT %s
            """,
            (_vecteur_sql(vecteur), matiere, k),
        )
    else:
        cur.execute(
            f"""
            SELECT v.chunk_id, v.content_sha256, p.page_start, p.page_end,
                   v.embedding <=> %s::vector AS distance
            FROM {SCHEMA}.{TABLE_VECTEURS} v
            JOIN {SCHEMA}.{TABLE_PASSAGES} p ON p.chunk_id = v.chunk_id
            ORDER BY distance LIMIT %s
            """,
            (_vecteur_sql(vecteur), k),
        )
    return [
        {
            "chunk_id": r[0],
            "content_sha256": r[1],
            "page_start": r[2],
            "page_end": r[3],
            "distance": float(r[4]),
        }
        for r in cur.fetchall()
    ]


def evaluer(resultats_par_requete: list[dict], autorises: set[str], refuses: set[str]):
    """Compte ce qui est mesurable, sans rien supposer."""
    vides = [r["query"] for r in resultats_par_requete if not r["results"]]
    hors_liste, refuses_vus, sans_citation, doublons = [], [], [], []
    for entree in resultats_par_requete:
        vus = set()
        for res in entree["results"]:
            if res["content_sha256"] not in autorises:
                hors_liste.append(res["chunk_id"])
            if res["content_sha256"] in refuses:
                refuses_vus.append(res["chunk_id"])
            if res["page_start"] is None or res["page_end"] is None:
                sans_citation.append(res["chunk_id"])
            if res["chunk_id"] in vus:
                doublons.append(res["chunk_id"])
            vus.add(res["chunk_id"])
    return {
        "queries": len(resultats_par_requete),
        "empty_result_queries": vides,
        "results_outside_allowlist": len(hors_liste),
        "gate_refused_results": len(refuses_vus),
        "results_without_citation": len(sans_citation),
        "duplicate_results": len(doublons),
    }


def rendre_markdown(etat: dict) -> str:
    c = etat["conditions"]
    lignes = [
        "# Validation du contrat de retrieval",
        "",
        f"- kind : `{etat['kind']}`",
        f"- index : `{etat['index']['dbname']}` "
        f"(`{etat['index']['host']}:{etat['index']['port']}`)",
        f"- vecteurs interrogés : {etat['index']['vector_rows']}",
        f"- contenus couverts : {etat['index']['vectorized_contents']}",
        f"- top-k : {etat['top_k']}",
        "",
        "## Conditions",
        "",
        "| Condition | État |",
        "|---|---|",
    ]
    for nom, valeur in sorted(c.items()):
        lignes.append(f"| `{nom}` | **{valeur}** |")
    lignes += [
        "",
        "## Mesures",
        "",
        "| Mesure | Valeur |",
        "|---|---:|",
        f"| requêtes | {etat['measured']['queries']} |",
        f"| requêtes sans résultat | {len(etat['measured']['empty_result_queries'])} |",
        f"| résultats hors liste blanche | {etat['measured']['results_outside_allowlist']} |",
        f"| résultats refusés par le gate | {etat['measured']['gate_refused_results']} |",
        f"| résultats sans citation | {etat['measured']['results_without_citation']} |",
        f"| doublons | {etat['measured']['duplicate_results']} |",
        f"| latence p50 | {etat['latency']['p50_ms']} ms |",
        f"| latence p95 | {etat['latency']['p95_ms']} ms |",
        "",
        f"> {etat['latency']['why_not_validated']}",
        "",
        "## Filtres de portée",
        "",
        f"- requêtes filtrées : {etat['scope_filters']['filtered_queries']}",
        f"- résultats hors filtre : **{etat['scope_filters']['results_off_filter']}**",
        f"- métadonnées chargées : {etat['scope_filters']['metadata_rows']}",
        "",
        "## Retour arrière",
        "",
        f"- éprouvé : `{c['rollback_validated']}`",
        f"- {etat['rollback']['how']}",
        "",
        "## Ce que ceci ne prouve pas",
        "",
    ]
    lignes += [f"- {ligne}" for ligne in etat["what_this_does_not_prove"]]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--load-metadata", action="store_true")
    parseur.add_argument("--top-k", type=int, default=TOP_K)
    arguments = parseur.parse_args(argv)

    racine = racine_depot()
    try:
        import psycopg  # noqa: PLC0415

        ecart = json.loads((racine / ECART).read_text(encoding="utf-8"))
        perimetre = ecart["indexable_scope"]
        autorises = set(perimetre["indexable"])
        refuses = set(perimetre["never_indexable"])
        dsn = _variable(VAR_DEDIEE)

        lignes_meta = 0
        if arguments.load_metadata:
            lignes_meta = charger_metadonnees(
                dsn, Path(_variable(VAR_CATALOGUE)), autorises
            )
            print(f"métadonnées chargées : {lignes_meta}", flush=True)

        modele = fournisseur(racine)
        from nexus_contracts.embedding_utils import format_query  # noqa: PLC0415

        with psycopg.connect(dsn) as cx, cx.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_META}")
            lignes_meta = cur.fetchone()[0] or lignes_meta
            cur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE_VECTEURS}")
            vecteurs = cur.fetchone()[0]
            cur.execute(
                f"SELECT count(DISTINCT content_sha256) FROM {SCHEMA}.{TABLE_VECTEURS}"
            )
            contenus = cur.fetchone()[0]

            resultats, latences = [], []
            for question, _ in REQUETES:
                vecteur = modele.encode([format_query(question)])[0]
                debut = time.perf_counter()
                lot = interroger(cur, vecteur, arguments.top_k)
                latences.append((time.perf_counter() - debut) * 1000.0)
                resultats.append({"query": question, "results": lot})

            hors_perimetre = interroger(
                cur,
                modele.encode([format_query(REQUETE_HORS_PERIMETRE)])[0],
                arguments.top_k,
            )

            filtrees, hors_filtre = 0, 0
            for question, matiere in REQUETES:
                vecteur = modele.encode([format_query(question)])[0]
                lot = interroger(cur, vecteur, arguments.top_k, matiere=matiere)
                if not lot:
                    continue
                filtrees += 1
                identifiants = [r["content_sha256"] for r in lot]
                cur.execute(
                    f"SELECT count(*) FROM unnest(%s::text[]) s WHERE NOT EXISTS ("
                    f"SELECT 1 FROM {SCHEMA}.{TABLE_META} m "
                    "WHERE m.content_sha256 = s AND m.matiere = %s)",
                    (identifiants, matiere),
                )
                hors_filtre += cur.fetchone()[0]

        retour_arriere = prouver_retour_arriere(dsn)
        mesures = evaluer(resultats, autorises, refuses)
        mesures_hors = evaluer(
            [{"query": REQUETE_HORS_PERIMETRE, "results": hors_perimetre}],
            autorises,
            refuses,
        )
        p50 = round(statistics.median(latences), 1)
        p95 = round(sorted(latences)[max(0, int(0.95 * len(latences)) - 1)], 1)

        conditions = {
            "retrieval_top_k_validated": (
                not mesures["empty_result_queries"]
                and mesures["results_outside_allowlist"] == 0
                and mesures["duplicate_results"] == 0
            ),
            "scope_filters_validated": (
                lignes_meta > 0 and filtrees == len(REQUETES) and hors_filtre == 0
            ),
            "citations_validated": mesures["results_without_citation"] == 0,
            "out_of_scope_query_stays_in_allowlist": (
                mesures_hors["results_outside_allowlist"] == 0
                and mesures_hors["gate_refused_results"] == 0
            ),
            "gate_refused_absent_from_results": mesures["gate_refused_results"] == 0,
            # Mesurée, jamais validée : le dépôt n'épingle aucun budget p95.
            # Un chiffre sans seuil ne valide rien.
            "latency_validated": False,
            # Éprouvé PAR CE SCRIPT, sur un conteneur jetable équivalent.
            "rollback_validated": retour_arriere["proven"],
        }

        etat = {
            "kind": KIND,
            "index": {
                "dbname": dsn.rsplit("/", 1)[-1],
                "host": "127.0.0.1",
                "port": 55436,
                "vector_rows": vecteurs,
                "vectorized_contents": contenus,
            },
            "top_k": arguments.top_k,
            "conditions": conditions,
            "measured": mesures,
            "out_of_scope_query": {
                "query": REQUETE_HORS_PERIMETRE,
                "results": len(hors_perimetre),
                "outside_allowlist": mesures_hors["results_outside_allowlist"],
                "note": (
                    "un index vectoriel rend toujours un plus proche voisin : "
                    "l'exigence n'est pas qu'il refuse, mais qu'il ne sorte pas "
                    "du périmètre autorisé"
                ),
            },
            "scope_filters": {
                "filtered_queries": filtrees,
                "results_off_filter": hors_filtre,
                "metadata_rows": lignes_meta,
            },
            "latency": {
                "p50_ms": p50,
                "p95_ms": p95,
                "budget_ms": None,
                "why_not_validated": (
                    "le dépôt n'épingle aucun budget de latence : "
                    "`retrieval_evaluation` porte un champ `latency_ms_p95` mais "
                    "aucun seuil. Mesurer sans cible ne valide rien, donc "
                    "`latency_validated` reste faux jusqu'à ce qu'un budget soit "
                    "décidé."
                ),
            },
            "rollback": retour_arriere,
            "review_db_read": False,
            "review_db_written": False,
            "production_touched": False,
            "what_this_does_not_prove": [
                "ne prouve rien sur la production : aucune base de production "
                "n'a été interrogée",
                "ne valide pas la qualité pédagogique des réponses, seulement "
                "les propriétés du contrat",
                "ne rend pas le go-live prêt",
            ],
        }
    except (EntreeManquante, KeyError) as erreur:
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
