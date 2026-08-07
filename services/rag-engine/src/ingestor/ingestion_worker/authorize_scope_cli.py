"""Outil opérateur LOT41A — enregistrement/révocation d'une autorisation de
scope d'ingestion (ADR-0032).

Même discipline que ``create_job_cli.py`` : jamais un endpoint réseau,
``docker exec`` uniquement, invoqué par un opérateur humain après qu'une
review GitHub ``APPROVED`` réelle existe déjà sur la PR de scope
(``record-authorization``) ou de révocation (``revoke-authorization``).

Aucune sous-commande n'écrit jamais une ligne à partir d'une simple
affirmation de l'opérateur : chacune revérifie en direct, via
``ingestion_control._trusted_review.run_check_github_review``, l'évidence
GitHub avant tout INSERT/UPDATE — refuse d'écrire si la vérification live
échoue (ADR-0032 § 5). L'évidence effectivement enregistrée est toujours
celle relue en direct (``decision``), jamais une valeur fournie par
l'opérateur sur la ligne de commande.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
import yaml
from nexus_contracts.ingestion import ResourceScope

try:
    from ingestor.ingestion_control._trusted_review import (
        TrustedReviewVerificationError,
        run_check_github_review,
    )
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029/ADR-0031) : même discipline que
    # create_job_cli.py — "ingestor" n'existe pas comme paquet ici.
    from ingestion_control._trusted_review import (
        TrustedReviewVerificationError,
        run_check_github_review,
    )
    from ingestion_control.db import get_ingestion_control_dsn

_AUTHORIZE_DECISION = "AUTHORIZE_INGESTION_SCOPE"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Enregistre ou révoque une autorisation de scope d'ingestion "
            "LOT41A. Outil opérateur uniquement : jamais un endpoint réseau."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record-authorization",
        help="Enregistre une nouvelle autorisation à partir d'une PR de scope déjà APPROVED.",
    )
    record.add_argument("--authorization-id", required=True)
    record.add_argument("--scope-file", required=True, type=Path)
    record.add_argument("--repository", required=True)
    record.add_argument("--pull-request", required=True, type=int)
    record.add_argument(
        "--expected-head", required=True,
        help="SHA (40 hex) du HEAD exact de la PR de scope au moment de la review — jamais déduit.",
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


def _load_scope_file(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML/JSON mapping")
    return data


def _cmd_record_authorization(args: argparse.Namespace) -> int:
    payload_file = _load_scope_file(args.scope_file)
    required_top_level = {
        "scope", "manifest_digest", "profile_id", "profile_version",
        "profile_fingerprint", "allowed_domains", "rights_categories",
        "pii_absence_attested", "pii_absence_evidence", "valid_from", "valid_until",
    }
    missing = required_top_level - payload_file.keys()
    if missing:
        print(f"SCOPE_FILE_MISSING_FIELDS: {sorted(missing)}", file=sys.stderr)
        return 1

    try:
        scope = ResourceScope.model_validate(payload_file["scope"])
    except Exception as exc:  # noqa: BLE001 - frontière CLI volontaire, jamais silencieuse
        print(f"SCOPE_VALIDATION_FAILED: {exc}", file=sys.stderr)
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
            f"AUTHORIZATION_DENIED: PR #{args.pull_request} is not APPROVED "
            f"at head {args.expected_head} — reason={decision.get('reason')}",
            file=sys.stderr,
        )
        return 1

    exclusions = payload_file.get("exclusions") or []

    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.scope_authorizations (
                    authorization_id, decision,
                    tenant, collection, niveau, voie, matiere, candidat,
                    audience, visibility, school_year, programme_version,
                    manifest_digest, profile_id, profile_version, profile_fingerprint,
                    allowed_domains, rights_categories, exclusions,
                    pii_absence_attested, pii_absence_evidence,
                    valid_from, valid_until,
                    evidence_repository, evidence_pull_request, evidence_base_sha,
                    evidence_head_sha, evidence_review_id, evidence_reviewer,
                    evidence_submitted_at, evidence_challenge
                ) VALUES (
                    %(authorization_id)s, %(decision)s,
                    %(tenant)s, %(collection)s, %(niveau)s, %(voie)s, %(matiere)s, %(candidat)s,
                    %(audience)s, %(visibility)s, %(school_year)s, %(programme_version)s,
                    %(manifest_digest)s, %(profile_id)s, %(profile_version)s, %(profile_fingerprint)s,
                    %(allowed_domains)s, %(rights_categories)s, %(exclusions)s,
                    %(pii_absence_attested)s, %(pii_absence_evidence)s,
                    %(valid_from)s, %(valid_until)s,
                    %(evidence_repository)s, %(evidence_pull_request)s, %(evidence_base_sha)s,
                    %(evidence_head_sha)s, %(evidence_review_id)s, %(evidence_reviewer)s,
                    %(evidence_submitted_at)s, %(evidence_challenge)s
                )
                """,
                {
                    "authorization_id": args.authorization_id,
                    "decision": _AUTHORIZE_DECISION,
                    "tenant": scope.tenant,
                    "collection": scope.collection,
                    "niveau": scope.niveau,
                    "voie": scope.voie,
                    "matiere": scope.matiere,
                    "candidat": scope.candidat,
                    "audience": sorted(a.value if hasattr(a, "value") else str(a) for a in scope.audience),
                    "visibility": scope.visibility,
                    "school_year": scope.school_year,
                    "programme_version": scope.programme_version,
                    "manifest_digest": payload_file["manifest_digest"],
                    "profile_id": payload_file["profile_id"],
                    "profile_version": payload_file["profile_version"],
                    "profile_fingerprint": payload_file["profile_fingerprint"],
                    "allowed_domains": payload_file["allowed_domains"],
                    "rights_categories": payload_file["rights_categories"],
                    "exclusions": exclusions,
                    "pii_absence_attested": payload_file["pii_absence_attested"],
                    "pii_absence_evidence": payload_file["pii_absence_evidence"],
                    "valid_from": payload_file["valid_from"],
                    "valid_until": payload_file["valid_until"],
                    "evidence_repository": decision["repository"],
                    "evidence_pull_request": decision["pull_request"],
                    "evidence_base_sha": decision["base_sha"],
                    "evidence_head_sha": decision["head_sha"],
                    "evidence_review_id": decision["review_id"],
                    "evidence_reviewer": decision["reviewer"],
                    "evidence_submitted_at": decision["submitted_at"],
                    "evidence_challenge": decision["challenge"],
                },
            )
        conn.commit()

    print(
        f"AUTHORIZATION_RECORDED authorization_id={args.authorization_id} "
        f"collection={scope.collection} pull_request={args.pull_request} "
        f"head_sha={args.expected_head}"
    )
    return 0


def _cmd_revoke_authorization(args: argparse.Namespace) -> int:
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
            f"REVOCATION_DENIED: revocation PR #{args.pull_request} is not "
            f"APPROVED at head {args.expected_head} — reason={decision.get('reason')}",
            file=sys.stderr,
        )
        return 1

    with psycopg.connect(get_ingestion_control_dsn()) as conn:
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
                    "repository": decision["repository"],
                    "pull_request": decision["pull_request"],
                    "base_sha": decision["base_sha"],
                    "head_sha": decision["head_sha"],
                    "review_id": decision["review_id"],
                    "reviewer": decision["reviewer"],
                    "submitted_at": decision["submitted_at"],
                    "challenge": decision["challenge"],
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
