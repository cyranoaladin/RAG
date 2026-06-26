"""Tests for multi-agent acquisition framework."""
from __future__ import annotations

from textwrap import dedent
from unittest.mock import patch

from agents.subject_agent import SubjectAgent


def _taxonomy_yaml(matiere: str = "mathematiques", niveau: str = "terminale") -> str:
    return dedent(f"""\
        id: test_{matiere}_{niveau}
        matiere: {matiere}
        niveau: {niveau}
        voie: generale
        statut_enseignement: specialite
        programme_version: BOEN_test
        themes:
          - id: theme1
            label: Theme 1
            notions:
              - id: notion_a
                label: Notion A
              - id: notion_b
                label: Notion B
              - id: notion_c
                label: Notion C
        competences:
          - raisonner
    """)


def test_subject_agent_plan(tmp_path) -> None:
    taxo = tmp_path / "taxo.yml"
    taxo.write_text(_taxonomy_yaml(), encoding="utf-8")
    agent = SubjectAgent(taxo, tmp_path / "staging")
    plan = agent.plan()
    assert plan["matiere"] == "mathematiques"
    assert plan["notions_count"] == 3
    assert plan["has_bo_correspondence"] is False


def test_subject_agent_refuses_when_staging_not_allowed(tmp_path, monkeypatch) -> None:
    taxo = tmp_path / "taxo.yml"
    taxo.write_text(_taxonomy_yaml(), encoding="utf-8")
    agent = SubjectAgent(taxo, tmp_path / "staging")

    fake_contract = tmp_path / "contract.yml"
    fake_contract.write_text("data_staging_allowed: false\n", encoding="utf-8")
    monkeypatch.setattr("agents.base.CONTRACT_PATH", fake_contract)

    result = agent.fetch()
    assert "error" in result
    assert "staging" in result["error"].lower()


def test_orchestrator_checks_ingestion_blocked(tmp_path, monkeypatch) -> None:
    from agents.orchestrator import OrchestratorAgent

    fake_contract = tmp_path / "contract.yml"
    fake_contract.write_text(
        "data_staging_allowed: true\ningestion_allowed: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("agents.base.CONTRACT_PATH", fake_contract)

    orch = OrchestratorAgent(niveaux=["terminale"], staging_root=tmp_path / "staging")
    result = orch.fetch()
    assert "error" in result
    assert "ingestion" in result["error"].lower()


def test_priorisation_orders_bo_not_found_first(tmp_path, monkeypatch) -> None:
    """Notions not_found in BO correspondence must come before found_exact."""
    taxo = tmp_path / "taxo.yml"
    taxo.write_text(_taxonomy_yaml(), encoding="utf-8")

    # Mock correspondence: notion_a=found_exact, notion_b=not_found, notion_c=found_partial
    fake_correspondence = {
        "notion_a": "found_exact",
        "notion_b": "not_found",
        "notion_c": "found_partial",
    }
    with patch("agents.subject_agent._load_correspondence", return_value=fake_correspondence):
        agent = SubjectAgent(taxo, tmp_path / "staging")
        plan = agent.plan()

    assert plan["has_bo_correspondence"] is True
    notions = plan["notions"]
    # Order: notion_b (bo_not_found) → notion_c (bo_partial) → notion_a (bo_found)
    assert notions[0]["notion_id"] == "notion_b"
    assert notions[0]["priority"] == "bo_not_found"
    assert notions[1]["notion_id"] == "notion_c"
    assert notions[1]["priority"] == "bo_partial"
    assert notions[2]["notion_id"] == "notion_a"
    assert notions[2]["priority"] == "bo_found"


def test_no_correspondence_preserves_taxonomy_order(tmp_path) -> None:
    """Without BO correspondence, notions stay in taxonomy order with no_correspondence."""
    taxo = tmp_path / "taxo.yml"
    taxo.write_text(_taxonomy_yaml(), encoding="utf-8")
    agent = SubjectAgent(taxo, tmp_path / "staging")
    plan = agent.plan()

    assert plan["has_bo_correspondence"] is False
    notions = plan["notions"]
    # All should be no_correspondence, order preserved
    assert all(n["priority"] == "no_correspondence" for n in notions)
    assert [n["notion_id"] for n in notions] == ["notion_a", "notion_b", "notion_c"]


def test_subject_agent_metadata_only_no_pdf_opened(tmp_path, monkeypatch) -> None:
    """SubjectAgent must not open any PDF — it reads JSON artefacts only."""
    taxo = tmp_path / "taxo.yml"
    taxo.write_text(_taxonomy_yaml(), encoding="utf-8")

    # Create a fake correspondence JSON artefact
    corr_dir = tmp_path / "correspondance"
    corr_dir.mkdir()
    import json
    (corr_dir / "mathematiques_terminale.json").write_text(json.dumps({
        "extraction_status": "ok",
        "details_found_exact": [{"notion_id": "notion_a", "label": "A"}],
        "details_found_partial": [],
        "details_not_found": [{"notion_id": "notion_b", "label": "B"}],
    }), encoding="utf-8")

    # Patch the correspondance directory
    monkeypatch.setattr("agents.subject_agent.CORRESPONDANCE_DIR", corr_dir)

    # Monkeypatch pypdf to fail if accessed
    import builtins
    original_import = builtins.__import__

    def fail_pypdf(name, *args, **kwargs):  # noqa: ANN002, ANN003
        if name == "pypdf":
            raise AssertionError("SubjectAgent must not import pypdf")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_pypdf)

    agent = SubjectAgent(taxo, tmp_path / "staging")
    plan = agent.plan()

    # Agent loaded correspondence from JSON, not PDF
    assert plan["has_bo_correspondence"] is True
    assert plan["notions"][0]["priority"] == "bo_not_found"  # notion_b first
