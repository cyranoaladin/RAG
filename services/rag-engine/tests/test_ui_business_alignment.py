"""Red tests — UI business alignment with RAG v2 catalogue.

These tests verify that app_v2.py is aligned with the v2 business model.
They check for absence of legacy references and presence of v2 patterns.
"""
from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
APP_V2 = ENGINE_ROOT / "src" / "ui" / "app_v2.py"

LEGACY_COLLECTIONS = [
    "rag_francais_premiere",
    "rag_maths_premiere",
    "rag_education",
    "rag_web3",
    "rag_divers",
]

LEGACY_STATS_PATTERNS = [
    '/stats/rag_',
    '/stats/{collection_education}',
]


def _read_app() -> str:
    return APP_V2.read_text(encoding="utf-8")


# --- Legacy collection references ---

def test_no_legacy_collection_rag_francais_premiere():
    content = _read_app()
    assert "rag_francais_premiere" not in content, (
        "app_v2.py still references legacy collection rag_francais_premiere"
    )


def test_no_legacy_collection_rag_maths_premiere():
    content = _read_app()
    assert "rag_maths_premiere" not in content, (
        "app_v2.py still references legacy collection rag_maths_premiere"
    )


def test_no_legacy_collection_rag_education():
    content = _read_app()
    assert "rag_education" not in content, (
        "app_v2.py still references legacy collection rag_education"
    )


def test_no_legacy_collection_rag_web3():
    content = _read_app()
    assert "rag_web3" not in content, (
        "app_v2.py still references legacy collection rag_web3"
    )


def test_no_legacy_collection_rag_divers():
    content = _read_app()
    assert "rag_divers" not in content, (
        "app_v2.py still references legacy collection rag_divers"
    )


# --- Legacy stats endpoint ---

def test_no_legacy_stats_calls():
    content = _read_app()
    for pattern in LEGACY_STATS_PATTERNS:
        assert pattern not in content, (
            f"app_v2.py still calls legacy stats endpoint: {pattern}"
        )


# --- V2 catalogue as source of truth ---

def test_ui_uses_catalogue_v2_for_dashboard():
    """Dashboard must use /catalogue/v2 or /collections/v2 for full catalogue."""
    content = _read_app()
    assert "/catalogue/v2" in content or "/collections/v2" in content


def test_dashboard_shows_catalogue_metrics():
    """Dashboard must display declared/instanciated/retrievable counts."""
    content = _read_app()
    for term in ["instanci", "retrievable", "declaree", "declared"]:
        if term in content.lower():
            return
    raise AssertionError(
        "Dashboard does not display instanciated/retrievable/declared metrics"
    )


def test_administration_shows_full_catalogue():
    """Administration must distinguish instanciated vs non-instanciated."""
    content = _read_app()
    assert "non instanci" in content.lower() or "not instantiated" in content.lower() or \
           "non_instanci" in content.lower() or "declaree" in content.lower(), (
        "Administration does not distinguish instanciated vs non-instanciated collections"
    )


def test_recherche_uses_only_v2():
    """Recherche page must use only /search/v2 and /collections/v2."""
    content = _read_app()
    assert "/search/v2" in content
    assert "/collections/v2" in content


def test_ingestion_uses_v2_catalogue():
    """Ingestion must derive targets from v2 catalogue, not legacy hardcoded lists."""
    content = _read_app()
    assert "ALL_COLLECTIONS" not in content, (
        "app_v2.py still uses hardcoded ALL_COLLECTIONS list"
    )


def test_no_web3_main_page():
    """Web3 must not be a main navigation page."""
    content = _read_app()
    assert "Web3 & Blockchain" not in content, (
        "Web3 & Blockchain is still a main navigation page"
    )


def test_no_divers_page():
    """Divers must not be a main navigation page."""
    content = _read_app()
    # "Divers" as a page nav entry should be gone
    assert '"📦 Divers"' not in content, (
        "Divers is still a main navigation page"
    )


def test_no_maths_1ere_legacy_page():
    """Maths 1ere legacy page must not exist as a navigation entry."""
    content = _read_app()
    assert "Maths 1" not in content, (
        "Legacy Maths 1ere page still exists"
    )
