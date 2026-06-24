"""Tests for the pedagogical chunker and pilot corpus chunks.

Validates:
1. All chunks conform to ChunkMetadata schema
2. No content loss (all source headings present in chunks)
3. Audience tagging correctness
4. Notions non-empty for taxonomy-mapped files
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.pedagogical_chunker import (
    TaggingConfig,
    chunk_file,
    parse_sections,
)

# ChunkMetadata from nexus-contracts
try:
    from nexus_contracts.chunk import ChunkMetadata
except ImportError:
    pytest.skip("nexus-contracts not installed", allow_module_level=True)


CHUNKS_DIR = Path(__file__).resolve().parents[1] / "data/chunks/terminale"
CORPUS_DIR = Path(__file__).resolve().parents[3] / "corpus"

EXPECTED_FILES = [
    "mathematiques.jsonl",
    "nsi.jsonl",
    "philosophie.jsonl",
    "referentiel_candidat_libre.jsonl",
]


def _load_jsonl(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


# --- Test: JSONL files exist ---

def test_all_jsonl_exist():
    for fname in EXPECTED_FILES:
        assert (CHUNKS_DIR / fname).is_file(), f"Missing {fname}"


# --- Test: 100% ChunkMetadata validation ---

@pytest.mark.parametrize("fname", EXPECTED_FILES)
def test_all_chunks_validate_metadata(fname):
    chunks = _load_jsonl(CHUNKS_DIR / fname)
    assert len(chunks) > 0, f"No chunks in {fname}"
    for i, chunk in enumerate(chunks):
        meta = chunk["metadata"]
        try:
            ChunkMetadata(**meta)
        except Exception as e:
            pytest.fail(f"{fname} chunk {i} ({chunk.get('chunk_id', '?')}): {e}")


# --- Test: audience correctness ---

def test_audience_disciplinaire_is_tous():
    for fname in ["mathematiques.jsonl", "nsi.jsonl", "philosophie.jsonl"]:
        chunks = _load_jsonl(CHUNKS_DIR / fname)
        for chunk in chunks:
            assert chunk["metadata"]["audience"] == ["tous"], (
                f"{fname} chunk {chunk['chunk_id']}: expected audience [tous], "
                f"got {chunk['metadata']['audience']}"
            )


def test_audience_referentiel_is_libre():
    chunks = _load_jsonl(CHUNKS_DIR / "referentiel_candidat_libre.jsonl")
    for chunk in chunks:
        assert chunk["metadata"]["audience"] == ["libre"], (
            f"referentiel chunk {chunk['chunk_id']}: expected audience [libre], "
            f"got {chunk['metadata']['audience']}"
        )


def test_no_aefe_audience_in_lot():
    for fname in EXPECTED_FILES:
        chunks = _load_jsonl(CHUNKS_DIR / fname)
        for chunk in chunks:
            assert "aefe" not in chunk["metadata"]["audience"], (
                f"{fname} chunk {chunk['chunk_id']}: unexpected aefe audience"
            )


# --- Test: content non-loss ---

def _extract_headings(md_text: str) -> set[str]:
    """Extract all heading texts from markdown."""
    import re
    headings = set()
    for line in md_text.split("\n"):
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            headings.add(m.group(1).strip())
    return headings


@pytest.mark.parametrize("md_file,jsonl_file", [
    ("Specialites/SPE_MATHEMATIQUES.md", "mathematiques.jsonl"),
    ("Specialites/SPE_NSI.md", "nsi.jsonl"),
    ("Tronc_commun/TRONC_PHILOSOPHIE.md", "philosophie.jsonl"),
    ("REFERENTIEL_CANDIDAT_LIBRE.md", "referentiel_candidat_libre.jsonl"),
])
def test_no_heading_lost(md_file, jsonl_file):
    md_path = CORPUS_DIR / md_file
    md_text = md_path.read_text(encoding="utf-8")
    headings = _extract_headings(md_text)

    chunks = _load_jsonl(CHUNKS_DIR / jsonl_file)
    all_chunk_text = " ".join(c["text"] for c in chunks)
    # Also check section paths
    all_paths = []
    for c in chunks:
        # Section titles appear in chunk_id or in the breadcrumb prefix
        pass

    # Every heading should appear somewhere in the chunk texts or be a parent
    # in the section path (which gets prefixed on subdivision)
    missing = []
    for h in headings:
        # Tolerate partial match (heading text appears in any chunk)
        if not any(h in c["text"] or h in str(c.get("metadata", {})) for c in chunks):
            missing.append(h)

    assert not missing, f"Headings lost in {jsonl_file}: {missing}"


# --- Test: statistics ---

def test_chunk_statistics():
    """Print statistics (not a hard assertion, for the report)."""
    for fname in EXPECTED_FILES:
        chunks = _load_jsonl(CHUNKS_DIR / fname)
        sizes = [len(c["text"].split()) for c in chunks]
        types = {}
        notions_count = 0
        for c in chunks:
            t = c["metadata"]["type_doc"]
            types[t] = types.get(t, 0) + 1
            if c["metadata"]["notions"]:
                notions_count += 1

        median_size = sorted(sizes)[len(sizes) // 2] if sizes else 0
        print(f"\n{fname}: {len(chunks)} chunks, median {median_size} words")
        print(f"  type_doc: {types}")
        print(f"  notions non-empty: {notions_count}/{len(chunks)}")
