"""Governed fetch module — GET-only, whitelist, robots.txt, rate limit.

Implements ADR-0004 scoped network access for pilot source acquisition.
No POST/PUT/DELETE. No JS execution. No authentication bypass.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

# ---------------------------------------------------------------------------
# Whitelist — only these domains are permitted
# ---------------------------------------------------------------------------

WHITELISTED_DOMAINS: frozenset[str] = frozenset({
    "eduscol.education.gouv.fr",
    "education.gouv.fr",
    "www.education.gouv.fr",
    "cache.media.eduscol.education.gouv.fr",
    "cache.media.education.gouv.fr",
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

_robots_cache: dict[str, RobotFileParser] = {}


def _get_robots(url: str) -> RobotFileParser:
    """Fetch and cache robots.txt for the domain."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    if robots_url not in _robots_cache:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception:
            # If robots.txt can't be fetched, assume everything is allowed
            rp.allow_all = True  # type: ignore[attr-defined]
        _robots_cache[robots_url] = rp
    return _robots_cache[robots_url]


def is_allowed_by_robots(url: str) -> bool:
    """Check if robots.txt allows fetching this URL."""
    rp = _get_robots(url)
    return rp.can_fetch(USER_AGENT, url)


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

    # 4. GET request (read-only)
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
    """Extract readable text from HTML. Basic — no JS rendering."""
    # Remove script/style tags
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
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

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "text_length": len(text),
        "fr_ratio": round(fr_ratio, 3),
    }
