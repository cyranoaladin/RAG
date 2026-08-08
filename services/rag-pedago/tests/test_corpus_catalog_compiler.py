"""Tests for corpus catalog compiler — H2-B."""
from pathlib import Path

import pytest

from rag_pedago.imports.corpus_catalog_compiler import (
    Disposition,
    compile_catalog,
    load_routing_config,
)

FIXTURES = Path(__file__).parent.parent / "data" / "fixtures" / "corpus_h2b"


class TestCorpusCatalogCompiler:
    """Test corpus catalog compilation with disposition assignment."""

    @pytest.fixture
    def manifest_path(self) -> Path:
        return FIXTURES / "test_manifest.tsv"

    @pytest.fixture
    def config_path(self) -> Path:
        return FIXTURES / "test_routing_config.yml"

    @pytest.fixture
    def config(self, config_path: Path) -> dict:
        return load_routing_config(config_path)

    def test_compile_catalog_assigns_dispositions(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Compiler assigns exactly one disposition per object."""
        report = compile_catalog(manifest_path, config)

        assert report.corpus_total_objects == 10
        assert len(report.objects) == 10

        # Each object has a disposition
        for obj in report.objects:
            assert obj.disposition is not None
            assert isinstance(obj.disposition, Disposition)

    def test_totals_sum_equals_corpus_total(
        self, manifest_path: Path, config: dict
    ) -> None:
        """SUM(dispositions) = corpus_total_objects."""
        report = compile_catalog(manifest_path, config)

        total = report.totals.total()
        assert total == report.corpus_total_objects
        assert total == 10

    def test_no_duplicate_sha256(
        self, manifest_path: Path, config: dict
    ) -> None:
        """No duplicate SHA256 values (no overlap)."""
        report = compile_catalog(manifest_path, config)

        sha256_values = [obj.sha256 for obj in report.objects]
        assert len(sha256_values) == len(set(sha256_values))

    def test_zone_routing_actuel_confirme(
        self, manifest_path: Path, config: dict
    ) -> None:
        """10_ACTUEL_CONFIRME → INGEST."""
        report = compile_catalog(manifest_path, config)

        actuel_objects = [
            obj for obj in report.objects
            if "/10_ACTUEL_CONFIRME/" in obj.path
        ]
        assert len(actuel_objects) == 1
        assert actuel_objects[0].disposition == Disposition.INGEST
        assert actuel_objects[0].currentness == "actuel"

    def test_zone_routing_transition(
        self, manifest_path: Path, config: dict
    ) -> None:
        """20_TRANSITION_OU_ACTUEL → REVIEW_REQUIRED."""
        report = compile_catalog(manifest_path, config)

        transition_objects = [
            obj for obj in report.objects
            if "/20_TRANSITION_OU_ACTUEL/" in obj.path
        ]
        assert len(transition_objects) == 1
        assert transition_objects[0].disposition == Disposition.REVIEW_REQUIRED
        assert transition_objects[0].currentness == "transition"

    def test_zone_routing_a_verifier(
        self, manifest_path: Path, config: dict
    ) -> None:
        """80_A_VERIFIER → REVIEW_REQUIRED."""
        report = compile_catalog(manifest_path, config)

        a_verifier_objects = [
            obj for obj in report.objects
            if "/80_A_VERIFIER/" in obj.path
        ]
        assert len(a_verifier_objects) == 1
        assert a_verifier_objects[0].disposition == Disposition.REVIEW_REQUIRED
        assert a_verifier_objects[0].currentness == "a_verifier"

    def test_zone_routing_archive(
        self, manifest_path: Path, config: dict
    ) -> None:
        """90_ARCHIVE_CATALOGUE → ARCHIVE_ONLY."""
        report = compile_catalog(manifest_path, config)

        archive_objects = [
            obj for obj in report.objects
            if "/90_ARCHIVE_CATALOGUE/" in obj.path
        ]
        assert len(archive_objects) == 1
        assert archive_objects[0].disposition == Disposition.ARCHIVE_ONLY
        assert archive_objects[0].currentness == "archive"

    def test_zone_routing_admin_excluded(
        self, manifest_path: Path, config: dict
    ) -> None:
        """00_ADMIN/ → EXCLUDE."""
        report = compile_catalog(manifest_path, config)

        admin_objects = [
            obj for obj in report.objects
            if obj.path.startswith("00_ADMIN/")
        ]
        assert len(admin_objects) == 1
        assert admin_objects[0].disposition == Disposition.EXCLUDE

    def test_zone_routing_index_excluded(
        self, manifest_path: Path, config: dict
    ) -> None:
        """00_INDEX_PROVENANCE/ → EXCLUDE."""
        report = compile_catalog(manifest_path, config)

        index_objects = [
            obj for obj in report.objects
            if obj.path.startswith("00_INDEX_PROVENANCE/")
        ]
        assert len(index_objects) == 1
        assert index_objects[0].disposition == Disposition.EXCLUDE

    def test_zone_routing_geogebra_unsupported(
        self, manifest_path: Path, config: dict
    ) -> None:
        """03_RESSOURCES_INTERACTIVES/ → UNSUPPORTED."""
        report = compile_catalog(manifest_path, config)

        ggb_objects = [
            obj for obj in report.objects
            if obj.path.startswith("03_RESSOURCES_INTERACTIVES/")
        ]
        assert len(ggb_objects) == 1
        assert ggb_objects[0].disposition == Disposition.UNSUPPORTED

    def test_zone_routing_nexus_diagnostics(
        self, manifest_path: Path, config: dict
    ) -> None:
        """02_NEXUS_DIAGNOSTICS/ → REVIEW_REQUIRED with nexus_proprietaire."""
        report = compile_catalog(manifest_path, config)

        nexus_objects = [
            obj for obj in report.objects
            if obj.path.startswith("02_NEXUS_DIAGNOSTICS/")
        ]
        assert len(nexus_objects) == 1
        assert nexus_objects[0].disposition == Disposition.REVIEW_REQUIRED

    def test_zone_routing_complements(
        self, manifest_path: Path, config: dict
    ) -> None:
        """04_COMPLEMENTS_PEDAGOGIQUES/ → REVIEW_REQUIRED."""
        report = compile_catalog(manifest_path, config)

        complement_objects = [
            obj for obj in report.objects
            if obj.path.startswith("04_COMPLEMENTS_PEDAGOGIQUES/")
        ]
        assert len(complement_objects) == 2
        for obj in complement_objects:
            assert obj.disposition == Disposition.REVIEW_REQUIRED

    def test_verification_passes_for_valid_catalog(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Verification passes when totals match."""
        report = compile_catalog(manifest_path, config)
        assert report.verification_passed
        assert len(report.verification_errors) == 0

    def test_expected_disposition_totals(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Check expected totals match fixture."""
        report = compile_catalog(manifest_path, config)

        # Based on the fixture:
        # 1 INGEST (10_ACTUEL_CONFIRME)
        # 5 REVIEW_REQUIRED (transition + a_verifier + nexus + 2 complements)
        # 0 QUARANTINE
        # 1 ARCHIVE_ONLY
        # 2 EXCLUDE (admin + index)
        # 1 UNSUPPORTED (geogebra)
        assert report.totals.ingest == 1
        assert report.totals.review_required == 5
        assert report.totals.quarantine == 0
        assert report.totals.archive_only == 1
        assert report.totals.exclude == 2
        assert report.totals.unsupported == 1


class TestDispositionCoverageInvariant:
    """Test the SUM(dispositions) = TOTAL invariant."""

    @pytest.fixture
    def manifest_path(self) -> Path:
        return FIXTURES / "test_manifest.tsv"

    @pytest.fixture
    def config(self) -> dict:
        return load_routing_config(FIXTURES / "test_routing_config.yml")

    def test_every_object_has_exactly_one_disposition(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Each object receives exactly one disposition (no gap, no overlap)."""
        report = compile_catalog(manifest_path, config)

        # Count by disposition
        by_disposition = {}
        for obj in report.objects:
            key = obj.disposition.value
            by_disposition[key] = by_disposition.get(key, 0) + 1

        # Verify counts match totals
        assert by_disposition.get("INGEST", 0) == report.totals.ingest
        assert by_disposition.get("REVIEW_REQUIRED", 0) == report.totals.review_required
        assert by_disposition.get("QUARANTINE", 0) == report.totals.quarantine
        assert by_disposition.get("ARCHIVE_ONLY", 0) == report.totals.archive_only
        assert by_disposition.get("EXCLUDE", 0) == report.totals.exclude
        assert by_disposition.get("UNSUPPORTED", 0) == report.totals.unsupported

        # Sum equals total objects
        assert sum(by_disposition.values()) == report.corpus_total_objects
