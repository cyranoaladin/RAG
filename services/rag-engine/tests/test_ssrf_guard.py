"""LOT43 : garde SSRF unifiée pour tout fetch d'URL externe côté ingestion v2.

Couvre les scénarios exigés par le brief P1.4 : loopback, RFC1918, IPv6
link-local, endpoint metadata cloud, redirection publique->privée, DNS
rebinding, taille excessive, timeout, schéma interdit, credentials en URL,
redirections excessives. Tout est déterministe : la résolution DNS est
monkeypatchée et les réponses HTTP sont simulées via httpx.MockTransport
(aucun accès réseau réel).
"""

from __future__ import annotations

import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.ssrf_guard import (  # noqa: E402
    ResponseTooLargeError,
    SSRFValidationError,
    TooManyRedirectsError,
    safe_fetch,
    validate_destination,
)


def _fake_getaddrinfo(mapping: dict[str, list[str]]) -> Callable[..., Any]:
    def _fake(host: str, *args: Any, **kwargs: Any) -> list[tuple]:
        ips = mapping.get(host)
        if ips is None:
            raise socket.gaierror(f"no mapping for {host}")
        results = []
        for ip in ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            results.append((family, socket.SOCK_STREAM, 6, "", (ip, 0)))
        return results

    return _fake


# --- validate_destination : cas bloqués --------------------------------

def test_rejects_literal_loopback_ip() -> None:
    with pytest.raises(SSRFValidationError):
        validate_destination("http://127.0.0.1/secret")


def test_rejects_literal_rfc1918_ip() -> None:
    with pytest.raises(SSRFValidationError):
        validate_destination("http://10.0.0.5/internal")


def test_rejects_ipv6_link_local() -> None:
    with pytest.raises(SSRFValidationError):
        validate_destination("http://[fe80::1]/")


def test_rejects_cloud_metadata_endpoint() -> None:
    with pytest.raises(SSRFValidationError):
        validate_destination("http://169.254.169.254/latest/meta-data/")


def test_rejects_disallowed_scheme() -> None:
    with pytest.raises(SSRFValidationError):
        validate_destination("file:///etc/passwd")


def test_rejects_credentials_in_url() -> None:
    with pytest.raises(SSRFValidationError):
        validate_destination("http://user:pass@example.com/")


def test_rejects_domain_resolving_to_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"evil.example.com": ["10.1.2.3"]})
    )
    with pytest.raises(SSRFValidationError):
        validate_destination("http://evil.example.com/")


def test_rejects_domain_resolving_to_ipv6_unique_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"evil6.example.com": ["fd00::1"]})
    )
    with pytest.raises(SSRFValidationError):
        validate_destination("http://evil6.example.com/")


def test_rejects_domain_with_one_public_and_one_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un domaine avec au moins une IP privée doit être rejeté (pas de round-robin bypass)."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo({"mixed.example.com": ["93.184.216.34", "127.0.0.1"]}),
    )
    with pytest.raises(SSRFValidationError):
        validate_destination("http://mixed.example.com/")


# --- validate_destination : cas autorisés -------------------------------

def test_allows_public_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"education.gouv.fr": ["93.184.216.34"]})
    )
    validate_destination("http://education.gouv.fr/programme")


# --- safe_fetch : redirections ------------------------------------------

def test_follows_redirect_to_validated_public_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo({"a.example.com": ["93.184.216.34"], "b.example.com": ["93.184.216.35"]}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a.example.com":
            return httpx.Response(302, headers={"Location": "http://b.example.com/final"})
        return httpx.Response(200, text="hello world")

    transport = httpx.MockTransport(handler)
    resp = safe_fetch("http://a.example.com/start", max_bytes=1_000_000, transport=transport)
    assert resp.text == "hello world"


def test_rejects_redirect_to_private_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"a.example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(SSRFValidationError):
        safe_fetch("http://a.example.com/start", max_bytes=1_000_000, transport=transport)


def test_rejects_dns_rebinding_between_validation_and_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le nom résout public au moment de valider puis privé au moment du transport."""
    calls = {"n": 0}

    def _rebinding(host: str, *args: Any, **kwargs: Any) -> list[tuple]:
        calls["n"] += 1
        ip = "93.184.216.34" if calls["n"] == 1 else "10.0.0.9"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _rebinding)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="should not be reached")

    transport = httpx.MockTransport(handler)
    with pytest.raises(SSRFValidationError):
        safe_fetch("http://rebind.example.com/", max_bytes=1_000_000, transport=transport)


def test_rejects_excessive_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"loop.example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://loop.example.com/next"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(TooManyRedirectsError):
        safe_fetch("http://loop.example.com/start", max_bytes=1_000_000, max_redirects=3, transport=transport)


# --- safe_fetch : taille et timeout --------------------------------------

def test_rejects_response_exceeding_max_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"big.example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2_000_000)

    transport = httpx.MockTransport(handler)
    with pytest.raises(ResponseTooLargeError):
        safe_fetch("http://big.example.com/", max_bytes=1_000_000, transport=transport)


def test_propagates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"slow.example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    transport = httpx.MockTransport(handler)
    with pytest.raises(httpx.ReadTimeout):
        safe_fetch("http://slow.example.com/", max_bytes=1_000_000, transport=transport)
