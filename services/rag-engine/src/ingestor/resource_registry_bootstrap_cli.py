"""Operator CLI for the one-time governed Resource Registry bootstrap export."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from importlib import metadata
from pathlib import Path

import psycopg
from nexus_contracts.canonical_json import canonical_model_bytes

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

    release_registry = load_release_registry_file(
        args.release_registry_path,
        args.release_registry_sha256,
    )
    release_artifact_sha256s = frozenset(
        artifact.content_sha256
        for manifest in release_registry.manifests
        for artifact in manifest.expectation.artifacts
    )
    with psycopg.connect(dsn) as connection:
        inventory = export_resource_registry_bootstrap_inventory(
            connection,
            producer_repository="cyranoaladin/RAG",
            producer_commit=args.producer_commit,
            generated_at=args.generated_at,
            package_version=metadata.version("nexus-contracts"),
            release_collections=frozenset(release_registry.collections),
            release_artifact_sha256s=release_artifact_sha256s,
        )

    args.output.write_bytes(canonical_model_bytes(inventory) + b"\n")
    print(f"RESOURCE_REGISTRY_BOOTSTRAP_SHA256={inventory.inventory_sha256}")
    print(f"RESOURCE_REGISTRY_BOOTSTRAP_ROWS={len(inventory.resources)}")
    return 0


__all__ = ["DSN_ENV", "main"]
