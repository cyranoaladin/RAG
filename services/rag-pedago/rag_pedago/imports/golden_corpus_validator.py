"""Fail-closed golden validation for the real sealed H2 corpus."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REAL_CATALOG_KIND = "REAL_SEALED_CORPUS"
VALIDATOR_VERSION = "golden-corpus-h2f-v2"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SHA256_PREFIX_RE = re.compile(r"[0-9a-f]{1,64}\Z")
_DISPOSITIONS = {
    "INGEST",
    "REVIEW_REQUIRED",
    "QUARANTINE",
    "ARCHIVE_ONLY",
    "EXCLUDE",
    "UNSUPPORTED",
}
_MISMATCH_SAMPLE_LIMIT = 5


@dataclass(frozen=True)
class ControlResult:
    """Result of one exhaustive golden control."""

    control_id: str
    control_type: str
    expected_disposition: str
    actual_disposition: str | None
    matched_object: str | None
    passed: bool
    failure_reason: str | None = None
    actual_base_disposition: str | None = None
    expected_count: int | None = None
    actual_count: int = 0
    mismatching_count: int = 0
    mismatching_objects: tuple[str, ...] = ()


@dataclass
class ValidationReport:
    """Input-bound golden corpus validation report."""

    spec_id: str
    spec_path: str
    catalog_path: str
    validated_at: str
    total_controls: int
    passed_controls: int
    failed_controls: int
    validation_passed: bool
    catalog_sha256: str
    spec_sha256: str
    catalog_manifest_sha256: str
    git_head: str
    validator_version: str
    policy_version: str
    objects_evaluated: int
    control_results: list[ControlResult] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the final machine-evidence schema without renamed counters."""
        return {
            "evidence_kind": "H2F_REAL_GOLDEN_VALIDATION",
            "spec_id": self.spec_id,
            "spec_path": self.spec_path,
            "catalog_path": self.catalog_path,
            "validated_at": self.validated_at,
            "golden_controls_total": self.total_controls,
            "golden_controls_passed": self.passed_controls,
            "golden_controls_failed": self.failed_controls,
            "golden_validation_passed": self.validation_passed,
            "catalog_sha256": self.catalog_sha256,
            "spec_sha256": self.spec_sha256,
            "catalog_manifest_sha256": self.catalog_manifest_sha256,
            "git_head": self.git_head,
            "validator_version": self.validator_version,
            "policy_version": self.policy_version,
            "objects_evaluated": self.objects_evaluated,
            **self.summary,
            "control_results": [asdict(result) for result in self.control_results],
        }


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"input file does not exist: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    )
    head = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ValueError("git HEAD is not a full commit SHA")
    return head


def load_spec(path: Path) -> dict[str, Any]:
    """Load one mapping-shaped golden specification."""
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError(f"Invalid spec format: {path}")
    return spec


def load_catalog(path: Path) -> dict[str, Any]:
    """Load one mapping-shaped corpus catalog."""
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict):
        raise ValueError(f"Invalid catalog format: {path}")
    return catalog


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"real catalog object {field_name} must be non-empty")
    return value


def _normalize_real_sealed_catalog(
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate the sole schema accepted by the final H2 golden gate."""
    if catalog.get("catalog_kind") != REAL_CATALOG_KIND:
        raise ValueError("final golden gate requires REAL_SEALED_CORPUS")
    manifest_sha256 = catalog.get("manifest_sha256")
    if not isinstance(manifest_sha256, str) or _SHA256_RE.fullmatch(
        manifest_sha256
    ) is None:
        raise ValueError("catalog manifest_sha256 is invalid")

    objects = catalog.get("physical_objects")
    if not isinstance(objects, list):
        raise ValueError("REAL_SEALED_CORPUS requires physical_objects")
    if catalog.get("physical_object_count") != len(objects):
        raise ValueError("physical_object_count does not match physical_objects")

    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(objects):
        if not isinstance(raw, dict):
            raise ValueError(f"physical_objects[{index}] must be a mapping")
        path = _required_string(raw.get("path"), "path")
        if path in seen_paths:
            raise ValueError(f"duplicate physical object path: {path}")
        seen_paths.add(path)

        content_sha256 = raw.get("content_sha256")
        if not isinstance(content_sha256, str) or _SHA256_RE.fullmatch(
            content_sha256
        ) is None:
            raise ValueError(f"physical_objects[{index}] content_sha256 is invalid")
        base_disposition = _required_string(
            raw.get("base_disposition"), "base_disposition"
        )
        disposition = _required_string(raw.get("disposition"), "disposition")
        if base_disposition not in _DISPOSITIONS or disposition not in _DISPOSITIONS:
            raise ValueError(f"physical_objects[{index}] disposition is invalid")

        if "currentness" not in raw:
            raise ValueError(
                f"physical_objects[{index}] currentness field is missing"
            )
        currentness = raw["currentness"]
        if currentness is not None and (
            not isinstance(currentness, str) or not currentness
        ):
            raise ValueError(f"physical_objects[{index}] currentness is invalid")
        gates = raw.get("gate_statuses")
        if not isinstance(gates, dict) or not all(
            isinstance(key, str)
            and key
            and isinstance(value, str)
            and value
            for key, value in gates.items()
        ):
            raise ValueError(f"physical_objects[{index}] gate_statuses is invalid")
        if raw.get("provenance_status") != "VERIFIED":
            raise ValueError(
                f"physical_objects[{index}] provenance_status is not VERIFIED"
            )
        attribution = raw.get("attribution_metadata")
        if not isinstance(attribution, dict) or not attribution or not all(
            isinstance(key, str)
            and key
            and isinstance(value, str)
            and value
            for key, value in attribution.items()
        ):
            raise ValueError(
                f"physical_objects[{index}] attribution_metadata is invalid"
            )
        normalized.append(dict(raw))
    return normalized


def _control_id(control: dict[str, Any]) -> str:
    return _required_string(control.get("control_id"), "control_id")


def _expected_disposition(control: dict[str, Any], field_name: str) -> str:
    value = _required_string(control.get(field_name), field_name)
    if value not in _DISPOSITIONS:
        raise ValueError(f"{field_name} is invalid")
    return value


def _safe_identifier(item: dict[str, Any]) -> str:
    path = item.get("path")
    return path if isinstance(path, str) else str(item.get("content_sha256"))


def _sample_mismatches(items: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(_safe_identifier(item) for item in items[:_MISMATCH_SAMPLE_LIMIT])


def _find_objects_by_sha256_prefix(
    objects: list[dict[str, Any]],
    sha256_prefix: object,
) -> list[dict[str, Any]]:
    if (
        not isinstance(sha256_prefix, str)
        or not sha256_prefix
        or _SHA256_PREFIX_RE.fullmatch(sha256_prefix) is None
    ):
        raise ValueError("positive control requires a non-empty SHA256 prefix")
    return [
        item
        for item in objects
        if str(item["content_sha256"]).startswith(sha256_prefix)
    ]


def _find_objects_by_zone(
    objects: list[dict[str, Any]], zone: object
) -> list[dict[str, Any]]:
    zone_value = _required_string(zone, "zone")
    return [item for item in objects if str(item["path"]).startswith(zone_value)]


def _find_objects_by_filename_pattern(
    objects: list[dict[str, Any]], pattern: object
) -> list[dict[str, Any]]:
    pattern_value = _required_string(pattern, "filename_pattern")
    return [
        item
        for item in objects
        if fnmatch.fnmatch(Path(str(item["path"])).name, pattern_value)
    ]


def _find_object_by_sha256_prefix(
    objects: list[dict[str, Any]], sha256_prefix: str
) -> dict[str, Any] | None:
    """Compatibility helper; ambiguity is fail-closed."""
    matches = _find_objects_by_sha256_prefix(objects, sha256_prefix)
    return matches[0] if len(matches) == 1 else None


def _find_object_by_zone(
    objects: list[dict[str, Any]], zone: str
) -> dict[str, Any] | None:
    """Compatibility helper; final controls use the exhaustive list function."""
    matches = _find_objects_by_zone(objects, zone)
    return matches[0] if len(matches) == 1 else None


def _find_object_by_filename_pattern(
    objects: list[dict[str, Any]], pattern: str
) -> dict[str, Any] | None:
    """Compatibility helper; final controls use the exhaustive list function."""
    matches = _find_objects_by_filename_pattern(objects, pattern)
    return matches[0] if len(matches) == 1 else None


def _validate_positive_control(
    control: dict[str, Any],
    objects: list[dict[str, Any]],
) -> ControlResult:
    """Validate distinct base eligibility and final disposition semantics."""
    control_id = _control_id(control)
    expected_base = _expected_disposition(
        control, "expected_base_disposition"
    )
    expected_final = _expected_disposition(
        control, "expected_final_disposition"
    )
    expected_currentness = _required_string(
        control.get("expected_currentness"), "expected_currentness"
    )
    expected_gates = control.get("expected_gate_statuses")
    if not isinstance(expected_gates, dict) or not expected_gates or not all(
        isinstance(key, str)
        and key
        and isinstance(value, str)
        and value
        for key, value in expected_gates.items()
    ):
        raise ValueError("positive expected_gate_statuses must be non-empty")

    matches = _find_objects_by_sha256_prefix(
        objects, control.get("sha256_prefix")
    )
    if len(matches) != 1:
        reason = (
            "SHA256 prefix matched zero objects"
            if not matches
            else f"SHA256 prefix is ambiguous ({len(matches)} objects)"
        )
        return ControlResult(
            control_id=control_id,
            control_type="positive",
            expected_disposition=expected_final,
            actual_disposition=None,
            matched_object=None,
            passed=False,
            failure_reason=reason,
            expected_count=1,
            actual_count=len(matches),
            mismatching_count=len(matches),
            mismatching_objects=_sample_mismatches(matches),
        )

    matched = matches[0]
    actual_base = str(matched["base_disposition"])
    actual_final = str(matched["disposition"])
    actual_gates = matched["gate_statuses"]
    mismatches: list[str] = []
    if actual_base != expected_base:
        mismatches.append(f"base expected {expected_base}, got {actual_base}")
    if actual_final != expected_final:
        mismatches.append(f"final expected {expected_final}, got {actual_final}")
    if matched.get("currentness") != expected_currentness:
        mismatches.append(
            "currentness expected "
            f"{expected_currentness}, got {matched.get('currentness')}"
        )
    for gate_name, expected_status in expected_gates.items():
        if actual_gates.get(gate_name) != expected_status:
            mismatches.append(
                f"gate {gate_name} expected {expected_status}, "
                f"got {actual_gates.get(gate_name)}"
            )
    passed = not mismatches
    return ControlResult(
        control_id=control_id,
        control_type="positive",
        expected_disposition=expected_final,
        actual_disposition=actual_final,
        actual_base_disposition=actual_base,
        matched_object=str(matched["content_sha256"]),
        passed=passed,
        failure_reason="; ".join(mismatches) if mismatches else None,
        expected_count=1,
        actual_count=1,
        mismatching_count=0 if passed else 1,
        mismatching_objects=() if passed else (_safe_identifier(matched),),
    )


def _expected_count(control: dict[str, Any]) -> int:
    raw = control.get("expected_count_in_zone", control.get("expected_count"))
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError("exhaustive control requires a positive expected count")
    return raw


def _validate_exhaustive_matches(
    *,
    control_id: str,
    control_type: str,
    expected: str,
    expected_count: int,
    expected_currentness: str | None,
    matches: list[dict[str, Any]],
) -> ControlResult:
    mismatches = [
        item
        for item in matches
        if item.get("disposition") != expected
        or (
            expected_currentness is not None
            and item.get("currentness") != expected_currentness
        )
    ]
    count_matches = len(matches) == expected_count
    passed = count_matches and not mismatches
    reasons: list[str] = []
    if not count_matches:
        reasons.append(f"expected count {expected_count}, got {len(matches)}")
    if mismatches:
        reasons.append(f"{len(mismatches)} objects violate boundary policy")
    dispositions = {str(item.get("disposition")) for item in matches}
    actual_disposition = (
        next(iter(dispositions)) if len(dispositions) == 1 else "MIXED"
    )
    return ControlResult(
        control_id=control_id,
        control_type=control_type,
        expected_disposition=expected,
        actual_disposition=actual_disposition if matches else None,
        matched_object=_safe_identifier(matches[0]) if len(matches) == 1 else None,
        passed=passed,
        failure_reason="; ".join(reasons) if reasons else None,
        expected_count=expected_count,
        actual_count=len(matches),
        mismatching_count=len(mismatches),
        mismatching_objects=_sample_mismatches(mismatches),
    )


def _validate_boundary_control(
    control: dict[str, Any],
    objects: list[dict[str, Any]],
) -> ControlResult:
    """Validate every object in a count-bound boundary zone."""
    expected_currentness_raw = control.get("expected_currentness")
    expected_currentness = (
        _required_string(expected_currentness_raw, "expected_currentness")
        if expected_currentness_raw is not None
        else None
    )
    return _validate_exhaustive_matches(
        control_id=_control_id(control),
        control_type="boundary",
        expected=_expected_disposition(control, "expected_disposition"),
        expected_count=_expected_count(control),
        expected_currentness=expected_currentness,
        matches=_find_objects_by_zone(objects, control.get("zone")),
    )


def _validate_negative_control(
    control: dict[str, Any],
    objects: list[dict[str, Any]],
) -> ControlResult:
    """Validate every exact/pattern/zone match; absence is failure."""
    selectors = [
        name
        for name in ("path", "filename_pattern", "zone")
        if control.get(name) is not None
    ]
    if len(selectors) != 1:
        raise ValueError("negative control requires exactly one match selector")
    selector = selectors[0]
    if selector == "path":
        path = _required_string(control.get("path"), "path")
        matches = [item for item in objects if item.get("path") == path]
    elif selector == "filename_pattern":
        matches = _find_objects_by_filename_pattern(
            objects, control.get("filename_pattern")
        )
    else:
        matches = _find_objects_by_zone(objects, control.get("zone"))
    return _validate_exhaustive_matches(
        control_id=_control_id(control),
        control_type="negative",
        expected=_expected_disposition(control, "expected_disposition"),
        expected_count=_expected_count(control),
        expected_currentness=None,
        matches=matches,
    )


def _controls(spec: dict[str, Any], field_name: str) -> list[dict[str, Any]]:
    raw = spec.get(field_name)
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError(f"golden {field_name} must be a list of mappings")
    return raw


def _validate_spec_perimeter(
    spec: dict[str, Any],
    positive: list[dict[str, Any]],
    boundary: list[dict[str, Any]],
    negative: list[dict[str, Any]],
) -> None:
    if spec.get("catalog_kind_required") != REAL_CATALOG_KIND:
        raise ValueError("golden spec must require REAL_SEALED_CORPUS")
    if "test_assertions" in spec:
        raise ValueError("test_assertions cannot be silently non-executable")
    descriptive = spec.get("descriptive_assertions")
    if not isinstance(descriptive, dict) or descriptive.get("authoritative") is not False:
        raise ValueError("descriptive_assertions must be explicitly non-authoritative")
    coverage = spec.get("coverage_summary")
    if not isinstance(coverage, dict):
        raise ValueError("golden coverage_summary is required")
    control_ids = [
        _control_id(control)
        for control in (*positive, *boundary, *negative)
    ]
    if len(control_ids) != len(set(control_ids)):
        raise ValueError("golden control_id values must be unique")
    actual = {
        "total_controls": len(positive) + len(boundary) + len(negative),
        "positive_controls": len(positive),
        "boundary_controls": len(boundary),
        "negative_controls": len(negative),
    }
    if actual["total_controls"] == 0:
        raise ValueError("golden spec requires at least one executable control")
    for field_name, actual_value in actual.items():
        if coverage.get(field_name) != actual_value:
            raise ValueError(f"golden coverage_summary {field_name} mismatch")


def validate_golden_corpus(
    spec: dict[str, Any],
    catalog: dict[str, Any],
    spec_path: Path,
    catalog_path: Path,
) -> ValidationReport:
    """Validate the full declared perimeter against one exact real catalog."""
    if load_spec(spec_path) != spec:
        raise ValueError("spec mapping does not match bound spec file")
    if load_catalog(catalog_path) != catalog:
        raise ValueError("catalog mapping does not match bound catalog file")
    objects = _normalize_real_sealed_catalog(catalog)
    positive = _controls(spec, "positive_controls")
    boundary = _controls(spec, "boundary_controls")
    negative = _controls(spec, "negative_controls")
    _validate_spec_perimeter(spec, positive, boundary, negative)

    results = [
        *(_validate_positive_control(control, objects) for control in positive),
        *(_validate_boundary_control(control, objects) for control in boundary),
        *(_validate_negative_control(control, objects) for control in negative),
    ]
    passed = sum(result.passed for result in results)
    failed = len(results) - passed
    summary: dict[str, int] = {}
    for control_type in ("positive", "boundary", "negative"):
        typed = [item for item in results if item.control_type == control_type]
        summary[f"{control_type}_controls_total"] = len(typed)
        summary[f"{control_type}_controls_passed"] = sum(
            item.passed for item in typed
        )
        summary[f"{control_type}_controls_failed"] = sum(
            not item.passed for item in typed
        )

    spec_id = _required_string(spec.get("spec_id"), "spec_id")
    return ValidationReport(
        spec_id=spec_id,
        spec_path=spec_path.name,
        catalog_path=catalog_path.name,
        validated_at=datetime.now(UTC).isoformat(),
        total_controls=len(results),
        passed_controls=passed,
        failed_controls=failed,
        validation_passed=failed == 0,
        catalog_sha256=_file_sha256(catalog_path),
        spec_sha256=_file_sha256(spec_path),
        catalog_manifest_sha256=str(catalog["manifest_sha256"]),
        git_head=_git_head(),
        validator_version=VALIDATOR_VERSION,
        policy_version=spec_id,
        objects_evaluated=sum(item.actual_count for item in results),
        control_results=results,
        summary=summary,
    )


def print_report(report: ValidationReport) -> None:
    """Print non-sensitive machine and human evidence."""
    print(f"GOLDEN CORPUS VALIDATION — {report.spec_id}")
    print("=" * 60)
    print(f"CATALOG_SHA256={report.catalog_sha256}")
    print(f"SPEC_SHA256={report.spec_sha256}")
    print(f"CATALOG_MANIFEST_SHA256={report.catalog_manifest_sha256}")
    print(f"GIT_HEAD={report.git_head}")
    print(f"VALIDATOR_VERSION={report.validator_version}")
    for result in report.control_results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"{result.control_id}={status} "
            f"objects={result.actual_count}/{result.expected_count} "
            f"mismatches={result.mismatching_count}"
        )
        if result.failure_reason:
            print(f"  reason={result.failure_reason}")
    print(f"GOLDEN_CONTROLS_TOTAL={report.total_controls}")
    print(f"GOLDEN_CONTROLS_PASSED={report.passed_controls}")
    print(f"GOLDEN_CONTROLS_FAILED={report.failed_controls}")
    print(f"OBJECTS_EVALUATED={report.objects_evaluated}")
    print(
        "GOLDEN_VALIDATION="
        f"{'PASS' if report.validation_passed else 'FAIL'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the real sealed corpus against the golden spec."
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path("configs/golden_corpus_h2b.yml"),
    )
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    spec = load_spec(args.spec)
    catalog = load_catalog(args.catalog)
    report = validate_golden_corpus(spec, catalog, args.spec, args.catalog)
    print_report(report)
    return 0 if report.validation_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
