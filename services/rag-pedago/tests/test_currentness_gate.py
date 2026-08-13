"""Tests for currentness classification gate — H2-B."""
from pathlib import Path

import pytest

from rag_pedago.imports.currentness_gate import (
    Currentness,
    classify_document,
    evaluate_currentness_gate,
    load_config,
)

FIXTURES = Path(__file__).parent.parent / "data" / "fixtures" / "corpus_h2b"


class TestCurrentnessClassification:
    """Test document currentness classification."""

    @pytest.fixture
    def config(self) -> dict:
        return load_config(FIXTURES / "test_routing_config.yml")

    def test_actuel_confirme_is_actuel(self, config: dict) -> None:
        """10_ACTUEL_CONFIRME → actuel."""
        classification = classify_document(
            sha256="abc123",
            path="01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL_MULTI_NIVEAUX/10_ACTUEL_CONFIRME/prog.pdf",
            config=config,
        )
        assert classification.currentness == Currentness.ACTUEL
        assert classification.ingest_eligible is True
        assert classification.disposition_recommendation == "INGEST"

    def test_transition_is_transition(self, config: dict) -> None:
        """20_TRANSITION_OU_ACTUEL → transition."""
        classification = classify_document(
            sha256="abc123",
            path="01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL_MULTI_NIVEAUX/20_TRANSITION_OU_ACTUEL/res.pdf",
            config=config,
        )
        assert classification.currentness == Currentness.TRANSITION
        assert classification.ingest_eligible is False
        assert classification.disposition_recommendation == "REVIEW_REQUIRED"

    def test_a_verifier_is_a_verifier(self, config: dict) -> None:
        """80_A_VERIFIER → a_verifier."""
        classification = classify_document(
            sha256="abc123",
            path="01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL_MULTI_NIVEAUX/80_A_VERIFIER/doc.pdf",
            config=config,
        )
        assert classification.currentness == Currentness.A_VERIFIER
        assert classification.ingest_eligible is False
        assert classification.disposition_recommendation == "REVIEW_REQUIRED"

    def test_archive_is_archive(self, config: dict) -> None:
        """90_ARCHIVE_CATALOGUE → archive."""
        classification = classify_document(
            sha256="abc123",
            path="01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/TRANSVERSAL_MULTI_NIVEAUX/90_ARCHIVE_CATALOGUE/old.pdf",
            config=config,
        )
        assert classification.currentness == Currentness.ARCHIVE
        assert classification.ingest_eligible is False
        assert classification.disposition_recommendation == "ARCHIVE_ONLY"

    def test_unknown_path_is_unclassified(self, config: dict) -> None:
        """Unknown path → unclassified."""
        classification = classify_document(
            sha256="abc123",
            path="01_EDUSCOL_OFFICIEL/UNKNOWN_ZONE/doc.pdf",
            config=config,
        )
        assert classification.currentness == Currentness.UNCLASSIFIED
        assert classification.ingest_eligible is False
        assert classification.disposition_recommendation == "REVIEW_REQUIRED"


class TestCurrentnessGate:
    """Test currentness gate evaluation."""

    @pytest.fixture
    def manifest_path(self) -> Path:
        return FIXTURES / "test_manifest.tsv"

    @pytest.fixture
    def config(self) -> dict:
        return load_config(FIXTURES / "test_routing_config.yml")

    def test_gate_evaluates_eduscol_documents(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Gate only evaluates Eduscol documents."""
        report = evaluate_currentness_gate(manifest_path, config)

        # Should have 4 Eduscol documents in test fixture
        assert report.total_documents == 4

    def test_counts_by_currentness(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Counts by currentness are correct."""
        report = evaluate_currentness_gate(manifest_path, config)

        # Based on fixture: 1 actuel, 1 transition, 1 a_verifier, 1 archive
        assert report.by_currentness.get("actuel", 0) == 1
        assert report.by_currentness.get("transition", 0) == 1
        assert report.by_currentness.get("a_verifier", 0) == 1
        assert report.by_currentness.get("archive", 0) == 1

    def test_ingest_eligible_count(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Only actuel documents are ingest eligible."""
        report = evaluate_currentness_gate(manifest_path, config)

        # Only 1 actuel document
        assert report.ingest_eligible_count == 1

    def test_gate_passes_when_complete(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Gate passes when all documents are classified."""
        report = evaluate_currentness_gate(manifest_path, config)

        # All 4 documents should be classified
        assert report.coverage_complete
        assert report.gate_passed
        assert "PASS" in report.gate_status

    def test_empty_manifest_is_not_complete(
        self, tmp_path: Path, config: dict
    ) -> None:
        manifest = tmp_path / "empty.tsv"
        manifest.write_text(
            "sha256\tchemin_technique_existant\n",
            encoding="utf-8",
        )

        report = evaluate_currentness_gate(manifest, config)

        assert report.total_documents == 0
        assert report.coverage_complete is False
        assert report.gate_passed is False
        assert report.gate_status == "BLOCKED_MANIFEST_PERIMETER_INCOMPLETE"

    def test_renamed_identity_headers_fail_closed(
        self, tmp_path: Path, config: dict
    ) -> None:
        manifest = tmp_path / "renamed.tsv"
        manifest.write_text(
            "digest\tlocation\n"
            f"{'a' * 64}\t01_EDUSCOL_OFFICIEL/10_ACTUEL_CONFIRME/a.pdf\n",
            encoding="utf-8",
        )

        report = evaluate_currentness_gate(manifest, config)

        assert report.manifest_schema_valid is False
        assert report.malformed_manifest_rows == 1
        assert report.coverage_complete is False
        assert report.gate_passed is False

    @pytest.mark.parametrize(
        "row",
        [
            "\t01_EDUSCOL_OFFICIEL/10_ACTUEL_CONFIRME/a.pdf\n",
            f"{'a' * 64}\t\n",
            "not-a-sha\t01_EDUSCOL_OFFICIEL/10_ACTUEL_CONFIRME/a.pdf\n",
        ],
        ids=("missing-sha", "missing-path", "malformed-sha"),
    )
    def test_malformed_manifest_rows_make_coverage_incomplete(
        self, tmp_path: Path, config: dict, row: str
    ) -> None:
        manifest = tmp_path / "malformed.tsv"
        manifest.write_text(
            "sha256\tchemin_technique_existant\tfamille\n" + row.rstrip("\n") + "\teduscol\n",
            encoding="utf-8",
        )

        report = evaluate_currentness_gate(manifest, config)

        assert report.manifest_rows == 1
        assert report.malformed_manifest_rows == 1
        assert report.skipped_eduscol_rows == 1
        assert report.coverage_complete is False
        assert report.gate_passed is False

    @pytest.mark.parametrize(
        ("famille", "url_source"),
        [
            ("eduscol", ""),
            ("", "https://eduscol.education.gouv.fr/resource.pdf"),
        ],
        ids=("eduscol-family", "eduscol-source-url"),
    )
    def test_valid_eduscol_identity_outside_canonical_prefix_fails_closed(
        self,
        tmp_path: Path,
        config: dict,
        famille: str,
        url_source: str,
    ) -> None:
        manifest = tmp_path / "off-prefix.tsv"
        manifest.write_text(
            "sha256\tchemin_technique_existant\tfamille\turl_source\n"
            f"{'a' * 64}\t02_NEXUS_DIAGNOSTICS/conflict.pdf\t"
            f"{famille}\t{url_source}\n",
            encoding="utf-8",
        )

        report = evaluate_currentness_gate(manifest, config)

        assert report.manifest_rows == 1
        assert report.eduscol_manifest_rows == 1
        assert report.total_documents == 0
        assert report.skipped_eduscol_rows == 1
        assert report.coverage_complete is False
        assert report.gate_passed is False
        assert report.gate_status == "BLOCKED_MANIFEST_PERIMETER_INCOMPLETE"


class TestCurrentnessInvariants:
    """Test currentness classification invariants."""

    @pytest.fixture
    def config(self) -> dict:
        return load_config(FIXTURES / "test_routing_config.yml")

    def test_only_actuel_is_ingest_eligible(self, config: dict) -> None:
        """Only actuel documents are ingest eligible."""
        test_cases = [
            ("01_EDUSCOL_OFFICIEL/.../10_ACTUEL_CONFIRME/doc.pdf", True),
            ("01_EDUSCOL_OFFICIEL/.../20_TRANSITION_OU_ACTUEL/doc.pdf", False),
            ("01_EDUSCOL_OFFICIEL/.../80_A_VERIFIER/doc.pdf", False),
            ("01_EDUSCOL_OFFICIEL/.../90_ARCHIVE_CATALOGUE/doc.pdf", False),
        ]

        for path, expected_eligible in test_cases:
            classification = classify_document("sha", path, config)
            assert classification.ingest_eligible == expected_eligible, f"Failed for {path}"

    def test_currentness_disposition_mapping(self, config: dict) -> None:
        """Currentness maps to correct disposition."""
        mappings = [
            (Currentness.ACTUEL, "INGEST"),
            (Currentness.TRANSITION, "REVIEW_REQUIRED"),
            (Currentness.A_VERIFIER, "REVIEW_REQUIRED"),
            (Currentness.ARCHIVE, "ARCHIVE_ONLY"),
            (Currentness.CONFLICT, "QUARANTINE"),
            (Currentness.UNCLASSIFIED, "REVIEW_REQUIRED"),
        ]

        for currentness, expected_disposition in mappings:
            # Create a path that matches the currentness
            path_map = {
                Currentness.ACTUEL: "01_EDUSCOL_OFFICIEL/.../10_ACTUEL_CONFIRME/d.pdf",
                Currentness.TRANSITION: "01_EDUSCOL_OFFICIEL/.../20_TRANSITION_OU_ACTUEL/d.pdf",
                Currentness.A_VERIFIER: "01_EDUSCOL_OFFICIEL/.../80_A_VERIFIER/d.pdf",
                Currentness.ARCHIVE: "01_EDUSCOL_OFFICIEL/.../90_ARCHIVE_CATALOGUE/d.pdf",
                Currentness.CONFLICT: "01_EDUSCOL_OFFICIEL/.../99_CONFLITS_STATUTS/d.pdf",
                Currentness.UNCLASSIFIED: "01_EDUSCOL_OFFICIEL/UNKNOWN/d.pdf",
            }
            path = path_map.get(currentness, "01_EDUSCOL_OFFICIEL/UNKNOWN/d.pdf")
            classification = classify_document("sha", path, config)

            if classification.currentness == currentness:
                assert classification.disposition_recommendation == expected_disposition, \
                    f"Failed for {currentness}"
