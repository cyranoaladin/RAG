"""Phase A of a governed R1 export attempt: every non-secret check, run in
the operator's own (non-secret) parent shell, before any credential is
requested. On success, publishes an immutable, atomically-written,
no-clobber ``0600`` attempt-state JSON file OUTSIDE every repository
worktree and prints only its path.

R1E replaces R1D's raw ``KEY=value`` stdout (meant to be ``eval``'d by the
operator's shell -- unsafe for any value containing shell metacharacters)
with this single file. Phase B (``r1_export_and_verify_cli.py``) loads it
back and independently re-validates and re-checks every fact it records
against the live repository -- the file is a hand-off artifact, never a
trusted-on-its-own credential of correctness.

Never opens a database connection. Never requests or reads a DSN. Never
accepts ``--release-id`` or ``--attempt-id`` as ordinary operator input for
a real governed attempt: the release id is derived from the sealed
registry itself, and the attempt id is generated fresh here -- a reused
attempt id is not a new governed attempt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ingestor.r1_operator_flow import (
    R1OperatorFlowError,
    build_attempt_state,
    write_attempt_state,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Non-secret preflight for one governed R1 export attempt: qualified "
            "commit, clean worktree, runtime-provenance attestation, sealed "
            "release-registry digest, evidence directory outside every repository "
            "worktree. Publishes an immutable attempt-state file for Phase B. "
            "Never touches PostgreSQL."
        )
    )
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--qualified-exporter-commit", required=True)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument(
        "--test-only-attempt-id",
        default=None,
        help=(
            "TEST-ONLY: reuse a specific attempt id instead of generating a fresh "
            "one. Never use this for a real governed attempt -- a reused attempt "
            "id is not a new governed attempt."
        ),
    )
    args = parser.parse_args(argv)

    args.evidence_dir.mkdir(parents=True, exist_ok=True)

    try:
        state = build_attempt_state(
            repo_root=args.repo_root,
            qualified_exporter_commit=args.qualified_exporter_commit,
            evidence_dir=args.evidence_dir,
            attempt_id=args.test_only_attempt_id,
        )
        state_path = args.evidence_dir.resolve() / f"r1-attempt-state-{state.attempt_id}.json"
        write_attempt_state(state_path, state)
    except R1OperatorFlowError as exc:
        print(f"R1_OPERATOR_FLOW_ERROR={exc}", file=sys.stderr)
        return 2

    print(f"R1_ATTEMPT_STATE_PATH={state_path}")
    print(f"R1_ATTEMPT_ID={state.attempt_id}")
    print(f"SEALED_RELEASE_ID={state.sealed_release_id}")
    print(f"BOOTSTRAP_OUT={state.bootstrap_out}")
    print(f"REPORT_OUT={state.report_out}")
    print("R1_PREFLIGHT_READY=YES")
    return 0


__all__ = ["main"]
