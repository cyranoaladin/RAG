"""LOT44d : CoverageAgent — agrégation déterministe de CoverageSnapshot.

Périmètre strict : cœur pur, aucune E/S, aucun PostgreSQL, aucune horloge —
``period_start``/``period_end`` sont des paramètres explicites.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from nexus_contracts.ingestion import CollectionProfile

from ingestor.ingestion_agents.coverage_agent import build_coverage_snapshot_core

VALID_SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def _profile(**overrides: object) -> CollectionProfile:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": VALID_SCOPE,
        "title": "NSI Terminale Spécialité",
        "owner": "equipe-nsi",
        "expected_topics": ["algorithmique", "récursivité", "graphes"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 10,
        "max_documents_per_run": 20,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.6,
    }
    payload.update(overrides)
    return CollectionProfile.model_validate(payload)


class TestBuildCoverageSnapshotCore:
    def test_covered_and_insufficient_topics_partition_expected_topics(self) -> None:
        snapshot = build_coverage_snapshot_core(
            profile=_profile(),
            snapshot_id=uuid4(),
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 8, 4, tzinfo=UTC),
            topic_evidence_per_resource=[("algorithmique",), ("algorithmique", "récursivité")],
            quality_scores=[0.8, 0.6],
        )
        assert snapshot.covered_topics == ["algorithmique", "récursivité"]
        assert snapshot.insufficient_topics == ["graphes"]
        assert snapshot.resources_per_topic == {
            "algorithmique": 2,
            "récursivité": 1,
            "graphes": 0,
        }

    def test_recommended_next_queries_matches_insufficient_topics(self) -> None:
        snapshot = build_coverage_snapshot_core(
            profile=_profile(),
            snapshot_id=uuid4(),
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 8, 4, tzinfo=UTC),
            topic_evidence_per_resource=[("algorithmique",)],
            quality_scores=[0.8],
        )
        assert snapshot.recommended_next_queries == snapshot.insufficient_topics
        assert snapshot.gaps == snapshot.insufficient_topics

    def test_average_quality_is_none_when_no_scores(self) -> None:
        snapshot = build_coverage_snapshot_core(
            profile=_profile(),
            snapshot_id=uuid4(),
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 8, 4, tzinfo=UTC),
            topic_evidence_per_resource=[],
            quality_scores=[],
        )
        assert snapshot.average_quality is None
        assert snapshot.covered_topics == []
        assert snapshot.insufficient_topics == ["algorithmique", "récursivité", "graphes"]

    def test_average_quality_is_mean_of_scores(self) -> None:
        snapshot = build_coverage_snapshot_core(
            profile=_profile(),
            snapshot_id=uuid4(),
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 8, 4, tzinfo=UTC),
            topic_evidence_per_resource=[("algorithmique",)],
            quality_scores=[0.4, 0.6],
        )
        assert snapshot.average_quality == 0.5

    def test_evidence_topic_outside_expected_topics_is_ignored(self) -> None:
        snapshot = build_coverage_snapshot_core(
            profile=_profile(),
            snapshot_id=uuid4(),
            period_start=datetime(2026, 8, 1, tzinfo=UTC),
            period_end=datetime(2026, 8, 4, tzinfo=UTC),
            topic_evidence_per_resource=[("sujet_hors_profil",)],
            quality_scores=[0.5],
        )
        assert snapshot.resources_per_topic == {
            "algorithmique": 0,
            "récursivité": 0,
            "graphes": 0,
        }
