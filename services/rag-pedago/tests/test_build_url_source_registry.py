"""Construction du registre — ce que le classement d'une sonde ne doit pas faire.

Une erreur transitoire (429, 5xx, réseau) ne prouve rien de permanent : elle
doit rester `EN_ATTENTE`, pas devenir `IRRECUPERABLE` sur un accident du
fournisseur ou du réseau. Une sonde directe qui rend une empreinte différente
de l'empreinte scellée est une dérive de contenu à la source : elle doit
arrêter la construction, pas s'écrire en silence dans le registre.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_url_source_registry import construire

SHA_A = "a" * 64

EVIDENCE_SANS_DIRECT = {
    "artifacts": [
        {
            "content_sha256": SHA_A,
            "current_download_url": None,
            "current_source_listing_url": "https://exemple/nav",
        }
    ]
}

EVIDENCE_AVEC_DIRECT = {
    "artifacts": [
        {
            "content_sha256": SHA_A,
            "current_download_url": "https://exemple/direct.pdf",
            "current_source_listing_url": "https://exemple/nav",
        }
    ]
}

CATALOGUE_TSV = "sha256\turl_source\n" f"{SHA_A}\thttps://exemple/nav\n"


def _ecrire(tmp_path: Path, evidence: dict) -> tuple[Path, Path]:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    catalogue_path = tmp_path / "catalogue.tsv"
    catalogue_path.write_text(CATALOGUE_TSV, encoding="utf-8")
    return evidence_path, catalogue_path


def _sondes(tmp_path: Path, sondes: dict) -> Path:
    sondes_path = tmp_path / "sondes.json"
    sondes_path.write_text(json.dumps(sondes), encoding="utf-8")
    return sondes_path


@pytest.mark.parametrize("statut", [429, 500, 503])
def test_un_statut_transitoire_reste_en_attente(tmp_path: Path, statut: int) -> None:
    evidence_path, catalogue_path = _ecrire(tmp_path, EVIDENCE_SANS_DIRECT)
    sondes_path = _sondes(
        tmp_path,
        {
            "https://exemple/nav": {
                "status": statut,
                "retrieved_at": "2026-09-05T18:00:00+00:00",
            }
        },
    )
    registre = construire(evidence_path, catalogue_path, sondes_path, nb_autorites=37)
    (entree,) = registre.entrees
    assert entree.resolution.value == "EN_ATTENTE"
    assert entree.raison_irrecuperabilite is None
    assert entree.preuve_irrecuperabilite is None


def test_une_erreur_reseau_sans_statut_reste_en_attente(tmp_path: Path) -> None:
    evidence_path, catalogue_path = _ecrire(tmp_path, EVIDENCE_SANS_DIRECT)
    sondes_path = _sondes(
        tmp_path,
        {
            "https://exemple/nav": {
                "status": None,
                "erreur": "Connection timed out",
                "retrieved_at": "2026-09-05T18:00:00+00:00",
            }
        },
    )
    registre = construire(evidence_path, catalogue_path, sondes_path, nb_autorites=37)
    (entree,) = registre.entrees
    assert entree.resolution.value == "EN_ATTENTE"


def test_un_403_reste_irrecuperable(tmp_path: Path) -> None:
    evidence_path, catalogue_path = _ecrire(tmp_path, EVIDENCE_SANS_DIRECT)
    sondes_path = _sondes(
        tmp_path,
        {
            "https://exemple/nav": {
                "status": 403,
                "retrieved_at": "2026-09-05T18:00:00+00:00",
            }
        },
    )
    registre = construire(evidence_path, catalogue_path, sondes_path, nb_autorites=37)
    (entree,) = registre.entrees
    assert entree.resolution.value == "IRRECUPERABLE"
    assert entree.raison_irrecuperabilite == "NAVIGATION_PROTEGEE_403"


def test_une_sonde_directe_incoherente_refuse_la_construction(tmp_path: Path) -> None:
    evidence_path, catalogue_path = _ecrire(tmp_path, EVIDENCE_AVEC_DIRECT)
    sondes_path = _sondes(
        tmp_path,
        {
            "https://exemple/direct.pdf": {
                "status": 200,
                "content_sha256": "b" * 64,
                "retrieved_at": "2026-09-05T18:00:00+00:00",
            },
            "https://exemple/nav": {
                "status": 200,
                "retrieved_at": "2026-09-05T18:00:00+00:00",
            },
        },
    )
    with pytest.raises(SystemExit, match="EMPREINTE_DERIVEE"):
        construire(evidence_path, catalogue_path, sondes_path, nb_autorites=37)
