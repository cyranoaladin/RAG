"""Rights Evidence Gate — H2-B.

Validates that rights evidence is present before authorizing ingestion.
Implements fail-closed model: UNRESOLVED rights blocks ingestion.

Usage:
    python -m rag_pedago.imports.rights_evidence_gate \
        --registry configs/rights_evidence_registry.yml
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class RightsStatus(str, Enum):
    """Rights resolution status."""

    RESOLVED = "RESOLVED"
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
    rationale: str


@dataclass
class RightsGateReport:
    """Rights evidence gate report."""

    registry_id: str
    registry_path: str
    evaluated_at: str
    total_zones: int
    resolved_zones: int
    unresolved_zones: int
    unsupported_zones: int
    gate_passed: bool
    gate_status: str
    zone_statuses: list[ZoneRightsStatus] = field(default_factory=list)
    blocking_zones: list[str] = field(default_factory=list)
    human_actions_required: list[str] = field(default_factory=list)


def load_registry(path: Path) -> dict[str, Any]:
    """Load rights evidence registry."""
    content = path.read_text(encoding="utf-8")
    registry = yaml.safe_load(content)
    if not isinstance(registry, dict):
        raise ValueError(f"Invalid registry format: {path}")
    return registry


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
    if source_evidence.get("rights_status") == "RESOLVED":
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


def evaluate_zone(zone_id: str, source_evidence: dict[str, Any]) -> ZoneRightsStatus:
    """Evaluate rights status for a zone."""
    zone = source_evidence.get("zone", zone_id)
    rights_status_str = source_evidence.get("rights_status", "UNRESOLVED")

    # Map status string to enum
    try:
        status = RightsStatus(rights_status_str)
    except ValueError:
        status = RightsStatus.UNRESOLVED

    recommended = source_evidence.get("recommended_rights_category")
    rationale = source_evidence.get("recommended_rights_category_rationale", "")
    blocking_count = _count_blocking_questions(source_evidence)
    human_required = _needs_human_verification(source_evidence)

    return ZoneRightsStatus(
        zone=zone,
        status=status,
        recommended_category=recommended,
        blocking_questions_count=blocking_count,
        human_verification_required=human_required,
        rationale=rationale.strip(),
    )


def evaluate_registry(registry: dict[str, Any], path: Path) -> RightsGateReport:
    """Evaluate full rights evidence registry."""
    registry_id = registry.get("registry_id", "unknown")
    source_evidence = registry.get("source_evidence", {})

    zone_statuses: list[ZoneRightsStatus] = []
    for zone_id, evidence in source_evidence.items():
        zone_status = evaluate_zone(zone_id, evidence)
        zone_statuses.append(zone_status)

    resolved = sum(1 for z in zone_statuses if z.status == RightsStatus.RESOLVED)
    unresolved = sum(1 for z in zone_statuses if z.status == RightsStatus.UNRESOLVED)
    unsupported = sum(1 for z in zone_statuses if z.status == RightsStatus.UNSUPPORTED)

    blocking_zones = [
        z.zone for z in zone_statuses
        if z.status == RightsStatus.UNRESOLVED and z.human_verification_required
    ]

    human_actions: list[str] = []
    checklist = registry.get("human_verification_checklist", [])
    for item in checklist:
        if item.get("verified_at") is None:
            human_actions.append(item.get("task", "Unknown task"))

    # Gate passes only if all zones are RESOLVED or UNSUPPORTED
    # UNSUPPORTED zones are blocked by format gate, not rights gate
    gate_passed = unresolved == 0

    if gate_passed:
        gate_status = "PASS"
    elif blocking_zones:
        gate_status = "BLOCKED_HUMAN_VERIFICATION_REQUIRED"
    else:
        gate_status = "BLOCKED_UNRESOLVED_RIGHTS"

    return RightsGateReport(
        registry_id=registry_id,
        registry_path=str(path),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        total_zones=len(zone_statuses),
        resolved_zones=resolved,
        unresolved_zones=unresolved,
        unsupported_zones=unsupported,
        gate_passed=gate_passed,
        gate_status=gate_status,
        zone_statuses=zone_statuses,
        blocking_zones=blocking_zones,
        human_actions_required=human_actions,
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
            RightsStatus.UNRESOLVED: "[!!]",
            RightsStatus.UNSUPPORTED: "[--]",
        }.get(z.status, "[??]")

        category = z.recommended_category or "(none)"
        print(f"  {status_icon} {z.zone:50} → {category}")
        if z.status == RightsStatus.UNRESOLVED:
            print(f"      Blocking questions: {z.blocking_questions_count}")
            print(f"      Human verification required: {z.human_verification_required}")

    print()
    print(f"SUMMARY:")
    print(f"  Total zones:      {report.total_zones}")
    print(f"  Resolved:         {report.resolved_zones}")
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
    args = parser.parse_args()

    registry = load_registry(args.registry)
    report = evaluate_registry(registry, args.registry)

    print_report(report)

    return 0 if report.gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
