from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ingestor.admin_api import router as admin_router


def _clear_tokens(monkeypatch) -> None:
    monkeypatch.delenv("INGESTOR_API_TOKEN", raising=False)
    monkeypatch.delenv("INGEST_AUTH_TOKEN", raising=False)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router)
    return TestClient(app)


def test_admin_without_token_in_production_is_rejected(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.get("/admin/documents")

    assert response.status_code == 503


def test_admin_without_token_in_development_is_explicitly_accepted(monkeypatch, tmp_path) -> None:
    _clear_tokens(monkeypatch)
    monkeypatch.setenv("RAG_ENV", "development")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.get("/admin/documents")

    assert response.status_code == 200


def test_admin_reindex_requires_auth_when_token_configured(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("INGESTOR_API_TOKEN", "admin-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.post("/admin/reindex")

    assert response.status_code == 401


def test_admin_reindex_does_not_bypass_security(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("RAG_ENV", "production")
    monkeypatch.setenv("INGESTOR_API_TOKEN", "admin-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path / "uploads"))

    client = _client()
    response = client.post("/admin/reindex", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
