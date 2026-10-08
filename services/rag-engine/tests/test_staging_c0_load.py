"""Le verdict C0 doit échouer fermé sur la vraie charge déclarée."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.go_live import staging_c0_load as c0
from scripts.go_live.staging_c0_load import evaluate_measurement, nearest_rank, validate_api_url

BUDGET = {
    "load_profile": {
        "concurrent_clients": 8,
        "measured_requests_total": 240,
        "client_timeout_ms": 7500,
    },
    "budget": {
        "p50_ms_max": 3000,
        "p95_ms_max": 6000,
        "p99_ms_max": 7500,
        "errors_max": 0,
        "timeouts_max": 0,
        "db_connections_peak_max": 10,
    },
}


def _measurement(*, latency: float = 2500, peak: int = 8) -> dict:
    return {
        "concurrent_clients": 8,
        "requests": [
            {"latency_ms": latency, "status": 200, "outcome": "ok", "detail": None}
            for _ in range(240)
        ],
        "db_connections": {"samples_count": 20, "peak_during_load": peak},
    }


def test_nearest_rank_uses_observed_tail() -> None:
    assert nearest_rank([1, 2, 3, 4, 5], 99) == 5


def test_staging_c0_refuses_prod_or_secret_bearing_url() -> None:
    assert validate_api_url("http://127.0.0.1:8001") == "http://127.0.0.1:8001"
    with pytest.raises(ValueError):
        validate_api_url("https://api.example.org")
    with pytest.raises(ValueError):
        validate_api_url("http://user:secret@127.0.0.1:8001/search")


def test_declared_c0_passes_only_with_all_240_valid_results() -> None:
    verdict = evaluate_measurement(_measurement(), BUDGET)
    assert verdict["pass"] is True
    assert verdict["requests"] == 240
    assert verdict["p99_ms"] == 2500


def test_c0_refuses_the_prior_503_failure_pattern() -> None:
    measured = _measurement()
    for row in measured["requests"][:232]:
        row.update(status=503, outcome="error", detail="http_503")
    verdict = evaluate_measurement(measured, BUDGET)
    assert verdict["pass"] is False
    assert verdict["errors"] == 232
    assert verdict["http_503"] == 232


def test_c0_refuses_missing_requests_timeouts_latency_and_pool_overflow() -> None:
    missing = _measurement()
    missing["requests"].pop()
    assert evaluate_measurement(missing, BUDGET)["pass"] is False

    timeout = _measurement()
    timeout["requests"][0].update(outcome="timeout", detail="client_timeout")
    assert evaluate_measurement(timeout, BUDGET)["pass"] is False

    slow = _measurement()
    for row in slow["requests"][-3:]:
        row["latency_ms"] = 7501
    assert evaluate_measurement(slow, BUDGET)["pass"] is False

    pool = _measurement(peak=11)
    assert evaluate_measurement(pool, BUDGET)["pass"] is False

    unsampled = _measurement()
    unsampled["db_connections"]["samples_count"] = 0
    assert evaluate_measurement(unsampled, BUDGET)["pass"] is False


def test_real_http_shape_requires_signed_scope_and_complete_citation() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/v2"
        assert request.headers["authorization"] == "Bearer bff-secret"
        assert request.headers["x-rag-api-key"] == "api-key"
        assert request.headers["x-nexus-identity"] == "signed-identity"
        return httpx.Response(200, json={
            "results": [{
                "chunk_id": "chunk-1", "doc_id": "doc-1", "score": 1,
                "excerpt": "La norme européenne", "citation": {
                    "source_label": "BOEN", "page": 3,
                    "source_uri": "https://example.org/boen.pdf", "rights": "officiel_public",
                },
                "metadata": {"collection": "collection-1", "content_sha256": "a" * 64},
            }]
        })

    config = c0.rag_query.ClientConfig(
        api_url="http://127.0.0.1:8001", bff_token="bff-secret",
        internal_secret="internal-secret", internal_issuer="issuer",
        internal_audience="audience", identity_issuer="sso", identity_audience="cockpit",
    )
    with httpx.Client(base_url="http://127.0.0.1:8001", transport=httpx.MockTransport(handle)) as client:
        row = c0._one_request(
            ("collection-1", "scope-1", "Question pédagogique", "a" * 64),
            config=config, api_key="api-key", timeout_s=7.5, client=client,
            identity_token="signed-identity", payload={"need": {"query": "Question pédagogique"}},
        )
    assert row["status"] == 200
    assert row["outcome"] == "ok"
    assert row["detail"] is None
