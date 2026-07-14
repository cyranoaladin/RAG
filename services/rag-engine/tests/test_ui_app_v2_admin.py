"""Static checks for the v2 collections UI."""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
APP_V2 = ENGINE_ROOT / "src" / "ui" / "app_v2.py"


def _literal_text(node: ast.expr) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
    return ""


def _rendered_text(content: str) -> list[str]:
    rendered: list[str] = []
    for node in ast.walk(ast.parse(content)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {
            "caption",
            "error",
            "info",
            "markdown",
            "metric",
            "selectbox",
            "subheader",
            "success",
            "title",
            "warning",
            "write",
        }:
            continue
        rendered.extend(_literal_text(arg) for arg in node.args)
    return rendered


def _assert_rendered_text(content: str, text: str) -> None:
    """Assert that a public label is passed to a Streamlit rendering method."""
    assert any(text in rendered for rendered in _rendered_text(content)), (
        f"{text!r} must be rendered by Streamlit"
    )


def _called_routes(content: str) -> set[str]:
    routes: set[str] = set()
    for node in ast.walk(ast.parse(content)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if isinstance(node.func, ast.Name) and node.func.id in {"api_get", "api_post"}:
            route = _literal_text(node.args[0])
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "httpx"
            and node.func.attr == "post"
        ):
            route = _literal_text(node.args[0])
        else:
            continue
        if route.startswith("/"):
            routes.add(route)
    return routes


def test_ui_uses_only_v2_collections_catalogue() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    assert 'api_get("/collections")' not in content
    assert 'api_get("/collections/v2")' in content


def test_administration_uses_v2_collections_label() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    assert "Collections ChromaDB" not in content
    _assert_rendered_text(content, "Catalogue v2 complet")


def test_dashboard_does_not_use_legacy_stats_for_v2_collections() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    assert 'api_get(f"/stats/{name}")' not in content


def test_ui_renders_lot27_p3_navigation_and_page_hierarchy() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    for label in (
        "API connectée",
        "Backend RAG v2",
        "Dashboard RAG v2",
        "Catalogue scolaire Nexus Réussite",
        "Déclarées",
        "Instanciées",
        "Non instanciées",
        "Recherche RAG v2",
        "Seules les collections instanciées et interrogeables (retrievable) sont proposées.",
        "Ingestion RAG v2",
        "Collection cible",
        "Type de document",
        "Droits",
        "needs_review",
        "Administration RAG v2",
        "Catalogue v2 complet",
        "Collections instanciées",
        "Collections déclarées non instanciées",
        "Collections retrievable",
        "Quarantaine",
        "Contrôles de cohérence",
    ):
        _assert_rendered_text(content, label)


def test_ui_exposes_only_supported_v2_presentation_routes() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    expected_routes = {
        "/health",
        "/catalogue/v2",
        "/collections/v2",
        "/search/v2",
        "/ingest/v2/upload-files",
        "/ingest/v2/urls",
    }
    assert _called_routes(content) == expected_routes


def test_ui_source_excludes_internal_address_and_legacy_collections() -> None:
    content = APP_V2.read_text(encoding="utf-8")

    forbidden = (
        "http://ingestor:8001",
        "Collections ChromaDB",
        "rag_francais_premiere",
        "rag_maths_premiere",
        "rag_education",
        "rag_web3",
        "rag_divers",
    )
    for value in forbidden:
        assert value not in content
