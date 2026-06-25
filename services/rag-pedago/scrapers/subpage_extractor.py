"""Extract sub-page links from Wikiversity lesson index pages.

Wikiversity lesson pages list chapters as internal links (/wiki/Titre/Chapitre_N).
This module extracts those links for governed fetching of actual course content.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urljoin


def extract_subpage_links(html: str, base_url: str) -> list[str]:
    """Extract internal wiki sub-page links from HTML.

    Looks for links matching /wiki/ParentTitle/SubPage patterns.
    Filters out navigation, talk pages, special pages, etc.
    """
    # Extract the parent path from the base URL
    parent_match = re.search(r"/wiki/([^?#]+)", base_url)
    if not parent_match:
        return []
    parent_path = unquote(parent_match.group(1))

    # Find all internal wiki links
    links = re.findall(r'href="(/wiki/[^"]+)"', html)

    subpages: list[str] = []
    seen: set[str] = set()

    for link in links:
        decoded = unquote(link)
        # Must be a sub-page of the parent
        if not decoded.startswith(f"/wiki/{parent_path}/"):
            continue
        # Skip special/talk/edit pages
        if any(x in decoded for x in ["action=", "Special:", "Discussion:", "Utilisateur:", "?", "#"]):
            continue
        # Build full URL
        full_url = urljoin(base_url, link)
        if full_url not in seen:
            seen.add(full_url)
            subpages.append(full_url)

    return subpages
