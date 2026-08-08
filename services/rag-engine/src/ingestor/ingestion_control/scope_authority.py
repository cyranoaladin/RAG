"""Vérification live LOT41A — autorité d'autorisation de scope (ADR-0032).

Remédiation revue GATE H1 (items B, C, D, G).

Ce que la première version prouvait — et ce qu'elle ne prouvait pas. Elle
vérifiait séparément (1) qu'une PR/head était ``APPROVED`` et (2) qu'un
fichier local arbitraire décrivait un scope. Elle ne prouvait **jamais**
que l'humain avait approuvé *ces octets-là*, ni que la ligne PostgreSQL
correspondait à ce qui avait été relu. Elle sélectionnait de plus
l'autorisation « la plus récente couvrant le scope » (``ORDER BY
valid_until DESC LIMIT 1``), ce qui laissait une autorisation choisir
implicitement à la place du demandeur.

La chaîne prouvée est désormais complète et sans maillon implicite :

    HEAD revu  ->  blob relu à ce HEAD  ->  digest canonique
               ->  ligne PostgreSQL     ->  contraintes appliquées

1. ``authorization_id`` est **toujours** explicite (item C) — il n'existe
   plus aucune sélection « la plus récente pour ce scope ».
2. Le digest canonique est recalculé (a) depuis les colonnes de la ligne
   stockée et (b) depuis le blob relu en direct au HEAD revu. Les deux
   doivent être égaux au digest stocké — une falsification de l'un ou
   l'autre côté échoue fail-closed (item B).
3. L'évidence GitHub stockée est comparée **champ par champ** à la
   décision live positive — jamais une simple appartenance du challenge à
   un ensemble (item G).
4. Les contraintes de l'autorisation sont **appliquées**, pas seulement
   retournées (item D) : scope exact, digests exacts, fenêtre de validité,
   domaine autorisé, exclusions, PII, catégories de droits.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.scope_authorization import (
    ScopeAuthorizationArtifact,
    ScopeRevocationArtifact,
    authorization_artifact_path,
    authorization_digest,
    revocation_artifact_path,
    revocation_digest,
)
from psycopg.types.json import Jsonb

from .github_authority import (
    GitHubAuthorityError,
    ReviewVerification,
    fetch_blob_at_ref,
    verify_review,
)


class ScopeAuthorizationDeniedError(RuntimeError):
    """Aucune autorisation de scope valide, liée aux octets revus et
    revérifiée en direct, ne couvre cette demande — le worker doit refuser
    de traiter le job, jamais poursuivre en supposant une autorisation
    implicite."""


@dataclass(frozen=True)
class VerifiedAuthorization:
    """Instantané immuable d'une autorisation **vérifiée**, destiné à être
    porté tout au long de l'exécution du job (item D) — jamais rejeté par
    l'appelant après vérification."""

    authorization_id: str
    artifact: ScopeAuthorizationArtifact
    digest: str
    evidence_repository: str
    evidence_pull_request: int
    evidence_head_sha: str

    @property
    def scope(self) -> ResourceScope:
        return self.artifact.scope

    @property
    def allowed_domains(self) -> tuple[str, ...]:
        return tuple(self.artifact.allowed_domains)

    @property
    def rights_categories(self) -> tuple[str, ...]:
        return tuple(self.artifact.rights_categories)

    @property
    def exclusions(self) -> tuple[str, ...]:
        return tuple(self.artifact.exclusions)


_ROW_COLUMNS = (
    "authorization_id", "decision", "protocol_version", "artifact_path",
    "authorization_digest",
    "tenant", "collection", "niveau", "voie", "matiere", "candidat", "audience",
    "visibility", "school_year", "programme_version",
    "manifest_digest", "profile_id", "profile_version", "profile_fingerprint",
    "allowed_domains", "rights_categories", "exclusions",
    "pii_absence_attested", "pii_absence_evidence", "valid_from", "valid_until",
    "evidence_repository", "evidence_pull_request", "evidence_base_sha",
    "evidence_head_sha", "evidence_review_id", "evidence_reviewer",
    "evidence_submitted_at", "evidence_challenge",
)


def _load_row(conn: psycopg.Connection, *, authorization_id: str) -> dict[str, Any]:
    columns = ", ".join(_ROW_COLUMNS)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {columns} FROM ingestion_control.scope_authorizations "  # noqa: S608 - colonnes littérales internes
            "WHERE authorization_id = %s AND revoked_at IS NULL",
            (authorization_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ScopeAuthorizationDeniedError(
            f"no non-revoked scope_authorizations row with "
            f"authorization_id={authorization_id!r}"
        )
    return dict(zip(_ROW_COLUMNS, row, strict=True))


def artifact_from_row(row: dict[str, Any]) -> ScopeAuthorizationArtifact:
    """Reconstruit l'artefact canonique **depuis les colonnes stockées**.

    Le digest de cet objet doit égaler ``row['authorization_digest']`` : une
    colonne falsifiée produit un digest différent et est donc détectée sans
    qu'aucune comparaison champ à champ manuelle ne soit nécessaire."""
    return ScopeAuthorizationArtifact(
        protocol_version="LOT41A-ARTIFACT-V1",
        authorization_id=row["authorization_id"],
        decision="AUTHORIZE_INGESTION_SCOPE",
        scope=ResourceScope(
            tenant=row["tenant"],
            collection=row["collection"],
            niveau=row["niveau"],
            voie=row["voie"],
            matiere=row["matiere"],
            candidat=row["candidat"],
            audience=row["audience"],
            visibility=row["visibility"],
            school_year=row["school_year"],
            programme_version=row["programme_version"],
        ),
        collection=row["collection"],
        manifest_digest=row["manifest_digest"],
        profile_id=row["profile_id"],
        profile_version=row["profile_version"],
        profile_fingerprint=row["profile_fingerprint"],
        allowed_domains=tuple(row["allowed_domains"]),
        rights_categories=tuple(row["rights_categories"]),
        exclusions=tuple(row["exclusions"] or ()),
        pii_absence_attested=row["pii_absence_attested"],
        pii_absence_evidence=row["pii_absence_evidence"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
    )


def parse_authorization_artifact(raw: bytes) -> ScopeAuthorizationArtifact:
    """Parse un artefact relu depuis GitHub. Tout écart de forme (champ
    inconnu, type invalide, protocole inattendu) échoue explicitement —
    ``extra="forbid"`` est ici une garantie, pas une commodité."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScopeAuthorizationDeniedError(
            f"authorization artifact is not valid UTF-8 JSON: {exc}"
        ) from exc
    try:
        return ScopeAuthorizationArtifact.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - frontière de validation volontaire
        raise ScopeAuthorizationDeniedError(
            f"authorization artifact does not satisfy the canonical contract: {exc}"
        ) from exc


def _compare_evidence_field_by_field(
    row: dict[str, Any], live: ReviewVerification
) -> None:
    """Item G : chaque champ de l'évidence stockée doit correspondre
    **exactement** à la décision live positive. Une simple appartenance du
    challenge à ``challenges.values()`` ne prouvait pas que l'évidence
    stockée représentait *cette* review — seulement qu'un challenge
    plausible existait quelque part."""
    if not live.approved:
        raise ScopeAuthorizationDeniedError(
            f"live GitHub review is not approved (reason={live.reason!r})"
        )
    mismatches: list[str] = []
    stored_submitted_at = row["evidence_submitted_at"]
    live_submitted_at = (
        datetime.fromisoformat(live.submitted_at.replace("Z", "+00:00"))
        if live.submitted_at
        else None
    )
    for label, stored, observed in (
        ("repository", row["evidence_repository"], live.repository),
        ("pull_request", int(row["evidence_pull_request"]), live.pull_request),
        ("base_sha", row["evidence_base_sha"], live.base_sha),
        ("head_sha", row["evidence_head_sha"], live.head_sha),
        ("review_id", int(row["evidence_review_id"]), live.review_id),
        ("reviewer", row["evidence_reviewer"], live.reviewer),
        ("submitted_at", stored_submitted_at, live_submitted_at),
        ("challenge", row["evidence_challenge"], live.challenge),
    ):
        if stored != observed:
            mismatches.append(f"{label} (stored={stored!r}, live={observed!r})")
    if mismatches:
        raise ScopeAuthorizationDeniedError(
            "stored GitHub evidence does not match the live approving review "
            f"field by field: {'; '.join(mismatches)}"
        )


def verify_scope_authorization_by_id(
    conn: psycopg.Connection, *, authorization_id: str, now: datetime | None = None
) -> VerifiedAuthorization:
    """Vérifie **exactement** l'autorisation demandée. Fail-closed.

    Aucune sélection implicite : l'appelant nomme toujours l'autorisation
    (item C). Aucune confiance dans l'état stocké seul : le digest est
    revalidé des deux côtés (item B) et l'évidence est comparée champ par
    champ à la review live (item G)."""
    row = _load_row(conn, authorization_id=authorization_id)

    # (a) Cohérence interne de la ligne : le digest stocké doit être celui
    # des colonnes stockées. Détecte toute falsification d'une colonne.
    artifact_from_db = artifact_from_row(row)
    digest_from_db = authorization_digest(artifact_from_db)
    stored_digest = row["authorization_digest"]
    if digest_from_db != stored_digest:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} row is internally inconsistent: "
            f"canonical digest of stored columns is {digest_from_db}, but the "
            f"stored authorization_digest is {stored_digest} — a stored column "
            "has been tampered with"
        )

    expected_path = authorization_artifact_path(authorization_id)
    if row["artifact_path"] != expected_path:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} artifact_path is "
            f"{row['artifact_path']!r}, expected the canonical {expected_path!r}"
        )

    # (b) Fenêtre de validité — appliquée, jamais seulement retournée.
    current = now if now is not None else datetime.now(UTC)
    if current < row["valid_from"]:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} is not yet valid "
            f"(valid_from={row['valid_from']!r}, now={current!r})"
        )
    if current >= row["valid_until"]:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} expired at {row['valid_until']!r} "
            f"(now={current!r})"
        )

    # (c) Review live, comparée champ par champ (item G).
    try:
        live = verify_review(
            repository=row["evidence_repository"],
            pull_request=int(row["evidence_pull_request"]),
            expected_head=row["evidence_head_sha"],
        )
    except GitHubAuthorityError as exc:
        raise ScopeAuthorizationDeniedError(
            f"live GitHub verification failed for authorization "
            f"{authorization_id!r}: {exc}"
        ) from exc
    _compare_evidence_field_by_field(row, live)

    # (d) Liaison aux octets revus : le blob relu au HEAD approuvé doit
    # produire exactement le digest stocké (item B).
    try:
        blob = fetch_blob_at_ref(
            repository=row["evidence_repository"],
            path=expected_path,
            ref=row["evidence_head_sha"],
        )
    except GitHubAuthorityError as exc:
        raise ScopeAuthorizationDeniedError(
            f"cannot re-read the reviewed authorization artifact for "
            f"{authorization_id!r}: {exc}"
        ) from exc
    artifact_from_github = parse_authorization_artifact(blob)
    digest_from_github = authorization_digest(artifact_from_github)
    if digest_from_github != stored_digest:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} is not bound to the reviewed "
            f"bytes: the artifact at {expected_path}@{row['evidence_head_sha']} "
            f"digests to {digest_from_github}, stored digest is {stored_digest}"
        )

    return VerifiedAuthorization(
        authorization_id=authorization_id,
        artifact=artifact_from_github,
        digest=stored_digest,
        evidence_repository=row["evidence_repository"],
        evidence_pull_request=int(row["evidence_pull_request"]),
        evidence_head_sha=row["evidence_head_sha"],
    )


# ---------------------------------------------------------------------------
# Application des contraintes (item D)
# ---------------------------------------------------------------------------


def assert_authorization_covers_scope(
    verified: VerifiedAuthorization,
    *,
    scope: ResourceScope,
    manifest_digest: str,
    profile_id: str,
    profile_version: str,
    profile_fingerprint: str,
) -> None:
    """Le scope et l'identité de profil demandés doivent correspondre
    **exactement** à ceux autorisés — jamais « compatibles », jamais un
    sous-ensemble deviné."""
    artifact = verified.artifact
    if scope != artifact.scope:
        raise ScopeAuthorizationDeniedError(
            f"requested scope does not exactly match the scope authorized by "
            f"{verified.authorization_id!r}"
        )
    for label, requested, authorized in (
        ("manifest_digest", manifest_digest, artifact.manifest_digest),
        ("profile_id", profile_id, artifact.profile_id),
        ("profile_version", profile_version, artifact.profile_version),
        ("profile_fingerprint", profile_fingerprint, artifact.profile_fingerprint),
    ):
        if requested != authorized:
            raise ScopeAuthorizationDeniedError(
                f"{label} mismatch against authorization "
                f"{verified.authorization_id!r}: requested={requested!r}, "
                f"authorized={authorized!r}"
            )


def _hostname(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().strip(".")
    if not host:
        raise ScopeAuthorizationDeniedError(f"cannot extract a hostname from {url!r}")
    return host


def assert_url_within_allowed_domains(
    verified: VerifiedAuthorization, *, url: str, label: str = "url"
) -> None:
    """Le hostname doit être un domaine autorisé, ou un sous-domaine strict
    de celui-ci. Jamais une comparaison de sous-chaîne (``evil-eduscol.
    education.fr.attacker.com`` ne doit jamais passer)."""
    host = _hostname(url)
    for allowed in verified.allowed_domains:
        candidate = allowed.lower().strip(".")
        if host == candidate or host.endswith(f".{candidate}"):
            return
    raise ScopeAuthorizationDeniedError(
        f"{label} host {host!r} is not within the domains authorized by "
        f"{verified.authorization_id!r}: {list(verified.allowed_domains)}"
    )


def assert_rights_category_allowed(
    verified: VerifiedAuthorization, *, rights_status: str
) -> None:
    """Second point d'application LOT41A (item D) : la catégorie de droits
    réellement constatée par ``RightsAgent`` doit être autorisée. Ne peut
    par construction pas être vérifiée avant que RightsAgent n'ait produit
    son résultat — d'où ce point de contrôle distinct, appelé plus tard
    dans la chaîne."""
    if rights_status not in verified.rights_categories:
        raise ScopeAuthorizationDeniedError(
            f"rights category {rights_status!r} is not authorized by "
            f"{verified.authorization_id!r} (allowed: "
            f"{list(verified.rights_categories)})"
        )


def assert_not_excluded(verified: VerifiedAuthorization, *, markers: tuple[str, ...]) -> None:
    """Les exclusions déclarées dans l'artefact revu sont appliquées : tout
    marqueur constaté qui figure dans ``exclusions`` refuse la ressource."""
    for marker in markers:
        if marker in verified.exclusions:
            raise ScopeAuthorizationDeniedError(
                f"marker {marker!r} is explicitly excluded by authorization "
                f"{verified.authorization_id!r}"
            )


def assert_pii_rule(verified: VerifiedAuthorization, *, pii_detected: bool) -> None:
    """L'artefact atteste l'absence de PII (invariant du contrat). Une PII
    effectivement détectée contredit donc l'autorisation : refus."""
    if pii_detected:
        raise ScopeAuthorizationDeniedError(
            f"PII was detected although authorization {verified.authorization_id!r} "
            "attests PII absence — refusing, never ingesting under a contradicted "
            "attestation"
        )


# ---------------------------------------------------------------------------
# Journalisation d'audit
# ---------------------------------------------------------------------------


def record_scope_authorization_denied(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    job_id: UUID,
    actor: str,
    reason: str,
    authorization_id: str | None = None,
) -> UUID:
    """Journalise un refus d'autorisation de scope dans
    ``ingestion_control.workflow_events`` (schéma générique LOT44b, aucune
    nouvelle table). Ne committe pas — responsabilité de l'appelant."""
    payload: dict[str, object] = {"reason": reason}
    if authorization_id is not None:
        payload["authorization_id"] = authorization_id
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
    "artifact_from_row",
    "assert_authorization_covers_scope",
    "assert_not_excluded",
    "assert_pii_rule",
    "assert_rights_category_allowed",
    "assert_url_within_allowed_domains",
    "parse_authorization_artifact",
    "record_scope_authorization_denied",
    "revocation_artifact_path",
    "revocation_digest",
    "ScopeRevocationArtifact",
    "verify_scope_authorization_by_id",
]
