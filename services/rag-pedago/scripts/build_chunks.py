#!/usr/bin/env python3
"""Build chunks from clean staging content.

Checks chunking_allowed before acting (gating).
Produces JSONL artefacts in data/chunks/.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs" / "pedago_interface_contract.yml"
STAGING_DIR = ROOT / "data" / "staging" / "agents"
CHUNKS_DIR = ROOT / "data" / "chunks"

# Chunking parameters (justified in ADR-0006)
TARGET_TOKENS = 750  # ~600-900 tokens target range
OVERLAP_RATIO = 0.12  # ~12% overlap


def check_chunking_allowed(contract_path: Path | None = None) -> bool:
    """Gate: chunking_allowed must be true."""
    path = contract_path or CONTRACT
    if not path.is_file():
        return False
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        return False
    return config.get("chunking_allowed") is True


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


def _split_at_boundaries(text: str) -> list[str]:
    """Split text at paragraph/section boundaries."""
    # Split at double newlines or heading-like patterns
    parts = re.split(r"\n\n+|\n(?=[A-Z])", text)
    # Also split long paragraphs at sentence boundaries
    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if _estimate_tokens(part) <= TARGET_TOKENS * 1.5:
            result.append(part)
        else:
            # Split at sentences
            sentences = re.split(r"(?<=[.!?])\s+", part)
            result.extend(s.strip() for s in sentences if s.strip())
    return result


def chunk_text(text: str) -> list[str]:
    """Split text into chunks of target size with overlap."""
    parts = _split_at_boundaries(text)
    if not parts:
        return [text] if text.strip() else []

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for part in parts:
        part_tokens = _estimate_tokens(part)

        if current_parts and current_tokens + part_tokens > TARGET_TOKENS:
            # Emit current chunk
            chunks.append(" ".join(current_parts))

            # Overlap: keep last N parts
            overlap_tokens = int(current_tokens * OVERLAP_RATIO)
            overlap_parts: list[str] = []
            ot = 0
            for p in reversed(current_parts):
                pt = _estimate_tokens(p)
                if ot + pt > overlap_tokens:
                    break
                overlap_parts.insert(0, p)
                ot += pt

            current_parts = overlap_parts + [part]
            current_tokens = sum(_estimate_tokens(p) for p in current_parts)
        else:
            current_parts.append(part)
            current_tokens += part_tokens

    if current_parts:
        chunks.append(" ".join(current_parts))

    return chunks


def build_chunks_for_notion(staging_file: Path) -> list[dict]:
    """Build chunks from a staging file, preserving all metadata."""
    data = json.loads(staging_file.read_text(encoding="utf-8"))
    text = data.get("text", data.get("text_preview", ""))

    if not text or len(text.strip()) < 50:
        return []

    chunks = chunk_text(text)
    result = []

    for i, chunk_text_content in enumerate(chunks):
        chunk_entry = {
            "chunk_index": i,
            "chunk_total": len(chunks),
            "text": chunk_text_content,
            "text_length": len(chunk_text_content),
            "tokens_est": _estimate_tokens(chunk_text_content),
            # Preserve all metadata from staging
            "notion_id": data.get("notion_id", ""),
            "matiere": data.get("matiere", ""),
            "niveau": data.get("niveau", ""),
            "voie": data.get("voie", ""),
            "statut_enseignement": data.get("statut_enseignement", ""),
            "audience": data.get("audience", "tous"),
            "source": data.get("source", ""),
            "source_label": data.get("source_label", ""),
            "rights": data.get("rights", ""),
            "chosen_url": data.get("chosen_url", data.get("url", "")),
        }
        result.append(chunk_entry)

    return result


def main() -> int:
    if not check_chunking_allowed():
        print("BLOCKED: chunking_allowed is false")
        return 1

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    total_chunks = 0
    total_notions = 0

    for niveau_dir in sorted(STAGING_DIR.iterdir()):
        if not niveau_dir.is_dir():
            continue
        for matiere_dir in sorted(niveau_dir.iterdir()):
            if not matiere_dir.is_dir():
                continue
            for staging_file in sorted(matiere_dir.glob("*.json")):
                chunks = build_chunks_for_notion(staging_file)
                if not chunks:
                    continue

                matiere = chunks[0]["matiere"]
                notion_id = chunks[0]["notion_id"]
                out_file = CHUNKS_DIR / f"{matiere}_{notion_id}.jsonl"
                with out_file.open("w", encoding="utf-8") as f:
                    for chunk in chunks:
                        f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

                total_chunks += len(chunks)
                total_notions += 1
                print(f"  {matiere}/{notion_id}: {len(chunks)} chunks")

    print(f"\n{total_notions} notions, {total_chunks} chunks total in {CHUNKS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
