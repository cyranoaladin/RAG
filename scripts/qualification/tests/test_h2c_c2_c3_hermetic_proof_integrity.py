"""Test hermétique de l'intégrité des preuves H2-C C2 et C3 (sans dépendance externe)."""

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


def test_verify_h2c_multilevel_gates_module_is_import_safe() -> None:
    """Vérifie que le module de qualification C2/C3 s'importe sans dépendance externe."""
    import verify_h2c_multilevel_gates as h2c_verifier

    assert hasattr(h2c_verifier, "MAIN_SHA_EXPECTED")
    assert hasattr(h2c_verifier, "C2_OUTPUT_JSON")
    assert hasattr(h2c_verifier, "C3_OUTPUT_JSON")
    assert hasattr(h2c_verifier, "build_c2_proof")
    assert hasattr(h2c_verifier, "build_c3_proof")


def test_c2_multilevel_ingestion_proof_file_exists_and_sha256_matches() -> None:
    """Vérifie l'existence et l'intégrité cryptographique SHA-256 de la preuve C2 scellée."""
    evidence_path = RACINE / "docs/reports/evidence/h2c_c2_multilevel_ingestion_e2e_proof.json"
    sha_path = RACINE / "docs/reports/evidence/h2c_c2_multilevel_ingestion_e2e_proof.sha256"

    assert evidence_path.is_file(), f"Fichier de preuve absent: {evidence_path}"
    assert sha_path.is_file(), f"Fichier sha256 absent: {sha_path}"

    octets = evidence_path.read_bytes()
    calcule = hashlib.sha256(octets).hexdigest()

    lignes = sha_path.read_text(encoding="utf-8").strip().splitlines()
    sha_attendu = lignes[0].split()[0]
    assert calcule == sha_attendu, f"SHA-256 altéré: {calcule} != {sha_attendu}"

    data = json.loads(octets.decode("utf-8"))
    assert data["kind"] == "NEXUS-C2-MULTILEVEL-INGESTION-E2E-PROOF-V1"
    assert data["verification_status"] == "VERIFIED"
    assert data["observed_at_main_sha"] == "4e7c40b731823a517f1a29f3838c3794638bde68"
    assert data["cardinalities"]["target_collections"] == 10
    assert data["cardinalities"]["stored_chunks"] == 353
    assert data["ephemeral_environment"]["docker_residues_after_test"] == 0
    assert data["ephemeral_environment"]["production_touched"] is False
    assert data["ephemeral_environment"]["production_db_writes"] == 0
    assert data["ephemeral_environment"]["current_switch"] == 0


def test_c3_worker_cli_proof_file_exists_and_sha256_matches() -> None:
    """Vérifie l'existence et l'intégrité cryptographique SHA-256 de la preuve C3 scellée."""
    evidence_path = RACINE / "docs/reports/evidence/h2c_c3_worker_cli_e2e_proof.json"
    sha_path = RACINE / "docs/reports/evidence/h2c_c3_worker_cli_e2e_proof.sha256"

    assert evidence_path.is_file(), f"Fichier de preuve absent: {evidence_path}"
    assert sha_path.is_file(), f"Fichier sha256 absent: {sha_path}"

    octets = evidence_path.read_bytes()
    calcule = hashlib.sha256(octets).hexdigest()

    lignes = sha_path.read_text(encoding="utf-8").strip().splitlines()
    sha_attendu = lignes[0].split()[0]
    assert calcule == sha_attendu, f"SHA-256 altéré: {calcule} != {sha_attendu}"

    data = json.loads(octets.decode("utf-8"))
    assert data["kind"] == "NEXUS-C3-WORKER-CLI-E2E-PROOF-V1"
    assert data["verification_status"] == "VERIFIED"
    assert data["observed_at_main_sha"] == "4e7c40b731823a517f1a29f3838c3794638bde68"
    assert data["cardinalities"]["target_collections"] == 2
    assert data["ephemeral_environment"]["docker_residues_after_test"] == 0
    assert data["ephemeral_environment"]["production_touched"] is False
    assert data["ephemeral_environment"]["production_db_writes"] == 0
    assert data["ephemeral_environment"]["current_switch"] == 0
