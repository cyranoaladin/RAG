"""Le verdict C0 doit échouer fermé sur la vraie charge déclarée."""

from __future__ import annotations

import base64
import json
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
        "error_rate_max": 0,
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
    assert validate_api_url("http://127.0.0.1:18003") == "http://127.0.0.1:18003"
    with pytest.raises(ValueError):
        validate_api_url("http://127.0.0.1:8001")
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

    failed_sampler = _measurement()
    failed_sampler["db_connections"]["sampler_failure"] = "SamplerJoinTimeout"
    assert evaluate_measurement(failed_sampler, BUDGET)["pass"] is False


def test_c0_refuses_external_suite_or_budget_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="suite canonique"):
        c0._assert_canonical_input_paths(tmp_path / "suite.json", c0.DEFAULT_BUDGET)
    with pytest.raises(ValueError, match="budget canonique"):
        c0._assert_canonical_input_paths(c0.DEFAULT_SUITE, tmp_path / "budget.json")


def test_c0_reads_remote_main_live_and_refuses_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def remote(*args: object, **kwargs: object) -> str:
        assert args[0] == ["git", "-C", str(c0.REPOSITORY_ROOT), "ls-remote", "origin", "refs/heads/main"]
        return "a" * 40 + "\trefs/heads/main\n"

    monkeypatch.setattr(c0.subprocess, "check_output", remote)
    assert c0._live_main_sha() == "a" * 40
    monkeypatch.setattr(c0.subprocess, "check_output", lambda *args, **kwargs: "garbage")
    with pytest.raises(ValueError, match="main distant"):
        c0._live_main_sha()


def test_sampler_join_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = c0._DbSampler("unused")
    monkeypatch.setattr(sampler, "join", lambda timeout: None)
    monkeypatch.setattr(sampler, "is_alive", lambda: True)
    sampler.stop()
    assert sampler.failure == "SamplerJoinTimeout"


def test_real_http_shape_requires_signed_scope_and_complete_citation() -> None:
    scope_id = c0.rag_query.available_scopes()[0]
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/v2"
        assert request.headers["authorization"] == "Bearer bff-secret"
        assert request.headers["x-rag-api-key"] == "api-key"
        token_parts = request.headers["x-nexus-identity"].split(".")
        assert len(token_parts) == 3
        claims = json.loads(base64.urlsafe_b64decode(token_parts[1] + "=="))
        assert claims["scope_id"] == scope_id
        assert len(claims["allowed_collections"]) == 1
        payload = json.loads(request.content)
        assert payload["student_profile"]["niveau"]
        assert payload["curriculum_scope"]["matiere"]
        return httpx.Response(200, json={
            "results": [{
                "chunk_id": "chunk-1", "doc_id": "doc-1", "score": 1,
                "excerpt": "La norme européenne", "citation": {
                    "source_label": "BOEN", "page": None,
                    "source_uri": "https://example.org/boen.pdf", "rights": "officiel_public",
                },
                "metadata": {"collection": "collection-1", "content_sha256": "a" * 64},
            }]
        })

    config = c0.rag_query.ClientConfig(
        api_url="http://127.0.0.1:8001", bff_token="bff-secret",
        internal_secret="internal-secret-32-characters-long", internal_issuer="issuer",
        internal_audience="audience", identity_issuer="sso", identity_audience="cockpit",
    )
    token, payload = c0._prepare_request(
        ("collection-1", scope_id, "Question pédagogique", "a" * 64), config
    )
    with httpx.Client(base_url="http://127.0.0.1:8001", transport=httpx.MockTransport(handle)) as client:
        row = c0._one_request(
            ("collection-1", scope_id, "Question pédagogique", "a" * 64),
            config=config, api_key="api-key", timeout_s=7.5, client=client,
            identity_token=token, payload=payload,
        )
    assert row["status"] == 200
    assert row["outcome"] == "ok"
    assert row["detail"] is None


def test_c0_refuses_one_result_without_content_identity_even_if_expected_source_is_present() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [
            {
                "chunk_id": "expected", "doc_id": "doc-1", "score": 1,
                "excerpt": "Texte", "citation": {
                    "source_label": "BOEN", "source_uri": "https://example.org/boen.pdf",
                    "rights": "officiel_public",
                },
                "metadata": {"collection": "collection-1", "content_sha256": "a" * 64},
            },
            {
                "chunk_id": "missing", "doc_id": "doc-2", "score": 0.5,
                "excerpt": "Autre texte", "citation": {
                    "source_label": "Autre", "source_uri": "https://example.org/other.pdf",
                    "rights": "officiel_public",
                },
                "metadata": {"collection": "collection-1"},
            },
        ]})

    config = c0.rag_query.ClientConfig(
        api_url="http://127.0.0.1:8001", bff_token="bff-secret",
        internal_secret="internal-secret-32-characters-long", internal_issuer="issuer",
        internal_audience="audience", identity_issuer="sso", identity_audience="cockpit",
    )
    with httpx.Client(base_url="http://127.0.0.1:8001", transport=httpx.MockTransport(handle)) as client:
        row = c0._one_request(
            ("collection-1", "scope-1", "Question pédagogique", "a" * 64),
            config=config, api_key="api-key", timeout_s=7.5, client=client,
            identity_token="signed-identity", payload={"need": {"query": "Question pédagogique"}},
        )
    assert row["outcome"] == "error"
    assert row["detail"] == "scope_or_citation"


def test_c0_evidence_is_private_and_cannot_overwrite_prior_measurement(tmp_path: Path) -> None:
    path = tmp_path / "qualification" / "c0.json"
    c0.write_report(path, {"verdict": {"pass": False}})
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(FileExistsError):
        c0.write_report(path, {"verdict": {"pass": True}})
    assert '"pass": false' in path.read_text()


def test_c0_evidence_refuses_permissive_parent_and_never_exposes_partial_final(tmp_path: Path) -> None:
    directory = tmp_path / "qualification"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    path = directory / "c0.json"
    with pytest.raises(PermissionError):
        c0.write_report(path, {"verdict": {"pass": True}})
    assert not path.exists()

    directory.chmod(0o700)
    with pytest.raises(TypeError):
        c0.write_report(path, {"unserializable": object()})
    assert not path.exists()
    assert list(directory.iterdir()) == []
