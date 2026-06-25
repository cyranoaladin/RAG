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
from scrapers.subpage_extractor import extract_subpage_links

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
     "url": "https://fr.wikipedia.org/wiki/Récursivité_(informatique)",
     "rights": "CC-BY-SA 4.0", "source": "wikipedia"},
    {"notion_id": "arbres", "matiere": "nsi",
     "url": "https://fr.wikipedia.org/wiki/Arbre_(structure_de_données)",
     "rights": "CC-BY-SA 4.0", "source": "wikipedia"},
    {"notion_id": "graphes", "matiere": "nsi",
     "url": "https://fr.wikipedia.org/wiki/Théorie_des_graphes",
     "rights": "CC-BY-SA 4.0", "source": "wikipedia"},
    {"notion_id": "sql", "matiere": "nsi",
     "url": "https://fr.wikiversity.org/wiki/Structured_Query_Language"},
]


def _check_staging_allowed() -> bool:
    """Check data_staging_allowed verrou."""
    if not CONTRACT_PATH.is_file():
        return False
    config = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return config.get("data_staging_allowed") is True


def _fetch_page(page: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch a page and its sub-pages. Returns a list of entries."""
    notion_id = page["notion_id"]
    url = page["url"]
    rights = page.get("rights", "CC-BY-SA 4.0")
    source = page.get("source", "wikiversity")

    result = governed_fetch(url)

    if isinstance(result, FetchRefusal):
        return [{"notion_id": notion_id, "matiere": page["matiere"],
                 "status": "refused", "reason": result.reason, "url": url}]

    if result.error:
        return [{"notion_id": notion_id, "matiere": page["matiere"],
                 "status": "error", "error": result.error, "url": url}]

    if result.status_code != 200:
        return [{"notion_id": notion_id, "matiere": page["matiere"],
                 "status": "http_error", "status_code": result.status_code, "url": url}]

    text = extract_text_from_html(result.text)
    qc = quality_check(text, notion_id)

    entries: list[dict[str, Any]] = []
    index_entry = {
        "notion_id": notion_id,
        "matiere": page["matiere"],
        "url": url,
        "source_label": f"{source}_{notion_id}",
        "rights": rights,
        "audience": "tous",
        "status": "ok" if qc["ok"] else "quality_issues",
        "text_length": len(text),
        "text_preview": text[:500],
        "quality": qc,
        "page_type": "index" if qc.get("navigation_suspected") else "content",
    }
    entries.append(index_entry)

    # For Wikiversity index pages, extract and fetch sub-pages
    if source == "wikiversity" and qc.get("navigation_suspected"):
        subpage_urls = extract_subpage_links(result.text, url)
        for i, sub_url in enumerate(subpage_urls[:5]):  # limit to 5 sub-pages
            sub_result = governed_fetch(sub_url)
            if isinstance(sub_result, FetchRefusal) or sub_result.error:
                continue
            if sub_result.status_code != 200:
                continue
            sub_text = extract_text_from_html(sub_result.text)
            sub_qc = quality_check(sub_text, notion_id)
            entries.append({
                "notion_id": notion_id,
                "matiere": page["matiere"],
                "url": sub_url,
                "source_label": f"{source}_{notion_id}_ch{i + 1}",
                "rights": rights,
                "audience": "tous",
                "status": "ok" if sub_qc["ok"] else "quality_issues",
                "text_length": len(sub_text),
                "text_preview": sub_text[:500],
                "quality": sub_qc,
                "page_type": "subpage",
            })

    return entries


def run_pilot_fetch() -> dict[str, Any]:
    """Execute the pilot fetch and deposit results in staging."""
    if not _check_staging_allowed():
        return {"error": "data_staging_allowed is false — staging refused", "results": []}

    STAGING_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for page in WIKIVERSITY_PAGES:
        notion_id = page["notion_id"]
        print(f"Fetching {notion_id} ({page['matiere']})...")

        entries = _fetch_page(page)
        results.extend(entries)

        # Deposit in staging
        for entry in entries:
            if entry.get("status") in ("ok", "quality_issues"):
                label = entry.get("source_label", notion_id)
                staging_file = STAGING_DIR / f"{page['matiere']}_{label}.json"
                staging_file.write_text(
                    json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                nav = "NAV" if entry.get("quality", {}).get("navigation_suspected") else "OK"
                print(f"  {nav}: {entry.get('text_length', 0)} chars → {staging_file.name}")
            else:
                print(f"  {entry.get('status', 'unknown')}: {entry.get('reason', entry.get('error', ''))}")

    return {
        "pilot_fetch": True,
        "sources": ["wikiversity", "wikipedia"],
        "licenses": ["CC-BY-SA 4.0"],
        "page_count": len(WIKIVERSITY_PAGES),
        "entry_count": len(results),
        "results": results,
        "staging_dir": str(STAGING_DIR.relative_to(ROOT)),
    }


if __name__ == "__main__":
    report = run_pilot_fetch()
    print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
