"""Vérifie localement la projection canonique de scope d'une release.

L'adaptateur consomme le snapshot de profils déjà vérifié par le gate de
``rag-engine``. Il n'importe jamais le plan de contrôle ``rag-pedago``.
"""

from __future__ import annotations

from nexus_contracts.authorization_set import (
    AuthorizationSetError,
    ReleaseScopePlacementV1,
    VerifiedProfileFactV1,
    parse_release_scope_placement,
    scope_digest,
)

from ingestor.ingestion_profiles.registry import profile_fingerprint
from ingestor.ingestion_profiles.startup_gate import StartupGateResult


class ReleaseScopePlacementVerificationError(ValueError):
    """La projection ne correspond pas au snapshot local de profils."""


def _fail(code: str, detail: str) -> ReleaseScopePlacementVerificationError:
    return ReleaseScopePlacementVerificationError(f"{code}: {detail}")


def verified_profile_facts(
    gate: StartupGateResult,
) -> tuple[VerifiedProfileFactV1, ...]:
    """Projette les profils du snapshot vérifié en faits de contrat purs."""
    facts: list[VerifiedProfileFactV1] = []
    for (collection, profile_version), profile in sorted(gate.registry.items()):
        if not profile.enabled:
            raise _fail(
                "PROFILE_DISABLED",
                f"profile {(collection, profile_version)!r} is disabled",
            )
        facts.append(
            VerifiedProfileFactV1(
                profile_id=collection,
                profile_version=profile_version,
                profile_fingerprint=profile_fingerprint(profile),
                scope=profile.scope,
            )
        )
    return tuple(facts)


def verify_release_scope_placement(
    *,
    raw: bytes,
    expected_digest: str,
    expected_profile_manifest_digest: str,
    gate: StartupGateResult,
) -> ReleaseScopePlacementV1:
    """Compare octets, digest, manifeste et scopes au snapshot du runtime."""
    try:
        placement = parse_release_scope_placement(raw)
    except AuthorizationSetError as exc:
        raise _fail("INVALID_PLACEMENT", str(exc)) from exc
    if placement.digest() != expected_digest:
        raise _fail(
            "PLACEMENT_DIGEST_MISMATCH",
            f"expected {expected_digest}, got {placement.digest()}",
        )
    actual_profile_manifest = gate.manifest.manifest_fingerprint
    if (
        placement.profile_manifest_digest != expected_profile_manifest_digest
        or actual_profile_manifest != expected_profile_manifest_digest
    ):
        raise _fail(
            "PROFILE_MANIFEST_MISMATCH",
            "placement, expected digest and verified runtime manifest differ",
        )

    profiles = {
        (fact.profile_id, fact.profile_version): fact for fact in verified_profile_facts(gate)
    }
    for entry in placement.placements:
        profile = profiles.get((entry.profile_id, entry.profile_version))
        if profile is None:
            raise _fail(
                "UNKNOWN_PROFILE",
                f"placement names {(entry.profile_id, entry.profile_version)!r}",
            )
        if entry.profile_fingerprint != profile.profile_fingerprint:
            raise _fail(
                "PROFILE_FINGERPRINT_MISMATCH",
                f"profile {entry.profile_id!r} content drifted",
            )
        if scope_digest(entry.scope) != scope_digest(profile.scope):
            raise _fail(
                "PROFILE_SCOPE_MISMATCH",
                f"content {entry.content_sha256} differs from profile scope",
            )
    return placement


__all__ = [
    "ReleaseScopePlacementVerificationError",
    "verified_profile_facts",
    "verify_release_scope_placement",
]
