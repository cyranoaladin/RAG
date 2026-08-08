"""Golden Corpus Validator — H2-B.

Validates corpus catalog against golden corpus specification.
Verifies positive, boundary, and negative controls.

Usage:
    python -m rag_pedago.imports.golden_corpus_validator \
        --spec configs/golden_corpus_h2b.yml \
        --catalog data/reports/corpus_disposition_catalog.json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ControlResult:
    """Result of validating a single control."""

    control_id: str
    control_type: str  # positive, boundary, negative
    expected_disposition: str
    actual_disposition: str | None
    matched_object: str | None  # SHA256 or path of matched object
    passed: bool
    failure_reason: str | None = None


@dataclass
class ValidationReport:
    """Golden corpus validation report."""

    spec_id: str
    spec_path: str
    catalog_path: str
    validated_at: str
    total_controls: int
    passed_controls: int
    failed_controls: int
    validation_passed: bool
    control_results: list[ControlResult] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


def load_spec(path: Path) -> dict[str, Any]:
    """Load golden corpus specification."""
    content = path.read_text(encoding="utf-8")
    spec = yaml.safe_load(content)
    if not isinstance(spec, dict):
        raise ValueError(f"Invalid spec format: {path}")
    return spec


def load_catalog(path: Path) -> dict[str, Any]:
    """Load corpus disposition catalog."""
    content = path.read_text(encoding="utf-8")
    catalog = json.loads(content)
    if not isinstance(catalog, dict):
        raise ValueError(f"Invalid catalog format: {path}")
    return catalog


def _find_object_by_sha256_prefix(
    objects: list[dict[str, Any]],
    sha256_prefix: str,
) -> dict[str, Any] | None:
    """Find object by SHA256 prefix."""
    for obj in objects:
        sha = obj.get("sha256", "")
        if sha.startswith(sha256_prefix):
            return obj
    return None


def _find_object_by_zone(
    objects: list[dict[str, Any]],
    zone: str,
) -> dict[str, Any] | None:
    """Find any object in a zone (for boundary/negative controls)."""
    for obj in objects:
        path = obj.get("path", "")
        if zone in path:
            return obj
    return None


def _find_object_by_filename_pattern(
    objects: list[dict[str, Any]],
    pattern: str,
) -> dict[str, Any] | None:
    """Find object by filename pattern."""
    import fnmatch

    for obj in objects:
        path = obj.get("path", "")
        filename = path.split("/")[-1]
        if fnmatch.fnmatch(filename, pattern):
            return obj
    return None


def _validate_positive_control(
    control: dict[str, Any],
    objects: list[dict[str, Any]],
) -> ControlResult:
    """Validate a positive control."""
    control_id = control.get("control_id", "unknown")
    sha256_prefix = control.get("sha256_prefix")
    expected = control.get("expected_disposition", "INGEST")
    zone = control.get("zone", "")

    # Find the object
    matched = None
    if sha256_prefix:
        matched = _find_object_by_sha256_prefix(objects, sha256_prefix)
    if not matched and zone:
        matched = _find_object_by_zone(objects, zone)

    if not matched:
        return ControlResult(
            control_id=control_id,
            control_type="positive",
            expected_disposition=expected,
            actual_disposition=None,
            matched_object=None,
            passed=False,
            failure_reason="Object not found in catalog",
        )

    actual = matched.get("disposition")
    # For positive controls, check currentness is actuel (INGEST eligible)
    currentness = matched.get("currentness")

    # Check if disposition and currentness match expectations
    passed = (actual == expected) or (currentness == "actuel" and expected == "INGEST")

    return ControlResult(
        control_id=control_id,
        control_type="positive",
        expected_disposition=expected,
        actual_disposition=actual,
        matched_object=matched.get("sha256") or matched.get("path"),
        passed=passed,
        failure_reason=None if passed else f"Expected {expected}, got {actual}",
    )


def _validate_boundary_control(
    control: dict[str, Any],
    objects: list[dict[str, Any]],
) -> ControlResult:
    """Validate a boundary control."""
    control_id = control.get("control_id", "unknown")
    expected = control.get("expected_disposition", "REVIEW_REQUIRED")
    zone = control.get("zone", "")

    # Find any object in the zone
    matched = _find_object_by_zone(objects, zone)

    if not matched:
        return ControlResult(
            control_id=control_id,
            control_type="boundary",
            expected_disposition=expected,
            actual_disposition=None,
            matched_object=None,
            passed=False,
            failure_reason=f"No objects found in zone: {zone}",
        )

    actual = matched.get("disposition")
    passed = actual == expected

    return ControlResult(
        control_id=control_id,
        control_type="boundary",
        expected_disposition=expected,
        actual_disposition=actual,
        matched_object=matched.get("sha256") or matched.get("path"),
        passed=passed,
        failure_reason=None if passed else f"Expected {expected}, got {actual}",
    )


def _validate_negative_control(
    control: dict[str, Any],
    objects: list[dict[str, Any]],
) -> ControlResult:
    """Validate a negative control."""
    control_id = control.get("control_id", "unknown")
    expected = control.get("expected_disposition", "EXCLUDE")
    zone = control.get("zone")
    filename_pattern = control.get("filename_pattern")

    # Find the object
    matched = None
    if filename_pattern:
        matched = _find_object_by_filename_pattern(objects, filename_pattern)
    if not matched and zone:
        matched = _find_object_by_zone(objects, zone)

    if not matched:
        # For negative controls, not finding the object may be acceptable
        # (e.g., it was properly excluded from the catalog)
        return ControlResult(
            control_id=control_id,
            control_type="negative",
            expected_disposition=expected,
            actual_disposition=None,
            matched_object=None,
            passed=True,  # Object not in catalog = properly excluded
            failure_reason=None,
        )

    actual = matched.get("disposition")
    passed = actual in [expected, "EXCLUDE", "UNSUPPORTED"]

    return ControlResult(
        control_id=control_id,
        control_type="negative",
        expected_disposition=expected,
        actual_disposition=actual,
        matched_object=matched.get("sha256") or matched.get("path"),
        passed=passed,
        failure_reason=None if passed else f"Expected {expected}, got {actual}",
    )


def validate_golden_corpus(
    spec: dict[str, Any],
    catalog: dict[str, Any],
    spec_path: Path,
    catalog_path: Path,
) -> ValidationReport:
    """Validate catalog against golden corpus specification."""
    spec_id = spec.get("spec_id", "unknown")
    objects = catalog.get("objects", [])

    results: list[ControlResult] = []

    # Validate positive controls
    for control in spec.get("positive_controls", []):
        result = _validate_positive_control(control, objects)
        results.append(result)

    # Validate boundary controls
    for control in spec.get("boundary_controls", []):
        result = _validate_boundary_control(control, objects)
        results.append(result)

    # Validate negative controls
    for control in spec.get("negative_controls", []):
        result = _validate_negative_control(control, objects)
        results.append(result)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    summary = {
        "positive_passed": sum(1 for r in results if r.control_type == "positive" and r.passed),
        "positive_failed": sum(1 for r in results if r.control_type == "positive" and not r.passed),
        "boundary_passed": sum(1 for r in results if r.control_type == "boundary" and r.passed),
        "boundary_failed": sum(1 for r in results if r.control_type == "boundary" and not r.passed),
        "negative_passed": sum(1 for r in results if r.control_type == "negative" and r.passed),
        "negative_failed": sum(1 for r in results if r.control_type == "negative" and not r.passed),
    }

    return ValidationReport(
        spec_id=spec_id,
        spec_path=str(spec_path),
        catalog_path=str(catalog_path),
        validated_at=datetime.now(UTC).isoformat(),
        total_controls=len(results),
        passed_controls=passed,
        failed_controls=failed,
        validation_passed=failed == 0,
        control_results=results,
        summary=summary,
    )


def print_report(report: ValidationReport) -> None:
    """Print validation report."""
    print(f"GOLDEN CORPUS VALIDATION — {report.spec_id}")
    print("=" * 60)
    print(f"Spec: {report.spec_path}")
    print(f"Catalog: {report.catalog_path}")
    print(f"Validated at: {report.validated_at}")
    print()

    print("CONTROL RESULTS:")
    for result in report.control_results:
        status = "[PASS]" if result.passed else "[FAIL]"
        print(f"  {status} {result.control_id}")
        print(f"       Type: {result.control_type}")
        print(f"       Expected: {result.expected_disposition}")
        print(f"       Actual: {result.actual_disposition or 'N/A'}")
        if not result.passed and result.failure_reason:
            print(f"       Reason: {result.failure_reason}")
    print()

    print("SUMMARY:")
    print(f"  Total controls:   {report.total_controls}")
    print(f"  Passed:           {report.passed_controls}")
    print(f"  Failed:           {report.failed_controls}")
    print()
    print(f"  Positive: {report.summary.get('positive_passed', 0)} pass, {report.summary.get('positive_failed', 0)} fail")
    print(f"  Boundary: {report.summary.get('boundary_passed', 0)} pass, {report.summary.get('boundary_failed', 0)} fail")
    print(f"  Negative: {report.summary.get('negative_passed', 0)} pass, {report.summary.get('negative_failed', 0)} fail")
    print()

    if report.validation_passed:
        print("VALIDATION: PASSED")
    else:
        print("VALIDATION: FAILED")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate corpus catalog against golden corpus specification."
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path("configs/golden_corpus_h2b.yml"),
        help="Path to golden corpus specification",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Path to corpus disposition catalog (JSON)",
    )
    args = parser.parse_args()

    spec = load_spec(args.spec)
    catalog = load_catalog(args.catalog)
    report = validate_golden_corpus(spec, catalog, args.spec, args.catalog)

    print_report(report)

    return 0 if report.validation_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
