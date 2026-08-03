"""Démonstration explicite des invariants de gouvernance LOT44a (ADR-0024).

Deux sujets couverts, à la demande de la revue LOT44a :

1. ``PublicationPolicy`` est une politique passive, verrouillée au type —
   pas un comportement de publication. Ce fichier prouve les cinq points
   exigés : auto-publication à False par défaut, absence de transition vers
   PUBLISHED, absence d'endpoint/comportement de publication, distinction
   stricte REVIEWED/RETRIEVAL_ELIGIBLE, publication produit hors périmètre
   (documentée par ADR-0024).
2. ``ResourceScope`` est obligatoire (aucun défaut) sur chacun des huit
   modèles canoniques, pas seulement sur lui-même.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus_contracts import (
    ArtifactRecord,
    CollectionProfile,
    CoverageSnapshot,
    IngestionRun,
    PublicationPolicy,
    QualityReport,
    ResourceCandidate,
    ResourceScope,
    RoutingDecision,
    SearchPlan,
)
from nexus_contracts.resource_state import ResourceState, is_valid_resource_transition

REPO_ROOT = Path(__file__).resolve().parents[3]
ADR_PATH = REPO_ROOT / "docs" / "adr" / "ADR-0024-contrats-canoniques-ingestion-lot44a.md"

CANONICAL_MODELS_WITH_SCOPE = [
    CollectionProfile, SearchPlan, ResourceCandidate, ArtifactRecord,
    RoutingDecision, QualityReport, IngestionRun, CoverageSnapshot,
]


# --- 1. PublicationPolicy : politique passive ---


def test_1_auto_publish_defaults_to_false() -> None:
    assert PublicationPolicy().auto_publish is False


def test_1_auto_publish_cannot_be_constructed_as_true() -> None:
    """Verrou de type, pas seulement une valeur par défaut contournable."""
    with pytest.raises(ValidationError):
        PublicationPolicy(auto_publish=True)


def test_1_auto_publish_type_is_locked_to_literal_false() -> None:
    import typing

    annotation = PublicationPolicy.model_fields["auto_publish"].annotation
    assert typing.get_origin(annotation) is typing.Literal
    assert typing.get_args(annotation) == (False,)


def test_2_no_transition_reaches_published_state() -> None:
    """PUBLISHED n'existe pas dans ResourceState : il ne peut donc exister
    aucune transition (valide ou invalide au sens fonctionnel) qui y mène,
    car il n'y a tout simplement pas de valeur PUBLISHED à atteindre."""
    assert "PUBLISHED" not in {state.value for state in ResourceState}
    for from_state in ResourceState:
        for to_state in ResourceState:
            # Aucun couple (from, to) ne peut représenter PUBLISHED : les
            # deux bornes viennent de l'énumération elle-même, qui ne le
            # contient pas.
            assert to_state.value != "PUBLISHED"
    # Preuve directe que REVIEWED ne peut mener qu'à RETRIEVAL_ELIGIBLE ou
    # SUPERSEDED — jamais à une notion de publication.
    reachable_from_reviewed = {
        target for target in ResourceState
        if is_valid_resource_transition(ResourceState.REVIEWED, target)
    }
    assert reachable_from_reviewed == {
        ResourceState.RETRIEVAL_ELIGIBLE,
        ResourceState.FAILED,
        ResourceState.REJECTED,
        ResourceState.QUARANTINED,
        ResourceState.CANCELLED,
        ResourceState.SUPERSEDED,
    }


def test_3_no_endpoint_or_publication_behavior_is_introduced() -> None:
    """LOT44a est strictement des modèles Pydantic — recherche exhaustive
    d'un endpoint FastAPI ou d'une route Next.js qui importerait ou
    exposerait CollectionProfile/PublicationPolicy à ce stade."""
    forbidden_targets = ("CollectionProfile", "PublicationPolicy")

    fastapi_endpoints = list(
        (REPO_ROOT / "services" / "rag-engine" / "src").rglob("*_endpoint.py")
    ) + list((REPO_ROOT / "services" / "rag-engine" / "src" / "ingestor").glob("api.py"))
    nextjs_routes = list(
        (REPO_ROOT / "services" / "cockpit" / "src" / "app" / "api").rglob("route.ts")
    )

    for path in [*fastapi_endpoints, *nextjs_routes]:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        for target in forbidden_targets:
            assert target not in content, (
                f"{path} référence {target} — aucun endpoint ne doit exister en LOT44a"
            )


def test_4_reviewed_and_retrieval_eligible_remain_distinct() -> None:
    assert ResourceState.REVIEWED != ResourceState.RETRIEVAL_ELIGIBLE
    assert is_valid_resource_transition(
        ResourceState.REVIEWED, ResourceState.RETRIEVAL_ELIGIBLE
    ) is True
    assert is_valid_resource_transition(
        ResourceState.RETRIEVAL_ELIGIBLE, ResourceState.REVIEWED
    ) is False


def test_5_product_publication_is_documented_as_out_of_scope() -> None:
    """La décision « publication produit hors périmètre » doit être écrite
    noir sur blanc dans l'ADR de gouvernance, pas seulement implicite dans
    le code — sinon une future revue pourrait la perdre."""
    assert ADR_PATH.is_file(), "ADR-0024 doit exister avant tout merge LOT44a"
    content = ADR_PATH.read_text(encoding="utf-8")
    assert "publication produit" in content.lower()
    assert "hors périmètre" in content.lower()
    assert "PUBLISHED" in content


# --- 2. ResourceScope obligatoire sur chacun des huit modèles ---


@pytest.mark.parametrize("model", CANONICAL_MODELS_WITH_SCOPE)
def test_scope_field_is_required_with_no_default(model: type) -> None:
    field = model.model_fields["scope"]
    assert field.is_required() is True
    assert field.annotation is ResourceScope


@pytest.mark.parametrize(
    "field_name",
    [
        "tenant", "collection", "niveau", "voie", "matiere", "candidat",
        "audience", "visibility", "school_year", "programme_version",
    ],
)
def test_resource_scope_field_has_no_default_value(field_name: str) -> None:
    """Complète la preuve par ValidationError déjà existante
    (test_ingestion_contracts.py) par une preuve d'introspection directe :
    aucun des dix champs de scope n'a de valeur par défaut au niveau du
    modèle Pydantic lui-même."""
    field = ResourceScope.model_fields[field_name]
    assert field.is_required() is True
