"""Tests du rapport de préservation.

Ce qui est protégé : qu'aucun secret ne soit publié, qu'une sauvegarde non
restaurée ne passe pas pour restaurée, et que mettre des octets à l'abri ne
ferme aucun compteur.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import report_staging_preservation as rapport  # noqa: E402

INSPECT = [
    {
        "Name": "/nexus-drive-staging-v2",
        "Id": "a" * 64,
        "Image": "sha256:" + "b" * 64,
        "Config": {
            "Image": "pgvector/pgvector:pg16",
            "Env": [
                "POSTGRES_DB=drivestaging",
                "POSTGRES_USER=drive",
                "POSTGRES_PASSWORD=tres-secret",
                "API_TOKEN=abc",
                "MY_SECRET_KEY=xyz",
                "LANG=en_US.utf8",
            ],
            "Labels": {},
        },
        "State": {"Status": "running", "StartedAt": "2026-09-06T21:47:26Z"},
        "HostConfig": {"RestartPolicy": {"Name": "no"}},
        "RestartCount": 0,
        "NetworkSettings": {"Ports": {}, "Networks": {"bridge": {}}},
        "Mounts": [
            {
                "Type": "volume",
                "Name": "e" * 64,
                "Destination": "/var/lib/postgresql/data",
                "RW": True,
            }
        ],
    }
]


def test_tout_secret_est_masque_quel_que_soit_son_nom():
    etat = rapport.construire_inventaire(INSPECT)
    rendu = json.dumps(etat) + rapport.rendre_inventaire_md(etat)
    for valeur in ("tres-secret", "abc", "xyz"):
        assert valeur not in rendu
    assert "POSTGRES_DB=drivestaging" in rendu
    assert etat["secrets_published"] is False


def test_un_volume_anonyme_est_signale_comme_risque():
    etat = rapport.construire_inventaire(INSPECT)
    assert etat["mounts"][0]["anonymous_volume"] is True
    assert etat["risk"]["anonymous_volumes"] == 1
    assert etat["risk"]["restart_policy_is_none"] is True


def test_un_volume_nomme_n_est_pas_signale_anonyme():
    inspect = json.loads(json.dumps(INSPECT))
    inspect[0]["Mounts"][0]["Name"] = "nexus-data"
    etat = rapport.construire_inventaire(inspect)
    assert etat["mounts"][0]["anonymous_volume"] is False
    assert etat["risk"]["anonymous_volumes"] == 0


@pytest.mark.parametrize("nom", ["PASSWORD", "DB_SECRET", "API_TOKEN", "SIGNING_KEY", "PASS"])
def test_les_noms_evoquant_un_secret_sont_reconnus(nom):
    assert rapport.est_secret(nom)


def test_un_nom_anodin_n_est_pas_masque():
    assert not rapport.est_secret("POSTGRES_DB")
    assert not rapport.est_secret("LANG")


def _mesures(**surcharges):
    base = {
        "counts_source": {"artifacts": 10},
        "counts_restored": {"artifacts": 10},
        "digests_source": {"artifacts": "d1"},
        "digests_restored": {"artifacts": "d1"},
        "controles": {"x": 1},
    }
    base.update(surcharges)
    return base


def test_une_restauration_identique_est_prouvee():
    m = _mesures()
    etat = rapport.construire_preuve(
        m["counts_source"], m["counts_restored"], m["digests_source"],
        m["digests_restored"], m["controles"],
    )
    assert etat["restore_proven"] is True


def test_un_comptage_different_refuse_la_preuve():
    m = _mesures(counts_restored={"artifacts": 9})
    etat = rapport.construire_preuve(
        m["counts_source"], m["counts_restored"], m["digests_source"],
        m["digests_restored"], m["controles"],
    )
    assert etat["restore_proven"] is False
    assert etat["count_mismatches"][0]["table"] == "artifacts"


def test_des_comptages_egaux_sur_un_texte_different_ne_prouvent_rien():
    """Le contrôle qui fait la différence : le digest, pas seulement le compte."""
    m = _mesures(digests_restored={"artifacts": "AUTRE"})
    etat = rapport.construire_preuve(
        m["counts_source"], m["counts_restored"], m["digests_source"],
        m["digests_restored"], m["controles"],
    )
    assert etat["count_mismatches"] == []
    assert etat["review_text_digests_match"] is False
    assert etat["restore_proven"] is False


def test_une_preuve_sans_source_est_refusee():
    with pytest.raises(rapport.EntreeManquante):
        rapport.construire_preuve({}, {}, {}, {}, {})


def test_le_magasin_non_pdf_ne_ferme_aucun_compteur():
    etat = rapport.construire_manifeste_non_pdf(
        "/tmp/x", [{"name": "a", "size": 3, "sha256": "s"}], 1
    )
    assert etat["complete"] is True
    assert etat["closes_gate_counter"] is False
    assert "non_pdf_37_vs_57_reconciliation" in etat["coverage_authority"]


def test_un_magasin_incomplet_est_dit_incomplet():
    etat = rapport.construire_manifeste_non_pdf(
        "/tmp/x", [{"name": "a", "size": 3, "sha256": "s"}], 57
    )
    assert etat["complete"] is False


def test_l_emplacement_ne_publie_aucun_chemin_absolu_de_la_machine():
    foyer = str(Path.home())
    etat = rapport.construire_manifeste_non_pdf(f"{foyer}/sauvegardes/x", [], 0)
    assert etat["durable_location"] == "~/sauvegardes/x"
    assert foyer not in json.dumps(etat)
