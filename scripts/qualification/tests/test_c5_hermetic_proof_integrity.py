"""Test hermétique de l'intégrité de la preuve C5 (sans dépendance à FastAPI ni rag-engine)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

RACINE = Path(__file__).resolve().parents[3]

sys.path.extend(
    [
        str(RACINE / "packages/contracts/src"),
        str(RACINE / "packages/release-chain/src"),
        str(RACINE / "packages/pdf-page-policy/src"),
        str(RACINE / "scripts/qualification"),
    ]
)

EXPECTED_C5_ASSERTIONS = {
    "UNKNOWN_SCOPE_ID_REFUSED",
    "FORGED_SCOPE_ID_REFUSED",
    "SCOPE_DIGEST_CORRUPTION_REFUSED",
    "TARGET_LEVEL_DRIFT_REFUSED",
    "CURRICULUM_LEVEL_DRIFT_REFUSED",
    "CROSS_SUBJECT_DRIFT_REFUSED",
    "OMITTED_CURRICULUM_SCOPE_REFUSED",
    "AUTHORIZATION_MAPPING_INCOMPLETE_REFUSED",
    "AUTHORIZATION_SET_V2_FALSIFIED_OR_DIVERGENT_REFUSED",
    "CONTENT_OUTSIDE_AUTHORIZATION_REFUSED",
    "OVERLAP_OR_DUPLICATION_REFUSED",
    "DENORMALIZED_COLUMNS_CANNOT_WIDEN_AUTHORITY",
    "INACTIVE_PLACEMENT_REFUSED",
    "STALE_OR_UNREVIEWED_PLACEMENT_REFUSED",
    "_EFFECTIVE_SCOPE_FILTER_SQL_ENFORCES_GOVERNED_PLACEMENT",
}


def test_verify_access_authority_scopes_module_is_import_safe() -> None:
    """Vérifie que le module C5 peut être importé sans fastapi ni rag-engine."""
    import verify_access_authority_scopes as c5_verifier

    assert hasattr(c5_verifier, "KIND")
    assert hasattr(c5_verifier, "DEFAULT_OUTPUT")
    assert hasattr(c5_verifier, "DEFAULT_SHA")
    assert hasattr(c5_verifier, "run_all_c5_verifications")


def test_c5_refusal_proof_file_exists_and_sha256_matches() -> None:
    """Vérifie l'existence et l'intégrité cryptographique SHA-256 de la preuve C5 scellée."""
    evidence_path = RACINE / "docs/reports/evidence/access_authority_c5_refusal_proof.json"
    sha_path = RACINE / "docs/reports/evidence/access_authority_c5_refusal_proof.sha256"

    assert evidence_path.is_file(), f"Fichier de preuve absent: {evidence_path}"
    assert sha_path.is_file(), f"Fichier sha256 absent: {sha_path}"

    octets = evidence_path.read_bytes()
    sha_reel = hashlib.sha256(octets).hexdigest()

    sha_line = sha_path.read_text(encoding="utf-8").strip()
    sha_attendu = sha_line.split()[0]
    assert sha_reel == sha_attendu, f"Empreinte C5 altérée: {sha_reel} != {sha_attendu}"


def test_c5_refusal_proof_contains_all_15_assertions_and_all_true() -> None:
    """Vérifie que la preuve scellée C5 contient les 15 assertions requises et qu'elles sont toutes vraies."""
    evidence_path = RACINE / "docs/reports/evidence/access_authority_c5_refusal_proof.json"
    data = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert data["kind"] == "NEXUS-C5-ACCESS-AUTHORITY-REFUSAL-PROOF-V1"
    assert data["verification_status"] == "VERIFIED"
    assert data["summary"]["failed_proofs"] == 0
    assert data["summary"]["passed_proofs"] >= 15

    verdicts = data.get("verdicts", {})
    missing_assertions = EXPECTED_C5_ASSERTIONS - set(verdicts.keys())
    assert not missing_assertions, f"Assertions C5 manquantes dans la preuve: {missing_assertions}"

    for assertion_name in EXPECTED_C5_ASSERTIONS:
        assert verdicts[assertion_name] is True, f"Assertion C5 non validée: {assertion_name} = {verdicts[assertion_name]}"
