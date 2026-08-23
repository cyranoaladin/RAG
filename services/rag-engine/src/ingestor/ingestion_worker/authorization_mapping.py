"""Lookups immuables d'autorité pour une release multi-scope vérifiée.

Le digest attendu vient du manifeste de readiness signé. Ce module ne lit
aucun fichier, ne cherche jamais une autorisation « récente » et ne crée
aucune nouvelle source de vérité : il projette uniquement les octets
canoniques de ``AuthorizationSetV1`` en deux fonctions totales sur l'union
de release.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from nexus_contracts.authorization_set import (
    AuthorizationSetError,
    content_set_digest,
    parse_authorization_set,
    scope_digest,
)
from nexus_contracts.ingestion import ResourceScope

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AuthorizationMappingError(ValueError):
    """Le set signé ne permet pas un lookup exact et non ambigu."""


def _require_digest(value: str, *, label: str) -> str:
    if _HEX64.fullmatch(value) is None:
        raise AuthorizationMappingError(f"{label} must be a lowercase SHA-256 digest")
    return value


_FACTORY_TOKEN = object()


@dataclass(frozen=True, init=False)
class AuthorizationMapping:
    """Projection sans alias mutable d'un ``AuthorizationSetV1`` authentifié."""

    authorization_set_digest: str
    authority_required_count: int
    authority_required_set_sha256: str
    content_authorization_ids: tuple[tuple[str, str], ...]
    scope_authorization_ids: tuple[tuple[str, str], ...]
    authorization_digests: tuple[tuple[str, str], ...]
    profile_manifest_digest: str

    def __init__(
        self,
        *,
        authorization_set_digest: str,
        authority_required_count: int,
        authority_required_set_sha256: str,
        content_authorization_ids: tuple[tuple[str, str], ...],
        scope_authorization_ids: tuple[tuple[str, str], ...],
        authorization_digests: tuple[tuple[str, str], ...] = (),
        profile_manifest_digest: str = "",
        _factory_token: object | None = None,
    ) -> None:
        if _factory_token is not _FACTORY_TOKEN:
            raise AuthorizationMappingError(
                "AuthorizationMapping is factory-only; use build_authorization_mapping"
            )
        object.__setattr__(self, "authorization_set_digest", authorization_set_digest)
        object.__setattr__(self, "authority_required_count", authority_required_count)
        object.__setattr__(
            self, "authority_required_set_sha256", authority_required_set_sha256
        )
        object.__setattr__(self, "content_authorization_ids", content_authorization_ids)
        object.__setattr__(self, "scope_authorization_ids", scope_authorization_ids)
        object.__setattr__(self, "authorization_digests", authorization_digests)
        object.__setattr__(self, "profile_manifest_digest", profile_manifest_digest)

    def authorization_digest(self, authorization_id: str) -> str:
        for candidate, digest in self.authorization_digests:
            if candidate == authorization_id:
                return digest
        raise AuthorizationMappingError(
            f"unknown authorization_id {authorization_id!r} in the signed authorization set"
        )

    def authorization_id_for_content(self, content_sha256: str) -> str:
        """Retourne l'unique autorisation couvrant les octets téléchargés."""
        _require_digest(content_sha256, label="content_sha256")
        for candidate, authorization_id in self.content_authorization_ids:
            if candidate == content_sha256:
                return authorization_id
        raise AuthorizationMappingError(
            f"unknown content_sha256 {content_sha256!r} in the signed authorization set"
        )

    def authorization_id_for_scope(self, scope: ResourceScope) -> str:
        """Résout avant fetch le scope canonique du job, jamais un wildcard."""
        return self.authorization_id_for_scope_digest(scope_digest(scope))

    def authorization_id_for_scope_digest(self, canonical_scope_digest: str) -> str:
        """Retourne l'unique membre ayant exactement ce digest de scope."""
        _require_digest(canonical_scope_digest, label="scope_digest")
        for candidate, authorization_id in self.scope_authorization_ids:
            if candidate == canonical_scope_digest:
                return authorization_id
        raise AuthorizationMappingError(
            f"unknown scope_digest {canonical_scope_digest!r} in the signed authorization set"
        )


def build_authorization_mapping(
    *,
    authorization_set_bytes: bytes | bytearray,
    expected_authorization_set_digest: str,
    authority_required_content_sha256: Sequence[str],
) -> AuthorizationMapping:
    """Valide l'identité signée et l'union réelle avant tout lookup.

    ``expected_authorization_set_digest`` est la valeur scellée par readiness.
    La liste requise est l'artefact Tier A figé. Leur vérification conjointe
    empêche qu'un set intrinsèquement cohérent mais incomplet devienne une
    autorité par simple auto-déclaration.
    """
    expected_digest = _require_digest(
        expected_authorization_set_digest,
        label="expected_authorization_set_digest",
    )
    raw = bytes(authorization_set_bytes)
    actual_digest = sha256(raw).hexdigest()
    if actual_digest != expected_digest:
        raise AuthorizationMappingError(
            "authorization set digest mismatch "
            f"(expected={expected_digest}, actual={actual_digest})"
        )

    try:
        authorization_set = parse_authorization_set(raw)
    except AuthorizationSetError as exc:
        raise AuthorizationMappingError(str(exc)) from exc

    required = tuple(authority_required_content_sha256)
    if len(required) != len(set(required)):
        raise AuthorizationMappingError("authority-required set repeats content")
    if any(_HEX64.fullmatch(value) is None for value in required):
        raise AuthorizationMappingError(
            "authority-required set contains a non-canonical content SHA-256"
        )

    owners = tuple(
        sorted(
            (content, member.authorization_id)
            for member in authorization_set.members
            for content in member.allowed_content_sha256
        )
    )
    owner_contents = {content for content, _ in owners}
    required_contents = set(required)
    gap = sorted(required_contents - owner_contents)
    extra = sorted(owner_contents - required_contents)
    if gap:
        raise AuthorizationMappingError(f"authorization union has a gap: {gap!r}")
    if extra:
        raise AuthorizationMappingError(f"authorization union has extra content: {extra!r}")

    required_digest = content_set_digest(required_contents)
    if authorization_set.authority_required_count != len(required_contents):
        raise AuthorizationMappingError("authority_required_count mismatch")
    if authorization_set.authority_required_set_sha256 != required_digest:
        raise AuthorizationMappingError("authority_required_set_sha256 mismatch")

    scope_owners = tuple(
        sorted(
            (member.scope_digest, member.authorization_id)
            for member in authorization_set.members
        )
    )
    if len({value for value, _ in scope_owners}) != len(scope_owners):
        raise AuthorizationMappingError("authorization set has an ambiguous scope")

    return AuthorizationMapping(
        authorization_set_digest=actual_digest,
        authority_required_count=len(required_contents),
        authority_required_set_sha256=required_digest,
        content_authorization_ids=owners,
        scope_authorization_ids=scope_owners,
        authorization_digests=tuple(
            (member.authorization_id, member.authorization_digest)
            for member in authorization_set.members
        ),
        profile_manifest_digest=authorization_set.profile_manifest_digest,
        _factory_token=_FACTORY_TOKEN,
    )


__all__ = [
    "AuthorizationMapping",
    "AuthorizationMappingError",
    "build_authorization_mapping",
]
