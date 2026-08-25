"""Client HTTP officiel des deux scopes Wave 0 étroits."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nexus_contracts import (
    RetrievalResponse,
    RetrievalScopeArtifactV2,
    load_retrieval_scope_registry,
)

from ingestor.identity_v2 import (
    IdentityVerifierConfig,
    verify_identity_token,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "rag_query.py"
SECRET = "test-wave0-internal-secret-at-least-32-bytes"
VALID_ENV = {
    "RAG_API_URL": "http://127.0.0.1:8001",
    "RAG_BFF_SERVICE_TOKEN": "test-wave0-bff-service-token-at-least-32-bytes",
    "NEXUS_INTERNAL_TOKEN_SECRET": SECRET,
    "NEXUS_INTERNAL_TOKEN_ISSUER": "nexus-cockpit",
    "NEXUS_INTERNAL_TOKEN_AUDIENCE": "nexus-rag-engine",
    "NEXUS_SSO_ISSUER": "nexus-sso",
    "NEXUS_SSO_AUDIENCE": "nexus-cockpit",
}


def _load_client() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rag_query_client", SCRIPT_PATH)
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


@pytest.mark.parametrize(
    ("scope_id", "matiere", "collection"),
    (
        (
            "entree_seconde_maths_v1",
            "maths",
            "rag_nexus_maths_troisieme_tc",
        ),
        (
            "entree_seconde_francais_v1",
            "francais",
            "rag_nexus_francais_troisieme_tc",
        ),
    ),
)
def test_client_signs_canonical_identity_and_posts_curriculum_scope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scope_id: str,
    matiere: str,
    collection: str,
) -> None:
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    captured: dict[str, Any] = {}

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps(_response()).encode("utf-8")

    def urlopen(request: object, *, timeout: float) -> Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(client.time, "time", lambda: 1_800_000_000)

    assert client.main(["--scope", scope_id, "--query", "Comment me préparer ?"]) == 0

    request = captured["request"]
    assert request.full_url == "http://127.0.0.1:8001/search/v2"
    assert request.get_header("Authorization") == (
        f"Bearer {VALID_ENV['RAG_BFF_SERVICE_TOKEN']}"
    )
    token = request.get_header("X-nexus-identity")
    assert isinstance(token, str)
    artifact = client.load_retrieval_scope_artifact(scope_id)
    verified = verify_identity_token(
        token,
        config=IdentityVerifierConfig(
            secret=SECRET,
            issuer=VALID_ENV["NEXUS_INTERNAL_TOKEN_ISSUER"],
            audience=VALID_ENV["NEXUS_INTERNAL_TOKEN_AUDIENCE"],
            identity_issuer=VALID_ENV["NEXUS_SSO_ISSUER"],
            identity_audience=VALID_ENV["NEXUS_SSO_AUDIENCE"],
            artifact=artifact,
            artifacts={scope_id: artifact},
        ),
        now=1_800_000_000,
    )
    assert verified.envelope.identity.role == "teacher"
    assert verified.envelope.identity.niveau.value == "seconde"
    assert verified.envelope.allowed_collections == [collection]

    payload = json.loads(request.data)
    assert payload["student_profile"]["niveau"] == "seconde"
    assert payload["student_profile"]["matieres"] == [matiere]
    assert payload["curriculum_scope"] == {
        "niveau": "troisieme",
        "voie": "college",
        "matiere": matiere,
        "statut_enseignement": "tronc_commun",
    }
    assert payload["need"]["query"] == "Comment me préparer ?"
    assert "collection" not in payload
    assert RetrievalResponse.model_validate(_response()).results

    output = capsys.readouterr().out
    assert "score=0.812346" in output
    assert "titre=Attendus de fin d'année en français en 3e" in output
    assert "page=3" in output
    assert "source=https://eduscol.education.fr/document.pdf" in output
    assert "rights=officiel_public" in output
    assert f"sha={'c' * 64}" in output
    assert "path=01_EDUSCOL_OFFICIEL/francais.pdf" in output
    for secret in (
        SECRET,
        VALID_ENV["RAG_BFF_SERVICE_TOKEN"],
        token,
    ):
        assert secret not in output


def test_client_rejects_missing_secret_without_sending_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("NEXUS_INTERNAL_TOKEN_SECRET")
    monkeypatch.setattr(
        client.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("HTTP must not run"),
    )

    assert client.main(
        ["--scope", "entree_seconde_maths_v1", "--query", "Fractions"]
    ) == 2
    assert "configuration d'identité invalide" in capsys.readouterr().err


def test_client_rejects_a_non_contractual_response(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b'{"results":"not-a-list"}'

    monkeypatch.setattr(client.urllib.request, "urlopen", lambda *_a, **_k: Response())

    assert client.main(
        ["--scope", "entree_seconde_maths_v1", "--query", "Fractions"]
    ) == 2
    assert "réponse API invalide" in capsys.readouterr().err


def test_help_needs_no_credentials() -> None:
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
    for scope_id in load_retrieval_scope_registry():
        assert scope_id in result.stdout
    assert result.stderr == ""


def test_list_scopes_prints_the_full_registry_without_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Scope discovery must never require the internal signing secret —
    only issuing an identity does."""
    client = _load_client()
    for key in VALID_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        client.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("HTTP must not run"),
    )

    assert client.main(["--list-scopes"]) == 0

    listed = capsys.readouterr().out.splitlines()
    assert sorted(listed) == sorted(load_retrieval_scope_registry())


def test_internal_cli_covers_every_backend_scope() -> None:
    """LOT H2-B remédiation (finding P2-cli-scope-coverage) : le client
    interne doit reconnaître 100% des scopes du registre canonique — plus
    l'allowlist statique de 2 scopes qui divergeait déjà du backend
    (BACKEND_SCOPE_COUNT=31 après liaison de la release production)."""
    client = _load_client()
    backend_scopes = load_retrieval_scope_registry()

    assert set(client.available_scopes()) == set(backend_scopes)
    assert len(client.available_scopes()) == len(backend_scopes) == 31


def test_internal_cli_can_issue_an_identity_for_every_v2_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every V2 scope in the registry (30 of the 31) must reach a signed,
    self-verifying identity through the same code path — not just the two
    Wave 0 scopes the old hardcoded allowlist happened to cover."""
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(client.time, "time", lambda: 1_800_000_000)
    config = client.load_client_config()

    v2_scopes = {
        scope_id: artifact
        for scope_id, artifact in load_retrieval_scope_registry().items()
        if isinstance(artifact, RetrievalScopeArtifactV2)
    }
    assert len(v2_scopes) == 30

    for scope_id in v2_scopes:
        token, artifact = client.issue_scope_identity(scope_id, config=config)
        assert isinstance(artifact, RetrievalScopeArtifactV2)
        verified = verify_identity_token(
            token,
            config=IdentityVerifierConfig(
                secret=SECRET,
                issuer=VALID_ENV["NEXUS_INTERNAL_TOKEN_ISSUER"],
                audience=VALID_ENV["NEXUS_INTERNAL_TOKEN_AUDIENCE"],
                identity_issuer=VALID_ENV["NEXUS_SSO_ISSUER"],
                identity_audience=VALID_ENV["NEXUS_SSO_AUDIENCE"],
                artifact=artifact,
                artifacts={scope_id: artifact},
            ),
            now=1_800_000_000,
        )
        assert verified.envelope.scope_id == scope_id


def test_internal_cli_refuses_the_pilot_scope_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 13th registry entry (``libre_terminale_maths_nsi_real_v1``) is a
    pilot-shaped artifact, not a V2 one — this CLI's identity issuance only
    speaks V2. Listing it as an available scope must never crash; it must
    fail with a clear, controlled error instead."""
    client = _load_client()
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)
    config = client.load_client_config()

    with pytest.raises(client.RagQueryClientError, match="scope Wave 0 invalide"):
        client.issue_scope_identity("libre_terminale_maths_nsi_real_v1", config=config)
