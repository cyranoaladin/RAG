"""SourceValidator — agent de validation des sources `to_verify` (LOT 31, ADR-0018 §6).

La bascule `to_verify` -> `verified` d'une source etait une revue humaine
(ADR-0009). ADR-0018 substitue des agents experts aux revues humaines : cet
agent relit chaque source candidate avec les regles du QualityExpert
(substance, motifs interdits, challenge WAF) et du RightsExpert (provenance
resolue par rights_map).

Perimetre strict : l'agent NE MODIFIE JAMAIS la configuration. Il produit un
verdict signe par source (`verified_candidate` / `stays_to_verify`) ; la
bascule effective de `status` reste un changement de config soumis a PR.

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
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import yaml

from agents.base import ROOT

SOURCES_PATH = ROOT / "configs" / "eduscol_sources.yml"
POLICY_PATH = ROOT / "configs" / "review_policy.yml"
REPORT_PATH = ROOT / "data" / "reports" / "source_validation_latest.md"
LEDGER_PATH = ROOT / "data" / "ledger" / "source_validation.jsonl"

_WS_RE = re.compile(r"\s+")
DEFAULT_MIN_WORDS = 200
DEFAULT_FORBID = ("just a moment", "enable javascript", "attention required")


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _fetch(url: str) -> tuple[int, str]:
    """Fetch gouverne navigateur (curl_cffi) — meme chaine de cibles TLS que
    l'agent d'ingestion (WAF Cloudflare : firefox/safari passent, chrome non).
    Retourne (status_code, texte). Levee d'exception = echec reseau."""
    import time

    from curl_cffi import requests as cffi_requests

    html = ""
    status_code = 0
    for target in ("firefox133", "safari18_0"):
        resp = cffi_requests.get(url, impersonate=target, timeout=30,
                                 allow_redirects=True)
        status_code = resp.status_code
        html = resp.text or ""
        if status_code != 403:
            break
        time.sleep(5.0)  # politesse entre deux tentatives (WAF)
    # Texte brut approximatif (pas de dependance HTML lourde) :
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return status_code, _WS_RE.sub(" ", text).strip()


def validate_source(source: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Relit une source candidate. Verdict signe, rejouable, sans effet de bord."""
    src_id = source.get("id", "?")
    url = source.get("url", "")
    rules: list[str] = []
    reasons: list[str] = []
    verdict = "verified_candidate"

    rights_map = policy.get("rights_map", {})
    domain = urlparse(url).netloc
    resolved = rights_map.get(domain)
    if resolved is None:
        verdict = "stays_to_verify"
        rules.append("unknown_rights_action:quarantine")
        reasons.append(f"droits inconnus pour la provenance '{domain}' (regle dure)")
    else:
        rules.append("rights_resolved_by_provenance")
        reasons.append(f"provenance '{domain}' -> droits '{resolved}'")

    status_code = 0
    words = 0
    if resolved is not None:
        try:
            status_code, text = _fetch(url)
            words = len(text.split())
        except Exception as exc:  # reseau indisponible -> pas de bascule
            verdict = "stays_to_verify"
            rules.append("fetch_error")
            reasons.append(f"echec fetch : {exc}")
        else:
            if status_code != 200:
                verdict = "stays_to_verify"
                rules.append(f"http_status:{status_code}")
                reasons.append(f"HTTP {status_code} != 200")
            text_norm = _WS_RE.sub(" ", text.lower())
            forbid = tuple(p.lower() for p in
                           policy.get("quality_expert", {}).get("forbid_patterns",
                                                                DEFAULT_FORBID))
            for pattern in forbid:
                if pattern in text_norm:
                    verdict = "stays_to_verify"
                    rules.append(f"forbid_pattern:{pattern}")
                    reasons.append(f"motif interdit : '{pattern}' (page degradee)")
            min_words = int(policy.get("quality_expert", {}).get("min_words",
                                                                 DEFAULT_MIN_WORDS))
            if words < min_words:
                verdict = "stays_to_verify"
                rules.append("too_thin")
                reasons.append(f"substance insuffisante : {words} mots < {min_words}")
            if verdict == "verified_candidate":
                rules.append("substance_ok")
                reasons.append(f"HTTP 200, {words} mots, aucun motif interdit")

    payload = {
        "source_id": src_id,
        "url": url,
        "verdict": verdict,
        "http_status": status_code,
        "words": words,
        "rules_fired": rules,
        "reasons": reasons,
        "validated_at": _utcnow(),
        "validator": "source_validator_v1",
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    payload["signature"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return payload


def run() -> dict[str, Any]:
    cfg = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8")) or {}
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    candidates = [s for s in cfg.get("sources", []) if s.get("status") == "to_verify"]

    verdicts = [validate_source(s, policy) for s in candidates]
    flip = [v["source_id"] for v in verdicts if v["verdict"] == "verified_candidate"]
    stay = [v["source_id"] for v in verdicts if v["verdict"] != "verified_candidate"]

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        entry = {"run_at": _utcnow(), "candidates": len(verdicts),
                 "verified_candidates": len(flip)}
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

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
            f"- `{v['source_id']}` → **{v['verdict']}** ({v['signature']}) — "
            f"{'; '.join(v['reasons'])}"
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
