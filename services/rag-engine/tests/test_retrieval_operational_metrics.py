"""Signaux opérationnels du retrieval v2, sans dimensions utilisateur libres."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ingestor import metrics
from ingestor import retrieval_v2_endpoint as endpoint
from ingestor.retrieval_observability import RetrievalAccessRecord


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return float(metrics.REGISTRY.get_sample_value(name, labels or {}) or 0)


def test_retrieval_metrics_count_requests_causes_empty_and_bounded_stages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metrics, "METRICS_ENABLED", True)
    before = {
        "requests": _sample("retrieval_requests_total"),
        "errors": _sample("retrieval_errors_total", {"cause": "pool_failure"}),
        "empty": _sample("retrieval_empty_results_total"),
        "refusals": _sample("retrieval_scope_refusals_total"),
        "unavailable": _sample("retrieval_http_503_total"),
        "ties": _sample("retrieval_tie_overflow_total"),
        "dense": _sample("retrieval_dense_latency_seconds_count"),
        "lexical": _sample("retrieval_lexical_latency_seconds_count"),
        "reranker": _sample("retrieval_reranker_latency_seconds_count"),
        "total": _sample("retrieval_total_search_latency_seconds_count"),
    }

    metrics.record_retrieval_http(status_code=503, seconds=0.12, cause="pool_failure")
    metrics.record_retrieval_http(status_code=403, seconds=0.03, cause="scope_refusal")
    metrics.record_retrieval_http(status_code=200, seconds=0.5, empty=True)
    metrics.record_retrieval_tie_overflow()
    for stage in ("dense", "lexical", "reranker"):
        metrics.observe_retrieval_stage(stage, 0.01)

    assert _sample("retrieval_requests_total") == before["requests"] + 3
    assert _sample("retrieval_errors_total", {"cause": "pool_failure"}) == before["errors"] + 1
    assert _sample("retrieval_empty_results_total") == before["empty"] + 1
    assert _sample("retrieval_scope_refusals_total") == before["refusals"] + 1
    assert _sample("retrieval_http_503_total") == before["unavailable"] + 1
    assert _sample("retrieval_tie_overflow_total") == before["ties"] + 1
    for stage in ("dense", "lexical", "reranker"):
        assert _sample(f"retrieval_{stage}_latency_seconds_count") == before[stage] + 1
    assert _sample("retrieval_total_search_latency_seconds_count") == before["total"] + 3

    monkeypatch.setattr(metrics, "METRICS_ENABLED", False)
    metrics.record_retrieval_http(status_code=503, seconds=1, cause="pool_failure")
    metrics.record_retrieval_tie_overflow()
    metrics.observe_retrieval_stage("dense", 1)
    assert _sample("retrieval_requests_total") == before["requests"] + 3
    assert _sample("retrieval_tie_overflow_total") == before["ties"] + 1
    assert _sample("retrieval_dense_latency_seconds_count") == before["dense"] + 1


def test_access_log_exposes_only_a_bounded_failure_cause() -> None:
    record = RetrievalAccessRecord(
        request_id="test-id",
        endpoint="/search/v2",
        client_id="client",
        granted_scopes=("rag:search",),
        status_code=503,
        latency_ms=200.0,
        cause="timeout",
    )

    assert record.as_mapping()["cause"] == "timeout"
    assert "query" not in record.as_json()


def test_wrapped_inference_timeout_retains_only_bounded_diagnostic() -> None:
    try:
        raise RuntimeError("secret model path") from TimeoutError("secret timeout")
    except RuntimeError as exc:
        assert endpoint._bounded_retrieval_failure_cause(exc) == "timeout"


def test_v2_prometheus_loads_the_retrieval_alert_file() -> None:
    root = Path(__file__).resolve().parents[1] / "infra"
    config = yaml.safe_load((root / "prometheus/prometheus.v2.yml").read_text())
    compose = yaml.safe_load((root / "docker-compose.v2.yml").read_text())
    prometheus = compose["services"]["prometheus"]
    rules_path = "/etc/prometheus/rules/retrieval.rules.yml"

    assert rules_path in config["rule_files"]
    assert "./prometheus/rules:/etc/prometheus/rules:ro" in prometheus["volumes"]
    alerts = yaml.safe_load((root / "prometheus/rules/retrieval.rules.yml").read_text())
    names = {rule["alert"] for group in alerts["groups"] for rule in group["rules"]}
    assert {"RAGRetrievalUnavailable", "RAGRetrievalTieOverflow", "RAGRetrievalP95High"} <= names
