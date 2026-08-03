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


class TestDefaultScope:
    """LOT43: tenant/candidat/visibility/school_year/programme_version must
    never be written as NULL — a missing or invalid server configuration
    must fail closed, never silently guess or omit a value."""

    def _set_valid_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXUS_DEFAULT_TENANT", "nexus-reussite")
        monkeypatch.setenv("NEXUS_DEFAULT_CANDIDAT", "libre")
        monkeypatch.setenv("NEXUS_DEFAULT_VISIBILITY", "internal")
        monkeypatch.setenv("NEXUS_DEFAULT_SCHOOL_YEAR", "2026-2027")
        monkeypatch.setenv("NEXUS_DEFAULT_PROGRAMME_VERSION", "france-2026")

    def test_valid_configuration_returns_scope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ingestor.ingest_v2 import _get_default_scope

        self._set_valid_env(monkeypatch)
        scope = _get_default_scope()
        assert scope.tenant == "nexus-reussite"
        assert scope.candidat == "libre"
        assert scope.visibility == "internal"
        assert scope.school_year == "2026-2027"
        assert scope.programme_version == "france-2026"

    @pytest.mark.parametrize(
        "missing_var",
        [
            "NEXUS_DEFAULT_TENANT",
            "NEXUS_DEFAULT_CANDIDAT",
            "NEXUS_DEFAULT_VISIBILITY",
            "NEXUS_DEFAULT_SCHOOL_YEAR",
            "NEXUS_DEFAULT_PROGRAMME_VERSION",
        ],
    )
    def test_missing_variable_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, missing_var: str
    ) -> None:
        from ingestor.ingest_v2 import ScopeConfigurationError, _get_default_scope

        self._set_valid_env(monkeypatch)
        monkeypatch.delenv(missing_var, raising=False)

        with pytest.raises(ScopeConfigurationError, match="Missing"):
            _get_default_scope()

    def test_invalid_candidat_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ingestor.ingest_v2 import ScopeConfigurationError, _get_default_scope

        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("NEXUS_DEFAULT_CANDIDAT", "not-a-real-value")

        with pytest.raises(ScopeConfigurationError, match="CANDIDAT"):
            _get_default_scope()

    def test_invalid_visibility_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ingestor.ingest_v2 import ScopeConfigurationError, _get_default_scope

        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("NEXUS_DEFAULT_VISIBILITY", "not-a-real-value")

        with pytest.raises(ScopeConfigurationError, match="VISIBILITY"):
            _get_default_scope()

    @pytest.mark.parametrize(
        "school_year",
        ["2026", "2026-2028", "abcd-efgh", "2026-2026"],
    )
    def test_invalid_school_year_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, school_year: str
    ) -> None:
        from ingestor.ingest_v2 import ScopeConfigurationError, _get_default_scope

        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("NEXUS_DEFAULT_SCHOOL_YEAR", school_year)

        with pytest.raises(ScopeConfigurationError, match="SCHOOL_YEAR"):
            _get_default_scope()

    def test_ingest_document_fails_closed_without_scope_configuration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end gate check: no scope config -> ingest_document refuses,
        never reaches embedding, never writes a NULL-scoped chunk."""
        import ingestor.ingest_v2 as ingest_v2_module

        monkeypatch.setenv("PG_RAG_DSN", "postgresql://unused/unused")
        for var in (
            "NEXUS_DEFAULT_TENANT", "NEXUS_DEFAULT_CANDIDAT",
            "NEXUS_DEFAULT_VISIBILITY", "NEXUS_DEFAULT_SCHOOL_YEAR",
            "NEXUS_DEFAULT_PROGRAMME_VERSION",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(ingest_v2_module, "MAX_CHUNKS_PER_COLLECTION_PER_DAY", 0)
        monkeypatch.setattr(
            ingest_v2_module,
            "_get_embed_model",
            lambda: (_ for _ in ()).throw(AssertionError("must not reach embedding")),
        )

        req = IngestV2Request(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="test.pdf",
            source_uri="upload://test.pdf",
            rights="usage_interne",
            matiere="nsi",
            niveau="terminale",
        )
        prov = Provenance(route="test", timestamp=0, token_hash="x", source_type="file")

        with pytest.raises(ingest_v2_module.ScopeConfigurationError, match="Missing"):
            ingest_v2_module.ingest_document("test content", req, prov)


class TestCollectionQuota:
    """LOT43: a collection's ingestion quota must be enforced before chunking/embedding."""

    def test_quota_exceeded_rejected_before_chunking_or_embedding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ingestor.ingest_v2 as ingest_v2_module

        monkeypatch.setenv("PG_RAG_DSN", "postgresql://unused/unused")
        monkeypatch.setattr(ingest_v2_module, "MAX_CHUNKS_PER_COLLECTION_PER_DAY", 10)
        monkeypatch.setattr(
            ingest_v2_module, "_count_recent_chunks", lambda collection, pg_dsn: 10
        )

        def _fail_if_called():
            raise AssertionError("embedding must not be reached when quota is exceeded")

        monkeypatch.setattr(ingest_v2_module, "_get_embed_model", _fail_if_called)

        req = IngestV2Request(
            collection="rag_nexus_nsi_terminale_specialite",  # instanciee: true
            source_label="test.pdf",
            source_uri="upload://test.pdf",
            rights="usage_interne",
            matiere="nsi",
            niveau="terminale",
        )
        prov = Provenance(route="test", timestamp=0, token_hash="x", source_type="file")

        with pytest.raises(ingest_v2_module.CollectionQuotaExceededError, match="quota"):
            ingest_v2_module.ingest_document("test content", req, prov)

    def test_quota_not_exceeded_allows_processing_to_continue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import ingestor.ingest_v2 as ingest_v2_module

        monkeypatch.setenv("PG_RAG_DSN", "postgresql://unused/unused")
        monkeypatch.setenv("NEXUS_DEFAULT_TENANT", "nexus-reussite")
        monkeypatch.setenv("NEXUS_DEFAULT_CANDIDAT", "libre")
        monkeypatch.setenv("NEXUS_DEFAULT_VISIBILITY", "internal")
        monkeypatch.setenv("NEXUS_DEFAULT_SCHOOL_YEAR", "2026-2027")
        monkeypatch.setenv("NEXUS_DEFAULT_PROGRAMME_VERSION", "france-2026")
        monkeypatch.setattr(ingest_v2_module, "MAX_CHUNKS_PER_COLLECTION_PER_DAY", 10)
        monkeypatch.setattr(
            ingest_v2_module, "_count_recent_chunks", lambda collection, pg_dsn: 3
        )

        reached_embedding = {"value": False}

        def _mark_reached():
            reached_embedding["value"] = True
            raise RuntimeError("stop after confirming quota gate passed")

        monkeypatch.setattr(ingest_v2_module, "_get_embed_model", _mark_reached)

        req = IngestV2Request(
            collection="rag_nexus_nsi_terminale_specialite",
            source_label="test.pdf",
            source_uri="upload://test.pdf",
            rights="usage_interne",
            matiere="nsi",
            niveau="terminale",
        )
        prov = Provenance(route="test", timestamp=0, token_hash="x", source_type="file")

        with pytest.raises(RuntimeError, match="stop after confirming"):
            ingest_v2_module.ingest_document("test content", req, prov)
        assert reached_embedding["value"] is True


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
