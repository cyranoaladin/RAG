"""Tests for v2 collection config: anti-auto-creation invariant (M-04, ADR-0013)."""
from __future__ import annotations

import pytest

from src.ingestor.collection_config import (
    CollectionNotInstanciatedError,
    CollectionUnknownError,
    list_instanciated_collections,
    resolve_collection_v2,
)

V2_CONFIG = {
    "version": 2,
    "physical_backend": {"type": "pgvector", "table": "rag_chunks"},
    "collections": {
        "rag_nexus_nsi_terminale_specialite": {
            "matiere": "nsi",
            "niveau": "terminale",
            "statut": "specialite",
            "instanciee": True,
        },
        "rag_nexus_maths_seconde_tc": {
            "matiere": "maths",
            "niveau": "seconde",
            "statut": "tronc_commun",
            "instanciee": False,
        },
        "rag_nexus_quarantine": {
            "matiere": None,
            "niveau": None,
            "statut": None,
            "instanciee": True,
        },
    },
}


class TestResolveCollectionV2:
    def test_instanciated_collection_resolves(self) -> None:
        result = resolve_collection_v2("rag_nexus_nsi_terminale_specialite", V2_CONFIG)
        assert result["matiere"] == "nsi"
        assert result["instanciee"] is True

    def test_quarantine_resolves(self) -> None:
        result = resolve_collection_v2("rag_nexus_quarantine", V2_CONFIG)
        assert result["instanciee"] is True

    def test_non_instanciated_collection_raises(self) -> None:
        with pytest.raises(CollectionNotInstanciatedError, match="not instanciated"):
            resolve_collection_v2("rag_nexus_maths_seconde_tc", V2_CONFIG)

    def test_unknown_collection_raises(self) -> None:
        with pytest.raises(CollectionUnknownError, match="not declared"):
            resolve_collection_v2("rag_nexus_fantasy_collection", V2_CONFIG)

    def test_auto_creation_blocked(self) -> None:
        """The anti-auto-creation invariant: unknown names MUST raise, never create."""
        with pytest.raises(CollectionUnknownError):
            resolve_collection_v2("rag_web3", V2_CONFIG)

    def test_catalogue_entry_without_instanciation_blocked(self) -> None:
        """A catalogue entry with instanciee=false MUST NOT be served."""
        with pytest.raises(CollectionNotInstanciatedError):
            resolve_collection_v2("rag_nexus_maths_seconde_tc", V2_CONFIG)


class TestListInstanciatedCollections:
    def test_returns_only_instanciated(self) -> None:
        result = list_instanciated_collections(V2_CONFIG)
        assert sorted(result) == [
            "rag_nexus_nsi_terminale_specialite",
            "rag_nexus_quarantine",
        ]

    def test_excludes_non_instanciated(self) -> None:
        result = list_instanciated_collections(V2_CONFIG)
        assert "rag_nexus_maths_seconde_tc" not in result
