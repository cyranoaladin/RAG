"""Regression tests for taxonomy-driven source selection."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from textwrap import dedent
from urllib.parse import quote

import yaml

from agents.subject_agent import SubjectAgent
from scrapers import taxonomy_fetcher
from scrapers.fetch import FetchRefusal, FetchResult


def _html(text: str) -> str:
    return f"<html><body><main><p>{text}</p></main></body></html>"


def _french_text(topic: str) -> str:
    return (
        f"Le cours de {topic} est une ressource de reference pour les eleves. "
        "La notion est presentee avec des definitions, des exemples, des methodes "
        "et des exercices. Les proprietes de la notion sont expliquees de maniere "
        "progressive pour un usage pedagogique en classe et en autonomie. "
    ) * 4


def _fetch_result(url: str, text: str) -> FetchResult:
    return FetchResult(
        url=url,
        status_code=200,
        content_type="text/html",
        text=_html(text),
        fetched_at=datetime.now(UTC),
    )


def test_fetch_notion_keeps_only_first_successful_article(monkeypatch) -> None:
    first_url = taxonomy_fetcher.WIKIPEDIA_URL.format(title=quote("Suite_(mathématiques)"))
    second_url = taxonomy_fetcher.WIKIVERSITY_URL.format(title=quote("Suites_et_récurrence"))
    calls: list[str] = []

    monkeypatch.setattr(
        taxonomy_fetcher,
        "_articles_cache",
        {
            ("suites", "mathematiques"): [
                {"source": "wikipedia", "title": "Suite_(mathématiques)"},
                {"source": "wikiversity", "title": "Suites_et_récurrence"},
            ],
        },
    )

    def fake_fetch(url: str) -> FetchResult:
        calls.append(url)
        return _fetch_result(url, _french_text("suites numeriques"))

    monkeypatch.setattr(taxonomy_fetcher, "governed_fetch", fake_fetch)

    entries = taxonomy_fetcher.fetch_notion(
        notion_id="suites",
        label="Suites",
        matiere="mathematiques",
        niveau="terminale",
        voie="generale",
        statut="specialite",
    )

    assert len(entries) == 1
    assert entries[0]["chosen_url"] == first_url
    assert calls == [first_url]
    assert second_url in entries[0]["candidate_urls"]
    assert second_url in entries[0]["ignored_candidate_urls"]


def test_fetch_notion_selects_one_wikiversity_subpage_with_real_url(monkeypatch) -> None:
    parent_url = taxonomy_fetcher.WIKIVERSITY_URL.format(title=quote("Suites_et_récurrence"))
    sub_url = f"{parent_url}/Chapitre_1"
    calls: list[str] = []

    monkeypatch.setattr(
        taxonomy_fetcher,
        "_articles_cache",
        {
            ("suites", "mathematiques"): [
                {"source": "wikiversity", "title": "Suites_et_récurrence"},
            ],
        },
    )
    monkeypatch.setattr(taxonomy_fetcher, "extract_subpage_links", lambda html, base: [sub_url])

    parent_text = (
        "Aller au contenu Menu principal Chapitres : Outils personnels Rechercher. "
        "Les suites sont listees dans cette page de navigation avec des liens. "
    ) * 4

    def fake_fetch(url: str) -> FetchResult:
        calls.append(url)
        if url == parent_url:
            return _fetch_result(url, parent_text)
        return _fetch_result(url, _french_text("suites numeriques"))

    monkeypatch.setattr(taxonomy_fetcher, "governed_fetch", fake_fetch)

    entries = taxonomy_fetcher.fetch_notion(
        notion_id="suites",
        label="Suites",
        matiere="mathematiques",
        niveau="terminale",
        voie="generale",
        statut="specialite",
    )

    assert len(entries) == 1
    assert entries[0]["url"] == sub_url
    assert entries[0]["chosen_url"] == sub_url
    assert entries[0]["source_label"] == "wikiversity_suites_ch1"
    assert entries[0]["page_type"] == "subpage"
    assert entries[0]["candidate_urls"] == [parent_url]
    assert entries[0]["ignored_candidate_urls"] == [parent_url]
    assert calls == [parent_url, sub_url]


def test_fallback_uses_label_before_notion_id(monkeypatch) -> None:
    calls: list[str] = []
    expected = taxonomy_fetcher.WIKIPEDIA_URL.format(title=quote("Suites numériques"))

    monkeypatch.setattr(taxonomy_fetcher, "_articles_cache", {})

    def fake_fetch(url: str) -> FetchRefusal:
        calls.append(url)
        return FetchRefusal(url=url, reason="stop after candidate recording")

    monkeypatch.setattr(taxonomy_fetcher, "governed_fetch", fake_fetch)

    taxonomy_fetcher.fetch_notion(
        notion_id="suite_numeric_fragile",
        label="Suites numériques",
        matiere="mathematiques",
        niveau="terminale",
        voie="generale",
        statut="specialite",
    )

    assert calls[0] == expected


def test_fallback_keeps_qualified_wikipedia_and_wikiversity_variants(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(taxonomy_fetcher, "_articles_cache", {})

    def fake_fetch(url: str) -> FetchRefusal:
        calls.append(url)
        return FetchRefusal(url=url, reason="stop after candidate recording")

    monkeypatch.setattr(taxonomy_fetcher, "governed_fetch", fake_fetch)

    taxonomy_fetcher.fetch_notion(
        notion_id="arbres_fragiles",
        label="Arbres",
        matiere="nsi",
        niveau="terminale",
        voie="generale",
        statut="specialite",
    )

    assert any("Arbres%20%28informatique%29" in url for url in calls)
    assert any("Arbre_%28structure_de_donn%C3%A9es%29" in url for url in calls)
    assert any(url.startswith(taxonomy_fetcher.WIKIVERSITY_URL.split("{title}")[0]) for url in calls)


def test_subject_agent_writes_only_canonical_notion_file(tmp_path, monkeypatch) -> None:
    taxonomy = tmp_path / "taxo.yml"
    taxonomy.write_text(
        dedent("""\
            id: test_math
            matiere: mathematiques
            niveau: terminale
            voie: generale
            statut_enseignement: specialite
            programme_version: test
            themes:
              - id: suites
                label: Suites
                notions:
                  - id: suites
                    label: Suites
            competences:
              - raisonner
        """),
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    stale = staging / "mathematiques_suites_wikiversity_suites.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")

    chosen_url = taxonomy_fetcher.WIKIPEDIA_URL.format(title=quote("Suite_(mathématiques)"))

    monkeypatch.setattr("agents.base.AcquisitionAgent.check_staging_allowed", lambda self: True)
    monkeypatch.setattr(
        "agents.subject_agent.fetch_notion",
        lambda **kwargs: [
            {
                "notion_id": "suites",
                "notion_label": "Suites",
                "matiere": "mathematiques",
                "niveau": "terminale",
                "voie": "generale",
                "statut_enseignement": "specialite",
                "url": chosen_url,
                "chosen_url": chosen_url,
                "source": "wikipedia",
                "source_label": "wikipedia_suites",
                "status": "ok",
                "candidate_urls": [chosen_url, "https://fr.wikiversity.org/wiki/Suites_et_récurrence"],
                "ignored_candidate_urls": ["https://fr.wikiversity.org/wiki/Suites_et_récurrence"],
            }
        ],
    )

    agent = SubjectAgent(taxonomy, staging)
    result = agent.fetch()

    canonical = staging / "mathematiques_suites.json"
    files = sorted(path.name for path in staging.glob("mathematiques_suites*.json"))
    written = json.loads(canonical.read_text(encoding="utf-8"))

    assert result["found"] == 1
    assert files == ["mathematiques_suites.json"]
    assert written["chosen_url"] == chosen_url
    assert written["source_label"] == "wikipedia_suites"
    assert written["ignored_candidate_urls"] == ["https://fr.wikiversity.org/wiki/Suites_et_récurrence"]


def test_notion_articles_contains_required_lot_11_entries() -> None:
    data = yaml.safe_load(taxonomy_fetcher.ARTICLES_TABLE_PATH.read_text(encoding="utf-8"))
    keys = {(entry["notion_id"], entry["matiere"]) for entry in data["articles"]}

    assert ("algorithmique_suites", "mathematiques") in keys
    assert ("dictionnaires", "nsi") in keys
