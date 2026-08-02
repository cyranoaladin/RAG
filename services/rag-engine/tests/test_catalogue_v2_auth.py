"""Tests — autorité BFF et rôles signés de /catalogue/v2."""
from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_FILE = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"


def _read_endpoint() -> str:
    return ENDPOINT_FILE.read_text(encoding="utf-8")


# --- /collections/v2 LOT41 ---

def test_collections_v2_requires_bff_identity_and_filters_signed_scope():
    """Le picker BFF ne réutilise plus les jetons humains historiques."""
    import re

    content = _read_endpoint()
    pattern = (
        r'@router\.get\("/collections/v2"\)'
        r'.*?def list_retrievable_collections'
        r'.*?(?=@router\.|# --- Full catalogue)'
    )
    match = re.search(pattern, content, re.DOTALL)
    assert match, "/collections/v2 endpoint not found"
    endpoint = match.group(0)
    assert '_require_retrieval_identity(request, endpoint="/collections/v2")' in endpoint
    assert "effective_signed_collections(verified)" in endpoint
    assert "build_server_retrieval_scope" in endpoint
    assert "_enforce_security_v2" not in endpoint


# --- /search/v2 unchanged ---

def test_search_v2_not_modified():
    """Verify /search/v2 route is still present and unchanged."""
    content = _read_endpoint()
    assert '/search/v2"' in content


# --- Runtime-like test ---

def test_catalogue_v2_function_returns_expected_structure():
    """Call _full_catalogue directly to verify schema."""
    import sys
    sys.path.insert(0, str(ENGINE_ROOT / "src"))
    try:
        from ingestor.retrieval_v2_endpoint import _full_catalogue
        result = _full_catalogue()
        assert result["version"] == 2
        assert isinstance(result["collections"], list)
        assert len(result["collections"]) >= 30
        assert "by_level" in result
        assert "by_domain" in result
        assert "by_status" in result
        # Verify enhanced fields
        for c in result["collections"]:
            assert "taxonomy_exists" in c, f"{c['name']} missing taxonomy_exists"
            assert "coherence_issues" in c, f"{c['name']} missing coherence_issues"
            assert "ingestion_enabled_reason" in c
            assert "search_enabled_reason" in c
    finally:
        sys.path.pop(0)
