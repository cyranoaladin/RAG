"""Tests for rights evidence gate — H2-B."""
from pathlib import Path

import pytest

from rag_pedago.imports.rights_evidence_gate import (
    RightsStatus,
    evaluate_registry,
    load_registry,
)


CONFIGS = Path(__file__).parent.parent / "configs"


class TestRightsEvidenceGate:
    """Test rights evidence gate evaluation."""

    @pytest.fixture
    def registry(self) -> dict:
        registry_path = CONFIGS / "rights_evidence_registry.yml"
        return load_registry(registry_path)

    @pytest.fixture
    def registry_path(self) -> Path:
        return CONFIGS / "rights_evidence_registry.yml"

    def test_gate_blocks_on_unresolved_rights(
        self, registry: dict, registry_path: Path
    ) -> None:
        """Gate blocks when any zone has unresolved rights."""
        report = evaluate_registry(registry, registry_path)

        # Current registry has unresolved zones
        assert not report.gate_passed
        assert report.unresolved_zones > 0

    def test_resolved_zones_are_counted(
        self, registry: dict, registry_path: Path
    ) -> None:
        """Resolved zones (Nexus content) are properly counted."""
        report = evaluate_registry(registry, registry_path)

        # Should have resolved zones for Nexus content
        assert report.resolved_zones >= 2

        resolved_zones = [
            z for z in report.zone_statuses
            if z.status == RightsStatus.RESOLVED
        ]
        assert any("NEXUS" in z.zone.upper() for z in resolved_zones)

    def test_blocking_zones_identified(
        self, registry: dict, registry_path: Path
    ) -> None:
        """Blocking zones requiring human verification are identified."""
        report = evaluate_registry(registry, registry_path)

        # Eduscol should be blocking
        assert any("EDUSCOL" in zone.upper() for zone in report.blocking_zones)

    def test_human_actions_listed(
        self, registry: dict, registry_path: Path
    ) -> None:
        """Human actions required are listed."""
        report = evaluate_registry(registry, registry_path)

        assert len(report.human_actions_required) > 0
        assert any("eduscol" in action.lower() for action in report.human_actions_required)

    def test_fail_closed_behavior(
        self, registry: dict, registry_path: Path
    ) -> None:
        """Gate implements fail-closed: unresolved = blocked."""
        report = evaluate_registry(registry, registry_path)

        # Fail-closed: any unresolved zone blocks the gate
        if report.unresolved_zones > 0:
            assert not report.gate_passed
            assert "BLOCKED" in report.gate_status


class TestRightsGateInvariants:
    """Test rights gate invariants."""

    @pytest.fixture
    def registry_path(self) -> Path:
        return CONFIGS / "rights_evidence_registry.yml"

    @pytest.fixture
    def report(self, registry_path: Path) -> any:
        registry = load_registry(registry_path)
        return evaluate_registry(registry, registry_path)

    def test_zone_counts_sum_correctly(self, report) -> None:
        """Zone counts sum to total."""
        total = report.resolved_zones + report.unresolved_zones + report.unsupported_zones
        assert total == report.total_zones

    def test_all_zones_have_status(self, report) -> None:
        """Every zone has a rights status."""
        for zone_status in report.zone_statuses:
            assert zone_status.status is not None
            assert isinstance(zone_status.status, RightsStatus)

    def test_resolved_zones_have_category(self, report) -> None:
        """Resolved zones have a recommended rights category."""
        for zone_status in report.zone_statuses:
            if zone_status.status == RightsStatus.RESOLVED:
                assert zone_status.recommended_category is not None
