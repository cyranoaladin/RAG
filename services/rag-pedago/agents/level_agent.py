"""LevelAgent — one per niveau (3e, 2de, 1re, Tle).

Discovers taxonomies for its level, instantiates SubjectAgents, orchestrates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.base import AcquisitionAgent
from agents.subject_agent import SubjectAgent

TAXONOMY_ROOT = Path(__file__).resolve().parents[1] / "taxonomy"
SKIP_DIRS = {"common", "exams", "proposals"}


class LevelAgent(AcquisitionAgent):
    def __init__(self, niveau: str, staging_root: Path) -> None:
        self.niveau = niveau
        self.staging_root = staging_root
        self._subjects: list[SubjectAgent] = []
        self._discover_taxonomies()

    def _discover_taxonomies(self) -> None:
        """Find all taxonomy files for this level."""
        import yaml

        from schema.taxonomy import TaxonomySpec

        for yml in sorted(TAXONOMY_ROOT.rglob("*.yml")):
            if yml.parent.name in SKIP_DIRS:
                continue
            try:
                data = yaml.safe_load(yml.read_text(encoding="utf-8"))
                spec = TaxonomySpec.model_validate(data)
                if spec.niveau.value == self.niveau:
                    staging = self.staging_root / spec.matiere
                    self._subjects.append(SubjectAgent(yml, staging))
            except Exception:
                continue

    def plan(self) -> dict[str, Any]:
        return {
            "niveau": self.niveau,
            "subjects": [s.plan() for s in self._subjects],
            "subject_count": len(self._subjects),
        }

    def fetch(self, max_notions: int | None = None) -> dict[str, Any]:
        if not self.check_staging_allowed():
            return {"error": "data_staging_allowed is false", "results": []}

        results = []
        for subject in self._subjects:
            print(f"  [{self.niveau}] {subject.spec.matiere}...")
            result = subject.fetch(max_notions=max_notions)
            results.append(result)

        return {
            "niveau": self.niveau,
            "subjects_processed": len(results),
            "results": results,
        }

    def report(self) -> dict[str, Any]:
        return {
            "niveau": self.niveau,
            "subjects": [s.report() for s in self._subjects],
        }
