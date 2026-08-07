"""Outil opérateur LOT42 — enregistrement d'une chaîne d'attestations de
publication (ADR-0033).

Même discipline que ``authorize_scope_cli.py`` : jamais un endpoint réseau,
``docker exec`` uniquement, invoqué après qu'une review GitHub ``APPROVED``
réelle existe déjà sur la PR de revue de publication. Les champs déjà
durables (``collection``, ``canonical_url``, ``content_sha256``) sont
toujours dérivés des tables ``resources``/``resource_candidates``/
``artifacts`` existantes — jamais acceptés en argument libre, pour éviter
toute divergence avec l'état réellement enregistré. Les résultats
rights/quality/gate ne sont pas encore persistés ailleurs dans ce lot
(hors périmètre — cf. plan de finalisation) : ils restent des arguments
explicites, jamais devinés (même principe que ``create_job_cli.py``).

``scope_authorization_id`` est revérifié en direct
(``scope_authority.verify_scope_authorization_by_id``) avant toute
écriture : une attestation ne peut jamais être créée en référence à une
autorisation de scope déjà invalide.
"""
from __future__ import annotations

import argparse
import sys
from uuid import UUID

import psycopg

try:
    from ingestor.ingestion_control._trusted_review import (
        TrustedReviewVerificationError,
        run_check_github_review,
    )
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_control.scope_authority import (
        ScopeAuthorizationDeniedError,
        verify_scope_authorization_by_id,
    )
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029/ADR-0031) : même discipline que
    # authorize_scope_cli.py — "ingestor" n'existe pas comme paquet ici.
    from ingestion_control._trusted_review import (
        TrustedReviewVerificationError,
        run_check_github_review,
    )
    from ingestion_control.db import get_ingestion_control_dsn
    from ingestion_control.scope_authority import (
        ScopeAuthorizationDeniedError,
        verify_scope_authorization_by_id,
    )

_PROTOCOL_VERSION = "LOT42-V1"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Enregistre une chaîne d'attestations de publication LOT42 pour "
            "une ressource, à partir d'une PR de revue de publication déjà "
            "APPROVED. Outil opérateur uniquement : jamais un endpoint réseau."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record-attestation",
        help="Enregistre une nouvelle attestation pour une ressource donnée.",
    )
    record.add_argument("--resource-id", required=True, type=UUID)
    record.add_argument("--artifact-id", required=True, type=UUID)
    record.add_argument("--scope-authorization-id", required=True)
    record.add_argument("--profile-id", required=True)
    record.add_argument("--profile-version", required=True)
    record.add_argument("--profile-fingerprint", required=True)
    record.add_argument("--manifest-digest", required=True)
    record.add_argument("--rights-status", required=True)
    record.add_argument("--rights-assessed-at", required=True)
    record.add_argument("--quality-passed", required=True, choices=["true", "false"])
    record.add_argument("--quality-score", required=True, type=float)
    record.add_argument("--quality-assessed-at", required=True)
    record.add_argument("--gate-passed", required=True, choices=["true", "false"])
    record.add_argument("--gate-name", required=True)
    record.add_argument("--gate-evaluated-at", required=True)
    record.add_argument("--repository", required=True)
    record.add_argument("--pull-request", required=True, type=int)
    record.add_argument(
        "--expected-head", required=True,
        help="SHA (40 hex) du HEAD exact de la PR de revue de publication.",
    )

    return parser


def _cmd_record_attestation(args: argparse.Namespace) -> int:
    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT collection FROM ingestion_control.resources WHERE resource_id = %s",
                (args.resource_id,),
            )
            resource_row = cur.fetchone()
        if resource_row is None:
            print(f"RESOURCE_NOT_FOUND: {args.resource_id}", file=sys.stderr)
            return 1
        (collection,) = resource_row

        with conn.cursor() as cur:
            cur.execute(
                "SELECT sha256 FROM ingestion_control.artifacts "
                "WHERE artifact_id = %s AND resource_id = %s",
                (args.artifact_id, args.resource_id),
            )
            artifact_row = cur.fetchone()
        if artifact_row is None:
            print(
                f"ARTIFACT_NOT_FOUND_FOR_RESOURCE: artifact_id={args.artifact_id} "
                f"resource_id={args.resource_id}",
                file=sys.stderr,
            )
            return 1
        (content_sha256,) = artifact_row

        with conn.cursor() as cur:
            cur.execute(
                "SELECT canonical_url FROM ingestion_control.resource_candidates "
                "WHERE resource_id = %s ORDER BY discovered_at DESC LIMIT 1",
                (args.resource_id,),
            )
            candidate_row = cur.fetchone()
        if candidate_row is None:
            print(f"RESOURCE_CANDIDATE_NOT_FOUND: {args.resource_id}", file=sys.stderr)
            return 1
        (canonical_url,) = candidate_row

        try:
            verify_scope_authorization_by_id(conn, authorization_id=args.scope_authorization_id)
        except ScopeAuthorizationDeniedError as exc:
            print(f"SCOPE_AUTHORIZATION_DENIED: {exc}", file=sys.stderr)
            return 1

        try:
            review_payload = run_check_github_review(
                repository=args.repository,
                pull_request=args.pull_request,
                expected_head=args.expected_head,
            )
        except TrustedReviewVerificationError as exc:
            print(f"LIVE_REVIEW_VERIFICATION_FAILED: {exc}", file=sys.stderr)
            return 1

        decision = review_payload["decision"]
        if not decision.get("approved"):
            print(
                f"ATTESTATION_DENIED: publication review PR #{args.pull_request} "
                f"is not APPROVED at head {args.expected_head} — "
                f"reason={decision.get('reason')}",
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
                    quality_passed, quality_score, quality_assessed_at,
                    gate_passed, gate_name, gate_evaluated_at,
                    human_review_repository, human_review_pull_request, human_review_base_sha,
                    human_review_head_sha, human_review_review_id, human_review_reviewer,
                    human_review_submitted_at, human_review_challenge,
                    protocol_version
                ) VALUES (
                    %(resource_id)s, %(artifact_id)s, %(content_sha256)s, %(canonical_url)s, %(collection)s,
                    %(scope_authorization_id)s, %(profile_id)s, %(profile_version)s, %(profile_fingerprint)s,
                    %(manifest_digest)s,
                    %(rights_status)s, %(rights_assessed_at)s,
                    %(quality_passed)s, %(quality_score)s, %(quality_assessed_at)s,
                    %(gate_passed)s, %(gate_name)s, %(gate_evaluated_at)s,
                    %(human_review_repository)s, %(human_review_pull_request)s, %(human_review_base_sha)s,
                    %(human_review_head_sha)s, %(human_review_review_id)s, %(human_review_reviewer)s,
                    %(human_review_submitted_at)s, %(human_review_challenge)s,
                    %(protocol_version)s
                )
                """,
                {
                    "resource_id": args.resource_id,
                    "artifact_id": args.artifact_id,
                    "content_sha256": content_sha256,
                    "canonical_url": canonical_url,
                    "collection": collection,
                    "scope_authorization_id": args.scope_authorization_id,
                    "profile_id": args.profile_id,
                    "profile_version": args.profile_version,
                    "profile_fingerprint": args.profile_fingerprint,
                    "manifest_digest": args.manifest_digest,
                    "rights_status": args.rights_status,
                    "rights_assessed_at": args.rights_assessed_at,
                    "quality_passed": args.quality_passed == "true",
                    "quality_score": args.quality_score,
                    "quality_assessed_at": args.quality_assessed_at,
                    "gate_passed": args.gate_passed == "true",
                    "gate_name": args.gate_name,
                    "gate_evaluated_at": args.gate_evaluated_at,
                    "human_review_repository": decision["repository"],
                    "human_review_pull_request": decision["pull_request"],
                    "human_review_base_sha": decision["base_sha"],
                    "human_review_head_sha": decision["head_sha"],
                    "human_review_review_id": decision["review_id"],
                    "human_review_reviewer": decision["reviewer"],
                    "human_review_submitted_at": decision["submitted_at"],
                    "human_review_challenge": decision["challenge"],
                    "protocol_version": _PROTOCOL_VERSION,
                },
            )
        conn.commit()

    print(
        f"ATTESTATION_RECORDED resource_id={args.resource_id} "
        f"artifact_id={args.artifact_id} pull_request={args.pull_request}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "record-attestation":
        return _cmd_record_attestation(args)
    raise AssertionError(f"unreachable: unknown command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover - couvert par appel direct de main() dans les tests
    sys.exit(main())


__all__ = ["main"]
