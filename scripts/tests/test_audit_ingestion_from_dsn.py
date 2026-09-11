"""Tests de l'audit d'ingestion.

L'accès base est injecté : ces tests portent sur ce que le rapport a le droit
de conclure, pas sur la disponibilité d'un PostgreSQL.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts" / "go_live"))

import audit_ingestion_from_dsn as audit  # noqa: E402

DSN = "postgresql://utilisateur:motdepasse@hote.exemple:5433/labase"


def _poser_matrice(tmp_path: Path, contenus: list[str]) -> Path:
    racine = tmp_path / "depot"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    (racine / audit.MATRICE).write_text(
        json.dumps({"rows": [{"content_sha256": c, "verdict": "X"} for c in contenus]}),
        encoding="utf-8",
    )
    return racine


def _mesure(contenus, *, colonnes_vecteur=0, extension=False, avec_texte=None):
    def interrogateur(dsn: str, schema: str) -> dict:
        return {
            "contenus": set(contenus),
            "avec_texte_canonique": len(contenus) if avec_texte is None else avec_texte,
            "colonnes_vecteur": colonnes_vecteur,
            "extension_vecteur": extension,
            "tables": ["artifacts"],
        }

    return interrogateur


def test_l_ingestion_est_mesuree(tmp_path: Path):
    racine = _poser_matrice(tmp_path, ["a", "b"])
    rapport = audit.auditer(racine, DSN, "s", interrogateur=_mesure(["a", "b"]))
    assert rapport["ingested"]["contenus"] == 2
    assert rapport["ingested"]["inconnus_de_la_matrice"] == []


def test_un_contenu_ingere_inconnu_de_la_matrice_est_nomme(tmp_path: Path):
    racine = _poser_matrice(tmp_path, ["a"])
    rapport = audit.auditer(racine, DSN, "s", interrogateur=_mesure(["a", "intrus"]))
    assert rapport["ingested"]["inconnus_de_la_matrice"] == ["intrus"]


def test_sans_vecteur_rien_n_est_exploitable_par_recherche(tmp_path: Path):
    racine = _poser_matrice(tmp_path, ["a", "b"])
    rapport = audit.auditer(racine, DSN, "s", interrogateur=_mesure(["a", "b"]))
    assert rapport["searchable"]["searchable_contents"] == 0
    assert "aucun vecteur" in rapport["searchable"]["why"]


def test_du_texte_stocke_ne_vaut_pas_une_recherche(tmp_path: Path):
    """Le piège central : tout ingérer ne rend rien recherchable."""
    racine = _poser_matrice(tmp_path, ["a", "b"])
    rapport = audit.auditer(
        racine, DSN, "s", interrogateur=_mesure(["a", "b"], avec_texte=2)
    )
    assert rapport["ingested"]["avec_texte_canonique"] == 2
    assert rapport["searchable"]["searchable_contents"] == 0


def test_avec_vecteurs_le_contenu_devient_exploitable(tmp_path: Path):
    racine = _poser_matrice(tmp_path, ["a", "b"])
    rapport = audit.auditer(
        racine,
        DSN,
        "s",
        interrogateur=_mesure(["a", "b"], colonnes_vecteur=1, extension=True),
    )
    assert rapport["searchable"]["searchable_contents"] == 2


def test_une_colonne_vecteur_sans_extension_ne_suffit_pas(tmp_path: Path):
    racine = _poser_matrice(tmp_path, ["a"])
    rapport = audit.auditer(
        racine,
        DSN,
        "s",
        interrogateur=_mesure(["a"], colonnes_vecteur=1, extension=False),
    )
    assert rapport["searchable"]["searchable_contents"] == 0


def test_la_production_n_est_jamais_prononcee(tmp_path: Path):
    racine = _poser_matrice(tmp_path, ["a"])
    rapport = audit.auditer(racine, DSN, "s", interrogateur=_mesure(["a"]))
    assert rapport["served_in_production"]["measured"] is False
    assert audit.NIVEAU_JAMAIS_PRONONCE in rapport["never_asserted_here"]


def test_la_source_est_nommee_sans_identifiants(tmp_path: Path):
    racine = _poser_matrice(tmp_path, ["a"])
    rapport = audit.auditer(racine, DSN, "s", interrogateur=_mesure(["a"]))
    assert rapport["source"] == {
        "host": "hote.exemple",
        "port": 5433,
        "dbname": "labase",
    }
    rendu = json.dumps(rapport, ensure_ascii=False)
    assert "motdepasse" not in rendu
    assert "utilisateur" not in rendu


def test_matrice_absente_refuse(tmp_path: Path):
    racine = tmp_path / "vide"
    (racine / "docs/reports/handoff").mkdir(parents=True)
    with pytest.raises(audit.EntreeManquante):
        audit.auditer(racine, DSN, "s", interrogateur=_mesure(["a"]))


def test_matrice_sans_lignes_refuse(tmp_path: Path):
    racine = _poser_matrice(tmp_path, [])
    with pytest.raises(audit.EntreeManquante, match="sans lignes"):
        audit.auditer(racine, DSN, "s", interrogateur=_mesure(["a"]))


def test_l_audit_ne_rend_aucun_verdict_de_servabilite(tmp_path: Path):
    """Il lit la matrice pour savoir ce qu'elle recense, jamais pour décider.

    Cette épreuve tient la ligne `MATRIX_READER` de la baseline d'unicité
    d'autorité : la matrice ne sert ici qu'à reperer un contenu ingere qu'elle
    ne connait pas. Aucun verdict n'en est lu, et aucun n'en est produit.
    """
    racine = _poser_matrice(tmp_path, ["a"])
    rapport = audit.auditer(racine, DSN, "s", interrogateur=_mesure(["a"]))
    rendu = json.dumps(rapport, ensure_ascii=False)
    for mot in ("servable", "CANDIDATE", "BLOCKED", "verdict"):
        assert mot not in rendu, f"l'audit prononce « {mot} » : il déciderait au lieu de mesurer"


def test_le_module_ne_lit_aucun_verdict_de_la_matrice():
    source = (
        RACINE / "scripts/go_live/audit_ingestion_from_dsn.py"
    ).read_text(encoding="utf-8")
    assert '["verdict"]' not in source
    assert "CANDIDATE_NO_BLOCKING_DIMENSION" not in source
