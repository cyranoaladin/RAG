"""Frontière LOT41 : credential BFF et identité précèdent toute lecture."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ingestor import retrieval_v2_endpoint as endpoint


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router)
    return TestClient(app)


def test_missing_identity_stops_before_collection_config_and_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_token = "lot41-bff-service-token-at-least-32-bytes"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", service_token)
    for variable in (
        "RAG_ADMIN_TOKEN",
        "RAG_REVIEWER_TOKEN",
        "REVIEWER_API_TOKEN",
        "RAG_TEACHER_TOKEN",
        "RAG_INGEST_AGENT_TOKEN",
        "INGESTOR_API_TOKEN",
        "INGEST_AUTH_TOKEN",
        "RAG_STUDENT_TOKEN",
    ):
        monkeypatch.delenv(variable, raising=False)
    load_config = MagicMock(side_effect=AssertionError("config touched before identity"))
    retrieve = MagicMock(side_effect=AssertionError("database touched before identity"))
    monkeypatch.setattr(endpoint, "load_collection_config", load_config)
    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)

    response = _client().post(
        "/search/v2",
        headers={"Authorization": f"Bearer {service_token}"},
        json={"q": "question", "collection": "arbitrary_collection", "k": 5},
    )

    assert response.status_code == 401
    load_config.assert_not_called()
    retrieve.assert_not_called()


def test_scope_rejection_is_generic_and_happens_before_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.retrieval_scope_v2 import RetrievalScopeError

    monkeypatch.setattr(
        endpoint,
        "_require_retrieval_identity",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        endpoint,
        "load_collection_config",
        lambda: {
            "collections": {
                "arbitrary_collection": {
                    "domain": "education",
                    "instanciee": True,
                }
            },
            "domains": {"education": {"retrievable": True}},
        },
    )
    monkeypatch.setattr(endpoint, "_check_retrievable", lambda *_args: {})
    monkeypatch.setattr(
        endpoint,
        "build_server_retrieval_scope",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RetrievalScopeError("private scope details")
        ),
    )
    retrieve = MagicMock()
    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)

    response = _client().post(
        "/search/v2",
        json={"q": "question", "collection": "arbitrary_collection", "k": 5},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
    assert "private" not in response.text
    retrieve.assert_not_called()


def test_collection_gate_rejection_is_generic_and_happens_before_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        endpoint,
        "_require_retrieval_identity",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(endpoint, "load_collection_config", lambda: {})
    monkeypatch.setattr(
        endpoint,
        "_check_retrievable",
        lambda *_args: (_ for _ in ()).throw(
            HTTPException(status_code=403, detail="private collection name")
        ),
    )
    build_scope = MagicMock()
    retrieve = MagicMock()
    monkeypatch.setattr(endpoint, "build_server_retrieval_scope", build_scope)
    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)

    response = _client().post(
        "/search/v2",
        json={"q": "question", "collection": "secret_collection", "k": 5},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
    assert "private" not in response.text
    assert "secret_collection" not in response.text
    build_scope.assert_not_called()
    retrieve.assert_not_called()


def test_readiness_accepts_only_the_distinct_bff_credential_and_signed_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    service_token = "lot41-bff-service-token-at-least-32-bytes"
    student_token = "distinct-human-student-token"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", service_token)
    monkeypatch.setenv("RAG_STUDENT_TOKEN", student_token)
    verified = SimpleNamespace(
        envelope=SimpleNamespace(allowed_collections=("pilot_collection",)),
    )
    monkeypatch.setattr(endpoint, "require_internal_identity", lambda _request: verified)
    monkeypatch.setattr(
        endpoint,
        "load_collection_config",
        lambda: {
            "collections": {
                "pilot_collection": {
                    "domain": "education",
                    "instanciee": True,
                    "matiere": "nsi",
                    "niveau": "terminale",
                    "voie": "generale",
                    "statut": "specialite",
                },
            },
            "domains": {"education": {"retrievable": True}},
        },
    )
    scope = MagicMock(collection="pilot_collection")
    monkeypatch.setattr(endpoint, "build_server_retrieval_scope", lambda *_args, **_kwargs: scope)
    monkeypatch.setattr(
        endpoint,
        "_get_reviewed_chunk_counts",
        lambda scopes: {"pilot_collection": 10} if tuple(scopes) == (scope,) else {},
    )

    human_response = _client().get(
        "/collections/readiness",
        headers={"Authorization": f"Bearer {student_token}", "X-Nexus-Identity": "signed"},
    )
    bff_response = _client().get(
        "/collections/readiness",
        headers={"Authorization": f"Bearer {service_token}", "X-Nexus-Identity": "signed"},
    )

    assert human_response.status_code == 401
    assert bff_response.status_code == 200
    assert bff_response.json()["total_collections"] == 1
    assert bff_response.json()["launch_ready"] is False
