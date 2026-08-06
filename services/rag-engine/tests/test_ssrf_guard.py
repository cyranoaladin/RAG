"""LOT43 : garde SSRF unifiée pour tout fetch d'URL externe côté ingestion v2.

Couvre les scénarios exigés par le brief P1.4 : loopback, RFC1918, IPv6
link-local, endpoint metadata cloud, redirection publique->privée, DNS
rebinding, taille excessive, timeout, schéma interdit, credentials en URL,
redirections excessives. Tout est déterministe : la résolution DNS est
monkeypatchée et les réponses HTTP sont simulées via httpx.MockTransport
(aucun accès réseau réel).

Réconciliation LOT44f : ajoute la couverture du bug de double décompression
(``iter_bytes()`` décode déjà gzip/deflate, mais le ``Response`` reconstruit
gardait l'en-tête ``Content-Encoding`` d'origine, provoquant une seconde
tentative de décompression sur des octets déjà en clair — cf. le correctif
dans ``safe_fetch``).
"""

from __future__ import annotations

import gzip
import socket
import sys
import zlib
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


def test_rejects_rfc6598_shared_address_space() -> None:
    """Revue PR#90 (Cubic P1) : 100.64.0.0/10 (RFC 6598, adressage partagé
    opérateur/CGNAT) n'est pas couvert par ``ip.is_private`` dans
    ``ipaddress`` — vérifie explicitement qu'il reste bloqué malgré
    cette lacune de la bibliothèque standard."""
    with pytest.raises(SSRFValidationError):
        validate_destination("http://100.64.0.1/")


def test_still_rejects_multicast_despite_is_global_quirk() -> None:
    """``ipaddress.IPv4Address('224.0.0.1').is_global`` vaut ``True``
    (propriété distincte de la routabilité unicast) — non-régression : le
    correctif RFC 6598 (``not ip.is_global``) ne doit jamais remplacer la
    vérification ``is_multicast`` explicite, seulement s'y ajouter."""
    with pytest.raises(SSRFValidationError):
        validate_destination("http://224.0.0.1/")


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


# --- safe_fetch : réponses compressées (LOT44f, régression du bug de
# double décompression) ---------------------------------------------------

def test_decodes_gzip_response_without_double_decompression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"gzip.example.com": ["93.184.216.34"]})
    )
    plain = b"hello world " * 100

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=gzip.compress(plain)
        )

    transport = httpx.MockTransport(handler)
    resp = safe_fetch("http://gzip.example.com/", max_bytes=1_000_000, transport=transport)
    assert resp.content == plain
    # La réponse reconstruite ne doit plus prétendre être encodée : sinon un
    # second appel à .content/.text par l'appelant redéclencherait le bug.
    assert "content-encoding" not in resp.headers
    assert resp.text == plain.decode("ascii")


def test_decodes_deflate_response_without_double_decompression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"deflate.example.com": ["93.184.216.34"]})
    )
    plain = b"hello world " * 100

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "deflate"}, content=zlib.compress(plain)
        )

    transport = httpx.MockTransport(handler)
    resp = safe_fetch("http://deflate.example.com/", max_bytes=1_000_000, transport=transport)
    assert resp.content == plain
    assert "content-encoding" not in resp.headers


def test_reconstructed_response_content_length_matches_decoded_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le Content-Length d'origine (taille compressée) ne doit pas survivre :
    il doit être recalculé sur le corps décodé, sinon un appelant qui s'y fie
    lirait une taille incohérente avec le corps réel."""
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"gzip2.example.com": ["93.184.216.34"]})
    )
    plain = b"x" * 10_000
    compressed = gzip.compress(plain)
    assert len(compressed) < len(plain)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-encoding": "gzip",
                "content-length": str(len(compressed)),
            },
            content=compressed,
        )

    transport = httpx.MockTransport(handler)
    resp = safe_fetch("http://gzip2.example.com/", max_bytes=1_000_000, transport=transport)
    assert resp.content == plain
    assert resp.headers.get("content-length") == str(len(plain))


def test_rejects_malformed_compressed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un Content-Encoding: gzip avec un corps qui n'est pas du gzip valide
    doit échouer bruyamment (fail-closed), jamais retourner des octets
    corrompus silencieusement."""
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"malformed.example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=b"not actually gzip data"
        )

    transport = httpx.MockTransport(handler)
    with pytest.raises(httpx.DecodingError):
        safe_fetch("http://malformed.example.com/", max_bytes=1_000_000, transport=transport)


def test_rejects_decompression_bomb_within_max_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un corps compressé petit mais qui se décompresse en un corps énorme
    doit être coupé par ``max_bytes`` sur la taille décodée, pas la taille
    compressée sur le fil (protection contre les bombes de décompression)."""
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"bomb.example.com": ["93.184.216.34"]})
    )
    bomb_plain = b"0" * 5_000_000
    bomb_compressed = gzip.compress(bomb_plain)
    assert len(bomb_compressed) < 100_000, "le corps compressé doit rester petit sur le fil"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=bomb_compressed)

    transport = httpx.MockTransport(handler)
    with pytest.raises(ResponseTooLargeError):
        safe_fetch("http://bomb.example.com/", max_bytes=1_000_000, transport=transport)


def test_decodes_gzip_response_across_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    """La revalidation SSRF sur redirection ne doit pas être perturbée par un
    corps compressé sur le saut final."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _fake_getaddrinfo(
            {"a-gz.example.com": ["93.184.216.34"], "b-gz.example.com": ["93.184.216.35"]}
        ),
    )
    plain = b"redirected and compressed"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a-gz.example.com":
            return httpx.Response(302, headers={"Location": "http://b-gz.example.com/final"})
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=gzip.compress(plain)
        )

    transport = httpx.MockTransport(handler)
    resp = safe_fetch("http://a-gz.example.com/start", max_bytes=1_000_000, transport=transport)
    assert resp.content == plain


def test_passes_through_uncompressed_response_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Régression : une réponse sans Content-Encoding ne doit pas être
    affectée par le correctif (pas de suppression de en-têtes légitimes)."""
    monkeypatch.setattr(
        socket, "getaddrinfo", _fake_getaddrinfo({"plain.example.com": ["93.184.216.34"]})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/plain; charset=utf-8"}, content=b"plain body"
        )

    transport = httpx.MockTransport(handler)
    resp = safe_fetch("http://plain.example.com/", max_bytes=1_000_000, transport=transport)
    assert resp.content == b"plain body"
    assert resp.headers.get("content-type") == "text/plain; charset=utf-8"
