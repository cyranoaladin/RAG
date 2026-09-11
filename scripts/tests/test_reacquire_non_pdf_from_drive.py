"""Tests de la réacquisition non-PDF.

Le téléchargement réseau est injecté : ces tests portent sur la règle de
vérification, pas sur la disponibilité du Drive. Un test qui exigerait le
réseau ne dirait plus si la règle est juste ou si la connexion était bonne.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import reacquire_non_pdf_from_drive as reacq  # noqa: E402


def _poser_manifeste(tmp_path: Path, contenus: dict[str, bytes], *, acceptation=None):
    racine = tmp_path / "depot"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    demandes = [
        {
            "drive_file_id": identifiant,
            "expected_content_sha256": hashlib.sha256(octets).hexdigest(),
            "expected_size": len(octets),
        }
        for identifiant, octets in contenus.items()
    ]
    document = {
        "kind": "NEXUS-NON-PDF-REACQUISITION-MANIFEST-V1",
        "requests": demandes,
        "acceptance": acceptation
        if acceptation is not None
        else {"REACQUIRED_NON_PDF": len(demandes), "SHA256_MISMATCH": 0, "SIZE_MISMATCH": 0},
    }
    (racine / reacq.MANIFESTE).write_text(json.dumps(document), encoding="utf-8")
    return racine


def _telechargeur(servi: dict[str, bytes]):
    def telecharger(identifiant: str, destination: Path) -> None:
        if identifiant in servi:
            destination.write_bytes(servi[identifiant])

    return telecharger


def test_octets_conformes_donnent_un_verdict_conforme(tmp_path: Path):
    contenus = {"id-a": b"alpha", "id-b": b"beta"}
    racine = _poser_manifeste(tmp_path, contenus)
    rapport = reacq.verifier(
        racine, tmp_path / "dest", telechargeur=_telechargeur(contenus)
    )
    assert rapport["verdict"] == reacq.VERDICT_CONFORME
    assert rapport["measurements"]["REACQUIRED_NON_PDF"] == 2
    assert rapport["failures"] == []


def test_empreinte_differente_est_refusee_et_nommee(tmp_path: Path):
    contenus = {"id-a": b"alpha"}
    racine = _poser_manifeste(tmp_path, contenus)
    rapport = reacq.verifier(
        racine, tmp_path / "dest", telechargeur=_telechargeur({"id-a": b"falsifie"})
    )
    assert rapport["verdict"] == reacq.VERDICT_NON_CONFORME
    assert rapport["measurements"]["SHA256_MISMATCH"] == 1
    assert rapport["failures"][0]["drive_file_id"] == "id-a"
    assert rapport["failures"][0]["observed_content_sha256"] != rapport["failures"][0][
        "expected_content_sha256"
    ]


def test_taille_differente_est_refusee(tmp_path: Path):
    contenus = {"id-a": b"alpha"}
    racine = _poser_manifeste(tmp_path, contenus)
    document = json.loads((racine / reacq.MANIFESTE).read_text())
    document["requests"][0]["expected_size"] = 999
    (racine / reacq.MANIFESTE).write_text(json.dumps(document), encoding="utf-8")
    rapport = reacq.verifier(
        racine, tmp_path / "dest", telechargeur=_telechargeur(contenus)
    )
    assert rapport["measurements"]["SIZE_MISMATCH"] == 1
    assert rapport["verdict"] == reacq.VERDICT_NON_CONFORME


def test_telechargement_impossible_est_compte_et_non_ignore(tmp_path: Path):
    contenus = {"id-a": b"alpha", "id-b": b"beta"}
    racine = _poser_manifeste(tmp_path, contenus)
    rapport = reacq.verifier(
        racine, tmp_path / "dest", telechargeur=_telechargeur({"id-a": b"alpha"})
    )
    assert rapport["measurements"]["FETCH_FAILED"] == 1
    assert rapport["verdict"] == reacq.VERDICT_NON_CONFORME


def test_une_demande_non_satisfaite_ne_peut_pas_etre_conforme(tmp_path: Path):
    contenus = {"id-a": b"alpha", "id-b": b"beta"}
    racine = _poser_manifeste(
        tmp_path, contenus, acceptation={"REACQUIRED_NON_PDF": 1}
    )
    rapport = reacq.verifier(
        racine, tmp_path / "dest", telechargeur=_telechargeur({"id-a": b"alpha"})
    )
    assert rapport["verdict"] == reacq.VERDICT_NON_CONFORME


def test_un_critere_d_acceptation_non_tenu_refuse_meme_sans_aucun_echec(
    tmp_path: Path,
):
    """Isole la clause d'acceptation : sans elle, ce cas passerait pour conforme."""
    contenus = {"id-a": b"alpha", "id-b": b"beta"}
    racine = _poser_manifeste(
        tmp_path, contenus, acceptation={"REACQUIRED_NON_PDF": 5}
    )
    rapport = reacq.verifier(
        racine, tmp_path / "dest", telechargeur=_telechargeur(contenus)
    )
    assert rapport["measurements"]["SHA256_MISMATCH"] == 0
    assert rapport["measurements"]["SIZE_MISMATCH"] == 0
    assert rapport["measurements"]["FETCH_FAILED"] == 0
    assert rapport["measurements"]["REACQUIRED_NON_PDF"] == 2
    assert rapport["verdict"] == reacq.VERDICT_NON_CONFORME


def test_un_statut_inconnu_ne_peut_pas_passer_pour_une_conformite(
    tmp_path: Path, monkeypatch
):
    """Le verdict porte sur les résultats, pas sur trois compteurs d'échec."""
    contenus = {"id-a": b"alpha"}
    racine = _poser_manifeste(tmp_path, contenus, acceptation={})
    monkeypatch.setattr(reacq, "VERIFIE", "STATUT_INATTENDU")
    rapport = reacq.verifier(
        racine, tmp_path / "dest", telechargeur=_telechargeur({"id-a": b"autre"})
    )
    assert rapport["verdict"] == reacq.VERDICT_NON_CONFORME


def test_le_rapport_ne_declare_jamais_une_copie_durable(tmp_path: Path):
    contenus = {"id-a": b"alpha"}
    racine = _poser_manifeste(tmp_path, contenus)
    rapport = reacq.verifier(
        racine, tmp_path / "dest", telechargeur=_telechargeur(contenus)
    )
    assert rapport["durable_copy_retained"] is False
    assert "servabilité" in rapport["proves_nothing_about"]


def test_manifeste_absent_refuse(tmp_path: Path):
    racine = tmp_path / "vide"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    with pytest.raises(reacq.EntreeManquante, match="manifeste de réacquisition absent"):
        reacq.verifier(racine, tmp_path / "dest")


def test_manifeste_sans_demande_refuse(tmp_path: Path):
    racine = tmp_path / "depot"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / reacq.MANIFESTE).write_text(json.dumps({"requests": []}), encoding="utf-8")
    with pytest.raises(reacq.EntreeManquante, match="aucune demande"):
        reacq.verifier(racine, tmp_path / "dest")


def test_demande_sans_empreinte_attendue_refusee(tmp_path: Path):
    racine = tmp_path / "depot"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / reacq.MANIFESTE).write_text(
        json.dumps({"requests": [{"drive_file_id": "x", "expected_size": 3}]}),
        encoding="utf-8",
    )
    with pytest.raises(reacq.EntreeManquante, match="expected_content_sha256"):
        reacq.verifier(racine, tmp_path / "dest")


def test_un_fichier_deja_present_et_conforme_n_est_pas_retelecharge(tmp_path: Path):
    contenus = {"id-a": b"alpha"}
    racine = _poser_manifeste(tmp_path, contenus)
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "id-a").write_bytes(b"alpha")

    appels: list[str] = []

    def telechargeur(identifiant: str, cible: Path) -> None:
        appels.append(identifiant)

    rapport = reacq.verifier(racine, destination, telechargeur=telechargeur)
    assert appels == []
    assert rapport["verdict"] == reacq.VERDICT_CONFORME
