"""H2-F (défaut 6) — dérivation et digest canonique de l'attribution.

Ce fichier ne teste que ce qui est démontrable sans base : la dérivation
depuis le candidat/profil gouvernés, la forme canonique du digest, et les
refus de valeurs hors contrat. **Tout** ce qui concerne l'écriture, les
rôles PostgreSQL, le scellement après attestation et la publication est
prouvé sur une base réelle par
``tests/integration/test_h2f_artifact_attribution_pg.py`` — aucun double de
test n'y remplace la base.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from nexus_contracts.ingestion import CollectionProfile, ResourceCandidate, ResourceScope

from ingestor.ingestion_control.artifact_attribution import (
    ATTRIBUTION_PROTOCOL_VERSION,
    ArtifactAttribution,
    ArtifactAttributionError,
    attribution_digest,
    derive_artifact_attribution,
)

ARTIFACT_ID = UUID("11111111-1111-1111-1111-111111111111")

SCOPE: dict[str, Any] = {
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


def _profile(**overrides: Any) -> CollectionProfile:
    document: dict[str, Any] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": SCOPE,
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
        "min_extraction_quality": 0.1,
    }
    document.update(overrides)
    return CollectionProfile.model_validate(document)


def _candidate(**overrides: Any) -> ResourceCandidate:
    document: dict[str, Any] = {
        "candidate_id": uuid4(),
        "resource_id": uuid4(),
        "run_id": uuid4(),
        "scope": SCOPE,
        "discovered_at": datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        "source_url": "https://eduscol.education.fr/nsi/algo",
        "canonical_url": "https://eduscol.education.fr/nsi/algo",
        "domain": "eduscol.education.fr",
        "proposed_type_doc": "cours",
        "dedup_key": hashlib.sha256(b"algo").hexdigest(),
    }
    document.update(overrides)
    return ResourceCandidate.model_validate(document)


class TestCanonicalDigest:
    def test_digest_is_length_prefixed_and_reproducible(self) -> None:
        expected_document = "|".join(
            (
                ATTRIBUTION_PROTOCOL_VERSION,
                f"{len(str(ARTIFACT_ID))}:{ARTIFACT_ID}",
                "7:Éduscol",  # longueur en CARACTÈRES, comme length() côté SQL
                "4:true",
                "20:eduscol.education.fr",
                "5:cours",
            )
        )
        assert attribution_digest(
            ingestion_artifact_id=ARTIFACT_ID,
            source_label="Éduscol",
            official=True,
            source_kind="eduscol.education.fr",
            type_doc="cours",
        ) == hashlib.sha256(expected_document.encode("utf-8")).hexdigest()

    def test_separator_inside_a_value_cannot_forge_another_document(self) -> None:
        """Le préfixe de longueur est ce qui rend deux découpages
        différents impossibles à confondre : sans lui, ``a|b`` et ``a``+``b``
        produiraient le même digest."""
        first = attribution_digest(
            ingestion_artifact_id=ARTIFACT_ID,
            source_label="a|4:true|1:b",
            official=True,
            source_kind="x",
            type_doc="cours",
        )
        second = attribution_digest(
            ingestion_artifact_id=ARTIFACT_ID,
            source_label="a",
            official=True,
            source_kind="b",
            type_doc="cours",
        )
        assert first != second

    def test_digest_is_bound_to_its_ingestion_artifact(self) -> None:
        common = {
            "source_label": "Éduscol",
            "official": True,
            "source_kind": "eduscol.education.fr",
            "type_doc": "cours",
        }
        assert attribution_digest(ingestion_artifact_id=ARTIFACT_ID, **common) != (
            attribution_digest(ingestion_artifact_id=uuid4(), **common)
        )

    @pytest.mark.parametrize(
        "override",
        (
            {"source_label": "Autre"},
            {"official": False},
            {"source_kind": "example.org"},
            {"type_doc": "annale"},
        ),
    )
    def test_every_fact_changes_the_digest(self, override: dict[str, Any]) -> None:
        base = {
            "ingestion_artifact_id": ARTIFACT_ID,
            "source_label": "Éduscol",
            "official": True,
            "source_kind": "eduscol.education.fr",
            "type_doc": "cours",
        }
        assert attribution_digest(**base) != attribution_digest(**{**base, **override})


class TestDerivation:
    def test_derives_the_four_facts_from_governed_inputs(self) -> None:
        attribution = derive_artifact_attribution(
            ingestion_artifact_id=ARTIFACT_ID,
            candidate=_candidate(),
            profile=_profile(),
        )
        assert attribution.source_label == "eduscol.education.fr"
        assert attribution.official is True
        assert attribution.source_kind == "eduscol.education.fr"
        assert attribution.type_doc == "cours"

    def test_publisher_declared_by_scout_wins_as_source_label(self) -> None:
        attribution = derive_artifact_attribution(
            ingestion_artifact_id=ARTIFACT_ID,
            candidate=_candidate(publisher="Ministère de l'Éducation nationale"),
            profile=_profile(),
        )
        assert attribution.source_label == "Ministère de l'Éducation nationale"

    @pytest.mark.parametrize(
        ("authority", "expected"),
        (("official", True), ("authorized", False), ("unknown", False)),
    )
    def test_official_mirrors_the_profile_source_authority(
        self, authority: str, expected: bool
    ) -> None:
        """Exactement le fait de profil que ``assess_rights_core`` consomme
        — jamais une seconde interprétation parallèle de l'autorité."""
        attribution = derive_artifact_attribution(
            ingestion_artifact_id=ARTIFACT_ID,
            candidate=_candidate(),
            profile=_profile(source_authority=authority),
        )
        assert attribution.official is expected

    def test_type_doc_outside_the_profile_perimeter_is_refused(self) -> None:
        with pytest.raises(ArtifactAttributionError, match="expected by profile"):
            derive_artifact_attribution(
                ingestion_artifact_id=ARTIFACT_ID,
                candidate=_candidate(proposed_type_doc="annale"),
                profile=_profile(expected_resource_types=["cours"]),
            )


class TestContractRefusals:
    def test_published_artifact_id_is_never_accepted_as_the_key(self) -> None:
        """Le ``artifact_id`` produit est le SHA-256 du contenu ; le
        confondre avec l'UUID d'ingestion était le second défaut de la
        version initiale de ce lot."""
        with pytest.raises(ArtifactAttributionError, match="UUID"):
            ArtifactAttribution(
                ingestion_artifact_id="a" * 64,  # type: ignore[arg-type]
                source_label="Éduscol",
                official=True,
                source_kind="eduscol.education.fr",
                type_doc="cours",
            )

    @pytest.mark.parametrize("field", ("source_label", "source_kind", "type_doc"))
    @pytest.mark.parametrize("blank", ("", "   "))
    def test_blank_strings_are_refused(self, field: str, blank: str) -> None:
        values = {
            "source_label": "Éduscol",
            "source_kind": "eduscol.education.fr",
            "type_doc": "cours",
        }
        values[field] = blank
        with pytest.raises(ArtifactAttributionError, match=field):
            ArtifactAttribution(
                ingestion_artifact_id=ARTIFACT_ID, official=True, **values
            )

    def test_type_doc_outside_the_contract_vocabulary_is_refused(self) -> None:
        with pytest.raises(ArtifactAttributionError, match="canonical TypeDoc"):
            ArtifactAttribution(
                ingestion_artifact_id=ARTIFACT_ID,
                source_label="Éduscol",
                official=True,
                source_kind="eduscol.education.fr",
                type_doc="programme",
            )

    def test_non_boolean_official_is_refused(self) -> None:
        with pytest.raises(ArtifactAttributionError, match="boolean"):
            ArtifactAttribution(
                ingestion_artifact_id=ARTIFACT_ID,
                source_label="Éduscol",
                official=1,  # type: ignore[arg-type]
                source_kind="eduscol.education.fr",
                type_doc="cours",
            )

    def test_over_long_source_label_is_refused_before_the_database(self) -> None:
        with pytest.raises(ArtifactAttributionError, match="512-character"):
            ArtifactAttribution(
                ingestion_artifact_id=ARTIFACT_ID,
                source_label="x" * 513,
                official=True,
                source_kind="eduscol.education.fr",
                type_doc="cours",
            )


def test_scope_is_declared_by_the_candidate_not_by_this_module() -> None:
    """Garde-fou de périmètre : la dérivation ne lit jamais le scope pour
    en déduire une attribution — deux ressources du même scope peuvent
    parfaitement avoir des attributions différentes."""
    scope = ResourceScope.model_validate(SCOPE)
    first = derive_artifact_attribution(
        ingestion_artifact_id=ARTIFACT_ID,
        candidate=_candidate(scope=scope.model_dump(mode="json"), domain="eduscol.education.fr"),
        profile=_profile(allowed_domains=["eduscol.education.fr", "example.org"]),
    )
    second = derive_artifact_attribution(
        ingestion_artifact_id=ARTIFACT_ID,
        candidate=_candidate(
            scope=scope.model_dump(mode="json"),
            domain="example.org",
            source_url="https://example.org/a",
            canonical_url="https://example.org/a",
        ),
        profile=_profile(allowed_domains=["eduscol.education.fr", "example.org"]),
    )
    assert first.source_kind != second.source_kind
    assert first.digest != second.digest
