"""Test hermétique de l'intégrité de la preuve CAS C6 (sans dépendance externe)."""

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

EXPECTED_C6_ASSERTIONS = {
    "CAS_ROOT_EXPLICITLY_NAMED",
    "CAS_MANIFEST_EXISTS",
    "CAS_MANIFEST_SCHEMA_CONFORMANT",
    "ALL_OBJECTS_READ_FROM_DISK",
    "SHA256_RECALCULATED_ON_BYTES",
    "DECLARED_SIZES_VERIFIED",
    "NO_EXPECTED_OBJECTS_MISSING",
    "NO_EXTRA_OBJECTS_SILENTLY_ACCEPTED",
    "NO_LOCATOR_ESCAPES_CAS_ROOT",
    "NO_SYMLINK_TRAVERSAL",
    "CONTENT_SET_DIGEST_MATCHES_EXPECTED_AUTHORITY",
    "EXPECTED_COUNT_MATCHES_EXACTLY",
    "COVERAGE_ON_GOVERNED_SCOPE",
    "NO_MATRIX_REFUSED_CONTENT_ADMITTED",
    "NO_PII_UNDECIDED_CONTENT_PROMOTED",
    "NO_CURRENTNESS_REFUSED_CONTENT_REINTRODUCED",
    "RESULT_SEALED_BY_SHA256",
}


def test_verify_corpus_cas_c6_module_is_import_safe() -> None:
    """Vérifie que le module de qualification C6 s'importe sans dépendance externe."""
    import verify_corpus_cas_c6 as c6_verifier

    assert hasattr(c6_verifier, "KIND")
    assert hasattr(c6_verifier, "DEFAULT_OUTPUT")
    assert hasattr(c6_verifier, "DEFAULT_SHA")
    assert hasattr(c6_verifier, "run_c6_qualification")


def test_c6_cas_proof_file_exists_and_sha256_matches() -> None:
    """Vérifie l'existence et l'intégrité cryptographique SHA-256 de la preuve C6 scellée."""
    evidence_path = RACINE / "docs/reports/evidence/corpus_cas_c6_proof.json"
    sha_path = RACINE / "docs/reports/evidence/corpus_cas_c6_proof.sha256"

    assert evidence_path.is_file(), f"Fichier de preuve absent: {evidence_path}"
    assert sha_path.is_file(), f"Fichier sha256 absent: {sha_path}"

    octets = evidence_path.read_bytes()
    sha_reel = hashlib.sha256(octets).hexdigest()

    sha_line = sha_path.read_text(encoding="utf-8").strip()
    sha_attendu = sha_line.split()[0]
    assert sha_reel == sha_attendu, f"Empreinte C6 altérée: {sha_reel} != {sha_attendu}"


def test_c6_cas_proof_contains_all_17_assertions_and_all_true() -> None:
    """Vérifie que la preuve scellée C6 contient les 17 assertions requises et qu'elles sont toutes vraies."""
    evidence_path = RACINE / "docs/reports/evidence/corpus_cas_c6_proof.json"
    data = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert data.get("verification_status") == "VERIFIED"
    assert data.get("kind") == "NEXUS-C6-CORPUS-CAS-QUALIFICATION-PROOF-V1"

    verdicts = data.get("verdicts", {})
    missing_assertions = EXPECTED_C6_ASSERTIONS - set(verdicts.keys())
    assert not missing_assertions, f"Assertions C6 manquantes: {missing_assertions}"

    failing_assertions = [k for k in EXPECTED_C6_ASSERTIONS if not verdicts.get(k)]
    assert not failing_assertions, f"Assertions C6 échouées: {failing_assertions}"

    summary = data.get("summary", {})
    assert summary.get("failed_items") == 0
    assert summary.get("passed_checks") >= 17


def test_c6_cas_proof_scope_and_matrix_exclusions() -> None:
    """Vérifie que la portée est strictement SERVABLE_CANDIDATE_SET et exclut les refusés."""
    evidence_path = RACINE / "docs/reports/evidence/corpus_cas_c6_proof.json"
    data = json.loads(evidence_path.read_text(encoding="utf-8"))

    target_scope = data.get("target_scope", {})
    assert target_scope.get("name") == "SERVABLE_CANDIDATE_SET"
    assert target_scope.get("count") == 2264
    assert (
        target_scope.get("content_set_digest")
        == "227617d4c4364dda1267b15bb30005a26a329414bc151f3c3e5f4c5362a1fbdd"
    )

    verif = data.get("verifications", {})
    assert verif.get("matrix_refused_admitted") == 0
    assert verif.get("pii_undecided_promoted") == 0
    assert verif.get("currentness_refused_reintroduced") == 0
    assert verif.get("expected_objects_missing") == 0
    assert verif.get("locator_escapes_detected") == 0
    assert verif.get("symlinks_detected") == 0
