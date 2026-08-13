"""Outil opérateur LOT41A — enregistrement/révocation d'une autorisation de
scope d'ingestion (ADR-0032).

Remédiation GATE H1 (items **B**, **C**, **K**).

**Ce que cet outil ne fait plus.** Il n'accepte plus de ``--scope-file``.
Un fichier local passé en argument n'a aucun lien avec ce qu'un humain a
approuvé : il pouvait décrire un scope plus large que celui relu dans la
PR, et l'outil l'aurait enregistré tel quel. La décision est désormais
lue **uniquement** depuis le dépôt, au chemin canonique dérivé de
``--authorization-id``, au commit exact approuvé. L'opérateur choisit
*quelle* autorisation enregistrer ; il ne choisit jamais *ce qu'elle dit*.

Chaîne réellement exécutée par ``record-authorization`` :

    verify_review (live, lecture seule, temps borné)
      -> refus si non APPROVED sur --expected-head exact
      -> fetch_blob_at_ref(chemin canonique, head approuvé)
      -> parse canonique strict (refus si octets non canoniques)
      -> digest SHA-256 recalculé intégralement
      -> INSERT (décision + digest + évidence live)

L'évidence enregistrée est toujours celle relue en direct, jamais une
valeur fournie sur la ligne de commande.

**Rôle PostgreSQL (item K).** Cet outil se connecte via
``PG_INGESTION_CONTROL_AUTHORITY_DSN`` — jamais le DSN applicatif du
worker. Il est conçu pour tourner dans un conteneur ponctuel dédié
(``scope-authority-operator``), pas dans le worker de longue durée, qui ne
reçoit jamais ce secret.
"""
from __future__ import annotations

import argparse
import sys

import psycopg

try:
    from ingestor.ingestion_control.db import get_authority_dsn
    from ingestor.ingestion_control.github_authority import (
        GitHubAuthorityError,
        ReviewVerification,
        fetch_blob_at_ref,
        verify_review,
    )
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029/ADR-0031) : même discipline que
    # create_job_cli.py — "ingestor" n'existe pas comme paquet ici.
    from ingestion_control.db import get_authority_dsn
    from ingestion_control.github_authority import (
        GitHubAuthorityError,
        ReviewVerification,
        fetch_blob_at_ref,
        verify_review,
    )

from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    ScopeAuthorizationArtifactAny,
    canonical_authorization_path,
    parse_scope_authorization_artifact,
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Enregistre ou révoque une autorisation de scope d'ingestion "
            "LOT41A à partir d'un artefact canonique approuvé dans le dépôt. "
            "Outil opérateur uniquement : jamais un endpoint réseau."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record-authorization",
        help=(
            "Enregistre l'autorisation décrite par "
            "governance/authorizations/<id>.json au HEAD approuvé de la PR."
        ),
    )
    record.add_argument(
        "--authorization-id", required=True,
        help=(
            "Identifiant canonique. Détermine à lui seul le chemin de "
            "l'artefact relu — jamais un chemin fourni librement."
        ),
    )
    record.add_argument("--repository", required=True)
    record.add_argument("--pull-request", required=True, type=int)
    record.add_argument(
        "--expected-head", required=True,
        help="SHA (40 hex) du HEAD exact de la PR d'autorité au moment de la review — jamais déduit.",
    )

    revoke = subparsers.add_parser(
        "revoke-authorization",
        help="Révoque une autorisation existante à partir d'une PR de révocation dédiée, déjà APPROVED.",
    )
    revoke.add_argument("--authorization-id", required=True)
    revoke.add_argument("--reason", required=True)
    revoke.add_argument("--repository", required=True)
    revoke.add_argument("--pull-request", required=True, type=int)
    revoke.add_argument(
        "--expected-head", required=True,
        help="SHA (40 hex) du HEAD exact de la PR de révocation au moment de la review.",
    )

    return parser


def _verified_approval(
    args: argparse.Namespace, *, label: str
) -> ReviewVerification | None:
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
            f"{label}: PR #{args.pull_request} is not APPROVED at head "
            f"{args.expected_head} — reason={live.reason}",
            file=sys.stderr,
        )
        return None
    return live


def _read_reviewed_artifact(
    *, repository: str, authorization_id: str, head_sha: str
) -> tuple[ScopeAuthorizationArtifactAny, str] | None:
    """Relit l'artefact au chemin canonique et au commit approuvé, puis le
    parse en exigeant la canonicité octet à octet. Retourne l'artefact et
    le SHA de blob Git de ces octets exacts."""
    path = canonical_authorization_path(authorization_id)
    try:
        blob = fetch_blob_at_ref(repository=repository, path=path, ref=head_sha)
    except GitHubAuthorityError as exc:
        print(f"REVIEWED_ARTIFACT_UNREADABLE: {path}@{head_sha}: {exc}", file=sys.stderr)
        return None
    try:
        artifact = parse_scope_authorization_artifact(blob.content)
    except CanonicalArtifactError as exc:
        print(f"REVIEWED_ARTIFACT_NOT_CANONICAL: {path}@{head_sha}: {exc}", file=sys.stderr)
        return None
    if artifact.authorization_id != authorization_id:
        # Impossible via le chemin canonique, mais vérifié explicitement :
        # le contenu ne doit jamais pouvoir revendiquer un autre identifiant
        # que celui sous lequel il est enregistré.
        print(
            f"REVIEWED_ARTIFACT_ID_MISMATCH: {path} declares "
            f"{artifact.authorization_id!r}, expected {authorization_id!r}",
            file=sys.stderr,
        )
        return None
    return artifact, blob.blob_sha


def _cmd_record_authorization(args: argparse.Namespace) -> int:
    try:
        canonical_authorization_path(args.authorization_id)
    except ValueError as exc:
        print(f"AUTHORIZATION_ID_NOT_CANONICAL: {exc}", file=sys.stderr)
        return 1

    live = _verified_approval(args, label="AUTHORIZATION_DENIED")
    if live is None:
        return 1

    read = _read_reviewed_artifact(
        repository=live.repository,
        authorization_id=args.authorization_id,
        head_sha=live.head_sha,
    )
    if read is None:
        return 1
    artifact, blob_sha = read

    # Digest recalculé intégralement ici, sur les octets relus — jamais
    # accepté d'une source externe, jamais réutilisé d'un calcul antérieur.
    digest = artifact.digest()

    with psycopg.connect(get_authority_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.scope_authorizations (
                    authorization_id, protocol_version, decision,
                    tenant, collection, niveau, voie, matiere, candidat,
                    audience, visibility, school_year, programme_version,
                    manifest_digest, profile_id, profile_version, profile_fingerprint,
                    allowed_domains, rights_categories, exclusions,
                    allowed_content_sha256,
                    pii_absence_attested, pii_absence_evidence,
                    valid_from, valid_until,
                    artifact_path, artifact_blob_sha, authorization_digest,
                    evidence_repository, evidence_pull_request, evidence_base_sha,
                    evidence_head_sha, evidence_review_id, evidence_reviewer,
                    evidence_submitted_at, evidence_challenge
                ) VALUES (
                    %(authorization_id)s, %(protocol_version)s, %(decision)s,
                    %(tenant)s, %(collection)s, %(niveau)s, %(voie)s, %(matiere)s, %(candidat)s,
                    %(audience)s, %(visibility)s, %(school_year)s, %(programme_version)s,
                    %(manifest_digest)s, %(profile_id)s, %(profile_version)s, %(profile_fingerprint)s,
                    %(allowed_domains)s, %(rights_categories)s, %(exclusions)s,
                    %(allowed_content_sha256)s,
                    %(pii_absence_attested)s, %(pii_absence_evidence)s,
                    %(valid_from)s, %(valid_until)s,
                    %(artifact_path)s, %(artifact_blob_sha)s, %(authorization_digest)s,
                    %(evidence_repository)s, %(evidence_pull_request)s, %(evidence_base_sha)s,
                    %(evidence_head_sha)s, %(evidence_review_id)s, %(evidence_reviewer)s,
                    %(evidence_submitted_at)s, %(evidence_challenge)s
                )
                """,
                {
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
                    "allowed_content_sha256": (
                        list(artifact.allowed_content_sha256)
                        if artifact.protocol_version == "LOT41A-V2"
                        else None
                    ),
                    "pii_absence_attested": artifact.pii_absence_attested,
                    "pii_absence_evidence": artifact.pii_absence_evidence,
                    "valid_from": artifact.valid_from,
                    "valid_until": artifact.valid_until,
                    "artifact_path": artifact.canonical_path(),
                    "artifact_blob_sha": blob_sha,
                    "authorization_digest": digest,
                    "evidence_repository": live.repository,
                    "evidence_pull_request": live.pull_request,
                    "evidence_base_sha": live.base_sha,
                    "evidence_head_sha": live.head_sha,
                    "evidence_review_id": live.review_id,
                    "evidence_reviewer": live.reviewer,
                    "evidence_submitted_at": live.submitted_at,
                    "evidence_challenge": live.challenge,
                },
            )
        conn.commit()

    print(
        f"AUTHORIZATION_RECORDED authorization_id={artifact.authorization_id} "
        f"collection={artifact.scope.collection} "
        f"artifact={artifact.canonical_path()}@{live.head_sha} "
        f"blob_sha={blob_sha} digest={digest}"
    )
    return 0


def _cmd_revoke_authorization(args: argparse.Namespace) -> int:
    live = _verified_approval(args, label="REVOCATION_DENIED")
    if live is None:
        return 1

    with psycopg.connect(get_authority_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_control.scope_authorizations
                SET revoked_at = now(), revoked_by = %(reviewer)s,
                    revocation_reason = %(reason)s,
                    revocation_evidence_repository = %(repository)s,
                    revocation_evidence_pull_request = %(pull_request)s,
                    revocation_evidence_base_sha = %(base_sha)s,
                    revocation_evidence_head_sha = %(head_sha)s,
                    revocation_evidence_review_id = %(review_id)s,
                    revocation_evidence_reviewer = %(reviewer)s,
                    revocation_evidence_submitted_at = %(submitted_at)s,
                    revocation_evidence_challenge = %(challenge)s
                WHERE authorization_id = %(authorization_id)s AND revoked_at IS NULL
                """,
                {
                    "authorization_id": args.authorization_id,
                    "reason": args.reason,
                    "repository": live.repository,
                    "pull_request": live.pull_request,
                    "base_sha": live.base_sha,
                    "head_sha": live.head_sha,
                    "review_id": live.review_id,
                    "reviewer": live.reviewer,
                    "submitted_at": live.submitted_at,
                    "challenge": live.challenge,
                },
            )
            updated = cur.rowcount
        conn.commit()

    if updated == 0:
        print(
            f"REVOCATION_NOOP: no non-revoked authorization "
            f"{args.authorization_id!r} found",
            file=sys.stderr,
        )
        return 1

    print(f"AUTHORIZATION_REVOKED authorization_id={args.authorization_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "record-authorization":
        return _cmd_record_authorization(args)
    if args.command == "revoke-authorization":
        return _cmd_revoke_authorization(args)
    raise AssertionError(f"unreachable: unknown command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover - couvert par appel direct de main() dans les tests
    sys.exit(main())


__all__ = ["main"]
