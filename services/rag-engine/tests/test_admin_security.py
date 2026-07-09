from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ingestor.admin_api import router as admin_router


def _clear_tokens(monkeypatch) -> None:
    monkeypatch.delenv("LEGACY_ADMIN_API_TOKEN", raising=False)
    monkeypatch.delenv("INGESTOR_API_TOKEN", raising=False)
    monkeypatch.delenv("INGEST_AUTH_TOKEN", raising=False)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router)
    return TestClient(app)


def test_admin_without_token_in_production_is_rejected(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_ADMIN_DEV", raising=False)
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.get("/admin/documents")

    assert response.status_code == 503


def test_admin_without_token_and_without_rag_env_is_rejected(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.delenv("RAG_ENV", raising=False)
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_ADMIN_DEV", raising=False)
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.get("/admin/documents")

    assert response.status_code == 503


def test_admin_without_token_in_development_requires_explicit_opt_in(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "development")
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_ADMIN_DEV", raising=False)
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.get("/admin/documents")

    assert response.status_code == 503


def test_admin_without_token_in_development_is_explicitly_accepted(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "development")
    monkeypatch.setenv("ALLOW_UNAUTHENTICATED_ADMIN_DEV", "true")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.get("/admin/documents")

    assert response.status_code == 200


def test_admin_reindex_requires_auth_when_token_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("LEGACY_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.post("/admin/reindex")

    assert response.status_code == 401


def test_admin_reindex_does_not_bypass_security(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("LEGACY_ADMIN_API_TOKEN", "admin-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.post("/admin/reindex", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401


def test_admin_does_not_fallback_to_ingestion_token_in_production(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("INGESTOR_API_TOKEN", "ingestion-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    response = _client().get(
        "/admin/documents",
        headers={"Authorization": "Bearer ingestion-token"},
    )

    assert response.status_code == 503
    assert "ingestion-token" not in response.text


def test_admin_accepts_dedicated_legacy_admin_token_in_production(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("LEGACY_ADMIN_API_TOKEN", "legacy-admin-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    response = _client().get(
        "/admin/documents",
        headers={"Authorization": "Bearer legacy-admin-token"},
    )

    assert response.status_code == 200


def test_admin_rejects_ingestion_token_when_admin_token_is_configured(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("LEGACY_ADMIN_API_TOKEN", "legacy-admin-token")
    monkeypatch.setenv("INGESTOR_API_TOKEN", "ingestion-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    response = _client().get(
        "/admin/documents",
        headers={"X-API-Token": "ingestion-token"},
    )

    assert response.status_code == 401
    assert "ingestion-token" not in response.text
    assert "legacy-admin-token" not in response.text


def test_admin_whitespace_api_token_falls_back_to_authorization(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("LEGACY_ADMIN_API_TOKEN", "legacy-admin-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    response = _client().get(
        "/admin/documents",
        headers={
            "X-API-Token": "   ",
            "Authorization": "Bearer legacy-admin-token",
        },
    )

    assert response.status_code == 200
