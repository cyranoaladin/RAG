from __future__ import annotations

from copy import deepcopy

import pytest
from nexus_contracts import (
    InternalIdentityEnvelope,
    RetrievalScopeArtifactV3,
)
from pydantic import ValidationError

SHA = "a" * 64


def aria_scope_payload() -> dict[str, object]:
    return {
        "artifact_version": "3",
        "scope_id": "aria_maths_premiere_v1",
        "status": "eligible_for_promotion",
        "source_sha256": SHA,
        "target_policy": {
            "tenant": "nexus",
            "niveau": "premiere",
            "voie": "generale",
            "matiere": "maths",
            "statut_enseignement": "specialite",
            "audiences": ["aefe", "libre"],
            "candidates": ["scolarise", "aefe", "libre"],
            "roles": ["student"],
        },
        "evidence_subject": {
            "collection": "rag_nexus_maths_premiere_gen_specialite",
            "tenant": "nexus",
            "niveau": "premiere",
            "voie": "generale",
            "matiere": "maths",
            "statut_enseignement": "specialite",
            "candidat": "scolarise",
            "audiences": ["aefe", "tous"],
            "visibility": "public",
            "rights": ["officiel_public"],
            "school_year": "2026-2027",
            "programme_version": "fr-national-2026",
        },
    }


def envelope_payload(
    artifact: RetrievalScopeArtifactV3,
    *,
    candidat: str = "scolarise",
    audience: str = "aefe",
) -> dict[str, object]:
    identity = {
        "aud": "nexus-rag-engine",
        "exp": 1_785_320_400,
        "iss": "nexus-cockpit",
        "jti": "aria-jti-123",
        "tenant": "nexus",
        "niveau": "premiere",
        "role": "student",
        "school_year": "2026-2027",
        "sub": "psn_1234567890abcdef",
        "pedagogical_profile": {
            "voie": "generale",
            "matieres": ["maths"],
            "statut_enseignement": "specialite",
            "candidat": candidat,
            "audience": audience,
        },
    }
    return {
        "protocol_version": "1",
        "iss": "nexus-cockpit",
        "aud": "nexus-rag-engine",
        "sub": identity["sub"],
        "jti": identity["jti"],
        "iat": 1_785_320_370,
        "exp": 1_785_320_400,
        "identity": identity,
        "scope_id": artifact.scope_id,
        "scope_digest": artifact.sha256_digest(),
        "request_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "allowed_collections": [artifact.evidence_subject.collection],
    }


@pytest.mark.parametrize(
    ("candidat", "audience"),
    [("scolarise", "aefe"), ("aefe", "aefe"), ("libre", "libre")],
)
def test_aria_scope_authorizes_declared_student_profiles_without_approximation(
    candidat: str,
    audience: str,
) -> None:
    artifact = RetrievalScopeArtifactV3.model_validate(aria_scope_payload())
    envelope = InternalIdentityEnvelope.model_validate(
        envelope_payload(artifact, candidat=candidat, audience=audience)
    )

    artifact.validate_envelope(envelope)


def test_aria_scope_refuses_undeclared_student_profile() -> None:
    artifact = RetrievalScopeArtifactV3.model_validate(aria_scope_payload())
    envelope = InternalIdentityEnvelope.model_validate(
        envelope_payload(artifact, candidat="cned_reglemente", audience="aefe")
    )

    with pytest.raises(ValueError, match="candidat"):
        artifact.validate_envelope(envelope)


def test_aria_scope_requires_canonical_slug_and_unique_policy_values() -> None:
    payload = aria_scope_payload()
    payload["scope_id"] = "aria-maths-premiere"
    with pytest.raises(ValidationError, match="scope_id"):
        RetrievalScopeArtifactV3.model_validate(payload)

    payload = deepcopy(aria_scope_payload())
    payload["target_policy"]["audiences"] = ["aefe", "aefe"]  # type: ignore[index]
    with pytest.raises(ValidationError, match="audiences"):
        RetrievalScopeArtifactV3.model_validate(payload)
