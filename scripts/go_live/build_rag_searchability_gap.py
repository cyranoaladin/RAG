#!/usr/bin/env python3
"""Dérive l'écart d'exploitabilité par recherche, et refuse de le supposer.

Un corpus gouverné n'est pas un corpus interrogeable. Le texte peut être
collecté, extrait, découpé, qualifié et promu sans qu'aucune recherche ne
puisse l'atteindre : il y faut des vecteurs, un contrat de retrieval, et une
base qui les serve.

La confusion coûte cher dans ce sens précis : « tout est ingéré » se lit
spontanément comme « le RAG fonctionne ». Les deux sont séparés par une étape
entière, et aucun compteur de gouvernance ne la mesure.

Ce script ne mesure rien lui-même. Il DÉRIVE d'un audit d'ingestion — qui, lui,
a interrogé une base nommée — et refuse si cet audit manque. Un écart supposé
n'est pas un écart mesuré, et prononcer `rag_searchable=false` sans l'avoir
observé serait aussi faux que de prononcer `true`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

KIND = "NEXUS-RAG-SEARCHABILITY-GAP-V1"

AUDIT = "docs/reports/go_live/ingestion_audit.json"
INVENTAIRE = "docs/reports/go_live/drive_corpus_inventory.json"
MATRICE = "docs/reports/handoff/servability_matrix_v1.json"

#: Le seul verdict qui autorise l'indexation. Tout autre verdict est un refus,
#: et un contenu refusé ne doit jamais devenir atteignable par une requête.
VERDICT_CANDIDAT = "CANDIDATE_NO_BLOCKING_DIMENSION"

#: Les conditions de fermeture. Toutes doivent être vraies ; aucune ne suffit.
#: Des vecteurs sans retrieval validé ne servent personne, et un retrieval
#: validé sur un échantillon ne dit rien du périmètre cible.
CONDITIONS_DE_FERMETURE = (
    "staging_vectors_present",
    "vector_dimensions_consistent",
    "retrieval_top_k_validated",
    "citations_validated",
    "scope_filters_validated",
    "latency_validated",
    "rollback_validated",
    "target_scope_searchable",
)


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au calcul est absente ou inexploitable."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _lire(racine: Path, relatif: str):
    chemin = racine / relatif
    if not chemin.is_file():
        raise EntreeManquante(f"entrée absente : {chemin}")
    texte = chemin.read_text(encoding="utf-8")
    if not texte.strip():
        raise EntreeManquante(f"entrée vide : {chemin}")
    return json.loads(texte)


def construire(racine: Path) -> dict:
    audit = _lire(racine, AUDIT)
    inventaire = _lire(racine, INVENTAIRE)

    recherchables = audit["searchable"]["searchable_contents"]
    colonnes = audit["searchable"]["vector_columns"]
    extension = audit["searchable"]["vector_extension"]
    ingérés = audit["ingested"]["contenus"]
    corpus_pedagogique = inventaire["pedagogical_scope"]["contenus"]

    # LE périmètre d'indexation n'est pas le corpus. Viser le corpus brut
    # exigerait d'indexer les contenus que le gate refuse — un index construit
    # sur eux deviendrait une porte dérobée autour du gate, et la condition
    # serait inatteignable sans violer la règle qui l'accompagne.
    lignes = json.loads((racine / MATRICE).read_text(encoding="utf-8"))["rows"]
    indexables = {
        ligne["content_sha256"]
        for ligne in lignes
        if ligne["verdict"] == VERDICT_CANDIDAT
    }
    refuses = {
        ligne["content_sha256"]
        for ligne in lignes
        if ligne["verdict"] != VERDICT_CANDIDAT
    }
    cible = len(indexables)

    vecteurs = recherchables if (colonnes and extension) else 0

    # Chaque condition est FAUSSE tant qu'une mesure ne l'a pas établie. Aucune
    # n'est supposée vraie par défaut : c'est le sens d'un gate fail-closed.
    conditions = {
        "staging_vectors_present": vecteurs > 0,
        "vector_dimensions_consistent": bool(colonnes) and extension,
        "retrieval_top_k_validated": False,
        "citations_validated": False,
        "scope_filters_validated": False,
        "latency_validated": False,
        "rollback_validated": False,
        "target_scope_searchable": vecteurs >= cible and cible > 0,
    }
    non_tenues = sorted(nom for nom, tenue in conditions.items() if not tenue)
    recherchable = not non_tenues

    return {
        "kind": KIND,
        "indexable_scope": {
            "definition": "les contenus que le gate de servabilité ne refuse pas",
            "count": cible,
            "pedagogical_corpus_count": corpus_pedagogique,
            "gate_refused_count": len(refuses),
            "why_not_the_raw_corpus": (
                "viser le corpus brut exigerait d'indexer les contenus refusés : "
                "la condition serait inatteignable sans violer la règle "
                "d'exclusion qui l'accompagne"
            ),
            "never_indexable": sorted(refuses),
        },
        "measured": {
            "canonical_text_in_staging": audit["ingested"]["avec_texte_canonique"],
            "ingested_contents": ingérés,
            "pedagogical_corpus_contents": corpus_pedagogique,
            "staging_vectors_present": vecteurs,
            "vector_columns": colonnes,
            "vector_extension": extension,
            "target_scope_contents": cible,
            "measurement_source": audit.get("source", {}),
        },
        "not_measured": {
            "production_searchable": None,
            "why": (
                "aucune base de production n'a été identifiée ni interrogée ; "
                "ne pas savoir n'est pas une autorisation"
            ),
        },
        "rag_searchable": recherchable,
        "target_scope_searchable": conditions["target_scope_searchable"],
        "production_searchable": False,
        "retrieval_contract_validated": conditions["retrieval_top_k_validated"],
        "rag_searchability_blocker": not recherchable,
        "closing_conditions": conditions,
        "conditions_not_met": non_tenues,
        "why_vectors_zero_means_unusable": (
            "le texte est stocké, pas indexé : aucune requête ne peut l'atteindre. "
            "Un corpus qualifié servable reste inatteignable tant qu'aucun vecteur "
            "ne le référence"
        ),
        "blocker_id": "RAG_SEARCHABILITY",
        "what_would_be_wrong_to_say": [
            "RAG fully ingested : le texte est stocké, pas indexé",
            "RAG searchable : aucun vecteur n'existe",
            "corpus prêt à servir : la servabilité est une qualification, pas une "
            "capacité de recherche",
        ],
    }


def rendre_markdown(etat: dict) -> str:
    mesure = etat["measured"]
    lignes = [
        "# L'écart entre un corpus gouverné et un RAG interrogeable",
        "",
        "Document dérivé. Ne pas éditer à la main :",
        "`scripts/go_live/build_rag_searchability_gap.py` le régénère depuis",
        "l'audit d'ingestion, qui a interrogé une base nommée.",
        "",
        "## Ce qui est mesuré",
        "",
        f"- texte canonique en préparation : **{mesure['canonical_text_in_staging']}**",
        f"- contenus ingérés : **{mesure['ingested_contents']}**",
        f"- **vecteurs présents : {mesure['staging_vectors_present']}**",
        f"- colonnes vectorielles : {mesure['vector_columns']}",
        f"- extension vectorielle : {mesure['vector_extension']}",
        f"- périmètre cible : **{mesure['target_scope_contents']}**",
        "",
        "## Ce qui n'est pas mesuré",
        "",
        f"- `production_searchable` — {etat['not_measured']['why']}.",
        "",
        "## Pourquoi zéro vecteur rend le RAG inexploitable",
        "",
        etat["why_vectors_zero_means_unusable"] + ".",
        "",
        "La confusion joue dans un sens précis : « tout est ingéré » se lit",
        "spontanément comme « le RAG fonctionne ». Les deux sont séparés par une",
        "étape entière.",
        "",
        "## Le blocage qui porte ce refus",
        "",
        f"`{etat['blocker_id']}` — `rag_searchability_blocker="
        f"{str(etat['rag_searchability_blocker']).lower()}`.",
        "",
        "Ce document ne se contente plus de constater : tant que les conditions",
        "ci-dessous ne sont pas toutes tenues, le readiness refuse le go-live et",
        "nomme cette raison.",
        "",
        "## Conditions de fermeture",
        "",
        "| condition | tenue |",
        "| --- | :---: |",
    ]
    for nom, tenue in etat["closing_conditions"].items():
        lignes.append(f"| `{nom}` | {'oui' if tenue else '**non**'} |")
    lignes += [
        "",
        "Aucune ne suffit seule. Des vecteurs sans retrieval validé ne servent",
        "personne ; un retrieval validé sur un échantillon ne dit rien du",
        "périmètre cible.",
        "",
        "Le déploiement en production n'est pas autorisé par la fermeture de ce",
        "blocage : il relève d'une décision distincte.",
        "",
        "## Trois phrases qu'il serait faux de dire",
        "",
    ]
    lignes += [f"- {x}" for x in etat["what_would_be_wrong_to_say"]]
    lignes.append("")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--output-json", default="docs/reports/go_live/rag_searchability_gap.json"
    )
    analyseur.add_argument(
        "--output-md", default="docs/reports/go_live/RAG_SEARCHABILITY_GAP.md"
    )
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    try:
        etat = construire(racine)
    except EntreeManquante as erreur:
        print(f"ENTREE_MANQUANTE: {erreur}", file=sys.stderr)
        return 2

    for relatif, contenu in (
        (arguments.output_json, json.dumps(etat, indent=2, ensure_ascii=False, sort_keys=True) + "\n"),
        (arguments.output_md, rendre_markdown(etat)),
    ):
        chemin = racine / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
        print(f"écrit : {chemin}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
