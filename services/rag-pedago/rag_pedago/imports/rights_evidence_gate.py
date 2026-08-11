"""Rights Evidence Gate — H2-B.

Validates that rights evidence is present before authorizing ingestion.
Implements fail-closed model: UNRESOLVED rights blocks ingestion.

Usage:
    python -m rag_pedago.imports.rights_evidence_gate \
        --registry configs/rights_evidence_registry.yml
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class RightsStatus(StrEnum):
    """Rights resolution status."""

    RESOLVED = "RESOLVED"
    CLEARED_BY_HUMAN_DECISION = "CLEARED_BY_HUMAN_DECISION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNRESOLVED = "UNRESOLVED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class ZoneRightsStatus:
    """Rights status for a corpus zone."""

    zone: str
    status: RightsStatus
    recommended_category: str | None
    blocking_questions_count: int
    human_verification_required: bool
    ingest_allowed: bool
    go_live_blocking: bool
    rationale: str


@dataclass
class RightsGateReport:
    """Rights evidence gate report."""

    registry_id: str
    registry_path: str
    evaluated_at: str
    total_zones: int
    resolved_zones: int
    cleared_by_human_decision_zones: int
    review_required_zones: int
    unresolved_zones: int
    unsupported_zones: int
    gate_passed: bool
    gate_status: str
    zone_statuses: list[ZoneRightsStatus] = field(default_factory=list)
    blocking_zones: list[str] = field(default_factory=list)
    human_actions_required: list[str] = field(default_factory=list)
    expected_zones: list[str] = field(default_factory=list)
    missing_expected_zones: list[str] = field(default_factory=list)
    unexpected_zones: list[str] = field(default_factory=list)


def load_registry(path: Path) -> dict[str, Any]:
    """Load rights evidence registry."""
    content = path.read_text(encoding="utf-8")
    registry = yaml.safe_load(content)
    if not isinstance(registry, dict):
        raise ValueError(f"Invalid registry format: {path}")
    return registry


def expected_rights_zones(routing_config: dict[str, Any]) -> frozenset[str]:
    """Dériver le périmètre droits depuis la politique indépendante."""
    raw = routing_config.get("rights_evidence_perimeter")
    if not isinstance(raw, list) or not raw:
        raise ValueError("routing rights_evidence_perimeter must be non-empty")
    if not all(
        isinstance(zone, str)
        and bool(zone)
        and zone.endswith("/")
        and not zone.startswith("/")
        and ".." not in zone.split("/")
        for zone in raw
    ):
        raise ValueError("routing rights evidence zone is not canonical")
    zones = frozenset(raw)
    if len(zones) != len(raw):
        raise ValueError("routing rights evidence zones must be unique")

    rules = routing_config.get("zone_rules")
    if not isinstance(rules, list):
        raise ValueError("routing zone_rules must be a list")
    prefixes = tuple(
        rule.get("zone_prefix")
        for rule in rules
        if isinstance(rule, dict)
        and isinstance(rule.get("zone_prefix"), str)
        and str(rule.get("zone_prefix")).endswith("/")
    )
    for zone in zones:
        if not any(zone.startswith(prefix) for prefix in prefixes):
            raise ValueError(
                f"rights evidence zone is outside routing policy: {zone}"
            )
    return zones


def _count_blocking_questions(source_evidence: dict[str, Any]) -> int:
    """Count unresolved blocking questions."""
    investigation = source_evidence.get("rights_investigation", {})
    questions = investigation.get("blocking_questions", [])
    return sum(
        1 for q in questions
        if q.get("answer") is None and q.get("human_verification_required", False)
    )


def _needs_human_verification(source_evidence: dict[str, Any]) -> bool:
    """Check if zone needs human verification."""
    if source_evidence.get("rights_status") in {
        "RESOLVED",
        "CLEARED_BY_HUMAN_DECISION",
        "REVIEW_REQUIRED",
        "UNSUPPORTED",
    }:
        return False

    investigation = source_evidence.get("rights_investigation", {})

    # Check attempted sources
    for source in investigation.get("attempted_sources", []):
        if source.get("human_verification_required", False):
            return True

    # Check blocking questions
    for question in investigation.get("blocking_questions", []):
        if question.get("human_verification_required", False):
            return True

    return False


def _human_decision_is_valid(
    decision: Any,
    expected_manifest_sha256: str,
) -> tuple[bool, str]:
    """Validate a human rights decision.

    P1 PRRT_kwDOTEIbbs6X3cnJ: expected_manifest_sha256 is REQUIRED.
    H2-F Défaut 3: The decision's scope_manifest_sha256 MUST match exactly.
    Fail-closed on mismatch.

    Returns:
        Tuple of (is_valid, error_reason).
    """
    if not isinstance(decision, dict):
        return False, "Decision is not a mapping"
    manifest_sha256 = decision.get("scope_manifest_sha256")
    if not isinstance(manifest_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None:
        return False, "scope_manifest_sha256 is missing or invalid"
    # P1: Always compare - expected_manifest_sha256 is no longer optional
    if manifest_sha256 != expected_manifest_sha256:
        return False, f"scope_manifest_sha256 mismatch: decision={manifest_sha256[:16]}... expected={expected_manifest_sha256[:16]}..."
    if decision.get("decision_type") != "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL":
        return False, "decision_type is not HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL"
    if not isinstance(decision.get("decision_maker"), str) or not decision.get("decision_maker"):
        return False, "decision_maker is missing or empty"
    if not isinstance(decision.get("decision_date"), str) or not decision.get("decision_date"):
        return False, "decision_date is missing or empty"
    if decision.get("approved_for_production_rag") is not True:
        return False, "approved_for_production_rag is not True"
    if decision.get("generic_rights_blocker") is not False:
        return False, "generic_rights_blocker is not False"
    return True, ""


def evaluate_zone(
    zone_id: str,
    source_evidence: dict[str, Any],
    human_decisions: dict[str, Any] | None = None,
    *,
    expected_manifest_sha256: str,
) -> ZoneRightsStatus:
    """Evaluate rights status for a zone.

    P1 PRRT_kwDOTEIbbs6X3cnJ: expected_manifest_sha256 is REQUIRED.
    H2-F Défaut 3: Human decisions MUST have a matching scope_manifest_sha256.
    Fail-closed on mismatch.
    """
    zone = source_evidence.get("zone", zone_id)
    rights_status_str = source_evidence.get("rights_status", "UNRESOLVED")

    status_aliases = {
        "UNSUPPORTED_FORMAT": RightsStatus.UNSUPPORTED.value,
        "DEFERRED_TO_REVIEW_REQUIRED": RightsStatus.REVIEW_REQUIRED.value,
    }
    rights_status_str = status_aliases.get(rights_status_str, rights_status_str)

    # Map status string to enum, failing closed for unknown values.
    try:
        status = RightsStatus(rights_status_str)
    except ValueError:
        status = RightsStatus.UNRESOLVED

    decision_error = ""
    if status is RightsStatus.CLEARED_BY_HUMAN_DECISION:
        decision_ref = source_evidence.get("rights_decision_ref")
        decision = (
            (human_decisions or {}).get(decision_ref)
            if isinstance(decision_ref, str)
            else None
        )
        is_valid, error_reason = _human_decision_is_valid(
            decision, expected_manifest_sha256
        )
        if not is_valid:
            status = RightsStatus.UNRESOLVED
            decision_error = error_reason or "Invalid or missing human organizational rights decision"

    recommended = source_evidence.get("recommended_rights_category")
    rationale = source_evidence.get("recommended_rights_category_rationale", "")
    blocking_count = (
        _count_blocking_questions(source_evidence)
        if status is RightsStatus.UNRESOLVED
        else 0
    )
    human_required = (
        _needs_human_verification(source_evidence)
        if status is RightsStatus.UNRESOLVED
        else False
    )
    ingest_allowed = status in {
        RightsStatus.RESOLVED,
        RightsStatus.CLEARED_BY_HUMAN_DECISION,
    }
    disposition_override = source_evidence.get("disposition_override")
    go_live_blocking = status is RightsStatus.UNRESOLVED and disposition_override not in {
        "REVIEW_REQUIRED",
        "QUARANTINE",
        "ARCHIVE_ONLY",
        "EXCLUDE",
        "UNSUPPORTED",
    }

    return ZoneRightsStatus(
        zone=zone,
        status=status,
        recommended_category=recommended,
        blocking_questions_count=blocking_count,
        human_verification_required=human_required,
        ingest_allowed=ingest_allowed,
        go_live_blocking=go_live_blocking,
        rationale=decision_error or rationale.strip(),
    )


def evaluate_registry(
    registry: dict[str, Any],
    path: Path,
    *,
    expected_zones: frozenset[str],
    expected_manifest_sha256: str,
) -> RightsGateReport:
    """Evaluate full rights evidence registry.

    P1 PRRT_kwDOTEIbbs6X3cnJ: expected_manifest_sha256 is REQUIRED.
    H2-F Défaut 3: All human decisions MUST have a matching scope_manifest_sha256.
    Fail-closed on mismatch.
    """
    registry_id = registry.get("registry_id", "unknown")
    source_evidence_raw = registry.get("source_evidence")
    summary = registry.get("summary")
    declared_total = summary.get("total_zones") if isinstance(summary, dict) else None
    source_evidence = (
        source_evidence_raw
        if isinstance(source_evidence_raw, dict)
        else {}
    )
    evidence_records_valid = all(
        isinstance(zone_id, str)
        and bool(zone_id)
        and isinstance(evidence, dict)
        for zone_id, evidence in source_evidence.items()
    )
    observed_zone_values = [
        evidence.get("zone")
        for evidence in source_evidence.values()
        if isinstance(evidence, dict)
    ]
    observed_zones = {
        zone for zone in observed_zone_values if isinstance(zone, str) and zone
    }
    zone_values_unique = len(observed_zones) == len(observed_zone_values)
    missing_expected_zones = sorted(expected_zones - observed_zones)
    unexpected_zones = sorted(observed_zones - expected_zones)
    perimeter_complete = (
        bool(expected_zones)
        and bool(source_evidence)
        and evidence_records_valid
        and zone_values_unique
        and isinstance(declared_total, int)
        and not isinstance(declared_total, bool)
        and declared_total > 0
        and declared_total == len(source_evidence)
        and declared_total == len(expected_zones)
        and not missing_expected_zones
        and not unexpected_zones
    )
    human_decisions = registry.get("human_rights_decisions", {})
    if not isinstance(human_decisions, dict):
        human_decisions = {}

    zone_statuses: list[ZoneRightsStatus] = []
    for zone_id, evidence in source_evidence.items():
        if not isinstance(zone_id, str) or not isinstance(evidence, dict):
            continue
        zone_status = evaluate_zone(
            zone_id,
            evidence,
            human_decisions,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        zone_statuses.append(zone_status)

    resolved = sum(1 for z in zone_statuses if z.status == RightsStatus.RESOLVED)
    cleared = sum(
        1
        for z in zone_statuses
        if z.status == RightsStatus.CLEARED_BY_HUMAN_DECISION
    )
    review_required = sum(
        1 for z in zone_statuses if z.status == RightsStatus.REVIEW_REQUIRED
    )
    unresolved = sum(1 for z in zone_statuses if z.status == RightsStatus.UNRESOLVED)
    unsupported = sum(1 for z in zone_statuses if z.status == RightsStatus.UNSUPPORTED)

    blocking_zones = [
        z.zone for z in zone_statuses
        if z.go_live_blocking
    ]

    human_actions: list[str] = []
    checklist = registry.get("human_verification_checklist", [])
    for item in checklist:
        if item.get("verified_at") is None and item.get("go_live_blocking", True):
            human_actions.append(item.get("task", "Unknown task"))

    # Global go-live is blocked only by an ingest-capable unresolved zone.
    # REVIEW_REQUIRED and UNSUPPORTED remain individually non-ingestible.
    gate_passed = perimeter_complete and not blocking_zones

    if not perimeter_complete:
        gate_status = "BLOCKED_RIGHTS_PERIMETER_INCOMPLETE"
    elif gate_passed:
        gate_status = "PASS"
    else:
        gate_status = "BLOCKED_UNRESOLVED_RIGHTS"

    return RightsGateReport(
        registry_id=registry_id,
        registry_path=str(path),
        evaluated_at=datetime.now(UTC).isoformat(),
        total_zones=len(zone_statuses),
        resolved_zones=resolved,
        cleared_by_human_decision_zones=cleared,
        review_required_zones=review_required,
        unresolved_zones=unresolved,
        unsupported_zones=unsupported,
        gate_passed=gate_passed,
        gate_status=gate_status,
        zone_statuses=zone_statuses,
        blocking_zones=blocking_zones,
        human_actions_required=human_actions,
        expected_zones=sorted(expected_zones),
        missing_expected_zones=missing_expected_zones,
        unexpected_zones=unexpected_zones,
    )


def print_report(report: RightsGateReport) -> None:
    """Print rights gate report to stdout."""
    print(f"RIGHTS EVIDENCE GATE — {report.registry_id}")
    print("=" * 60)
    print(f"Registry: {report.registry_path}")
    print(f"Evaluated at: {report.evaluated_at}")
    print()

    print("ZONE STATUS:")
    for z in report.zone_statuses:
        status_icon = {
            RightsStatus.RESOLVED: "[OK]",
            RightsStatus.CLEARED_BY_HUMAN_DECISION: "[OK]",
            RightsStatus.REVIEW_REQUIRED: "[??]",
            RightsStatus.UNRESOLVED: "[!!]",
            RightsStatus.UNSUPPORTED: "[--]",
        }.get(z.status, "[??]")

        category = z.recommended_category or "(none)"
        print(f"  {status_icon} {z.zone:50} → {category}")
        if z.status == RightsStatus.UNRESOLVED:
            print(f"      Blocking questions: {z.blocking_questions_count}")
            print(f"      Human verification required: {z.human_verification_required}")

    print()
    print("SUMMARY:")
    print(f"  Total zones:      {report.total_zones}")
    print(f"  Resolved:         {report.resolved_zones}")
    print(f"  Human decision:   {report.cleared_by_human_decision_zones}")
    print(f"  Review required:  {report.review_required_zones}")
    print(f"  Unresolved:       {report.unresolved_zones}")
    print(f"  Unsupported:      {report.unsupported_zones}")
    print()

    if report.gate_passed:
        print("GATE: PASS")
        print("  All zones have resolved rights evidence.")
    else:
        print(f"GATE: {report.gate_status}")
        print()
        if report.blocking_zones:
            print("BLOCKING ZONES (require human verification):")
            for zone in report.blocking_zones:
                print(f"  - {zone}")
            print()
        if report.human_actions_required:
            print("HUMAN ACTIONS REQUIRED:")
            for action in report.human_actions_required:
                print(f"  - {action}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate rights evidence gate."
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/rights_evidence_registry.yml"),
        help="Path to rights evidence registry",
    )
    parser.add_argument(
        "--routing",
        type=Path,
        default=Path("configs/corpus_zone_routing.yml"),
        help="Independent routing policy defining the rights perimeter",
    )
    # P1 PRRT_kwDOTEIbbs6X3cnJ: manifest SHA256 is REQUIRED
    parser.add_argument(
        "--manifest-sha256",
        type=str,
        required=True,
        help="Expected manifest SHA256 for human decision binding verification",
    )
    args = parser.parse_args()

    # Validate manifest SHA256 format
    if not re.fullmatch(r"[0-9a-f]{64}", args.manifest_sha256):
        print("ERROR: --manifest-sha256 must be a 64-character lowercase hex string")
        return 1

    registry = load_registry(args.registry)
    routing = load_registry(args.routing)
    report = evaluate_registry(
        registry,
        args.registry,
        expected_zones=expected_rights_zones(routing),
        expected_manifest_sha256=args.manifest_sha256,
    )

    print_report(report)

    return 0 if report.gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
