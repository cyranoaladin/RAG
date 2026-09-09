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

R1F closes two further gaps: (1) the evidence directory is now only ever
created AFTER every preflight gate, including evidence-directory
exclusion, has already passed -- a forbidden request never leaves even an
empty directory behind; (2) ``--print-state-path-only`` makes this
program's stdout, on success, contain nothing but the attempt-state path,
so the runbook can capture it with plain command substitution and check
the exit code, without ``eval``, ``grep``, or ``cut`` ever standing between
a failed Phase A and a credential prompt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ingestor.r1_operator_flow import (
    R1OperatorFlowError,
    build_attempt_state,
    canonical_attempt_state_path,
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
    parser.add_argument(
        "--print-state-path-only",
        action="store_true",
        help=(
            "On success, print ONLY the attempt-state file's path to stdout, with "
            "no other line -- so a caller can capture it with plain command "
            "substitution (VAR=$(...)) and check the exit code, never eval, grep, "
            "or cut. On failure, nothing is printed to stdout and the exit code is "
            "non-zero, exactly as without this flag."
        ),
    )
    args = parser.parse_args(argv)

    try:
        # Every preflight gate -- including evidence-directory exclusion from
        # every repository worktree -- must pass BEFORE this process creates
        # anything on disk. A forbidden evidence directory must never even be
        # `mkdir`'d, empty or otherwise: filesystem mutation is a consequence
        # of authorization, never a side effect of merely attempting it.
        state = build_attempt_state(
            repo_root=args.repo_root,
            qualified_exporter_commit=args.qualified_exporter_commit,
            evidence_dir=args.evidence_dir,
            attempt_id=args.test_only_attempt_id,
        )
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        state_path = canonical_attempt_state_path(args.evidence_dir, state.attempt_id)
        write_attempt_state(state_path, state)
    except R1OperatorFlowError as exc:
        print(f"R1_OPERATOR_FLOW_ERROR={exc}", file=sys.stderr)
        return 2

    if args.print_state_path_only:
        print(state_path)
        return 0

    print(f"R1_ATTEMPT_STATE_PATH={state_path}")
    print(f"R1_ATTEMPT_ID={state.attempt_id}")
    print(f"SEALED_RELEASE_ID={state.sealed_release_id}")
    print(f"BOOTSTRAP_OUT={state.bootstrap_out}")
    print(f"REPORT_OUT={state.report_out}")
    print("R1_PREFLIGHT_READY=YES")
    return 0


__all__ = ["main"]
