"""LOT44c : vérifications contractuelles — aucun conflit avec LOT44a.

Périmètre strict : vérifie que LOT44c réutilise les contrats canoniques
LOT44a sans les modifier, n'introduit aucun état de ressource
supplémentaire, et que ses propres types n'entrent en collision avec rien
d'existant.
"""
from __future__ import annotations

import inspect
import math
import typing
from uuid import UUID

import pytest
from nexus_contracts.ingestion import CollectionProfile, PublicationPolicy, ResourceScope
from nexus_contracts.resource_state import NORMAL_SEQUENCE, ResourceState

from ingestor.ingestion_profiles.events import (
    PROFILE_VALIDATION_EVENT_TYPE,
    canonical_json_bytes,
    record_validation_result,
)
from ingestor.ingestion_profiles.validation import (
    SCOPE_DIMENSIONS,
    ValidationIssue,
    ValidationResult,
)


class TestCollectionProfileUnmodified:
    def test_collection_profile_has_no_new_required_field(self) -> None:
        """LOT44c ne modifie jamais CollectionProfile — vérifié en
        confirmant que les champs obligatoires connus de LOT44a sont
        exactement ceux attendus, aucun de plus."""
        required = {
            name
            for name, field in CollectionProfile.model_fields.items()
            if field.is_required()
        }
        assert required == {
            "profile_version",
            "enabled",
            "scope",
            "title",
            "owner",
            "expected_topics",
            "expected_resource_types",
            "allowed_domains",
            "source_authority",
            "search_cadence",
            "max_queries_per_run",
            "max_documents_per_run",
            "max_chunk_size",
            "chunk_overlap",
            "min_source_confidence",
            "min_scope_confidence",
            "min_extraction_quality",
        }

    def test_publication_policy_still_locked_to_false(self) -> None:
        assert PublicationPolicy().auto_publish is False

    def test_resource_scope_still_has_exactly_ten_dimensions(self) -> None:
        assert set(ResourceScope.model_fields.keys()) == set(SCOPE_DIMENSIONS)


class TestNoResourceStateConflict:
    def test_resource_state_still_has_exactly_twenty_values(self) -> None:
        assert len(list(ResourceState)) == 20

    def test_published_still_absent_from_resource_state(self) -> None:
        assert "PUBLISHED" not in {state.value for state in ResourceState}

    def test_candidate_and_staged_still_separated_by_seven_states(self) -> None:
        candidate_index = NORMAL_SEQUENCE.index(ResourceState.CANDIDATE)
        staged_index = NORMAL_SEQUENCE.index(ResourceState.STAGED)
        assert staged_index - candidate_index == 8  # 7 états intermédiaires

    def test_reviewed_and_retrieval_eligible_remain_distinct(self) -> None:
        assert ResourceState.REVIEWED != ResourceState.RETRIEVAL_ELIGIBLE


class TestValidationResultTypedAndDistinct:
    def test_validation_result_is_not_a_resource_state(self) -> None:
        assert not issubclass(ValidationResult, ResourceState)

    def test_validation_issue_uses_stable_code_not_only_free_text(self) -> None:
        issue = ValidationIssue(code="SCOPE_DIMENSION_MISMATCH", path="niveau", message="x")
        assert issue.code == "SCOPE_DIMENSION_MISMATCH"

    def test_profile_validation_event_type_does_not_collide_with_transition(self) -> None:
        assert PROFILE_VALIDATION_EVENT_TYPE == "profile_validation"
        assert PROFILE_VALIDATION_EVENT_TYPE != "transition"


class TestIdentifiersAreUuidWhereExpectedByEvents:
    def test_record_validation_result_requires_uuid_run_id(self) -> None:
        hints = typing.get_type_hints(record_validation_result)
        assert hints["run_id"] is UUID

    def test_record_validation_result_never_accepts_job_id(self) -> None:
        """LOT44c ne fournit jamais job_id — cohérent avec ADR-0027 (aucun
        producteur automatique en dehors d'un futur contrat IngestionJob)."""
        signature = inspect.signature(record_validation_result)
        assert "job_id" not in signature.parameters


class TestCanonicalJsonBytes:
    """Preuve que la sérialisation utilisée pour mesurer la taille du
    payload est réellement canonique (pas seulement déterministe par
    accident de l'ordre d'insertion du dict)."""

    def test_key_order_independent(self) -> None:
        a = {"z": 1, "a": 2}
        b = {"a": 2, "z": 1}
        assert canonical_json_bytes(a) == canonical_json_bytes(b)

    def test_no_extraneous_whitespace(self) -> None:
        assert canonical_json_bytes({"a": 1}) == b'{"a":1}'

    def test_non_ascii_is_escaped(self) -> None:
        result = canonical_json_bytes({"a": "é"})
        assert result == b'{"a":"\\u00e9"}'
        assert all(byte < 128 for byte in result)

    def test_nan_is_rejected_not_silently_serialized(self) -> None:
        with pytest.raises(ValueError):
            canonical_json_bytes({"a": math.nan})

    def test_infinity_is_rejected_not_silently_serialized(self) -> None:
        with pytest.raises(ValueError):
            canonical_json_bytes({"a": math.inf})

    def test_deterministic_across_repeated_calls(self) -> None:
        payload = {"status": "passed", "issues": [], "collection": "c", "profile_version": "v1"}
        assert canonical_json_bytes(payload) == canonical_json_bytes(payload)


class TestPublicApiStability:
    def test_public_symbols_are_exported(self) -> None:
        import ingestor.ingestion_profiles as pkg

        for name in (
            "load_profile_registry",
            "select_profile",
            "validate_scope_against_profile",
            "record_validation_result",
            "ValidationResult",
            "ValidationIssue",
        ):
            assert hasattr(pkg, name)
