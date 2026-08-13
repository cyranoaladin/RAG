#!/usr/bin/env python3
"""Prove that the H2-F coverage gate consumes the real golden verdict."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PEDAGO_ROOT = REPO_ROOT / "services" / "rag-pedago"
TARGET = PEDAGO_ROOT / "rag_pedago" / "imports" / "h2b_coverage_report.py"
TARGET_TEST = (
    "tests/test_h2f_golden_final_gate.py"
    "::test_perfect_counts_with_one_golden_failure_keep_coverage_red"
)
ORIGINAL_GUARD = "    golden_pass = golden_report.validation_passed"
MUTATED_GUARD = "    golden_pass = True  # MUT-H2F-GOLDEN-01"
EXPECTED_FAILURE = "assert True is False"
REPORT_FIELDS = (
    "GOLDEN_BASELINE_GREEN",
    "GOLDEN_MUTATION_APPLIED",
    "GOLDEN_MUTANT_RED",
    "GOLDEN_DIRECT_FAILURE_CAUSE",
    "GOLDEN_RESTORED_BYTES",
    "GOLDEN_RESTORED_GREEN",
    "GOLDEN_GATE_NON_VACUOUS",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _run_target() -> tuple[bool, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-x", TARGET_TEST],
        cwd=PEDAGO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    return completed.returncode == 0, completed.stdout + completed.stderr


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def run_mutation() -> dict[str, object]:
    baseline_green, _ = _run_target()
    original = TARGET.read_bytes()
    original_guard = ORIGINAL_GUARD.encode()
    if original.count(original_guard) != 1:
        raise RuntimeError("GOLDEN_MUTATION_ANCHOR_LOST")

    mutant_green = True
    mutant_output = ""
    mutation_applied = False
    try:
        TARGET.write_bytes(
            original.replace(original_guard, MUTATED_GUARD.encode())
        )
        mutation_applied = True
        mutant_green, mutant_output = _run_target()
    finally:
        TARGET.write_bytes(original)

    restored_bytes = TARGET.read_bytes() == original
    restored_green, _ = _run_target()
    direct_cause = EXPECTED_FAILURE in mutant_output
    non_vacuous = all(
        (
            baseline_green,
            mutation_applied,
            not mutant_green,
            direct_cause,
            restored_bytes,
            restored_green,
        )
    )
    return {
        "evidence_kind": "H2F_GOLDEN_GATE_TRUE_MUTATION",
        "git_head": _git_head(),
        "target": str(TARGET.relative_to(REPO_ROOT)),
        "target_test": TARGET_TEST,
        "original_sha256": _sha256(original),
        "GOLDEN_BASELINE_GREEN": baseline_green,
        "GOLDEN_MUTATION_APPLIED": mutation_applied,
        "GOLDEN_MUTANT_RED": not mutant_green,
        "GOLDEN_DIRECT_FAILURE_CAUSE": direct_cause,
        "GOLDEN_RESTORED_BYTES": restored_bytes,
        "GOLDEN_RESTORED_GREEN": restored_green,
        "GOLDEN_GATE_NON_VACUOUS": non_vacuous,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = run_mutation()
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report.with_suffix(args.report.suffix + ".tmp")
        temporary.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.report)
    for field_name in REPORT_FIELDS:
        print(f"{field_name}={str(result[field_name]).lower()}")
    return 0 if result["GOLDEN_GATE_NON_VACUOUS"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
