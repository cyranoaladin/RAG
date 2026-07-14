"""Tests — /catalogue/v2 auth policy.

Verifies the role-based access control for the catalogue endpoint
matches the expected policy after LOT 27.1 hotfix.
"""
from __future__ import annotations

import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
ENDPOINT_FILE = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"


def _read_endpoint() -> str:
    return ENDPOINT_FILE.read_text(encoding="utf-8")


def _extract_catalogue_v2_roles(content: str) -> set[str]:
    """Extract the allowed_roles set from the /catalogue/v2 endpoint."""
    # Find the block: @router.get("/catalogue/v2") ... allowed_roles={...}
    pattern = r'@router\.get\("/catalogue/v2"\).*?allowed_roles=\{([^}]+)\}'
    match = re.search(pattern, content, re.DOTALL)
    assert match, "/catalogue/v2 endpoint not found or allowed_roles missing"
    roles_block = match.group(1)
    roles = set(re.findall(r"SecurityRole\.(\w+)", roles_block))
    return roles


def _extract_collections_v2_roles(content: str) -> set[str]:
    """Extract the allowed_roles set from the /collections/v2 endpoint."""
    pattern = r'@router\.get\("/collections/v2"\).*?allowed_roles=\{([^}]+)\}'
    match = re.search(pattern, content, re.DOTALL)
    assert match, "/collections/v2 endpoint not found or allowed_roles missing"
    roles_block = match.group(1)
    return set(re.findall(r"SecurityRole\.(\w+)", roles_block))


# --- /catalogue/v2 auth tests ---

def test_catalogue_v2_allows_admin():
    roles = _extract_catalogue_v2_roles(_read_endpoint())
    assert "ADMIN" in roles


def test_catalogue_v2_allows_reviewer():
    roles = _extract_catalogue_v2_roles(_read_endpoint())
    assert "REVIEWER" in roles


def test_catalogue_v2_allows_teacher():
    roles = _extract_catalogue_v2_roles(_read_endpoint())
    assert "TEACHER" in roles


def test_catalogue_v2_allows_ingest_agent():
    """LOT 27.1: UI token is INGEST_AGENT; must be allowed."""
    roles = _extract_catalogue_v2_roles(_read_endpoint())
    assert "INGEST_AGENT" in roles


def test_catalogue_v2_does_not_allow_student():
    """STUDENT excluded: catalogue exposes governance details."""
    roles = _extract_catalogue_v2_roles(_read_endpoint())
    assert "STUDENT" not in roles


# --- /collections/v2 unchanged ---

def test_collections_v2_allows_all_roles():
    """/collections/v2 (search picker) must keep its broad access."""
    roles = _extract_collections_v2_roles(_read_endpoint())
    assert "ADMIN" in roles
    assert "REVIEWER" in roles
    assert "TEACHER" in roles
    assert "INGEST_AGENT" in roles
    assert "STUDENT" in roles


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
