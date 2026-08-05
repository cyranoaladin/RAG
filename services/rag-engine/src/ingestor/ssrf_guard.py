"""Garde SSRF unifiée pour tout fetch d'URL externe côté ingestion v2 (LOT43).

Point d'entrée unique à utiliser partout où une URL fournie par un client ou
un agent est résolue/téléchargée : `validate_destination` (contrôle seul,
sans réseau) et `safe_fetch` (contrôle + téléchargement borné, redirections
revalidées à chaque saut).

Ne jamais contourner ce module avec un `httpx.get`/`requests.get` direct sur
une URL externe non fiable.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

ALLOWED_SCHEMES = {"http", "https"}

DEFAULT_MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
_STREAM_CHUNK_SIZE = 64 * 1024


class SSRFValidationError(ValueError):
    """L'URL ou une destination résolue/redirigée est interdite."""


class TooManyRedirectsError(SSRFValidationError):
    """Le nombre de redirections autorisées a été dépassé."""


class ResponseTooLargeError(SSRFValidationError):
    """La réponse dépasse la taille maximale autorisée."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _resolve_all_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(hostname.strip("[]"))
        return [literal]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise SSRFValidationError(f"DNS resolution failed for {hostname}: {exc}") from exc

    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for _family, _type, _proto, _canonname, sockaddr in infos:
        raw_ip = sockaddr[0]
        try:
            ips.append(ipaddress.ip_address(raw_ip))
        except ValueError:
            continue
    if not ips:
        raise SSRFValidationError(f"DNS resolution returned no usable address for {hostname}")
    return ips


def validate_destination(url: str) -> str:
    """Valide un schéma, l'absence de credentials, et toutes les IP résolues.

    Retourne l'URL inchangée si elle est autorisée ; lève SSRFValidationError sinon.
    Une nouvelle résolution DNS est effectuée à chaque appel (jamais de cache
    partagé entre la validation et le fetch, pour limiter le DNS rebinding).
    """
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SSRFValidationError(f"Unsupported scheme: {parsed.scheme!r}")

    if parsed.username or parsed.password:
        raise SSRFValidationError("Credentials embedded in URL are not allowed")

    hostname = parsed.hostname or ""
    if not hostname:
        raise SSRFValidationError(f"Invalid URL, no hostname: {url}")

    if parsed.port is not None and parsed.port not in (80, 443):
        raise SSRFValidationError(f"Port not allowed: {parsed.port}")

    for ip in _resolve_all_ips(hostname):
        if _is_blocked_ip(ip):
            raise SSRFValidationError(f"Blocked destination IP {ip} for host {hostname}")

    return url


class _RevalidatingTransport(httpx.BaseTransport):
    """Revalide la destination juste avant chaque dispatch réseau.

    Se place au plus près possible de la connexion réelle : une résolution
    DNS fraîche est effectuée ici, séparée de celle faite en amont pour
    choisir la prochaine URL à suivre. Cela réduit la fenêtre de TOCTOU
    exploitable par un DNS rebinding (TTL=0) sans nécessiter d'épinglage bas
    niveau de la connexion TCP/TLS à une IP précise (non supporté proprement
    par httpx pour HTTPS sans complexifier significativement la vérification
    du certificat). Limite connue et assumée : une fenêtre résiduelle,
    infime, subsiste entre cette revalidation et la résolution DNS propre au
    transport réseau sous-jacent.
    """

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        validate_destination(str(request.url))
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def safe_fetch(
    url: str,
    *,
    max_bytes: int,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    transport: httpx.BaseTransport | None = None,
) -> httpx.Response:
    """Télécharge une URL en revalidant la destination à chaque redirection.

    - Suit les redirections manuellement (follow_redirects=False côté httpx).
    - Revalide la destination (DNS + IP) avant de choisir chaque saut, ET une
      seconde fois juste avant le dispatch réseau (cf. _RevalidatingTransport),
      pour empêcher le DNS rebinding et les rebonds vers des réseaux internes.
    - Limite le nombre de sauts à `max_redirects`.
    - Coupe le téléchargement en streaming dès que `max_bytes` est dépassé.
    """
    current_url = url
    inner_transport = transport if transport is not None else httpx.HTTPTransport()
    client_kwargs: dict[str, Any] = {
        "follow_redirects": False,
        "timeout": timeout,
        "transport": _RevalidatingTransport(inner_transport),
    }

    with httpx.Client(**client_kwargs) as client:
        for _hop in range(max_redirects + 1):
            validate_destination(current_url)

            with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise SSRFValidationError("Redirect response without Location header")
                    current_url = urljoin(current_url, location)
                    continue

                body = bytearray()
                for chunk in response.iter_bytes(_STREAM_CHUNK_SIZE):
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ResponseTooLargeError(
                            f"Response exceeds {max_bytes} bytes from {current_url}"
                        )
                # `iter_bytes()` already decoded any Content-Encoding (gzip/deflate/
                # br/zstd). The original response headers still advertise that
                # encoding, so carrying them over verbatim onto a Response built
                # from `content=` (already-decoded bytes) makes a later `.read()`/
                # `.text` re-run decompression on plain bytes and raise
                # `zlib.error: incorrect header check`. Drop the now-stale
                # transfer/encoding headers and let httpx recompute an accurate
                # Content-Length for the decoded body.
                response_headers = httpx.Headers(response.headers)
                for stale_header in ("content-encoding", "content-length", "transfer-encoding"):
                    if stale_header in response_headers:
                        del response_headers[stale_header]
                return httpx.Response(
                    response.status_code,
                    headers=response_headers,
                    content=bytes(body),
                    request=response.request,
                )

        raise TooManyRedirectsError(f"Exceeded {max_redirects} redirects starting from {url}")
