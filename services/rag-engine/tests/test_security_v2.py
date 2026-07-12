from __future__ import annotations

# Ensure local imports resolve when tests are launched from repository root.
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.security_v2 import SecurityRole, configured_tokens, token_hash  # noqa: E402


@pytest.fixture
def role_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build a tiny app exposing endpoints with explicit role constraints."""
    app = FastAPI()
    router = APIRouter()

    @app.middleware("http")
    async def override_client_host(request: Request, call_next: Any) -> Any:
        client_host = request.headers.get("x-test-client-host")
        if client_host:
            request.scope["client"] = (client_host, 50000)
        return await call_next(request)

    def _search_probe() -> dict[str, Any]:
        return {"ok": True}

    def _ingest_probe() -> dict[str, Any]:
        return {"ok": True}

    def _pending_probe() -> dict[str, Any]:
        return {"ok": True}

    def _decide_probe() -> dict[str, Any]:
        return {"ok": True}

    def _collections_probe() -> dict[str, Any]:
        return {"ok": True}

    def _cache_probe() -> dict[str, Any]:
        return {"ok": True}

    @router.get("/search")
    def search_probe(request: Request) -> dict[str, bool]:
        from ingestor.security_v2 import require_role

        require_role(
            request,
            allowed_roles={
                SecurityRole.ADMIN,
                SecurityRole.REVIEWER,
                SecurityRole.TEACHER,
                SecurityRole.INGEST_AGENT,
                SecurityRole.STUDENT,
            },
            endpoint="/search",
        )
        return _search_probe()

    @router.get("/ingest")
    def ingest_probe(request: Request) -> dict[str, bool]:
        from ingestor.security_v2 import require_role

        require_role(
            request,
            allowed_roles={SecurityRole.ADMIN, SecurityRole.INGEST_AGENT},
            endpoint="/ingest",
            enforce_ip_allowlist=True,
        )
        return _ingest_probe()

    @router.get("/review/queue")
    def pending_probe(request: Request) -> dict[str, bool]:
        from ingestor.security_v2 import require_role

        require_role(
            request,
            allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER, SecurityRole.TEACHER},
            endpoint="/review/v2/queue",
        )
        return _pending_probe()

    @router.get("/review/decide")
    def decide_probe(request: Request) -> dict[str, bool]:
        from ingestor.security_v2 import require_role

        require_role(
            request,
            allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER},
            endpoint="/review/decide",
        )
        return _decide_probe()

    @router.get("/collections")
    def collections_probe(request: Request) -> dict[str, bool]:
        from ingestor.security_v2 import require_role

        require_role(
            request,
            allowed_roles={
                SecurityRole.ADMIN,
                SecurityRole.REVIEWER,
                SecurityRole.TEACHER,
                SecurityRole.INGEST_AGENT,
                SecurityRole.STUDENT,
            },
            endpoint="/collections",
        )
        return _collections_probe()

    @router.get("/cache")
    def cache_probe(request: Request) -> dict[str, bool]:
        from ingestor.security_v2 import require_role

        require_role(
            request,
            allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER},
            endpoint="/cache",
        )
        return _cache_probe()

    app.include_router(router)

    for var in (
        "RAG_ADMIN_TOKEN",
        "RAG_REVIEWER_TOKEN",
        "REVIEWER_API_TOKEN",
        "RAG_TEACHER_TOKEN",
        "RAG_INGEST_AGENT_TOKEN",
        "INGESTOR_API_TOKEN",
        "INGEST_AUTH_TOKEN",
        "RAG_STUDENT_TOKEN",
        "INGESTOR_IP_ALLOWLIST",
        "INGESTOR_TRUSTED_PROXY_CIDRS",
    ):
        monkeypatch.delenv(var, raising=False)

    monkeypatch.setenv("RAG_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("RAG_REVIEWER_TOKEN", "reviewer-token")
    monkeypatch.setenv("RAG_TEACHER_TOKEN", "teacher-token")
    monkeypatch.setenv("RAG_INGEST_AGENT_TOKEN", "ingest-agent-token")
    monkeypatch.setenv("RAG_STUDENT_TOKEN", "student-token")

    return TestClient(app)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestSecurityV2Authorization:
    """LOT 26.3 role matrix smoke checks."""

    def test_search_allowed_roles(self, role_client: TestClient) -> None:
        assert role_client.get("/search", headers=_auth_headers("admin-token")).status_code == 200
        assert role_client.get("/search", headers=_auth_headers("reviewer-token")).status_code == 200
        assert role_client.get("/search", headers=_auth_headers("teacher-token")).status_code == 200
        assert role_client.get("/search", headers=_auth_headers("student-token")).status_code == 200
        assert role_client.get("/search", headers=_auth_headers("ingest-agent-token")).status_code == 200

    def test_blank_x_api_token_falls_back_to_authorization(self, role_client: TestClient) -> None:
        response = role_client.get(
            "/search",
            headers={
                "X-API-Token": "   ",
                "Authorization": "Bearer student-token",
            },
        )

        assert response.status_code == 200

    def test_non_ascii_bearer_token_is_unauthorized(self, role_client: TestClient) -> None:
        response = role_client.get(
            "/search",
            headers=[
                (b"Authorization", "Bearer étudïant-token".encode()),
            ],
        )

        assert response.status_code == 401

    def test_non_ascii_x_api_token_is_unauthorized(self, role_client: TestClient) -> None:
        response = role_client.get(
            "/search",
            headers=[
                (b"X-API-Token", "étudïant-token".encode()),
            ],
        )

        assert response.status_code == 401

    def test_non_ascii_token_is_rejected_before_ip_allowlist(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")

        response = role_client.get(
            "/ingest",
            headers=[
                (b"Authorization", "Bearer étudïant-token".encode()),
                (b"X-Test-Client-Host", b"198.51.100.200"),
            ],
        )

        assert response.status_code == 401

    def test_ingest_allowed_roles(self, role_client: TestClient) -> None:
        assert role_client.get("/ingest", headers=_auth_headers("admin-token")).status_code == 200
        assert role_client.get("/ingest", headers=_auth_headers("ingest-agent-token")).status_code == 200
        assert role_client.get("/ingest", headers=_auth_headers("teacher-token")).status_code == 403

    def test_ingest_agent_aliases(self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("INGESTOR_API_TOKEN", "ingestor-api-token")
        monkeypatch.setenv("INGEST_AUTH_TOKEN", "ingest-auth-token")

        assert role_client.get("/ingest", headers=_auth_headers("ingest-agent-token")).status_code == 200
        assert role_client.get("/ingest", headers=_auth_headers("ingestor-api-token")).status_code == 200
        assert role_client.get("/ingest", headers=_auth_headers("ingest-auth-token")).status_code == 200

    def test_review_queue_and_decision_roles(self, role_client: TestClient) -> None:
        assert role_client.get("/review/queue", headers=_auth_headers("admin-token")).status_code == 200
        assert role_client.get("/review/queue", headers=_auth_headers("reviewer-token")).status_code == 200
        assert role_client.get("/review/queue", headers=_auth_headers("teacher-token")).status_code == 200
        assert role_client.get("/review/queue", headers=_auth_headers("ingest-agent-token")).status_code == 403
        assert role_client.get("/review/queue", headers=_auth_headers("student-token")).status_code == 403

        assert role_client.get("/review/decide", headers=_auth_headers("admin-token")).status_code == 200
        assert role_client.get("/review/decide", headers=_auth_headers("reviewer-token")).status_code == 200
        assert role_client.get("/review/decide", headers=_auth_headers("teacher-token")).status_code == 403
        assert role_client.get("/review/decide", headers=_auth_headers("ingest-agent-token")).status_code == 403

    def test_cache_and_collections_roles(self, role_client: TestClient) -> None:
        assert role_client.get("/collections", headers=_auth_headers("student-token")).status_code == 200
        assert role_client.get("/cache", headers=_auth_headers("admin-token")).status_code == 200
        assert role_client.get("/cache", headers=_auth_headers("reviewer-token")).status_code == 200
        assert role_client.get("/cache", headers=_auth_headers("student-token")).status_code == 403

    def test_reviewer_aliases(self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REVIEWER_API_TOKEN", "reviewer-api-token")

        assert role_client.get("/review/decide", headers=_auth_headers("reviewer-token")).status_code == 200
        assert role_client.get("/review/decide", headers=_auth_headers("reviewer-api-token")).status_code == 200

    def test_token_collision_is_fail_closed(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RAG_ADMIN_TOKEN", "shared-token")
        monkeypatch.setenv("RAG_REVIEWER_TOKEN", "shared-token")

        response = role_client.get("/search", headers=_auth_headers("shared-token"))

        assert response.status_code == 503
        assert "shared-token" not in response.text

    def test_token_matching_uses_compare_digest(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import hmac

        compare_calls = 0
        real_compare_digest = hmac.compare_digest

        def compare_digest_spy(candidate: str, configured: str) -> bool:
            nonlocal compare_calls
            compare_calls += 1
            return real_compare_digest(candidate, configured)

        monkeypatch.setattr(hmac, "compare_digest", compare_digest_spy)

        response = role_client.get("/search", headers=_auth_headers("student-token"))

        assert response.status_code == 200
        assert compare_calls > 0

    def test_token_matching_uses_role_mapping_as_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ingestor import security_v2

        monkeypatch.setattr(
            security_v2,
            "_ROLE_TOKEN_ENV",
            {SecurityRole.STUDENT: ("ROUND7_STUDENT_TOKEN",)},
        )
        monkeypatch.setenv("ROUND7_STUDENT_TOKEN", "round7-student-token")

        assert security_v2._match_role("round7-student-token") is SecurityRole.STUDENT

    def test_ip_allowlist_does_not_oracle_missing_token(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")

        response = role_client.get("/ingest", headers={"X-Test-Client-Host": "198.51.100.200"})

        assert response.status_code == 401

    def test_ip_allowlist_does_not_oracle_invalid_token(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("invalid-token"),
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 401

    def test_ip_allowlist_rejects_valid_token_outside_allowlist(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_accepts_valid_token_inside_allowlist(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("INGESTOR_TRUSTED_PROXY_CIDRS", raising=False)
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Test-Client-Host": "203.0.113.17",
            },
        )

        assert response.status_code == 200

    def test_ip_allowlist_rejects_invalid_trusted_proxy_configuration(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "not-a-cidr")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "trusted proxy configuration invalid"}

    def test_ip_allowlist_accepts_mixed_valid_trusted_proxy_configuration(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv(
            "INGESTOR_TRUSTED_PROXY_CIDRS",
            "not-a-cidr,198.51.100.200/32",
        )

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 200

    def test_invalid_trusted_proxy_configuration_cannot_allow_proxy_peer(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "198.51.100.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "not-a-cidr")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "trusted proxy configuration invalid"}

    def test_ip_allowlist_ignores_x_forwarded_for_without_trusted_proxy(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17, 10.0.0.1",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_x_forwarded_for_allowed_from_trusted_proxy(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 200

    def test_ip_allowlist_strips_trusted_proxy_from_xff_chain(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.0/24")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17, 198.51.100.200",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 200

    def test_ip_allowlist_rejects_malformed_xff_on_right(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17, malformed",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_rejects_malformed_xff_on_left(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "malformed, 203.0.113.17",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_rejects_empty_xff_entry(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17, , 198.51.100.200",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_x_forwarded_for_spoofed_first_ip_rejected_from_trusted_proxy(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17, 198.51.100.7",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_x_forwarded_for_rejected_from_trusted_proxy(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "198.51.100.7",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_rejects_x_forwarded_for_from_untrusted_proxy(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "192.0.2.0/24")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "203.0.113.17",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_x_real_ip_is_ignored_from_trusted_proxy(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Real-IP": "203.0.113.9",
                "X-Forwarded-For": "198.51.100.7",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_rejects_trusted_proxy_without_xff(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "INGESTOR_IP_ALLOWLIST",
            "198.51.100.0/24",
        )
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Real-IP": "203.0.113.9",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_rejects_trusted_proxy_only_xff(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "198.51.100.0/24")
        monkeypatch.setenv("INGESTOR_TRUSTED_PROXY_CIDRS", "198.51.100.200/32")

        response = role_client.get(
            "/ingest",
            headers={
                **_auth_headers("ingest-agent-token"),
                "X-Forwarded-For": "198.51.100.200",
                "X-Test-Client-Host": "198.51.100.200",
            },
        )

        assert response.status_code == 403

    def test_ip_allowlist_missing_ip_rejected(
        self, role_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "203.0.113.0/24")

        response = role_client.get("/ingest", headers=_auth_headers("ingest-agent-token"))

        assert response.status_code == 403

    def test_ip_allowlist_absent_does_not_block(self, role_client: TestClient) -> None:
        assert role_client.get("/ingest", headers=_auth_headers("ingest-agent-token")).status_code == 200

    def test_missing_configuration_is_fail_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = FastAPI()
        router = APIRouter()

        @router.get("/search")
        def search_probe(request: Request) -> dict[str, str]:
            from ingestor.security_v2 import require_role

            require_role(
                request,
                allowed_roles={
                    SecurityRole.ADMIN,
                    SecurityRole.REVIEWER,
                    SecurityRole.TEACHER,
                    SecurityRole.STUDENT,
                },
                endpoint="/search",
            )
            return {}

        app.include_router(router)
        client = TestClient(app)

        for var in (
            "RAG_ADMIN_TOKEN",
            "RAG_REVIEWER_TOKEN",
            "REVIEWER_API_TOKEN",
            "RAG_TEACHER_TOKEN",
            "RAG_INGEST_AGENT_TOKEN",
            "INGESTOR_API_TOKEN",
            "INGEST_AUTH_TOKEN",
            "RAG_STUDENT_TOKEN",
        ):
            monkeypatch.delenv(var, raising=False)

        response = client.get("/search", headers=_auth_headers("whatever"))
        assert response.status_code == 503


class TestSecurityV2Internals:
    def test_hash_is_short_and_reproducible(self) -> None:
        assert token_hash("abc123") == token_hash("abc123")
        assert len(token_hash("abc123")) == 16

    def test_hash_uses_the_complete_token(self) -> None:
        assert token_hash("prefix01-AAAA") != token_hash("prefix01-BBBB")

    def test_hash_does_not_contain_raw_token(self) -> None:
        token = "prefix01-sensitive-token"

        assert token not in token_hash(token)

    def test_configured_tokens_are_hashed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RAG_ADMIN_TOKEN", "abc")
        hashed = configured_tokens()["admin"]
        assert hashed
        assert hashed[0] != "abc"
