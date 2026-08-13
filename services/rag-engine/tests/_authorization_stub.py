"""Autorisation LOT41A vérifiée, fabriquée pour les tests **qui ne portent
pas sur la frontière GitHub elle-même**.

Reconstruire une PR approuvée, un blob Git et une review réelle dans chaque
suite qui traverse le worker serait à la fois coûteux et trompeur : ces
suites testent Scout→QualityAgent, pas l'autorité. Elles injectent donc un
``verify_scope_authorization`` qui rend une ``VerifiedAuthorization``
préfabriquée.

**Ce que cela ne dispense jamais de faire.** L'autorisation rendue ici est
*cohérente avec le job* : mêmes domaines, mêmes droits, même empreinte de
profil, même digest de manifest. Les points de contrôle d'enforcement
(item D) s'exécutent donc réellement dans ces suites — un job qui sortirait
du périmètre y échouerait, exactement comme en production. Seule la
relecture GitHub est court-circuitée, et elle est couverte par ses propres
suites dédiées (``test_lot41a_scope_authority.py``,
``test_lot41a_github_authority_transport.py``,
``test_lot41a_docker_authority_e2e.py``).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import psycopg
from nexus_contracts.ingestion import ResourceScope

from ingestor.ingestion_control.scope_authority import VerifiedAuthorization

STUB_AUTHORIZATION_ID = "auth-test-stub-0001"


def verified_authorization(
    *,
    scope: ResourceScope | dict[str, Any],
    manifest_digest: str,
    profile_id: str,
    profile_version: str,
    profile_fingerprint: str,
    allowed_domains: tuple[str, ...] = ("eduscol.education.fr",),
    rights_categories: tuple[str, ...] = ("officiel_public", "public_allowed"),
    exclusions: tuple[str, ...] = (),
    protocol_version: Literal["LOT41A-V1", "LOT41A-V2"] = "LOT41A-V1",
    allowed_content_sha256: tuple[str, ...] | None = None,
    authorization_id: str = STUB_AUTHORIZATION_ID,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> VerifiedAuthorization:
    now = datetime.now(UTC)
    if protocol_version == "LOT41A-V1" and allowed_content_sha256 is not None:
        raise ValueError("LOT41A-V1 test authorization must not carry a content allowlist")
    if protocol_version == "LOT41A-V2" and not allowed_content_sha256:
        raise ValueError("LOT41A-V2 test authorization requires a content allowlist")
    if protocol_version not in {"LOT41A-V1", "LOT41A-V2"}:
        raise ValueError(f"unsupported test authorization protocol {protocol_version!r}")
    resolved = scope if isinstance(scope, ResourceScope) else ResourceScope.model_validate(scope)
    return VerifiedAuthorization(
        authorization_id=authorization_id,
        scope=resolved,
        manifest_digest=manifest_digest,
        profile_id=profile_id,
        profile_version=profile_version,
        profile_fingerprint=profile_fingerprint,
        allowed_domains=allowed_domains,
        rights_categories=rights_categories,
        exclusions=exclusions,
        pii_absence_attested=True,
        valid_from=valid_from or (now - timedelta(days=1)),
        valid_until=valid_until or (now + timedelta(days=365)),
        artifact_path=f"governance/authorizations/{authorization_id}.json",
        artifact_blob_sha="0" * 40,
        authorization_digest="0" * 64,
        evidence_repository="cyranoaladin/RAG",
        evidence_pull_request=1,
        evidence_base_sha="1" * 40,
        evidence_head_sha="2" * 40,
        evidence_review_id=1,
        evidence_reviewer="abenrhouma",
        evidence_challenge="NEXUS-TRUSTED-REVIEW-V1:" + "0" * 64,
        verified_at=now,
        protocol_version=protocol_version,
        allowed_content_sha256=allowed_content_sha256,
    )


def stub_verifier(authorization: VerifiedAuthorization) -> Any:
    """Vérificateur injectable qui rend toujours ``authorization`` — mais
    seulement si le job la nomme réellement. Un job qui référencerait un
    autre ``authorization_id`` échoue ici comme en production."""

    def verify(
        conn: psycopg.Connection,
        *,
        authorization_id: str,
        scope: ResourceScope | None = None,
        now: datetime | None = None,
    ) -> VerifiedAuthorization:
        from ingestor.ingestion_control.scope_authority import (
            ScopeAuthorizationDeniedError,
        )

        if authorization_id != authorization.authorization_id:
            raise ScopeAuthorizationDeniedError(
                f"no scope_authorizations row with authorization_id={authorization_id!r}"
            )
        return authorization

    return verify


__all__ = ["STUB_AUTHORIZATION_ID", "stub_verifier", "verified_authorization"]
