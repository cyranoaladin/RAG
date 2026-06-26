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
    """Extract the main article content from HTML (MediaWiki-aware).

    For Wikipedia/Wikiversity pages, extracts only the article body
    (mw-parser-output / mw-content-text), stripping navigation, menus,
    infoboxes, references, see-also, and external links.
    Falls back to generic extraction for non-MediaWiki pages.
    """
    # Try MediaWiki-specific extraction first
    content = _extract_mediawiki_body(html)
    if content and len(content) > 100:
        return content

    # Fallback: generic extraction
    text = re.sub(
        r"<(script|style|nav|header|footer)[^>]*>.*?</\1>",
        "", html, flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_mediawiki_body(html: str) -> str:
    """Extract article body from a MediaWiki page."""
    # Find the main content container
    # MediaWiki uses <div id="mw-content-text"> or <div class="mw-parser-output">
    body = ""
    for pattern in [
        r'<div[^>]*class="mw-parser-output"[^>]*>(.*)',
        r'<div[^>]*id="mw-content-text"[^>]*>(.*)',
    ]:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            body = m.group(1)
            break

    if not body:
        return ""

    # Remove unwanted sections by their container patterns
    # Table of contents
    body = re.sub(r'<div[^>]*id="toc"[^>]*>.*?</div>\s*</div>', "", body, flags=re.DOTALL)
    # Infoboxes
    body = re.sub(r'<table[^>]*class="[^"]*infobox[^"]*"[^>]*>.*?</table>', "", body, flags=re.DOTALL)
    # Navigation boxes
    body = re.sub(r'<div[^>]*class="[^"]*navbox[^"]*"[^>]*>.*?</div>\s*</div>', "", body, flags=re.DOTALL)
    body = re.sub(r'<div[^>]*class="[^"]*navbox[^"]*"[^>]*>.*?</div>', "", body, flags=re.DOTALL)
    body = re.sub(r'<table[^>]*class="[^"]*navbox[^"]*"[^>]*>.*?</table>', "", body, flags=re.DOTALL)
    # Disambiguation banners
    body = re.sub(r'<div[^>]*class="[^"]*homonymie[^"]*"[^>]*>.*?</div>', "", body, flags=re.DOTALL)
    body = re.sub(r'<div[^>]*class="[^"]*bandeau[^"]*"[^>]*>.*?</div>', "", body, flags=re.DOTALL)
    # References section
    body = re.sub(r'<div[^>]*class="[^"]*references[^"]*"[^>]*>.*?</div>', "", body, flags=re.DOTALL)
    body = re.sub(r'<ol[^>]*class="references"[^>]*>.*?</ol>', "", body, flags=re.DOTALL)

    # Remove specific sections: Notes, Références, Voir aussi, Liens externes
    for section_title in ["Notes et références", "Voir aussi", "Liens externes",
                          "Bibliographie", "Articles connexes", "Notes"]:
        # Remove from <h2>Section</h2> to next <h2> or end
        pattern = (
            rf'<h2[^>]*>\s*<span[^>]*>\s*{re.escape(section_title)}\s*</span>.*?'
            r'(?=<h2|$)'
        )
        body = re.sub(pattern, "", body, flags=re.DOTALL | re.IGNORECASE)

    # Remove script/style tags
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.DOTALL | re.IGNORECASE)
    # Remove sup tags (footnote markers [1], [2])
    body = re.sub(r"<sup[^>]*>.*?</sup>", "", body, flags=re.DOTALL)

    # Strip all remaining tags
    text = re.sub(r"<[^>]+>", " ", body)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


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

    # Anti-navigation check (calibrated on real Wikiversity/Wikipedia pages)
    nav_markers = {"chapitres", "voir aussi", "catégorie :", "modifier les liens",
                   "outils personnels", "menu principal", "aller au contenu",
                   "rechercher", "faire un don", "créer un compte", "se connecter",
                   "autres leçons", "département"}
    lower_text = text.lower()
    nav_hits = sum(1 for m in nav_markers if m in lower_text)
    # Short pages with many nav markers are likely indexes. Long articles often
    # retain a few footer labels after extraction; those are not blocking.
    words_count = len(text.split())
    navigation_suspected = nav_hits >= 3 and words_count < 500

    if navigation_suspected:
        issues.append(f"navigation_suspected ({nav_hits} nav markers found)")

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "text_length": len(text),
        "fr_ratio": round(fr_ratio, 3),
        "navigation_suspected": navigation_suspected,
    }
