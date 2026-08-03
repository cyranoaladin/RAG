"""LOT43 : ferme les endpoints d'ingestion legacy, ne laisse passer que /ingest/v2/*.

Les routes historiques (/ingest, /ingest/urls, /ingest/upload-files, /ingest/drive,
/ingest/check-duplicates) restent définies dans src/ingestor/api.py mais ne doivent
plus jamais être atteignables depuis l'extérieur : Nginx doit les fermer en 410
avant qu'elles n'atteignent l'upstream, tout en laissant passer /ingest/v2/*.
"""

from __future__ import annotations

import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
NGINX = ENGINE_ROOT / "infra" / "nginx"

LEGACY_INGEST_PATHS = (
    "/ingest",
    "/ingest/urls",
    "/ingest/upload-files",
    "/ingest/drive",
    "/ingest/drive/status/some-task-id",
    "/ingest/check-duplicates",
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


def _prefix_locations(config: str) -> list[tuple[str, bool, str]]:
    """Return (prefix, is_exact_or_priority, body) for every /ingest* location."""
    results: list[tuple[str, bool, str]] = []
    for match in re.finditer(
        r"location\s+(?P<mod>=|\^~)?\s*(?P<path>/ingest\S*)\s*\{(?P<body>.*?)^\s*\}",
        config,
        re.MULTILINE | re.DOTALL,
    ):
        results.append((match.group("path"), match.group("mod") is not None, match.group("body")))
    return results


def _closes_path(config: str, path: str) -> bool:
    """Simulate Nginx's longest-prefix-wins matching for /ingest* locations."""
    candidates = _prefix_locations(config)
    for prefix, _is_priority, body in candidates:
        if prefix == path:
            return "return 410" in body
    best: tuple[str, str] | None = None
    for prefix, _is_priority, body in candidates:
        if path == prefix or path.startswith(prefix.rstrip("/") + "/") or path.startswith(prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, body)
    assert best is not None, f"no Nginx location covers {path}"
    return "return 410" in best[1]


def test_v2_proxy_closes_legacy_ingest_endpoints() -> None:
    config = _read("rag-v2.conf")
    for path in LEGACY_INGEST_PATHS:
        assert _closes_path(config, path), f"{path} must be closed (410) in rag-v2.conf"

    v2_block = _location_block(config, "location ^~ /ingest/v2/")
    assert "proxy_pass http://rag_api" in v2_block
    assert "return 410" not in v2_block


def test_rendered_api_template_closes_legacy_ingest_endpoints() -> None:
    config = _read("rag-api.conf.template")
    for path in LEGACY_INGEST_PATHS:
        assert _closes_path(config, path), f"{path} must be closed (410) in rag-api.conf.template"

    v2_block = _location_block(config, "location ^~ /ingest/v2/")
    assert "proxy_pass http://127.0.0.1:${NGINX_API_PORT}" in v2_block
    assert "return 410" not in v2_block
