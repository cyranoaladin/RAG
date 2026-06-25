"""Taxonomy-driven acquisition agent.

Loads a TaxonomySpec YAML and fetches content for each notion from
whitelisted libre sources (Wikipedia FR, Wikiversité FR).
Deposits in staging with full labeling. Checks data_staging_allowed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from schema.taxonomy import TaxonomySpec
from scrapers.fetch import (
    FetchRefusal,
    extract_text_from_html,
    governed_fetch,
    quality_check,
)
from scrapers.subpage_extractor import extract_subpage_links

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"

# URL templates for libre sources
WIKIPEDIA_URL = "https://fr.wikipedia.org/wiki/{title}"
WIKIVERSITY_URL = "https://fr.wikiversity.org/wiki/{title}"


def _check_staging_allowed() -> bool:
    if not CONTRACT_PATH.is_file():
        return False
    config = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return config.get("data_staging_allowed") is True


def _notion_search_titles(notion_id: str, label: str | None, matiere: str) -> list[str]:
    """Generate candidate page titles for a notion."""
    titles = []
    # Use label if available, else notion_id with underscores→spaces
    name = (label or notion_id).replace("_", " ")
    # Capitalized version for Wikipedia
    cap = name[0].upper() + name[1:] if name else name
    titles.append(cap)
    # With matiere qualifier
    titles.append(f"{cap} ({matiere})")
    # With informatique for NSI
    if matiere == "nsi":
        titles.append(f"{cap} (informatique)")
    return titles


def fetch_notion(
    notion_id: str,
    label: str | None,
    matiere: str,
    niveau: str,
    voie: str,
    statut: str,
) -> list[dict[str, Any]]:
    """Try to fetch content for a notion from Wikipedia/Wikiversity."""
    entries: list[dict[str, Any]] = []
    titles = _notion_search_titles(notion_id, label, matiere)

    for title in titles:
        # Try Wikipedia first (richer content)
        url = WIKIPEDIA_URL.format(title=quote(title))
        result = governed_fetch(url)

        if isinstance(result, FetchRefusal):
            continue
        if result.error or result.status_code != 200:
            continue

        text = extract_text_from_html(result.text)
        if len(text) < 100:
            continue

        qc = quality_check(text, notion_id)
        entries.append({
            "notion_id": notion_id,
            "notion_label": label or notion_id,
            "matiere": matiere,
            "niveau": niveau,
            "voie": voie,
            "statut_enseignement": statut,
            "url": url,
            "source": "wikipedia",
            "source_label": f"wikipedia_{notion_id}",
            "rights": "CC-BY-SA 4.0",
            "audience": "tous",
            "status": "ok" if qc["ok"] else "quality_issues",
            "text_length": len(text),
            "text_preview": text[:500],
            "quality": qc,
        })
        break  # Found content, stop trying titles

    if not entries:
        # Try Wikiversity
        for title in titles:
            url = WIKIVERSITY_URL.format(title=quote(title))
            result = governed_fetch(url)

            if isinstance(result, FetchRefusal):
                continue
            if result.error or result.status_code != 200:
                continue

            text = extract_text_from_html(result.text)
            if len(text) < 100:
                continue

            qc = quality_check(text, notion_id)
            entry: dict[str, Any] = {
                "notion_id": notion_id,
                "notion_label": label or notion_id,
                "matiere": matiere,
                "niveau": niveau,
                "voie": voie,
                "statut_enseignement": statut,
                "url": url,
                "source": "wikiversity",
                "source_label": f"wikiversity_{notion_id}",
                "rights": "CC-BY-SA 4.0",
                "audience": "tous",
                "status": "ok" if qc["ok"] else "quality_issues",
                "text_length": len(text),
                "text_preview": text[:500],
                "quality": qc,
            }
            entries.append(entry)

            # If it's a nav page, try sub-pages
            if qc.get("navigation_suspected"):
                subpages = extract_subpage_links(result.text, url)
                for i, sub_url in enumerate(subpages[:3]):
                    sub_r = governed_fetch(sub_url)
                    if isinstance(sub_r, FetchRefusal) or sub_r.error or sub_r.status_code != 200:
                        continue
                    sub_text = extract_text_from_html(sub_r.text)
                    sub_qc = quality_check(sub_text, notion_id)
                    entries.append({
                        **entry,
                        "url": sub_url,
                        "source_label": f"wikiversity_{notion_id}_ch{i + 1}",
                        "text_length": len(sub_text),
                        "text_preview": sub_text[:500],
                        "quality": sub_qc,
                        "page_type": "subpage",
                    })
            break

    if not entries:
        entries.append({
            "notion_id": notion_id,
            "notion_label": label or notion_id,
            "matiere": matiere,
            "niveau": niveau,
            "status": "not_found",
        })

    return entries


def fetch_taxonomy(
    taxonomy_path: Path,
    staging_dir: Path,
    max_notions: int | None = None,
) -> dict[str, Any]:
    """Fetch content for all notions in a taxonomy."""
    if not _check_staging_allowed():
        return {"error": "data_staging_allowed is false", "results": []}

    data = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8"))
    spec = TaxonomySpec.model_validate(data)

    staging_dir.mkdir(parents=True, exist_ok=True)

    all_entries: list[dict[str, Any]] = []
    notion_count = 0

    for theme in spec.themes:
        for notion in theme.notions:
            if max_notions and notion_count >= max_notions:
                break

            print(f"  [{spec.matiere}/{spec.niveau.value}] {notion.id}...")
            entries = fetch_notion(
                notion_id=notion.id,
                label=notion.label,
                matiere=spec.matiere,
                niveau=spec.niveau.value,
                voie=spec.voie.value,
                statut=spec.statut_enseignement.value,
            )
            all_entries.extend(entries)

            # Deposit in staging
            for entry in entries:
                if entry.get("status") in ("ok", "quality_issues"):
                    fname = f"{spec.matiere}_{notion.id}.json"
                    (staging_dir / fname).write_text(
                        json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
                    )

            notion_count += 1

    found = sum(1 for e in all_entries if e.get("status") in ("ok", "quality_issues"))
    not_found = sum(1 for e in all_entries if e.get("status") == "not_found")

    return {
        "taxonomy": str(taxonomy_path),
        "matiere": spec.matiere,
        "niveau": spec.niveau.value,
        "notions_total": notion_count,
        "found": found,
        "not_found": not_found,
        "entries": all_entries,
    }
