"""Surface Nginx LOT41U : allowlist exacte du runtime lecture/revue."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
NGINX = ENGINE_ROOT / "infra" / "nginx"
PROXIED_PATHS = {
    "/health",
    "/metrics",
    "/search/v2",
    "/chat",
    "/collections/v2",
    "/catalogue/v2",
    "/collections/readiness",
    "/review/v2/queue",
    "/review/v2/decide",
}
LEGACY_LOCATIONS = (
    "location = /ingest",
    "location ^~ /ingest/",
    "location = /search",
    "location ^~ /search/",
    "location ^~ /admin",
    "location ^~ /stats",
    "location ^~ /eval",
    "location ^~ /kb",
    "location ^~ /rag",
)


def _read(name: str) -> str:
    return (NGINX / name).read_text(encoding="utf-8")


def _location_block(config: str, location: str) -> str:
    match = re.search(
        rf"{re.escape(location)}\s*\{{(?P<body>.*?)^\s*\}}",
        config,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing Nginx block: {location}"
    return match.group("body")


def _proxied_location_selectors(config: str) -> set[str]:
    proxied: set[str] = set()
    for match in re.finditer(
        r"^\s*location\s+(?P<selector>[^\{]+?)\s*\{(?P<body>.*?)^\s*\}",
        config,
        re.MULTILINE | re.DOTALL,
    ):
        if "proxy_pass" in match.group("body"):
            proxied.add(" ".join(match.group("selector").split()))
    return proxied


@pytest.mark.parametrize("name", ["rag-v2.conf", "rag-api.conf.template"])
def test_proxy_exposes_exact_runtime_allowlist(name: str) -> None:
    config = _read(name)
    assert _proxied_location_selectors(config) == {
        f"= {path}" for path in PROXIED_PATHS
    }


def test_host_vhost_targets_the_loopback_published_compose_port() -> None:
    config = _read("rag-v2.conf")

    assert "server 127.0.0.1:${NGINX_API_PORT};" in config
    assert "server ingestor:" not in config


def test_materialized_tls_vhost_has_a_documented_exact_render_command() -> None:
    config = _read("rag-v2.conf")
    readme = _read("README.md")

    assert "server_name ${RAG_API_EXTERNAL_DOMAIN};" in config
    assert (
        "envsubst '${RAG_API_EXTERNAL_DOMAIN} ${NGINX_API_PORT}'"
        in readme
    )
    assert "< infra/nginx/rag-v2.conf" in readme


@pytest.mark.parametrize("name", ["rag-v2.conf", "rag-api.conf.template"])
def test_proxy_closes_all_legacy_routes_without_forwarding(name: str) -> None:
    config = _read(name)

    for location in LEGACY_LOCATIONS:
        block = _location_block(config, location)
        assert "return 410" in block
        assert "proxy_pass" not in block


@pytest.mark.parametrize("name", ["rag-v2.conf", "rag-api.conf.template"])
def test_metrics_is_loopback_only_and_default_is_404(name: str) -> None:
    config = _read(name)
    metrics = _location_block(config, "location = /metrics")
    default = _location_block(config, "location /")

    assert "allow 127.0.0.1" in metrics
    assert "allow ::1" in metrics
    assert "deny all" in metrics
    assert "return 404" in default
    assert "proxy_pass" not in default


@pytest.mark.parametrize("name", ["rag-v2.conf", "rag-api.conf.template"])
def test_deep_health_is_loopback_only(name: str) -> None:
    health = _location_block(_read(name), "location = /health")

    assert "allow 127.0.0.1" in health
    assert "allow ::1" in health
    assert "deny all" in health


@pytest.mark.parametrize(
    ("name", "rate", "burst"),
    [
        ("rag-v2.conf", 30, 60),
        ("rag-api.conf.template", 20, 40),
    ],
)
def test_collection_readiness_does_not_charge_the_business_request_bucket(
    name: str,
    rate: int,
    burst: int,
) -> None:
    config = _read(name)
    readiness = _location_block(config, "location = /collections/readiness")

    assert "limit_req zone=api_v2" not in readiness
    assert f"limit_req zone=readiness_v2 burst={burst} nodelay;" in readiness
    assert f"zone=readiness_v2:10m rate={rate}r/s;" in config


def test_canonical_v2_runtime_uses_one_metrics_process() -> None:
    compose = (ENGINE_ROOT / "infra" / "docker-compose.v2.yml").read_text(
        encoding="utf-8"
    )

    assert "uvicorn api_v2:app --host 0.0.0.0 --port 8001 --workers 1" in compose
    assert "INGESTOR_WORKERS" not in compose


@pytest.mark.parametrize("name", ["rag-v2.conf", "rag-api.conf.template"])
def test_proxy_has_no_legacy_upstream_or_forwarded_header_authority(name: str) -> None:
    config = _read(name)

    for forbidden in (
        "upstream rag_ui",
        "server ui:",
        "$host",
        "X-Forwarded-For",
        "X-Forwarded-Host",
        "X-Forwarded-Proto",
    ):
        assert forbidden not in config
