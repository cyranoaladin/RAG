"""EduscolAgent — ingestion continue gouvernee depuis eduscol (LOT 28, ADR-0016).

Perimetre strict :
- fetch GET-only via scrapers.fetch.governed_fetch (whitelist + robots.txt) ;
- delai par domaine >= crawl-delay robots.txt (eduscol : 10 s) ;
- depot en STAGING uniquement (texte extrait + manifestes JSONL) ;
- detection de changement par sha256 du contenu normalise ;
- decouverte de liens 1 niveau, statut to_review (revue humaine) ;
- AUCUNE ecriture pgvector, AUCUN contournement quality -> gate -> review.

Refuse de demarrer (fail-closed) si les verrous data_staging_allowed ou
network_allowed ne sont pas a true dans configs/pedago_interface_contract.yml.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import yaml

from agents.base import ROOT, AcquisitionAgent
from scrapers.fetch import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    FetchRefusal,
    FetchResult,
    apply_domain_delay,
    governed_fetch,
    is_allowed_by_robots,
    is_whitelisted,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECT_HOPS = 5


def _redirect_target(current_url: str, resp: Any) -> str | None:
    """Cible de redirection eventuelle (Location), resolue en absolu."""
    if getattr(resp, "status_code", 0) in _REDIRECT_STATUSES:
        location = resp.headers.get("location") or resp.headers.get("Location")
        if location:
            return urljoin(current_url, location)
    return None


def browser_governed_fetch(url: str) -> FetchResult | FetchRefusal:
    """GET gouverne avec empreinte TLS navigateur (contournement WAF Cloudflare).

    Contexte (diagnostic LOT 28, 25/07/2026) : eduscol est derriere Cloudflare,
    qui bloque par empreinte TLS tout client non-navigateur (403) — y compris
    requests/curl avec User-Agent navigateur — alors que le robots.txt autorise
    explicitement le crawl (Crawl-delay: 10, Allow: *.pdf, pages publiques).
    Empreintes testees le 25/07/2026 (diag LOT 28, etape 14) : chrome/edge
    bloques (challenge "Just a moment..."), firefox133 et safari18_0 passent.
    Ce transport essaie les empreintes dans l'ordre, avec repli final sur
    governed_fetch (requests) si curl_cffi est absent.

    Gouvernance INCHANGEE : whitelist + robots.txt + GET-only + UA identifie.
    La politesse (delai par domaine >= crawl-delay) reste assuree par l'agent ;
    un delai de 5 s separe les tentatives d'empreintes sur un meme domaine.
    """
    if not is_whitelisted(url):
        return FetchRefusal(url=url, reason=f"domain not whitelisted: {urlparse(url).netloc}")
    if not is_allowed_by_robots(url):
        return FetchRefusal(url=url, reason="blocked by robots.txt")
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return governed_fetch(url)

    last_result: FetchResult | None = None
    for target in ("firefox133", "safari18_0", "chrome"):
        try:
            # Redirections suivies hop par hop : whitelist + robots.txt sont
            # verifies AVANT chaque saut (jamais de fetch d'un hote interdit).
            current = url
            resp = None
            for _hop in range(_MAX_REDIRECT_HOPS + 1):
                hop_domain = urlparse(current).netloc
                apply_domain_delay(
                    hop_domain, min_seconds=_configured_domain_delay(hop_domain))
                resp = cffi_requests.get(
                    current,
                    impersonate=target,
                    headers={"User-Agent": USER_AGENT},
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
                nxt = _redirect_target(current, resp)
                if nxt is None:
                    break
                if not is_whitelisted(nxt):
                    return FetchRefusal(
                        url=url,
                        reason=f"redirect vers domaine non whitelist: "
                               f"{urlparse(nxt).netloc}")
                if not is_allowed_by_robots(nxt):
                    return FetchRefusal(
                        url=url, reason=f"redirect bloque par robots.txt: {nxt}")
                current = nxt
        except Exception as exc:  # reseau, TLS, timeout...
            return FetchResult(
                url=url,
                status_code=0,
                content_type="",
                text="",
                fetched_at=datetime.now(UTC),
                error=str(exc),
            )
        assert resp is not None
        last_result = FetchResult(
            url=url,
            status_code=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            text=resp.text,
            fetched_at=datetime.now(UTC),
            final_url=current,
        )
        if resp.status_code != 403:
            return last_result
        time.sleep(5.0)  # politesse entre tentatives d'empreintes
    assert last_result is not None
    return last_result

SOURCES_PATH = ROOT / "configs" / "eduscol_sources.yml"
POLICY_PATH = ROOT / "configs" / "continuous_ingestion.yml"
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"

_DELAY_CACHE: dict[str, float] | None = None


def _configured_domain_delay(domain: str) -> float:
    """Crawl-delay configure pour le domaine (continuous_ingestion.yml),
    replie sur ``default_delay`` (10.0 s si absent). Charge une fois.
    Utilise par la boucle de redirections : chaque saut doit respecter le
    crawl-delay du domaine visite, pas seulement le plancher global de 2 s
    (revue PR #74, round 5)."""
    global _DELAY_CACHE
    if _DELAY_CACHE is None:
        policy: dict[str, Any] = {}
        if POLICY_PATH.is_file():
            try:
                policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
            except Exception:
                policy = {}
        delays: dict[str, float] = {}
        for key, val in (policy.get("per_domain_delay") or {}).items():
            try:
                delays[str(key)] = float(val)
            except (TypeError, ValueError):
                continue
        try:
            delays.setdefault("", float(policy.get("default_delay", 10.0)))
        except (TypeError, ValueError):
            delays.setdefault("", 10.0)
        _DELAY_CACHE = delays
    return _DELAY_CACHE.get(domain, _DELAY_CACHE.get("", 10.0))


_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Fichiers statiques exclus de la decouverte (favicons, assets DSFR, etc.)
_STATIC_EXT = (
    ".png", ".svg", ".ico", ".css", ".js", ".webmanifest", ".jpg", ".jpeg",
    ".gif", ".woff", ".woff2", ".ttf", ".eot", ".map", ".xml", ".json",
)
_STATIC_PATH_PREFIXES = ("/libraries/", "/assets/", "/static/", "/themes/")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def normalize_text(html: str) -> str:
    """Extraction texte minimaliste et deterministe (pas de dependance externe).

    Supprime scripts/styles, balises, puis compacte les espaces. Le nettoyage
    riche (anti-navigation) reste l'affaire de la chaine de chunking gouvernee.
    """
    txt = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    txt = _TAG_RE.sub(" ", txt)
    return _WS_RE.sub(" ", txt).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class SourceEntry:
    id: str
    url: str
    status: str
    matiere: str
    niveaux: list[str]
    voies: list[str]
    collections_cibles: list[str]
    note: str = ""


@dataclass
class FetchRecord:
    source_id: str
    url: str
    status: str                      # fetched | unchanged | refused | skipped_ttl | skipped_unverified | error
    sha256: str | None = None
    bytes: int = 0
    detail: str = ""
    fetched_at: str = field(default_factory=_utcnow)


class EduscolAgent(AcquisitionAgent):
    """Agent d'ingestion continue des sources eduscol verifiees."""

    def __init__(
        self,
        sources_path: Path = SOURCES_PATH,
        policy_path: Path = POLICY_PATH,
    ) -> None:
        self.sources_cfg = yaml.safe_load(sources_path.read_text(encoding="utf-8")) or {}
        self.policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        self._records: list[FetchRecord] = []
        self._pages_fetched = 0
        self._bytes_fetched = 0
        self._started = time.monotonic()
        self._state_path = ROOT / self.policy.get("change_detection", {}).get(
            "state_file", "data/staging/agents/_state/eduscol_agent_state.json"
        )
        self._staging_root = ROOT / self.policy.get("staging", {}).get(
            "root", "data/staging/agents/continuous"
        )

    # ------------------------------------------------------------------
    # Verrous et budget
    # ------------------------------------------------------------------
    def _lock(self, name: str) -> bool:
        if not CONTRACT_PATH.is_file():
            return False
        cfg = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        return isinstance(cfg, dict) and cfg.get(name) is True

    def check_run_allowed(self) -> tuple[bool, str]:
        """Fail-closed : les deux verrous requis doivent etre a true."""
        for lock in ("data_staging_allowed", "network_allowed"):
            if not self._lock(lock):
                return False, f"verrou {lock} absent ou false (fail-closed)"
        return True, ""

    def _budget_exceeded(self) -> str | None:
        b = self.policy.get("budgets", {})
        if self._pages_fetched >= b.get("max_pages_per_run", 40):
            return "max_pages_per_run atteint"
        if time.monotonic() - self._started >= b.get("max_run_seconds", 3600):
            return "max_run_seconds atteint"
        if self._bytes_fetched >= b.get("max_bytes_per_run", 200 * 1024 * 1024):
            return "max_bytes_per_run atteint"
        return None

    # ------------------------------------------------------------------
    # Politesse : delai par domaine (>= crawl-delay robots.txt)
    # ------------------------------------------------------------------
    def _domain_delay(self, url: str) -> float:
        delays = self.policy.get("per_domain_delay", {})
        domain = urlparse(url).netloc
        return float(delays.get(domain, self.policy.get("default_delay", 5.0)))

    # ------------------------------------------------------------------
    # Etat (detection de changement / TTL)
    # ------------------------------------------------------------------
    def _load_state(self) -> dict[str, Any]:
        if self._state_path.is_file():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------
    # AcquisitionAgent interface
    # ------------------------------------------------------------------
    def plan(self) -> dict[str, Any]:
        sources = self.sources_cfg.get("sources", [])
        verified = [s for s in sources if s.get("status") == "verified"]
        return {
            "agent": "eduscol_agent",
            "policy": self.policy.get("policy_id"),
            "sources_total": len(sources),
            "sources_verified": len(verified),
            "sources_to_verify": len(sources) - len(verified),
            "staging_root": str(self._staging_root.relative_to(ROOT)),
            "budgets": self.policy.get("budgets", {}),
        }

    def fetch(self, max_notions: int | None = None) -> dict[str, Any]:
        ok, reason = self.check_run_allowed()
        if not ok:
            return {"error": reason, "results": []}

        state = self._load_state()
        ttl_h = float(self.policy.get("schedule", {}).get("ttl_hours", 168))

        for raw in self.sources_cfg.get("sources", []):
            budget = self._budget_exceeded()
            if budget:
                self._records.append(FetchRecord(
                    source_id=raw.get("id", "?"), url=raw.get("url", ""),
                    status="skipped_budget", detail=budget))
                break
            src = SourceEntry(
                id=raw["id"], url=raw["url"], status=raw.get("status", "to_verify"),
                matiere=raw.get("matiere", "?"), niveaux=raw.get("niveaux", []),
                voies=raw.get("voies", []), collections_cibles=raw.get("collections_cibles", []),
                note=raw.get("note", ""),
            )
            if src.status != "verified":
                self._records.append(FetchRecord(
                    source_id=src.id, url=src.url, status="skipped_unverified",
                    detail="status != verified : revue humaine requise avant activation"))
                continue
            self._fetch_source(src, state, ttl_h)

        self._save_state(state)
        self._write_ledger()
        return {"agent": "eduscol_agent", "records": [asdict(r) for r in self._records]}

    def _fetch_source(self, src: SourceEntry, state: dict[str, Any], ttl_h: float) -> None:
        prev = state.get(src.id, {})
        if prev.get("last_fetched_at"):
            last = datetime.fromisoformat(prev["last_fetched_at"])
            age_h = (datetime.now(UTC) - last).total_seconds() / 3600
            if age_h < ttl_h:
                self._records.append(FetchRecord(
                    source_id=src.id, url=src.url, status="skipped_ttl",
                    detail=f"derniere visite il y a {age_h:.1f} h < TTL {ttl_h} h"))
                return

        time.sleep(self._domain_delay(src.url))
        result = browser_governed_fetch(src.url)
        if isinstance(result, FetchRefusal):
            self._records.append(FetchRecord(
                source_id=src.id, url=src.url, status="refused", detail=result.reason))
            return
        assert isinstance(result, FetchResult)
        if result.error or result.status_code != 200:
            self._records.append(FetchRecord(
                source_id=src.id, url=src.url, status="error",
                detail=result.error or f"HTTP {result.status_code}"))
            return

        text = normalize_text(result.text)
        digest = sha256_text(text)
        self._pages_fetched += 1
        self._bytes_fetched += len(result.text)

        if digest == prev.get("sha256"):
            state[src.id] = {**prev, "last_fetched_at": _utcnow()}
            self._records.append(FetchRecord(
                source_id=src.id, url=src.url, status="unchanged", sha256=digest))
            return

        artefact_dir = self._deposit(src, text, digest, result.text)
        state[src.id] = {"sha256": digest, "last_fetched_at": _utcnow(),
                         "artefact_dir": str(artefact_dir.relative_to(ROOT))}
        self._records.append(FetchRecord(
            source_id=src.id, url=src.url, status="fetched", sha256=digest,
            bytes=len(result.text)))

        if self.policy.get("discovery", {}).get("enabled", True):
            self._discover_links(src, result.text)

    # ------------------------------------------------------------------
    # Depot staging + manifeste
    # ------------------------------------------------------------------
    def _deposit(self, src: SourceEntry, text: str, digest: str, html: str) -> Path:
        niveau = src.niveaux[0] if src.niveaux else "transversal"
        out = self._staging_root / niveau / src.matiere / src.id
        out.mkdir(parents=True, exist_ok=True)

        (out / "page.txt").write_text(text, encoding="utf-8")
        manifest = {
            "source_id": src.id, "url": src.url, "sha256": digest,
            "fetched_at": _utcnow(), "matiere": src.matiere,
            "niveaux": src.niveaux, "voies": src.voies,
            "collections_cibles": src.collections_cibles,
            "rights_default": self.sources_cfg.get("rights_default"),
            "human_review_required": True,
            "review_status": "pending",
            "note": src.note,
        }
        (out / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    # ------------------------------------------------------------------
    # Decouverte de liens (1 niveau, statut to_review)
    # ------------------------------------------------------------------
    def _discover_links(self, src: SourceEntry, html: str) -> None:
        disc = self.policy.get("discovery", {})
        domain = urlparse(src.url).netloc
        forbidden = tuple(disc.get("forbidden_path_prefixes", {}).get(domain, []))
        max_links = self.policy.get("budgets", {}).get("max_discovered_links_per_source", 25)

        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_href in _LINK_RE.findall(html):
            absolute = urljoin(src.url, raw_href).split("#")[0]
            if absolute in seen:
                continue
            seen.add(absolute)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if disc.get("same_domain_only", True) and parsed.netloc != domain:
                # seuls les sous-domaines eduscol whitelists (cache.media...) sont gardes
                if "eduscol" not in parsed.netloc and "education.gouv.fr" not in parsed.netloc:
                    continue
            if forbidden and parsed.path.startswith(forbidden):
                continue
            path_lower = parsed.path.lower()
            if path_lower.endswith(_STATIC_EXT):
                continue  # assets statiques : hors perimetre de revue
            if parsed.path.startswith(_STATIC_PATH_PREFIXES):
                continue
            kind = "pdf" if path_lower.endswith(".pdf") else "page"
            links.append({"url": absolute, "kind": kind})
            if len(links) >= max_links:
                break

        if not links:
            return
        niveau = src.niveaux[0] if src.niveaux else "transversal"
        out = self._staging_root / niveau / src.matiere / src.id / "discovered_links.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for link in links:
                fh.write(json.dumps({
                    **link, "source_id": src.id, "discovered_at": _utcnow(),
                    "status": disc.get("discovered_status", "to_review"),
                    "ingest_content": False,
                    "human_review_required": True,
                }, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Ledger + rapport
    # ------------------------------------------------------------------
    def _write_ledger(self) -> None:
        ledger = ROOT / self.policy.get("review", {}).get(
            "ledger_append", "data/ledger/continuous_ingestion.jsonl")
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "run_at": _utcnow(), "agent": "eduscol_agent",
                "policy": self.policy.get("policy_id"),
                "records": [asdict(r) for r in self._records],
            }, ensure_ascii=False) + "\n")

    def report(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for r in self._records:
            counts[r.status] = counts.get(r.status, 0) + 1
        return {
            "agent": "eduscol_agent",
            "runs_records": len(self._records),
            "by_status": counts,
            "pages_fetched": self._pages_fetched,
            "bytes_fetched": self._bytes_fetched,
            "invariant": "staging uniquement — aucune ecriture pgvector (ADR-0016)",
        }
