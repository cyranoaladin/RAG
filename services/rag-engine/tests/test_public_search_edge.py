"""Public search edge: run the rendered vhost through a real local Nginx."""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "infra/nginx/rag-api.public-search.conf.template"


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_public_vhost_has_one_exact_search_upstream_and_no_other_proxy() -> None:
    config = TEMPLATE.read_text(encoding="utf-8")
    assert config.count("proxy_pass ") == 1
    assert "location = /search/v2 {" in config
    assert "limit_except POST {" in config
    assert "proxy_pass http://127.0.0.1:${NGINX_API_PORT}/search/v2;" in config
    assert "location / {\n    return 404;\n  }" in config
    assert "server_name ${RAG_API_EXTERNAL_DOMAIN};" in config


@pytest.mark.skipif(
    not (shutil.which("nginx") and shutil.which("openssl")),
    reason="Nginx et OpenSSL nécessaires au test HTTP réel",
)
def test_public_vhost_forwards_only_post_search(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []

    class Backend(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            calls.append(("POST", self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        def do_GET(self) -> None:  # noqa: N802
            calls.append(("GET", self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        def log_message(self, *_args: object) -> None:
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()
    http_port, https_port = _port(), _port()
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=api.example.test", "-keyout", str(key), "-out", str(cert)],
        check=True, capture_output=True,
    )
    rendered = TEMPLATE.read_text(encoding="utf-8")
    rendered = rendered.replace("${RAG_API_EXTERNAL_DOMAIN}", "api.example.test")
    rendered = rendered.replace("${NGINX_API_PORT}", str(backend.server_port))
    rendered = rendered.replace("listen 80;", f"listen 127.0.0.1:{http_port};")
    rendered = rendered.replace("listen 443 ssl http2;", f"listen 127.0.0.1:{https_port} ssl;")
    rendered = rendered.replace(
        "/etc/letsencrypt/live/api.example.test/fullchain.pem", str(cert)
    ).replace("/etc/letsencrypt/live/api.example.test/privkey.pem", str(key))
    site = tmp_path / "site.conf"
    site.write_text(rendered, encoding="utf-8")
    nginx_conf = tmp_path / "nginx.conf"
    nginx_conf.write_text(
        f"pid {tmp_path / 'nginx.pid'};\n"
        f"error_log {tmp_path / 'error.log'};\n"
        f"events {{}}\nhttp {{ access_log off; include {site}; }}\n",
        encoding="utf-8",
    )
    cmd = ["nginx", "-p", str(tmp_path), "-c", str(nginx_conf)]
    subprocess.run([*cmd, "-t"], check=True, capture_output=True)
    nginx = subprocess.Popen([*cmd, "-g", "daemon off;"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
    opener = build_opener(HTTPSHandler(context=ssl._create_unverified_context()))

    def status(path: str, method: str = "GET") -> int:
        request = Request(
            f"https://127.0.0.1:{https_port}{path}",
            data=b"{}" if method == "POST" else None,
            method=method,
            headers={"Host": "api.example.test"},
        )
        try:
            with opener.open(request, timeout=2) as response:
                return response.status
        except HTTPError as error:
            return error.code

    def http_status(path: str) -> int:
        connection = HTTPConnection("127.0.0.1", http_port, timeout=2)
        try:
            connection.request("GET", path, headers={"Host": "api.example.test"})
            return connection.getresponse().status
        finally:
            connection.close()

    try:
        for _ in range(40):
            try:
                status("/unknown")
                break
            except (URLError, TimeoutError):
                time.sleep(0.05)
        assert status("/search/v2", "POST") == 200
        assert status("/search/v2") in {403, 405}
        for path in (
            "/ingest", "/ingest/v2", "/metrics", "/health",
            "/review/v2/decide", "/review/v2/queue", "/collections/v2",
            "/collections/readiness", "/chat", "/catalogue/v2", "/search/v2/extra",
        ):
            assert status(path) == 404, path
        for path in ("/ingest", "/ingest/v2", "/review/v2/decide", "/chat"):
            assert status(path, "POST") == 404, path
        assert http_status("/search/v2") == 308
        for path in ("/ingest", "/ingest/v2", "/review/v2/decide", "/metrics"):
            assert http_status(path) == 404, path
        assert calls == [("POST", "/search/v2")]
    finally:
        nginx.terminate()
        nginx.wait(timeout=5)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=5)
