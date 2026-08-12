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
from ingestor.ingestion_control.revocation_registry import (
    load_revocation_registry,
    require_revocation_registry_matches_manifest,
)
from ingestor.ingestion_profiles.readiness_gate import (
    ReadinessGateResult,
    enforce_readiness_gate,
)
from ingestor.ingestion_profiles.registry import load_profile_registry
from ingestor.release_readiness import load_release_registry_file

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
    # Preuves exigées uniquement en production (cf. _enforce_production_evidence) :
    # rehearsal ne les fournit jamais, et cela ne les rend pas moins exactes
    # quand elles sont fournies.
    parser.add_argument("--release-registry-path", type=Path, default=None)
    parser.add_argument("--release-registry-sha256", default=None)
    parser.add_argument("--revocation-registry-path", type=Path, default=None)
    parser.add_argument("--revocation-registry-sha256", default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-iterations", type=_positive_int, default=None)
    parser.add_argument(
        "--poll-interval-s",
        type=_finite_non_negative_float,
        default=DEFAULT_POLL_INTERVAL_S,
    )
    parser.add_argument(
        "--heartbeat-file",
        type=Path,
        default=None,
        help=(
            "Optionnel : fichier réécrit avec l'horodatage courant après "
            "chaque itération (réussie ou non) et une fois avant la première — "
            "sert uniquement de liveness check externe (ex. HEALTHCHECK Docker "
            "basé sur la fraîcheur du fichier). Aucune valeur par défaut : "
            "absent signifie pas de heartbeat écrit, comportement inchangé."
        ),
    )
    return parser


def _write_heartbeat(path: Path | None) -> None:
    if path is None:
        return
    path.write_text(str(time.time()), encoding="utf-8")


def _reap_expired_leases(conn: psycopg.Connection[object]) -> None:
    reap_expired_job_leases(conn)
    reap_expired_leases(conn)
    conn.commit()


def _enforce_production_evidence(
    args: argparse.Namespace, readiness: ReadinessGateResult
) -> None:
    """Production exige des preuves supplémentaires, jamais un check en moins.

    ``enforce_readiness_gate`` a déjà refusé de démarrer sans l'ancre de
    confiance de production gouvernée — cette fonction n'y ajoute rien.
    Ce qu'elle ajoute : le registre de releases canonique borné (LOT H2-B,
    ``release_readiness.load_release_registry_file``) et un registre de
    révocation gouverné, lié par digest au manifeste de readiness signé.
    L'un ou l'autre absent est un refus de démarrage, jamais une
    dégradation silencieuse en « aucune révocation »."""
    if args.release_registry_path is None or not args.release_registry_sha256:
        raise RuntimeAuthorityStartupError(
            "production requires the canonical release registry "
            "(--release-registry-path/--release-registry-sha256)"
        )
    load_release_registry_file(args.release_registry_path, args.release_registry_sha256)

    if args.revocation_registry_path is None or not args.revocation_registry_sha256:
        raise RuntimeAuthorityStartupError(
            "production requires a governed revocation registry "
            "(--revocation-registry-path/--revocation-registry-sha256)"
        )
    revocation = load_revocation_registry(
        args.revocation_registry_path,
        expected_sha256=args.revocation_registry_sha256,
    )
    require_revocation_registry_matches_manifest(
        revocation,
        manifest_revocation_registry_digest=readiness.manifest.revocation_registry_digest,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        readiness = enforce_readiness_gate()
        if readiness.environment not in ("rehearsal", "production"):
            raise RuntimeAuthorityStartupError(
                "multilevel worker requires rehearsal or production readiness"
            )
        if readiness.environment == "production":
            _enforce_production_evidence(args, readiness)
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

    if readiness.environment == "production":
        print(
            "MULTILEVEL_WORKER_STARTUP_AUTHORITY "
            "authority_mode=PRODUCTION_SIGNED_READINESS_MANIFEST "
            f"release_registry_sha256={args.release_registry_sha256} "
            f"revocation_registry_sha256={args.revocation_registry_sha256} "
            f"profile_manifest_sha256={args.profile_manifest_sha256} "
            f"declared_count={len(profiles)}"
        )
    else:
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
            _write_heartbeat(args.heartbeat_file)
            while max_iterations is None or iterations < max_iterations:
                _reap_expired_leases(conn)
                outcome = run_worker_iteration(conn, deps=deps)
                iterations += 1
                _write_heartbeat(args.heartbeat_file)
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
