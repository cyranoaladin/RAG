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
INPUT_FORMAT = "e5-passage-v1"  # tracks the prefix convention


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


def _load_existing_embeddings(emb_file: Path) -> dict[str, dict]:
    """Load existing embeddings: chunk_id → full entry (for idempotence check)."""
    if not emb_file.is_file():
        return {}
    result: dict[str, dict] = {}
    for line in emb_file.read_text(encoding="utf-8").strip().split("\n"):
        if line.strip():
            entry = json.loads(line)
            result[entry["chunk_id"]] = entry
    return result


def _can_reuse(existing_entry: dict) -> bool:
    """Check if an existing embedding can be reused (same model + dim + format)."""
    return (
        existing_entry.get("model") == MODEL_NAME
        and existing_entry.get("dim") == MODEL_DIM
        and existing_entry.get("input_format") == INPUT_FORMAT
    )


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

    # Idempotence check: (chunk_sha256, model, dim) must all match
    existing = _load_existing_embeddings(emb_file)

    to_compute: list[dict] = []
    reused: list[dict] = []

    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        chunk_sha = chunk.get("chunk_sha256", "")
        existing_entry = existing.get(chunk_id)
        if (
            existing_entry
            and existing_entry.get("chunk_sha256") == chunk_sha
            and chunk_sha
            and _can_reuse(existing_entry)
        ):
            # Refresh metadata from current sidecar (audience/niveau may have changed)
            existing_entry["niveau"] = sidecar.get("niveau", existing_entry.get("niveau", ""))
            existing_entry["voie"] = sidecar.get("voie", existing_entry.get("voie", ""))
            existing_entry["audience"] = sidecar.get("audience", existing_entry.get("audience", []))
            existing_entry["matiere"] = sidecar.get("matiere", existing_entry.get("matiere", ""))
            reused.append(existing_entry)
        else:
            to_compute.append(chunk)

    # Compute new embeddings with "passage: " prefix (e5 convention)
    from scrapers.embedding_utils import format_passage

    computed_entries: list[dict] = []
    if to_compute:
        prefixed_texts = [format_passage(c["text"]) for c in to_compute]
        vectors = model.encode(prefixed_texts, normalize_embeddings=True).tolist()

        for i, vector in enumerate(vectors):
            chunk_data = to_compute[i]
            computed_entries.append({
                "chunk_id": chunk_data["chunk_id"],
                "doc_id": chunk_data["doc_id"],
                "chunk_sha256": chunk_data.get("chunk_sha256", ""),
                "dim": len(vector),
                "vector": vector,
                "model": MODEL_NAME,
                "input_format": INPUT_FORMAT,
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
