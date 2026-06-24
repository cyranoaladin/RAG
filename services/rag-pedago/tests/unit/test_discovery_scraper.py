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


def test_discovery_plan_matches_local_sources_without_network(tmp_path) -> None:
    maths = tmp_path / "taxonomy" / "maths.yml"
    nsi = tmp_path / "taxonomy" / "nsi.yml"

    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites", "limites"]))
    _write_yaml(nsi, _nsi_payload())

    sources = {
        "math_programme_terminale": _official_source(),
        "nsi_portail": _official_source(
            source_id="nsi_portail",
            title="Ressources NSI",
            url="https://eduscol.education.gouv.fr/nsi",
            authority_level="official_verified",
            applies_to=["nsi", "terminale_generale"],
        ),
    }

    plan = build_discovery_plan(
        taxonomy_paths=[maths, nsi],
        discovered_at=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
        sources_override=sources,
    )

    notion_by_id = {notion["notion_id"]: notion for notion in plan["notions"]}

    assert notion_by_id["suites"]["candidates"]
    assert notion_by_id["listes"]["candidates"] == []

    for notion in plan["notions"]:
        for candidate in notion["candidates"]:
            manifest = SourceManifestItem.model_validate(candidate["source_manifest"])
            assert manifest.source_name == candidate["source_label"]
            assert manifest.source_uri == candidate["source_uri"]


def test_coverage_counts_identify_uncovered_notions(tmp_path) -> None:
    maths = tmp_path / "taxonomy" / "maths.yml"
    nsi = tmp_path / "taxonomy" / "nsi.yml"

    _write_yaml(maths, _taxonomy_payload(notion_ids=["suites", "limites"]))
    _write_yaml(nsi, _nsi_payload())

    plan = build_discovery_plan(
        taxonomy_paths=[maths, nsi],
        discovered_at=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
        sources_override={
            "math_programme_terminale": _official_source(),
        },
    )

    coverage = compute_coverage(plan)

    assert coverage == {
        "total_notions": 3,
        "covered_notions": 2,
        "uncovered_notions": 1,
        "by_matiere": {
            "mathematiques": {
                "total": 2,
                "covered": 2,
                "uncovered": [],
            },
            "nsi": {
                "total": 1,
                "covered": 0,
                "uncovered": ["listes"],
            },
        },
    }
