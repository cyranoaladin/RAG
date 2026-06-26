"""Governed fetch module — GET-only, whitelist, robots.txt, rate limit.

Implements ADR-0004 scoped network access for pilot source acquisition.
No POST/PUT/DELETE. No JS execution. No authentication bypass.
"""
from __future__ import annotations

import html as html_module
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Whitelist — only these domains are permitted
# ---------------------------------------------------------------------------

WHITELISTED_DOMAINS: frozenset[str] = frozenset({
    "eduscol.education.gouv.fr",
    "education.gouv.fr",
    "www.education.gouv.fr",
    "cache.media.eduscol.education.gouv.fr",
    "cache.media.education.gouv.fr",
    "fr.wikiversity.org",  # CC-BY-SA 4.0
    "fr.wikipedia.org",  # CC-BY-SA 4.0
})

USER_AGENT = "NexusReussiteBot/0.1 (+https://nexusreussite.academy; pedagogical-rag)"
RATE_LIMIT_SECONDS = 2.0
REQUEST_TIMEOUT = 30
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Whitelist check
# ---------------------------------------------------------------------------

def is_whitelisted(url: str) -> bool:
    """Check if URL domain is in the whitelist."""
    parsed = urlparse(url)
    return parsed.netloc in WHITELISTED_DOMAINS


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

_robots_cache: dict[str, object] = {}


def _get_robots(url: str) -> object:
    """Fetch and cache robots.txt for the domain, using our identified UA."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    if robots_url not in _robots_cache:
        from urllib.robotparser import RobotFileParser
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            # Fetch robots.txt with our identified UA (some sites block default urllib UA)
            import requests as _req
            resp = _req.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=10)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.disallow_all = True  # type: ignore[attr-defined]
        except Exception:
            rp.disallow_all = True  # type: ignore[attr-defined]  # conservative: refuse if unavailable
        _robots_cache[robots_url] = rp
    return _robots_cache[robots_url]


def is_allowed_by_robots(url: str) -> bool:
    """Check if robots.txt allows fetching this URL."""
    rp = _get_robots(url)
    return rp.can_fetch(USER_AGENT, url)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

_last_fetch_time: dict[str, float] = {}


def _apply_rate_limit(domain: str) -> float:
    """Wait if needed to respect rate limit. Returns delay applied."""
    now = time.monotonic()
    last = _last_fetch_time.get(domain, 0.0)
    elapsed = now - last
    delay = 0.0
    if elapsed < RATE_LIMIT_SECONDS:
        delay = RATE_LIMIT_SECONDS - elapsed
        time.sleep(delay)
    _last_fetch_time[domain] = time.monotonic()
    return delay


# ---------------------------------------------------------------------------
# Fetch result
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    url: str
    status_code: int
    content_type: str
    text: str
    fetched_at: datetime
    delay_applied: float = 0.0
    error: str | None = None


@dataclass
class FetchRefusal:
    url: str
    reason: str


# ---------------------------------------------------------------------------
# Core fetch function
# ---------------------------------------------------------------------------

def governed_fetch(url: str) -> FetchResult | FetchRefusal:
    """Fetch a URL with all governance checks.

    Returns FetchResult on success, FetchRefusal if blocked.
    Only GET requests are issued. Never POST/PUT/DELETE.
    """
    # 1. Whitelist check
    if not is_whitelisted(url):
        return FetchRefusal(url=url, reason=f"domain not whitelisted: {urlparse(url).netloc}")

    # 2. robots.txt check
    if not is_allowed_by_robots(url):
        return FetchRefusal(url=url, reason="blocked by robots.txt")

    # 3. Rate limit
    domain = urlparse(url).netloc
    delay = _apply_rate_limit(domain)

    # 4. GET request (read-only) — lazy import to avoid polluting sys.modules
    import requests

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        # Enforce max size
        content = b""
        for chunk in response.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > MAX_RESPONSE_BYTES:
                return FetchResult(
                    url=url,
                    status_code=response.status_code,
                    content_type=response.headers.get("Content-Type", ""),
                    text="",
                    fetched_at=datetime.now(UTC),
                    delay_applied=delay,
                    error=f"response exceeds {MAX_RESPONSE_BYTES} bytes",
                )

        text = content.decode("utf-8", errors="replace")
        return FetchResult(
            url=url,
            status_code=response.status_code,
            content_type=response.headers.get("Content-Type", ""),
            text=text,
            fetched_at=datetime.now(UTC),
            delay_applied=delay,
        )
    except requests.RequestException as e:
        return FetchResult(
            url=url,
            status_code=0,
            content_type="",
            text="",
            fetched_at=datetime.now(UTC),
            delay_applied=delay,
            error=str(e),
        )


# ---------------------------------------------------------------------------
# HTML text extraction (basic)
# ---------------------------------------------------------------------------

def extract_text_from_html(html: str) -> str:
    """Extract the main article content from HTML using BeautifulSoup.

    For MediaWiki pages: extracts only #mw-content-text / .mw-parser-output,
    removes navigation, infoboxes, references, terminal sections, and footer chrome.
    Falls back to generic body extraction for non-MediaWiki pages.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Try MediaWiki content container
    content = soup.find("div", class_="mw-parser-output")
    if not content:
        content = soup.find("div", id="mw-content-text")
    if not content:
        # Fallback: use body
        content = soup.find("body") or soup

    # Remove unwanted elements BEFORE extracting text
    _REMOVE_TAGS = ["script", "style", "nav", "header", "footer", "sup"]
    for tag_name in _REMOVE_TAGS:
        for tag in content.find_all(tag_name):
            tag.decompose()

    _REMOVE_CLASSES = [
        "navbox", "infobox", "metadata", "reference", "references",
        "mw-editsection", "hatnote", "bandeau-container", "bandeau",
        "homonymie", "catlinks", "printfooter", "mw-authority-control",
        "sister-project", "sistersitebox", "side-box", "navbox-wikimedia",
        "mw-references-wrap", "reflist", "refbegin",
    ]
    for cls_name in _REMOVE_CLASSES:
        for tag in content.find_all(class_=lambda c, cn=cls_name: c and cn in c):
            tag.decompose()

    _REMOVE_IDS = ["toc", "catlinks", "mw-navigation"]
    for id_val in _REMOVE_IDS:
        tag = content.find(id=id_val)  # type: ignore[assignment]
        if tag:
            tag.decompose()

    # Remove terminal sections: Notes et références, Voir aussi, etc.
    # Handle both h2 and h3 headings.
    # Use find_all_next() to catch content in nested containers, not just direct siblings.
    _TERMINAL_SECTIONS = {
        "notes et références", "voir aussi", "liens externes",
        "bibliographie", "articles connexes", "notes", "annexes",
        "sur les autres projets", "références",
    }
    for heading in content.find_all(["h2", "h3"]):
        heading_text = heading.get_text(strip=True).lower()
        if any(section in heading_text for section in _TERMINAL_SECTIONS):
            same_level = heading.name
            # Remove ALL following elements until next heading of same level
            for following in list(heading.find_all_next()):
                if following.name == same_level and following != heading:
                    break
                # Only decompose if it's still in the document (not already removed)
                if following.parent is not None:
                    try:
                        following.decompose()
                    except Exception:
                        pass
            if heading.parent is not None:
                heading.decompose()

    # Remove footer/sister-project containers by text content
    for el in content.find_all(["div", "table", "ul"]):
        text_start = el.get_text(strip=True)[:80].lower()
        if any(text_start.startswith(p) for p in [
            "portail :", "catégorie :", "récupérée de", "sur les autres projets",
            "ce document provient", "dernière modification",
        ]):
            el.decompose()

    # Extract text
    text = content.get_text(separator=" ", strip=True)
    text = html_module.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()

    # Post-extraction safety net: truncate at first residual tail marker
    _FOOTER_MARKERS = [
        "Voir aussi", "Articles connexes", "Sur les autres projets",
        "Notes et références", "Bibliographie", "Liens externes",
        "Notices d'autorité", "Récupérée de", "Références",
        "Ce document provient de", "Dernière modification",
    ]
    for marker in _FOOTER_MARKERS:
        idx = text.find(marker)
        if idx > len(text) // 2:
            text = text[:idx].rstrip()

    # Bibliographic residue safety net: truncate at dense ISBN/reference patterns
    # in the last quarter of text
    _BIBLIO_PATTERNS = ["ISBN", "(en)", "lire en ligne", "coll.", "éd.)"]
    last_quarter_start = len(text) * 3 // 4
    for pattern in _BIBLIO_PATTERNS:
        idx = text.find(pattern, last_quarter_start)
        if idx > 0:
            # Find the start of the line/sentence containing the pattern
            line_start = text.rfind(". ", 0, idx)
            if line_start > last_quarter_start:
                text = text[:line_start + 1].rstrip()
                break

    return text


# ---------------------------------------------------------------------------
# Quality check
# ---------------------------------------------------------------------------

MIN_TEXT_LENGTH = 200

def quality_check(text: str, notion_id: str) -> dict[str, Any]:
    """Basic quality check: language, length, relevance."""
    issues: list[str] = []
    if len(text) < MIN_TEXT_LENGTH:
        issues.append(f"text too short ({len(text)} chars, min {MIN_TEXT_LENGTH})")

    # Check for French content (simple heuristic)
    fr_markers = {"le", "la", "les", "de", "des", "du", "en", "un", "une", "est", "sont"}
    words = set(text.lower().split()[:100])
    fr_ratio = len(words.intersection(fr_markers)) / max(len(words), 1)
    if fr_ratio < 0.05:
        issues.append(f"low French content ratio ({fr_ratio:.2%})")

    # Anti-navigation / chrome residue check (length-independent)
    # After BeautifulSoup extraction, residual chrome indicates extraction failure
    chrome_markers = {"aller au contenu", "modifier le code", "outils personnels",
                      "menu principal", "faire un don", "créer un compte",
                      "se connecter", "modifier les liens", "récupérée de",
                      "portail :", "catégorie :", "autres leçons", "département",
                      "sur les autres projets", "articles connexes",
                      "wiktionnaire", "sur wikiversity", "notices d'autorité",
                      "lire en ligne"}
    lower_text = text.lower()
    chrome_hits = sum(1 for m in chrome_markers if m in lower_text)
    # Any chrome marker = suspected (post-extraction, these should be absent)
    navigation_suspected = chrome_hits >= 2

    if navigation_suspected:
        issues.append(f"navigation_suspected ({chrome_hits} chrome markers found)")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "text_length": len(text),
        "fr_ratio": round(fr_ratio, 3),
        "navigation_suspected": navigation_suspected,
    }
