"""Vérification live LOT42 — chaîne d'attestations de publication (ADR-0033).

Remédiation GATE H1, items **E** et **F**.

``verify_publication_attestation`` réévalue **toute** la chaîne à chaque
appel : jamais un statut mis en cache, jamais un booléen stocké. Une
attestation enregistrée n'est qu'un index vers des preuves qui doivent
toutes tenir *maintenant* :

    ligne d'attestation
      -> faits durables du pipeline relus (workflow_events append-only)
      -> artefact de revue relu au head approuvé, digest recalculé
      -> review humaine GitHub revérifiée, champ par champ
      -> autorisation de scope LOT41A revérifiée intégralement
      -> contenu / profil / manifest inchangés

**Item F — une chaîne négative ne publie jamais.** Le refus est imposé
trois fois, à trois niveaux indépendants, parce qu'une seule barrière est
une barrière qu'on peut contourner :

1. *Irreprésentable dans l'artefact* — ``PublicationReviewArtifact``
   refuse de se construire si ``quality_passed``/``gate_passed`` est faux
   ou si ``rights_status`` vaut ``unknown``.
2. *Irreprésentable en base* — les contraintes ``CHECK`` de la migration
   008 refusent la ligne correspondante.
3. *Refusé à la relecture* — les vérifications ci-dessous rejettent la
   transition même si une ligne avait été introduite par un chemin
   inattendu.

Fail-closed : toute absence ou invalidation lève
``PublicationAttestationInvalidError``. Une invalidation détectée est
persistée au mieux-effort (``invalidated_at``/``invalidated_reason``) —
trace d'audit, jamais la source de vérité, qui reste toujours la relecture
live elle-même.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    PublicationReviewArtifactV2,
    canonical_publication_review_path,
    parse_publication_review_artifact,
    require_publication_review_v2,
)
from nexus_contracts.document import Rights
from nexus_contracts.resource_state import ResourceState

from .github_authority import (
    GitHubAuthorityError,
    ReviewVerification,
    fetch_blob_at_ref,
    verify_review,
)
from .publication_evidence import (
    PublicationEvidenceMissingError,
    PublicationFacts,
    collect_publication_facts,
)
from .scope_authority import (
    ScopeAuthorizationDeniedError,
    VerifiedAuthorization,
    authorization_allows_rights,
    verify_scope_authorization,
)
from .scope_enforcement import (
    ScopeEnforcementViolation,
    enforce_content_sha256,
    require_h2_content_bound_authority,
)
from .transitions import TransitionResult, cas_transition


class PublicationAttestationInvalidError(RuntimeError):
    """Aucune chaîne d'attestations de publication valide et revérifiée en
    direct n'existe pour cette ressource — la transition
    ``REVIEWED -> RETRIEVAL_ELIGIBLE`` ne doit jamais être tentée."""


_ATTESTATION_COLUMNS = """
    attestation_id, resource_id, artifact_id, content_sha256, canonical_url,
    collection, scope_authorization_id,
    profile_id, profile_version, profile_fingerprint, manifest_digest,
    rights_status, rights_assessed_at,
    quality_passed, quality_report_digest, quality_assessed_at,
    gate_passed, gate_name, gate_evaluated_at,
    evidence_event_ids,
    review_id, review_artifact_path, review_artifact_blob_sha, attestation_digest,
    human_review_repository, human_review_pull_request, human_review_base_sha,
    human_review_head_sha, human_review_review_id, human_review_reviewer,
    human_review_submitted_at, human_review_challenge,
    protocol_version, attributed_facts_digest
"""


@dataclass(frozen=True)
class VerifiedAttestation:
    attestation_id: UUID
    resource_id: UUID
    artifact_id: UUID
    content_sha256: str
    scope_authorization_id: str
    profile_fingerprint: str
    manifest_digest: str
    review_id: str
    attestation_digest: str
    #: ADR-0035 : exposé pour que le publisher puisse exiger LOT42-V2
    #: *explicitement*, plutôt que d'hériter silencieusement du refus
    #: appliqué ici. Une garantie transitive est une garantie qu'un
    #: futur refactor peut retirer sans qu'aucun test ne rougisse.
    protocol_version: str
    attributed_facts_digest: str
    authorization: VerifiedAuthorization
    facts: PublicationFacts


def _load_active_row(conn: psycopg.Connection, *, resource_id: UUID) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_ATTESTATION_COLUMNS} "  # noqa: S608 - liste de colonnes littérale
            "FROM ingestion_control.publication_attestations "
            "WHERE resource_id = %s AND invalidated_at IS NULL",
            (resource_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        assert cur.description is not None  # noqa: S101 - row non-None implique description
        columns = [desc.name for desc in cur.description]
    return dict(zip(columns, row, strict=True))


def _mark_invalidated(conn: psycopg.Connection, *, attestation_id: UUID, reason: str) -> None:
    """Meilleur effort : persiste la raison d'invalidation détectée pour
    audit. N'est jamais la condition de fail-closed elle-même — l'appelant
    lève déjà ``PublicationAttestationInvalidError`` indépendamment de la
    réussite de cette écriture.

    Le rôle runtime est volontairement en lecture seule sur cette table et
    la vérification gouvernée peut s'exécuter dans ``conn.transaction()``.
    Un rollback/UPDATE alors interdit ne doit donc jamais masquer le refus
    de sécurité déjà déterminé. Le rôle attestor, lui, conserve la
    persistance de ce cache d'audit lors d'une vérification autonome."""
    try:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_control.publication_attestations
                SET invalidated_at = now(), invalidated_reason = %s
                WHERE attestation_id = %s AND invalidated_at IS NULL
                """,
                (reason[:2000], attestation_id),
            )
        conn.commit()
    except psycopg.Error:
        # Hors contexte transactionnel, nettoie l'état aborted laissé par un
        # UPDATE refusé au rôle app. Dans un ``conn.transaction()`` externe,
        # ce rollback est lui-même interdit : l'exception de sécurité qui
        # sortira du contexte effectuera alors le rollback atomique attendu.
        try:
            conn.rollback()
        except psycopg.Error:
            pass


class _Invalidator:
    """Petit utilitaire : chaque refus invalide la ligne puis lève, sans
    répéter ces deux gestes vingt fois. Le message d'audit et le message
    d'exception sont toujours le même texte — jamais deux formulations qui
    divergeraient à la lecture d'un incident."""

    def __init__(self, conn: psycopg.Connection, attestation_id: UUID) -> None:
        self._conn = conn
        self._attestation_id = attestation_id

    def fail(self, reason: str) -> PublicationAttestationInvalidError:
        _mark_invalidated(self._conn, attestation_id=self._attestation_id, reason=reason)
        return PublicationAttestationInvalidError(
            f"attestation {self._attestation_id} invalidated: {reason}"
        )

    def require_equal(self, field: str, stored: Any, current: Any) -> None:
        if stored != current:
            raise self.fail(f"{field} drift (attested={stored!r}, current={current!r})")


def _normalize_moment(value: Any) -> str:
    if value is None:
        return ""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


def _verify_human_review(row: dict[str, Any], invalidator: _Invalidator) -> ReviewVerification:
    """Même discipline champ par champ que LOT41A (item G) — jamais une
    simple appartenance du challenge à l'ensemble des challenges live."""
    try:
        live = verify_review(
            repository=row["human_review_repository"],
            pull_request=row["human_review_pull_request"],
            expected_head=row["human_review_head_sha"],
        )
    except GitHubAuthorityError as exc:
        raise invalidator.fail(f"human_review transport failure: {exc}") from exc

    if not live.approved:
        raise invalidator.fail(
            f"human_review is no longer approved (reason={live.reason}) — PR "
            "closure, review dismissal, a new head, or a lost reviewer "
            "permission all land here"
        )

    invalidator.require_equal("human_review_repository", row["human_review_repository"], live.repository)
    invalidator.require_equal("human_review_pull_request", row["human_review_pull_request"], live.pull_request)
    invalidator.require_equal("human_review_base_sha", row["human_review_base_sha"], live.base_sha)
    invalidator.require_equal("human_review_head_sha", row["human_review_head_sha"], live.head_sha)
    invalidator.require_equal("human_review_review_id", row["human_review_review_id"], live.review_id)
    invalidator.require_equal("human_review_reviewer", row["human_review_reviewer"], live.reviewer)
    invalidator.require_equal("human_review_challenge", row["human_review_challenge"], live.challenge)
    invalidator.require_equal(
        "human_review_submitted_at",
        _normalize_moment(row["human_review_submitted_at"]),
        _normalize_moment(live.submitted_at),
    )
    return live


def _verify_review_artifact(
    row: dict[str, Any], *, live: ReviewVerification, invalidator: _Invalidator
) -> PublicationReviewArtifactV2:
    """Item E : la décision de publication est relue depuis le blob Git
    approuvé, jamais reconstruite depuis les colonnes de la base.

    ADR-0035 : seul un artefact **LOT42-V2** peut autoriser une
    publication. Un V1 historique reste parsable — il doit le rester pour
    l'audit — mais il est refusé ici, avant toute comparaison, parce qu'il
    n'a jamais lié la provenance publiée à la relecture humaine."""
    expected_path = canonical_publication_review_path(
        review_id=row["review_id"], digest=row["attestation_digest"]
    )
    invalidator.require_equal("review_artifact_path", row["review_artifact_path"], expected_path)

    try:
        blob = fetch_blob_at_ref(
            repository=live.repository, path=expected_path, ref=live.head_sha
        )
    except GitHubAuthorityError as exc:
        raise invalidator.fail(
            f"cannot re-read the reviewed publication artifact {expected_path}"
            f"@{live.head_sha}: {exc}"
        ) from exc

    invalidator.require_equal("review_artifact_blob_sha", row["review_artifact_blob_sha"], blob.blob_sha)

    try:
        parsed = parse_publication_review_artifact(blob.content)
        artifact = require_publication_review_v2(parsed)
    except CanonicalArtifactError as exc:
        raise invalidator.fail(
            f"reviewed publication artifact is not canonical: {exc}"
        ) from exc

    invalidator.require_equal("attestation_digest", row["attestation_digest"], artifact.digest())
    return artifact


def _require_row_matches_artifact(
    row: dict[str, Any], artifact: PublicationReviewArtifactV2, invalidator: _Invalidator
) -> None:
    """Toute colonne persistée doit être dérivable de l'artefact revu — un
    UPDATE direct en base ne survit jamais à la relecture.

    ADR-0035 : ``attributed_facts_digest`` en fait désormais partie. Sans
    cette comparaison, la ligne pourrait citer une attribution différente
    de celle que l'humain a relue dans les octets de l'artefact."""
    expected: dict[str, Any] = {
        "protocol_version": artifact.protocol_version,
        "attributed_facts_digest": artifact.attributed_facts_digest,
        "review_id": artifact.review_id,
        "resource_id": str(row["resource_id"]),
        "artifact_id": str(row["artifact_id"]),
        "collection": artifact.collection,
        "canonical_url": artifact.canonical_url,
        "content_sha256": artifact.content_sha256,
        "scope_authorization_id": artifact.scope_authorization_id,
        "profile_id": artifact.profile_id,
        "profile_version": artifact.profile_version,
        "profile_fingerprint": artifact.profile_fingerprint,
        "manifest_digest": artifact.manifest_digest,
        "rights_status": artifact.rights_status.value,
        "quality_passed": artifact.quality_passed,
        "gate_passed": artifact.gate_passed,
        "gate_name": artifact.gate_name,
    }
    invalidator.require_equal("artifact.resource_id", artifact.resource_id, str(row["resource_id"]))
    invalidator.require_equal("artifact.artifact_id", artifact.artifact_id, str(row["artifact_id"]))
    for field, value in expected.items():
        if field in ("resource_id", "artifact_id"):
            continue
        invalidator.require_equal(field, row[field], value)
    invalidator.require_equal(
        "evidence_event_ids",
        sorted(str(e) for e in row["evidence_event_ids"]),
        sorted(artifact.evidence_event_ids),
    )


def _require_facts_still_hold(
    row: dict[str, Any], artifact: PublicationReviewArtifactV2, invalidator: _Invalidator,
    facts: PublicationFacts,
) -> None:
    """Item F : les résultats du pipeline sont relus **maintenant** et
    doivent être à la fois positifs et identiques à ceux revus."""
    if not facts.quality_passed:
        raise invalidator.fail("durable quality result is now false — never publishable")
    if not facts.gate_passed:
        raise invalidator.fail("durable gate result is now false — never publishable")
    if facts.rights_status == Rights.unknown:
        raise invalidator.fail("durable rights result is now 'unknown' — never publishable")

    invalidator.require_equal("facts.content_sha256", artifact.content_sha256, facts.content_sha256)
    invalidator.require_equal("facts.canonical_url", artifact.canonical_url, facts.canonical_url)
    invalidator.require_equal("facts.collection", artifact.collection, facts.collection)
    invalidator.require_equal(
        "facts.rights_status", artifact.rights_status.value, facts.rights_status.value
    )
    invalidator.require_equal(
        "facts.quality_report_digest", row["quality_report_digest"], facts.quality_report_digest
    )
    # H2-F (défaut 6) : les quatre faits d'attribution scellés par cette
    # attestation doivent être *exactement* ceux qui sont persistés
    # maintenant. Le trigger de la migration 012 interdit déjà de les
    # modifier tant qu'une attestation active les nomme ; cette
    # comparaison ferme le cas restant — une attestation écrite avant que
    # le scellement n'existe, ou une ligne d'attestation modifiée
    # directement en base. Un digest absent n'est jamais interprété comme
    # « rien à vérifier ».
    if not row["attributed_facts_digest"]:
        raise invalidator.fail(
            "attestation carries no attributed_facts_digest — it predates the "
            "H2-F attribution binding and can never authorize a publication"
        )
    invalidator.require_equal(
        "facts.attribution_digest",
        row["attributed_facts_digest"],
        facts.attribution_digest,
    )
    # ADR-0035, troisième branche de l'égalité à trois voies : les octets
    # relus par l'humain doivent désigner l'attribution vivante. Les deux
    # autres branches (artefact ↔ ligne, ligne ↔ faits) sont vérifiées
    # ci-dessus et dans ``_require_row_matches_artifact`` ; celle-ci est
    # redondante par construction et le reste **volontairement** : elle
    # tombe en panne bruyamment si l'une des deux autres était un jour
    # affaiblie.
    invalidator.require_equal(
        "artifact.attributed_facts_digest",
        artifact.attributed_facts_digest,
        facts.attribution_digest,
    )
    invalidator.require_equal("facts.gate_name", artifact.gate_name, facts.gate_name)
    invalidator.require_equal(
        "facts.evidence_event_ids",
        sorted(artifact.evidence_event_ids),
        sorted(facts.evidence_event_ids),
    )


def verify_publication_attestation(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    current_content_sha256: str,
    current_profile_fingerprint: str,
    current_manifest_digest: str,
    require_content_bound_authority: bool = False,
) -> VerifiedAttestation:
    """Revérifie **intégralement** la chaîne LOT42 d'une ressource.

    ``current_*`` sont les valeurs que l'appelant observe au moment de
    publier ; toute divergence avec ce qui a été attesté invalide la
    chaîne (dérive de contenu, de profil, de manifest)."""
    row = _load_active_row(conn, resource_id=resource_id)
    if row is None:
        raise PublicationAttestationInvalidError(
            f"no active (non-invalidated) publication_attestations row for "
            f"resource_id={resource_id}"
        )
    invalidator = _Invalidator(conn, row["attestation_id"])

    invalidator.require_equal("content_sha256", row["content_sha256"], current_content_sha256)
    invalidator.require_equal(
        "profile_fingerprint", row["profile_fingerprint"], current_profile_fingerprint
    )
    invalidator.require_equal("manifest_digest", row["manifest_digest"], current_manifest_digest)

    # Les faits durables d'abord : inutile de solliciter GitHub pour une
    # ressource dont le pipeline n'a produit aucune évidence exploitable.
    try:
        facts = collect_publication_facts(
            conn, resource_id=resource_id, artifact_id=row["artifact_id"]
        )
    except PublicationEvidenceMissingError as exc:
        raise invalidator.fail(f"durable pipeline evidence missing: {exc}") from exc

    live = _verify_human_review(row, invalidator)
    artifact = _verify_review_artifact(row, live=live, invalidator=invalidator)
    _require_row_matches_artifact(row, artifact, invalidator)
    _require_facts_still_hold(row, artifact, invalidator, facts)

    try:
        authorization = verify_scope_authorization(
            conn, authorization_id=row["scope_authorization_id"]
        )
    except ScopeAuthorizationDeniedError as exc:
        raise invalidator.fail(
            f"referenced scope_authorization_id={row['scope_authorization_id']!r} "
            f"no longer verifies live: {exc}"
        ) from exc

    # Les droits produits doivent rester couverts par l'autorisation LOT41A
    # *courante* : révoquer une catégorie de droits dans une nouvelle
    # autorisation ne suffirait pas si l'attestation continuait de publier
    # sous l'ancienne — c'est bien celle qu'elle nomme qui est revérifiée.
    if not authorization_allows_rights(authorization, facts.rights_status):
        raise invalidator.fail(
            f"rights category {facts.rights_status.value!r} is not among the "
            f"categories authorized by {authorization.authorization_id!r} "
            f"({list(authorization.rights_categories)!r})"
        )
    if authorization.profile_fingerprint != current_profile_fingerprint:
        raise invalidator.fail(
            f"profile fingerprint drift against the scope authorization "
            f"(authorized={authorization.profile_fingerprint!r}, "
            f"current={current_profile_fingerprint!r})"
        )
    if authorization.manifest_digest != current_manifest_digest:
        raise invalidator.fail(
            f"manifest digest drift against the scope authorization "
            f"(authorized={authorization.manifest_digest!r}, "
            f"current={current_manifest_digest!r})"
        )

    if require_content_bound_authority:
        try:
            require_h2_content_bound_authority(authorization)
        except ScopeEnforcementViolation as exc:
            raise invalidator.fail(str(exc)) from exc
        invalidator.require_equal(
            "FETCHED authority id",
            facts.content_scope_authorization_id,
            authorization.authorization_id,
        )
        invalidator.require_equal(
            "FETCHED authority digest",
            facts.content_scope_authorization_digest,
            authorization.authorization_digest,
        )
        invalidator.require_equal(
            "FETCHED authority protocol",
            facts.content_scope_authorization_protocol_version,
            authorization.protocol_version,
        )
        try:
            enforce_content_sha256(
                authorization,
                content_sha256=facts.content_sha256,
            )
        except ScopeEnforcementViolation as exc:
            raise invalidator.fail(str(exc)) from exc

    return VerifiedAttestation(
        attestation_id=row["attestation_id"],
        resource_id=row["resource_id"],
        artifact_id=row["artifact_id"],
        content_sha256=row["content_sha256"],
        scope_authorization_id=row["scope_authorization_id"],
        profile_fingerprint=row["profile_fingerprint"],
        manifest_digest=row["manifest_digest"],
        review_id=row["review_id"],
        attestation_digest=row["attestation_digest"],
        protocol_version=row["protocol_version"],
        attributed_facts_digest=row["attributed_facts_digest"],
        authorization=authorization,
        facts=facts,
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
) -> TransitionResult:
    """Point d'ancrage unique LOT42 (ADR-0033 § 6) : la SEULE fonction
    autorisée à faire transitionner une ressource ``REVIEWED ->
    RETRIEVAL_ELIGIBLE``. Vérifie d'abord ``verify_publication_attestation``
    (fail-closed) — la transition n'est jamais tentée si cette vérification
    échoue, et la ressource reste ``REVIEWED`` (état stable, jamais un état
    d'erreur nouveau).

    Non appelée par ``ingestion_worker.runner`` : le chemin interne de
    répétition ``governed_publication_path`` atteint ``REVIEWED`` sous tests,
    puis appelle cette ancre. Il n'est monté ni dans le worker vivant, ni
    dans une API, un démarrage ou un cron ;
    ``LOT42_LIVE_PIPELINE_WIRED=false`` reste donc vrai. Toute activation
    ultérieure doit réutiliser cette ancre — jamais réinventer sa propre
    vérification LOT42 ni un second point d'accès."""
    verify_publication_attestation(
        conn,
        resource_id=resource_id,
        current_content_sha256=current_content_sha256,
        current_profile_fingerprint=current_profile_fingerprint,
        current_manifest_digest=current_manifest_digest,
        require_content_bound_authority=True,
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
