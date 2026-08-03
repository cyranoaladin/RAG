"""LOT43 (suite) : ferme les derniers endpoints legacy interrogeant ChromaDB.

`/collections` et `/stats/{collection_name}` (src/ingestor/api.py) lisent
ChromaDB directement — plus utilisés par l'UI v2 (cf.
test_ui_app_v2_admin.py, qui vérifie leur absence au profit de
`/collections/v2`). Ils doivent être fermés (410) au niveau Nginx, sans
bloquer les routes v2 homonymes par préfixe (`/collections/v2`,
`/collections/readiness`).
"""

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


def _has_exact_or_prefix_block(config: str, path: str) -> bool:
    for mod in ("=", "^~"):
        pattern = rf"location\s+{re.escape(mod)}\s+{re.escape(path)}\s*\{{(?P<body>.*?)^\s*\}}"
        match = re.search(pattern, config, re.MULTILINE | re.DOTALL)
        if match:
            return "return 410" in match.group("body")
    return False


def test_v2_proxy_closes_legacy_chromadb_collections_and_stats() -> None:
    config = _read("rag-v2.conf")

    assert _has_exact_or_prefix_block(config, "/collections"), (
        "/collections (ChromaDB direct) must be closed with return 410"
    )
    assert _has_exact_or_prefix_block(config, "/stats"), (
        "/stats/{name} (ChromaDB direct) must be closed with return 410"
    )

    # /collections/v2 and /collections/readiness (retrieval_v2_endpoint.py)
    # must remain reachable — no dedicated closing block should shadow them,
    # and the exact-match closure of /collections must not be a prefix.
    assert not re.search(
        r"location\s+\^~\s+/collections\s*\{", config
    ), "/collections closure must be an exact match, not a prefix (would shadow /collections/v2)"


def test_rendered_api_template_closes_legacy_chromadb_collections_and_stats() -> None:
    config = _read("rag-api.conf.template")

    assert _has_exact_or_prefix_block(config, "/collections"), (
        "/collections (ChromaDB direct) must be closed with return 410"
    )
    assert _has_exact_or_prefix_block(config, "/stats"), (
        "/stats/{name} (ChromaDB direct) must be closed with return 410"
    )
    assert not re.search(
        r"location\s+\^~\s+/collections\s*\{", config
    ), "/collections closure must be an exact match, not a prefix (would shadow /collections/v2)"
