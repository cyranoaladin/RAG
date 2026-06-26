"""Tests for build_chunks — gating + chunk quality."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_chunks.py"
CHUNKS_DIR = Path(__file__).resolve().parents[2] / "data" / "chunks"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_chunks", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- Gating tests ---

def test_gate_blocks_when_chunking_false(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("chunking_allowed: false\n", encoding="utf-8")
    module = _load_module()
    assert module.check_chunking_allowed(contract) is False


def test_gate_allows_when_chunking_true(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("chunking_allowed: true\n", encoding="utf-8")
    module = _load_module()
    assert module.check_chunking_allowed(contract) is True


def test_gate_blocks_on_empty_contract(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("", encoding="utf-8")
    module = _load_module()
    assert module.check_chunking_allowed(contract) is False


def test_gate_blocks_on_missing_contract(tmp_path) -> None:
    module = _load_module()
    assert module.check_chunking_allowed(tmp_path / "nonexistent.yml") is False


# --- Chunk quality tests (on real artefacts) ---

def _load_all_chunks() -> list[dict]:
    chunks = []
    for jsonl in sorted(CHUNKS_DIR.glob("*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


@pytest.fixture(scope="module")
def all_chunks():
    return _load_all_chunks()


def test_chunks_exist(all_chunks) -> None:
    assert len(all_chunks) > 0, "No chunks produced"


def test_all_chunks_have_required_metadata(all_chunks) -> None:
    required = {"notion_id", "matiere", "niveau", "voie", "statut_enseignement",
                "audience", "source", "rights", "chunk_index", "chunk_total"}
    for i, chunk in enumerate(all_chunks):
        missing = required - set(chunk.keys())
        assert not missing, f"Chunk {i} missing keys: {missing}"


def test_no_trivial_chunks(all_chunks) -> None:
    for i, chunk in enumerate(all_chunks):
        assert len(chunk["text"]) >= 50, f"Chunk {i} too short: {len(chunk['text'])} chars"


def test_no_chrome_in_chunks(all_chunks) -> None:
    from scrapers.fetch import quality_check
    for i, chunk in enumerate(all_chunks):
        qc = quality_check(chunk["text"], chunk["notion_id"])
        assert not qc["navigation_suspected"], (
            f"Chunk {i} ({chunk['notion_id']}) has chrome: {qc['issues']}"
        )


def test_chunks_deterministic() -> None:
    """Two loads of the same JSONL files produce identical chunks."""
    chunks1 = _load_all_chunks()
    chunks2 = _load_all_chunks()
    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2, strict=True):
        assert c1 == c2
