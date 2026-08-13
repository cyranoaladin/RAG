"""Registre fermé des dix scopes de retrieval multi-niveaux."""

from __future__ import annotations

from typing import NamedTuple

import pytest

from nexus_contracts import (
    InternalIdentityEnvelope,
    RetrievalScopeArtifactV2,
    load_retrieval_scope_artifact,
    load_retrieval_scope_registry,
)


class ScopeFacts(NamedTuple):
    collection: str
    source_sha256: str
    target_tenant: str
    target_niveau: str
    target_voie: str
    matiere: str
    statut: str
    evidence_tenant: str
    evidence_niveau: str
    evidence_voie: str
    programme_version: str


MULTILEVEL_SCOPES = {
    "entree_premiere_maths_v1": ScopeFacts(
        "rag_nexus_maths_seconde_tc",
        "fede87cc7bfa5097eecf597b90f51a1a97c7e7f2282a148a74cae0bbadad7971",
        "libre_premiere",
        "premiere",
        "generale",
        "maths",
        "tronc_commun",
        "libre_seconde",
        "seconde",
        "generale",
        "BOEN_14_2026-04-02_MENE2602914A",
    ),
    "entree_premiere_francais_v1": ScopeFacts(
        "rag_nexus_francais_seconde_tc",
        "e8c7aefc1cf4e0c195ef5b0f3d6b3ebea07b2741662d1aef4fb3dc64745189f0",
        "libre_premiere",
        "premiere",
        "generale",
        "francais",
        "tronc_commun",
        "libre_seconde",
        "seconde",
        "generale",
        "BOEN_special_1_2019-01-22",
    ),
    "entree_troisieme_maths_v1": ScopeFacts(
        "rag_nexus_maths_quatrieme_tc",
        "7341306ef319594dd72cc9020350ebcac7cd5e43dd6ef0dd3780dfc8a479130b",
        "libre_troisieme",
        "troisieme",
        "college",
        "maths",
        "tronc_commun",
        "libre_quatrieme",
        "quatrieme",
        "college",
        "BOEN_special_11_2018-07-26_aj_2020",
    ),
    "entree_troisieme_francais_v1": ScopeFacts(
        "rag_nexus_francais_quatrieme_tc",
        "b507a655f7c42c7acf9e0df0636c38b2c138d14bce6c8b62df9f471f2ef4ab28",
        "libre_troisieme",
        "troisieme",
        "college",
        "francais",
        "tronc_commun",
        "libre_quatrieme",
        "quatrieme",
        "college",
        "BOEN_special_11_2018-07-26_aj_2020",
    ),
    "entree_terminale_maths_v1": ScopeFacts(
        "rag_nexus_maths_premiere_gen_specialite",
        "a0edfafb3e8e076fa090971828072eb01ca3636271258c9df14da836e01b828e",
        "libre_terminale",
        "terminale",
        "generale",
        "maths",
        "specialite",
        "libre_premiere",
        "premiere",
        "generale",
        "BOEN_14_2026-04-02_MENE2602917A",
    ),
    "entree_terminale_nsi_v1": ScopeFacts(
        "rag_nexus_nsi_premiere_specialite",
        "4520576d1a7412abfba0354f33bbb6a50f4cff707ce2b7dc042b17dbb9fd04a8",
        "libre_terminale",
        "terminale",
        "generale",
        "nsi",
        "specialite",
        "libre_premiere",
        "premiere",
        "generale",
        "BOEN_special_1_2019-01-22",
    ),
    "eaf_premiere_francais_v1": ScopeFacts(
        "rag_nexus_francais_premiere_tc",
        "60797507f3f7e36e3bd041739d891968d649a0623774895145cf296b5d9dc005",
        "libre_premiere",
        "premiere",
        "generale",
        "francais",
        "tronc_commun",
        "libre_premiere",
        "premiere",
        "generale",
        "BOEN_special_1_2019-01-22",
    ),
    "terminale_maths_v1": ScopeFacts(
        "rag_nexus_maths_terminale_gen_specialite",
        "e6e7adc97b5904eec39a9fca05a10795f8d2cd81662f9df1275c6f6ba4e516ff",
        "libre_terminale",
        "terminale",
        "generale",
        "maths",
        "specialite",
        "libre_terminale",
        "terminale",
        "generale",
        "BOEN_special_8_2019-07-25",
    ),
    "terminale_nsi_v1": ScopeFacts(
        "rag_nexus_nsi_terminale_specialite",
        "07e2b2e539bfc4fb7db89d82617622a746692d4a955b8a17e965e433cd9df612",
        "libre_terminale",
        "terminale",
        "generale",
        "nsi",
        "specialite",
        "libre_terminale",
        "terminale",
        "generale",
        "BOEN_special_8_2019-07-25",
    ),
    "terminale_physique_chimie_v1": ScopeFacts(
        "rag_nexus_pc_terminale_specialite",
        "6522eff27c492a4a8a3e934093b12e5ad6a09f135a96196604689bb95f9eb563",
        "libre_terminale",
        "terminale",
        "generale",
        "physique_chimie",
        "specialite",
        "libre_terminale",
        "terminale",
        "generale",
        "BOEN_special_8_2019-07-25",
    ),
}

HISTORICAL_SCOPES = {
    "libre_terminale_maths_nsi_real_v1",
    "entree_seconde_maths_v1",
    "entree_seconde_francais_v1",
}


def _teacher_envelope(artifact: RetrievalScopeArtifactV2) -> InternalIdentityEnvelope:
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    return InternalIdentityEnvelope.model_validate(
        {
            "protocol_version": "1",
            "iss": "nexus-cockpit",
            "aud": "nexus-rag-engine",
            "sub": "psn_1234567890abcdef",
            "jti": "jti-multilevel-123",
            "iat": 1_785_319_800,
            "exp": 1_785_320_400,
            "identity": {
                "aud": "nexus-rag-engine",
                "exp": 1_785_320_400,
                "iss": "nexus-cockpit",
                "jti": "jti-multilevel-123",
                "tenant": target.tenant,
                "niveau": target.niveau,
                "role": "teacher",
                "school_year": evidence.school_year,
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
            "allowed_collections": [evidence.collection],
        }
    )


def test_registry_contains_exactly_three_historical_and_ten_multilevel_scopes() -> None:
    registry = load_retrieval_scope_registry()

    assert set(registry) == HISTORICAL_SCOPES | set(MULTILEVEL_SCOPES)
    assert len(registry) == 13


@pytest.mark.parametrize(("scope_id", "facts"), MULTILEVEL_SCOPES.items())
def test_multilevel_scope_binds_exact_target_evidence_and_release(
    scope_id: str,
    facts: ScopeFacts,
) -> None:
    artifact = load_retrieval_scope_artifact(scope_id)

    assert isinstance(artifact, RetrievalScopeArtifactV2)
    assert artifact.source_sha256 == facts.source_sha256
    assert artifact.target_identity.tenant == facts.target_tenant
    assert artifact.target_identity.niveau.value == facts.target_niveau
    assert artifact.target_identity.voie.value == facts.target_voie
    assert artifact.target_identity.matiere == facts.matiere
    assert artifact.target_identity.statut_enseignement.value == facts.statut
    assert artifact.target_identity.audience == "libre"
    assert [item.value for item in artifact.target_identity.candidates] == ["libre"]
    evidence = artifact.evidence_subject
    assert evidence.collection == facts.collection
    assert evidence.tenant == facts.evidence_tenant
    assert evidence.niveau.value == facts.evidence_niveau
    assert evidence.voie.value == facts.evidence_voie
    assert evidence.matiere == facts.matiere
    assert evidence.statut_enseignement.value == facts.statut
    assert evidence.candidat.value == "libre"
    assert evidence.audiences == ["libre", "tous"]
    assert evidence.visibility == "internal"
    assert [item.value for item in evidence.rights] == ["officiel_public"]
    assert evidence.school_year == "2026-2027"
    assert evidence.programme_version == facts.programme_version
    artifact.validate_envelope(_teacher_envelope(artifact))


def test_multilevel_scope_rejects_a_collection_from_another_scope() -> None:
    artifact = load_retrieval_scope_artifact("entree_premiere_maths_v1")
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    envelope = _teacher_envelope(artifact)
    payload = envelope.model_dump(mode="json")
    payload["allowed_collections"] = ["rag_nexus_francais_seconde_tc"]

    with pytest.raises(ValueError, match="allowed_collections"):
        artifact.validate_envelope(InternalIdentityEnvelope.model_validate(payload))
