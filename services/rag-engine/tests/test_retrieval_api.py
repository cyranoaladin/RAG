"""Tests for retrieval_api — governance gating + HMAC-signed profile + filtering.

Tests the API contract:
- Governance: server refuses to start if locks are false
- Profile: HMAC-signed, server-verified, forgery rejected
- Filtering: niveau/audience IMPOSED by signed profile, bypass impossible
- Read-only: no write routes exist
- Validation: empty query, oversized query, top_k bounds
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
# HMAC signing + verification
# ---------------------------------------------------------------------------


class TestHmacSigning:
    def test_sign_and_verify_roundtrip(self) -> None:
        mod = _load_module()
        token = mod.sign_profile("terminale", "libre", TEST_SECRET)
        profile = mod.verify_profile(token, TEST_SECRET)
        assert profile.niveau == "terminale"
        assert profile.audience == "libre"

    def test_forgery_wrong_secret_rejected(self) -> None:
        """A token signed with a different secret is REJECTED."""
        mod = _load_module()
        token = mod.sign_profile("terminale", "aefe", "attacker-secret")
        with pytest.raises(ValueError, match="invalid signature"):
            mod.verify_profile(token, TEST_SECRET)

    def test_tampered_payload_rejected(self) -> None:
        """Modifying the payload after signing invalidates the HMAC."""
        mod = _load_module()
        token = mod.sign_profile("premiere", "libre", TEST_SECRET)
        payload, sig = token.rsplit(".", 1)
        # Tamper: change premiere → terminale in payload
        tampered_payload = payload.replace("premiere", "terminale")
        tampered_token = f"{tampered_payload}.{sig}"
        with pytest.raises(ValueError, match="invalid signature"):
            mod.verify_profile(tampered_token, TEST_SECRET)

    def test_malformed_token_rejected(self) -> None:
        mod = _load_module()
        with pytest.raises(ValueError, match="malformed token"):
            mod.verify_profile("no-dot-separator", TEST_SECRET)

    def test_invalid_niveau_rejected(self) -> None:
        mod = _load_module()
        payload = json.dumps({"niveau": "doctorat", "audience": "libre"}, separators=(",", ":"))
        sig = hmac.new(TEST_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        with pytest.raises(ValueError, match="invalid niveau"):
            mod.verify_profile(f"{payload}.{sig}", TEST_SECRET)

    def test_invalid_audience_rejected(self) -> None:
        mod = _load_module()
        payload = json.dumps({"niveau": "terminale", "audience": "vip"}, separators=(",", ":"))
        sig = hmac.new(TEST_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        with pytest.raises(ValueError, match="invalid audience"):
            mod.verify_profile(f"{payload}.{sig}", TEST_SECRET)

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
        """Client sends niveau/audience in body → silently ignored."""
        mod = _load_module()
        req = mod.SearchRequest(query="test", top_k=5)
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
# _search_pgvector — filters are MANDATORY
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

        fake_vector = [0.1] * 1024
        mod._search_pgvector(
            mock_conn, fake_vector,
            niveau="terminale", audience="libre", top_k=5,
        )

        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        assert "WHERE niveau = %s AND (%s = ANY(audience) OR 'tous' = ANY(audience))" in sql
        assert "terminale" in params
        assert "libre" in params
