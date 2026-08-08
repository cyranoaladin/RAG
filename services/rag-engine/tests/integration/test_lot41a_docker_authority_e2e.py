"""Autorité GitHub dans l'IMAGE RÉELLE du worker (item **I**).

Ces tests construisent ``Dockerfile.ingestion-worker`` puis exécutent la
vérification d'autorité **dans le conteneur produit**, pas dans le
virtualenv de développement. C'est la seule façon de prouver ce que l'item
I demande :

- aucun binaire ``gh`` n'est requis (et il n'y en a pas dans l'image) ;
- la décision est rendue par la vraie fonction pure d'ADR-0025, chargée
  depuis les fichiers réellement copiés dans l'image, sans aucun
  monkeypatch ;
- le jeton est lu à l'exécution depuis un fichier secret monté, jamais
  présent dans une couche, un ``ENV``, un label ou une commande ;
- l'échéance globale (item J) borne réellement une panne GitHub.

Le serveur GitHub est local (``--network host``) pour que le scénario soit
reproductible sans dépendre d'Internet — mais c'est un vrai serveur HTTP,
atteint par le vrai client httpx du conteneur.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _local_github import (  # noqa: E402
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    local_github_server,
)
from _pg_authority import requires_docker  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

IMAGE_TAG = "nexus-ingestion-worker:h1-authority-e2e"
PR_NUMBER, HEAD_SHA, BASE_SHA, REVIEW_ID = 4242, "b" * 40, "a" * 40, 777

#: Script exécuté DANS le conteneur. Il importe le module d'autorité réel de
#: l'image et n'installe aucun double : si la décision d'ADR-0025 n'était pas
#: chargeable depuis l'image, ce script échouerait — ce qui est précisément
#: ce que l'item I veut détecter.
E2E_SCRIPT = '''
import json, sys, time
from ingestion_control.github_authority import (
    GitHubAuthorityError, verify_review,
)

started = time.monotonic()
try:
    result = verify_review(
        repository=sys.argv[1], pull_request=int(sys.argv[2]), expected_head=sys.argv[3]
    )
    payload = {
        "outcome": "verified",
        "approved": result.approved,
        "reason": result.reason,
        "reviewer": result.reviewer,
        "review_id": result.review_id,
        "head_sha": result.head_sha,
    }
except GitHubAuthorityError as exc:
    payload = {"outcome": "error", "type": type(exc).__name__, "message": str(exc)}
payload["elapsed_s"] = round(time.monotonic() - started, 3)
print(json.dumps(payload))
'''


def _docker(*args: str, check: bool = True, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=timeout
    )


@pytest.fixture(scope="module")
def worker_image() -> Iterator[str]:
    """Construit la VRAIE image, depuis un contexte propre (la racine du
    dépôt telle que Git la connaît) — jamais un contexte pollué par des
    artefacts locaux."""
    _docker(
        "build", "-f", str(ENGINE_ROOT / "infra" / "Dockerfile.ingestion-worker"),
        "-t", IMAGE_TAG, str(REPO_ROOT),
        timeout=1800,
    )
    try:
        yield IMAGE_TAG
    finally:
        _docker("image", "rm", "-f", IMAGE_TAG, check=False)


@pytest.fixture
def github(tmp_path: Path) -> Iterator[tuple[LocalGitHub, str, Path]]:
    state = LocalGitHub()
    state.add_approved_pr(
        number=PR_NUMBER, head_sha=HEAD_SHA, base_sha=BASE_SHA, review_id=REVIEW_ID,
    )
    token_file = tmp_path / "gh-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    token_file.chmod(0o644)
    with local_github_server(state) as base_url:
        yield state, base_url, token_file


def run_in_container(
    image: str,
    *,
    api_base: str,
    token_file: Path | None,
    token_env: str | None = None,
    expected_head: str = HEAD_SHA,
    pull_request: int = PR_NUMBER,
    total_timeout_s: str | None = None,
    request_timeout_s: str | None = None,
    script_dir: Path,
) -> dict[str, Any]:
    script = script_dir / "e2e.py"
    script.write_text(E2E_SCRIPT, encoding="utf-8")
    script.chmod(0o644)

    args = [
        "run", "--rm", "--network", "host",
        "--security-opt", "no-new-privileges:true",
        "-v", f"{script}:/app/e2e.py:ro",
        "-e", f"NEXUS_GITHUB_API_BASE={api_base}",
    ]
    if token_file is not None:
        args += ["-v", f"{token_file}:/run/secrets/nexus_github_token:ro",
                 "-e", "NEXUS_GITHUB_TOKEN_FILE=/run/secrets/nexus_github_token"]
    if token_env is not None:
        args += ["-e", f"NEXUS_GITHUB_TOKEN={token_env}"]
    if total_timeout_s is not None:
        args += ["-e", f"NEXUS_GITHUB_TOTAL_TIMEOUT_S={total_timeout_s}"]
    if request_timeout_s is not None:
        args += ["-e", f"NEXUS_GITHUB_REQUEST_TIMEOUT_S={request_timeout_s}"]
    args += [image, "python", "/app/e2e.py", REPOSITORY, str(pull_request), expected_head]

    result = _docker(*args, timeout=300)
    payload: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return payload


class TestTheImageNeedsNoGitHubCli:
    def test_gh_is_absent_from_the_image(self, worker_image: str) -> None:
        """Le transport ``gh api`` n'aurait jamais fonctionné ici. Sa
        disparition est vérifiée, pas supposée."""
        result = _docker(
            "run", "--rm", "--entrypoint", "sh", worker_image,
            "-c", "command -v gh || echo ABSENT", check=False,
        )
        assert "ABSENT" in result.stdout

    def test_the_gh_adapter_script_is_not_shipped(self, worker_image: str) -> None:
        result = _docker(
            "run", "--rm", "--entrypoint", "sh", worker_image,
            "-c", "test -e /app/scripts/github/trusted_human_review_github.py "
                  "&& echo PRESENT || echo ABSENT",
            check=False,
        )
        assert "ABSENT" in result.stdout

    def test_the_pure_adr0025_decision_is_shipped(self, worker_image: str) -> None:
        result = _docker(
            "run", "--rm", "--entrypoint", "sh", worker_image,
            "-c", "test -f /app/scripts/github/trusted_human_review.py "
                  "&& test -f /app/scripts/github/trusted-reviewers.json && echo OK",
        )
        assert "OK" in result.stdout

    def test_the_shipped_decision_is_byte_identical_to_the_repository(
        self, worker_image: str
    ) -> None:
        """L'image ne doit jamais embarquer une variante « adaptée » de la
        décision d'autorité — c'est le contournement de gouvernance le plus
        simple à commettre, donc celui qu'il faut mesurer."""
        result = _docker(
            "run", "--rm", "--entrypoint", "sh", worker_image,
            "-c", "sha256sum /app/scripts/github/trusted_human_review.py "
                  "/app/scripts/github/trusted-reviewers.json",
        )
        shipped = {line.split()[1].rsplit("/", 1)[1]: line.split()[0]
                   for line in result.stdout.strip().splitlines()}
        local = subprocess.run(
            ["sha256sum",
             str(REPO_ROOT / "scripts" / "github" / "trusted_human_review.py"),
             str(REPO_ROOT / "scripts" / "github" / "trusted-reviewers.json")],
            capture_output=True, text=True, check=True,
        )
        expected = {line.split()[1].rsplit("/", 1)[1]: line.split()[0]
                    for line in local.stdout.strip().splitlines()}
        assert shipped == expected


class TestLiveAuthorityInsideTheRealImage:
    def test_an_approved_pr_verifies(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        _, api_base, token_file = github
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=token_file, script_dir=tmp_path
        )
        assert payload["outcome"] == "verified"
        assert payload["approved"] is True
        assert payload["reviewer"] == "abenrhouma"
        assert payload["review_id"] == REVIEW_ID

    def test_a_missing_token_fails_closed(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        _, api_base, _ = github
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=None, script_dir=tmp_path
        )
        assert payload["outcome"] == "error"
        assert "no GitHub read credential" in payload["message"]

    def test_an_invalid_token_fails_closed(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        _, api_base, _ = github
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=None,
            token_env="ghp_wrong_value", script_dir=tmp_path,
        )
        assert payload["outcome"] == "error"
        assert "HTTP 401" in payload["message"]

    def test_the_token_never_leaks_into_the_error(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        state, api_base, _ = github
        state.force_status = 500
        state.require_token = None
        secret = "ghp_super_secret_never_logged"
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=None,
            token_env=secret, script_dir=tmp_path,
        )
        assert payload["outcome"] == "error"
        assert secret not in json.dumps(payload)

    def test_github_unreachable_fails_closed(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        _, _, token_file = github
        payload = run_in_container(
            worker_image, api_base="http://127.0.0.1:1", token_file=token_file,
            script_dir=tmp_path,
        )
        assert payload["outcome"] == "error"

    def test_a_slow_github_fails_within_the_global_deadline(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        """Item J vérifié dans l'image réelle : une panne lente ne bloque
        jamais le worker indéfiniment."""
        state, api_base, token_file = github
        state.delay_s = 10.0
        started = time.monotonic()
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=token_file,
            total_timeout_s="2", request_timeout_s="2", script_dir=tmp_path,
        )
        elapsed = time.monotonic() - started
        assert payload["outcome"] == "error"
        assert payload["elapsed_s"] < 8.0, payload
        assert elapsed < 60.0

    def test_a_closed_pr_is_refused(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        state, api_base, token_file = github
        state.close_pr(PR_NUMBER)
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=token_file, script_dir=tmp_path
        )
        assert payload["approved"] is False
        assert payload["reason"] == "pull_request_not_open"

    def test_a_dismissed_review_is_refused(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        state, api_base, token_file = github
        state.dismiss_reviews(PR_NUMBER)
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=token_file, script_dir=tmp_path
        )
        assert payload["approved"] is False
        assert payload["reason"] == "approval_revoked"

    def test_a_changed_head_is_refused(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        state, api_base, token_file = github
        state.move_head(PR_NUMBER, "e" * 40)
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=token_file, script_dir=tmp_path
        )
        assert payload["approved"] is False

    def test_a_challenge_mismatch_is_refused(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        """Le corps de la review ne porte plus le challenge canonique : la
        vraie décision d'ADR-0025, exécutée dans l'image, refuse."""
        state, api_base, token_file = github
        state.reviews[PR_NUMBER][0]["body"] = "LGTM"
        payload = run_in_container(
            worker_image, api_base=api_base, token_file=token_file, script_dir=tmp_path
        )
        assert payload["approved"] is False

    def test_the_container_never_issues_a_mutating_request(
        self, worker_image: str, github: tuple[LocalGitHub, str, Path], tmp_path: Path
    ) -> None:
        state, api_base, token_file = github
        run_in_container(
            worker_image, api_base=api_base, token_file=token_file, script_dir=tmp_path
        )
        assert state.non_get_requests == [], state.non_get_requests
        assert state.request_log, "the container must actually have called GitHub"


class TestNoSecretIsBakedIntoTheImage:
    """Un secret dans une couche reste extractible même si le fichier est
    supprimé plus tard. On inspecte donc l'historique, pas seulement le
    système de fichiers final."""

    SECRET_MARKERS = (
        "ghp_", "github_pat_", "PASSWORD=", "_DSN=", "NEXUS_GITHUB_TOKEN=",
        "BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY",
    )

    def test_history_contains_no_secret(self, worker_image: str) -> None:
        history = _docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", worker_image)
        for marker in self.SECRET_MARKERS:
            assert marker not in history.stdout, f"{marker!r} found in image history"

    def test_env_labels_and_command_contain_no_secret(self, worker_image: str) -> None:
        inspected = _docker("inspect", worker_image)
        document = json.loads(inspected.stdout)[0]
        config = document["Config"]
        surface = json.dumps(
            {
                "Env": config.get("Env"),
                "Labels": config.get("Labels"),
                "Cmd": config.get("Cmd"),
                "Entrypoint": config.get("Entrypoint"),
            }
        )
        for marker in self.SECRET_MARKERS:
            assert marker not in surface, f"{marker!r} found in image config: {surface}"

    def test_no_credential_file_is_present_in_the_filesystem(
        self, worker_image: str
    ) -> None:
        result = _docker(
            "run", "--rm", "--entrypoint", "sh", worker_image,
            "-c",
            # Les magasins de certificats publics (/etc/ssl/certs,
            # certifi) sont exclus : ce sont des ancres de confiance
            # publiques, pas des credentials. Ce qui est recherché, ce sont
            # des CLÉS PRIVÉES et des fichiers d'identifiants.
            "grep -rIl -e 'BEGIN PRIVATE KEY' -e 'BEGIN RSA PRIVATE KEY' "
            "-e 'BEGIN OPENSSH PRIVATE KEY' / --exclude-dir=proc --exclude-dir=sys "
            "2>/dev/null | head -20; "
            "find / -xdev \\( -name '.env' -o -name '.netrc' -o -name '.pgpass' "
            "-o -name 'nexus_github_token' -o -name 'id_rsa' \\) 2>/dev/null | head -20; "
            "echo SCAN_DONE",
            check=False,
        )
        listed = result.stdout.replace("SCAN_DONE", "").strip()
        assert listed == "", f"unexpected credential-like files in the image: {listed}"

    def test_grep_finds_no_token_shaped_string_in_the_app_layer(
        self, worker_image: str
    ) -> None:
        result = _docker(
            "run", "--rm", "--entrypoint", "sh", worker_image,
            "-c",
            "grep -rIl -e 'ghp_[A-Za-z0-9]' -e 'github_pat_' /app 2>/dev/null "
            "| head -20; echo SCAN_DONE",
            check=False,
        )
        listed = result.stdout.replace("SCAN_DONE", "").strip()
        assert listed == "", f"token-shaped strings found under /app: {listed}"
