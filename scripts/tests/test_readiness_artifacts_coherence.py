"""Cohérence des artefacts de décision versionnés.

Ces épreuves existent à cause d'une erreur réelle : un rapport source a été
régénéré et rendu bloquant, mais le snapshot de readiness versionné, lui, est
resté celui d'un lot antérieur. Le code était juste ; les artefacts sur
lesquels on décide ne l'étaient pas.

C'est la pire forme d'incohérence, parce qu'elle ne se voit pas : chaque
fichier est plausible isolément. Seule leur confrontation la révèle.

Ces tests portent sur les fichiers VERSIONNÉS du dépôt, pas sur des fixtures.
Ils échouent si l'on commite un snapshot périmé.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]

ETAT = RACINE / "docs/reports/go_live/go_live_readiness_state.json"
ECART_RECHERCHE = RACINE / "docs/reports/go_live/rag_searchability_gap.json"
MARKDOWN = RACINE / "docs/reports/go_live/GO_LIVE_READINESS.md"

#: Champs que le readiness doit porter pour que l'exploitabilité par recherche
#: soit décidable en le lisant seul.
CHAMPS_RECHERCHE = (
    "rag_searchable",
    "staging_vectors_present",
    "target_scope_searchable",
    "production_searchable",
    "retrieval_contract_validated",
    "rag_searchability_blocker",
    "rag_searchability_conditions_not_met",
)


@pytest.fixture(scope="module")
def etat() -> dict:
    return json.loads(ETAT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ecart() -> dict:
    return json.loads(ECART_RECHERCHE.read_text(encoding="utf-8"))


def test_le_readiness_porte_tous_les_champs_de_recherche(etat):
    manquants = [champ for champ in CHAMPS_RECHERCHE if champ not in etat]
    assert not manquants, (
        f"le readiness versionné ne porte pas {manquants} : "
        "l'exploitabilité par recherche ne serait pas décidable en le lisant"
    )


def test_un_ecart_bloquant_apparait_dans_les_raisons_de_refus(etat, ecart):
    """Le test qui aurait attrapé le snapshot périmé.

    Si le rapport d'écart bloque et que le readiness ne le dit pas, l'un des
    deux est en retard sur l'autre — et c'est toujours celui qui décide.
    """
    if not ecart["rag_searchability_blocker"]:
        pytest.skip("l'écart de recherche ne bloque pas : rien à confronter")
    assert etat["rag_searchability_blocker"] is True, (
        "le rapport d'écart bloque mais le readiness versionné dit l'inverse : "
        "le snapshot est périmé"
    )
    assert "rag_searchability_blocker" in etat["blocking_reasons"], (
        "le rapport d'écart bloque mais la raison n'est pas dans "
        "blocking_reasons : le snapshot est périmé"
    )
    assert etat["go_live_ready"] is False


def test_les_valeurs_de_recherche_du_readiness_suivent_le_rapport(etat, ecart):
    """Ni l'un ni l'autre ne doit dériver : ce sont les mêmes faits."""
    assert etat["rag_searchable"] == ecart["rag_searchable"]
    assert etat["target_scope_searchable"] == ecart["target_scope_searchable"]
    assert etat["production_searchable"] == ecart["production_searchable"]
    assert (
        etat["retrieval_contract_validated"] == ecart["retrieval_contract_validated"]
    )
    assert (
        etat["staging_vectors_present"]
        == ecart["measured"]["staging_vectors_present"]
    )


def test_le_snapshot_nomme_le_commit_qu_il_evalue(etat):
    """Un snapshot qui ne dit pas ce qu'il a évalué n'est pas opposable."""
    for champ in ("evaluated_ref", "evaluated_head", "main_head"):
        valeur = etat.get(champ)
        assert valeur, f"{champ} absent du snapshot"
        assert valeur != champ, f"{champ} contient son propre nom"
    assert len(etat["evaluated_head"]) == 40
    assert len(etat["main_head"]) == 40


def test_le_markdown_derive_reste_aligne_sur_l_etat(etat):
    rendu = MARKDOWN.read_text(encoding="utf-8")
    attendu = "true" if etat["go_live_ready"] else "false"
    assert f"GO_LIVE_READY={attendu}" in rendu
    for raison in etat["blocking_reasons"]:
        assert raison in rendu, f"raison de refus absente du markdown : {raison}"


def test_aucun_go_live_vert_ne_peut_etre_commite(etat):
    """Un garde-fou de dernier recours, sur l'artefact lui-même."""
    if etat["blocking_reasons"]:
        assert etat["go_live_ready"] is False
