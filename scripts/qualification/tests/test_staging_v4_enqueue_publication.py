"""DG — mettre en file la publication d'une release attestée, et elle seule."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import staging_v4_enqueue_publication as outil  # noqa: E402

V4 = "production-profile-gate-2026-2027-v4"


class _Resultat:
    def __init__(self, lignes):
        self._lignes = lignes

    def fetchall(self):
        return list(self._lignes)


class _Connexion:
    """Rend les lignes attestées ; enregistre les paramètres de la requête."""

    def __init__(self, lignes):
        self.lignes = lignes
        self.parametres = None

    def execute(self, requete, parametres):
        assert "invalidated_at IS NULL" in requete and "pa.release_id" in requete
        self.parametres = parametres
        return _Resultat(self.lignes)


def _ligne(etat="NEEDS_REVIEW", collection="rag_nexus_nsi_premiere_specialite"):
    return (uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), collection, uuid.uuid4(), 10, etat)


class _File:
    """``find_or_create_job`` simulé : idempotent sur (collection, dedup_key)."""

    def __init__(self):
        self.jobs: dict[tuple[str, str], dict] = {}

    def __call__(self, conn, *, run_id, collection, job_type, dedup_key, resource_id, payload):
        assert job_type == "publication_resume"
        cle = (collection, dedup_key)
        if cle in self.jobs:
            return uuid.uuid4(), False
        self.jobs[cle] = dict(payload, resource_id_arg=str(resource_id), run_id_arg=str(run_id))
        return uuid.uuid4(), True


def test_un_job_par_attestation_nommant_ce_que_worker_b_exige():
    lignes = [_ligne() for _ in range(3)]
    file = _File()
    bilan = outil.mettre_en_file(_Connexion(lignes), release_id=V4, attendu=3, find_or_create_job=file)
    assert bilan == {"crees": 3, "deja_en_file": 0, "deja_publies": 0}
    for attestation, ressource, artefact, collection, run, version, _etat in lignes:
        job = file.jobs[(collection, f"publication:{attestation}")]
        assert job == {
            "resource_id": str(ressource), "run_id": str(run), "expected_state_version": version,
            "publication_attestation_id": str(attestation), "artifact_id": str(artefact),
            "resource_id_arg": str(ressource), "run_id_arg": str(run),
        }


def test_le_rejeu_ne_recree_rien():
    lignes = [_ligne() for _ in range(4)]
    file = _File()
    outil.mettre_en_file(_Connexion(lignes), release_id=V4, attendu=4, find_or_create_job=file)
    rejeu = outil.mettre_en_file(_Connexion(lignes), release_id=V4, attendu=4, find_or_create_job=file)
    assert rejeu == {"crees": 0, "deja_en_file": 4, "deja_publies": 0}


def test_une_ressource_deja_publiee_n_est_pas_remise_en_file():
    lignes = [_ligne(), _ligne("RETRIEVAL_ELIGIBLE")]
    file = _File()
    bilan = outil.mettre_en_file(_Connexion(lignes), release_id=V4, attendu=2, find_or_create_job=file)
    assert bilan == {"crees": 1, "deja_en_file": 0, "deja_publies": 1}
    assert len(file.jobs) == 1


@pytest.mark.parametrize("attendu", [2, 4])
def test_un_compte_different_de_l_attendu_est_refuse(attendu):
    lignes = [_ligne() for _ in range(3)]
    with pytest.raises(outil.MiseEnFileRefusee, match="attendu"):
        outil.mettre_en_file(_Connexion(lignes), release_id=V4, attendu=attendu, find_or_create_job=_File())


@pytest.mark.parametrize("etat", ["CANDIDATE", "STORED", "REJECTED", "PUBLISHING"])
def test_une_ressource_hors_revue_est_refusee(etat):
    lignes = [_ligne(), _ligne(etat)]
    with pytest.raises(outil.MiseEnFileRefusee, match=etat):
        outil.mettre_en_file(_Connexion(lignes), release_id=V4, attendu=2, find_or_create_job=_File())


def test_deux_attestations_actives_pour_une_ressource_sont_refusees():
    premiere = _ligne()
    doublon = (uuid.uuid4(), premiere[1], *premiere[2:])
    with pytest.raises(outil.MiseEnFileRefusee, match="plusieurs attestations"):
        outil.mettre_en_file(_Connexion([premiere, doublon]), release_id=V4, attendu=2, find_or_create_job=_File())


def test_la_requete_nomme_la_release_et_filtre_les_collections_si_demande():
    conn = _Connexion([_ligne()])
    outil.mettre_en_file(conn, release_id=V4, attendu=1, find_or_create_job=_File())
    assert conn.parametres == {"release": V4, "toutes": True, "collections": []}
    conn = _Connexion([_ligne()])
    outil.mettre_en_file(conn, release_id=V4, attendu=1, collections=("rag_nexus_x",), find_or_create_job=_File())
    assert conn.parametres == {"release": V4, "toutes": False, "collections": ["rag_nexus_x"]}


def test_la_requete_exige_l_artefact_de_la_release_et_la_meme_collection():
    assert "a.payload->>'release_id' = %(release)s" in outil.REQUETE
    assert "r.collection = pa.collection" in outil.REQUETE
    assert "JOIN ingestion_control.artifacts a ON a.artifact_id = pa.artifact_id" in outil.REQUETE
