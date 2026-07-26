"""SourceValidator — validation agentique des sources `to_verify` (LOT 31).

La bascule `to_verify` -> `verified` d'une source etait une revue humaine
(ADR-0009). ADR-0018 substitue des agents experts aux revues humaines : cet
agent relit chaque source candidate avec :
- le FETCH GOUVERNE de l'agent d'ingestion (whitelist + robots.txt + chaine
  d'empreintes WAF), JAMAIS un appel reseau direct ;
- le RightsExpert : droits resolus par provenance sur l'URL d'origine ET sur
  l'URL finale apres redirections (fail-closed si provenance finale inconnue) ;
- le QualityExpert : HTTP 200, substance, motifs interdits / challenge WAF ;
- le SubjectExpert : pertinence pedagogique REELLE du contenu vs les
  collections cibles (couverture de notions ou marqueurs d'examen selon le
  domaine) — 200 mots ne suffisent pas a valider une source.

Perimetre strict : l'agent NE MODIFIE JAMAIS la configuration. Chaque verdict
signe est consigne tel quel dans le ledger append-only (source de verite des
bascules `verified` effectuees ensuite par PR).

Usage (depuis services/rag-pedago) :
    python -m agents.source_validator --plan   # liste les sources to_verify
    python -m agents.source_validator --run    # relit chaque source candidate
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from agents.base import ROOT
from agents.eduscol_agent import browser_governed_fetch
from agents.reviewers import Artefact, SubjectExpertAgent
from scrapers.fetch import FetchRefusal, FetchResult

SOURCES_PATH = ROOT / "configs" / "eduscol_sources.yml"
POLICY_PATH = ROOT / "configs" / "review_policy.yml"
INGESTION_POLICY_PATH = ROOT / "configs" / "continuous_ingestion.yml"
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"
REPORT_PATH = ROOT / "data" / "reports" / "source_validation_latest.md"
LEDGER_PATH = ROOT / "data" / "ledger" / "source_validation.jsonl"

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(
    r"<script.*?</script>|<style.*?</style>", re.DOTALL | re.IGNORECASE)
_TAG_ANY_RE = re.compile(r"<[^>]+>")
DEFAULT_MIN_WORDS = 200
DEFAULT_MAX_WORDS = 200000
# v4 : regles round 8 (substance exam) + persistance immediate/reprise.
# Tout changement de logique de revue DOIT bumper cette version : les
# verdicts d'une version anterieure sont perimes (portes de l'export).
VALIDATOR_VERSION = "source_validator_v4"
# TTL de reprise : un verdict recent (meme version, meme URL) dispense de
# refetcher la source apres une interruption (revue PR #74, round 9).
RESUME_TTL_SECONDS = 3600
DEFAULT_FORBID = ("just a moment", "enable javascript", "attention required")
DEFAULT_DOMAIN_DELAY = 10.0  # crawl-delay eduscol (robots.txt)


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _strip_html(html: str) -> str:
    """Extraction du contenu PRINCIPAL : le chrome de page (nav, header,
    footer, aside, formulaires) est exclu AVANT le comptage de substance et
    la relue pedagogique — 200 mots de navigation ne font pas une source."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # repli regex minimal si bs4 absent
        text = _TAG_RE.sub(" ", html)
        text = _TAG_ANY_RE.sub(" ", text)
        return _WS_RE.sub(" ", text).strip()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                     "form", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return _WS_RE.sub(" ", main.get_text(" ", strip=True))


def validate_source(source: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Relit une source candidate. Verdict signe, rejouable, sans effet de bord."""
    src_id = source.get("id", "?")
    url = source.get("url", "")
    rules: list[str] = []
    reasons: list[str] = []
    verdict = "verified_candidate"

    # 1. Droits sur la provenance declaree (regle dure inchangee)
    rights_map = policy.get("rights_map", {})
    domain = urlparse(url).netloc
    resolved = rights_map.get(domain)
    if resolved is None:
        rules.append("unknown_rights_action:quarantine")
        reasons.append(f"droits inconnus pour la provenance '{domain}' (regle dure)")
        verdict = "stays_to_verify"
    else:
        rules.append("rights_resolved_by_provenance")
        reasons.append(f"provenance '{domain}' -> droits '{resolved}'")

    status_code = 0
    words = 0
    final_url = url
    final_rights: str | None = resolved
    content_sha256 = ""
    if resolved is not None:
        # 2. Fetch GOUVERNE (whitelist + robots.txt + empreintes) — jamais direct
        result = browser_governed_fetch(url)
        if isinstance(result, FetchRefusal):
            rules.append("fetch_refused")
            reasons.append(f"fetch gouverne refuse : {result.reason}")
            verdict = "stays_to_verify"
        else:
            assert isinstance(result, FetchResult)
            status_code = result.status_code
            text = _strip_html(result.text or "")
            words = len(text.split())
            content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

            if status_code != 200:
                rules.append(f"http_status:{status_code}")
                reasons.append(f"HTTP {status_code} != 200")
                verdict = "stays_to_verify"

            # 3. Droits revalidés sur la provenance FINALE (redirections) :
            #    hotes inconnus -> fail-closed ; droits DIFFERENTS -> rejet
            #    (le contenu serait ingere sous la mauvaise licence).
            final_url = result.final_url or url
            final_domain = urlparse(final_url).netloc
            if final_domain != domain:
                resolved_final = rights_map.get(final_domain)
                final_rights = resolved_final
                if resolved_final is None:
                    rules.append("redirect_rights_unresolved")
                    reasons.append(
                        f"redirection vers '{final_domain}' absente de rights_map "
                        "(fail-closed)")
                    verdict = "stays_to_verify"
                elif resolved_final != resolved:
                    rules.append("redirect_rights_mismatch")
                    reasons.append(
                        f"droits divergents apres redirection : '{resolved}' "
                        f"(origine) != '{resolved_final}' (finale) — "
                        "licence inapplicable presumee")
                    verdict = "stays_to_verify"
                else:
                    rules.append("redirect_rights_resolved")
                    reasons.append(
                        f"redirection vers '{final_domain}' -> droits '{resolved_final}'")

            # 4. Qualite : motifs interdits + substance minimale
            text_norm = _WS_RE.sub(" ", text.lower())
            forbid = tuple(
                p.lower()
                for p in policy.get("quality_expert", {}).get(
                    "forbid_patterns", DEFAULT_FORBID)
            )
            for pattern in forbid:
                if pattern in text_norm:
                    rules.append(f"forbid_pattern:{pattern}")
                    reasons.append(f"motif interdit : '{pattern}' (page degradee)")
                    verdict = "stays_to_verify"
            min_words = int(policy.get("quality_expert", {}).get(
                "min_words", DEFAULT_MIN_WORDS))
            if words < min_words:
                rules.append("too_thin")
                reasons.append(f"substance insuffisante : {words} mots < {min_words}")
                verdict = "stays_to_verify"
            # Borne haute symetrique au QualityExpertAgent : un document
            # pathologique (concatenation accidentelle...) ne doit pas etre
            # active meme s'il contient assez de termes (revue PR #74, r7).
            max_words = int(policy.get("quality_expert", {}).get(
                "max_words", DEFAULT_MAX_WORDS))
            if words > max_words:
                rules.append("too_large")
                reasons.append(f"document pathologique : {words} mots > {max_words}")
                verdict = "stays_to_verify"

            # 5. Pertinence pedagogique REELLE (SubjectExpert, perimetre complet)
            if verdict == "verified_candidate":
                artefact = Artefact(
                    staging_dir=Path("."),
                    manifest={
                        "source_id": src_id,
                        "url": url,
                        "collections_cibles": source.get("collections_cibles") or [],
                        "sha256": content_sha256,
                    },
                    text=text,
                )
                sv = SubjectExpertAgent(policy).review(artefact)
                rules.append(f"subject_expert:{sv.status}")
                if sv.status != "approved":
                    verdict = "stays_to_verify"
                    reasons.append(
                        "pertinence pedagogique insuffisante — "
                        + "; ".join(sv.reasons))
                else:
                    rules.append("substance_ok")
                    reasons.append(
                        f"HTTP 200, {words} mots, pertinence confirmee : "
                        + "; ".join(sv.reasons))

    payload = {
        "source_id": src_id,
        "url": url,
        "verdict": verdict,
        "http_status": status_code,
        "words": words,
        # Verdict lie aux octets relus et a la provenance reelle (activation
        # ulterieure verifiable contre ce digest et cette URL finale).
        "content_sha256": content_sha256,
        "final_url": final_url,
        "final_rights": final_rights,
        "rules_fired": rules,
        "reasons": reasons,
        "validated_at": _utcnow(),
        "validator": VALIDATOR_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    payload["signature"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return payload


def _domain_delay() -> float:
    """Delai de politesse par domaine, aligne sur la politique d'ingestion."""
    if INGESTION_POLICY_PATH.is_file():
        cfg = yaml.safe_load(INGESTION_POLICY_PATH.read_text(encoding="utf-8")) or {}
        try:
            return float(cfg.get("per_domain_delay", DEFAULT_DOMAIN_DELAY))
        except (TypeError, ValueError):
            return DEFAULT_DOMAIN_DELAY
    return DEFAULT_DOMAIN_DELAY


def _lock(name: str) -> bool:
    """Verrou fail-closed du contrat d'interface (meme regle qu'EduscolAgent)."""
    if not CONTRACT_PATH.is_file():
        return False
    cfg = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return isinstance(cfg, dict) and cfg.get(name) is True


def _latest_verdicts() -> dict[str, dict[str, Any]]:
    """Dernier verdict du ledger par source_id (reprise). Lecture TOLERANTE
    aux lignes malformees : la reprise refetchera simplement la source ; la
    porte fail-closed sur la corruption est celle de l'export de preuves."""
    latest: dict[str, dict[str, Any]] = {}
    if not LEDGER_PATH.is_file():
        return latest
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = entry.get("source_id")
        if sid and "verdict" in entry:
            latest[sid] = entry
    return latest


def _is_resumable(prev: dict[str, Any], source: dict[str, Any]) -> bool:
    """Un verdict est reutilisable s'il est de la version courante, pour la
    meme URL, et plus jeune que RESUME_TTL_SECONDS (reprise apres crash)."""
    if prev.get("validator") != VALIDATOR_VERSION:
        return False
    if source.get("url") and prev.get("url") != source["url"]:
        return False
    ts = prev.get("validated_at")
    if not isinstance(ts, str):
        return False
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(ts)).total_seconds()
    except ValueError:
        return False
    return 0 <= age < RESUME_TTL_SECONDS


def run() -> dict[str, Any]:
    # Kill-switch reseau : AUCUNE requete si le verrou n'est pas leve.
    if not _lock("network_allowed"):
        return {"status": "refused",
                "error": "verrou network_allowed absent ou false (fail-closed) "
                         "— aucune requete reseau emise",
                "exit_code": 1}

    cfg = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")) or {}
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    candidates = [s for s in cfg.get("sources", []) if s.get("status") == "to_verify"]

    # Reprise : un verdict recent (meme version, meme URL) dispense de
    # refetcher la source (run interrompu puis relance, revue PR #74 r9).
    prior = _latest_verdicts()
    verdicts: list[dict[str, Any]] = []
    delay = _domain_delay()
    fetched = 0
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        for source in candidates:
            sid = source.get("id") or source.get("source_id")
            prev = prior.get(sid) if sid else None
            if prev and _is_resumable(prev, source):
                resumed = dict(prev)
                resumed["resumed"] = True
                verdicts.append(resumed)
                continue
            if fetched > 0:
                time.sleep(delay)  # politesse entre sources d'un meme domaine
            fetched += 1
            verdict = validate_source(source, policy)
            verdicts.append(verdict)
            # Persistance IMMEDIATE de chaque verdict signe : une
            # interruption n'efface pas les validations deja produites
            # (revue PR #74, round 9).
            fh.write(json.dumps(verdict, ensure_ascii=False) + "\n")
            fh.flush()
        summary = {"run_at": _utcnow(), "candidates": len(verdicts),
                   "verified_candidates": sum(
                       1 for v in verdicts if v["verdict"] == "verified_candidate")}
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    flip = [v["source_id"] for v in verdicts if v["verdict"] == "verified_candidate"]
    stay = [v["source_id"] for v in verdicts if v["verdict"] != "verified_candidate"]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Validation des sources to_verify (LOT 31 / ADR-0018 §6)",
        "",
        f"- Candidates relues : {len(verdicts)}",
        f"- verified_candidate : {len(flip)} | stays_to_verify : {len(stay)}",
        "",
        "La bascule `status: verified` reste un changement de config soumis a PR.",
        "",
        "## Verdicts",
    ]
    for v in verdicts:
        lines.append(
            f"- `{v['source_id']}` → **{v['verdict']}** "
            f"({v['signature']}) — {'; '.join(v['reasons'])}"
        )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"status": "ok", "candidates": len(verdicts),
            "verified_candidates": flip, "stays_to_verify": stay,
            "report": str(REPORT_PATH), "exit_code": 0}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validation agentique des sources to_verify")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()

    cfg = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")) or {}
    if args.plan:
        candidates = [s.get("id") for s in cfg.get("sources", [])
                      if s.get("status") == "to_verify"]
        out: dict[str, Any] = {"to_verify": len(candidates), "sources": candidates,
                               "exit_code": 0}
    else:
        out = run()
    print(json.dumps(out, indent=2, ensure_ascii=False))
    exit_code = out.get("exit_code", 0)
    sys.exit(exit_code if isinstance(exit_code, int) else 1)


if __name__ == "__main__":
    main()
