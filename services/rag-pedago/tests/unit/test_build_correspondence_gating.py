"""Tests for build_correspondence gating — non-regression of parsing governance."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_correspondence.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_correspondence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gate_blocks_when_pdf_not_allowed(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("pdf_allowed: false\nparsing_allowed: true\n", encoding="utf-8")
    module = _load_module()
    assert module.check_parsing_allowed(contract) is False


def test_gate_blocks_when_parsing_not_allowed(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("pdf_allowed: true\nparsing_allowed: false\n", encoding="utf-8")
    module = _load_module()
    assert module.check_parsing_allowed(contract) is False


def test_gate_allows_when_both_true(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("pdf_allowed: true\nparsing_allowed: true\n", encoding="utf-8")
    module = _load_module()
    assert module.check_parsing_allowed(contract) is True


def test_gate_blocks_on_empty_contract(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("", encoding="utf-8")
    module = _load_module()
    assert module.check_parsing_allowed(contract) is False


def test_gate_blocks_on_nondict_contract(tmp_path) -> None:
    contract = tmp_path / "contract.yml"
    contract.write_text("- item1\n- item2\n", encoding="utf-8")
    module = _load_module()
    assert module.check_parsing_allowed(contract) is False


def test_gate_blocks_on_missing_contract(tmp_path) -> None:
    missing = tmp_path / "nonexistent.yml"
    module = _load_module()
    assert module.check_parsing_allowed(missing) is False
