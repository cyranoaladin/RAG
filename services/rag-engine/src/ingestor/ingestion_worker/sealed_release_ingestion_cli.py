"""CLI du point d'entrée d'ingestion orienté release scellée (ADR-0056).

Frontière fail-closed : tout est refusé avant PostgreSQL, puis l'ingestion
entière se fait dans une seule transaction — elle aboutit complètement ou
ne laisse rien.

Ce CLI ne connaît pas ``PG_RAG_DSN``, n'ouvre que la connexion
``ingestion_control``, et refuse de s'exécuter en production.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

from ingestor.ingestion_control.attestation import (
    WorkerAttestationError,
    attest_runtime_role,
)
from ingestor.ingestion_control.db import get_ingestion_control_dsn
from ingestor.ingestion_profiles.readiness_gate import enforce_readiness_gate
from ingestor.ingestion_profiles.registry import load_profile_registry

from .runtime_authority import RuntimeAuthorityStartupError
from .sealed_release_ingestion import (
    SealedReleaseIngestionError,
    ingest_sealed_release,
    load_sealed_release,
)

#: Le seul environnement où ce point d'entrée s'exécute. La production est
#: refusée **nommément** : ce lot ingère un corpus qui n'a pas encore reçu
#: son attestation LOT42 batch, et rien de tel n'a sa place en production.
REQUIRED_ENVIRONMENT = "rehearsal"


def _non_blank(raw: str) -> str:
    if not raw.strip():
        raise argparse.ArgumentTypeError("must not be blank")
    return raw


def _mapping_entry(raw: str) -> tuple[str, str]:
    collection, separator, authorization_id = raw.partition("=")
    if not separator or not collection.strip() or not authorization_id.strip():
        raise argparse.ArgumentTypeError(
            "expected collection=authorization_id (both non-blank)"
        )
    return collection.strip(), authorization_id.strip()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ingestion d'une release scellée jusqu'à NEEDS_REVIEW — "
            "ne publie rien, n'atteste rien"
        )
    )
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--release-manifest-sha256", required=True, type=_non_blank)
    parser.add_argument("--artifacts-release-sha256", required=True, type=_non_blank)
    parser.add_argument("--candidate-inventory-sha256", required=True, type=_non_blank)
    parser.add_argument(
        "--artifact-transfer-manifest-path", required=True, type=Path
    )
    parser.add_argument(
        "--artifact-transfer-manifest-sha256", required=True, type=_non_blank
    )
    parser.add_argument("--artifact-store-dir", required=True, type=Path)
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True, type=_non_blank)
    parser.add_argument("--expected-role", required=True, type=_non_blank)
    parser.add_argument(
        "--scope-authorization",
        required=True,
        action="append",
        type=_mapping_entry,
        metavar="COLLECTION=AUTHORIZATION_ID",
        help=(
            "Autorisation LOT41A nommée pour une collection. Répéter une fois "
            "par collection : aucune autorisation n'est devinée ni choisie "
            "par ancienneté."
        ),
    )
    parser.add_argument(
        "--expected-collection",
        action="append",
        default=None,
        type=_non_blank,
        help=(
            "Collection attendue. Quand l'option est fournie, une collection "
            "manquante ET une collection en surplus sont toutes deux refusées."
        ),
    )
    parser.add_argument("--report-path", type=Path, default=None)
    return parser


def _scope_authorization_ids(
    entries: list[tuple[str, str]],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for collection, authorization_id in entries:
        if collection in mapping and mapping[collection] != authorization_id:
            raise SealedReleaseIngestionError(
                f"{collection} : deux autorisations nommées "
                f"({mapping[collection]!r} et {authorization_id!r}) — l'ambiguïté "
                "est refusée, jamais arbitrée"
            )
        mapping[collection] = authorization_id
    return mapping


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        readiness = enforce_readiness_gate()
        if readiness.environment != REQUIRED_ENVIRONMENT:
            raise RuntimeAuthorityStartupError(
                "sealed release ingestion runs only under "
                f"{REQUIRED_ENVIRONMENT!r}; refusing to run under "
                f"{readiness.environment!r}"
            )
        profiles = load_profile_registry(args.profiles_dir)
        facts = load_sealed_release(
            args.release_dir,
            release_manifest_sha256=args.release_manifest_sha256,
            artifacts_release_sha256=args.artifacts_release_sha256,
            candidate_inventory_sha256=args.candidate_inventory_sha256,
            artifact_transfer_manifest_path=args.artifact_transfer_manifest_path,
            artifact_transfer_manifest_sha256=args.artifact_transfer_manifest_sha256,
        )
        authorizations = _scope_authorization_ids(args.scope_authorization)
    except Exception as exc:
        print(f"SEALED_RELEASE_INGESTION_STARTUP_FAILED: {exc}", file=sys.stderr)
        return 1

    print(
        "SEALED_RELEASE_INGESTION_STARTUP "
        f"environment={readiness.environment} "
        f"release_id={facts.release_id} "
        f"release_manifest_sha256={facts.release_manifest_sha256} "
        f"subjects={len(facts.collections)} "
        f"unique_artifacts={len(facts.artifact_ids)} "
        f"placements={len(facts.placements)} "
        f"unique_chunks={facts.unique_chunk_count}"
    )

    try:
        with psycopg.connect(get_ingestion_control_dsn()) as conn:
            try:
                attestation = attest_runtime_role(
                    conn, expected_role=args.expected_role
                )
            except WorkerAttestationError as exc:
                print(
                    f"SEALED_RELEASE_INGESTION_ATTESTATION_FAILED: {exc}",
                    file=sys.stderr,
                )
                return 1
            print(
                "SEALED_RELEASE_INGESTION_ATTESTATION_OK "
                f"current_user={attestation.current_user}"
            )
            report = ingest_sealed_release(
                conn,
                facts=facts,
                artifact_store_dir=args.artifact_store_dir,
                profile_registry=profiles,
                scope_authorization_ids=authorizations,
                owner=args.owner,
                expected_collections=args.expected_collection,
            )
            conn.commit()
    except SealedReleaseIngestionError as exc:
        print(f"SEALED_RELEASE_INGESTION_REFUSED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"SEALED_RELEASE_INGESTION_FAILED: {exc}", file=sys.stderr)
        return 1

    payload = report.as_dict()
    if args.report_path is not None:
        args.report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        "SEALED_RELEASE_INGESTION_DONE "
        f"runs={report.runs} resources={report.resources} "
        f"candidates={report.resource_candidates} artifacts={report.artifacts} "
        f"workflow_events={report.workflow_events} "
        f"terminal_state={report.terminal_state} "
        f"published_rows={report.published_rows} "
        f"attestations={report.attestations}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["REQUIRED_ENVIRONMENT", "main"]
