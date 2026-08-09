"""Contrat du publisher produit interne et gouverné H2-C."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from uuid import uuid4

import pytest
from nexus_contracts import Candidat, Niveau, Voie
from nexus_contracts.ingestion import ResourceScope

from ingestor.governed_publisher_v2 import (
    EligiblePlacement,
    GovernedArtifact,
    canonical_placement_id,
    publish_governed_artifact,
)

CONTENT = b"octets canoniques d'un document pedagogique"
CONTENT_SHA = hashlib.sha256(CONTENT).hexdigest()


def _scope(*, collection: str, matiere: str) -> ResourceScope:
    return ResourceScope(
        tenant="libre_terminale",
        collection=collection,
        niveau=Niveau.terminale,
        voie=Voie.generale,
        matiere=matiere,
        candidat=Candidat.libre,
        audience=["tous"],
        visibility="public",
        school_year="2026-2027",
        programme_version="BOEN_2025",
    )


def _placement(*, collection: str, matiere: str) -> EligiblePlacement:
    return EligiblePlacement(
        resource_id=uuid4(),
        scope=_scope(collection=collection, matiere=matiere),
        statut_enseignement="tronc_commun",
        domain="lycee",
        source_scope=f"01_EDUSCOL_OFFICIEL/terminale/{matiere}",
        source_placement_id=f"eduscol:5793:terminale:{matiere}",
        source_path=f"01_EDUSCOL_OFFICIEL/{matiere}/source.pdf",
        source_uri=f"https://eduscol.education.gouv.fr/{matiere}",
        current_profile_fingerprint="1" * 64,
        current_manifest_digest="2" * 64,
    )


def test_artifact_identity_is_exactly_the_content_sha() -> None:
    artifact = GovernedArtifact(
        content=CONTENT,
        content_sha256=CONTENT_SHA,
        source_label="Ressource Eduscol",
        source_uri="https://eduscol.education.fr/document.pdf",
        rights="officiel_public",
        official=True,
        source_kind="eduscol",
        type_doc="ressource_officielle",
    )

    assert artifact.artifact_id == CONTENT_SHA
    assert artifact.content_sha256 == hashlib.sha256(artifact.content).hexdigest()


def test_artifact_rejects_a_content_sha_drift() -> None:
    with pytest.raises(ValueError, match="content SHA-256"):
        GovernedArtifact(
            content=CONTENT,
            content_sha256="0" * 64,
            source_label="Ressource Eduscol",
            source_uri="https://eduscol.education.fr/document.pdf",
            rights="officiel_public",
            official=True,
            source_kind="eduscol",
            type_doc="ressource_officielle",
        )


def test_placement_identity_changes_without_changing_artifact_identity() -> None:
    philosophy = _placement(
        collection="rag_nexus_philo_terminale_tc",
        matiere="philosophie",
    )
    arts = _placement(
        collection="rag_nexus_arts_terminale_option",
        matiere="arts",
    )

    assert canonical_placement_id(CONTENT_SHA, philosophy) != canonical_placement_id(
        CONTENT_SHA, arts
    )
    assert canonical_placement_id(CONTENT_SHA, philosophy) == canonical_placement_id(
        CONTENT_SHA, philosophy
    )


def test_placement_preserves_its_own_source_uri() -> None:
    philosophy = _placement(
        collection="rag_nexus_philo_terminale_tc",
        matiere="philosophie",
    )

    assert philosophy.source_uri == "https://eduscol.education.gouv.fr/philosophie"


def test_publisher_surface_requires_governance_objects_not_bare_text() -> None:
    parameters = inspect.signature(publish_governed_artifact).parameters

    assert tuple(parameters) == (
        "control_conn",
        "product_conn",
        "artifact",
        "placements",
        "extract_text",
        "embed_chunks",
    )
    assert "text" not in parameters
    assert "collection" not in parameters


def test_no_http_writer_mount_imports_the_internal_publisher() -> None:
    engine_root = Path(__file__).resolve().parents[1]
    api = (engine_root / "src/ingestor/api_v2.py").read_text(encoding="utf-8")
    endpoint = (engine_root / "src/ingestor/retrieval_v2_endpoint.py").read_text(
        encoding="utf-8"
    )

    assert "governed_publisher_v2" not in api
    assert "governed_publisher_v2" not in endpoint
