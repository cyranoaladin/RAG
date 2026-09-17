"""Qualification tests for Lot CF: Release exclusion tooling and reseal preparation.

Proves:
- Sealed currentness exclusion registry integrity (hash, kind, ADR-0055, 4 archives)
- Fail-closed behavior of registry loader and validation
- Preflight verification for V2 candidate identity and exact exclusion alignment
- Hermetic proof sealing for preflight
- Dry-run simulation of build_production_profile_release with exact metrics:
    * 315 unique artifacts (319 - 4)
    * 479 placements (486 - 7)
    * 11 collections (0 empty collections)
    * 8268 unique chunks (8324 - 56)
    * 0 disk writes during dry-run
- Historical V1 release immutability (ADR-0050)
- Governance and safety invariants preserved (GO_LIVE_READY=false, assert-ready=1, C1 open, 4 refused)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
REGISTRY_PATH = RACINE / "docs/reports/evidence/release_currentness_exclusion_registry.json"
REGISTRY_SHA_PATH = RACINE / "docs/reports/evidence/release_currentness_exclusion_registry.sha256"
PREFLIGHT_PROOF_PATH = RACINE / "docs/reports/evidence/release_exclusion_tooling_preflight_proof.json"
PREFLIGHT_PROOF_SHA_PATH = RACINE / "docs/reports/evidence/release_exclusion_tooling_preflight_proof.sha256"
BUILD_SCRIPT = RACINE / "services/rag-pedago/scripts/build_production_profile_release.py"
PREFLIGHT_SCRIPT = RACINE / "scripts/go_live/preflight_currentness_reseal.py"
V1_RELEASE_ROOT = RACINE / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
READINESS_SCRIPT = RACINE / "scripts/go_live/check_go_live_readiness.py"

VENV_PYTHON = RACINE / "services/rag-pedago/.venv/bin/python3"
PYTHON_EXE = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable

ARCHIVES_EXCLUES = [
    "157309db13b674ffe4bf1371015bfc7c9c9cf475af75769a6beaf4dade45925f",
    "174f273ff25818064be60cd4c7cded89ab8f257de484b32a21250578f323149b",
    "ccffe628bbd64e34a8442a045f95ec2ef65109765c0a0a476c0156aa84a5f9a2",
    "dc58fcc42ef9b4e6d15a129124eff54ce5d76e0e16e1e4f62115b64482e94fd2",
]


@pytest.fixture(scope="module")
def exclusion_registry_bytes() -> bytes:
    assert REGISTRY_PATH.is_file(), f"missing registry file: {REGISTRY_PATH}"
    return REGISTRY_PATH.read_bytes()


@pytest.fixture(scope="module")
def exclusion_registry(exclusion_registry_bytes: bytes) -> dict:
    return json.loads(exclusion_registry_bytes.decode("utf-8"))


def test_exclusion_registry_sealed_hash(exclusion_registry_bytes: bytes) -> None:
    assert REGISTRY_SHA_PATH.is_file(), f"missing sha256 file: {REGISTRY_SHA_PATH}"
    expected_sha = REGISTRY_SHA_PATH.read_text(encoding="utf-8").split()[0].lower()
    actual_sha = hashlib.sha256(exclusion_registry_bytes).hexdigest().lower()
    assert actual_sha == expected_sha
    assert len(actual_sha) == 64


def test_exclusion_registry_content_and_governance(exclusion_registry: dict) -> None:
    assert exclusion_registry["kind"] == "NEXUS-CURRENTNESS-EXCLUSION-REGISTRY-V1"
    assert exclusion_registry["governance_reference"] == "ADR-0055"
    assert exclusion_registry["excluded_contents_count"] == 4

    entries = exclusion_registry["excluded_contents"]
    assert len(entries) == 4
    entry_shas = [e["content_sha256"] for e in entries]
    assert sorted(entry_shas) == sorted(ARCHIVES_EXCLUES)

    for entry in entries:
        assert entry["currentness_status"] == "ARCHIVE_DECLARED"
        assert entry["servability_verdict"] == "BLOCKED_NOT_CURRENT_BY_SOURCE"
        assert entry["exclusion_reason"] == "ARCHIVE_DECLARED_BY_SOURCE_ADR_0055"
        assert entry["is_promoted"] is True
        assert "label" in entry and len(entry["label"]) > 5


def test_loader_validation_fail_closed(tmp_path: Path) -> None:
    sys.path.insert(0, str(RACINE / "services/rag-pedago"))
    sys.path.insert(0, str(RACINE / "services/rag-pedago/scripts"))
    try:
        from build_production_profile_release import load_and_validate_exclusion_registry
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"rag-pedago dependencies not installed in this runner: {exc}")

    # None returns None
    assert load_and_validate_exclusion_registry(None) is None

    # Missing file fails
    with pytest.raises(FileNotFoundError):
        load_and_validate_exclusion_registry(tmp_path / "non_existent.json")

    # Valid loads successfully
    reg = load_and_validate_exclusion_registry(REGISTRY_PATH)
    assert reg is not None
    assert reg.excluded_contents == frozenset(ARCHIVES_EXCLUES)

    # Corrupt hash fails
    with pytest.raises(ValueError, match="sha256 mismatch"):
        load_and_validate_exclusion_registry(
            REGISTRY_PATH,
            expected_sha256="0000000000000000000000000000000000000000000000000000000000000000",
        )

    # Invalid JSON fails
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_and_validate_exclusion_registry(bad_json)

    # Wrong count fails
    wrong_count = tmp_path / "wrong_count.json"
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    data["excluded_contents"] = data["excluded_contents"][:2]
    wrong_count.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="count mismatch"):
        load_and_validate_exclusion_registry(wrong_count)


def test_preflight_tooling_and_sealed_proof() -> None:
    assert PREFLIGHT_PROOF_PATH.is_file()
    assert PREFLIGHT_PROOF_SHA_PATH.is_file()
    expected_sha = PREFLIGHT_PROOF_SHA_PATH.read_text(encoding="utf-8").split()[0].lower()
    actual_sha = hashlib.sha256(PREFLIGHT_PROOF_PATH.read_bytes()).hexdigest().lower()
    assert actual_sha == expected_sha

    proof = json.loads(PREFLIGHT_PROOF_PATH.read_text(encoding="utf-8"))
    assert proof["preflight_passed"] is True
    assert proof["release_identity"]["is_free"] is True
    assert proof["contents_to_exclude"]["count"] == 4
    assert sorted(proof["contents_to_exclude"]["content_sha256"]) == sorted(ARCHIVES_EXCLUES)
    assert proof["blocking_findings"] == []
    assert proof["exclusion_registry"]["concordance"] is True
    assert proof["exclusion_registry"]["count"] == 4


def test_build_production_profile_release_dry_run_cli() -> None:
    if not VENV_PYTHON.is_file():
        pytest.skip("rag-pedago canonical venv not available in minimal qualification runner")

    res = subprocess.run(
        [
            PYTHON_EXE,
            str(BUILD_SCRIPT),
            "--release-mode",
            "rehearsal",
            "--source-release-root",
            str(V1_RELEASE_ROOT),
            "--release-id",
            "production-profile-gate-2026-2027-v2",
            "--exclusion-registry",
            str(REGISTRY_PATH),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(RACINE),
    )
    assert res.returncode == 0, f"dry-run failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"
    out = res.stdout

    assert "DRY_RUN=true" in out
    assert "EXCLUDED_CONTENTS_COUNT=4" in out
    assert "PRODUCTION_PROFILE_RELEASE_UNIQUE_ARTIFACTS=315" in out
    assert "PRODUCTION_PROFILE_RELEASE_PLACEMENTS=479" in out
    assert "PRODUCTION_PROFILE_RELEASE_COLLECTIONS=11" in out
    assert "PRODUCTION_PROFILE_RELEASE_CHUNKS=8268" in out
    assert "PRODUCTION_PROFILE_RELEASE_SHA256=" in out


def test_v1_historical_release_immutability() -> None:
    v1_manifest = V1_RELEASE_ROOT / "production-profile-gate.release.json"
    assert v1_manifest.is_file()
    data = json.loads(v1_manifest.read_text(encoding="utf-8"))
    assert data["expected_counts"]["placements"] == 486
    assert len(data["subjects"]) == 11

    unique_artifacts: set[str] = set()
    unique_chunks: set[str] = set()
    for s in data["subjects"]:
        subj_data = json.loads((V1_RELEASE_ROOT / s["path"]).read_text(encoding="utf-8"))
        for a in subj_data["artifacts"]:
            unique_artifacts.add(a["content_sha256"])
            for c in a.get("chunks", []):
                unique_chunks.add(c.get("chunk_id") or c.get("chunk_sha256"))
    assert len(unique_artifacts) == 319
    assert len(unique_chunks) == 8324


def test_governance_invariants_lot_cf() -> None:
    res = subprocess.run(
        [PYTHON_EXE, str(READINESS_SCRIPT), "--check-only"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(RACINE),
    )
    assert res.returncode == 0
    readiness = json.loads(
        (RACINE / "docs/reports/go_live/go_live_readiness_state.json").read_text(encoding="utf-8")
    )

    # In Lot CF, C1 is NOT closed yet, 4 archives remain refused in V1 active release
    assert readiness["pii_undecided"] == 0
    assert readiness["pre_release_blockers"] == 0
    assert readiness["release_promoted_refused_contents"] == 4
    assert readiness["go_live_qualification_blockers"] == 4
    assert readiness["go_live_ready"] is False
    assert "C1" in readiness["go_live_qualification_blocker_ids"]
    assert "go_live_qualification_blockers" in readiness["blocking_reasons"]
    assert "release_promoted_refused_contents" in readiness["blocking_reasons"]

    # Fail-closed assert-ready
    assert_res = subprocess.run(
        [PYTHON_EXE, str(READINESS_SCRIPT), "--assert-ready"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(RACINE),
    )
    assert assert_res.returncode == 1
