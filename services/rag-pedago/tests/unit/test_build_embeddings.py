"""Tests for build_embeddings — gating + artefact quality."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_embeddings.py"
EMBEDDINGS_DIR = Path(__file__).resolve().parents[2] / "data" / "embeddings"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_embeddings", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- Gating ---

def test_gate_blocks_when_false(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("embeddings_allowed: false\n", encoding="utf-8")
    module = _load_module()
    assert module.check_embeddings_allowed(contract) is False


def test_gate_allows_when_true(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("embeddings_allowed: true\n", encoding="utf-8")
    module = _load_module()
    assert module.check_embeddings_allowed(contract) is True


def test_gate_blocks_on_empty(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("", encoding="utf-8")
    module = _load_module()
    assert module.check_embeddings_allowed(contract) is False


def test_gate_blocks_on_malformed(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("{invalid yaml: [", encoding="utf-8")
    module = _load_module()
    assert module.check_embeddings_allowed(contract) is False


def test_gate_blocks_on_missing(tmp_path) -> None:
    module = _load_module()
    assert module.check_embeddings_allowed(tmp_path / "nonexistent.yml") is False


# --- Artefact quality (only if embeddings have been computed) ---

def _load_all_embeddings() -> list[dict]:
    entries = []
    for jsonl in sorted(EMBEDDINGS_DIR.rglob("*.jsonl")):
        for line in jsonl.read_text(encoding="utf-8").strip().split("\n"):
            if line.strip():
                entries.append(json.loads(line))
    return entries


def test_embedding_artefacts_exist() -> None:
    """Skip if no embeddings computed yet."""
    entries = _load_all_embeddings()
    if not entries:
        import pytest
        pytest.skip("No embeddings computed yet")
    assert len(entries) > 0


def test_dimension_consistent() -> None:
    entries = _load_all_embeddings()
    if not entries:
        import pytest
        pytest.skip("No embeddings")
    dims = {e["dim"] for e in entries}
    assert len(dims) == 1, f"Multiple dimensions: {dims}"


def test_no_null_nan_vectors() -> None:
    import math
    entries = _load_all_embeddings()
    if not entries:
        import pytest
        pytest.skip("No embeddings")
    for e in entries:
        v = e["vector"]
        assert len(v) > 0
        assert not any(math.isnan(x) or math.isinf(x) for x in v)
        assert any(x != 0 for x in v)


def test_model_change_forces_full_recompute(tmp_path) -> None:
    """Changing MODEL_NAME must invalidate the cache (0 skip)."""
    module = _load_module()

    # Create a fake embedding file with a different model
    emb_file = tmp_path / "test.jsonl"
    emb_file.write_text(json.dumps({
        "chunk_id": "test#0", "doc_id": "test",
        "chunk_sha256": "abc123",
        "dim": 1024, "vector": [0.1] * 1024,
        "model": "DIFFERENT_MODEL",
        "niveau": "terminale", "voie": "generale",
        "audience": ["tous"], "matiere": "test", "notions": ["test"],
    }) + "\n", encoding="utf-8")

    existing = module._load_existing_embeddings(emb_file)
    entry = existing.get("test#0")
    assert entry is not None
    # _can_reuse must return False (different model)
    assert module._can_reuse(entry) is False


def test_filtering_metadata_present() -> None:
    entries = _load_all_embeddings()
    if not entries:
        import pytest
        pytest.skip("No embeddings")
    for e in entries:
        assert e.get("niveau"), f"Missing niveau on {e['chunk_id']}"
        assert e.get("matiere"), f"Missing matiere on {e['chunk_id']}"
        assert "audience" in e, f"Missing audience on {e['chunk_id']}"
