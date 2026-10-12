#!/usr/bin/env python3
"""Émettre l'autorité temporelle A2 depuis 253 sources recontrôlées en direct.

Lecture seule des preuves privées et de A1 ; aucune écriture DB ou déploiement.
La sortie n'autorise ni publication ni ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from attest_student_derivative_source_currentness import attest_repository
from build_public_successor_content_anchor import inspect_content_preparation
from nexus_release_chain.public_successor_activation import verify_content_anchor
from nexus_release_chain.public_successor_temporal import (
    POLICY_SHA256,
    PublicSuccessorTemporalError,
    build_temporal_successor,
    canonical_bytes,
)

ROOT = Path(__file__).resolve().parents[2]


def write_output_pair(
    authority_path: Path, authority_raw: bytes,
    report_path: Path, report_raw: bytes,
) -> None:
    """Préparer les deux sorties puis rendre l'autorité visible en dernier."""
    if authority_path.absolute() == report_path.absolute():
        raise PublicSuccessorTemporalError("A2 authority/report output paths collide")
    outputs = ((report_path, report_raw), (authority_path, authority_raw))
    for path, raw in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        if (path.parent.resolve() != path.parent.absolute()
                or path.is_symlink()
                or (path.exists() and path.read_bytes() != raw)):
            raise PublicSuccessorTemporalError(f"A2 output path unsafe or divergent: {path.name}")
    if authority_path.exists() != report_path.exists():
        raise PublicSuccessorTemporalError("A2 output pair incomplete")
    if authority_path.exists():
        return
    staged: list[tuple[Path, Path]] = []
    try:
        for path, raw in outputs:
            descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            temporary = Path(name)
            staged.append((temporary, path))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        for temporary, path in staged:
            os.replace(temporary, path)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def produce(
    *, repository_root: Path, anchor_path: Path, release_root: Path,
    issue_attestation_path: Path, private_root: Path,
    source_checkpoint_root: Path, fresh_root: Path, private_cas_root: Path,
    issued_at_utc: datetime,
) -> tuple[dict, dict]:
    """Rejouer les octets privés avant de sceller la seule autorité temporelle."""
    anchor_raw = anchor_path.read_bytes()
    policy_path = (repository_root /
                   "governance/student_public_rights/public_successor_temporal_policy_a2_v1.yml")
    if hashlib.sha256(policy_path.read_bytes()).hexdigest() != POLICY_SHA256:
        raise PublicSuccessorTemporalError("A2 policy bytes differ from sealed verifier")
    anchor_sha = hashlib.sha256(anchor_raw).hexdigest()
    content = verify_content_anchor(anchor_path, anchor_sha, release_root)
    replay = inspect_content_preparation(
        release_root / "profile_gate/production-profile-gate.release.json",
        content.content_manifest_sha256,
        private_cas_root=private_cas_root, repository_root=repository_root,
    )
    if not replay["inclusion_population_verified"] or not replay["private_cas_replay_verified"]:
        raise PublicSuccessorTemporalError("A1 population or private CAS replay failed")
    issue_raw = issue_attestation_path.read_bytes()
    source_packet_raw = (repository_root /
        "docs/reports/go_live/student_public_rights_individual_review_packet_20261009.json"
    ).read_bytes()
    approval_raw = (repository_root /
        "docs/reports/go_live/student_rights_evidence/pr300_final_authority_approval.json"
    ).read_bytes()
    attestation = json.loads(issue_raw)
    replayed = attest_repository(
        repository_root, private_root, source_checkpoint_root, fresh_root,
        attested_at_utc=attestation["attested_at_utc"],
    )
    if canonical_bytes(replayed) != issue_raw:
        raise PublicSuccessorTemporalError("fresh source attestation differs from private replay")
    authority = build_temporal_successor(
        content, release_root, issue_raw, source_packet_raw=source_packet_raw,
        approval_raw=approval_raw, issued_at_utc=issued_at_utc,
    )
    authority_raw = canonical_bytes(authority)
    expiry = datetime.fromisoformat(authority["valid_until_utc"])
    report = {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_A2_CONTINUITY_REPORT_V1",
        "status": "PASS_NOT_ACTIVATION_AUTHORITY",
        "observed_at_utc": issued_at_utc.isoformat().replace("+00:00", "Z"),
        "content_anchor_sha256": anchor_sha,
        "policy_sha256": POLICY_SHA256,
        "content_manifest_sha256": content.content_manifest_sha256,
        "release_id": content.release_id,
        "private_cas_manifest_sha256": authority["private_cas_manifest_sha256"],
        "initial_source_attestation_sha256": authority["initial_source_attestation_sha256"],
        "initial_source_index_file_sha256": authority["initial_source_index_file_sha256"],
        "source_inventory_packet_sha256": authority["source_inventory_packet_sha256"],
        "excluded_source_set_sha256": authority["excluded_source_set_sha256"],
        "excluded_source_count": authority["excluded_source_count"],
        "content_set_unchanged": True,
        "manifest_unchanged": True,
        "cas_index_unchanged": True,
        "rights_registry_unchanged": True,
        "pii_registry_unchanged": True,
        "exclusion_set_unchanged": True,
        "cftr_still_excluded": True,
        "only_temporal_authorities_changed": True,
        "a2_authority_sha256": hashlib.sha256(authority_raw).hexdigest(),
        "source_pass_count": attestation["decision_count"],
        "source_revocation_replay": "PASS_253_OF_253_AT_ISSUE",
        "expected_counts": content.expected_counts,
        "valid_until_utc": expiry.isoformat().replace("+00:00", "Z"),
        "c_time_source_revalidation_required": True,
        "a2_consumed_by_c": False,
        "publication_authorized": False,
    }
    return authority, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--issue-attestation", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--source-checkpoint-root", type=Path, required=True)
    parser.add_argument("--fresh-root", type=Path, required=True)
    parser.add_argument("--private-cas-root", type=Path, required=True)
    parser.add_argument("--authority-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(UTC)
    try:
        authority, report = produce(
            repository_root=args.repository_root, anchor_path=args.anchor,
            release_root=args.release_root, issue_attestation_path=args.issue_attestation,
            private_root=args.private_root,
            source_checkpoint_root=args.source_checkpoint_root,
            fresh_root=args.fresh_root, private_cas_root=args.private_cas_root,
            issued_at_utc=now,
        )
        write_output_pair(
            args.authority_output, canonical_bytes(authority),
            args.report_output, canonical_bytes(report),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(error)}, sort_keys=True))
        return 1
    print(json.dumps({"status": "PASS_NOT_ACTIVATION_AUTHORITY",
                      "a2_authority_sha256": report["a2_authority_sha256"],
                      "valid_until_utc": report["valid_until_utc"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
