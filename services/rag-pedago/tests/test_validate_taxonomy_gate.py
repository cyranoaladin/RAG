"""Contrat de la garde `taxonomy-validation` — R15.

La garde rendait `0` sur un répertoire vide exactement comme sur soixante fichiers
valides : `return 1 if errors else 0`, et zéro fichier ne produit zéro erreur. Une
cible de CI qui **certifie l'absence de la chose qu'elle valide** est pire qu'aucune
garde — elle transforme la disparition du socle taxonomique en succès annoncé.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_taxonomy.py"
REELLE = Path(__file__).resolve().parents[1] / "taxonomy"


def _charger(racine: Path | None, monkeypatch: pytest.MonkeyPatch) -> Any:
    if racine is not None:
        monkeypatch.setenv("NEXUS_TAXONOMY_DIR", str(racine))
    else:
        monkeypatch.delenv("NEXUS_TAXONOMY_DIR", raising=False)
    spec = importlib.util.spec_from_file_location("validate_taxonomy_sut", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_un_repertoire_vide_est_refuse(tmp_path: Path, monkeypatch) -> None:
    """Zéro fichier validé n'est pas « rien à signaler », c'est « rien mesuré »."""
    outil = _charger(tmp_path, monkeypatch)
    assert outil.validate_all() != 0


def test_un_repertoire_absent_est_refuse(tmp_path: Path, monkeypatch) -> None:
    """Une racine inexistante ne doit pas se lire comme une taxonomie sans défaut."""
    outil = _charger(tmp_path / "nulle-part", monkeypatch)
    assert outil.validate_all() != 0


def test_la_taxonomie_reelle_est_acceptee(monkeypatch) -> None:
    """Témoin positif : sans lui, un refus systématique passerait pour une garde."""
    outil = _charger(None, monkeypatch)
    assert outil.validate_all() == 0


def test_la_racine_est_surchargeable(tmp_path: Path, monkeypatch) -> None:
    """`AGENTS.md` : racine dérivée de l'emplacement, AVEC override d'environnement."""
    outil = _charger(tmp_path, monkeypatch)
    assert outil.TAXONOMY_DIR == tmp_path


def test_la_racine_par_defaut_reste_la_taxonomie_du_service(monkeypatch) -> None:
    outil = _charger(None, monkeypatch)
    assert outil.TAXONOMY_DIR == REELLE
