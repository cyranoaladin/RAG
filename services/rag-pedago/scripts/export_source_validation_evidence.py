#!/usr/bin/env python3
"""Export versionne des preuves de validation des sources (revue PR #74, round 6).

Constat Codex : les verdicts signes produits par ``source_validator`` vivent
sous ``data/`` (ignore par git) ; ni la revue ni un deploiement ulterieur ne
peuvent prouver qu'un couple URL/contenu precis a recu ``verified_candidate``.

Ce script consigne les verdicts signes (dernier par source) dans
``docs/validation/source_validation_evidence.json`` — fichier VERSIONNE — et
applique une porte fail-closed : toute source ``status: verified`` suivie par
le ledger DOIT avoir un verdict ``verified_candidate`` signe dont l'URL
correspond a la config actuelle. Les 9 sources verifiees avant LOT 31 ne sont
pas suivies par le ledger : hors perimetre de cette porte.

Usage (depuis services/rag-pedago) :

    python3 scripts/export_source_validation_evidence.py

Code de sortie : 0 si l'export est ecrit et coherent, 1 sinon.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]  # services/rag-pedago
REPO_ROOT = ROOT.parents[1]  # racine du depot
LEDGER_PATH = ROOT / "data" / "ledger" / "source_validation.jsonl"
SOURCES_PATH = ROOT / "configs" / "eduscol_sources.yml"
EVIDENCE_PATH = REPO_ROOT / "docs" / "validation" / "source_validation_evidence.json"


def load_verdicts(ledger_path: Path) -> list[dict]:
    """Dernier verdict signe par source_id (resumes de run exclus)."""
    if not ledger_path.is_file():
        return []
    latest: dict[str, dict] = {}
    order: list[str] = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = entry.get("source_id")
        if not sid or "verdict" not in entry:
            continue  # resume de run, pas un verdict signe
        if sid not in latest:
            order.append(sid)
        latest[sid] = entry
    return [latest[sid] for sid in order]


def export(ledger_path: Path, sources_path: Path,
           evidence_path: Path) -> tuple[int, str]:
    """Exporte les preuves et verifie la coherence config/ledger."""
    verdicts = load_verdicts(ledger_path)
    if not verdicts:
        return 1, f"AUCUN verdict signe dans {ledger_path} — rien a exporter"

    cfg = yaml.safe_load(sources_path.read_text(encoding="utf-8")) or {}
    sources = cfg.get("sources", []) or []
    by_id = {v["source_id"]: v for v in verdicts}

    # Porte fail-closed : une source `verified` suivie par le ledger sans
    # verdict `verified_candidate` signe — ou avec une URL divergente — est
    # une violation de gouvernance (pas de bascule sans preuve versionnee).
    violations: list[str] = []
    for s in sources:
        if s.get("status") != "verified":
            continue
        sid = s.get("id") or s.get("source_id")
        v = by_id.get(sid)
        if v is None:
            continue  # source verifiee avant LOT 31 : hors perimetre
        if v.get("verdict") != "verified_candidate":
            violations.append(f"{sid} (verdict={v.get('verdict')})")
        elif s.get("url") and v.get("url") and s["url"] != v["url"]:
            violations.append(f"{sid} (url divergente config/ledger)")

    if violations:
        return 1, ("VIOLATIONS preuves sources: " + "; ".join(violations))

    ledger_bytes = ledger_path.read_bytes()
    evidence = {
        "exported_at": datetime.now(UTC).isoformat(),
        "ledger": str(ledger_path.relative_to(REPO_ROOT))
        if ledger_path.is_relative_to(REPO_ROOT) else str(ledger_path),
        "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "verdicts_count": len(verdicts),
        "verdicts": verdicts,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return 0, (f"evidence exportee: {len(verdicts)} verdict(s) signe(s) "
               f"-> {evidence_path}")


def main() -> int:
    code, msg = export(LEDGER_PATH, SOURCES_PATH, EVIDENCE_PATH)
    print(msg, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
