"""LOT43 (suite) : limites applicatives sur l'ingestion v2 (upload, urls, texte extrait).

Couvre les limites exigées par le brief P1.5 : taille max par fichier upload,
nombre max de fichiers par requête, nombre max d'URLs par requête, nombre max
d'URLs vers un même domaine dans une requête, taille max du texte extrait.
Aucun accès réseau ou pgvector réel : tout est monkeypatché/mocké.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor import ingest_v2_endpoint  # noqa: E402


def _make_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(ingest_v2_endpoint, "_enforce_security", lambda request: "test-token")
    app = FastAPI()
    app.include_router(ingest_v2_endpoint.router)
    return TestClient(app)


def test_upload_rejects_too_many_files(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app(monkeypatch)
    monkeypatch.setattr(ingest_v2_endpoint, "MAX_FILES_PER_UPLOAD", 2)

    files = [
        ("files", (f"f{i}.txt", io.BytesIO(b"hello"), "text/plain"))
        for i in range(3)
    ]
    response = client.post(
        "/ingest/v2/upload-files",
        params={"collection": "c", "rights": "r", "matiere": "m", "niveau": "n"},
        files=files,
    )
    assert response.status_code == 400
    assert "too many files" in response.text.lower()


def test_upload_rejects_oversized_file_without_unbounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _make_app(monkeypatch)
    monkeypatch.setattr(ingest_v2_endpoint, "MAX_UPLOAD_FILE_BYTES", 10)
    monkeypatch.setattr(
        ingest_v2_endpoint, "ingest_document", MagicMock(side_effect=AssertionError("should not be called"))
    )

    files = [("files", ("big.txt", io.BytesIO(b"x" * 1000), "text/plain"))]
    response = client.post(
        "/ingest/v2/upload-files",
        params={"collection": "c", "rights": "r", "matiere": "m", "niveau": "n"},
        files=files,
    )
    assert response.status_code == 200
    body = response.json()
    assert "too large" in body["results"][0]["error"].lower()


def test_upload_rejects_extracted_text_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app(monkeypatch)
    monkeypatch.setattr(ingest_v2_endpoint, "MAX_EXTRACTED_TEXT_CHARS", 5)
    monkeypatch.setattr(
        ingest_v2_endpoint, "_extract_text_from_file", lambda path: "way too much text"
    )
    monkeypatch.setattr(
        ingest_v2_endpoint, "ingest_document", MagicMock(side_effect=AssertionError("should not be called"))
    )

    files = [("files", ("f.txt", io.BytesIO(b"short"), "text/plain"))]
    response = client.post(
        "/ingest/v2/upload-files",
        params={"collection": "c", "rights": "r", "matiere": "m", "niveau": "n"},
        files=files,
    )
    assert response.status_code == 200
    body = response.json()
    assert "extracted text too large" in body["results"][0]["error"].lower()


def test_urls_request_rejects_too_many_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app(monkeypatch)
    monkeypatch.setattr(ingest_v2_endpoint, "MAX_URLS_PER_REQUEST", 2)

    response = client.post(
        "/ingest/v2/urls",
        json={
            "urls": ["https://a.example.com", "https://b.example.com", "https://c.example.com"],
            "collection": "c",
            "rights": "r",
            "matiere": "m",
            "niveau": "n",
        },
    )
    assert response.status_code == 400
    assert "too many urls" in response.text.lower()


def test_extract_text_from_pdf_rejects_too_many_pages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ingest_v2_endpoint, "MAX_PDF_PAGES", 3)

    class _FakePage:
        def extract_text(self) -> str:
            return "page text"

    class _FakeReader:
        def __init__(self, _path: str) -> None:
            self.pages = [_FakePage() for _ in range(5)]

    monkeypatch.setattr("pypdf.PdfReader", _FakeReader)

    pdf_path = tmp_path / "big.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    with pytest.raises(ValueError, match="too many pages"):
        ingest_v2_endpoint._extract_text_from_file(pdf_path)


def test_urls_request_caps_requests_per_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_app(monkeypatch)
    monkeypatch.setattr(ingest_v2_endpoint, "MAX_URLS_PER_DOMAIN_PER_REQUEST", 1)
    monkeypatch.setattr(ingest_v2_endpoint, "MAX_URLS_PER_REQUEST", 10)

    fetch_calls: list[str] = []

    def fake_safe_fetch(url: str, **_kwargs: Any):
        fetch_calls.append(url)
        raise ingest_v2_endpoint.SSRFValidationError("not reached in this test")

    monkeypatch.setattr(ingest_v2_endpoint, "safe_fetch", fake_safe_fetch)

    response = client.post(
        "/ingest/v2/urls",
        json={
            "urls": [
                "https://same-domain.example.com/a",
                "https://same-domain.example.com/b",
            ],
            "collection": "c",
            "rights": "r",
            "matiere": "m",
            "niveau": "n",
        },
    )
    assert response.status_code == 200
    body = response.json()
    errors = [r.get("error", "") for r in body["results"]]
    assert any("too many requests to this domain" in e.lower() for e in errors)
    assert len(fetch_calls) == 1
