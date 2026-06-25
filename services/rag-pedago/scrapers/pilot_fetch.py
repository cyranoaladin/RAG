"""Pilot fetch — taxonomy-driven acquisition from libre sources.

Loads taxonomy YAML files and fetches content for each notion.
Respects data_staging_allowed verrou. Does NOT import to corpus.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scrapers.taxonomy_fetcher import fetch_taxonomy

ROOT = Path(__file__).resolve().parents[1]
STAGING_DIR = ROOT / "data" / "staging" / "lot7"
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"

# Auto-discover taxonomy files (exclude common/exams metadata)
TAXONOMY_ROOT = ROOT / "taxonomy"
TAXONOMY_FILES = sorted(
    f for f in TAXONOMY_ROOT.rglob("*.yml")
    if f.parent.name not in ("common", "exams", "proposals")
)

# Limit per taxonomy to keep pilot manageable
MAX_NOTIONS_PER_TAXONOMY = 5


def _check_staging_allowed() -> bool:
    if not CONTRACT_PATH.is_file():
        return False
    config = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return config.get("data_staging_allowed") is True


def run_pilot_fetch() -> dict[str, Any]:
    """Execute taxonomy-driven pilot fetch."""
    if not _check_staging_allowed():
        return {"error": "data_staging_allowed is false — staging refused", "results": []}

    all_results: list[dict[str, Any]] = []

    for taxonomy_path in TAXONOMY_FILES:
        if not taxonomy_path.is_file():
            print(f"SKIP: {taxonomy_path} not found")
            continue

        print(f"\n=== {taxonomy_path.name} ===")
        staging = STAGING_DIR / taxonomy_path.stem
        report = fetch_taxonomy(
            taxonomy_path=taxonomy_path,
            staging_dir=staging,
            max_notions=MAX_NOTIONS_PER_TAXONOMY,
        )
        all_results.append(report)

    return {
        "pilot_fetch": True,
        "mode": "taxonomy_driven",
        "taxonomies": len(TAXONOMY_FILES),
        "max_notions_per_taxonomy": MAX_NOTIONS_PER_TAXONOMY,
        "results": all_results,
    }


if __name__ == "__main__":
    report = run_pilot_fetch()
    print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
