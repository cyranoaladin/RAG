"""Épreuves de la validation du contrat de retrieval.

Un index n'est pas un retrieval. Ces épreuves portent sur ce qui distingue les
deux, et surtout sur les refus : ce qui n'a pas été mesuré ne doit pas être
déclaré vrai.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import validate_retrieval_contract as vr  # noqa: E402

RAPPORT = RACINE / "docs/reports/go_live/retrieval_contract_validation.json"
ECART = RACINE / "docs/reports/go_live/rag_searchability_gap.json"


def _resultat(sha: str, page: int | None = 1, chunk: str = "c1") -> dict:
    return {
        "chunk_id": chunk,
        "content_sha256": sha,
        "page_start": page,
        "page_end": page,
        "distance": 0.1,
    }


# --- L'évaluation compte, elle ne suppose pas -----------------------------


def test_un_resultat_hors_liste_blanche_est_compte():
    mesures = vr.evaluer(
        [{"query": "q", "results": [_resultat("intrus")]}], {"autorise"}, set()
    )
    assert mesures["results_outside_allowlist"] == 1


def test_un_resultat_refuse_par_le_gate_est_compte():
    mesures = vr.evaluer(
        [{"query": "q", "results": [_resultat("refuse")]}], {"refuse"}, {"refuse"}
    )
    assert mesures["gate_refused_results"] == 1


def test_un_resultat_sans_page_est_compte_comme_sans_citation():
    """Une citation sans page n'est pas une citation."""
    mesures = vr.evaluer(
        [{"query": "q", "results": [_resultat("ok", page=None)]}], {"ok"}, set()
    )
    assert mesures["results_without_citation"] == 1


def test_un_doublon_dans_le_top_k_est_compte():
    mesures = vr.evaluer(
        [
            {
                "query": "q",
                "results": [_resultat("ok", chunk="c1"), _resultat("ok", chunk="c1")],
            }
        ],
        {"ok"},
        set(),
    )
    assert mesures["duplicate_results"] == 1


def test_une_requete_sans_resultat_est_nommee():
    mesures = vr.evaluer([{"query": "muette", "results": []}], set(), set())
    assert mesures["empty_result_queries"] == ["muette"]


def test_un_top_k_propre_ne_declenche_rien():
    """Le compteur doit discriminer, sinon il ne prouve rien."""
    mesures = vr.evaluer(
        [{"query": "q", "results": [_resultat("ok", chunk="a"), _resultat("ok", chunk="b")]}],
        {"ok"},
        set(),
    )
    assert mesures["results_outside_allowlist"] == 0
    assert mesures["gate_refused_results"] == 0
    assert mesures["results_without_citation"] == 0
    assert mesures["duplicate_results"] == 0
    assert mesures["empty_result_queries"] == []


# --- Ce que le module refuse de faire -------------------------------------


def test_le_module_ne_touche_pas_la_base_de_revue():
    source = Path(vr.__file__).read_text(encoding="utf-8")
    assert "REVIEW_DB" not in source
    assert "drivestaging" not in source


def test_la_latence_n_est_jamais_validee_sans_budget():
    """Un chiffre sans seuil ne valide rien : fail-closed sans budget."""
    valide, etat = vr.evaluer_latence([10.0, 20.0], None)
    assert valide is False
    assert etat["budget_ms"] is None
    assert "aucun budget de latence" in etat["why_not_validated"]
    source = Path(vr.__file__).read_text(encoding="utf-8")
    assert "BUDGET_LATENCE" in source


def test_evaluer_latence_refuse_si_seuil_depasse():
    """Un dépassement de p50 ou p95 refuse la validation."""
    politique = {"adopted": True, "budget": {"p50_ms_max": 200.0, "p95_ms_max": 250.0, "errors_max": 0, "timeouts_max": 0}}
    valide, etat = vr.evaluer_latence([300.0, 400.0], politique)
    assert valide is False
    assert "dépassement" in etat["why_not_validated"]


def test_evaluer_latence_refuse_si_timeout_ou_erreur_depasse():
    """Un timeout ou une erreur au-delà du max refuse la validation."""
    politique = {"adopted": True, "budget": {"p50_ms_max": 200.0, "p95_ms_max": 250.0, "errors_max": 0, "timeouts_max": 0}}
    valide, etat = vr.evaluer_latence([100.0, 150.0], politique, timeouts_count=1)
    assert valide is False
    assert "timeouts=1/0" in etat["why_not_validated"]

    valide, etat = vr.evaluer_latence([100.0, 150.0], politique, empty_queries_count=1)
    assert valide is False
    assert "erreurs=1/0" in etat["why_not_validated"]


def test_le_retour_arriere_n_est_pas_un_drapeau_de_l_appelant():
    """Le défaut relevé en revue au lot BI2 ne doit pas se rejouer ici."""
    source = Path(vr.__file__).read_text(encoding="utf-8")
    assert "NEXUS_ROLLBACK_PROVEN" not in source
    assert 'retour_arriere["proven"]' in source
    assert "def prouver_retour_arriere" in source


def test_le_retour_arriere_n_est_jamais_eprouve_sur_l_index_en_place():
    """Prouver qu'on sait supprimer ne doit pas supprimer."""
    source = Path(vr.__file__).read_text(encoding="utf-8")
    assert "jumeau" in source
    assert "nexus-rollback-proof-" in source
    assert "nexus-vector-staging-a" not in source


def test_les_libelles_de_matiere_sont_releves_et_non_devines():
    source = Path(vr.__file__).read_text(encoding="utf-8")
    assert "RELEVÉS et" in source
    for invente in (
        "sciences-de-la-vie-et-de-la-terre",
        "numerique-et-sciences-informatiques",
    ):
        assert f'"{invente}"' not in source


# --- Le rapport VERSIONNÉ -------------------------------------------------


@pytest.fixture(scope="module")
def rapport() -> dict:
    if not RAPPORT.is_file():
        pytest.skip("validation pas encore exécutée")
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_aucun_resultat_ne_sort_du_perimetre_autorise(rapport):
    assert rapport["measured"]["results_outside_allowlist"] == 0
    assert rapport["measured"]["gate_refused_results"] == 0
    assert rapport["measured"]["duplicate_results"] == 0


def test_toutes_les_citations_portent_une_page(rapport):
    assert rapport["measured"]["results_without_citation"] == 0
    assert rapport["conditions"]["citations_validated"] is True


def test_une_requete_hors_domaine_reste_dans_le_perimetre(rapport):
    """Un index vectoriel rend toujours un voisin : l'exigence est le périmètre."""
    hors = rapport["out_of_scope_query"]
    assert hors["results"] > 0
    assert hors["outside_allowlist"] == 0
    assert rapport["conditions"]["out_of_scope_query_stays_in_allowlist"] is True


def test_les_filtres_de_portee_filtrent_reellement(rapport):
    assert rapport["scope_filters"]["results_off_filter"] == 0
    assert rapport["scope_filters"]["metadata_rows"] > 0
    assert rapport["scope_filters"]["filtered_queries"] == rapport["measured"]["queries"]


def test_la_latence_est_validee_sous_budget_adopte(rapport):
    assert rapport["latency"]["p50_ms"] > 0
    assert rapport["latency"]["p95_ms"] > 0
    assert rapport["latency"]["budget_ms"] == 250.0
    assert rapport["latency"]["p50_ms"] <= 200.0
    assert rapport["latency"]["p95_ms"] <= 250.0
    assert rapport["conditions"]["latency_validated"] is True


def test_le_retour_arriere_a_ete_reellement_execute(rapport):
    retour = rapport["rollback"]
    assert retour["twin_existed_before"] is True
    assert retour["twin_volume_existed_before"] is True
    assert retour["twin_removed"] is True
    assert retour["twin_volume_removed"] is True
    assert retour["dedicated_index_untouched_rows"] > 0
    assert rapport["conditions"]["rollback_validated"] is True


def test_la_base_de_revue_reste_hors_du_chemin(rapport):
    assert rapport["review_db_read"] is False
    assert rapport["review_db_written"] is False
    assert rapport["production_touched"] is False


def test_l_ecart_lit_ces_conditions_au_lieu_de_les_supposer():
    """Sans cela, l'écart resterait bloqué sur des conditions déjà prouvées."""
    ecart = json.loads(ECART.read_text(encoding="utf-8"))
    rapport = json.loads(RAPPORT.read_text(encoding="utf-8"))
    for nom in (
        "retrieval_top_k_validated",
        "citations_validated",
        "scope_filters_validated",
        "latency_validated",
        "rollback_validated",
    ):
        assert ecart["closing_conditions"][nom] == rapport["conditions"][nom], nom


def test_le_blocage_de_recherche_reste_ouvert_sur_ce_qui_manque():
    ecart = json.loads(ECART.read_text(encoding="utf-8"))
    assert ecart["rag_searchability_blocker"] is True
    assert set(ecart["conditions_not_met"]) == {
        "target_scope_searchable",
    }
