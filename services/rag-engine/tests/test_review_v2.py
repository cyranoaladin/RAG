"""Tests for review v2 endpoints (agent needs_review workflow).

Tests governance invariants:
- Only needs_review → reviewed or quarantined transitions allowed
- Decision invalidates retrieval cache
- Routes are registered
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.review_v2_endpoint import ReviewDecision, router

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
    return {"target_type": "doc", "target_id": "doc123", "decision": "reviewed"}


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _clear_role_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ROLE_TOKEN_ENV:
        monkeypatch.delenv(var, raising=False)


class TestReviewDecisionModel:
    """Pydantic validation for ReviewDecision."""

    def test_valid_review(self) -> None:
        d = ReviewDecision(target_id="doc123", decision="reviewed")
        assert d.decision == "reviewed"
        assert d.target_type == "doc"

    def test_valid_quarantine(self) -> None:
        d = ReviewDecision(target_id="chunk456", target_type="chunk", decision="quarantined")
        assert d.decision == "quarantined"
        assert d.target_type == "chunk"

    def test_with_reason(self) -> None:
        d = ReviewDecision(target_id="doc123", decision="reviewed", reason="Contenu vérifié par M. Dupont")
        assert d.reason == "Contenu vérifié par M. Dupont"

    def test_empty_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewDecision(target_id="", decision="reviewed")

    def test_invalid_decision_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewDecision(target_id="doc123", decision="approved")  # type: ignore[arg-type]

    def test_invalid_target_type_rejected(self) -> None:
        with pytest.raises(ValueError):
            ReviewDecision(target_id="doc123", target_type="collection", decision="reviewed")  # type: ignore[arg-type]

    def test_needs_review_not_a_valid_decision(self) -> None:
        """An agent cannot set needs_review via the review endpoint."""
        with pytest.raises(ValueError):
            ReviewDecision(target_id="doc123", decision="needs_review")  # type: ignore[arg-type]


class TestRoutes:
    """Verify review v2 endpoints are registered."""

    def test_routes_exist(self) -> None:
        routes = [r.path for r in router.routes]
        assert "/review/v2/queue" in routes
        assert "/review/v2/decide" in routes


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
        ReviewDecision(target_id="x", decision="reviewed")
        ReviewDecision(target_id="x", decision="quarantined")
        # Invalid — cannot go back to needs_review
        with pytest.raises(ValueError):
            ReviewDecision(target_id="x", decision="needs_review")  # type: ignore[arg-type]

    def test_sql_only_updates_needs_review(self) -> None:
        """The UPDATE only touches chunks WHERE review_status = 'needs_review'.

        A chunk already reviewed cannot be re-reviewed or un-reviewed via this endpoint.
        """
        import inspect

        from ingestor.review_v2_endpoint import review_decide
        source = inspect.getsource(review_decide)
        assert "WHERE review_status = 'needs_review'" in source or \
               "review_status = 'needs_review'" in source

    def test_cache_invalidated_on_decision(self) -> None:
        """Review decisions must invalidate the retrieval cache."""
        import inspect

        from ingestor.review_v2_endpoint import review_decide
        source = inspect.getsource(review_decide)
        assert "invalidate_cache" in source

    def test_reviewer_token_required_for_decide(self) -> None:
        """D-AGENT-NEEDS-REVIEW enforced by code: ingestion token rejected."""
        import inspect

        from ingestor.review_v2_endpoint import _enforce_reviewer_security
        source = inspect.getsource(_enforce_reviewer_security)
        # Must check REVIEWER_API_TOKEN (distinct from INGESTOR_API_TOKEN)
        assert "require_role" in source
        assert "SecurityRole.REVIEWER" in source or "reviewer" in source.lower()

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
        """An ingest_agent token must never authorize review decisions."""
        _clear_role_tokens(monkeypatch)
        monkeypatch.setenv("RAG_REVIEWER_TOKEN", "reviewer-token")
        monkeypatch.setenv("INGESTOR_API_TOKEN", "ingestor-token")
        client = _review_client()

        response = client.post(
            "/review/v2/decide",
            json=_review_payload(),
            headers=_auth_headers("ingestor-token"),
        )

        assert response.status_code == 403
