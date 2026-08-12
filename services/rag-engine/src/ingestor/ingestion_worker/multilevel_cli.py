"""CLI staging Worker A pour une release multi-collections scellée."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import psycopg

from ingestor.ingestion_control.attestation import (
    WorkerAttestationError,
    attest_runtime_role,
)
from ingestor.ingestion_control.db import get_ingestion_control_dsn
from ingestor.ingestion_control.jobs import reap_expired_job_leases
from ingestor.ingestion_control.lease_reaper import reap_expired_leases
from ingestor.ingestion_profiles.readiness_gate import enforce_readiness_gate
from ingestor.ingestion_profiles.registry import load_profile_registry

from .multilevel_runtime_authority import (
    add_multilevel_runtime_authority_arguments,
    load_multilevel_runtime_authorities,
    multilevel_runtime_authority_inputs_from_args,
)
from .runner import WorkerDeps, run_worker_iteration
from .runtime_authority import RuntimeAuthorityStartupError
from .storage import make_filesystem_artifact_reader, make_filesystem_artifact_store

DEFAULT_POLL_INTERVAL_S = 5.0


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _finite_non_negative_float(raw: str) -> float:
    value = float(raw)
    if not (value >= 0) or value == float("inf"):
        raise argparse.ArgumentTypeError("must be finite and non-negative")
    return value


def _non_blank(raw: str) -> str:
    if not raw.strip():
        raise argparse.ArgumentTypeError("must not be blank")
    return raw


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Worker A staging gouverné pour release multi-collections"
    )
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--artifact-store-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True, type=_non_blank)
    parser.add_argument("--expected-role", required=True, type=_non_blank)
    add_multilevel_runtime_authority_arguments(parser)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-iterations", type=_positive_int, default=None)
    parser.add_argument(
        "--poll-interval-s",
        type=_finite_non_negative_float,
        default=DEFAULT_POLL_INTERVAL_S,
    )
    return parser


def _reap_expired_leases(conn: psycopg.Connection[object]) -> None:
    reap_expired_job_leases(conn)
    reap_expired_leases(conn)
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        readiness = enforce_readiness_gate()
        if readiness.environment != "rehearsal":
            raise RuntimeAuthorityStartupError(
                "multilevel staging worker requires rehearsal readiness"
            )
        profiles = load_profile_registry(args.profiles_dir)
        authorities = load_multilevel_runtime_authorities(
            multilevel_runtime_authority_inputs_from_args(args),
            profile_registry=profiles,
        )
    except Exception as exc:
        # Frontière CLI fail-closed avant PostgreSQL. Le ``Exception`` final
        # nomme aussi les digests et fichiers malformés des autorités scellées.
        print(f"MULTILEVEL_WORKER_STARTUP_FAILED: {exc}", file=sys.stderr)
        return 1

    print(
        "MULTILEVEL_WORKER_STARTUP_AUTHORITY "
        "authority_mode=STAGING_LOCAL_GITHUB_ONLY production_approval=false "
        f"release_manifest_sha256={args.release_manifest_sha256} "
        f"profile_manifest_sha256={args.profile_manifest_sha256} "
        f"declared_count={len(profiles)}"
    )
    deps = WorkerDeps(
        owner=args.owner,
        profile_registry=profiles,
        artifact_store=make_filesystem_artifact_store(args.artifact_store_dir),
        artifact_reader=make_filesystem_artifact_reader(args.artifact_store_dir),
        pii_evidence_registry=authorities.pii_evidence_registry,
        rights_evidence_registry=authorities.rights_evidence_registry,
        placement_resolver=authorities.placement_resolver,
        manifest_digest=authorities.placement_resolver.release_profile_manifest_digest,
    )
    max_iterations = 1 if args.once else args.max_iterations
    iterations = 0
    try:
        with psycopg.connect(get_ingestion_control_dsn()) as conn:
            try:
                attestation = attest_runtime_role(
                    conn,
                    expected_role=args.expected_role,
                )
            except WorkerAttestationError as exc:
                print(f"MULTILEVEL_WORKER_ATTESTATION_FAILED: {exc}", file=sys.stderr)
                return 1
            print("MULTILEVEL_WORKER_ATTESTATION_OK " f"current_user={attestation.current_user}")
            while max_iterations is None or iterations < max_iterations:
                _reap_expired_leases(conn)
                outcome = run_worker_iteration(conn, deps=deps)
                iterations += 1
                if outcome.worked:
                    print(
                        f"MULTILEVEL_WORKER_ITERATION job_id={outcome.job_id} "
                        f"status={outcome.status}"
                    )
                    if outcome.error:
                        print(
                            f"MULTILEVEL_WORKER_ITERATION_ERROR job_id={outcome.job_id}: "
                            f"{outcome.error}",
                            file=sys.stderr,
                        )
                elif args.once:
                    print("MULTILEVEL_WORKER_ITERATION no_job_available")
                    break
                else:
                    time.sleep(args.poll_interval_s)
    except RuntimeAuthorityStartupError as exc:
        print(f"MULTILEVEL_WORKER_STARTUP_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
