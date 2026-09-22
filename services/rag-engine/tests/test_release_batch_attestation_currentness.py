"""L'actualité d'une revue batch est mesurée, portée, puis reconfrontée (ADR-0059)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ingestor.ingestion_control.release_batch_attestation import (
    MeasuredReleaseBatchFacts,
    ReleaseBatchAttestationError,
    build_release_batch_review_artifact,
    require_artifact_matches_facts,
)

COLLECTIONS = ("rag_nexus_ses_terminale_specialite", "rag_nexus_svt_terminale_specialite")


def _faits(currentness: str) -> MeasuredReleaseBatchFacts:
    ressource = uuid4()
    return MeasuredReleaseBatchFacts(
        release_id="production-profile-gate-2026-2027-v3",
        release_manifest_sha256="1" * 64,
        artifacts_release_sha256="2" * 64,
        candidate_inventory_sha256="3" * 64,
        artifact_transfer_manifest_sha256="4" * 64,
        collections=COLLECTIONS,
        scope_authorization_ids=tuple(
            "lot41a-staging-v2-" + c.removeprefix("rag_nexus_").replace("_", "-")
            for c in COLLECTIONS
        ),
        subjects=2,
        unique_artifacts=1,
        placements=2,
        unique_chunks=5,
        provenance_source_url_count=1,
        resource_ids=(ressource,),
        par_ressource={ressource: (uuid4(), "a" * 64, COLLECTIONS[0], "x")},
        currentness=currentness,
    )


def _artefact(faits: MeasuredReleaseBatchFacts):  # type: ignore[no-untyped-def]
    debut = datetime(2026, 9, 22, tzinfo=UTC)
    return build_release_batch_review_artifact(
        review_id="lot42-release-batch-v3",
        facts=faits,
        valid_from=debut,
        valid_until=debut + timedelta(days=30),
    )


@pytest.mark.parametrize("currentness", ["current", "official_snapshot"])
def test_l_artefact_porte_l_actualite_mesuree(currentness: str) -> None:
    assert _artefact(_faits(currentness)).placement_evidence.currentness == currentness


@pytest.mark.parametrize(
    ("revue", "persiste"),
    [("current", "official_snapshot"), ("official_snapshot", "current")],
)
def test_une_revue_sur_une_autre_actualite_ne_couvre_pas_les_faits_persistes(
    revue: str, persiste: str
) -> None:
    artefact = _artefact(_faits(revue))
    with pytest.raises(ReleaseBatchAttestationError, match="currentness"):
        require_artifact_matches_facts(artefact, _faits(persiste))


def test_une_revue_conforme_aux_faits_persistes_est_admise() -> None:
    faits = _faits("official_snapshot")
    require_artifact_matches_facts(_artefact(faits), dataclasses.replace(faits))
