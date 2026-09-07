"""Phase B of a governed R1 export attempt: the ONE credential-handling
step. Runs the governed exporter and, immediately afterward -- in the same
process, with the credential already discarded from this process's own
environment -- the R1 evidence verifier, against the EXACT bootstrap path
this same invocation just published. No subshell boundary exists between
"run the exporter" and "run the verifier" here: it is one Python process,
so there is no shell-variable-continuity class of bug to have.

Takes ``--bootstrap-out``/``--report-out`` as explicit arguments (normally
the exact values ``r1_attempt_preflight_cli.py`` printed for this same
attempt) rather than recomputing or rediscovering them -- no globbing, no
"latest file" heuristic, ever.

Reads the production DSN from the ``NEXUS_RESOURCE_EXPORT_DSN`` environment
variable (never from argv), and pops it from this process's own
``os.environ`` immediately after the exporter step, before the verifier
step runs -- the verifier never opens a database connection to begin with,
but this makes "the DSN is gone before verification" a checked fact about
this process, not merely a true statement about what the verifier happens
not to use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
from ingestor.r1_evidence_verifier import R1EvidenceVerifierError, verify_r1_evidence
from ingestor.r1_operator_flow import EXPECTED_SEALED_RELEASE_REGISTRY_SHA256
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
        description=(
            "Run the governed R1 exporter, then immediately the R1 evidence "
            "verifier, in one process, against one already-resolved attempt's "
            "paths. The only step in the R1 flow that opens a database "
            "connection."
        )
    )
    parser.add_argument("--producer-commit", required=True)
    parser.add_argument("--generated-at", required=True, type=_aware_datetime)
    parser.add_argument("--bootstrap-out", required=True, type=Path)
    parser.add_argument("--report-out", required=True, type=Path)
    parser.add_argument("--release-registry-path", required=True, type=Path)
    parser.add_argument("--profile-root", required=True, type=Path)
    parser.add_argument("--profile-manifest-path", required=True, type=Path)
    args = parser.parse_args(argv)

    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        raise SystemExit(f"{DSN_ENV} is required and is never accepted on argv")

    # Fail before ever touching the production database.
    try:
        assert_publishable(args.bootstrap_out)
        assert_publishable(args.report_out)
    except AtomicArtifactError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        release_registry = load_release_registry_file(
            args.release_registry_path,
            EXPECTED_SEALED_RELEASE_REGISTRY_SHA256,
        )
    except Exception as exc:
        raise SystemExit(f"release authority is not sound: {exc}") from exc

    release_artifact_bindings = frozenset(
        (artifact.collection, artifact.content_sha256)
        for manifest in release_registry.manifests
        for artifact in manifest.expectation.artifacts
    )

    try:
        with psycopg.connect(dsn) as connection:
            inventory = export_resource_registry_bootstrap_inventory(
                connection,
                producer_repository="cyranoaladin/RAG",
                producer_commit=args.producer_commit,
                generated_at=args.generated_at,
                package_version=metadata.version("nexus-contracts"),
                release_collections=frozenset(release_registry.collections),
                release_artifact_bindings=release_artifact_bindings,
            )
    finally:
        # The DSN is never needed again in this process. Discarding both
        # the local reference and the environment entry makes "gone before
        # the verifier runs" a fact about this process's own state, not
        # merely a true statement about what the verifier happens to use.
        dsn = None  # noqa: F841 -- best-effort local scrub
        os.environ.pop(DSN_ENV, None)

    try:
        publish_atomic_no_clobber(args.bootstrap_out, canonical_model_bytes(inventory) + b"\n")
    except AtomicArtifactError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"RESOURCE_REGISTRY_BOOTSTRAP_SHA256={inventory.inventory_sha256}")
    print(f"RESOURCE_REGISTRY_BOOTSTRAP_ROWS={len(inventory.resources)}")

    assert DSN_ENV not in os.environ, "DSN must be gone before the verifier ever runs"

    try:
        report = verify_r1_evidence(
            bootstrap_path=args.bootstrap_out,
            release_registry_path=args.release_registry_path,
            release_registry_sha256=EXPECTED_SEALED_RELEASE_REGISTRY_SHA256,
            profile_root=args.profile_root,
            profile_manifest_path=args.profile_manifest_path,
        )
    except R1EvidenceVerifierError as exc:
        print(f"R1_EVIDENCE_VERIFIER_ERROR={exc}", file=sys.stderr)
        return 2

    serialized = json.dumps(report.to_json(), indent=2, sort_keys=True, ensure_ascii=False)
    try:
        publish_atomic_no_clobber(args.report_out, (serialized + "\n").encode("utf-8"))
    except AtomicArtifactError as exc:
        raise SystemExit(str(exc)) from exc

    for key, value in report.gates.items():
        if isinstance(value, list | dict):
            continue
        print(f"{key}={value}")
    print(f"R1_EVIDENCE_BLOCKERS={len(report.blockers)}")
    for blocker in report.blockers:
        print(f"R1_EVIDENCE_BLOCKER={blocker}")
    print(f"R1_EVIDENCE_READY={'YES' if report.ready else 'NO'}")

    return 0 if report.ready else 1


__all__ = ["DSN_ENV", "main"]
