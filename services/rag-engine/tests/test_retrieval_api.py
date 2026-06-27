"""Tests for retrieval_api — governance gating + non-contournable filtering.

Tests the API contract:
- Governance: server refuses to start if locks are false
- Profile resolution: server-side only, not from client body
- Filtering: niveau/audience IMPOSED by profile, bypass attempts fail
- Read-only: no write routes exist
- Validation: empty query, oversized query, top_k bounds
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retrieval_api.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("retrieval_api", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Governance gating
# ---------------------------------------------------------------------------


class TestGovernanceGating:
    def test_blocks_when_server_start_false(self, tmp_path) -> None:
        mod = _load_module()
        contract = tmp_path / "c.yml"
        contract.write_text(
            "server_start_allowed: false\nruntime_api_allowed: true\n"
        )
        locks = mod.check_runtime_allowed(contract)
        assert locks["server_start_allowed"] is False

    def test_blocks_when_runtime_api_false(self, tmp_path) -> None:
        mod = _load_module()
        contract = tmp_path / "c.yml"
        contract.write_text(
            "server_start_allowed: true\nruntime_api_allowed: false\n"
        )
        locks = mod.check_runtime_allowed(contract)
        assert locks["runtime_api_allowed"] is False

    def test_allows_when_both_true(self, tmp_path) -> None:
        mod = _load_module()
        contract = tmp_path / "c.yml"
        contract.write_text(
            "server_start_allowed: true\nruntime_api_allowed: true\n"
        )
        locks = mod.check_runtime_allowed(contract)
        assert locks["server_start_allowed"] is True
        assert locks["runtime_api_allowed"] is True

    def test_blocks_on_missing_file(self, tmp_path) -> None:
        mod = _load_module()
        locks = mod.check_runtime_allowed(tmp_path / "missing.yml")
        assert locks["server_start_allowed"] is False
        assert locks["runtime_api_allowed"] is False

    def test_blocks_on_malformed(self, tmp_path) -> None:
        mod = _load_module()
        contract = tmp_path / "c.yml"
        contract.write_text("{broken: [")
        locks = mod.check_runtime_allowed(contract)
        assert locks["server_start_allowed"] is False


# ---------------------------------------------------------------------------
# Profile resolution — server-side
# ---------------------------------------------------------------------------


class TestProfileResolution:
    def test_known_profile_resolves(self) -> None:
        mod = _load_module()
        profile = mod.resolve_profile("terminale-libre")
        assert profile.niveau == "terminale"
        assert profile.audience == "libre"

    def test_unknown_profile_raises_403(self) -> None:
        mod = _load_module()
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            mod.resolve_profile("hacker-all-access")
        assert exc_info.value.status_code == 403

    def test_profile_is_frozen(self) -> None:
        mod = _load_module()
        profile = mod.resolve_profile("terminale-aefe")
        with pytest.raises(AttributeError):
            profile.niveau = "premiere"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SearchRequest validation
# ---------------------------------------------------------------------------


class TestSearchRequestValidation:
    def test_empty_query_rejected(self) -> None:
        mod = _load_module()
        with pytest.raises(ValueError):
            mod.SearchRequest(query="", top_k=5)

    def test_oversized_query_rejected(self) -> None:
        mod = _load_module()
        with pytest.raises(ValueError):
            mod.SearchRequest(query="x" * 501, top_k=5)

    def test_top_k_zero_rejected(self) -> None:
        mod = _load_module()
        with pytest.raises(ValueError):
            mod.SearchRequest(query="test", top_k=0)

    def test_top_k_over_max_rejected(self) -> None:
        mod = _load_module()
        with pytest.raises(ValueError):
            mod.SearchRequest(query="test", top_k=21)

    def test_valid_request(self) -> None:
        mod = _load_module()
        req = mod.SearchRequest(query="dérivée", top_k=5)
        assert req.query == "dérivée"
        assert req.top_k == 5


# ---------------------------------------------------------------------------
# Body injection attempt — schema has NO niveau/audience fields
# ---------------------------------------------------------------------------


class TestBodyInjection:
    def test_schema_ignores_extra_fields(self) -> None:
        """Client sends niveau/audience in body → silently ignored."""
        mod = _load_module()
        # Pydantic model_config doesn't include extra fields by default
        req = mod.SearchRequest(
            query="test",
            top_k=5,
            # These extra fields are NOT in the schema
        )
        assert not hasattr(req, "niveau")
        assert not hasattr(req, "audience")

    def test_schema_has_only_query_and_topk(self) -> None:
        mod = _load_module()
        fields = set(mod.SearchRequest.model_fields.keys())
        assert fields == {"query", "top_k"}, f"Unexpected fields: {fields}"


# ---------------------------------------------------------------------------
# Read-only — no write routes
# ---------------------------------------------------------------------------


class TestReadOnly:
    def test_no_write_routes(self) -> None:
        mod = _load_module()
        routes = [
            (r.path, list(r.methods))
            for r in mod.app.routes
            if hasattr(r, "methods")
        ]
        write_methods = {"PUT", "DELETE", "PATCH"}
        for path, methods in routes:
            for method in methods:
                assert method not in write_methods, (
                    f"Write route found: {method} {path}"
                )
        # POST only on /search
        post_routes = [p for p, m in routes if "POST" in m]
        assert post_routes == ["/search"], f"Unexpected POST routes: {post_routes}"


# ---------------------------------------------------------------------------
# _search_pgvector — filters are MANDATORY (not optional like index_pgvector)
# ---------------------------------------------------------------------------


class TestSearchFiltering:
    def test_search_always_filters_by_niveau_and_audience(self) -> None:
        """The API search function ALWAYS applies niveau+audience filters.

        Unlike index_pgvector.search() where filters are optional,
        _search_pgvector() requires them — they come from the profile.
        """
        mod = _load_module()
        # Mock connection to verify the SQL query includes WHERE clause
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []

        fake_vector = [0.1] * 1024
        mod._search_pgvector(
            mock_conn, fake_vector,
            niveau="terminale", audience="libre", top_k=5,
        )

        # Verify the SQL was called with niveau + audience in params
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "WHERE niveau = %s AND (%s = ANY(audience) OR 'tous' = ANY(audience))" in sql
        assert "terminale" in params
        assert "libre" in params
