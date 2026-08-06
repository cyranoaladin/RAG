"""LOT44d : QualityAgent — QualityReport réel + RoutingDecision calculée non persistée.

Périmètre strict : cœurs purs testés sans E/S ; ``run_quality_agent`` testé
avec ``apply_resource_transition`` monkeypatché — aucun PostgreSQL réel.

Point de gouvernance central de ce fichier : prouver que
``QUALITY_CHECKED -> ROUTED`` n'est **jamais** appliquée — un seul appel de
transition, quel que soit le contenu de la ``RoutingDecision`` calculée.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ArtifactRecord, CollectionProfile
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents import quality_agent as quality_agent_module
from ingestor.ingestion_agents.classifier import ConformityResult
from ingestor.ingestion_agents.quality_agent import (
    build_quality_report_core,
    decide_routing_core,
    run_quality_agent,
)
from ingestor.ingestion_agents.transitions import TransitionResult

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
        "expected_topics": ["algorithmique", "récursivité"],
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
        "min_extraction_quality": 0.1,
    }
    payload.update(overrides)
    return CollectionProfile.model_validate(payload)


def _artifact(**overrides: object) -> ArtifactRecord:
    payload: dict[str, object] = {
        "artifact_id": uuid4(),
        "resource_id": uuid4(),
        "run_id": uuid4(),
        "scope": VALID_SCOPE,
        "sha256": "a" * 64,
        "size_bytes": 100,
        "mime_declared": "text/html",
        "mime_detected": "text/html",
        "original_url": "https://eduscol.education.fr/nsi/algo",
        "final_url": "https://eduscol.education.fr/nsi/algo",
        "collected_at": datetime(2026, 8, 4, tzinfo=UTC),
        "domain": "eduscol.education.fr",
        "rights_status": "unknown",
        "title": "Algorithmique",
        "publisher": "Eduscol",
        "license": "CC-BY-SA",
    }
    payload.update(overrides)
    return ArtifactRecord.model_validate(payload)


_CONFORMITY_OK = ConformityResult(
    niveau_conformity=True,
    voie_conformity=True,
    matiere_conformity=True,
    programme_conformity=True,
    matiere_evidence=("algorithmique", "récursivité"),
)


class TestBuildQualityReportCore:
    def test_topic_coverage_reflects_fraction_of_expected_topics_found(self) -> None:
        report = build_quality_report_core(
            artifact=_artifact(),
            profile=_profile(),
            conformity=_CONFORMITY_OK,
            rights=Rights.officiel_public,
            extracted_text="algorithmique et récursivité sont au programme. " * 20,
            declared_language="fr",
            pii_detected=False,
            duplicate_detected=False,
            report_id=uuid4(),
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert report.topic_coverage == 1.0
        assert report.rejection_reasons == []

    def test_rejection_reasons_accumulate_deterministically(self) -> None:
        conformity_fail = ConformityResult(
            niveau_conformity=True,
            voie_conformity=True,
            matiere_conformity=False,
            programme_conformity=True,
            matiere_evidence=(),
        )
        report = build_quality_report_core(
            artifact=_artifact(),
            profile=_profile(min_extraction_quality=0.99),
            conformity=conformity_fail,
            rights=Rights.unknown,
            extracted_text="court",
            declared_language="fr",
            pii_detected=True,
            duplicate_detected=True,
            report_id=uuid4(),
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert report.rejection_reasons == [
            "extraction_quality_below_threshold",
            "matiere_conformity_failed",
            "rights_unknown",
            "pii_detected",
            "duplicate_detected",
        ]

    def test_unknown_rights_is_not_rejected_when_profile_allows_it(self) -> None:
        """Revue PR#90 (Cubic P2) : ``reject_unknown_rights=False`` doit
        réellement être honoré par QualityAgent, pas seulement par
        RightsAgent en amont — avant ce correctif, ``rights_unknown``
        était ajouté sans condition, contredisant silencieusement un
        profil qui autorise explicitement ce cas."""
        report = build_quality_report_core(
            artifact=_artifact(),
            profile=_profile(reject_unknown_rights=False),
            conformity=_CONFORMITY_OK,
            rights=Rights.unknown,
            extracted_text="algorithmique et récursivité sont au programme. " * 20,
            declared_language="fr",
            pii_detected=False,
            duplicate_detected=False,
            report_id=uuid4(),
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert "rights_unknown" not in report.rejection_reasons

    def test_unknown_rights_is_still_rejected_when_profile_requires_it(self) -> None:
        report = build_quality_report_core(
            artifact=_artifact(),
            profile=_profile(reject_unknown_rights=True),
            conformity=_CONFORMITY_OK,
            rights=Rights.unknown,
            extracted_text="algorithmique et récursivité sont au programme. " * 20,
            declared_language="fr",
            pii_detected=False,
            duplicate_detected=False,
            report_id=uuid4(),
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert "rights_unknown" in report.rejection_reasons

    def test_metadata_quality_measures_actual_field_completeness(self) -> None:
        full_metadata = _artifact(
            title="Algorithmique", publisher="Eduscol", license="CC-BY-SA",
            pages_count=10, version="1",
        )
        empty_metadata = _artifact(title=None, publisher=None, license=None)
        report_full = build_quality_report_core(
            artifact=full_metadata, profile=_profile(), conformity=_CONFORMITY_OK,
            rights=Rights.officiel_public, extracted_text="algorithmique",
            declared_language="fr", pii_detected=False, duplicate_detected=False,
            report_id=uuid4(), evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        report_empty = build_quality_report_core(
            artifact=empty_metadata, profile=_profile(), conformity=_CONFORMITY_OK,
            rights=Rights.officiel_public, extracted_text="algorithmique",
            declared_language="fr", pii_detected=False, duplicate_detected=False,
            report_id=uuid4(), evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert report_full.metadata_quality == 1.0
        assert report_empty.metadata_quality < report_full.metadata_quality


class TestDecideRoutingCore:
    def test_duplicate_takes_priority_over_everything(self) -> None:
        report = build_quality_report_core(
            artifact=_artifact(), profile=_profile(), conformity=_CONFORMITY_OK,
            rights=Rights.officiel_public, extracted_text="algorithmique",
            declared_language="fr", pii_detected=True, duplicate_detected=True,
            report_id=uuid4(), evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        decision = decide_routing_core(
            quality_report=report, profile=_profile(), decision_id=uuid4(),
            decided_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert decision.decision == "DUPLICATE"

    def test_clean_report_routes(self) -> None:
        report = build_quality_report_core(
            artifact=_artifact(), profile=_profile(), conformity=_CONFORMITY_OK,
            rights=Rights.officiel_public,
            extracted_text="algorithmique et récursivité sont au programme. " * 20,
            declared_language="fr", pii_detected=False, duplicate_detected=False,
            report_id=uuid4(), evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        decision = decide_routing_core(
            quality_report=report, profile=_profile(), decision_id=uuid4(),
            decided_at=datetime(2026, 8, 4, tzinfo=UTC),
        )
        assert decision.decision == "ROUTE"
        assert decision.agent_identity == "QualityAgent"


class TestRunQualityAgentRoutedActivation:
    """LOT44f (ADR-0029) : QUALITY_CHECKED -> ROUTED est désormais appliquée,
    mais **uniquement** quand la RoutingDecision calculée vaut "ROUTE" —
    remplace l'ancienne classe TestRunQualityAgentNeverActivatesRouted
    (LOT44d, ADR-0029 Décision 3, changement intentionnel documenté)."""

    def test_non_route_decision_still_makes_exactly_one_transition_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artifact = _artifact()
        fake_transition = TransitionResult(
            resource_id=artifact.resource_id,
            from_state=ResourceState.RIGHTS_CHECKED,
            to_state=ResourceState.QUALITY_CHECKED,
            state_version=7,
        )
        mock_apply = MagicMock(return_value=fake_transition)
        monkeypatch.setattr(quality_agent_module, "apply_resource_transition", mock_apply)

        quality_report, routing_decision, transition = run_quality_agent(
            conn=MagicMock(),
            artifact=artifact,
            profile=_profile(),
            conformity=_CONFORMITY_OK,
            rights=Rights.officiel_public,
            extracted_text="algorithmique et récursivité sont au programme. " * 20,
            declared_language="fr",
            pii_detected=True,
            duplicate_detected=True,
            report_id=uuid4(),
            decision_id=uuid4(),
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
            expected_version=6,
            actor="quality-test",
        )

        assert mock_apply.call_count == 1, "DUPLICATE ne doit jamais déclencher de seconde transition"
        called_kwargs = mock_apply.call_args.kwargs
        assert called_kwargs["expected_state"] == ResourceState.RIGHTS_CHECKED
        assert called_kwargs["new_state"] == ResourceState.QUALITY_CHECKED
        assert transition is fake_transition
        assert routing_decision.decision == "DUPLICATE"
        assert quality_report.duplicate_detected is True

    def test_route_decision_makes_a_second_transition_to_routed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artifact = _artifact()
        first_transition = TransitionResult(
            resource_id=artifact.resource_id, from_state=ResourceState.RIGHTS_CHECKED,
            to_state=ResourceState.QUALITY_CHECKED, state_version=7,
        )
        second_transition = TransitionResult(
            resource_id=artifact.resource_id, from_state=ResourceState.QUALITY_CHECKED,
            to_state=ResourceState.ROUTED, state_version=8,
        )
        mock_apply = MagicMock(side_effect=[first_transition, second_transition])
        monkeypatch.setattr(quality_agent_module, "apply_resource_transition", mock_apply)
        job_id = uuid4()

        quality_report, routing_decision, transition = run_quality_agent(
            conn=MagicMock(),
            artifact=artifact,
            profile=_profile(),
            conformity=_CONFORMITY_OK,
            rights=Rights.officiel_public,
            extracted_text="algorithmique et récursivité sont au programme. " * 20,
            declared_language="fr",
            pii_detected=False,
            duplicate_detected=False,
            report_id=uuid4(),
            decision_id=uuid4(),
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
            expected_version=6,
            actor="quality-test",
            job_id=job_id,
        )

        assert routing_decision.decision == "ROUTE"
        assert mock_apply.call_count == 2
        first_call_kwargs, second_call_kwargs = (c.kwargs for c in mock_apply.call_args_list)
        assert first_call_kwargs["expected_state"] == ResourceState.RIGHTS_CHECKED
        assert first_call_kwargs["new_state"] == ResourceState.QUALITY_CHECKED
        assert second_call_kwargs["expected_state"] == ResourceState.QUALITY_CHECKED
        assert second_call_kwargs["new_state"] == ResourceState.ROUTED
        # La seconde transition part de la version rendue par la première —
        # jamais une valeur devinée ou l'expected_version d'origine réutilisée.
        assert second_call_kwargs["expected_version"] == first_transition.state_version
        assert second_call_kwargs["job_id"] == job_id
        assert transition is second_transition, (
            "le TransitionResult retourné doit être le dernier appliqué (ROUTED), "
            "pas celui de QUALITY_CHECKED"
        )

    def test_non_route_decisions_never_target_routed_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        artifact = _artifact()
        mock_apply = MagicMock(
            return_value=TransitionResult(
                resource_id=artifact.resource_id,
                from_state=ResourceState.RIGHTS_CHECKED,
                to_state=ResourceState.QUALITY_CHECKED,
                state_version=7,
            )
        )
        monkeypatch.setattr(quality_agent_module, "apply_resource_transition", mock_apply)

        # rights=unknown -> rejection_reasons non vide -> decision == "REJECT"
        run_quality_agent(
            conn=MagicMock(),
            artifact=artifact,
            profile=_profile(),
            conformity=_CONFORMITY_OK,
            rights=Rights.unknown,
            extracted_text="algorithmique et récursivité sont au programme. " * 20,
            declared_language="fr",
            pii_detected=False,
            duplicate_detected=False,
            report_id=uuid4(),
            decision_id=uuid4(),
            evaluated_at=datetime(2026, 8, 4, tzinfo=UTC),
            expected_version=6,
            actor="quality-test",
        )

        all_new_states = [call.kwargs["new_state"] for call in mock_apply.call_args_list]
        assert ResourceState.ROUTED not in all_new_states
        assert mock_apply.call_count == 1
