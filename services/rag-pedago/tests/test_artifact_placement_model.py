"""Tests for Artifact-Placement Model — H2-B."""
from rag_pedago.imports.artifact_placement_model import (
    DISPOSITION_PRIORITY,
    ArtifactPlacementCatalog,
    CorpusArtifact,
    CorpusPlacement,
    Currentness,
    Disposition,
)


class TestCorpusPlacement:
    """Test CorpusPlacement model."""

    def test_placement_to_dict(self) -> None:
        """Placement serializes correctly."""
        placement = CorpusPlacement(
            path="01_EDUSCOL/maths/terminale/suites.pdf",
            zone="01_EDUSCOL",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current programme, eligible for ingestion",
        )
        result = placement.to_dict()
        assert result["path"] == "01_EDUSCOL/maths/terminale/suites.pdf"
        assert result["currentness"] == "actuel"
        assert result["disposition"] == "INGEST"


class TestCorpusArtifact:
    """Test CorpusArtifact model."""

    def test_artifact_single_placement(self) -> None:
        """Artifact with single placement."""
        artifact = CorpusArtifact(
            sha256="abc123",
            size_bytes=1024,
        )
        artifact.add_placement(CorpusPlacement(
            path="01_EDUSCOL/maths/suites.pdf",
            zone="01_EDUSCOL",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Test",
        ))
        assert artifact.placement_count == 1
        assert artifact.best_disposition == Disposition.INGEST

    def test_artifact_multi_placement_best_wins(self) -> None:
        """Artifact with multiple placements uses best disposition."""
        artifact = CorpusArtifact(
            sha256="def456",
            size_bytes=2048,
        )
        # Add ARCHIVE placement first
        artifact.add_placement(CorpusPlacement(
            path="99_ARCHIVE/old/suites.pdf",
            zone="99_ARCHIVE",
            currentness=Currentness.ARCHIVE,
            disposition=Disposition.ARCHIVE_ONLY,
            disposition_reason="Archived version",
        ))
        # Add INGEST placement second
        artifact.add_placement(CorpusPlacement(
            path="01_EDUSCOL/maths/suites.pdf",
            zone="01_EDUSCOL",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current version",
        ))
        # Best should be INGEST (more favorable)
        assert artifact.placement_count == 2
        assert artifact.best_disposition == Disposition.INGEST

    def test_artifact_zones_property(self) -> None:
        """Artifact zones property collects all zones."""
        artifact = CorpusArtifact(sha256="ghi789", size_bytes=512)
        artifact.add_placement(CorpusPlacement(
            path="01_EDUSCOL/a.pdf", zone="01_EDUSCOL",
            currentness=Currentness.ACTUEL, disposition=Disposition.INGEST,
            disposition_reason="",
        ))
        artifact.add_placement(CorpusPlacement(
            path="02_NEXUS/a.pdf", zone="02_NEXUS",
            currentness=Currentness.ACTUEL, disposition=Disposition.INGEST,
            disposition_reason="",
        ))
        assert artifact.zones == {"01_EDUSCOL", "02_NEXUS"}

    def test_artifact_pii_fields(self) -> None:
        """Artifact can track PII scan results."""
        artifact = CorpusArtifact(sha256="pii123", size_bytes=100)
        artifact.pii_scanned = True
        artifact.pii_detected = True
        artifact.pii_signal_classes = ["email_address", "phone_french"]
        artifact.pii_signal_count = 3

        result = artifact.to_dict(include_placements=False)
        assert result["pii_scanned"] is True
        assert result["pii_detected"] is True
        assert "email_address" in result["pii_signal_classes"]
        assert result["pii_signal_count"] == 3


class TestDispositionPriority:
    """Test disposition priority ordering."""

    def test_ingest_is_best(self) -> None:
        """INGEST has highest priority (lowest number)."""
        assert DISPOSITION_PRIORITY[Disposition.INGEST] == 0

    def test_unsupported_is_worst(self) -> None:
        """UNSUPPORTED has lowest priority (highest number)."""
        assert DISPOSITION_PRIORITY[Disposition.UNSUPPORTED] == 5

    def test_priority_order(self) -> None:
        """Priority order is correct."""
        priorities = sorted(Disposition, key=lambda d: DISPOSITION_PRIORITY[d])
        expected = [
            Disposition.INGEST,
            Disposition.REVIEW_REQUIRED,
            Disposition.QUARANTINE,
            Disposition.ARCHIVE_ONLY,
            Disposition.EXCLUDE,
            Disposition.UNSUPPORTED,
        ]
        assert priorities == expected


class TestArtifactPlacementCatalog:
    """Test ArtifactPlacementCatalog."""

    def test_catalog_add_artifact(self) -> None:
        """Catalog tracks artifacts by SHA256."""
        catalog = ArtifactPlacementCatalog(
            config_id="test",
            manifest_path="test.tsv",
            manifest_sha256="abc",
            compiled_at="2026-08-08T00:00:00Z",
        )
        artifact = CorpusArtifact(sha256="sha1", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/a.pdf", zone="test", currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST, disposition_reason="",
        ))
        catalog.add_artifact(artifact)

        assert catalog.artifact_count == 1
        assert catalog.get_artifact("sha1") is artifact

    def test_catalog_deduplicates_by_sha256(self) -> None:
        """Same SHA256 updates existing artifact, not duplicate."""
        catalog = ArtifactPlacementCatalog(
            config_id="test",
            manifest_path="test.tsv",
            manifest_sha256="abc",
            compiled_at="2026-08-08T00:00:00Z",
        )
        # First artifact
        a1 = CorpusArtifact(sha256="same_sha", size_bytes=100)
        a1.add_placement(CorpusPlacement(
            path="/a.pdf", zone="test", currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST, disposition_reason="",
        ))
        catalog.add_artifact(a1)

        # Second artifact with same SHA256 - should replace
        a2 = CorpusArtifact(sha256="same_sha", size_bytes=200)
        a2.add_placement(CorpusPlacement(
            path="/b.pdf", zone="test", currentness=Currentness.ARCHIVE,
            disposition=Disposition.ARCHIVE_ONLY, disposition_reason="",
        ))
        catalog.add_artifact(a2)

        # Should have only 1 artifact (the second one replaced the first)
        assert catalog.artifact_count == 1
        assert catalog.get_artifact("same_sha") is a2

    def test_catalog_compute_stats(self) -> None:
        """Catalog computes correct statistics."""
        catalog = ArtifactPlacementCatalog(
            config_id="test",
            manifest_path="test.tsv",
            manifest_sha256="abc",
            compiled_at="2026-08-08T00:00:00Z",
        )
        # Single-placement artifact
        a1 = CorpusArtifact(sha256="sha1", size_bytes=100)
        a1.add_placement(CorpusPlacement(
            path="/a.pdf", zone="test", currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST, disposition_reason="",
        ))
        catalog.add_artifact(a1)

        # Multi-placement artifact
        a2 = CorpusArtifact(sha256="sha2", size_bytes=200)
        a2.add_placement(CorpusPlacement(
            path="/b1.pdf", zone="test", currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST, disposition_reason="",
        ))
        a2.add_placement(CorpusPlacement(
            path="/b2.pdf", zone="test", currentness=Currentness.ARCHIVE,
            disposition=Disposition.ARCHIVE_ONLY, disposition_reason="",
        ))
        catalog.add_artifact(a2)

        catalog.compute_stats()

        assert catalog.artifact_count == 2
        assert catalog.placement_count == 3
        assert catalog.single_placement_count == 1
        assert catalog.multi_placement_count == 1
        assert catalog.max_placements_per_artifact == 2


class TestMutationTests:
    """H2-B mutation tests for artifact/placement model."""

    def test_mut_apm_01_best_disposition_selects_ingest_over_archive(self) -> None:
        """MUT-APM-01: Best disposition prefers INGEST over ARCHIVE."""
        artifact = CorpusArtifact(sha256="mut01", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/archive/old.pdf", zone="archive",
            currentness=Currentness.ARCHIVE,
            disposition=Disposition.ARCHIVE_ONLY,
            disposition_reason="Archived",
        ))
        artifact.add_placement(CorpusPlacement(
            path="/current/new.pdf", zone="current",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current",
        ))
        assert artifact.best_disposition == Disposition.INGEST, \
            "INGEST must win over ARCHIVE_ONLY"

    def test_mut_apm_02_single_placement_returns_its_disposition(self) -> None:
        """MUT-APM-02: Single placement returns its own disposition."""
        artifact = CorpusArtifact(sha256="mut02", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/review/check.pdf", zone="review",
            currentness=Currentness.A_VERIFIER,
            disposition=Disposition.REVIEW_REQUIRED,
            disposition_reason="Needs review",
        ))
        assert artifact.best_disposition == Disposition.REVIEW_REQUIRED

    def test_mut_apm_03_no_placement_returns_review_required(self) -> None:
        """MUT-APM-03: Artifact with no placements defaults to REVIEW_REQUIRED."""
        artifact = CorpusArtifact(sha256="mut03", size_bytes=100)
        assert artifact.best_disposition == Disposition.REVIEW_REQUIRED, \
            "Orphan artifacts must default to REVIEW_REQUIRED"

    def test_mut_apm_04_placement_count_increments(self) -> None:
        """MUT-APM-04: Placement count increments correctly."""
        artifact = CorpusArtifact(sha256="mut04", size_bytes=100)
        assert artifact.placement_count == 0
        artifact.add_placement(CorpusPlacement(
            path="/a.pdf", zone="test", currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST, disposition_reason="",
        ))
        assert artifact.placement_count == 1
        artifact.add_placement(CorpusPlacement(
            path="/b.pdf", zone="test", currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST, disposition_reason="",
        ))
        assert artifact.placement_count == 2

    def test_mut_apm_05_catalog_verification_fails_on_orphan(self) -> None:
        """MUT-APM-05: Verification fails if artifact has no placements."""
        catalog = ArtifactPlacementCatalog(
            config_id="test",
            manifest_path="test.tsv",
            manifest_sha256="abc",
            compiled_at="2026-08-08T00:00:00Z",
            expected_artifact_count=1,
            expected_placement_count=1,
        )
        # Add orphan artifact (no placements)
        orphan = CorpusArtifact(sha256="orphan", size_bytes=100)
        catalog.add_artifact(orphan)
        catalog.verify()

        assert not catalog.verification_passed
        assert any("ORPHAN" in e for e in catalog.verification_errors)

    def test_mut_apm_06_best_placement_returns_correct_one(self) -> None:
        """MUT-APM-06: best_placement returns the placement with best disposition."""
        artifact = CorpusArtifact(sha256="mut06", size_bytes=100)
        p1 = CorpusPlacement(
            path="/archive/old.pdf", zone="archive",
            currentness=Currentness.ARCHIVE,
            disposition=Disposition.ARCHIVE_ONLY,
            disposition_reason="Archived",
        )
        p2 = CorpusPlacement(
            path="/current/new.pdf", zone="current",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current",
        )
        artifact.add_placement(p1)
        artifact.add_placement(p2)

        assert artifact.best_placement is p2, \
            "best_placement must return the INGEST placement"
