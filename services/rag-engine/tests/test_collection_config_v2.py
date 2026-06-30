"""Tests for v2 collection config: anti-auto-creation invariant (M-04, ADR-0013).

These tests validate resolve_collection_v2 — the SOLE resolver for new code.
No cross-contamination with legacy resolver.
"""
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

    def test_non_instanciated_raises(self) -> None:
        """S-03: instanciee:false MUST raise on ALL resolution paths."""
        with pytest.raises(CollectionNotInstanciatedError, match="not instanciated"):
            resolve_collection_v2("rag_nexus_maths_seconde_tc", V2_CONFIG)

    def test_unknown_raises(self) -> None:
        with pytest.raises(CollectionUnknownError, match="not declared"):
            resolve_collection_v2("rag_nexus_fantasy_collection", V2_CONFIG)

    def test_auto_creation_blocked(self) -> None:
        """Anti-auto-creation: unknown names MUST raise, never create."""
        with pytest.raises(CollectionUnknownError):
            resolve_collection_v2("rag_web3", V2_CONFIG)

    # R-02/S-03: instanciee must be boolean True, not truthy
    def test_truthy_string_rejected(self) -> None:
        config = {
            "version": 2,
            "collections": {"test_col": {"matiere": "x", "instanciee": "true"}},
        }
        with pytest.raises(CollectionNotInstanciatedError):
            resolve_collection_v2("test_col", config)

    def test_truthy_int_rejected(self) -> None:
        config = {
            "version": 2,
            "collections": {"test_col": {"matiere": "x", "instanciee": 1}},
        }
        with pytest.raises(CollectionNotInstanciatedError):
            resolve_collection_v2("test_col", config)

    # S-02: no fallback, no name-matching, no "first instanciated" guessing
    def test_no_name_matching_fallback(self) -> None:
        """section='education' must NOT silently match a collection containing 'education'."""
        # resolve_collection_v2 takes a collection NAME, not a section — no matching.
        with pytest.raises(CollectionUnknownError):
            resolve_collection_v2("education", V2_CONFIG)

    def test_no_first_instanciated_fallback(self) -> None:
        """An unknown name must raise, not fall back to first instanciated."""
        with pytest.raises(CollectionUnknownError):
            resolve_collection_v2("default", V2_CONFIG)


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

    def test_truthy_string_excluded(self) -> None:
        """instanciee: 'true' (string) must NOT be listed."""
        config = {
            "version": 2,
            "collections": {"test_col": {"matiere": "x", "instanciee": "true"}},
        }
        assert list_instanciated_collections(config) == []
