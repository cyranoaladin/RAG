"""Client externe sûr — jamais le secret interne, identité déjà émise.

LOT H2-B remédiation (finding P2-cli-scope-coverage) : contrairement à
`scripts/rag_query.py` (opérateur interne, signe sa propre identité),
`scripts/rag_query_external.py` ne détient jamais `NEXUS_INTERNAL_TOKEN_
SECRET` et reçoit un jeton d'identité pré-émis.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nexus_contracts import RetrievalResponse, load_retrieval_scope_registry

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "rag_query_external.py"
VALID_ENV = {
    "RAG_API_URL": "http://127.0.0.1:8001",
    "RAG_BFF_SERVICE_TOKEN": "test-external-bff-service-token-at-least-32b",
    "RAG_IDENTITY_TOKEN": "pre-issued.identity.token",
}


def _load_client() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rag_query_external_client", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _response() -> dict[str, object]:
    return {
        "results": [
            {
                "chunk_id": "chunk-fr-1",
                "doc_id": "c" * 64,
                "score": 0.8123456,
                "title": "Attendus de fin d'année en français en 3e",
                "excerpt": "Un extrait pédagogique suffisamment court.",
                "citation": {
                    "source_label": "Éduscol officiel",
                    "page": 3,
                    "source_uri": "https://eduscol.education.fr/document.pdf",
                    "rights": "officiel_public",
                },
                "metadata": {
                    "artifact_id": "c" * 64,
                    "content_sha256": "c" * 64,
                    "placement_source_path": "01_EDUSCOL_OFFICIEL/francais.pdf",
                },
            }
        ],
        "warnings": [],
        "filters_applied": {
            "collection": "rag_nexus_francais_troisieme_tc",
            "scope_digest": "a" * 64,
        },
    }


class _Response:
    status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(_response()).encode("utf-8")


def _non_docstring_string_constants() -> set[str]:
    """Every string literal in the module, EXCEPT docstrings (module,
    function, and class docstrings intentionally *name*
    ``identity_v2``/``NEXUS_INTERNAL_TOKEN_SECRET`` in prose, to document
    what this client must never do — only the code itself matters here)."""
    import ast

    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    docstring_nodes: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstring_nodes.add(body[0].value)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node not in docstring_nodes
    }


def test_module_never_imports_the_internal_identity_signer() -> None:
    """Static, structural guarantee — not just behavioral: this module must
    never even import ``ingestor.identity_v2`` (the HS256 signer), so a
    static/dependency audit can prove it, not just a passing test."""
    import ast

    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("identity_v2" in name for name in imported_modules)
    assert "hmac" not in imported_modules

    constants = _non_docstring_string_constants()
    assert "_sign_hs256" not in constants
    assert "NEXUS_INTERNAL_TOKEN_SECRET" not in constants


def test_module_has_no_master_secret_requirement() -> None:
    client = _load_client()
    signature = inspect.signature(client.load_external_client_config)
    assert "NEXUS_INTERNAL_TOKEN_SECRET" not in str(signature)
    assert "NEXUS_INTERNAL_TOKEN_SECRET" not in _non_docstring_string_constants()


def test_valid_bff_and_identity_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    captured: dict[str, Any] = {}

    def urlopen(request: object, *, timeout: float) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)

    assert (
        client.main(
            ["--scope", "entree_seconde_maths_v1", "--query", "Comment me préparer ?"]
        )
        == 0
    )

    request = captured["request"]
    assert request.full_url == "http://127.0.0.1:8001/search/v2"
    assert request.get_header("Authorization") == f"Bearer {VALID_ENV['RAG_BFF_SERVICE_TOKEN']}"
    assert request.get_header("X-nexus-identity") == VALID_ENV["RAG_IDENTITY_TOKEN"]

    payload = json.loads(request.data)
    assert payload["need"]["query"] == "Comment me préparer ?"
    assert "collection" not in payload
    assert RetrievalResponse.model_validate(_response()).results

    output = capsys.readouterr().out
    assert "titre=Attendus de fin d'année en français en 3e" in output
    for secret in (VALID_ENV["RAG_BFF_SERVICE_TOKEN"], VALID_ENV["RAG_IDENTITY_TOKEN"]):
        assert secret not in output


def test_missing_bff_token_fails_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("RAG_BFF_SERVICE_TOKEN")
    monkeypatch.setattr(
        client.urllib.request,
        "urlopen",
        lambda *_a, **_k: pytest.fail("HTTP must not run"),
    )

    assert (
        client.main(["--scope", "entree_seconde_maths_v1", "--query", "Fractions"]) == 2
    )
    assert "RAG_BFF_SERVICE_TOKEN requis" in capsys.readouterr().err


def test_missing_identity_fails_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("RAG_IDENTITY_TOKEN")
    monkeypatch.setattr(
        client.urllib.request,
        "urlopen",
        lambda *_a, **_k: pytest.fail("HTTP must not run"),
    )

    assert (
        client.main(["--scope", "entree_seconde_maths_v1", "--query", "Fractions"]) == 2
    )
    assert "RAG_IDENTITY_TOKEN requis" in capsys.readouterr().err


@pytest.mark.parametrize("status", [401, 403])
def test_server_rejected_identity_surfaces_as_http_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    """Bad, expired, or scope-mismatched identity is entirely the server's
    call — this client never re-signs, retries with a different identity,
    or otherwise works around a rejection; it just surfaces it."""
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)

    def urlopen(*_a: object, **_k: object) -> None:
        raise client.urllib.error.HTTPError(
            "http://127.0.0.1:8001/search/v2", status, "denied", None, None
        )

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)

    assert (
        client.main(["--scope", "entree_seconde_maths_v1", "--query", "Fractions"]) == 2
    )
    assert f"API HTTP {status}" in capsys.readouterr().err


def test_list_scopes_needs_no_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = _load_client()
    for key in VALID_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        client.urllib.request,
        "urlopen",
        lambda *_a, **_k: pytest.fail("HTTP must not run"),
    )

    assert client.main(["--list-scopes"]) == 0
    listed = capsys.readouterr().out.splitlines()
    assert sorted(listed) == sorted(load_retrieval_scope_registry())


def test_covers_every_backend_scope_choice() -> None:
    client = _load_client()
    assert set(client.available_scopes()) == set(load_retrieval_scope_registry())


def test_help_needs_no_credentials() -> None:
    import os
    import subprocess

    environment = os.environ.copy()
    for key in VALID_ENV:
        environment.pop(key, None)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
