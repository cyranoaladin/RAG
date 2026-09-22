"""Épreuves de l'index de revue restreint aux contenus promus bloquants : dérivé, stable, fail-closed."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))
sys.path.insert(0, str(RACINE / "services/rag-pedago/scripts"))

import build_promoted_restricted_review_index as restreint  # noqa: E402


@pytest.fixture(scope="module")
def construit() -> dict:
    return restreint.construire(RACINE)


def _poser(tmp_path: Path, document: dict, *, tamper_sha: bool = False) -> Path:
    for relatif in (restreint.INDEX_V2, restreint.IMPACT, restreint.READINESS):
        cible = tmp_path / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes((RACINE / relatif).read_bytes())
    octets = restreint.octets_canoniques(document)
    sortie = tmp_path / restreint.SORTIE
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_bytes(octets)
    digest = "f" * 64 if tamper_sha else hashlib.sha256(octets).hexdigest()
    (tmp_path / restreint.SORTIE_SHA).write_text(f"{digest}  {restreint.SORTIE}\n", encoding="utf-8")
    return tmp_path


def _refus(tmp_path, construit, muter=None, **kw) -> str:
    document = copy.deepcopy(construit)
    if muter:
        muter(document)
    ecarts = restreint.valider(_poser(tmp_path, document, **kw))
    assert ecarts, "le validateur aurait dû refuser"
    return " | ".join(ecarts)


def test_populations_derivees_des_autorites(construit):
    impact = json.loads((RACINE / restreint.IMPACT).read_text(encoding="utf-8"))
    promus = {r["content_sha256"] for r in impact["rows"]}
    pii = {b["content_sha256"] for b in construit["bundles"]}
    actualite = {c["content_sha256"] for c in construit["currentness_contents"]}
    assert pii | actualite == promus and not pii & actualite
    assert len(actualite) == impact["counts"]["release_promoted_refused_by_currentness"]
    assert construit["counts"] == {"bundles": len(pii), "scanned": len(pii),
                                   "findings": sum(b["finding_count"] for b in construit["bundles"]),
                                   "currentness_contents": len(actualite)}


def test_chaque_paquet_est_celui_de_l_index_v2_a_l_identique(construit):
    v2 = {b["content_sha256"]: b for b in json.loads((RACINE / restreint.INDEX_V2).read_text(encoding="utf-8"))["bundles"]}
    for paquet in construit["bundles"]:
        origine = v2[paquet["content_sha256"]]
        sans_page = {**paquet, "findings": [{k: v for k, v in f.items() if k != "page"} for f in paquet["findings"]]}
        assert sans_page == origine
        assert all(f["page"] == f["page_number"] for f in paquet["findings"])


def test_instruments_repris_de_l_index_v2_jamais_reecrits(construit):
    v2 = json.loads((RACINE / restreint.INDEX_V2).read_text(encoding="utf-8"))
    for cle in restreint.INSTRUMENTS:
        assert construit[cle] == v2[cle]
    assert construit["protocol_version"] == "NEXUS-PII-REVIEW-INDEX-V1"


def test_stable_aucune_date_ni_empreinte_du_readiness(construit):
    """Le jeu de décisions épinglera l'empreinte de CE fichier : il ne doit pas bouger à chaque lot."""
    assert restreint.octets_canoniques(construit) == restreint.octets_canoniques(restreint.construire(RACINE))
    texte = json.dumps(construit)
    assert restreint.READINESS not in texte and "generated_at" not in construit


def test_artefact_versionne_a_jour_scelle_et_valide(construit):
    assert (RACINE / restreint.SORTIE).read_bytes() == restreint.octets_canoniques(construit)
    assert restreint.valider(RACINE) == []


def test_le_scelleur_gouverne_accepte_l_index_restreint_et_desormais_le_v2(tmp_path):
    """La raison d'être du lot CB : `sceller_decisions_pii.py` plantait sur l'index V2
    (`page_number`). Le lot CV l'a corrigé (ADR-0059 §6) : la page se lit sous l'une
    ou l'autre clé, et une divergence entre les deux est refusée. L'index V2 donne
    donc un gabarit complet, sans aucune décision prise."""
    import sceller_decisions_pii as scelleur

    arguments = {"decision_set_id": "pii-review-epreuve-cb", "corpus_manifest_sha256": "a" * 64, "reviewer_login": "reviewer"}
    scelleur.brouillon(index_path=RACINE / restreint.INDEX_V2, sortie=tmp_path / "v2.json", **arguments)
    v2 = json.loads((RACINE / restreint.INDEX_V2).read_text(encoding="utf-8"))
    gabarit_v2 = json.loads((tmp_path / "v2.json").read_text(encoding="utf-8"))
    assert set(gabarit_v2["decisions"]) == {b["content_sha256"] for b in v2["bundles"]}
    assert {d["decision"] for d in gabarit_v2["decisions"].values()} == {scelleur.PLACEHOLDER}
    scelleur.brouillon(index_path=RACINE / restreint.SORTIE, sortie=tmp_path / "restreint.json", **arguments)
    brouillon = json.loads((tmp_path / "restreint.json").read_text(encoding="utf-8"))
    assert len(brouillon["decisions"]) == 23
    # Le brouillon n'est qu'un gabarit : toute décision y est encore à prendre.
    assert {d["decision"] for d in brouillon["decisions"].values()} == {scelleur.PLACEHOLDER}
    assert {f["disposition"] for d in brouillon["decisions"].values() for f in d["findings"].values()} == {scelleur.PLACEHOLDER}


def test_scellement_de_bout_en_bout_sur_un_index_synthetique(tmp_path):
    """Mécanique seule, sur des empreintes FICTIVES : aucune décision n'est prise sur un contenu réel."""
    import sceller_decisions_pii as scelleur

    v2 = json.loads((RACINE / restreint.INDEX_V2).read_text(encoding="utf-8"))
    modele = copy.deepcopy(v2["bundles"][0])
    modele["content_sha256"] = "c" * 64
    synthetique = restreint.restreindre(
        {**v2, "bundles": [modele]}, pii_promus=["c" * 64], actualite=[], impact_par_sha={}, sources={}
    )
    index_path = tmp_path / "index.json"
    index_path.write_bytes(restreint.octets_canoniques(synthetique))
    arguments = {"decision_set_id": "pii-review-epreuve-synthetique", "corpus_manifest_sha256": "a" * 64, "reviewer_login": "reviewer"}
    scelleur.brouillon(index_path=index_path, sortie=tmp_path / "b.json", **arguments)
    brouillon = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    entree = brouillon["decisions"]["c" * 64]
    entree.update(decision="REJECTED", decided_at="2026-01-01T00:00:00+00:00",
                  justification={"category": "PERSONAL_DATA_PRESENT", "statement": "épreuve mécanique sur empreinte fictive"})
    for finding in entree["findings"].values():
        finding["disposition"] = "PERSONAL_DATA_PRESENT"
    (tmp_path / "b.json").write_text(json.dumps(brouillon), encoding="utf-8")
    digest = scelleur.sceller(draft=tmp_path / "b.json", index_path=index_path, sortie=tmp_path / "scelle.json")
    assert len(digest) == 64
    scelle = json.loads((tmp_path / "scelle.json").read_text(encoding="utf-8"))
    assert scelle["review_index_sha256"] == hashlib.sha256(index_path.read_bytes()).hexdigest()


def test_refuse_index_absent_et_altere(tmp_path, construit):
    assert any("absent" in e for e in restreint.valider(tmp_path))
    assert "altér" in _refus(tmp_path, construit, tamper_sha=True)


def test_refuse_contenu_non_promu_ou_promu_manquant(tmp_path, construit):
    def ajoute(d):
        intrus = copy.deepcopy(d["bundles"][0])
        intrus["content_sha256"] = "0" * 64
        d["bundles"].append(intrus)
    assert "non promu" in _refus(tmp_path, construit, ajoute)

    def retire(d):
        d["bundles"].pop()
    assert "manquant" in _refus(tmp_path, construit, retire)


def test_refuse_finding_manquant_ou_modifie(tmp_path, construit):
    def retire(d):
        d["bundles"][0]["findings"].pop()
    assert "finding" in _refus(tmp_path, construit, retire)

    def modifie(d):
        d["bundles"][0]["findings"][0]["match_sha256"] = "0" * 64
    assert "finding" in _refus(tmp_path, construit, modifie)


def test_refuse_actualite_manquante(tmp_path, construit):
    def retire(d):
        d["currentness_contents"].pop()
    assert "actualité" in _refus(tmp_path, construit, retire)


def test_refuse_instrument_reecrit(tmp_path, construit):
    def m(d):
        d["scanner_sha256"] = "0" * 64
    assert "instrument" in _refus(tmp_path, construit, m)


@pytest.mark.parametrize("cle", ["decision", "disposition", "human_decision", "reviewer_decision"])
def test_refuse_decision_preremplie(tmp_path, construit, cle):
    def m(d):
        d["bundles"][0][cle] = "APPROVED"
    assert "décision" in _refus(tmp_path, construit, m)


def test_refuse_matiere_brute_secret_et_chemin_personnel(tmp_path, construit):
    def brute(d):
        d["bundles"][0]["findings"][0]["match_text"] = "x"
    assert "brute" in _refus(tmp_path, construit, brute)

    def chemin(d):
        d["bundles"][0]["bundle_dir"] = "/home/quelquun/paquets/abc"
    assert "chemin" in _refus(tmp_path, construit, chemin)

    def secret(d):
        d["note"] = "password=hunter2"
    assert "secret" in _refus(tmp_path, construit, secret)


# --- passage suivant : feuille remplie → brouillon du scelleur gouverné ----------------------


def _feuille_fictive(tmp_path: Path, *, laisser_en_attente: bool = False) -> Path:
    """Feuille remplie de décisions FICTIVES, écrite hors dépôt, pour éprouver la seule mécanique.
    Tout y est REJECTED / PERSONAL_DATA_PRESENT : le sens le plus restrictif, qui n'admet aucun contenu."""
    import csv
    import io

    import build_pii_currentness_decision_packet as dossier

    lignes = list(csv.DictReader(io.StringIO(dossier.rendre_tsv_c1(dossier.construire(RACINE))), delimiter="\t"))
    for ligne in lignes:
        if ligne["row_kind"] == "PII_FINDING":
            ligne["FINDING_DISPOSITION"] = "PERSONAL_DATA_PRESENT"
        elif ligne["row_kind"] == "PII_CONTENT":
            ligne.update(HUMAN_DECISION="EXCLUDE_FROM_SERVABLE_SET", JUSTIFICATION_CATEGORY="PERSONAL_DATA_PRESENT",
                         REVIEWER_LOGIN="reviewer-fictif", COMMENT="décision fictive, épreuve mécanique seulement")
    if laisser_en_attente:
        next(x for x in lignes if x["row_kind"] == "PII_CONTENT")["HUMAN_DECISION"] = ""
    chemin = tmp_path / "feuille.tsv"
    with chemin.open("w", encoding="utf-8", newline="") as flux:
        ecrit = csv.DictWriter(flux, fieldnames=list(lignes[0]), delimiter="\t", lineterminator="\n")
        ecrit.writeheader()
        ecrit.writerows(lignes)
    return chemin


def test_feuille_minimale_et_index_restreint_disent_la_meme_chose(construit):
    import csv
    import io

    import build_pii_currentness_decision_packet as dossier

    lignes = list(csv.DictReader(io.StringIO(dossier.rendre_tsv_c1(dossier.construire(RACINE))), delimiter="\t"))
    assert {x["content_sha256"] for x in lignes if x["row_kind"] == "PII_CONTENT"} == {b["content_sha256"] for b in construit["bundles"]}
    assert {x["finding_id"] for x in lignes if x["row_kind"] == "PII_FINDING"} == {f["finding_id"] for b in construit["bundles"] for f in b["findings"]}
    assert {x["content_sha256"] for x in lignes if x["row_kind"] == "CURRENTNESS_CONTENT"} == {c["content_sha256"] for c in construit["currentness_contents"]}


def test_conversion_puis_scellement_par_l_outil_gouverne_hors_depot(tmp_path):
    import convert_review_sheet_to_sealer_draft as convertisseur
    import sceller_decisions_pii as scelleur

    resultat = convertisseur.convertir(
        RACINE, _feuille_fictive(tmp_path), decision_set_id="pii-review-epreuve-mecanique",
        corpus_manifest_sha256="a" * 64, decided_at="2026-01-01T00:00:00+00:00",
    )
    assert len(resultat["sealer_draft"]["decisions"]) == 23
    assert set(resultat["human_options"].values()) == {"EXCLUDE_FROM_SERVABLE_SET"}
    (tmp_path / "draft.json").write_text(json.dumps(resultat["sealer_draft"]), encoding="utf-8")
    scelleur.sceller(draft=tmp_path / "draft.json", index_path=RACINE / restreint.SORTIE, sortie=tmp_path / "scelle.json")
    scelle = json.loads((tmp_path / "scelle.json").read_text(encoding="utf-8"))
    assert len(scelle["decisions"]) == 23 and {d["decision"] for d in scelle["decisions"]} == {"REJECTED"}
    assert scelle["review_index_sha256"] == hashlib.sha256((RACINE / restreint.SORTIE).read_bytes()).hexdigest()
    # Rien n'a été écrit dans le dépôt : ni décision, ni compteur.
    assert not list((RACINE / "governance/pii-review-decisions").glob("*epreuve*"))


def test_conversion_refuse_une_feuille_incomplete_ou_vierge(tmp_path):
    import convert_review_sheet_to_sealer_draft as convertisseur

    arguments = {"decision_set_id": "x", "corpus_manifest_sha256": "a" * 64, "decided_at": "2026-01-01T00:00:00+00:00"}
    with pytest.raises(convertisseur.ConversionRefusee, match="scellable"):
        convertisseur.convertir(RACINE, _feuille_fictive(tmp_path, laisser_en_attente=True), **arguments)
    with pytest.raises(convertisseur.ConversionRefusee, match="scellable"):
        convertisseur.convertir(RACINE, RACINE / "docs/reports/go_live/pii_currentness_minimal_c1_review.tsv", **arguments)
    with pytest.raises(convertisseur.ConversionRefusee, match="fuseau"):
        convertisseur.convertir(RACINE, _feuille_fictive(tmp_path), **{**arguments, "decided_at": "2026-01-01T00:00:00"})
