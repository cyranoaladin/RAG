"""Wikiversity API client — fetch course content via MediaWiki API.

Uses the TextExtracts API to get plain text summaries of Wikiversity pages.
License: CC-BY-SA 4.0 (all Wikiversity content).
No HTML scraping — uses the structured API only.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote


def wikiversity_search_url(query: str, limit: int = 5) -> str:
    """Build a Wikiversity API search URL."""
    q = quote(query)
    return (
        f"https://fr.wikiversity.org/w/api.php?"
        f"action=query&list=search&srsearch={q}&srlimit={limit}"
        f"&format=json&utf8=1"
    )


def wikiversity_extract_url(title: str) -> str:
    """Build a Wikiversity API extract URL for a page title."""
    t = quote(title)
    return (
        f"https://fr.wikiversity.org/w/api.php?"
        f"action=query&titles={t}&prop=extracts&exintro=0"
        f"&explaintext=1&format=json&utf8=1"
    )


def parse_search_results(data: dict[str, Any]) -> list[dict[str, str]]:
    """Parse search API response into title/snippet pairs."""
    results = []
    for item in data.get("query", {}).get("search", []):
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
            "pageid": str(item.get("pageid", "")),
        })
    return results


def parse_extract(data: dict[str, Any]) -> str:
    """Parse extract API response into plain text."""
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        return page.get("extract", "")
    return ""
