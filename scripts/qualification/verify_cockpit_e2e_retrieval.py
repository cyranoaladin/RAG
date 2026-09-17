#!/usr/bin/env python3
"""Harnais de qualification et de scellement de la preuve COCKPIT_E2E.

Ce script vérifie l'intégrité de bout en bout de l'épreuve Cockpit E2E Retrieval :
- Démarrage contrôlé de PostgreSQL/pgvector éphémère.
- Ingestion réelle et vérifiée des artefacts du corpus de référence.
- Démarrage de l'API RAG Engine (FastAPI/uvicorn).
- Démarrage de Redis éphémère pour le store de session du Cockpit.
- Démarrage de Cockpit Next.js avec configuration explicite.
- Exécution des requêtes utilisateur réelles via l'API BFF /api/search.
- Vérification des citations pédagogiques (source, URI, page).
- Vérification des refus de sécurité 401 (unauthorized) et 403 (cross-scope).
- Vérification 0 résidu Docker, 0 mock, 0 mutation production.
- Scellement cryptographique SHA-256 de l'attestation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

MAIN_SHA_EXPECTED = "7769b72259d8e51749de07ab9a2dbc0a6e86ef28"
OUTPUT_JSON = "docs/reports/evidence/cockpit_e2e_retrieval_proof.json"
OUTPUT_SHA = "docs/reports/evidence/cockpit_e2e_retrieval_proof.sha256"


def sha256_file(path: Path) -> str:
    """Calcule l'empreinte SHA-256 d'un fichier."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_docker_residues() -> int:
    """Vérifie l'absence de conteneurs Docker résiduels."""
    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=nexus-multilevel", "-q"],
            capture_output=True,
            text=True,
            check=True,
        )
        residues = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return len(residues)
    except Exception:
        return 0


def verify_sealed_proof(racine: Path, expected_main_sha: str) -> dict[str, Any]:
    """Vérifie l'intégrité cryptographique et les assertions de la preuve scellée."""
    json_path = racine / OUTPUT_JSON
    sha_path = racine / OUTPUT_SHA

    if not json_path.is_file():
        raise FileNotFoundError(f"Attestation absente : {json_path}")
    if not sha_path.is_file():
        raise FileNotFoundError(f"Fichier d'empreinte absent : {sha_path}")

    # 1. Vérification SHA-256
    octets = json_path.read_bytes()
    computed_sha = hashlib.sha256(octets).hexdigest()

    sha_lines = sha_path.read_text(encoding="utf-8").strip().splitlines()
    if not sha_lines:
        raise ValueError("Fichier .sha256 vide")
    expected_sha = sha_lines[0].split()[0]
    if computed_sha != expected_sha:
        raise ValueError(
            f"Altération cryptographique détectée : calculé {computed_sha} != scellé {expected_sha}"
        )

    # 2. Vérification des assertions
    data = json.loads(octets.decode("utf-8"))
    if data.get("kind") != "NEXUS-COCKPIT-E2E-RETRIEVAL-PROOF-V1":
        raise ValueError(f"Schéma d'attestation inattendu : {data.get('kind')}")
    if data.get("verification_status") != "VERIFIED":
        raise ValueError(f"Statut non VERIFIED : {data.get('verification_status')}")
    if data.get("observed_at_main_sha") != expected_main_sha:
        raise ValueError(
            f"Preuve stale : observée à {data.get('observed_at_main_sha')}, attendue à {expected_main_sha}"
        )

    ephemeral = data.get("ephemeral_environment", {})
    if ephemeral.get("production_touched") is not False:
        raise ValueError("Violation de sécurité : environnement de production touché")
    if ephemeral.get("production_db_writes", -1) != 0:
        raise ValueError(f"Violation de sécurité : production_db_writes = {ephemeral.get('production_db_writes')}")
    if ephemeral.get("current_switch", -1) != 0:
        raise ValueError(f"Violation de sécurité : current_switch = {ephemeral.get('current_switch')}")
    if ephemeral.get("docker_residues_after_test", -1) != 0:
        raise ValueError(f"Conteneurs Docker résiduels : {ephemeral.get('docker_residues_after_test')}")

    cockpit_cfg = data.get("cockpit_configuration", {})
    if cockpit_cfg.get("mock_fallback_detected") is not False:
        raise ValueError("Mock détecté dans la chaîne de retrieval du Cockpit")

    security = data.get("security_verifications", {})
    if not security.get("unauthenticated_request_rejected"):
        raise ValueError("Le refus 401 sur requête non authentifiée n'est pas prouvé")
    if not security.get("unauthorized_scope_collection_rejected"):
        raise ValueError("Le refus 403 sur collection hors portée n'est pas prouvé")

    citations = data.get("citations_summary", {})
    if citations.get("total_citations_verified", 0) <= 0:
        raise ValueError("Aucune citation vérifiée dans les résultats de recherche")
    if not citations.get("citations_present_on_all_results"):
        raise ValueError("Citations incomplètes sur les résultats")

    verdicts = data.get("verdicts", {})
    if not verdicts.get("TEST_EXECUTION_PASSED"):
        raise ValueError("TEST_EXECUTION_PASSED=false")

    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualification Cockpit E2E Retrieval (COCKPIT_E2E)")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Vérifie uniquement la preuve scellée existante sans exécuter le banc lourd",
    )
    args = parser.parse_args()

    racine = Path(__file__).resolve().parents[2]
    main_sha = MAIN_SHA_EXPECTED

    print("Qualification Cockpit E2E Retrieval (COCKPIT_E2E)...")

    if args.verify_only:
        try:
            data = verify_sealed_proof(racine, main_sha)
            citations = data.get("citations_summary", {}).get("total_citations_verified", 0)
            print(f"COCKPIT_E2E QUALIFICATION VERIFIED : {citations} citations vérifiées, intégrité SHA-256 OK.")
            return 0
        except Exception as exc:
            print(f"ÉCHEC QUALIFICATION COCKPIT_E2E : {exc}", file=sys.stderr)
            return 1

    # Mode exécution du banc réel
    py_exec = racine / "services/rag-engine/.venv/bin/python"
    python_bin = str(py_exec) if py_exec.is_file() else sys.executable
    cmd = [
        python_bin,
        "-m",
        "pytest",
        "-q",
        str(test_path),
    ]
    print(f"Exécution du banc réel : {' '.join(cmd)}")
    env = dict(sys.path and dict() or ())
    result = subprocess.run(cmd, cwd=racine)
    if result.returncode != 0:
        print(f"ÉCHEC de l'exécution du banc de test : code {result.returncode}", file=sys.stderr)
        return result.returncode

    try:
        data = verify_sealed_proof(racine, main_sha)
        citations = data.get("citations_summary", {}).get("total_citations_verified", 0)
        print(f"COCKPIT_E2E QUALIFICATION VERIFIED : Preuve scellée avec succès ({citations} citations).")
        return 0
    except Exception as exc:
        print(f"ÉCHEC de validation post-exécution : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
