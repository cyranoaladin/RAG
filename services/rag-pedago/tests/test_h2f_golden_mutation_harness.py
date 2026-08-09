"""Meta-tests for the dedicated H2-F golden-gate mutation proof."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "services"
    / "rag-pedago"
    / "scripts"
    / "h2f_golden_mutation_harness.py"
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "h2f_golden_mutation_harness",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_golden_mutation_targets_the_actual_coverage_decision() -> None:
    module = _module()

    assert module.TARGET.is_file()
    source = module.TARGET.read_text(encoding="utf-8")
    assert source.count(module.ORIGINAL_GUARD) == 1
    assert module.ORIGINAL_GUARD != module.MUTATED_GUARD
    assert module.TARGET_TEST.endswith(
        "::test_perfect_counts_with_one_golden_failure_keep_coverage_red"
    )


def test_golden_mutation_report_contract_is_non_vacuous() -> None:
    module = _module()

    assert set(module.REPORT_FIELDS) == {
        "GOLDEN_BASELINE_GREEN",
        "GOLDEN_MUTATION_APPLIED",
        "GOLDEN_MUTANT_RED",
        "GOLDEN_DIRECT_FAILURE_CAUSE",
        "GOLDEN_RESTORED_BYTES",
        "GOLDEN_RESTORED_GREEN",
        "GOLDEN_GATE_NON_VACUOUS",
    }
