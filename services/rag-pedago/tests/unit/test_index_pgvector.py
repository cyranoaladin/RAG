"""Tests for index_pgvector — gating + manifest admission (production code)."""
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
    module = _load_module()
    contract = tmp_path / "c.yml"
    contract.write_text("ingestion_allowed: false\n", encoding="utf-8")
    assert module.check_ingestion_allowed(contract) is False


def test_gate_allows_when_true(tmp_path) -> None:
    module = _load_module()
    contract = tmp_path / "c.yml"
    contract.write_text("ingestion_allowed: true\n", encoding="utf-8")
    assert module.check_ingestion_allowed(contract) is True


def test_gate_blocks_on_empty(tmp_path) -> None:
    module = _load_module()
    contract = tmp_path / "c.yml"
    contract.write_text("", encoding="utf-8")
    assert module.check_ingestion_allowed(contract) is False


def test_gate_blocks_on_malformed(tmp_path) -> None:
    module = _load_module()
    contract = tmp_path / "c.yml"
    contract.write_text("{broken: [", encoding="utf-8")
    assert module.check_ingestion_allowed(contract) is False


def test_gate_blocks_on_missing(tmp_path) -> None:
    module = _load_module()
    assert module.check_ingestion_allowed(tmp_path / "x.yml") is False


# --- is_admitted (calls production function, mutation-proof) ---

def test_admitted_when_listed_and_sha_matches() -> None:
    module = _load_module()
    manifest = {"chunk_A#0": "sha_correct"}
    admitted, reason = module.is_admitted("chunk_A#0", "sha_correct", manifest)
    assert admitted is True
    assert reason == "ok"


def test_rejected_when_not_in_manifest() -> None:
    module = _load_module()
    manifest = {"chunk_A#0": "sha_a"}
    admitted, reason = module.is_admitted("chunk_B#0", "sha_b", manifest)
    assert admitted is False
    assert reason == "not_in_manifest"


def test_rejected_when_sha_mismatch() -> None:
    module = _load_module()
    manifest = {"chunk_A#0": "correct_sha"}
    admitted, reason = module.is_admitted("chunk_A#0", "wrong_sha", manifest)
    assert admitted is False
    assert reason == "sha_mismatch"


# --- load_review_manifest ---

def test_manifest_loads_correctly(tmp_path) -> None:
    module = _load_module()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "approved_count": 2, "rejected_count": 0,
        "approved": [
            {"chunk_id": "c1", "chunk_sha256": "s1"},
            {"chunk_id": "c2", "chunk_sha256": "s2"},
        ],
        "rejected": [],
    }), encoding="utf-8")
    assert module.load_review_manifest(path) == {"c1": "s1", "c2": "s2"}


def test_manifest_empty_blocks(tmp_path) -> None:
    module = _load_module()
    assert module.load_review_manifest(tmp_path / "missing.json") == {}
