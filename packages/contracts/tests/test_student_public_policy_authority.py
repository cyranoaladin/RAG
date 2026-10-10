"""ADR-0064 ne peut autoriser que le périmètre élève public proposé.

Ce test ne vaut ni approbation humaine ni émission d'un scope actif.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest
from nexus_contracts.hggsp_successor_scopes import load_retrieval_scope_artifact

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_retrieval_scope_artifacts as emitter  # noqa: E402

EXPECTED_PREDECESSORS = {
    "rag_nexus_dgemc_terminale_option": "prod_dgemc_terminale_option_v3",
    "rag_nexus_hggsp_premiere_specialite": "prod_hggsp_premiere_specialite_v3",
    "rag_nexus_hggsp_terminale_specialite": "prod_hggsp_terminale_specialite_v3",
    "rag_nexus_hlp_premiere_specialite": "prod_hlp_premiere_specialite_v3",
    "rag_nexus_hlp_terminale_specialite": "prod_hlp_terminale_specialite_v2",
    "rag_nexus_nsi_premiere_specialite": "prod_nsi_premiere_specialite_v3",
    "rag_nexus_nsi_terminale_specialite": "prod_nsi_terminale_specialite_v3",
    "rag_nexus_ses_premiere_specialite": "prod_ses_premiere_specialite_v3",
    "rag_nexus_ses_terminale_specialite": "prod_ses_terminale_specialite_v3",
    "rag_nexus_svt_premiere_specialite": "prod_svt_premiere_specialite_v3",
    "rag_nexus_svt_terminale_specialite": "prod_svt_terminale_specialite_v3",
}


def test_adr_0064_allowlist_is_exactly_the_reviewed_eleven() -> None:
    assert dict(emitter.STUDENT_PUBLIC_PREDECESSORS) == EXPECTED_PREDECESSORS


def _proposal(**overrides: object) -> emitter.PolicyRegistryEntry:
    entry = emitter.PolicyRegistryEntry(
        collection="rag_nexus_dgemc_terminale_option",
        decision_status="GOVERNED_BY_HUMAN_DECISION",
        authority_source="NEXUS_HUMAN_DECISION_ADR_0064",
        policy_source_scope_id=None,
        subject_manifest_sha256="a" * 64,
        tenant="libre_terminale",
        niveau="terminale",
        voie="generale",
        matiere="dgemc",
        statut_enseignement="option",
        candidat="libre",
        audiences=("libre", "aefe"),
        rights=("public_allowed",),
        policy_visibility="public",
        evidence_visibility="public",
        programme_version="BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A",
        target_audience="libre",
        target_candidates=("libre",),
    )
    return replace(entry, **overrides)


@pytest.mark.parametrize(
    "collection,predecessor_id",
    sorted(EXPECTED_PREDECESSORS.items()),
)
def test_adr_0064_is_limited_to_the_eleven_existing_policies(
    collection: str, predecessor_id: str
) -> None:
    source = load_retrieval_scope_artifact(predecessor_id)
    evidence = source.evidence_subject
    target = source.target_identity
    entry = _proposal(
        collection=collection,
        tenant=target.tenant,
        niveau=target.niveau,
        voie=target.voie,
        matiere=target.matiere,
        statut_enseignement=target.statut_enseignement,
        candidat=evidence.candidat.value,
        audiences=("libre", "aefe"),
        programme_version=evidence.programme_version,
    )
    emitter._require_human_decision_is_declared_as_such(entry)


@pytest.mark.parametrize(
    "field,value",
    [
        ("collection", "rag_nexus_anglais_terminale"),
        ("rights", ("usage_interne",)),
        ("rights", ("officiel_public",)),
        ("rights", ("officiel_public", "nexus_proprietaire")),
        ("policy_visibility", "internal"),
        ("evidence_visibility", "internal"),
        ("target_audience", "aefe"),
        ("target_candidates", ("scolaire",)),
        ("candidat", "scolaire"),
        ("audiences", ("aefe",)),
        ("policy_source_scope_id", "prod_dgemc_terminale_option_v3"),
    ],
)
def test_adr_0064_refuses_wider_or_disguised_policy(field: str, value: object) -> None:
    with pytest.raises(emitter.ScopeEmissionError):
        emitter._require_human_decision_is_declared_as_such(_proposal(**{field: value}))


@pytest.mark.parametrize(
    "scope_id",
    (
        "prod_hggsp_premiere_specialite_v3",
        "prod_hggsp_terminale_specialite_v3",
    ),
)
def test_hggsp_successor_id_cannot_be_reissued_with_other_bytes(scope_id: str) -> None:
    pinned = load_retrieval_scope_artifact(scope_id)
    changed = pinned.model_copy(update={"source_sha256": "f" * 64})
    with pytest.raises(emitter.ScopeEmissionError, match="collision de scope_id"):
        emitter._require_registry_reuse_is_a_strict_reproduction(scope_id, changed)


@pytest.mark.parametrize(
    "scope_id",
    (
        "prod_hggsp_premiere_specialite_v3",
        "prod_hggsp_terminale_specialite_v3",
    ),
)
def test_hggsp_successor_subject_is_found_by_existing_match(scope_id: str) -> None:
    pinned = load_retrieval_scope_artifact(scope_id)
    assert emitter.exact_existing_matches(
        str(pinned.evidence_subject.collection), pinned.source_sha256
    ) == (scope_id,)
