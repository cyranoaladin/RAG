"""CLI staging Worker B pour une release multi-collections scellée."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg

from ingestor.embedding_provider import VerifiedE5EmbeddingProvider
from ingestor.ingestion_control.attestation import (
    WorkerAttestationError,
    attest_runtime_role,
)
from ingestor.ingestion_control.db import get_ingestion_control_dsn
from ingestor.ingestion_control.jobs import reap_expired_job_leases
from ingestor.ingestion_control.revocation_registry import (
    load_revocation_registry,
    load_shared_authorization_revocations,
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
from .publication_resume import PublicationResumeDeps, run_publication_resume_iteration
from .runtime_authority import RuntimeAuthorityStartupError
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
        description="Worker B staging gouverné pour release multi-collections"
    )
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--artifact-store-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True, type=_non_blank)
    parser.add_argument("--expected-role", required=True, type=_non_blank)
    add_multilevel_runtime_authority_arguments(parser)
    parser.add_argument("--embedding-artifact-root", required=True, type=Path)
    parser.add_argument(
        "--embedding-inventory-sha256",
        required=True,
        type=_non_blank,
    )
    # Preuves exigées uniquement en production (cf. _enforce_production_evidence).
    parser.add_argument("--release-registry-path", type=Path, default=None)
    parser.add_argument("--release-registry-sha256", default=None)
    parser.add_argument("--revocation-registry-path", type=Path, default=None)
    parser.add_argument("--revocation-registry-sha256", default=None)
    parser.add_argument("--expected-product-role", type=_non_blank, default=None)
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


def _product_dsn() -> str:
    dsn = os.environ.get("PG_RAG_DSN", "").strip()
    if not dsn:
        raise RuntimeAuthorityStartupError("PG_RAG_DSN is required for Worker B")
    return dsn


def _extract_non_pdf_text(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("latin-1")


def _enforce_production_evidence(
    args: argparse.Namespace,
    readiness: ReadinessGateResult,
    *,
    product_dsn: str,
) -> None:
    """Production exige des preuves supplémentaires, jamais un check en moins.

    Au-delà du registre de releases et du registre de révocation gouvernés
    (identiques à Worker A), Worker B publie réellement dans la base
    produit : son DSN produit ne doit jamais coïncider avec le DSN de
    contrôle d'ingestion, et le rôle qui l'utilise ne doit jamais être un
    superutilisateur ou porter un privilège de repli élevé."""
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
    loader = (
        load_shared_authorization_revocations
        if getattr(readiness.manifest, "protocol_version", "")
        == "NEXUS-PRODUCTION-READINESS-V2"
        else load_revocation_registry
    )
    revocation = loader(
        args.revocation_registry_path,
        expected_sha256=args.revocation_registry_sha256,
    )
    require_revocation_registry_matches_manifest(
        revocation,
        manifest_revocation_registry_digest=readiness.manifest.revocation_registry_digest,
    )

    if args.expected_product_role is None:
        raise RuntimeAuthorityStartupError(
            "production requires --expected-product-role for the product-publisher DSN"
        )
    if product_dsn == get_ingestion_control_dsn():
        raise RuntimeAuthorityStartupError(
            "production requires the product-publisher DSN and the ingestion-control "
            "DSN to be distinct — a single shared DSN collapses the role separation"
        )
    try:
        with psycopg.connect(product_dsn) as product_conn:
            attest_runtime_role(product_conn, expected_role=args.expected_product_role)
    except WorkerAttestationError as exc:
        raise RuntimeAuthorityStartupError(
            f"product-publisher DSN attestation failed: {exc}"
        ) from exc


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        readiness = enforce_readiness_gate()
        if readiness.environment not in ("rehearsal", "production"):
            raise RuntimeAuthorityStartupError(
                "multilevel worker requires rehearsal or production readiness"
            )
        product_dsn = _product_dsn()
        if readiness.environment == "production":
            _enforce_production_evidence(args, readiness, product_dsn=product_dsn)
        profiles = load_profile_registry(args.profiles_dir)
        authorities = load_multilevel_runtime_authorities(
            multilevel_runtime_authority_inputs_from_args(args),
            profile_registry=profiles,
            environment=readiness.environment,
        )
        resolver = authorities.placement_resolver
        readiness_mapping = getattr(readiness, "authorization_mapping", None)
        if (
            readiness_mapping is not None
            and resolver.release_profile_manifest_digest
            != readiness_mapping.profile_manifest_digest
        ):
            raise RuntimeAuthorityStartupError(
                "loaded profile manifest digest differs from the signed authorization set"
            )
        if (
            resolver.release_embedding_model_id != VerifiedE5EmbeddingProvider.model_id
            or resolver.release_embedding_dimension != VerifiedE5EmbeddingProvider.dimension
            or resolver.release_embedding_inventory_sha256 != args.embedding_inventory_sha256
        ):
            raise RuntimeAuthorityStartupError(
                "embedding provider inputs differ from the release manifest"
            )
        provider = VerifiedE5EmbeddingProvider.from_artifact(
            artifact_root=args.embedding_artifact_root,
            inventory_sha256=args.embedding_inventory_sha256,
            pg_dsn=product_dsn,
        )
    except Exception as exc:  # frontière CLI fail-closed avant control PostgreSQL
        print(f"MULTILEVEL_PUBLICATION_WORKER_STARTUP_FAILED: {exc}", file=sys.stderr)
        return 1

    if readiness.environment == "production":
        print(
            "MULTILEVEL_PUBLICATION_WORKER_STARTUP_AUTHORITY "
            "authority_mode=PRODUCTION_SIGNED_READINESS_MANIFEST "
            f"release_registry_sha256={args.release_registry_sha256} "
            f"revocation_registry_sha256={args.revocation_registry_sha256} "
            f"profile_manifest_sha256={args.profile_manifest_sha256} "
            f"declared_count={len(profiles)} "
            f"embedding_inventory_sha256={args.embedding_inventory_sha256}"
        )
    else:
        print(
            "MULTILEVEL_PUBLICATION_WORKER_STARTUP_AUTHORITY "
            "authority_mode=STAGING_LOCAL_GITHUB_ONLY production_approval=false "
            f"release_manifest_sha256={args.release_manifest_sha256} "
            f"profile_manifest_sha256={args.profile_manifest_sha256} "
            f"declared_count={len(profiles)} "
            f"embedding_inventory_sha256={args.embedding_inventory_sha256}"
        )
    deps = PublicationResumeDeps(
        owner=args.owner,
        product_dsn=product_dsn,
        artifact_reader=make_filesystem_artifact_reader(args.artifact_store_dir),
        extract_text=_extract_non_pdf_text,
        embedding_provider=provider,
        pii_evidence_registry=authorities.pii_evidence_registry,
        rights_evidence_registry=authorities.rights_evidence_registry,
        manifest_digest=resolver.release_profile_manifest_digest,
        placement_resolver=resolver,
        authorization_mapping=getattr(readiness, "authorization_mapping", None),
        authorization_context=getattr(readiness, "authorization_context", None),
    )
    max_iterations = 1 if args.once else args.max_iterations
    iterations = 0
    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        try:
            attestation = attest_runtime_role(conn, expected_role=args.expected_role)
        except WorkerAttestationError as exc:
            print(
                f"MULTILEVEL_PUBLICATION_WORKER_ATTESTATION_FAILED: {exc}",
                file=sys.stderr,
            )
            return 1
        print(
            "MULTILEVEL_PUBLICATION_WORKER_ATTESTATION_OK "
            f"current_user={attestation.current_user}"
        )
        _write_heartbeat(args.heartbeat_file)
        while max_iterations is None or iterations < max_iterations:
            reap_expired_job_leases(conn)
            conn.commit()
            outcome = run_publication_resume_iteration(conn, deps=deps)
            iterations += 1
            _write_heartbeat(args.heartbeat_file)
            if outcome.worked:
                print(
                    f"MULTILEVEL_PUBLICATION_WORKER_ITERATION job_id={outcome.job_id} "
                    f"status={outcome.status} artifact_id={outcome.artifact_id or ''} "
                    f"placements={outcome.placement_rows} chunks={outcome.chunk_rows}"
                )
                if outcome.error:
                    print(
                        "MULTILEVEL_PUBLICATION_WORKER_ITERATION_ERROR "
                        f"job_id={outcome.job_id}: {outcome.error}",
                        file=sys.stderr,
                    )
            elif args.once:
                print("MULTILEVEL_PUBLICATION_WORKER_ITERATION no_job_available")
                break
            else:
                time.sleep(args.poll_interval_s)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
