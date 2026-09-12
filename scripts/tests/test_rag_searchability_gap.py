"""Tests de l'écart d'exploitabilité par recherche.

Ce qui est protégé : qu'on ne puisse pas faire passer du texte stocké pour un
corpus indexé, ni déclarer une condition tenue sans l'avoir mesurée.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import build_rag_searchability_gap as gap  # noqa: E402


def _poser(
    tmp_path: Path,
    *,
    searchable_contents: int = 0,
    vector_columns: int = 0,
    vector_extension: bool = False,
    ingested: int = 2473,
    target: int = 2529,
    vectorized_contents: int | None = None,
    dimensions_consistent: bool | None = None,
) -> Path:
    """Pose les entrées de l'écart.

    `searchable_contents` désigne désormais les VECTEURS de la base dédiée, et
    `vectorized_contents` les CONTENUS qu'ils couvrent. Les deux étaient
    confondus tant que la mesure venait de la base de revue, où il n'y avait
    ni l'un ni l'autre.
    """
    racine = tmp_path / "depot"
    (racine / "docs/reports/go_live").mkdir(parents=True)
    (racine / gap.AUDIT).write_text(
        json.dumps(
            {
                "ingested": {"contenus": ingested, "avec_texte_canonique": ingested},
                "searchable": {
                    "searchable_contents": searchable_contents,
                    "vector_columns": vector_columns,
                    "vector_extension": vector_extension,
                },
                "source": {"host": "h", "port": 1, "dbname": "d"},
            }
        ),
        encoding="utf-8",
    )
    (racine / gap.INVENTAIRE).write_text(
        json.dumps({"pedagogical_scope": {"contenus": target}}), encoding="utf-8"
    )
    # Les vecteurs vivent dans la base DÉDIÉE : l'écart les y mesure, et refuse
    # de conclure si cette mesure manque plutôt que de retomber sur la revue.
    couverts = (
        vectorized_contents
        if vectorized_contents is not None
        else searchable_contents
    )
    coherentes = (
        dimensions_consistent
        if dimensions_consistent is not None
        else bool(vector_extension and searchable_contents)
    )
    (racine / gap.MAGASIN_VECTEURS).write_text(
        json.dumps(
            {
                "staging_vectors_present": searchable_contents,
                "vector_dimensions_consistent": coherentes,
                "review_db_intact": True,
                "pgvector_installed_in_review_db": False,
                "dedicated": {
                    "source": {"host": "h", "port": 2, "dbname": "dediee"},
                    "vector_extension": vector_extension,
                    "vectorized_contents": couverts,
                },
            }
        ),
        encoding="utf-8",
    )
    # La matrice est nécessaire : le périmètre indexable s'en déduit. Par
    # défaut, autant de contenus candidats que le périmètre visé.
    (racine / "docs/reports/handoff").mkdir(parents=True, exist_ok=True)
    if not (racine / gap.MATRICE).exists():
        (racine / gap.MATRICE).write_text(
            json.dumps(
                {
                    "rows": [
                        {
                            "content_sha256": f"{index:064d}",
                            "verdict": gap.VERDICT_CANDIDAT,
                        }
                        for index in range(target)
                    ]
                }
            ),
            encoding="utf-8",
        )
    return racine


def test_sans_vecteur_le_corpus_n_est_pas_interrogeable(tmp_path: Path):
    etat = gap.construire(_poser(tmp_path))
    assert etat["measured"]["staging_vectors_present"] == 0
    assert etat["rag_searchable"] is False
    assert etat["rag_searchability_blocker"] is True


def test_du_texte_ingere_ne_compte_jamais_comme_des_vecteurs(tmp_path: Path):
    """Le piège central : 2473 documents ingérés, zéro vecteur."""
    etat = gap.construire(_poser(tmp_path, ingested=2473))
    assert etat["measured"]["ingested_contents"] == 2473
    assert etat["measured"]["staging_vectors_present"] == 0
    assert etat["rag_searchable"] is False


def test_une_colonne_vectorielle_sans_extension_ne_compte_pas(tmp_path: Path):
    etat = gap.construire(
        _poser(tmp_path, searchable_contents=100, vector_columns=1, vector_extension=False)
    )
    assert etat["measured"]["staging_vectors_present"] == 0
    assert etat["rag_searchability_blocker"] is True


def test_des_vecteurs_ne_suffisent_pas_sans_retrieval_valide(tmp_path: Path):
    """Des vecteurs sans retrieval validé ne servent personne."""
    etat = gap.construire(
        _poser(
            tmp_path, searchable_contents=2529, vector_columns=1, vector_extension=True
        )
    )
    assert etat["closing_conditions"]["staging_vectors_present"] is True
    assert etat["closing_conditions"]["target_scope_searchable"] is True
    # Et pourtant le blocage tient : le retrieval n'est pas validé.
    assert etat["closing_conditions"]["retrieval_top_k_validated"] is False
    assert etat["rag_searchable"] is False
    assert etat["rag_searchability_blocker"] is True


def test_une_couverture_partielle_ne_couvre_pas_la_portee_cible(tmp_path: Path):
    etat = gap.construire(
        _poser(
            tmp_path, searchable_contents=5, vector_columns=1, vector_extension=True,
            target=2529,
        )
    )
    assert etat["target_scope_searchable"] is False
    assert "target_scope_searchable" in etat["conditions_not_met"]


def test_toutes_les_conditions_commencent_fausses(tmp_path: Path):
    """Aucune n'est supposée tenue : c'est le sens d'un gate fail-closed."""
    etat = gap.construire(_poser(tmp_path))
    assert set(etat["conditions_not_met"]) == set(gap.CONDITIONS_DE_FERMETURE)
    assert all(v is False for v in etat["closing_conditions"].values())


def test_la_production_n_est_jamais_declaree_interrogeable(tmp_path: Path):
    etat = gap.construire(_poser(tmp_path, searchable_contents=2529,
                                 vector_columns=1, vector_extension=True))
    assert etat["production_searchable"] is False
    assert etat["not_measured"]["production_searchable"] is None


def test_le_blocage_suit_exactement_les_conditions(tmp_path: Path):
    """Le drapeau n'est pas indépendant : il se dérive des conditions."""
    etat = gap.construire(_poser(tmp_path))
    assert etat["rag_searchability_blocker"] is bool(etat["conditions_not_met"])
    assert etat["rag_searchable"] is not bool(etat["conditions_not_met"])


def test_un_audit_absent_est_refuse(tmp_path: Path):
    racine = tmp_path / "vide"
    (racine / "docs/reports/go_live").mkdir(parents=True)
    with pytest.raises(gap.EntreeManquante):
        gap.construire(racine)


def test_le_markdown_nomme_le_blocage(tmp_path: Path):
    etat = gap.construire(_poser(tmp_path))
    rendu = gap.rendre_markdown(etat)
    assert "RAG_SEARCHABILITY" in rendu
    assert "Ne pas éditer à la main" in rendu
    assert "vecteurs présents : 0" in rendu
    assert "rag_searchability_blocker=true" in rendu


# --- Le périmètre indexable ne peut pas inclure un contenu refusé -----------


def _poser_avec_matrice(tmp_path: Path, verdicts: dict, **kw) -> Path:
    racine = _poser(tmp_path, **kw)
    (racine / "docs/reports/handoff").mkdir(parents=True, exist_ok=True)
    # On écrase la matrice par défaut : ce test veut ses propres verdicts.
    (racine / gap.MATRICE).write_text(
        json.dumps(
            {
                "rows": [
                    {"content_sha256": sha, "verdict": verdict}
                    for sha, verdict in sorted(verdicts.items())
                ]
            }
        ),
        encoding="utf-8",
    )
    return racine


def test_le_perimetre_indexable_exclut_tout_contenu_refuse(tmp_path: Path):
    """La garantie est structurelle : l'intersection est vide par construction."""
    verdicts = {
        "a" * 64: gap.VERDICT_CANDIDAT,
        "b" * 64: gap.VERDICT_CANDIDAT,
        "c" * 64: "BLOCKED_PII_HUMAN_REVIEW",
        "d" * 64: "BLOCKED_NOT_CURRENT_BY_SOURCE",
        "e" * 64: "NOT_INDEXABLE_BY_ROLE",
    }
    racine = _poser_avec_matrice(tmp_path, verdicts, target=5)
    etat = gap.construire(racine)

    perimetre = etat["indexable_scope"]
    assert perimetre["count"] == 2
    assert perimetre["gate_refused_count"] == 3
    refuses = set(perimetre["never_indexable"])
    assert refuses == {"c" * 64, "d" * 64, "e" * 64}


def test_la_cible_n_est_pas_le_corpus_brut(tmp_path: Path):
    """Viser le corpus brut rendrait la condition inatteignable sans violer
    la règle d'exclusion qui l'accompagne."""
    verdicts = {
        "a" * 64: gap.VERDICT_CANDIDAT,
        "c" * 64: "BLOCKED_PII_HUMAN_REVIEW",
    }
    racine = _poser_avec_matrice(tmp_path, verdicts, target=99)
    etat = gap.construire(racine)
    assert etat["measured"]["target_scope_contents"] == 1
    assert etat["measured"]["pedagogical_corpus_contents"] == 99
    assert etat["indexable_scope"]["count"] != 99


def test_couvrir_le_perimetre_indexable_suffit_a_cette_condition(tmp_path: Path):
    """Le gate doit pouvoir se fermer sans indexer un seul contenu refusé."""
    verdicts = {
        "a" * 64: gap.VERDICT_CANDIDAT,
        "c" * 64: "BLOCKED_PII_HUMAN_REVIEW",
    }
    racine = _poser_avec_matrice(
        tmp_path, verdicts, searchable_contents=1, vector_columns=1,
        vector_extension=True, target=99,
    )
    etat = gap.construire(racine)
    assert etat["closing_conditions"]["target_scope_searchable"] is True
    # Le blocage tient encore, pour les conditions de retrieval.
    assert etat["rag_searchability_blocker"] is True


def test_le_module_ne_rend_aucun_verdict_de_servabilite():
    """Il lit la matrice pour EXCLURE, jamais pour décider.

    Cette épreuve tient la ligne `MATRIX_READER` de la baseline d'unicité
    d'autorité : le seul verdict nommé est celui qui autorise l'indexation, et
    il sert à écarter tous les autres — pas à en prononcer un.
    """
    source = (
        RACINE / "scripts/go_live/build_rag_searchability_gap.py"
    ).read_text(encoding="utf-8")
    for interdit in (
        "BLOCKED_PII_HUMAN_REVIEW",
        "BLOCKED_NOT_CURRENT_BY_SOURCE",
        "BLOCKED_NO_URL_PROVENANCE",
        "NOT_INDEXABLE_BY_ROLE",
        "REFUSED_PROGRAM_INCOMPATIBLE",
    ):
        assert interdit not in source, (
            f"{interdit} est écrit ici : le module déciderait au lieu d'exclure"
        )


def test_le_perimetre_vectorisable_versionne_exclut_tout_refuse():
    """Épreuve sur les artefacts VERSIONNÉS, pas sur une fixture.

    Ce qui est protégé : qu'un contenu refusé ne puisse pas entrer dans
    l'ensemble d'entrée d'une vectorisation. Un index construit sur lui serait
    une porte dérobée autour du gate.
    """
    matrice = json.loads(
        (RACINE / "docs/reports/handoff/servability_matrix_v1.json").read_text(
            encoding="utf-8"
        )
    )
    preflight = json.loads(
        (
            RACINE / "docs/reports/go_live/vectorization_phase_a_preflight.json"
        ).read_text(encoding="utf-8")
    )
    indexable = {
        ligne["content_sha256"]
        for ligne in matrice["rows"]
        if ligne["verdict"] == gap.VERDICT_CANDIDAT
    }
    refuses = {
        ligne["content_sha256"]
        for ligne in matrice["rows"]
        if ligne["verdict"] != gap.VERDICT_CANDIDAT
    }
    assert preflight["input_set"]["count"] == len(indexable)
    assert not (indexable & refuses)
    for nom, valeur in preflight["exclusion_proofs"].items():
        if nom.startswith("intersection"):
            assert valeur == 0, f"{nom} n'est pas vide"
    assert preflight["vectorization_executed"] is False
    assert preflight["target_database"]["must_not_target_review_base"] is True
