"""Surface Nginx LOT41 : seul le retrieval gouverné reste exposé."""

from __future__ import annotations

import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
NGINX = ENGINE_ROOT / "infra" / "nginx"


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


def test_v2_proxy_closes_legacy_retrieval_and_keeps_canonical_bff_routes() -> None:
    config = _read("rag-v2.conf")

    for location in (
        "location = /search",
        "location ^~ /search/",
        "location ^~ /kb",
        "location ^~ /rag",
    ):
        block = _location_block(config, location)
        assert "return 410" in block
        assert "proxy_pass" not in block

    for location in ("location = /search/v2", "location = /chat"):
        block = _location_block(config, location)
        assert "proxy_pass http://rag_api" in block


def test_rendered_api_template_applies_the_same_fail_closed_boundary() -> None:
    config = _read("rag-api.conf.template")

    for location in (
        "location = /search",
        "location ^~ /search/",
        "location ^~ /kb",
        "location ^~ /rag",
    ):
        block = _location_block(config, location)
        assert "return 410" in block
        assert "proxy_pass" not in block

    for location in ("location = /search/v2", "location = /chat"):
        block = _location_block(config, location)
        assert "proxy_pass http://127.0.0.1:${NGINX_API_PORT}" in block
