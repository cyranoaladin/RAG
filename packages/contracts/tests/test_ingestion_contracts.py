"""Tests des contrats canoniques du moteur d'ingestion (LOT44a).

Couvre : CollectionProfile, SearchPlan, ResourceCandidate, ArtifactRecord,
RoutingDecision, QualityReport, IngestionRun, CoverageSnapshot.

Invariants vérifiés :
- le scope gouverné complet (tenant/collection/niveau/voie/matiere/candidat/
  audience/visibility/school_year/programme_version) est obligatoire et
  fail-closed sur chaque modèle qui porte un scope ;
- les identifiants d'exécution (run_id, job équivalent, resource_id,
  candidate_id, artifact_id, decision_id, report_id, snapshot_id,
  search_plan_id) sont des UUID, jamais des hash ;
- les hash déterministes (dedup_key, sha256) restent réservés à la
  déduplication/l'idempotence/le rattachement de version ;
- l'auto-publication est verrouillée à False au niveau du type, pas
  seulement par une valeur par défaut ;
- aucun de ces modèles ne référence ni ne construit un état "PUBLISHED".
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from nexus_contracts import (
    ArtifactRecord,
    Audience,
    Candidat,
    CollectionProfile,
    CoverageSnapshot,
    IngestionRun,
    Niveau,
    PublicationPolicy,
    QualityReport,
    ResourceCandidate,
    ResourceScope,
    Rights,
    RoutingDecision,
    SearchPlan,
    TypeDoc,
    Voie,
)

NOW = datetime(2026, 8, 3, tzinfo=timezone.utc)


def _valid_scope(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "tenant": "libre_terminale",
        "collection": "rag_nexus_nsi_terminale_specialite",
        "niveau": Niveau.terminale,
        "voie": Voie.generale,
        "matiere": "nsi",
        "candidat": Candidat.libre,
        "audience": [Audience.libre, Audience.tous],
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "BOEN_special_8_2019-07-25",
    }
    base.update(overrides)
    return base


# --- ResourceScope : obligatoire et fail-closed ---


def test_resource_scope_valid_construction() -> None:
    scope = ResourceScope(**_valid_scope())
    assert scope.tenant == "libre_terminale"
    assert scope.candidat is Candidat.libre


@pytest.mark.parametrize(
    "missing_field",
    [
        "tenant", "collection", "niveau", "voie", "matiere", "candidat",
        "audience", "visibility", "school_year", "programme_version",
    ],
)
def test_resource_scope_fails_closed_when_any_field_is_missing(missing_field: str) -> None:
    payload = _valid_scope()
    del payload[missing_field]
    with pytest.raises(ValidationError):
        ResourceScope(**payload)


def test_resource_scope_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ResourceScope(**_valid_scope(extra_field="not_allowed"))


def test_resource_scope_rejects_duplicate_audience() -> None:
    with pytest.raises(ValidationError):
        ResourceScope(**_valid_scope(audience=[Audience.tous, Audience.tous]))


def test_resource_scope_rejects_empty_audience() -> None:
    with pytest.raises(ValidationError):
        ResourceScope(**_valid_scope(audience=[]))


@pytest.mark.parametrize("school_year", ["2026", "2026-2028", "abcd-efgh", "2026-2026"])
def test_resource_scope_rejects_invalid_school_year(school_year: str) -> None:
    with pytest.raises(ValidationError):
        ResourceScope(**_valid_scope(school_year=school_year))


def test_resource_scope_rejects_invalid_visibility() -> None:
    with pytest.raises(ValidationError):
        ResourceScope(**_valid_scope(visibility="not_a_real_visibility"))


# --- PublicationPolicy : auto-publication verrouillée ---


def test_publication_policy_defaults_to_human_review_and_no_auto_publish() -> None:
    policy = PublicationPolicy()
    assert policy.mode == "human_review"
    assert policy.auto_publish is False


def test_publication_policy_rejects_auto_publish_true() -> None:
    with pytest.raises(ValidationError):
        PublicationPolicy(auto_publish=True)


def test_publication_policy_rejects_unimplemented_mode() -> None:
    with pytest.raises(ValidationError):
        PublicationPolicy(mode="trusted_auto_publish")


# --- CollectionProfile ---


def _valid_collection_profile(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "profile_version": "1.0",
        "enabled": True,
        "scope": ResourceScope(**_valid_scope()),
        "title": "NSI Terminale Spécialité",
        "owner": "nexus-reussite",
        "expected_topics": ["algorithmique", "structures_de_donnees"],
        "expected_resource_types": [TypeDoc.programme_officiel, TypeDoc.cours],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 20,
        "max_documents_per_run": 50,
        "max_chunk_size": 1200,
        "chunk_overlap": 150,
        "min_source_confidence": 0.9,
        "min_scope_confidence": 0.9,
        "min_extraction_quality": 0.95,
    }
    base.update(overrides)
    return base


def test_collection_profile_valid_construction() -> None:
    profile = CollectionProfile(**_valid_collection_profile())
    assert profile.enabled is True
    assert profile.publication.auto_publish is False
    assert profile.publication.mode == "human_review"


def test_collection_profile_requires_scope() -> None:
    payload = _valid_collection_profile()
    del payload["scope"]
    with pytest.raises(ValidationError):
        CollectionProfile(**payload)


def test_collection_profile_rejects_chunk_overlap_not_smaller_than_chunk_size() -> None:
    with pytest.raises(ValidationError):
        CollectionProfile(**_valid_collection_profile(max_chunk_size=100, chunk_overlap=100))


def test_collection_profile_rejects_empty_allowed_domains() -> None:
    with pytest.raises(ValidationError):
        CollectionProfile(**_valid_collection_profile(allowed_domains=[]))


def test_collection_profile_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CollectionProfile(**_valid_collection_profile(unexpected="value"))


# --- SearchPlan ---


def _valid_search_plan(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "search_plan_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "scope": ResourceScope(**_valid_scope()),
        "generated_at": NOW,
        "profile_version": "1.0",
        "queries": ["programme officiel NSI terminale"],
        "allowed_domains": ["eduscol.education.fr"],
        "max_results": 20,
        "reason": "lacune de couverture sur le theme algorithmique",
    }
    base.update(overrides)
    return base


def test_search_plan_valid_construction_uses_uuid_identifiers() -> None:
    plan = SearchPlan(**_valid_search_plan())
    assert isinstance(plan.search_plan_id, uuid.UUID)
    assert isinstance(plan.run_id, uuid.UUID)


def test_search_plan_rejects_string_identifiers_that_are_not_uuids() -> None:
    with pytest.raises(ValidationError):
        SearchPlan(**_valid_search_plan(run_id="not-a-uuid"))


def test_search_plan_rejects_empty_queries() -> None:
    with pytest.raises(ValidationError):
        SearchPlan(**_valid_search_plan(queries=[]))


def test_search_plan_requires_a_reason() -> None:
    payload = _valid_search_plan()
    del payload["reason"]
    with pytest.raises(ValidationError):
        SearchPlan(**payload)


# --- ResourceCandidate ---


def _valid_candidate(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "candidate_id": uuid.uuid4(),
        "resource_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "scope": ResourceScope(**_valid_scope()),
        "discovered_at": NOW,
        "source_url": "https://eduscol.education.fr/nsi-terminale",
        "canonical_url": "https://eduscol.education.fr/nsi-terminale",
        "domain": "eduscol.education.fr",
        "proposed_type_doc": TypeDoc.programme_officiel,
        "dedup_key": "a" * 64,
    }
    base.update(overrides)
    return base


def test_resource_candidate_always_carries_a_resource_id() -> None:
    """Invariant : un candidat accepté possède une ressource provisoire
    rattachée — resource_id est donc obligatoire, jamais nul."""
    candidate = ResourceCandidate(**_valid_candidate())
    assert isinstance(candidate.resource_id, uuid.UUID)


def test_resource_candidate_requires_resource_id() -> None:
    payload = _valid_candidate()
    del payload["resource_id"]
    with pytest.raises(ValidationError):
        ResourceCandidate(**payload)


def test_resource_candidate_dedup_key_is_a_deterministic_hash_not_a_uuid() -> None:
    candidate = ResourceCandidate(**_valid_candidate())
    assert isinstance(candidate.dedup_key, str)
    assert len(candidate.dedup_key) == 64


def test_resource_candidate_rejects_malformed_dedup_key() -> None:
    with pytest.raises(ValidationError):
        ResourceCandidate(**_valid_candidate(dedup_key="not-a-sha256"))


def test_resource_candidate_has_no_status_field() -> None:
    """Le statut d'un candidat n'existe qu'au travers de resource_state
    (rattaché via resource_id) — un second suivi d'état parallèle sur le
    candidat lui-même romprait le principe d'un gate d'état unique."""
    assert "status" not in ResourceCandidate.model_fields


# --- ArtifactRecord ---


def _valid_artifact(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "artifact_id": uuid.uuid4(),
        "resource_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "scope": ResourceScope(**_valid_scope()),
        "sha256": "b" * 64,
        "size_bytes": 204800,
        "mime_declared": "application/pdf",
        "mime_detected": "application/pdf",
        "original_url": "https://eduscol.education.fr/doc.pdf",
        "final_url": "https://eduscol.education.fr/doc.pdf",
        "collected_at": NOW,
        "domain": "eduscol.education.fr",
        "rights_status": Rights.officiel_public,
    }
    base.update(overrides)
    return base


def test_artifact_record_valid_construction() -> None:
    artifact = ArtifactRecord(**_valid_artifact())
    assert artifact.sha256 == "b" * 64
    assert isinstance(artifact.artifact_id, uuid.UUID)


def test_artifact_record_rejects_negative_size() -> None:
    with pytest.raises(ValidationError):
        ArtifactRecord(**_valid_artifact(size_bytes=-1))


def test_artifact_record_rejects_malformed_sha256() -> None:
    with pytest.raises(ValidationError):
        ArtifactRecord(**_valid_artifact(sha256="too-short"))


# --- RoutingDecision ---


def _valid_routing_decision(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "decision_id": uuid.uuid4(),
        "resource_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "scope": ResourceScope(**_valid_scope()),
        "decision": "ROUTE",
        "confidence": 0.95,
        "rules_applied": ["domain_official_whitelist", "scope_exact_match"],
        "profile_version": "1.0",
        "agent_identity": "classifier-v1",
        "decided_at": NOW,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("decision", ["ROUTE", "QUARANTINE", "REJECT", "DUPLICATE", "SUPERSEDED"])
def test_routing_decision_accepts_all_minimal_decisions(decision: str) -> None:
    routing = RoutingDecision(**_valid_routing_decision(decision=decision))
    assert routing.decision == decision


def test_routing_decision_rejects_unknown_decision_value() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision(**_valid_routing_decision(decision="PUBLISH"))


def test_routing_decision_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision(**_valid_routing_decision(confidence=1.5))


def test_routing_decision_requires_at_least_one_rule() -> None:
    with pytest.raises(ValidationError):
        RoutingDecision(**_valid_routing_decision(rules_applied=[]))


# --- QualityReport ---


def _valid_quality_report(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "report_id": uuid.uuid4(),
        "resource_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "scope": ResourceScope(**_valid_scope()),
        "extraction_quality": 0.9,
        "readability": 0.8,
        "language_detected": "fr",
        "structure_score": 0.85,
        "niveau_conformity": True,
        "voie_conformity": True,
        "matiere_conformity": True,
        "programme_conformity": True,
        "topic_coverage": 0.7,
        "relevance_score": 0.9,
        "pii_detected": False,
        "duplicate_detected": False,
        "metadata_quality": 0.9,
        "rights_status": Rights.officiel_public,
        "evaluated_at": NOW,
    }
    base.update(overrides)
    return base


def test_quality_report_valid_construction() -> None:
    report = QualityReport(**_valid_quality_report())
    assert report.pii_detected is False


@pytest.mark.parametrize(
    "field",
    ["extraction_quality", "readability", "structure_score", "topic_coverage", "relevance_score", "metadata_quality"],
)
def test_quality_report_scores_are_bounded_between_zero_and_one(field: str) -> None:
    with pytest.raises(ValidationError):
        QualityReport(**_valid_quality_report(**{field: 1.2}))


# --- IngestionRun ---


def _valid_ingestion_run(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "run_id": uuid.uuid4(),
        "scope": ResourceScope(**_valid_scope()),
        "profile_version": "1.0",
        "trigger": "scheduled",
    }
    base.update(overrides)
    return base


def test_ingestion_run_defaults_are_safe() -> None:
    run = IngestionRun(**_valid_ingestion_run())
    assert run.mode == "auto_stage"
    assert run.status == "planned"
    assert run.resources_retrieval_eligible == 0
    assert run.errors == []


def test_ingestion_run_run_id_is_a_uuid_not_a_hash() -> None:
    run = IngestionRun(**_valid_ingestion_run())
    assert isinstance(run.run_id, uuid.UUID)


def test_ingestion_run_has_no_published_counter() -> None:
    """Aucune notion de publication n'existe : le compteur s'arrête à
    resources_retrieval_eligible, jamais resources_published."""
    assert "resources_published" not in IngestionRun.model_fields
    assert "resources_retrieval_eligible" in IngestionRun.model_fields


def test_ingestion_run_rejects_finished_before_started() -> None:
    with pytest.raises(ValidationError):
        IngestionRun(**_valid_ingestion_run(
            started_at=NOW,
            finished_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        ))


def test_ingestion_run_mode_is_locked_to_auto_stage() -> None:
    with pytest.raises(ValidationError):
        IngestionRun(**_valid_ingestion_run(mode="trusted_auto_publish"))


# --- CoverageSnapshot ---


def _valid_coverage_snapshot(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "snapshot_id": uuid.uuid4(),
        "scope": ResourceScope(**_valid_scope()),
        "period_start": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "period_end": NOW,
        "expected_topics": ["algorithmique", "structures_de_donnees"],
    }
    base.update(overrides)
    return base


def test_coverage_snapshot_valid_construction() -> None:
    snapshot = CoverageSnapshot(**_valid_coverage_snapshot())
    assert snapshot.covered_topics == []


def test_coverage_snapshot_rejects_period_end_before_period_start() -> None:
    with pytest.raises(ValidationError):
        CoverageSnapshot(**_valid_coverage_snapshot(
            period_start=NOW,
            period_end=datetime(2026, 8, 1, tzinfo=timezone.utc),
        ))


def test_coverage_snapshot_requires_at_least_one_expected_topic() -> None:
    with pytest.raises(ValidationError):
        CoverageSnapshot(**_valid_coverage_snapshot(expected_topics=[]))


# --- Invariant transversal : aucun de ces modèles ne porte de champ "published" ---


@pytest.mark.parametrize(
    "model",
    [
        CollectionProfile, SearchPlan, ResourceCandidate, ArtifactRecord,
        RoutingDecision, QualityReport, IngestionRun, CoverageSnapshot,
    ],
)
def test_no_canonical_model_exposes_a_published_field(model: type) -> None:
    field_names = set(model.model_fields)
    assert not any("published" in name for name in field_names), (
        f"{model.__name__} ne doit porter aucune notion de publication (LOT44a)"
    )
