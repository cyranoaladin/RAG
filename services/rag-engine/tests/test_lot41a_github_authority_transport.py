"""LOT41A/LOT42 — adaptateur GitHub lecture seule : transport, secret,
échéance globale (remédiation GATE H1, items I et J).

Discipline de ce fichier : **la logique d'autorité n'est jamais simulée**.
Un vrai serveur HTTP local sert les trois endpoints GitHub consommés, et
``github_authority`` exécute pour de vrai la fonction de décision partagée
d'ADR-0025 (``evaluate_trusted_review``, non modifiée). Seul le transport
réseau est local — jamais la décision.

Couvre :
- credential absent -> fail-closed ;
- credential lu depuis un fichier monté (jamais l'environnement) ;
- credential invalide (401/403) -> fail-closed ;
- GitHub indisponible (connexion refusée) -> fail-closed ;
- GitHub lent -> échec **en temps borné** (item J), jamais une attente
  indéfinie ;
- head différent de celui attendu -> refus (rejeu d'évidence périmée) ;
- PR fermée/fusionnée -> refus (ADR-0032 § 7) ;
- relecture d'un blob au commit exact + plafond de taille.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from nexus_contracts.authority_artifacts import git_blob_sha1

from ingestor.ingestion_control.github_authority import (
    GitHubAuthorityError,
    GitHubAuthorityTimeoutError,
    GitHubRateLimitedError,
    fetch_blob_at_ref,
    verify_review,
)

REPOSITORY = "cyranoaladin/RAG"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
VALID_TOKEN = "ghp_test_valid_token_value"


def _challenge(pull_request: dict[str, Any]) -> str:
    from ingestor.ingestion_control.github_authority import _load_trusted_review_module

    thr = _load_trusted_review_module()
    root = Path(__file__).resolve().parents[3] / "scripts" / "github"
    config = thr.load_config(root / "trusted-reviewers.json")
    return thr.build_expected_challenges(pull_request, config)["abenrhouma"]


def _pull_request(*, state: str = "open", head_sha: str = HEAD_SHA) -> dict[str, Any]:
    return {
        "number": 4242,
        "state": state,
        "draft": False,
        "base": {"ref": "main", "sha": BASE_SHA},
        "head": {"sha": head_sha, "repo": {"full_name": REPOSITORY}},
        "user": {"login": "cyranoaladin"},
    }


class _State:
    """État mutable du faux GitHub — le test le modifie entre deux appels
    pour simuler une révocation, une lenteur, etc."""

    def __init__(self) -> None:
        pr = _pull_request()
        self.pull_request: dict[str, Any] = pr
        self.reviews: list[dict[str, Any]] = [
            {
                "id": 777,
                "state": "APPROVED",
                "body": _challenge(pr),
                "commit_id": pr["head"]["sha"],
                "submitted_at": "2026-08-08T10:00:00Z",
                "user": {"login": "abenrhouma"},
            }
        ]
        self.permissions: dict[str, Any] = {
            "abenrhouma": {"permission": "write", "role_name": "write"}
        }
        self.blobs: dict[str, bytes] = {}
        self.delay_s: float = 0.0
        self.force_status: int | None = None
        #: Lot DI : en-têtes et message servis avec ``force_status``.
        self.force_headers: dict[str, str] = {}
        self.force_message: str = "forced"
        #: Nombre de réponses forcées restantes (``None`` = toutes).
        self.force_count: int | None = None
        self.requests: list[str] = []
        self.request_authorizations: list[str] = []
        self.require_token: str | None = VALID_TOKEN
        #: Force un `sha` erroné pour prouver que le client le recalcule.
        self.lying_blob_sha: str | None = None


def _make_handler(state: _State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # silence
            return

        def _send(
            self, code: int, payload: Any, headers: dict[str, str] | None = None
        ) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - imposé par BaseHTTPRequestHandler
            state.requests.append(self.path)
            state.request_authorizations.append(self.headers.get("Authorization", ""))
            if state.delay_s:
                time.sleep(state.delay_s)
            if state.require_token is not None:
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {state.require_token}":
                    self._send(401, {"message": "Bad credentials"})
                    return
            if state.force_status is not None and state.force_count != 0:
                if state.force_count is not None:
                    state.force_count -= 1
                self._send(
                    state.force_status, {"message": state.force_message}, state.force_headers
                )
                return

            path = self.path
            if "/pulls/" in path and "/reviews" in path:
                page = 1
                if "page=" in path:
                    page = int(path.rsplit("page=", 1)[1])
                self._send(200, state.reviews if page == 1 else [])
                return
            if "/pulls/" in path:
                self._send(200, state.pull_request)
                return
            if "/collaborators/" in path and path.endswith("/permission"):
                login = path.split("/collaborators/", 1)[1].rsplit("/permission", 1)[0]
                perm = state.permissions.get(login)
                self._send(200 if perm else 404, perm or {"message": "Not Found"})
                return
            if "/contents/" in path:
                import base64 as _b64

                key = path.split("/contents/", 1)[1]
                blob = state.blobs.get(key)
                if blob is None:
                    self._send(404, {"message": "Not Found"})
                    return
                self._send(
                    200,
                    {
                        "type": "file",
                        "encoding": "base64",
                        "size": len(blob),
                        "sha": state.lying_blob_sha or git_blob_sha1(blob),
                        "content": _b64.b64encode(blob).decode("ascii"),
                    },
                )
                return
            self._send(404, {"message": "unhandled"})

    return Handler


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[_State]:
    state = _State()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    monkeypatch.setenv("NEXUS_GITHUB_API_BASE", f"http://{host}:{port}")
    token_file = tmp_path / "gh-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


class TestHappyPath:
    def test_open_approved_pr_at_exact_head_verifies(self, fake_github: _State) -> None:
        result = verify_review(
            repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA
        )
        assert result.approved is True
        assert result.reason == "approved"
        assert result.head_sha == HEAD_SHA
        assert result.reviewer == "abenrhouma"
        assert result.review_id == 777


class TestCredentialHandling:
    def test_missing_credential_fails_closed(
        self, fake_github: _State, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN_FILE", raising=False)
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        with pytest.raises(GitHubAuthorityError, match="no GitHub read credential"):
            verify_review(repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA)

    def test_invalid_credential_fails_closed(
        self, fake_github: _State, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad-token"
        bad.write_text("ghp_wrong_value", encoding="utf-8")
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(bad))
        with pytest.raises(GitHubAuthorityError, match="HTTP 401"):
            verify_review(repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA)

    def test_empty_token_file_fails_closed(
        self, fake_github: _State, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty-token"
        empty.write_text("   \n", encoding="utf-8")
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(empty))
        with pytest.raises(GitHubAuthorityError, match="empty"):
            verify_review(repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA)

    def test_token_is_never_present_in_error_messages(
        self, fake_github: _State, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Un jeton ne doit jamais fuiter par un message d'exception."""
        secret = "ghp_super_secret_never_logged"
        token_file = tmp_path / "secret-token"
        token_file.write_text(secret, encoding="utf-8")
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        fake_github.force_status = 500
        fake_github.require_token = None
        with pytest.raises(GitHubAuthorityError) as excinfo:
            verify_review(repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA)
        assert secret not in str(excinfo.value)
        assert secret not in repr(excinfo.value)


class TestOutageAndTimeoutAreBounded:
    def test_github_unreachable_fails_closed(
        self, fake_github: _State, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", "http://127.0.0.1:1")
        with pytest.raises(GitHubAuthorityError):
            verify_review(repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA)

    def test_slow_github_fails_within_the_bounded_deadline(
        self, fake_github: _State, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Item J : une panne lente doit échouer fail-closed **en temps
        borné**, jamais bloquer le worker indéfiniment."""
        fake_github.delay_s = 5.0
        monkeypatch.setenv("NEXUS_GITHUB_TOTAL_TIMEOUT_S", "1")
        monkeypatch.setenv("NEXUS_GITHUB_REQUEST_TIMEOUT_S", "1")
        started = time.monotonic()
        with pytest.raises(GitHubAuthorityError):
            verify_review(repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA)
        elapsed = time.monotonic() - started
        assert elapsed < 4.0, (
            f"verification took {elapsed:.1f}s — the global deadline did not bound it"
        )

    def test_total_deadline_is_enforced_across_multiple_requests(
        self, fake_github: _State, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'échéance est **globale** : plusieurs requêtes individuellement
        sous leur timeout ne peuvent pas dépasser le budget total."""
        fake_github.delay_s = 0.4
        monkeypatch.setenv("NEXUS_GITHUB_TOTAL_TIMEOUT_S", "0.5")
        monkeypatch.setenv("NEXUS_GITHUB_REQUEST_TIMEOUT_S", "10")
        started = time.monotonic()
        with pytest.raises(GitHubAuthorityTimeoutError):
            verify_review(repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA)
        assert time.monotonic() - started < 3.0


class TestLifecycleThroughTheRealTransport:
    def test_expected_head_mismatch_is_refused(self, fake_github: _State) -> None:
        """Rejeu d'une évidence périmée : la PR est bien approuvée, mais pas
        sur le head que l'appelant croyait vérifier."""
        result = verify_review(
            repository=REPOSITORY, pull_request=4242, expected_head="c" * 40
        )
        assert result.approved is False
        assert result.reason == "expected_head_mismatch"

    def test_closed_authority_pr_is_refused(self, fake_github: _State) -> None:
        """ADR-0032 § 7 vérifié de bout en bout à travers le vrai transport."""
        fake_github.pull_request = _pull_request(state="closed")
        result = verify_review(
            repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA
        )
        assert result.approved is False
        assert result.reason == "pull_request_not_open"

    def test_dismissed_review_is_refused(self, fake_github: _State) -> None:
        fake_github.reviews.append(
            {
                "id": 778,
                "state": "DISMISSED",
                "body": "",
                "commit_id": HEAD_SHA,
                "submitted_at": "2026-08-08T12:00:00Z",
                "user": {"login": "abenrhouma"},
            }
        )
        result = verify_review(
            repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA
        )
        assert result.approved is False
        assert result.reason == "approval_revoked"

    def test_repository_outside_config_is_refused(self, fake_github: _State) -> None:
        with pytest.raises(GitHubAuthorityError, match="does not match the trusted"):
            verify_review(
                repository="attacker/RAG", pull_request=4242, expected_head=HEAD_SHA
            )


class TestBlobFetch:
    def test_fetches_exact_bytes_at_ref(self, fake_github: _State) -> None:
        content = b'{"hello":"world"}'
        fake_github.blobs["governance/authorizations/auth-1.json?ref=" + HEAD_SHA] = content
        blob = fetch_blob_at_ref(
            repository=REPOSITORY,
            path="governance/authorizations/auth-1.json",
            ref=HEAD_SHA,
        )
        assert blob.content == content
        assert blob.blob_sha == git_blob_sha1(content)
        assert blob.ref == HEAD_SHA

    def test_a_blob_sha_that_does_not_match_the_bytes_is_refused(
        self, fake_github: _State
    ) -> None:
        """Un transport compromis qui renverrait un contenu substitué sous
        un ``sha`` légitime est détecté : le SHA d'objet Git est recalculé
        localement sur les octets reçus, jamais cru sur parole."""
        fake_github.blobs["governance/authorizations/auth-1.json?ref=" + HEAD_SHA] = (
            b'{"hello":"world"}'
        )
        fake_github.lying_blob_sha = "0" * 40
        with pytest.raises(GitHubAuthorityError, match="blob sha mismatch"):
            fetch_blob_at_ref(
                repository=REPOSITORY,
                path="governance/authorizations/auth-1.json",
                ref=HEAD_SHA,
            )

    def test_missing_blob_fails_closed(self, fake_github: _State) -> None:
        with pytest.raises(GitHubAuthorityError, match="HTTP 404"):
            fetch_blob_at_ref(
                repository=REPOSITORY,
                path="governance/authorizations/absent.json",
                ref=HEAD_SHA,
            )


class TestRateLimitingFailsClosedWithSafeDiagnostics:
    """Lot DI — incident Worker B : 390 jobs ont échoué sur
    ``GitHub returned HTTP 403 for repos/…/pulls/262`` sans qu'aucun
    en-tête de limitation ne soit conservé. Une limitation de débit reste un
    REFUS (jamais une approbation, jamais une décision en cache) ; elle est
    seulement nommée, avec le délai que GitHub impose."""

    SECRET = "ghp_rate_limit_secret_never_logged"

    @pytest.fixture(autouse=True)
    def _secret_token(
        self, fake_github: _State, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        token_file = tmp_path / "rl-token"
        token_file.write_text(self.SECRET, encoding="utf-8")
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        fake_github.require_token = self.SECRET

    def _verify(self) -> Any:
        return verify_review(repository=REPOSITORY, pull_request=4242, expected_head=HEAD_SHA)

    def _assert_no_secret(self, error: BaseException) -> None:
        for rendered in (str(error), repr(error), repr(getattr(error, "diagnostics", ""))):
            assert self.SECRET not in rendered

    def test_secondary_403_with_retry_after_is_rate_limited_and_refused(
        self, fake_github: _State
    ) -> None:
        fake_github.force_status = 403
        fake_github.force_headers = {"Retry-After": "60", "x-ratelimit-remaining": "4210"}
        fake_github.force_message = "You have exceeded a secondary rate limit."
        with pytest.raises(GitHubRateLimitedError) as excinfo:
            self._verify()
        error = excinfo.value
        assert isinstance(error, GitHubAuthorityError), "fail-closed pour tout appelant existant"
        assert (error.kind, error.retry_after_s) == ("secondary", 60.0)
        assert "GitHub returned HTTP 403 for repos/cyranoaladin/RAG/pulls/4242" in str(error)
        assert "retry-after=60" in str(error) and "x-ratelimit-remaining=4210" in str(error)
        assert "secondary rate limit" in str(error)
        self._assert_no_secret(error)
        assert len(fake_github.requests) == 1, "aucun appel supplémentaire après la limitation"

    def test_secondary_403_without_retry_after_is_rate_limited_without_delay(
        self, fake_github: _State
    ) -> None:
        fake_github.force_status = 403
        fake_github.force_message = "You have exceeded a secondary rate limit. Please wait."
        with pytest.raises(GitHubRateLimitedError) as excinfo:
            self._verify()
        assert (excinfo.value.kind, excinfo.value.retry_after_s) == ("secondary", None)
        self._assert_no_secret(excinfo.value)

    def test_primary_quota_exhaustion_waits_until_reset(self, fake_github: _State) -> None:
        reset = int(time.time()) + 120
        fake_github.force_status = 403
        fake_github.force_headers = {
            "x-ratelimit-limit": "5000",
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": str(reset),
        }
        fake_github.force_message = "API rate limit exceeded for user ID 1."
        with pytest.raises(GitHubRateLimitedError) as excinfo:
            self._verify()
        assert excinfo.value.kind == "primary"
        assert excinfo.value.retry_after_s is not None
        assert 100.0 <= excinfo.value.retry_after_s <= 120.0

    @pytest.mark.parametrize("headers", [{"Retry-After": "7"}, {}])
    def test_429_is_rate_limited_with_or_without_retry_after(
        self, fake_github: _State, headers: dict[str, str]
    ) -> None:
        fake_github.force_status = 429
        fake_github.force_headers = headers
        with pytest.raises(GitHubRateLimitedError) as excinfo:
            self._verify()
        assert excinfo.value.retry_after_s == (7.0 if headers else None)
        self._assert_no_secret(excinfo.value)

    def test_a_permission_403_is_not_disguised_as_rate_limiting(
        self, fake_github: _State
    ) -> None:
        """Un 403 de droits reste un refus ordinaire : ralentir ne le
        corrigerait pas, et l'étiqueter « limitation » masquerait sa cause."""
        fake_github.force_status = 403
        fake_github.force_headers = {"x-ratelimit-remaining": "4999"}
        fake_github.force_message = "Resource not accessible by personal access token"
        with pytest.raises(GitHubAuthorityError) as excinfo:
            self._verify()
        assert not isinstance(excinfo.value, GitHubRateLimitedError)
        assert "Resource not accessible by personal access token" in str(excinfo.value)

    def test_a_message_echoing_the_token_is_redacted(self, fake_github: _State) -> None:
        fake_github.force_status = 403
        fake_github.force_message = f"secondary rate limit for {self.SECRET}"
        with pytest.raises(GitHubRateLimitedError) as excinfo:
            self._verify()
        self._assert_no_secret(excinfo.value)
        assert "[redacted]" in str(excinfo.value)

    def test_hostile_header_values_are_not_copied(self, fake_github: _State) -> None:
        fake_github.force_status = 429
        fake_github.force_headers = {"x-github-request-id": "a béc"}
        with pytest.raises(GitHubRateLimitedError) as excinfo:
            self._verify()
        assert "x-github-request-id" not in str(excinfo.value)

    def test_a_rate_limited_blob_read_fails_closed(self, fake_github: _State) -> None:
        fake_github.blobs["governance/a.json?ref=" + HEAD_SHA] = b"{}"
        fake_github.force_status = 429
        fake_github.force_headers = {"Retry-After": "30"}
        with pytest.raises(GitHubRateLimitedError):
            fetch_blob_at_ref(repository=REPOSITORY, path="governance/a.json", ref=HEAD_SHA)

    def test_after_the_limit_lifts_the_same_verification_is_live_again(
        self, fake_github: _State
    ) -> None:
        """Aucune décision n'est mémorisée : après la levée, la vérification
        suivante refait TOUS les appels live et rend le verdict courant."""
        fake_github.force_status = 403
        fake_github.force_headers = {"Retry-After": "1"}
        fake_github.force_count = 1
        with pytest.raises(GitHubRateLimitedError):
            self._verify()
        before = len(fake_github.requests)
        assert self._verify().approved is True
        assert len(fake_github.requests) - before >= 4, "la vérification reste entièrement live"
        fake_github.pull_request = _pull_request(state="closed")
        assert self._verify().approved is False, "l'état GitHub courant, jamais un cache"
