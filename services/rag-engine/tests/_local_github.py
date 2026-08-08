"""Serveur GitHub local réaliste pour les tests d'autorité LOT41A/LOT42.

**Ce qui est simulé, et ce qui ne l'est pas.** Seul le *serveur HTTP* est
local. Tout le reste de la chaîne d'autorité est le code réel :

- ``ingestion_control.github_authority`` effectue de vraies requêtes HTTP
  (httpx), avec son vrai en-tête d'authentification, sa vraie échéance
  globale, ses vrais refus de statut ;
- la décision est rendue par ``scripts/github/trusted_human_review.py``
  (ADR-0025), **chargée depuis le dépôt et non modifiée**, avec la vraie
  ``trusted-reviewers.json`` et les vrais challenges canoniques ;
- les blobs sont servis avec leur véritable SHA-1 d'objet Git, que le
  client recalcule et vérifie.

Aucun test n'a le droit de monkeypatcher la fonction de décision : la seule
chose qu'un test contrôle ici, c'est l'état que GitHub *renvoie*.

Le serveur écoute sur 127.0.0.1 et exige un jeton Bearer — les scénarios
« credential absent/invalide » sont donc exercés contre un vrai 401.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha1
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

#: Doit correspondre exactement à ``scripts/github/trusted-reviewers.json``.
REPOSITORY = "cyranoaladin/RAG"
BASE_REF = "main"
REVIEWER = "abenrhouma"
VALID_TOKEN = "ghp_local_test_token_value"

_SCRIPTS_GITHUB = Path(__file__).resolve().parents[3] / "scripts" / "github"


def git_blob_sha(raw: bytes) -> str:
    """SHA-1 d'objet Git — la valeur que GitHub renvoie réellement dans
    ``sha`` pour un fichier."""
    return sha1(b"blob %d\0" % len(raw) + raw, usedforsecurity=False).hexdigest()  # noqa: S324


def trusted_review_module() -> Any:
    """Charge la VRAIE fonction de décision d'ADR-0025 — jamais une copie."""
    from ingestor.ingestion_control.github_authority import _load_trusted_review_module

    return _load_trusted_review_module()


def challenge_for(pull_request: dict[str, Any], reviewer: str = REVIEWER) -> str:
    """Challenge canonique réel de cette PR pour ce reviewer, calculé par le
    code d'ADR-0025 lui-même."""
    module = trusted_review_module()
    config = module.load_config(_SCRIPTS_GITHUB / "trusted-reviewers.json")
    challenges: dict[str, str] = module.build_expected_challenges(pull_request, config)
    return challenges[reviewer]


def pull_request_doc(
    *, number: int, head_sha: str, base_sha: str, state: str = "open", draft: bool = False
) -> dict[str, Any]:
    return {
        "number": number,
        "state": state,
        "draft": draft,
        "base": {"ref": BASE_REF, "sha": base_sha},
        "head": {"sha": head_sha, "repo": {"full_name": REPOSITORY}},
        "user": {"login": "cyranoaladin"},
    }


def approved_review(
    *, review_id: int, pull_request: dict[str, Any], submitted_at: str, reviewer: str = REVIEWER
) -> dict[str, Any]:
    return {
        "id": review_id,
        "state": "APPROVED",
        "body": challenge_for(pull_request, reviewer),
        "commit_id": pull_request["head"]["sha"],
        "submitted_at": submitted_at,
        "user": {"login": reviewer},
    }


class LocalGitHub:
    """État mutable du GitHub local — un test le modifie entre deux
    vérifications pour simuler une fermeture de PR, une dismissal, un
    changement de head, une panne."""

    def __init__(self) -> None:
        self.pulls: dict[int, dict[str, Any]] = {}
        self.reviews: dict[int, list[dict[str, Any]]] = {}
        self.permissions: dict[str, dict[str, Any]] = {
            REVIEWER: {"permission": "write", "role_name": "write"}
        }
        #: clé : ``(path, ref)`` -> octets exacts. Le SHA est recalculé, jamais
        #: stocké séparément : un test ne peut pas mentir sur l'identité Git
        #: du contenu qu'il sert.
        self.blobs: dict[tuple[str, str], bytes] = {}
        self.delay_s: float = 0.0
        self.force_status: int | None = None
        self.require_token: str | None = VALID_TOKEN
        self.request_log: list[str] = []
        #: Enregistre toute méthode HTTP non-GET reçue : la preuve que
        #: l'adaptateur est réellement en lecture seule est faite ici, pas
        #: seulement par relecture de code.
        self.non_get_requests: list[tuple[str, str]] = []

    # -- helpers de scénario -------------------------------------------

    def add_approved_pr(
        self, *, number: int, head_sha: str, base_sha: str, review_id: int,
        submitted_at: str = "2026-08-08T10:00:00Z", reviewer: str = REVIEWER,
    ) -> dict[str, Any]:
        doc = pull_request_doc(number=number, head_sha=head_sha, base_sha=base_sha)
        self.pulls[number] = doc
        self.reviews[number] = [
            approved_review(
                review_id=review_id, pull_request=doc,
                submitted_at=submitted_at, reviewer=reviewer,
            )
        ]
        return doc

    def put_blob(self, *, path: str, ref: str, content: bytes) -> str:
        self.blobs[(path, ref)] = content
        return git_blob_sha(content)

    def dismiss_reviews(self, number: int) -> None:
        """Ajoute une DISMISSED strictement POSTÉRIEURE à la dernière review
        existante. Un horodatage antérieur ne révoquerait rien (règle
        d'ADR-0025), et le test passerait pour une raison fausse."""
        doc = self.pulls[number]
        latest = max(
            (str(review.get("submitted_at", "")) for review in self.reviews[number]),
            default="2026-01-01T00:00:00Z",
        )
        year = int(latest[:4]) + 1
        self.reviews[number].append(
            {
                "id": 999_000 + number,
                "state": "DISMISSED",
                "body": "",
                "commit_id": doc["head"]["sha"],
                "submitted_at": f"{year}-01-01T00:00:00Z",
                "user": {"login": REVIEWER},
            }
        )

    def close_pr(self, number: int) -> None:
        self.pulls[number]["state"] = "closed"

    def move_head(self, number: int, new_head_sha: str) -> None:
        self.pulls[number]["head"]["sha"] = new_head_sha


def _make_handler(state: LocalGitHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # silence pytest output
            return

        def _send(self, code: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _reject_mutation(self, method: str) -> None:
            state.non_get_requests.append((method, self.path))
            self._send(405, {"message": "read-only local GitHub"})

        def do_POST(self) -> None:  # noqa: N802 - imposé par BaseHTTPRequestHandler
            self._reject_mutation("POST")

        def do_PUT(self) -> None:  # noqa: N802
            self._reject_mutation("PUT")

        def do_PATCH(self) -> None:  # noqa: N802
            self._reject_mutation("PATCH")

        def do_DELETE(self) -> None:  # noqa: N802
            self._reject_mutation("DELETE")

        def do_GET(self) -> None:  # noqa: N802
            state.request_log.append(self.path)
            if state.delay_s:
                time.sleep(state.delay_s)
            if state.require_token is not None:
                if self.headers.get("Authorization", "") != f"Bearer {state.require_token}":
                    self._send(401, {"message": "Bad credentials"})
                    return
            if state.force_status is not None:
                self._send(state.force_status, {"message": "forced"})
                return

            parts = urlsplit(self.path)
            path, query = parts.path, parts.query
            segments = [s for s in path.split("/") if s]

            # /repos/{owner}/{repo}/pulls/{n}/reviews
            if len(segments) == 6 and segments[0] == "repos" and segments[3] == "pulls" \
                    and segments[5] == "reviews":
                number = int(segments[4])
                page = 1
                for item in query.split("&"):
                    if item.startswith("page="):
                        page = int(item.split("=", 1)[1])
                self._send(200, state.reviews.get(number, []) if page == 1 else [])
                return

            # /repos/{owner}/{repo}/pulls/{n}
            if len(segments) == 5 and segments[0] == "repos" and segments[3] == "pulls":
                number = int(segments[4])
                doc = state.pulls.get(number)
                self._send(200 if doc else 404, doc or {"message": "Not Found"})
                return

            # /repos/{owner}/{repo}/collaborators/{login}/permission
            if len(segments) == 6 and segments[3] == "collaborators" \
                    and segments[5] == "permission":
                perm = state.permissions.get(segments[4])
                self._send(200 if perm else 404, perm or {"message": "Not Found"})
                return

            # /repos/{owner}/{repo}/contents/{path...}?ref=...
            if len(segments) >= 4 and segments[3] == "contents":
                blob_path = unquote("/".join(segments[4:]))
                ref = ""
                for item in query.split("&"):
                    if item.startswith("ref="):
                        ref = item.split("=", 1)[1]
                content = state.blobs.get((blob_path, ref))
                if content is None:
                    self._send(404, {"message": "Not Found"})
                    return
                self._send(
                    200,
                    {
                        "type": "file",
                        "encoding": "base64",
                        "size": len(content),
                        "sha": git_blob_sha(content),
                        "path": blob_path,
                        "content": base64.b64encode(content).decode("ascii"),
                    },
                )
                return

            self._send(404, {"message": "unhandled"})

    return Handler


@contextmanager
def local_github_server(state: LocalGitHub) -> Iterator[str]:
    """Démarre le serveur et rend son URL de base. Toujours arrêté à la
    sortie, même sur exception — jamais de thread résiduel entre tests."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


__all__ = [
    "BASE_REF",
    "REPOSITORY",
    "REVIEWER",
    "VALID_TOKEN",
    "LocalGitHub",
    "approved_review",
    "challenge_for",
    "git_blob_sha",
    "local_github_server",
    "pull_request_doc",
    "trusted_review_module",
]
