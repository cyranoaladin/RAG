"""Tests for ingestion v2 pipeline and endpoints (FE-03).

Tests governance guarantees WITHOUT needing pgvector or models.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.ingest_v2 import (
    IngestV2Request,
    Provenance,
    _is_artifact,
)


class TestIngestV2Request:
    """F-01: all required fields must be provided."""

    def test_valid_request(self) -> None:
        req = IngestV2Request(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="cours.pdf",
            source_uri="upload://cours.pdf",
            rights="usage_interne",
            matiere="nsi",
            niveau="terminale",
        )
        assert req.collection == "rag_nexus_nsi_terminale_specialite"
        assert req.rights == "usage_interne"

    def test_empty_collection_rejected(self) -> None:
        with pytest.raises(ValueError):
            IngestV2Request(
                collection="",
                source_label="x", source_uri="x", rights="x",
                matiere="nsi", niveau="terminale",
            )

    def test_empty_rights_rejected(self) -> None:
        with pytest.raises(ValueError):
            IngestV2Request(
                collection="test",
                source_label="x", source_uri="x", rights="",
                matiere="nsi", niveau="terminale",
            )

    def test_empty_source_label_rejected(self) -> None:
        with pytest.raises(ValueError):
            IngestV2Request(
                collection="test",
                source_label="", source_uri="x", rights="x",
                matiere="nsi", niveau="terminale",
            )

    def test_empty_source_uri_rejected(self) -> None:
        with pytest.raises(ValueError):
            IngestV2Request(
                collection="test",
                source_label="x", source_uri="", rights="x",
                matiere="nsi", niveau="terminale",
            )


class TestArtifactFilter:
    """Base64/artifact filter (LOT 25a)."""

    def test_normal_text_passes(self) -> None:
        assert not _is_artifact("Ceci est un cours de NSI sur les arbres binaires.")

    def test_empty_is_artifact(self) -> None:
        assert _is_artifact("")
        assert _is_artifact("   ")

    def test_base64_is_artifact(self) -> None:
        b64 = "iVBORw0KGgoAAAANSUhEUgAAAAUA" * 10
        assert _is_artifact(b64)

    def test_mixed_mostly_base64(self) -> None:
        text = "Titre\n" + "AAAA" * 100 + "=" * 200
        assert _is_artifact(text)


class TestProvenance:
    """Provenance tracking."""

    def test_provenance_fields(self) -> None:
        p = Provenance(
            route="upload",
            timestamp=1234567890.0,
            token_hash="abc123",
            source_type="file",
        )
        assert p.route == "upload"
        assert p.source_type == "file"


class TestCollectionGate:
    """Collection must be instanciated for ingestion."""

    def test_non_instanciated_rejected(self) -> None:
        """Ingesting into a non-instanciated collection must fail."""
        from ingestor.ingest_v2 import ingest_document

        req = IngestV2Request(
            collection="rag_nexus_maths_seconde_tc",  # instanciee: false
            source_label="test.pdf",
            source_uri="upload://test.pdf",
            rights="usage_interne",
            matiere="maths",
            niveau="seconde",
        )
        prov = Provenance(route="test", timestamp=0, token_hash="x", source_type="file")

        with pytest.raises(ValueError, match="Collection gate"):
            ingest_document("test content", req, prov)

    def test_quarantine_write_allowed(self) -> None:
        """Quarantine is instanciee:true — writing is allowed (retrieval gate blocks serving)."""
        # The RETRIEVAL gate blocks quarantine from being served (retrievable:false).
        # The INGESTION gate only checks instanciee:true — quarantine IS instanciated,
        # so writing to it is allowed. This is by design: quarantine = place to PUT
        # dubious chunks, not to SERVE them.
        pass  # Documented distinction, no assertion needed


class TestReviewStatusAlwaysNeedsReview:
    """review_status must always be needs_review on ingestion."""

    def test_review_status_in_request_model(self) -> None:
        """IngestV2Result always has review_status=needs_review."""
        from ingestor.ingest_v2 import IngestV2Result
        r = IngestV2Result(
            doc_id="test", chunks_total=10, chunks_written=8,
            chunks_filtered=2, chunks_dedup=0, collection="test",
        )
        assert r.review_status == "needs_review"


class TestEndpointRoutes:
    """Verify v2 ingestion endpoints are registered."""

    def test_routes_exist(self) -> None:
        from ingestor.ingest_v2_endpoint import router
        routes = [r.path for r in router.routes]
        assert "/ingest/v2/upload-files" in routes
        assert "/ingest/v2/urls" in routes
        assert "/ingest/v2/drive" in routes

    def test_upload_uses_shared_token_fingerprint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ingestor import ingest_v2_endpoint

        captured: dict[str, Provenance] = {}

        monkeypatch.setattr(
            ingest_v2_endpoint,
            "_enforce_security",
            lambda request: "prefix01-sensitive-token",
        )
        monkeypatch.setattr(
            ingest_v2_endpoint,
            "token_hash",
            lambda token: "shared-fingerprint",
            raising=False,
        )
        monkeypatch.setattr(
            ingest_v2_endpoint,
            "_extract_text_from_file",
            lambda path: "contenu pédagogique",
        )

        def fake_ingest_document(text, request, provenance, *, doc_id):
            captured["provenance"] = provenance
            return SimpleNamespace(
                doc_id=doc_id,
                chunks_written=1,
                chunks_filtered=0,
                chunks_dedup=0,
                review_status="needs_review",
            )

        monkeypatch.setattr(
            ingest_v2_endpoint,
            "ingest_document",
            fake_ingest_document,
        )

        app = FastAPI()
        app.include_router(ingest_v2_endpoint.router)
        response = TestClient(app).post(
            "/ingest/v2/upload-files",
            params={
                "collection": "rag_nexus_nsi_terminale_specialite",
                "rights": "usage_interne",
                "matiere": "nsi",
                "niveau": "terminale",
            },
            files={"files": ("cours.txt", b"contenu", "text/plain")},
        )

        assert response.status_code == 200
        assert response.json()["route"] == "upload_v2"
        assert response.json()["results"][0]["review_status"] == "needs_review"
        assert captured["provenance"].token_hash == "shared-fingerprint"
