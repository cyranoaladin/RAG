"""Vérification live LOT42 — chaîne d'attestations de publication (ADR-0033).

``verify_publication_attestation`` réévalue, à chaque appel, les cinq
conditions d'invalidation d'ADR-0033 § 4 : jamais un statut mis en cache.
Une attestation stockée n'est jamais suffisante seule — elle doit toujours
concorder avec l'état courant du contenu, du profil, du manifest, et avec
une revérification live du scope LOT41A référencé et de la revue humaine
finale elle-même (même frontière GitHub, cf.
``ingestion_control.scope_authority``/``_trusted_review``).

Fail-closed : toute absence ou invalidation détectée lève
``PublicationAttestationInvalidError`` — jamais un ``bool`` silencieux.
Une invalidation détectée est aussi persistée au mieux-effort
(``invalidated_at``/``invalidated_reason``, colonnes dédiées accordées au
rôle ``ingestion_control_attestor``) — trace d'audit, jamais la source de
vérité (qui reste toujours la relecture live elle-même).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from nexus_contracts.resource_state import ResourceState

from ._trusted_review import TrustedReviewVerificationError, run_check_github_review
from .scope_authority import ScopeAuthorizationDeniedError, verify_scope_authorization_by_id
from .transitions import TransitionResult, cas_transition


class PublicationAttestationInvalidError(RuntimeError):
    """Aucune chaîne d'attestations de publication valide et revérifiée en
    direct n'existe pour cette ressource — la transition
    REVIEWED -> RETRIEVAL_ELIGIBLE ne doit jamais être tentée."""


@dataclass(frozen=True)
class VerifiedAttestation:
    attestation_id: UUID
    resource_id: UUID
    artifact_id: UUID
    content_sha256: str
    scope_authorization_id: str
    profile_fingerprint: str
    manifest_digest: str


def _load_active_row(conn: psycopg.Connection, *, resource_id: UUID) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT attestation_id, resource_id, artifact_id, content_sha256,
                   scope_authorization_id, profile_fingerprint, manifest_digest,
                   human_review_repository, human_review_pull_request,
                   human_review_head_sha, human_review_challenge
            FROM ingestion_control.publication_attestations
            WHERE resource_id = %s AND invalidated_at IS NULL
            """,
            (resource_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        assert cur.description is not None  # noqa: S101 - row non-None implies description set
        columns = [desc.name for desc in cur.description]
    return dict(zip(columns, row, strict=True))


def _mark_invalidated(
    conn: psycopg.Connection, *, attestation_id: UUID, reason: str
) -> None:
    """Meilleur effort : persiste la raison d'invalidation détectée pour
    audit. N'est jamais la condition de fail-closed elle-même — l'appelant
    lève déjà ``PublicationAttestationInvalidError`` indépendamment de la
    réussite de cette écriture."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_control.publication_attestations
            SET invalidated_at = now(), invalidated_reason = %s
            WHERE attestation_id = %s AND invalidated_at IS NULL
            """,
            (reason, attestation_id),
        )
    conn.commit()


def verify_publication_attestation(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    current_content_sha256: str,
    current_profile_fingerprint: str,
    current_manifest_digest: str,
    repo_root: Path | None = None,
) -> VerifiedAttestation:
    row = _load_active_row(conn, resource_id=resource_id)
    if row is None:
        raise PublicationAttestationInvalidError(
            f"no active (non-invalidated) publication_attestations row for "
            f"resource_id={resource_id!r}"
        )

    if row["content_sha256"] != current_content_sha256:
        _mark_invalidated(conn, attestation_id=row["attestation_id"], reason="content_sha256_drift")
        raise PublicationAttestationInvalidError(
            f"attestation {row['attestation_id']!r} invalidated: content_sha256 "
            f"drift (attested={row['content_sha256']!r}, current={current_content_sha256!r})"
        )
    if row["profile_fingerprint"] != current_profile_fingerprint:
        _mark_invalidated(conn, attestation_id=row["attestation_id"], reason="profile_fingerprint_drift")
        raise PublicationAttestationInvalidError(
            f"attestation {row['attestation_id']!r} invalidated: profile_fingerprint "
            f"drift (attested={row['profile_fingerprint']!r}, current={current_profile_fingerprint!r})"
        )
    if row["manifest_digest"] != current_manifest_digest:
        _mark_invalidated(conn, attestation_id=row["attestation_id"], reason="manifest_digest_drift")
        raise PublicationAttestationInvalidError(
            f"attestation {row['attestation_id']!r} invalidated: manifest_digest "
            f"drift (attested={row['manifest_digest']!r}, current={current_manifest_digest!r})"
        )

    try:
        verify_scope_authorization_by_id(
            conn, authorization_id=row["scope_authorization_id"], repo_root=repo_root
        )
    except ScopeAuthorizationDeniedError as exc:
        _mark_invalidated(
            conn, attestation_id=row["attestation_id"], reason=f"scope_authorization_denied: {exc}"
        )
        raise PublicationAttestationInvalidError(
            f"attestation {row['attestation_id']!r} invalidated: referenced "
            f"scope_authorization_id={row['scope_authorization_id']!r} no longer "
            f"verifies live: {exc}"
        ) from exc

    try:
        payload = run_check_github_review(
            repository=row["human_review_repository"],
            pull_request=row["human_review_pull_request"],
            expected_head=row["human_review_head_sha"],
            repo_root=repo_root,
        )
    except TrustedReviewVerificationError as exc:
        _mark_invalidated(
            conn, attestation_id=row["attestation_id"], reason=f"human_review_denied: {exc}"
        )
        raise PublicationAttestationInvalidError(
            f"attestation {row['attestation_id']!r} invalidated: human_review no "
            f"longer verifies live: {exc}"
        ) from exc

    live_challenges = payload.get("challenges", {})
    if row["human_review_challenge"] not in live_challenges.values():
        _mark_invalidated(
            conn, attestation_id=row["attestation_id"], reason="human_review_challenge_mismatch"
        )
        raise PublicationAttestationInvalidError(
            f"attestation {row['attestation_id']!r} invalidated: stored "
            "human_review_challenge does not match any challenge produced by "
            "the live GitHub verification — possible replay"
        )

    return VerifiedAttestation(
        attestation_id=row["attestation_id"],
        resource_id=row["resource_id"],
        artifact_id=row["artifact_id"],
        content_sha256=row["content_sha256"],
        scope_authorization_id=row["scope_authorization_id"],
        profile_fingerprint=row["profile_fingerprint"],
        manifest_digest=row["manifest_digest"],
    )


def attempt_retrieval_eligible_transition(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    run_id: UUID,
    expected_version: int,
    actor: str,
    current_content_sha256: str,
    current_profile_fingerprint: str,
    current_manifest_digest: str,
    job_id: UUID | None = None,
    repo_root: Path | None = None,
) -> TransitionResult:
    """Point d'ancrage unique LOT42 (ADR-0033 § 6) : la SEULE fonction
    autorisée à faire transitionner une ressource ``REVIEWED ->
    RETRIEVAL_ELIGIBLE``. Vérifie d'abord ``verify_publication_attestation``
    (fail-closed) — la transition n'est jamais tentée si cette vérification
    échoue, et la ressource reste ``REVIEWED`` (état stable, jamais un état
    d'erreur nouveau).

    Non encore appelée par ``ingestion_worker.runner`` dans ce lot : aucune
    ressource n'atteint ``REVIEWED`` dans le pipeline actuel (le pipeline
    s'arrête à ``ROUTED``, cf. ``quality_agent.run_quality_agent`` — les
    états ``STAGED``/``NEEDS_REVIEW``/``REVIEWED`` restent hors périmètre,
    explicitement escaladés). Cette fonction existe et est testée
    indépendamment pour qu'un futur lot qui construit le pipeline jusqu'à
    ``REVIEWED`` n'ait qu'à l'appeler — jamais à réinventer sa propre
    vérification LOT42 ni un second point d'ancrage."""
    verify_publication_attestation(
        conn,
        resource_id=resource_id,
        current_content_sha256=current_content_sha256,
        current_profile_fingerprint=current_profile_fingerprint,
        current_manifest_digest=current_manifest_digest,
        repo_root=repo_root,
    )
    return cas_transition(
        conn,
        resource_id=resource_id,
        expected_state=ResourceState.REVIEWED,
        expected_version=expected_version,
        new_state=ResourceState.RETRIEVAL_ELIGIBLE,
        actor=actor,
        run_id=run_id,
        job_id=job_id,
    )


__all__ = [
    "PublicationAttestationInvalidError",
    "VerifiedAttestation",
    "attempt_retrieval_eligible_transition",
    "verify_publication_attestation",
]
