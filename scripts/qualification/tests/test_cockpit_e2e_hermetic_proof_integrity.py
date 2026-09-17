"""Test hermétique de l'intégrité de la preuve COCKPIT_E2E (sans dépendance externe)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]

sys.path.extend(
    [
        str(RACINE / "packages/contracts/src"),
        str(RACINE / "packages/release-chain/src"),
        str(RACINE / "packages/pdf-page-policy/src"),
        str(RACINE / "scripts/qualification"),
    ]
)


def test_verify_cockpit_e2e_retrieval_module_is_import_safe() -> None:
    """Vérifie que le module de qualification COCKPIT_E2E s'importe sans dépendance externe."""
    import verify_cockpit_e2e_retrieval as verifier

    assert hasattr(verifier, "MAIN_SHA_EXPECTED")
    assert hasattr(verifier, "OUTPUT_JSON")
    assert hasattr(verifier, "OUTPUT_SHA")
    assert hasattr(verifier, "verify_sealed_proof")


def test_cockpit_e2e_retrieval_proof_file_exists_and_sha256_matches() -> None:
    """Vérifie l'existence et l'intégrité cryptographique SHA-256 de la preuve COCKPIT_E2E."""
    evidence_path = RACINE / "docs/reports/evidence/cockpit_e2e_retrieval_proof.json"
    sha_path = RACINE / "docs/reports/evidence/cockpit_e2e_retrieval_proof.sha256"

    assert evidence_path.is_file(), f"Fichier de preuve absent: {evidence_path}"
    assert sha_path.is_file(), f"Fichier sha256 absent: {sha_path}"

    octets = evidence_path.read_bytes()
    calcule = hashlib.sha256(octets).hexdigest()

    lignes = sha_path.read_text(encoding="utf-8").strip().splitlines()
    sha_attendu = lignes[0].split()[0]
    assert calcule == sha_attendu, f"SHA-256 altéré: {calcule} != {sha_attendu}"

    data = json.loads(octets.decode("utf-8"))
    assert data["kind"] == "NEXUS-COCKPIT-E2E-RETRIEVAL-PROOF-V1"
    assert data["verification_status"] == "VERIFIED"
    assert data["observed_at_main_sha"] == "7769b72259d8e51749de07ab9a2dbc0a6e86ef28"
    assert data["cockpit_configuration"]["mock_fallback_detected"] is False
    assert data["ephemeral_environment"]["docker_residues_after_test"] == 0
    assert data["ephemeral_environment"]["production_touched"] is False
    assert data["ephemeral_environment"]["production_db_writes"] == 0
    assert data["ephemeral_environment"]["current_switch"] == 0
    assert data["security_verifications"]["unauthenticated_request_rejected"] is True
    assert data["security_verifications"]["unauthorized_scope_collection_rejected"] is True
    assert data["citations_summary"]["total_citations_verified"] > 0
    assert data["verdicts"]["TEST_EXECUTION_PASSED"] is True
