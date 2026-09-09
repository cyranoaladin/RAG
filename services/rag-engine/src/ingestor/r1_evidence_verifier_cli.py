"""Operator CLI for the R1 evidence verifier.

Never opens a PostgreSQL connection. Never mutates anything. Exits non-zero
on any blocker.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ingestor.atomic_artifact import (
    AtomicArtifactError,
    assert_publishable,
    publish_atomic_no_clobber,
)
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
        "--profile-root",
        required=True,
        type=Path,
        help=(
            "Directory of declarative CollectionProfile YAML files. Never "
            "trusted merely for sitting at this path -- accepted only once "
            "its fingerprint chain is proven against the sealed release."
        ),
    )
    parser.add_argument(
        "--profile-manifest-path",
        required=True,
        type=Path,
        help="Path to the signed ingestion profile manifest (e.g. ingestion_manifest_v2_livraison_319.yml).",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Optional path to write the JSON report to."
    )
    args = parser.parse_args(argv)

    if args.out is not None:
        try:
            assert_publishable(args.out)
        except AtomicArtifactError as exc:
            print(f"R1_EVIDENCE_VERIFIER_ERROR={exc}", file=sys.stderr)
            return 2

    try:
        report = verify_r1_evidence(
            bootstrap_path=args.bootstrap,
            release_registry_path=args.release_registry_path,
            release_registry_sha256=args.release_registry_sha256,
            profile_root=args.profile_root,
            profile_manifest_path=args.profile_manifest_path,
        )
    except R1EvidenceVerifierError as exc:
        print(f"R1_EVIDENCE_VERIFIER_ERROR={exc}", file=sys.stderr)
        return 2

    payload = report.to_json()
    serialized = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out is not None:
        try:
            publish_atomic_no_clobber(args.out, (serialized + "\n").encode("utf-8"))
        except AtomicArtifactError as exc:
            print(f"R1_EVIDENCE_VERIFIER_ERROR={exc}", file=sys.stderr)
            return 2
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
