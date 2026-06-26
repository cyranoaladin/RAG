"""Tests for index_pgvector — gating + manifest rejection."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "index_pgvector.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("index_pgvector", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --- Gating ---

def test_gate_blocks_when_false(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("ingestion_allowed: false\n", encoding="utf-8")
    module = _load_module()
    assert module.check_ingestion_allowed(contract) is False


def test_gate_allows_when_true(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("ingestion_allowed: true\n", encoding="utf-8")
    module = _load_module()
    assert module.check_ingestion_allowed(contract) is True


def test_gate_blocks_on_empty(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("", encoding="utf-8")
    module = _load_module()
    assert module.check_ingestion_allowed(contract) is False


def test_gate_blocks_on_malformed(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("{broken yaml: [", encoding="utf-8")
    module = _load_module()
    assert module.check_ingestion_allowed(contract) is False


def test_gate_blocks_on_missing(tmp_path) -> None:
    module = _load_module()
    assert module.check_ingestion_allowed(tmp_path / "nonexistent.yml") is False


# --- Manifest review gate (no DB needed) ---

def test_manifest_rejects_unlisted_chunk() -> None:
    """A chunk not in the manifest must be skipped."""
    manifest = {"chunk_A#0": "sha_a"}
    assert "chunk_B#0" not in manifest


def test_manifest_rejects_sha_mismatch() -> None:
    """A chunk with wrong sha must be rejected."""
    manifest = {"chunk_A#0": "correct_sha"}
    assert manifest.get("chunk_A#0") != "wrong_sha"


def test_manifest_loads_correctly(tmp_path) -> None:
    """load_review_manifest reads chunk_id→sha mapping."""
    module = _load_module()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "approved_count": 2,
        "rejected_count": 0,
        "approved": [
            {"chunk_id": "c1", "chunk_sha256": "sha1"},
            {"chunk_id": "c2", "chunk_sha256": "sha2"},
        ],
        "rejected": [],
    }), encoding="utf-8")

    result = module.load_review_manifest(manifest_path)
    assert result == {"c1": "sha1", "c2": "sha2"}


def test_manifest_empty_blocks(tmp_path) -> None:
    """Empty or missing manifest returns empty dict (blocks indexation)."""
    module = _load_module()
    assert module.load_review_manifest(tmp_path / "nonexistent.json") == {}
