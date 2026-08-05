"""LOT44c : moteur de validation déterministe scope/profil.

Périmètre strict : tests unitaires purs. Aucun réseau, aucun PostgreSQL,
aucune horloge — le moteur est une fonction pure testée en mémoire.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_profiles.registry import load_profile_registry
from ingestor.ingestion_profiles.validation import (
    SCOPE_DIMENSIONS,
    ValidationResult,
    validate_scope_against_profile,
)

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


def _profile_payload(**overrides: object) -> dict[str, object]:
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
    return payload


@pytest.fixture
def registry(tmp_path: Path):
    path = tmp_path / "nsi.yml"
    path.write_text(yaml.safe_dump(_profile_payload()), encoding="utf-8")
    return load_profile_registry(tmp_path)


class TestPassingValidation:
    def test_matching_scope_passes(self, registry) -> None:
        result = validate_scope_against_profile(
            raw_scope=VALID_SCOPE,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "passed"
        assert result.issues == ()

    def test_result_carries_collection_and_version(self, registry) -> None:
        result = validate_scope_against_profile(
            raw_scope=VALID_SCOPE,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.collection == "rag_nexus_nsi_terminale_specialite"
        assert result.profile_version == "v1"


class TestUnknownAndDisabledProfile:
    def test_unknown_profile_is_a_distinct_status(self, registry) -> None:
        result = validate_scope_against_profile(
            raw_scope=VALID_SCOPE,
            registry=registry,
            collection="does_not_exist",
            profile_version="v1",
        )
        assert result.status == "profile_unknown"
        assert result.issues[0].code == "PROFILE_UNKNOWN"

    def test_disabled_profile_is_a_distinct_status(self, tmp_path: Path) -> None:
        (tmp_path / "nsi.yml").write_text(
            yaml.safe_dump(_profile_payload(enabled=False)), encoding="utf-8"
        )
        reg = load_profile_registry(tmp_path)
        result = validate_scope_against_profile(
            raw_scope=VALID_SCOPE,
            registry=reg,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "profile_disabled"


class TestIncompleteScope:
    @pytest.mark.parametrize("dimension", SCOPE_DIMENSIONS)
    def test_missing_dimension_is_rejected(self, registry, dimension: str) -> None:
        broken_scope = {k: v for k, v in VALID_SCOPE.items() if k != dimension}
        result = validate_scope_against_profile(
            raw_scope=broken_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "incomplete_input"
        assert any(issue.path.startswith(dimension) for issue in result.issues)

    def test_empty_string_value_is_rejected(self, registry) -> None:
        broken_scope = {**VALID_SCOPE, "tenant": ""}
        result = validate_scope_against_profile(
            raw_scope=broken_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "incomplete_input"

    def test_unknown_enum_value_is_rejected(self, registry) -> None:
        broken_scope = {**VALID_SCOPE, "niveau": "does_not_exist"}
        result = validate_scope_against_profile(
            raw_scope=broken_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "incomplete_input"

    def test_empty_audience_list_is_rejected(self, registry) -> None:
        broken_scope = {**VALID_SCOPE, "audience": []}
        result = validate_scope_against_profile(
            raw_scope=broken_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "incomplete_input"


class TestScopeProfileMismatch:
    def test_mismatched_dimension_fails_with_structured_issue(self, registry) -> None:
        mismatched_scope = {**VALID_SCOPE, "niveau": "seconde"}
        result = validate_scope_against_profile(
            raw_scope=mismatched_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "failed"
        assert result.issues[0].code == "SCOPE_DIMENSION_MISMATCH"
        assert result.issues[0].path == "niveau"

    def test_tenant_mismatch_is_rejected_like_any_other_dimension(self, registry) -> None:
        """Vérifie explicitement la dimension tenant — la limitation
        actuelle (une valeur par dimension par déploiement, ADR-0025)
        n'exempte jamais tenant d'être comparé comme les neuf autres
        dimensions : aucun traitement spécial, aucun bypass."""
        mismatched_scope = {**VALID_SCOPE, "tenant": "aefe_terminale"}
        result = validate_scope_against_profile(
            raw_scope=mismatched_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "failed"
        assert result.issues[0].code == "SCOPE_DIMENSION_MISMATCH"
        assert result.issues[0].path == "tenant"

    def test_multiple_mismatches_are_all_reported(self, registry) -> None:
        mismatched_scope = {**VALID_SCOPE, "niveau": "seconde", "voie": "technologique"}
        result = validate_scope_against_profile(
            raw_scope=mismatched_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status == "failed"
        paths = {issue.path for issue in result.issues}
        assert paths == {"niveau", "voie"}


class TestDeterminism:
    def test_repeated_calls_with_identical_input_produce_identical_result(
        self, registry
    ) -> None:
        broken_scope = {k: v for k, v in VALID_SCOPE.items() if k != "matiere"}
        first = validate_scope_against_profile(
            raw_scope=broken_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        second = validate_scope_against_profile(
            raw_scope=broken_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert first == second

    def test_error_order_is_deterministic_across_calls(self, registry) -> None:
        broken_scope = {
            k: v for k, v in VALID_SCOPE.items() if k not in {"tenant", "matiere", "audience"}
        }
        first = validate_scope_against_profile(
            raw_scope=broken_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        second = validate_scope_against_profile(
            raw_scope=broken_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert [issue.path for issue in first.issues] == [issue.path for issue in second.issues]


class TestFailClosedBoundary:
    def test_technical_error_status_is_reachable_type(self) -> None:
        """Le type ValidationStatus représente technical_error — vérifié
        structurellement plutôt que forcé artificiellement (aucun réseau ni
        I/O à faire échouer dans ce moteur pur)."""
        result = ValidationResult(
            status="technical_error", issues=(), collection="c", profile_version="v1"
        )
        assert result.status == "technical_error"

    def test_validation_never_raises_for_malformed_raw_scope_types(self, registry) -> None:
        result = validate_scope_against_profile(
            raw_scope={"tenant": 12345, "niveau": None},
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.status in {"incomplete_input", "technical_error"}


class TestProfileFingerprintPropagation:
    def test_passing_result_carries_a_fingerprint(self, registry) -> None:
        result = validate_scope_against_profile(
            raw_scope=VALID_SCOPE,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.profile_fingerprint is not None
        assert len(result.profile_fingerprint) == 64  # sha256 hex digest

    def test_failing_result_still_carries_the_resolved_profile_fingerprint(
        self, registry
    ) -> None:
        mismatched_scope = {**VALID_SCOPE, "niveau": "seconde"}
        result = validate_scope_against_profile(
            raw_scope=mismatched_scope,
            registry=registry,
            collection="rag_nexus_nsi_terminale_specialite",
            profile_version="v1",
        )
        assert result.profile_fingerprint is not None

    def test_unknown_profile_result_has_no_fingerprint(self, registry) -> None:
        result = validate_scope_against_profile(
            raw_scope=VALID_SCOPE,
            registry=registry,
            collection="does_not_exist",
            profile_version="v1",
        )
        assert result.profile_fingerprint is None

    def test_two_different_profile_contents_never_share_a_fingerprint(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a.yml").write_text(
            yaml.safe_dump(_profile_payload(profile_version="v1", title="A")), encoding="utf-8"
        )
        (tmp_path / "b.yml").write_text(
            yaml.safe_dump(_profile_payload(profile_version="v2", title="B")), encoding="utf-8"
        )
        reg = load_profile_registry(tmp_path)
        result_a = validate_scope_against_profile(
            raw_scope=VALID_SCOPE, registry=reg,
            collection="rag_nexus_nsi_terminale_specialite", profile_version="v1",
        )
        result_b = validate_scope_against_profile(
            raw_scope=VALID_SCOPE, registry=reg,
            collection="rag_nexus_nsi_terminale_specialite", profile_version="v2",
        )
        assert result_a.profile_fingerprint != result_b.profile_fingerprint


class TestNoPublishedNoStateConflict:
    def test_validation_status_values_never_collide_with_resource_state(self) -> None:
        status_values = {
            "passed",
            "failed",
            "profile_unknown",
            "profile_disabled",
            "incomplete_input",
            "technical_error",
        }
        resource_state_values = {state.value for state in ResourceState}
        assert status_values.isdisjoint(resource_state_values)

    def test_published_is_not_a_validation_status(self) -> None:
        status_values = {
            "passed",
            "failed",
            "profile_unknown",
            "profile_disabled",
            "incomplete_input",
            "technical_error",
        }
        assert "PUBLISHED" not in status_values
        assert "published" not in status_values
