"""Static checks for the v2 collections UI."""

from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
APP_V2 = ENGINE_ROOT / "src" / "ui" / "app_v2.py"


def test_ui_uses_only_v2_collections_catalogue() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    assert 'api_get("/collections")' not in content
    assert 'api_get("/collections/v2")' in content


def test_administration_uses_v2_collections_label() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    assert "Collections ChromaDB" not in content
    assert "Collections RAG v2" in content


def test_dashboard_does_not_use_legacy_stats_for_v2_collections() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    assert 'api_get(f"/stats/{name}")' not in content
