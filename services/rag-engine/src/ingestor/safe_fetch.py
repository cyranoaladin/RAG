"""Bounded HTTP fetches pinned to validated public IPs; no environment proxies."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from email.message import Message
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


class FetchError(ValueError):
    pass


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, ip, *, timeout):
        super().__init__(host, port, timeout=timeout)
        self._validated_ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._validated_ip, self.port), timeout=self.timeout)
        self._fetch_socket = self.sock


class PinnedHTTPSConnection(PinnedHTTPConnection):
    def __init__(self, host, port, ip, *, timeout, context=None):
        super().__init__(host, port, ip, timeout=timeout)
        self._context = context if context is not None else ssl.create_default_context()

    def connect(self):
        super().connect()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
        self._fetch_socket = self.sock


@dataclass(frozen=True)
class FetchedURL:
    url: str
    data: bytes
    headers: dict[str, str]

    @property
    def text(self):
        message = Message()
        message["content-type"] = self.headers.get("content-type", "")
        encoding = message.get_content_charset() or "utf-8"
        try:
            return self.data.decode(encoding, errors="replace")
        except LookupError:
            return self.data.decode("utf-8", errors="replace")


def resolve_public(url):
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise FetchError("Remote URL not allowed")
        host = parsed.hostname.encode("idna").decode("ascii")
        if any(c in host for c in "\r\n\x00"):
            raise FetchError("Remote URL not allowed")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(a[4][0] for a in answers))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise FetchError("Non-public remote address refused")
        return parsed, host, port, ips[0]
    except FetchError:
        raise
    except (ValueError, UnicodeError, OSError) as exc:
        raise FetchError("Remote URL resolution failed") from exc


def fetch_public_url(url, *, max_bytes, timeout=30, max_redirects=5):
    if max_bytes <= 0 or timeout <= 0:
        raise FetchError("Invalid fetch bounds")
    # The OS resolver retains its system timeout; all socket I/O is deadline-bound.
    deadline = time.monotonic() + timeout
    current = url

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise FetchError("Remote fetch timed out")
        return value

    for hop in range(max_redirects + 1):
        parsed, host, port, ip = resolve_public(current)
        cls = PinnedHTTPSConnection if parsed.scheme == "https" else PinnedHTTPConnection
        conn = cls(host, port, ip, timeout=remaining())
        response = None
        expired = threading.Event()

        def expire(conn=conn, expired=expired):
            expired.set()
            sock = getattr(conn, "_fetch_socket", None) or getattr(conn, "sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass

        watchdog = threading.Timer(remaining(), expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            path = urlunsplit(
                (
                    "",
                    "",
                    quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                    quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~"),
                    "",
                )
            )
            conn.request(
                "GET",
                path,
                headers={
                    "User-Agent": "rag-public-fetch/1.0",
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                },
            )
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or hop >= max_redirects:
                    raise FetchError("Remote redirect limit exceeded")
                current = urljoin(current, location)
                continue
            if response.status < 200 or response.status >= 300:
                raise FetchError("Remote HTTP request failed")
            declared = response.getheader("Content-Length")
            length = None
            if declared is not None:
                try:
                    length = int(declared)
                except ValueError:
                    raise FetchError("Invalid remote content length") from None
                if length < 0 or length > max_bytes:
                    raise FetchError("Remote response too large")
            chunks = []
            total = 0
            while True:
                if response.isclosed():
                    break
                sock = getattr(conn, "_fetch_socket", None)
                left = remaining()
                if sock is not None:
                    sock.settimeout(left)
                chunk = response.read1(min(65536, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError("Remote response too large")
                chunks.append(chunk)
            if expired.is_set():
                raise FetchError("Remote fetch timed out")
            if length is not None and total != length:
                raise FetchError("Incomplete remote response")
            return FetchedURL(
                current, b"".join(chunks), {k.lower(): v for k, v in response.getheaders()}
            )
        except FetchError:
            raise
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise FetchError("Remote fetch failed") from exc
        finally:
            watchdog.cancel()
            watchdog.join()
            if response is not None:
                getattr(response, "close", lambda: None)()
            conn.close()
    raise FetchError("Remote redirect limit exceeded")
