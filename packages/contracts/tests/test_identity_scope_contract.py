from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from nexus_contracts import (
    InternalIdentityEnvelope,
    PILOT_RETRIEVAL_SCOPE_DIGEST,
    PilotRetrievalScopeArtifact,
    load_pilot_retrieval_scope,
)
from pydantic import ValidationError

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
ARTIFACT_PATH = (
    PACKAGE_ROOT
    / "src"
    / "nexus_contracts"
    / "artifacts"
    / "pilot-retrieval-scope-v1.json"
)
LOT38_SCOPE_PATH = (
    REPOSITORY_ROOT
    / "services"
    / "rag-pedago"
    / "configs"
    / "pilot_validation_scope.yml"
)
LOT38_SOURCE_SHA256 = (
    "b55ef1383fceabbbe0bf30c47a45a1fce607697f56bac340162156fabcf0fe26"
)
EXPECTED_ARTIFACT_SHA256 = (
    "a1ed0fb1c7ec6344c17b155004d5bb61172b77f4b5bff6f5a250cc8b968fdd24"
)


def _artifact() -> PilotRetrievalScopeArtifact:
    artifact = PilotRetrievalScopeArtifact.model_validate_json(ARTIFACT_PATH.read_bytes())
    assert load_pilot_retrieval_scope() == artifact
    return artifact


def _identity_payload() -> dict[str, object]:
    return {
        "aud": "nexus-rag-engine",
        "exp": 4_102_444_800,
        "iss": "nexus-cockpit",
        "jti": "jti-12345",
        "tenant": "libre_terminale",
        "niveau": "terminale",
        "role": "student",
        "school_year": "2026-2027",
        "sub": "psn_1234567890abcdef",
        "pedagogical_profile": {
            "voie": "generale",
            "matieres": ["maths", "nsi"],
            "statut_enseignement": "specialite",
            "candidat": "libre",
            "audience": "libre",
        },
    }


def _envelope_payload(artifact: PilotRetrievalScopeArtifact) -> dict[str, object]:
    return {
        "protocol_version": "1",
        "iss": "nexus-cockpit",
        "aud": "nexus-rag-engine",
        "sub": "psn_1234567890abcdef",
        "jti": "jti-12345",
        "iat": 1_785_319_800,
        "exp": 1_785_320_400,
        "identity": _identity_payload(),
        "scope_id": artifact.scope_id,
        "scope_digest": artifact.sha256_digest(),
        "allowed_collections": [subject.collection for subject in artifact.subjects],
    }


def test_pilot_artifact_is_exact_projection_of_lot38_scope() -> None:
    raw_scope = LOT38_SCOPE_PATH.read_bytes()
    source = yaml.safe_load(raw_scope)
    artifact = _artifact()

    assert hashlib.sha256(raw_scope).hexdigest() == LOT38_SOURCE_SHA256
    assert artifact.source_sha256 == LOT38_SOURCE_SHA256
    assert artifact.scope_id == source["scope_id"]
    assert artifact.status == source["status"] == "eligible_for_promotion"
    assert artifact.school_year == source["school_year"]
    assert artifact.identity.model_dump(mode="json") == {
        "tenant": source["identity"]["tenant"],
        "niveau": source["identity"]["level"],
        "voie": source["identity"]["track"],
        "statut_enseignement": source["identity"]["teaching_status"],
        "audience": source["identity"]["audience"],
        "candidates": source["identity"]["candidates"],
    }
    assert [subject.model_dump(mode="json") for subject in artifact.subjects] == [
        {
            "matiere": subject["subject"],
            "collection": subject["collection"],
            "programme_version": subject["programme_version"],
        }
        for subject in source["subjects"]
    ]


def test_artifact_digest_uses_canonical_json_bytes() -> None:
    artifact = _artifact()
    expected = json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert artifact.canonical_bytes() == expected
    assert artifact.sha256_digest() == hashlib.sha256(expected).hexdigest()
    assert artifact.sha256_digest() == EXPECTED_ARTIFACT_SHA256
    assert PILOT_RETRIEVAL_SCOPE_DIGEST == EXPECTED_ARTIFACT_SHA256


def test_envelope_binds_identity_and_exact_pilot_scope() -> None:
    artifact = _artifact()
    envelope = InternalIdentityEnvelope(**_envelope_payload(artifact))

    artifact.validate_envelope(envelope)
    assert envelope.protocol_version == "1"


@pytest.mark.parametrize("binding", ["sub", "jti"])
def test_envelope_rejects_identity_binding_mismatch(binding: str) -> None:
    artifact = _artifact()
    payload = _envelope_payload(artifact)
    payload[binding] = "psn_abcdef1234567890" if binding == "sub" else "other-jti"

    with pytest.raises(ValidationError, match=binding):
        InternalIdentityEnvelope(**payload)


def test_envelope_exp_cannot_outlive_identity() -> None:
    artifact = _artifact()
    payload = _envelope_payload(artifact)
    payload["exp"] = 4_102_444_801

    with pytest.raises(ValidationError, match="exp"):
        InternalIdentityEnvelope(**payload)


def test_manifest_bound_envelope_requires_atomic_short_lived_hashes() -> None:
    artifact = _artifact()
    payload = _envelope_payload(artifact)
    payload["iat"] = 1_785_320_370
    payload["request_sha256"] = "a" * 64
    payload["manifest_sha256"] = "b" * 64

    envelope = InternalIdentityEnvelope(**payload)
    assert envelope.request_sha256 == "a" * 64
    assert envelope.manifest_sha256 == "b" * 64

    del payload["manifest_sha256"]
    with pytest.raises(ValidationError, match="provided together"):
        InternalIdentityEnvelope(**payload)

    payload["manifest_sha256"] = "b" * 64
    payload["iat"] -= 1
    with pytest.raises(ValidationError, match="30 seconds"):
        InternalIdentityEnvelope(**payload)


@pytest.mark.parametrize("allowed_collections", [[], ["collection_a", "collection_a"]])
def test_envelope_requires_unique_non_empty_collections(
    allowed_collections: list[str],
) -> None:
    artifact = _artifact()
    payload = _envelope_payload(artifact)
    payload["allowed_collections"] = allowed_collections

    with pytest.raises(ValidationError, match="allowed_collections"):
        InternalIdentityEnvelope(**payload)


@pytest.mark.parametrize("field", ["scope_id", "scope_digest", "allowed_collections"])
def test_artifact_rejects_envelope_outside_exact_scope(field: str) -> None:
    artifact = _artifact()
    payload = _envelope_payload(artifact)
    if field == "allowed_collections":
        payload[field] = ["rag_nexus_maths_terminale_gen_specialite"]
    else:
        payload[field] = "0" * 64 if field == "scope_digest" else "other_scope"
    envelope = InternalIdentityEnvelope(**payload)

    with pytest.raises(ValueError, match=field):
        artifact.validate_envelope(envelope)


def test_artifact_has_no_runtime_issuer_or_audience_policy() -> None:
    _artifact()
    assert "issuer" not in PilotRetrievalScopeArtifact.model_fields
    assert "token_audience" not in PilotRetrievalScopeArtifact.model_fields
