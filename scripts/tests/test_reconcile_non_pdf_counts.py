"""Tests de la réconciliation 37 / 57.

Ce que ces tests protègent : qu'aucun des deux totaux ne puisse passer pour
l'autre, et qu'une conservation vérifiée ne ferme pas un compteur par elle-même.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import reconcile_non_pdf_counts as reco  # noqa: E402


def _poser(tmp_path: Path, demandes, *, servable=None, total=None, retenu=0):
    racine = tmp_path / "depot"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / "docs/reports/evidence-index").mkdir(parents=True)
    (racine / reco.MANIFESTE).write_text(
        json.dumps({"requests": demandes}), encoding="utf-8"
    )
    nb_servable = sum(
        1 for d in demandes if d["classification"] == reco.CLASSIFICATION_SERVABLE
    )
    (racine / reco.CONSOLIDATION).write_text(
        json.dumps(
            {
                "NON_PDF_SERVABLE": nb_servable if servable is None else servable,
                "NON_PDF_TOTAL": len(demandes) if total is None else total,
                "NON_PDF_LOCAL_COPY_RETAINED": retenu,
            }
        ),
        encoding="utf-8",
    )
    return racine


def _demande(nom, octets, classification=reco.CLASSIFICATION_SERVABLE, ident=None):
    return {
        "drive_file_id": ident or f"id-{nom}",
        "drive_path": f"NEXUS_RAG_GDRIVE_READY/03/{nom}",
        "expected_content_sha256": hashlib.sha256(octets).hexdigest(),
        "expected_size": len(octets),
        "classification": classification,
        "target_disposition": classification,
    }


def _magasin(tmp_path: Path, contenus: dict[str, bytes]) -> Path:
    d = tmp_path / "durable"
    d.mkdir()
    for ident, octets in contenus.items():
        (d / ident).write_bytes(octets)
    return d


def test_les_deux_totaux_sont_distincts_et_reconcilies(tmp_path: Path):
    demandes = [
        _demande("a.ggb", b"a"),
        _demande("b.ggb", b"b"),
        _demande("c.yaml", b"c", "DIAGNOSTIC_QUESTION_BANK_NON_INDEXABLE"),
    ]
    etat = reco.reconcilier(_poser(tmp_path, demandes), None)
    assert etat["totals"]["requests_57"] == 3
    assert etat["totals"]["servable_37"] == 2
    assert etat["totals"]["non_indexable"] == 1
    assert etat["reconciled"] is True


def test_un_compteur_de_gate_qui_ne_correspond_pas_refuse_la_reconciliation(
    tmp_path: Path,
):
    demandes = [_demande("a.ggb", b"a"), _demande("b.ggb", b"b")]
    etat = reco.reconcilier(_poser(tmp_path, demandes, servable=99), None)
    assert etat["reconciled"] is False


def test_une_ligne_non_servable_n_entre_pas_dans_le_37(tmp_path: Path):
    demandes = [_demande("c.yaml", b"c", "DIAGNOSTIC_QUESTION_BANK_NON_INDEXABLE")]
    etat = reco.reconcilier(_poser(tmp_path, demandes), None)
    ligne = etat["rows"][0]
    assert ligne["counted_in_37"] is False
    assert ligne["counted_in_57"] is True
    assert ligne["disposition"] == reco.NON_GGB_NON_PDF


def test_deux_demandes_sur_les_memes_octets_sont_nommees_doublon(tmp_path: Path):
    demandes = [_demande("a.ggb", b"meme", ident="id-1"), _demande("b.ggb", b"meme", ident="id-2")]
    etat = reco.reconcilier(_poser(tmp_path, demandes), None)
    assert all(ligne["disposition"] == reco.DUPLICATE_REQUEST_SAME_BYTES for ligne in etat["rows"])
    # Deux demandes, une seule empreinte : la réconciliation doit le refuser.
    assert etat["reconciled"] is False


def test_conservation_mesuree_sur_les_octets_pas_declaree(tmp_path: Path):
    demandes = [_demande("a.ggb", b"a"), _demande("b.ggb", b"b")]
    racine = _poser(tmp_path, demandes)
    magasin = _magasin(tmp_path, {"id-a.ggb": b"a"})
    etat = reco.reconcilier(racine, magasin)
    statuts = {x["drive_file_id"]: x["retained_copy_status"] for x in etat["rows"]}
    assert statuts["id-a.ggb"] == reco.RETENU
    assert statuts["id-b.ggb"] == reco.ABSENT


def test_des_octets_alteres_ne_comptent_pas_comme_retenus(tmp_path: Path):
    demandes = [_demande("a.ggb", b"attendu")]
    racine = _poser(tmp_path, demandes)
    magasin = _magasin(tmp_path, {"id-a.ggb": b"different"})
    etat = reco.reconcilier(racine, magasin)
    assert etat["rows"][0]["retained_copy_status"] == reco.ALTERE
    assert etat["retention"]["retained_verified"] == 0


def test_des_octets_de_meme_taille_mais_differents_sont_refuses(tmp_path: Path):
    """Isole le contrôle d'empreinte : la taille seule ne l'attraperait pas.

    Sans cette épreuve, supprimer la comparaison de SHA passerait inaperçu,
    parce qu'une falsification change presque toujours aussi la longueur.
    """
    demandes = [_demande("a.ggb", b"attendu")]
    racine = _poser(tmp_path, demandes)
    magasin = _magasin(tmp_path, {"id-a.ggb": b"AUTRE!!"})  # 7 octets, comme b"attendu"
    assert len(b"AUTRE!!") == len(b"attendu")
    etat = reco.reconcilier(racine, magasin)
    assert etat["rows"][0]["retained_copy_status"] == reco.ALTERE
    assert etat["retention"]["retained_verified"] == 0


def test_une_conservation_complete_ne_ferme_aucun_compteur(tmp_path: Path):
    """Le piège : tout retenir ne vaut pas décision de gouvernance."""
    demandes = [_demande("a.ggb", b"a")]
    racine = _poser(tmp_path, demandes)
    etat = reco.reconcilier(racine, _magasin(tmp_path, {"id-a.ggb": b"a"}))
    assert etat["retention"]["retained_verified"] == 1
    assert etat["retention"]["closes_gate_counter"] is False
    assert etat["gate_counts"]["NON_PDF_LOCAL_COPY_RETAINED"] == 0


def test_sans_magasin_rien_n_est_retenu(tmp_path: Path):
    demandes = [_demande("a.ggb", b"a")]
    etat = reco.reconcilier(_poser(tmp_path, demandes), None)
    assert etat["retention"]["durable_store_named"] is False
    assert etat["retention"]["retained_verified"] == 0


def test_manifeste_absent_refuse(tmp_path: Path):
    racine = tmp_path / "vide"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    with pytest.raises(reco.EntreeManquante):
        reco.reconcilier(racine, None)


def test_compteur_de_consolidation_absent_refuse_en_nommant(tmp_path: Path):
    demandes = [_demande("a.ggb", b"a")]
    racine = _poser(tmp_path, demandes)
    (racine / reco.CONSOLIDATION).write_text(json.dumps({"AUTRE": 1}), encoding="utf-8")
    with pytest.raises(reco.EntreeManquante) as err:
        reco.reconcilier(racine, None)
    assert "NON_PDF_SERVABLE" in str(err.value) and "AUTRE" in str(err.value)
