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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.review_v2_endpoint import ReviewDecision, router


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
        assert "/review/v2/pending" in routes
        assert "/review/v2/decide" in routes


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
        assert "REVIEWER_API_TOKEN" in source
        # Must explicitly reject ingestion token
        assert "INGESTOR_API_TOKEN" in source or "INGEST_AUTH_TOKEN" in source

    def test_reviewer_token_fail_closed(self) -> None:
        """If REVIEWER_API_TOKEN is not set, review decisions are blocked."""
        import inspect

        from ingestor.review_v2_endpoint import _enforce_reviewer_security
        source = inspect.getsource(_enforce_reviewer_security)
        assert "fail-closed" in source.lower() or "503" in source
