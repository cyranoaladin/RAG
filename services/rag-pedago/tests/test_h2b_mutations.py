"""H2-B Mutation Tests — prove gates are non-vacuous.

Each mutation test proves that a specific H2-B gate ACTUALLY BLOCKS
when its condition is violated. A gate that never blocks is vacuous
and provides no security.

Mutation Matrix (MUT-H2B-01 through MUT-H2B-12):
- MUT-H2B-01: Rights gate blocks unknown rights
- MUT-H2B-02: Rights gate blocks unresolved evidence
- MUT-H2B-03: PII gate blocks detected PII
- MUT-H2B-04: PII gate passes clean content
- MUT-H2B-05: Currentness gate blocks non-actuel
- MUT-H2B-06: Currentness gate passes actuel
- MUT-H2B-07: Format gate blocks unsupported
- MUT-H2B-08: Format gate passes PDF
- MUT-H2B-09: Zone routing assigns correct disposition
- MUT-H2B-10: Golden corpus positive controls pass
- MUT-H2B-11: Golden corpus negative controls block
- MUT-H2B-12: Disposition sum equals corpus total
"""
from pathlib import Path

import pytest
import yaml

# Import the modules under test
from rag_pedago.imports.corpus_catalog_compiler import (
    Disposition,
    _determine_disposition,
    load_routing_config,
)
from rag_pedago.imports.currentness_gate import (
    Currentness,
    classify_document,
)
from rag_pedago.imports.currentness_gate import (
    load_config as load_currentness_config,
)
from rag_pedago.imports.golden_corpus_validator import (
    _validate_negative_control,
    _validate_positive_control,
)
from rag_pedago.imports.pii_scanner import (
    DEFAULT_PII_PATTERNS,
    scan_text_for_pii,
)
from rag_pedago.imports.rights_evidence_gate import (
    RightsStatus,
    evaluate_zone,
)


class TestMutH2B01RightsBlocksUnknown:
    """MUT-H2B-01: Rights gate blocks unknown/unresolved rights."""

    def test_unknown_rights_blocks_ingest(self) -> None:
        """A zone with unknown rights status cannot proceed to INGEST."""
        result = evaluate_zone(
            "synthetic_unresolved_zone",
            {
                "zone": "synthetic_unresolved_zone/",
                "rights_status": "UNRESOLVED",
            },
        )

        assert result.status is RightsStatus.UNRESOLVED
        assert result.ingest_allowed is False
        assert result.go_live_blocking is True


class TestMutH2B02RightsBlocksNoEvidence:
    """MUT-H2B-02: Rights gate blocks zones without evidence."""

    def test_missing_evidence_blocks_ingest(self) -> None:
        """A zone not in the registry cannot proceed to INGEST."""
        # Empty evidence = no rights cleared (defaults to UNRESOLVED)
        empty_evidence: dict = {}
        result = evaluate_zone("nonexistent_zone", empty_evidence)
        assert result.status != RightsStatus.RESOLVED, \
            "Zone without evidence must NOT pass rights gate"


class TestMutH2B03PIIBlocksDetected:
    """MUT-H2B-03: PII gate blocks when PII is detected."""

    def test_pii_detected_triggers_block(self) -> None:
        """Content with PII must trigger blocking."""
        text_with_pii = "Contact: jean.martin@gmail.com Tel: 06 12 34 56 78"

        matches = scan_text_for_pii(text_with_pii, DEFAULT_PII_PATTERNS)

        assert len(matches) > 0, \
            "PII patterns must detect real PII"
        assert any(m.pattern_id == "email_address" for m in matches), \
            "Email pattern must match real email"
        assert any(m.pattern_id == "phone_french" for m in matches), \
            "Phone pattern must match real phone"


class TestMutH2B04PIIPassesClean:
    """MUT-H2B-04: PII gate passes clean content."""

    def test_clean_content_passes(self) -> None:
        """Pedagogical content without PII must pass."""
        clean_text = """
        Chapitre 3: Les fonctions

        Definition: Une fonction f de R vers R associe a chaque
        reel x un unique reel f(x).

        Exemple: f(x) = x^2 est une fonction.
        """

        matches = scan_text_for_pii(clean_text, DEFAULT_PII_PATTERNS)

        assert len(matches) == 0, \
            "Clean pedagogical content must not trigger false positives"


class TestMutH2B05CurrentnessBlocksNonActuel:
    """MUT-H2B-05: Currentness gate blocks non-actuel documents."""

    def test_non_actuel_blocks_ingest(self) -> None:
        """Documents outside 10_ACTUEL_CONFIRME cannot be INGEST."""
        config_path = Path("configs/corpus_zone_routing.yml")
        if not config_path.exists():
            pytest.skip("Zone routing config not found")

        config = load_currentness_config(config_path)

        test_cases = [
            ("01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL/80_A_VERIFIER/doc.pdf", Currentness.A_VERIFIER),
            ("01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL/90_ARCHIVE_CATALOGUE/old.pdf", Currentness.ARCHIVE),
            ("01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL/20_TRANSITION_OU_ACTUEL/maybe.pdf", Currentness.TRANSITION),
        ]

        for path, expected_status in test_cases:
            result = classify_document("abc123", path, config)
            assert result.currentness != Currentness.ACTUEL, \
                f"Path {path} must NOT be classified as actuel"
            assert result.currentness == expected_status, \
                f"Path {path} must be classified as {expected_status}"


class TestMutH2B06CurrentnessPassesActuel:
    """MUT-H2B-06: Currentness gate passes actuel documents."""

    def test_actuel_passes_currentness(self) -> None:
        """Documents in 10_ACTUEL_CONFIRME pass currentness gate."""
        config_path = Path("configs/corpus_zone_routing.yml")
        if not config_path.exists():
            pytest.skip("Zone routing config not found")

        config = load_currentness_config(config_path)
        path = "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL/10_ACTUEL_CONFIRME/prog.pdf"

        result = classify_document("abc123", path, config)

        assert result.currentness == Currentness.ACTUEL, \
            "10_ACTUEL_CONFIRME paths must be classified as actuel"
        assert result.ingest_eligible, \
            "Actuel documents must pass currentness gate"


class TestMutH2B07FormatBlocksUnsupported:
    """MUT-H2B-07: Format gate blocks unsupported formats."""

    def test_ggb_format_blocked(self) -> None:
        """GeoGebra .ggb files are marked UNSUPPORTED."""
        config_path = Path("configs/corpus_zone_routing.yml")
        if not config_path.exists():
            pytest.skip("Zone routing config not found")

        config = load_routing_config(config_path)
        path = "03_RESSOURCES_INTERACTIVES/geometry.ggb"

        disposition, reason, zone, currentness, rights = _determine_disposition(path, config)

        assert disposition == Disposition.UNSUPPORTED, \
            "GeoGebra .ggb files must be UNSUPPORTED"


class TestMutH2B08FormatPassesPDF:
    """MUT-H2B-08: Format gate passes PDF files."""

    def test_pdf_format_accepted(self) -> None:
        """PDF files pass format gate."""
        config_path = Path("configs/corpus_zone_routing.yml")
        if not config_path.exists():
            pytest.skip("Zone routing config not found")

        config = load_routing_config(config_path)
        path = "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL/10_ACTUEL_CONFIRME/prog.pdf"

        disposition, reason, zone, currentness, rights = _determine_disposition(path, config)

        # PDF in ACTUEL_CONFIRME should be INGEST
        assert disposition == Disposition.INGEST, \
            "PDF files in actuel zone must be INGEST eligible"


class TestMutH2B09ZoneRoutingCorrect:
    """MUT-H2B-09: Zone routing assigns correct disposition."""

    def test_admin_zone_excluded(self) -> None:
        """00_ADMIN zone is EXCLUDE."""
        config_path = Path("configs/corpus_zone_routing.yml")
        if not config_path.exists():
            pytest.skip("Zone routing config not found")

        config = load_routing_config(config_path)
        path = "00_ADMIN/SHA256SUMS.txt"

        disposition, reason, zone, currentness, rights = _determine_disposition(path, config)

        assert disposition == Disposition.EXCLUDE, \
            "00_ADMIN zone must be EXCLUDE"

    def test_review_required_for_a_verifier(self) -> None:
        """80_A_VERIFIER zone is REVIEW_REQUIRED."""
        config_path = Path("configs/corpus_zone_routing.yml")
        if not config_path.exists():
            pytest.skip("Zone routing config not found")

        config = load_routing_config(config_path)
        path = "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL/80_A_VERIFIER/doc.pdf"

        disposition, reason, zone, currentness, rights = _determine_disposition(path, config)

        assert disposition == Disposition.REVIEW_REQUIRED, \
            "80_A_VERIFIER zone must be REVIEW_REQUIRED"


class TestMutH2B10GoldenPositiveControlsPass:
    """MUT-H2B-10: Golden corpus positive controls pass."""

    def test_positive_control_finds_actuel_document(self) -> None:
        """Positive control validates actuel documents."""
        control = {
            "control_id": "pos_test",
            "sha256_prefix": "a" * 12,
            "expected_base_disposition": "INGEST",
            "expected_final_disposition": "REVIEW_REQUIRED",
            "expected_currentness": "actuel",
            "expected_gate_statuses": {
                "rights": "PASS",
                "pii": "PASS",
                "authority": "BLOCKED_NOT_CLEARED",
            },
        }
        objects = [
            {
                "content_sha256": "a" * 64,
                "path": "01_EDUSCOL/10_ACTUEL_CONFIRME/prog.pdf",
                "base_disposition": "INGEST",
                "disposition": "REVIEW_REQUIRED",
                "currentness": "actuel",
                "gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": "BLOCKED_NOT_CLEARED",
                },
            },
        ]

        result = _validate_positive_control(control, objects)

        assert result.passed, \
            "Positive control must pass for matching actuel document"


class TestMutH2B11GoldenNegativeControlsBlock:
    """MUT-H2B-11: Golden corpus negative controls block."""

    def test_negative_control_excludes_admin(self) -> None:
        """Negative control validates exclusion."""
        control = {
            "control_id": "neg_test",
            "zone": "00_ADMIN/",
            "expected_count_in_zone": 1,
            "expected_disposition": "EXCLUDE",
        }
        objects = [
            {
                "content_sha256": "a" * 64,
                "path": "00_ADMIN/manifest.txt",
                "disposition": "EXCLUDE",
            },
        ]

        result = _validate_negative_control(control, objects)

        assert result.passed, \
            "Negative control must pass for excluded admin zone"

    def test_negative_control_fails_if_ingested(self) -> None:
        """Negative control fails if document wrongly ingested."""
        control = {
            "control_id": "neg_fail_test",
            "zone": "00_ADMIN/",
            "expected_count_in_zone": 1,
            "expected_disposition": "EXCLUDE",
        }
        objects = [
            {
                "content_sha256": "a" * 64,
                "path": "00_ADMIN/manifest.txt",
                "disposition": "INGEST",  # Wrong! Should be EXCLUDE
            },
        ]

        result = _validate_negative_control(control, objects)

        assert not result.passed, \
            "Negative control must FAIL if admin doc is wrongly ingested"


class TestMutH2B12DispositionSumEqualsTotal:
    """MUT-H2B-12: Disposition sum equals corpus total."""

    def test_expected_totals_sum_to_corpus_total(self) -> None:
        """Expected totals in config must sum to CORPUS_TOTAL."""
        config_path = Path("configs/corpus_zone_routing.yml")
        if not config_path.exists():
            pytest.skip("Zone routing config not found")

        config = yaml.safe_load(config_path.read_text())

        corpus_total = config.get("corpus_total_objects", 0)
        expected_totals = config.get("expected_totals", {})

        totals_sum = sum(expected_totals.values())

        assert totals_sum == corpus_total, \
            f"SUM(expected_totals) = {totals_sum} must equal corpus_total = {corpus_total}"

    def test_corpus_total_is_2584(self) -> None:
        """Corpus total is exactly 2584."""
        config_path = Path("configs/corpus_zone_routing.yml")
        if not config_path.exists():
            pytest.skip("Zone routing config not found")

        config = yaml.safe_load(config_path.read_text())
        corpus_total = config.get("corpus_total_objects", 0)

        assert corpus_total == 2584, \
            f"CORPUS_TOTAL must be 2584, got {corpus_total}"


class TestGateNonVacuityMatrix:
    """Consolidated gate non-vacuity verification."""

    def test_all_gates_have_blocking_path(self) -> None:
        """Every gate must have at least one path that blocks."""
        # Rights gate blocking
        unresolved_evidence = {"rights_status": "UNRESOLVED"}
        result = evaluate_zone("zone_x", unresolved_evidence)
        assert result.status != RightsStatus.RESOLVED, "Rights gate must have blocking path"

        # PII gate blocking
        matches = scan_text_for_pii("email: test@real.com", DEFAULT_PII_PATTERNS)
        assert len(matches) > 0, "PII gate must have blocking path"

        # Currentness gate blocking - use config to test properly
        config_path = Path("configs/corpus_zone_routing.yml")
        if config_path.exists():
            config = load_currentness_config(config_path)
            currentness_result = classify_document("abc", "01_EDUSCOL_OFFICIEL/80_A_VERIFIER/doc.pdf", config)
            assert not currentness_result.ingest_eligible, "Currentness gate must have blocking path"

    def test_all_gates_have_passing_path(self) -> None:
        """Every gate must have at least one path that passes."""
        # Rights gate passing
        resolved_evidence = {"rights_status": "RESOLVED", "recommended_rights_category": "officiel_public"}
        result = evaluate_zone("zone_x", resolved_evidence)
        assert result.status == RightsStatus.RESOLVED, "Rights gate must have passing path"

        # PII gate passing
        matches = scan_text_for_pii("Theoreme de Pythagore", DEFAULT_PII_PATTERNS)
        assert len(matches) == 0, "PII gate must have passing path"

        # Currentness gate passing - use config to test properly
        config_path = Path("configs/corpus_zone_routing.yml")
        if config_path.exists():
            config = load_currentness_config(config_path)
            currentness_result = classify_document("abc", "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL/10_ACTUEL_CONFIRME/prog.pdf", config)
            assert currentness_result.ingest_eligible, "Currentness gate must have passing path"
