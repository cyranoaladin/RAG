"""Taxonomy-driven acquisition agent.

Loads a TaxonomySpec YAML and fetches content for each notion from
whitelisted libre sources (Wikipedia FR, Wikiversité FR).
Deposits in staging with full labeling. Checks data_staging_allowed.
"""
from __future__ import annotations

import json
import unicodedata
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

# Notion→article table (robots blocks search API)
ARTICLES_TABLE_PATH = ROOT / "data" / "sources" / "notion_articles.yml"
_articles_cache: dict[tuple[str, str], list[dict[str, str]]] | None = None
ACCEPTED_STATUSES = {"ok", "quality_issues"}


def _load_articles_table() -> dict[tuple[str, str], list[dict[str, str]]]:
    """Load the notion→article mapping table."""
    global _articles_cache  # noqa: PLW0603
    if _articles_cache is not None:
        return _articles_cache
    _articles_cache = {}
    if ARTICLES_TABLE_PATH.is_file():
        data = yaml.safe_load(ARTICLES_TABLE_PATH.read_text(encoding="utf-8"))
        for entry in data.get("articles", []):
            key = (entry["notion_id"], entry["matiere"])
            _articles_cache[key] = entry.get("articles", [])
    return _articles_cache


def _check_staging_allowed() -> bool:
    if not CONTRACT_PATH.is_file():
        return False
    config = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return config.get("data_staging_allowed") is True


def _dedupe(items: list[str]) -> list[str]:
    """Return items in order, dropping exact duplicates."""
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _capitalize_title(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


def _title_variants(raw_title: str) -> list[str]:
    title = " ".join(raw_title.replace("_", " ").split())
    if not title:
        return []

    capitalized = _capitalize_title(title)
    accentless = _strip_accents(capitalized)
    variants = [
        capitalized,
        capitalized.replace(" ", "_"),
        accentless,
        accentless.replace(" ", "_"),
    ]
    return _dedupe(variants)


def _nsi_structure_titles(notion_id: str, label: str | None) -> list[str]:
    """Known NSI structure titles restored for fragile title fallback."""
    key_candidates = {
        notion_id,
        notion_id.replace("_", " "),
        _strip_accents((label or "").lower()).replace("_", " ").strip(),
    }
    mapping = {
        "listes": ["Liste_(informatique)"],
        "liste": ["Liste_(informatique)"],
        "piles": ["Pile_(informatique)"],
        "pile": ["Pile_(informatique)"],
        "files": ["File_(structure_de_données)"],
        "file": ["File_(structure_de_données)"],
        "arbres": ["Arbre_(structure_de_données)"],
        "arbre": ["Arbre_(structure_de_données)"],
        "dictionnaires": ["Tableau_associatif", "Table_de_hachage"],
        "dictionnaire": ["Tableau_associatif", "Table_de_hachage"],
        "graphes": ["Théorie_des_graphes", "Graphe_(mathématiques_discrètes)"],
        "graphe": ["Théorie_des_graphes", "Graphe_(mathématiques_discrètes)"],
    }

    titles: list[str] = []
    for key in key_candidates:
        titles.extend(mapping.get(key, []))
    return _dedupe(titles)


def _fallback_article_urls(
    notion_id: str,
    matiere: str,
    label: str | None,
) -> list[tuple[str, str]]:
    """Build legacy title guesses, preferring the human label over notion_id."""
    title_inputs: list[str] = []
    if label:
        title_inputs.extend(_title_variants(label))
    title_inputs.extend(_title_variants(notion_id))
    base_titles = _dedupe(title_inputs)

    wikipedia_titles: list[str] = []
    wikipedia_titles.extend(base_titles)
    wikipedia_titles.extend(f"{title} ({matiere})" for title in base_titles)
    if matiere == "nsi":
        wikipedia_titles.extend(f"{title} (informatique)" for title in base_titles)
        wikipedia_titles.extend(_nsi_structure_titles(notion_id, label))

    urls: list[tuple[str, str]] = [
        (WIKIPEDIA_URL.format(title=quote(title)), "wikipedia")
        for title in _dedupe(wikipedia_titles)
    ]
    urls.extend(
        (WIKIVERSITY_URL.format(title=quote(title)), "wikiversity")
        for title in base_titles
    )
    return _dedupe_url_pairs(urls)


def _dedupe_url_pairs(urls: list[tuple[str, str]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, source_name in urls:
        if url not in seen:
            seen.add(url)
            result.append((url, source_name))
    return result


def _get_article_urls(
    notion_id: str,
    matiere: str,
    label: str | None = None,
) -> list[tuple[str, str]]:
    """Get verified article URLs from the notion→article table.

    Returns list of (url, source_name) tuples.
    Falls back to title guessing if no table entry exists.
    """
    table = _load_articles_table()
    key = (notion_id, matiere)
    urls: list[tuple[str, str]] = []

    if key in table:
        for article in table[key]:
            source = article.get("source", "wikipedia")
            title = article["title"]
            if source == "wikiversity":
                urls.append((WIKIVERSITY_URL.format(title=quote(title)), "wikiversity"))
            else:
                urls.append((WIKIPEDIA_URL.format(title=quote(title)), "wikipedia"))
        return _dedupe_url_pairs(urls)

    return _fallback_article_urls(notion_id, matiere, label)


def _quality_is_blocking(qc: dict[str, Any], source_name: str) -> bool:
    return source_name == "wikiversity" and qc.get("navigation_suspected") is True


def _entry(
    *,
    notion_id: str,
    label: str | None,
    matiere: str,
    niveau: str,
    voie: str,
    statut: str,
    url: str,
    source_name: str,
    source_label: str,
    text: str,
    qc: dict[str, Any],
    search_method: str,
    candidate_urls: list[str],
    selection_reason: str,
    page_type: str = "article",
) -> dict[str, Any]:
    return {
        "notion_id": notion_id,
        "notion_label": label or notion_id,
        "matiere": matiere,
        "niveau": niveau,
        "voie": voie,
        "statut_enseignement": statut,
        "url": url,
        "chosen_url": url,
        "source": source_name,
        "source_label": source_label,
        "rights": "CC-BY-SA 4.0",
        "audience": "tous",
        "status": "ok" if qc["ok"] else "quality_issues",
        "page_type": page_type,
        "text": text,
        "text_length": len(text),
        "text_preview": text[:500],
        "quality": qc,
        "search_method": search_method,
        "fallback_used": search_method == "title_guess",
        "candidate_urls": candidate_urls,
        "ignored_candidate_urls": [candidate for candidate in candidate_urls if candidate != url],
        "selection_reason": selection_reason,
    }


def _fetch_subpage_candidate(
    *,
    parent_html: str,
    parent_url: str,
    notion_id: str,
    label: str | None,
    matiere: str,
    niveau: str,
    voie: str,
    statut: str,
    search_method: str,
    candidate_urls: list[str],
) -> dict[str, Any] | None:
    for i, sub_url in enumerate(extract_subpage_links(parent_html, parent_url)[:3]):
        sub_r = governed_fetch(sub_url)
        if isinstance(sub_r, FetchRefusal) or sub_r.error or sub_r.status_code != 200:
            continue

        sub_text = extract_text_from_html(sub_r.text)
        if len(sub_text.strip()) < 100:
            continue

        sub_qc = quality_check(sub_text, notion_id)
        if _quality_is_blocking(sub_qc, "wikiversity"):
            continue

        return _entry(
            notion_id=notion_id,
            label=label,
            matiere=matiere,
            niveau=niveau,
            voie=voie,
            statut=statut,
            url=sub_url,
            source_name="wikiversity",
            source_label=f"wikiversity_{notion_id}_ch{i + 1}",
            text=sub_text,
            qc=sub_qc,
            search_method=search_method,
            candidate_urls=candidate_urls,
            selection_reason="wikiversity_navigation_subpage",
            page_type="subpage",
        )
    return None


def fetch_notion(
    notion_id: str,
    label: str | None,
    matiere: str,
    niveau: str,
    voie: str,
    statut: str,
) -> list[dict[str, Any]]:
    """Fetch content for a notion using the verified article table.

    Uses notion_articles.yml for verified titles (robots blocks search API).
    Falls back to title guessing if no table entry exists.
    Traces: search method, candidate URLs, chosen URL.
    """
    table = _load_articles_table()
    search_method = "article_table" if (notion_id, matiere) in table else "title_guess"
    article_urls = _get_article_urls(notion_id, matiere, label=label)
    candidate_urls = [u for u, _ in article_urls]

    for url, source_name in article_urls:
        result = governed_fetch(url)

        if isinstance(result, FetchRefusal):
            continue
        if result.error or result.status_code != 200:
            continue

        text = extract_text_from_html(result.text)
        if len(text) < 100:
            continue

        qc = quality_check(text, notion_id)

        if source_name == "wikiversity" and qc.get("navigation_suspected"):
            sub_entry = _fetch_subpage_candidate(
                parent_html=result.text,
                parent_url=url,
                notion_id=notion_id,
                label=label,
                matiere=matiere,
                niveau=niveau,
                voie=voie,
                statut=statut,
                search_method=search_method,
                candidate_urls=candidate_urls,
            )
            if sub_entry is not None:
                return [sub_entry]
            continue

        if _quality_is_blocking(qc, source_name):
            continue

        return [
            _entry(
                notion_id=notion_id,
                label=label,
                matiere=matiere,
                niveau=niveau,
                voie=voie,
                statut=statut,
                url=url,
                source_name=source_name,
                source_label=f"{source_name}_{notion_id}",
                text=text,
                qc=qc,
                search_method=search_method,
                candidate_urls=candidate_urls,
                selection_reason="first_acceptable_candidate",
            )
        ]

    return [
        {
            "notion_id": notion_id,
            "notion_label": label or notion_id,
            "matiere": matiere,
            "niveau": niveau,
            "status": "not_found",
            "search_method": search_method,
            "fallback_used": search_method == "title_guess",
            "candidate_urls": candidate_urls,
            "ignored_candidate_urls": candidate_urls,
        }
    ]


def _accepted_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("status") in ACCEPTED_STATUSES]


def _cleanup_previous_notion_files(staging_dir: Path, matiere: str, notion_id: str) -> None:
    filenames = [staging_dir / f"{matiere}_{notion_id}.json"]
    filenames.extend(staging_dir.glob(f"{matiere}_{notion_id}_wikipedia*.json"))
    filenames.extend(staging_dir.glob(f"{matiere}_{notion_id}_wikiversity*.json"))
    for path in filenames:
        if path.is_file():
            path.unlink()


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

            accepted = _accepted_entries(entries)
            if accepted:
                _cleanup_previous_notion_files(staging_dir, spec.matiere, notion.id)
                fname = f"{spec.matiere}_{notion.id}.json"
                (staging_dir / fname).write_text(
                    json.dumps(accepted[0], ensure_ascii=False, indent=2), encoding="utf-8"
                )

            notion_count += 1

    found = len({e.get("notion_id") for e in all_entries if e.get("status") in ACCEPTED_STATUSES})
    not_found = len({e.get("notion_id") for e in all_entries if e.get("status") == "not_found"})

    return {
        "taxonomy": str(taxonomy_path),
        "matiere": spec.matiere,
        "niveau": spec.niveau.value,
        "notions_total": notion_count,
        "found": found,
        "not_found": not_found,
        "entries": all_entries,
    }
