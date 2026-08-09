#!/usr/bin/env python3
"""Exécute et scelle la répétition H2-C réelle hors production."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REAL_SHA = "371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d"
CORPUS_MANIFEST_SHA = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)
PII_EVIDENCE_SHA = (
    "76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311"
)
RESULT_PREFIX = "H2C_GOVERNED_REHEARSAL_RESULT="


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Valide les octets et preuves scellés, lance deux PostgreSQL "
            "jetables, puis scelle les métriques de la répétition LOT41A/LOT42."
        )
    )
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--pii-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def _catalog_placements(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    artifacts = document.get("artifacts")
    if isinstance(artifacts, dict):
        entry = artifacts.get(REAL_SHA)
    elif isinstance(artifacts, list):
        entry = next((item for item in artifacts if item.get("sha256") == REAL_SHA), None)
    else:
        raise RuntimeError("REAL_CATALOG_ARTIFACTS_MISSING")
    if not isinstance(entry, dict):
        raise RuntimeError("REAL_MULTI_PLACEMENT_ARTIFACT_MISSING")
    placements = entry.get("pedagogical_placements")
    if not isinstance(placements, list) or len(placements) != 7:
        raise RuntimeError("REAL_MULTI_PLACEMENT_CARDINALITY_INVALID")
    return placements


def _pii_binding(path: Path) -> dict[str, Any]:
    if _sha256(path) != PII_EVIDENCE_SHA:
        raise RuntimeError("PII_EVIDENCE_SHA256_MISMATCH")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("corpus_manifest_sha256") != CORPUS_MANIFEST_SHA:
        raise RuntimeError("PII_EVIDENCE_MANIFEST_MISMATCH")
    results = document.get("results")
    if not isinstance(results, list):
        raise RuntimeError("PII_EVIDENCE_RESULTS_MISSING")
    result = next(
        (item for item in results if item.get("content_sha256") == REAL_SHA),
        None,
    )
    if not isinstance(result, dict) or result.get("status") != "CLEARED":
        raise RuntimeError("REAL_MULTI_PLACEMENT_PII_NOT_CLEARED")
    if result.get("pii_detected") is not False:
        raise RuntimeError("REAL_MULTI_PLACEMENT_PII_RESULT_INVALID")
    return {
        "content_sha256": REAL_SHA,
        "evidence_sha256": PII_EVIDENCE_SHA,
        "pages_scanned": result.get("pages_scanned"),
        "status": "CLEARED",
    }


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = _arguments()
    if _sha256(args.pdf) != REAL_SHA:
        raise RuntimeError("REAL_PDF_SHA256_MISMATCH")
    placements = _catalog_placements(args.catalog)
    pii = _pii_binding(args.pii_evidence)

    service_root = Path(__file__).resolve().parents[1]
    runner = service_root / "infra" / "scripts" / "test_hybrid_integration.sh"
    environment = os.environ.copy()
    environment.update(
        {
            "NEXUS_H2C_REAL_REHEARSAL": "1",
            "NEXUS_H2C_REAL_PDF_PATH": str(args.pdf.resolve()),
            "NEXUS_H2C_REAL_CATALOG_PATH": str(args.catalog.resolve()),
        }
    )
    completed = subprocess.run(
        ["bash", str(runner)],
        cwd=service_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        return completed.returncode
    result_lines = [
        line.split(RESULT_PREFIX, 1)[1]
        for line in completed.stdout.splitlines()
        if RESULT_PREFIX in line
    ]
    if len(result_lines) != 1:
        raise RuntimeError("H2C_REHEARSAL_RESULT_MISSING_OR_DUPLICATED")
    result = json.loads(result_lines[0])
    if result.get("full_governed_rehearsal_pass") is not True:
        raise RuntimeError("H2C_REHEARSAL_NOT_GREEN")

    evidence = {
        "corpus_manifest_sha256": CORPUS_MANIFEST_SHA,
        "evidence_kind": "H2C_REAL_GOVERNED_REHEARSAL",
        "generated_at": datetime.now(UTC).isoformat(),
        "github_boundary": "LOCAL_HTTP_REHEARSAL_WITH_CANONICAL_LIVE_VERIFIERS",
        "pii_binding": pii,
        "product_database": "DISPOSABLE_POSTGRESQL_PGVECTOR",
        "production_database_touched": False,
        "production_publication_attestation": False,
        "real_catalog_sha256": _sha256(args.catalog),
        "real_pdf_sha256": REAL_SHA,
        "real_placement_count": len(placements),
        "rehearsal": result,
        "runner_output_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
    }
    _write_json(args.output, evidence)
    print(f"H2C_GOVERNED_REHEARSAL_EVIDENCE_SHA256={_sha256(args.output)}")
    print("PRODUCTION_DATABASE_TOUCHED=false")
    print("REAL_PRODUCTION_PUBLICATION_ATTESTATIONS=DEFERRED_TO_P4_BY_DESIGN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
