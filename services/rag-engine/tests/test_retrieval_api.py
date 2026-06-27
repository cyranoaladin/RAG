"""Tests for retrieval_api — governance gating + HMAC-signed profile + filtering.

Tests the API contract:
- Governance: server refuses to start if locks are false
- Profile: HMAC-signed (base64url), server-verified, forgery rejected
- Filtering: niveau/audience IMPOSED by signed profile, bypass impossible
- Read-only: no write routes exist
- Validation: empty query, oversized query, top_k bounds
- Robustness: missing table → 503
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import psycopg.errors
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retrieval_api.py"
TEST_SECRET = "test-secret-for-unit-tests"


def _load_module():
    spec = importlib.util.spec_from_file_location("retrieval_api", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _b64url(data: str) -> str:
    """Helper: base64url-encode a string without padding."""
    return base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode("ascii")


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

    def test_blocks_on_malformed(self, tmp_path) -> None:
        mod = _load_module()
        contract = tmp_path / "c.yml"
        contract.write_text("{broken: [")
        locks = mod.check_runtime_allowed(contract)
        assert locks["server_start_allowed"] is False


# ---------------------------------------------------------------------------
# HMAC signing + verification (base64url format)
# ---------------------------------------------------------------------------


class TestHmacSigning:
    def test_sign_and_verify_roundtrip(self) -> None:
        mod = _load_module()
        token = mod.sign_profile("terminale", "libre", TEST_SECRET)
        profile = mod.verify_profile(token, TEST_SECRET)
        assert profile.niveau == "terminale"
        assert profile.audience == "libre"

    def test_token_is_header_safe(self) -> None:
        """Token contains only [A-Za-z0-9_-] and one dot separator."""
        mod = _load_module()
        token = mod.sign_profile("terminale", "aefe", TEST_SECRET)
        assert mod._TOKEN_RE.fullmatch(token), f"Token not header-safe: {token}"
        # No braces, quotes, colons
        assert "{" not in token
        assert "}" not in token
        assert '"' not in token
        assert ":" not in token

    def test_forgery_wrong_secret_rejected(self) -> None:
        mod = _load_module()
        token = mod.sign_profile("terminale", "aefe", "attacker-secret")
        with pytest.raises(ValueError, match="invalid signature"):
            mod.verify_profile(token, TEST_SECRET)

    def test_tampered_payload_rejected(self) -> None:
        """Modifying the base64url payload after signing invalidates the HMAC."""
        mod = _load_module()
        token = mod.sign_profile("premiere", "libre", TEST_SECRET)
        encoded_payload, sig = token.rsplit(".", 1)
        # Tamper: re-encode a different payload
        tampered_encoded = _b64url(
            json.dumps({"niveau": "terminale", "audience": "libre"}, separators=(",", ":"))
        )
        tampered_token = f"{tampered_encoded}.{sig}"
        with pytest.raises(ValueError, match="invalid signature"):
            mod.verify_profile(tampered_token, TEST_SECRET)

    def test_malformed_token_rejected(self) -> None:
        mod = _load_module()
        with pytest.raises(ValueError, match="malformed token"):
            mod.verify_profile("no-dot-separator", TEST_SECRET)

    def test_raw_json_token_rejected(self) -> None:
        """Old-format raw JSON tokens are rejected (not base64url)."""
        mod = _load_module()
        raw = '{"niveau":"terminale","audience":"libre"}'
        sig = hmac.new(TEST_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
        # Braces/quotes/colons fail the regex
        with pytest.raises(ValueError, match="malformed token"):
            mod.verify_profile(f"{raw}.{sig}", TEST_SECRET)

    def test_invalid_niveau_rejected(self) -> None:
        mod = _load_module()
        payload_json = json.dumps({"niveau": "doctorat", "audience": "libre"}, separators=(",", ":"))
        encoded = _b64url(payload_json)
        sig = hmac.new(TEST_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        with pytest.raises(ValueError, match="invalid niveau"):
            mod.verify_profile(f"{encoded}.{sig}", TEST_SECRET)

    def test_invalid_audience_rejected(self) -> None:
        mod = _load_module()
        payload_json = json.dumps({"niveau": "terminale", "audience": "vip"}, separators=(",", ":"))
        encoded = _b64url(payload_json)
        sig = hmac.new(TEST_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        with pytest.raises(ValueError, match="invalid audience"):
            mod.verify_profile(f"{encoded}.{sig}", TEST_SECRET)

    def test_profile_is_frozen(self) -> None:
        mod = _load_module()
        token = mod.sign_profile("terminale", "aefe", TEST_SECRET)
        profile = mod.verify_profile(token, TEST_SECRET)
        with pytest.raises(AttributeError):
            profile.niveau = "premiere"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# resolve_profile — header-level verification
# ---------------------------------------------------------------------------


class TestResolveProfile:
    def test_valid_bearer_resolves(self, monkeypatch) -> None:
        mod = _load_module()
        monkeypatch.setattr(mod, "PROFILE_SECRET", TEST_SECRET)
        token = mod.sign_profile("terminale", "libre", TEST_SECRET)
        profile = mod.resolve_profile(f"Bearer {token}")
        assert profile.niveau == "terminale"
        assert profile.audience == "libre"

    def test_missing_bearer_prefix_rejected(self, monkeypatch) -> None:
        mod = _load_module()
        monkeypatch.setattr(mod, "PROFILE_SECRET", TEST_SECRET)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            mod.resolve_profile("just-a-token")
        assert exc_info.value.status_code == 401

    def test_forged_token_rejected(self, monkeypatch) -> None:
        mod = _load_module()
        monkeypatch.setattr(mod, "PROFILE_SECRET", TEST_SECRET)
        forged = mod.sign_profile("terminale", "aefe", "wrong-secret")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            mod.resolve_profile(f"Bearer {forged}")
        assert exc_info.value.status_code == 401

    def test_no_secret_configured_rejects(self, monkeypatch) -> None:
        mod = _load_module()
        monkeypatch.setattr(mod, "PROFILE_SECRET", "")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            mod.resolve_profile("Bearer anything")
        assert exc_info.value.status_code == 500


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
        mod = _load_module()
        req = mod.SearchRequest(query="test", top_k=5)
        assert not hasattr(req, "niveau")
        assert not hasattr(req, "audience")

    def test_schema_has_only_query_and_topk(self) -> None:
        mod = _load_module()
        fields = set(mod.SearchRequest.model_fields.keys())
        assert fields == {"query", "top_k"}, f"Unexpected fields: {fields}"


# ---------------------------------------------------------------------------
# Read-only — no write routes, no token oracle
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
        post_routes = [p for p, m in routes if "POST" in m]
        assert post_routes == ["/search"], f"Unexpected POST routes: {post_routes}"

    def test_no_token_endpoint(self) -> None:
        """No route can issue a signed token — oracle is closed."""
        mod = _load_module()
        route_paths = [
            r.path for r in mod.app.routes if hasattr(r, "methods")
        ]
        for path in route_paths:
            assert "token" not in path.lower(), (
                f"Token-issuing route found: {path}"
            )
        app_routes = {p for p in route_paths if not p.startswith(("/docs", "/openapi", "/redoc"))}
        assert app_routes == {"/health", "/search"}, (
            f"Unexpected app routes: {app_routes}"
        )


# ---------------------------------------------------------------------------
# _search_pgvector — filters MANDATORY, pilote table, 503 on missing
# ---------------------------------------------------------------------------


class TestSearchFiltering:
    def test_search_always_filters_by_niveau_and_audience(self) -> None:
        mod = _load_module()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []

        mod._search_pgvector(
            mock_conn, [0.1] * 1024,
            niveau="terminale", audience="libre", top_k=5,
        )

        sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]
        assert "WHERE niveau = %s AND (%s = ANY(audience) OR 'tous' = ANY(audience))" in sql
        assert "terminale" in params
        assert "libre" in params

    def test_uses_pilote_table_not_historical(self) -> None:
        mod = _load_module()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.fetchall.return_value = []

        mod._search_pgvector(
            mock_conn, [0.1] * 1024,
            niveau="terminale", audience="libre", top_k=5,
        )
        sql = mock_cursor.execute.call_args[0][0]
        assert "rag_chunks_pilote" in sql
        assert "FROM rag_chunks " not in sql.replace("rag_chunks_pilote", "")

    def test_missing_table_returns_503(self) -> None:
        """If rag_chunks_pilote doesn't exist, return 503 not 500."""
        mod = _load_module()
        from fastapi import HTTPException

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(
            return_value=mock_cursor
        )
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = psycopg.errors.UndefinedTable(
            "relation \"rag_chunks_pilote\" does not exist"
        )

        with pytest.raises(HTTPException) as exc_info:
            mod._search_pgvector(
                mock_conn, [0.1] * 1024,
                niveau="terminale", audience="libre", top_k=5,
            )
        assert exc_info.value.status_code == 503
        assert "not ready" in exc_info.value.detail
