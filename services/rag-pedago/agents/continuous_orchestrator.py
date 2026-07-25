"""ContinuousOrchestrator — pilote les passes d'ingestion continue (LOT 28).

Une « passe » = un run complet des agents continus declares dans la politique
(actuellement : EduscolAgent ; extensible a WikipediaAgent / WikiversityAgent
via le meme contrat). La continuite est assuree par un planificateur externe
(systemd timer ou cron) — ce module ne boucle jamais lui-meme (kill-switch
simple, observabilite par run).

Code de sortie : 0 si la passe est nominale, 1 si un refus de gouvernance
(verrou ferme) ou une erreur d'agent survient — ainsi systemd/journald et la
supervision distinguent un refus intentionnel d'un run vide valide.

Usage (depuis services/rag-pedago) :
    python -m agents.continuous_orchestrator --plan
    python -m agents.continuous_orchestrator --run
"""
from __future__ import annotations

import argparse
import json
import sys
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
        return {"mode": "plan", "plan": plan, "exit_code": 0}

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
    ]

    if "error" in result:
        # Refus de gouvernance (verrou ferme) ou erreur agent : la passe est
        # marquee en echec et le code de sortie est non nul (fix revue PR).
        report["status"] = "refused"
        report["error"] = result["error"]
        report["exit_code"] = 1
        lines += [
            "",
            "## REFUS — passe non executee",
            f"- Motif : {result['error']}",
            "- Action : verifier configs/pedago_interface_contract.yml (verrous).",
        ]
    else:
        report["status"] = "ok"
        report["exit_code"] = 0
        lines += [
            f"- Pages fetchees : {report['pages_fetched']} ({report['bytes_fetched']} octets)",
            f"- Statuts : {json.dumps(report['by_status'], ensure_ascii=False)}",
        ]

    lines += [
        "",
        "## Invariants",
        "- Depot staging uniquement ; aucune ecriture pgvector.",
        "- Tout artefact exige une revue humaine avant gate (human_review_required).",
        "- Delais par domaine >= crawl-delay robots.txt (eduscol : 10 s).",
    ]
    if result.get("records"):
        lines += ["", "## Detail par source"]
        for rec in result["records"]:
            lines.append(f"- `{rec['source_id']}` → **{rec['status']}** {rec.get('detail', '')}")
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
    sys.exit(out.get("exit_code", 0))


if __name__ == "__main__":
    main()
