"""Vérification live LOT41A — autorité d'autorisation de scope (ADR-0032).

Remédiation GATE H1, items **B**, **C** et **G**.

Une ligne PostgreSQL n'est jamais une autorisation. Elle n'est qu'un
*index* vers la seule chose qui en soit une : des octets précis, à un
chemin canonique précis, dans un commit précis, qu'un humain de confiance
a approuvé sur GitHub. ``verify_scope_authorization`` refait la chaîne
entière à chaque usage :

    authorization_id explicite (jamais « la plus récente »)
      -> ligne PostgreSQL exacte
      -> review GitHub relue en direct, comparée **champ par champ**
      -> blob Git relu au head approuvé exact, au chemin canonique exact
      -> parse canonique + digest recalculé intégralement
      -> égalité champ par champ artefact ↔ ligne PostgreSQL

Chacune de ces cinq étapes peut refuser seule. Un seul octet, un seul
champ, un seul identifiant de review qui diverge suffit à échouer — c'est
ce qui empêche qu'une review portant sur un scope étroit autorise en fait
un scope large, et qu'une ligne modifiée directement en base survive à sa
propre relecture.

**Pourquoi ``authorization_id`` est obligatoire (item C).** Sélectionner
« l'autorisation la plus récente couvrant ce scope » ferait d'une écriture
en base une décision d'autorité : enregistrer une autorisation large plus
tardive suffirait à élargir silencieusement un job déjà planifié. Un job
est lié à **une** autorisation nommée ; plusieurs autorisations
historiques peuvent coexister pour un même scope sans qu'aucune ne
supplante l'autre.

Fail-closed : toute absence, expiration, révocation, divergence ou échec
de revérification live lève ``ScopeAuthorizationDeniedError`` — jamais un
``None`` silencieux, jamais un booléen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    ScopeAuthorizationArtifact,
    canonical_authorization_path,
    parse_scope_authorization_artifact,
)
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ResourceScope
from psycopg.types.json import Jsonb

from .github_authority import (
    GitHubAuthorityError,
    ReviewVerification,
    fetch_blob_at_ref,
    verify_review,
)


class ScopeAuthorizationDeniedError(RuntimeError):
    """Aucune autorisation de scope valide et revérifiée en direct ne
    couvre cet usage — le worker doit refuser, jamais poursuivre en
    supposant une autorisation implicite."""


#: Colonnes relues pour toute vérification — liste unique, jamais dupliquée
#: entre deux requêtes qui pourraient diverger.
_AUTHORIZATION_COLUMNS = """
    authorization_id, protocol_version, decision,
    tenant, collection, niveau, voie, matiere, candidat, audience,
    visibility, school_year, programme_version,
    manifest_digest, profile_id, profile_version, profile_fingerprint,
    allowed_domains, rights_categories, exclusions,
    pii_absence_attested, pii_absence_evidence,
    valid_from, valid_until,
    artifact_path, artifact_blob_sha, authorization_digest,
    evidence_repository, evidence_pull_request, evidence_base_sha,
    evidence_head_sha, evidence_review_id, evidence_reviewer,
    evidence_submitted_at, evidence_challenge,
    revoked_at, revocation_reason
"""


@dataclass(frozen=True)
class VerifiedAuthorization:
    """Autorisation dont **toute** la chaîne vient d'être revérifiée.

    Porte l'intégralité des contraintes, pas seulement l'autorisation d'un
    scope : le worker en a besoin pour appliquer les points de contrôle
    d'ingestion (item D) sans jamais relire la base ni réinterpréter la
    décision."""

    authorization_id: str
    scope: ResourceScope
    manifest_digest: str
    profile_id: str
    profile_version: str
    profile_fingerprint: str
    allowed_domains: tuple[str, ...]
    rights_categories: tuple[str, ...]
    exclusions: tuple[str, ...]
    pii_absence_attested: bool
    valid_from: datetime
    valid_until: datetime
    artifact_path: str
    artifact_blob_sha: str
    authorization_digest: str
    evidence_repository: str
    evidence_pull_request: int
    evidence_base_sha: str
    evidence_head_sha: str
    evidence_review_id: int
    evidence_reviewer: str
    evidence_challenge: str
    #: Instant exact de cette vérification live — un appelant qui
    #: revalide à un point de contrôle ultérieur peut prouver quand la
    #: dernière relecture GitHub réelle a eu lieu.
    verified_at: datetime


def _load_row(conn: psycopg.Connection, *, authorization_id: str) -> dict[str, Any]:
    """Charge **exactement** la ligne nommée. Aucun ``ORDER BY``, aucun
    ``LIMIT`` : il n'existe aucun chemin par lequel une autre autorisation
    puisse être substituée à celle demandée (item C)."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_AUTHORIZATION_COLUMNS} "  # noqa: S608 - liste de colonnes littérale, aucune entrée externe
            "FROM ingestion_control.scope_authorizations WHERE authorization_id = %s",
            (authorization_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ScopeAuthorizationDeniedError(
                f"no scope_authorizations row with authorization_id={authorization_id!r}"
            )
        assert cur.description is not None  # noqa: S101 - row non-None implique description
        columns = [desc.name for desc in cur.description]
    return dict(zip(columns, row, strict=True))


def _scope_from_row(row: dict[str, Any]) -> ResourceScope:
    return ResourceScope(
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
    )


def _require_equal(*, field: str, stored: Any, live: Any, authorization_id: str) -> None:
    if stored != live:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r}: stored {field}={stored!r} does "
            f"not equal the live value {live!r} — the persisted decision and the "
            "GitHub review no longer describe the same event"
        )


def _verify_live_review(row: dict[str, Any]) -> ReviewVerification:
    """Item G : comparaison **champ par champ** de la décision live et des
    données persistées.

    L'ancienne forme (« le challenge stocké appartient-il à l'ensemble des
    challenges live ? ») acceptait une évidence dont le reviewer, la
    review, ou le base_sha avaient changé, du moment qu'un challenge —
    n'importe lequel — coïncidait. Ici, les huit champs doivent coïncider
    ensemble et avec la review effectivement retenue par ADR-0025."""
    authorization_id = row["authorization_id"]
    try:
        live = verify_review(
            repository=row["evidence_repository"],
            pull_request=row["evidence_pull_request"],
            expected_head=row["evidence_head_sha"],
        )
    except GitHubAuthorityError as exc:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r}: live GitHub verification failed: {exc}"
        ) from exc

    if not live.approved:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r}: the authority pull request is no "
            f"longer approved (reason={live.reason}) — closure, dismissal, a new "
            "head, or a lost reviewer permission all land here"
        )

    _require_equal(
        field="evidence_repository", stored=row["evidence_repository"],
        live=live.repository, authorization_id=authorization_id,
    )
    _require_equal(
        field="evidence_pull_request", stored=row["evidence_pull_request"],
        live=live.pull_request, authorization_id=authorization_id,
    )
    _require_equal(
        field="evidence_base_sha", stored=row["evidence_base_sha"],
        live=live.base_sha, authorization_id=authorization_id,
    )
    _require_equal(
        field="evidence_head_sha", stored=row["evidence_head_sha"],
        live=live.head_sha, authorization_id=authorization_id,
    )
    _require_equal(
        field="evidence_review_id", stored=row["evidence_review_id"],
        live=live.review_id, authorization_id=authorization_id,
    )
    _require_equal(
        field="evidence_reviewer", stored=row["evidence_reviewer"],
        live=live.reviewer, authorization_id=authorization_id,
    )
    _require_equal(
        field="evidence_challenge", stored=row["evidence_challenge"],
        live=live.challenge, authorization_id=authorization_id,
    )
    _require_equal(
        field="evidence_submitted_at",
        stored=_normalize_submitted_at(row["evidence_submitted_at"]),
        live=_normalize_submitted_at(live.submitted_at),
        authorization_id=authorization_id,
    )
    return live


def _normalize_submitted_at(value: Any) -> str:
    """``submitted_at`` traverse deux représentations (``TIMESTAMPTZ``
    PostgreSQL et chaîne ISO GitHub) — comparées sur une forme UTC unique,
    jamais sur leur texte brut (qui différerait toujours)."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


def _verify_reviewed_artifact(
    row: dict[str, Any], *, live: ReviewVerification
) -> ScopeAuthorizationArtifact:
    """Item B : relit les octets exacts approuvés et recompose la décision
    depuis eux — jamais depuis la ligne PostgreSQL."""
    authorization_id = row["authorization_id"]

    # Le chemin relu est dérivé de l'identifiant, pas lu depuis la ligne :
    # une ligne dont l'artifact_path aurait été altéré désigne un autre
    # fichier, et cette égalité le détecte avant même la requête réseau.
    expected_path = canonical_authorization_path(authorization_id)
    _require_equal(
        field="artifact_path", stored=row["artifact_path"],
        live=expected_path, authorization_id=authorization_id,
    )

    try:
        blob = fetch_blob_at_ref(
            repository=live.repository, path=expected_path, ref=live.head_sha
        )
    except GitHubAuthorityError as exc:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r}: cannot re-read the reviewed "
            f"artifact {expected_path} at {live.head_sha}: {exc}"
        ) from exc

    _require_equal(
        field="artifact_blob_sha", stored=row["artifact_blob_sha"],
        live=blob.blob_sha, authorization_id=authorization_id,
    )

    try:
        artifact = parse_scope_authorization_artifact(blob.content)
    except CanonicalArtifactError as exc:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r}: reviewed artifact at "
            f"{expected_path}@{live.head_sha} is not a canonical LOT41A "
            f"authorization: {exc}"
        ) from exc

    # Digest recalculé intégralement depuis les octets relus — jamais lu
    # depuis la base, jamais réutilisé d'un calcul antérieur.
    _require_equal(
        field="authorization_digest", stored=row["authorization_digest"],
        live=artifact.digest(), authorization_id=authorization_id,
    )
    return artifact


def _require_row_matches_artifact(
    row: dict[str, Any], artifact: ScopeAuthorizationArtifact
) -> None:
    """Toute colonne persistée doit être *dérivable* de l'artefact revu.

    Sans cette comparaison, un UPDATE direct en base (élargir
    ``allowed_domains``, avancer ``valid_until``) survivrait à la relecture :
    le digest porterait toujours sur l'artefact d'origine, mais le worker
    lirait la contrainte élargie."""
    authorization_id = row["authorization_id"]
    expected: dict[str, Any] = {
        "authorization_id": artifact.authorization_id,
        "protocol_version": artifact.protocol_version,
        "decision": artifact.decision,
        "tenant": artifact.scope.tenant,
        "collection": artifact.scope.collection,
        "niveau": artifact.scope.niveau.value,
        "voie": artifact.scope.voie.value,
        "matiere": artifact.scope.matiere,
        "candidat": artifact.scope.candidat.value,
        "audience": sorted(a.value for a in artifact.scope.audience),
        "visibility": artifact.scope.visibility,
        "school_year": artifact.scope.school_year,
        "programme_version": artifact.scope.programme_version,
        "manifest_digest": artifact.manifest_digest,
        "profile_id": artifact.profile_id,
        "profile_version": artifact.profile_version,
        "profile_fingerprint": artifact.profile_fingerprint,
        "allowed_domains": list(artifact.allowed_domains),
        "rights_categories": [r.value for r in artifact.rights_categories],
        "exclusions": list(artifact.exclusions),
        "pii_absence_attested": artifact.pii_absence_attested,
        "pii_absence_evidence": artifact.pii_absence_evidence,
        "valid_from": artifact.valid_from,
        "valid_until": artifact.valid_until,
    }
    for field, value in expected.items():
        stored = row[field]
        if isinstance(stored, list):
            stored = list(stored)
        if isinstance(stored, datetime) and isinstance(value, datetime):
            stored = stored.astimezone(UTC)
            value = value.astimezone(UTC)
        _require_equal(
            field=field, stored=stored, live=value, authorization_id=authorization_id
        )


def verify_scope_authorization(
    conn: psycopg.Connection,
    *,
    authorization_id: str,
    scope: ResourceScope | None = None,
    now: datetime | None = None,
) -> VerifiedAuthorization:
    """Revérifie intégralement l'autorisation **nommée**.

    ``scope``, quand il est fourni, doit correspondre exactement aux dix
    dimensions de l'autorisation : un job ne peut jamais s'exécuter sous
    une autorisation qui porte sur un autre scope, même valide par
    ailleurs.

    ``now`` est injectable pour les tests de fenêtre de validité ; la
    production ne le fournit jamais et lit l'horloge ici même, de sorte
    qu'une revalidation ultérieure voie réellement le temps passer."""
    moment = now or datetime.now(UTC)
    row = _load_row(conn, authorization_id=authorization_id)

    if row["revoked_at"] is not None:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} was revoked at {row['revoked_at']!r} "
            f"(reason={row['revocation_reason']!r})"
        )
    if moment < row["valid_from"]:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} is not valid yet "
            f"(valid_from={row['valid_from']!r}, now={moment!r})"
        )
    if moment >= row["valid_until"]:
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} expired at {row['valid_until']!r} "
            f"(now={moment!r})"
        )

    stored_scope = _scope_from_row(row)
    if scope is not None and scope_key(scope) != scope_key(stored_scope):
        raise ScopeAuthorizationDeniedError(
            f"authorization {authorization_id!r} authorizes scope "
            f"{scope_key(stored_scope)!r}, which is not the requested scope "
            f"{scope_key(scope)!r} — an authorization never covers a scope it "
            "does not name"
        )

    live = _verify_live_review(row)
    artifact = _verify_reviewed_artifact(row, live=live)
    _require_row_matches_artifact(row, artifact)

    return VerifiedAuthorization(
        authorization_id=artifact.authorization_id,
        scope=artifact.scope,
        manifest_digest=artifact.manifest_digest,
        profile_id=artifact.profile_id,
        profile_version=artifact.profile_version,
        profile_fingerprint=artifact.profile_fingerprint,
        allowed_domains=tuple(artifact.allowed_domains),
        rights_categories=tuple(r.value for r in artifact.rights_categories),
        exclusions=tuple(artifact.exclusions),
        pii_absence_attested=artifact.pii_absence_attested,
        valid_from=artifact.valid_from,
        valid_until=artifact.valid_until,
        artifact_path=row["artifact_path"],
        artifact_blob_sha=row["artifact_blob_sha"],
        authorization_digest=row["authorization_digest"],
        evidence_repository=live.repository,
        evidence_pull_request=live.pull_request,
        evidence_base_sha=live.base_sha,
        evidence_head_sha=live.head_sha,
        evidence_review_id=int(live.review_id or 0),
        evidence_reviewer=str(live.reviewer),
        evidence_challenge=str(live.challenge),
        verified_at=moment,
    )


def _enum_value(value: Any) -> str:
    """Valeur textuelle d'une dimension, qu'elle soit une Enum ou déjà une
    chaîne. Un ``ResourceScope`` validé porte des Enums, mais un scope
    construit par ``model_copy(update=...)`` (qui contourne la validation)
    peut porter des chaînes brutes — deux scopes équivalents doivent
    produire la même clé quelle que soit leur provenance, jamais lever."""
    return str(getattr(value, "value", value))


def scope_key(scope: ResourceScope) -> tuple[Any, ...]:
    """Identité comparable des dix dimensions — ``audience`` triée, pour
    que deux ordres d'écriture du même scope soient égaux."""
    return (
        scope.tenant, scope.collection, _enum_value(scope.niveau), _enum_value(scope.voie),
        scope.matiere, _enum_value(scope.candidat),
        tuple(sorted(_enum_value(a) for a in scope.audience)),
        scope.visibility, scope.school_year, scope.programme_version,
    )


def authorization_allows_rights(
    authorization: VerifiedAuthorization, rights: Rights | str
) -> bool:
    """Une catégorie de droits produite par le pipeline est-elle couverte ?
    Comparaison sur la valeur exacte — jamais un préfixe, jamais une
    inclusion permissive."""
    value = rights.value if isinstance(rights, Rights) else str(rights)
    return value in authorization.rights_categories


def record_scope_authorization_denied(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    job_id: UUID,
    actor: str,
    reason: str,
    checkpoint: str = "pre_claim",
    authorization_id: str | None = None,
) -> UUID:
    """Journalise un refus d'autorisation de scope dans
    ``ingestion_control.workflow_events`` (schéma générique LOT44b, aucune
    nouvelle table). ``checkpoint`` nomme le point de contrôle qui a refusé
    (item D) : un refus au moment du fetch et un refus au moment des droits
    ne sont pas le même événement d'audit. Ne committe pas — même
    convention que les primitives LOT44b/44c (ADR-0032 § 6)."""
    payload: dict[str, object] = {"reason": reason, "checkpoint": checkpoint}
    if authorization_id is not None:
        payload["scope_authorization_id"] = authorization_id
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
        if row is None:  # pragma: no cover - INSERT ... RETURNING rend toujours une ligne
            raise RuntimeError("workflow_events insert did not return event_id")
        event_id: UUID = row[0]
        return event_id


__all__ = [
    "ScopeAuthorizationDeniedError",
    "VerifiedAuthorization",
    "authorization_allows_rights",
    "scope_key",
    "record_scope_authorization_denied",
    "verify_scope_authorization",
]
