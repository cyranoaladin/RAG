"""Currentness Classification Gate — H2-B.

Classifies corpus documents by regulatory currentness.
Only 'actuel' documents are eligible for INGEST.

Currentness values:
- actuel: Currently in force (programme version valid)
- transition: May be superseded or still valid (requires verification)
- a_verifier: Regulatory status unknown (requires investigation)
- archive: Superseded by newer programme version
- conflict: Conflicting status indicators (requires human resolution)
- unclassified: Path doesn't match known currentness zone

Usage:
    python -m rag_pedago.imports.currentness_gate \
        --manifest data/corpus/eduscol_catalog.tsv \
        --config configs/corpus_zone_routing.yml
"""
from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class Currentness(StrEnum):
    """Document regulatory currentness."""

    ACTUEL = "actuel"
    TRANSITION = "transition"
    A_VERIFIER = "a_verifier"
    ARCHIVE = "archive"
    CONFLICT = "conflict"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class CurrentnessClassification:
    """Classification result for a document."""

    sha256: str
    path: str
    currentness: Currentness
    ingest_eligible: bool
    disposition_recommendation: str


@dataclass
class CurrentnessGateReport:
    """Currentness gate evaluation report."""

    manifest_path: str
    config_id: str
    evaluated_at: str
    total_documents: int
    ingest_eligible_count: int
    review_required_count: int
    archive_count: int
    gate_passed: bool
    gate_status: str
    by_currentness: dict[str, int] = field(default_factory=dict)
    classifications: list[CurrentnessClassification] = field(default_factory=list)
    coverage_complete: bool = True
    unclassified_count: int = 0
    manifest_rows: int = 0
    eduscol_manifest_rows: int = 0
    malformed_manifest_rows: int = 0
    skipped_eduscol_rows: int = 0
    manifest_schema_valid: bool = False


def _extract_currentness_from_path(path: str, config: dict[str, Any]) -> Currentness:
    """Extract currentness from path using zone routing rules."""
    zone_rules = config.get("zone_rules", [])

    for rule in zone_rules:
        zone_prefix = rule.get("zone_prefix", "")
        if not path.startswith(zone_prefix):
            continue

        sub_zone_routing = rule.get("sub_zone_routing")
        if sub_zone_routing:
            for sub_rule in sub_zone_routing:
                sub_zone_suffix = sub_rule.get("sub_zone_suffix")
                if sub_zone_suffix and sub_zone_suffix in path:
                    currentness_str = sub_rule.get("currentness")
                    if currentness_str:
                        try:
                            return Currentness(currentness_str)
                        except ValueError:
                            pass

    return Currentness.UNCLASSIFIED


def _currentness_to_disposition(currentness: Currentness) -> str:
    """Map currentness to disposition recommendation."""
    mapping = {
        Currentness.ACTUEL: "INGEST",
        Currentness.TRANSITION: "REVIEW_REQUIRED",
        Currentness.A_VERIFIER: "REVIEW_REQUIRED",
        Currentness.ARCHIVE: "ARCHIVE_ONLY",
        Currentness.CONFLICT: "QUARANTINE",
        Currentness.UNCLASSIFIED: "REVIEW_REQUIRED",
    }
    return mapping.get(currentness, "REVIEW_REQUIRED")


def classify_document(
    sha256: str,
    path: str,
    config: dict[str, Any],
) -> CurrentnessClassification:
    """Classify a document's currentness."""
    currentness = _extract_currentness_from_path(path, config)
    disposition = _currentness_to_disposition(currentness)
    ingest_eligible = currentness == Currentness.ACTUEL

    return CurrentnessClassification(
        sha256=sha256,
        path=path,
        currentness=currentness,
        ingest_eligible=ingest_eligible,
        disposition_recommendation=disposition,
    )


def load_config(path: Path) -> dict[str, Any]:
    """Load zone routing configuration."""
    content = path.read_text(encoding="utf-8")
    config = yaml.safe_load(content)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid config format: {path}")
    return config


def evaluate_currentness_gate(
    manifest_path: Path,
    config: dict[str, Any],
) -> CurrentnessGateReport:
    """Evaluate currentness gate for all documents in manifest."""
    config_id = config.get("config_id", "unknown")
    classifications: list[CurrentnessClassification] = []
    by_currentness: dict[str, int] = {}
    manifest_rows = 0
    eduscol_manifest_rows = 0
    malformed_manifest_rows = 0
    skipped_eduscol_rows = 0

    # Parse manifest
    with manifest_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = set(reader.fieldnames or [])
        manifest_schema_valid = (
            "sha256" in fieldnames
            and bool({"chemin_technique_existant", "path"} & fieldnames)
        )
        for line in reader:
            manifest_rows += 1
            sha256 = line.get("sha256", "")
            path = (
                line.get("chemin_technique_existant")
                or line.get("path")
                or ""
            )
            looks_eduscol = (
                path.startswith("01_EDUSCOL_OFFICIEL/")
                or str(line.get("famille", "")).strip().lower() == "eduscol"
                or "eduscol.education.gouv.fr" in str(line.get("url_source", ""))
            )

            row_valid = (
                manifest_schema_valid
                and re.fullmatch(r"[0-9a-f]{64}", sha256) is not None
                and bool(path)
            )
            if not row_valid:
                malformed_manifest_rows += 1
                if looks_eduscol or not manifest_schema_valid:
                    skipped_eduscol_rows += 1
                continue

            # A row that declares an Eduscol identity outside the canonical
            # prefix is part of the perimeter, but cannot be classified from
            # an ambiguous path. Count it and fail the perimeter closed.
            if not path.startswith("01_EDUSCOL_OFFICIEL/"):
                if looks_eduscol:
                    skipped_eduscol_rows += 1
                continue
            eduscol_manifest_rows += 1

            classification = classify_document(sha256, path, config)
            classifications.append(classification)

            key = classification.currentness.value
            by_currentness[key] = by_currentness.get(key, 0) + 1

    total = len(classifications)
    ingest_eligible = sum(1 for c in classifications if c.ingest_eligible)
    review_required = sum(
        1 for c in classifications
        if c.disposition_recommendation == "REVIEW_REQUIRED"
    )
    archive = sum(
        1 for c in classifications
        if c.disposition_recommendation == "ARCHIVE_ONLY"
    )
    unclassified = by_currentness.get("unclassified", 0)

    eduscol_manifest_rows += skipped_eduscol_rows
    perimeter_complete = (
        manifest_schema_valid
        and manifest_rows > 0
        and eduscol_manifest_rows > 0
        and malformed_manifest_rows == 0
        and skipped_eduscol_rows == 0
        and total == eduscol_manifest_rows
    )
    # Gate passes only when the complete declared Eduscol perimeter is classified.
    coverage_complete = perimeter_complete and unclassified == 0

    # Gate status
    if not perimeter_complete:
        gate_status = "BLOCKED_MANIFEST_PERIMETER_INCOMPLETE"
        gate_passed = False
    elif coverage_complete:
        gate_status = "PASS_COVERAGE_COMPLETE"
        gate_passed = True
    else:
        gate_status = f"BLOCKED_UNCLASSIFIED_{unclassified}"
        gate_passed = False

    return CurrentnessGateReport(
        manifest_path=str(manifest_path),
        config_id=config_id,
        evaluated_at=datetime.now(UTC).isoformat(),
        total_documents=total,
        ingest_eligible_count=ingest_eligible,
        review_required_count=review_required,
        archive_count=archive,
        gate_passed=gate_passed,
        gate_status=gate_status,
        by_currentness=by_currentness,
        classifications=classifications,
        coverage_complete=coverage_complete,
        unclassified_count=unclassified,
        manifest_rows=manifest_rows,
        eduscol_manifest_rows=eduscol_manifest_rows,
        malformed_manifest_rows=malformed_manifest_rows,
        skipped_eduscol_rows=skipped_eduscol_rows,
        manifest_schema_valid=manifest_schema_valid,
    )


def print_report(report: CurrentnessGateReport) -> None:
    """Print currentness gate report."""
    print(f"CURRENTNESS CLASSIFICATION GATE — {report.config_id}")
    print("=" * 60)
    print(f"Manifest: {report.manifest_path}")
    print(f"Evaluated at: {report.evaluated_at}")
    print()

    print("CLASSIFICATION BREAKDOWN:")
    for currentness, count in sorted(report.by_currentness.items()):
        pct = (count / report.total_documents * 100) if report.total_documents > 0 else 0
        print(f"  {currentness:20} = {count:5} ({pct:5.1f}%)")
    print(f"  {'TOTAL':20} = {report.total_documents:5}")
    print()

    print("DISPOSITION ELIGIBILITY:")
    print(f"  INGEST eligible:    {report.ingest_eligible_count}")
    print(f"  REVIEW_REQUIRED:    {report.review_required_count}")
    print(f"  ARCHIVE_ONLY:       {report.archive_count}")
    print()

    if report.coverage_complete:
        print("COVERAGE: COMPLETE")
        print("  All Eduscol documents have currentness classification.")
    else:
        print(f"COVERAGE: INCOMPLETE — {report.unclassified_count} unclassified")
        print("  Some documents need path-to-currentness mapping.")
    print()

    if report.gate_passed:
        print(f"GATE: {report.gate_status}")
    else:
        print(f"GATE: {report.gate_status}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate currentness classification gate."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to corpus manifest (TSV format)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/corpus_zone_routing.yml"),
        help="Path to zone routing config",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    report = evaluate_currentness_gate(args.manifest, config)

    print_report(report)

    return 0 if report.gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
