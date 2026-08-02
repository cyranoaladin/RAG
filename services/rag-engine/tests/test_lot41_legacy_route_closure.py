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
