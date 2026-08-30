"""Tests de la frontière d'identité signée cockpit vers rag-engine."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import HTTPException
from nexus_contracts import (
    RetrievalScopeArtifactV2,
    RetrievalScopeArtifactV3,
    load_pilot_retrieval_scope,
    load_retrieval_scope_artifact,
    load_retrieval_scope_registry,
)
from starlette.requests import Request

from src.ingestor.identity_v2 import (
    IdentityConfigurationError,
    IdentityScopeError,
    IdentityTokenError,
    IdentityVerifierConfig,
    load_identity_verifier_config,
    require_internal_identity,
    verify_identity_token,
)

TEST_CONFIG = IdentityVerifierConfig(
    secret="test-secret-long-enough-for-hs256",
    issuer="cockpit-internal",
    audience="rag-engine",
    identity_issuer="nexus-issuer",
    identity_audience="nexus-cockpit",
    artifact=load_pilot_retrieval_scope(),
)
NOW = 1_800_000_000
VALID_ENV = {
    "NEXUS_INTERNAL_TOKEN_SECRET": TEST_CONFIG.secret,
    "NEXUS_INTERNAL_TOKEN_ISSUER": TEST_CONFIG.issuer,
    "NEXUS_INTERNAL_TOKEN_AUDIENCE": TEST_CONFIG.audience,
    "NEXUS_SSO_ISSUER": TEST_CONFIG.identity_issuer,
    "NEXUS_SSO_AUDIENCE": TEST_CONFIG.identity_audience,
}


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _sign(
    payload: object,
    *,
    algorithm: str = "HS256",
    header_extra: dict[str, object] | None = None,
) -> str:
    protected: dict[str, object] = {"alg": algorithm, "typ": "JWT"}
    protected.update(header_extra or {})
    header = _b64url(json.dumps(protected).encode())
    body = _b64url(json.dumps(payload).encode())
    signed = f"{header}.{body}"
    signature = hmac.new(TEST_CONFIG.secret.encode(), signed.encode(), hashlib.sha256).digest()
    return f"{signed}.{_b64url(signature)}"


def _identity_payload(**overrides: object) -> dict[str, object]:
    identity: dict[str, object] = {
        "aud": TEST_CONFIG.identity_audience,
        "exp": NOW + 600,
        "iss": TEST_CONFIG.identity_issuer,
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
            "candidat": "individuel",
            "audience": "libre",
        },
    }
    identity.update(overrides)
    return identity


def _envelope_payload(**overrides: object) -> dict[str, object]:
    artifact = TEST_CONFIG.artifact
    envelope: dict[str, object] = {
        "protocol_version": "1",
        "iss": TEST_CONFIG.issuer,
        "aud": TEST_CONFIG.audience,
        "sub": "psn_1234567890abcdef",
        "jti": "jti-12345",
        "iat": NOW - 10,
        "exp": NOW + 300,
        "identity": _identity_payload(),
        "scope_id": artifact.scope_id,
        "scope_digest": artifact.sha256_digest(),
        "allowed_collections": [subject.collection for subject in artifact.subjects],
    }
    envelope.update(overrides)
    return envelope


def _request(*, identity_token: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if identity_token is not None:
        headers.append((b"x-nexus-identity", identity_token.encode("ascii")))
    return Request({"type": "http", "headers": headers})


def test_missing_identity_header_is_rejected_before_configuration() -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_internal_identity(_request())

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


def test_bad_signature_is_rejected() -> None:
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.invalid-signature"

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=1_800_000_000)


def test_algorithm_other_than_hs256_is_rejected_even_with_matching_signature() -> None:
    token = _sign({}, algorithm="HS512")

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=1_800_000_000)


@pytest.mark.parametrize("payload", [[], "identity", 7, None])
def test_signed_non_object_payload_is_rejected(payload: object) -> None:
    token = _sign(payload)

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=1_800_000_000)


def test_valid_signed_envelope_is_bound_to_the_canonical_artifact() -> None:
    verified = verify_identity_token(
        _sign(_envelope_payload()),
        config=TEST_CONFIG,
        now=NOW,
    )

    assert verified.envelope.identity.tenant == "libre_terminale"
    assert verified.artifact is TEST_CONFIG.artifact
    assert verified.scope_digest == TEST_CONFIG.artifact.sha256_digest()


def test_shared_manifest_bound_identity_fixture_verifies_with_runtime() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "contracts"
        / "fixtures"
        / "internal-identity-envelope-v1.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    artifact = RetrievalScopeArtifactV3.model_validate(fixture["retrievalScope"])
    config = IdentityVerifierConfig(
        secret=fixture["secret"],
        issuer=fixture["envelope"]["iss"],
        audience=fixture["envelope"]["aud"],
        identity_issuer=fixture["envelope"]["identity"]["iss"],
        identity_audience=fixture["envelope"]["identity"]["aud"],
        artifact=artifact,
        artifacts={artifact.scope_id: artifact},
    )

    verified = verify_identity_token(
        fixture["jwt"],
        config=config,
        now=fixture["envelope"]["iat"],
    )

    assert verified.artifact == artifact
    assert verified.scope_digest == fixture["retrievalScopeSha256"]


def test_signed_envelope_selects_the_exact_wave0_scope_from_registry() -> None:
    artifact = load_retrieval_scope_artifact("entree_seconde_maths_v1")
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    target = artifact.target_identity
    evidence = artifact.evidence_subject
    identity = _identity_payload(
        tenant=target.tenant,
        niveau=target.niveau.value,
        role="teacher",
        school_year=evidence.school_year,
        pedagogical_profile={
            "voie": target.voie.value,
            "matieres": [target.matiere],
            "statut_enseignement": target.statut_enseignement.value,
            "candidat": target.candidates[0].value,
            "audience": target.audience,
        },
    )
    token = _sign(
        _envelope_payload(
            identity=identity,
            scope_id=artifact.scope_id,
            scope_digest=artifact.sha256_digest(),
            allowed_collections=[evidence.collection],
        )
    )
    config = replace(TEST_CONFIG, artifacts=load_retrieval_scope_registry())

    verified = verify_identity_token(token, config=config, now=NOW)

    assert verified.artifact is config.artifacts[artifact.scope_id]
    assert verified.artifact.scope_id == "entree_seconde_maths_v1"


def test_signed_envelope_with_unknown_registry_scope_is_forbidden() -> None:
    config = replace(TEST_CONFIG, artifacts=load_retrieval_scope_registry())
    with pytest.raises(IdentityScopeError, match="identity scope forbidden"):
        verify_identity_token(
            _sign(_envelope_payload(scope_id="unknown_scope")),
            config=config,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("claim", "unexpected"),
    [("iss", "other-cockpit"), ("aud", "other-engine")],
)
def test_transport_issuer_and_audience_must_match_engine_policy(
    claim: str,
    unexpected: str,
) -> None:
    token = _sign(_envelope_payload(**{claim: unexpected}))

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=NOW)


@pytest.mark.parametrize("expired_at", [NOW - 1, NOW])
def test_expired_transport_token_is_rejected(expired_at: int) -> None:
    token = _sign(_envelope_payload(exp=expired_at, iat=expired_at - 60))

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=NOW)


@pytest.mark.parametrize(
    ("claim", "unexpected"),
    [("iss", "other-sso"), ("aud", "other-client")],
)
def test_external_identity_issuer_and_audience_must_match_policy(
    claim: str,
    unexpected: str,
) -> None:
    identity = _identity_payload(**{claim: unexpected})
    token = _sign(_envelope_payload(identity=identity))

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=NOW)


def test_contract_0_3_identity_without_school_year_is_rejected() -> None:
    identity = _identity_payload()
    del identity["school_year"]

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(
            _sign(_envelope_payload(identity=identity)),
            config=TEST_CONFIG,
            now=NOW,
        )


@pytest.mark.parametrize(
    "envelope_overrides",
    [
        {"sub": "psn_abcdef1234567890"},
        {"jti": "jti-other"},
        {"exp": NOW + 601},
    ],
)
def test_transport_claims_are_bound_to_the_nested_identity(
    envelope_overrides: dict[str, object],
) -> None:
    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(
            _sign(_envelope_payload(**envelope_overrides)),
            config=TEST_CONFIG,
            now=NOW,
        )


@pytest.mark.parametrize(
    "scope_overrides",
    [
        {"scope_id": "other_scope"},
        {"scope_digest": "b" * 64},
        {
            "allowed_collections": [
                "rag_nexus_nsi_terminale_specialite",
                "rag_nexus_maths_terminale_gen_specialite",
            ]
        },
    ],
)
def test_envelope_scope_must_match_the_engine_artifact_exactly(
    scope_overrides: dict[str, object],
) -> None:
    with pytest.raises(IdentityScopeError, match="identity scope forbidden"):
        verify_identity_token(
            _sign(_envelope_payload(**scope_overrides)),
            config=TEST_CONFIG,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("identity_overrides", "profile_overrides"),
    [
        ({"tenant": "aefe_terminale"}, {}),
        ({"niveau": "premiere"}, {}),
        ({"school_year": "2027-2028"}, {}),
        ({}, {"voie": "technologique"}),
        ({}, {"matieres": ["nsi", "francais"]}),
        ({}, {"statut_enseignement": "tronc_commun"}),
        ({}, {"candidat": "aefe"}),
        ({}, {"audience": "aefe"}),
    ],
)
def test_identity_projection_must_match_the_canonical_artifact(
    identity_overrides: dict[str, object],
    profile_overrides: dict[str, object],
) -> None:
    identity = _identity_payload(**identity_overrides)
    profile = dict(identity["pedagogical_profile"])
    profile.update(profile_overrides)
    identity["pedagogical_profile"] = profile

    with pytest.raises(IdentityScopeError, match="identity scope forbidden"):
        verify_identity_token(
            _sign(_envelope_payload(identity=identity)),
            config=TEST_CONFIG,
            now=NOW,
        )


@pytest.mark.parametrize(
    "field",
    ["secret", "issuer", "audience", "identity_issuer", "identity_audience"],
)
def test_all_signature_and_party_settings_are_mandatory(field: str) -> None:
    with pytest.raises(IdentityConfigurationError, match="identity configuration invalid"):
        replace(TEST_CONFIG, **{field: "  "})


def test_http_boundary_returns_the_verified_identity() -> None:
    verified = require_internal_identity(
        _request(identity_token=_sign(_envelope_payload())),
        config=TEST_CONFIG,
        now=NOW,
    )

    assert verified.envelope.identity.niveau.value == "terminale"


@pytest.mark.parametrize(
    ("token", "expected_status"),
    [
        ("invalid", 401),
        (_sign(_envelope_payload(scope_digest="c" * 64)), 403),
    ],
)
def test_http_boundary_maps_failures_without_disclosing_claims(
    token: str,
    expected_status: int,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_internal_identity(
            _request(identity_token=token),
            config=TEST_CONFIG,
            now=NOW,
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail in {"Unauthorized", "Forbidden"}


def test_runtime_loader_uses_required_settings_and_packaged_artifact() -> None:
    config = load_identity_verifier_config(VALID_ENV)

    assert config.issuer == "cockpit-internal"
    assert config.audience == "rag-engine"
    assert config.identity_issuer == "nexus-issuer"
    assert config.identity_audience == "nexus-cockpit"
    assert config.artifact.sha256_digest() == TEST_CONFIG.artifact.sha256_digest()


@pytest.mark.parametrize("missing", sorted(VALID_ENV))
def test_runtime_loader_fails_closed_when_a_setting_is_missing(missing: str) -> None:
    environ = dict(VALID_ENV)
    del environ[missing]

    with pytest.raises(IdentityConfigurationError, match="identity configuration invalid"):
        load_identity_verifier_config(environ)


def test_hs256_secret_must_be_at_least_32_bytes() -> None:
    with pytest.raises(IdentityConfigurationError, match="identity configuration invalid"):
        replace(TEST_CONFIG, secret="short-secret")


def test_sso_audience_policy_must_be_one_exact_value() -> None:
    with pytest.raises(IdentityConfigurationError, match="identity configuration invalid"):
        replace(TEST_CONFIG, identity_audience="nexus-cockpit,other-client")


def test_http_boundary_loads_runtime_policy_when_not_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in VALID_ENV.items():
        monkeypatch.setenv(name, value)

    verified = require_internal_identity(
        _request(identity_token=_sign(_envelope_payload())),
        now=NOW,
    )

    assert verified.scope_digest == TEST_CONFIG.artifact.sha256_digest()


@pytest.mark.parametrize(
    "token",
    ["é.e30.signature", "e30.é.signature", "e30.e30.signaturé"],
)
def test_non_ascii_jwt_segments_are_rejected_without_encoding_error(token: str) -> None:
    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=NOW)


def test_protected_header_rejects_any_unapproved_field() -> None:
    token = _sign(_envelope_payload(), header_extra={"kid": "unexpected-key"})

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=NOW)


def test_future_issued_at_is_rejected_without_clock_skew() -> None:
    token = _sign(_envelope_payload(iat=NOW + 1))

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=NOW)


def test_transport_lifetime_is_bounded_by_engine_policy() -> None:
    token = _sign(
        _envelope_payload(
            iat=NOW - 3_601,
            exp=NOW + 1,
            identity=_identity_payload(exp=NOW + 600),
        )
    )

    with pytest.raises(IdentityTokenError, match="invalid identity token"):
        verify_identity_token(token, config=TEST_CONFIG, now=NOW)
