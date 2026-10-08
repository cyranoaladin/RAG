"""Prometheus metrics helpers for ingest services."""

# -----------------------------------------------------------------------------
# Metrics Contract (documentation only)
# -----------------------------------------------------------------------------
# - This service exposes a single CollectorRegistry via ``REGISTRY``.
#   ALL counters/histograms must register against THIS instance (not the global
#   registry). That preserves per-process isolation and predictable scrape
#   surfaces in tests.
#
# - Gating par ``METRICS_ENABLED`` :
#   * By default metrics stay ENABLED until the environment variable is set to
#     ``false`` explicitly.
#   * The ``/metrics`` endpoint MUST return 404 when disabled.
#   * Metric helper functions MUST no-op when disabled.
#
# - Namespace guidance:
#   * ``METRICS_NAMESPACE`` scopes legacy ingest families (e.g. ``rag_*``).
#   * Retrieval families keep their fixed ``retrieval_*`` names, shared with
#     the operational alert rules and the go-live metric contract.
#   * Counters/histograms should always pass ``registry=REGISTRY``.
#
# - Tests:
#   * Tests can monkeypatch ``ingest_metrics.METRICS_ENABLED`` to steer
#     ``/metrics`` behaviour without re-importing the module.
#   * This documentation block introduces zero functional changes.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar, cast

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

if __package__:
    from .retrieval_observability import RETRIEVAL_ERROR_CAUSES
else:
    from retrieval_observability import RETRIEVAL_ERROR_CAUSES  # type: ignore[no-redef]

__all__ = [
    "METRICS_ENABLED",
    "REGISTRY",
    "generate_latest",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "INGEST_RESULT",
    "ingest_requests_total",
    "record_request",
    "record_http_request",
    "observe_latency",
    "record_success",
    "record_failure",
    "record_chunk",
    "record_bytes",
    "track_latency",
    "track_mm_parse_latency",
    "record_mm_chunk",
    "record_mm_failure",
    "record_retrieval_http",
    "record_retrieval_tie_overflow",
    "observe_retrieval_stage",
]

METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
NAMESPACE = os.getenv("METRICS_NAMESPACE", "rag_local")

REGISTRY = CollectorRegistry()

_REQUESTS = Counter(
    f"{NAMESPACE}_ingest_requests_total",
    "Total ingest endpoint requests",
    ("route", "method"),
    registry=REGISTRY,
)
_SUCCESS = Counter(
    f"{NAMESPACE}_ingest_success_total",
    "Successful ingests by modality",
    ("modality",),
    registry=REGISTRY,
)
_FAILURE = Counter(
    f"{NAMESPACE}_ingest_failure_total",
    "Failed ingests by reason",
    ("reason",),
    registry=REGISTRY,
)
_CHUNKS = Counter(
    f"{NAMESPACE}_ingest_chunks_total",
    "Number of chunks stored by modality",
    ("modality",),
    registry=REGISTRY,
)
_BYTES = Counter(
    f"{NAMESPACE}_ingest_bytes_total",
    "Aggregate bytes persisted during ingest",
    registry=REGISTRY,
)
_LATENCY = Histogram(
    f"{NAMESPACE}_ingest_latency_seconds",
    "Latency observed per ingest route",
    ("route",),
    buckets=(0.1, 0.3, 0.6, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

_MM_LATENCY = Histogram(
    f"{NAMESPACE}_mm_parse_latency_seconds",
    "Latency observed during multimodal parsing",
    buckets=(0.1, 0.3, 0.6, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)
_MM_CHUNKS = Counter(
    f"{NAMESPACE}_mm_chunks_total",
    "Number of multimodal chunks emitted by modality",
    ("modality",),
    registry=REGISTRY,
)
_MM_BYTES = Counter(
    f"{NAMESPACE}_mm_bytes_total",
    "Bytes processed while emitting multimodal chunks",
    ("modality",),
    registry=REGISTRY,
)
_MM_FAILURES = Counter(
    f"{NAMESPACE}_mm_parse_failures_total",
    "Multimodal parse failures by reason",
    ("reason",),
    registry=REGISTRY,
)

# Route et causes à cardinalité fermée : ni requête, ni collection, ni identité
# élève ne deviennent des labels Prometheus.
_RETRIEVAL_CAUSES = RETRIEVAL_ERROR_CAUSES
_RETRIEVAL_REQUESTS = Counter(
    "retrieval_requests_total", "POST /search/v2 requests", registry=REGISTRY
)
_RETRIEVAL_ERRORS = Counter(
    "retrieval_errors_total", "Retrieval failures by bounded cause", ("cause",), registry=REGISTRY
)
_RETRIEVAL_EMPTY = Counter(
    "retrieval_empty_results_total", "Valid searches with no results", registry=REGISTRY
)
_RETRIEVAL_SCOPE_REFUSALS = Counter(
    "retrieval_scope_refusals_total", "Search scope refusals", registry=REGISTRY
)
_RETRIEVAL_HTTP_503 = Counter(
    "retrieval_http_503_total", "Search HTTP 503 responses", registry=REGISTRY
)
_RETRIEVAL_TIE_OVERFLOW = Counter(
    "retrieval_tie_overflow_total", "Dense ANN tie overflows", registry=REGISTRY
)
_RETRIEVAL_LATENCY_BUCKETS = (0.01, 0.03, 0.1, 0.3, 0.6, 1.0, 3.0, 6.0, 7.5, 10.0)
_RETRIEVAL_STAGE_LATENCY = {
    stage: Histogram(
        f"retrieval_{stage}_latency_seconds",
        f"Retrieval {stage} stage latency",
        buckets=_RETRIEVAL_LATENCY_BUCKETS,
        registry=REGISTRY,
    )
    for stage in ("dense", "lexical", "reranker")
}
_RETRIEVAL_TOTAL_LATENCY = Histogram(
    "retrieval_total_search_latency_seconds",
    "POST /search/v2 end-to-end latency",
    buckets=_RETRIEVAL_LATENCY_BUCKETS,
    registry=REGISTRY,
)

if "REQUEST_COUNT" not in globals():
    REQUEST_COUNT = Counter(
        "ingestor_requests_total",
        "Total requests",
        ("path", "method", "code"),
        registry=REGISTRY,
    )

if "REQUEST_LATENCY" not in globals():
    REQUEST_LATENCY = Histogram(
        "ingestor_request_latency_seconds",
        "Request latency",
        ("path", "method"),
        registry=REGISTRY,
    )

if "INGEST_RESULT" not in globals():
    INGEST_RESULT = Counter(
        "ingestor_ingest_events_total",
        "Ingest events",
        ("status",),
        registry=REGISTRY,
    )

if "ingest_requests_total" not in globals():
    ingest_requests_total = Counter(
        "ingest_requests_total",
        "Ingest request outcomes by source and modality",
        ("source", "modality", "status"),
        registry=REGISTRY,
    )


F = TypeVar("F", bound=Callable[..., object])


def _guarded(func: F) -> F:
    def wrapper(*args: Any, **kwargs: Any) -> object | None:
        if not METRICS_ENABLED:
            return None
        return func(*args, **kwargs)

    return cast(F, wrapper)


@_guarded
def record_request(route: str, method: str) -> None:
    _REQUESTS.labels(route=route, method=method).inc()


@_guarded
def record_http_request(path: str, method: str, code: int, seconds: float) -> None:
    """Observer une requête HTTP sur une route à cardinalité déjà bornée."""
    REQUEST_COUNT.labels(path=path, method=method, code=str(code)).inc()
    REQUEST_LATENCY.labels(path=path, method=method).observe(max(seconds, 0.0))


@_guarded
def observe_latency(route: str, seconds: float) -> None:
    _LATENCY.labels(route=route).observe(seconds)


@_guarded
def record_success(modality: str) -> None:
    _SUCCESS.labels(modality=modality).inc()


@_guarded
def record_failure(reason: str) -> None:
    _FAILURE.labels(reason=reason).inc()


@_guarded
def record_chunk(modality: str) -> None:
    _CHUNKS.labels(modality=modality).inc()


@_guarded
def record_bytes(amount: int) -> None:
    if amount < 0:
        return
    _BYTES.inc(amount)


@contextmanager
def track_latency(route: str) -> Iterator[None]:
    if not METRICS_ENABLED:
        yield
        return
    with _LATENCY.labels(route=route).time():
        yield


def _normalize_modality(modality: str) -> str:
    normalized = (modality or "").strip().lower()
    if normalized in {"text", "image", "table", "formula"}:
        return normalized
    return "other"


@contextmanager
def track_mm_parse_latency() -> Iterator[None]:
    if not METRICS_ENABLED:
        yield
        return
    with _MM_LATENCY.time():
        yield


@_guarded
def record_mm_chunk(modality: str, nbytes: int) -> None:
    safe_modality = _normalize_modality(modality)
    _MM_CHUNKS.labels(modality=safe_modality).inc()
    if nbytes > 0:
        _MM_BYTES.labels(modality=safe_modality).inc(nbytes)


@_guarded
def record_mm_failure(reason: str) -> None:
    safe_reason = (reason or "unknown").strip().lower().replace(" ", "_")
    if not safe_reason:
        safe_reason = "unknown"
    _MM_FAILURES.labels(reason=safe_reason).inc()


@_guarded
def record_retrieval_http(
    *, status_code: int, seconds: float, cause: str | None = None, empty: bool = False
) -> None:
    """Compter une seule fois chaque POST search, sans rompre le service si Prometheus échoue."""
    try:
        _RETRIEVAL_REQUESTS.inc()
        _RETRIEVAL_TOTAL_LATENCY.observe(max(seconds, 0.0))
        if status_code == 200 and empty:
            _RETRIEVAL_EMPTY.inc()
        if status_code == 403:
            _RETRIEVAL_SCOPE_REFUSALS.inc()
        if status_code == 503:
            _RETRIEVAL_HTTP_503.inc()
        if status_code >= 400:
            fallback = (
                "authentication" if status_code == 401 else
                "scope_refusal" if status_code == 403 else
                "invalid_request" if status_code in {400, 422} else
                "service_unavailable" if status_code == 503 else
                "internal_error"
            )
            _RETRIEVAL_ERRORS.labels(
                cause=cause if cause in _RETRIEVAL_CAUSES else fallback
            ).inc()
    except Exception:  # pragma: no cover - observabilité non bloquante
        pass


@_guarded
def observe_retrieval_stage(stage: str, seconds: float) -> None:
    """Observer uniquement les trois étapes exécutées, sans label dynamique."""
    histogram = _RETRIEVAL_STAGE_LATENCY.get(stage)
    if histogram is None:
        return
    try:
        histogram.observe(max(seconds, 0.0))
    except Exception:  # pragma: no cover - observabilité non bloquante
        pass


@_guarded
def record_retrieval_tie_overflow() -> None:
    try:
        _RETRIEVAL_TIE_OVERFLOW.inc()
    except Exception:  # pragma: no cover - observabilité non bloquante
        pass
