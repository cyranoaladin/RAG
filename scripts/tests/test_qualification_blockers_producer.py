"""Épreuves du producteur de blocages de qualification.

La liste était tenue à la main. Deux défauts en découlaient : un blocage dont
la preuve existait pouvait rester ouvert par oubli, et un blocage pouvait être
fermé d'un coup d'éditeur sans preuve. Ces épreuves portent sur les deux.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import build_qualification_blockers as blocages  # noqa: E402

RAPPORT = RACINE / "docs/reports/go_live/qualification_blockers.json"


def test_fermer_sans_preuve_est_refuse_a_la_construction(monkeypatch):
    """LA règle du mandat, tenue par le code et non par la vigilance."""
    faux = (("X", "titre", "operateur", "condition", lambda _r: {"closed": True, "proof": None}),)
    monkeypatch.setattr(blocages, "BLOCAGES", faux)
    with pytest.raises(blocages.PreuveAbsente, match="sans preuve"):
        blocages.construire(RACINE)


def test_un_blocage_sans_verificateur_reste_ouvert(monkeypatch):
    """Ne pas savoir n'est pas fermer."""
    monkeypatch.setattr(
        blocages, "BLOCAGES", (("X", "titre", "operateur", "condition", None),)
    )
    etat = blocages.construire(RACINE)
    assert etat["blockers"][0]["closed"] is False
    assert etat["blockers"][0]["proof"] is None
    assert "ne pas savoir" in etat["blockers"][0]["why_still_open"]


def test_un_verificateur_qui_prouve_ferme(monkeypatch):
    """Le refus doit discriminer, sinon rien ne se fermerait jamais."""
    monkeypatch.setattr(
        blocages,
        "BLOCAGES",
        (
            (
                "X", "titre", "operateur", "condition",
                lambda _r: {"closed": True, "proof": {"verification": "mesurée"}},
            ),
        ),
    )
    etat = blocages.construire(RACINE)
    assert etat["blockers"][0]["closed"] is True
    assert etat["closed_count"] == 1


def test_un_store_absent_ne_ferme_pas(tmp_path, monkeypatch):
    """Une preuve qui ne peut pas être recalculée n'est pas une preuve.

    L'emplacement est ici DANS la racine canonique : ce que le cas éprouve est
    bien l'absence, pas le hors-périmètre, qui a son propre cas.
    """
    monkeypatch.setenv("NEXUS_NON_PDF_STORE", str(tmp_path / "store"))
    (tmp_path / "docs/reports/go_live").mkdir(parents=True)
    for nom, contenu in (
        (blocages.RECONCILIATION, {"rows": [], "gate_counts": {"NON_PDF_SERVABLE": 0}}),
        (
            blocages.MANIFESTE_STORE,
            {"durable_location": str(tmp_path / "store" / "absent"), "sha256sums": []},
        ),
        (
            blocages.POLITIQUE,
            {
                "adopted": True,
                "closes_blocker_when": "x",
                "durable_store": {
                    "canonical_root": str(tmp_path / "store"),
                    "env_override": "NEXUS_NON_PDF_STORE",
                },
            },
        ),
    ):
        (tmp_path / nom).write_text(json.dumps(contenu), encoding="utf-8")
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "store durable absent" in resultat["why"]


def test_une_politique_non_adoptee_ne_ferme_pas(tmp_path):
    (tmp_path / "docs/reports/go_live").mkdir(parents=True)
    for nom, contenu in (
        (blocages.RECONCILIATION, {"rows": [], "gate_counts": {"NON_PDF_SERVABLE": 0}}),
        (blocages.MANIFESTE_STORE, {"durable_location": "/x", "sha256sums": []}),
        (blocages.POLITIQUE, {"adopted": False}),
    ):
        (tmp_path / nom).write_text(json.dumps(contenu), encoding="utf-8")
    assert blocages.verifier_non_pdf(tmp_path)["closed"] is False


def test_une_entree_absente_interrompt(tmp_path):
    with pytest.raises(blocages.EntreeManquante):
        blocages.verifier_non_pdf(tmp_path)


# --- Le rapport VERSIONNÉ -------------------------------------------------


@pytest.fixture(scope="module")
def rapport() -> dict:
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_aucun_blocage_ferme_sans_preuve(rapport):
    for bloc in rapport["blockers"]:
        if bloc["closed"]:
            assert bloc["proof"], bloc["id"]


def test_chaque_blocage_porte_sa_condition_de_fermeture(rapport):
    """Sans condition écrite, son propriétaire ne sait pas quoi produire."""
    for bloc in rapport["blockers"]:
        assert bloc["closing_condition"], bloc["id"]
        assert len(bloc["closing_condition"]) > 20, bloc["id"]


def test_le_rollback_de_staging_ne_ferme_pas_celui_de_production(rapport):
    """Deux objets différents : les confondre fermerait un blocage à tort."""
    rollback = next(b for b in rapport["blockers"] if b["id"] == "ROLLBACK")
    assert rollback["closed"] is False
    assert "staging" in rollback["closing_condition"]
    assert "pas les mêmes objets" in rollback["closing_condition"]


def test_la_reacquisition_non_pdf_est_fermee_par_mesure(rapport):
    bloc = next(b for b in rapport["blockers"] if b["id"] == "NON_PDF_REACQUISITION")
    assert bloc["closed"] is True
    assert bloc["proof"]["servable_resources_verified"] == 37
    assert "RECALCULÉE" in bloc["proof"]["verification"]
    assert bloc["proof"]["does_not_close"]


def test_le_compte_ouvert_correspond_aux_blocages(rapport):
    ouverts = [b for b in rapport["blockers"] if not b["closed"]]
    assert rapport["open_count"] == len(ouverts)
    assert rapport["closed_count"] + rapport["open_count"] == len(rapport["blockers"])


# --- Le store doit être le CANONIQUE, pas n'importe lequel ----------------


def _poser_non_pdf(tmp_path, *, store: Path, taille: int | None = 10,
                   canonical_root: str = "/backup/rag/non-pdf-reacquired"):
    (tmp_path / "docs/reports/go_live").mkdir(parents=True, exist_ok=True)
    store.mkdir(parents=True, exist_ok=True)
    octets = b"x" * 10
    (store / "ressource").write_bytes(octets)
    import hashlib

    empreinte = hashlib.sha256(octets).hexdigest()
    entree = {"name": "ressource", "sha256": empreinte}
    if taille is not None:
        entree["size"] = taille
    for nom, contenu in (
        (
            blocages.RECONCILIATION,
            {
                "rows": [{"sha256": empreinte, "counted_in_37": True}],
                "gate_counts": {"NON_PDF_SERVABLE": 1},
            },
        ),
        (
            blocages.MANIFESTE_STORE,
            {"durable_location": str(store), "sha256sums": [entree]},
        ),
        (
            blocages.POLITIQUE,
            {
                "adopted": True,
                "closes_blocker_when": "condition",
                "does_not_close": [],
                "durable_store": {
                    "canonical_root": canonical_root,
                    "env_override": "NEXUS_NON_PDF_STORE",
                },
            },
        ),
    ):
        (tmp_path / nom).write_text(json.dumps(contenu), encoding="utf-8")
    return empreinte


def test_un_store_hors_racine_canonique_ne_ferme_pas(tmp_path, monkeypatch):
    """La sauvegarde de secours contient les bonnes empreintes — et ne compte pas.

    La politique dit `emergency_is_not_canonical`. Faire confiance au chemin
    que le manifeste NOMME laisserait fermer le blocage sur elle.
    """
    monkeypatch.delenv("NEXUS_NON_PDF_STORE", raising=False)
    secours = tmp_path / "secours" / "non-pdf-reacquired" / "20260911T155246Z"
    _poser_non_pdf(tmp_path, store=secours)
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "hors du store canonique" in resultat["why"]


def test_une_surcharge_declaree_par_la_politique_est_honoree(tmp_path, monkeypatch):
    """Le refus doit discriminer : une surcharge légitime doit passer."""
    store = tmp_path / "ailleurs" / "20260911T155246Z"
    monkeypatch.setenv("NEXUS_NON_PDF_STORE", str(tmp_path / "ailleurs"))
    _poser_non_pdf(tmp_path, store=store)
    assert blocages.verifier_non_pdf(tmp_path)["closed"] is True


def test_une_politique_sans_racine_canonique_ne_ferme_pas(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_NON_PDF_STORE", raising=False)
    store = tmp_path / "s" / "t"
    _poser_non_pdf(tmp_path, store=store, canonical_root="")
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "racine de store canonique" in resultat["why"]


# --- La taille doit être LUE, pas seulement prétendue ---------------------


def test_une_taille_absente_du_manifeste_ne_ferme_pas(tmp_path, monkeypatch):
    """Ne pas savoir n'est pas vérifier."""
    monkeypatch.setenv("NEXUS_NON_PDF_STORE", str(tmp_path / "s"))
    _poser_non_pdf(tmp_path, store=tmp_path / "s" / "t", taille=None)
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "sans taille attendue" in resultat["why"]


def test_une_taille_discordante_ne_ferme_pas(tmp_path, monkeypatch):
    """Le contrôle lisait `bytes` quand le champ s'appelle `size` : il était
    inerte, et la preuve affirmait pourtant que les tailles étaient comparées."""
    monkeypatch.setenv("NEXUS_NON_PDF_STORE", str(tmp_path / "s"))
    _poser_non_pdf(tmp_path, store=tmp_path / "s" / "t", taille=999999)
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "tailles discordantes" in resultat["why"]


def test_la_preuve_nomme_la_racine_et_le_nombre_de_tailles_comparees(rapport):
    bloc = next(b for b in rapport["blockers"] if b["id"] == "NON_PDF_REACQUISITION")
    assert bloc["proof"]["canonical_root"]
    assert bloc["proof"]["sizes_compared"] == 37
