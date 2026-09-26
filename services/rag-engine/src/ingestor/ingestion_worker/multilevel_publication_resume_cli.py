"""CLI staging Worker B pour une release multi-collections scellée."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg
from nexus_contracts.staging_readiness import STAGING_READINESS_PROTOCOL
from nexus_release_chain.release_readiness import load_release_registry_file

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
from ingestor.ingestion_profiles.release_qualification import (
    ReleaseBoundQualification,
    qualify_release_from_staging_readiness,
)
from ingestor.ingestion_profiles.staging_readiness_gate import (
    EXPECTED_PROTOCOL_ENV,
    enforce_staging_readiness_gate,
    require_running_image_matches_manifest,
)

from .multilevel_runtime_authority import (
    add_multilevel_runtime_authority_arguments,
    load_multilevel_runtime_authorities,
    multilevel_runtime_authority_inputs_from_args,
)
from .publication_resume import PublicationResumeDeps, run_publication_resume_iteration
from .runtime_authority import RuntimeAuthorityStartupError
from .storage import (
    make_filesystem_artifact_reader,
    make_sealed_release_artifact_reader,
)

DEFAULT_POLL_INTERVAL_S = 5.0
#: Lot DI — plafond d'une pause imposée par GitHub. Au-delà, le worker
#: s'arrête (code ``EXIT_RATE_LIMITED``) plutôt que de dormir sans borne :
#: la reprise redevient une décision d'opérateur.
DEFAULT_RATE_LIMIT_MAX_WAIT_S = 900.0
DEFAULT_MAX_CONSECUTIVE_RATE_LIMITS = 3
#: EX_TEMPFAIL : rien n'a échoué, rien n'a été publié à tort ; la file est
#: intacte et le même lancement pourra reprendre plus tard.
EXIT_RATE_LIMITED = 75


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
        "--collection",
        action="append",
        default=[],
        type=_non_blank,
        help=(
            "Lot DI — liste d'autorisation (répétable) des collections dont les "
            "jobs peuvent être réclamés. Absente : toute la file (comportement "
            "historique). Chaque collection doit appartenir à la release et se "
            "résoudre par ses mappings scellés, sinon le démarrage est refusé."
        ),
    )
    parser.add_argument(
        "--min-job-interval-s",
        type=_finite_non_negative_float,
        default=0.0,
        help=(
            "Lot DI — délai minimal entre deux réclamations de job (cadence des "
            "vérifications GitHub live). 0 : comportement historique."
        ),
    )
    parser.add_argument(
        "--rate-limit-max-wait-s",
        type=_finite_non_negative_float,
        default=DEFAULT_RATE_LIMIT_MAX_WAIT_S,
    )
    parser.add_argument(
        "--max-consecutive-rate-limits",
        type=_positive_int,
        default=DEFAULT_MAX_CONSECUTIVE_RATE_LIMITS,
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


def _require_distinct_control_and_product_dsn(product_dsn: str) -> None:
    """La séparation des rôles vaut dans TOUS les environnements.

    Ce refus vivait dans `_enforce_production_evidence`, donc en production
    seulement : un staging pouvait publier avec un DSN unique, et la
    séparation entre contrôle d'ingestion et base produit s'effondrait
    silencieusement là où on la qualifie justement. Lot CH4 : la garde
    s'applique aussi en rehearsal. Elle n'est retirée nulle part.
    """
    if product_dsn == get_ingestion_control_dsn():
        raise RuntimeAuthorityStartupError(
            "the product-publisher DSN and the ingestion-control DSN must be "
            "distinct — a single shared DSN collapses the role separation"
        )


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
        # ADR-0060 : une readiness de STAGING qualifie une release nommée ; la
        # qualification se déduit de la readiness vérifiée, jamais d'un
        # argument. Toute autre readiness suit le chemin inchangé.
        readiness: ReadinessGateResult | None = None
        qualification: ReleaseBoundQualification | None = None
        if os.environ.get(EXPECTED_PROTOCOL_ENV, "") == STAGING_READINESS_PROTOCOL:
            staging = enforce_staging_readiness_gate()
            qualification = qualify_release_from_staging_readiness(
                staging,
                release_manifest_path=args.release_manifest_path,
                release_manifest_sha256=args.release_manifest_sha256,
                running_image=require_running_image_matches_manifest(staging.manifest),
            )
            environment = staging.environment
        else:
            readiness = enforce_readiness_gate()
            environment = readiness.environment
        if environment not in ("rehearsal", "production"):
            raise RuntimeAuthorityStartupError(
                "multilevel worker requires rehearsal or production readiness"
            )
        product_dsn = _product_dsn()
        _require_distinct_control_and_product_dsn(product_dsn)
        if environment == "production":
            assert readiness is not None
            _enforce_production_evidence(args, readiness, product_dsn=product_dsn)
        profiles = load_profile_registry(args.profiles_dir)
        authorities = load_multilevel_runtime_authorities(
            multilevel_runtime_authority_inputs_from_args(args),
            profile_registry=profiles,
            environment=environment,
            qualification=qualification,
        )
        resolver = authorities.placement_resolver
        claim_collections = tuple(dict.fromkeys(args.collection)) or None
        # Lot DI : aucune collection réclamable dont les mappings scellés ne
        # résolvent pas les faits — refus AVANT toute réclamation, au lieu
        # d'un échec job par job qui consomme les tentatives.
        resolver.require_collections_governed(claim_collections)
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

    if environment == "production":
        print(
            "MULTILEVEL_PUBLICATION_WORKER_STARTUP_AUTHORITY "
            "authority_mode=PRODUCTION_SIGNED_READINESS_MANIFEST "
            f"release_registry_sha256={args.release_registry_sha256} "
            f"revocation_registry_sha256={args.revocation_registry_sha256} "
            f"profile_manifest_sha256={args.profile_manifest_sha256} "
            f"declared_count={len(profiles)} "
            f"embedding_inventory_sha256={args.embedding_inventory_sha256}"
        )
    elif qualification is not None:
        print(
            "MULTILEVEL_PUBLICATION_WORKER_STARTUP_AUTHORITY "
            "authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION production_approval=false "
            f"release_id={qualification.release_id} "
            f"release_manifest_sha256={qualification.release_manifest_sha256} "
            f"readiness_manifest_sha256={qualification.readiness_manifest_sha256} "
            f"worker_image={qualification.worker_image} "
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
        # Le magasin transporte aussi les objets SCELLES, nommes par
        # leur empreinte. Le lecteur les relit sous la meme protection
        # et re-mesure leur digest avant toute publication.
        sealed_artifact_reader=make_sealed_release_artifact_reader(
            args.artifact_store_dir
        ),
        extract_text=_extract_non_pdf_text,
        embedding_provider=provider,
        pii_evidence_registry=authorities.pii_evidence_registry,
        rights_evidence_registry=authorities.rights_evidence_registry,
        manifest_digest=resolver.release_profile_manifest_digest,
        placement_resolver=resolver,
        authorization_mapping=getattr(readiness, "authorization_mapping", None),
        authorization_context=getattr(readiness, "authorization_context", None),
        # Le catalogue SCELLE, charge au demarrage par le chemin canonique.
        # Il n'est pas construit ici : le CLI le transporte, il ne l'invente
        # pas. Absent, la branche scellee refusera de lire — ce qui est le
        # comportement voulu pour une release qui n'en porte pas.
        sealed_release_artifacts=(
            authorities.sealed_release_catalog.artifacts
            if authorities.sealed_release_catalog is not None
            else None
        ),
        sealed_media_type_invariant=(
            authorities.sealed_release_catalog.media_type_invariant
            if authorities.sealed_release_catalog is not None
            else ""
        ),
        claim_collections=claim_collections,
    )
    if claim_collections is not None:
        print(
            "MULTILEVEL_PUBLICATION_WORKER_CLAIM_SCOPE "
            f"collections={','.join(claim_collections)}"
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
        consecutive_rate_limits = 0
        last_claim_at: float | None = None
        while max_iterations is None or iterations < max_iterations:
            if last_claim_at is not None and args.min_job_interval_s > 0:
                pause = args.min_job_interval_s - (time.monotonic() - last_claim_at)
                if pause > 0:
                    time.sleep(pause)
            reap_expired_job_leases(conn)
            conn.commit()
            last_claim_at = time.monotonic()
            outcome = run_publication_resume_iteration(conn, deps=deps)
            iterations += 1
            _write_heartbeat(args.heartbeat_file)
            if outcome.status == "rate_limited":
                consecutive_rate_limits += 1
                wait_s = float(outcome.retry_after_s or 0.0)
                print(
                    "MULTILEVEL_PUBLICATION_WORKER_RATE_LIMITED "
                    f"job_id={outcome.job_id} wait_s={wait_s:.0f} "
                    f"consecutive={consecutive_rate_limits} attempt_consumed=false",
                    file=sys.stderr,
                )
                if (
                    consecutive_rate_limits >= args.max_consecutive_rate_limits
                    or wait_s > args.rate_limit_max_wait_s
                ):
                    print(
                        "MULTILEVEL_PUBLICATION_WORKER_RATE_LIMITED_STOP "
                        f"wait_s={wait_s:.0f} consecutive={consecutive_rate_limits} "
                        f"exit_code={EXIT_RATE_LIMITED}",
                        file=sys.stderr,
                    )
                    return EXIT_RATE_LIMITED
                # Suspendre TOUTE réclamation : continuer d'appeler GitHub
                # pendant une limitation la prolonge.
                time.sleep(wait_s)
                continue
            if outcome.worked and outcome.status != "lease_lost":
                consecutive_rate_limits = 0
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
