"""Épreuves du validateur de feuille de revue : il contrôle, il n'importe ni ne décide."""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import build_pii_currentness_decision_packet as dossier  # noqa: E402
import validate_pii_currentness_review_sheet as validateur  # noqa: E402


@pytest.fixture(scope="module")
def vierge() -> list[dict]:
    return list(csv.DictReader(io.StringIO(dossier.rendre_tsv_c1(dossier.construire(RACINE))), delimiter="\t"))


def _ecrire(tmp_path: Path, lignes: list[dict]) -> Path:
    chemin = tmp_path / "feuille.tsv"
    with chemin.open("w", encoding="utf-8", newline="") as flux:
        ecrit = csv.DictWriter(flux, fieldnames=list(lignes[0]), delimiter="\t", lineterminator="\n")
        ecrit.writeheader()
        ecrit.writerows(lignes)
    return chemin


def _copie(lignes):
    return [dict(ligne) for ligne in lignes]


def _premier_contenu_pii(lignes):
    contenu = next(x for x in lignes if x["row_kind"] == "PII_CONTENT")
    findings = [x for x in lignes if x["row_kind"] == "PII_FINDING" and x["content_sha256"] == contenu["content_sha256"]]
    return contenu, findings


def test_feuille_vierge_valide_et_tout_en_attente(tmp_path, vierge):
    bilan = validateur.valider(RACINE, _ecrire(tmp_path, _copie(vierge)))
    assert bilan["errors"] == []
    assert bilan["counts"]["decided"] == 0
    assert bilan["counts"]["pending"] == 26
    assert bilan["sealable"] is False, "une feuille avec des lignes en attente n'est pas scellable"
    assert bilan["imports_nothing"] is True


def test_decision_complete_et_coherente_acceptee(tmp_path, vierge):
    lignes = _copie(vierge)
    contenu, findings = _premier_contenu_pii(lignes)
    for f in findings:
        f["FINDING_DISPOSITION"] = "FALSE_POSITIVE_TECHNICAL"
    contenu.update(HUMAN_DECISION="PII_CLEARED", JUSTIFICATION_CATEGORY="TECHNICAL_FALSE_POSITIVE", REVIEWER_LOGIN="abenrhouma")
    bilan = validateur.valider(RACINE, _ecrire(tmp_path, lignes))
    assert bilan["errors"] == [] and bilan["counts"]["decided"] == 1
    assert bilan["sealable"] is False, "25 contenus restent en attente"


def test_cleared_refuse_si_un_finding_est_personnel(tmp_path, vierge):
    lignes = _copie(vierge)
    contenu, findings = _premier_contenu_pii(lignes)
    for f in findings:
        f["FINDING_DISPOSITION"] = "FALSE_POSITIVE_TECHNICAL"
    findings[0]["FINDING_DISPOSITION"] = "PERSONAL_DATA_PRESENT"
    contenu.update(HUMAN_DECISION="PII_CLEARED", JUSTIFICATION_CATEGORY="TECHNICAL_FALSE_POSITIVE", REVIEWER_LOGIN="abenrhouma")
    erreurs = validateur.valider(RACINE, _ecrire(tmp_path, lignes))["errors"]
    assert any("PERSONAL_DATA_PRESENT" in e for e in erreurs)


def test_decision_sans_tous_les_findings_refusee(tmp_path, vierge):
    lignes = _copie(vierge)
    contenu, _findings = _premier_contenu_pii(lignes)
    contenu.update(HUMAN_DECISION="PII_CLEARED", JUSTIFICATION_CATEGORY="TECHNICAL_FALSE_POSITIVE", REVIEWER_LOGIN="abenrhouma")
    erreurs = validateur.valider(RACINE, _ecrire(tmp_path, lignes))["errors"]
    assert any("finding" in e for e in erreurs)


def test_rejet_exige_un_finding_personnel(tmp_path, vierge):
    lignes = _copie(vierge)
    contenu, findings = _premier_contenu_pii(lignes)
    for f in findings:
        f["FINDING_DISPOSITION"] = "PUBLIC_INSTITUTIONAL_DATA"
    contenu.update(HUMAN_DECISION="EXCLUDE_FROM_SERVABLE_SET", JUSTIFICATION_CATEGORY="PERSONAL_DATA_PRESENT", REVIEWER_LOGIN="abenrhouma")
    erreurs = validateur.valider(RACINE, _ecrire(tmp_path, lignes))["errors"]
    assert any("au moins un" in e for e in erreurs)


def test_valeur_hors_liste_login_absent_et_preuve_absente(tmp_path, vierge):
    lignes = _copie(vierge)
    contenu, findings = _premier_contenu_pii(lignes)
    findings[0]["FINDING_DISPOSITION"] = "OK"
    actualite = next(x for x in lignes if x["row_kind"] == "CURRENTNESS_CONTENT")
    actualite.update(HUMAN_DECISION="KEEP_IF_STILL_CURRENT_WITH_EVIDENCE")
    erreurs = validateur.valider(RACINE, _ecrire(tmp_path, lignes))["errors"]
    assert any("OK" in e for e in erreurs)
    assert any("REVIEWER_LOGIN" in e for e in erreurs)
    assert any("EVIDENCE_REFERENCE" in e for e in erreurs)


def test_colonne_en_lecture_seule_modifiee_ou_ligne_inconnue_refusee(tmp_path, vierge):
    lignes = _copie(vierge)
    lignes[5]["pattern_id"] = "autre_chose"
    lignes.append({**lignes[0], "content_sha256": "0" * 64})
    erreurs = validateur.valider(RACINE, _ecrire(tmp_path, lignes))["errors"]
    assert any("lecture seule" in e for e in erreurs)
    assert any("inconnue" in e for e in erreurs)


def test_decision_posee_sur_une_ligne_de_finding_refusee(tmp_path, vierge):
    lignes = _copie(vierge)
    _contenu, findings = _premier_contenu_pii(lignes)
    findings[0]["HUMAN_DECISION"] = "PII_CLEARED"
    erreurs = validateur.valider(RACINE, _ecrire(tmp_path, lignes))["errors"]
    assert any("PII_FINDING" in e for e in erreurs)


def test_le_validateur_n_ecrit_rien(tmp_path, vierge):
    avant = {p: p.stat().st_mtime_ns for p in (RACINE / "governance").rglob("*") if p.is_file()}
    validateur.valider(RACINE, _ecrire(tmp_path, _copie(vierge)))
    assert avant == {p: p.stat().st_mtime_ns for p in (RACINE / "governance").rglob("*") if p.is_file()}
