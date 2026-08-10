"""H2-B Coverage Report Generator.

Generates comprehensive coverage report proving:
- CORPUS_TOTAL = 2,584
- SUM(dispositions) = CORPUS_TOTAL
- Zero overlap (each object has exactly one disposition)
- Zero gap (no object without disposition)

Usage:
    python -m rag_pedago.imports.h2b_coverage_report \
        --catalog data/reports/corpus_disposition_catalog.json \
        --rights configs/rights_evidence_registry.yml \
        --pii /path/to/sealed_pii_evidence.json \
        --routing configs/corpus_zone_routing.yml \
        --golden configs/golden_corpus_h2b.yml \
        --output data/reports/h2b_coverage_report.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from rag_pedago.imports.corpus_catalog_compiler import (
    verify_catalog_evidence_bindings,
)
from rag_pedago.imports.golden_corpus_validator import (
    load_spec,
    validate_golden_corpus,
)


@dataclass
class CoverageReport:
    """H2-B coverage report."""

    report_id: str
    generated_at: str
    git_commit: str
    git_branch: str

    # Evidence provenance
    real_corpus_catalog_source: bool
    synthetic_catalog_used_for_final_gate: bool
    manifest_sha256: str

    # Corpus totals
    corpus_total_expected: int
    corpus_total_actual: int
    corpus_match: bool

    # Disposition totals
    totals: dict[str, int] = field(default_factory=dict)
    totals_sum: int = 0

    # Verification
    sum_equals_total: bool = False
    zero_overlap: bool = False
    zero_gap: bool = False
    decision_coverage_complete: bool = False
    coverage_complete: bool = False
    unclassified: int = 0
    multiple_primary_disposition: int = 0
    safety_invariants: dict[str, int] = field(default_factory=dict)
    blocked_ingest_candidates: int = 0
    mandatory_gate_blockers: dict[str, int] = field(default_factory=dict)

    # Artifact / placement integration
    content_artifact_count: int = 0
    eduscol_unique_artifacts: int = 0
    eduscol_placement_count: int = 0
    eduscol_placements_classified: int = 0
    eduscol_placements_unclassified: int = 0
    multi_placement_artifacts: int = 0

    # Gate statuses
    rights_gate_status: str = "UNKNOWN"
    pii_gate_status: str = "UNKNOWN"
    rights_evidence_bound: bool = False
    pii_evidence_bound: bool = False
    currentness_gate_status: str = "UNKNOWN"
    format_gate_status: str = "UNKNOWN"

    # Golden corpus
    golden_controls_total: int = 0
    golden_controls_passed: int = 0
    golden_controls_failed: int = 0
    golden_validation_status: str = "UNKNOWN"
    golden_validation_pass: bool = False
    h2_coverage_gate_pass: bool = False

    # Files and hashes
    input_files: dict[str, str] = field(default_factory=dict)


def _get_git_commit() -> str:
    """Get current git commit hash."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("git HEAD is not a full commit SHA")
    return commit


def _get_git_branch() -> str:
    """Get current git branch."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _file_sha256(path: Path) -> str:
    """Compute SHA256 of a file."""
    if not path.exists():
        return "file_not_found"
    sha = hashlib.sha256()
    sha.update(path.read_bytes())
    return sha.hexdigest()


def load_catalog(path: Path) -> dict[str, Any]:
    """Load corpus disposition catalog."""
    content = path.read_text(encoding="utf-8")
    return json.loads(content)


def _load_yaml_mapping(path: Path, *, label: str) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def generate_coverage_report(
    catalog_path: Path,
    rights_path: Path | None = None,
    pii_path: Path | None = None,
    routing_path: Path | None = None,
    golden_path: Path | None = None,
    expected_total: int = 2584,
    expected_manifest_sha256: str | None = None,
) -> CoverageReport:
    """Generate H2-B coverage report."""
    catalog = load_catalog(catalog_path)
    if catalog.get("catalog_kind") != "REAL_SEALED_CORPUS":
        raise ValueError("final gate requires a real sealed corpus catalog")
    manifest_sha256 = catalog.get("manifest_sha256")
    if not isinstance(manifest_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", manifest_sha256
    ) is None:
        raise ValueError("catalog manifest SHA256 is invalid")
    if (
        expected_manifest_sha256 is not None
        and manifest_sha256 != expected_manifest_sha256
    ):
        raise ValueError("catalog manifest SHA256 mismatch")
    if golden_path is None or not golden_path.is_file():
        raise ValueError("golden specification is required for the final gate")
    if rights_path is None or not rights_path.is_file():
        raise ValueError("rights evidence is required for the final gate")
    if pii_path is None or not pii_path.is_file():
        raise ValueError("PII evidence is required for the final gate")
    if routing_path is None or not routing_path.is_file():
        raise ValueError("routing policy is required for the final gate")

    # Git info
    git_commit = _get_git_commit()
    git_branch = _get_git_branch()

    # Corpus totals
    actual_total = catalog.get("physical_object_count")
    if (
        isinstance(actual_total, bool)
        or not isinstance(actual_total, int)
        or actual_total < 0
    ):
        raise ValueError("catalog physical_object_count is invalid")
    totals = catalog.get("disposition_counts", {})
    if not isinstance(totals, dict) or not all(
        isinstance(key, str)
        and key
        and not isinstance(value, bool)
        and isinstance(value, int)
        and value >= 0
        for key, value in totals.items()
    ):
        raise ValueError("catalog disposition counts are invalid")
    totals_sum = sum(totals.values())

    # Verification
    sum_equals_total = totals_sum == actual_total
    unclassified = catalog.get("unclassified")
    multiple_primary = catalog.get("multiple_primary_disposition")
    if (
        isinstance(unclassified, bool)
        or not isinstance(unclassified, int)
        or unclassified < 0
        or isinstance(multiple_primary, bool)
        or not isinstance(multiple_primary, int)
        or multiple_primary < 0
    ):
        raise ValueError("catalog classification counters are invalid")
    zero_overlap = (
        catalog.get("verification_passed") is True and multiple_primary == 0
    )
    zero_gap = sum_equals_total and unclassified == 0
    corpus_match = actual_total == expected_total

    safety_invariants = {
        "INGEST_WITHOUT_RIGHTS_CLEARANCE": 0,
        "INGEST_WITHOUT_PII_CLEARANCE": 0,
        "INGEST_WITHOUT_CURRENTNESS_CLEARANCE": 0,
        "INGEST_WITH_UNSUPPORTED_FORMAT": 0,
        "INGEST_WITHOUT_PROVENANCE": 0,
        "INGEST_WITHOUT_CONTENT_SHA": 0,
        "INGEST_WITHOUT_AUTHORITY": 0,
        "INGEST_WITHOUT_ATTRIBUTION_METADATA": 0,
    }
    physical_objects = catalog.get("physical_objects")
    if not isinstance(physical_objects, list):
        raise ValueError("real catalog must include physical objects")
    if len(physical_objects) != actual_total:
        raise ValueError("physical object list does not match reported total")
    measured_dispositions: dict[str, int] = {}
    for item in physical_objects:
        if not isinstance(item, dict):
            raise ValueError("real catalog physical object must be a mapping")
        disposition = item.get("disposition")
        if not isinstance(disposition, str) or not disposition:
            raise ValueError("real catalog physical object disposition is invalid")
        measured_dispositions[disposition] = (
            measured_dispositions.get(disposition, 0) + 1
        )
    if {
        key: value for key, value in totals.items() if value != 0
    } != measured_dispositions:
        raise ValueError("disposition_counts do not match physical objects")

    rights_registry = _load_yaml_mapping(rights_path, label="rights registry")
    routing_config = _load_yaml_mapping(routing_path, label="routing policy")
    pii_evidence = load_catalog(pii_path)
    if not isinstance(pii_evidence, dict):
        raise ValueError("PII evidence must be a mapping")
    verify_catalog_evidence_bindings(
        catalog,
        routing_config,
        rights_registry,
        pii_evidence,
    )
    blocked_ingest_candidates = 0
    mandatory_gate_blockers: dict[str, int] = {}
    for item in physical_objects:
        if not isinstance(item, dict):
            continue
        gates = item.get("gate_statuses")
        if (
            item.get("base_disposition") == "INGEST"
            and item.get("disposition") != "INGEST"
        ):
            blocked_ingest_candidates += 1
            if isinstance(gates, dict):
                for gate_name, status in gates.items():
                    if status != "PASS":
                        mandatory_gate_blockers[gate_name] = (
                            mandatory_gate_blockers.get(gate_name, 0) + 1
                        )
        if item.get("disposition") != "INGEST":
            continue
        if not isinstance(gates, dict) or gates.get("rights") != "PASS":
            safety_invariants["INGEST_WITHOUT_RIGHTS_CLEARANCE"] += 1
        if not isinstance(gates, dict) or gates.get("pii") != "PASS":
            safety_invariants["INGEST_WITHOUT_PII_CLEARANCE"] += 1
        if item.get("currentness") != "actuel":
            safety_invariants["INGEST_WITHOUT_CURRENTNESS_CLEARANCE"] += 1
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.lower().endswith(".pdf"):
            safety_invariants["INGEST_WITH_UNSUPPORTED_FORMAT"] += 1
        if item.get("provenance_status") != "VERIFIED":
            safety_invariants["INGEST_WITHOUT_PROVENANCE"] += 1
        content_sha256 = item.get("content_sha256")
        if not isinstance(content_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", content_sha256
        ) is None:
            safety_invariants["INGEST_WITHOUT_CONTENT_SHA"] += 1
        if not isinstance(gates, dict) or gates.get("authority") != "PASS":
            safety_invariants["INGEST_WITHOUT_AUTHORITY"] += 1
        attribution = item.get("attribution_metadata")
        if not isinstance(attribution, dict) or not all(
            isinstance(attribution.get(field_name), str)
            and bool(attribution.get(field_name))
            for field_name in ("source", "source_url")
        ):
            safety_invariants["INGEST_WITHOUT_ATTRIBUTION_METADATA"] += 1

    # Input files
    input_files = {
        "catalog": _file_sha256(catalog_path),
        "pii": _file_sha256(pii_path),
        "rights": _file_sha256(rights_path),
        "routing": _file_sha256(routing_path),
    }

    # Rights gate
    rights_gate_status = (
        "PASS"
        if safety_invariants["INGEST_WITHOUT_RIGHTS_CLEARANCE"] == 0
        else "BLOCKED_INGEST_WITHOUT_CLEARANCE"
    )
    pii_gate_status = (
        "PASS"
        if safety_invariants["INGEST_WITHOUT_PII_CLEARANCE"] == 0
        else "BLOCKED_INGEST_WITHOUT_CLEARANCE"
    )

    # Currentness gate (derived from catalog)
    if safety_invariants["INGEST_WITHOUT_CURRENTNESS_CLEARANCE"] == 0:
        currentness_gate_status = "PASS"
    else:
        currentness_gate_status = "BLOCKED_INGEST_WITHOUT_CURRENTNESS"

    # Format gate (derived from catalog)
    unsupported = totals.get("UNSUPPORTED", 0)
    if safety_invariants["INGEST_WITH_UNSUPPORTED_FORMAT"] == 0:
        format_gate_status = f"PASS_WITH_{unsupported}_UNSUPPORTED"
    else:
        format_gate_status = f"CHECK_{unsupported}_UNSUPPORTED"

    # Golden corpus — the final gate executes the validator on this exact catalog.
    golden = load_spec(golden_path)
    golden_report = validate_golden_corpus(
        golden,
        catalog,
        golden_path,
        catalog_path,
    )
    golden_total = golden_report.total_controls
    golden_passed = golden_report.passed_controls
    golden_failed = golden_report.failed_controls
    golden_pass = golden_report.validation_passed
    golden_status = "PASS" if golden_pass else "FAIL"
    input_files["golden"] = _file_sha256(golden_path)

    decision_coverage_complete = (
        sum_equals_total
        and zero_overlap
        and zero_gap
        and corpus_match
    )
    h2_coverage_gate_pass = (
        decision_coverage_complete
        and golden_pass
        and rights_gate_status == "PASS"
        and pii_gate_status == "PASS"
        and all(value == 0 for value in safety_invariants.values())
    )

    return CoverageReport(
        report_id=f"h2b_coverage_{git_commit}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        generated_at=datetime.now(UTC).isoformat(),
        git_commit=git_commit,
        git_branch=git_branch,
        real_corpus_catalog_source=True,
        synthetic_catalog_used_for_final_gate=False,
        manifest_sha256=manifest_sha256,
        corpus_total_expected=expected_total,
        corpus_total_actual=actual_total,
        corpus_match=corpus_match,
        totals=totals,
        totals_sum=totals_sum,
        sum_equals_total=sum_equals_total,
        zero_overlap=zero_overlap,
        zero_gap=zero_gap,
        decision_coverage_complete=decision_coverage_complete,
        coverage_complete=h2_coverage_gate_pass,
        unclassified=unclassified,
        multiple_primary_disposition=multiple_primary,
        safety_invariants=safety_invariants,
        blocked_ingest_candidates=blocked_ingest_candidates,
        mandatory_gate_blockers=dict(sorted(mandatory_gate_blockers.items())),
        content_artifact_count=catalog.get("content_artifact_count", 0),
        eduscol_unique_artifacts=catalog.get("eduscol_unique_artifacts", 0),
        eduscol_placement_count=catalog.get("eduscol_placement_count", 0),
        eduscol_placements_classified=catalog.get(
            "eduscol_placements_classified", 0
        ),
        eduscol_placements_unclassified=catalog.get(
            "eduscol_placements_unclassified", 0
        ),
        multi_placement_artifacts=catalog.get("multi_placement_artifacts", 0),
        rights_gate_status=rights_gate_status,
        pii_gate_status=pii_gate_status,
        rights_evidence_bound=True,
        pii_evidence_bound=True,
        currentness_gate_status=currentness_gate_status,
        format_gate_status=format_gate_status,
        golden_controls_total=golden_total,
        golden_controls_passed=golden_passed,
        golden_controls_failed=golden_failed,
        golden_validation_status=golden_status,
        golden_validation_pass=golden_pass,
        h2_coverage_gate_pass=h2_coverage_gate_pass,
        input_files=input_files,
    )


def render_markdown(report: CoverageReport) -> str:
    """Render coverage report as Markdown."""
    lines = [
        "# H2-B CORPUS COVERAGE REPORT",
        "",
        f"**Report ID**: `{report.report_id}`",
        f"**Generated**: {report.generated_at}",
        f"**Git Commit**: `{report.git_commit}`",
        f"**Git Branch**: `{report.git_branch}`",
        "",
        f"REAL_CORPUS_CATALOG_SOURCE={'true' if report.real_corpus_catalog_source else 'false'}",
        "SYNTHETIC_CATALOG_USED_FOR_FINAL_GATE="
        f"{'true' if report.synthetic_catalog_used_for_final_gate else 'false'}",
        f"CORPUS_MANIFEST_SHA256={report.manifest_sha256}",
        "",
        "---",
        "",
        "## 1. CORPUS TOTALS",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Expected total | {report.corpus_total_expected:,} |",
        f"| Actual total | {report.corpus_total_actual:,} |",
        f"| **Match** | **{'YES' if report.corpus_match else 'NO'}** |",
        "",
        "---",
        "",
        "## 2. DISPOSITION BREAKDOWN",
        "",
        "| Disposition | Count | Percentage |",
        "|-------------|-------|------------|",
    ]

    total = report.totals_sum or 1  # Avoid division by zero
    for disposition, count in sorted(report.totals.items()):
        pct = count / total * 100
        lines.append(f"| {disposition} | {count:,} | {pct:.1f}% |")

    lines.extend([
        f"| **SUM** | **{report.totals_sum:,}** | **100.0%** |",
        "",
        "---",
        "",
        "## 3. COVERAGE VERIFICATION",
        "",
        "| Check | Status |",
        "|-------|--------|",
        f"| SUM(dispositions) = corpus_total | **{'PASS' if report.sum_equals_total else 'FAIL'}** |",
        f"| Zero overlap (no duplicate SHA256) | **{'PASS' if report.zero_overlap else 'FAIL'}** |",
        f"| Zero gap (all objects assigned) | **{'PASS' if report.zero_gap else 'FAIL'}** |",
        f"| Corpus total matches expected | **{'PASS' if report.corpus_match else 'FAIL'}** |",
        f"| Unclassified objects | **{report.unclassified}** |",
        f"| Multiple primary dispositions | **{report.multiple_primary_disposition}** |",
        f"| Blocked ingest candidates | **{report.blocked_ingest_candidates}** |",
        f"| Decision coverage complete | **{'PASS' if report.decision_coverage_complete else 'FAIL'}** |",
        f"| Golden validation | **{'PASS' if report.golden_validation_pass else 'FAIL'}** |",
        f"| H2 coverage gate | **{'PASS' if report.h2_coverage_gate_pass else 'FAIL'}** |",
        "",
        f"BLOCKED_INGEST_CANDIDATES={report.blocked_ingest_candidates}",
        "DECISION_COVERAGE_COMPLETE="
        f"{'true' if report.decision_coverage_complete else 'false'}",
        "GOLDEN_VALIDATION_PASS="
        f"{'true' if report.golden_validation_pass else 'false'}",
        "H2_COVERAGE_GATE_PASS="
        f"{'true' if report.h2_coverage_gate_pass else 'false'}",
        "",
        f"**COVERAGE_COMPLETE = {'TRUE' if report.coverage_complete else 'FALSE'}**",
        "",
        "---",
        "",
        "## 4. INGEST SAFETY INVARIANTS",
        "",
        "| Invariant | Count |",
        "|-----------|-------|",
    ])

    for invariant, count in report.safety_invariants.items():
        lines.append(f"| {invariant} | {count} |")

    lines.extend([
        "",
        "---",
        "",
        "## 5. GATE STATUSES",
        "",
        "| Gate | Status |",
        "|------|--------|",
        f"| Rights evidence | `{report.rights_gate_status}` |",
        f"| PII content scan | `{report.pii_gate_status}` |",
        f"| Rights evidence bound | `{'PASS' if report.rights_evidence_bound else 'FAIL'}` |",
        f"| PII evidence bound | `{'PASS' if report.pii_evidence_bound else 'FAIL'}` |",
        f"| Currentness classification | `{report.currentness_gate_status}` |",
        f"| Format support | `{report.format_gate_status}` |",
        "",
        "---",
        "",
        "## 6. GOLDEN CORPUS VALIDATION",
        "",
        f"- Total controls: {report.golden_controls_total}",
        f"- Passed controls: {report.golden_controls_passed}",
        f"- Failed controls: {report.golden_controls_failed}",
        f"- Status: `{report.golden_validation_status}`",
        "",
        "---",
        "",
        "## 7. INPUT FILE HASHES",
        "",
        "| File | SHA256 |",
        "|------|--------|",
    ])

    for name, sha in sorted(report.input_files.items()):
        lines.append(f"| {name} | `{sha}` |")

    lines.extend([
        "",
        "---",
        "",
        "## 8. BLOCKING ITEMS FOR GO-LIVE",
        "",
    ])

    blocking = []
    if report.rights_gate_status != "PASS":
        blocking.append(f"- Rights gate: `{report.rights_gate_status}`")
    if "BLOCKED" in report.pii_gate_status:
        blocking.append(f"- PII gate: `{report.pii_gate_status}`")
    if "INCOMPLETE" in report.currentness_gate_status:
        blocking.append(f"- Currentness gate: `{report.currentness_gate_status}`")
    if not report.corpus_match:
        blocking.append(f"- Corpus total mismatch: {report.corpus_total_actual} vs {report.corpus_total_expected}")
    if report.blocked_ingest_candidates:
        blocking.append(
            f"- Blocked ingest candidates: {report.blocked_ingest_candidates} "
            f"({report.mandatory_gate_blockers})"
        )
    for invariant, count in report.safety_invariants.items():
        if count:
            blocking.append(f"- {invariant}: {count}")
    if not report.golden_validation_pass:
        blocking.append(
            f"- Golden validation: {report.golden_controls_failed} failed controls"
        )

    if blocking:
        lines.extend(blocking)
    else:
        lines.append("None — all gates pass.")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate H2-B coverage report."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Path to corpus disposition catalog (JSON)",
    )
    parser.add_argument(
        "--rights",
        type=Path,
        required=True,
        help="Path to rights evidence registry (YAML)",
    )
    parser.add_argument(
        "--pii",
        type=Path,
        required=True,
        help="Path to sealed PII evidence (JSON)",
    )
    parser.add_argument(
        "--routing",
        type=Path,
        required=True,
        help="Path to independent corpus routing policy (YAML)",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        help="Path to golden corpus specification (YAML)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for Markdown report",
    )
    parser.add_argument(
        "--expected-total",
        type=int,
        default=2584,
        help="Expected corpus total",
    )
    parser.add_argument(
        "--expected-manifest-sha256",
        help="Expected sealed SHA256SUMS digest",
    )
    args = parser.parse_args()

    report = generate_coverage_report(
        catalog_path=args.catalog,
        rights_path=args.rights,
        pii_path=args.pii,
        routing_path=args.routing,
        golden_path=args.golden,
        expected_total=args.expected_total,
        expected_manifest_sha256=args.expected_manifest_sha256,
    )

    markdown = render_markdown(report)
    print(markdown)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(f"\nReport written to: {args.output}")

    return 0 if report.coverage_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
