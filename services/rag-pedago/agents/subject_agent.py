"""SubjectAgent — one per (matiere, niveau, statut).

Knows its TaxonomySpec, its libre sources, and the BO correspondence.
Prioritizes notions not_found/found_partial from the correspondence report.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agents.base import AcquisitionAgent
from schema.taxonomy import TaxonomySpec
from scrapers.taxonomy_fetcher import fetch_notion


class SubjectAgent(AcquisitionAgent):
    def __init__(
        self,
        taxonomy_path: Path,
        staging_dir: Path,
        sources: list[dict[str, str]] | None = None,
    ) -> None:
        data = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8"))
        self.spec = TaxonomySpec.model_validate(data)
        self.taxonomy_path = taxonomy_path
        self.staging_dir = staging_dir
        self.sources = sources or []
        self._results: list[dict[str, Any]] = []

    def plan(self) -> dict[str, Any]:
        notions = []
        for theme in self.spec.themes:
            for notion in theme.notions:
                notions.append({
                    "notion_id": notion.id,
                    "label": notion.label or notion.id,
                    "theme": theme.id,
                })
        return {
            "matiere": self.spec.matiere,
            "niveau": self.spec.niveau.value,
            "statut": self.spec.statut_enseignement.value,
            "notions_count": len(notions),
            "notions": notions,
        }

    def fetch(self, max_notions: int | None = None) -> dict[str, Any]:
        if not self.check_staging_allowed():
            return {"error": "data_staging_allowed is false", "results": []}

        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._results = []
        count = 0

        for theme in self.spec.themes:
            for notion in theme.notions:
                if max_notions and count >= max_notions:
                    break
                entries = fetch_notion(
                    notion_id=notion.id,
                    label=notion.label,
                    matiere=self.spec.matiere,
                    niveau=self.spec.niveau.value,
                    voie=self.spec.voie.value,
                    statut=self.spec.statut_enseignement.value,
                )
                self._results.extend(entries)

                # Deposit in staging
                import json
                for entry in entries:
                    if entry.get("status") in ("ok", "quality_issues"):
                        fname = f"{self.spec.matiere}_{notion.id}.json"
                        (self.staging_dir / fname).write_text(
                            json.dumps(entry, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                count += 1

        found = sum(1 for e in self._results if e.get("status") in ("ok", "quality_issues"))
        not_found = sum(1 for e in self._results if e.get("status") == "not_found")

        return {
            "matiere": self.spec.matiere,
            "niveau": self.spec.niveau.value,
            "notions_processed": count,
            "found": found,
            "not_found": not_found,
        }

    def report(self) -> dict[str, Any]:
        found = [e for e in self._results if e.get("status") in ("ok", "quality_issues")]
        not_found = [e for e in self._results if e.get("status") == "not_found"]
        return {
            "matiere": self.spec.matiere,
            "niveau": self.spec.niveau.value,
            "found_count": len(found),
            "not_found_count": len(not_found),
            "found_notions": [e.get("notion_id") for e in found],
            "not_found_notions": [e.get("notion_id") for e in not_found],
        }
