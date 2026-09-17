"""Qualification tests for Lot CE: Import of approved PII and currentness decisions.

Proves:
- 149 sealed PII decisions (23 approved, 126 precautionary exclusions)
- 0 pii_undecided in servability matrix and readiness
- pre_release_blockers closed (1 -> 0)
- 26 -> 4 promoted refused contents (all 4 are BLOCKED_NOT_CURRENT_BY_SOURCE)
- 157309db13b6 transition audit: PII_CLEARED but BLOCKED_NOT_CURRENT_BY_SOURCE (Option 1)
- Explicit provenance cabling in servability matrix inputs
- Strict preservation of security and production invariants (no writes, switch=0, no raw PII)
- --assert-ready returns 1 (fail-closed)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from nexus_contracts import parse_pii_review_decision_set

RACINE = Path(__file__).resolve().parents[3]

SEALED_DECISIONS = RACINE / "governance/pii-review-decisions/pii-review-2026-09-17-final.json"
DECISION_SET_SHA256 = "0805c9babfc16def873bbf0b3593ae6f7d0ce6fcb9002a68eb456d80b8906352"
MATRICE_PATH = RACINE / "docs/reports/handoff/servability_matrix_v1.json"
READINESS_PATH = RACINE / "docs/reports/go_live/go_live_readiness_state.json"
PROOF_PATH = RACINE / "docs/reports/evidence/pii_currentness_approved_import_proof.json"
PROOF_SHA_PATH = RACINE / "docs/reports/evidence/pii_currentness_approved_import_proof.sha256"

ARCHIVES_BLOQUEES = [
    "157309db13b674ffe4bf1371015bfc7c9c9cf475af75769a6beaf4dade45925f",
    "174f273ff25818064be60cd4c7cded89ab8f257de484b32a21250578f323149b",
    "ccffe628bbd64e34a8442a045f95ec2ef65109765c0a0a476c0156aa84a5f9a2",
    "dc58fcc42ef9b4e6d15a129124eff54ce5d76e0e16e1e4f62115b64482e94fd2",
]


@pytest.fixture(scope="module")
def decisions_scellees():
    assert SEALED_DECISIONS.is_file()
    octets = SEALED_DECISIONS.read_bytes()
    assert hashlib.sha256(octets).hexdigest() == DECISION_SET_SHA256
    return parse_pii_review_decision_set(octets)


@pytest.fixture(scope="module")
def matrice():
    return json.loads(MATRICE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def readiness():
    return json.loads(READINESS_PATH.read_text(encoding="utf-8"))


def test_149_pii_decisions_scellees_et_valides(decisions_scellees) -> None:
    assert len(decisions_scellees.decisions) == 149
    approved = [d for d in decisions_scellees.decisions if d.decision == "APPROVED"]
    rejected = [d for d in decisions_scellees.decisions if d.decision == "REJECTED"]
    assert len(approved) == 23
    assert len(rejected) == 126
    assert decisions_scellees.decision_set_id == "pii-review-2026-09-17-final"
    for d in decisions_scellees.decisions:
        assert d.reviewer_login == "abenrhouma"
        assert d.decided_at.isoformat().startswith("2026-09-17")


def test_readiness_metrics_post_ce(readiness) -> None:
    assert readiness["pii_undecided"] == 0
    assert readiness["pre_release_blockers"] == 0
    assert readiness["release_promoted_refused_contents"] == 4
    assert readiness["release_promoted_refused_by_verdict"] == {"BLOCKED_NOT_CURRENT_BY_SOURCE": 4}
    assert readiness["go_live_qualification_blockers"] == 4
    assert readiness["go_live_ready"] is False
    assert "pre_release_blockers" not in readiness["blocking_reasons"]
    assert "pii_undecided" not in readiness["blocking_reasons"]
    assert "go_live_qualification_blockers" in readiness["blocking_reasons"]
    assert "release_promoted_refused_contents" in readiness["blocking_reasons"]


def test_les_4_refus_promus_sont_strictement_des_archives(readiness, matrice) -> None:
    assert sorted(readiness["release_promoted_refused_content_ids"]) == sorted(ARCHIVES_BLOQUEES)
    matrice_par_sha = {r["content_sha256"]: r for r in matrice["rows"]}
    for sha in ARCHIVES_BLOQUEES:
        assert sha in matrice_par_sha
        assert matrice_par_sha[sha]["verdict"] == "BLOCKED_NOT_CURRENT_BY_SOURCE"


def test_cas_157309db13b6_audit_transition(decisions_scellees, matrice) -> None:
    sha = "157309db13b674ffe4bf1371015bfc7c9c9cf475af75769a6beaf4dade45925f"
    d_scellee = next(d for d in decisions_scellees.decisions if d.content_sha256 == sha)
    assert d_scellee.decision == "APPROVED"

    matrice_par_sha = {r["content_sha256"]: r for r in matrice["rows"]}
    ligne = matrice_par_sha[sha]
    assert ligne["pii"] == "PII_CLEARED"
    assert ligne["currentness"] == "ARCHIVE_DECLARED"
    assert ligne["currentness_disposition"] == "NOT_CURRENT_DECLARED_BY_SOURCE"
    assert ligne["verdict"] == "BLOCKED_NOT_CURRENT_BY_SOURCE"


def test_matrice_cablage_provenance_explicite(matrice) -> None:
    inputs = matrice["inputs"]
    pii_dec = inputs.get("pii_decisions")
    assert pii_dec is not None
    assert pii_dec["path"] == "governance/pii-review-decisions/pii-review-2026-09-17-final.json"
    assert pii_dec["sha256"] == DECISION_SET_SHA256
    assert pii_dec["decision_set_id"] == "pii-review-2026-09-17-final"
    assert pii_dec["decisions_count"] == 149
    assert pii_dec["reviewer_login"] == "abenrhouma"
    assert pii_dec["source_pr"] == 219

    by_pii = matrice["by_pii"]
    assert by_pii.get("PII_UNDECIDED", 0) == 0
    assert by_pii["PII_CLEARED"] == 23
    assert by_pii["REJECTED"] == 126
    assert by_pii["PII_CLEARED_OR_NOT_SCANNED"] == 2381


def test_securite_invariants_production_et_matiere_brute(readiness) -> None:
    assert readiness["current_switch"] == 0
    assert readiness["production_db_writes"] == 0
    assert readiness["production_deployments"] == 0

    assert PROOF_PATH.is_file()
    octets = PROOF_PATH.read_bytes()
    scelle = PROOF_SHA_PATH.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(octets).hexdigest() == scelle

    preuve = json.loads(octets)
    assert preuve["kind"] == "NEXUS-PII-CURRENTNESS-APPROVED-IMPORT-PROOF-V1"
    assert preuve["counts"]["pii_undecided"] == 0
    assert preuve["counts"]["release_promoted_refused_contents_after"] == 4
    assert preuve["security_and_production_invariants"]["raw_pii_present"] is False
    assert preuve["security_and_production_invariants"]["current_switch"] == 0


def test_assert_ready_echoue_strictement() -> None:
    res = subprocess.run(
        [sys.executable, str(RACINE / "scripts/go_live/check_go_live_readiness.py"), "--assert-ready"],
        cwd=str(RACINE),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 1
    assert "ASSERT_READY=failed" in res.stderr
