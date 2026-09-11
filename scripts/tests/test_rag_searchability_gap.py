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
) -> Path:
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
