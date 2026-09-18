"""Épreuves du dossier de décision humaine PII / actualité : il prépare, il ne décide pas."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import build_pii_currentness_decision_packet as dossier  # noqa: E402


@pytest.fixture(scope="module")
def construit() -> dict:
    return dossier.construire(RACINE)


def test_populations_recoupees_avec_le_readiness(construit) -> None:
    readiness = json.loads((RACINE / dossier.READINESS).read_text(encoding="utf-8"))
    c = construit["counts"]
    assert c["pii_undecided"] == len(construit["pii_contents"]) == 149
    if readiness["pii_undecided"] == 0:
        assert readiness["release_promoted_refused_contents"] in (0, 4)
    else:
        assert c["pii_undecided"] == readiness["pii_undecided"]
        assert c["release_promoted_refused_contents"] == readiness["release_promoted_refused_contents"]
    assert c["promoted_blocked_by_pii"] + c["promoted_blocked_by_currentness"] == c["release_promoted_refused_contents"]
    assert c["promoted_blocked_by_currentness"] == len(construit["currentness_contents"])
    assert c["pii_findings"] == sum(len(x["findings"]) for x in construit["pii_contents"])


def test_aucune_decision_pre_remplie(construit) -> None:
    assert construit["counts"]["decisions_prefilled"] == 0
    assert all(x["human_decision"] is None for x in construit["pii_contents"])
    assert all(x["human_decision"] is None for x in construit["currentness_contents"])
    assert all(f["human_disposition"] is None for x in construit["pii_contents"] for f in x["findings"])


def test_decision_v1_citee_jamais_etendue(construit) -> None:
    cites = [x for x in construit["pii_contents"] if x["prior_v1_decision_not_extended"]]
    assert cites, "les décisions V1 existantes doivent être visibles du reviewer"
    assert all(x["human_decision"] is None for x in cites)


def test_aucune_matiere_brute(construit) -> None:
    texte = json.dumps(construit)
    assert construit["raw_pii_in_packet"] is False
    for cle in ('"match_text"', '"context"', '"text"'):
        assert cle not in texte


def test_ordre_et_risque_viennent_du_pilotage_jamais_recalcules(construit) -> None:
    pilotage = {
        p["content_sha256"]: p
        for p in json.loads((RACINE / dossier.PILOTAGE).read_text(encoding="utf-8"))["packets"]
    }
    ordres = [x["review_order"] for x in construit["pii_contents"]]
    assert ordres == sorted(ordres)
    assert [x["priority"] for x in construit["pii_contents"]] == sorted(x["priority"] for x in construit["pii_contents"])
    for x in construit["pii_contents"]:
        assert x["risk_tier"] == pilotage[x["content_sha256"]]["risk_level"]


def test_ne_lit_pas_la_matrice_de_servabilite() -> None:
    assert "servability_matrix" not in Path(dossier.__file__).read_text(encoding="utf-8")


def test_tsv_colonnes_de_decision_vides(construit) -> None:
    lignes = list(csv.DictReader(dossier.rendre_tsv(construit).splitlines(), delimiter="\t"))
    c = construit["counts"]
    assert len(lignes) == c["pii_undecided"] + c["pii_findings"] + c["promoted_blocked_by_currentness"]
    for ligne in lignes:
        for colonne in ("HUMAN_DECISION", "FINDING_DISPOSITION", "JUSTIFICATION_CATEGORY", "REVIEWER_LOGIN"):
            assert ligne[colonne] == ""


def test_refuse_des_autorites_incoherentes(tmp_path) -> None:
    for relatif in (dossier.PILOTAGE, dossier.INDEX_PII, dossier.IMPACT, dossier.READINESS, dossier.DECISIONS_V1):
        cible = tmp_path / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes((RACINE / relatif).read_bytes())
    etat = json.loads((tmp_path / dossier.READINESS).read_text(encoding="utf-8"))
    etat["pii_undecided"] -= 1
    (tmp_path / dossier.READINESS).write_text(json.dumps(etat), encoding="utf-8")
    with pytest.raises(dossier.EntreeIncoherente):
        dossier.construire(tmp_path)


def test_artefacts_versionnes_a_jour_et_scelles(construit) -> None:
    octets = (RACINE / dossier.SORTIE_JSON).read_bytes()
    assert (RACINE / dossier.SORTIE_SHA).read_text(encoding="utf-8").split()[0] == hashlib.sha256(octets).hexdigest()
    versionne = json.loads(octets)
    # L'état de readiness est régénéré à chaque lot : son empreinte d'entrée peut différer,
    # le CONTENU du dossier, lui, doit être celui que les autorités donnent aujourd'hui.
    for d in (versionne, construit):
        d["inputs"].pop(dossier.READINESS)
    assert versionne == construit


def test_extrait_c1_est_un_sous_ensemble_strict_sans_decision(construit) -> None:
    complet = list(csv.DictReader(dossier.rendre_tsv(construit).splitlines(), delimiter="\t"))
    lignes = list(csv.DictReader(dossier.rendre_tsv_c1(construit).splitlines(), delimiter="\t"))
    # Projetée sur les colonnes de la feuille complète, chaque ligne de l'extrait en est une, à l'identique.
    projetees = [{c: ligne[c] for c in dossier.COLONNES} for ligne in lignes]
    assert all(p in complet for p in projetees)
    promus = [x for x in construit["pii_contents"] if x["promoted_in_release"]]
    assert len(lignes) == len(construit["currentness_contents"]) + len(promus) + sum(x["finding_count"] for x in promus)
    assert {ligne["priority"] for ligne in lignes} == {dossier.PRIORITE_C1}
    assert [int(ligne["review_order"]) for ligne in lignes] == list(range(1, len(lignes) + 1))
    for ligne in lignes:
        assert ligne["WHAT_TO_FILL_ON_THIS_ROW"] == dossier.A_REMPLIR[ligne["row_kind"]]
        assert not ligne["open_this_file"].startswith("/"), "aucun chemin absolu machine-local"
        for colonne in ("HUMAN_DECISION", "FINDING_DISPOSITION", "JUSTIFICATION_CATEGORY", "REVIEWER_LOGIN"):
            assert ligne[colonne] == ""


def test_vue_de_lecture_c1_sans_colonne_de_decision_et_a_jour(construit) -> None:
    rendu = dossier.rendre_markdown_c1(construit)
    assert "HUMAN_DECISION" not in rendu and "PII_CLEARED" not in rendu
    assert (RACINE / dossier.SORTIE_MD_C1).read_text(encoding="utf-8") == rendu
    assert (RACINE / dossier.SORTIE_TSV_C1).read_text(encoding="utf-8") == dossier.rendre_tsv_c1(construit)
