"""OrchestratorAgent — coordinates all LevelAgents.

Dispatches work, aggregates reports, respects governance.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agents.base import AcquisitionAgent
from agents.level_agent import LevelAgent

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGING = ROOT / "data" / "staging" / "agents"


class OrchestratorAgent(AcquisitionAgent):
    def __init__(
        self,
        niveaux: list[str] | None = None,
        staging_root: Path = DEFAULT_STAGING,
        max_notions_per_subject: int | None = None,
    ) -> None:
        self.niveaux = niveaux or ["terminale"]
        self.staging_root = staging_root
        self.max_notions = max_notions_per_subject
        self._levels: list[LevelAgent] = []
        for niveau in self.niveaux:
            self._levels.append(LevelAgent(niveau, staging_root / niveau))

    def plan(self) -> dict[str, Any]:
        return {
            "orchestrator": True,
            "niveaux": self.niveaux,
            "levels": [level.plan() for level in self._levels],
        }

    def fetch(self, max_notions: int | None = None) -> dict[str, Any]:
        if not self.check_staging_allowed():
            return {"error": "data_staging_allowed is false", "results": []}
        if not self.check_ingestion_blocked():
            return {"error": "ingestion_allowed must be false", "results": []}

        effective_max = max_notions or self.max_notions
        results = []
        for level in self._levels:
            print(f"\n=== Niveau: {level.niveau} ===")
            result = level.fetch(max_notions=effective_max)
            results.append(result)

        return {
            "orchestrator": True,
            "niveaux": self.niveaux,
            "results": results,
        }

    def report(self) -> dict[str, Any]:
        """Hierarchical coverage report: niveau → matière → notions."""
        levels = []
        total_found = 0
        total_not_found = 0

        for level in self._levels:
            level_report = level.report()
            for subject in level_report.get("subjects", []):
                total_found += subject.get("found_count", 0)
                total_not_found += subject.get("not_found_count", 0)
            levels.append(level_report)

        return {
            "orchestrator": True,
            "niveaux": self.niveaux,
            "total_found": total_found,
            "total_not_found": total_not_found,
            "levels": levels,
        }


def main() -> None:
    """CLI entry point for orchestrated acquisition."""
    import argparse
    parser = argparse.ArgumentParser(description="Orchestrated acquisition")
    parser.add_argument("--niveau", nargs="+", default=["terminale"])
    parser.add_argument("--max-notions", type=int, default=3)
    args = parser.parse_args()

    orch = OrchestratorAgent(
        niveaux=args.niveau,
        max_notions_per_subject=args.max_notions,
    )

    print("=== PLAN ===")
    plan = orch.plan()
    for level in plan["levels"]:
        for subj in level["subjects"]:
            print(f"  {level['niveau']}/{subj['matiere']}: {subj['notions_count']} notions")

    print("\n=== FETCH ===")
    orch.fetch()

    print("\n=== REPORT ===")
    report = orch.report()
    print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))


if __name__ == "__main__":
    main()
