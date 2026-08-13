"""CLI autonome de Worker B, consommateur exclusif de ``publication_resume``."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg

try:
    from ingestor.embedding_provider import VerifiedE5EmbeddingProvider
    from ingestor.ingestion_control.attestation import (
        WorkerAttestationError,
        attest_runtime_role,
    )
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_control.jobs import reap_expired_job_leases
    from ingestor.ingestion_profiles.readiness_gate import (
        ReadinessGateError,
        enforce_readiness_gate,
    )
    from ingestor.ingestion_profiles.startup_gate import enforce_production_manifest_gate
except (ImportError, ValueError):
    from embedding_provider import VerifiedE5EmbeddingProvider
    from ingestion_control.attestation import (
        WorkerAttestationError,
        attest_runtime_role,
    )
    from ingestion_control.db import get_ingestion_control_dsn
    from ingestion_control.jobs import (
        reap_expired_job_leases,
    )
    from ingestion_profiles.readiness_gate import (
        ReadinessGateError,
        enforce_readiness_gate,
    )
    from ingestion_profiles.startup_gate import (
        enforce_production_manifest_gate,
    )

from .publication_resume import PublicationResumeDeps, run_publication_resume_iteration
from .runtime_authority import (
    RuntimeAuthorityStartupError,
    add_runtime_authority_arguments,
    load_governed_runtime_authorities,
    runtime_authority_inputs_from_args,
)
from .storage import make_filesystem_artifact_reader

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
        description="Worker B gouverné — publication_resume uniquement"
    )
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--manifest-path", required=True, type=Path)
    parser.add_argument("--artifact-store-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True, type=_non_blank)
    parser.add_argument("--expected-role", required=True, type=_non_blank)
    parser.add_argument("--pii-evidence-path", required=True, type=Path)
    parser.add_argument("--pii-evidence-sha256", required=True, type=_non_blank)
    parser.add_argument("--rights-evidence-path", required=True, type=Path)
    parser.add_argument("--rights-evidence-sha256", required=True, type=_non_blank)
    parser.add_argument("--corpus-manifest-sha256", required=True, type=_non_blank)
    add_runtime_authority_arguments(parser)
    parser.add_argument("--embedding-artifact-root", required=True, type=Path)
    parser.add_argument("--embedding-inventory-sha256", required=True, type=_non_blank)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-iterations", type=_positive_int, default=None)
    parser.add_argument(
        "--poll-interval-s",
        type=_finite_non_negative_float,
        default=DEFAULT_POLL_INTERVAL_S,
    )
    return parser


def _extract_non_pdf_text(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("latin-1")


def _product_dsn() -> str:
    dsn = os.environ.get("PG_RAG_DSN", "").strip()
    if not dsn:
        raise RuntimeAuthorityStartupError("PG_RAG_DSN is required for Worker B")
    return dsn


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        readiness = enforce_readiness_gate()
    except ReadinessGateError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"PUBLICATION_WORKER_READINESS release_sha={readiness.manifest.merge_sha} "
        f"release_tag={readiness.manifest.release_tag} environment={readiness.environment}"
    )
    try:
        gate_result = enforce_production_manifest_gate(
            args.profiles_dir, args.manifest_path
        )
        authorities = load_governed_runtime_authorities(
            runtime_authority_inputs_from_args(args),
            profile_registry=gate_result.registry,
            profile_manifest_digest=gate_result.manifest.manifest_fingerprint,
        )
        product_dsn = _product_dsn()
        resolver = authorities.placement_resolver
        if (
            resolver.release_embedding_model_id
            != VerifiedE5EmbeddingProvider.model_id
            or resolver.release_embedding_dimension
            != VerifiedE5EmbeddingProvider.dimension
            or resolver.release_embedding_inventory_sha256
            != args.embedding_inventory_sha256
        ):
            raise RuntimeAuthorityStartupError(
                "embedding provider inputs differ from the release manifest"
            )
        provider = VerifiedE5EmbeddingProvider.from_artifact(
            artifact_root=args.embedding_artifact_root,
            inventory_sha256=args.embedding_inventory_sha256,
            pg_dsn=product_dsn,
        )
    except Exception as exc:  # frontière CLI : tout startup drift est nommé
        print(f"PUBLICATION_WORKER_STARTUP_FAILED: {exc}", file=sys.stderr)
        return 1

    deps = PublicationResumeDeps(
        owner=args.owner,
        product_dsn=product_dsn,
        artifact_reader=make_filesystem_artifact_reader(args.artifact_store_dir),
        extract_text=_extract_non_pdf_text,
        embedding_provider=provider,
        pii_evidence_registry=authorities.pii_evidence_registry,
        rights_evidence_registry=authorities.rights_evidence_registry,
        manifest_digest=gate_result.manifest.manifest_fingerprint,
        placement_resolver=resolver,
    )
    max_iterations = 1 if args.once else args.max_iterations
    iterations = 0
    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        try:
            attestation = attest_runtime_role(conn, expected_role=args.expected_role)
        except WorkerAttestationError as exc:
            print(f"PUBLICATION_WORKER_ATTESTATION_FAILED: {exc}", file=sys.stderr)
            return 1
        print(
            f"PUBLICATION_WORKER_ATTESTATION_OK current_user={attestation.current_user}"
        )
        while max_iterations is None or iterations < max_iterations:
            reap_expired_job_leases(conn)
            conn.commit()
            outcome = run_publication_resume_iteration(conn, deps=deps)
            iterations += 1
            if outcome.worked:
                print(
                    f"PUBLICATION_WORKER_ITERATION job_id={outcome.job_id} "
                    f"status={outcome.status} artifact_id={outcome.artifact_id or ''} "
                    f"placements={outcome.placement_rows} chunks={outcome.chunk_rows}"
                )
                if outcome.error:
                    print(
                        f"PUBLICATION_WORKER_ITERATION_ERROR job_id={outcome.job_id}: "
                        f"{outcome.error}",
                        file=sys.stderr,
                    )
            elif args.once:
                print("PUBLICATION_WORKER_ITERATION no_job_available")
                break
            else:
                time.sleep(args.poll_interval_s)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
