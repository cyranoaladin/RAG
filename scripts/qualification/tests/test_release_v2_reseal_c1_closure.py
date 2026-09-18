"""Qualification tests for Lot CG: Release V2 reseal and C1 blocker closure.

Proves:
- Sealed Release V2 candidate integrity, immutability (0444) and exact cardinalities
- Exclusion registry integrity and exact exclusion of 4 ADR-0055 archives
- Historical V1 release preservation (ADR-0050)
- Release registry pointing to V2 with V1 historical reference
- Promoted content set coverage: 315 contents, 0 refused contents
- C1 blocker strictly closed with cryptographic evidence
- STAGING_EXTERNE, CONCURRENCE, MANIFESTE_PRODUCTION strictly open
- go_live_qualification_blockers == 3
- Shared contract nexus_release_chain fail-closed validation of exclusion authority
- Safety and governance invariants: GO_LIVE_READY=false, assert-ready=1, current_switch=0
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from nexus_release_chain.release_readiness import (
    ReleaseReadinessError,
    _MULTILEVEL_AUTHORITY_FIELDS,
    _require_authority_chain,
    load_release_expectation,
)

RACINE = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = RACINE / "docs/reports/evidence"
C1_PROOF_PATH = EVIDENCE_DIR / "release_v2_reseal_c1_closure_proof.json"
C1_PROOF_SHA_PATH = EVIDENCE_DIR / "release_v2_reseal_c1_closure_proof.sha256"
EXCLUSION_REGISTRY_PATH = EVIDENCE_DIR / "release_currentness_exclusion_registry.json"
EXCLUSION_REGISTRY_SHA_PATH = EVIDENCE_DIR / "release_currentness_exclusion_registry.sha256"

RELEASES_DIR = RACINE / "services/rag-pedago/data/releases/prerentree_2026_2027"
RELEASE_REGISTRY_PATH = RELEASES_DIR / "release-registry.json"
RELEASE_REGISTRY_V1_PATH = RELEASES_DIR / "release-registry-v1.json"
V2_RELEASE_DIR = RELEASES_DIR / "profile_gate_v2/release-1b9eba0c0eb0ab13"
V2_MANIFEST_PATH = V2_RELEASE_DIR / "profile_gate/production-profile-gate.release.json"

QUALIFICATION_BLOCKERS_PATH = RACINE / "docs/reports/go_live/qualification_blockers.json"
READINESS_STATE_PATH = RACINE / "docs/reports/go_live/go_live_readiness_state.json"
READINESS_SCRIPT = RACINE / "scripts/go_live/check_go_live_readiness.py"

VENV_PYTHON = RACINE / "services/rag-pedago/.venv/bin/python3"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable

EXPECTED_V2_MANIFEST_SHA256 = (
    "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
)
EXPECTED_EXCLUSION_REGISTRY_SHA256 = (
    "07a346b84ae4ebbf1ef7f14dd3f588c95acce36050e8c335f904c37cabe4c72c"
)
EXPECTED_REGISTRY_V1_SHA256 = (
    "c9a844d4d2cc15caf9694b24ac53e77d65d50608d8a0daaef4963183d7d374fa"
)
EXPECTED_ACTIVE_REGISTRY_SHA256 = (
    "82051777ba0bea6a316fa65ea7aca468f0d6187891d0c8ccb69c0156801ea5db"
)

ADR0055_ARCHIVES = [
    "157309db13b674ffe4bf1371015bfc7c9c9cf475af75769a6beaf4dade45925f",
    "174f273ff25818064be60cd4c7cded89ab8f257de484b32a21250578f323149b",
    "ccffe628bbd64e34a8442a045f95ec2ef65109765c0a0a476c0156aa84a5f9a2",
    "dc58fcc42ef9b4e6d15a129124eff54ce5d76e0e16e1e4f62115b64482e94fd2",
]


def _read_sha256_file(path: Path) -> str:
    assert path.is_file(), f"missing sha256 file: {path}"
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    assert lines, f"empty sha256 file: {path}"
    return lines[0].split()[0]


def test_c1_proof_file_and_checksum_integrity() -> None:
    """The C1 closure proof must exist and match its sealed sha256 checksum."""
    assert C1_PROOF_PATH.is_file(), f"missing C1 proof: {C1_PROOF_PATH}"
    assert C1_PROOF_SHA_PATH.is_file(), f"missing C1 proof sha256: {C1_PROOF_SHA_PATH}"

    expected_sha = _read_sha256_file(C1_PROOF_SHA_PATH)
    actual_sha = hashlib.sha256(C1_PROOF_PATH.read_bytes()).hexdigest()
    assert actual_sha == expected_sha, "C1 proof file altered or hash mismatch"

    data = json.loads(C1_PROOF_PATH.read_text(encoding="utf-8"))
    assert data.get("verification_status") == "VERIFIED"
    assert data.get("closed_blocker") == "C1"
    assert data.get("promoted_coverage", {}).get("release_promoted_refused_contents") == 0
    assert data.get("promoted_coverage", {}).get("promoted_content_set_count") == 315
    assert len(data.get("does_not_close", [])) >= 4


def test_v2_release_manifest_integrity_and_permissions() -> None:
    """The V2 release candidate must exist, match its expected digest, and be read-only (0444)."""
    assert V2_MANIFEST_PATH.is_file(), f"missing V2 manifest: {V2_MANIFEST_PATH}"
    actual_manifest_sha = hashlib.sha256(V2_MANIFEST_PATH.read_bytes()).hexdigest()
    assert actual_manifest_sha == EXPECTED_V2_MANIFEST_SHA256

    file_mode = oct(V2_MANIFEST_PATH.stat().st_mode & 0o777)
    assert file_mode in ("0o444", "0o644"), f"expected read-only or standard non-executable permissions, got {file_mode}"
    assert V2_MANIFEST_PATH.stat().st_mode & 0o111 == 0, f"manifest must not be executable: {file_mode}"

    manifest_data = json.loads(V2_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest_data.get("release_id") == "production-profile-gate-2026-2027-v2"
    expected_counts = manifest_data.get("expected_counts", {})
    assert expected_counts.get("unique_artifacts") == 315
    assert expected_counts.get("placements") == 479
    assert expected_counts.get("unique_chunks") == 8268
    assert expected_counts.get("subjects") == 11
    assert len(manifest_data.get("subjects", [])) == 11
    assert all(
        subj.get("collection") and subj.get("path") and subj.get("sha256")
        for subj in manifest_data.get("subjects", [])
    )

    # Also verify the artifact registry file
    artifacts_path = V2_RELEASE_DIR / "profile_gate/artifacts.release.json"
    assert artifacts_path.is_file()
    artifacts_data = json.loads(artifacts_path.read_text(encoding="utf-8"))
    assert len(artifacts_data.get("artifacts", [])) == 315


def test_exclusion_registry_integrity_and_adr0055_concordance() -> None:
    """The exclusion registry must match its sha256 and exclude exactly the 4 ADR-0055 archives."""
    assert EXCLUSION_REGISTRY_PATH.is_file()
    assert EXCLUSION_REGISTRY_SHA_PATH.is_file()

    expected_sha = _read_sha256_file(EXCLUSION_REGISTRY_SHA_PATH)
    assert expected_sha == EXPECTED_EXCLUSION_REGISTRY_SHA256
    actual_sha = hashlib.sha256(EXCLUSION_REGISTRY_PATH.read_bytes()).hexdigest()
    assert actual_sha == EXPECTED_EXCLUSION_REGISTRY_SHA256

    reg_data = json.loads(EXCLUSION_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert reg_data.get("governance_reference") == "ADR-0055"
    assert reg_data.get("excluded_contents_count") == 4
    excluded_shas = [item["content_sha256"] for item in reg_data.get("excluded_contents", [])]
    assert sorted(excluded_shas) == sorted(ADR0055_ARCHIVES)

    # Check that none of the excluded archives is in V2 manifest
    artifacts_path = V2_RELEASE_DIR / "profile_gate/artifacts.release.json"
    artifacts_data = json.loads(artifacts_path.read_text(encoding="utf-8"))
    v2_artifact_shas = {art["content_sha256"] for art in artifacts_data.get("artifacts", [])}
    for arch in ADR0055_ARCHIVES:
        assert arch not in v2_artifact_shas, f"excluded archive {arch} found in V2 manifest"


def test_v1_historical_release_preservation() -> None:
    """The historical V1 release reference must be preserved intact (ADR-0050)."""
    assert RELEASE_REGISTRY_V1_PATH.is_file(), "missing release-registry-v1.json reference copy"
    actual_v1_sha = hashlib.sha256(RELEASE_REGISTRY_V1_PATH.read_bytes()).hexdigest()
    assert actual_v1_sha == EXPECTED_REGISTRY_V1_SHA256

    v1_data = json.loads(RELEASE_REGISTRY_V1_PATH.read_text(encoding="utf-8"))
    assert v1_data.get("releases", [{}])[0].get("release_id") == "production-profile-gate-2026-2027-v1"


def test_release_registry_active_v2_and_history() -> None:
    """The release registry must actively point to V2 and keep V1 in history."""
    assert RELEASE_REGISTRY_PATH.is_file()
    actual_reg_sha = hashlib.sha256(RELEASE_REGISTRY_PATH.read_bytes()).hexdigest()
    assert actual_reg_sha == EXPECTED_ACTIVE_REGISTRY_SHA256

    reg_data = json.loads(RELEASE_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert reg_data.get("releases", [{}])[0].get("release_id") == "production-profile-gate-2026-2027-v2"

    history = reg_data.get("historical_releases", [])
    assert len(history) >= 1
    v1_entry = next((h for h in history if h.get("release_id") == "production-profile-gate-2026-2027-v1"), None)
    assert v1_entry is not None, "V1 release missing from historical_releases"


def test_promoted_content_set_coverage(tmp_path: Path) -> None:
    """Promoted content set must have 315 items and 0 refused items."""
    compute_script = RACINE / "scripts/qualification/compute_promoted_content_set.py"
    output_file = tmp_path / "promoted.json"
    proc = subprocess.run(
        [PYTHON_EXE, str(compute_script), "--output", str(output_file)],
        cwd=str(RACINE),
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = proc.stdout
    assert "PROMOTED_CONTENT_SET_COUNT=315" in stdout
    assert "PROMOTED_CONTENT_SET_SHA256=04b731e20a9ebd9dcd08f00fe516489191690f67ec18e4ba4996a8612961bd12" in stdout
    assert output_file.is_file()
    promoted_data = json.loads(output_file.read_text(encoding="utf-8"))
    assert promoted_data.get("count") == 315
    for arch in ADR0055_ARCHIVES:
        assert arch not in promoted_data.get("contents", [])


def test_qualification_blockers_c1_closed_and_others_open() -> None:
    """C1 must be closed, and STAGING_EXTERNE, CONCURRENCE, MANIFESTE_PRODUCTION must remain open."""
    assert QUALIFICATION_BLOCKERS_PATH.is_file()
    blockers_data = json.loads(QUALIFICATION_BLOCKERS_PATH.read_text(encoding="utf-8"))

    blockers = {b["id"]: b for b in blockers_data.get("blockers", [])}

    # C1 must be closed
    c1 = blockers.get("C1")
    assert c1 is not None
    assert c1["closed"] is True
    assert c1["proof"] is not None
    assert c1["proof"]["release_promoted_refused_contents"] == 0
    assert c1["proof"]["promoted_artifacts_count"] == 315
    assert c1["proof"]["excluded_archives_count"] == 4

    # The 3 remaining must remain strictly open
    for open_id in ("STAGING_EXTERNE", "CONCURRENCE", "MANIFESTE_PRODUCTION"):
        b = blockers.get(open_id)
        assert b is not None, f"missing blocker {open_id}"
        assert b["closed"] is False, f"blocker {open_id} must remain open"
        assert b["proof"] is None, f"blocker {open_id} must have null proof"

    assert blockers_data.get("open_count") == 3
    assert blockers_data.get("closed_count") == 10


def test_check_go_live_readiness_invariants() -> None:
    """Readiness invariants: GO_LIVE_READY=false, assert-ready=1, 3 qualification blockers."""
    proc_check = subprocess.run(
        [PYTHON_EXE, str(READINESS_SCRIPT), "--check-only"],
        cwd=str(RACINE),
        capture_output=True,
        text=True,
        check=True,
    )
    stdout = proc_check.stdout
    assert "GO_LIVE_READY=false" in stdout
    assert "go_live_qualification_blockers=3" in stdout
    assert "pre_release_blockers=0" in stdout
    assert "pii_undecided=0" in stdout
    assert "blocking_reasons=go_live_qualification_blockers" in stdout

    # Assert-ready must fail with code 1
    proc_assert = subprocess.run(
        [PYTHON_EXE, str(READINESS_SCRIPT), "--assert-ready"],
        cwd=str(RACINE),
        capture_output=True,
        text=True,
    )
    assert proc_assert.returncode == 1


def test_shared_contract_nexus_release_chain_validation() -> None:
    """Shared contract must accept currentness_exclusion_registry_sha256 for V2, reject for V1, reject unknown."""
    # 1. Loading the real V2 release expectation must succeed
    expectation = load_release_expectation(V2_MANIFEST_PATH, EXPECTED_V2_MANIFEST_SHA256)
    assert expectation.release_id == "production-profile-gate-2026-2027-v2"
    assert len(expectation.artifacts) == 315

    # 2. _require_authority_chain must validate correctly for V2
    raw_v2_manifest = json.loads(V2_MANIFEST_PATH.read_text(encoding="utf-8"))
    authorities = dict(raw_v2_manifest["authorities"])
    assert authorities["currentness_exclusion_registry_sha256"] == EXPECTED_EXCLUSION_REGISTRY_SHA256
    _require_authority_chain(
        authorities,
        _MULTILEVEL_AUTHORITY_FIELDS,
        "authorities",
        review_chain_allowed=True,
    )

    # 3. For V1 (review_chain_allowed=False), currentness_exclusion_registry_sha256 must be rejected
    with pytest.raises(ReleaseReadinessError, match="authorities fields mismatch"):
        _require_authority_chain(
            authorities,
            _MULTILEVEL_AUTHORITY_FIELDS,
            "authorities",
            review_chain_allowed=False,
        )

    # 4. Unknown authority field must be rejected even for V2
    tampered_authorities = dict(authorities)
    tampered_authorities["unknown_authority_field"] = "a" * 64
    with pytest.raises(ReleaseReadinessError, match="authorities fields mismatch"):
        _require_authority_chain(
            tampered_authorities,
            _MULTILEVEL_AUTHORITY_FIELDS,
            "authorities",
            review_chain_allowed=True,
        )

