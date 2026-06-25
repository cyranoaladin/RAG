"""Pilot fetch — governed acquisition from libre sources.

Fetches from whitelisted+licensed sources, deposits in staging.
Respects data_staging_allowed verrou. Does NOT import to corpus.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from scrapers.fetch import (
    FetchRefusal,
    extract_text_from_html,
    governed_fetch,
    quality_check,
)

ROOT = Path(__file__).resolve().parents[1]
STAGING_DIR = ROOT / "data" / "staging" / "lot5"
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"

# Wikiversity direct page URLs per notion (robots-allowed /wiki/ paths)
WIKIVERSITY_PAGES: list[dict[str, str]] = [
    {"notion_id": "suites", "matiere": "mathematiques",
     "url": "https://fr.wikiversity.org/wiki/Suites_et_récurrence"},
    {"notion_id": "fonction_exponentielle", "matiere": "mathematiques",
     "url": "https://fr.wikiversity.org/wiki/Fonction_exponentielle"},
    {"notion_id": "derivation", "matiere": "mathematiques",
     "url": "https://fr.wikiversity.org/wiki/Fonction_dérivée"},
    {"notion_id": "probabilites_conditionnelles", "matiere": "mathematiques",
     "url": "https://fr.wikiversity.org/wiki/Probabilités_conditionnelles"},
    {"notion_id": "primitives", "matiere": "mathematiques",
     "url": "https://fr.wikiversity.org/wiki/Intégration_(mathématiques)"},
    {"notion_id": "recursivite", "matiere": "nsi",
     "url": "https://fr.wikiversity.org/wiki/Récursivité"},
    {"notion_id": "arbres", "matiere": "nsi",
     "url": "https://fr.wikiversity.org/wiki/Arbres_(informatique)"},
    {"notion_id": "sql", "matiere": "nsi",
     "url": "https://fr.wikiversity.org/wiki/Structured_Query_Language"},
]


def _check_staging_allowed() -> bool:
    """Check data_staging_allowed verrou."""
    if not CONTRACT_PATH.is_file():
        return False
    config = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return config.get("data_staging_allowed") is True


def _fetch_page(page: dict[str, str]) -> dict[str, Any]:
    """Fetch a Wikiversity page and extract text."""
    notion_id = page["notion_id"]
    url = page["url"]

    result = governed_fetch(url)

    if isinstance(result, FetchRefusal):
        return {"notion_id": notion_id, "matiere": page["matiere"],
                "status": "refused", "reason": result.reason, "url": url}

    if result.error:
        return {"notion_id": notion_id, "matiere": page["matiere"],
                "status": "error", "error": result.error, "url": url}

    if result.status_code != 200:
        return {"notion_id": notion_id, "matiere": page["matiere"],
                "status": "http_error", "status_code": result.status_code, "url": url}

    text = extract_text_from_html(result.text)
    qc = quality_check(text, notion_id)

    return {
        "notion_id": notion_id,
        "matiere": page["matiere"],
        "url": url,
        "source_label": f"wikiversity_{notion_id}",
        "rights": "CC-BY-SA 4.0",
        "audience": "tous",
        "status": "ok" if qc["ok"] else "quality_issues",
        "text_length": len(text),
        "text_preview": text[:500],
        "quality": qc,
        "delay_applied": result.delay_applied,
    }


def run_pilot_fetch() -> dict[str, Any]:
    """Execute the pilot fetch and deposit results in staging."""
    if not _check_staging_allowed():
        return {"error": "data_staging_allowed is false — staging refused", "results": []}

    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for page in WIKIVERSITY_PAGES:
        notion_id = page["notion_id"]
        print(f"Fetching {notion_id} ({page['matiere']})...")

        entry = _fetch_page(page)
        results.append(entry)

        # Deposit in staging if content was retrieved
        if entry.get("status") in ("ok", "quality_issues"):
            staging_file = STAGING_DIR / f"{page['matiere']}_{notion_id}.json"
            staging_file.write_text(
                json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  OK: {entry.get('text_length', 0)} chars → {staging_file.name}")
        else:
            print(f"  {entry.get('status', 'unknown')}: {entry.get('reason', entry.get('error', ''))}")

    return {
        "pilot_fetch": True,
        "source": "wikiversity",
        "license": "CC-BY-SA 4.0",
        "query_count": len(WIKIVERSITY_PAGES),
        "results": results,
        "staging_dir": str(STAGING_DIR.relative_to(ROOT)),
    }


if __name__ == "__main__":
    report = run_pilot_fetch()
    print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
