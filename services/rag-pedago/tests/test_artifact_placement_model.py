"""Tests for Artifact-Placement Model — H2-B.

CRITICAL: Tests verify FAIL-CLOSED semantics.
Any blocking disposition MUST override INGEST.
"""
from rag_pedago.imports.artifact_placement_model import (
    DISPOSITION_PRECEDENCE,
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
        assert artifact.final_disposition == Disposition.INGEST

    def test_artifact_multi_placement_blocking_wins(self) -> None:
        """FAIL-CLOSED: Blocking disposition wins over INGEST."""
        artifact = CorpusArtifact(
            sha256="def456",
            size_bytes=2048,
        )
        # Add INGEST placement first
        artifact.add_placement(CorpusPlacement(
            path="01_EDUSCOL/maths/suites.pdf",
            zone="01_EDUSCOL",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current version",
        ))
        # Add ARCHIVE placement second
        artifact.add_placement(CorpusPlacement(
            path="99_ARCHIVE/old/suites.pdf",
            zone="99_ARCHIVE",
            currentness=Currentness.ARCHIVE,
            disposition=Disposition.ARCHIVE_ONLY,
            disposition_reason="Archived version",
        ))
        # ARCHIVE_ONLY must block INGEST (fail-closed)
        assert artifact.placement_count == 2
        assert artifact.final_disposition == Disposition.ARCHIVE_ONLY

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


class TestDispositionPrecedence:
    """Test FAIL-CLOSED disposition precedence."""

    def test_exclude_has_highest_precedence(self) -> None:
        """EXCLUDE blocks everything (lowest number)."""
        assert DISPOSITION_PRECEDENCE[Disposition.EXCLUDE] == 0

    def test_ingest_has_lowest_precedence(self) -> None:
        """INGEST only wins if nothing blocks (highest number)."""
        assert DISPOSITION_PRECEDENCE[Disposition.INGEST] == 5

    def test_precedence_order_is_fail_closed(self) -> None:
        """Precedence order: EXCLUDE > QUARANTINE > UNSUPPORTED > ARCHIVE > REVIEW > INGEST."""
        order = sorted(Disposition, key=lambda d: DISPOSITION_PRECEDENCE[d])
        expected = [
            Disposition.EXCLUDE,
            Disposition.QUARANTINE,
            Disposition.UNSUPPORTED,
            Disposition.ARCHIVE_ONLY,
            Disposition.REVIEW_REQUIRED,
            Disposition.INGEST,
        ]
        assert order == expected


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

        # Multi-placement artifact (final = ARCHIVE_ONLY due to fail-closed)
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


class TestFailClosedMutations:
    """H2-B CRITICAL: Prove fail-closed semantics with mutation tests."""

    def test_mut_fc_01_exclude_blocks_ingest(self) -> None:
        """MUT-FC-01: EXCLUDE + INGEST → EXCLUDE (never INGEST)."""
        artifact = CorpusArtifact(sha256="fc01", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/current/doc.pdf", zone="current",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current",
        ))
        artifact.add_placement(CorpusPlacement(
            path="/admin/doc.pdf", zone="admin",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.EXCLUDE,
            disposition_reason="Admin metadata",
        ))
        assert artifact.final_disposition == Disposition.EXCLUDE, \
            "EXCLUDE must block INGEST"

    def test_mut_fc_02_quarantine_blocks_ingest(self) -> None:
        """MUT-FC-02: QUARANTINE + INGEST → QUARANTINE (PII signal)."""
        artifact = CorpusArtifact(sha256="fc02", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/current/doc.pdf", zone="current",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current",
        ))
        artifact.add_placement(CorpusPlacement(
            path="/quarantine/doc.pdf", zone="quarantine",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.QUARANTINE,
            disposition_reason="PII signal detected",
        ))
        assert artifact.final_disposition == Disposition.QUARANTINE, \
            "QUARANTINE must block INGEST"

    def test_mut_fc_03_unsupported_blocks_ingest(self) -> None:
        """MUT-FC-03: UNSUPPORTED + INGEST → UNSUPPORTED."""
        artifact = CorpusArtifact(sha256="fc03", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/current/doc.pdf", zone="current",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current",
        ))
        artifact.add_placement(CorpusPlacement(
            path="/interactive/doc.ggb", zone="interactive",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.UNSUPPORTED,
            disposition_reason="GeoGebra format",
        ))
        assert artifact.final_disposition == Disposition.UNSUPPORTED, \
            "UNSUPPORTED must block INGEST"

    def test_mut_fc_04_archive_blocks_ingest(self) -> None:
        """MUT-FC-04: ARCHIVE_ONLY + INGEST → ARCHIVE_ONLY."""
        artifact = CorpusArtifact(sha256="fc04", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/current/doc.pdf", zone="current",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current",
        ))
        artifact.add_placement(CorpusPlacement(
            path="/archive/doc.pdf", zone="archive",
            currentness=Currentness.ARCHIVE,
            disposition=Disposition.ARCHIVE_ONLY,
            disposition_reason="Superseded",
        ))
        assert artifact.final_disposition == Disposition.ARCHIVE_ONLY, \
            "ARCHIVE_ONLY must block INGEST"

    def test_mut_fc_05_review_blocks_ingest(self) -> None:
        """MUT-FC-05: REVIEW_REQUIRED + INGEST → REVIEW_REQUIRED."""
        artifact = CorpusArtifact(sha256="fc05", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/current/doc.pdf", zone="current",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current",
        ))
        artifact.add_placement(CorpusPlacement(
            path="/review/doc.pdf", zone="review",
            currentness=Currentness.A_VERIFIER,
            disposition=Disposition.REVIEW_REQUIRED,
            disposition_reason="Rights unresolved",
        ))
        assert artifact.final_disposition == Disposition.REVIEW_REQUIRED, \
            "REVIEW_REQUIRED must block INGEST"

    def test_mut_fc_06_only_ingest_produces_ingest(self) -> None:
        """MUT-FC-06: ALL placements INGEST → INGEST."""
        artifact = CorpusArtifact(sha256="fc06", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/eduscol/doc.pdf", zone="eduscol",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Cleared",
        ))
        artifact.add_placement(CorpusPlacement(
            path="/nexus/doc.pdf", zone="nexus",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Cleared",
        ))
        assert artifact.final_disposition == Disposition.INGEST, \
            "All INGEST placements → INGEST"


class TestMutationTests:
    """Additional H2-B mutation tests for artifact/placement model."""

    def test_mut_apm_01_single_placement_returns_its_disposition(self) -> None:
        """MUT-APM-01: Single placement returns its own disposition."""
        artifact = CorpusArtifact(sha256="mut01", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/review/check.pdf", zone="review",
            currentness=Currentness.A_VERIFIER,
            disposition=Disposition.REVIEW_REQUIRED,
            disposition_reason="Needs review",
        ))
        assert artifact.final_disposition == Disposition.REVIEW_REQUIRED

    def test_mut_apm_02_no_placement_returns_review_required(self) -> None:
        """MUT-APM-02: Artifact with no placements defaults to REVIEW_REQUIRED."""
        artifact = CorpusArtifact(sha256="mut02", size_bytes=100)
        assert artifact.final_disposition == Disposition.REVIEW_REQUIRED, \
            "Orphan artifacts must default to REVIEW_REQUIRED"

    def test_mut_apm_03_placement_count_increments(self) -> None:
        """MUT-APM-03: Placement count increments correctly."""
        artifact = CorpusArtifact(sha256="mut03", size_bytes=100)
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

    def test_mut_apm_04_catalog_verification_fails_on_orphan(self) -> None:
        """MUT-APM-04: Verification fails if artifact has no placements."""
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

    def test_mut_apm_05_controlling_placement_is_blocking_one(self) -> None:
        """MUT-APM-05: controlling_placement returns the blocking placement."""
        artifact = CorpusArtifact(sha256="mut05", size_bytes=100)
        p_ingest = CorpusPlacement(
            path="/current/new.pdf", zone="current",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.INGEST,
            disposition_reason="Current",
        )
        p_exclude = CorpusPlacement(
            path="/admin/meta.txt", zone="admin",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.EXCLUDE,
            disposition_reason="Admin file",
        )
        artifact.add_placement(p_ingest)
        artifact.add_placement(p_exclude)

        assert artifact.controlling_placement is p_exclude, \
            "controlling_placement must return the EXCLUDE placement"

    def test_mut_apm_06_exclude_beats_quarantine(self) -> None:
        """MUT-APM-06: EXCLUDE beats QUARANTINE (structural > safety)."""
        artifact = CorpusArtifact(sha256="mut06", size_bytes=100)
        artifact.add_placement(CorpusPlacement(
            path="/quarantine/pii.pdf", zone="quarantine",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.QUARANTINE,
            disposition_reason="PII",
        ))
        artifact.add_placement(CorpusPlacement(
            path="/admin/meta.txt", zone="admin",
            currentness=Currentness.ACTUEL,
            disposition=Disposition.EXCLUDE,
            disposition_reason="Admin",
        ))
        assert artifact.final_disposition == Disposition.EXCLUDE, \
            "EXCLUDE must beat QUARANTINE"
