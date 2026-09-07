"""Operator CLI for the R1 evidence verifier.

Never opens a PostgreSQL connection. Never mutates anything. Exits non-zero
on any blocker.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ingestor.r1_evidence_verifier import R1EvidenceVerifierError, verify_r1_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prove an already-exported ResourceRegistryBootstrap represents "
            "exactly the sealed production release it claims to. Read-only; "
            "never connects to PostgreSQL."
        )
    )
    parser.add_argument("--bootstrap", required=True, type=Path)
    parser.add_argument("--release-registry-path", required=True, type=Path)
    parser.add_argument("--release-registry-sha256", required=True)
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional path to write the JSON report to."
    )
    args = parser.parse_args(argv)

    try:
        report = verify_r1_evidence(
            bootstrap_path=args.bootstrap,
            release_registry_path=args.release_registry_path,
            release_registry_sha256=args.release_registry_sha256,
        )
    except R1EvidenceVerifierError as exc:
        print(f"R1_EVIDENCE_VERIFIER_ERROR={exc}", file=sys.stderr)
        return 2

    payload = report.to_json()
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out is not None:
        args.out.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)

    for key, value in report.gates.items():
        if isinstance(value, list | dict):
            continue
        print(f"{key}={value}")
    print(f"R1_EVIDENCE_BLOCKERS={len(report.blockers)}")
    for blocker in report.blockers:
        print(f"R1_EVIDENCE_BLOCKER={blocker}")
    print(f"R1_EVIDENCE_READY={'YES' if report.ready else 'NO'}")

    return 0 if report.ready else 1


__all__ = ["main"]
