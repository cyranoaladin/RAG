"""Vérification live LOT41A — autorité d'autorisation de scope (ADR-0032).

``verify_scope_authorization`` ne fait jamais confiance à une ligne
PostgreSQL stockée seule : elle relit systématiquement, en direct, la
review GitHub d'approbation embarquée (``evidence``) via
``scripts/github/trusted_human_review_github.check_github_review`` (racine
du dépôt, propriété d'aucun service — invoqué par sous-processus plutôt
qu'importé, cf. AGENTS.md : « un service n'importe jamais directement le
code d'un autre service »). Une ligne stockée qui affirme une autorisation
valide n'est jamais suffisante à elle seule : si la review GitHub sous-
jacente a été dismissée, si le HEAD a changé, ou si le challenge ne
correspond plus, la vérification échoue explicitement même si
``scope_authorizations`` contient une ligne non révoquée et non expirée.
C'est cette double vérification (stockage + relecture live) qui rend la
révocation réelle (ADR-0032 § 4).

Fail-closed : toute absence, expiration, révocation, ou échec de
revérification live lève ``ScopeAuthorizationDeniedError`` — jamais un
``None`` silencieux.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import ResourceScope
from psycopg.types.json import Jsonb

from ._trusted_review import TrustedReviewVerificationError, run_check_github_review


class ScopeAuthorizationDeniedError(RuntimeError):
    """Aucune autorisation de scope valide et revérifiée en direct n'existe
    pour ce scope — le worker doit refuser de traiter le job, jamais
    poursuivre en supposant une autorisation implicite."""


@dataclass(frozen=True)
class VerifiedAuthorization:
    authorization_id: str
    scope: ResourceScope
    manifest_digest: str
    profile_id: str
    profile_version: str
    profile_fingerprint: str
    allowed_domains: tuple[str, ...]
    rights_categories: tuple[str, ...]
    exclusions: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    evidence_repository: str
    evidence_pull_request: int
    evidence_head_sha: str


def _run_check_github_review(
    *, repository: str, pull_request: int, expected_head: str, repo_root: Path | None
) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = run_check_github_review(
            repository=repository,
            pull_request=pull_request,
            expected_head=expected_head,
            repo_root=repo_root,
        )
    except TrustedReviewVerificationError as exc:
        raise ScopeAuthorizationDeniedError(str(exc)) from exc
    return payload


def _load_latest_row(conn: psycopg.Connection, *, scope: ResourceScope) -> dict[str, Any] | None:
    sorted_audience = sorted(a.value if hasattr(a, "value") else str(a) for a in scope.audience)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT authorization_id, tenant, collection, niveau, voie, matiere,
                   candidat, audience, visibility, school_year, programme_version,
                   manifest_digest, profile_id, profile_version, profile_fingerprint,
                   allowed_domains, rights_categories, exclusions,
                   valid_from, valid_until,
                   evidence_repository, evidence_pull_request, evidence_base_sha,
                   evidence_head_sha, evidence_review_id, evidence_reviewer,
                   evidence_submitted_at, evidence_challenge
            FROM ingestion_control.scope_authorizations
            WHERE collection = %s AND tenant = %s AND niveau = %s AND voie = %s
              AND matiere = %s AND candidat = %s AND visibility = %s
              AND school_year = %s AND programme_version = %s
              AND audience = %s
              AND revoked_at IS NULL
            ORDER BY valid_until DESC
            LIMIT 1
            """,
            (
                scope.collection, scope.tenant, scope.niveau, scope.voie,
                scope.matiere, scope.candidat, scope.visibility,
                scope.school_year, scope.programme_version, sorted_audience,
            ),
        )
        row = cur.fetchone()
        if row is None:
            return None
        assert cur.description is not None  # noqa: S101 - row non-None implies description set
        columns = [desc.name for desc in cur.description]
    return dict(zip(columns, row, strict=True))


def _verify_row(
    row: dict[str, Any], *, scope: ResourceScope, repo_root: Path | None
) -> VerifiedAuthorization:
    now = datetime.now(UTC)
    if now >= row["valid_until"]:
        raise ScopeAuthorizationDeniedError(
            f"authorization {row['authorization_id']!r} expired at "
            f"{row['valid_until']!r} (now={now!r})"
        )

    payload = _run_check_github_review(
        repository=row["evidence_repository"],
        pull_request=row["evidence_pull_request"],
        expected_head=row["evidence_head_sha"],
        repo_root=repo_root,
    )
    live_challenges = payload.get("challenges", {})
    if row["evidence_challenge"] not in live_challenges.values():
        raise ScopeAuthorizationDeniedError(
            f"stored evidence_challenge for authorization "
            f"{row['authorization_id']!r} does not match any challenge "
            "produced by the live GitHub verification — possible replay of "
            "a stale/dismissed evidence"
        )

    return VerifiedAuthorization(
        authorization_id=row["authorization_id"],
        scope=scope,
        manifest_digest=row["manifest_digest"],
        profile_id=row["profile_id"],
        profile_version=row["profile_version"],
        profile_fingerprint=row["profile_fingerprint"],
        allowed_domains=tuple(row["allowed_domains"]),
        rights_categories=tuple(row["rights_categories"]),
        exclusions=tuple(row["exclusions"]),
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        evidence_repository=row["evidence_repository"],
        evidence_pull_request=row["evidence_pull_request"],
        evidence_head_sha=row["evidence_head_sha"],
    )


def verify_scope_authorization(
    conn: psycopg.Connection, *, scope: ResourceScope, repo_root: Path | None = None
) -> VerifiedAuthorization:
    """Vérifie, en direct, qu'une autorisation de scope valide couvre
    ``scope``. Lève ``ScopeAuthorizationDeniedError`` fail-closed sur toute
    absence, expiration, ou échec de revérification GitHub live — jamais un
    résultat positif basé uniquement sur l'état stocké."""
    row = _load_latest_row(conn, scope=scope)
    if row is None:
        raise ScopeAuthorizationDeniedError(
            f"no non-revoked scope_authorizations row matches scope "
            f"(collection={scope.collection!r}, tenant={scope.tenant!r})"
        )
    return _verify_row(row, scope=scope, repo_root=repo_root)


def verify_scope_authorization_by_id(
    conn: psycopg.Connection, *, authorization_id: str, repo_root: Path | None = None
) -> VerifiedAuthorization:
    """Même vérification live que ``verify_scope_authorization``, mais par
    identifiant direct — utilisé par LOT42
    (``publication_attestation.verify_publication_attestation``) pour
    revérifier le scope référencé par une attestation existante, sans
    reconstruire un ``ResourceScope`` complet côté appelant."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT authorization_id, tenant, collection, niveau, voie, matiere,
                   candidat, audience, visibility, school_year, programme_version,
                   manifest_digest, profile_id, profile_version, profile_fingerprint,
                   allowed_domains, rights_categories, exclusions,
                   valid_from, valid_until,
                   evidence_repository, evidence_pull_request, evidence_base_sha,
                   evidence_head_sha, evidence_review_id, evidence_reviewer,
                   evidence_submitted_at, evidence_challenge
            FROM ingestion_control.scope_authorizations
            WHERE authorization_id = %s AND revoked_at IS NULL
            """,
            (authorization_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ScopeAuthorizationDeniedError(
                f"no non-revoked scope_authorizations row with "
                f"authorization_id={authorization_id!r}"
            )
        assert cur.description is not None  # noqa: S101 - row non-None implies description set
        columns = [desc.name for desc in cur.description]
    row_dict = dict(zip(columns, row, strict=True))

    scope = ResourceScope(
        tenant=row_dict["tenant"],
        collection=row_dict["collection"],
        niveau=row_dict["niveau"],
        voie=row_dict["voie"],
        matiere=row_dict["matiere"],
        candidat=row_dict["candidat"],
        audience=row_dict["audience"],
        visibility=row_dict["visibility"],
        school_year=row_dict["school_year"],
        programme_version=row_dict["programme_version"],
    )
    # Vérifie exactement la ligne référencée par authorization_id — jamais
    # une délégation à verify_scope_authorization(scope=...), qui pourrait
    # silencieusement sélectionner une AUTRE autorisation plus récente
    # couvrant le même scope si plusieurs existent (cf. valid_until DESC
    # dans _load_latest_row). Une attestation LOT42 référence une
    # autorisation précise ; c'est celle-là, et aucune autre, qui doit être
    # revérifiée en direct ici.
    return _verify_row(row_dict, scope=scope, repo_root=repo_root)


def record_scope_authorization_denied(
    conn: psycopg.Connection, *, run_id: UUID, job_id: UUID, actor: str, reason: str
) -> UUID:
    """Journalise un refus d'autorisation de scope dans
    ``ingestion_control.workflow_events`` (même table/convention que
    ``ingestion_profiles.events.record_validation_result`` — schéma
    générique LOT44b, aucune nouvelle table). Ne committe pas — même
    convention que les primitives LOT44b/44c, responsabilité de
    l'appelant (ADR-0032 § 6)."""
    payload: dict[str, object] = {"reason": reason}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.workflow_events
                (run_id, job_id, resource_id, event_type, from_state, to_state, actor, payload)
            VALUES (%s, %s, NULL, %s, NULL, NULL, %s, %s)
            RETURNING event_id
            """,
            (run_id, job_id, "SCOPE_AUTHORIZATION_DENIED", actor, Jsonb(payload)),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - INSERT ... RETURNING toujours une ligne
            raise RuntimeError("workflow_events insert did not return event_id")
        event_id: UUID = row[0]
        return event_id


__all__ = [
    "ScopeAuthorizationDeniedError",
    "VerifiedAuthorization",
    "record_scope_authorization_denied",
    "verify_scope_authorization",
    "verify_scope_authorization_by_id",
]
