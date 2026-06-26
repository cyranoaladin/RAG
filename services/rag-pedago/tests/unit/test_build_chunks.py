"""Tests for build_chunks — gating + contract conformity."""
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


# --- Contract conformity tests (model_validate) ---

def _load_all_chunks() -> list[dict]:
    chunks = []
    for jsonl in sorted(CHUNKS_DIR.rglob("*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def _load_all_sidecars() -> list[dict]:
    sidecars = []
    for meta in sorted(CHUNKS_DIR.rglob("*.meta.json")):
        sidecars.append(json.loads(meta.read_text(encoding="utf-8")))
    return sidecars


@pytest.fixture(scope="module")
def all_chunks():
    return _load_all_chunks()


@pytest.fixture(scope="module")
def all_sidecars():
    return _load_all_sidecars()


def test_chunks_exist(all_chunks) -> None:
    assert len(all_chunks) > 0


def test_all_chunks_validate_chunkmeta(all_chunks) -> None:
    """Every JSONL line must pass ChunkMeta.model_validate (not just field presence)."""
    from nexus_contracts.document import ChunkMeta
    for i, chunk in enumerate(all_chunks):
        try:
            ChunkMeta.model_validate(chunk)
        except Exception as e:
            pytest.fail(f"Chunk {i} ({chunk.get('chunk_id', '?')}): ChunkMeta validation failed: {e}")


def test_all_sidecars_validate_chunkmetadata(all_sidecars) -> None:
    """Every .meta.json must pass ChunkMetadata.model_validate."""
    from nexus_contracts.chunk import ChunkMetadata
    for i, sidecar in enumerate(all_sidecars):
        try:
            ChunkMetadata.model_validate(sidecar)
        except Exception as e:
            pytest.fail(f"Sidecar {i}: ChunkMetadata validation failed: {e}")


def test_no_trivial_chunks(all_chunks) -> None:
    for i, chunk in enumerate(all_chunks):
        text = chunk.get("text", "")
        assert len(text) >= 50, f"Chunk {i} too short: {len(text)} chars"


def test_no_chrome_in_chunks(all_chunks) -> None:
    from scrapers.fetch import quality_check
    for i, chunk in enumerate(all_chunks):
        notion = chunk.get("notions", [""])[0]
        qc = quality_check(chunk["text"], notion)
        assert not qc["navigation_suspected"], (
            f"Chunk {i} ({chunk.get('chunk_id')}): chrome detected: {qc['issues']}"
        )


def test_chunks_deterministic() -> None:
    chunks1 = _load_all_chunks()
    chunks2 = _load_all_chunks()
    assert len(chunks1) == len(chunks2)
    for c1, c2 in zip(chunks1, chunks2, strict=True):
        assert c1 == c2


def test_multi_niveau_no_collision(tmp_path) -> None:
    """Same matiere+notion on two niveaux must produce two distinct files."""
    module = _load_module()

    staging = tmp_path / "staging"
    for niveau in ["premiere", "terminale"]:
        d = staging / niveau / "mathematiques"
        d.mkdir(parents=True)
        (d / "mathematiques_suites.json").write_text(json.dumps({
            "notion_id": "suites", "matiere": "mathematiques", "niveau": niveau,
            "voie": "generale", "statut_enseignement": "specialite",
            "audience": "tous", "source": "wikipedia", "source_label": f"wp_{niveau}",
            "rights": "CC-BY-SA 4.0", "chosen_url": f"https://example.com/{niveau}",
            "text": f"Les suites en {niveau}. " * 50,
        }), encoding="utf-8")

    chunks_dir = tmp_path / "chunks"
    # Patch paths
    orig_staging = module.STAGING_DIR
    orig_chunks = module.CHUNKS_DIR
    module.STAGING_DIR = staging
    module.CHUNKS_DIR = chunks_dir
    try:
        module.main()
    finally:
        module.STAGING_DIR = orig_staging
        module.CHUNKS_DIR = orig_chunks

    # Two distinct files
    premiere_file = chunks_dir / "premiere" / "mathematiques_suites.jsonl"
    terminale_file = chunks_dir / "terminale" / "mathematiques_suites.jsonl"
    assert premiere_file.is_file(), "Missing premiere chunks file"
    assert terminale_file.is_file(), "Missing terminale chunks file"

    # doc_id and chunk_id must differ
    p_chunk = json.loads(premiere_file.read_text().strip().split("\n")[0])
    t_chunk = json.loads(terminale_file.read_text().strip().split("\n")[0])
    assert p_chunk["doc_id"] != t_chunk["doc_id"]
    assert p_chunk["chunk_id"] != t_chunk["chunk_id"]
    assert "premiere" in p_chunk["doc_id"]
    assert "terminale" in t_chunk["doc_id"]


def test_sidecars_have_retrieval_fields(all_sidecars) -> None:
    """Sidecars must carry tenant/niveau/voie/audience/matiere for retrieval filtering."""
    for i, sc in enumerate(all_sidecars):
        assert sc.get("tenant"), f"Sidecar {i} missing tenant"
        assert sc.get("niveau"), f"Sidecar {i} missing niveau"
        assert sc.get("voie"), f"Sidecar {i} missing voie"
        assert sc.get("audience"), f"Sidecar {i} missing audience"
        assert sc.get("matiere"), f"Sidecar {i} missing matiere"
