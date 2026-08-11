"""Tests for the fail-closed H2-B rights evidence gate."""
from pathlib import Path

import pytest
import yaml

from rag_pedago.imports.rights_evidence_gate import (
    RightsStatus,
    evaluate_registry,
    expected_rights_zones,
    load_registry,
)

CONFIGS = Path(__file__).parent.parent / "configs"
MANIFEST_SHA256 = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
NEXUS_SET_DIGEST = "877591ddc3a1be85da2c09b61bd4e161020bb0a7cb135ad33c68b5c27de0eb38"
ROUTING = yaml.safe_load((CONFIGS / "corpus_zone_routing.yml").read_text())
EXPECTED_ZONES = expected_rights_zones(ROUTING)


@pytest.fixture
def registry_path() -> Path:
    return CONFIGS / "rights_evidence_registry.yml"


@pytest.fixture
def registry(registry_path: Path) -> dict:
    return load_registry(registry_path)


def _zone(report, prefix: str):  # noqa: ANN001, ANN202
    return next(item for item in report.zone_statuses if item.zone.startswith(prefix))


class TestRecordedHumanDecisions:
    def test_generic_eduscol_decision_clears_only_the_generic_rights_gate(
        self, registry: dict, registry_path: Path
    ) -> None:
        report = evaluate_registry(
            registry, registry_path, expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )
        eduscol = _zone(report, "01_EDUSCOL_OFFICIEL/")

        assert eduscol.status == RightsStatus.CLEARED_BY_HUMAN_DECISION
        assert eduscol.ingest_allowed is True
        assert eduscol.go_live_blocking is False
        assert report.gate_passed is True
        assert report.blocking_zones == []
        assert not any(
            "eduscol" in action.lower()
            for action in report.human_actions_required
        )

    def test_eduscol_decision_is_organizational_and_bound_to_sealed_manifest(
        self, registry: dict
    ) -> None:
        decision = registry["human_rights_decisions"]["eduscol_generic_approval"]

        assert decision["decision_type"] == "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL"
        assert decision["decision_maker"] == "Nexus Réussite"
        assert decision["decision_source"] == "EXPLICIT_GO_LIVE_INSTRUCTION"
        assert decision["scope_manifest_sha256"] == MANIFEST_SHA256
        assert decision["scope_zone"] == "01_EDUSCOL_OFFICIEL/"
        assert decision["approved_for_production_rag"] is True
        assert decision["generic_rights_blocker"] is False
        assert decision["external_legal_opinion"] is False

    def test_nexus_decision_is_bound_to_the_exact_current_sha_set(
        self, registry: dict
    ) -> None:
        decision = registry["human_rights_decisions"]["nexus_internal_approval"]

        assert decision["scope_manifest_sha256"] == MANIFEST_SHA256
        assert decision["artifact_count"] == 39
        assert decision["content_sha256_set_digest"] == NEXUS_SET_DIGEST
        assert decision["set_digest_canonicalization"] == (
            "lowercase SHA256 values, lexicographically sorted, one per line, "
            "final newline"
        )
        assert decision["cryptographic_signature_claimed"] is False


class TestDocumentSpecificFailClosedHandling:
    def test_depp_review_does_not_authorize_ingest_or_block_other_content(
        self, registry: dict, registry_path: Path
    ) -> None:
        report = evaluate_registry(
            registry, registry_path, expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )
        depp = _zone(
            report,
            "04_COMPLEMENTS_PEDAGOGIQUES/01_SOURCES_INSTITUTIONNELLES/",
        )

        assert depp.status == RightsStatus.REVIEW_REQUIRED
        assert depp.ingest_allowed is False
        assert depp.go_live_blocking is False

    def test_unsupported_geogebra_is_not_rights_authorized(
        self, registry: dict, registry_path: Path
    ) -> None:
        report = evaluate_registry(
            registry, registry_path, expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )
        geogebra = _zone(report, "03_RESSOURCES_INTERACTIVES/")

        assert geogebra.status == RightsStatus.UNSUPPORTED
        assert geogebra.ingest_allowed is False
        assert geogebra.go_live_blocking is False

    def test_unresolved_ingest_capable_zone_remains_a_global_blocker(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "unresolved.yml"
        registry = {
            "registry_id": "unresolved-test",
            "summary": {"total_zones": 1},
            "source_evidence": {
                "unsafe": {
                    "zone": "01_EXTERNAL/",
                    "rights_status": "UNRESOLVED",
                }
            },
        }

        report = evaluate_registry(
            registry, path, expected_zones=frozenset({"01_EXTERNAL/"}),
            expected_manifest_sha256="0" * 64,
        )

        assert report.gate_passed is False
        assert report.blocking_zones == ["01_EXTERNAL/"]
        assert report.gate_status == "BLOCKED_UNRESOLVED_RIGHTS"

    @pytest.mark.parametrize(
        "decision_ref",
        ("missing", []),
        ids=("missing", "malformed"),
    )
    def test_invalid_human_decision_reference_fails_closed(
        self, tmp_path: Path, decision_ref: object
    ) -> None:
        path = tmp_path / "invalid-decision.yml"
        registry = {
            "registry_id": "invalid-decision-test",
            "summary": {"total_zones": 1},
            "human_rights_decisions": {},
            "source_evidence": {
                "unsafe": {
                    "zone": "01_EXTERNAL/",
                    "rights_status": "CLEARED_BY_HUMAN_DECISION",
                    "rights_decision_ref": decision_ref,
                }
            },
        }

        report = evaluate_registry(
            registry, path, expected_zones=frozenset({"01_EXTERNAL/"}),
            expected_manifest_sha256="0" * 64,
        )

        unsafe = report.zone_statuses[0]
        assert unsafe.status == RightsStatus.UNRESOLVED
        assert unsafe.ingest_allowed is False
        assert unsafe.go_live_blocking is True
        assert report.gate_passed is False


class TestRightsGateInvariants:
    def test_missing_rights_perimeter_fails_closed(self, tmp_path: Path) -> None:
        report = evaluate_registry(
            {
                "registry_id": "missing-perimeter-test",
                "summary": {"total_zones": 1},
            },
            tmp_path / "registry.yml",
            expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )

        assert report.total_zones == 0
        assert report.gate_passed is False
        assert report.gate_status == "BLOCKED_RIGHTS_PERIMETER_INCOMPLETE"

    @pytest.mark.parametrize(
        ("source_evidence", "summary"),
        [
            ({}, {"total_zones": 0}),
            ({}, {"total_zones": 5}),
            (
                {
                    "only-zone": {
                        "zone": "01_ONLY/",
                        "rights_status": "RESOLVED",
                    }
                },
                {"total_zones": 5},
            ),
        ],
        ids=("empty-perimeter", "missing-five-zones", "truncated-perimeter"),
    )
    def test_empty_or_truncated_rights_perimeter_fails_closed(
        self,
        tmp_path: Path,
        source_evidence: dict,
        summary: dict,
    ) -> None:
        report = evaluate_registry(
            {
                "registry_id": "perimeter-test",
                "source_evidence": source_evidence,
                "summary": summary,
            },
            tmp_path / "registry.yml",
            expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )

        assert report.gate_passed is False
        assert report.gate_status == "BLOCKED_RIGHTS_PERIMETER_INCOMPLETE"

    def test_zone_counts_sum_correctly(
        self, registry: dict, registry_path: Path
    ) -> None:
        report = evaluate_registry(
            registry, registry_path, expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )
        total = (
            report.resolved_zones
            + report.cleared_by_human_decision_zones
            + report.review_required_zones
            + report.unresolved_zones
            + report.unsupported_zones
        )
        assert total == report.total_zones

    def test_every_zone_has_exactly_one_rights_status(
        self, registry: dict, registry_path: Path
    ) -> None:
        report = evaluate_registry(
            registry, registry_path, expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )

        assert report.total_zones == 5
        assert all(isinstance(item.status, RightsStatus) for item in report.zone_statuses)
        assert sum(item.ingest_allowed for item in report.zone_statuses) == 3

    def test_registry_cannot_shrink_its_own_expected_perimeter(
        self, registry: dict, registry_path: Path
    ) -> None:
        source_evidence = registry["source_evidence"]
        removed_key = next(iter(source_evidence))
        del source_evidence[removed_key]
        registry["summary"]["total_zones"] -= 1

        report = evaluate_registry(
            registry, registry_path, expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )

        assert report.gate_passed is False
        assert report.gate_status == "BLOCKED_RIGHTS_PERIMETER_INCOMPLETE"
        assert report.missing_expected_zones


class TestHumanDecisionManifestBinding:
    """H2-F Défaut 3: Human decisions must be bound to the exact routed manifest."""

    def test_decision_with_wrong_manifest_sha256_fails_closed(
        self, tmp_path: Path
    ) -> None:
        """Decision with mismatched manifest SHA256 must be rejected."""
        expected_manifest = "a" * 64  # The routing manifest
        wrong_manifest = "b" * 64  # The decision claims a different manifest

        path = tmp_path / "wrong-manifest.yml"
        registry = {
            "registry_id": "wrong-manifest-test",
            "summary": {"total_zones": 1},
            "human_rights_decisions": {
                "wrong_manifest_decision": {
                    "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                    "decision_maker": "Test User",
                    "decision_date": "2026-08-10",
                    "scope_manifest_sha256": wrong_manifest,
                    "approved_for_production_rag": True,
                    "generic_rights_blocker": False,
                }
            },
            "source_evidence": {
                "test-zone": {
                    "zone": "01_TEST/",
                    "rights_status": "CLEARED_BY_HUMAN_DECISION",
                    "rights_decision_ref": "wrong_manifest_decision",
                }
            },
        }

        report = evaluate_registry(
            registry,
            path,
            expected_zones=frozenset({"01_TEST/"}),
            expected_manifest_sha256=expected_manifest,
        )

        zone = report.zone_statuses[0]
        assert zone.status == RightsStatus.UNRESOLVED
        assert zone.ingest_allowed is False
        assert zone.go_live_blocking is True
        assert "manifest" in zone.rationale.lower()
        assert report.gate_passed is False

    def test_decision_with_correct_manifest_sha256_is_accepted(
        self, tmp_path: Path
    ) -> None:
        """Decision with matching manifest SHA256 must be accepted."""
        manifest = "c" * 64

        path = tmp_path / "correct-manifest.yml"
        registry = {
            "registry_id": "correct-manifest-test",
            "summary": {"total_zones": 1},
            "human_rights_decisions": {
                "correct_decision": {
                    "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                    "decision_maker": "Test User",
                    "decision_date": "2026-08-10",
                    "scope_manifest_sha256": manifest,
                    "approved_for_production_rag": True,
                    "generic_rights_blocker": False,
                }
            },
            "source_evidence": {
                "test-zone": {
                    "zone": "01_TEST/",
                    "rights_status": "CLEARED_BY_HUMAN_DECISION",
                    "rights_decision_ref": "correct_decision",
                }
            },
        }

        report = evaluate_registry(
            registry,
            path,
            expected_zones=frozenset({"01_TEST/"}),
            expected_manifest_sha256=manifest,
        )

        zone = report.zone_statuses[0]
        assert zone.status == RightsStatus.CLEARED_BY_HUMAN_DECISION
        assert zone.ingest_allowed is True
        assert report.gate_passed is True

    def test_real_registry_decisions_match_routing_manifest(
        self, registry: dict, registry_path: Path
    ) -> None:
        """Real registry decisions must match the routing manifest."""
        report = evaluate_registry(
            registry,
            registry_path,
            expected_zones=EXPECTED_ZONES,
            expected_manifest_sha256=MANIFEST_SHA256,
        )

        # All decisions should still be valid
        assert report.gate_passed is True
        eduscol = next(
            z for z in report.zone_statuses
            if z.zone.startswith("01_EDUSCOL")
        )
        assert eduscol.status == RightsStatus.CLEARED_BY_HUMAN_DECISION
