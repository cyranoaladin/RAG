"""SubjectAgent — one per (matiere, niveau, statut).

Loads a TaxonomySpec and, when available, the BO correspondence report
to prioritize notions: bo_not_found first, then bo_partial, then bo_found.
When no programme is available, falls back to taxonomy order (no_correspondence).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from agents.base import ROOT, AcquisitionAgent
from schema.taxonomy import TaxonomySpec
from scrapers.taxonomy_fetcher import (
    ACCEPTED_STATUSES,
    _cleanup_previous_notion_files,
    fetch_notion,
)

CORRESPONDANCE_DIR = ROOT / "data" / "programmes" / "correspondance"


def _load_correspondence(matiere: str, niveau: str) -> dict[str, str] | None:
    """Load pre-computed BO correspondence artefact (JSON, no PDF parsing).

    Returns a dict mapping notion_id → status (found_exact/found_partial/not_found),
    or None if no artefact exists.
    """
    artefact = CORRESPONDANCE_DIR / f"{matiere}_{niveau}.json"
    if not artefact.is_file():
        return None

    try:
        report = json.loads(artefact.read_text(encoding="utf-8"))
        if report.get("extraction_status") == "failed":
            return None

        result: dict[str, str] = {}
        for entry in report.get("details_found_exact", []):
            result[entry["notion_id"]] = "found_exact"
        for entry in report.get("details_found_partial", []):
            result[entry["notion_id"]] = "found_partial"
        for entry in report.get("details_not_found", []):
            result[entry["notion_id"]] = "not_found"
        return result
    except Exception:
        return None


# Priority order for sorting
_PRIORITY_ORDER = {"bo_not_found": 0, "bo_partial": 1, "no_correspondence": 2, "bo_found": 3}


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
        self._correspondence = _load_correspondence(
            self.spec.matiere, self.spec.niveau.value
        )

    def _priority_for(self, notion_id: str) -> str:
        """Derive priority from BO correspondence."""
        if self._correspondence is None:
            return "no_correspondence"
        status = self._correspondence.get(notion_id)
        if status == "not_found":
            return "bo_not_found"
        if status == "found_partial":
            return "bo_partial"
        if status == "found_exact":
            return "bo_found"
        return "no_correspondence"

    def plan(self) -> dict[str, Any]:
        notions = []
        for theme in self.spec.themes:
            for notion in theme.notions:
                priority = self._priority_for(notion.id)
                notions.append({
                    "notion_id": notion.id,
                    "label": notion.label or notion.id,
                    "theme": theme.id,
                    "priority": priority,
                })

        # Sort by priority: bo_not_found first, then bo_partial, then no_correspondence, then bo_found
        notions.sort(key=lambda n: _PRIORITY_ORDER.get(n["priority"], 99))

        has_correspondence = self._correspondence is not None
        return {
            "matiere": self.spec.matiere,
            "niveau": self.spec.niveau.value,
            "statut": self.spec.statut_enseignement.value,
            "has_bo_correspondence": has_correspondence,
            "notions_count": len(notions),
            "notions": notions,
        }

    def fetch(self, max_notions: int | None = None) -> dict[str, Any]:
        if not self.check_staging_allowed():
            return {"error": "data_staging_allowed is false", "results": []}

        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._results = []

        # Use prioritized plan order
        plan = self.plan()
        notions_ordered = plan["notions"]
        count = 0

        for notion_entry in notions_ordered:
            if max_notions is not None and count >= max_notions:
                break
            notion_id = notion_entry["notion_id"]
            label = notion_entry["label"]
            priority = notion_entry["priority"]

            entries = fetch_notion(
                notion_id=notion_id,
                label=label,
                matiere=self.spec.matiere,
                niveau=self.spec.niveau.value,
                voie=self.spec.voie.value,
                statut=self.spec.statut_enseignement.value,
            )
            for entry in entries:
                entry["priority"] = priority
            self._results.extend(entries)

            accepted = [entry for entry in entries if entry.get("status") in ACCEPTED_STATUSES]
            if accepted:
                _cleanup_previous_notion_files(self.staging_dir, self.spec.matiere, notion_id)
                fname = f"{self.spec.matiere}_{notion_id}.json"
                (self.staging_dir / fname).write_text(
                    json.dumps(accepted[0], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            count += 1

        found = len({
            e.get("notion_id")
            for e in self._results
            if e.get("status") in ACCEPTED_STATUSES
        })
        not_found = len({
            e.get("notion_id")
            for e in self._results
            if e.get("status") == "not_found"
        })

        return {
            "matiere": self.spec.matiere,
            "niveau": self.spec.niveau.value,
            "has_bo_correspondence": plan["has_bo_correspondence"],
            "notions_processed": count,
            "found": found,
            "not_found": not_found,
        }

    def report(self) -> dict[str, Any]:
        found = [e for e in self._results if e.get("status") in ("ok", "quality_issues")]
        not_found = [e for e in self._results if e.get("status") == "not_found"]
        found_by_notion = {e.get("notion_id"): e for e in found}
        not_found_by_notion = {e.get("notion_id"): e for e in not_found}
        return {
            "matiere": self.spec.matiere,
            "niveau": self.spec.niveau.value,
            "has_bo_correspondence": self._correspondence is not None,
            "found_count": len(found_by_notion),
            "not_found_count": len(not_found_by_notion),
            "found_notions": [
                {
                    "notion_id": e.get("notion_id"),
                    "priority": e.get("priority"),
                    "chosen_url": e.get("chosen_url"),
                    "source_label": e.get("source_label"),
                    "candidate_urls": e.get("candidate_urls", []),
                    "ignored_candidate_urls": e.get("ignored_candidate_urls", []),
                    "selection_reason": e.get("selection_reason"),
                    "fallback_used": e.get("fallback_used", False),
                }
                for e in found_by_notion.values()
            ],
            "not_found_notions": [
                {"notion_id": e.get("notion_id"), "priority": e.get("priority")}
                for e in not_found_by_notion.values()
            ],
        }
