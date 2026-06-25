"""Tests for the governed fetch module — all network mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from scrapers.fetch import (
    FetchRefusal,
    FetchResult,
    extract_text_from_html,
    governed_fetch,
    is_whitelisted,
    quality_check,
)

# --- Whitelist ---

def test_whitelisted_domain():
    assert is_whitelisted("https://eduscol.education.gouv.fr/path")
    assert is_whitelisted("https://education.gouv.fr/programmes")


def test_non_whitelisted_domain():
    assert not is_whitelisted("https://example.com/page")
    assert not is_whitelisted("https://wikipedia.org/suites")


def test_fetch_refuses_non_whitelisted():
    result = governed_fetch("https://example.com/page")
    assert isinstance(result, FetchRefusal)
    assert "not whitelisted" in result.reason


# --- robots.txt ---

@patch("scrapers.fetch._get_robots")
def test_robots_refusal(mock_robots):
    rp = MagicMock()
    rp.can_fetch.return_value = False
    mock_robots.return_value = rp

    result = governed_fetch("https://eduscol.education.gouv.fr/restricted")
    assert isinstance(result, FetchRefusal)
    assert "robots.txt" in result.reason


@patch("scrapers.fetch._get_robots")
@patch("requests.get")
@patch("scrapers.fetch._apply_rate_limit", return_value=0.0)
def test_robots_allowed_proceeds_to_fetch(mock_rate, mock_get, mock_robots):
    rp = MagicMock()
    rp.can_fetch.return_value = True
    mock_robots.return_value = rp

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"<html>Contenu</html>"]
    mock_get.return_value = mock_response

    result = governed_fetch("https://eduscol.education.gouv.fr/page")
    assert isinstance(result, FetchResult)
    assert result.status_code == 200


# --- Rate limit ---

@patch("scrapers.fetch._get_robots")
@patch("requests.get")
def test_rate_limit_applied(mock_get, mock_robots):
    rp = MagicMock()
    rp.can_fetch.return_value = True
    mock_robots.return_value = rp

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"<html>ok</html>"]
    mock_get.return_value = mock_response

    r1 = governed_fetch("https://eduscol.education.gouv.fr/page1")
    assert isinstance(r1, FetchResult)


# --- Read-only ---

@patch("scrapers.fetch._get_robots")
@patch("requests.get")
@patch("scrapers.fetch._apply_rate_limit", return_value=0.0)
def test_only_get_requests(mock_rate, mock_get, mock_robots):
    """Verify that only GET is called, never POST/PUT/DELETE."""
    rp = MagicMock()
    rp.can_fetch.return_value = True
    mock_robots.return_value = rp

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "text/html"}
    mock_response.iter_content.return_value = [b"content"]
    mock_get.return_value = mock_response

    governed_fetch("https://eduscol.education.gouv.fr/page")

    mock_get.assert_called_once()


# --- Text extraction ---

def test_extract_text_from_html():
    html = "<html><head><script>var x=1;</script></head><body><h1>Title</h1><p>Content here.</p></body></html>"
    text = extract_text_from_html(html)
    assert "Title" in text
    assert "Content here" in text
    assert "<script>" not in text
    assert "<h1>" not in text


# --- Quality check ---

def test_quality_check_pass():
    text = "Les suites numériques sont un concept fondamental en mathématiques. " * 10
    qc = quality_check(text, "suites")
    assert qc["ok"]


def test_quality_check_too_short():
    qc = quality_check("court", "suites")
    assert not qc["ok"]
    assert any("too short" in i for i in qc["issues"])


# --- robots.txt failure → refusal (conservative) ---

@patch("scrapers.fetch._get_robots")
def test_robots_failure_refuses(mock_robots):
    """If robots.txt can't be fetched, refuse by default (conservative)."""
    rp = MagicMock()
    rp.can_fetch.return_value = False  # conservative default
    mock_robots.return_value = rp

    result = governed_fetch("https://eduscol.education.gouv.fr/page")
    assert isinstance(result, FetchRefusal)
