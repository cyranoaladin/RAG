"""Chemin de rôle pour les onze futurs scopes publics (fixture non activée).

La portée publique n'existe pas encore dans une release : chaque scope de ce
test est une copie synthétique dont la seule visibilité devient ``public``.
Le test ne vaut ni revue humaine, ni preuve E2E sur pgvector.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from nexus_contracts import InternalIdentity, InternalIdentityEnvelope
from nexus_contracts.hggsp_successor_scopes import load_retrieval_scope_artifact
from nexus_contracts.scope import RetrievalScopeArtifactV2

from src.ingestor.collection_config import validate_collection_catalogue_v2
from src.ingestor.identity_v2 import VerifiedInternalIdentity
from src.ingestor.retrieval_scope_v2 import (
    RetrievalScopeError,
    build_server_retrieval_scope,
)

ROOT = Path(__file__).resolve().parents[3]
AUTHORITY = ROOT / "packages/contracts/authorities/production-profile-scope-successors-v4.yml"
HGGSP = ROOT / "packages/contracts/authorities/production-profile-scope-successors-hggsp-v5.yml"


def _active_scope_ids() -> dict[str, str]:
    v4 = yaml.safe_load(AUTHORITY.read_text(encoding="utf-8"))
    v5 = yaml.safe_load(HGGSP.read_text(encoding="utf-8"))
    scopes = {row["collection"]: row["scope_id"] for row in v4["bindings"]}
    scopes.update({row["collection"]: row["scope_id"] for row in v5["bindings"]})
    assert len(scopes) == 11
    return scopes


def _proposal(scope_id: str) -> RetrievalScopeArtifactV2:
    historical = load_retrieval_scope_artifact(scope_id)
    assert isinstance(historical, RetrievalScopeArtifactV2)
    payload = historical.model_dump(mode="json")
    assert payload["evidence_subject"]["visibility"] == "internal"
    payload["scope_id"] = "student_public_test_scope"
    payload["source_sha256"] = "a" * 64
    payload["evidence_subject"]["visibility"] = "public"
    return RetrievalScopeArtifactV2.model_validate(payload)


def _verified(artifact: RetrievalScopeArtifactV2, role: str) -> VerifiedInternalIdentity:
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    identity = InternalIdentity.model_validate(
        {
            "aud": "nexus-cockpit",
            "exp": 1_800_000_600,
            "iss": "nexus-issuer",
            "jti": "student-public-fixture",
            "tenant": target.tenant,
            "niveau": target.niveau,
            "role": role,
            "school_year": evidence.school_year,
            "sub": "psn_student_public_fixture",
            "pedagogical_profile": {
                "voie": target.voie,
                "matieres": [target.matiere],
                "statut_enseignement": target.statut_enseignement,
                "candidat": target.candidates[0],
                "audience": target.audience,
            },
        }
    )
    envelope = InternalIdentityEnvelope(
        protocol_version="1",
        iss="cockpit-internal",
        aud="rag-engine",
        sub=identity.sub,
        jti=identity.jti,
        iat=1_799_999_990,
        exp=1_800_000_300,
        identity=identity,
        scope_id=artifact.scope_id,
        scope_digest=artifact.sha256_digest(),
        allowed_collections=[evidence.collection],
    )
    return VerifiedInternalIdentity(envelope=envelope, artifact=artifact)


@pytest.mark.parametrize("collection,scope_id", sorted(_active_scope_ids().items()))
def test_student_and_teacher_receive_only_the_public_collection(
    collection: str, scope_id: str
) -> None:
    artifact = _proposal(scope_id)
    catalogue = validate_collection_catalogue_v2()
    for role in ("student", "teacher"):
        verified = _verified(artifact, role)
        scope = build_server_retrieval_scope(
            verified, collection=collection, collection_config=catalogue
        )
        assert scope.collection == collection
        assert scope.visibilities == ("public",)
        assert [right.value for right in scope.rights] == ["officiel_public"]

        other = next(name for name in _active_scope_ids() if name != collection)
        with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
            build_server_retrieval_scope(verified, collection=other, collection_config=catalogue)


@pytest.mark.parametrize("collection,scope_id", sorted(_active_scope_ids().items()))
def test_student_still_cannot_use_the_internal_predecessor(collection: str, scope_id: str) -> None:
    predecessor = load_retrieval_scope_artifact(scope_id)
    assert isinstance(predecessor, RetrievalScopeArtifactV2)
    with pytest.raises(RetrievalScopeError, match="retrieval scope forbidden"):
        build_server_retrieval_scope(
            _verified(predecessor, "student"),
            collection=collection,
            collection_config=validate_collection_catalogue_v2(),
        )
