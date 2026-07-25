"""ContinuousOrchestrator — pilote les passes d'ingestion continue (LOT 28).

Une « passe » = un run complet des agents continus declares dans la politique
(actuellement : EduscolAgent ; extensible a WikipediaAgent / WikiversityAgent
via le meme contrat). La continuite est assuree par un planificateur externe
(systemd timer ou cron) — ce module ne boucle jamais lui-meme (kill-switch
simple, observabilite par run).

Usage (depuis services/rag-pedago) :
    python -m agents.continuous_orchestrator --plan
    python -m agents.continuous_orchestrator --run
    python -m agents.continuous_orchestrator --report
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from agents.base import ROOT
from agents.eduscol_agent import EduscolAgent

POLICY_PATH = ROOT / "configs" / "continuous_ingestion.yml"
REPORT_PATH_DEFAULT = "data/reports/continuous_ingestion_latest.md"


def load_policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}


def run_pass(dry_run: bool = False) -> dict[str, Any]:
    """Execute une passe complete. Retourne le rapport agrege."""
    agent = EduscolAgent()
    plan = agent.plan()
    if dry_run:
        return {"mode": "plan", "plan": plan}

    result = agent.fetch()
    report = agent.report()
    report["plan"] = plan

    policy = load_policy()
    report_path = ROOT / policy.get("review", {}).get("report_file", REPORT_PATH_DEFAULT)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Rapport d'ingestion continue (LOT 28)",
        "",
        f"- Politique : `{policy.get('policy_id')}`",
        f"- Sources verifiees : {plan['sources_verified']} / {plan['sources_total']}",
        f"- Pages fetchees : {report['pages_fetched']} ({report['bytes_fetched']} octets)",
        f"- Statuts : {json.dumps(report['by_status'], ensure_ascii=False)}",
        "",
        "## Invariants",
        "- Depot staging uniquement ; aucune ecriture pgvector.",
        "- Tout artefact exige une revue humaine avant gate (human_review_required).",
        "- Delais par domaine >= crawl-delay robots.txt (eduscol : 10 s).",
        "",
        "## Detail par source",
    ]
    for rec in result.get("records", []):
        lines.append(f"- `{rec['source_id']}` → **{rec['status']}** {rec.get('detail','')}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report["report_file"] = str(report_path.relative_to(ROOT))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestion continue gouvernee (LOT 28)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true", help="Affiche le plan sans fetcher")
    group.add_argument("--run", action="store_true", help="Execute une passe")
    args = parser.parse_args()

    out = run_pass(dry_run=args.plan)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
