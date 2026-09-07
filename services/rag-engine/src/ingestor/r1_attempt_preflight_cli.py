"""Phase A of a governed R1 export attempt: every non-secret check, run in
the operator's own (non-secret) parent shell, before any credential is
requested. On success, prints the resolved event state as shell-sourceable
``KEY=value`` lines so the parent shell captures them BEFORE it ever enters
a credential-handling subshell -- Phase B
(``r1_export_and_verify_cli.py``) then receives these exact values back as
explicit arguments, so nothing depends on shell variables surviving a
subshell boundary they were never assigned in.

Never opens a database connection. Never requests or reads a DSN.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ingestor.r1_operator_flow import (
    R1OperatorFlowError,
    resolve_attempt_paths,
    run_preflight,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Non-secret preflight for one governed R1 export attempt: qualified "
            "commit, clean worktree, sealed release-registry digest, evidence "
            "directory outside the repository. Never touches PostgreSQL."
        )
    )
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--qualified-exporter-commit", required=True)
    parser.add_argument("--release-registry-path", required=True, type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument(
        "--attempt-id",
        default=None,
        help="Reuse a specific attempt id instead of generating a new one.",
    )
    args = parser.parse_args(argv)

    try:
        run_preflight(
            repo_root=args.repo_root,
            qualified_commit=args.qualified_exporter_commit,
            release_registry_path=args.release_registry_path,
            evidence_dir=args.evidence_dir,
        )
    except R1OperatorFlowError as exc:
        print(f"R1_OPERATOR_FLOW_ERROR={exc}", file=sys.stderr)
        return 2

    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    attempt = resolve_attempt_paths(
        evidence_dir=args.evidence_dir,
        release_id=args.release_id,
        qualified_commit=args.qualified_exporter_commit,
        attempt_id=args.attempt_id,
    )

    print(f"R1_ATTEMPT_ID={attempt.attempt_id}")
    print(f"SHORT_SHA={attempt.short_sha}")
    print(f"BOOTSTRAP_OUT={attempt.bootstrap_out}")
    print(f"REPORT_OUT={attempt.report_out}")
    print("R1_PREFLIGHT_READY=YES")
    return 0


__all__ = ["main"]
