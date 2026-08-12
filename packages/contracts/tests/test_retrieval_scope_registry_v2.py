from __future__ import annotations

import pytest
from nexus_contracts import (
    InternalIdentityEnvelope,
    RetrievalScopeArtifactV2,
    load_retrieval_scope_artifact,
    load_retrieval_scope_registry,
)


EXPECTED = {
    "libre_terminale_maths_nsi_real_v1",
    "entree_seconde_maths_v1",
    "entree_seconde_francais_v1",
    "entree_premiere_maths_v1",
    "entree_premiere_francais_v1",
    "entree_troisieme_maths_v1",
    "entree_troisieme_francais_v1",
    "entree_terminale_maths_v1",
    "entree_terminale_nsi_v1",
    "eaf_premiere_francais_v1",
    "terminale_maths_v1",
    "terminale_nsi_v1",
    "terminale_physique_chimie_v1",
}


def _wave0_envelope(artifact: RetrievalScopeArtifactV2) -> InternalIdentityEnvelope:
    target = artifact.target_identity
    return InternalIdentityEnvelope.model_validate(
        {
            "protocol_version": "1",
            "iss": "nexus-cockpit",
            "aud": "nexus-rag-engine",
            "sub": "psn_1234567890abcdef",
            "jti": "jti-wave0-123",
            "iat": 1_785_319_800,
            "exp": 1_785_320_400,
            "identity": {
                "aud": "nexus-rag-engine",
                "exp": 1_785_320_400,
                "iss": "nexus-cockpit",
                "jti": "jti-wave0-123",
                "tenant": target.tenant,
                "niveau": target.niveau,
                "role": "teacher",
                "school_year": artifact.evidence_subject.school_year,
                "sub": "psn_1234567890abcdef",
                "pedagogical_profile": {
                    "voie": target.voie,
                    "matieres": [target.matiere],
                    "statut_enseignement": target.statut_enseignement,
                    "candidat": target.candidates[0],
                    "audience": target.audience,
                },
            },
            "scope_id": artifact.scope_id,
            "scope_digest": artifact.sha256_digest(),
            "allowed_collections": [artifact.evidence_subject.collection],
        }
    )


def test_registry_contains_only_the_legacy_wave0_and_multilevel_scopes() -> None:
    registry = load_retrieval_scope_registry()
    maths = registry["entree_seconde_maths_v1"]
    francais = registry["entree_seconde_francais_v1"]

    assert set(registry) == EXPECTED
    assert isinstance(maths, RetrievalScopeArtifactV2)
    assert isinstance(francais, RetrievalScopeArtifactV2)
    assert maths.evidence_subject.collection == (
        "rag_nexus_maths_troisieme_tc"
    )
    assert francais.evidence_subject.collection == (
        "rag_nexus_francais_troisieme_tc"
    )


@pytest.mark.parametrize(
    ("scope_id", "matiere"),
    [
        ("entree_seconde_maths_v1", "maths"),
        ("entree_seconde_francais_v1", "francais"),
    ],
)
def test_wave0_scope_separates_seconde_target_from_troisieme_evidence(
    scope_id: str,
    matiere: str,
) -> None:
    artifact = load_retrieval_scope_artifact(scope_id)

    assert isinstance(artifact, RetrievalScopeArtifactV2)
    assert artifact.artifact_version == "2"
    assert artifact.target_identity.niveau.value == "seconde"
    assert artifact.target_identity.matiere == matiere
    assert artifact.evidence_subject.niveau.value == "troisieme"
    assert artifact.evidence_subject.voie.value == "college"
    assert artifact.evidence_subject.matiere == matiere
    artifact.validate_envelope(_wave0_envelope(artifact))


def test_registry_rejects_an_unknown_scope_without_fallback() -> None:
    with pytest.raises(ValueError, match="unknown retrieval scope"):
        load_retrieval_scope_artifact("entree_seconde_everything_v1")


def test_v2_artifact_rejects_target_identity_or_collection_drift() -> None:
    artifact = load_retrieval_scope_artifact("entree_seconde_maths_v1")
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    payload = _wave0_envelope(artifact).model_dump(mode="json")
    payload["identity"]["niveau"] = "terminale"
    envelope = InternalIdentityEnvelope.model_validate(payload)
    with pytest.raises(ValueError, match="identity.niveau"):
        artifact.validate_envelope(envelope)

    payload = _wave0_envelope(artifact).model_dump(mode="json")
    payload["allowed_collections"] = ["rag_nexus_francais_troisieme_tc"]
    envelope = InternalIdentityEnvelope.model_validate(payload)
    with pytest.raises(ValueError, match="allowed_collections"):
        artifact.validate_envelope(envelope)
