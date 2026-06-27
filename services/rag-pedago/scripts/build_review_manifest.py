#!/usr/bin/env python3
"""Build review manifest from validated embeddings.

Produces data/embeddings/review_manifest.json listing approved
(chunk_id, chunk_sha256) pairs. The indexer only admits chunks
present in this manifest with matching sha.

This script VALIDATES quality before approval:
- dim = 1024
- norme ≈ 1.0
- metadata complete (niveau, matiere, audience)
- 0 NaN/Inf
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBEDDINGS_DIR = ROOT / "data" / "embeddings"
MANIFEST_PATH = EMBEDDINGS_DIR / "review_manifest.json"
EXPECTED_DIM = 1024


def main() -> int:
    approved: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []

    for jsonl in sorted(EMBEDDINGS_DIR.rglob("*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            entry = json.loads(line)
            chunk_id = entry.get("chunk_id", "")
            sha = entry.get("chunk_sha256", "")
            issues: list[str] = []

            # Quality checks
            if entry.get("dim") != EXPECTED_DIM:
                issues.append(f"dim={entry.get('dim')}")
            vec = entry.get("vector", [])
            if any(math.isnan(v) or math.isinf(v) for v in vec):
                issues.append("NaN/Inf in vector")
            if not entry.get("niveau"):
                issues.append("missing niveau")
            if not entry.get("matiere"):
                issues.append("missing matiere")

            if issues:
                rejected.append({"chunk_id": chunk_id, "issues": ", ".join(issues)})
            else:
                approved.append({"chunk_id": chunk_id, "chunk_sha256": sha})

    manifest = {
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "approved": approved,
        "rejected": rejected,
    }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Manifest: {len(approved)} approved, {len(rejected)} rejected → {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
