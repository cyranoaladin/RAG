"""LOT44d : Classifier — conformité déterministe du texte extrait au profil.

Périmètre strict : cœur pur testé sans E/S ; ``run_classifier`` testé avec
``apply_resource_transition`` monkeypatché — aucun PostgreSQL réel.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from nexus_contracts.ingestion import CollectionProfile
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents import classifier as classifier_module
from ingestor.ingestion_agents.classifier import classify_conformity_core, run_classifier
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
        "min_extraction_quality": 0.6,
    }
    payload.update(overrides)
    return CollectionProfile.model_validate(payload)


class TestClassifyConformityCore:
    def test_matiere_conformity_true_when_topic_present(self) -> None:
        result = classify_conformity_core(
            extracted_text="Ce cours présente l'algorithmique de base.",
            profile=_profile(),
        )
        assert result.matiere_conformity is True
        assert result.matiere_evidence == ("algorithmique",)

    def test_matiere_conformity_false_when_no_topic_present(self) -> None:
        result = classify_conformity_core(
            extracted_text="Ce texte ne parle que de cuisine.",
            profile=_profile(),
        )
        assert result.matiere_conformity is False
        assert result.matiere_evidence == ()

    def test_case_insensitive_matching(self) -> None:
        result = classify_conformity_core(
            extracted_text="ALGORITHMIQUE avancée",
            profile=_profile(),
        )
        assert result.matiere_conformity is True

    def test_multiple_topics_are_all_reported(self) -> None:
        result = classify_conformity_core(
            extracted_text="algorithmique et récursivité au programme",
            profile=_profile(),
        )
        assert set(result.matiere_evidence) == {"algorithmique", "récursivité"}

    def test_niveau_voie_programme_conformity_are_structural_placeholders(self) -> None:
        result = classify_conformity_core(extracted_text="cuisine", profile=_profile())
        assert result.niveau_conformity is True
        assert result.voie_conformity is True
        assert result.programme_conformity is True


class TestRunClassifierWiring:
    def test_transitions_extracted_to_classified(self, monkeypatch: pytest.MonkeyPatch) -> None:
        resource_id = uuid4()
        run_id = uuid4()
        fake_transition = TransitionResult(
            resource_id=resource_id,
            from_state=ResourceState.EXTRACTED,
            to_state=ResourceState.CLASSIFIED,
            state_version=5,
        )
        mock_apply = MagicMock(return_value=fake_transition)
        monkeypatch.setattr(classifier_module, "apply_resource_transition", mock_apply)

        result, transition = run_classifier(
            conn=MagicMock(),
            resource_id=resource_id,
            run_id=run_id,
            extracted_text="algorithmique",
            profile=_profile(),
            expected_version=4,
            actor="classifier-test",
        )

        assert transition is fake_transition
        assert result.matiere_conformity is True
        kwargs = mock_apply.call_args.kwargs
        assert kwargs["expected_state"] == ResourceState.EXTRACTED
        assert kwargs["new_state"] == ResourceState.CLASSIFIED
        assert kwargs["resource_id"] == resource_id
        assert kwargs["run_id"] == run_id
