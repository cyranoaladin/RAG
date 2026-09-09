"""Operator CLI for the one-time governed Resource Registry bootstrap export."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from importlib import metadata
from pathlib import Path

import psycopg
from nexus_contracts.canonical_json import canonical_model_bytes

from ingestor.atomic_artifact import (
    AtomicArtifactError,
    assert_publishable,
    publish_atomic_no_clobber,
)
from ingestor.release_readiness import load_release_registry_file
from ingestor.resource_registry_bootstrap import (
    export_resource_registry_bootstrap_inventory,
)

DSN_ENV = "NEXUS_RESOURCE_EXPORT_DSN"


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("generated-at must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("generated-at must include a timezone")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export governed RAG ResourceVersion identities without mutation"
    )
    parser.add_argument("--producer-commit", required=True)
    parser.add_argument("--generated-at", required=True, type=_aware_datetime)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--release-registry-path", required=True, type=Path)
    parser.add_argument("--release-registry-sha256", required=True)
    args = parser.parse_args(argv)

    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        raise SystemExit(f"{DSN_ENV} is required and is never accepted on argv")

    # Fail before ever touching the production database: an operator must
    # never discover an unusable --output only after the DB round trip.
    # This is a fast pre-flight only -- publish_atomic_no_clobber below is
    # the authoritative, race-free no-clobber guard.
    try:
        assert_publishable(args.output)
    except AtomicArtifactError as exc:
        raise SystemExit(str(exc)) from exc

    release_registry = load_release_registry_file(
        args.release_registry_path,
        args.release_registry_sha256,
    )
    release_artifact_bindings = frozenset(
        (artifact.collection, artifact.content_sha256)
        for manifest in release_registry.manifests
        for artifact in manifest.expectation.artifacts
    )
    # R1G: the same digest-verified ``ExpectedArtifact.chunks`` the release
    # readiness authority already parsed -- no parallel JSON parsing, no
    # filename heuristics, reused exactly as loaded.
    release_chunk_bindings = frozenset(
        (
            artifact.content_sha256,
            str(chunk["chunk_id"]),
            int(chunk["chunk_index"]),
            str(chunk["chunk_sha256"]),
            int(chunk["page_start"]),
            int(chunk["page_end"]),
        )
        for manifest in release_registry.manifests
        for artifact in manifest.expectation.artifacts
        for chunk in artifact.chunks
    )
    with psycopg.connect(dsn) as connection:
        inventory = export_resource_registry_bootstrap_inventory(
            connection,
            producer_repository="cyranoaladin/RAG",
            producer_commit=args.producer_commit,
            generated_at=args.generated_at,
            package_version=metadata.version("nexus-contracts"),
            release_collections=frozenset(release_registry.collections),
            release_artifact_bindings=release_artifact_bindings,
            release_chunk_bindings=release_chunk_bindings,
        )

    try:
        publish_atomic_no_clobber(args.output, canonical_model_bytes(inventory) + b"\n")
    except AtomicArtifactError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"RESOURCE_REGISTRY_BOOTSTRAP_SHA256={inventory.inventory_sha256}")
    print(f"RESOURCE_REGISTRY_BOOTSTRAP_ROWS={len(inventory.resources)}")
    # Reaching this line means the exporter's own pre-publication chunk-set
    # comparison (export_resource_registry_bootstrap_inventory) already
    # passed -- a mismatch raises BootstrapInventoryError before any output
    # is written, so this is a positive report, not a re-check.
    print("R1_DB_CHUNK_IDENTITY_BINDING=PASS")
    return 0


__all__ = ["DSN_ENV", "main"]
