from __future__ import annotations

from datetime import UTC, datetime

from schema.official_reference import OfficialSource
from schema.source import SourceManifestItem
from scrapers.discovery import build_discovery_plan, compute_coverage


def _taxonomy_payload(*, notion_ids: list[str]) -> str:
    blocks = [
        """
  - id: bloc-{}
    label: Bloc {}
    notions:
      - id: {}
        label: {}
""".strip("\n").format(index, index, notion_id, notion_id)
        for index, notion_id in enumerate(notion_ids, start=1)
    ]

    return """
id: test_taxonomy
matiere: mathematiques
niveau: terminale
voie: generale
statut_enseignement: specialite
programme_version: fixture
themes:
{}
competences:
  - raisonner
""".format("\n".join(blocks))


def _nsi_payload() -> str:
    return """
id: test_nsi
matiere: nsi
niveau: terminale
voie: generale
statut_enseignement: specialite
programme_version: fixture
themes:
  - id: programmation
    label: Programmation
    notions:
      - id: listes
        label: listes
competences:
  - raisonner
"""


def _write_yaml(path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _official_source(**updates: object) -> OfficialSource:
    payload = {
        "source_id": "math_programme_terminale",
        "title": "Programme de mathematiques en terminale",
        "url": "https://education.gouv.fr/programme-maths-terminale",
        "authority_level": "official_verified",
        "verification_status": "verified",
        "last_verified_at": "2026-06-14T00:00:00+00:00",
        "applies_to": ["mathematiques", "terminale_generale"],
    }
    payload.update(updates)
    return OfficialSource.model_validate(payload)


def test_strict_matching_requires_notion_token_in_source(tmp_path) -> None:
    """A generic programme source should NOT match all notions."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites", "convexite"]))

    # This source has "mathematiques" and "terminale" but NOT "suites" or "convexite"
    generic_source = _official_source(
        source_id="math_programme_terminale",
        title="Programme de mathematiques en terminale",
        applies_to=["mathematiques", "terminale_generale"],
    )

    plan = build_discovery_plan(
        taxonomy_paths=[maths],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override={"generic": generic_source},
    )

    notion_by_id = {n["notion_id"]: n for n in plan["notions"]}
    # Neither notion should match — no notion-specific token in generic source
    assert notion_by_id["suites"]["candidates"] == []
    assert notion_by_id["convexite"]["candidates"] == []


def test_notion_specific_source_matches(tmp_path) -> None:
    """A source mentioning the notion explicitly should match."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites", "convexite"]))

    # Source that mentions "suites" in its title
    suites_source = _official_source(
        source_id="math_suites_terminale",
        title="Suites et recurrence en terminale mathematiques",
        applies_to=["mathematiques", "terminale_generale"],
    )

    plan = build_discovery_plan(
        taxonomy_paths=[maths],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override={"suites": suites_source},
    )

    notion_by_id = {n["notion_id"]: n for n in plan["notions"]}
    assert len(notion_by_id["suites"]["candidates"]) == 1
    assert notion_by_id["convexite"]["candidates"] == []


def test_no_asymmetry_between_maths_and_nsi(tmp_path) -> None:
    """Both maths and nsi should use the same strict matching — no special curriculum fallback."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    nsi = tmp_path / "taxonomy" / "nsi.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites"]))
    _write_yaml(nsi, _nsi_payload())

    # Generic sources for both subjects (no notion-specific tokens)
    sources = {
        "math_generic": _official_source(
            source_id="math_programme_terminale",
            title="Programme de mathematiques en terminale",
            applies_to=["mathematiques", "terminale_generale"],
        ),
        "nsi_generic": _official_source(
            source_id="nsi_programme_terminale",
            title="Programme NSI en terminale",
            url="https://education.gouv.fr/nsi",
            applies_to=["nsi", "terminale_generale"],
        ),
    }

    plan = build_discovery_plan(
        taxonomy_paths=[maths, nsi],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override=sources,
    )

    notion_by_id = {n["notion_id"]: n for n in plan["notions"]}
    # Both should be uncovered — strict matching, no fallback
    assert notion_by_id["suites"]["candidates"] == []
    assert notion_by_id["listes"]["candidates"] == []


def test_coverage_with_strict_matching_shows_uncovered(tmp_path) -> None:
    """Coverage should honestly show uncovered notions."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    nsi = tmp_path / "taxonomy" / "nsi.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites", "limites"]))
    _write_yaml(nsi, _nsi_payload())

    plan = build_discovery_plan(
        taxonomy_paths=[maths, nsi],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override={
            "math_generic": _official_source(),  # generic — won't match any notion
        },
    )

    coverage = compute_coverage(plan)
    assert coverage["total_notions"] == 3
    assert coverage["covered_notions"] == 0  # strict: generic source covers nothing
    assert coverage["uncovered_notions"] == 3


def test_audience_derives_libre(tmp_path) -> None:
    """A candidat libre source should get audience=libre."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites"]))

    source = _official_source(
        source_id="candidat_libre_suites",
        title="Suites pour le candidat libre",
        applies_to=["mathematiques", "terminale_generale", "candidat_individuel"],
    )

    plan = build_discovery_plan(
        taxonomy_paths=[maths],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override={"libre": source},
    )

    notion_by_id = {n["notion_id"]: n for n in plan["notions"]}
    assert len(notion_by_id["suites"]["candidates"]) == 1
    assert notion_by_id["suites"]["candidates"][0]["audience"] == "libre"


def test_audience_derives_aefe(tmp_path) -> None:
    """An AEFE source should get audience=aefe."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites"]))

    source = _official_source(
        source_id="aefe_suites_terminale",
        title="Suites mathematiques AEFE terminale",
        applies_to=["mathematiques", "terminale_generale"],
    )

    plan = build_discovery_plan(
        taxonomy_paths=[maths],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override={"aefe": source},
    )

    notion_by_id = {n["notion_id"]: n for n in plan["notions"]}
    assert len(notion_by_id["suites"]["candidates"]) == 1
    assert notion_by_id["suites"]["candidates"][0]["audience"] == "aefe"


def test_audience_defaults_to_tous(tmp_path) -> None:
    """A standard disciplinary source should get audience=tous."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites"]))

    source = _official_source(
        source_id="math_suites_terminale",
        title="Suites en terminale mathematiques",
        applies_to=["mathematiques", "terminale_generale"],
    )

    plan = build_discovery_plan(
        taxonomy_paths=[maths],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override={"standard": source},
    )

    notion_by_id = {n["notion_id"]: n for n in plan["notions"]}
    assert notion_by_id["suites"]["candidates"][0]["audience"] == "tous"


def test_source_manifest_is_valid(tmp_path) -> None:
    """Produced source manifests must validate."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites"]))

    source = _official_source(
        source_id="math_suites_terminale",
        title="Suites en terminale mathematiques",
    )

    plan = build_discovery_plan(
        taxonomy_paths=[maths],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override={"s": source},
    )

    for notion in plan["notions"]:
        for candidate in notion["candidates"]:
            manifest = SourceManifestItem.model_validate(candidate["source_manifest"])
            assert manifest.source_name == candidate["source_label"]


def test_stopwords_excluded_from_matching(tmp_path) -> None:
    """Notion 'formule_des_probabilites_totales' must NOT match a generic source
    just because of the stopword 'des'."""
    maths = tmp_path / "taxonomy" / "maths.yml"
    _write_yaml(maths, _taxonomy_payload(notion_ids=["formule_des_probabilites_totales"]))

    # Source with "des" in title but not "formule"/"probabilites"/"totales"
    generic = _official_source(
        source_id="education_maths_reforme_lycee",
        title="Reforme des programmes mathematiques lycee",
        applies_to=["mathematiques", "terminale_generale"],
    )

    plan = build_discovery_plan(
        taxonomy_paths=[maths],
        discovered_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
        sources_override={"generic": generic},
    )

    notion_by_id = {n["notion_id"]: n for n in plan["notions"]}
    assert notion_by_id["formule_des_probabilites_totales"]["candidates"] == []
