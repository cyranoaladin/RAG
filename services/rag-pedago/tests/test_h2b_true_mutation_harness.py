"""Le harnais H2-B doit prouver ses propres mutations, jamais les déclarer."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "services" / "rag-pedago" / "scripts" / "h2b_true_mutation_harness.py"


def _module():
    spec = importlib.util.spec_from_file_location("h2b_true_mutation_harness", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matrix_has_the_exact_twelve_required_guards() -> None:
    module = _module()
    assert [check.number for check in module.CHECKS] == list(range(1, 13))
    assert [check.invariant for check in module.CHECKS] == [
        "rights",
        "PII",
        "currentness",
        "exclusion",
        "unsupported format",
        "unknown object",
        "content SHA",
        "manifest",
        "scope authority",
        "revocation",
        "extraction failure",
        "single primary disposition",
    ]


def test_every_mutation_anchor_is_exact_and_every_failure_reason_is_named() -> None:
    module = _module()
    for check in module.CHECKS:
        assert check.expected_failure_contains
        assert check.test
        assert check.mutations
        for mutation in check.mutations:
            assert mutation.path.is_file()
            assert mutation.path.resolve().is_relative_to(ROOT.resolve())
            source = mutation.path.read_text(encoding="utf-8")
            assert source.count(mutation.old) == 1
            assert mutation.old != mutation.new


def test_report_contract_contains_non_vacuity_and_restore_proofs() -> None:
    module = _module()
    expected = {
        "BASELINE_GREEN",
        "MUTATION_APPLIED",
        "TARGET_TEST",
        "MUTANT_RED",
        "EXPECTED_FAILURE",
        "ACTUAL_FAILURE",
        "DIRECT_CAUSE",
        "MASKED_BY_OTHER_GUARD",
        "RESTORED_BYTES",
        "RESTORED_GREEN",
        "NON_VACUOUS",
    }
    assert set(module.REPORT_FIELDS) == expected
