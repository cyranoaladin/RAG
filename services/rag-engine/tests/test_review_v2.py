"""Tests for review v2 endpoints (agent needs_review workflow).

Tests governance invariants:
- Only needs_review → reviewed or quarantined transitions allowed
- Decision invalidates retrieval cache
- Routes are registered
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from nexus_contracts import (
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueuePayload,
    ReviewQueueResponse,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor import review_v2_endpoint as review
from ingestor.review_v2_endpoint import router

ROLE_TOKEN_ENV = (
    "RAG_ADMIN_TOKEN",
    "RAG_REVIEWER_TOKEN",
    "REVIEWER_API_TOKEN",
    "RAG_TEACHER_TOKEN",
    "RAG_INGEST_AGENT_TOKEN",
    "INGESTOR_API_TOKEN",
    "INGEST_AUTH_TOKEN",
    "RAG_STUDENT_TOKEN",
)


def _review_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _review_payload() -> dict[str, str]:
    return {
        "target_type": "doc",
        "target_id": "doc123",
        "decision": "reviewed",
        "tenant": "libre_terminale",
    }


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _clear_role_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ROLE_TOKEN_ENV:
        monkeypatch.delenv(var, raising=False)


class TestReviewDecisionRequestModel:
    """Validation canonique de la requête BFF vers moteur."""

    def test_valid_review(self) -> None:
        d = ReviewDecisionRequest(
            target_id="doc123",
            decision="reviewed",
            tenant="libre_terminale",
        )
        assert d.decision == "reviewed"
        assert d.target_type == "doc"

    def test_valid_quarantine(self) -> None:
        d = ReviewDecisionRequest(
            target_id="chunk456",
            target_type="chunk",
            decision="quarantined",
            tenant="libre_terminale",
        )
        assert d.decision == "quarantined"
        assert d.target_type == "chunk"

    def test_reason_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewDecisionRequest(
                target_id="doc123",
                decision="reviewed",
                tenant="libre_terminale",
                reason="Contenu vérifié par M. Dupont",  # type: ignore[call-arg]
            )

    def test_empty_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewDecisionRequest(
                target_id="",
                decision="reviewed",
                tenant="libre_terminale",
            )

    def test_invalid_decision_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewDecisionRequest(
                target_id="doc123",
                decision="approved",  # type: ignore[arg-type]
                tenant="libre_terminale",
            )

    def test_invalid_target_type_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewDecisionRequest(
                target_id="doc123",
                target_type="collection",  # type: ignore[arg-type]
                decision="reviewed",
                tenant="libre_terminale",
            )

    def test_needs_review_not_a_valid_decision(self) -> None:
        """An agent cannot set needs_review via the review endpoint."""
        with pytest.raises(ValueError):
            ReviewDecisionRequest(
                target_id="doc123",
                decision="needs_review",  # type: ignore[arg-type]
                tenant="libre_terminale",
            )


class TestRoutes:
    """Verify review v2 endpoints are registered."""

    def test_routes_exist(self) -> None:
        routes = {route.path: route for route in router.routes}
        assert routes["/review/v2/queue"].response_model is ReviewQueueResponse
        assert routes["/review/v2/decide"].response_model is ReviewDecisionResponse


class TestQueueQueryValidation:
    """FastAPI validation for review queue pagination."""

    def test_queue_rejects_zero_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_role_tokens(monkeypatch)
        monkeypatch.setenv("RAG_TEACHER_TOKEN", "teacher-token")
        client = _review_client()

        response = client.get(
            "/review/v2/queue?limit=0",
            headers=_auth_headers("teacher-token"),
        )

        assert response.status_code == 422

    def test_queue_rejects_limit_above_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_role_tokens(monkeypatch)
        monkeypatch.setenv("RAG_TEACHER_TOKEN", "teacher-token")
        client = _review_client()

        response = client.get(
            "/review/v2/queue?limit=501",
            headers=_auth_headers("teacher-token"),
        )

        assert response.status_code == 422

    def test_queue_rejects_negative_offset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_role_tokens(monkeypatch)
        monkeypatch.setenv("RAG_TEACHER_TOKEN", "teacher-token")
        client = _review_client()

        response = client.get(
            "/review/v2/queue?offset=-1",
            headers=_auth_headers("teacher-token"),
        )

        assert response.status_code == 422

    def test_queue_accepts_valid_pagination_before_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_role_tokens(monkeypatch)
        monkeypatch.setenv("RAG_TEACHER_TOKEN", "teacher-token")
        monkeypatch.delenv("PG_RAG_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
        client = _review_client()

        response = client.get(
            "/review/v2/queue?limit=50&offset=0",
            headers=_auth_headers("teacher-token"),
        )

        assert response.status_code == 503
        assert response.status_code != 422


class TestGovernanceInvariant:
    """D-AGENT-NEEDS-REVIEW: agents submit, humans review."""

    def test_decision_only_reviewed_or_quarantined(self) -> None:
        """The only allowed transitions are needs_review → reviewed or quarantined."""
        # Valid
        ReviewDecisionRequest(
            target_id="x",
            decision="reviewed",
            tenant="libre_terminale",
        )
        ReviewDecisionRequest(
            target_id="x",
            decision="quarantined",
            tenant="libre_terminale",
        )
        # Invalid — cannot go back to needs_review
        with pytest.raises(ValueError):
            ReviewDecisionRequest(
                target_id="x",
                decision="needs_review",  # type: ignore[arg-type]
                tenant="libre_terminale",
            )

    def test_sql_only_updates_needs_review(self) -> None:
        """La transition est bornée par une liste d'états source paramétrée."""
        import inspect

        from ingestor.review_v2_endpoint import review_decide
        source = inspect.getsource(review_decide)
        assert "review_status = ANY(%s::text[])" in source
        assert '["needs_review"]' in source
        assert '["needs_review", "reviewed"]' in source

    def test_cache_invalidated_on_decision(self) -> None:
        """Review decisions must invalidate the retrieval cache."""
        import inspect

        from ingestor.review_v2_endpoint import review_decide
        source = inspect.getsource(review_decide)
        assert "invalidate_cache" in source

    def test_reviewer_token_required_for_decide(self) -> None:
        """D-AGENT-NEEDS-REVIEW exige le BFF et l'identité signée."""
        import inspect

        from ingestor.review_v2_endpoint import _require_review_identity
        source = inspect.getsource(_require_review_identity)
        assert "require_bff_service" in source
        assert "require_internal_identity" in source
        assert "_REVIEW_ROLES" in source

    def test_queue_and_decision_share_bounded_database_connections(self) -> None:
        """Les deux opérations doivent partager les bornes SQL du runtime."""
        import inspect

        assert "_connect_review_database(pg_dsn)" in inspect.getsource(
            review.list_queue
        )
        assert "_connect_review_database(pg_dsn)" in inspect.getsource(
            review.review_decide
        )

    def test_queue_and_decision_execute_schema_qualified_queries(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Les requêtes réellement transmises ciblent la relation gouvernée."""
        executed_sql: list[str] = []

        class RecordingCursor:
            rowcount = 1

            def __enter__(self) -> RecordingCursor:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def execute(self, sql: str, _params: object = None) -> None:
                executed_sql.append(sql)

            def fetchone(self) -> tuple[int]:
                return (0,)

            def fetchall(self) -> list[tuple[object, ...]]:
                return []

        class RecordingConnection:
            def cursor(self) -> RecordingCursor:
                return RecordingCursor()

            def commit(self) -> None:
                return None

            def rollback(self) -> None:
                raise AssertionError("rollback inattendu")

            def close(self) -> None:
                return None

        verified = SimpleNamespace(scope_digest="scope-digest")
        monkeypatch.setattr(
            review,
            "_require_review_identity",
            lambda *_args, **_kwargs: verified,
        )
        monkeypatch.setattr(
            review,
            "_load_review_scopes",
            lambda *_args, **_kwargs: (object(),),
        )
        monkeypatch.setattr(
            review,
            "_scope_filter",
            lambda _scopes: ("TRUE", ()),
        )
        monkeypatch.setattr(review, "_get_pg_dsn", lambda: "postgresql://test")
        monkeypatch.setattr(
            review,
            "_connect_review_database",
            lambda _dsn: RecordingConnection(),
        )
        monkeypatch.setattr(review, "invalidate_cache", lambda: 0)

        queue = review.list_queue(
            MagicMock(),
            ReviewQueuePayload(limit=50, offset=0),
        )
        queue_sql = list(executed_sql)
        decision = review.review_decide(
            ReviewDecisionRequest(
                target_id="doc123",
                decision="reviewed",
                tenant="libre_terminale",
            ),
            MagicMock(),
        )

        queue_relation_queries = [sql for sql in queue_sql if "rag_chunks" in sql]
        decision_relation_queries = [
            sql for sql in executed_sql[len(queue_sql):] if "rag_chunks" in sql
        ]
        assert queue.total_pending_docs == 0
        assert decision.chunks_affected == 1
        assert queue_relation_queries
        assert all(
            "FROM public.rag_chunks" in sql for sql in queue_relation_queries
        )
        assert decision_relation_queries
        assert all(
            "public.rag_chunks" in sql for sql in decision_relation_queries
        )
        assert any(
            sql.lstrip().startswith("UPDATE public.rag_chunks")
            for sql in decision_relation_queries
        )

    def test_review_connection_applies_connect_statement_and_lock_timeouts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        observed: dict[str, object] = {}
        sentinel = object()

        monkeypatch.setenv("PG_CONNECT_TIMEOUT_S", "4")
        monkeypatch.setenv("PG_STATEMENT_TIMEOUT_MS", "5500")
        monkeypatch.setenv("PG_LOCK_TIMEOUT_MS", "750")

        def connect(dsn: str, **kwargs: object) -> object:
            observed.update({"dsn": dsn, **kwargs})
            return sentinel

        monkeypatch.setattr(review.psycopg, "connect", connect)

        assert review._connect_review_database("postgresql://reviewer") is sentinel
        assert observed == {
            "dsn": "postgresql://reviewer",
            "connect_timeout": 4,
            "options": "-c statement_timeout=5500 -c lock_timeout=750",
        }

    def test_reviewer_token_fail_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If admin/reviewer tokens are not set, review decisions are blocked."""
        _clear_role_tokens(monkeypatch)
        client = _review_client()

        response = client.post(
            "/review/v2/decide",
            json=_review_payload(),
            headers=_auth_headers("whatever"),
        )

        assert response.status_code == 503

    def test_ingestor_token_cannot_decide(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Une identité signée ingest_agent ne peut jamais décider."""
        from ingestor import review_v2_endpoint as review

        monkeypatch.setattr(review, "require_bff_service", lambda *_a, **_k: None)
        monkeypatch.setattr(
            review,
            "require_internal_identity",
            lambda *_a, **_k: SimpleNamespace(
                envelope=SimpleNamespace(
                    identity=SimpleNamespace(role="ingest_agent")
                )
            ),
        )

        with pytest.raises(HTTPException) as exc_info:
            review._require_review_identity(
                MagicMock(),
                endpoint="/review/v2/decide",
            )
        assert getattr(exc_info.value, "status_code", None) == 403
