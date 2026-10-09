"""Le vhost public Cockpit expose les seuls parcours de recherche étudiant."""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "infra/nginx/rag-cockpit.public-search.conf.template"


@pytest.mark.skipif(
    not (shutil.which("nginx") and shutil.which("openssl")),
    reason="Nginx et OpenSSL nécessaires",
)
def test_public_cockpit_vhost_only_forwards_student_search_routes(tmp_path: Path) -> None:
    calls: list[tuple[str, str, str | None, str | None, str | None]] = []

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.respond()

        def do_POST(self) -> None:  # noqa: N802
            self.respond()

        def respond(self) -> None:
            calls.append((self.command, self.path, self.headers.get("Host"),
                          self.headers.get("X-Forwarded-Proto"),
                          self.headers.get("X-Nexus-Identity")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args: object) -> None:
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    reservations: list[socket.socket] = []
    nginx: subprocess.Popen[bytes] | None = None
    try:
        thread.start()
        reservations = [socket.socket(), socket.socket()]
        for reservation in reservations:
            reservation.bind(("127.0.0.1", 0))
        http_port, https_port = (reservation.getsockname()[1] for reservation in reservations)
        cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
        certificate = subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
             "-subj", "/CN=cockpit.example.test", "-keyout", str(key), "-out", str(cert)],
            capture_output=True, text=True, check=False,
        )
        assert certificate.returncode == 0, certificate.stderr
        rendered = TEMPLATE.read_text(encoding="utf-8")
        rendered = rendered.replace("${RAG_COCKPIT_EXTERNAL_DOMAIN}", "cockpit.example.test")
        rendered = rendered.replace("${NGINX_COCKPIT_PORT}", str(backend.server_port))
        rendered = rendered.replace("listen 80;", f"listen 127.0.0.1:{http_port};")
        rendered = rendered.replace("listen 443 ssl http2;", f"listen 127.0.0.1:{https_port} ssl;")
        rendered = rendered.replace(
            "/etc/letsencrypt/live/cockpit.example.test/fullchain.pem", str(cert)
        ).replace("/etc/letsencrypt/live/cockpit.example.test/privkey.pem", str(key))
        site = tmp_path / "site.conf"
        site.write_text(rendered, encoding="utf-8")
        nginx_conf = tmp_path / "nginx.conf"
        nginx_conf.write_text(
            f"pid {tmp_path / 'nginx.pid'};\nerror_log {tmp_path / 'error.log'};\n"
            f"events {{}}\nhttp {{ access_log off; include {site}; }}\n", encoding="utf-8",
        )
        command = ["nginx", "-p", str(tmp_path), "-c", str(nginx_conf)]
        configured = subprocess.run([*command, "-t"], capture_output=True, text=True, check=False)
        assert configured.returncode == 0, configured.stderr
        for reservation in reservations:
            reservation.close()
        nginx = subprocess.Popen([*command, "-g", "daemon off;"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE)
        opener = build_opener(HTTPSHandler(context=ssl._create_unverified_context()))

        def status(path: str, method: str = "GET") -> int:
            request = Request(
                f"https://127.0.0.1:{https_port}{path}",
                data=b"{}" if method == "POST" else None,
                method=method,
                headers={"Host": "cockpit.example.test", "X-Forwarded-Proto": "http",
                         "X-Nexus-Identity": "forged"},
            )
            try:
                with opener.open(request, timeout=2) as response:
                    return response.status
            except HTTPError as error:
                return error.code

        def http_status(path: str) -> int:
            connection = HTTPConnection("127.0.0.1", http_port, timeout=2)
            try:
                connection.request("GET", path, headers={"Host": "cockpit.example.test"})
                return connection.getresponse().status
            finally:
                connection.close()

        for _ in range(40):
            try:
                status("/blocked")
                break
            except (URLError, TimeoutError):
                time.sleep(0.05)
        allowed = (
            ("GET", "/"), ("GET", "/_next/static/app.js"),
            ("GET", "/api/auth/session"), ("GET", "/api/auth/error"),
            ("POST", "/api/auth/callback/credentials"),
            ("GET", "/api/health"), ("GET", "/api/collections"),
            ("POST", "/api/search"),
        )
        for method, path in allowed:
            assert status(path, method) == 200, (method, path)
        assert [(method, path) for method, path, *_ in calls] == list(allowed)
        assert all(host == "cockpit.example.test" and proto == "https" and identity is None
                   for _, _, host, proto, identity in calls)
        for method, path in (
            ("GET", "/api/search"), ("POST", "/api/collections"),
            ("POST", "/api/chat"), ("GET", "/api/review/queue"),
            ("POST", "/api/review/decide"), ("POST", "/api/health"),
            ("POST", "/ingest"), ("GET", "/metrics"),
            ("GET", "/api/auth/unknown"), ("GET", "/_next/image"),
        ):
            assert status(path, method) in {403, 404, 405}, (method, path)
        assert [(method, path) for method, path, *_ in calls] == list(allowed)
        assert http_status("/") == 308
        assert http_status("/ingest") == 404
        assert http_status("/api/search") == 404
        with ThreadPoolExecutor(max_workers=8) as executor:
            assert list(executor.map(lambda _: status("/api/search", "POST"), range(8))) == [200] * 8
        with ThreadPoolExecutor(max_workers=32) as executor:
            flood = list(executor.map(lambda _: status("/api/search", "POST"), range(80)))
        assert 429 in flood
    finally:
        if nginx is not None:
            nginx.terminate()
            nginx.wait(timeout=5)
        for reservation in reservations:
            reservation.close()
        if thread.is_alive():
            backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
