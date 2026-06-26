"""Tests for index_pgvector — gating."""
from __future__ import annotations

import importlib.util
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
