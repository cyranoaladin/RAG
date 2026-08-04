"""LOT44d : RightsAgent — détermination déterministe des droits.

Périmètre strict : cœur pur testé sans E/S ; ``run_rights_agent`` testé
avec ``apply_resource_transition`` monkeypatché — aucun PostgreSQL réel.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ArtifactRecord, CollectionProfile
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents import rights_agent as rights_agent_module
from ingestor.ingestion_agents.rights_agent import (
    UnknownRightsRejectedError,
    assess_rights_core,
    run_rights_agent,
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
        "expected_topics": ["algorithmique"],
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
    }
    payload.update(overrides)
    return ArtifactRecord.model_validate(payload)


class TestAssessRightsCore:
    def test_no_license_is_always_unknown_regardless_of_authority(self) -> None:
        with pytest.raises(UnknownRightsRejectedError):
            assess_rights_core(
                artifact=_artifact(license=None),
                profile=_profile(source_authority="official"),
            )

    def test_official_authority_with_license_yields_officiel_public(self) -> None:
        rights = assess_rights_core(
            artifact=_artifact(license="CC-BY-SA"),
            profile=_profile(source_authority="official"),
        )
        assert rights == Rights.officiel_public

    def test_authorized_authority_with_license_yields_public_allowed(self) -> None:
        rights = assess_rights_core(
            artifact=_artifact(license="CC-BY-SA"),
            profile=_profile(source_authority="authorized"),
        )
        assert rights == Rights.public_allowed

    def test_unknown_authority_with_license_is_rejected_when_profile_requires_it(self) -> None:
        with pytest.raises(UnknownRightsRejectedError):
            assess_rights_core(
                artifact=_artifact(license="CC-BY-SA"),
                profile=_profile(source_authority="unknown", reject_unknown_rights=True),
            )

    def test_unknown_rights_are_returned_when_profile_allows_it(self) -> None:
        rights = assess_rights_core(
            artifact=_artifact(license="CC-BY-SA"),
            profile=_profile(source_authority="unknown", reject_unknown_rights=False),
        )
        assert rights == Rights.unknown


class TestRunRightsAgentWiring:
    def test_transitions_classified_to_rights_checked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        artifact = _artifact(license="CC-BY-SA")
        fake_transition = TransitionResult(
            resource_id=artifact.resource_id,
            from_state=ResourceState.CLASSIFIED,
            to_state=ResourceState.RIGHTS_CHECKED,
            state_version=6,
        )
        mock_apply = MagicMock(return_value=fake_transition)
        monkeypatch.setattr(rights_agent_module, "apply_resource_transition", mock_apply)

        rights, transition = run_rights_agent(
            conn=MagicMock(),
            artifact=artifact,
            profile=_profile(source_authority="official"),
            expected_version=5,
            actor="rights-test",
        )

        assert rights == Rights.officiel_public
        assert transition is fake_transition
        kwargs = mock_apply.call_args.kwargs
        assert kwargs["expected_state"] == ResourceState.CLASSIFIED
        assert kwargs["new_state"] == ResourceState.RIGHTS_CHECKED

    def test_rejection_happens_before_any_transition_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_apply = MagicMock()
        monkeypatch.setattr(rights_agent_module, "apply_resource_transition", mock_apply)

        with pytest.raises(UnknownRightsRejectedError):
            run_rights_agent(
                conn=MagicMock(),
                artifact=_artifact(license=None),
                profile=_profile(),
                expected_version=5,
                actor="rights-test",
            )
        mock_apply.assert_not_called()
