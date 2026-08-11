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


#: Scanner de credentials de l'image — **une seule** définition, utilisée mot
#: pour mot par le contrôle réel et par ses tests de non-vacuité. Un scanner
#: dupliqué dans le test de non-vacuité ne prouverait rien sur celui qui
#: tourne réellement.
#:
#: Deux recherches indépendantes, aucune exclusion de répertoire au-delà de
#: ``/proc`` et ``/sys`` (systèmes de fichiers virtuels, pas du contenu
#: d'image) :
#:
#: 1. **Par contenu, structurelle.** Un simple ``grep 'BEGIN … PRIVATE KEY'``
#:    signalait toute bibliothèque capable d'*analyser* un format de clé —
#:    ``cryptography…serialization/ssh.py`` porte cet en-tête comme constante
#:    de parsing. Exclure ``site-packages`` aurait fermé le faux positif en
#:    ouvrant un angle mort : une vraie clé au nom banal (``innocent-data.bin``)
#:    y serait devenue invisible. La détection porte donc sur un **bloc
#:    complet** : marqueur BEGIN seul sur sa ligne, marqueur END *du même
#:    type*, et au moins une ligne de charge utile base64 crédible entre les
#:    deux. Une constante entre guillemets ne satisfait jamais l'ancrage de
#:    ligne ; un BEGIN orphelin, un bloc vide, des marqueurs dépareillés et
#:    une charge utile invraisemblable échouent tous sur l'une des trois
#:    conditions.
#: 2. **Par nom de fichier**, sans aucune exclusion. Cette branche est
#:    volontairement *fail-closed* : elle juge le NOM, jamais le contenu.
#:    ``*.key`` y figure à ce titre — tout fichier régulier portant cette
#:    extension est traité comme sensible, même vide, tronqué ou public. La
#:    mesure sur l'image réelle donne aujourd'hui zéro correspondance, donc
#:    zéro faux positif ; le jour où un ``.key`` légitime apparaîtra, il
#:    faudra une décision explicite plutôt qu'un silence.
_CREDENTIAL_SCAN_SH = r"""
grep -rIlE '^[[:space:]]*-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY-----[[:space:]]*$' / \
    --exclude-dir=proc --exclude-dir=sys 2>/dev/null \
| while IFS= read -r candidate; do
    awk '
      {
          line = $0
          sub(/\r$/, "", line)
          sub(/[ \t]+$/, "", line)
          bare = line
          sub(/^[ \t]+/, "", bare)
      }
      bare ~ /^-----BEGIN ([A-Z0-9]+ )*PRIVATE KEY-----$/ {
          endmark = bare
          sub(/^-----BEGIN /, "-----END ", endmark)
          inblock = 1
          payload = 0
          strong = 0
          next
      }
      inblock == 1 {
          if (bare == endmark) {
              if (strong >= 1) { print FILENAME; exit 0 }
              inblock = 0
              payload = 0
              strong = 0
              next
          }
          if (bare ~ /^[A-Za-z0-9+\/]+={0,2}$/ && length(bare) >= 4) {
              payload = payload + 1
              if (length(bare) >= 16) { strong = strong + 1 }
              next
          }
          if (bare ~ /^[A-Za-z][A-Za-z0-9-]*: .+$/ || bare == "") {
              next
          }
          inblock = 0
          payload = 0
          strong = 0
      }
    ' "$candidate"
  done | head -40
find / -xdev -type f \( \
       -name '.env' -o -name '.netrc' -o -name '.pgpass' \
    -o -name 'nexus_github_token' \
    -o -name 'id_rsa' -o -name 'id_ed25519' -o -name 'id_ecdsa' -o -name 'id_dsa' \
    -o -name '*.p12' -o -name '*.pfx' -o -name '*.pkcs12' \
    -o -name '*.key' \
    \) 2>/dev/null | head -40
echo SCAN_DONE
"""


#: Plantation de fixtures DANS le conteneur, exécutée avant le scanner.
#:
#: Toutes les clés sont de VRAIES clés, engendrées ici même par
#: ``cryptography`` et détruites avec le conteneur : aucune n'entre dans le
#: dépôt, aucune n'est affichée (seuls les CHEMINS trouvés remontent). Elles
#: portent des noms banals et vivent dans ``site-packages``/``dist-packages``
#: — exactement les endroits qu'une exclusion de répertoire rendrait
#: invisibles et qu'une recherche par nom de fichier n'atteindrait jamais.
_PLANT_FIXTURES_SH = r"""
SP=$(python -c 'import site; print(site.getsitepackages()[0])')
DP=/usr/lib/python3/dist-packages
mkdir -p "$DP"
SP="$SP" DP="$DP" python - <<'PLANT_PY'
import os, pathlib, datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography import x509
from cryptography.x509.oid import NameOID

sp = pathlib.Path(os.environ["SP"])
dp = pathlib.Path(os.environ["DP"])
app = pathlib.Path("/app")
PEM, DER = serialization.Encoding.PEM, serialization.Encoding.DER
NOENC = serialization.NoEncryption()

ed = Ed25519PrivateKey.generate()
pkcs8 = ed.private_bytes(PEM, serialization.PrivateFormat.PKCS8, NOENC)

# --- vraies clés, noms banals ---
(app / "telemetry.dat").write_bytes(pkcs8)
(app / "settings.yaml").write_text(
    "service:\n  tls:\n    key: |\n"
    + "\n".join("      " + line for line in pkcs8.decode().splitlines())
    + "\n"
)
(sp / "legacy.conf").write_bytes(pkcs8.replace(b"\n", b"\r\n"))
(sp / "wheel-index.bin").write_bytes(
    ed.private_bytes(PEM, serialization.PrivateFormat.OpenSSH, NOENC)
)
(sp / "session.cache").write_bytes(
    ed.private_bytes(
        PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"ephemeral"),
    )
)
(sp / "blob.bin").write_bytes(
    ed.private_bytes(DER, serialization.PrivateFormat.PKCS8, NOENC)
)
rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
(sp / "innocent-data.bin").write_bytes(
    rsa_key.private_bytes(PEM, serialization.PrivateFormat.PKCS8, NOENC)
)
(dp / "cache.dat").write_bytes(
    rsa_key.private_bytes(PEM, serialization.PrivateFormat.TraditionalOpenSSL, NOENC)
)
ec_key = ec.generate_private_key(ec.SECP256R1())
(app / "metrics.tmp").write_bytes(
    b"-----BEGIN EC PARAMETERS-----\nBggqhkjOPQMBBw==\n-----END EC PARAMETERS-----\n"
    + ec_key.private_bytes(
        PEM, serialization.PrivateFormat.TraditionalOpenSSL, NOENC
    )
)

# --- leurres : rien de tout ceci n'est une clé privée ---
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "probe")])
cert = (
    x509.CertificateBuilder()
    .subject_name(name).issuer_name(name)
    .public_key(rsa_key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime(2026, 1, 1))
    .not_valid_after(datetime.datetime(2027, 1, 1))
    .sign(rsa_key, hashes.SHA256())
)
(app / "chain.pem").write_bytes(cert.public_bytes(PEM))
(app / "cert.der").write_bytes(cert.public_bytes(DER))
(app / "pub.pem").write_bytes(
    ed.public_key().public_bytes(PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
)
(app / "pub.ssh").write_bytes(
    ed.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
)
(sp / "ssh.py").write_text(
    '_SK_START = b"-----BEGIN OPENSSH PRIVATE KEY-----"\n'
    '_SK_END = b"-----END OPENSSH PRIVATE KEY-----"\n'
    'HEADER = "-----BEGIN PRIVATE KEY-----\\n"\n'
)
(app / "begin_only.pem").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nnothing\n")
(app / "empty_block.txt").write_text(
    "-----BEGIN RSA PRIVATE KEY-----\n-----END RSA PRIVATE KEY-----\n"
)
(app / "mismatched.txt").write_text(
    "-----BEGIN RSA PRIVATE KEY-----\nQUJDREVGR0hJSktMTU5PUA==\n"
    "-----END EC PRIVATE KEY-----\n"
)
(app / "fake_payload.txt").write_text(
    "-----BEGIN PRIVATE KEY-----\nthis is not base64 at all !!\n"
    "-----END PRIVATE KEY-----\n"
)
(sp / "random.bin").write_bytes(bytes(range(256)) * 8)

# Fichiers sensibles reconnus par leur NOM, déposés là où la recherche par
# CONTENU ne les verrait jamais. Vides : c'est le nom qui compte.
(sp / ".netrc").write_text("")

# Conteneur PKCS#12 : couvert par la recherche par NOM (le contenu est
# binaire et ne porte aucun marqueur PEM).
(dp / "keystore.p12").write_bytes(
    pkcs12.serialize_key_and_certificates(
        b"probe", rsa_key, cert, None, NOENC
    )
)
PLANT_PY
"""

def _run_credential_scan(worker_image: str, *, prelude: str = "") -> list[str]:
    """Exécute le scanner canonique dans l'image et rend les chemins trouvés.

    ``prelude`` permet de planter des fixtures — clés éphémères engendrées
    dans le conteneur, jamais dans le dépôt, jamais affichées : seuls les
    CHEMINS trouvés remontent, jamais le contenu d'un fichier."""
    result = _docker(
        "run", "--rm", "--entrypoint", "sh", worker_image,
        "-c", prelude + _CREDENTIAL_SCAN_SH,
        check=False,
    )
    return [
        line.strip()
        for line in result.stdout.replace("SCAN_DONE", "").splitlines()
        if line.strip()
    ]


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
        listed = _run_credential_scan(worker_image)
        assert listed == [], f"unexpected credential-like files in the image: {listed}"

    def test_the_credential_scan_detects_real_keys_under_banal_names(
        self, worker_image: str
    ) -> None:
        """Non-vacuité du garde-fou précédent, mesurée sur le MÊME scanner.

        Un scan de credentials qui ne trouve jamais rien est indistinguable
        d'un scan cassé. Ce test plante de **vraies** clés — engendrées dans
        le conteneur par ``cryptography``, éphémères, jamais journalisées —
        sous des noms banals, dans les zones que la recherche par nom de
        fichier n'atteindrait jamais, et exige que chacune soit trouvée.

        Les leurres sont l'autre moitié du contrat : constantes d'analyse,
        certificat public, clés publiques, bloc incomplet, marqueurs
        dépareillés, charge utile invraisemblable et binaire arbitraire
        doivent tous rester silencieux. Sans eux, il suffirait de tout
        signaler pour rendre ce test vert.
        """
        listed = _run_credential_scan(worker_image, prelude=_PLANT_FIXTURES_SH)
        joined = "\n".join(listed)

        must_find = {
            "/app/settings.yaml": "clé PKCS#8 INDENTÉE dans un YAML",
            "legacy.conf": "clé PKCS#8 en fins de ligne CRLF",
            "wheel-index.bin": "vraie clé OpenSSH (Encoding.PEM/PrivateFormat.OpenSSH)",
            "telemetry.dat": "clé PKCS#8 ed25519 (charge utile d'une seule ligne)",
            "innocent-data.bin": "clé PKCS#8 RSA dans site-packages",
            "cache.dat": "clé RSA traditionnelle dans dist-packages",
            "session.cache": "clé PKCS#8 chiffrée",
            "metrics.tmp": "clé EC précédée d'un bloc EC PARAMETERS",
            ".netrc": "fichier sensible trouvé par son NOM",
            "keystore.p12": "conteneur PKCS#12 trouvé par son NOM",
        }
        for needle, why in must_find.items():
            assert any(needle in item for item in listed), (
                f"the credential scan went blind on {needle!r} ({why}) — "
                f"output: {joined}"
            )

        must_ignore = {
            "ssh.py": "constante d'analyse, pas une clé",
            "chain.pem": "certificat public",
            "pub.pem": "clé PUBLIQUE PEM",
            "pub.ssh": "clé PUBLIQUE OpenSSH",
            "begin_only.pem": "BEGIN sans bloc complet",
            "empty_block.txt": "bloc sans charge utile",
            "mismatched.txt": "marqueurs BEGIN/END incompatibles",
            "fake_payload.txt": "charge utile invraisemblable",
            "random.bin": "binaire arbitraire",
        }
        for needle, why in must_ignore.items():
            assert not any(needle in item for item in listed), (
                f"{needle!r} ({why}) was reported — a scan that cries wolf gets "
                f"disabled. Output: {joined}"
            )

    def test_der_private_keys_are_a_known_limit_not_a_silent_gap(
        self, worker_image: str
    ) -> None:
        """Limite CONNUE et mesurée, pas un angle mort silencieux.

        Une clé DER est binaire : elle ne porte aucun marqueur PEM et
        ``grep -I`` l'écarte. La détecter exigerait de parser l'ASN.1 de
        chaque fichier binaire de l'image — un scanner d'une autre nature.
        Ce test fige l'état réel : la clé DER n'est PAS trouvée par contenu.
        Le jour où une détection DER sera ajoutée, il tombera et forcera la
        mise à jour de la documentation plutôt que de laisser croire à une
        couverture qui n'existe pas.

        Le garde-fou complémentaire est la recherche par NOM, qui couvre les
        conteneurs usuels (``.p12``/``.pfx``/``.pkcs12``) — vérifiée par le
        test précédent.
        """
        listed = _run_credential_scan(worker_image, prelude=_PLANT_FIXTURES_SH)
        assert not any("blob.bin" in item for item in listed), (
            "a DER private key is now detected by content — excellent, but the "
            "documented limit (DER_PRIVATE_KEY_DETECTION=false) must be updated"
        )
        assert not any("cert.der" in item for item in listed), (
            "a DER certificate must never be reported as a private key"
        )

    def test_conventional_ssh_key_names_are_detected_by_name_alone(
        self, worker_image: str
    ) -> None:
        """Les quatre noms conventionnels de clés SSH, détectés par leur NOM.

        Le contenu planté n'est délibérément **pas** une clé valide (vide,
        tronqué, binaire bénin) : si l'un de ces fichiers remonte, c'est
        nécessairement grâce à la recherche par nom, jamais grâce à la
        détection structurelle PEM. C'est exactement le trou que l'audit
        pré-commit a trouvé — `id_rsa` était couvert, `id_ed25519`,
        `id_ecdsa` et `id_dsa` ne l'étaient pas.

        Les variantes `.pub` portent de VRAIES clés publiques OpenSSH et
        doivent rester silencieuses : `-name 'id_rsa'` compare le nom de base
        entier, donc `id_rsa.pub` n'est pas `id_rsa`. Un motif global `id_*`
        aurait au contraire ramassé les `.pub` et n'importe quel fichier
        applicatif — d'où l'énumération explicite.
        """
        plant = (
            "python - <<'SSHNAMES_PY'\n"
            "import pathlib\n"
            "from cryptography.hazmat.primitives import serialization\n"
            "from cryptography.hazmat.primitives.asymmetric.ed25519 import "
            "Ed25519PrivateKey\n"
            "d = pathlib.Path('/root/.ssh'); d.mkdir(parents=True, exist_ok=True)\n"
            "# Contenus volontairement NON valides : seul le nom doit compter.\n"
            "(d / 'id_rsa').write_text('')\n"
            "(d / 'id_ed25519').write_text('-----BEGIN OPENSSH PRIVATE KEY-----\\n')\n"
            "(d / 'id_ecdsa').write_bytes(bytes(range(64)))\n"
            "(d / 'id_dsa').write_text('truncated, not a key\\n')\n"
            "# Variantes publiques : de VRAIES clés publiques OpenSSH.\n"
            "pub = Ed25519PrivateKey.generate().public_key().public_bytes(\n"
            "    serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH\n"
            ")\n"
            "for stem in ('id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa'):\n"
            "    (d / (stem + '.pub')).write_bytes(pub + b'\\n')\n"
            "# Fichiers applicatifs banals : aucun ne doit être signalé.\n"
            "app = pathlib.Path('/app')\n"
            "(app / 'id_token.py').write_text('ID_TOKEN = \"opaque\"\\n')\n"
            "(app / 'id_mapping.json').write_text('{\"a\": 1}\\n')\n"
            "(app / 'identity_provider.py').write_text('PROVIDER = \"local\"\\n')\n"
            "SSHNAMES_PY\n"
        )
        listed = _run_credential_scan(worker_image, prelude=plant)
        joined = "\n".join(listed)

        for name in ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"):
            assert any(item.endswith(f"/{name}") for item in listed), (
                f"{name!r} is a conventional SSH private key name but the "
                f"filename scan does not cover it — output: {joined}"
            )

        for name in ("id_rsa.pub", "id_ed25519.pub", "id_ecdsa.pub", "id_dsa.pub"):
            assert not any(item.endswith(f"/{name}") for item in listed), (
                f"{name!r} is a PUBLIC key and must never be reported — "
                f"output: {joined}"
            )

        for name in ("id_token.py", "id_mapping.json", "identity_provider.py"):
            assert not any(item.endswith(f"/{name}") for item in listed), (
                f"{name!r} is an ordinary application file — an 'id_*' glob "
                f"would have caught it. Output: {joined}"
            )

    def test_dot_key_extension_is_a_name_rule_not_a_content_classifier(
        self, worker_image: str
    ) -> None:
        """``*.key`` est une règle par NOM, assumée conservatrice.

        Elle ne cherche pas à classifier ce que le fichier contient : un
        ``.key`` vide, binaire ou même **public** est signalé. C'est
        délibéré — l'extension est une déclaration d'intention, et un
        ``.key`` légitime dans l'image doit faire l'objet d'une décision
        explicite plutôt que d'être ignoré en silence.

        Le revers est mesuré ici : la règle porte sur l'extension, pas sur
        la sous-chaîne « key ». ``/app/key`` (sans extension), ``monkey``,
        ``turkey.json`` et ``keyboard.py`` restent silencieux.
        """
        plant = (
            "python - <<'DOTKEY_PY'\n"
            "import pathlib\n"
            "from cryptography.hazmat.primitives import serialization\n"
            "from cryptography.hazmat.primitives.asymmetric.ed25519 import "
            "Ed25519PrivateKey\n"
            "app = pathlib.Path('/app')\n"
            "# Signalés par leur NOM, quel que soit le contenu.\n"
            "(app / 'service.key').write_text('')\n"
            "(app / 'cache.key').write_bytes(bytes(range(48)))\n"
            "(app / 'public.key').write_bytes(\n"
            "    Ed25519PrivateKey.generate().public_key().public_bytes(\n"
            "        serialization.Encoding.OpenSSH,\n"
            "        serialization.PublicFormat.OpenSSH,\n"
            "    )\n"
            ")\n"
            "# Non signalés : la règle vise l'EXTENSION, pas la sous-chaine.\n"
            "(app / 'key').write_text('not a key file\\n')\n"
            "(app / 'monkey').write_text('primate\\n')\n"
            "(app / 'turkey.json').write_text('{\"bird\": true}\\n')\n"
            "(app / 'keyboard.py').write_text('LAYOUT = \"azerty\"\\n')\n"
            "DOTKEY_PY\n"
        )
        listed = _run_credential_scan(worker_image, prelude=plant)
        joined = "\n".join(listed)

        for name, why in (
            ("service.key", "vide"),
            ("cache.key", "octets binaires bénins"),
            ("public.key", "clé PUBLIQUE — signalée par politique conservatrice"),
        ):
            assert any(item.endswith(f"/{name}") for item in listed), (
                f"{name!r} ({why}) must be reported: *.key is a name rule, and "
                f"the rule judges the name, never the content. Output: {joined}"
            )

        for name in ("key", "monkey", "turkey.json", "keyboard.py"):
            assert not any(item.endswith(f"/{name}") for item in listed), (
                f"{name!r} does not carry the .key extension — the rule must not "
                f"degrade into a 'key' substring match. Output: {joined}"
            )

    def test_parser_constants_are_not_reported_as_keys(
        self, worker_image: str
    ) -> None:
        """``cryptography`` sait *analyser* les clés OpenSSH : son source
        porte ``_SK_START = b"-----BEGIN OPENSSH PRIVATE KEY-----"``. Un
        analyseur n'est pas une clé. C'est le faux positif qui a motivé la
        détection structurelle — il est mesuré ici plutôt que contourné par
        une exclusion de répertoire."""
        probe = _docker(
            "run", "--rm", "--entrypoint", "sh", worker_image, "-c",
            "python -c \"import cryptography.hazmat.primitives.serialization.ssh as m; "
            "print(m.__file__)\" 2>/dev/null || true; echo PROBE_DONE",
            check=False,
        )
        source = probe.stdout.replace("PROBE_DONE", "").strip()
        if not source:
            pytest.skip("cryptography is not installed in this image")
        assert "_SK_START" in _docker(
            "run", "--rm", "--entrypoint", "sh", worker_image, "-c",
            f"grep -c '_SK_START' {source} >/dev/null && echo _SK_START",
            check=False,
        ).stdout, "the probe did not find the parser constant it claims to test"

        listed = _run_credential_scan(worker_image)
        assert not any(source in item for item in listed), (
            f"{source} is parser source, not key material, but the scan reported it"
        )

    def test_the_content_scan_covers_every_sensitive_zone(
        self, worker_image: str
    ) -> None:
        """Couverture explicite : /app, /root, /home et /etc restent
        fouillés par CONTENU. Une régression qui exclurait l'une de ces
        zones passerait inaperçue sans ce test."""
        plant = (
            "python - <<'ZONE_PY'\n"
            "import pathlib\n"
            "from cryptography.hazmat.primitives import serialization\n"
            "from cryptography.hazmat.primitives.asymmetric.ed25519 import "
            "Ed25519PrivateKey\n"
            "pem = Ed25519PrivateKey.generate().private_bytes(\n"
            "    serialization.Encoding.PEM,\n"
            "    serialization.PrivateFormat.PKCS8,\n"
            "    serialization.NoEncryption(),\n"
            ")\n"
            "for zone in ('/app', '/root', '/home', '/etc'):\n"
            "    d = pathlib.Path(zone); d.mkdir(parents=True, exist_ok=True)\n"
            "    (d / 'zone-probe.dat').write_bytes(pem)\n"
            "ZONE_PY\n"
        )
        listed = _run_credential_scan(worker_image, prelude=plant)
        for zone in ("/app", "/root", "/home", "/etc"):
            assert any(item.startswith(f"{zone}/zone-probe.dat") for item in listed), (
                f"the content scan no longer covers {zone} — output: {listed}"
            )

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
