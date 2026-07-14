"""Tests — UI business alignment with RAG v2 catalogue.

Verifies that app_v2.py is aligned with the v2 business model:
- No legacy collection references
- No legacy endpoint calls
- Uses v2 ingestion endpoints
- Uses v2 catalogue for all data
"""
from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
APP_V2 = ENGINE_ROOT / "src" / "ui" / "app_v2.py"


def _read_app() -> str:
    return APP_V2.read_text(encoding="utf-8")


# --- Legacy collection references must be absent ---

def test_no_legacy_collection_rag_francais_premiere():
    assert "rag_francais_premiere" not in _read_app()


def test_no_legacy_collection_rag_maths_premiere():
    assert "rag_maths_premiere" not in _read_app()


def test_no_legacy_collection_rag_education():
    assert "rag_education" not in _read_app()


def test_no_legacy_collection_rag_web3():
    assert "rag_web3" not in _read_app()


def test_no_legacy_collection_rag_divers():
    assert "rag_divers" not in _read_app()


# --- Legacy endpoints must be absent ---

def test_no_legacy_stats_calls():
    content = _read_app()
    assert '/stats/rag_' not in content
    assert '/stats/{collection_education}' not in content


def test_no_legacy_ingest_upload():
    """Must use /ingest/v2/upload-files, not /ingest/upload-files."""
    content = _read_app()
    assert '"/ingest/upload-files"' not in content


def test_no_legacy_ingest_urls():
    """Must use /ingest/v2/urls, not /ingest/urls."""
    content = _read_app()
    assert '"/ingest/urls"' not in content


def test_no_legacy_ingest_drive():
    """Must not call /ingest/drive (legacy)."""
    content = _read_app()
    assert '"/ingest/drive"' not in content


# --- V2 ingestion endpoints must be present ---

def test_uses_v2_upload():
    assert "/ingest/v2/upload-files" in _read_app()


def test_uses_v2_urls():
    assert "/ingest/v2/urls" in _read_app()


def test_drive_v2_handled():
    """Either uses /ingest/v2/drive or shows explicit 'not activated' message."""
    content = _read_app()
    assert "/ingest/v2/drive" in content or "501" in content or "non activ" in content.lower()


# --- V2 catalogue as source of truth ---

def test_ui_uses_catalogue_v2():
    content = _read_app()
    assert "/catalogue/v2" in content
    assert "/collections/v2" in content


def test_dashboard_shows_catalogue_metrics():
    content = _read_app()
    lower = content.lower()
    assert "instanci" in lower
    assert "retrievable" in lower


def test_administration_shows_full_catalogue():
    content = _read_app()
    lower = content.lower()
    assert "non instanci" in lower


def test_recherche_uses_only_v2():
    content = _read_app()
    assert "/search/v2" in content
    assert "/collections/v2" in content


def test_ingestion_uses_v2_catalogue():
    assert "ALL_COLLECTIONS" not in _read_app()


def test_no_web3_main_page():
    assert "Web3 & Blockchain" not in _read_app()


def test_no_divers_page():
    assert '"Divers"' not in _read_app()


def test_no_maths_1ere_legacy_page():
    assert "Maths 1" not in _read_app()


# --- UX: proper French accents (may be unicode escapes in source) ---

def _has_accent(content: str, *variants: str) -> bool:
    """Check if any variant is found in the file content."""
    return any(v in content for v in variants)


def test_french_accents_nexus_reussite():
    assert _has_accent(_read_app(), "R\u00e9ussite", "\\u00e9ussite")


def test_french_accents_premiere():
    assert _has_accent(_read_app(), "Premi\u00e8re", "\\u00e8re")


def test_french_accents_specialite():
    assert _has_accent(_read_app(), "Sp\u00e9cialit\u00e9", "\\u00e9cialit")


def test_french_accents_ingerer():
    assert _has_accent(_read_app(), "Ing\u00e9re", "\\u00e9rer", "\\u00e9rez")


def test_french_accents_declarees():
    assert _has_accent(_read_app(), "D\u00e9clar\u00e9e", "\\u00e9clar")


def test_french_accents_sante():
    assert _has_accent(_read_app(), "Sant\u00e9", "Sant\\u00e9")


# --- Metadata: rights selector ---

def test_has_rights_selector():
    content = _read_app()
    assert "nexus_owned" in content
    assert "rights" in content.lower()
