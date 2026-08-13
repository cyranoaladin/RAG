from __future__ import annotations

import pytest
from nexus_contracts import (
    InternalIdentityEnvelope,
    Niveau,
    RetrievalCurriculumScope,
    RetrievalNeed,
    RetrievalRequest,
    RetrievalScopeArtifactV2,
    StudentProfile,
    load_retrieval_scope_artifact,
    load_retrieval_scope_registry,
)

from src.ingestor.identity_v2 import (
    IdentityVerifierConfig,
    VerifiedInternalIdentity,
)
from src.ingestor.retrieval_scope_v2 import (
    build_server_retrieval_scope,
    effective_signed_collections,
)


def _request(
    scope_id: str,
    *,
    curriculum_niveau: Niveau = Niveau.troisieme,
    target_niveau: Niveau = Niveau.seconde,
    include_curriculum: bool = True,
) -> RetrievalRequest:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    return RetrievalRequest(
        student_profile=StudentProfile(
            niveau=target_niveau,
            voie=target.voie,
            matieres=[target.matiere],
            statut_enseignement=target.statut_enseignement,
            candidat=target.candidates[0],
            school_year=evidence.school_year,
            zone=target.audience,
        ),
        curriculum_scope=(
            RetrievalCurriculumScope(
                niveau=curriculum_niveau,
                voie=evidence.voie,
                matiere=evidence.matiere,
                statut_enseignement=evidence.statut_enseignement,
            )
            if include_curriculum
            else None
        ),
        need=RetrievalNeed(intent="remediation", query="Diagnostic d'entrée"),
    )


def _verified(scope_id: str) -> VerifiedInternalIdentity:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    envelope = InternalIdentityEnvelope.model_validate(
        {
            "protocol_version": "1",
            "iss": "cockpit-internal",
            "aud": "rag-engine",
            "sub": "psn_1234567890abcdef",
            "jti": "jti-wave0-123",
            "iat": 1_799_999_990,
            "exp": 1_800_000_300,
            "identity": {
                "aud": "nexus-cockpit",
                "exp": 1_800_000_600,
                "iss": "nexus-issuer",
                "jti": "jti-wave0-123",
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
    return VerifiedInternalIdentity(envelope=envelope, artifact=artifact)


def _catalogue(verified: VerifiedInternalIdentity) -> dict[str, object]:
    artifact = verified.artifact
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    evidence = artifact.evidence_subject
    return {
        "collections": {
            evidence.collection: {
                "matiere": evidence.matiere,
                "niveau": evidence.niveau.value,
                "voie": evidence.voie.value,
                "statut": evidence.statut_enseignement.value,
                "domain": "education",
                "instanciee": True,
            }
        },
        "domains": {"education": {"retrievable": True}},
    }


@pytest.mark.parametrize(
    "scope_id",
    ["entree_seconde_maths_v1", "entree_seconde_francais_v1"],
)
def test_v2_server_scope_uses_evidence_dimensions_not_target_dimensions(
    scope_id: str,
) -> None:
    verified = _verified(scope_id)
    artifact = verified.artifact
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    evidence = artifact.evidence_subject

    scope = build_server_retrieval_scope(
        verified,
        collection=evidence.collection,
        collection_config=_catalogue(verified),
    )

    assert effective_signed_collections(verified) == (evidence.collection,)
    assert verified.envelope.identity.niveau.value == "seconde"
    assert scope.tenant == "libre_troisieme"
    assert scope.niveau == "troisieme"
    assert scope.voie == "college"
    assert scope.matiere == evidence.matiere
    assert scope.statut_enseignement == "tronc_commun"
    assert scope.candidat == "libre"
    assert scope.audiences == ("libre", "tous")
    assert scope.visibilities == ("internal",)


def test_identity_registry_rejects_unknown_scope_id_before_any_fallback() -> None:
    verified = _verified("entree_seconde_maths_v1")
    config = IdentityVerifierConfig(
        secret="test-secret-long-enough-for-hs256",
        issuer="cockpit-internal",
        audience="rag-engine",
        identity_issuer="nexus-issuer",
        identity_audience="nexus-cockpit",
        artifact=load_retrieval_scope_artifact("libre_terminale_maths_nsi_real_v1"),
        artifacts=load_retrieval_scope_registry(),
    )
    payload = verified.envelope.model_dump(mode="json")
    payload["scope_id"] = "unknown_scope"
    # Keep this as a unit assertion on the selected registry path. Signature
    # helpers remain covered exhaustively by test_identity_v2.py.
    from src.ingestor import identity_v2

    with pytest.raises(identity_v2.IdentityScopeError, match="identity scope forbidden"):
        identity_v2.resolve_identity_scope(payload["scope_id"], config=config)


def test_identity_registry_rejects_wrong_digest_for_selected_scope() -> None:
    verified = _verified("entree_seconde_maths_v1")
    artifact = verified.artifact
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    payload = verified.envelope.model_dump(mode="json")
    payload["scope_digest"] = "0" * 64
    bad = InternalIdentityEnvelope.model_validate(payload)
    with pytest.raises(ValueError, match="scope_digest"):
        artifact.validate_envelope(bad)


@pytest.mark.parametrize(
    "scope_id",
    ["entree_seconde_maths_v1", "entree_seconde_francais_v1"],
)
def test_endpoint_scope_matching_accepts_seconde_target_and_troisieme_evidence(
    scope_id: str,
) -> None:
    from src.ingestor import retrieval_v2_endpoint as endpoint

    verified = _verified(scope_id)
    artifact = verified.artifact
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    payload = _request(scope_id)
    collection = endpoint._collection_for_retrieval_request(payload, verified)
    scope = build_server_retrieval_scope(
        verified,
        collection=collection,
        collection_config=_catalogue(verified),
    )

    endpoint._require_retrieval_profile_match(payload, scope, verified)
    assert collection == artifact.evidence_subject.collection


def test_v2_endpoint_requires_curriculum_scope_without_student_fallback() -> None:
    from src.ingestor import retrieval_v2_endpoint as endpoint

    verified = _verified("entree_seconde_maths_v1")
    with pytest.raises(endpoint.RetrievalScopeError, match="retrieval scope forbidden"):
        endpoint._collection_for_retrieval_request(
            _request("entree_seconde_maths_v1", include_curriculum=False),
            verified,
        )


@pytest.mark.parametrize(
    ("payload", "scope_id"),
    [
        (
            _request(
                "entree_seconde_maths_v1",
                curriculum_niveau=Niveau.seconde,
            ),
            "entree_seconde_maths_v1",
        ),
        (
            _request(
                "entree_seconde_maths_v1",
                target_niveau=Niveau.terminale,
            ),
            "entree_seconde_maths_v1",
        ),
    ],
)
def test_v2_endpoint_rejects_target_or_curriculum_level_drift(
    payload: RetrievalRequest,
    scope_id: str,
) -> None:
    from src.ingestor import retrieval_v2_endpoint as endpoint

    verified = _verified(scope_id)
    artifact = verified.artifact
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    scope = build_server_retrieval_scope(
        verified,
        collection=artifact.evidence_subject.collection,
        collection_config=_catalogue(verified),
    )

    with pytest.raises(endpoint.RetrievalScopeError, match="retrieval scope forbidden"):
        endpoint._require_retrieval_profile_match(payload, scope, verified)


def test_v2_endpoint_rejects_math_curriculum_with_french_signed_scope() -> None:
    from src.ingestor import retrieval_v2_endpoint as endpoint

    verified = _verified("entree_seconde_francais_v1")
    payload = _request("entree_seconde_maths_v1")
    with pytest.raises(endpoint.RetrievalScopeError, match="retrieval scope forbidden"):
        endpoint._collection_for_retrieval_request(payload, verified)
