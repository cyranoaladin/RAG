"""ADR-0061 — le programme d'un profil hors lignée historique est la référence officielle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
PROFILS = RACINE / "services/rag-engine/configs/ingestion_profiles"
REGISTRE = RACINE / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/programme_registry.json"
)


def _profils(dossier: str):
    from nexus_release_chain.ingestion_profiles.registry import load_profile_registry

    return {p.scope.collection: p for p in load_profile_registry(PROFILS / dossier).values()}


def test_les_profils_v4_portent_le_programme_du_registre() -> None:
    from conftest import load_producer

    producer = load_producer()
    producer.require_profile_programmes_match_registry(
        _profils("v3_livraison_315"), json.loads(REGISTRE.read_text(encoding="utf-8"))
    )


def test_les_profils_historiques_sont_refuses_hors_de_leur_lignee() -> None:
    from conftest import load_producer

    producer = load_producer()
    with pytest.raises(ValueError, match="official programme"):
        producer.require_profile_programmes_match_registry(
            _profils("v2_livraison_319"), json.loads(REGISTRE.read_text(encoding="utf-8"))
        )


def test_une_collection_absente_du_registre_est_refusee() -> None:
    from conftest import load_producer

    producer = load_producer()
    registre = json.loads(REGISTRE.read_text(encoding="utf-8"))
    registre["taxonomies"] = registre["taxonomies"][1:]
    with pytest.raises(ValueError, match="official programme"):
        producer.require_profile_programmes_match_registry(_profils("v3_livraison_315"), registre)
