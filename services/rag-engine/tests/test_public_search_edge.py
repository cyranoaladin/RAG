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


def test_public_vhost_has_one_exact_search_upstream_and_no_other_proxy() -> None:
    config = TEMPLATE.read_text(encoding="utf-8")
    assert config.count("proxy_pass ") == 1
    assert "location = /search/v2 {" in config
    assert "limit_except POST {" in config
    assert "proxy_pass http://127.0.0.1:${NGINX_API_PORT}/search/v2;" in config
    assert "location / {\n    return 404;\n  }" in config
    assert "server_name ${RAG_API_EXTERNAL_DOMAIN};" in config
    assert 'add_header Strict-Transport-Security "max-age=63072000" always;' in config


@pytest.mark.skipif(
    not (shutil.which("nginx") and shutil.which("openssl")),
    reason="Nginx et OpenSSL nécessaires au test HTTP réel",
)
def test_public_vhost_forwards_only_post_search(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    forwarded_headers: list[dict[str, str | None]] = []
    authorization_headers: list[dict[str, str | None]] = []
    upstream_hosts: list[str | None] = []

    class Backend(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            calls.append(("POST", self.path))
            upstream_hosts.append(self.headers.get("Host"))
            forwarded_headers.append({
                name: self.headers.get(name)
                for name in (
                    "Forwarded", "X-Forwarded-For", "X-Forwarded-Host",
                    "X-Forwarded-Proto", "X-Forwarded-Port",
                    "X-Forwarded-Prefix", "X-Forwarded-Server", "X-Real-IP",
                )
            })
            authorization_headers.append({
                name: self.headers.get(name)
                for name in ("Authorization", "X-RAG-API-Key", "X-Nexus-Identity")
            })
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
    http_reservation, https_reservation = socket.socket(), socket.socket()
    http_reservation.bind(("127.0.0.1", 0))
    https_reservation.bind(("127.0.0.1", 0))
    http_port = http_reservation.getsockname()[1]
    https_port = https_reservation.getsockname()[1]
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    certificate_result = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=api.example.test", "-keyout", str(key), "-out", str(cert)],
        capture_output=True, text=True,
    )
    assert certificate_result.returncode == 0, certificate_result.stderr
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
    config_result = subprocess.run([*cmd, "-t"], capture_output=True, text=True)
    assert config_result.returncode == 0, config_result.stderr
    http_reservation.close()
    https_reservation.close()
    nginx = subprocess.Popen([*cmd, "-g", "daemon off;"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
    opener = build_opener(HTTPSHandler(context=ssl._create_unverified_context()))

    def status(
        path: str, method: str = "GET", headers: dict[str, str] | None = None,
    ) -> int:
        request = Request(
            f"https://127.0.0.1:{https_port}{path}",
            data=b"{}" if method == "POST" else None,
            method=method,
            headers={"Host": "api.example.test", **(headers or {})},
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
        with pytest.raises(HTTPError) as rejected:
            opener.open(Request(
                f"https://127.0.0.1:{https_port}/unknown",
                headers={"Host": "api.example.test"},
            ), timeout=2)
        assert rejected.value.headers["Strict-Transport-Security"] == "max-age=63072000"
        assert status("/search/v2", "POST", {
            "Forwarded": "for=203.0.113.55;proto=http",
            "X-Forwarded-For": "203.0.113.55",
            "X-Forwarded-Host": "attacker.example",
            "X-Forwarded-Proto": "http",
            "X-Forwarded-Port": "1234",
            "X-Forwarded-Prefix": "/attacker",
            "X-Forwarded-Server": "attacker.example",
            "X-Real-IP": "203.0.113.55",
            "Authorization": "Bearer synthetic-token",
            "X-RAG-API-Key": "synthetic-api-key",
            "X-Nexus-Identity": "synthetic-signed-identity",
        }) == 200
        assert forwarded_headers == [{
            "Forwarded": None, "X-Forwarded-For": None,
            "X-Forwarded-Host": None, "X-Forwarded-Proto": None,
            "X-Forwarded-Port": None, "X-Forwarded-Prefix": None,
            "X-Forwarded-Server": None,
            "X-Real-IP": None,
        }]
        assert authorization_headers == [{
            "Authorization": "Bearer synthetic-token",
            "X-RAG-API-Key": "synthetic-api-key",
            "X-Nexus-Identity": "synthetic-signed-identity",
        }]
        assert upstream_hosts == ["api.example.test"]
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
        for _ in range(60):
            assert status("/search/v2") in {403, 405}
        assert status("/search/v2", "POST") == 200
        assert calls == [("POST", "/search/v2"), ("POST", "/search/v2")]
    finally:
        nginx.terminate()
        nginx.wait(timeout=5)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=5)
