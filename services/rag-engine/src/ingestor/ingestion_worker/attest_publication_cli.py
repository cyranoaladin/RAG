"""Outil opérateur LOT42 — chaîne d'attestations de publication (ADR-0033).

Remédiation GATE H1 (items **E**, **F**, **K**).

**Ce que cet outil ne fait plus.** Il n'accepte plus ``--content-sha256``,
``--rights-status``, ``--quality-passed``, ``--quality-score``,
``--gate-passed``, ``--gate-name``, ni aucune des dates associées. Ces
valeurs existent déjà dans le système : les accepter en argument libre
permettait d'attester une publication conforme pour une ressource dont le
gate avait échoué. Elles sont désormais **lues** depuis les faits durables
du pipeline (``publication_evidence.collect_publication_facts``).

Deux sous-commandes, une par étape du protocole :

``propose-review``
    Lit les faits durables, refuse immédiatement toute chaîne négative
    (item F), et écrit sur la sortie standard l'artefact de revue
    canonique **et** le chemin Git où le commiter. C'est ce fichier, et
    lui seul, que l'humain relit dans la PR de revue de publication.

``record-attestation``
    Après approbation : revérifie la review en direct, relit l'artefact
    depuis le blob Git approuvé, **recompare champ par champ à la base**,
    et n'écrit qu'ensuite. Une divergence DB ↔ artefact est un refus.

**Rôle PostgreSQL (item K).** Les deux sous-commandes se connectent via
``PG_INGESTION_CONTROL_ATTESTOR_DSN``, et **uniquement** lui — jamais le
DSN applicatif du worker. Le rôle attestor détient SELECT sur les tables
du pipeline et sur ``workflow_events``, INSERT sur
``publication_attestations``, et rien d'autre : ce conteneur ne porte
donc qu'un seul secret, jamais deux.
"""
from __future__ import annotations

import argparse
import sys
from uuid import UUID

import psycopg

try:
    from ingestor.ingestion_control.artifact_attribution import (
        ArtifactAttributionError,
        load_artifact_attribution,
    )
    from ingestor.ingestion_control.db import get_attestor_dsn
    from ingestor.ingestion_control.github_authority import (
        GitHubAuthorityError,
        ReviewVerification,
        fetch_blob_at_ref,
        verify_review,
    )
    from ingestor.ingestion_control.publication_evidence import (
        PublicationEvidenceMissingError,
        PublicationFacts,
        collect_publication_facts,
    )
    from ingestor.ingestion_control.scope_authority import (
        ScopeAuthorizationDeniedError,
        VerifiedAuthorization,
        authorization_allows_rights,
        verify_scope_authorization,
    )
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029/ADR-0031) : "ingestor" n'existe
    # pas comme paquet ici — même discipline que create_job_cli.py.
    from ingestion_control.artifact_attribution import (
        ArtifactAttributionError,
        load_artifact_attribution,
    )
    from ingestion_control.db import get_attestor_dsn
    from ingestion_control.github_authority import (
        GitHubAuthorityError,
        ReviewVerification,
        fetch_blob_at_ref,
        verify_review,
    )
    from ingestion_control.publication_evidence import (
        PublicationEvidenceMissingError,
        PublicationFacts,
        collect_publication_facts,
    )
    from ingestion_control.scope_authority import (
        ScopeAuthorizationDeniedError,
        VerifiedAuthorization,
        authorization_allows_rights,
        verify_scope_authorization,
    )

from nexus_contracts.authority_artifacts import (
    LOT42_PROTOCOL_VERSION,
    CanonicalArtifactError,
    PublicationReviewArtifact,
    canonical_publication_review_path,
    parse_publication_review_artifact,
)
from nexus_contracts.document import Rights


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prépare puis enregistre une chaîne d'attestations de publication "
            "LOT42 à partir des faits durables du pipeline et d'une PR de "
            "revue approuvée. Outil opérateur uniquement : jamais un endpoint "
            "réseau."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser(
        "propose-review",
        help=(
            "Produit l'artefact de revue canonique depuis les faits durables. "
            "Lecture seule — n'écrit jamais en base."
        ),
    )
    propose.add_argument("--resource-id", required=True, type=UUID)
    propose.add_argument("--artifact-id", required=True, type=UUID)
    propose.add_argument("--scope-authorization-id", required=True)
    propose.add_argument(
        "--review-id", required=True,
        help="Identifiant canonique de cette revue de publication (minuscules, [a-z0-9._-]).",
    )

    record = subparsers.add_parser(
        "record-attestation",
        help="Enregistre l'attestation après approbation humaine de l'artefact de revue.",
    )
    record.add_argument("--resource-id", required=True, type=UUID)
    record.add_argument("--artifact-id", required=True, type=UUID)
    record.add_argument("--scope-authorization-id", required=True)
    record.add_argument("--review-id", required=True)
    record.add_argument("--repository", required=True)
    record.add_argument("--pull-request", required=True, type=int)
    record.add_argument(
        "--expected-head", required=True,
        help="SHA (40 hex) du HEAD exact de la PR de revue de publication.",
    )

    return parser


def _reject_negative_chain(facts: PublicationFacts) -> str | None:
    """Item F, première barrière côté outil : une chaîne négative est
    refusée *avant* toute construction d'artefact, avec un message qui
    nomme le fait exact qui bloque."""
    if not facts.quality_passed:
        return (
            f"PUBLICATION_DENIED_QUALITY: resource {facts.resource_id} has "
            "quality_passed=false in its durable evidence"
        )
    if not facts.gate_passed:
        return (
            f"PUBLICATION_DENIED_GATE: resource {facts.resource_id} has "
            f"gate_passed=false ({facts.gate_name}) in its durable evidence"
        )
    if facts.rights_status == Rights.unknown:
        return (
            f"PUBLICATION_DENIED_RIGHTS: resource {facts.resource_id} has "
            "rights_status='unknown' in its durable evidence"
        )
    return None


def _build_artifact(
    *,
    review_id: str,
    facts: PublicationFacts,
    authorization: VerifiedAuthorization,
) -> PublicationReviewArtifact:
    """Construit l'artefact **entièrement** depuis les faits durables et
    l'autorisation vérifiée. Aucun champ n'a d'autre origine."""
    return PublicationReviewArtifact(
        protocol_version=LOT42_PROTOCOL_VERSION,
        review_id=review_id,
        decision="AUTHORIZE_PUBLICATION",
        resource_id=str(facts.resource_id),
        artifact_id=str(facts.artifact_id),
        collection=facts.collection,
        canonical_url=facts.canonical_url,
        content_sha256=facts.content_sha256,
        scope_authorization_id=authorization.authorization_id,
        profile_id=authorization.profile_id,
        profile_version=authorization.profile_version,
        profile_fingerprint=authorization.profile_fingerprint,
        manifest_digest=authorization.manifest_digest,
        rights_status=facts.rights_status,
        rights_assessed_at=facts.rights_assessed_at,
        quality_passed=facts.quality_passed,
        quality_report_digest=facts.quality_report_digest,
        quality_assessed_at=facts.quality_assessed_at,
        gate_passed=facts.gate_passed,
        gate_name=facts.gate_name,
        gate_evaluated_at=facts.gate_evaluated_at,
        evidence_event_ids=facts.evidence_event_ids,
    )


def _load_facts_and_authorization(
    conn: psycopg.Connection, *, resource_id: UUID, artifact_id: UUID, authorization_id: str
) -> tuple[PublicationFacts, VerifiedAuthorization] | None:
    try:
        facts = collect_publication_facts(
            conn, resource_id=resource_id, artifact_id=artifact_id
        )
    except PublicationEvidenceMissingError as exc:
        print(f"DURABLE_EVIDENCE_MISSING: {exc}", file=sys.stderr)
        return None

    denial = _reject_negative_chain(facts)
    if denial is not None:
        print(denial, file=sys.stderr)
        return None

    try:
        authorization = verify_scope_authorization(conn, authorization_id=authorization_id)
    except ScopeAuthorizationDeniedError as exc:
        print(f"SCOPE_AUTHORIZATION_DENIED: {exc}", file=sys.stderr)
        return None

    if authorization.scope.collection != facts.collection:
        print(
            f"SCOPE_COLLECTION_MISMATCH: authorization covers "
            f"{authorization.scope.collection!r}, resource is in {facts.collection!r}",
            file=sys.stderr,
        )
        return None
    if not authorization_allows_rights(authorization, facts.rights_status):
        print(
            f"RIGHTS_NOT_AUTHORIZED: {facts.rights_status.value!r} is not among "
            f"{list(authorization.rights_categories)!r}",
            file=sys.stderr,
        )
        return None
    return facts, authorization


def _cmd_propose_review(args: argparse.Namespace) -> int:
    with psycopg.connect(get_attestor_dsn()) as conn:
        loaded = _load_facts_and_authorization(
            conn,
            resource_id=args.resource_id,
            artifact_id=args.artifact_id,
            authorization_id=args.scope_authorization_id,
        )
        if loaded is None:
            return 1
        facts, authorization = loaded

    try:
        artifact = _build_artifact(
            review_id=args.review_id, facts=facts, authorization=authorization
        )
    except ValueError as exc:
        print(f"REVIEW_ARTIFACT_INVALID: {exc}", file=sys.stderr)
        return 1

    print(f"REVIEW_ARTIFACT_PATH {artifact.canonical_path()}")
    print(f"REVIEW_ARTIFACT_DIGEST {artifact.digest()}")
    sys.stdout.write(artifact.canonical_bytes().decode("utf-8"))
    return 0


def _verified_approval(args: argparse.Namespace) -> ReviewVerification | None:
    try:
        live = verify_review(
            repository=args.repository,
            pull_request=args.pull_request,
            expected_head=args.expected_head,
        )
    except GitHubAuthorityError as exc:
        print(f"LIVE_REVIEW_VERIFICATION_FAILED: {exc}", file=sys.stderr)
        return None
    if not live.approved:
        print(
            f"ATTESTATION_DENIED: publication review PR #{args.pull_request} is "
            f"not APPROVED at head {args.expected_head} — reason={live.reason}",
            file=sys.stderr,
        )
        return None
    return live


def _cmd_record_attestation(args: argparse.Namespace) -> int:
    # Lecture des faits sous le rôle attestor lui-même : il détient SELECT
    # sur les tables du pipeline et sur workflow_events, mais aucune
    # écriture. Ce conteneur ne reçoit donc qu'UN seul credential (item K)
    # — jamais aussi celui du worker sous prétexte de lire des faits.
    with psycopg.connect(get_attestor_dsn()) as read_conn:
        loaded = _load_facts_and_authorization(
            read_conn,
            resource_id=args.resource_id,
            artifact_id=args.artifact_id,
            authorization_id=args.scope_authorization_id,
        )
        if loaded is None:
            return 1
        facts, authorization = loaded

    live = _verified_approval(args)
    if live is None:
        return 1

    # L'artefact attendu est recalculé depuis la base, puis le blob approuvé
    # est relu et comparé octet à octet à ce calcul : c'est cette double
    # dérivation qui interdit toute divergence DB ↔ artefact revu.
    try:
        expected_artifact = _build_artifact(
            review_id=args.review_id, facts=facts, authorization=authorization
        )
    except ValueError as exc:
        print(f"REVIEW_ARTIFACT_INVALID: {exc}", file=sys.stderr)
        return 1

    digest = expected_artifact.digest()
    path = canonical_publication_review_path(review_id=args.review_id, digest=digest)

    try:
        blob = fetch_blob_at_ref(repository=live.repository, path=path, ref=live.head_sha)
    except GitHubAuthorityError as exc:
        print(
            f"REVIEWED_ARTIFACT_UNREADABLE: {path}@{live.head_sha}: {exc}\n"
            "Hint: the committed artifact must match the database exactly — its "
            "digest is part of its canonical path, so any divergence changes "
            "the path and makes it unreadable here.",
            file=sys.stderr,
        )
        return 1

    if blob.content != expected_artifact.canonical_bytes():
        print(
            f"REVIEWED_ARTIFACT_DIVERGES_FROM_DB: {path}@{live.head_sha} does not "
            "byte-match the artifact derived from durable evidence",
            file=sys.stderr,
        )
        return 1

    try:
        reviewed = parse_publication_review_artifact(blob.content)
    except CanonicalArtifactError as exc:
        print(f"REVIEWED_ARTIFACT_NOT_CANONICAL: {exc}", file=sys.stderr)
        return 1

    with psycopg.connect(get_attestor_dsn()) as conn:
        # H2-F (défaut 6) : les faits ont été lus sur une connexion déjà
        # refermée. Ils sont donc relus ICI, dans la transaction qui écrit
        # l'attestation et sous ``FOR SHARE`` : un writer concurrent qui
        # voudrait changer l'attribution est bloqué jusqu'au commit, et une
        # attribution qui aurait changé depuis la revue est refusée plutôt
        # que scellée à l'insu de l'humain qui a approuvé.
        try:
            _attribution, attributed_facts_digest = load_artifact_attribution(
                conn, ingestion_artifact_id=args.artifact_id, lock=True
            )
        except ArtifactAttributionError as exc:
            print(f"ATTRIBUTION_EVIDENCE_MISSING: {exc}", file=sys.stderr)
            return 1
        if attributed_facts_digest != facts.attribution_digest:
            print(
                "ATTRIBUTION_DRIFTED_SINCE_REVIEW: the control-plane attribution "
                f"of artifact {args.artifact_id} changed between the reviewed "
                f"proposal ({facts.attribution_digest}) and this attestation "
                f"({attributed_facts_digest}) — re-propose the review",
                file=sys.stderr,
            )
            return 1

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.publication_attestations (
                    resource_id, artifact_id, content_sha256, canonical_url, collection,
                    scope_authorization_id, profile_id, profile_version, profile_fingerprint,
                    manifest_digest,
                    rights_status, rights_assessed_at,
                    quality_passed, quality_report_digest, quality_assessed_at,
                    gate_passed, gate_name, gate_evaluated_at,
                    evidence_event_ids,
                    review_id, review_artifact_path, review_artifact_blob_sha, attestation_digest,
                    human_review_repository, human_review_pull_request, human_review_base_sha,
                    human_review_head_sha, human_review_review_id, human_review_reviewer,
                    human_review_submitted_at, human_review_challenge,
                    protocol_version, attributed_facts_digest
                ) VALUES (
                    %(resource_id)s, %(artifact_id)s, %(content_sha256)s, %(canonical_url)s, %(collection)s,
                    %(scope_authorization_id)s, %(profile_id)s, %(profile_version)s, %(profile_fingerprint)s,
                    %(manifest_digest)s,
                    %(rights_status)s, %(rights_assessed_at)s,
                    %(quality_passed)s, %(quality_report_digest)s, %(quality_assessed_at)s,
                    %(gate_passed)s, %(gate_name)s, %(gate_evaluated_at)s,
                    %(evidence_event_ids)s,
                    %(review_id)s, %(review_artifact_path)s, %(review_artifact_blob_sha)s, %(attestation_digest)s,
                    %(human_review_repository)s, %(human_review_pull_request)s, %(human_review_base_sha)s,
                    %(human_review_head_sha)s, %(human_review_review_id)s, %(human_review_reviewer)s,
                    %(human_review_submitted_at)s, %(human_review_challenge)s,
                    %(protocol_version)s, %(attributed_facts_digest)s
                )
                """,
                {
                    "resource_id": args.resource_id,
                    "artifact_id": args.artifact_id,
                    "content_sha256": reviewed.content_sha256,
                    "canonical_url": reviewed.canonical_url,
                    "collection": reviewed.collection,
                    "scope_authorization_id": reviewed.scope_authorization_id,
                    "profile_id": reviewed.profile_id,
                    "profile_version": reviewed.profile_version,
                    "profile_fingerprint": reviewed.profile_fingerprint,
                    "manifest_digest": reviewed.manifest_digest,
                    "rights_status": reviewed.rights_status.value,
                    "rights_assessed_at": reviewed.rights_assessed_at,
                    "quality_passed": reviewed.quality_passed,
                    "quality_report_digest": facts.quality_report_digest,
                    "quality_assessed_at": reviewed.quality_assessed_at,
                    "gate_passed": reviewed.gate_passed,
                    "gate_name": reviewed.gate_name,
                    "gate_evaluated_at": reviewed.gate_evaluated_at,
                    "evidence_event_ids": list(reviewed.evidence_event_ids),
                    "review_id": reviewed.review_id,
                    "review_artifact_path": path,
                    "review_artifact_blob_sha": blob.blob_sha,
                    "attestation_digest": digest,
                    "human_review_repository": live.repository,
                    "human_review_pull_request": live.pull_request,
                    "human_review_base_sha": live.base_sha,
                    "human_review_head_sha": live.head_sha,
                    "human_review_review_id": live.review_id,
                    "human_review_reviewer": live.reviewer,
                    "human_review_submitted_at": live.submitted_at,
                    "human_review_challenge": live.challenge,
                    "protocol_version": LOT42_PROTOCOL_VERSION,
                    "attributed_facts_digest": attributed_facts_digest,
                },
            )
        conn.commit()

    print(
        f"ATTESTATION_RECORDED resource_id={args.resource_id} "
        f"artifact_id={args.artifact_id} review={path}@{live.head_sha} "
        f"blob_sha={blob.blob_sha} digest={digest}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "propose-review":
        return _cmd_propose_review(args)
    if args.command == "record-attestation":
        return _cmd_record_attestation(args)
    raise AssertionError(f"unreachable: unknown command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover - couvert par appel direct de main() dans les tests
    sys.exit(main())


__all__ = ["main"]
