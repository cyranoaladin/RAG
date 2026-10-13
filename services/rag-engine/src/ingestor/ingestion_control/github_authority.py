"""Adaptateur GitHub en lecture seule pour les autorités LOT41A/LOT42.

Remédiation revue GATE H1 (items I et J).

**Pourquoi ce module remplace le transport ``gh``** — l'image
``Dockerfile.ingestion-worker`` est volontairement minimale et ne contient
aucun binaire ``gh`` : le transport précédent (sous-processus ``gh api``)
n'aurait donc jamais fonctionné dans l'image réellement déployée, et
installer/épingler ``gh`` y ajouterait une surface non auditée pour trois
requêtes HTTP GET. Ce module effectue ces requêtes directement via
``httpx`` (déjà une dépendance du worker — aucune dépendance nouvelle).

**Ce module ne crée AUCUNE frontière de confiance parallèle.** La décision
d'autorité elle-même reste exactement celle d'ADR-0025/LOT41V : la fonction
pure ``trusted_human_review.evaluate_trusted_review`` (racine du dépôt,
``scripts/github/``, **non modifiée**) est chargée et appelée telle quelle,
avec la même ``trusted-reviewers.json``, les mêmes challenges canoniques et
les mêmes règles de rejet. Seul le *transport* change (HTTP direct au lieu
de ``gh api``) ; la sémantique d'autorité, elle, est partagée à l'octet
près. Toute divergence future de cette fonction s'applique donc
automatiquement ici.

Propriétés de sécurité imposées :

- **Lecture seule** : uniquement des ``GET``. Aucune méthode mutante n'est
  atteignable — la seule fonction de transport n'accepte pas de verbe.
- **Aucun secret journalisé** : le jeton n'apparaît jamais dans un message
  d'erreur, une exception, ou une trace (les en-têtes ne sont jamais
  inclus dans les diagnostics).
- **Jamais dans l'image** : le jeton est lu à l'exécution depuis
  ``NEXUS_GITHUB_TOKEN`` ou, préférablement, depuis le fichier désigné par
  ``NEXUS_GITHUB_TOKEN_FILE`` (montage de secret) — jamais construit dans
  l'image, jamais commité.
- **Délai total borné** (item J) : chaque requête a son propre timeout
  *et* l'opération complète porte une échéance globale
  (``NEXUS_GITHUB_TOTAL_TIMEOUT_S``, défaut 30 s). Une panne GitHub fait
  donc échouer la vérification **fail-closed en temps borné**, sans jamais
  bloquer indéfiniment un worker ni consommer sa capacité.
"""
from __future__ import annotations

import base64
import copy
import importlib.util
import os
import re
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from nexus_contracts.authority_artifacts import git_blob_sha1

#: services/rag-engine/src/ingestor/ingestion_control/github_authority.py ->
#: racine du dépôt (cinq niveaux au-dessus). Jamais un chemin absolu
#: machine-local (AGENTS.md).
#:
#: Cette profondeur n'existe PAS dans l'image Docker aplatie, où ce fichier
#: vit sous ``/app/ingestion_control/`` — soit deux niveaux seulement.
#: Calculer ``parents[5]`` au moment de l'import y levait ``IndexError``
#: **avant même** que les surcharges d'environnement du Dockerfile puissent
#: servir : toute vérification d'autorité échouait dans l'image réellement
#: déployée, alors qu'elle passait en développement. Détecté par le E2E
#: Docker (item I) — invisible depuis ruff, mypy et les tests unitaires.
#: La résolution est donc paresseuse et tolère une arborescence courte.
_REPO_ROOT_DEPTH = 5
_TRUSTED_REVIEW_MODULE_ENV = "NEXUS_TRUSTED_REVIEW_MODULE"
_TRUSTED_REVIEWERS_CONFIG_ENV = "NEXUS_TRUSTED_REVIEWERS_CONFIG"

_TOKEN_ENV = "NEXUS_GITHUB_TOKEN"
_TOKEN_FILE_ENV = "NEXUS_GITHUB_TOKEN_FILE"
_API_BASE_ENV = "NEXUS_GITHUB_API_BASE"
_TOTAL_TIMEOUT_ENV = "NEXUS_GITHUB_TOTAL_TIMEOUT_S"
_REQUEST_TIMEOUT_ENV = "NEXUS_GITHUB_REQUEST_TIMEOUT_S"

_DEFAULT_API_BASE = "https://api.github.com"
#: Même version d'API que l'adaptateur ``gh`` d'ADR-0025 — jamais une autre.
_GH_API_VERSION = "2026-03-10"
_DEFAULT_TOTAL_TIMEOUT_S = 30.0
_DEFAULT_REQUEST_TIMEOUT_S = 10.0
_PAGE_SIZE = 100
_MAX_REVIEW_PAGES = 20
#: Plafond de taille d'un artefact d'autorité relu depuis GitHub — un blob
#: anormalement gros est rejeté avant tout décodage, jamais chargé en
#: mémoire sans borne.
_MAX_BLOB_BYTES = 1_048_576
_BLOB_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class _JobReadCache:
    """HTTP snapshot confined to one Worker B job, never an authority.

    The first verification is live. Intermediate checkpoints still execute
    all parsers and DB/revocation checks against the same external snapshot.
    The publisher disables this cache before its final live verification in
    the product transaction. No response survives the job or a failed call.
    """

    def __init__(self) -> None:
        self.responses: dict[str, Any] = {}
        self.enabled = True
        self.serve_cached = False

    def activate(self) -> None:
        # Only after the complete LOT42 and LOT41A proof has passed. During
        # the first verification, duplicate GETs of the PR must remain live
        # to preserve the existing head/base TOCTOU check.
        if self.enabled:
            self.serve_cached = True

    def disable(self) -> None:
        self.responses.clear()
        self.enabled = False


_JOB_READ_CACHE: ContextVar[_JobReadCache | None] = ContextVar(
    "nexus_github_job_read_cache", default=None,
)


@contextmanager
def job_github_read_cache() -> Iterator[None]:
    """Keep successful GET responses only within one publication iteration."""
    token = _JOB_READ_CACHE.set(_JobReadCache())
    try:
        yield
    finally:
        _JOB_READ_CACHE.reset(token)


def force_live_github_reads() -> None:
    """Make every subsequent GET live before the product commit."""
    cache = _JOB_READ_CACHE.get()
    if cache is not None:
        cache.disable()


def activate_job_github_read_cache() -> None:
    """Reuse a fully verified first snapshot at intermediate checkpoints."""
    cache = _JOB_READ_CACHE.get()
    if cache is not None:
        cache.activate()


class GitHubAuthorityError(RuntimeError):
    """Échec de transport, d'authentification, de forme, ou dépassement de
    l'échéance globale. Ne contient jamais le jeton."""


class GitHubAuthorityTimeoutError(GitHubAuthorityError):
    """L'échéance globale a été atteinte — fail-closed en temps borné
    (item J), jamais une attente indéfinie."""


class GitHubRateLimitedError(GitHubAuthorityError):
    """GitHub a limité le débit (lot DI) — refus, jamais une approbation.

    Sous-classe de ``GitHubAuthorityError`` : tout appelant existant, qui ne
    connaît que la classe mère, continue d'échouer fermé exactement comme
    avant. Seul un appelant qui sait RALENTIR (Worker B) lit en plus le délai
    d'attente. Aucune attente n'a lieu ici : dormir dans la vérification
    tiendrait le bail du job et les verrous de la migration 010.

    ``retry_after_s`` est le délai minimal avant tout nouvel appel, dérivé
    des seuls en-têtes documentés par GitHub (``Retry-After``, sinon
    ``x-ratelimit-reset`` quand ``x-ratelimit-remaining`` vaut 0), ou
    ``None`` si GitHub n'en donne aucun (l'appelant applique alors son
    propre plancher)."""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        retry_after_s: float | None,
        diagnostics: GitHubResponseDiagnostics,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after_s = retry_after_s
        self.diagnostics = diagnostics


#: En-têtes de limitation documentés par GitHub. Aucun autre en-tête n'est
#: jamais recopié dans un diagnostic : ceux de la REQUÊTE (dont
#: ``Authorization``) n'y figurent donc jamais.
_DIAGNOSTIC_HEADERS = (
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-ratelimit-used",
    "x-ratelimit-resource",
    "x-github-request-id",
)
_SAFE_HEADER_VALUE = re.compile(r"\A[0-9A-Za-z:._-]{1,64}\Z")
_MAX_SAFE_MESSAGE_CHARS = 200
_RATE_LIMIT_MESSAGE = re.compile(r"rate limit", re.IGNORECASE)


@dataclass(frozen=True)
class GitHubResponseDiagnostics:
    """Faits sûrs d'une réponse GitHub non-200 : statut, en-têtes de
    limitation, et champ ``message`` du corps JSON, borné et filtré.

    Jamais un en-tête de requête, jamais le corps brut, jamais le jeton."""

    status: int
    headers: tuple[tuple[str, str], ...]
    message: str | None

    def header(self, name: str) -> str | None:
        return dict(self.headers).get(name)

    def render(self) -> str:
        parts = [f"{name}={value}" for name, value in self.headers]
        if self.message is not None:
            parts.append(f"message={self.message!r}")
        return "; ".join(parts)


def _safe_message(response: httpx.Response, token: str) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str):
        return None
    cleaned = "".join(ch for ch in message if ch.isprintable())[:_MAX_SAFE_MESSAGE_CHARS]
    # Défense en profondeur : GitHub ne renvoie pas le jeton, mais un
    # diagnostic n'a jamais le droit de le recopier s'il le faisait.
    return cleaned.replace(token, "[redacted]") if token else cleaned


def _diagnostics(response: httpx.Response, token: str) -> GitHubResponseDiagnostics:
    headers = tuple(
        (name, value)
        for name in _DIAGNOSTIC_HEADERS
        if (value := response.headers.get(name)) is not None
        and _SAFE_HEADER_VALUE.fullmatch(value)
        and (not token or token not in value)
    )
    return GitHubResponseDiagnostics(
        status=response.status_code, headers=headers, message=_safe_message(response, token)
    )


def _rate_limit(
    diagnostics: GitHubResponseDiagnostics, *, now_epoch: float
) -> tuple[str, float | None] | None:
    """Classification d'une réponse non-200 : ``(nature, attente)`` si c'est
    une limitation de débit, ``None`` sinon.

    Règles, dans l'ordre documenté par GitHub :

    - ``Retry-After`` présent (403 ou 429) : limitation, attente imposée ;
    - ``x-ratelimit-remaining: 0`` : quota primaire épuisé, attente jusqu'à
      ``x-ratelimit-reset`` ;
    - 429 sans en-tête, ou 403 dont le message GitHub nomme une limitation
      de débit : limitation secondaire, sans délai fourni.

    Un autre 403 (droits, jeton révoqué, SSO) n'est PAS une limitation : il
    reste un refus ordinaire. Ralentir ne le corrigerait pas, et l'étiqueter
    « limitation » masquerait sa vraie cause."""
    if diagnostics.status not in (403, 429):
        return None
    retry_after = diagnostics.header("retry-after")
    if retry_after is not None and retry_after.isdigit():
        return "secondary", float(retry_after)
    if diagnostics.header("x-ratelimit-remaining") == "0":
        reset = diagnostics.header("x-ratelimit-reset")
        wait = max(0.0, float(reset) - now_epoch) if reset and reset.isdigit() else None
        return "primary", wait
    if diagnostics.status == 429 or _RATE_LIMIT_MESSAGE.search(diagnostics.message or ""):
        return "secondary", None
    return None


def _default_repo_root() -> Path | None:
    """Racine du dépôt si ce fichier vit dans un checkout complet, ``None``
    dans l'image aplatie. ``None`` n'est pas une erreur : l'image fournit
    toujours les surcharges explicites, et un défaut absent y est plus sûr
    qu'un chemin deviné."""
    here = Path(__file__).resolve()
    if len(here.parents) <= _REPO_ROOT_DEPTH:
        return None
    return here.parents[_REPO_ROOT_DEPTH]


def _resolve_shared_path(env_var: str, relative: str) -> Path:
    """Surcharge d'environnement d'abord (image aplatie), défaut dérivé du
    checkout ensuite. Si aucune des deux ne s'applique, l'erreur est
    explicite — jamais un chemin inventé."""
    override = os.environ.get(env_var, "").strip()
    if override:
        return Path(override)
    root = _default_repo_root()
    if root is None:
        raise GitHubAuthorityError(
            f"{env_var} must be set: this build has no repository checkout to "
            f"derive {relative} from, and an authority decision is never "
            "loaded from a guessed path"
        )
    return root / relative


def _load_trusted_review_module() -> Any:
    """Charge la fonction de décision pure d'ADR-0025 par chemin de fichier.

    Même motif que ``scripts/tests/test-trusted-human-review-github.py``
    (importlib depuis un chemin) : ``scripts/github/`` n'est pas un paquet
    installable et n'appartient à aucun service — il n'est donc jamais
    importé par un ``import`` ordinaire, jamais copié/dupliqué non plus."""
    module_path = _resolve_shared_path(
        _TRUSTED_REVIEW_MODULE_ENV, "scripts/github/trusted_human_review.py"
    )
    if not module_path.is_file():
        raise GitHubAuthorityError(
            f"trusted_human_review.py not found at {module_path} — the shared "
            "ADR-0025 decision function is required and is never reimplemented here"
        )
    spec = importlib.util.spec_from_file_location("nexus_trusted_human_review", module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - chemin vérifié ci-dessus
        raise GitHubAuthorityError(f"cannot load trusted_human_review.py from {module_path}")
    cached = sys.modules.get(spec.name)
    if cached is not None:
        return cached
    module = importlib.util.module_from_spec(spec)
    # ``sys.modules[spec.name] = module`` AVANT ``exec_module`` n'est pas
    # cosmétique : ``@dataclass`` (utilisé par TrustedReviewerConfig et
    # TrustedReviewDecision) résout ``cls.__module__`` via ``sys.modules`` et
    # lève ``AttributeError: 'NoneType' object has no attribute '__dict__'``
    # si le module n'y figure pas encore. Sans cette ligne, TOUTE vérification
    # d'autorité échouait au premier chargement — détecté en exerçant la
    # fonction réelle, jamais visible depuis mypy/ruff.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _trusted_reviewers_config_path() -> Path:
    return _resolve_shared_path(
        _TRUSTED_REVIEWERS_CONFIG_ENV, "scripts/github/trusted-reviewers.json"
    )


def _read_token() -> str:
    """Jeton lu à l'exécution uniquement. ``NEXUS_GITHUB_TOKEN_FILE`` est
    préféré (montage de secret : jamais dans l'environnement du processus,
    donc jamais exposé par ``/proc/<pid>/environ`` à un autre processus du
    même utilisateur)."""
    token_file = os.environ.get(_TOKEN_FILE_ENV, "").strip()
    if token_file:
        path = Path(token_file)
        if not path.is_file():
            raise GitHubAuthorityError(
                f"{_TOKEN_FILE_ENV} points to {path} which is not a readable file"
            )
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise GitHubAuthorityError(f"{_TOKEN_FILE_ENV} file is empty")
        return token
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        raise GitHubAuthorityError(
            f"no GitHub read credential configured: set {_TOKEN_FILE_ENV} "
            f"(preferred) or {_TOKEN_ENV} — verification fails closed without one"
        )
    return token


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise GitHubAuthorityError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise GitHubAuthorityError(f"{name} must be strictly positive, got {value}")
    return value


@dataclass
class _Deadline:
    """Échéance globale monotone (item J) — indépendante de l'horloge murale."""

    total_timeout_s: float
    started_at: float

    @classmethod
    def start(cls, total_timeout_s: float) -> _Deadline:
        return cls(total_timeout_s=total_timeout_s, started_at=time.monotonic())

    def remaining(self) -> float:
        return self.total_timeout_s - (time.monotonic() - self.started_at)

    def check(self, operation: str) -> float:
        left = self.remaining()
        if left <= 0:
            raise GitHubAuthorityTimeoutError(
                f"global GitHub verification deadline of {self.total_timeout_s}s "
                f"exceeded before {operation} — failing closed"
            )
        return left


class _ReadOnlyGitHubClient:
    """Client HTTP strictement GET. Aucun verbe mutant n'est exposé."""

    def __init__(self, *, token: str, api_base: str, request_timeout_s: float) -> None:
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._request_timeout_s = request_timeout_s
        self._client = httpx.Client(
            timeout=httpx.Timeout(request_timeout_s),
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": _GH_API_VERSION,
                "User-Agent": "nexus-rag-engine-authority/1",
            },
        )

    def __enter__(self) -> _ReadOnlyGitHubClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._client.close()

    def get_json(self, path: str, *, deadline: _Deadline) -> Any:
        remaining = deadline.check(f"GET {path}")
        url = f"{self._api_base}/{path.lstrip('/')}"
        cache = _JOB_READ_CACHE.get()
        if (cache is not None and cache.enabled and cache.serve_cached
                and url in cache.responses):
            return copy.deepcopy(cache.responses[url])
        try:
            response = self._client.get(
                url, timeout=httpx.Timeout(min(self._request_timeout_s, remaining))
            )
        except httpx.TimeoutException:
            # Jamais l'exception brute : elle peut porter l'URL complète, et
            # l'on ne veut aucun risque de fuite d'en-tête dans les traces.
            raise GitHubAuthorityTimeoutError(
                f"timeout while fetching {path} — failing closed"
            ) from None
        except httpx.HTTPError as exc:
            raise GitHubAuthorityError(
                f"transport error while fetching {path}: {type(exc).__name__}"
            ) from None
        if response.status_code != 200:
            # Lot DI : le statut seul ne permettait pas de distinguer une
            # limitation de débit d'un refus de droits. Les en-têtes de
            # limitation et le message GitHub, filtrés, sont désormais
            # conservés — jamais un en-tête de requête, jamais le jeton.
            diagnostics = _diagnostics(response, self._token)
            message = (
                f"GitHub returned HTTP {response.status_code} for {path} — failing closed"
                + (f" [{diagnostics.render()}]" if diagnostics.render() else "")
            )
            limitation = _rate_limit(diagnostics, now_epoch=time.time())
            if limitation is not None:
                kind, retry_after_s = limitation
                raise GitHubRateLimitedError(
                    f"{message} (rate_limited={kind})",
                    kind=kind,
                    retry_after_s=retry_after_s,
                    diagnostics=diagnostics,
                )
            raise GitHubAuthorityError(message)
        try:
            payload = response.json()
        except ValueError:
            raise GitHubAuthorityError(f"GitHub returned malformed JSON for {path}") from None
        if cache is not None and cache.enabled:
            if len(cache.responses) >= 64 and url not in cache.responses:
                raise GitHubAuthorityError("job GitHub read cache exceeded its bound")
            cache.responses[url] = copy.deepcopy(payload)
        return payload


def _collect_reviews(
    client: _ReadOnlyGitHubClient, *, repository: str, pull_request: int, deadline: _Deadline
) -> tuple[list[Any], bool]:
    reviews: list[Any] = []
    for page in range(1, _MAX_REVIEW_PAGES + 1):
        payload = client.get_json(
            f"repos/{repository}/pulls/{pull_request}/reviews"
            f"?per_page={_PAGE_SIZE}&page={page}",
            deadline=deadline,
        )
        if not isinstance(payload, list):
            raise GitHubAuthorityError("reviews response is not a JSON list")
        reviews.extend(payload)
        if len(payload) < _PAGE_SIZE:
            return reviews, True
    return reviews, False


#: Le contexte requis par la protection de branche. Le scellement refuse
#: tout autre nom : un contexte homonyme ne serait pas celui-là.
HEAD_PINNED_CONTEXT = "trusted-human-review/head-pinned"


@dataclass(frozen=True)
class ReviewVerification:
    """Résultat d'une vérification live. ``decision`` est le
    ``TrustedReviewDecision`` d'ADR-0025 converti en dict, sans
    réinterprétation."""

    approved: bool
    reason: str
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    reviewer: str | None
    review_id: int | None
    submitted_at: str | None
    challenge: str | None
    #: Faits complémentaires nécessaires au SCELLEMENT (ADR-0058).
    #:
    #: ``TrustedReviewDecision`` porte le verdict ; il ne porte ni l'auteur,
    #: ni la ``base_ref``, ni le ``node_id`` de la revue, ni le statut du
    #: contexte de protection. Ils sont dérivés ici, des documents que
    #: ``verify_review`` a DÉJÀ lus — plutôt qu'en élargissant le contrat de
    #: décision d'ADR-0025, ou en ajoutant un second aller-retour.
    author: str | None = None
    base_ref: str | None = None
    review_node_id: str | None = None
    head_pinned_status: str | None = None
    head_pinned_context: str = HEAD_PINNED_CONTEXT


def load_trusted_reviewers() -> tuple[str, ...]:
    """L'allowlist gouvernée des relecteurs — **sans aucun accès réseau**.

    ``verify_review`` lit la même configuration, mais pour une décision
    live. Celle-ci sert à la vérification d'une preuve scellée (ADR-0058) :
    la revue a déjà eu lieu, seule l'habilitation du signataire reste à
    confronter à l'allowlist courante."""
    trusted_review = _load_trusted_review_module()
    config = trusted_review.load_config(_trusted_reviewers_config_path())
    return tuple(config.reviewers)


def verify_review(
    *, repository: str, pull_request: int, expected_head: str,
    verified_merged_binding: tuple[str, str, str, int, str, str] | None = None,
    verified_c_at_utc: datetime | None = None,
) -> ReviewVerification:
    """Vérifie en direct, en lecture seule et en temps borné, qu'une review
    humaine ``APPROVED`` d'ADR-0025 existe sur ``expected_head`` exact.

    La décision est rendue par la fonction pure partagée
    ``evaluate_trusted_review`` — jamais par ce module. Le mode historique
    est réservé à un binding déjà recomposé par C depuis un reçu de PR
    fusionnée ; sans ce binding, une PR fermée reste refusée."""
    trusted_review = _load_trusted_review_module()
    config = trusted_review.load_config(_trusted_reviewers_config_path())

    if repository != config.repository:
        raise GitHubAuthorityError(
            "repository does not match the trusted reviewer configuration"
        )

    deadline = _Deadline.start(_float_env(_TOTAL_TIMEOUT_ENV, _DEFAULT_TOTAL_TIMEOUT_S))
    request_timeout = _float_env(_REQUEST_TIMEOUT_ENV, _DEFAULT_REQUEST_TIMEOUT_S)

    with _ReadOnlyGitHubClient(
        token=_read_token(), api_base=_api_base(), request_timeout_s=request_timeout
    ) as client:
        pull_request_doc = client.get_json(
            f"repos/{repository}/pulls/{pull_request}", deadline=deadline
        )
        reviewed_pr = pull_request_doc
        if verified_merged_binding is not None:
            binding = verified_merged_binding
            head = pull_request_doc.get("head") if isinstance(pull_request_doc, dict) else None
            base = pull_request_doc.get("base") if isinstance(pull_request_doc, dict) else None
            if (
                not isinstance(binding, tuple) or len(binding) != 6
                or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None
                       for value in binding[:3])
                or type(binding[3]) is not int or binding[3] <= 0
                or not isinstance(binding[4], str)
                or re.fullmatch(r"NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}", binding[4]) is None
                or not isinstance(binding[5], str) or not binding[5]
                or not isinstance(head, dict) or not isinstance(base, dict)
                or pull_request_doc.get("number") != pull_request
                or head.get("sha") != expected_head or head.get("sha") != binding[1]
                or base.get("ref") != config.base_ref
            ):
                raise GitHubAuthorityError("merged review PR differs from C binding")
            if pull_request_doc.get("state") == "closed":
                # The pinned REST API version may omit merge_commit_sha on
                # an already merged PR. C independently verified and sealed
                # that SHA in its historical receipt; the live state, merge
                # time and C-after-merge ordering remain mandatory here.
                merge_sha = pull_request_doc.get("merge_commit_sha")
                try:
                    merged_at = datetime.fromisoformat(
                        str(pull_request_doc.get("merged_at")).replace("Z", "+00:00")
                    )
                except ValueError as exc:
                    raise GitHubAuthorityError("historical LOT42 merge time invalid") from exc
                if (
                    pull_request_doc.get("merged") is not True
                    or (merge_sha is not None and (
                        not isinstance(merge_sha, str)
                        or re.fullmatch(r"[0-9a-f]{40}", merge_sha) is None
                    ))
                    or verified_c_at_utc is None
                    or verified_c_at_utc.tzinfo is None
                    or merged_at.tzinfo is None
                    or merged_at.utcoffset() != timedelta(0)
                    or verified_c_at_utc.utcoffset() != timedelta(0)
                    or verified_c_at_utc > datetime.now(UTC)
                    or not merged_at.astimezone(UTC) <= verified_c_at_utc.astimezone(UTC)
                ):
                    raise GitHubAuthorityError("historical LOT42 merge was not covered by C")
                reviewed_pr = {
                    **pull_request_doc,
                    "state": "open", "draft": False,
                    "base": {**base, "sha": binding[0]},
                }
        reviews, reviews_complete = _collect_reviews(
            client, repository=repository, pull_request=pull_request, deadline=deadline
        )
        reviewers = list(config.reviewers)
        permissions: dict[str, Any] = {}
        for reviewer in reviewers:
            permissions[reviewer] = client.get_json(
                f"repos/{repository}/collaborators/{reviewer}/permission", deadline=deadline
            )

        decision = trusted_review.evaluate_trusted_review(
            pull_request=reviewed_pr,
            reviews=reviews,
            permissions=permissions,
            config=config,
            reviews_complete=reviews_complete,
        )

        # Même garde que l'adaptateur ``gh`` d'ADR-0025 : relire la PR après
        # l'évaluation et refuser si head/base a bougé pendant celle-ci —
        # jamais une décision rendue sur un état déjà périmé.
        final_doc = client.get_json(
            f"repos/{repository}/pulls/{pull_request}", deadline=deadline
        )
        # Le contexte requis de la protection de branche, sur ce head exact.
        # Sceller une revue dont la porte n'était pas passée scellerait un
        # fait qui n'a pas eu lieu (ADR-0058).
        #
        # Cette lecture est délibérément NON FATALE. Elle a été ajoutée à une
        # fonction dont tous les appelants existants attendent un verdict de
        # revue : la faire échouer transformerait un refus propre — « PR
        # fermée », « revue retirée » — en erreur de transport, et masquerait
        # la vraie raison. Un statut indisponible laisse donc
        # ``head_pinned_status`` à None, et c'est le SCELLEMENT qui refuse,
        # avec son propre message.
        try:
            statut = client.get_json(
                f"repos/{repository}/commits/{_revision(pull_request_doc)[0]}/status",
                deadline=deadline,
            )
        except GitHubAuthorityError:
            statut = {}

    if (_revision(final_doc) != _revision(pull_request_doc)
            or (verified_merged_binding is not None and isinstance(pull_request_doc, dict)
                and isinstance(final_doc, dict) and any(
                    final_doc.get(field) != pull_request_doc.get(field)
                    for field in (
                        "number", "state", "merged", "merged_at",
                        "merge_commit_sha", "user",
                    )
                ))):
        return ReviewVerification(
            approved=False,
            reason="head_or_base_changed_during_evaluation",
            repository=repository,
            pull_request=pull_request,
            base_sha=str(_revision(pull_request_doc)[1]),
            head_sha=str(_revision(pull_request_doc)[0]),
            reviewer=None,
            review_id=None,
            submitted_at=None,
            challenge=None,
        )

    node_id = next(
        (
            str(review.get("node_id"))
            for review in reviews
            if decision.review_id is not None
            and review.get("id") == decision.review_id
            and review.get("node_id")
        ),
        None,
    )

    verification = ReviewVerification(
        approved=bool(decision.approved),
        reason=str(decision.reason),
        repository=str(decision.repository),
        pull_request=int(decision.pull_request),
        base_sha=str(decision.base_sha),
        head_sha=str(decision.head_sha),
        reviewer=decision.reviewer,
        review_id=decision.review_id,
        submitted_at=decision.submitted_at,
        challenge=decision.challenge,
        author=str((pull_request_doc.get("user") or {}).get("login") or "") or None,
        base_ref=str((pull_request_doc.get("base") or {}).get("ref") or "") or None,
        review_node_id=node_id,
        head_pinned_status=_latest_head_pinned_status(statut),
    )

    # Liaison au head attendu : la décision d'ADR-0025 porte déjà sur le
    # head courant de la PR ; ce module refuse en plus toute divergence avec
    # le head que l'appelant croyait vérifier (rejeu d'une évidence périmée).
    if verification.approved and verification.head_sha != expected_head:
        return ReviewVerification(
            approved=False,
            reason="expected_head_mismatch",
            repository=verification.repository,
            pull_request=verification.pull_request,
            base_sha=verification.base_sha,
            head_sha=verification.head_sha,
            reviewer=None,
            review_id=None,
            submitted_at=None,
            challenge=None,
        )
    if verified_merged_binding is not None and (
        not verification.approved
        or verification.base_sha != verified_merged_binding[0]
        or verification.head_sha != verified_merged_binding[1]
        or verification.review_id != verified_merged_binding[3]
        or verification.challenge != verified_merged_binding[4]
        or verification.reviewer != verified_merged_binding[5]
        or verification.head_pinned_status != "success"
    ):
        return ReviewVerification(
            approved=False, reason="merged_review_differs_from_c",
            repository=repository, pull_request=pull_request,
            base_sha=verification.base_sha, head_sha=verification.head_sha,
            reviewer=None, review_id=None, submitted_at=None, challenge=None,
        )
    return verification


def _api_base() -> str:
    return os.environ.get(_API_BASE_ENV, "").strip() or _DEFAULT_API_BASE


def _revision(pull_request_doc: Any) -> tuple[str, str, str]:
    if not isinstance(pull_request_doc, dict):
        raise GitHubAuthorityError("pull request response is not a JSON object")
    head = pull_request_doc.get("head")
    base = pull_request_doc.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise GitHubAuthorityError("pull request head/base is malformed")
    return (str(head.get("sha")), str(base.get("sha")), str(base.get("ref")))


def _latest_head_pinned_status(status_document: Any) -> str | None:
    """Select the newest matching status; ambiguous chronology refuses."""
    rows = status_document.get("statuses") if isinstance(status_document, dict) else None
    if not isinstance(rows, list):
        return None
    candidates: list[tuple[datetime, int, str]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("context") != HEAD_PINNED_CONTEXT:
            continue
        stamp = row.get("created_at")
        identity = row.get("id")
        state = row.get("state")
        if (not isinstance(stamp, str) or type(identity) is not int
                or identity <= 0 or not isinstance(state, str)):
            return None
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return None
        if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
            return None
        candidates.append((moment, identity, state))
    if not candidates:
        return None
    newest = max((moment, identity) for moment, identity, _state in candidates)
    states = {state for moment, identity, state in candidates
              if (moment, identity) == newest}
    return next(iter(states)) if len(states) == 1 else None


@dataclass(frozen=True)
class GitHubBlob:
    """Octets exacts d'un fichier à un commit exact, plus l'identifiant Git
    que GitHub attribue à ces octets. Les deux sont conservés : le
    vérificateur recoupe le ``blob_sha`` annoncé par GitHub avec celui
    recalculé localement sur les octets reçus (``git_blob_sha1``), de sorte
    qu'un contenu substitué en transit ne puisse pas se faire passer pour
    le blob revu."""

    repository: str
    path: str
    ref: str
    blob_sha: str
    content: bytes


def fetch_blob_at_ref(*, repository: str, path: str, ref: str) -> GitHubBlob:
    """Relit le contenu **exact** d'un fichier au commit ``ref`` exact.

    Utilisé pour lier une autorisation/attestation aux octets réellement
    relus (items B et E) : le contenu n'est jamais pris depuis un fichier
    local fourni par l'opérateur, toujours depuis le HEAD revu."""
    deadline = _Deadline.start(_float_env(_TOTAL_TIMEOUT_ENV, _DEFAULT_TOTAL_TIMEOUT_S))
    request_timeout = _float_env(_REQUEST_TIMEOUT_ENV, _DEFAULT_REQUEST_TIMEOUT_S)
    with _ReadOnlyGitHubClient(
        token=_read_token(), api_base=_api_base(), request_timeout_s=request_timeout
    ) as client:
        payload = client.get_json(
            f"repos/{repository}/contents/{path.lstrip('/')}?ref={ref}", deadline=deadline
        )
    if not isinstance(payload, dict):
        raise GitHubAuthorityError(f"contents response for {path} is not a JSON object")
    if payload.get("type") != "file":
        raise GitHubAuthorityError(f"{path} at {ref} is not a regular file")
    size = payload.get("size")
    if isinstance(size, int) and size > _MAX_BLOB_BYTES:
        raise GitHubAuthorityError(
            f"{path} at {ref} is {size} bytes, exceeding the {_MAX_BLOB_BYTES} byte cap"
        )
    if payload.get("encoding") != "base64":
        raise GitHubAuthorityError(
            f"unexpected encoding {payload.get('encoding')!r} for {path} at {ref}"
        )
    content = payload.get("content")
    if not isinstance(content, str):
        raise GitHubAuthorityError(f"missing content for {path} at {ref}")
    try:
        raw = base64.b64decode(content, validate=False)
    except (ValueError, TypeError) as exc:
        raise GitHubAuthorityError(f"malformed base64 content for {path} at {ref}") from exc
    if len(raw) > _MAX_BLOB_BYTES:
        raise GitHubAuthorityError(
            f"{path} at {ref} decodes to {len(raw)} bytes, exceeding the cap"
        )

    # Les octets reçus doivent être *exactement* ceux que GitHub identifie
    # comme le blob de ce chemin à ce commit. Recalculer le SHA-1 d'objet
    # Git localement et exiger l'égalité ferme la fenêtre où un transport
    # compromis renverrait un `content` substitué sous un `sha` légitime.
    announced = payload.get("sha")
    if not isinstance(announced, str) or not _BLOB_SHA_PATTERN.fullmatch(announced):
        raise GitHubAuthorityError(f"missing or malformed blob sha for {path} at {ref}")
    recomputed = git_blob_sha1(raw)
    if recomputed != announced:
        raise GitHubAuthorityError(
            f"blob sha mismatch for {path} at {ref}: GitHub announced "
            f"{announced}, the received bytes hash to {recomputed} — failing closed"
        )
    return GitHubBlob(
        repository=repository, path=path, ref=ref, blob_sha=recomputed, content=raw
    )


@dataclass(frozen=True)
class PullRequestActorContext:
    """Auteur et permission du relecteur — deux faits qu'une décision
    d'ADR-0025 ne rend pas, mais qu'un reçu de liaison de revue (ADR-0035)
    doit nommer pour rester vérifiable hors ligne.

    ``evaluate_trusted_review`` exige déjà ces deux propriétés pour
    approuver : les relire ici ne les *décide* pas, cela les *constate*
    pour pouvoir les inscrire dans une preuve durable."""

    repository: str
    pull_request: int
    author: str
    base_ref: str
    reviewer: str
    reviewer_permission: str
    reviewer_role_name: str


def pull_request_actor_context(
    *, repository: str, pull_request: int, reviewer: str
) -> PullRequestActorContext:
    """Relit l'auteur de la PR et la permission effective d'un relecteur.

    Même transport que ``verify_review`` — client strictement GET, mêmes
    délais bornés, même échec fermé. Aucune décision n'est prise ici : la
    seule autorité sur une review reste ``evaluate_trusted_review``."""
    deadline = _Deadline.start(_float_env(_TOTAL_TIMEOUT_ENV, _DEFAULT_TOTAL_TIMEOUT_S))
    request_timeout = _float_env(_REQUEST_TIMEOUT_ENV, _DEFAULT_REQUEST_TIMEOUT_S)
    with _ReadOnlyGitHubClient(
        token=_read_token(), api_base=_api_base(), request_timeout_s=request_timeout
    ) as client:
        pull_request_doc = client.get_json(
            f"repos/{repository}/pulls/{pull_request}", deadline=deadline
        )
        permission_doc = client.get_json(
            f"repos/{repository}/collaborators/{reviewer}/permission", deadline=deadline
        )

    if not isinstance(pull_request_doc, dict):
        raise GitHubAuthorityError("pull request response is not a JSON object")
    user = pull_request_doc.get("user")
    if not isinstance(user, dict) or not isinstance(user.get("login"), str):
        raise GitHubAuthorityError("pull request author is missing or malformed")
    base = pull_request_doc.get("base")
    if not isinstance(base, dict) or not isinstance(base.get("ref"), str):
        raise GitHubAuthorityError("pull request base ref is missing or malformed")

    if not isinstance(permission_doc, dict):
        raise GitHubAuthorityError("permission response is not a JSON object")
    permission = permission_doc.get("permission")
    role_name = permission_doc.get("role_name")
    if not isinstance(permission, str) or not isinstance(role_name, str):
        raise GitHubAuthorityError(
            f"permission response for {reviewer} is missing permission/role_name"
        )

    return PullRequestActorContext(
        repository=repository,
        pull_request=pull_request,
        author=str(user["login"]),
        base_ref=str(base["ref"]),
        reviewer=reviewer,
        reviewer_permission=permission,
        reviewer_role_name=role_name,
    )


__all__ = [
    "GitHubAuthorityError",
    "GitHubAuthorityTimeoutError",
    "GitHubBlob",
    "GitHubRateLimitedError",
    "GitHubResponseDiagnostics",
    "PullRequestActorContext",
    "ReviewVerification",
    "activate_job_github_read_cache",
    "fetch_blob_at_ref",
    "force_live_github_reads",
    "job_github_read_cache",
    "pull_request_actor_context",
    "HEAD_PINNED_CONTEXT",
    "load_trusted_reviewers",
    "verify_review",
]
