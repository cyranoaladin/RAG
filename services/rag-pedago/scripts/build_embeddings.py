#!/usr/bin/env python3
"""Build embedding vectors for chunked content.

Checks embeddings_allowed before acting (gating).
Produces JSONL artefacts in data/embeddings/.
Idempotent: skips chunks whose sha256 hasn't changed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs" / "pedago_interface_contract.yml"
CHUNKS_DIR = ROOT / "data" / "chunks"
EMBEDDINGS_DIR = ROOT / "data" / "embeddings"

# Production model: multilingual-e5-large (1024 dims, multilingue FR)
# Dimension is DEFINITIVE (conditions pgvector schema at Lot 14)
MODEL_NAME = "intfloat/multilingual-e5-large"
MODEL_DIM = 1024


def check_embeddings_allowed(contract_path: Path | None = None) -> bool:
    """Gate: embeddings_allowed must be true."""
    path = contract_path or CONTRACT
    if not path.is_file():
        return False
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(config, dict):
        return False
    return config.get("embeddings_allowed") is True


def _load_existing_embeddings(emb_file: Path) -> dict[str, str]:
    """Load existing embeddings index: chunk_id → chunk_sha256."""
    if not emb_file.is_file():
        return {}
    result: dict[str, str] = {}
    for line in emb_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            entry = json.loads(line)
            result[entry["chunk_id"]] = entry.get("chunk_sha256", "")
    return result


def _load_model():
    """Load the sentence-transformers model (lazy import)."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def build_embeddings_for_notion(
    chunks_file: Path,
    sidecar_file: Path,
    emb_file: Path,
    model: Any,
) -> dict[str, int]:
    """Compute embeddings for one notion's chunks. Returns stats."""
    chunks = []
    for line in chunks_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            chunks.append(json.loads(line))

    if not chunks:
        return {"computed": 0, "skipped": 0}

    # Load sidecar for filtering metadata
    sidecar = {}
    if sidecar_file.is_file():
        sidecar = json.loads(sidecar_file.read_text(encoding="utf-8"))

    # Check existing embeddings for idempotence
    existing = _load_existing_embeddings(emb_file)

    to_compute: list[dict] = []
    reused: list[dict] = []

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        chunk_sha = chunk.get("chunk_sha256", "")
        if existing.get(chunk_id) == chunk_sha and chunk_sha:
            # Reuse existing — read from file
            reused_entry = None
            if emb_file.is_file():
                for line in emb_file.read_text(encoding="utf-8").strip().split("\n"):
                    entry = json.loads(line)
                    if entry["chunk_id"] == chunk_id:
                        reused_entry = entry
                        break
            if reused_entry:
                reused.append(reused_entry)
                continue
        to_compute.append(chunk)

    # Compute new embeddings
    computed_entries: list[dict] = []
    if to_compute:
        texts = [c["text"] for c in to_compute]
        vectors = model.encode(texts, normalize_embeddings=True).tolist()

        for chunk, vector in zip(texts, vectors, strict=False):
            chunk_data = to_compute[texts.index(chunk)]
            computed_entries.append({
                "chunk_id": chunk_data["chunk_id"],
                "doc_id": chunk_data["doc_id"],
                "chunk_sha256": chunk_data.get("chunk_sha256", ""),
                "dim": len(vector),
                "vector": vector,
                "model": MODEL_NAME,
                # Filtering metadata from sidecar
                "niveau": sidecar.get("niveau", ""),
                "voie": sidecar.get("voie", ""),
                "audience": sidecar.get("audience", []),
                "matiere": sidecar.get("matiere", ""),
                "notions": chunk_data.get("notions", []),
            })

    # Write all embeddings (reused + computed)
    all_entries = reused + computed_entries
    if all_entries:
        emb_file.parent.mkdir(parents=True, exist_ok=True)
        with emb_file.open("w", encoding="utf-8") as f:
            for entry in all_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"computed": len(computed_entries), "skipped": len(reused)}


def main() -> int:
    if not check_embeddings_allowed():
        print("BLOCKED: embeddings_allowed is false")
        return 1

    print(f"Loading model: {MODEL_NAME}...")
    model = _load_model()

    total_computed = 0
    total_skipped = 0
    total_notions = 0

    for jsonl in sorted(CHUNKS_DIR.rglob("*.jsonl")):
        sidecar = jsonl.with_suffix(".meta.json")
        rel = jsonl.relative_to(CHUNKS_DIR)
        emb_file = EMBEDDINGS_DIR / rel

        stats = build_embeddings_for_notion(jsonl, sidecar, emb_file, model)
        total_computed += stats["computed"]
        total_skipped += stats["skipped"]
        total_notions += 1
        print(f"  {rel.stem}: {stats['computed']} computed, {stats['skipped']} skipped")

    print(f"\n{total_notions} notions, {total_computed} computed, {total_skipped} skipped")
    print(f"Embeddings in {EMBEDDINGS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
