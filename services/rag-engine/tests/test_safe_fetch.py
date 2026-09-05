import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/ingestor"))


def module():
    return importlib.import_module("safe_fetch")


def dns(ips):
    return lambda *a, **kw: [(2, 1, 6, "", (ip, 443)) for ip in ips]


def test_mixed_dns_private_answer_refused(monkeypatch):
    m = module()
    monkeypatch.setattr(m.socket, "getaddrinfo", dns(["93.184.216.34", "127.0.0.1"]))
    with pytest.raises(m.FetchError):
        m.resolve_public("https://docs.example/file")


def test_private_ipv6_refused(monkeypatch):
    m = module()
    monkeypatch.setattr(m.socket, "getaddrinfo", dns(["::1"]))
    with pytest.raises(m.FetchError):
        m.resolve_public("https://docs.example/file")


def test_connection_uses_validated_ip_and_original_tls_name(monkeypatch):
    m = module()
    calls = []

    class Sock:
        def setsockopt(self, *a):
            pass

    class Context:
        def wrap_socket(self, sock, server_hostname):
            calls.append(("tls", server_hostname))
            return sock

    monkeypatch.setattr(
        m.socket,
        "create_connection",
        lambda addr, **kw: (calls.append(("connect", addr)) or Sock()),
    )
    c = m.PinnedHTTPSConnection("docs.example", 443, "93.184.216.34", timeout=3, context=Context())
    c.connect()
    assert calls == [("connect", ("93.184.216.34", 443)), ("tls", "docs.example")]


def test_redirect_private_target_refused_before_connect(monkeypatch):
    m = module()
    connected = []

    def resolve(host, *a, **kw):
        return dns(["127.0.0.1"] if host == "internal.example" else ["93.184.216.34"])()

    monkeypatch.setattr(m.socket, "getaddrinfo", resolve)

    class Response:
        status = 302

        def getheader(self, key, default=None):
            return "http://internal.example/" if key == "Location" else default

        def getheaders(self):
            return []

    class Connection:
        def __init__(self, host, *a, **kw):
            connected.append(host)

        def request(self, *a, **kw):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(m, "PinnedHTTPSConnection", Connection)
    monkeypatch.setattr(m, "PinnedHTTPConnection", Connection)
    with pytest.raises(m.FetchError):
        m.fetch_public_url("https://docs.example/", max_bytes=100)
    assert connected == ["docs.example"]


def test_oversize_response_refused(monkeypatch):
    m = module()
    monkeypatch.setattr(m.socket, "getaddrinfo", dns(["93.184.216.34"]))

    class Response:
        status = 200

        def getheader(self, key, default=None):
            return "101" if key == "Content-Length" else default

        def getheaders(self):
            return []

    class Connection:
        def __init__(self, *a, **kw):
            pass

        def request(self, *a, **kw):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(m, "PinnedHTTPSConnection", Connection)
    with pytest.raises(m.FetchError):
        m.fetch_public_url("https://docs.example/", max_bytes=100)


def test_actual_http_transport_keeps_host_and_uses_pinned_destination(monkeypatch):
    import http.server
    import socket
    import threading

    m = module()
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.headers["Host"], self.path))
            self.send_response(200)
            self.send_header("Content-Length", "7")
            self.end_headers()
            self.wfile.write(b"fixture")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_create = socket.create_connection
    destinations = []

    def connect(address, **kwargs):
        destinations.append(address)
        return real_create(("127.0.0.1", server.server_port), **kwargs)

    original_resolve = socket.getaddrinfo

    def resolve(host, *a, **kw):
        if host == "docs.example":
            return dns(["93.184.216.34"])()
        return original_resolve(host, *a, **kw)

    monkeypatch.setattr(m.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(m.socket, "create_connection", connect)
    try:
        result = m.fetch_public_url("http://docs.example/été?q=été", max_bytes=100)
        assert result.data == b"fixture"
        assert seen == [("docs.example", "/%C3%A9t%C3%A9?q=%C3%A9t%C3%A9")]
        assert destinations == [("93.184.216.34", 80)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_tls_default_verifies_certificate_and_hostname():
    import ssl

    m = module()
    c = m.PinnedHTTPSConnection("docs.example", 443, "93.184.216.34", timeout=1)
    assert c._context.check_hostname is True and c._context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://name:password@docs.example/",
        "http://127.0.0.1/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
def test_local_or_credentialled_urls_refused(url):
    m = module()
    with pytest.raises(m.FetchError):
        m.resolve_public(url)


def test_body_reads_recheck_total_deadline_between_partial_chunks(monkeypatch):
    m = module()
    clock = [0.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(m.socket, "getaddrinfo", dns(["93.184.216.34"]))

    class Response:
        status = 200

        def getheader(self, key, default=None):
            return default

        def getheaders(self):
            return []

        def isclosed(self):
            return False

        def read(self, size):
            pytest.fail("Buffered read can hide arbitrarily many slow network reads")

        def read1(self, size):
            clock[0] += 0.6
            return b"x"

        def close(self):
            pass

    class Connection:
        def __init__(self, *a, **kw):
            pass

        def request(self, *a, **kw):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(m, "PinnedHTTPConnection", Connection)
    with pytest.raises(m.FetchError, match="timed out"):
        m.fetch_public_url("http://docs.example/", max_bytes=100, timeout=1)


@pytest.mark.parametrize("response_kind", ["slow_headers", "truncated"])
def test_actual_transport_refuses_slow_headers_and_truncated_body(monkeypatch, response_kind):
    import socket
    import socketserver
    import threading
    import time

    m = module()
    real_connect = socket.create_connection

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(4096)
            try:
                if response_kind == "slow_headers":
                    self.request.sendall(b"HTTP/1.1 200 OK\r\n")
                    for _ in range(12):
                        self.request.sendall(b"X-Slow: a\r\n")
                        time.sleep(0.025)
                    self.request.sendall(b"Content-Length: 1\r\n\r\nx")
                else:
                    self.request.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nx")
            except OSError:
                pass

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    monkeypatch.setattr(
        m, "resolve_public", lambda url: (m.urlsplit(url), "docs.example", 80, "93.184.216.34")
    )
    monkeypatch.setattr(
        m.socket,
        "create_connection",
        lambda address, **kw: real_connect(server.server_address, **kw),
    )
    started = time.monotonic()
    try:
        with pytest.raises(m.FetchError):
            m.fetch_public_url("http://docs.example/", max_bytes=100, timeout=0.12)
        assert time.monotonic() - started < 0.25
    finally:
        server.server_close()
        thread.join(timeout=1)
