"""Le multi-placement est légitime ; le doublon dans une même collection ne l'est pas.

Ces deux tests tirent dans les deux sens. Le second est celui qui empêchera qu'on
réintroduise la contradiction : un contrôle d'unicité globale du contenu
interdirait le multi-placement, que le modèle de données, le mandat et la
conception du corpus prévoient tous les trois.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_producteur",
    Path(__file__).resolve().parents[1] / "scripts" / "build_production_profile_release.py",
)
_PRODUCTEUR = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_PRODUCTEUR)

_CONTENU = "a" * 64
_AUTRE = "b" * 64


def test_un_doublon_dans_la_meme_collection_echoue() -> None:
    """L'invariant réel : deux fois le même contenu dans la même collection."""
    lignes = [
        {"collection": "rag_nexus_maths_terminale", "content_sha256": _CONTENU},
        {"collection": "rag_nexus_maths_terminale", "content_sha256": _CONTENU},
    ]
    with pytest.raises(ValueError, match="duplicate collection/content"):
        _PRODUCTEUR.stable_release_order(lignes)


def test_le_multi_placement_passe() -> None:
    """Un même contenu dans DEUX collections différentes est légitime.

    C'est le cas que le contrôle d'unicité globale interdisait. 922 documents du
    corpus Éduscol sont dans cette situation, pour 5 379 placements — un
    programme de spécialité arts vaut pour sept disciplines, un B.O. générique
    pour plusieurs niveaux.
    """
    lignes = [
        {"collection": "rag_nexus_arts_plastiques_premiere", "content_sha256": _CONTENU},
        {"collection": "rag_nexus_musique_premiere", "content_sha256": _CONTENU},
        {"collection": "rag_nexus_danse_terminale", "content_sha256": _CONTENU},
    ]
    ordonnees = _PRODUCTEUR.stable_release_order(lignes)
    assert len(ordonnees) == 3
    assert {ligne["content_sha256"] for ligne in ordonnees} == {_CONTENU}
    assert len({ligne["collection"] for ligne in ordonnees}) == 3


def test_l_ordre_reste_stable_et_deterministe() -> None:
    """Deux exécutions sur les mêmes lignes rendent le même ordre."""
    lignes = [
        {"collection": "rag_nexus_b", "content_sha256": _AUTRE},
        {"collection": "rag_nexus_a", "content_sha256": _CONTENU},
        {"collection": "rag_nexus_a", "content_sha256": _AUTRE},
    ]
    premier = _PRODUCTEUR.stable_release_order(list(lignes))
    second = _PRODUCTEUR.stable_release_order(list(reversed(lignes)))
    assert premier == second
    assert [ligne["collection"] for ligne in premier] == [
        "rag_nexus_a", "rag_nexus_a", "rag_nexus_b"]
