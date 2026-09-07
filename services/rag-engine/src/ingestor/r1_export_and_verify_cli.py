"""Phase B of a governed R1 export attempt: the ONE credential-handling
step. Runs the governed exporter and, immediately afterward -- in the same
process, with the credential already discarded from this process's own
environment -- the R1 evidence verifier, against the EXACT bootstrap path
this same invocation just published. No subshell boundary exists between
"run the exporter" and "run the verifier" here: it is one Python process,
so there is no shell-variable-continuity class of bug to have.

Takes exactly one non-secret input: ``--attempt-state``, the immutable JSON
file Phase A (``r1_attempt_preflight_cli.py``) published. Every other fact
this step needs (the qualified commit, the sealed release identity and
digest, the profile authority paths, the bootstrap/report output paths) is
either loaded from that file and independently re-validated, or derived
fresh from the live repository at the moment this process actually runs --
never accepted as a second, separately-supplied CLI argument that could
silently disagree with the attempt state. In particular:

- the actual git HEAD is re-verified against the state's own
  ``qualified_exporter_commit`` (TOCTOU closure: HEAD, or the worktree's
  cleanliness, could have changed since Phase A ran) and its own,
  freshly-confirmed value -- never the state's claimed value on its own --
  becomes the exporter's ``producer_commit``;
- ``generated_at`` is captured internally, at the moment of the actual
  export call, never accepted as an operator-supplied timestamp;
- the profile authority and release-registry paths are derived from the
  state's own ``repo_root``, never independently operator-supplied.

Reads the production DSN from the ``NEXUS_RESOURCE_EXPORT_DSN`` environment
variable (never from argv), and pops it from this process's own
``os.environ`` immediately after the exporter step, before the verifier
step runs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import psycopg
from nexus_contracts.canonical_json import canonical_model_bytes

from ingestor.atomic_artifact import AtomicArtifactError, publish_atomic_no_clobber
from ingestor.r1_evidence_verifier import (
    R1EvidenceReport,
    R1EvidenceVerifierError,
    verify_r1_evidence,
)
from ingestor.r1_operator_flow import (
    EXPECTED_SEALED_RELEASE_REGISTRY_SHA256,
    R1AttemptState,
    R1OperatorFlowError,
    canonical_profile_paths,
    load_attempt_state,
    revalidate_attempt_state_against_live_repo,
)
from ingestor.release_readiness import load_release_registry_file
from ingestor.resource_registry_bootstrap import (
    export_resource_registry_bootstrap_inventory,
)

DSN_ENV = "NEXUS_RESOURCE_EXPORT_DSN"


def run_governed_attempt(
    state: R1AttemptState,
    *,
    dsn: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[str, int, R1EvidenceReport]:
    """The credential-handling core, factored out of ``main`` so tests can
    call it directly with a fixed ``clock`` without touching argv. Returns
    ``(inventory_sha256, resource_count, report)``. Raises on any failure;
    ``main`` translates those into process exit codes."""
    actual_head = revalidate_attempt_state_against_live_repo(state)

    repo_root = Path(state.repo_root)
    release_registry_path = Path(state.sealed_release_registry_path)
    profile_root, profile_manifest_path = canonical_profile_paths(repo_root)
    bootstrap_out = Path(state.bootstrap_out)
    report_out = Path(state.report_out)

    release_registry = load_release_registry_file(
        release_registry_path, EXPECTED_SEALED_RELEASE_REGISTRY_SHA256
    )
    release_artifact_bindings = frozenset(
        (artifact.collection, artifact.content_sha256)
        for manifest in release_registry.manifests
        for artifact in manifest.expectation.artifacts
    )

    generated_at = clock()
    try:
        with psycopg.connect(dsn) as connection:
            inventory = export_resource_registry_bootstrap_inventory(
                connection,
                producer_repository="cyranoaladin/RAG",
                producer_commit=actual_head,
                generated_at=generated_at,
                package_version=metadata.version("nexus-contracts"),
                release_collections=frozenset(release_registry.collections),
                release_artifact_bindings=release_artifact_bindings,
            )
    finally:
        # The DSN is never needed again in this process. Discarding both
        # the local reference and the environment entry makes "gone before
        # the verifier runs" a fact about this process's own state.
        os.environ.pop(DSN_ENV, None)

    publish_atomic_no_clobber(bootstrap_out, canonical_model_bytes(inventory) + b"\n")

    assert DSN_ENV not in os.environ, "DSN must be gone before the verifier ever runs"

    report = verify_r1_evidence(
        bootstrap_path=bootstrap_out,
        release_registry_path=release_registry_path,
        release_registry_sha256=EXPECTED_SEALED_RELEASE_REGISTRY_SHA256,
        profile_root=profile_root,
        profile_manifest_path=profile_manifest_path,
    )

    payload = {"attempt_id": state.attempt_id, **report.to_json()}
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    publish_atomic_no_clobber(report_out, (serialized + "\n").encode("utf-8"))

    return inventory.inventory_sha256, len(inventory.resources), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the governed R1 exporter, then immediately the R1 evidence "
            "verifier, in one process, against one Phase-A-resolved attempt. "
            "The only step in the R1 flow that opens a database connection."
        )
    )
    parser.add_argument("--attempt-state", required=True, type=Path)
    args = parser.parse_args(argv)

    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        raise SystemExit(f"{DSN_ENV} is required and is never accepted on argv")

    try:
        state = load_attempt_state(args.attempt_state)
    except R1OperatorFlowError as exc:
        raise SystemExit(f"attempt state is not sound: {exc}") from exc

    try:
        inventory_sha256, resource_count, report = run_governed_attempt(state, dsn=dsn)
    except R1OperatorFlowError as exc:
        raise SystemExit(str(exc)) from exc
    except AtomicArtifactError as exc:
        raise SystemExit(str(exc)) from exc
    except R1EvidenceVerifierError as exc:
        print(f"R1_EVIDENCE_VERIFIER_ERROR={exc}", file=sys.stderr)
        return 2

    print(f"RESOURCE_REGISTRY_BOOTSTRAP_SHA256={inventory_sha256}")
    print(f"RESOURCE_REGISTRY_BOOTSTRAP_ROWS={resource_count}")
    for key, value in report.gates.items():
        if isinstance(value, list | dict):
            continue
        print(f"{key}={value}")
    print(f"R1_EVIDENCE_BLOCKERS={len(report.blockers)}")
    for blocker in report.blockers:
        print(f"R1_EVIDENCE_BLOCKER={blocker}")
    print(f"R1_EVIDENCE_READY={'YES' if report.ready else 'NO'}")

    return 0 if report.ready else 1


__all__ = ["DSN_ENV", "main", "run_governed_attempt"]
