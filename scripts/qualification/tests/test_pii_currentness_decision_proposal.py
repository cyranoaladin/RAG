"""Épreuves de la PROPOSITION de décisions : elle propose, elle ne décide ni n'importe."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import build_pii_currentness_decision_proposal as proposition  # noqa: E402
import validate_pii_currentness_review_sheet as validateur  # noqa: E402


@pytest.fixture(scope="module")
def construit():
    return proposition.construire(RACINE)


def _autorites():
    index = json.loads((RACINE / proposition.INDEX_PII).read_text(encoding="utf-8"))
    v1 = json.loads((RACINE / proposition.DECISIONS_V1).read_text(encoding="utf-8"))
    return index, v1


def test_reconduction_seulement_sur_preuve_identique():
    index, v1 = _autorites()
    assert len(proposition.reconductibles(index, v1)) == len(v1["decisions"])
    cible = v1["decisions"][0]["content_sha256"]

    modifie = copy.deepcopy(index)
    paquet = next(b for b in modifie["bundles"] if b["content_sha256"] == cible)
    paquet["findings"][0]["context_sha256"] = "0" * 64
    assert cible not in proposition.reconductibles(modifie, v1), "un contexte différent interdit la reconduction"

    ajoute = copy.deepcopy(index)
    paquet = next(b for b in ajoute["bundles"] if b["content_sha256"] == cible)
    paquet["findings"].append({**paquet["findings"][0], "finding_id": "f" * 64, "match_sha256": "1" * 64})
    assert cible not in proposition.reconductibles(ajoute, v1), "un finding nouveau interdit la reconduction"


def test_aucune_reconduction_si_un_instrument_a_change():
    index, v1 = _autorites()
    assert proposition.reconductibles({**index, "scanner_sha256": "0" * 64}, v1) == {}


def test_une_decision_v1_rejetee_n_est_jamais_reconduite_en_admission():
    index, v1 = _autorites()
    v1 = copy.deepcopy(v1)
    v1["decisions"][0]["decision"] = "REJECTED"
    assert v1["decisions"][0]["content_sha256"] not in proposition.reconductibles(index, v1)


def test_rien_n_est_admis_hors_reconduction(construit):
    lignes, resume = construit
    reconduits = set(resume["content_ids_by_rule"]["CARRY_OVER_IDENTICAL_EVIDENCE"])
    for ligne in lignes:
        if ligne["row_kind"] == "PII_CONTENT" and ligne["content_sha256"] not in reconduits:
            assert ligne["HUMAN_DECISION"] == "EXCLUDE_FROM_SERVABLE_SET"
        if ligne["row_kind"] == "PII_FINDING" and ligne["content_sha256"] not in reconduits:
            assert ligne["FINDING_DISPOSITION"] == "PERSONAL_DATA_PRESENT"
        if ligne["row_kind"] == "CURRENTNESS_CONTENT":
            assert ligne["HUMAN_DECISION"] == "EXCLUDE_FROM_PROMOTED_RELEASE"


def test_reconduction_reprend_les_mots_du_reviewer(construit):
    lignes, resume = construit
    _index, v1 = _autorites()
    anciennes = {d["content_sha256"]: d for d in v1["decisions"]}
    for ligne in lignes:
        if ligne["row_kind"] == "PII_CONTENT" and ligne["content_sha256"] in resume["content_ids_by_rule"]["CARRY_OVER_IDENTICAL_EVIDENCE"]:
            ancienne = anciennes[ligne["content_sha256"]]
            assert ligne["COMMENT"] == ancienne["justification"]["statement"]
            assert ligne["JUSTIFICATION_CATEGORY"] == ancienne["justification"]["category"]


def test_couvre_tout_et_passe_le_validateur(construit, tmp_path):
    lignes, resume = construit
    readiness = json.loads((RACINE / "docs/reports/go_live/go_live_readiness_state.json").read_text(encoding="utf-8"))
    assert resume["counts"]["pii_contents"] == 149
    if readiness["pii_undecided"] == 0:
        assert readiness["release_promoted_refused_contents"] == 4
    else:
        assert resume["counts"]["pii_contents"] == readiness["pii_undecided"]
        assert resume["counts"]["currentness_contents"] == readiness["release_promoted_refused_by_currentness"]
    chemin = tmp_path / "p.tsv"
    chemin.write_text(proposition.rendre_tsv(lignes), encoding="utf-8")
    bilan = validateur.valider(RACINE, chemin)
    assert bilan["errors"] == [] and bilan["sealable"] is True
    assert bilan["pii"] == {"decided": 149, "pending": 0}
    assert bilan["reviewer_login"] == proposition.REVIEWER


def test_proposition_sans_effet_et_sans_matiere_brute(construit):
    _lignes, resume = construit
    assert resume["status"] == "PROPOSED_NOT_EFFECTIVE"
    assert resume["raw_pii_read"] is False and resume["raw_pii_in_proposal"] is False
    assert resume["expected_counters_after_governed_import"]["changed_by_this_proposal"] == "aucun"
    source = Path(proposition.__file__).read_text(encoding="utf-8")
    for interdit in ("nexus-pii-review", "NEXUS_PII_REVIEW_ROOT", "page-", "document.pdf", "servability_matrix"):
        assert interdit not in source, f"la proposition ne doit lire ni paquet brut ni matrice : {interdit}"


def test_les_feuilles_de_travail_restent_vierges_et_rien_n_est_importe():
    for feuille in ("pii_currentness_decision_sheet.tsv", "pii_currentness_minimal_c1_review.tsv"):
        lignes = list(csv.DictReader((RACINE / "docs/reports/go_live" / feuille).open(encoding="utf-8"), delimiter="\t"))
        assert all(not ligne[c] for ligne in lignes for c in ("HUMAN_DECISION", "FINDING_DISPOSITION", "REVIEWER_LOGIN"))
    decisions = sorted(p.name for p in (RACINE / "governance/pii-review-decisions").glob("*.json"))
    assert "pii-review-2026-09-03-final.json" in decisions
    assert "pii-review-2026-09-17-final.json" in decisions


def test_artefacts_versionnes_a_jour_et_scelles(construit):
    lignes, resume = construit
    assert (RACINE / proposition.SORTIE_TSV).read_text(encoding="utf-8") == proposition.rendre_tsv(lignes)
    octets = (RACINE / proposition.SORTIE_JSON).read_bytes()
    assert (RACINE / proposition.SORTIE_SHA).read_text(encoding="utf-8").split()[0] == hashlib.sha256(octets).hexdigest()
    versionne = json.loads(octets)
    assert versionne["sheet_sha256"] == hashlib.sha256((RACINE / proposition.SORTIE_TSV).read_bytes()).hexdigest()
    versionne.pop("sheet_sha256")
    assert versionne == resume
