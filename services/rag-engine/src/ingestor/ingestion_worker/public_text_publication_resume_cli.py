"""Entrée Worker B du successeur public, exclusivement dérivé texte A/C."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from nexus_contracts.staging_readiness import STAGING_READINESS_PROTOCOL
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationVerdict,
    verify_public_successor_activation,
)
from nexus_release_chain.release_readiness import (
    RELEASE_AUTHORITY_REGISTRY_FILE,
    load_selected_release_registry,
    select_release_authority,
)

from ingestor.embedding_provider import VerifiedE5EmbeddingProvider
from ingestor.ingestion_control.attestation import attest_runtime_role
from ingestor.ingestion_control.db import get_ingestion_control_dsn
from ingestor.ingestion_control.release_batch_attestation import (
    measure_release_batch_facts,
    require_facts_match_catalog,
)
from ingestor.ingestion_profiles.readiness_gate import enforce_readiness_gate
from ingestor.ingestion_profiles.staging_readiness_gate import (
    EXPECTED_PROTOCOL_ENV,
    enforce_staging_readiness_gate,
)

from .multilevel_publication_resume_cli import (
    _finite_non_negative_float,
    _non_blank,
    _positive_int,
)
from .public_text_runtime_authority import (
    PublicTextRuntimeAuthorities,
    load_public_text_runtime_authorities,
)
from .publication_resume import PublicationResumeDeps
from .storage import (
    make_filesystem_artifact_reader,
    make_sealed_derivative_receipt_reader,
    make_sealed_release_artifact_reader,
)

_SHA = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class _SignedPublication:
    environment: str
    release_id: str
    manifest_sha256: str
    anchor_sha256: str
    envelope_sha256: str


def _signed_publication(root: Path) -> _SignedPublication:
    if os.environ.get(EXPECTED_PROTOCOL_ENV) == STAGING_READINESS_PROTOCOL:
        verified = enforce_staging_readiness_gate()
        manifest = verified.manifest
        if manifest.public_successor_phase != "PUBLICATION":
            raise ValueError("signed staging readiness is not PUBLICATION")
        return _SignedPublication(
            environment="rehearsal",
            release_id=manifest.allowed_release_id,
            manifest_sha256=manifest.allowed_release_manifest_sha256,
            anchor_sha256=manifest.public_successor_content_anchor_digest,
            envelope_sha256=manifest.public_successor_phase_authority_digest,
        )
    verified = enforce_readiness_gate()
    manifest = verified.manifest
    if verified.environment != "production" or any(
        getattr(manifest, field, None) is None for field in (
            "public_successor_content_manifest_digest",
            "public_successor_content_anchor_digest",
            "public_successor_authority_envelope_digest",
        )
    ):
        raise ValueError("signed production readiness lacks public A/C")
    selection = select_release_authority()
    expected_path = root / "release" / "release-registry.json"
    if (
        selection is None
        or selection.mechanism != RELEASE_AUTHORITY_REGISTRY_FILE
        or len(selection.bindings) != 1
        or selection.bindings[0][0].resolve() != expected_path.resolve()
        or selection.bindings[0][1] != _required_sha_env("RAG_RELEASE_REGISTRY_SHA256")
    ):
        raise ValueError("production public Worker B requires the selected A release registry")
    registry = load_selected_release_registry(selection)
    if len(registry.manifests) != 1 or (
        registry.manifests[0].expected_sha256
        != manifest.public_successor_content_manifest_digest
        or manifest.sealed_manifest_digest
        != manifest.public_successor_content_manifest_digest
    ):
        raise ValueError("signed production readiness differs from A registry")
    return _SignedPublication(
        environment="production",
        release_id=registry.manifests[0].expectation.release_id,
        manifest_sha256=manifest.public_successor_content_manifest_digest,
        anchor_sha256=manifest.public_successor_content_anchor_digest,
        envelope_sha256=manifest.public_successor_authority_envelope_digest,
    )


def _required_sha_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if _SHA.fullmatch(value) is None:
        raise ValueError(f"{name} must be an explicit SHA-256 digest")
    return value


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker B des dérivés publics A/C")
    parser.add_argument("--public-successor-bundle-root", type=Path, required=True)
    parser.add_argument("--artifact-store-dir", type=Path, required=True)
    parser.add_argument("--owner", required=True, type=_non_blank)
    parser.add_argument("--expected-role", required=True, type=_non_blank)
    parser.add_argument("--expected-product-role", type=_non_blank, default=None)
    parser.add_argument("--embedding-artifact-root", type=Path, required=True)
    parser.add_argument("--embedding-inventory-sha256", required=True, type=_non_blank)
    parser.add_argument("--collection", action="append", required=True, type=_non_blank)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-iterations", type=_positive_int, default=None)
    parser.add_argument("--poll-interval-s", type=_finite_non_negative_float, default=5.0)
    parser.add_argument("--min-job-interval-s", type=_finite_non_negative_float, default=0.0)
    parser.add_argument("--rate-limit-max-wait-s", type=_finite_non_negative_float, default=900.0)
    parser.add_argument("--max-consecutive-rate-limits", type=_positive_int, default=3)
    parser.add_argument("--max-idle-polls", type=_positive_int, default=None)
    parser.add_argument("--heartbeat-file", type=Path, default=None)
    return parser


def _transfer_authority(root: Path, envelope_sha256: str) -> tuple[Path, str]:
    path = root / "authority-envelope.json"
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != envelope_sha256:
        raise ValueError("signed authority envelope differs")
    envelope = json.loads(path.read_bytes())
    digest = envelope["authorities"]["artifact_transfer_manifest_sha256"]
    if _SHA.fullmatch(digest) is None:
        raise ValueError("public transfer manifest digest invalid")
    transfer = root / "authorities" / "artifact_transfer_manifest_sha256.bin"
    if transfer.is_symlink() or hashlib.sha256(transfer.read_bytes()).hexdigest() != digest:
        raise ValueError("public transfer manifest differs from C")
    return transfer, digest


def _verified_runtime(
    root: Path,
) -> tuple[_SignedPublication, PublicSuccessorActivationVerdict, PublicTextRuntimeAuthorities]:
    signed = _signed_publication(root)
    registry_sha = _required_sha_env("RAG_RELEASE_REGISTRY_SHA256")
    scope_sha = _required_sha_env("NEXUS_PUBLIC_SCOPE_AUTHORITY_SHA256")
    verdict = verify_public_successor_activation(
        root,
        expected_content_anchor_sha256=signed.anchor_sha256,
        expected_authority_envelope_sha256=signed.envelope_sha256,
        expected_release_id=signed.release_id,
        expected_registry_sha256=registry_sha,
        expected_scope_authority_sha256=scope_sha,
    )
    if not isinstance(verdict, PublicSuccessorActivationVerdict) or (
        verdict.release_id != signed.release_id
        or verdict.content_manifest_sha256 != signed.manifest_sha256
        or verdict.content_anchor_sha256 != signed.anchor_sha256
        or verdict.authority_envelope_sha256 != signed.envelope_sha256
        or verdict.release_registry_sha256 != registry_sha
        or verdict.scope_authority_sha256 != scope_sha
    ):
        raise ValueError("typed public activation C differs from signed readiness")
    transfer_path, transfer_sha = _transfer_authority(root, signed.envelope_sha256)
    authorities = load_public_text_runtime_authorities(
        release_root=root / "release",
        content_anchor_path=root / "content-anchor.json",
        expected_content_anchor_sha256=signed.anchor_sha256,
        activation=verdict,
        transfer_manifest_path=transfer_path,
        expected_transfer_manifest_sha256=transfer_sha,
    )
    return signed, verdict, authorities


def require_public_lot42_db(
    conn: psycopg.Connection,
    *,
    activation: PublicSuccessorActivationVerdict,
    authorities: PublicTextRuntimeAuthorities,
    transfer_sha256: str,
) -> None:
    """Comparer le LOT42 de cette DB avec A/C avant une mutation de bail."""
    facts = measure_release_batch_facts(conn, release_id=activation.release_id)
    require_facts_match_catalog(facts, authorities.sealed_release_catalog)
    if (
        facts.release_manifest_sha256 != activation.content_manifest_sha256
        or facts.candidate_inventory_sha256
        != authorities.placement_resolver._candidate_inventory_sha256
        or facts.artifact_transfer_manifest_sha256 != transfer_sha256
        or facts.subjects != activation.counts["subjects"]
        or facts.placements != activation.counts["placements"]
        or facts.unique_artifacts != activation.counts["unique_artifacts"]
        or facts.unique_chunks != activation.counts["unique_chunks"]
        or set(facts.collections) != authorities.placement_resolver.collections
    ):
        raise ValueError("live LOT42 batch facts differ from public A/C")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT resource_id, content_sha256, collection, attestation_id "
            "FROM ingestion_control.publication_attestations "
            "WHERE release_id = %s AND release_manifest_sha256 = %s "
            "AND protocol_version = 'LOT42-RELEASE-BATCH-V1' "
            "AND invalidated_at IS NULL",
            (activation.release_id, activation.content_manifest_sha256),
        )
        rows = cur.fetchall()
    expected = {
        (resource_id, content_sha256, collection)
        for resource_id, (_, content_sha256, collection, _) in facts.par_ressource.items()
    }
    actual = {(row[0], row[1], row[2]) for row in rows}
    if len(rows) != len(expected) or actual != expected or any(row[3] is None for row in rows):
        raise ValueError("live LOT42 publication attestation coverage incomplete")
    # Ces SELECT ne confèrent aucune autorité d'écriture : clore la transaction
    # sans enregistrer d'effet potentiel sur la connexion réutilisée par Worker B.
    conn.rollback()


def main_public(argv: list[str]) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        signed, verdict, authorities = _verified_runtime(args.public_successor_bundle_root)
        collections = tuple(dict.fromkeys(args.collection))
        authorities.placement_resolver.require_collections_governed(collections)
        if args.embedding_inventory_sha256 != authorities.placement_resolver.release_embedding_inventory_sha256:
            raise ValueError("embedding inventory differs from A")
        product_dsn = os.environ.get("PG_RAG_DSN", "").strip()
        if not product_dsn or product_dsn == get_ingestion_control_dsn():
            raise ValueError("public Worker B requires distinct product and control DSNs")
        if signed.environment == "production" and not args.expected_product_role:
            raise ValueError("production public Worker B requires expected product role")
        provider = VerifiedE5EmbeddingProvider.from_artifact(
            artifact_root=args.embedding_artifact_root,
            inventory_sha256=args.embedding_inventory_sha256,
            pg_dsn=product_dsn,
        )
        if signed.environment == "production":
            with psycopg.connect(product_dsn) as product_conn:
                attest_runtime_role(product_conn, expected_role=args.expected_product_role)
        deps = PublicationResumeDeps(
            owner=args.owner,
            product_dsn=product_dsn,
            artifact_reader=make_filesystem_artifact_reader(args.artifact_store_dir),
            sealed_artifact_reader=make_sealed_release_artifact_reader(
                args.artifact_store_dir, media_type="text/plain; charset=utf-8",
            ),
            sealed_derivative_receipt_reader=make_sealed_derivative_receipt_reader(
                args.artifact_store_dir,
            ),
            extract_text=lambda raw: raw.decode("utf-8"),
            embedding_provider=provider,
            pii_evidence_registry=authorities.pii_evidence_registry,
            rights_evidence_registry=authorities.rights_evidence_registry,
            manifest_digest=authorities.placement_resolver.release_profile_manifest_digest,
            placement_resolver=authorities.placement_resolver,
            sealed_release_artifacts=authorities.sealed_release_catalog.artifacts,
            sealed_media_type_invariant=authorities.sealed_release_catalog.media_type_invariant,
            claim_collections=collections,
            claim_release_id=verdict.release_id,
            claim_release_manifest_sha256=verdict.content_manifest_sha256,
        )
    except Exception as exc:
        print(f"PUBLIC_TEXT_WORKER_STARTUP_FAILED: {exc}", file=sys.stderr)
        return 1
    from .multilevel_publication_resume_cli import _run_worker_loop

    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        try:
            attest_runtime_role(conn, expected_role=args.expected_role)
            transfer, transfer_sha = _transfer_authority(
                args.public_successor_bundle_root, signed.envelope_sha256,
            )
            del transfer

            def reverify() -> None:
                fresh_signed, fresh_verdict, fresh_authorities = _verified_runtime(
                    args.public_successor_bundle_root,
                )
                if fresh_signed != signed or fresh_verdict != verdict:
                    raise ValueError("public readiness or C drifted during Worker B")
                require_public_lot42_db(
                    conn, activation=fresh_verdict,
                    authorities=fresh_authorities, transfer_sha256=transfer_sha,
                )

            reverify()
            return _run_worker_loop(
                conn, deps=deps, args=args,
                max_iterations=1 if args.once else args.max_iterations,
                pre_iteration=reverify,
            )
        except Exception as exc:
            print(f"PUBLIC_TEXT_WORKER_AUTHORITY_FAILED: {exc}", file=sys.stderr)
            return 1


__all__ = ["main_public", "require_public_lot42_db"]
