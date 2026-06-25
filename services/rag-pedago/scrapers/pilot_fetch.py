"""Pilot fetch — seed-list for 5 notions (3 maths + 2 NSI).

Fetches whitelisted URLs, extracts text, deposits in staging.
Does NOT import to corpus (ingestion_allowed=false).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scrapers.fetch import (
    FetchRefusal,
    extract_text_from_html,
    governed_fetch,
    quality_check,
)

ROOT = Path(__file__).resolve().parents[1]
STAGING_DIR = ROOT / "data" / "staging" / "pilot_4_2"

# Seed-list: 5 notions × official/CC URLs (whitelisted domains only)
SEED_LIST: list[dict[str, str]] = [
    {
        "notion_id": "suites",
        "matiere": "mathematiques",
        "url": "https://eduscol.education.gouv.fr/2068/programmes-et-ressources-en-mathematiques-voie-gt",
        "source_label": "eduscol_maths_gt_programmes",
    },
    {
        "notion_id": "derivation",
        "matiere": "mathematiques",
        "url": "https://eduscol.education.gouv.fr/1723/programmes-et-ressources-en-mathematiques-voie-g",
        "source_label": "eduscol_maths_g_programmes",
    },
    {
        "notion_id": "probabilites_conditionnelles",
        "matiere": "mathematiques",
        "url": "https://eduscol.education.gouv.fr/2068/programmes-et-ressources-en-mathematiques-voie-gt",
        "source_label": "eduscol_maths_gt_programmes",
    },
    {
        "notion_id": "recursivite",
        "matiere": "nsi",
        "url": "https://eduscol.education.gouv.fr/2068/programmes-et-ressources-en-nsi",
        "source_label": "eduscol_nsi_programmes",
    },
    {
        "notion_id": "arbres",
        "matiere": "nsi",
        "url": "https://eduscol.education.gouv.fr/2068/programmes-et-ressources-en-nsi",
        "source_label": "eduscol_nsi_programmes",
    },
]


def run_pilot_fetch() -> dict[str, Any]:
    """Execute the pilot fetch and deposit results in staging."""
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for seed in SEED_LIST:
        notion_id = seed["notion_id"]
        url = seed["url"]
        print(f"Fetching {notion_id} from {url}...")

        result = governed_fetch(url)

        entry: dict[str, Any]
        if isinstance(result, FetchRefusal):
            entry = {
                "notion_id": notion_id,
                "matiere": seed["matiere"],
                "url": url,
                "source_label": seed["source_label"],
                "status": "refused",
                "reason": result.reason,
                "fetched_at": datetime.now(UTC).isoformat(),
            }
            results.append(entry)
            print(f"  REFUSED: {result.reason}")
            continue

        if result.error:
            entry = {
                "notion_id": notion_id,
                "matiere": seed["matiere"],
                "url": url,
                "source_label": seed["source_label"],
                "status": "error",
                "error": result.error,
                "status_code": result.status_code,
                "fetched_at": result.fetched_at.isoformat(),
            }
            results.append(entry)
            print(f"  ERROR: {result.error}")
            continue

        # Extract text
        text = extract_text_from_html(result.text)
        qc = quality_check(text, notion_id)

        # Deposit in staging
        staging_file = STAGING_DIR / f"{seed['matiere']}_{notion_id}.json"
        staging_data = {
            "notion_id": notion_id,
            "matiere": seed["matiere"],
            "url": url,
            "source_label": seed["source_label"],
            "audience": "tous",
            "rights": "officiel_public",
            "status_code": result.status_code,
            "content_type": result.content_type,
            "text_length": len(text),
            "text_preview": text[:500],
            "quality": qc,
            "delay_applied": result.delay_applied,
            "fetched_at": result.fetched_at.isoformat(),
        }
        staging_file.write_text(
            json.dumps(staging_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        entry = {
            "notion_id": notion_id,
            "matiere": seed["matiere"],
            "url": url,
            "status": "ok" if qc["ok"] else "quality_issues",
            "text_length": len(text),
            "quality": qc,
            "staging_file": str(staging_file.relative_to(ROOT)),
            "delay_applied": result.delay_applied,
        }
        results.append(entry)
        print(f"  OK: {len(text)} chars, quality={'PASS' if qc['ok'] else 'ISSUES'}")

    return {
        "pilot_fetch": True,
        "seed_count": len(SEED_LIST),
        "results": results,
        "staging_dir": str(STAGING_DIR.relative_to(ROOT)),
    }


if __name__ == "__main__":
    import yaml
    report = run_pilot_fetch()
    print("\n" + yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
