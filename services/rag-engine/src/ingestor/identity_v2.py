"""Validation de l'identité interne signée transmise par le cockpit."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from fastapi import HTTPException, Request
from nexus_contracts import (
    InternalIdentityEnvelope,
    PilotRetrievalScopeArtifact,
    load_pilot_retrieval_scope,
)
from pydantic import ValidationError


class IdentityTokenError(ValueError):
    """Jeton interne absent, mal formé ou cryptographiquement invalide."""


class IdentityScopeError(ValueError):
    """Enveloppe valide mais hors du scope moteur autoritatif."""


class IdentityConfigurationError(RuntimeError):
    """Configuration d'identité moteur absente ou ambiguë."""


@dataclass(frozen=True)
class IdentityVerifierConfig:
    """Configuration serveur attendue pour le transport d'identité."""

    secret: str = field(repr=False)
    issuer: str
    audience: str
    identity_issuer: str
    identity_audience: str
    artifact: PilotRetrievalScopeArtifact

    def __post_init__(self) -> None:
        required = (
            self.secret,
            self.issuer,
            self.audience,
            self.identity_issuer,
            self.identity_audience,
        )
        if any(not value.strip() for value in required):
            raise IdentityConfigurationError("identity configuration invalid")
        if len(self.secret.encode("utf-8")) < 32:
            raise IdentityConfigurationError("identity configuration invalid")


@dataclass(frozen=True, repr=False)
class VerifiedInternalIdentity:
    """Enveloppe validée liée à l'artefact moteur, sans repr personnelle."""

    envelope: InternalIdentityEnvelope
    artifact: PilotRetrievalScopeArtifact

    @property
    def scope_digest(self) -> str:
        return str(self.envelope.scope_digest)

    def __repr__(self) -> str:
        return f"VerifiedInternalIdentity(scope_digest={self.scope_digest!r})"


def load_identity_verifier_config(
    environ: Mapping[str, str] | None = None,
) -> IdentityVerifierConfig:
    """Charger fail-closed la politique moteur et l'artefact contractuel."""
    source = os.environ if environ is None else environ
    secret = source.get("NEXUS_INTERNAL_TOKEN_SECRET", "")
    return IdentityVerifierConfig(
        secret=secret,
        issuer=source.get("NEXUS_INTERNAL_TOKEN_ISSUER", "").strip(),
        audience=source.get("NEXUS_INTERNAL_TOKEN_AUDIENCE", "").strip(),
        identity_issuer=source.get("NEXUS_SSO_ISSUER", "").strip(),
        identity_audience=source.get("NEXUS_SSO_AUDIENCE", "").strip(),
        artifact=load_pilot_retrieval_scope(),
    )


def _decode_segment(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise IdentityTokenError("invalid identity token") from exc


def _decode_object(value: str) -> dict[str, object]:
    try:
        decoded = json.loads(_decode_segment(value))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IdentityTokenError("invalid identity token") from exc
    if not isinstance(decoded, dict):
        raise IdentityTokenError("invalid identity token")
    return decoded


def verify_identity_token(
    token: str,
    *,
    config: IdentityVerifierConfig,
    now: int | None = None,
) -> VerifiedInternalIdentity:
    """Vérifier la signature HS256 avant d'interpréter les claims."""
    current_time = int(time.time()) if now is None else now
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise IdentityTokenError("invalid identity token") from exc

    try:
        signed = f"{header_segment}.{payload_segment}".encode("ascii")
    except UnicodeEncodeError as exc:
        raise IdentityTokenError("invalid identity token") from exc
    expected = hmac.new(config.secret.encode("utf-8"), signed, hashlib.sha256).digest()
    supplied = _decode_segment(signature_segment)
    if not hmac.compare_digest(supplied, expected):
        raise IdentityTokenError("invalid identity token")
    header = _decode_object(header_segment)
    if header != {"alg": "HS256", "typ": "JWT"}:
        raise IdentityTokenError("invalid identity token")
    payload = _decode_object(payload_segment)
    try:
        envelope = InternalIdentityEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise IdentityTokenError("invalid identity token") from exc
    if envelope.iss != config.issuer or envelope.aud != config.audience:
        raise IdentityTokenError("invalid identity token")
    if envelope.exp <= current_time or envelope.iat > current_time:
        raise IdentityTokenError("invalid identity token")
    identity = envelope.identity
    if (
        identity.iss != config.identity_issuer
        or identity.aud != config.identity_audience
    ):
        raise IdentityTokenError("invalid identity token")
    try:
        config.artifact.validate_envelope(envelope)
    except ValueError as exc:
        raise IdentityScopeError("identity scope forbidden") from exc
    return VerifiedInternalIdentity(envelope=envelope, artifact=config.artifact)


def require_internal_identity(
    request: Request,
    *,
    config: IdentityVerifierConfig | None = None,
    now: int | None = None,
) -> VerifiedInternalIdentity:
    """Exiger le header privé d'identité avant toute configuration ou I/O."""
    token = (request.headers.get("x-nexus-identity") or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if config is None:
        try:
            config = load_identity_verifier_config()
        except (IdentityConfigurationError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail="identity configuration invalid",
            ) from exc
    try:
        return verify_identity_token(token, config=config, now=now)
    except IdentityTokenError as exc:
        raise HTTPException(status_code=401, detail="Unauthorized") from exc
    except IdentityScopeError as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc


__all__ = [
    "IdentityConfigurationError",
    "IdentityScopeError",
    "IdentityTokenError",
    "IdentityVerifierConfig",
    "VerifiedInternalIdentity",
    "load_identity_verifier_config",
    "require_internal_identity",
    "verify_identity_token",
]
